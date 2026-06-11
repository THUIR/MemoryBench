"""
Local provenance index for offline conversation skill extraction.

This module keeps a durable mapping from one extracted/updated skill to the
conversation units that contributed to it, without modifying the core skill
artifact format.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


_WS_RE = re.compile(r"\s+")
_MAX_SOURCES_PER_SKILL = 500
_MAX_HISTORY_PER_SKILL = 500


def conversation_provenance_path(*, sdk: Any, user_id: str) -> str:
    """
    Returns the local provenance index path for one user's offline conversation imports.

    Stored under:
    - <store_root>/index/offline_conversation_provenance_<user>.json
    """

    root = ""
    store = getattr(sdk, "store", None)
    root = str(getattr(store, "path", "") or "").strip()
    if not root:
        cfg = dict(getattr(getattr(sdk, "config", None), "store", {}) or {})
        root = str(cfg.get("path") or "").strip()
    if not root:
        root = "SkillBank"
    root_abs = os.path.abspath(os.path.expanduser(root))
    idx_dir = os.path.join(root_abs, "index")
    safe_user = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(user_id or "u1").strip() or "u1")
    return os.path.join(idx_dir, f"offline_conversation_provenance_{safe_user}.json")


def load_skill_conversation_provenance(
    *,
    sdk: Any,
    user_id: str,
    skill_id: str,
    max_sources: int = 100,
    max_history: int = 100,
) -> Dict[str, Any]:
    """Loads one skill's offline conversation provenance summary."""

    store = ConversationProvenanceStore(
        path=conversation_provenance_path(sdk=sdk, user_id=user_id),
        user_id=user_id,
    )
    return store.get_skill_record(
        skill_id=str(skill_id or "").strip(),
        max_sources=max_sources,
        max_history=max_history,
    )


