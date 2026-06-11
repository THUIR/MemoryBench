from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List
import hashlib
import json
import re


_SLUG_RE = re.compile(r"[^\w-]+", re.UNICODE)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not path.is_file():
        return dict(default or {})
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return dict(default or {})


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        for item in rows:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.is_file():
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = str(line or "").strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def stable_hash(payload: Any) -> str:
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def slugify(text: str, *, limit: int = 64) -> str:
    s = str(text or "").strip().lower().replace("/", "-").replace("\\", "-")
    s = _SLUG_RE.sub("-", s).strip("-_")
    if not s:
        s = "lineage"
    return s[: max(1, int(limit))]
