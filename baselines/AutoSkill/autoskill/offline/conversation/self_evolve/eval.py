"""
Run standalone evals and host shared self-evolve evaluation helpers.

python -m autoskill.offline.conversation.self_evolve.eval \
  --run-root log/self-evolve/2026-0408-1307/Reflection \
  --prompt-source base \
  --dataset eval \
  --llm-provider codex \
  --codex-auto-backend llm

python -m autoskill.offline.conversation.self_evolve.eval \
  --run-root log/self-evolve/2026-0408-1307/Reflection \
  --prompt-source round_candidate \
  --round 3 \
  --dataset train
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm.auto import tqdm

from ..extract import _build_sdk_from_args, _offline_extract_channel, run_extract_job
from ..file_loader import load_openai_units
from ..prompts import ACTIVE_SPECIFIC_PROMPT_ENV
from .artifacts import (
    ROUND_LOG_ARTIFACT_SECTIONS,
    _ensure_grouped_round_layout,
    _ensure_log_round_layout,
    _json_dump,
    _load_json,
    _load_jsonl,
    _log_round_artifact,
    _norm_path,
    _normalize_manifest_log_paths,
    _round_store_path,
    _round_tag,
    _safe_read_text,
    _write_jsonl,
)
from ..llm_backend import add_codex_llm_args, is_codex_provider


_PROXY_DISABLE_SENTINEL = "AUTOSKILL_DISABLE_ENV_PROXY"
_PROXY_ENV_KEYS: Tuple[str, ...] = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "no_proxy",
    "NO_PROXY",
)


def _basename(path: str) -> str:
    return Path(str(path or "")).name


def _load_meta(meta_info_jsonl: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    rows = _load_jsonl(meta_info_jsonl)
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        source_file = str(row.get("source_file") or "").strip()
        name = _basename(source_file)
        if not name:
            raise SystemExit(f"meta_info row missing source_file: {row}")
        if name in by_name:
            raise SystemExit(f"Duplicate basename in meta_info: {name}")
        by_name[name] = row
    return rows, by_name


def _limit_meta_rows(meta_rows: List[Dict[str, Any]], *, max_samples: int) -> List[Dict[str, Any]]:
    limit = max(0, int(max_samples or 0))
    if limit <= 0 or limit >= len(meta_rows):
        return list(meta_rows)
    return list(meta_rows[:limit])


def _resolve_source_file_path(source_file: str, *, meta_info_jsonl: Optional[Path] = None) -> str:
    raw = str(source_file or "").strip()
    if not raw:
        return ""

    p = Path(raw).expanduser()
    candidates: List[Path] = []
    workspace_root = Path(__file__).resolve().parents[4]
    package_root = workspace_root / "autoskill"
    if p.is_absolute():
        candidates.append(p)
    else:
        cwd = Path.cwd()
        candidates.extend([cwd / p, workspace_root / p, package_root / p])
        first_part = str(p.parts[0] if p.parts else "")
        if first_part == workspace_root.name and len(p.parts) >= 2:
            trimmed = Path(*p.parts[1:])
            candidates.extend([cwd / trimmed, workspace_root / trimmed, package_root / trimmed])
        if first_part == package_root.name and len(p.parts) >= 2:
            trimmed = Path(*p.parts[1:])
            candidates.extend([cwd / trimmed, package_root / trimmed, workspace_root / trimmed])
        if meta_info_jsonl is not None:
            meta_dir = Path(meta_info_jsonl).expanduser().resolve().parent
            candidates.extend([meta_dir / p, meta_dir.parent / p])

    seen = set()
    for cand in candidates:
        try:
            resolved = cand.expanduser().resolve()
        except Exception:
            resolved = cand
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists():
            return key

    basename = p.name
    if basename:
        search_roots: List[Path] = []
        if meta_info_jsonl is not None:
            meta_dir = Path(meta_info_jsonl).expanduser().resolve().parent
            search_roots.extend([meta_dir, meta_dir.parent / "train", meta_dir.parent / "eval"])
        search_roots.extend(
            [
                workspace_root / "data" / "train",
                workspace_root / "data" / "eval",
            ]
        )
        search_seen = set()
        found: List[Path] = []
        for root in search_roots:
            root_key = str(root)
            if root_key in search_seen or not root.is_dir():
                continue
            search_seen.add(root_key)
            candidate = root / basename
            if candidate.is_file():
                found.append(candidate.resolve())
        if len(found) == 1:
            return str(found[0])
    return str(candidates[0].expanduser().resolve()) if candidates else raw


def _subset_dataset_view_root(*, log_root: Path, dataset_name: str, sample_count: int) -> Path:
    safe_name = str(dataset_name or "dataset").strip().replace("/", "_")
    return log_root / "_datasets" / f"{safe_name}_first_{int(sample_count):05d}"


def _materialize_eval_subset_root(
    *,
    eval_root: Path,
    meta_rows: List[Dict[str, Any]],
    meta_info_jsonl: Path,
    subset_root: Path,
) -> Path:
    expected_files: List[Tuple[str, Path]] = []
    for row in meta_rows:
        source_file = str(row.get("source_file") or "").strip()
        resolved_source = _resolve_source_file_path(source_file, meta_info_jsonl=meta_info_jsonl)
        if not resolved_source:
            raise SystemExit(f"Unable to resolve source_file for train subset: {source_file}")
        src = Path(resolved_source).expanduser().resolve()
        if not src.is_file():
            raise SystemExit(f"Train subset source_file is not a file: {src}")
        expected_files.append((source_file, src))

    manifest_path = subset_root / "_subset_manifest.json"
    subset_root.mkdir(parents=True, exist_ok=True)
    existing_manifest = _load_json(manifest_path)
    expected_names = [src.name for _source_file, src in expected_files]
    if (
        existing_manifest
        and int(existing_manifest.get("sample_count", 0) or 0) == len(expected_files)
        and list(existing_manifest.get("file_names") or []) == expected_names
        and all((subset_root / name).exists() or (subset_root / name).is_symlink() for name in expected_names)
    ):
        return subset_root

    for child in subset_root.iterdir():
        if child.name == "_subset_manifest.json":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()

    manifest_rows: List[Dict[str, Any]] = []
    for source_file, src in expected_files:
        dst = subset_root / src.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        try:
            os.symlink(str(src), str(dst))
        except OSError:
            try:
                os.link(str(src), str(dst))
            except OSError:
                shutil.copy2(str(src), str(dst))
        manifest_rows.append(
            {
                "source_file": source_file,
                "resolved_source_file": str(src),
                "subset_file": str(dst),
            }
        )
    _json_dump(
        manifest_path,
        {
            "eval_root": str(eval_root),
            "meta_info_jsonl": str(meta_info_jsonl),
            "sample_count": len(meta_rows),
            "file_names": expected_names,
            "files": manifest_rows,
        },
    )
    return subset_root


def _load_conversation_messages(
    source_file: str,
    *,
    conversation_index: int = 0,
    meta_info_jsonl: Optional[Path] = None,
) -> List[Dict[str, str]]:
    resolved_source = _resolve_source_file_path(source_file, meta_info_jsonl=meta_info_jsonl)
    units, _abs = load_openai_units(file_path=str(resolved_source))
    if not units:
        return []
    idx = max(0, int(conversation_index or 0))
    if idx >= len(units):
        idx = 0
    return list(units[idx].get("messages") or [])


def _derive_metrics(*, yy: int, nn: int, yn: int, ny: int) -> Dict[str, Any]:
    eval_n = yy + nn + yn + ny
    acc = (yy + nn) / eval_n if eval_n else 0.0
    precision = yy / (yy + yn) if (yy + yn) else 0.0
    recall = yy / (yy + ny) if (yy + ny) else 0.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    pred_yes = yy + yn
    pred_no = nn + ny
    gold_yes = yy + ny
    gold_no = nn + yn
    return {
        "eval_n": eval_n,
        "accuracy": acc,
        "precision_yes": precision,
        "recall_yes": recall,
        "f1_yes": f1,
        "yy": yy,
        "nn": nn,
        "yn": yn,
        "ny": ny,
        "pred_yes_rate": (pred_yes / eval_n if eval_n else 0.0),
        "pred_no_rate": (pred_no / eval_n if eval_n else 0.0),
        "gold_yes_rate": (gold_yes / eval_n if eval_n else 0.0),
        "gold_no_rate": (gold_no / eval_n if eval_n else 0.0),
        "fp_rate_among_pred_yes": (yn / pred_yes if pred_yes else 0.0),
        "fn_rate_among_gold_yes": (ny / gold_yes if gold_yes else 0.0),
    }


def _build_error_sample(
    *,
    meta_row: Dict[str, Any],
    pred_row: Dict[str, Any],
    analysis_priority: str,
    meta_info_jsonl: Optional[Path] = None,
) -> Dict[str, Any]:
    source_file = str(meta_row.get("source_file") or pred_row.get("source_file") or "").strip()
    conv_index = int(pred_row.get("conversation_index", 0) or 0)
    resolved_source = _resolve_source_file_path(source_file, meta_info_jsonl=meta_info_jsonl)
    messages = _load_conversation_messages(
        resolved_source,
        conversation_index=conv_index,
        meta_info_jsonl=meta_info_jsonl,
    )
    return {
        "id": str(meta_row.get("id") or ""),
        "source_file": resolved_source,
        "file_name": str(meta_row.get("file_name") or _basename(source_file)),
        "gold_label": str(meta_row.get("label") or "").strip().lower(),
        "pred_label": str(pred_row.get("extracted") or "").strip().lower(),
        "conversation_index": conv_index,
        "messages": messages,
        "skills": list(pred_row.get("skills") or []),
        "candidate_count": int(pred_row.get("candidate_count", 0) or 0),
        "analysis_priority": analysis_priority,
        "note": str(meta_row.get("note") or ""),
        "prompt_version": str(pred_row.get("prompt_version") or ""),
        "error_cluster": None,
    }


def _evaluate_trace_rows(
    *,
    trace_rows: List[Dict[str, Any]],
    meta_rows: List[Dict[str, Any]],
    meta_by_name: Dict[str, Dict[str, Any]],
    prompt_version: str,
    meta_info_jsonl: Optional[Path] = None,
) -> Dict[str, Any]:
    preds_by_name: Dict[str, Dict[str, Any]] = {}
    extra_predictions: List[str] = []
    for row in trace_rows:
        if str(row.get("type") or "").strip() != "conversation":
            continue
        name = _basename(str(row.get("source_file") or row.get("file_name") or ""))
        if not name:
            continue
        preds_by_name[name] = row
        if name not in meta_by_name:
            extra_predictions.append(name)

    yy = nn = yn = ny = 0
    matched = 0
    missing_predictions: List[str] = []
    yn_samples: List[Dict[str, Any]] = []
    ny_samples: List[Dict[str, Any]] = []
    invalid_predictions: List[str] = []

    for meta_row in meta_rows:
        name = _basename(str(meta_row.get("source_file") or ""))
        pred = preds_by_name.get(name)
        if pred is None:
            missing_predictions.append(name)
            continue
        gold = str(meta_row.get("label") or "").strip().lower()
        pred_label = str(pred.get("extracted") or "").strip().lower()
        if pred_label not in {"yes", "no"}:
            invalid_predictions.append(name)
            continue
        matched += 1
        if pred_label == "yes" and gold == "yes":
            yy += 1
        elif pred_label == "no" and gold == "no":
            nn += 1
        elif pred_label == "yes" and gold == "no":
            yn += 1
            yn_samples.append(
                _build_error_sample(
                    meta_row=meta_row,
                    pred_row=pred,
                    analysis_priority="primary",
                    meta_info_jsonl=meta_info_jsonl,
                )
            )
        elif pred_label == "no" and gold == "yes":
            ny += 1
            ny_samples.append(
                _build_error_sample(
                    meta_row=meta_row,
                    pred_row=pred,
                    analysis_priority="secondary",
                    meta_info_jsonl=meta_info_jsonl,
                )
            )

    metrics = _derive_metrics(yy=yy, nn=nn, yn=yn, ny=ny)
    metrics["coverage"] = matched
    metrics["gold_total"] = len(meta_rows)
    metrics["trace_total"] = len(preds_by_name)
    metrics["missing_prediction_count"] = len(missing_predictions)
    metrics["invalid_prediction_count"] = len(invalid_predictions)
    metrics["extra_prediction_count"] = len(extra_predictions)
    metrics["trace_error_count"] = sum(1 for row in trace_rows if str(row.get("status") or "") == "error")
    return {
        "prompt_version": prompt_version,
        "metrics": metrics,
        "missing_predictions": missing_predictions,
        "invalid_predictions": invalid_predictions,
        "extra_predictions": extra_predictions,
        "yn_samples": yn_samples,
        "ny_samples": ny_samples,
    }


def _display_path(path: Path | str) -> str:
    p = Path(str(path or "")).expanduser()
    try:
        resolved = p.resolve()
    except Exception:
        resolved = p
    cwd = Path.cwd().resolve()
    try:
        return str(resolved.relative_to(cwd))
    except Exception:
        return str(resolved)


def _print_header(title: str, *, blank_before: bool = True) -> None:
    if blank_before:
        print("", flush=True)
    print(f"== {str(title).strip()} ==", flush=True)


def _print_detail(message: str) -> None:
    print(f"  {str(message).strip()}", flush=True)


class _RoundProgress:
    """Render one tqdm progress bar for one evaluation round."""

    def __init__(self, *, round_index: int, total: int, enabled: bool, initial: int = 0, desc: str = "") -> None:
        self.round_index = int(round_index)
        self.total = max(0, int(total or 0))
        self.initial = max(0, int(initial or 0))
        self.enabled = bool(enabled)
        self._bar = None
        if self.enabled:
            label = str(desc or "").strip() or f"round {self.round_index:03d}"
            self._bar = tqdm(
                total=(self.total or None),
                desc=label,
                unit="conv",
                file=sys.stdout,
                dynamic_ncols=True,
                leave=True,
            )
            if self.initial > 0:
                self._bar.update(min(self.initial, self.total) if self.total else self.initial)

    def update(self, evt: Dict[str, Any]) -> None:
        if self._bar is None:
            return
        self._bar.update(1)
        status = str(evt.get("status") or "ok")
        candidate_count = int(evt.get("candidate_count", 0) or 0)
        file_name = str(evt.get("file_name") or "")
        postfix = {"status": status, "cand": candidate_count}
        if file_name:
            postfix["file"] = file_name[:32]
        self._bar.set_postfix(postfix, refresh=False)

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()


def _print_round_metrics(
    *,
    round_index: int,
    metrics: Dict[str, Any],
    promoted: Optional[bool] = None,
    promotion_reason: str = "",
    label: str = "eval",
) -> None:
    suffix = ""
    if promoted is not None:
        suffix = f" promoted={1 if promoted else 0}"
        if promotion_reason:
            suffix += f" reason={promotion_reason}"
    print("", flush=True)
    print(
        "[round-summary] "
        f"round={int(round_index):03d} "
        f"label={label} "
        f"coverage={int(metrics.get('coverage', 0) or 0)}/{int(metrics.get('gold_total', 0) or 0)} "
        f"acc={float(metrics.get('accuracy', 0.0) or 0.0):.4f} "
        f"p={float(metrics.get('precision_yes', 0.0) or 0.0):.4f} "
        f"r={float(metrics.get('recall_yes', 0.0) or 0.0):.4f} "
        f"f1={float(metrics.get('f1_yes', 0.0) or 0.0):.4f} "
        f"yy={int(metrics.get('yy', 0) or 0)} "
        f"nn={int(metrics.get('nn', 0) or 0)} "
        f"yn={int(metrics.get('yn', 0) or 0)} "
        f"ny={int(metrics.get('ny', 0) or 0)} "
        f"errors={int(metrics.get('trace_error_count', 0) or 0)}"
        f"{suffix}",
        flush=True,
    )


@contextmanager
def _active_prompt_env(prompt_path: Path):
    old = os.getenv(ACTIVE_SPECIFIC_PROMPT_ENV)
    os.environ[ACTIVE_SPECIFIC_PROMPT_ENV] = str(prompt_path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(ACTIVE_SPECIFIC_PROMPT_ENV, None)
        else:
            os.environ[ACTIVE_SPECIFIC_PROMPT_ENV] = old


@contextmanager
def _proxy_env_control(*, disable_proxy: bool):
    if not bool(disable_proxy):
        yield
        return
    old_env = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    old_sentinel = os.environ.get(_PROXY_DISABLE_SENTINEL)
    try:
        for key in _PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ[_PROXY_DISABLE_SENTINEL] = "1"
        yield
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if old_sentinel is None:
            os.environ.pop(_PROXY_DISABLE_SENTINEL, None)
        else:
            os.environ[_PROXY_DISABLE_SENTINEL] = old_sentinel

def _named_eval_log_dir(log_root: Path, *, name: str) -> Path:
    path = log_root / str(name).strip()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_one_eval(
    *,
    args: argparse.Namespace,
    eval_root: Path,
    meta_info_jsonl: Path,
    prompt_file: Path,
    log_root: Path,
    round_index: int,
    prompt_version: str,
    fixed_log_dir: Optional[Path] = None,
    progress_desc: str = "",
    store_name: str = "",
    max_samples: int = 0,
) -> Dict[str, Any]:
    round_log_dir = fixed_log_dir or _ensure_log_round_layout(log_root, round_index=round_index)
    round_log_dir.mkdir(parents=True, exist_ok=True)
    _ensure_grouped_round_layout(round_log_dir, section_map=ROUND_LOG_ARTIFACT_SECTIONS)
    trace_path = _log_round_artifact(round_log_dir, "extract_trace.jsonl")
    eval_path = _log_round_artifact(round_log_dir, "eval.json")
    yn_path = _log_round_artifact(round_log_dir, "yn_samples.jsonl")
    ny_path = _log_round_artifact(round_log_dir, "ny_samples.jsonl")
    all_meta_rows, _ = _load_meta(meta_info_jsonl)
    meta_rows = _limit_meta_rows(all_meta_rows, max_samples=max_samples)
    meta_by_name = {
        _basename(str(row.get("source_file") or "")): row
        for row in meta_rows
        if _basename(str(row.get("source_file") or ""))
    }
    effective_eval_root = eval_root
    if len(meta_rows) < len(all_meta_rows):
        dataset_name = Path(meta_info_jsonl).expanduser().resolve().parent.name or "dataset"
        effective_eval_root = _materialize_eval_subset_root(
            eval_root=eval_root,
            meta_rows=meta_rows,
            meta_info_jsonl=meta_info_jsonl,
            subset_root=_subset_dataset_view_root(
                log_root=log_root,
                dataset_name=dataset_name,
                sample_count=len(meta_rows),
            ),
        )
    existing_trace_rows = _load_jsonl(trace_path)
    allowed_names = set(meta_by_name.keys())
    existing_processed_names = {
        _basename(str(row.get("source_file") or row.get("file_name") or ""))
        for row in existing_trace_rows
        if str(row.get("type") or "").strip() == "conversation"
        and str(row.get("extracted") or "").strip().lower() in {"yes", "no"}
        and _basename(str(row.get("source_file") or row.get("file_name") or "")) in allowed_names
    }
    progress = _RoundProgress(
        round_index=round_index,
        total=len(meta_rows),
        enabled=bool(int(args.print_progress or 0)),
        initial=len(existing_processed_names),
        desc=progress_desc,
    )
    if existing_processed_names:
        _print_detail(
            f"[round-resume] round={round_index:03d} existing_trace_rows={len(existing_processed_names)} "
            f"trace_jsonl={_display_path(trace_path)}"
        )

    job_args = argparse.Namespace(**vars(args))
    setattr(job_args, "store_path", _round_store_path(args, log_root=log_root, name=(str(store_name).strip() or _round_tag(round_index))))
    sdk = _build_sdk_from_args(job_args)

    try:
        with _active_prompt_env(prompt_file):
            result = run_extract_job(
                sdk=sdk,
                user_id=str(args.user_id).strip() or "evolve_eval",
                file_path=str(effective_eval_root),
                hint=(str(args.hint).strip() or None),
                continue_on_error=True,
                max_messages_per_conversation=int(args.max_messages_per_conversation or 0),
                max_workers=int(args.max_workers or 0),
                metadata={"channel": _offline_extract_channel(extract_mode=args.extract_mode)},
                extract_mode=str(args.extract_mode),
                trace_jsonl=str(trace_path),
                overwrite_trace=False,
                append_trace=True,
                trace_flush_every=10,
                max_failed_retries=int(args.max_failed_retries or 3),
                prompt_version=prompt_version,
                round_index=round_index,
                print_progress=False,
                progress_callback=progress.update,
            )
    finally:
        progress.close()

    eval_payload = _evaluate_trace_rows(
        trace_rows=list(result.get("trace_records") or []),
        meta_rows=meta_rows,
        meta_by_name=meta_by_name,
        prompt_version=prompt_version,
        meta_info_jsonl=meta_info_jsonl,
    )
    eval_payload["trace_jsonl"] = str(trace_path)
    eval_payload["eval_json"] = str(eval_path)
    eval_payload["yn_samples_jsonl"] = str(yn_path)
    eval_payload["ny_samples_jsonl"] = str(ny_path)
    eval_payload["requested_max_samples"] = int(max_samples or 0)
    eval_payload["effective_sample_count"] = int(len(meta_rows))
    if effective_eval_root != eval_root:
        eval_payload["subset_view_root"] = str(effective_eval_root)
    _json_dump(eval_path, eval_payload)
    _write_jsonl(yn_path, list(eval_payload.get("yn_samples") or []))
    _write_jsonl(ny_path, list(eval_payload.get("ny_samples") or []))
    return eval_payload


def _run_eval_dataset(
    *,
    args: argparse.Namespace,
    eval_root: Path,
    meta_info_jsonl: Path,
    prompt_file: Path,
    log_root: Path,
    eval_name: str,
    prompt_version: str,
) -> Dict[str, Any]:
    eval_log_dir = _named_eval_log_dir(log_root, name=eval_name)
    return _run_one_eval(
        args=args,
        eval_root=eval_root,
        meta_info_jsonl=meta_info_jsonl,
        prompt_file=prompt_file,
        log_root=log_root,
        round_index=0,
        prompt_version=prompt_version,
        fixed_log_dir=eval_log_dir,
        progress_desc=eval_name,
        store_name=eval_name,
    )


def _load_manifest(run_root: Path) -> Dict[str, Any]:
    manifest = _load_json(run_root / "manifest.json")
    if not manifest:
        raise SystemExit(f"manifest.json missing or invalid: {run_root / 'manifest.json'}")
    return manifest


def _default_loop_arg_values() -> Dict[str, Any]:
    from .loop import build_parser as build_loop_parser

    parser = build_loop_parser(add_help=False)
    args = parser.parse_args(["--run-name", "__eval__"])
    return dict(vars(args))


def _timestamp_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _prompt_round_path(run_root: Path, *, round_index: int, name: str) -> Path:
    return run_root / f"round_{int(round_index):03d}" / "prompt" / name


def _resolve_prompt_file(
    *,
    run_root: Path,
    prompt_source: str,
    round_index: int,
    prompt_file_override: str,
) -> tuple[Path, str]:
    if str(prompt_file_override or "").strip():
        p = _norm_path(prompt_file_override)
        if not p.is_file():
            raise SystemExit(f"prompt-file is not a file: {p}")
        return p, f"manual_file:{p.name}"

    source = str(prompt_source or "best").strip().lower()
    if source == "base":
        return run_root / "base_prompt.txt", "manual_base"
    if source == "best":
        return run_root / "best_prompt.txt", "manual_best"
    if source == "active":
        return run_root / "active_prompt.txt", "manual_active"
    if source == "round_candidate":
        return _prompt_round_path(run_root, round_index=round_index, name="prompt_candidate.txt"), f"round_{int(round_index):03d}_candidate"
    if source == "round_before":
        return _prompt_round_path(run_root, round_index=round_index, name="prompt_before.txt"), f"round_{int(round_index):03d}_before"
    raise SystemExit(f"unsupported prompt-source: {prompt_source}")


def _resolve_dataset_paths(*, args: argparse.Namespace) -> tuple[Path, Path, int, str]:
    dataset = str(args.dataset or "eval").strip().lower()
    if dataset == "eval":
        eval_root = _norm_path(str(args.eval_root))
        meta_info_jsonl = _norm_path(str(args.eval_meta_info_jsonl))
        max_samples = 0
    elif dataset == "train":
        eval_root = _norm_path(str(args.train_root))
        meta_info_jsonl = _norm_path(str(args.train_meta_info_jsonl))
        max_samples = int(args.train_max_samples or 0)
    else:
        raise SystemExit(f"unsupported dataset: {args.dataset}")
    if not eval_root.is_dir():
        raise SystemExit(f"dataset root is not a directory: {eval_root}")
    if not meta_info_jsonl.is_file():
        raise SystemExit(f"meta info jsonl is not a file: {meta_info_jsonl}")
    return eval_root, meta_info_jsonl, max_samples, dataset


def _validate_backend_args(args: argparse.Namespace) -> None:
    backend = str(getattr(args, "codex_auto_backend", "llm") or "llm").strip().lower() or "llm"
    if backend == "command":
        raise SystemExit(
            "--codex-auto-backend command is not supported by standalone eval; "
            "use --codex-auto-backend llm"
        )
    if backend not in {"llm"}:
        raise SystemExit(f"unsupported codex-auto-backend for eval: {backend}")


def build_parser() -> argparse.ArgumentParser:
    defaults = _default_loop_arg_values()
    p = argparse.ArgumentParser(description="Run one standalone eval for an existing self-evolve run.")
    p.add_argument("--run-root", required=True, help="Run root like log/self-evolve/<stamp>/<run_name>")
    p.add_argument("--dataset", default="eval", help="eval|train")
    p.add_argument("--prompt-source", default="best", help="base|best|active|round_candidate|round_before")
    p.add_argument("--round", type=int, default=0, help="Required when prompt-source is round_candidate or round_before.")
    p.add_argument("--prompt-file", default="", help="Optional explicit prompt file; overrides --prompt-source.")
    p.add_argument("--eval-name", default="", help="Optional output folder name under the run root.")

    p.add_argument("--train-root", default=defaults["train_root"])
    p.add_argument("--train-meta-info-jsonl", default=defaults["train_meta_info_jsonl"])
    p.add_argument("--train-max-samples", type=int, default=int(defaults["train_max_samples"]))
    p.add_argument("--eval-root", default=defaults["eval_root"])
    p.add_argument("--eval-meta-info-jsonl", default=defaults["eval_meta_info_jsonl"])
    p.add_argument("--extract-mode", default=defaults["extract_mode"])
    p.add_argument("--user-id", default=defaults["user_id"])
    p.add_argument("--hint", default=defaults["hint"])
    p.add_argument("--max-messages-per-conversation", type=int, default=int(defaults["max_messages_per_conversation"]))
    p.add_argument("--max-workers", type=int, default=int(defaults["max_workers"]))
    p.add_argument("--max-failed-retries", type=int, default=int(defaults["max_failed_retries"]))
    p.add_argument("--print-progress", default=defaults["print_progress"])
    p.add_argument("--disable-env-proxy", default=defaults["disable_env_proxy"])
    p.add_argument("--llm-provider", default=defaults["llm_provider"])
    p.add_argument("--llm-model", default=defaults["llm_model"])
    p.add_argument("--llm-base-url", default=defaults["llm_base_url"])
    p.add_argument("--llm-api-key", default=defaults["llm_api_key"])
    p.add_argument("--auth-mode", default=defaults["auth_mode"])
    p.add_argument(
        "--codex-auto-backend",
        default="llm",
        choices=("llm", "command"),
        help="Compatibility flag with orchestrator. Eval only supports llm; command is rejected.",
    )
    add_codex_llm_args(p)
    p.add_argument("--embeddings-provider", default=defaults["embeddings_provider"])
    p.add_argument("--embeddings-model", default=defaults["embeddings_model"])
    p.add_argument("--embeddings-base-url", default=defaults["embeddings_base_url"])
    p.add_argument("--embeddings-api-key", default=defaults["embeddings_api_key"])
    p.add_argument("--embeddings-auth-mode", default=defaults["embeddings_auth_mode"])
    p.add_argument("--embeddings-dims", type=int, default=int(defaults["embeddings_dims"]))
    p.add_argument("--store-path", default=defaults["store_path"])
    p.add_argument("--strict-llm-errors", default=defaults["strict_llm_errors"])
    return p


def main() -> None:
    args = build_parser().parse_args()
    _validate_backend_args(args)
    run_root = _norm_path(str(args.run_root))
    if not run_root.is_dir():
        raise SystemExit(f"run-root is not a directory: {run_root}")

    manifest = _normalize_manifest_log_paths(manifest=_load_manifest(run_root), log_root=run_root)
    prompt_file, prompt_version = _resolve_prompt_file(
        run_root=run_root,
        prompt_source=str(args.prompt_source),
        round_index=int(args.round or 0),
        prompt_file_override=str(args.prompt_file),
    )
    if not prompt_file.is_file():
        raise SystemExit(f"prompt file is not a file: {prompt_file}")
    if not _safe_read_text(prompt_file).strip():
        raise SystemExit(f"prompt file is empty: {prompt_file}")

    dataset_root, meta_info_jsonl, max_samples, dataset = _resolve_dataset_paths(args=args)
    eval_name = str(args.eval_name or "").strip() or f"manual_eval_{dataset}_{prompt_version}_{_timestamp_tag()}"
    if getattr(args, "run_name", None) is None:
        setattr(args, "run_name", str(manifest.get("run_name") or run_root.name))

    with _proxy_env_control(disable_proxy=bool(int(args.disable_env_proxy or 0))):
        _print_header("Eval")
        _print_header("Config", blank_before=False)
        print(f"  run_root: {_display_path(run_root)}", flush=True)
        print(f"  dataset: {dataset}", flush=True)
        print(f"  prompt_file: {_display_path(prompt_file)}", flush=True)
        print(f"  eval_name: {eval_name}", flush=True)
        print(f"  llm_provider: {str(args.llm_provider).strip() or 'unknown'}", flush=True)
        print(f"  llm_model: {str(args.llm_model).strip() or 'unknown'}", flush=True)
        if is_codex_provider(getattr(args, "llm_provider", "")):
            print(f"  codex_auto_backend: {str(args.codex_auto_backend).strip() or 'llm'}", flush=True)

        if dataset == "eval":
            payload = _run_eval_dataset(
                args=args,
                eval_root=dataset_root,
                meta_info_jsonl=meta_info_jsonl,
                prompt_file=prompt_file,
                log_root=run_root,
                eval_name=eval_name,
                prompt_version=prompt_version,
            )
        else:
            payload = _run_one_eval(
                args=args,
                eval_root=dataset_root,
                meta_info_jsonl=meta_info_jsonl,
                prompt_file=prompt_file,
                log_root=run_root,
                round_index=0,
                prompt_version=prompt_version,
                fixed_log_dir=run_root / eval_name,
                progress_desc=eval_name,
                store_name=eval_name,
                max_samples=max_samples,
            )

        _print_round_metrics(
            round_index=int(args.round or 0),
            metrics=dict(payload.get("metrics") or {}),
            promoted=None,
            label=eval_name,
        )
        _print_header("Outputs")
        print(f"  eval_json: {_display_path(str(payload.get('eval_json') or ''))}", flush=True)
        print(f"  trace_jsonl: {_display_path(str(payload.get('trace_jsonl') or ''))}", flush=True)
        print(f"  yn_samples_jsonl: {_display_path(str(payload.get('yn_samples_jsonl') or ''))}", flush=True)
        print(f"  ny_samples_jsonl: {_display_path(str(payload.get('ny_samples_jsonl') or ''))}", flush=True)


if __name__ == "__main__":
    main()
