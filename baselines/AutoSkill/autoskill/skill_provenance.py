"""
Durable online skill provenance for real-time extraction/update flows.

This index stores which live conversation windows produced or updated a skill,
so downstream tooling can reverse-locate the original chat content from a skill.
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
_MAX_SOURCES_PER_SKILL = 300
_MAX_HISTORY_PER_SKILL = 300
_MAX_MESSAGES_PER_EVENT = 200
_MAX_EVENTS_PER_RECORD = 200


def online_skill_provenance_path(*, sdk: Any, user_id: str) -> str:
    """
    Returns the local online provenance index path for one user.

    Stored under:
    - <store_root>/index/online_skill_provenance_<user>.json
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
    return os.path.join(idx_dir, f"online_skill_provenance_{safe_user}.json")


def load_online_skill_provenance(
    *,
    sdk: Any,
    user_id: str,
    skill_id: str,
    max_sources: int = 20,
    max_history: int = 20,
    include_messages: bool = True,
) -> Dict[str, Any]:
    """Loads one skill's provenance record."""

    store = OnlineSkillProvenanceStore(
        path=online_skill_provenance_path(sdk=sdk, user_id=user_id),
        user_id=user_id,
    )
    record = store.get_skill_record(
        skill_id=skill_id,
        max_sources=max_sources,
        max_history=max_history,
        include_messages=include_messages,
    )
    return _enrich_skill_record_live(
        sdk=sdk,
        user_id=user_id,
        skill_id=skill_id,
        record=record,
    )


