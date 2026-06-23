"""Reflection backends for self-evolve prompt optimization."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from autoskill.embeddings.factory import build_embeddings
from autoskill.llm.factory import build_llm

from ..extract import _build_embeddings_config, _build_llm_config
from ..llm_backend import add_codex_llm_args, build_conversation_llm_config


PATCH_FIELD_MAP = {
    "add_negative_rules": ("add_negative_rules", "must_add_negative_rules"),
    "add_positive_rules": ("add_positive_rules", "must_add_positive_rules"),
    "weaken_rules": ("weaken_rules", "must_weaken_rules"),
    "strengthen_rules": ("strengthen_rules", "must_strengthen_rules"),
    "delete_rules": ("delete_rules", "must_delete_rules"),
}
SUPPORTED_PATCH_OPERATIONS = {"insert_rule", "rewrite_rule", "delete_rule", "move_rule"}
SUPPORTED_TARGET_SECTIONS = {
    "core_principle",
    "evidence_scope",
    "positive_rules",
    "negative_rules",
    "negative_cases",
    "generalization",
    "no_invention",
    "output_construction",
    "confidence_guidance",
    "final_emission_check",
    "language_consistency",
    "json_validity",
}
SUPPORTED_OPERATION_POSITIONS = {"append", "before_anchor", "after_anchor", "replace"}
SUPPORTED_REFLECTION_MODES = {"llm", "codex"}
DIAGNOSIS_BATCH_SIZE = 8
DIAGNOSIS_CLUSTER_SIMILARITY_THRESHOLD = 0.82


def _normalize_patch_strategy(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = dict(payload or {})
    cluster_ranking_raw = list(src.get("cluster_ranking") or []) if isinstance(src.get("cluster_ranking"), list) else []
    cluster_ranking: List[Dict[str, Any]] = []
    for item in cluster_ranking_raw:
        if not isinstance(item, dict):
            continue
        cluster_ranking.append(
            {
                "cluster_id": str(item.get("cluster_id") or "").strip(),
                "role": str(item.get("role") or "").strip(),
                "summary": str(item.get("summary") or "").strip(),
                "why_now": str(item.get("why_now") or "").strip(),
            }
        )
    preferred_actions_raw = list(src.get("preferred_actions") or []) if isinstance(src.get("preferred_actions"), list) else []
    preferred_actions: List[Dict[str, Any]] = []
    for item in preferred_actions_raw:
        if not isinstance(item, dict):
            continue
        preferred_actions.append(
            {
                "type": str(item.get("type") or "").strip(),
                "target_section": str(item.get("target_section") or "").strip(),
                "intent": str(item.get("intent") or "").strip(),
            }
        )
    avoid_actions_raw = list(src.get("avoid_actions") or []) if isinstance(src.get("avoid_actions"), list) else []
    avoid_actions: List[Dict[str, Any]] = []
    for item in avoid_actions_raw:
        if not isinstance(item, dict):
            continue
        avoid_actions.append({"code": str(item.get("code") or "").strip(), "text": str(item.get("text") or "").strip()})
    return {
        "language": str(src.get("language") or "").strip(),
        "global_goal": str(src.get("global_goal") or "").strip(),
        "cluster_ranking": cluster_ranking,
        "primary_targets": _string_list(src.get("primary_targets")),
        "secondary_targets": _string_list(src.get("secondary_targets")),
        "preserve_clusters": _string_list(src.get("preserve_clusters")),
        "preferred_actions": preferred_actions,
        "avoid_actions": avoid_actions,
        "tradeoff_expectation": str(src.get("tradeoff_expectation") or "").strip(),
        "success_criteria": _string_list(src.get("success_criteria")),
        "one_paragraph_strategy": str(src.get("one_paragraph_strategy") or "").strip(),
    }


class ReflectionPendingError(RuntimeError):
    """Raised when codex-mode reflection is waiting for an external result."""


def normalize_reflection_mode(mode: str) -> str:
    value = str(mode or "llm").strip().lower() or "llm"
    if value not in SUPPORTED_REFLECTION_MODES:
        raise SystemExit(f"Unsupported reflection-mode: {mode}. Expected one of {sorted(SUPPORTED_REFLECTION_MODES)}")
    return value


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _sample_id(sample: Dict[str, Any]) -> str:
    raw_id = str(sample.get("id") or "").strip()
    if raw_id:
        return raw_id
    source_file = str(sample.get("source_file") or sample.get("file_name") or "").strip()
    conversation_index = str(sample.get("conversation_index") or "").strip()
    return f"{source_file}#{conversation_index}" if source_file else conversation_index


def _user_texts(sample: Dict[str, Any]) -> List[str]:
    messages = sample.get("messages")
    if not isinstance(messages, list):
        return []
    out: List[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() != "user":
            continue
        text = str(msg.get("content") or "").strip()
        if text:
            out.append(text)
    return out


def _compact_text(text: str, limit: int = 240) -> str:
    value = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _skill_names(sample: Dict[str, Any]) -> List[str]:
    existing = sample.get("skill_names")
    if isinstance(existing, list):
        return [str(x).strip() for x in existing if str(x).strip()]
    skills = sample.get("skills")
    if not isinstance(skills, list):
        return []
    names: List[str] = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _sample_brief(sample: Dict[str, Any]) -> Dict[str, Any]:
    users = _user_texts(sample)
    if not users and ("first_user" in sample or "last_user" in sample):
        return {
            "id": _sample_id(sample),
            "gold_label": str(sample.get("gold_label") or ""),
            "pred_label": str(sample.get("pred_label") or ""),
            "candidate_count": _safe_int(sample.get("candidate_count"), 0),
            "turn_count": _safe_int(sample.get("turn_count"), 0),
            "first_user": _compact_text(str(sample.get("first_user") or ""), 260),
            "last_user": _compact_text(str(sample.get("last_user") or ""), 320),
            "skill_names": list(sample.get("skill_names") or []),
            "source_file": str(sample.get("source_file") or ""),
        }
    return {
        "id": _sample_id(sample),
        "gold_label": str(sample.get("gold_label") or ""),
        "pred_label": str(sample.get("pred_label") or ""),
        "candidate_count": _safe_int(sample.get("candidate_count"), 0),
        "turn_count": len(users),
        "first_user": _compact_text(users[0], 260) if users else "",
        "last_user": _compact_text(users[-1], 320) if users else "",
        "skill_names": _skill_names(sample),
        "source_file": str(sample.get("source_file") or ""),
    }


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


def _dominant_language_for_sample(sample: Dict[str, Any]) -> str:
    users = _user_texts(sample)
    if users:
        return _dominant_language_code("\n".join(users))
    fallback = " ".join(
        [
            str(sample.get("first_user") or ""),
            str(sample.get("last_user") or ""),
            " ".join(_skill_names(sample)),
        ]
    )
    return _dominant_language_code(fallback)


def _language_instruction(code: str) -> str:
    value = str(code or "").strip().lower()
    if value == "zh":
        return "Chinese"
    if value == "en":
        return "English"
    return "the dominant language of the USER text, without mixing languages across fields"


def _sample_payload_for_diagnosis(sample: Dict[str, Any]) -> Dict[str, Any]:
    users = _user_texts(sample)
    user_preview = [_compact_text(text, 320) for text in users[:4]]
    brief = _sample_brief(sample)
    return {
        "sample_id": str(brief.get("id") or ""),
        "gold_label": str(brief.get("gold_label") or ""),
        "pred_label": str(brief.get("pred_label") or ""),
        "candidate_count": _safe_int(brief.get("candidate_count"), 0),
        "turn_count": _safe_int(brief.get("turn_count"), 0),
        "source_file": str(brief.get("source_file") or ""),
        "skill_names": list(brief.get("skill_names") or []),
        "dominant_language": _dominant_language_for_sample(sample),
        "first_user": str(brief.get("first_user") or ""),
        "last_user": str(brief.get("last_user") or ""),
        "user_messages": user_preview,
    }


def _normalize_text_key(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _error_index(eval_payload: Dict[str, Any], sample_key: str) -> Dict[str, Dict[str, Any]]:
    samples = eval_payload.get(sample_key)
    if not isinstance(samples, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        sid = _sample_id(sample)
        if sid:
            out[sid] = sample
    return out


def _ordered_samples(index: Dict[str, Dict[str, Any]], ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sid in ids:
        sample = index.get(str(sid))
        if sample:
            out.append(sample)
    return out


def _sorted_sample_ids(ids: Iterable[str]) -> List[str]:
    def key(value: str) -> Tuple[int, Any]:
        text = str(value)
        try:
            return (0, int(text))
        except Exception:
            return (1, text)

    return sorted([str(x) for x in ids if str(x)], key=key)


def _metric_subset(eval_payload: Dict[str, Any]) -> Dict[str, Any]:
    metrics = dict(eval_payload.get("metrics") or {})
    keys = [
        "eval_n",
        "accuracy",
        "precision_yes",
        "recall_yes",
        "f1_yes",
        "yy",
        "nn",
        "yn",
        "ny",
        "pred_yes_rate",
        "pred_no_rate",
        "fp_rate_among_pred_yes",
        "fn_rate_among_gold_yes",
        "coverage",
        "trace_error_count",
    ]
    return {key: metrics.get(key) for key in keys if key in metrics}


def _metric_delta(reference_eval: Dict[str, Any], current_eval: Dict[str, Any]) -> Dict[str, Any]:
    before = dict(reference_eval.get("metrics") or {})
    after = dict(current_eval.get("metrics") or {})
    keys = [
        "accuracy",
        "precision_yes",
        "recall_yes",
        "f1_yes",
        "yy",
        "nn",
        "yn",
        "ny",
        "pred_yes_rate",
        "pred_no_rate",
        "fp_rate_among_pred_yes",
        "fn_rate_among_gold_yes",
        "coverage",
        "trace_error_count",
    ]
    out: Dict[str, Any] = {}
    for key in keys:
        if key not in before and key not in after:
            continue
        out[key] = _safe_float(after.get(key), 0.0) - _safe_float(before.get(key), 0.0)
    return out


def _delta_bucket(
    *,
    ids: Sequence[str],
    index: Dict[str, Dict[str, Any]],
    max_samples: int,
) -> Dict[str, Any]:
    sample_ids = list(ids)
    return {
        "count": len(sample_ids),
        "ids": sample_ids[:100],
        "sample_ids_truncated": max(0, len(sample_ids) - 100),
        "samples": [_sample_brief(sample) for sample in _ordered_samples(index, sample_ids[:max_samples])],
    }


def build_error_delta(
    *,
    reference_eval: Dict[str, Any],
    current_eval: Dict[str, Any],
    max_samples_per_bucket: int = 12,
) -> Dict[str, Any]:
    ref_yn = _error_index(reference_eval, "yn_samples")
    ref_ny = _error_index(reference_eval, "ny_samples")
    cur_yn = _error_index(current_eval, "yn_samples")
    cur_ny = _error_index(current_eval, "ny_samples")
    ref_yn_ids = set(ref_yn)
    ref_ny_ids = set(ref_ny)
    cur_yn_ids = set(cur_yn)
    cur_ny_ids = set(cur_ny)
    fixed_fp = _sorted_sample_ids(ref_yn_ids - cur_yn_ids)
    new_fp = _sorted_sample_ids(cur_yn_ids - ref_yn_ids)
    unchanged_fp = _sorted_sample_ids(ref_yn_ids & cur_yn_ids)
    fixed_fn = _sorted_sample_ids(ref_ny_ids - cur_ny_ids)
    new_fn = _sorted_sample_ids(cur_ny_ids - ref_ny_ids)
    unchanged_fn = _sorted_sample_ids(ref_ny_ids & cur_ny_ids)
    return {
        "reference_prompt_version": str(reference_eval.get("prompt_version") or ""),
        "current_prompt_version": str(current_eval.get("prompt_version") or ""),
        "reference_metrics": _metric_subset(reference_eval),
        "current_metrics": _metric_subset(current_eval),
        "metric_delta": _metric_delta(reference_eval, current_eval),
        "fixed_fp": _delta_bucket(ids=fixed_fp, index=ref_yn, max_samples=max_samples_per_bucket),
        "new_fp": _delta_bucket(ids=new_fp, index=cur_yn, max_samples=max_samples_per_bucket),
        "unchanged_fp": _delta_bucket(ids=unchanged_fp, index=cur_yn, max_samples=min(4, max_samples_per_bucket)),
        "fixed_fn": _delta_bucket(ids=fixed_fn, index=ref_ny, max_samples=max_samples_per_bucket),
        "new_fn": _delta_bucket(ids=new_fn, index=cur_ny, max_samples=max_samples_per_bucket),
        "unchanged_fn": _delta_bucket(ids=unchanged_fn, index=cur_ny, max_samples=min(4, max_samples_per_bucket)),
    }


def build_sample_diagnosis_system_prompt() -> str:
    return (
        "You analyze offline extraction mistakes one sample at a time and output structured diagnoses.\n"
        "Output ONLY strict JSON parseable by json.loads.\n"
        "You are not proposing prompt patches yet. You are diagnosing why the current prompt failed on each sample.\n"
        "For each sample, return exactly these fields:\n"
        "- sample_id\n"
        "- error_side\n"
        "- language\n"
        "- root_cause\n"
        "- secondary_causes\n"
        "- missing_or_bad_prompt_rule\n"
        "- rationale\n"
        "- confidence\n"
        "Rules:\n"
        "1. Keep root_cause focused on the abstract decision mistake, not the topic.\n"
        "2. Keep secondary_causes to at most 3 short items.\n"
        "3. missing_or_bad_prompt_rule must describe the prompt boundary that is too weak, too broad, too narrow, or missing.\n"
        "4. Separate reusable protocol from current payload, one-off facts, files, entities, and troubleshooting details.\n"
        "5. For fp samples, explain why the request should NOT have been extracted.\n"
        "6. For fn samples, explain why the request SHOULD have been extracted.\n"
        "7. Each diagnosis must obey language consistency: use the requested dominant language consistently across root_cause, secondary_causes, missing_or_bad_prompt_rule, and rationale.\n"
        "8. Do not mix languages inside one diagnosis unless the input itself is irreducibly mixed.\n"
        "Return this schema exactly:\n"
        "{\n"
        '  "diagnoses": [\n'
        "    {\n"
        '      "sample_id": "...",\n'
        '      "error_side": "fp",\n'
        '      "language": "zh",\n'
        '      "root_cause": "...",\n'
        '      "secondary_causes": ["..."],\n'
        '      "missing_or_bad_prompt_rule": "...",\n'
        '      "rationale": "...",\n'
        '      "confidence": 0.8\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _diagnosis_user_payload(
    *,
    current_prompt: str,
    error_side: str,
    samples: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    items = []
    for sample in list(samples or []):
        payload = _sample_payload_for_diagnosis(sample)
        payload["error_side"] = str(error_side or "").strip() or "fp"
        items.append(payload)
    return {
        "error_side": str(error_side or "").strip() or "fp",
        "side_definition": (
            "fp means predicted yes but gold no; diagnose why this should NOT have been extracted."
            if str(error_side or "").strip() == "fp"
            else "fn means predicted no but gold yes; diagnose why this SHOULD have been extracted."
        ),
        "current_prompt": str(current_prompt or ""),
        "samples": items,
    }


def _diagnosis_retry_budget() -> int:
    return max(
        1,
        _safe_int(
            os.environ.get("AUTOSKILL_CODEX_REFLECTION_MAX_RETRIES")
            or os.environ.get("CODEX_REFLECTION_MAX_RETRIES")
            or "1",
            1,
        ),
    )


def _empty_sample_diagnosis(
    sample: Dict[str, Any],
    *,
    error_side: str,
    status: str,
) -> Dict[str, Any]:
    brief = _sample_brief(sample)
    language = _dominant_language_for_sample(sample)
    if language == "zh":
        root_cause = "诊断生成失败，当前样本尚未得到可用的错误归因。"
        gap = "需要重试 reflection diagnosis 生成后，才能确定缺失或过宽的 prompt 边界。"
        rationale = "当前条目仅保留样本元信息，不引入任何预设题材分类或关键词归因。"
    else:
        root_cause = "Diagnosis generation failed, so this sample does not yet have a usable error attribution."
        gap = "The reflection diagnosis step needs to be retried before we can identify the missing or overly broad prompt boundary."
        rationale = "This entry keeps only sample metadata and avoids any pre-baked topic classification or keyword-based attribution."
    return {
        "sample_id": str(brief.get("id") or ""),
        "error_side": str(error_side or "").strip() or "fp",
        "language": language,
        "root_cause": root_cause,
        "secondary_causes": [],
        "missing_or_bad_prompt_rule": gap,
        "rationale": rationale,
        "confidence": 0.0,
        "source_file": str(brief.get("source_file") or ""),
        "first_user": str(brief.get("first_user") or ""),
        "last_user": str(brief.get("last_user") or ""),
        "skill_names": list(brief.get("skill_names") or []),
        "diagnosis_status": str(status or "").strip() or "generation_failed",
    }


def _sanitize_diagnosis_item(
    item: Dict[str, Any],
    *,
    sample: Dict[str, Any],
    error_side: str,
    fallback_status: str = "generation_failed",
) -> Dict[str, Any]:
    fallback = _empty_sample_diagnosis(sample, error_side=error_side, status=fallback_status)
    root_cause = str(item.get("root_cause") or "").strip()
    secondary = _string_list(item.get("secondary_causes"))[:3]
    gap = str(item.get("missing_or_bad_prompt_rule") or "").strip()
    rationale = str(item.get("rationale") or "").strip()
    language = str(item.get("language") or "").strip().lower() or _dominant_language_for_sample(sample)
    confidence = _safe_float(item.get("confidence"), fallback.get("confidence"))
    out = dict(fallback)
    if root_cause:
        out["root_cause"] = root_cause
    if secondary:
        out["secondary_causes"] = secondary
    if gap:
        out["missing_or_bad_prompt_rule"] = gap
    if rationale:
        out["rationale"] = rationale
    out["language"] = language if language in {"zh", "en", "mixed"} else fallback.get("language", "mixed")
    out["confidence"] = max(0.0, min(1.0, float(confidence)))
    if root_cause and gap and rationale:
        out["diagnosis_status"] = "generated"
    return out


def diagnose_error_samples(
    *,
    current_prompt: str,
    samples: Sequence[Dict[str, Any]],
    error_side: str,
    llm: Any,
    batch_size: int = DIAGNOSIS_BATCH_SIZE,
) -> List[Dict[str, Any]]:
    sample_list = [dict(sample) for sample in list(samples or []) if isinstance(sample, dict)]
    if not sample_list:
        return []
    if llm is None:
        return [
            _empty_sample_diagnosis(sample, error_side=error_side, status="llm_unavailable")
            for sample in sample_list
        ]

    out: List[Dict[str, Any]] = []
    for start in range(0, len(sample_list), max(1, int(batch_size or DIAGNOSIS_BATCH_SIZE))):
        chunk = sample_list[start : start + max(1, int(batch_size or DIAGNOSIS_BATCH_SIZE))]
        payload = _diagnosis_user_payload(current_prompt=current_prompt, error_side=error_side, samples=chunk)
        mapped: Dict[str, Dict[str, Any]] = {}
        for _attempt in range(_diagnosis_retry_budget()):
            try:
                raw = llm.complete(
                    system=build_sample_diagnosis_system_prompt(),
                    user=json.dumps(payload, ensure_ascii=False),
                    temperature=0.0,
                )
                parsed = _extract_json_object(raw)
                raw_items = list(parsed.get("diagnoses") or [])
                mapped = {}
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    sid = str(item.get("sample_id") or "").strip()
                    if sid:
                        mapped[sid] = dict(item)
                if mapped:
                    break
            except Exception:
                mapped = {}
        for sample in chunk:
            sid = str(_sample_id(sample) or "")
            out.append(
                _sanitize_diagnosis_item(
                    mapped.get(sid) or {},
                    sample=sample,
                    error_side=error_side,
                    fallback_status="generation_failed",
                )
            )
    return out


def _diagnosis_embedding_text(item: Dict[str, Any]) -> str:
    secondary = "; ".join(_string_list(item.get("secondary_causes")))
    return "\n".join(
        [
            f"error_side={str(item.get('error_side') or '').strip()}",
            f"language={str(item.get('language') or '').strip()}",
            f"root_cause={str(item.get('root_cause') or '').strip()}",
            f"secondary_causes={secondary}",
            f"prompt_rule_gap={str(item.get('missing_or_bad_prompt_rule') or '').strip()}",
            f"rationale={str(item.get('rationale') or '').strip()}",
        ]
    ).strip()


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        af = float(a)
        bf = float(b)
        dot += af * bf
        norm_a += af * af
        norm_b += bf * bf
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return float(dot / math.sqrt(norm_a * norm_b))


def _average_link_similarity(cluster_a: Sequence[int], cluster_b: Sequence[int], sim_matrix: Sequence[Sequence[float]]) -> float:
    total = 0.0
    count = 0
    for idx_a in cluster_a:
        for idx_b in cluster_b:
            total += float(sim_matrix[idx_a][idx_b])
            count += 1
    if count <= 0:
        return 0.0
    return float(total / float(count))


def _agglomerative_cluster_indices(
    vectors: Sequence[Sequence[float]],
    *,
    threshold: float,
) -> List[List[int]]:
    n = len(list(vectors or []))
    if n <= 0:
        return []
    if n == 1:
        return [[0]]
    sim_matrix: List[List[float]] = [[0.0 for _ in range(n)] for _ in range(n)]
    for i in range(n):
        sim_matrix[i][i] = 1.0
        for j in range(i + 1, n):
            sim = _cosine_similarity(vectors[i], vectors[j])
            sim_matrix[i][j] = sim
            sim_matrix[j][i] = sim
    clusters: List[List[int]] = [[i] for i in range(n)]
    while True:
        best_pair: Optional[Tuple[int, int]] = None
        best_sim = float(threshold)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                sim = _average_link_similarity(clusters[i], clusters[j], sim_matrix)
                if sim > best_sim:
                    best_sim = sim
                    best_pair = (i, j)
        if best_pair is None:
            break
        left, right = best_pair
        merged = sorted(list(clusters[left]) + list(clusters[right]))
        clusters[left] = merged
        clusters.pop(right)
    clusters.sort(key=lambda idxs: (idxs[0], len(idxs)))
    return clusters


def build_reason_clusters(
    *,
    sample_diagnoses: Sequence[Dict[str, Any]],
    embeddings: Any = None,
    max_representatives_per_cluster: int = 6,
    similarity_threshold: float = DIAGNOSIS_CLUSTER_SIMILARITY_THRESHOLD,
) -> List[Dict[str, Any]]:
    items = [
        dict(item)
        for item in list(sample_diagnoses or [])
        if isinstance(item, dict) and str(item.get("diagnosis_status") or "generated").strip() == "generated"
    ]
    if not items:
        return []
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for item in items:
        key = (
            str(item.get("error_side") or "").strip() or "fp",
            str(item.get("language") or "").strip().lower() or "mixed",
        )
        grouped.setdefault(key, []).append(item)

    out: List[Dict[str, Any]] = []
    cluster_seq = 0
    for (error_side, language), group_items in grouped.items():
        cluster_groups: List[List[Dict[str, Any]]] = []
        vectors: List[List[float]] = []
        used_embedding = False
        if embeddings is not None and len(group_items) > 1:
            try:
                texts = [_diagnosis_embedding_text(item) for item in group_items]
                raw_vectors = embeddings.embed(texts)
                if isinstance(raw_vectors, list) and len(raw_vectors) == len(texts):
                    vectors = [[float(x) for x in list(vec or [])] for vec in raw_vectors]
                    if vectors and all(vec for vec in vectors):
                        used_embedding = True
            except Exception:
                used_embedding = False
        if used_embedding:
            idx_groups = _agglomerative_cluster_indices(vectors, threshold=float(similarity_threshold))
            cluster_groups = [[group_items[idx] for idx in idxs] for idxs in idx_groups]
        else:
            fallback_map: Dict[str, List[Dict[str, Any]]] = {}
            for item in group_items:
                key = _normalize_text_key(str(item.get("root_cause") or "")) or "__empty__"
                fallback_map.setdefault(key, []).append(item)
            cluster_groups = list(fallback_map.values())

        for members in cluster_groups:
            root_counter = Counter(
                [str(item.get("root_cause") or "").strip() for item in members if str(item.get("root_cause") or "").strip()]
            )
            gap_counter = Counter(
                [
                    str(item.get("missing_or_bad_prompt_rule") or "").strip()
                    for item in members
                    if str(item.get("missing_or_bad_prompt_rule") or "").strip()
                ]
            )
            secondary_counter = Counter()
            for item in members:
                secondary_counter.update([text for text in _string_list(item.get("secondary_causes")) if text])
            representative_cases: List[Dict[str, Any]] = []
            for item in sorted(members, key=lambda row: float(row.get("confidence", 0.0) or 0.0), reverse=True)[
                : max(1, int(max_representatives_per_cluster))
            ]:
                representative_cases.append(
                    {
                        "sample_id": str(item.get("sample_id") or ""),
                        "source_file": str(item.get("source_file") or ""),
                        "first_user": str(item.get("first_user") or ""),
                        "last_user": str(item.get("last_user") or ""),
                        "root_cause": str(item.get("root_cause") or ""),
                        "secondary_causes": list(item.get("secondary_causes") or []),
                        "missing_or_bad_prompt_rule": str(item.get("missing_or_bad_prompt_rule") or ""),
                        "rationale": str(item.get("rationale") or ""),
                        "confidence": float(item.get("confidence", 0.0) or 0.0),
                    }
                )
            cluster_seq += 1
            out.append(
                {
                    "cluster_id": f"{error_side}_{language}_{cluster_seq:03d}",
                    "name": root_counter.most_common(1)[0][0] if root_counter else "",
                    "error_side": error_side,
                    "language": language,
                    "sample_count": int(len(members)),
                    "root_cause_summary": root_counter.most_common(1)[0][0] if root_counter else "",
                    "secondary_cause_summaries": [text for text, _n in secondary_counter.most_common(3)],
                    "prompt_rule_gap_summary": gap_counter.most_common(1)[0][0] if gap_counter else "",
                    "member_ids": [str(item.get("sample_id") or "") for item in members if str(item.get("sample_id") or "").strip()],
                    "mean_confidence": round(
                        sum(float(item.get("confidence", 0.0) or 0.0) for item in members) / float(max(1, len(members))),
                        4,
                    ),
                    "cluster_method": "embedding_average_link" if used_embedding else "root_cause_text_fallback",
                    "representative_cases": representative_cases,
                }
            )
    out.sort(key=lambda item: (-_safe_int(item.get("sample_count"), 0), str(item.get("error_side") or ""), str(item.get("name") or "")))
    return out


def build_reason_clusters_from_samples(
    *,
    current_prompt: str,
    samples: Sequence[Dict[str, Any]],
    error_side: str,
    diagnosis_llm: Any = None,
    embeddings: Any = None,
    similarity_threshold: float = DIAGNOSIS_CLUSTER_SIMILARITY_THRESHOLD,
) -> List[Dict[str, Any]]:
    diagnoses = diagnose_error_samples(
        current_prompt=current_prompt,
        samples=samples,
        error_side=error_side,
        llm=diagnosis_llm,
    )
    return build_reason_clusters(
        sample_diagnoses=diagnoses,
        embeddings=embeddings,
        similarity_threshold=similarity_threshold,
    )


def build_reason_cluster_summaries_from_bucket(
    *,
    current_prompt: str,
    bucket: Dict[str, Any],
    error_side: str,
    diagnosis_llm: Any = None,
    embeddings: Any = None,
    max_items: int = 3,
) -> List[Dict[str, Any]]:
    if not isinstance(bucket, dict):
        return []
    samples = [dict(item) for item in list(bucket.get("samples") or []) if isinstance(item, dict)]
    if not samples:
        return []
    clusters = build_reason_clusters_from_samples(
        current_prompt=current_prompt,
        samples=samples,
        error_side=error_side,
        diagnosis_llm=diagnosis_llm,
        embeddings=embeddings,
    )
    out: List[Dict[str, Any]] = []
    for cluster in clusters[: max(1, int(max_items or 3))]:
        out.append(
            {
                "cluster_id": str(cluster.get("cluster_id") or ""),
                "summary": str(cluster.get("root_cause_summary") or cluster.get("name") or "").strip(),
                "count": _safe_int(cluster.get("sample_count"), 0),
                "prompt_rule_gap_summary": str(cluster.get("prompt_rule_gap_summary") or "").strip(),
            }
        )
    return out


def _default_target_section_for_legacy(field_name: str) -> str:
    return {
        "add_negative_rules": "negative_cases",
        "add_positive_rules": "positive_rules",
        "strengthen_rules": "generalization",
        "weaken_rules": "generalization",
        "delete_rules": "generalization",
    }.get(str(field_name or "").strip(), "generalization")


def _legacy_patch_payload_to_operations(src: Dict[str, Any]) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    for target, sources in PATCH_FIELD_MAP.items():
        items: List[str] = []
        for source in sources:
            items.extend(_string_list(src.get(source)))
        for item in _dedupe_keep_order(items):
            section = _default_target_section_for_legacy(target)
            if target == "delete_rules":
                operations.append(
                    {
                        "op": "delete_rule",
                        "target_section": section,
                        "anchor_text": item,
                        "position": "replace",
                        "content": "",
                        "rationale": "",
                        "priority": 0.5,
                    }
                )
            elif target in {"strengthen_rules", "weaken_rules"}:
                operations.append(
                    {
                        "op": "rewrite_rule",
                        "target_section": section,
                        "anchor_text": "",
                        "position": "append",
                        "content": item,
                        "rationale": "",
                        "priority": 0.6,
                    }
                )
            else:
                operations.append(
                    {
                        "op": "insert_rule",
                        "target_section": section,
                        "anchor_text": "",
                        "position": "append",
                        "content": item,
                        "rationale": "",
                        "priority": 0.7,
                    }
                )
    return operations


def _normalize_operation_item(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    op_name = str(value.get("op") or "").strip()
    if op_name not in SUPPORTED_PATCH_OPERATIONS:
        return None
    target_section = str(value.get("target_section") or "").strip()
    if target_section and target_section not in SUPPORTED_TARGET_SECTIONS:
        target_section = ""
    position = str(value.get("position") or "").strip() or "append"
    if position not in SUPPORTED_OPERATION_POSITIONS:
        position = "append"
    anchor_text = str(value.get("anchor_text") or "").strip()
    content = str(value.get("content") or "").strip()
    rationale = str(value.get("rationale") or "").strip()
    if op_name in {"insert_rule", "rewrite_rule", "move_rule"} and not content:
        return None
    if op_name in {"rewrite_rule", "delete_rule", "move_rule"} and not anchor_text:
        if op_name != "rewrite_rule" or position != "append":
            return None
    return {
        "op": op_name,
        "target_section": target_section,
        "anchor_text": anchor_text,
        "position": position,
        "content": content,
        "rationale": rationale,
        "priority": _safe_float(value.get("priority"), 0.0),
    }


def _normalize_operation_list(value: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen = set()
    if not isinstance(value, list):
        return normalized
    for item in value:
        op = _normalize_operation_item(item)
        if not op:
            continue
        key = (
            str(op.get("op") or ""),
            str(op.get("target_section") or ""),
            str(op.get("anchor_text") or ""),
            str(op.get("position") or ""),
            str(op.get("content") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(op)
    return normalized


def build_reflection_system_prompt() -> str:
    return (
        "You are a prompt reflection and rewrite engine for AutoSkill offline conversation extraction.\n"
        "Your job is to analyze current extraction errors and produce a SMALL, TRACEABLE PATCH for the specific-mode extraction prompt.\n"
        "Output ONLY strict JSON parseable by json.loads.\n"
        "You are not labeling examples one by one. You are diagnosing why the current prompt fails and deriving the smallest reusable prompt edits that correct recurring error structure.\n"
        "You must analyze both error directions:\n"
        "- yn: predicted yes but gold no. Explain why these SHOULD NOT be extracted.\n"
        "- ny: predicted no but gold yes. Explain why these SHOULD be extracted.\n"
        "When reflection_input includes active_vs_reference_delta, inspect fixed_fp/new_fp/fixed_fn/new_fn before proposing patches.\n"
        "When reflection_input includes sample_diagnoses, treat them as first-pass structured analyses of per-sample failure reasons, but still verify them against representative cases.\n"
        "When reflection_input includes error_clusters, reason at the cluster level first, then use representative cases only as evidence.\n"
        "If diagnosis-derived clusters are present, use root_cause_summary and prompt_rule_gap_summary to identify reusable prompt boundaries that need to change.\n"
        "When reflection_input includes candidate_patch_lessons or anti_regression_memory, treat them as anti-regression memory: learn from all failed candidate attempts, preserve their useful gains, and avoid repeating already-proven harmful moves.\n"
        "A good patch should preserve fixed errors while directly addressing new regressions; do not propose a rule that fixes one cluster by predictably breaking another.\n"
        "For every patch, consider which cluster it targets, which opposite-direction cluster it may hurt, and how to narrow it to avoid regressions.\n"
        "You must prioritize reducing false positives, but you must not ignore systematic false negatives.\n"
        "Think in three cognitive stages even though you return one JSON object: first summarize recurring diagnosis patterns, then form patch_strategy over all relevant clusters, then emit operations consistent with that strategy.\n"
        "Use the prompt as a reusable decision policy, not as a bag of ad hoc exceptions.\n"
        "All edits must be traceable to the observed error patterns.\n"
        "Do not invent product rules unrelated to the provided data.\n"
        "Do not rewrite the whole prompt. Do not replace the prompt skeleton.\n"
        "Return only local patch suggestions that can be merged into the existing prompt.\n"
        "Prefer small, conservative edits over aggressive rewrites.\n"
        "Prefer boundary sharpening over topic-specific patching.\n"
        "Derive rules from recurring error structure, not from single examples or surface domains alone.\n"
        "Always look for the smallest abstraction that explains multiple samples.\n"
        "Before proposing any patch, separate reusable execution requirements from current-case facts, payload, artifact details, environment details, and troubleshooting context.\n"
        "A good patch should still make sense after removing current entities, files, projects, products, datasets, incidents, and one-off task details.\n"
        "If a candidate rule collapses after de-identification, it is not a prompt rule and should not be emitted.\n"
        "When analyzing yn false positives, explicitly ask whether the model confused a current-case request, current-case consultation, or current-case problem description with a reusable protocol.\n"
        "When analyzing ny false negatives, explicitly ask whether the user actually specified a stable schema, workflow, rubric, template, persistent preference, or repeatable procedure that should survive beyond the current instance.\n"
        "Do not convert a broad topical pattern into a patch unless the real failure is truly topic-level. Prefer rules about task boundary, reusability, provenance, de-identification, repeat-use value, or durable protocol detection.\n"
        "Do not overfit to wording such as one particular app, file type, algorithm, domain, or business case unless the shared failure mode is genuinely about that class.\n"
        "Preserve diagnosis language consistency when you summarize recurring failure families. Do not mix languages inside one concise cause statement unless the supporting samples are irreducibly mixed.\n"
        "For each proposed operation, mentally test three questions before emitting it:\n"
        "1. Does it cover multiple observed errors rather than a single anecdote?\n"
        "2. Would it still be correct after removing current-case facts?\n"
        "3. Is this really missing from the prompt, or is an existing rule merely too weak, too ambiguous, or in the wrong place?\n"
        "If the issue is that an existing rule is too weak or too ambiguous, prefer rewrite_rule over insert_rule.\n"
        "Use delete_rule only when an existing clause is clearly over-broad, misleading, or harmful.\n"
        "Use move_rule only when content belongs in another section; do not use it as a substitute for better reasoning.\n"
        "Patch rationales should mention the abstract error family being corrected, not just repeat one sample.\n"
        "Use operation-based patch edits instead of legacy must_add/must_delete lists.\n"
        "Supported target_section values are: core_principle, evidence_scope, positive_rules, negative_rules, negative_cases, generalization, no_invention, output_construction, confidence_guidance, final_emission_check, language_consistency, json_validity.\n"
        "Supported op values are: insert_rule, rewrite_rule, delete_rule, move_rule.\n"
        "Use insert_rule for adding a new rule, rewrite_rule for strengthening or softening an existing rule, delete_rule for removing an over-broad rule, and move_rule only when a rule belongs in another section.\n"
        "When rewriting or deleting, include the shortest reliable anchor_text that identifies the current rule to change.\n"
        "For rewrite_rule, delete_rule, and move_rule, anchor_text MUST be copied verbatim from the current_prompt text, not paraphrased or invented.\n"
        "For rewrite_rule, delete_rule, and move_rule, target_section MUST be the section where that exact anchor_text appears in current_prompt.\n"
        "If you cannot find an exact current_prompt anchor in the intended section, do not emit that rewrite/delete/move operation; use a narrower insert_rule instead.\n"
        "When replacing a multi-line rule, preserve readable Markdown formatting: put sub-points on separate lines as indented '- ' bullets instead of flattening them into one sentence.\n"
        "Use position=append for pure additions, before_anchor or after_anchor for local insertion, and replace only when the operation directly replaces the anchored rule.\n"
        "Anchor text should be chosen from the current prompt, not invented. If you cannot identify a reliable anchor, either use append or choose a more abstract patch.\n"
        "Good reflections often discover failures such as:\n"
        "- the prompt lacks a boundary that distinguishes durable protocol from current-case help\n"
        "- the prompt has the right concept but phrases it too weakly\n"
        "- the prompt allows a looser interpretation than intended\n"
        "- the prompt under-specifies what counts as reusable evidence\n"
        "- the prompt fails to separate current payload from reusable method\n"
        "Bad reflections usually look like:\n"
        "- adding one new exception per sample topic\n"
        "- restating a sample in prompt language without abstraction\n"
        "- proposing a rule that only makes sense for the current artifact or domain\n"
        "- compensating for weak reasoning by emitting many narrow insertions\n"
        "Return this schema exactly:\n"
        "{\n"
        '  "yn_root_causes": ["..."],\n'
        '  "ny_root_causes": ["..."],\n'
        '  "fp_patterns": ["..."],\n'
        '  "fn_patterns": ["..."],\n'
        '  "patch_strategy": {\n'
        '    "language": "zh",\n'
        '    "global_goal": "...",\n'
        '    "cluster_ranking": [\n'
        '      {"cluster_id": "...", "role": "primary_target", "summary": "...", "why_now": "..."}\n'
        "    ],\n"
        '    "primary_targets": ["..."],\n'
        '    "secondary_targets": ["..."],\n'
        '    "preserve_clusters": ["..."],\n'
        '    "preferred_actions": [\n'
        '      {"type": "rewrite_rule", "target_section": "negative_cases", "intent": "..."}\n'
        "    ],\n"
        '    "avoid_actions": [\n'
        '      {"code": "...", "text": "..."}\n'
        "    ],\n"
        '    "tradeoff_expectation": "...",\n'
        '    "success_criteria": ["..."],\n'
        '    "one_paragraph_strategy": "..."\n'
        "  },\n"
        '  "operations": [\n'
        "    {\n"
        '      "op": "insert_rule",\n'
        '      "target_section": "negative_cases",\n'
        '      "anchor_text": "",\n'
        '      "position": "append",\n'
        '      "content": "Do not extract from generic coding requests unless the user defines a reusable protocol.",\n'
        '      "rationale": "Reduces false positives on one-off coding help.",\n'
        '      "priority": 0.9\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def build_reflection_input(
    *,
    base_prompt: str,
    current_prompt: str,
    current_patch_set: Dict[str, Any],
    active_eval: Dict[str, Any],
    history_rows: List[Dict[str, Any]],
    reference_eval: Optional[Dict[str, Any]] = None,
    recent_candidate_deltas: Optional[List[Dict[str, Any]]] = None,
    candidate_patch_lessons: Optional[List[Dict[str, Any]]] = None,
    anti_regression_memory: Optional[Dict[str, Any]] = None,
    diagnosis_llm: Any = None,
    embeddings: Any = None,
) -> Dict[str, Any]:
    active_delta = (
        build_error_delta(reference_eval=dict(reference_eval or {}), current_eval=active_eval)
        if isinstance(reference_eval, dict) and reference_eval
        else None
    )
    yn_samples = list(active_eval.get("yn_samples") or [])
    ny_samples = list(active_eval.get("ny_samples") or [])
    sample_diagnoses: List[Dict[str, Any]] = []
    sample_diagnoses.extend(
        diagnose_error_samples(
            current_prompt=current_prompt,
            samples=yn_samples,
            error_side="fp",
            llm=diagnosis_llm,
        )
    )
    sample_diagnoses.extend(
        diagnose_error_samples(
            current_prompt=current_prompt,
            samples=ny_samples,
            error_side="fn",
            llm=diagnosis_llm,
        )
    )
    diagnosis_clusters = build_reason_clusters(sample_diagnoses=sample_diagnoses, embeddings=embeddings)
    payload = {
        "objective": "precision-first",
        "base_prompt": base_prompt,
        "current_prompt": current_prompt,
        "current_active_patch_set": normalize_patch_payload(current_patch_set),
        "current_metrics": dict(active_eval.get("metrics") or {}),
        "current_prompt_version": str(active_eval.get("prompt_version") or ""),
        "yn_samples": yn_samples,
        "ny_samples": ny_samples,
        "sample_diagnoses": sample_diagnoses,
        "error_clusters": diagnosis_clusters,
        "error_cluster_method": {
            "name": "embedding_average_link" if diagnosis_clusters and embeddings is not None else "root_cause_text_fallback",
            "similarity_threshold": float(DIAGNOSIS_CLUSTER_SIMILARITY_THRESHOLD),
            "diagnosis_mode": "llm_generated" if diagnosis_llm is not None else "llm_unavailable",
        },
        "candidate_patch_lessons": list(candidate_patch_lessons or []),
        "anti_regression_memory": dict(anti_regression_memory or {}),
        "history_tail": history_rows[-5:],
        "instructions": {
            "priority": "Analyze yn first, but fully analyze ny as well.",
            "edit_policy": "Output patch suggestions only. Do not rewrite the full prompt. Keep changes local and conservative.",
            "must_answer": [
                "Why each yn sample should not be extracted.",
                "Why each ny sample should be extracted.",
                "Which error clusters explain multiple samples.",
                "What failed candidate attempts already taught us not to repeat.",
                "What patch strategy should guide operations before writing them.",
                "Which fixed errors must be preserved and which new regressions must be avoided.",
                "Which negative rules are missing.",
                "Which positive rules are too weak or absent.",
                "Which current prompt clauses are too broad, too narrow, or ambiguous.",
            ],
        },
    }
    if active_delta is not None:
        payload["active_vs_reference_delta"] = active_delta
    if recent_candidate_deltas:
        payload["recent_candidate_deltas"] = list(recent_candidate_deltas)
    return payload


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty reflection output")
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        obj = json.loads(raw[start : end + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("reflection output is not valid JSON object")


def normalize_patch_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = dict(payload or {})
    out = {
        "yn_root_causes": _string_list(src.get("yn_root_causes")),
        "ny_root_causes": _string_list(src.get("ny_root_causes")),
        "fp_patterns": _string_list(src.get("fp_patterns")),
        "fn_patterns": _string_list(src.get("fn_patterns")),
        "patch_strategy": _normalize_patch_strategy(dict(src.get("patch_strategy") or {}))
        if isinstance(src.get("patch_strategy"), dict)
        else _normalize_patch_strategy({}),
    }
    if "accepted_rounds" in src:
        out["accepted_rounds"] = [int(x) for x in list(src.get("accepted_rounds") or []) if str(x).strip()]
    operations = _normalize_operation_list(src.get("operations"))
    if not operations:
        patch_src = dict(src.get("patch") or {}) if isinstance(src.get("patch"), dict) else src
        operations = _normalize_operation_list(patch_src.get("operations"))
    if not operations:
        operations = _normalize_operation_list(_legacy_patch_payload_to_operations(src))
    if not operations and isinstance(src.get("patch"), dict):
        operations = _normalize_operation_list(_legacy_patch_payload_to_operations(dict(src.get("patch") or {})))
    out["operations"] = operations
    return out


def load_reflection_output(path: Path) -> Dict[str, Any]:
    payload = _safe_load_json(path)
    if not payload:
        raise ValueError(f"reflection output missing or invalid: {path}")
    return normalize_patch_payload(payload)


def build_reflection_llm(args: argparse.Namespace):
    reflection_provider = str(getattr(args, "reflection_provider", "") or "").strip()
    reflection_model = str(getattr(args, "reflection_model", "") or "").strip()
    reflection_base_url = str(getattr(args, "reflection_base_url", "") or "").strip()
    reflection_api_key = str(getattr(args, "reflection_api_key", "") or "").strip()
    reflection_auth_mode = str(getattr(args, "reflection_auth_mode", "") or "").strip()
    reflection_retry_budget = int(
        getattr(args, "codex_reflection_max_retries", 0) or getattr(args, "codex_max_retries", 0) or 0
    )
    if not any(
        [
            reflection_provider,
            reflection_model,
            reflection_base_url,
            reflection_api_key,
            reflection_auth_mode,
        ]
    ):
        cfg = _build_llm_config(args)
        if reflection_retry_budget > 0:
            cfg["codex_max_retries"] = max(1, int(reflection_retry_budget))
    else:
        cfg = build_conversation_llm_config(
            provider=(reflection_provider or getattr(args, "llm_provider", "")),
            model=(reflection_model or str(getattr(args, "llm_model", "") or "").strip() or None),
            base_url=(reflection_base_url or getattr(args, "llm_base_url", "")),
            api_key=(reflection_api_key or getattr(args, "llm_api_key", "")),
            auth_mode=(reflection_auth_mode or getattr(args, "auth_mode", "")),
            codex_cli_path=getattr(args, "codex_cli_path", ""),
            codex_exec_cwd=getattr(args, "codex_exec_cwd", ""),
            codex_timeout_s=getattr(args, "codex_timeout_s", 0),
            codex_max_retries=reflection_retry_budget,
            codex_full_auto=getattr(args, "codex_full_auto", "1"),
            codex_preserve_openai_env=getattr(args, "codex_preserve_openai_env", "0"),
            where="self_evolve:build_reflection_llm",
        )
    return build_llm(cfg)


def build_reflection_embeddings(args: argparse.Namespace):
    try:
        cfg = _build_embeddings_config(args)
    except Exception:
        cfg = {"provider": "hashing", "dims": 256}
    if str(cfg.get("provider") or "").strip().lower() == "none":
        return None
    try:
        return build_embeddings(cfg)
    except Exception:
        return build_embeddings({"provider": "hashing", "dims": 256})


def run_reflection(
    *,
    mode: str,
    llm: Any,
    reflection_input: Dict[str, Any],
    temperature: float,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    normalized_mode = normalize_reflection_mode(mode)
    if output_path is not None and output_path.is_file():
        try:
            return load_reflection_output(output_path)
        except Exception:
            if normalized_mode == "codex":
                raise ReflectionPendingError(
                    "codex reflection output exists but is invalid; rerun external reflection and resume. "
                    f"expected_path={output_path}"
                )
            raise
    if normalized_mode == "codex":
        target = str(output_path) if output_path is not None else "<reflection_output.json>"
        raise ReflectionPendingError(
            "codex reflection pending; write a valid reflection_output.json and resume. "
            f"expected_path={target}"
        )
    if llm is None:
        raise ValueError("llm reflection mode requires a configured reflection llm")
    raw = llm.complete(
        system=build_reflection_system_prompt(),
        user=json.dumps(reflection_input, ensure_ascii=False),
        temperature=float(temperature),
    )
    normalized = normalize_patch_payload(_extract_json_object(raw))
    normalized["_raw_text"] = raw
    if output_path is not None:
        _json_dump(output_path, normalized)
    return normalized


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Standalone reflection runner for self-evolve.")
    p.add_argument("--input-json", required=True)
    p.add_argument("--output-json", required=True)
    p.add_argument("--reflection-mode", default="llm", help="llm|codex")
    p.add_argument("--llm-provider", default=os.getenv("AUTOSKILL_LLM_PROVIDER", ""))
    p.add_argument("--llm-model", default=os.getenv("AUTOSKILL_LLM_MODEL", ""))
    p.add_argument("--llm-base-url", default=os.getenv("AUTOSKILL_LLM_BASE_URL", ""))
    p.add_argument("--llm-api-key", default=os.getenv("AUTOSKILL_LLM_API_KEY", ""))
    p.add_argument("--auth-mode", default=os.getenv("AUTOSKILL_LLM_AUTH_MODE", ""))
    p.add_argument("--reflection-provider", default="")
    p.add_argument("--reflection-model", default="")
    p.add_argument("--reflection-base-url", default="")
    p.add_argument("--reflection-api-key", default="")
    p.add_argument("--reflection-auth-mode", default="")
    p.add_argument("--reflection-temperature", type=float, default=0.2)
    add_codex_llm_args(p)
    return p


def main() -> None:
    args = build_parser().parse_args()
    mode = normalize_reflection_mode(args.reflection_mode)
    input_path = Path(str(args.input_json)).expanduser().resolve()
    output_path = Path(str(args.output_json)).expanduser().resolve()
    payload = _safe_load_json(input_path)
    if not payload:
        raise SystemExit(f"input-json is not a valid JSON object: {input_path}")
    llm = build_reflection_llm(args) if mode == "llm" else None
    try:
        result = run_reflection(
            mode=mode,
            llm=llm,
            reflection_input=payload,
            temperature=float(args.reflection_temperature),
            output_path=output_path,
        )
    except ReflectionPendingError as exc:
        raise SystemExit(str(exc))
    _json_dump(output_path, result)
    print(output_path)


if __name__ == "__main__":
    main()