class ConversationProvenanceStore:
    """Durable per-user index from skill ids to source conversation units."""

    def __init__(self, *, path: str, user_id: str) -> None:
        self.path = str(path or "").strip()
        self.user_id = str(user_id or "").strip() or "u1"
        self.data: Dict[str, Any] = {
            "version": 1,
            "user_id": self.user_id,
            "skills": {},
            "lineages": {},
        }
        self._pending_updates = 0
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                self.data = obj
        except Exception:
            pass

    def save(self) -> None:
        """Atomically persists the provenance index."""

        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        self._pending_updates = 0

    def maybe_save(self, *, interval: int = 20) -> None:
        """Checkpoint-saves after a bounded number of updates."""

        if self._pending_updates >= max(1, int(interval or 1)):
            self.save()

    def summary(self) -> Dict[str, Any]:
        """Returns a compact summary for CLI/API responses."""

        skills = dict(self.data.get("skills") or {})
        return {
            "path": self.path,
            "skill_count": len(skills),
            "skills": [
                {
                    "skill_id": sid,
                    "name": str((row or {}).get("name") or ""),
                    "version": str((row or {}).get("current_version") or ""),
                    "source_count": int((row or {}).get("source_count", 0) or 0),
                    "history_count": int((row or {}).get("history_count", 0) or 0),
                }
                for sid, row in skills.items()
            ],
        }

    def get_skill_record(
        self,
        *,
        skill_id: str,
        max_sources: int = 100,
        max_history: int = 100,
    ) -> Dict[str, Any]:
        """Returns one skill's provenance record with bounded lists."""

        sid = str(skill_id or "").strip()
        if not sid:
            return {}
        row = dict((self.data.get("skills") or {}).get(sid) or {})
        if not row:
            return {}
        out = copy.deepcopy(row)
        sources = list(out.get("sources") or [])
        sources.sort(key=lambda x: int((x or {}).get("last_seen_at_ms", 0) or 0), reverse=True)
        out["sources"] = sources[: max(1, int(max_sources or 1))]
        history = list(out.get("history") or [])
        history.sort(key=lambda x: int((x or {}).get("timestamp_ms", 0) or 0), reverse=True)
        out["history"] = history[: max(1, int(max_history or 1))]
        return out

    def record_skill_update(
        self,
        *,
        skill: Any,
        lineage_key: str,
        source_ref: Dict[str, Any],
    ) -> None:
        """Appends one skill-version provenance event and updates source aggregation."""

        sid = str(getattr(skill, "id", "") or "").strip()
        if not sid:
            return
        now_ms = _now_ms()
        now_iso = _now_iso()
        skills = self.data.setdefault("skills", {})
        lineages = self.data.setdefault("lineages", {})
        row = skills.setdefault(
            sid,
            {
                "skill_id": sid,
                "name": "",
                "current_version": "",
                "lineage_key": "",
                "updated_at": "",
                "updated_at_ms": 0,
                "source_count": 0,
                "history_count": 0,
                "sources": [],
                "history": [],
            },
        )

        row["skill_id"] = sid
        row["name"] = str(getattr(skill, "name", "") or "")
        row["current_version"] = str(getattr(skill, "version", "") or "")
        row["lineage_key"] = str(lineage_key or "").strip()
        row["updated_at"] = now_iso
        row["updated_at_ms"] = now_ms
        if row["lineage_key"]:
            lineages[row["lineage_key"]] = sid

        src = _normalize_source_ref(source_ref)
        if src:
            self._merge_source_row(row=row, source_ref=src, now_iso=now_iso, now_ms=now_ms)
            self._append_history_event(row=row, source_ref=src, now_iso=now_iso, now_ms=now_ms)
        row["source_count"] = len(list(row.get("sources") or []))
        row["history_count"] = len(list(row.get("history") or []))
        self._pending_updates += 1

    def _merge_source_row(
        self,
        *,
        row: Dict[str, Any],
        source_ref: Dict[str, Any],
        now_iso: str,
        now_ms: int,
    ) -> None:
        sources = list(row.get("sources") or [])
        key = str(source_ref.get("conversation_key") or "").strip()
        found = None
        for item in sources:
            if str((item or {}).get("conversation_key") or "").strip() == key:
                found = item
                break
        if found is None:
            found = dict(source_ref)
            found["first_seen_at"] = now_iso
            found["first_seen_at_ms"] = now_ms
            found["last_seen_at"] = now_iso
            found["last_seen_at_ms"] = now_ms
            found["seen_count"] = 1
            sources.append(found)
        else:
            found.update({k: v for k, v in source_ref.items() if v not in (None, "", [])})
            found["last_seen_at"] = now_iso
            found["last_seen_at_ms"] = now_ms
            found["seen_count"] = int(found.get("seen_count", 0) or 0) + 1

        sources.sort(key=lambda x: int((x or {}).get("last_seen_at_ms", 0) or 0), reverse=True)
        row["sources"] = sources[:_MAX_SOURCES_PER_SKILL]

    def _append_history_event(
        self,
        *,
        row: Dict[str, Any],
        source_ref: Dict[str, Any],
        now_iso: str,
        now_ms: int,
    ) -> None:
        history = list(row.get("history") or [])
        event = {
            "timestamp": now_iso,
            "timestamp_ms": now_ms,
            "version": str(row.get("current_version") or ""),
            "name": str(row.get("name") or ""),
            "lineage_key": str(row.get("lineage_key") or ""),
            "conversation_key": str(source_ref.get("conversation_key") or ""),
            "source_file": str(source_ref.get("source_file") or ""),
            "conversation_index": source_ref.get("conversation_index"),
            "import_index": source_ref.get("import_index"),
            "title": str(source_ref.get("title") or ""),
            "locator": str(source_ref.get("locator") or ""),
            "primary_user_questions_preview": str(source_ref.get("primary_user_questions_preview") or ""),
        }
        if history:
            last = dict(history[-1] or {})
            if (
                str(last.get("version") or "") == event["version"]
                and str(last.get("conversation_key") or "") == event["conversation_key"]
                and str(last.get("name") or "") == event["name"]
            ):
                last["timestamp"] = now_iso
                last["timestamp_ms"] = now_ms
                last["repeat_count"] = int(last.get("repeat_count", 1) or 1) + 1
                history[-1] = last
                row["history"] = history[-_MAX_HISTORY_PER_SKILL:]
                return
        event["repeat_count"] = 1
        history.append(event)
        row["history"] = history[-_MAX_HISTORY_PER_SKILL:]


def _normalize_source_ref(source_ref: Dict[str, Any]) -> Dict[str, Any]:
    src = dict(source_ref or {})
    source_file = str(src.get("source_file") or "").strip()
    title = str(src.get("title") or "").strip()
    conv_idx = src.get("conversation_index")
    try:
        conv_idx = int(conv_idx) if conv_idx is not None else None
    except Exception:
        conv_idx = None
    import_idx = src.get("import_index")
    try:
        import_idx = int(import_idx) if import_idx is not None else None
    except Exception:
        import_idx = None
    preview = _preview_text(str(src.get("primary_user_questions_preview") or ""))
    locator = str(src.get("locator") or "").strip()
    if not locator:
        base = os.path.basename(source_file) if source_file else (title or "conversation")
        if conv_idx is not None and conv_idx >= 0:
            locator = f"{base}#conv_{conv_idx + 1}"
        else:
            locator = base
    key_seed = json.dumps(
        {
            "source_file": source_file,
            "conversation_index": conv_idx,
            "title": title,
            "preview": preview,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "conversation_key": hashlib.sha1(key_seed.encode("utf-8")).hexdigest(),
        "source_file": source_file,
        "conversation_index": conv_idx,
        "import_index": import_idx,
        "title": title,
        "locator": locator,
        "message_count": int(src.get("message_count", 0) or 0),
        "user_turn_count": int(src.get("user_turn_count", 0) or 0),
        "primary_user_questions_preview": preview,
    }


def _preview_text(text: str, limit: int = 240) -> str:
    s = _WS_RE.sub(" ", str(text or "").strip())
    if len(s) <= limit:
        return s
    return s[: max(1, int(limit) - 3)].rstrip() + "..."


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