def record_online_skill_updates(
    *,
    sdk: Any,
    user_id: str,
    updated: List[Any],
    messages: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persists provenance for one online ingestion result."""

    skills = [s for s in list(updated or []) if s is not None]
    if not skills:
        return {"path": online_skill_provenance_path(sdk=sdk, user_id=user_id), "skill_count": 0, "skills": []}

    store = OnlineSkillProvenanceStore(
        path=online_skill_provenance_path(sdk=sdk, user_id=user_id),
        user_id=user_id,
    )
    source_ref = build_online_source_ref(messages=messages, events=events, metadata=metadata)
    for skill in skills:
        store.record_skill_update(
            skill=skill,
            source_ref=source_ref,
            usage_stats=_load_usage_stats_for_skill(sdk=sdk, user_id=user_id, skill_id=str(getattr(skill, "id", "") or "")),
            version_timeline=_build_version_timeline(skill),
        )
        # Persist each update immediately so crash/interruption does not lose the latest event.
        store.save()
    return store.summary()


def sync_online_skill_state(
    *,
    sdk: Any,
    user_id: str,
    skill_ids: Optional[List[str]] = None,
    delete_skill_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Synchronizes persisted provenance rows with live version/usage state immediately."""

    uid = str(user_id or "").strip() or "u1"
    store = OnlineSkillProvenanceStore(
        path=online_skill_provenance_path(sdk=sdk, user_id=uid),
        user_id=uid,
    )
    touched: List[str] = []
    deleted: List[str] = []
    skills_map = store.data.setdefault("skills", {})

    for sid_raw in list(delete_skill_ids or []):
        sid = str(sid_raw or "").strip()
        if not sid:
            continue
        if sid in skills_map:
            skills_map.pop(sid, None)
            deleted.append(sid)

    for sid_raw in list(skill_ids or []):
        sid = str(sid_raw or "").strip()
        if not sid:
            continue
        row = dict(skills_map.get(sid) or {})
        if not row:
            skill = None
            try:
                skill = sdk.get(sid)
            except Exception:
                skill = None
            usage_stats = _load_usage_stats_for_skill(sdk=sdk, user_id=uid, skill_id=sid)
            if skill is None and not usage_stats:
                continue
            row = {
                "skill_id": sid,
                "name": str(getattr(skill, "name", "") or ""),
                "current_version": str(getattr(skill, "version", "") or ""),
                "updated_at": str(getattr(skill, "updated_at", "") or ""),
                "updated_at_ms": 0,
                "source_count": 0,
                "history_count": 0,
                "version_history_count": 0,
                "last_channel": "",
                "last_trigger": "",
                "usage_stats": {},
                "version_timeline": [],
                "sources": [],
                "history": [],
            }
        skills_map[sid] = _enrich_skill_record_live(
            sdk=sdk,
            user_id=uid,
            skill_id=sid,
            record=row,
        )
        touched.append(sid)

    if touched or deleted:
        store.save()
    return {
        "path": store.path,
        "updated": len(touched),
        "deleted": len(deleted),
        "skill_ids": touched,
        "deleted_skill_ids": deleted,
    }


def build_online_source_ref(
    *,
    messages: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds a stable provenance source payload from one ingestion window."""

    md = dict(metadata or {})
    msgs = _normalize_messages(messages)
    evs = _normalize_events(events)
    latest_user = ""
    latest_assistant = ""
    user_turn_count = 0
    assistant_turn_count = 0
    for item in msgs:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role == "user":
            user_turn_count += 1
            latest_user = content or latest_user
        elif role == "assistant":
            assistant_turn_count += 1
            latest_assistant = content or latest_assistant
    channel = str(md.get("channel") or "ingest").strip() or "ingest"
    trigger = str(md.get("trigger") or "").strip()
    session_id = str(md.get("session_id") or "").strip()
    job_id = str(md.get("job_id") or "").strip()
    conversation_id = str(md.get("conversation_id") or "").strip()
    source_label = str(md.get("source_label") or "").strip()
    if not source_label:
        parts = [x for x in [channel, trigger, session_id or job_id] if x]
        source_label = ":".join(parts) if parts else channel
    key_seed = {
        "channel": channel,
        "trigger": trigger,
        "session_id": session_id,
        "job_id": job_id,
        "conversation_id": conversation_id,
        "messages": msgs,
        "events": evs,
    }
    return {
        "source_key": hashlib.sha1(json.dumps(key_seed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "channel": channel,
        "trigger": trigger,
        "session_id": session_id,
        "job_id": job_id,
        "conversation_id": conversation_id,
        "source_label": source_label,
        "message_hash": hashlib.sha1(json.dumps(msgs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if msgs
        else "",
        "messages": msgs[:_MAX_MESSAGES_PER_EVENT],
        "events": evs[:_MAX_EVENTS_PER_RECORD],
        "message_count": len(msgs),
        "event_count": len(evs),
        "user_turn_count": int(user_turn_count),
        "assistant_turn_count": int(assistant_turn_count),
        "latest_user_preview": _preview_text(latest_user),
        "latest_assistant_preview": _preview_text(latest_assistant),
        "metadata": _json_safe_metadata(md),
    }


class OnlineSkillProvenanceStore:
    """Durable per-user mapping from online updated skills to source conversation windows."""

    def __init__(self, *, path: str, user_id: str) -> None:
        self.path = str(path or "").strip()
        self.user_id = str(user_id or "").strip() or "u1"
        self.data: Dict[str, Any] = {
            "version": 1,
            "user_id": self.user_id,
            "skills": {},
        }
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
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def summary(self) -> Dict[str, Any]:
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
                    "version_history_count": int((row or {}).get("version_history_count", 0) or 0),
                    "last_channel": str((row or {}).get("last_channel") or ""),
                    "last_trigger": str((row or {}).get("last_trigger") or ""),
                    "usage_stats": dict((row or {}).get("usage_stats") or {}),
                }
                for sid, row in skills.items()
            ],
        }

    def get_skill_record(
        self,
        *,
        skill_id: str,
        max_sources: int = 20,
        max_history: int = 20,
        include_messages: bool = True,
    ) -> Dict[str, Any]:
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
        history = history[: max(1, int(max_history or 1))]
        if not include_messages:
            for item in history:
                if isinstance(item, dict):
                    item.pop("messages", None)
                    item.pop("events", None)
                    item.pop("metadata", None)
        out["history"] = history
        return out

    def record_skill_update(
        self,
        *,
        skill: Any,
        source_ref: Dict[str, Any],
        usage_stats: Optional[Dict[str, Any]] = None,
        version_timeline: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        sid = str(getattr(skill, "id", "") or "").strip()
        if not sid:
            return
        now_ms = _now_ms()
        now_iso = _now_iso()
        skills = self.data.setdefault("skills", {})
        row = skills.setdefault(
            sid,
            {
                "skill_id": sid,
                "name": "",
                "current_version": "",
                "updated_at": "",
                "updated_at_ms": 0,
                "source_count": 0,
                "history_count": 0,
                "version_history_count": 0,
                "last_channel": "",
                "last_trigger": "",
                "usage_stats": {},
                "version_timeline": [],
                "sources": [],
                "history": [],
            },
        )
        row["name"] = str(getattr(skill, "name", "") or "")
        row["current_version"] = str(getattr(skill, "version", "") or "")
        row["updated_at"] = now_iso
        row["updated_at_ms"] = now_ms
        row["last_channel"] = str(source_ref.get("channel") or "")
        row["last_trigger"] = str(source_ref.get("trigger") or "")
        row["usage_stats"] = dict(usage_stats or {})
        row["version_timeline"] = list(version_timeline or [])
        row["version_history_count"] = len(list(row.get("version_timeline") or []))

        self._merge_source_row(row=row, source_ref=source_ref, now_iso=now_iso, now_ms=now_ms)
        self._append_history_event(
            row=row,
            skill=skill,
            source_ref=source_ref,
            now_iso=now_iso,
            now_ms=now_ms,
            usage_stats=dict(usage_stats or {}),
            version_timeline=list(version_timeline or []),
        )
        row["source_count"] = len(list(row.get("sources") or []))
        row["history_count"] = len(list(row.get("history") or []))

    def _merge_source_row(
        self,
        *,
        row: Dict[str, Any],
        source_ref: Dict[str, Any],
        now_iso: str,
        now_ms: int,
    ) -> None:
        sources = list(row.get("sources") or [])
        key = str(source_ref.get("source_key") or "").strip()
        found = None
        for item in sources:
            if str((item or {}).get("source_key") or "").strip() == key:
                found = item
                break
        compact = {
            "source_key": key,
            "channel": str(source_ref.get("channel") or ""),
            "trigger": str(source_ref.get("trigger") or ""),
            "session_id": str(source_ref.get("session_id") or ""),
            "job_id": str(source_ref.get("job_id") or ""),
            "conversation_id": str(source_ref.get("conversation_id") or ""),
            "source_label": str(source_ref.get("source_label") or ""),
            "message_count": int(source_ref.get("message_count", 0) or 0),
            "event_count": int(source_ref.get("event_count", 0) or 0),
            "user_turn_count": int(source_ref.get("user_turn_count", 0) or 0),
            "assistant_turn_count": int(source_ref.get("assistant_turn_count", 0) or 0),
            "latest_user_preview": str(source_ref.get("latest_user_preview") or ""),
            "latest_assistant_preview": str(source_ref.get("latest_assistant_preview") or ""),
            "last_version": str(row.get("current_version") or ""),
        }
        if found is None:
            compact["first_seen_at"] = now_iso
            compact["first_seen_at_ms"] = now_ms
            compact["last_seen_at"] = now_iso
            compact["last_seen_at_ms"] = now_ms
            compact["seen_count"] = 1
            sources.append(compact)
        else:
            found.update({k: v for k, v in compact.items() if v not in ("", None, [])})
            found["last_seen_at"] = now_iso
            found["last_seen_at_ms"] = now_ms
            found["seen_count"] = int(found.get("seen_count", 0) or 0) + 1
        sources.sort(key=lambda x: int((x or {}).get("last_seen_at_ms", 0) or 0), reverse=True)
        row["sources"] = sources[:_MAX_SOURCES_PER_SKILL]

    def _append_history_event(
        self,
        *,
        row: Dict[str, Any],
        skill: Any,
        source_ref: Dict[str, Any],
        now_iso: str,
        now_ms: int,
        usage_stats: Dict[str, Any],
        version_timeline: List[Dict[str, Any]],
    ) -> None:
        history = list(row.get("history") or [])
        event = {
            "timestamp": now_iso,
            "timestamp_ms": now_ms,
            "version": str(getattr(skill, "version", "") or ""),
            "name": str(getattr(skill, "name", "") or ""),
            "description": str(getattr(skill, "description", "") or ""),
            "channel": str(source_ref.get("channel") or ""),
            "trigger": str(source_ref.get("trigger") or ""),
            "session_id": str(source_ref.get("session_id") or ""),
            "job_id": str(source_ref.get("job_id") or ""),
            "conversation_id": str(source_ref.get("conversation_id") or ""),
            "source_key": str(source_ref.get("source_key") or ""),
            "source_label": str(source_ref.get("source_label") or ""),
            "message_hash": str(source_ref.get("message_hash") or ""),
            "message_count": int(source_ref.get("message_count", 0) or 0),
            "event_count": int(source_ref.get("event_count", 0) or 0),
            "user_turn_count": int(source_ref.get("user_turn_count", 0) or 0),
            "assistant_turn_count": int(source_ref.get("assistant_turn_count", 0) or 0),
            "latest_user_preview": str(source_ref.get("latest_user_preview") or ""),
            "latest_assistant_preview": str(source_ref.get("latest_assistant_preview") or ""),
            "usage_stats": dict(usage_stats or {}),
            "version_history_count": len(list(version_timeline or [])),
            "version_timeline_tail": list(version_timeline[-5:] if version_timeline else []),
            "messages": list(source_ref.get("messages") or []),
            "events": list(source_ref.get("events") or []),
            "metadata": _json_safe_metadata(dict(source_ref.get("metadata") or {})),
        }
        if history:
            last = dict(history[-1] or {})
            if (
                str(last.get("version") or "") == event["version"]
                and str(last.get("message_hash") or "") == event["message_hash"]
                and str(last.get("trigger") or "") == event["trigger"]
                and str(last.get("session_id") or "") == event["session_id"]
            ):
                last["timestamp"] = now_iso
                last["timestamp_ms"] = now_ms
                last["repeat_count"] = int(last.get("repeat_count", 1) or 1) + 1
                last["usage_stats"] = dict(usage_stats or {})
                last["version_history_count"] = len(list(version_timeline or []))
                last["version_timeline_tail"] = list(version_timeline[-5:] if version_timeline else [])
                history[-1] = last
                row["history"] = history[-_MAX_HISTORY_PER_SKILL:]
                return
        event["repeat_count"] = 1
        history.append(event)
        row["history"] = history[-_MAX_HISTORY_PER_SKILL:]


def _normalize_messages(messages: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in list(messages or [])[:_MAX_MESSAGES_PER_EVENT]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower() or "user"
        content = str(item.get("content") or "")
        if not content:
            continue
        out.append({"role": role, "content": content})
    return out


def _normalize_events(events: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in list(events or [])[:_MAX_EVENTS_PER_RECORD]:
        if not isinstance(item, dict):
            continue
        out.append(_json_safe_metadata(item))
    return out


def _json_safe_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in dict(data or {}).items():
        key = str(k or "").strip()
        if not key:
            continue
        try:
            json.dumps(v, ensure_ascii=False)
            out[key] = v
        except Exception:
            out[key] = str(v)
    return out


def _preview_text(text: str, limit: int = 240) -> str:
    s = _WS_RE.sub(" ", str(text or "").strip())
    if len(s) <= limit:
        return s
    return s[: max(1, int(limit) - 3)].rstrip() + "..."


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _enrich_skill_record_live(
    *,
    sdk: Any,
    user_id: str,
    skill_id: str,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    """Merges live version/usage state into a persisted provenance record."""

    out = copy.deepcopy(dict(record or {}))
    if not out:
        return out
    sid = str(skill_id or out.get("skill_id") or "").strip()
    if not sid:
        return out
    skill = None
    try:
        skill = sdk.get(sid)
    except Exception:
        skill = None
    if skill is not None:
        timeline = _build_version_timeline(skill)
        out["version_timeline"] = timeline
        out["version_history_count"] = len(timeline)
        out["current_version"] = str(getattr(skill, "version", "") or out.get("current_version") or "")
        out["name"] = str(getattr(skill, "name", "") or out.get("name") or "")
        out["updated_at"] = str(getattr(skill, "updated_at", "") or out.get("updated_at") or "")
    usage_stats = _load_usage_stats_for_skill(sdk=sdk, user_id=user_id, skill_id=sid)
    if usage_stats:
        out["usage_stats"] = usage_stats
    return out


def _load_usage_stats_for_skill(*, sdk: Any, user_id: str, skill_id: str) -> Dict[str, Any]:
    """Loads one skill's retrieval/relevance/usage counters from the configured store."""

    sid = str(skill_id or "").strip()
    uid = str(user_id or "").strip()
    if not sid or not uid:
        return {}
    try:
        fn = getattr(getattr(sdk, "store", None), "get_skill_usage_stats", None)
        if not callable(fn):
            return {}
        raw = fn(user_id=uid, skill_id=sid)
    except Exception:
        return {}
    skills = dict(raw.get("skills") or {}) if isinstance(raw, dict) else {}
    row = dict(skills.get(sid) or {})
    if not row:
        return {}
    return {
        "retrieved": int(row.get("retrieved", 0) or 0),
        "relevant": int(row.get("relevant", 0) or 0),
        "used": int(row.get("used", 0) or 0),
        "last_retrieved_at": int(row.get("last_retrieved_at", 0) or 0),
        "last_relevant_at": int(row.get("last_relevant_at", 0) or 0),
        "last_used_at": int(row.get("last_used_at", 0) or 0),
    }


def _build_version_timeline(skill: Any) -> List[Dict[str, Any]]:
    """Builds a compact version timeline from `_autoskill_version_history` plus current state."""

    metadata = dict(getattr(skill, "metadata", {}) or {})
    hist_raw = metadata.get("_autoskill_version_history")
    out: List[Dict[str, Any]] = []
    if isinstance(hist_raw, list):
        for item in hist_raw:
            if not isinstance(item, dict):
                continue
            out.append(_compact_version_entry(item, is_current=False))
    out.append(
        _compact_version_entry(
            {
                "version": str(getattr(skill, "version", "") or ""),
                "name": str(getattr(skill, "name", "") or ""),
                "description": str(getattr(skill, "description", "") or ""),
                "instructions": str(getattr(skill, "instructions", "") or ""),
                "tags": [str(t).strip() for t in (getattr(skill, "tags", []) or []) if str(t).strip()],
                "triggers": [str(t).strip() for t in (getattr(skill, "triggers", []) or []) if str(t).strip()],
                "examples": list(getattr(skill, "examples", []) or []),
                "updated_at": str(getattr(skill, "updated_at", "") or ""),
            },
            is_current=True,
        )
    )
    return out


def _compact_version_entry(item: Dict[str, Any], *, is_current: bool) -> Dict[str, Any]:
    """Normalizes one version snapshot into a compact timeline row."""

    tags = [str(t).strip() for t in (item.get("tags") or []) if str(t).strip()]
    triggers = [str(t).strip() for t in (item.get("triggers") or []) if str(t).strip()]
    examples = item.get("examples")
    if isinstance(examples, list):
        examples_count = len(examples)
    else:
        examples_count = 0
    return {
        "version": str(item.get("version") or ""),
        "name": str(item.get("name") or ""),
        "description": str(item.get("description") or ""),
        "updated_at": str(item.get("updated_at") or ""),
        "is_current": bool(is_current),
        "tags": tags[:12],
        "triggers": triggers[:12],
        "examples_count": int(examples_count),
        "instructions_preview": _preview_text(str(item.get("instructions") or ""), limit=320),
    }
