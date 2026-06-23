"""
Offline prompt evolution loop for conversation extraction.
"""

from __future__ import annotations

import argparse
import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..extract import _normalize_extract_mode
from ..llm_backend import add_codex_llm_args
from .artifacts import (
    _default_prompt_text,
    _ensure_log_round_layout,
    _ensure_prompt_round_layout,
    _ensure_run_roots,
    _history_paths,
    _initialize_run,
    _json_dump,
    _load_history,
    _load_json,
    _log_round_artifact,
    _migrate_all_prompt_round_files,
    _norm_path,
    _prompt_round_artifact,
    _round_tag,
    _safe_read_text,
    _write_history_row,
)
from .eval import (
    _display_path,
    _normalize_manifest_log_paths,
    _print_detail,
    _print_header,
    _print_round_metrics,
    _proxy_env_control,
    _run_eval_dataset,
    _run_one_eval,
)
from .patch import (
    PATCH_CATEGORIES,
    _backfill_prompt_patch_artifacts,
    _build_prompt_diff,
    _compose_prompt_from_base_and_patch_set,
    _empty_patch_set,
    _merge_patch_set_with_budget,
    _normalize_legacy_overlay_prompt,
    _normalize_patch_set,
    _patch_has_prompt_visible_content,
    _write_prompt_patch_artifacts,
)
from .promotion import (
    _print_promote_decision,
    _promotion_cmp_key,
    _safety_gate,
)
from .reflection import (
    ReflectionPendingError,
    build_reason_cluster_summaries_from_bucket,
    build_error_delta,
    build_reflection_embeddings,
    build_reflection_input,
    build_reflection_llm,
    normalize_reflection_mode,
    normalize_patch_payload,
    run_reflection,
)


@dataclass
class LoopRunResult:
    stamp: str
    prompt_root: Path
    log_root: Path
    best_prompt_path: Path
    best_metrics_path: Path
    stop_signal: Optional[str] = None
    pending_round_index: Optional[int] = None
    pending_round_dir: Optional[Path] = None


def _mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return 0


def _normalize_prompt_file_legacy_overlay(path: Path) -> Dict[str, Any]:
    raw = _safe_read_text(path).rstrip("\n")
    normalized = _normalize_legacy_overlay_prompt(raw)
    if bool(normalized.get("had_legacy_overlay")):
        prompt_text = str(normalized.get("prompt_text") or "").rstrip("\n")
        if prompt_text and prompt_text != raw:
            path.write_text(prompt_text + "\n", encoding="utf-8")
    return normalized


def _parse_ratio_arg(raw: Any) -> float:
    text = str(raw or "").strip()
    if not text:
        raise argparse.ArgumentTypeError("ratio must not be empty")
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1].strip()
    try:
        value = float(text)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"invalid ratio value: {raw}") from exc
    if is_percent or value > 1.0:
        value = value / 100.0
    if value < 0.0 or value > 1.0:
        raise argparse.ArgumentTypeError("ratio must be between 0 and 1, or between 0 and 100%")
    return float(value)


def _should_build_reflection_analysis_llm(args: argparse.Namespace) -> bool:
    mode = normalize_reflection_mode(str(getattr(args, "reflection_mode", "llm") or "llm"))
    if mode == "llm":
        return True
    if mode == "codex":
        return True
    return False


def _parse_multiplier_arg(raw: Any) -> float:
    text = str(raw or "").strip()
    if not text:
        raise argparse.ArgumentTypeError("multiplier must not be empty")
    suffix = ""
    if text[-1:] in {"x", "X", "%"}:
        suffix = text[-1]
        text = text[:-1].strip()
    try:
        value = float(text)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"invalid multiplier value: {raw}") from exc
    if suffix == "%":
        value = value / 100.0
    if value <= 0.0:
        raise argparse.ArgumentTypeError("multiplier must be > 0")
    return float(value)


def _round_index_from_prompt_version(prompt_version: str) -> Optional[int]:
    text = str(prompt_version or "").strip()
    if not text.startswith("round_"):
        return None
    parts = text.split("_")
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except Exception:
        return None


def _eval_path_for_prompt_version(*, prompt_root: Path, log_root: Path, prompt_version: str) -> Path:
    round_index = _round_index_from_prompt_version(prompt_version)
    if round_index is None:
        return Path("")
    round_dir_name = _round_tag(round_index)
    log_path = _log_round_artifact(log_root / round_dir_name, "eval.json")
    if log_path.is_file():
        return log_path
    prompt_path = _log_round_artifact(prompt_root / round_dir_name, "eval.json")
    if prompt_path.is_file():
        return prompt_path
    return log_path


def _load_eval_for_prompt_version(*, prompt_root: Path, log_root: Path, prompt_version: str) -> Dict[str, Any]:
    path = _eval_path_for_prompt_version(prompt_root=prompt_root, log_root=log_root, prompt_version=prompt_version)
    return _load_json(path) if path and path.is_file() else {}


def _history_row_for_prompt_version(history_rows: List[Dict[str, Any]], prompt_version: str) -> Dict[str, Any]:
    target = str(prompt_version or "").strip()
    if not target:
        return {}
    for row in reversed(history_rows):
        if str(row.get("prompt_version") or "").strip() == target:
            return dict(row)
    return {}


def _load_reference_eval_for_active(
    *,
    active_eval: Dict[str, Any],
    history_rows: List[Dict[str, Any]],
    prompt_root: Path,
    log_root: Path,
) -> Dict[str, Any]:
    active_version = str(active_eval.get("prompt_version") or "").strip()
    row = _history_row_for_prompt_version(history_rows, active_version)
    parent_version = str(row.get("parent_prompt_version") or "").strip()
    if not parent_version:
        return {}
    return _load_eval_for_prompt_version(prompt_root=prompt_root, log_root=log_root, prompt_version=parent_version)


