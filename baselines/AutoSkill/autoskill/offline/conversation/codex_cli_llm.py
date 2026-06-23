"""
Codex CLI-backed LLM connector for offline conversation flows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from autoskill.llm.base import LLM


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


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _parse_bool_text(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _truncate_text(text: str, *, limit: int = 600) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "...(truncated)"


def _resolve_codex_cli(config: Dict[str, Any]) -> str:
    candidates = []
    explicit = str(config.get("codex_cli_path") or "").strip()
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
    raise ValueError(
        "Unable to locate the Codex CLI. Set --codex-cli-path or CODEX_CLI_PATH."
    )


def _build_codex_env(*, preserve_openai_env: bool) -> Dict[str, str]:
    env = dict(os.environ)
    if preserve_openai_env:
        return env
    for key in _CODEX_CLI_ENV_BLOCKLIST:
        env.pop(key, None)
    return env


def _retry_delay_seconds(attempt_index: int) -> int:
    attempt = max(1, int(attempt_index or 1))
    return min(20, 2 * attempt)


def _build_prompt(*, system: str | None, user: str, temperature: float) -> str:
    parts = [
        "You are acting as a drop-in LLM backend for AutoSkill.",
        "Treat the SYSTEM MESSAGE as the highest-priority instruction set.",
        "Then answer the USER MESSAGE exactly as the target assistant would.",
        "Return only the assistant response body.",
        "Do not add wrappers, explanations, or code fences unless the SYSTEM MESSAGE or USER MESSAGE explicitly requires them.",
    ]
    if str(system or "").strip():
        parts.extend(
            [
                "",
                "=== SYSTEM MESSAGE BEGIN ===",
                str(system),
                "=== SYSTEM MESSAGE END ===",
            ]
        )
    parts.extend(
        [
            "",
            "=== USER MESSAGE BEGIN ===",
            str(user),
            "=== USER MESSAGE END ===",
            "",
            f"Caller temperature hint: {float(temperature):.3f}",
        ]
    )
    return "\n".join(parts).strip() + "\n"


class CodexCliLLM(LLM):
    def __init__(self, config: Dict[str, Any]) -> None:
        self._config = dict(config or {})
        self._model = str(self._config.get("model") or "gpt-5.4").strip() or "gpt-5.4"
        self._timeout_s = max(1, _safe_int(self._config.get("timeout_s"), 900))
        self._max_retries = max(1, _safe_int(self._config.get("codex_max_retries"), 1))
        self._full_auto = _parse_bool_text(self._config.get("codex_full_auto"), True)
        self._preserve_openai_env = _parse_bool_text(
            self._config.get("codex_preserve_openai_env"),
            False,
        )
        self._exec_cwd = str(self._config.get("codex_exec_cwd") or "").strip()
        self._codex_cli = _resolve_codex_cli(self._config)

    def complete(
        self,
        *,
        system: str | None,
        user: str,
        temperature: float = 0.0,
    ) -> str:
        prompt = _build_prompt(system=system, user=user, temperature=temperature)
        workdir = Path(self._exec_cwd).expanduser().resolve() if self._exec_cwd else Path.cwd().resolve()
        with tempfile.TemporaryDirectory(prefix="autoskill-codex-llm-", dir="/tmp") as tmp_dir:
            output_path = Path(tmp_dir) / "codex_output.txt"
            cmd = [
                self._codex_cli,
                "exec",
                "-C",
                str(workdir),
                "-m",
                self._model,
                "-o",
                str(output_path),
                "-",
            ]
            if self._full_auto:
                cmd.insert(2, "--full-auto")

            last_error = ""
            for attempt in range(1, self._max_retries + 1):
                completed = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=self._timeout_s,
                    env=_build_codex_env(preserve_openai_env=self._preserve_openai_env),
                )
                if completed.returncode == 0 and output_path.is_file():
                    return output_path.read_text(encoding="utf-8")
                stdout_text = _truncate_text(completed.stdout)
                stderr_text = _truncate_text(completed.stderr)
                last_error = (
                    f"codex exec failed attempt={attempt}/{self._max_retries} "
                    f"returncode={completed.returncode} "
                    f"cwd={_display_path(workdir)} "
                    f"stdout={stdout_text or '-'} "
                    f"stderr={stderr_text or '-'}"
                )
                if attempt < self._max_retries:
                    time.sleep(_retry_delay_seconds(attempt))

            raise RuntimeError(last_error or "codex exec failed without details")


def build_codex_llm(config: Dict[str, Any]) -> LLM:
    return CodexCliLLM(config)
