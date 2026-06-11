from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from autoskill.models import Skill
from autoskill.offline.conversation import load_skill_conversation_provenance
from autoskill.offline.conversation.file_loader import load_openai_units

from .config import SkillEvoConfig
from .io_utils import stable_hash, write_jsonl
from .models import LineageRecord, ReplaySample, SkillSnapshot
from .registry import ensure_evo_layout, lineage_dataset_dir, upsert_lineage_record


def snapshot_from_skill(skill: Skill) -> SkillSnapshot:
    return SkillSnapshot(
        skill_id=str(getattr(skill, "id", "") or ""),
        user_id=str(getattr(skill, "user_id", "") or ""),
        name=str(getattr(skill, "name", "") or ""),
        description=str(getattr(skill, "description", "") or ""),
        instructions=str(getattr(skill, "instructions", "") or ""),
        version=str(getattr(skill, "version", "") or ""),
        tags=[str(x).strip() for x in (getattr(skill, "tags", []) or []) if str(x).strip()],
        triggers=[str(x).strip() for x in (getattr(skill, "triggers", []) or []) if str(x).strip()],
        metadata=dict(getattr(skill, "metadata", {}) or {}),
    )


class ReplayBuilder:
    def __init__(self, *, config: SkillEvoConfig, sdk: Any) -> None:
        self.config = config
        self.sdk = sdk
        self._offline_cache: Dict[str, List[Dict[str, Any]]] = {}

    def build_for_skill(
        self,
        *,
        user_id: str,
        skill_id: str,
        max_samples: int | None = None,
    ) -> Tuple[LineageRecord, SkillSnapshot, List[ReplaySample], Dict[str, Any], Dict[str, Any]]:
        ensure_evo_layout(self.config)
        skill = self.sdk.get(str(skill_id or "").strip())
        if skill is None:
            raise ValueError(f"skill not found: {skill_id}")

        skill_snapshot = snapshot_from_skill(skill)
        online = self.sdk.get_skill_provenance(
            user_id=user_id,
            skill_id=skill_snapshot.skill_id,
            max_sources=300,
            max_history=300,
            include_messages=True,
        )
        offline = load_skill_conversation_provenance(
            sdk=self.sdk,
            user_id=user_id,
            skill_id=skill_snapshot.skill_id,
            max_sources=300,
            max_history=300,
        )

        offline_lineage_key = str(offline.get("lineage_key") or "").strip()
        lineage_id = self._lineage_id(
            user_id=user_id,
            skill=skill_snapshot,
            offline_lineage_key=offline_lineage_key,
        )

        online_samples = self._samples_from_online(
            user_id=user_id,
            lineage_id=lineage_id,
            skill=skill_snapshot,
            online_record=online,
        )
        offline_samples = self._samples_from_offline(
            user_id=user_id,
            lineage_id=lineage_id,
            skill=skill_snapshot,
            offline_record=offline,
        )
        merged = self._dedupe_samples(online_samples + offline_samples)
        merged = self._limit_and_split(merged, max_samples=max_samples)

        lineage = LineageRecord(
            lineage_id=lineage_id,
            user_id=user_id,
            skill_id=skill_snapshot.skill_id,
            skill_name=skill_snapshot.name,
            current_version=skill_snapshot.version,
            offline_lineage_key=offline_lineage_key,
            online_available=bool(online),
            offline_available=bool(offline),
            replay_count=len(merged),
            replay_dev_count=sum(1 for x in merged if x.split == "mutate_dev"),
            replay_test_count=sum(1 for x in merged if x.split == "promotion_test"),
            version_timeline=list(online.get("version_timeline") or []),
            sources={
                "online_history_count": int(len(list(online.get("history") or []))),
                "offline_history_count": int(len(list(offline.get("history") or []))),
                "offline_source_count": int(len(list(offline.get("sources") or []))),
            },
        )

        dataset_path = lineage_dataset_dir(self.config, lineage_id) / "replay_pool.jsonl"
        write_jsonl(dataset_path, [x.to_dict() for x in merged])
        upsert_lineage_record(self.config, lineage)
        return lineage, skill_snapshot, merged, online, offline

    def _lineage_id(
        self,
        *,
        user_id: str,
        skill: SkillSnapshot,
        offline_lineage_key: str,
    ) -> str:
        seed = {
            "user_id": str(user_id or "").strip(),
            "skill_id": skill.skill_id,
            "offline_lineage_key": str(offline_lineage_key or "").strip(),
            "name": skill.name,
        }
        if offline_lineage_key:
            return f"lineage-{stable_hash(seed)[:16]}"
        return f"skill-{stable_hash(seed)[:16]}"

    def _samples_from_online(
        self,
        *,
        user_id: str,
        lineage_id: str,
        skill: SkillSnapshot,
        online_record: Dict[str, Any],
    ) -> List[ReplaySample]:
        out: List[ReplaySample] = []
        for item in list(online_record.get("history") or []):
            messages = self._normalize_messages(item.get("messages"))
            if not self._has_user_turn(messages):
                continue
            sample_id = self._sample_id(
                lineage_id=lineage_id,
                source_type="online",
                key=str(item.get("source_key") or ""),
                version=str(item.get("version") or ""),
                latest_user=self._latest_user(messages),
            )
            out.append(
                ReplaySample(
                    sample_id=sample_id,
                    lineage_id=lineage_id,
                    user_id=user_id,
                    skill_id=skill.skill_id,
                    source_type="online",
                    split="mutate_dev",
                    messages=messages,
                    events=list(item.get("events") or []),
                    version_anchor=str(item.get("version") or ""),
                    provenance_ref={
                        "source_key": str(item.get("source_key") or ""),
                        "source_label": str(item.get("source_label") or ""),
                        "timestamp_ms": int(item.get("timestamp_ms", 0) or 0),
                        "channel": str(item.get("channel") or ""),
                        "trigger": str(item.get("trigger") or ""),
                    },
                    tags=["online"],
                )
            )
        return out

    def _samples_from_offline(
        self,
        *,
        user_id: str,
        lineage_id: str,
        skill: SkillSnapshot,
        offline_record: Dict[str, Any],
    ) -> List[ReplaySample]:
        out: List[ReplaySample] = []
        version_by_key: Dict[str, str] = {}
        timestamp_by_key: Dict[str, int] = {}
        for item in list(offline_record.get("history") or []):
            key = str(item.get("conversation_key") or "").strip()
            if not key:
                continue
            version_by_key[key] = str(item.get("version") or "")
            timestamp_by_key[key] = int(item.get("timestamp_ms", 0) or 0)

        for source in list(offline_record.get("sources") or []):
            messages = self._load_offline_messages(source)
            if not self._has_user_turn(messages):
                continue
            conversation_key = str(source.get("conversation_key") or "").strip()
            sample_id = self._sample_id(
                lineage_id=lineage_id,
                source_type="offline",
                key=conversation_key,
                version=str(version_by_key.get(conversation_key) or ""),
                latest_user=self._latest_user(messages),
            )
            out.append(
                ReplaySample(
                    sample_id=sample_id,
                    lineage_id=lineage_id,
                    user_id=user_id,
                    skill_id=skill.skill_id,
                    source_type="offline",
                    split="mutate_dev",
                    messages=messages,
                    events=[],
                    version_anchor=str(version_by_key.get(conversation_key) or ""),
                    provenance_ref={
                        "conversation_key": conversation_key,
                        "source_file": str(source.get("source_file") or ""),
                        "conversation_index": source.get("conversation_index"),
                        "locator": str(source.get("locator") or ""),
                        "timestamp_ms": int(
                            source.get("last_seen_at_ms", 0) or timestamp_by_key.get(conversation_key, 0) or 0
                        ),
                        "title": str(source.get("title") or ""),
                    },
                    tags=["offline"],
                )
            )
        return out

    def _load_offline_messages(self, source: Dict[str, Any]) -> List[Dict[str, str]]:
        source_file = str(source.get("source_file") or "").strip()
        if not source_file:
            return []
        if source_file not in self._offline_cache:
            units, _abs = load_openai_units(file_path=source_file)
            self._offline_cache[source_file] = list(units or [])
        units = self._offline_cache.get(source_file) or []
        target_index = source.get("conversation_index")
        try:
            idx = int(target_index) if target_index is not None else -1
        except Exception:
            idx = -1
        if 0 <= idx < len(units):
            return self._normalize_messages((units[idx] or {}).get("messages"))
        locator = str(source.get("locator") or "").strip()
        title = str(source.get("title") or "").strip()
        for unit in units:
            if str(unit.get("title") or "").strip() == title:
                return self._normalize_messages(unit.get("messages"))
            if locator and locator.endswith(f"#conv_{int(unit.get('conversation_index', -1)) + 1}"):
                return self._normalize_messages(unit.get("messages"))
        return []

    def _dedupe_samples(self, samples: List[ReplaySample]) -> List[ReplaySample]:
        best: Dict[str, ReplaySample] = {}
        for sample in samples:
            prev = best.get(sample.sample_id)
            if prev is None:
                best[sample.sample_id] = sample
                continue
            prev_ts = int(prev.provenance_ref.get("timestamp_ms", 0) or 0)
            cur_ts = int(sample.provenance_ref.get("timestamp_ms", 0) or 0)
            if cur_ts >= prev_ts:
                best[sample.sample_id] = sample
        out = list(best.values())
        out.sort(key=lambda x: int(x.provenance_ref.get("timestamp_ms", 0) or 0), reverse=True)
        return out

    def _limit_and_split(self, samples: List[ReplaySample], *, max_samples: int | None) -> List[ReplaySample]:
        limit = max(1, int(max_samples or self.config.replay_limit))
        trimmed = list(samples[:limit])
        out: List[ReplaySample] = []
        for item in trimmed:
            split = "mutate_dev" if self._split_score(item.sample_id) < self.config.dev_split_ratio else "promotion_test"
            out.append(
                ReplaySample(
                    sample_id=item.sample_id,
                    lineage_id=item.lineage_id,
                    user_id=item.user_id,
                    skill_id=item.skill_id,
                    source_type=item.source_type,
                    split=split,
                    messages=list(item.messages),
                    events=list(item.events),
                    version_anchor=item.version_anchor,
                    provenance_ref=dict(item.provenance_ref),
                    tags=list(item.tags),
                )
            )
        if len(out) >= 2 and not any(x.split == "promotion_test" for x in out):
            out[-1].split = "promotion_test"
        if len(out) >= 2 and not any(x.split == "mutate_dev" for x in out):
            out[0].split = "mutate_dev"
        return out

    def _sample_id(
        self,
        *,
        lineage_id: str,
        source_type: str,
        key: str,
        version: str,
        latest_user: str,
    ) -> str:
        return stable_hash(
            {
                "lineage_id": lineage_id,
                "source_type": source_type,
                "key": str(key or ""),
                "version": str(version or ""),
                "latest_user": str(latest_user or ""),
            }
        )[:20]

    def _split_score(self, sample_id: str) -> float:
        return int(str(sample_id or "0")[:8], 16) / float(16**8 - 1)

    def _normalize_messages(self, raw: Any) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for item in list(raw or []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "")
            if not role or not content:
                continue
            out.append({"role": role, "content": content})
        if self.config.sample_history_turns > 0 and len(out) > self.config.sample_history_turns:
            out = out[-int(self.config.sample_history_turns) :]
        return out

    def _has_user_turn(self, messages: List[Dict[str, str]]) -> bool:
        return any(str(x.get("role") or "").strip().lower() == "user" for x in messages)

    def _latest_user(self, messages: List[Dict[str, str]]) -> str:
        for item in reversed(messages):
            if str(item.get("role") or "").strip().lower() == "user":
                return str(item.get("content") or "")
        return ""
