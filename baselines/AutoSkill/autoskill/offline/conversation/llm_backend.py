"""
Local LLM backend helpers for offline conversation flows.
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Dict, Optional

from autoskill.offline.provider_config import (
    build_llm_config as _build_provider_llm_config,
    pick_default_provider as _pick_default_provider,
)

from .utils.ban_mock import ensure_llm_config_not_mock, ensure_not_mock


CODEX_PROVIDER = "codex"
CODEX_CONNECTOR_FACTORY = "autoskill.offline.conversation.codex_cli_llm:build_codex_llm"


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value is not None and value.strip() else default


def _parse_bool_text(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def is_codex_provider(provider: Any) -> bool:
    value = str(provider or "").strip().lower()
    return value in {"codex", "codex-cli", "codex_cli"}


def embeddings_parent_provider(llm_provider: Any) -> str:
    provider = str(llm_provider or "").strip().lower() or "mock"
    if not is_codex_provider(provider):
        return provider
    hint = str(
        _env(
            "AUTOSKILL_EMBEDDINGS_LLM_PROVIDER_HINT",
            _env("AUTOSKILL_CODEX_EMBEDDINGS_PROVIDER_HINT", ""),
        )
    ).strip().lower()
    if hint:
        return hint
    return str(_pick_default_provider() or "mock").strip().lower() or "mock"


def add_codex_llm_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--codex-cli-path",
        default=_env("CODEX_CLI_PATH", ""),
        help="Optional path to Codex CLI when llm-provider=codex.",
    )
    parser.add_argument(
        "--codex-exec-cwd",
        default=_env("AUTOSKILL_CODEX_EXEC_CWD", ""),
        help="Optional working directory for Codex LLM runs.",
    )
    parser.add_argument(
        "--codex-timeout-s",
        type=int,
        default=_safe_int(_env("AUTOSKILL_CODEX_TIMEOUT_S", "900"), 900),
        help="Timeout for each Codex LLM completion in seconds.",
    )
    parser.add_argument(
        "--codex-max-retries",
        type=int,
        default=_safe_int(_env("AUTOSKILL_CODEX_MAX_RETRIES", "1"), 1),
        help="Retry count for Codex-backed llm.complete calls.",
    )
    parser.add_argument(
        "--codex-full-auto",
        default=_env("AUTOSKILL_CODEX_FULL_AUTO", "1"),
        help="1|0. Pass --full-auto to `codex exec` when enabled.",
    )
    parser.add_argument(
        "--codex-preserve-openai-env",
        default=_env("CODEX_PRESERVE_OPENAI_ENV", "0"),
        help="1|0. Preserve OpenAI/proxy env vars when invoking Codex CLI.",
    )
    return parser


def build_conversation_llm_config(
    *,
    provider: Any,
    model: Optional[str],
    base_url: Any = "",
    api_key: Any = "",
    auth_mode: Any = "",
    codex_cli_path: Any = "",
    codex_exec_cwd: Any = "",
    codex_timeout_s: Any = 0,
    codex_max_retries: Any = 0,
    codex_full_auto: Any = "1",
    codex_preserve_openai_env: Any = "0",
    where: str,
) -> Dict[str, Any]:
    provider_text = str(provider or _pick_default_provider()).strip() or "mock"
    ensure_not_mock(provider_text, where=f"{where}(provider)")
    model_text = str(model or "").strip() or None

    if is_codex_provider(provider_text):
        timeout_s = _safe_int(codex_timeout_s, _safe_int(_env("AUTOSKILL_CODEX_TIMEOUT_S", "900"), 900))
        max_retries = _safe_int(codex_max_retries, _safe_int(_env("AUTOSKILL_CODEX_MAX_RETRIES", "1"), 1))
        cfg = {
            "provider": CODEX_PROVIDER,
            "model": model_text or _env("AUTOSKILL_CODEX_MODEL", "gpt-5.4"),
            "connector_factory": CODEX_CONNECTOR_FACTORY,
            "codex_cli_path": str(codex_cli_path or _env("CODEX_CLI_PATH", "")).strip(),
            "codex_exec_cwd": str(codex_exec_cwd or _env("AUTOSKILL_CODEX_EXEC_CWD", "")).strip(),
            "timeout_s": max(1, int(timeout_s)),
            "codex_max_retries": max(1, int(max_retries)),
            "codex_full_auto": _parse_bool_text(
                codex_full_auto if str(codex_full_auto or "").strip() else _env("AUTOSKILL_CODEX_FULL_AUTO", "1"),
                True,
            ),
            "codex_preserve_openai_env": _parse_bool_text(
                codex_preserve_openai_env
                if str(codex_preserve_openai_env or "").strip()
                else _env("CODEX_PRESERVE_OPENAI_ENV", "0"),
                False,
            ),
        }
        return cfg

    cfg = _build_provider_llm_config(provider_text, model=model_text)
    ensure_llm_config_not_mock(cfg, where=f"{where}(cfg)")
    if str(base_url or "").strip():
        cfg["base_url"] = str(base_url).strip()
    if str(api_key or "").strip():
        cfg["api_key"] = str(api_key).strip()
    if str(auth_mode or "").strip():
        cfg["auth_mode"] = str(auth_mode).strip()
    return cfg


def build_conversation_llm_config_from_args(
    args: argparse.Namespace,
    *,
    provider_attr: str = "llm_provider",
    model_attr: str = "llm_model",
    base_url_attr: str = "llm_base_url",
    api_key_attr: str = "llm_api_key",
    auth_mode_attr: str = "auth_mode",
    where: str,
) -> Dict[str, Any]:
    return build_conversation_llm_config(
        provider=getattr(args, provider_attr, ""),
        model=(str(getattr(args, model_attr, "") or "").strip() or None),
        base_url=getattr(args, base_url_attr, ""),
        api_key=getattr(args, api_key_attr, ""),
        auth_mode=getattr(args, auth_mode_attr, ""),
        codex_cli_path=getattr(args, "codex_cli_path", ""),
        codex_exec_cwd=getattr(args, "codex_exec_cwd", ""),
        codex_timeout_s=getattr(args, "codex_timeout_s", 0),
        codex_max_retries=getattr(args, "codex_max_retries", 0),
        codex_full_auto=getattr(args, "codex_full_auto", "1"),
        codex_preserve_openai_env=getattr(args, "codex_preserve_openai_env", "0"),
        where=where,
    )
