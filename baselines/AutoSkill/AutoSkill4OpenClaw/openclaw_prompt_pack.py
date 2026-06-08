"""
Shared OpenClaw prompt pack loader for sidecar + embedded paths.

The prompt pack is a text file with sections:
  @@version <version>
  @@block <name>
  ...
  @@end
  @@template <name>
  ...
  @@end

Templates may reference:
  {{block.<name>}}  -> inline block content
  {{var.<name>}}    -> render-time variable value
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_TOKEN_RE = re.compile(r"\{\{([a-zA-Z0-9_.:-]+)\}\}")
_MAX_RENDER_DEPTH = 12

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {
    "path": "",
    "mtime_ns": -1,
    "pack": None,
}


def _default_prompt_pack_path() -> Path:
    """Returns the default prompt pack path bundled with the plugin adapter."""
    return Path(__file__).resolve().parent / "adapter" / "openclaw_prompt_pack.txt"


def _resolve_prompt_pack_path(explicit_path: str = "") -> Path:
    """Resolves prompt-pack path by explicit arg/env/default candidates."""
    candidates = []
    explicit = str(explicit_path or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    env_path = str(os.getenv("AUTOSKILL_OPENCLAW_PROMPT_PACK_PATH", "") or "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())

    repo_dir = str(os.getenv("AUTOSKILL_REPO_DIR", "") or "").strip()
    if repo_dir:
        candidates.append(
            Path(repo_dir).expanduser() / "AutoSkill4OpenClaw" / "adapter" / "openclaw_prompt_pack.txt"
        )

    candidates.append(_default_prompt_pack_path())

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists():
            return resolved

    # Keep deterministic fallback even when file is missing.
    return _default_prompt_pack_path()


def _parse_prompt_pack(raw: str) -> Dict[str, Any]:
    """Parses custom prompt-pack text format into version/blocks/templates."""
    version = ""
    blocks: Dict[str, str] = {}
    templates: Dict[str, str] = {}

    mode = ""
    name = ""
    buf = []

    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not mode and stripped.startswith("@@version "):
            version = stripped[len("@@version ") :].strip()
            continue
        if not mode and stripped.startswith("@@block "):
            mode = "block"
            name = stripped[len("@@block ") :].strip()
            buf = []
            continue
        if not mode and stripped.startswith("@@template "):
            mode = "template"
            name = stripped[len("@@template ") :].strip()
            buf = []
            continue
        if mode and stripped == "@@end":
            text = "\n".join(buf).strip("\n")
            if mode == "block" and name:
                blocks[name] = text
            elif mode == "template" and name:
                templates[name] = text
            mode = ""
            name = ""
            buf = []
            continue
        if mode:
            buf.append(line)

    return {
        "version": str(version or "").strip(),
        "blocks": blocks,
        "templates": templates,
    }


def _load_prompt_pack(path: Path) -> Optional[Dict[str, Any]]:
    """Loads and caches prompt pack by path/mtime."""
    p = Path(path).expanduser()
    try:
        stat = p.stat()
    except Exception:
        return None
    mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
    key = str(p.resolve())

    with _CACHE_LOCK:
        if _CACHE.get("path") == key and int(_CACHE.get("mtime_ns", -1)) == mtime_ns:
            cached = _CACHE.get("pack")
            return dict(cached) if isinstance(cached, dict) else None

    try:
        raw = p.read_text(encoding="utf-8")
    except Exception:
        return None

    try:
        parsed = _parse_prompt_pack(raw)
    except Exception:
        return None

    with _CACHE_LOCK:
        _CACHE["path"] = key
        _CACHE["mtime_ns"] = mtime_ns
        _CACHE["pack"] = dict(parsed)
    return parsed


def _render_text(
    text: str,
    *,
    blocks: Dict[str, str],
    variables: Dict[str, Any],
    depth: int = 0,
) -> str:
    """Renders one template text with block/var substitutions."""
    if depth >= _MAX_RENDER_DEPTH:
        return str(text or "")
    src = str(text or "")

    def _replace(match: re.Match[str]) -> str:
        token = str(match.group(1) or "").strip()
        if not token:
            return ""
        if token.startswith("var."):
            name = token[len("var.") :].strip()
            return str(variables.get(name, ""))
        if token.startswith("block."):
            name = token[len("block.") :].strip()
            block_text = blocks.get(name)
            if block_text is None:
                return ""
            return _render_text(
                block_text,
                blocks=blocks,
                variables=variables,
                depth=depth + 1,
            )
        return match.group(0)

    return _TOKEN_RE.sub(_replace, src)


def render_openclaw_prompt(
    template_key: str,
    *,
    variables: Optional[Dict[str, Any]] = None,
    fallback: str = "",
    prompt_pack_path: str = "",
) -> str:
    """
    Renders one template from the shared prompt pack.

    Returns fallback when prompt pack is unavailable, malformed, or missing the key.
    """
    key = str(template_key or "").strip()
    if not key:
        return str(fallback or "")
    pack = _load_prompt_pack(_resolve_prompt_pack_path(prompt_pack_path))
    if not isinstance(pack, dict):
        return str(fallback or "")
    templates = pack.get("templates")
    blocks = pack.get("blocks")
    if not isinstance(templates, dict) or not isinstance(blocks, dict):
        return str(fallback or "")
    raw = templates.get(key)
    if not isinstance(raw, str) or not raw.strip():
        return str(fallback or "")
    vars_map = dict(variables or {})
    try:
        rendered = _render_text(raw, blocks=blocks, variables=vars_map)
    except Exception:
        return str(fallback or "")
    return rendered or str(fallback or "")


def get_openclaw_prompt_pack_info(prompt_pack_path: str = "") -> Tuple[str, str]:
    """
    Returns (version, path) for observability.

    Empty values mean pack is unavailable.
    """
    path = _resolve_prompt_pack_path(prompt_pack_path)
    pack = _load_prompt_pack(path)
    if not isinstance(pack, dict):
        return "", str(path)
    version = str(pack.get("version") or "").strip()
    return version, str(path)

