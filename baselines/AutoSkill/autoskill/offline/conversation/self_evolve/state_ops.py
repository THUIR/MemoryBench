"""State management helpers for self-evolve runs."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .artifacts import (
    _json_dump,
    _load_json,
    _load_jsonl,
    _log_round_artifact,
    _prompt_round_artifact,
    _round_tag,
    _safe_read_text,
    _write_jsonl,
)
from .eval import _display_path
from .patch import _empty_patch_set, _normalize_patch_set


def _norm_path(path: str) -> Path:
    return Path(str(path or "")).expanduser().resolve()


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _print_header(title: str, *, blank_before: bool = True) -> None:
    if blank_before:
        print("", flush=True)
    print(f"== {str(title).strip()} ==", flush=True)


def _print_detail(message: str) -> None:
    print(f"  {str(message).strip()}", flush=True)


def _run_state_log_path(run_root: Path) -> Path:
    return run_root / "_state_ops" / "state_ops.jsonl"


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_history(run_root: Path) -> List[Dict[str, Any]]:
    return _load_jsonl(run_root / "history.jsonl")


def _load_manifest(run_root: Path) -> Dict[str, Any]:
    manifest = _load_json(run_root / "manifest.json")
    if not manifest:
        raise SystemExit(f"manifest.json missing or invalid: {run_root / 'manifest.json'}")
    return manifest


def _round_dir(run_root: Path, round_index: int) -> Path:
    return run_root / _round_tag(round_index)


def _find_round_paths(run_root: Path, round_index: int) -> Dict[str, Path]:
    round_dir = _round_dir(run_root, round_index)
    if not round_dir.is_dir():
        raise SystemExit(f"round directory not found: {round_dir}")
    paths = {
        "round_dir": round_dir,
        "prompt_candidate": _prompt_round_artifact(round_dir, "prompt_candidate.txt"),
        "candidate_patch_set": _prompt_round_artifact(round_dir, "candidate_patch_set.json"),
        "round_summary": _prompt_round_artifact(round_dir, "round_summary.json"),
        "eval_json": _log_round_artifact(round_dir, "eval.json"),
    }
    required = ("prompt_candidate", "candidate_patch_set", "eval_json")
    for key in required:
        if not paths[key].is_file():
            raise SystemExit(f"required round artifact missing: {paths[key]}")
    return paths


def _history_row_by_round(history_rows: List[Dict[str, Any]], round_index: int) -> Dict[str, Any] | None:
    for row in history_rows:
        if int(row.get("round", -1) or -1) == int(round_index):
            return row
    return None


def _target_state_from_round(run_root: Path, round_index: int) -> Dict[str, Any]:
    if int(round_index) == 0:
        base_prompt_path = run_root / "base_prompt.txt"
        eval_json_path = _log_round_artifact(_round_dir(run_root, 0), "eval.json")
        metrics_payload = _load_json(eval_json_path)
        if not base_prompt_path.is_file() or not eval_json_path.is_file():
            raise SystemExit("round_000 baseline artifacts are incomplete; cannot rollback to round 000")
        return {
            "prompt_text": _safe_read_text(base_prompt_path).rstrip("\n"),
            "patch_set": _empty_patch_set(),
            "eval_json_path": eval_json_path,
            "metrics": dict(metrics_payload.get("metrics") or {}),
            "round_dir": _round_dir(run_root, 0),
        }

    paths = _find_round_paths(run_root, round_index)
    patch_payload = _load_json(paths["candidate_patch_set"])
    eval_payload = _load_json(paths["eval_json"])
    return {
        "prompt_text": _safe_read_text(paths["prompt_candidate"]).rstrip("\n"),
        "patch_set": _normalize_patch_set(dict(patch_payload.get("patch_set") or patch_payload)),
        "eval_json_path": paths["eval_json"],
        "metrics": dict(eval_payload.get("metrics") or {}),
        "round_dir": paths["round_dir"],
        "round_summary_path": paths["round_summary"],
    }


def _archive_later_round_artifacts(run_root: Path, *, target_round: int) -> Dict[str, List[str]]:
    archive_root = run_root / "_state_ops" / "archive" / _now_tag()
    archived: Dict[str, List[str]] = {"round_dirs": [], "stores": []}
    for path in sorted(run_root.glob("round_*")):
        if not path.is_dir():
            continue
        try:
            round_index = int(path.name.split("_")[-1])
        except Exception:
            continue
        if round_index <= int(target_round):
            continue
        dst = archive_root / path.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dst))
        archived["round_dirs"].append(str(dst))

    store_root = run_root / "_stores"
    if store_root.is_dir():
        for path in sorted(store_root.glob("round_*")):
            if not path.exists():
                continue
            try:
                round_index = int(path.name.split("_")[-1])
            except Exception:
                continue
            if round_index <= int(target_round):
                continue
            dst = archive_root / "_stores" / path.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dst))
            archived["stores"].append(str(dst))
    return archived


def _apply_target_state(
    *,
    run_root: Path,
    target_round: int,
    state: Dict[str, Any],
    history_rows: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    promotion_reason: str,
    dry_run: bool,
) -> Dict[str, Any]:
    prompt_text = str(state.get("prompt_text") or "").rstrip("\n")
    patch_set = _normalize_patch_set(dict(state.get("patch_set") or _empty_patch_set()))
    eval_json_path = Path(str(state.get("eval_json_path") or "")).expanduser()
    metrics = dict(state.get("metrics") or {})

    target_history = [dict(row) for row in history_rows if int(row.get("round", -1) or -1) <= int(target_round)]
    target_row = _history_row_by_round(target_history, target_round)
    if target_row is None:
        if int(target_round) == 0:
            target_row = {
                "round": 0,
                "prompt_version": "round_000_active",
                "parent_prompt_version": None,
            }
            target_history.append(target_row)
        else:
            raise SystemExit(f"history.jsonl missing row for target round: {target_round}")
    target_row["promoted"] = True
    target_row["promotion_reason"] = str(promotion_reason)
    target_row["stop_signal"] = None
    for key, value in metrics.items():
        if key in {
            "accuracy",
            "precision_yes",
            "recall_yes",
            "f1_yes",
            "yy",
            "nn",
            "yn",
            "ny",
            "coverage",
            "trace_error_count",
            "gold_total",
            "trace_total",
            "missing_prediction_count",
            "invalid_prediction_count",
            "extra_prediction_count",
        }:
            target_row["errors" if key == "trace_error_count" else key] = value

    completed_rounds = sorted({int(row.get("round", 0) or 0) for row in target_history})
    manifest["active_train_eval_json"] = str(eval_json_path)
    manifest["best_train_eval_json"] = str(eval_json_path)
    manifest["completed_rounds"] = completed_rounds
    manifest["eval_final_json"] = ""

    root_writes = {
        run_root / "active_prompt.txt": prompt_text + "\n",
        run_root / "best_prompt.txt": prompt_text + "\n",
    }
    root_json_writes = {
        run_root / "active_patch_set.json": patch_set,
        run_root / "best_patch_set.json": patch_set,
        run_root / "best_metrics.json": metrics,
        run_root / "manifest.json": manifest,
    }

    round_summary_path = Path(str(state.get("round_summary_path") or "")).expanduser() if str(state.get("round_summary_path") or "").strip() else Path("")
    if round_summary_path:
        round_summary = _load_json(round_summary_path)
        if round_summary:
            round_summary["promoted"] = True
            round_summary["promotion_reason"] = str(promotion_reason)
            round_summary["stop_signal"] = None
            root_json_writes[round_summary_path] = round_summary

    if not dry_run:
        for path, text in root_writes.items():
            path.write_text(text, encoding="utf-8")
        for path, payload in root_json_writes.items():
            _json_dump(path, payload)
        _write_jsonl(run_root / "history.jsonl", target_history)

    return {
        "target_round": int(target_round),
        "completed_rounds": completed_rounds,
        "active_train_eval_json": str(eval_json_path),
        "promotion_reason": str(promotion_reason),
        "prompt_chars": len(prompt_text),
        "metrics": metrics,
    }


def _state_log_row(*, op: str, run_root: Path, details: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "op": str(op),
        "run_root": str(run_root),
        **dict(details or {}),
    }


def show_state(run_root: Path) -> None:
    manifest = _load_manifest(run_root)
    history_rows = _load_history(run_root)
    completed_rounds = list(manifest.get("completed_rounds") or [])
    promoted_rounds = [
        int(row.get("round", 0) or 0)
        for row in history_rows
        if bool(row.get("promoted"))
    ]
    _print_header("State")
    _print_detail(f"run_root: {_display_path(run_root)}")
    _print_detail(f"completed_rounds: {completed_rounds}")
    _print_detail(f"promoted_rounds: {promoted_rounds}")
    _print_detail(f"active_train_eval_json: {_display_path(str(manifest.get('active_train_eval_json') or ''))}")
    _print_detail(f"best_train_eval_json: {_display_path(str(manifest.get('best_train_eval_json') or ''))}")
    _print_detail(f"active_prompt: {_display_path(run_root / 'active_prompt.txt')}")
    _print_detail(f"best_prompt: {_display_path(run_root / 'best_prompt.txt')}")
    if history_rows:
        last_row = history_rows[-1]
        _print_detail(
            "last_history: "
            f"round={int(last_row.get('round', 0) or 0):03d} "
            f"promoted={1 if bool(last_row.get('promoted')) else 0} "
            f"reason={str(last_row.get('promotion_reason') or '')}"
        )


def rebase_state(
    run_root: Path,
    *,
    target_round: int,
    archive_later_rounds: bool,
    dry_run: bool,
    promotion_reason: str,
) -> None:
    manifest = _load_manifest(run_root)
    history_rows = _load_history(run_root)
    state = _target_state_from_round(run_root, target_round)
    archived = {"round_dirs": [], "stores": []}
    if archive_later_rounds:
        archived = _archive_later_round_artifacts(run_root, target_round=target_round) if not dry_run else archived
    result = _apply_target_state(
        run_root=run_root,
        target_round=target_round,
        state=state,
        history_rows=history_rows,
        manifest=manifest,
        promotion_reason=promotion_reason,
        dry_run=dry_run,
    )
    log_row = _state_log_row(
        op="rebase",
        run_root=run_root,
        details={
            "target_round": int(target_round),
            "archived": archived,
            "result": result,
            "dry_run": bool(dry_run),
        },
    )
    if not dry_run:
        _append_jsonl(_run_state_log_path(run_root), log_row)
    _print_header("Rebase")
    _print_detail(f"run_root: {_display_path(run_root)}")
    _print_detail(f"target_round: {int(target_round):03d}")
    _print_detail(f"promotion_reason: {promotion_reason}")
    _print_detail(f"active_train_eval_json: {_display_path(result['active_train_eval_json'])}")
    _print_detail(f"completed_rounds: {result['completed_rounds']}")
    _print_detail(f"archived_round_dirs: {len(archived['round_dirs'])}")
    _print_detail(f"archived_stores: {len(archived['stores'])}")
    _print_detail(f"dry_run: {1 if dry_run else 0}")


def rollback_state(
    run_root: Path,
    *,
    target_round: int,
    archive_later_rounds: bool,
    dry_run: bool,
) -> None:
    history_rows = _load_history(run_root)
    target_row = _history_row_by_round(history_rows, target_round)
    if target_row is None:
        raise SystemExit(f"history row not found for round {target_round}")
    if int(target_round) != 0 and not bool(target_row.get("promoted")):
        raise SystemExit(
            f"round {target_round} is not a promoted mainline state; use `rebase --round {target_round}` instead"
        )
    rebase_state(
        run_root,
        target_round=target_round,
        archive_later_rounds=archive_later_rounds,
        dry_run=dry_run,
        promotion_reason=f"rollback_to_round_{int(target_round):03d}",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Inspect or rewrite the mainline state of a self-evolve run.")
    p.add_argument("--run-root", required=True, help="Run root like log/self-evolve/<stamp>/<run_name>")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("show-state", help="Print the current run state.")

    rebase_p = sub.add_parser("rebase", help="Promote one historical round candidate as the new mainline.")
    rebase_p.add_argument("--round", type=int, required=True)
    rebase_p.add_argument("--archive-later-rounds", default="1")
    rebase_p.add_argument("--dry-run", default="0")
    rebase_p.add_argument("--promotion-reason", default="")

    rollback_p = sub.add_parser("rollback", help="Rollback to an already-promoted round.")
    rollback_p.add_argument("--round", type=int, required=True)
    rollback_p.add_argument("--archive-later-rounds", default="1")
    rollback_p.add_argument("--dry-run", default="0")
    return p


def main() -> None:
    args = build_parser().parse_args()
    run_root = _norm_path(str(args.run_root))
    if not run_root.is_dir():
        raise SystemExit(f"run-root is not a directory: {run_root}")

    if args.command == "show-state":
        show_state(run_root)
        return

    if args.command == "rebase":
        promotion_reason = str(args.promotion_reason or "").strip() or f"manual_rebase_from_round_{int(args.round):03d}"
        rebase_state(
            run_root,
            target_round=int(args.round),
            archive_later_rounds=bool(int(args.archive_later_rounds or 0)),
            dry_run=bool(int(args.dry_run or 0)),
            promotion_reason=promotion_reason,
        )
        return

    if args.command == "rollback":
        rollback_state(
            run_root,
            target_round=int(args.round),
            archive_later_rounds=bool(int(args.archive_later_rounds or 0)),
            dry_run=bool(int(args.dry_run or 0)),
        )
        return

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
