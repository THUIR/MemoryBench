"""External orchestrator for codex-mode self-evolve runs."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..llm_backend import is_codex_provider
from ..run_codex_reflection import run_codex_reflection_backend
from .loop import LoopRunResult, build_parser as build_loop_parser, run_parsed_args
from .reflection import build_reflection_llm, load_reflection_output, run_reflection


def _norm_path(path: str) -> Path:
    return Path(str(path or "")).expanduser().resolve()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _reflection_artifact(round_dir: Path, name: str) -> Path:
    return round_dir / "reflection" / name


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


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_parser() -> argparse.ArgumentParser:
    loop_parent = build_loop_parser(add_help=False)
    p = argparse.ArgumentParser(
        description="Auto-resume codex-mode self-evolve runs by generating reflection_output.json externally.",
        parents=[loop_parent],
    )
    p.add_argument("--codex-auto-backend", default="llm", choices=("llm", "command"))
    p.add_argument("--codex-command", default="", help="Shell command used when --codex-auto-backend command.")
    p.add_argument("--codex-command-cwd", default="", help="Optional working directory for --codex-command.")
    p.add_argument("--codex-command-timeout", type=int, default=1800)
    p.add_argument("--codex-reflection-max-retries", type=int, default=3)
    p.add_argument("--codex-max-auto-resumes", type=int, default=64)
    return p


def _render_command(template: str, replacements: Dict[str, str]) -> str:
    rendered = str(template or "")
    for key, value in replacements.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def _update_reflection_status(
    *,
    round_dir: Path,
    status: str,
    backend: str,
    output_json: Path,
    increment_attempt: bool = False,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    status_path = _reflection_artifact(round_dir, "reflection_status.json")
    payload = _load_json(status_path)
    payload["status"] = status
    payload["auto_backend"] = backend
    payload["expected_output_json"] = str(output_json)
    payload["updated_at"] = _now_iso()
    if increment_attempt:
        payload["attempt_count"] = int(payload.get("attempt_count", 0) or 0) + 1
    else:
        payload["attempt_count"] = int(payload.get("attempt_count", 0) or 0)
    for key, value in dict(extra or {}).items():
        payload[key] = value
    _json_dump(status_path, payload)
    return payload


def _run_command_backend(
    *,
    args: argparse.Namespace,
    input_json: Path,
    output_json: Path,
    loop_result: LoopRunResult,
) -> Dict[str, Any]:
    template = str(getattr(args, "codex_command", "") or "").strip()
    if not template:
        raise SystemExit("codex command backend requires --codex-command")
    round_dir = input_json.parent
    replacements = {
        "input_json": str(input_json),
        "output_json": str(output_json),
        "round_dir": str(round_dir),
        "run_root": str(loop_result.log_root),
        "prompt_root": str(loop_result.prompt_root),
        "log_root": str(loop_result.log_root),
        "run_name": str(getattr(args, "run_name", "") or ""),
        "stamp": loop_result.stamp,
        "round_index": str(loop_result.pending_round_index or ""),
    }
    cmd = _render_command(template, replacements)
    cwd = _norm_path(str(args.codex_command_cwd)) if str(args.codex_command_cwd or "").strip() else Path.cwd()
    env = dict(os.environ)
    env["AUTOSKILL_REFLECTION_INPUT_JSON"] = str(input_json)
    env["AUTOSKILL_REFLECTION_OUTPUT_JSON"] = str(output_json)
    env["AUTOSKILL_REFLECTION_ROUND_DIR"] = str(round_dir)
    env["AUTOSKILL_EVOLVE_RUN_ROOT"] = str(loop_result.log_root)
    env["AUTOSKILL_EVOLVE_PROMPT_ROOT"] = str(loop_result.prompt_root)
    env["AUTOSKILL_EVOLVE_LOG_ROOT"] = str(loop_result.log_root)
    env["AUTOSKILL_EVOLVE_SESSION_STAMP"] = str(loop_result.stamp)
    env["AUTOSKILL_CODEX_REFLECTION_MAX_RETRIES"] = str(int(args.codex_reflection_max_retries or 0))
    env["CODEX_REFLECTION_MAX_RETRIES"] = str(int(args.codex_reflection_max_retries or 0))
    subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd),
        env=env,
        check=True,
        timeout=int(args.codex_command_timeout),
    )
    return load_reflection_output(output_json)


def _run_llm_backend(
    *,
    args: argparse.Namespace,
    input_json: Path,
    output_json: Path,
) -> Dict[str, Any]:
    reflection_provider = str(getattr(args, "reflection_provider", "") or "").strip()
    llm_provider = str(getattr(args, "llm_provider", "") or "").strip()
    resolved_provider = reflection_provider or llm_provider
    if is_codex_provider(resolved_provider):
        reflection_model = str(getattr(args, "reflection_model", "") or "").strip()
        llm_model = str(getattr(args, "llm_model", "") or "").strip()
        model = reflection_model or llm_model or "gpt-5.4"
        preserve_openai_env = str(getattr(args, "codex_preserve_openai_env", "") or "").strip()
        return run_codex_reflection_backend(
            input_path=input_json,
            output_path=output_json,
            model=model,
            max_retries=int(
                getattr(args, "codex_reflection_max_retries", 0)
                or getattr(args, "codex_max_retries", 0)
                or 3
            ),
            codex_cli_path=str(getattr(args, "codex_cli_path", "") or ""),
            exec_cwd=str(getattr(args, "codex_exec_cwd", "") or ""),
            preserve_openai_env=(
                None
                if not preserve_openai_env
                else preserve_openai_env.lower() in {"1", "true", "yes", "y", "on"}
            ),
            print_progress=True,
        )
    payload = _load_json(input_json)
    if not payload:
        raise SystemExit(f"reflection_input.json missing or invalid: {input_json}")
    llm = build_reflection_llm(args)
    return run_reflection(
        mode="llm",
        llm=llm,
        reflection_input=payload,
        temperature=float(args.reflection_temperature),
        output_path=output_json,
    )


def resolve_pending_reflection(args: argparse.Namespace, loop_result: LoopRunResult) -> Dict[str, Any]:
    round_dir = loop_result.pending_round_dir
    if round_dir is None:
        raise SystemExit("codex auto-resume expected a pending round directory, but none was recorded")
    input_json = _reflection_artifact(round_dir, "reflection_input.json")
    output_json = _reflection_artifact(round_dir, "reflection_output.json")
    backend = str(args.codex_auto_backend or "llm").strip().lower() or "llm"
    status_extra = {
        "reflection_mode": "codex",
        "reflection_input_json": str(input_json),
        "started_at": _now_iso(),
        "pending_round": int(loop_result.pending_round_index or 0),
    }
    if backend == "command":
        status_extra["command_template"] = str(args.codex_command or "")
    round_text = (
        f"{int(loop_result.pending_round_index):03d}"
        if loop_result.pending_round_index is not None
        else "unknown"
    )
    _print_header(f"Reflection Resolve {round_text}")
    _print_detail(
        "[reflection-resolve] "
        f"backend={backend} "
        f"input_json={_display_path(input_json)} "
        f"output_json={_display_path(output_json)}"
    )
    _update_reflection_status(
        round_dir=round_dir,
        status="running",
        backend=backend,
        output_json=output_json,
        increment_attempt=True,
        extra=status_extra,
    )
    try:
        if backend == "command":
            normalized = _run_command_backend(
                args=args,
                input_json=input_json,
                output_json=output_json,
                loop_result=loop_result,
            )
        else:
            normalized = _run_llm_backend(
                args=args,
                input_json=input_json,
                output_json=output_json,
            )
    except Exception as exc:
        stdout_log = _reflection_artifact(round_dir, "codex_exec.stdout.log")
        stderr_log = _reflection_artifact(round_dir, "codex_exec.stderr.log")
        _update_reflection_status(
            round_dir=round_dir,
            status="error",
            backend=backend,
            output_json=output_json,
            extra={
                "error": str(exc),
                "failed_at": _now_iso(),
                "stdout_log": str(stdout_log) if stdout_log.is_file() else "",
                "stderr_log": str(stderr_log) if stderr_log.is_file() else "",
            },
        )
        _print_detail(
            "[reflection-resolve-error] "
            f"backend={backend} "
            f"error={exc} "
            f"stdout_log={_display_path(stdout_log) if stdout_log.is_file() else '-'} "
            f"stderr_log={_display_path(stderr_log) if stderr_log.is_file() else '-'}"
        )
        raise
    _update_reflection_status(
        round_dir=round_dir,
        status="completed",
        backend=backend,
        output_json=output_json,
        extra={
            "resolved_at": _now_iso(),
        },
    )
    _print_detail(
        "[reflection-resolve-done] "
        f"backend={backend} "
        f"output_json={_display_path(output_json)}"
    )
    return normalized


def run_codex_auto(args: argparse.Namespace) -> LoopRunResult:
    loop_args = copy.deepcopy(args)
    loop_args.reflection_mode = "codex"
    max_auto_resumes = int(args.codex_max_auto_resumes or 0)
    resume_count = 0
    while True:
        loop_result = run_parsed_args(loop_args)
        if loop_result.stop_signal != "waiting_for_codex_reflection":
            return loop_result
        if resume_count >= max_auto_resumes:
            raise SystemExit(
                f"codex auto-resume exceeded limit: pending reflections={resume_count}, "
                f"limit={max_auto_resumes}"
            )
        round_text = (
            f"{int(loop_result.pending_round_index):03d}"
            if loop_result.pending_round_index is not None
            else "unknown"
        )
        _print_header("Codex Auto")
        _print_detail(f"resolve round={round_text} backend={str(args.codex_auto_backend)}")
        resolve_pending_reflection(args, loop_result)
        resume_count += 1
        loop_args.resume = "1"
        loop_args.session_stamp = loop_result.stamp
        _print_detail(f"resume round={round_text} stamp={loop_result.stamp}")


def main() -> None:
    args = build_parser().parse_args()
    run_codex_auto(args)


if __name__ == "__main__":
    main()
