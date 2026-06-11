"""
Run/round artifact helpers for self-evolve.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ..prompts import (
    EXTRACT_MODE_COMMON,
    build_builtin_offline_extract_prompt_specific,
    build_offline_extract_prompt_common,
)


ROUND_PROMPT_ARTIFACT_SECTIONS: Dict[str, str] = {
    "prompt_before.txt": "prompt",
    "prompt_candidate.txt": "prompt",
    "prompt_diff.md": "prompt",
    "prompt_patch.json": "prompt",
    "prompt_patch.md": "prompt",
    "active_patch_set_before.json": "prompt",
    "candidate_patch_set.json": "prompt",
    "reflection_input.json": "reflection",
    "reflection_output.json": "reflection",
    "reflection_status.json": "reflection",
    "reflection_error.json": "reflection",
    "codex_exec.stdout.log": "reflection",
    "codex_exec.stderr.log": "reflection",
    "round_status.json": "state",
    "round_summary.json": "state",
}
ROUND_LOG_ARTIFACT_SECTIONS: Dict[str, str] = {
    "extract_trace.jsonl": "trace",
    "eval.json": "eval",
    "yn_samples.jsonl": "eval",
    "ny_samples.jsonl": "eval",
    "round_summary.json": "state",
}


def _timestamp_tag(dt: datetime | None = None) -> str:
    now = dt or datetime.now()
    return now.strftime("%Y-%m%d-%H%M")


def _norm_path(path: str) -> Path:
    return Path(str(path or "")).expanduser().resolve()


def _run_root(*, stamp: str, run_name: str) -> Path:
    return _norm_path(f"log/self-evolve/{stamp}/{run_name}")


def _legacy_prompt_root(*, stamp: str, run_name: str) -> Path:
    return _norm_path(f"autoskill/offline/conversation/prompt_evolution/{stamp}/{run_name}")


def _legacy_log_root(*, stamp: str, run_name: str) -> Path:
    return _norm_path(f"log/prompt_evolution/{stamp}/{run_name}")


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _merge_jsonl_files(src: Path, dst: Path) -> None:
    seen: set[str] = set()
    merged_lines: List[str] = []
    for path in (src, dst):
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = str(raw_line or "").rstrip("\n")
                if not line or line in seen:
                    continue
                seen.add(line)
                merged_lines.append(line)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        for line in merged_lines:
            f.write(line + "\n")


def _safe_read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = str(line or "").strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as exc:
                raise SystemExit(f"Invalid JSONL at {path}:{line_no}") from exc
            if not isinstance(obj, dict):
                raise SystemExit(f"Expected JSON object at {path}:{line_no}")
            out.append(obj)
    return out


def _empty_patch_set() -> Dict[str, Any]:
    return {
        "type": "patch_set",
        "accepted_rounds": [],
        "operations": [],
        "add_negative_rules": [],
        "add_positive_rules": [],
        "weaken_rules": [],
        "strengthen_rules": [],
        "delete_rules": [],
    }


def _default_prompt_text(*, extract_mode: str) -> str:
    mode = str(extract_mode or "").strip().lower()
    if mode == EXTRACT_MODE_COMMON:
        return build_offline_extract_prompt_common(
            channel="offline_extract_from_conversation:common",
            max_candidates=1,
        )
    return build_builtin_offline_extract_prompt_specific(
        channel="offline_extract_from_conversation:specific",
        max_candidates=1,
    )


def _default_specific_prompt_text() -> str:
    return _default_prompt_text(extract_mode="specific")


def _round_tag(round_index: int) -> str:
    return f"round_{int(round_index):03d}"


def _round_artifact_path(round_dir: Path, *, name: str, section_map: Dict[str, str]) -> Path:
    section = str(section_map.get(name) or "").strip()
    if not section:
        return round_dir / name
    return round_dir / section / name


def _prompt_round_artifact(round_dir: Path, name: str) -> Path:
    return _round_artifact_path(round_dir, name=name, section_map=ROUND_PROMPT_ARTIFACT_SECTIONS)


def _log_round_artifact(round_dir: Path, name: str) -> Path:
    return _round_artifact_path(round_dir, name=name, section_map=ROUND_LOG_ARTIFACT_SECTIONS)


def _ensure_grouped_round_layout(round_dir: Path, *, section_map: Dict[str, str]) -> Path:
    round_dir.mkdir(parents=True, exist_ok=True)
    for section in sorted(set(section_map.values())):
        (round_dir / section).mkdir(parents=True, exist_ok=True)
    for name in section_map:
        legacy_path = round_dir / name
        target_path = _round_artifact_path(round_dir, name=name, section_map=section_map)
        if not legacy_path.exists() and not legacy_path.is_symlink():
            continue
        if target_path.exists() or target_path.is_symlink():
            if legacy_path != target_path:
                legacy_path.unlink()
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(target_path))
    return round_dir


def _log_round_dir(log_root: Path, *, round_index: int) -> Path:
    return log_root / _round_tag(round_index)


def _ensure_log_round_layout(log_root: Path, *, round_index: int) -> Path:
    round_tag = _round_tag(round_index)
    round_dir = _log_round_dir(log_root, round_index=round_index)
    _ensure_grouped_round_layout(round_dir, section_map=ROUND_LOG_ARTIFACT_SECTIONS)

    legacy_map = {
        log_root / f"{round_tag}_extract_trace.jsonl": _log_round_artifact(round_dir, "extract_trace.jsonl"),
        log_root / f"{round_tag}_eval.json": _log_round_artifact(round_dir, "eval.json"),
        log_root / f"{round_tag}_yn_samples.jsonl": _log_round_artifact(round_dir, "yn_samples.jsonl"),
        log_root / f"{round_tag}_ny_samples.jsonl": _log_round_artifact(round_dir, "ny_samples.jsonl"),
        log_root / f"{round_tag}_round_summary.json": _log_round_artifact(round_dir, "round_summary.json"),
    }
    for src, dst in legacy_map.items():
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
    return round_dir


def _migrate_all_legacy_log_round_files(log_root: Path) -> None:
    if not log_root.is_dir():
        return
    suffix_map = {
        "_extract_trace.jsonl": "extract_trace.jsonl",
        "_eval.json": "eval.json",
        "_yn_samples.jsonl": "yn_samples.jsonl",
        "_ny_samples.jsonl": "ny_samples.jsonl",
        "_round_summary.json": "round_summary.json",
    }
    for path in sorted(log_root.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        for suffix, target_name in suffix_map.items():
            if not name.startswith("round_") or not name.endswith(suffix):
                continue
            round_tag = name[: -len(suffix)]
            if not round_tag.startswith("round_"):
                continue
            round_dir = log_root / round_tag
            _ensure_grouped_round_layout(round_dir, section_map=ROUND_LOG_ARTIFACT_SECTIONS)
            target = _log_round_artifact(round_dir, target_name)
            if target_name == "extract_trace.jsonl" and target.exists():
                _merge_jsonl_files(path, target)
                path.unlink()
            elif not target.exists():
                shutil.move(str(path), str(target))
            else:
                path.unlink()
            break


def _ensure_prompt_round_layout(prompt_root: Path, *, round_index: int) -> Path:
    round_dir = prompt_root / _round_tag(round_index)
    return _ensure_grouped_round_layout(round_dir, section_map=ROUND_PROMPT_ARTIFACT_SECTIONS)


def _migrate_all_prompt_round_files(prompt_root: Path) -> None:
    if not prompt_root.is_dir():
        return
    for round_dir in sorted(p for p in prompt_root.glob("round_*") if p.is_dir()):
        _ensure_grouped_round_layout(round_dir, section_map=ROUND_PROMPT_ARTIFACT_SECTIONS)


def _history_paths(prompt_root: Path, log_root: Path) -> Tuple[Path, Path]:
    return prompt_root / "history.jsonl", log_root / "history.jsonl"


def _load_history(path: Path) -> List[Dict[str, Any]]:
    return _load_jsonl(path)


def _write_history_row(prompt_root: Path, log_root: Path, row: Dict[str, Any]) -> None:
    p1, p2 = _history_paths(prompt_root, log_root)
    _append_jsonl(p1, row)
    if p2.resolve() != p1.resolve():
        _append_jsonl(p2, row)


def _normalize_manifest_log_paths(*, manifest: Dict[str, Any], log_root: Path) -> Dict[str, Any]:
    _migrate_all_legacy_log_round_files(log_root)
    completed = [int(x or 0) for x in list(manifest.get("completed_rounds") or [])]
    for round_index in completed:
        _ensure_log_round_layout(log_root, round_index=round_index)

    for key in ("active_eval_json", "best_eval_json", "active_train_eval_json", "best_train_eval_json"):
        raw = str(manifest.get(key) or "").strip()
        if not raw:
            continue
        p = Path(raw).expanduser()
        name = p.name
        if name.startswith("round_") and name.endswith("_eval.json"):
            round_tag = name[: -len("_eval.json")]
            round_dir = log_root / round_tag
            new_path = _log_round_artifact(round_dir, "eval.json")
            if new_path.exists():
                manifest[key] = str(new_path)
                continue
        if name == "eval.json" and p.parent.name.startswith("round_"):
            round_dir = log_root / p.parent.name
            new_path = _log_round_artifact(round_dir, "eval.json")
            if new_path.exists():
                manifest[key] = str(new_path)
    return manifest


def _latest_run_stamp(run_name: str) -> str:
    roots = [
        _norm_path("log/self-evolve"),
        _norm_path("autoskill/offline/conversation/prompt_evolution"),
        _norm_path("log/prompt_evolution"),
    ]
    matches: List[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for stamp_dir in root.iterdir():
            if not stamp_dir.is_dir():
                continue
            if (stamp_dir / run_name).is_dir():
                matches.append(stamp_dir.name)
    if not matches:
        raise SystemExit(f"No self-evolve run found for run_name={run_name}")
    return sorted(matches)[-1]


def _ensure_run_roots(args: argparse.Namespace) -> Tuple[str, Path, Path]:
    stamp = str(args.session_stamp or "").strip()
    if bool(int(args.resume or 0)):
        if not stamp:
            stamp = _latest_run_stamp(str(args.run_name))
        run_root = _run_root(stamp=stamp, run_name=str(args.run_name))
        if run_root.is_dir():
            return stamp, run_root, run_root
        prompt_root = _legacy_prompt_root(stamp=stamp, run_name=str(args.run_name))
        log_root = _legacy_log_root(stamp=stamp, run_name=str(args.run_name))
        if not prompt_root.is_dir() or not log_root.is_dir():
            raise SystemExit(
                "resume requested but run roots not found: "
                f"{run_root} | {prompt_root} | {log_root}"
            )
        return stamp, prompt_root, log_root

    stamp = stamp or _timestamp_tag()
    run_root = _run_root(stamp=stamp, run_name=str(args.run_name))
    legacy_prompt_root = _legacy_prompt_root(stamp=stamp, run_name=str(args.run_name))
    legacy_log_root = _legacy_log_root(stamp=stamp, run_name=str(args.run_name))
    if run_root.exists() or legacy_prompt_root.exists() or legacy_log_root.exists():
        raise SystemExit(f"run already exists: {stamp}/{args.run_name} (use --resume 1 or a different run-name/session-stamp)")
    run_root.mkdir(parents=True, exist_ok=False)
    return stamp, run_root, run_root


def _round_store_path(args: argparse.Namespace, *, log_root: Path, name: str) -> str:
    if str(args.store_path or "").strip():
        base = _norm_path(args.store_path) / "_self_evolve" / name
    else:
        base = log_root / "_stores" / name
    return str(base)


def _initialize_run(
    *,
    args: argparse.Namespace,
    stamp: str,
    prompt_root: Path,
    log_root: Path,
) -> Dict[str, Any]:
    base_prompt_path = prompt_root / "base_prompt.txt"
    active_prompt_path = prompt_root / "active_prompt.txt"
    best_prompt_path = prompt_root / "best_prompt.txt"
    active_patch_set_path = prompt_root / "active_patch_set.json"
    best_patch_set_path = prompt_root / "best_patch_set.json"
    best_metrics_path = prompt_root / "best_metrics.json"
    manifest_path = prompt_root / "manifest.json"

    default_prompt_text = _default_prompt_text(extract_mode=str(args.extract_mode))

    if not active_prompt_path.is_file():
        prompt_text = default_prompt_text
        active_prompt_path.write_text(prompt_text + "\n", encoding="utf-8")
        best_prompt_path.write_text(prompt_text + "\n", encoding="utf-8")
    if not best_prompt_path.is_file():
        best_prompt_path.write_text((_safe_read_text(active_prompt_path).rstrip("\n") or default_prompt_text) + "\n", encoding="utf-8")
    if not base_prompt_path.is_file():
        base_text = _safe_read_text(active_prompt_path).rstrip("\n") or default_prompt_text
        base_prompt_path.write_text(base_text + "\n", encoding="utf-8")
    if not active_patch_set_path.is_file():
        _json_dump(active_patch_set_path, _empty_patch_set())
    if not best_patch_set_path.is_file():
        _json_dump(best_patch_set_path, _load_json(active_patch_set_path) or _empty_patch_set())

    manifest = _load_json(manifest_path)
    if not manifest:
        manifest = {
            "stamp": stamp,
            "run_name": str(args.run_name),
            "run_root": str(log_root if log_root.resolve() == prompt_root.resolve() else log_root),
            "prompt_root": str(prompt_root),
            "log_root": str(log_root),
            "base_prompt_path": str(base_prompt_path),
            "active_prompt_path": str(active_prompt_path),
            "best_prompt_path": str(best_prompt_path),
            "active_patch_set_path": str(active_patch_set_path),
            "best_patch_set_path": str(best_patch_set_path),
            "best_metrics_path": str(best_metrics_path),
            "active_train_eval_json": "",
            "best_train_eval_json": "",
            "eval_baseline_json": "",
            "eval_final_json": "",
            "completed_rounds": [],
            "max_rounds": int(args.max_rounds),
            "patience": int(args.patience),
            "eval_before": bool(int(args.eval_before or 0)),
            "eval_after": bool(int(args.eval_after or 0)),
            "extract_mode": str(args.extract_mode),
            "train_max_samples": int(args.train_max_samples or 0),
            "base_prompt_min_length_ratio": float(getattr(args, "base_prompt_min_length_ratio", 0.70)),
            "base_prompt_max_length_ratio": float(getattr(args, "base_prompt_max_length_ratio", 1.50)),
        }
        _json_dump(manifest_path, manifest)
        _json_dump(log_root / "manifest.json", manifest)
    else:
        manifest.setdefault("run_root", str(log_root if log_root.resolve() == prompt_root.resolve() else log_root))
        manifest.setdefault("base_prompt_path", str(base_prompt_path))
        manifest.setdefault("active_patch_set_path", str(active_patch_set_path))
        manifest.setdefault("best_patch_set_path", str(best_patch_set_path))
        if "active_eval_json" in manifest and "active_train_eval_json" not in manifest:
            manifest["active_train_eval_json"] = str(manifest.get("active_eval_json") or "")
        if "best_eval_json" in manifest and "best_train_eval_json" not in manifest:
            manifest["best_train_eval_json"] = str(manifest.get("best_eval_json") or "")
        manifest.setdefault("active_train_eval_json", "")
        manifest.setdefault("best_train_eval_json", "")
        if "heldout_baseline_eval_json" in manifest and "eval_baseline_json" not in manifest:
            manifest["eval_baseline_json"] = str(manifest.get("heldout_baseline_eval_json") or "")
        if "heldout_final_eval_json" in manifest and "eval_final_json" not in manifest:
            manifest["eval_final_json"] = str(manifest.get("heldout_final_eval_json") or "")
        manifest.setdefault("eval_baseline_json", "")
        manifest.setdefault("eval_final_json", "")
        manifest.setdefault("eval_before", bool(int(args.eval_before or 0)))
        manifest.setdefault("eval_after", bool(int(args.eval_after or 0)))
        manifest.setdefault("train_max_samples", int(args.train_max_samples or 0))
        manifest.setdefault("base_prompt_min_length_ratio", float(getattr(args, "base_prompt_min_length_ratio", 0.70)))
        manifest.setdefault("base_prompt_max_length_ratio", float(getattr(args, "base_prompt_max_length_ratio", 1.50)))
    return manifest
