"""
Generic offline file loader.

Loads either a single file or all files under a directory, and returns each file
as one text unit so offline extraction can process heterogeneous sources without
strict schema assumptions.

Current support is text-first:
- plain text / markdown / json / jsonl can be read directly
- `.doc` / `.docx` rely on local conversion tools when available
- unsupported binary files are skipped instead of being ingested as garbage text
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Tuple

_KNOWN_BINARY_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".pyc",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".npy",
    ".npz",
}
_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".runtime",
}
_GENERATED_VISIBLE_TREE_FILES = {
    "children_manifest.json",
    "children_map.md",
    "evidence.md",
    "evidence_manifest.json",
    "domain_manifest.json",
    "library_manifest.json",
}
_GENERATED_VISIBLE_TREE_DIRS = {
    "总技能",
    "一级技能",
    "二级技能",
    "微技能",
    "子技能",
    "Family技能",
}


def load_file_units(path: str, *, max_files: int = 0) -> Tuple[List[Dict[str, str]], str]:
    """
    Returns (units, abs_input_path), where each unit has:
    - title: display name (relative path if directory)
    - text: file content as text
    - source_file: absolute file path
    """

    abs_path = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not abs_path:
        return [], ""
    if os.path.isfile(abs_path):
        if _looks_like_generated_visible_artifact(abs_path):
            return [], abs_path
        text = _read_any_file_as_text(abs_path)
        if not text.strip():
            return [], abs_path
        return (
            [
                {
                    "title": os.path.basename(abs_path),
                    "text": text,
                    "source_file": abs_path,
                }
            ],
            abs_path,
        )
    if not os.path.isdir(abs_path):
        raise ValueError(f"path not found: {abs_path}")

    files: List[str] = []
    for root, dirnames, names in os.walk(abs_path):
        dirnames[:] = [
            dirname
            for dirname in sorted(dirnames)
            if not dirname.startswith(".") and dirname not in _SKIP_DIR_NAMES
        ]
        for name in sorted(names):
            if name.startswith("."):
                continue
            p = os.path.join(root, name)
            if os.path.isfile(p) and not _looks_like_generated_visible_artifact(p):
                files.append(p)
                if int(max_files or 0) > 0 and len(files) >= int(max_files):
                    break
        if int(max_files or 0) > 0 and len(files) >= int(max_files):
            break
    files.sort()

    out: List[Dict[str, str]] = []
    for p in files:
        text = _read_any_file_as_text(p)
        if not text.strip():
            continue
        rel = os.path.relpath(p, abs_path)
        out.append(
            {
                "title": rel,
                "text": text,
                "source_file": p,
            }
        )
    return out, abs_path


def _looks_like_generated_visible_artifact(path: str) -> bool:
    """Skips generated visible-skill-tree artifacts when scanning source documents."""

    abs_path = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not abs_path:
        return False
    basename = os.path.basename(abs_path)
    parts = [part for part in abs_path.replace("\\", "/").split("/") if part]
    if ".runtime" in parts:
        return True
    if basename in _GENERATED_VISIBLE_TREE_FILES:
        return True
    parts_set = set(parts)
    if basename == "SKILL.md" and (_GENERATED_VISIBLE_TREE_DIRS & parts_set):
        return True
    if basename == "README.md":
        root_dir = os.path.dirname(abs_path)
        manifest_path = os.path.join(root_dir, ".runtime", "library_manifest.json")
        if os.path.isfile(manifest_path):
            return True
    return False


def data_to_text_unit(data: Any, *, title: str = "inline_data") -> Dict[str, str]:
    """
    Converts arbitrary in-memory data into one text unit.
    """

    txt = _to_text(data).strip()
    return {
        "title": str(title or "inline_data"),
        "text": txt,
        "source_file": "",
    }


def _read_any_file_as_text(path: str, *, max_bytes: int = 8_000_000) -> str:
    """Reads one file as text when the file format appears text-like."""

    ext = os.path.splitext(path)[1].lower()
    if ext in {".doc", ".docx"}:
        txt = _read_word_document(path)
        if txt.strip():
            return txt
    elif ext in _KNOWN_BINARY_EXTENSIONS:
        return ""

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        pass

    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
    except Exception:
        return ""

    if _looks_binary(raw):
        return ""

    text = raw.decode("utf-8", errors="ignore").replace("\x00", "").strip()
    if text:
        return text
    text2 = raw.decode("latin-1", errors="ignore").replace("\x00", "").strip()
    if text2:
        return text2
    return ""


def _looks_binary(raw: bytes) -> bool:
    """Heuristically decides whether a byte stream is binary-like."""

    if not raw:
        return False
    sample = raw[:2048]
    if b"\x00" in sample:
        return True
    nontext = 0
    for byte in sample:
        if byte in {9, 10, 12, 13}:
            continue
        if 32 <= byte <= 126:
            continue
        nontext += 1
    return nontext / max(1, len(sample)) > 0.30


def _read_word_document(path: str) -> str:
    """Reads `.doc` / `.docx` content through local conversion tools when present."""

    # macOS built-in converter.
    out = _run_text_command(["textutil", "-convert", "txt", "-stdout", path], timeout_s=20)
    if out.strip():
        return out
    # Common Linux tools.
    out = _run_text_command(["antiword", path], timeout_s=20)
    if out.strip():
        return out
    out = _run_text_command(["catdoc", path], timeout_s=20)
    if out.strip():
        return out
    return ""


def _run_text_command(argv: List[str], *, timeout_s: int) -> str:
    """Runs one external text-conversion command and returns stdout on success."""

    if not argv:
        return ""
    bin_name = str(argv[0] or "").strip()
    if not bin_name:
        return ""
    if shutil.which(bin_name) is None:
        return ""
    try:
        cp = subprocess.run(
            argv,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=int(timeout_s),
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if cp.returncode != 0:
            return ""
        return str(cp.stdout or "").strip()
    except Exception:
        return ""


def _to_text(obj: Any) -> str:
    """Converts arbitrary structured inline input into a plain text block."""

    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float, bool)):
        return str(obj)
    if isinstance(obj, list):
        return "\n".join(_to_text(x) for x in obj)
    if isinstance(obj, dict):
        parts: List[str] = []
        for k, v in obj.items():
            parts.append(f"{k}: {_to_text(v)}")
        return "\n".join(parts)
    return str(obj)
