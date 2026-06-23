"""Codex command-wrapper for self-evolve reflection rounds."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from .self_evolve.reflection import (
    _extract_json_object,
    build_reflection_system_prompt,
    normalize_patch_payload,
)


_CODEX_CLI_ENV_BLOCKLIST = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _workflow_path() -> Path:
    return _repo_root() / "autoskill" / "offline" / "conversation" / "self_evolve" / "WORKFLOW.md"


def _resolve_codex_cli(codex_cli_path: str = "") -> str:
    candidates = []
    explicit = str(codex_cli_path or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_path = str(os.getenv("CODEX_CLI_PATH", "") or "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    which_path = shutil.which("codex")
    if which_path:
        candidates.append(Path(which_path))
    candidates.extend(
        [
            Path("/Applications/Codex.app/Contents/Resources/codex"),
            Path("/Applications/Codex.app/Contents/MacOS/Codex"),
        ]
    )
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(
        "Unable to locate the Codex CLI. Set CODEX_CLI_PATH or ensure `codex` is available in PATH."
    )


def _build_codex_prompt(*, workflow_path: Path, input_json_path: Path) -> str:
    system_prompt = build_reflection_system_prompt().strip()
    return (
        "Read the workflow document first to understand the end-to-end self-evolve process:\n"
        f"{workflow_path}\n\n"
        "You are acting as the external codex reflection backend for AutoSkill self-evolve.\n"
        "The authoritative reflection instruction set is the exact system prompt below.\n"
        "Follow it strictly. Do not add any extra text outside the final JSON object.\n\n"
        "=== EXACT REFLECTION SYSTEM PROMPT BEGIN ===\n"
        f"{system_prompt}\n"
        "=== EXACT REFLECTION SYSTEM PROMPT END ===\n\n"
        "The reflection input JSON was already produced by build_reflection_input(...).\n"
        f"Read it directly from this file path:\n{input_json_path}\n\n"
        "Use the workflow document and that reflection_input.json as your only task inputs.\n"
        "Return only one strict JSON object matching the exact schema required by the reflection system prompt."
    )


def _normalize_output_file(path: Path) -> None:
    raw_text = path.read_text(encoding="utf-8")
    payload = normalize_patch_payload(_extract_json_object(raw_text))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


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


def _build_codex_env(*, preserve_openai_env: bool | None = None) -> dict:
    env = dict(os.environ)
    preserve = preserve_openai_env
    if preserve is None:
        preserve = str(os.getenv("CODEX_PRESERVE_OPENAI_ENV", "") or "").strip().lower() in {"1", "true", "yes"}
    if preserve:
        return env
    for key in _CODEX_CLI_ENV_BLOCKLIST:
        env.pop(key, None)
    return env


def _retry_delay_seconds(attempt_index: int) -> int:
    attempt = max(1, int(attempt_index or 1))
    return min(20, 3 * attempt)


def _temp_output_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".tmp")


def run_codex_reflection_backend(
    *,
    input_path: Path,
    output_path: Path,
    model: str,
    max_retries: int,
    codex_cli_path: str = "",
    exec_cwd: str = "",
    preserve_openai_env: bool | None = None,
    print_progress: bool = True,
) -> Dict[str, Any]:
    input_path = Path(str(input_path)).expanduser().resolve()
    output_path = Path(str(output_path)).expanduser().resolve()
    workflow_path = _workflow_path()
    codex_cli = _resolve_codex_cli(codex_cli_path)
    prompt = _build_codex_prompt(
        workflow_path=workflow_path,
        input_json_path=input_path,
    )
    if print_progress:
        _print_header("Codex Reflection")
        _print_detail(
            "[codex-reflection-start] "
            f"model={str(model)} "
            f"max_retries={int(max_retries or 0)} "
            f"codex_cli={_display_path(codex_cli)} "
            f"input_json={_display_path(input_path)} "
            f"output_json={_display_path(output_path)} "
            f"workflow_md={_display_path(workflow_path)} "
            "system_prompt=build_reflection_system_prompt "
            "input_mode=file_reference"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        codex_cli,
        "exec",
        "--full-auto",
        "-C",
        str(Path(str(exec_cwd or _repo_root())).expanduser().resolve()),
        "-m",
        str(model),
        "-o",
        str(_temp_output_path(output_path)),
        "-",
    ]
    max_attempts = max(1, int(max_retries or 0))
    stdout_log = output_path.parent / "codex_exec.stdout.log"
    stderr_log = output_path.parent / "codex_exec.stderr.log"
    tmp_output_path = _temp_output_path(output_path)
    last_completed: subprocess.CompletedProcess[str] | None = None
    combined_stdout_parts = []
    combined_stderr_parts = []
    env = dict(_build_codex_env(preserve_openai_env=preserve_openai_env))
    for attempt in range(1, max_attempts + 1):
        if tmp_output_path.exists():
            tmp_output_path.unlink()
        completed = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            env=env,
        )
        last_completed = completed
        combined_stdout_parts.append(
            f"\n===== attempt {attempt}/{max_attempts} stdout =====\n{completed.stdout or ''}"
        )
        combined_stderr_parts.append(
            f"\n===== attempt {attempt}/{max_attempts} stderr =====\n{completed.stderr or ''}"
        )
        if completed.returncode == 0:
            break
        if tmp_output_path.exists():
            tmp_output_path.unlink()
        if attempt >= max_attempts:
            break
        delay_seconds = _retry_delay_seconds(attempt)
        if print_progress:
            _print_detail(
                "[codex-reflection-retry] "
                f"attempt={attempt}/{max_attempts} "
                f"returncode={completed.returncode} "
                f"sleep={delay_seconds}s"
            )
        time.sleep(delay_seconds)

    if last_completed is None or last_completed.returncode != 0:
        if tmp_output_path.exists():
            tmp_output_path.unlink()
        _write_text(stdout_log, "".join(combined_stdout_parts))
        _write_text(stderr_log, "".join(combined_stderr_parts))
        final_code = last_completed.returncode if last_completed is not None else -1
        raise SystemExit(
            "codex exec failed after retries; "
            f"stdout_log={stdout_log} stderr_log={stderr_log} returncode={final_code}"
        )
    if not tmp_output_path.is_file():
        _write_text(stdout_log, "".join(combined_stdout_parts))
        _write_text(stderr_log, "".join(combined_stderr_parts))
        raise SystemExit(
            "codex exec succeeded but temporary output file is missing; "
            f"tmp_output={tmp_output_path} stdout_log={stdout_log} stderr_log={stderr_log}"
        )
    raw_text = tmp_output_path.read_text(encoding="utf-8")
    payload = normalize_patch_payload(_extract_json_object(raw_text))
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_output_path.unlink()
    _write_text(stdout_log, "".join(combined_stdout_parts))
    _write_text(stderr_log, "".join(combined_stderr_parts))
    if print_progress:
        _print_detail(
            "[codex-reflection-codex-done] "
            f"output_json={_display_path(output_path)}"
        )
        _print_detail(
            "[codex-reflection-normalized] "
            f"output_json={_display_path(output_path)}"
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run one Codex-backed self-evolve reflection round.")
    p.add_argument("input_json", nargs="?", default="")
    p.add_argument("output_json", nargs="?", default="")
    p.add_argument("--input-json", dest="input_json_flag", default="")
    p.add_argument("--output-json", dest="output_json_flag", default="")
    p.add_argument("--model", default=os.getenv("CODEX_REFLECTION_MODEL", "gpt-5.4"))
    p.add_argument(
        "--max-retries",
        type=int,
        default=int(
            os.getenv(
                "AUTOSKILL_CODEX_REFLECTION_MAX_RETRIES",
                os.getenv("CODEX_REFLECTION_MAX_RETRIES", "3"),
            )
            or 3
        ),
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    input_raw = str(args.input_json_flag or args.input_json or "").strip()
    output_raw = str(args.output_json_flag or args.output_json or "").strip()
    if not input_raw or not output_raw:
        raise SystemExit("usage: run_codex_reflection.py <input_json> <output_json>")

    run_codex_reflection_backend(
        input_path=Path(input_raw).expanduser().resolve(),
        output_path=Path(output_raw).expanduser().resolve(),
        model=str(args.model),
        max_retries=int(args.max_retries or 0),
    )


if __name__ == "__main__":
    main()