def _build_recent_candidate_deltas(
    *,
    history_rows: List[Dict[str, Any]],
    prompt_root: Path,
    log_root: Path,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    deltas: List[Dict[str, Any]] = []
    for row in reversed(history_rows[-8:]):
        prompt_version = str(row.get("prompt_version") or "").strip()
        parent_version = str(row.get("parent_prompt_version") or "").strip()
        if not prompt_version or not parent_version:
            continue
        current_eval = _load_eval_for_prompt_version(prompt_root=prompt_root, log_root=log_root, prompt_version=prompt_version)
        reference_eval = _load_eval_for_prompt_version(prompt_root=prompt_root, log_root=log_root, prompt_version=parent_version)
        if not current_eval or not reference_eval:
            continue
        delta = build_error_delta(reference_eval=reference_eval, current_eval=current_eval, max_samples_per_bucket=4)
        delta["round"] = _safe_round_int(row.get("round"))
        delta["promoted"] = bool(row.get("promoted"))
        delta["promotion_reason"] = str(row.get("promotion_reason") or "")
        deltas.append(delta)
        if len(deltas) >= max(0, int(limit)):
            break
    return list(reversed(deltas))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _compact_text(text: Any, limit: int = 180) -> str:
    raw = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


def _contains_cjk(ch: str) -> bool:
    return "\u4e00" <= str(ch or "") <= "\u9fff"


def _dominant_language_code(text: str) -> str:
    raw = str(text or "")
    cjk_count = sum(1 for ch in raw if _contains_cjk(ch))
    alpha_count = sum(1 for ch in raw if str(ch).isalpha() and str(ch).isascii())
    if cjk_count <= 0 and alpha_count <= 0:
        return "mixed"
    if cjk_count >= max(2, int(alpha_count * 0.6)):
        return "zh"
    if alpha_count >= max(3, cjk_count * 2):
        return "en"
    return "mixed"


def _lesson_text_for_language(*, zh: str, en: str, language: str) -> str:
    return zh if str(language or "").strip().lower() == "zh" else en


def _round_json_from_roots(*, prompt_root: Path, log_root: Path, round_index: int, artifact_name: str) -> Dict[str, Any]:
    round_tag = _round_tag(int(round_index))
    candidates = [
        _prompt_round_artifact(prompt_root / round_tag, artifact_name),
        _prompt_round_artifact(log_root / round_tag, artifact_name),
        _log_round_artifact(log_root / round_tag, artifact_name),
    ]
    seen = set()
    for path in candidates:
        norm = str(path)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if path.is_file():
            payload = _load_json(path)
            if payload:
                return payload
    return {}


def _round_text_from_roots(*, prompt_root: Path, log_root: Path, round_index: int, artifact_name: str) -> str:
    round_tag = _round_tag(int(round_index))
    candidates = [
        _prompt_round_artifact(prompt_root / round_tag, artifact_name),
        _prompt_round_artifact(log_root / round_tag, artifact_name),
        _log_round_artifact(log_root / round_tag, artifact_name),
    ]
    seen = set()
    for path in candidates:
        norm = str(path)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if path.is_file():
            text = _safe_read_text(path).rstrip("\n")
            if text:
                return text
    return ""


def _operation_digest(op: Dict[str, Any], *, status: str) -> Dict[str, Any]:
    return {
        "status": str(status or "").strip() or "accepted",
        "op": str(op.get("op") or "").strip(),
        "target_section": str(op.get("target_section") or "").strip(),
        "content_summary": _compact_text(str(op.get("content") or "").strip(), 160),
    }


def _infer_failure_mode(
    *,
    language: str,
    promotion_reason: str,
    accepted_operation_count: int,
    metric_delta: Dict[str, Any],
    fixed_fp_count: int,
    new_fp_count: int,
    fixed_fn_count: int,
    new_fn_count: int,
) -> Dict[str, str]:
    reason = str(promotion_reason or "").strip()
    p_delta = _safe_float(metric_delta.get("precision_yes"), 0.0)
    recall_delta = _safe_float(metric_delta.get("recall_yes"), 0.0)
    if accepted_operation_count <= 0:
        return {
            "code": "no_effective_patch_applied",
            "text": _lesson_text_for_language(
                zh="没有真正形成有效 patch，本轮更像一次无效尝试或合并后无实质变化。",
                en="No effective patch was actually applied, so this round behaved more like a no-op or merge-without-real-change attempt.",
                language=language,
            ),
        }
    if reason == "recall_drop_too_large_for_small_precision_gain":
        return {
            "code": "precision_gain_but_recall_damage",
            "text": _lesson_text_for_language(
                zh="虽然 precision 有所改善，但 recall 损伤过大，说明这类边界收得太狠。",
                en="Precision improved somewhat, but recall damage was too large, which means the boundary became too aggressive.",
                language=language,
            ),
        }
    if reason == "ny_spike_without_meaningful_precision_gain":
        return {
            "code": "fn_spike_without_precision_gain",
            "text": _lesson_text_for_language(
                zh="FN/NY 明显上升，却没有带来足够的 precision 收益，说明这次修补方向不划算。",
                en="False negatives spiked without enough precision gain, so the tradeoff was not worth it.",
                language=language,
            ),
        }
    if fixed_fp_count > 0 and new_fn_count > 0 and new_fn_count >= max(1, fixed_fp_count // 2):
        return {
            "code": "too_broad_negative_boundary",
            "text": _lesson_text_for_language(
                zh="负向边界过宽，虽然压住了一些误抽，但也误伤了本应保留的正例。",
                en="The negative boundary became too broad: it fixed some false positives, but also suppressed positives that should have been preserved.",
                language=language,
            ),
        }
    if fixed_fn_count > 0 and new_fp_count > 0 and new_fp_count >= max(1, fixed_fn_count // 2):
        return {
            "code": "too_broad_positive_boundary",
            "text": _lesson_text_for_language(
                zh="正向边界过宽，虽然补回了一些漏抽，但也放进了过多不该抽取的样本。",
                en="The positive boundary became too broad: it recovered some false negatives, but also admitted too many false positives.",
                language=language,
            ),
        }
    if fixed_fp_count <= 0 and fixed_fn_count <= 0 and p_delta <= 0.0 and recall_delta <= 0.0:
        return {
            "code": "low_signal_or_wrong_direction",
            "text": _lesson_text_for_language(
                zh="这次 patch 没有形成明确收益，说明信号不足，或者修补方向本身就偏了。",
                en="This patch did not create a clear benefit, which suggests either weak signal or the wrong repair direction.",
                language=language,
            ),
        }
    return {
        "code": "mixed_effect_needs_narrower_patch",
        "text": _lesson_text_for_language(
            zh="这次尝试既有局部收益也有副作用，需要更窄、更精确的 patch，而不是简单重复原动作。",
            en="This attempt had mixed effects, so it needs a narrower and more precise patch rather than a direct repeat.",
            language=language,
        ),
    }


def _do_not_repeat_and_refine(*, language: str, failure_mode_code: str) -> Dict[str, str]:
    if failure_mode_code == "too_broad_negative_boundary":
        return {
            "do_not_repeat": _lesson_text_for_language(
                zh="不要按题材整类压制请求，也不要把当前问题求解和可复用 workflow 混成一个负例族。",
                en="Do not suppress an entire task category, and do not collapse current problem solving together with reusable workflows into one negative family.",
                language=language,
            ),
            "refine_instead": _lesson_text_for_language(
                zh="应把负向边界收窄到 one-off current-task help、一次性交付参数和强 payload 依赖请求。",
                en="Instead, narrow the negative boundary to one-off current-task help, delivery-only parameters, and strongly payload-dependent requests.",
                language=language,
            ),
        }
    if failure_mode_code == "too_broad_positive_boundary":
        return {
            "do_not_repeat": _lesson_text_for_language(
                zh="不要因为存在一点格式、流程或重复表达，就把整类请求直接当成可复用技能。",
                en="Do not treat a whole family of requests as reusable skills just because they contain some formatting, workflow, or repetition signal.",
                language=language,
            ),
            "refine_instead": _lesson_text_for_language(
                zh="应补强真正稳定 schema / workflow / rubric 的正向证据，而不是扩大宽泛正向规则。",
                en="Instead, strengthen positive evidence for truly stable schema, workflow, or rubric signals instead of broadening positive rules indiscriminately.",
                language=language,
            ),
        }
    if failure_mode_code == "precision_gain_but_recall_damage":
        return {
            "do_not_repeat": _lesson_text_for_language(
                zh="不要为了很小的 precision 提升接受过大的 recall 损失。",
                en="Do not accept large recall damage for only a tiny precision gain.",
                language=language,
            ),
            "refine_instead": _lesson_text_for_language(
                zh="应优先寻找更局部的 rewrite，而不是继续整体收紧边界。",
                en="Instead, look for a more local rewrite instead of tightening the boundary globally again.",
                language=language,
            ),
        }
    if failure_mode_code == "fn_spike_without_precision_gain":
        return {
            "do_not_repeat": _lesson_text_for_language(
                zh="不要重复会明显抬高 NY/FN 却几乎不提升 precision 的 patch 方向。",
                en="Do not repeat a patch direction that sharply increases false negatives without delivering meaningful precision gain.",
                language=language,
            ),
            "refine_instead": _lesson_text_for_language(
                zh="应把当前负向规则收窄，并同步补强对稳定正向证据的识别。",
                en="Instead, narrow the current negative rule and strengthen recognition of stable positive evidence at the same time.",
                language=language,
            ),
        }
    return {
        "do_not_repeat": _lesson_text_for_language(
            zh="不要机械重复上一轮的 patch 文本或同一类过宽动作。",
            en="Do not mechanically repeat the previous patch text or the same over-broad move.",
            language=language,
        ),
        "refine_instead": _lesson_text_for_language(
            zh="应保留局部有效部分，并把边界改得更窄、更可解释。",
            en="Instead, preserve the locally effective part and make the boundary narrower and more explainable.",
            language=language,
        ),
    }


def _build_candidate_patch_lessons(
    *,
    history_rows: List[Dict[str, Any]],
    prompt_root: Path,
    log_root: Path,
    diagnosis_llm: Any = None,
    embeddings: Any = None,
) -> List[Dict[str, Any]]:
    lessons: List[Dict[str, Any]] = []
    for row in list(history_rows or []):
        prompt_version = str(row.get("prompt_version") or "").strip()
        if not prompt_version.startswith("round_"):
            continue
        if bool(row.get("promoted")):
            continue
        round_index = _safe_round_int(row.get("round"))
        parent_version = str(row.get("parent_prompt_version") or "").strip()
        if round_index <= 0 or not parent_version:
            continue
        reflection_output = _round_json_from_roots(
            prompt_root=prompt_root,
            log_root=log_root,
            round_index=round_index,
            artifact_name="reflection_output.json",
        )
        candidate_patch_plan = _round_json_from_roots(
            prompt_root=prompt_root,
            log_root=log_root,
            round_index=round_index,
            artifact_name="candidate_patch_set.json",
        )
        candidate_prompt = _round_text_from_roots(
            prompt_root=prompt_root,
            log_root=log_root,
            round_index=round_index,
            artifact_name="prompt_candidate.txt",
        )
        current_eval = _load_eval_for_prompt_version(prompt_root=prompt_root, log_root=log_root, prompt_version=prompt_version)
        reference_eval = _load_eval_for_prompt_version(prompt_root=prompt_root, log_root=log_root, prompt_version=parent_version)
        if not current_eval or not reference_eval:
            continue
        delta = build_error_delta(reference_eval=reference_eval, current_eval=current_eval, max_samples_per_bucket=4)
        normalized_reflection = normalize_patch_payload(reflection_output)
        accepted_ops = list(dict(candidate_patch_plan.get("accepted_patch") or {}).get("operations") or [])
        rejected_ops = list(dict(candidate_patch_plan.get("rejected_patch") or {}).get("operations") or [])
        target_sections = sorted(
            {
                str(op.get("target_section") or "").strip()
                for op in list(accepted_ops) + list(rejected_ops)
                if str(op.get("target_section") or "").strip()
            }
        )
        text_for_lang = " ".join(
            _string_list(normalized_reflection.get("yn_root_causes"))
            + _string_list(normalized_reflection.get("ny_root_causes"))
            + _string_list(normalized_reflection.get("fp_patterns"))
            + _string_list(normalized_reflection.get("fn_patterns"))
        )
        language = _dominant_language_code(text_for_lang)
        helped_clusters = build_reason_cluster_summaries_from_bucket(
            current_prompt=candidate_prompt,
            bucket=dict(delta.get("fixed_fp") or {}),
            error_side="fp",
            diagnosis_llm=diagnosis_llm,
            embeddings=embeddings,
        ) + build_reason_cluster_summaries_from_bucket(
            current_prompt=candidate_prompt,
            bucket=dict(delta.get("fixed_fn") or {}),
            error_side="fn",
            diagnosis_llm=diagnosis_llm,
            embeddings=embeddings,
        )
        hurt_clusters = build_reason_cluster_summaries_from_bucket(
            current_prompt=candidate_prompt,
            bucket=dict(delta.get("new_fp") or {}),
            error_side="fp",
            diagnosis_llm=diagnosis_llm,
            embeddings=embeddings,
        ) + build_reason_cluster_summaries_from_bucket(
            current_prompt=candidate_prompt,
            bucket=dict(delta.get("new_fn") or {}),
            error_side="fn",
            diagnosis_llm=diagnosis_llm,
            embeddings=embeddings,
        )
        metric_delta = dict(delta.get("metric_delta") or {})
        fixed_fp_count = _safe_round_int(dict(delta.get("fixed_fp") or {}).get("count"))
        new_fp_count = _safe_round_int(dict(delta.get("new_fp") or {}).get("count"))
        fixed_fn_count = _safe_round_int(dict(delta.get("fixed_fn") or {}).get("count"))
        new_fn_count = _safe_round_int(dict(delta.get("new_fn") or {}).get("count"))
        failure_mode = _infer_failure_mode(
            language=language,
            promotion_reason=str(row.get("promotion_reason") or ""),
            accepted_operation_count=len(accepted_ops),
            metric_delta=metric_delta,
            fixed_fp_count=fixed_fp_count,
            new_fp_count=new_fp_count,
            fixed_fn_count=fixed_fn_count,
            new_fn_count=new_fn_count,
        )
        guidance = _do_not_repeat_and_refine(language=language, failure_mode_code=str(failure_mode.get("code") or ""))
        operation_digests = [
            _operation_digest(op, status="accepted") for op in accepted_ops[:4]
        ] + [
            _operation_digest(op, status="rejected") for op in rejected_ops[:2]
        ]
        lessons.append(
            {
                "round": int(round_index),
                "prompt_version": prompt_version,
                "parent_prompt_version": parent_version,
                "language": language,
                "promoted": False,
                "promotion_reason": str(row.get("promotion_reason") or ""),
                "attempt_summary": {
                    "yn_root_causes": _string_list(normalized_reflection.get("yn_root_causes")),
                    "ny_root_causes": _string_list(normalized_reflection.get("ny_root_causes")),
                    "fp_patterns": _string_list(normalized_reflection.get("fp_patterns")),
                    "fn_patterns": _string_list(normalized_reflection.get("fn_patterns")),
                },
                "attempted_patch": {
                    "accepted_operation_count": int(len(accepted_ops)),
                    "rejected_operation_count": int(len(rejected_ops)),
                    "target_sections": target_sections,
                    "operation_digests": operation_digests,
                },
                "observed_effect": {
                    "metric_delta": metric_delta,
                    "fixed_fp_count": int(fixed_fp_count),
                    "new_fp_count": int(new_fp_count),
                    "fixed_fn_count": int(fixed_fn_count),
                    "new_fn_count": int(new_fn_count),
                },
                "cluster_effect": {
                    "helped_clusters": helped_clusters,
                    "hurt_clusters": hurt_clusters,
                },
                "lesson": {
                    "failure_mode": failure_mode,
                    "do_not_repeat": guidance["do_not_repeat"],
                    "refine_instead": guidance["refine_instead"],
                },
            }
        )
    lessons.sort(key=lambda item: int(item.get("round", 0) or 0))
    return lessons


def _build_anti_regression_memory(*, candidate_patch_lessons: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidate_patch_lessons:
        return {"language": "mixed", "stable_do_not_repeat": [], "known_risk_transitions": [], "preserve_wins": [], "open_tradeoffs": []}
    language_counts: Dict[str, int] = {}
    for lesson in candidate_patch_lessons:
        lang = str(lesson.get("language") or "mixed").strip().lower() or "mixed"
        language_counts[lang] = language_counts.get(lang, 0) + 1
    language = sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    stable_do_not_repeat: List[Dict[str, str]] = []
    seen_repeat = set()
    preserve_wins: List[Dict[str, str]] = []
    seen_preserve = set()
    known_risk_transitions: List[Dict[str, str]] = []
    seen_risk = set()
    open_tradeoffs: List[Dict[str, str]] = []
    seen_tradeoff = set()

    for lesson in candidate_patch_lessons:
        failure_mode = dict(dict(lesson.get("lesson") or {}).get("failure_mode") or {})
        failure_code = str(failure_mode.get("code") or "").strip()
        do_not_repeat = str(dict(lesson.get("lesson") or {}).get("do_not_repeat") or "").strip()
        refine_instead = str(dict(lesson.get("lesson") or {}).get("refine_instead") or "").strip()
        if failure_code or do_not_repeat:
            key = (failure_code, do_not_repeat)
            if key not in seen_repeat:
                seen_repeat.add(key)
                stable_do_not_repeat.append({"code": failure_code, "text": do_not_repeat})
        if failure_code or refine_instead:
            key = (failure_code, refine_instead)
            if key not in seen_tradeoff:
                seen_tradeoff.add(key)
                open_tradeoffs.append({"code": failure_code, "text": refine_instead})
        helped = list(dict(lesson.get("cluster_effect") or {}).get("helped_clusters") or [])
        hurt = list(dict(lesson.get("cluster_effect") or {}).get("hurt_clusters") or [])
        for item in helped:
            cluster_id = str(item.get("cluster_id") or "").strip()
            summary = str(item.get("summary") or "").strip()
            key = (cluster_id, summary)
            if cluster_id and key not in seen_preserve:
                seen_preserve.add(key)
                preserve_wins.append({"cluster": cluster_id, "text": summary})
        for src in helped:
            for dst in hurt:
                from_id = str(src.get("cluster_id") or "").strip()
                to_id = str(dst.get("cluster_id") or "").strip()
                if not from_id or not to_id:
                    continue
                key = (from_id, to_id)
                if key in seen_risk:
                    continue
                seen_risk.add(key)
                known_risk_transitions.append(
                    {
                        "from_cluster": from_id,
                        "to_cluster": to_id,
                        "risk_text": _lesson_text_for_language(
                            zh=f"修复“{str(src.get('summary') or '').strip()}”时，曾经误伤“{str(dst.get('summary') or '').strip()}”。",
                            en=f"Fixing '{str(src.get('summary') or '').strip()}' previously hurt '{str(dst.get('summary') or '').strip()}'.",
                            language=language,
                        ),
                    }
                )

    return {
        "language": language,
        "stable_do_not_repeat": stable_do_not_repeat,
        "known_risk_transitions": known_risk_transitions,
        "preserve_wins": preserve_wins,
        "open_tradeoffs": open_tradeoffs,
    }


def _safe_round_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def build_parser(*, add_help: bool = True) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Self-evolution loop for offline conversation extract prompt.",
        add_help=add_help,
    )
    p.add_argument("--train-root", default="data/train")
    p.add_argument("--train-meta-info-jsonl", default="data/train/meta_info.jsonl")
    p.add_argument("--train-max-samples", type=int, default=0, help="0 means use the full train dataset; otherwise use the first N train meta rows.")
    p.add_argument("--eval-root", default="data/eval")
    p.add_argument("--eval-meta-info-jsonl", default="data/eval/meta_info.jsonl")
    p.add_argument("--run-name", required=True)
    p.add_argument("--session-stamp", default="", help="Optional fixed session stamp like 2026-0402-1711.")
    p.add_argument("--resume", default="0", help="1|0. Resume an existing run.")
    p.add_argument("--extract-mode", default="specific", help="common|specific. Default specific.")
    p.add_argument("--max-rounds", type=int, default=20)
    p.add_argument("--patience", type=int, default=3)
    p.add_argument("--eval-before", default="1", help="1|0. Run held-out baseline eval before evolve.")
    p.add_argument("--eval-after", default="1", help="1|0. Run held-out final eval after evolve.")
    p.add_argument(
        "--max-candidate-prompt-change-ratio",
        type=_parse_ratio_arg,
        default=0.25,
        help="Max single-round candidate prompt delta vs current active prompt. Accepts 0.25, 25, or 25%%. Default 25%%.",
    )
    p.add_argument(
        "--base-prompt-min-length-ratio",
        type=_parse_multiplier_arg,
        default=0.70,
        help="Lower bound for recomposed prompt length vs base_prompt. Accepts 0.7, 0.7x, or 70%%. Default 0.7x.",
    )
    p.add_argument(
        "--base-prompt-max-length-ratio",
        type=_parse_multiplier_arg,
        default=1.50,
        help="Upper bound for recomposed prompt length vs base_prompt. Accepts 1.5, 1.5x, or 150%%. Default 1.5x.",
    )
    p.add_argument("--auto-promote", default="1", help="1|0. Auto promote better prompts.")
    p.add_argument("--user-id", default="evolve_eval")
    p.add_argument("--hint", default="")
    p.add_argument("--max-messages-per-conversation", type=int, default=0)
    p.add_argument("--max-workers", type=int, default=8)
    p.add_argument("--max-failed-retries", type=int, default=3)
    p.add_argument("--print-progress", default="1")
    p.add_argument("--disable-env-proxy", default="1", help="1|0. Temporarily clear HTTP(S)_PROXY style env vars during evolve.")

    p.add_argument("--llm-provider", default=os.getenv("AUTOSKILL_LLM_PROVIDER", ""))
    p.add_argument("--llm-model", default=os.getenv("AUTOSKILL_LLM_MODEL", ""))
    p.add_argument("--llm-base-url", default=os.getenv("AUTOSKILL_LLM_BASE_URL", ""))
    p.add_argument("--llm-api-key", default=os.getenv("AUTOSKILL_LLM_API_KEY", ""))
    p.add_argument("--auth-mode", default=os.getenv("AUTOSKILL_LLM_AUTH_MODE", ""))
    add_codex_llm_args(p)
    p.add_argument("--embeddings-provider", default=os.getenv("AUTOSKILL_EMBEDDINGS_PROVIDER", os.getenv("AUTOSKILL_EMBEDDING_PROVIDER", "")))
    p.add_argument("--embeddings-model", default=os.getenv("AUTOSKILL_EMBEDDINGS_MODEL", ""))
    p.add_argument("--embeddings-base-url", default=os.getenv("AUTOSKILL_EMBEDDINGS_BASE_URL", ""))
    p.add_argument("--embeddings-api-key", default=os.getenv("AUTOSKILL_EMBEDDINGS_API_KEY", ""))
    p.add_argument("--embeddings-auth-mode", default=os.getenv("AUTOSKILL_EMBEDDINGS_AUTH_MODE", ""))
    p.add_argument("--embeddings-dims", type=int, default=int(os.getenv("AUTOSKILL_EMBEDDINGS_DIMS", "0") or 0))
    p.add_argument("--store-path", default="")
    p.add_argument("--strict-llm-errors", default=os.getenv("AUTOSKILL_OFFLINE_STRICT_LLM_ERRORS", "1"))

    p.add_argument("--reflection-provider", default="")
    p.add_argument("--reflection-model", default="")
    p.add_argument("--reflection-base-url", default="")
    p.add_argument("--reflection-api-key", default="")
    p.add_argument("--reflection-auth-mode", default="")
    p.add_argument("--reflection-mode", default="llm", help="llm|codex")
    p.add_argument("--reflection-temperature", type=float, default=0.2)
    return p


def run_parsed_args(args: argparse.Namespace) -> LoopRunResult:
    args.extract_mode = _normalize_extract_mode(args.extract_mode)
    args.reflection_mode = normalize_reflection_mode(getattr(args, "reflection_mode", "llm"))
    final_stop_signal: Optional[str] = None
    pending_round_index: Optional[int] = None
    pending_round_dir: Optional[Path] = None

    with _proxy_env_control(disable_proxy=bool(int(args.disable_env_proxy or 0))):
        train_root = _norm_path(str(args.train_root))
        if not train_root.is_dir():
            raise SystemExit(f"train-root is not a directory: {train_root}")
        train_meta_info_jsonl = _norm_path(str(args.train_meta_info_jsonl))
        if not train_meta_info_jsonl.is_file():
            raise SystemExit(f"train-meta-info-jsonl is not a file: {train_meta_info_jsonl}")
        eval_root = _norm_path(str(args.eval_root))
        if not eval_root.is_dir():
            raise SystemExit(f"eval-root is not a directory: {eval_root}")
        eval_meta_info_jsonl = _norm_path(str(args.eval_meta_info_jsonl))
        if not eval_meta_info_jsonl.is_file():
            raise SystemExit(f"eval-meta-info-jsonl is not a file: {eval_meta_info_jsonl}")

        stamp, prompt_root, log_root = _ensure_run_roots(args)
        manifest = _initialize_run(args=args, stamp=stamp, prompt_root=prompt_root, log_root=log_root)
        _migrate_all_prompt_round_files(prompt_root)
        manifest = _normalize_manifest_log_paths(manifest=manifest, log_root=log_root)
        _json_dump(prompt_root / "manifest.json", manifest)
        _json_dump(log_root / "manifest.json", manifest)
        _backfill_prompt_patch_artifacts(prompt_root)
        history_prompt_path, _history_log_path = _history_paths(prompt_root, log_root)
        history_rows = _load_history(history_prompt_path)

        base_prompt_path = Path(str(manifest.get("base_prompt_path") or prompt_root / "base_prompt.txt")).expanduser()
        active_prompt_path = prompt_root / "active_prompt.txt"
        best_prompt_path = prompt_root / "best_prompt.txt"
        active_patch_set_path = Path(str(manifest.get("active_patch_set_path") or prompt_root / "active_patch_set.json")).expanduser()
        best_patch_set_path = Path(str(manifest.get("best_patch_set_path") or prompt_root / "best_patch_set.json")).expanduser()
        best_metrics_path = prompt_root / "best_metrics.json"
        baseline_eval_metrics_path = prompt_root / "baseline_eval_metrics.json"
        final_eval_metrics_path = prompt_root / "final_eval_metrics.json"
        eval_before_enabled = bool(int(args.eval_before or 0))
        eval_after_enabled = bool(int(args.eval_after or 0))
        default_extract_mode = str(manifest.get("extract_mode") or args.extract_mode or "specific")
        base_prompt_min_length_ratio = float(
            manifest.get("base_prompt_min_length_ratio", getattr(args, "base_prompt_min_length_ratio", 0.70))
        )
        base_prompt_max_length_ratio = float(
            manifest.get("base_prompt_max_length_ratio", getattr(args, "base_prompt_max_length_ratio", 1.50))
        )
        if base_prompt_min_length_ratio > base_prompt_max_length_ratio:
            raise SystemExit(
                "base prompt length bounds invalid: "
                f"min={base_prompt_min_length_ratio} > max={base_prompt_max_length_ratio}"
            )

        normalized_base = _normalize_prompt_file_legacy_overlay(base_prompt_path)
        normalized_active = _normalize_prompt_file_legacy_overlay(active_prompt_path)
        normalized_best = _normalize_prompt_file_legacy_overlay(best_prompt_path)
        for label, payload in (
            ("base_prompt", normalized_base),
            ("active_prompt", normalized_active),
            ("best_prompt", normalized_best),
        ):
            if bool(payload.get("had_legacy_overlay")):
                _print_detail(
                    f"[legacy-overlay-migrated] file={label} "
                    f"operations={int(payload.get('migrated_operation_count', 0) or 0)}"
                )

        base_prompt = _safe_read_text(base_prompt_path).rstrip("\n") or _default_prompt_text(extract_mode=default_extract_mode)
        active_patch_set = _normalize_patch_set(_load_json(active_patch_set_path))
        best_patch_set = _normalize_patch_set(_load_json(best_patch_set_path))
        active_prompt_text = _safe_read_text(active_prompt_path).rstrip("\n")
        active_prompt_is_manual_mainline = (
            bool(active_prompt_text.strip())
            and active_prompt_text != base_prompt.rstrip("\n")
            and not _patch_has_prompt_visible_content(active_patch_set)
            and _mtime_ns(active_prompt_path) > _mtime_ns(base_prompt_path)
        )
        if active_prompt_is_manual_mainline:
            base_prompt = active_prompt_text
            base_prompt_path.write_text(base_prompt.rstrip("\n") + "\n", encoding="utf-8")
            _print_detail(
                "[manual-active-prompt-preserved] refreshed base_prompt from newer active_prompt "
                "because active_patch_set is empty"
            )
        else:
            recomposed_active_prompt = _compose_prompt_from_base_and_patch_set(base_prompt, active_patch_set)
            if recomposed_active_prompt.strip() and recomposed_active_prompt.rstrip("\n") != active_prompt_text:
                active_prompt_path.write_text(recomposed_active_prompt.rstrip("\n") + "\n", encoding="utf-8")
        recomposed_best_prompt = _compose_prompt_from_base_and_patch_set(base_prompt, best_patch_set)
        if recomposed_best_prompt.strip() and recomposed_best_prompt.rstrip("\n") != _safe_read_text(best_prompt_path).rstrip("\n"):
            best_prompt_path.write_text(recomposed_best_prompt.rstrip("\n") + "\n", encoding="utf-8")

        eval_baseline_path = Path(str(manifest.get("eval_baseline_json") or "")).expanduser() if str(manifest.get("eval_baseline_json") or "").strip() else Path("")
        if eval_before_enabled and not eval_baseline_path.is_file():
            _print_header("Eval Baseline")
            eval_baseline = _run_eval_dataset(
                args=args,
                eval_root=eval_root,
                meta_info_jsonl=eval_meta_info_jsonl,
                prompt_file=active_prompt_path,
                log_root=log_root,
                eval_name="eval_baseline",
                prompt_version="eval_baseline_active",
            )
            _json_dump(baseline_eval_metrics_path, dict(eval_baseline.get("metrics") or {}))
            manifest["eval_baseline_json"] = str(eval_baseline.get("eval_json") or "")
            _json_dump(prompt_root / "manifest.json", manifest)
            _json_dump(log_root / "manifest.json", manifest)
            _print_round_metrics(
                round_index=0,
                metrics=dict(eval_baseline.get("metrics") or {}),
                promoted=None,
                label="eval_baseline",
            )
        elif not eval_before_enabled:
            _print_header("Eval Baseline")
            _print_detail("[skip] eval_before=off")

        if not history_rows:
            _print_header("Round 000")
            _print_detail("phase: baseline")
            baseline_eval = _run_one_eval(
                args=args,
                eval_root=train_root,
                meta_info_jsonl=train_meta_info_jsonl,
                prompt_file=active_prompt_path,
                log_root=log_root,
                round_index=0,
                prompt_version="round_000_active",
                max_samples=int(args.train_max_samples or 0),
            )
            baseline_metrics = dict(baseline_eval.get("metrics") or {})
            _json_dump(best_metrics_path, baseline_metrics)
            round_dir = _ensure_prompt_round_layout(prompt_root, round_index=0)
            current_prompt = _safe_read_text(active_prompt_path).rstrip("\n")
            prompt_before_path = _prompt_round_artifact(round_dir, "prompt_before.txt")
            prompt_candidate_path = _prompt_round_artifact(round_dir, "prompt_candidate.txt")
            prompt_diff_path = _prompt_round_artifact(round_dir, "prompt_diff.md")
            prompt_before_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_before_path.write_text(current_prompt + "\n", encoding="utf-8")
            prompt_candidate_path.write_text(current_prompt + "\n", encoding="utf-8")
            prompt_diff_path.write_text(_build_prompt_diff(current_prompt, current_prompt), encoding="utf-8")
            baseline_summary = {
                "round": 0,
                "prompt_version": "round_000_active",
                "parent_prompt_version": None,
                **baseline_metrics,
                "errors": int(baseline_metrics.get("trace_error_count", 0) or 0),
                "promoted": True,
                "promotion_reason": "initial_baseline",
                "stop_signal": None,
            }
            prompt_summary_path = _prompt_round_artifact(round_dir, "round_summary.json")
            log_round_dir = _ensure_log_round_layout(log_root, round_index=0)
            log_summary_path = _log_round_artifact(log_round_dir, "round_summary.json")
            _json_dump(prompt_summary_path, baseline_summary)
            if prompt_summary_path.resolve() != log_summary_path.resolve():
                _json_dump(log_summary_path, baseline_summary)
            _write_history_row(prompt_root, log_root, baseline_summary)
            manifest["active_train_eval_json"] = str(baseline_eval.get("eval_json") or "")
            manifest["best_train_eval_json"] = str(baseline_eval.get("eval_json") or "")
            manifest["completed_rounds"] = [0]
            _json_dump(prompt_root / "manifest.json", manifest)
            _json_dump(log_root / "manifest.json", manifest)
            history_rows = _load_history(history_prompt_path)
            _print_round_metrics(
                round_index=0,
                metrics=baseline_metrics,
                promoted=True,
                promotion_reason="initial_baseline",
                label="baseline",
            )

        reflection_llm = build_reflection_llm(args) if _should_build_reflection_analysis_llm(args) else None
        reflection_embeddings = build_reflection_embeddings(args)
        best_metrics = _load_json(best_metrics_path)
        active_eval_path = Path(str(manifest.get("active_train_eval_json") or manifest.get("active_eval_json") or "")).expanduser()
        if not active_eval_path.is_file():
            raise SystemExit("active_train_eval_json missing from manifest; cannot continue evolution")

        no_improve_rounds = 0
        completed_rounds = [int(row.get("round", 0) or 0) for row in history_rows]
        start_round = max(completed_rounds) + 1 if completed_rounds else 1
        should_run_final_eval = True
        max_candidate_prompt_change_ratio = float(getattr(args, "max_candidate_prompt_change_ratio", 0.25) or 0.25)

        for round_index in range(start_round, int(args.max_rounds) + 1):
            _print_header(f"Round {round_index:03d}")
            _print_detail("phase: reflect_and_eval")
            base_prompt = _safe_read_text(base_prompt_path).rstrip("\n") or _default_prompt_text(extract_mode=default_extract_mode)
            current_prompt = _safe_read_text(active_prompt_path).rstrip("\n")
            current_patch_set = _normalize_patch_set(_load_json(active_patch_set_path))
            active_eval = _load_json(active_eval_path)
            round_dir = _ensure_prompt_round_layout(prompt_root, round_index=round_index)
            prompt_before_path = _prompt_round_artifact(round_dir, "prompt_before.txt")
            active_patch_before_path = _prompt_round_artifact(round_dir, "active_patch_set_before.json")
            prompt_before_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_before_path.write_text(current_prompt + "\n", encoding="utf-8")
            _json_dump(active_patch_before_path, current_patch_set)
            reference_eval = _load_reference_eval_for_active(
                active_eval=active_eval,
                history_rows=history_rows,
                prompt_root=prompt_root,
                log_root=log_root,
            )
            recent_candidate_deltas = _build_recent_candidate_deltas(
                history_rows=history_rows,
                prompt_root=prompt_root,
                log_root=log_root,
                limit=3,
            )
            candidate_patch_lessons = _build_candidate_patch_lessons(
                history_rows=history_rows,
                prompt_root=prompt_root,
                log_root=log_root,
                diagnosis_llm=reflection_llm,
                embeddings=reflection_embeddings,
            )
            anti_regression_memory = _build_anti_regression_memory(
                candidate_patch_lessons=candidate_patch_lessons,
            )

            reflection_input = build_reflection_input(
                base_prompt=base_prompt,
                current_prompt=current_prompt,
                current_patch_set=current_patch_set,
                active_eval=active_eval,
                history_rows=history_rows,
                reference_eval=reference_eval,
                recent_candidate_deltas=recent_candidate_deltas,
                candidate_patch_lessons=candidate_patch_lessons,
                anti_regression_memory=anti_regression_memory,
                diagnosis_llm=reflection_llm,
                embeddings=reflection_embeddings,
            )
            reflection_input_path = _prompt_round_artifact(round_dir, "reflection_input.json")
            reflection_output_path = _prompt_round_artifact(round_dir, "reflection_output.json")
            reflection_status_path = _prompt_round_artifact(round_dir, "reflection_status.json")
            round_status_path = _prompt_round_artifact(round_dir, "round_status.json")
            candidate_patch_set_path = _prompt_round_artifact(round_dir, "candidate_patch_set.json")
            prompt_candidate_path = _prompt_round_artifact(round_dir, "prompt_candidate.txt")
            prompt_diff_path = _prompt_round_artifact(round_dir, "prompt_diff.md")
            prompt_summary_path = _prompt_round_artifact(round_dir, "round_summary.json")
            _json_dump(reflection_input_path, reflection_input)
            _print_detail(
                "[reflection-start] "
                f"round={round_index:03d} "
                f"mode={str(args.reflection_mode)} "
                f"input_json={_display_path(reflection_input_path)}"
            )

            stop_signal: Optional[str] = None
            promoted = False
            promotion_reason = "not_promoted"
            candidate_prompt = current_prompt
            candidate_patch_plan: Dict[str, Any] = {
                "patch_set": copy.deepcopy(current_patch_set),
                "accepted_patch": {"operations": []},
                "rejected_patch": {"operations": []},
                "budget": {
                    "max_growth_ratio": max_candidate_prompt_change_ratio,
                    "current_prompt_char_count": len(current_prompt),
                    "candidate_prompt_char_count": len(current_prompt),
                    "delta_ratio": 0.0,
                },
                "candidate_prompt": current_prompt,
            }
            try:
                reflection_output = run_reflection(
                    mode=str(args.reflection_mode),
                    llm=reflection_llm,
                    reflection_input=reflection_input,
                    temperature=float(args.reflection_temperature),
                    output_path=reflection_output_path,
                )
                candidate_patch_plan = _merge_patch_set_with_budget(
                    current_patch_set=current_patch_set,
                    proposal_patch=reflection_output,
                    base_prompt=base_prompt,
                    current_prompt=current_prompt,
                    round_index=round_index,
                    max_growth_ratio=max_candidate_prompt_change_ratio,
                    base_prompt_min_ratio=base_prompt_min_length_ratio,
                    base_prompt_max_ratio=base_prompt_max_length_ratio,
                )
                _json_dump(candidate_patch_set_path, candidate_patch_plan)
                candidate_prompt = str(candidate_patch_plan.get("candidate_prompt") or "").rstrip("\n") or current_prompt
                _print_detail(
                    "[reflection-done] "
                    f"round={round_index:03d} "
                    f"mode={str(args.reflection_mode)} "
                    f"output_json={_display_path(reflection_output_path)}"
                )
            except ReflectionPendingError as exc:
                stop_signal = "waiting_for_codex_reflection"
                _json_dump(
                    reflection_status_path,
                    {
                        "status": "pending",
                        "reflection_mode": str(args.reflection_mode),
                        "message": str(exc),
                        "reflection_input_json": str(reflection_input_path),
                        "expected_output_json": str(reflection_output_path),
                    },
                )
                _print_detail(
                    "[reflection-pending] "
                    f"round={round_index:03d} "
                    f"mode={str(args.reflection_mode)} "
                    f"status_json={_display_path(reflection_status_path)} "
                    f"expected_output_json={_display_path(reflection_output_path)}"
                )
            except Exception as exc:
                reflection_output = {"error": str(exc)}
                _json_dump(_prompt_round_artifact(round_dir, "reflection_error.json"), reflection_output)
                stop_signal = "reflection_invalid"
                _print_detail(
                    "[reflection-error] "
                    f"round={round_index:03d} "
                    f"mode={str(args.reflection_mode)} "
                    f"error={exc}"
                )

            if stop_signal is not None:
                final_stop_signal = stop_signal
                pending_round_index = int(round_index)
                pending_round_dir = round_dir
                _json_dump(
                    round_status_path,
                    {
                        "round": int(round_index),
                        "status": "stopped_before_eval",
                        "stop_signal": stop_signal,
                        "reflection_mode": str(args.reflection_mode),
                    },
                )
                should_run_final_eval = False
                _print_detail(f"[stop] round={round_index:03d} reason={stop_signal}")
                break

            prompt_candidate_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_candidate_path.write_text(candidate_prompt + "\n", encoding="utf-8")
            prompt_diff_path.write_text(_build_prompt_diff(current_prompt, candidate_prompt), encoding="utf-8")
            _write_prompt_patch_artifacts(
                round_dir=round_dir,
                round_index=round_index,
                before_prompt=current_prompt,
                candidate_prompt=candidate_prompt,
                reflection_output=reflection_output,
            )

            candidate_eval = _run_one_eval(
                args=args,
                eval_root=train_root,
                meta_info_jsonl=train_meta_info_jsonl,
                prompt_file=prompt_candidate_path,
                log_root=log_root,
                round_index=round_index,
                prompt_version=f"{_round_tag(round_index)}_candidate",
                max_samples=int(args.train_max_samples or 0),
            )
            candidate_metrics = dict(candidate_eval.get("metrics") or {})
            best_metrics_before = dict(best_metrics or {})
            better = _promotion_cmp_key(candidate_metrics) > _promotion_cmp_key(best_metrics_before)
            gate_ok, gate_reason = _safety_gate(candidate_metrics=candidate_metrics, best_metrics=best_metrics_before)
            auto_promote_enabled = bool(int(args.auto_promote or 0))
            if better and gate_ok and auto_promote_enabled:
                best_metrics = candidate_metrics
                best_prompt_path.write_text(candidate_prompt + "\n", encoding="utf-8")
                active_prompt_path.write_text(candidate_prompt + "\n", encoding="utf-8")
                _json_dump(active_patch_set_path, dict(candidate_patch_plan.get("patch_set") or _empty_patch_set()))
                _json_dump(best_patch_set_path, dict(candidate_patch_plan.get("patch_set") or _empty_patch_set()))
                _json_dump(best_metrics_path, best_metrics)
                manifest["active_train_eval_json"] = str(candidate_eval.get("eval_json") or "")
                manifest["best_train_eval_json"] = str(candidate_eval.get("eval_json") or "")
                promoted = True
                promotion_reason = "precision_first_improved"
                no_improve_rounds = 0
                active_eval_path = Path(str(manifest.get("active_train_eval_json") or "")).expanduser()
            else:
                promoted = False
                promotion_reason = "candidate_not_better" if not better else gate_reason
                no_improve_rounds += 1

            _print_promote_decision(
                round_index=round_index,
                best_metrics_before=best_metrics_before,
                candidate_metrics=candidate_metrics,
                better=better,
                gate_ok=gate_ok,
                gate_reason=gate_reason,
                auto_promote_enabled=auto_promote_enabled,
                promoted=promoted,
                promotion_reason=promotion_reason,
            )

            summary_metrics = dict(candidate_eval.get("metrics") or best_metrics)
            history_row = {
                "round": int(round_index),
                "prompt_version": f"{_round_tag(round_index)}_candidate",
                "parent_prompt_version": str(active_eval.get("prompt_version") or "round_000_active"),
                "precision_yes": float(summary_metrics.get("precision_yes", 0.0) or 0.0),
                "f1_yes": float(summary_metrics.get("f1_yes", 0.0) or 0.0),
                "recall_yes": float(summary_metrics.get("recall_yes", 0.0) or 0.0),
                "accuracy": float(summary_metrics.get("accuracy", 0.0) or 0.0),
                "yy": int(summary_metrics.get("yy", 0) or 0),
                "nn": int(summary_metrics.get("nn", 0) or 0),
                "yn": int(summary_metrics.get("yn", 0) or 0),
                "ny": int(summary_metrics.get("ny", 0) or 0),
                "coverage": int(summary_metrics.get("coverage", 0) or 0),
                "errors": int(summary_metrics.get("trace_error_count", 0) or 0),
                "patch_budget_delta_ratio": float(dict(candidate_patch_plan.get("budget") or {}).get("delta_ratio", 0.0) or 0.0),
                "promoted": bool(promoted),
                "promotion_reason": promotion_reason,
                "stop_signal": stop_signal,
            }
            _json_dump(prompt_summary_path, history_row)
            log_round_dir = _ensure_log_round_layout(log_root, round_index=round_index)
            log_summary_path = _log_round_artifact(log_round_dir, "round_summary.json")
            if prompt_summary_path.resolve() != log_summary_path.resolve():
                _json_dump(log_summary_path, history_row)
            _write_history_row(prompt_root, log_root, history_row)
            history_rows.append(history_row)
            manifest["completed_rounds"] = list(manifest.get("completed_rounds") or []) + [int(round_index)]
            _json_dump(prompt_root / "manifest.json", manifest)
            _json_dump(log_root / "manifest.json", manifest)
            _print_round_metrics(
                round_index=round_index,
                metrics=summary_metrics,
                promoted=promoted,
                promotion_reason=promotion_reason,
                label="candidate",
            )

            if no_improve_rounds >= int(args.patience):
                _print_detail(f"[stop] round={round_index:03d} reason=patience_exhausted({no_improve_rounds})")
                break

        if not should_run_final_eval:
            _print_header("Evolve Loop")
            if prompt_root.resolve() == log_root.resolve():
                _print_detail(f"run_root: {_display_path(log_root)}")
            else:
                _print_detail(f"prompt_root: {_display_path(prompt_root)}")
                _print_detail(f"log_root: {_display_path(log_root)}")
            _print_detail(f"best_prompt: {_display_path(best_prompt_path)}")
            _print_detail(f"best_metrics: {_display_path(best_metrics_path)}")
            return LoopRunResult(
                stamp=stamp,
                prompt_root=prompt_root,
                log_root=log_root,
                best_prompt_path=best_prompt_path,
                best_metrics_path=best_metrics_path,
                stop_signal=final_stop_signal,
                pending_round_index=pending_round_index,
                pending_round_dir=pending_round_dir,
            )

        if eval_after_enabled:
            _print_header("Eval Final")
            eval_final = _run_eval_dataset(
                args=args,
                eval_root=eval_root,
                meta_info_jsonl=eval_meta_info_jsonl,
                prompt_file=best_prompt_path,
                log_root=log_root,
                eval_name="eval_final",
                prompt_version="eval_final_best",
            )
            _json_dump(final_eval_metrics_path, dict(eval_final.get("metrics") or {}))
            manifest["eval_final_json"] = str(eval_final.get("eval_json") or "")
            _json_dump(prompt_root / "manifest.json", manifest)
            _json_dump(log_root / "manifest.json", manifest)
            _print_round_metrics(
                round_index=max(completed_rounds or [0]) if completed_rounds else 0,
                metrics=dict(eval_final.get("metrics") or {}),
                promoted=None,
                label="eval_final",
            )
        else:
            _print_header("Eval Final")
            _print_detail("[skip] eval_after=off")

        _print_header("Evolve Loop")
        if prompt_root.resolve() == log_root.resolve():
            _print_detail(f"run_root: {_display_path(log_root)}")
        else:
            _print_detail(f"prompt_root: {_display_path(prompt_root)}")
            _print_detail(f"log_root: {_display_path(log_root)}")
        _print_detail(f"best_prompt: {_display_path(best_prompt_path)}")
        _print_detail(f"best_metrics: {_display_path(best_metrics_path)}")
        return LoopRunResult(
            stamp=stamp,
            prompt_root=prompt_root,
            log_root=log_root,
            best_prompt_path=best_prompt_path,
            best_metrics_path=best_metrics_path,
            stop_signal=final_stop_signal,
            pending_round_index=pending_round_index,
            pending_round_dir=pending_round_dir,
        )


def main() -> None:
    args = build_parser().parse_args()
    run_parsed_args(args)


if __name__ == "__main__":
    main()
