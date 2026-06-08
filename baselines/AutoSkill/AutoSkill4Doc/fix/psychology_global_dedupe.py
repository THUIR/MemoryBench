"""
One-off global dedupe repair for the psychology visible domain.

This script is intentionally scoped to a single visible domain root such as:

  <store_root>/心理咨询

It does not change the register pipeline. Instead it repairs current registry /
store state and then rebuilds the visible tree for that domain.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
import os
import re
import shutil
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from autoskill import AutoSkill
from autoskill.config import AutoSkillConfig
from autoskill.llm.mock import MockLLM
from autoskill.models import SkillExample

from ..core.common import dedupe_strings, normalize_text
from ..core.config import DEFAULT_DOC_SKILL_USER_ID
from ..models import DocumentRecord, SkillSpec, SupportRecord, VersionState
from ..stages.compiler import _build_structured_prompt
from ..store.layout import domain_visible_root, safe_domain_name, safe_family_name
from ..store.registry import DocumentRegistry, default_registry_root
from ..store.versioning import (
    _ACTIVE_STORE_STATES,
    _copy_support,
    _store_skill_from_spec,
    VersionManager,
)
from ..store.visible_tree import (
    _family_name_for_skill,
    _normalize_domain_root_candidate,
    sync_visible_skill_tree,
)

_VISIBLE_DOMAIN_PREFIX = "Family技能"
_VISIBLE_STATES = {
    VersionState.CANDIDATE,
    VersionState.DRAFT,
    VersionState.EVALUATING,
    VersionState.ACTIVE,
    VersionState.WATCHLIST,
}
_MERGE_LIST_FIELDS = (
    "applicable_signals",
    "contraindications",
    "intervention_moves",
    "workflow_steps",
    "constraints",
    "cautions",
    "output_contract",
    "tags",
    "triggers",
)
_BOUNDARY_HINTS = ("适用于", "不用于", "仅在", "在", "当", "针对", "若", "如果", "需在")
_SECTION_SPLIT_RE = re.compile(r"\n##\s+")
_KEY_RE_TEMPLATE = r'^{key}:\s*"?([^"\n]+)"?\s*$'
_PSYCHOLOGY_FAMILY_NAMES = (
    "认知行为疗法",
    "行为主义",
    "后现代主义",
    "人本-存在主义",
    "心理动力学",
)


@dataclass
class VisibleSkillArtifact:
    """One visible skill artifact discovered under the target domain root."""

    skill_id: str
    name: str
    family_name: str
    level_label: str
    skill_md_path: str
    dir_path: str
    support_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "family_name": self.family_name,
            "level_label": self.level_label,
            "skill_md_path": self.skill_md_path,
            "dir_path": self.dir_path,
            "support_count": self.support_count,
        }


@dataclass
class PsychologyGlobalDedupeSummary:
    """Compact summary for one dry-run or apply pass."""

    store_path: str
    domain_root_name: str
    dry_run: bool = True
    visible_skill_count: int = 0
    domain_skill_count: int = 0
    cross_family_groups: List[Dict[str, Any]] = field(default_factory=list)
    merged_groups: List[Dict[str, Any]] = field(default_factory=list)
    updated_skill_ids: List[str] = field(default_factory=list)
    deprecated_skill_ids: List[str] = field(default_factory=list)
    rebound_support_count: int = 0
    orphan_visible_skill_ids: List[str] = field(default_factory=list)
    visible_tree: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "store_path": self.store_path,
            "domain_root_name": self.domain_root_name,
            "dry_run": self.dry_run,
            "visible_skill_count": self.visible_skill_count,
            "domain_skill_count": self.domain_skill_count,
            "cross_family_groups": list(self.cross_family_groups or []),
            "merged_groups": list(self.merged_groups or []),
            "updated_skill_ids": list(self.updated_skill_ids or []),
            "deprecated_skill_ids": list(self.deprecated_skill_ids or []),
            "rebound_support_count": int(self.rebound_support_count or 0),
            "orphan_visible_skill_ids": list(self.orphan_visible_skill_ids or []),
            "visible_tree": dict(self.visible_tree or {}),
        }


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(_KEY_RE_TEMPLATE.format(key=re.escape(str(key or "").strip())), text, re.MULTILINE)
    return str(match.group(1) or "").strip() if match else ""


def _evidence_support_count(skill_dir: str) -> int:
    manifest_path = os.path.join(skill_dir, "references", "evidence_manifest.json")
    if not os.path.isfile(manifest_path):
        return 0
    try:
        payload = json.loads(_read_text(manifest_path))
    except Exception:
        return 0
    try:
        return max(0, int(payload.get("support_count", 0) or 0))
    except Exception:
        return 0


def scan_visible_domain(*, store_path: str, domain_root_name: str) -> List[VisibleSkillArtifact]:
    """Scans one visible domain root and returns child skill artifacts only."""

    domain_dir = domain_visible_root(base_store_root=store_path, domain_root_name=domain_root_name)
    if not os.path.isdir(domain_dir):
        return []
    out: List[VisibleSkillArtifact] = []
    for dirpath, _, filenames in os.walk(domain_dir):
        if "SKILL.md" not in filenames:
            continue
        skill_md_path = os.path.join(dirpath, "SKILL.md")
        rel_parts = os.path.relpath(skill_md_path, domain_dir).split(os.sep)
        if len(rel_parts) < 5 or rel_parts[0] != _VISIBLE_DOMAIN_PREFIX:
            continue
        family_name = str(rel_parts[1] or "").strip()
        level_label = str(rel_parts[2] or "").strip()
        text = _read_text(skill_md_path)
        skill_id = _frontmatter_value(text, "id")
        skill_name = _frontmatter_value(text, "name") or os.path.basename(dirpath)
        out.append(
            VisibleSkillArtifact(
                skill_id=skill_id,
                name=skill_name,
                family_name=family_name,
                level_label=level_label,
                skill_md_path=skill_md_path,
                dir_path=dirpath,
                support_count=_evidence_support_count(dirpath),
            )
        )
    return out


def _domain_root_for_skill(skill: SkillSpec) -> str:
    md = dict(skill.metadata or {})
    for candidate in (
        str(md.get("domain_root_name") or "").strip(),
        str(md.get("domain") or "").strip(),
        str(md.get("domain_type") or "").strip(),
        str(skill.domain or "").strip(),
    ):
        if candidate:
            return safe_domain_name(_normalize_domain_root_candidate(candidate))
    return ""


def _domain_skill_filter(skills: Sequence[SkillSpec], *, domain_root_name: str) -> List[SkillSpec]:
    target = safe_domain_name(domain_root_name)
    return [skill for skill in list(skills or []) if _domain_root_for_skill(skill) == target]


def _normalize_family_key(value: str) -> str:
    raw = str(value or "").strip().replace("_", "-")
    raw = raw.replace("（", "(").replace("）", ")")
    return normalize_text(raw, lower=True)


def _match_family_candidate(value: str, family_names: Sequence[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    norm = _normalize_family_key(raw)
    if not norm:
        return ""
    ordered_families = sorted(
        [str(item or "").strip() for item in family_names if str(item or "").strip()],
        key=lambda item: (-len(_normalize_family_key(item)), item),
    )
    for family_name in ordered_families:
        family_norm = _normalize_family_key(family_name)
        if norm == family_norm or family_norm in norm or norm in family_norm:
            return safe_family_name(family_name)
    return ""


def _family_from_tags(skill: SkillSpec, family_names: Sequence[str]) -> str:
    tags = list(skill.tags or [])
    for tag in tags:
        raw = str(tag or "").strip()
        if raw.startswith("class:"):
            matched = _match_family_candidate(raw.split(":", 1)[1], family_names)
            if matched:
                return matched
        if raw.startswith("profile:"):
            tail = raw.rsplit("::", 1)[-1]
            matched = _match_family_candidate(tail, family_names)
            if matched:
                return matched
    return ""


def _family_votes_from_supports(
    *,
    skill: SkillSpec,
    support_by_id: Dict[str, SupportRecord],
    family_names: Sequence[str],
) -> Counter:
    votes: Counter = Counter()
    for support_id in list(skill.support_ids or []):
        support = support_by_id.get(str(support_id or "").strip())
        if support is None:
            continue
        md = dict(support.metadata or {})
        matched = _match_family_candidate(str(md.get("method_family") or "").strip(), family_names)
        if matched:
            votes[matched] += 1
    return votes


def _safe_family_names(values: Sequence[str]) -> List[str]:
    return dedupe_strings(
        [safe_family_name(str(value or "").strip()) for value in list(values or []) if str(value or "").strip()],
        lower=False,
    )


def _choose_canonical_family(
    *,
    skill: SkillSpec,
    visible_entries: Sequence[VisibleSkillArtifact],
    support_by_id: Dict[str, SupportRecord],
    family_names: Sequence[str],
) -> str:
    allowed_families = _safe_family_names(family_names)
    allowed_set = set(allowed_families)
    support_votes = _family_votes_from_supports(skill=skill, support_by_id=support_by_id, family_names=family_names)
    if support_votes:
        ordered = sorted(
            [
                (family_name, vote_count)
                for family_name, vote_count in support_votes.items()
                if not allowed_set or str(family_name or "").strip() in allowed_set
            ],
            key=lambda item: (-int(item[1] or 0), str(item[0] or "")),
        )
        if ordered:
            return str(ordered[0][0] or "").strip()
    matched_method_family = _match_family_candidate(skill.method_family, family_names)
    if matched_method_family:
        return matched_method_family
    matched_from_tags = _family_from_tags(skill, family_names)
    if matched_from_tags:
        return matched_from_tags
    if visible_entries:
        by_visible_supports: Dict[str, int] = defaultdict(int)
        for entry in list(visible_entries or []):
            family_name = safe_family_name(str(entry.family_name or "").strip())
            if allowed_set and family_name not in allowed_set:
                continue
            by_visible_supports[family_name] += int(entry.support_count or 0)
        if by_visible_supports:
            ordered = sorted(by_visible_supports.items(), key=lambda item: (-int(item[1] or 0), str(item[0] or "")))
            return str(ordered[0][0] or "").strip()
    family_candidates = {
        safe_family_name(str(entry.family_name or "").strip())
        for entry in list(visible_entries or [])
        if str(entry.family_name or "").strip()
    }
    if allowed_set:
        family_candidates = {family_name for family_name in family_candidates if family_name in allowed_set}
    if family_candidates:
        return sorted(family_candidates)[0]
    current_family = safe_family_name(_family_name_for_skill(skill, metadata={}))
    if not allowed_set or current_family in allowed_set:
        return current_family
    return ""


def _version_key(value: str) -> Tuple[int, int, int]:
    parts = [part for part in str(value or "").strip().split(".") if part.isdigit()]
    if len(parts) != 3:
        return (0, 0, 0)
    return int(parts[0]), int(parts[1]), int(parts[2])


def _skill_completeness_score(skill: SkillSpec) -> int:
    score = 0
    if str(skill.description or "").strip():
        score += 1
    if str(skill.objective or "").strip():
        score += 1
    if str(skill.skill_body or "").strip():
        score += 1
    for field_name in _MERGE_LIST_FIELDS:
        score += len(list(getattr(skill, field_name, []) or []))
    score += len(list(skill.examples or [])) * 2
    return score


def _canonical_skill_sort_key(skill: SkillSpec) -> Tuple[int, int, int, Tuple[int, int, int], str]:
    return (
        -len(list(skill.support_ids or [])),
        0 if str(skill.hierarchy_status or "").strip() == "linked" else 1,
        -_skill_completeness_score(skill),
        tuple(-part for part in _version_key(skill.version)),
        str(skill.skill_id or ""),
    )


def _coalesce_text(values: Iterable[str]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_prompt_text(skill_body: str) -> str:
    body = str(skill_body or "").strip()
    if not body:
        return ""
    match = _SECTION_SPLIT_RE.search(body)
    if match is None:
        return body
    return body[: match.start()].strip()


def _merge_text_items(primary: Sequence[str], secondary: Sequence[str]) -> List[str]:
    out: List[str] = []
    norms: List[str] = []
    for raw in list(primary or []) + list(secondary or []):
        item = str(raw or "").strip()
        if not item:
            continue
        norm = normalize_text(item, lower=True)
        replaced = False
        for idx, existing_norm in enumerate(list(norms)):
            if norm == existing_norm:
                if len(item) > len(out[idx]):
                    out[idx] = item
                    norms[idx] = norm
                replaced = True
                break
            if norm in existing_norm or existing_norm in norm:
                if len(item) > len(out[idx]):
                    out[idx] = item
                    norms[idx] = norm
                replaced = True
                break
        if replaced:
            continue
        out.append(item)
        norms.append(norm)
    return out


def _merge_examples(primary: Sequence[SkillExample], secondary: Sequence[SkillExample]) -> List[SkillExample]:
    buckets: Dict[str, List[SkillExample]] = {}
    ordered_keys: List[str] = []
    for example in list(primary or []) + list(secondary or []):
        if example is None or not str(example.input or "").strip():
            continue
        input_norm = normalize_text(str(example.input or "").strip(), lower=True)
        if input_norm not in buckets:
            buckets[input_norm] = []
            ordered_keys.append(input_norm)
        output_norm = normalize_text(str(example.output or "").strip(), lower=True)
        matched = False
        for idx, existing in enumerate(list(buckets[input_norm])):
            existing_output_norm = normalize_text(str(existing.output or "").strip(), lower=True)
            if output_norm == existing_output_norm:
                if not str(existing.notes or "").strip() and str(example.notes or "").strip():
                    buckets[input_norm][idx] = SkillExample(
                        input=str(existing.input or "").strip(),
                        output=str(existing.output or "").strip() or None,
                        notes=str(example.notes or "").strip() or None,
                    )
                matched = True
                break
        if not matched:
            buckets[input_norm].append(
                SkillExample(
                    input=str(example.input or "").strip(),
                    output=str(example.output or "").strip() or None,
                    notes=str(example.notes or "").strip() or None,
                )
            )
    out: List[SkillExample] = []
    for key in ordered_keys:
        out.extend(buckets.get(key, []))
    return out


def _merge_description(primary: str, secondaries: Sequence[str]) -> str:
    base = str(primary or "").strip()
    if not base:
        return _coalesce_text(secondaries)
    base_norm = normalize_text(base, lower=True)
    for secondary in list(secondaries or []):
        text = str(secondary or "").strip()
        if not text:
            continue
        text_norm = normalize_text(text, lower=True)
        if text_norm == base_norm or text_norm in base_norm or base_norm in text_norm:
            if len(text) > len(base):
                base = text
                base_norm = text_norm
            continue
        if any(hint in text for hint in _BOUNDARY_HINTS):
            return f"{base} {text}".strip()
    return base


def _merge_objective(primary: str, secondaries: Sequence[str]) -> str:
    base = str(primary or "").strip()
    if not base:
        return _coalesce_text(secondaries)
    base_norm = normalize_text(base, lower=True)
    for secondary in list(secondaries or []):
        text = str(secondary or "").strip()
        if not text:
            continue
        text_norm = normalize_text(text, lower=True)
        if base_norm == text_norm or base_norm in text_norm:
            if len(text) > len(base):
                base = text
                base_norm = text_norm
    return base


def _merge_metadata(
    primary: Dict[str, Any],
    secondaries: Sequence[Dict[str, Any]],
    *,
    metadata_update: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    merged = dict(primary or {})
    for secondary in list(secondaries or []):
        payload = dict(secondary or {})
        for field_name in ("files", "resources"):
            current_map = dict(merged.get(field_name) or {})
            incoming_map = dict(payload.get(field_name) or {})
            for key, value in incoming_map.items():
                current_map.setdefault(str(key), value)
            if current_map:
                merged[field_name] = current_map
    if metadata_update:
        merged.update(dict(metadata_update or {}))
    return merged


def _replace_skill(skill: SkillSpec, *, metadata_update: Optional[Dict[str, Any]] = None, **fields: Any) -> SkillSpec:
    payload = skill.to_dict()
    for key, value in fields.items():
        if key == "status" and isinstance(value, VersionState):
            payload[key] = value.value
        else:
            payload[key] = value
    if metadata_update is not None:
        payload["metadata"] = _merge_metadata(
            dict(payload.get("metadata") or {}),
            [],
            metadata_update=metadata_update,
        )
    return SkillSpec.from_dict(payload)


def _build_sdk(*, store_path: str) -> AutoSkill:
    config = AutoSkillConfig.from_dict(
        {
            "llm": {"provider": "mock"},
            "embeddings": {"provider": "hashing", "dims": 256},
            "store": {"provider": "local", "path": store_path},
        }
    )
    return AutoSkill(config=config)


def _doc_ids_for_support_ids(support_ids: Sequence[str], support_by_id: Dict[str, SupportRecord]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for support_id in list(support_ids or []):
        support = support_by_id.get(str(support_id or "").strip())
        if support is None:
            continue
        doc_id = str(support.doc_id or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        out.append(doc_id)
    return out


def _mark_deprecated_empty_supports(
    *,
    manager: VersionManager,
    skill: SkillSpec,
    reason: str,
    related_ids: Sequence[str],
) -> Tuple[SkillSpec, Dict[str, Any], Any, Dict[str, Any]]:
    next_version = manager.create_new_version(current_version=skill.version, action="deprecate")
    updated_skill = _replace_skill(
        skill,
        version=next_version,
        status=VersionState.DEPRECATED,
        support_ids=[],
        metadata_update={
            "change_action": "deprecate",
            "deprecation_reason": str(reason or "").strip(),
            "related_skill_ids": list(related_ids or []),
        },
    )
    provenance = {
        "entity_type": "skill",
        "entity_id": updated_skill.skill_id,
        "doc_ids": [],
        "support_added": [],
        "support_conflicts": [],
        "related_entity_ids": list(related_ids or []),
    }
    lifecycle = manager.update_lifecycle(
        skill_id=updated_skill.skill_id,
        current_state=skill.status,
        action="deprecate",
        target_state=VersionState.DEPRECATED,
        metadata={"reason": str(reason or "").strip(), "related_entity_ids": list(related_ids or [])},
    )
    change_log = manager._change_payload(
        entity_type="skill",
        entity_id=updated_skill.skill_id,
        action="deprecate",
        from_version=skill.version,
        to_version=updated_skill.version,
        from_state=skill.status.value,
        to_state=updated_skill.status.value,
        summary=str(reason or "").strip(),
        provenance=provenance,
        related_entity_ids=list(related_ids or []),
    )
    version_history = manager._history_payload(
        entity_type="skill",
        entity_id=updated_skill.skill_id,
        version=updated_skill.version,
        action="deprecate",
        status=updated_skill.status,
        related_entity_ids=list(related_ids or []),
    )
    return updated_skill, provenance, lifecycle, {"change_log": change_log, "version_history": version_history}


def _merge_duplicate_group(
    *,
    manager: VersionManager,
    skills: Sequence[SkillSpec],
    support_by_id: Dict[str, SupportRecord],
) -> Dict[str, Any]:
    ordered = sorted(list(skills or []), key=_canonical_skill_sort_key)
    canonical = ordered[0]
    secondaries = ordered[1:]
    merged_support_ids = dedupe_strings(
        [
            str(support_id or "").strip()
            for skill in [canonical] + list(secondaries)
            for support_id in list(skill.support_ids or [])
            if str(support_id or "").strip()
        ],
        lower=False,
    )
    merged_examples = _merge_examples(
        canonical.examples,
        [example for skill in secondaries for example in list(skill.examples or [])],
    )
    merged_lists: Dict[str, List[str]] = {}
    for field_name in _MERGE_LIST_FIELDS:
        merged_lists[field_name] = _merge_text_items(
            list(getattr(canonical, field_name, []) or []),
            [item for skill in secondaries for item in list(getattr(skill, field_name, []) or [])],
        )
    merged_description = _merge_description(canonical.description, [skill.description for skill in secondaries])
    merged_objective = _merge_objective(canonical.objective, [skill.objective for skill in secondaries])
    next_version = manager.create_new_version(
        current_version=canonical.version,
        action="temporary_duplicate_merge",
    )
    prompt_text = _extract_prompt_text(canonical.skill_body) or canonical.description or canonical.objective
    updated_canonical = _replace_skill(
        canonical,
        description=merged_description,
        objective=merged_objective or canonical.objective or merged_description,
        applicable_signals=merged_lists["applicable_signals"],
        contraindications=merged_lists["contraindications"],
        intervention_moves=merged_lists["intervention_moves"],
        workflow_steps=merged_lists["workflow_steps"],
        constraints=merged_lists["constraints"],
        cautions=merged_lists["cautions"],
        output_contract=merged_lists["output_contract"],
        tags=merged_lists["tags"],
        triggers=merged_lists["triggers"],
        examples=merged_examples,
        support_ids=merged_support_ids,
        skill_body=_build_structured_prompt(
            prompt=prompt_text,
            objective=merged_objective or canonical.objective or merged_description,
            applicable_signals=merged_lists["applicable_signals"],
            contraindications=merged_lists["contraindications"],
            intervention_moves=merged_lists["intervention_moves"],
            workflow_steps=merged_lists["workflow_steps"],
            constraints=merged_lists["constraints"],
            cautions=merged_lists["cautions"],
            output_contract=merged_lists["output_contract"],
            examples=merged_examples,
        ),
        version=next_version,
        metadata_update=_merge_metadata(
            dict(canonical.metadata or {}),
            [dict(skill.metadata or {}) for skill in secondaries],
            metadata_update={
                "change_action": "temporary_duplicate_merge",
                "merged_from_skill_ids": [skill.skill_id for skill in secondaries],
            },
        ),
    )
    added_support_ids = [
        support_id for support_id in merged_support_ids if support_id not in set(list(canonical.support_ids or []))
    ]
    support_updates: Dict[str, SupportRecord] = {}
    for secondary in list(secondaries or []):
        for support_id in list(secondary.support_ids or []):
            support = support_by_id.get(str(support_id or "").strip())
            if support is None:
                continue
            support_updates[support.support_id] = _copy_support(
                support,
                skill_id=updated_canonical.skill_id,
                metadata_update={
                    "dedupe_rebound_from_skill_id": secondary.skill_id,
                    "dedupe_rebound_to_skill_id": updated_canonical.skill_id,
                },
            )
    provenance = {
        "entity_type": "skill",
        "entity_id": updated_canonical.skill_id,
        "doc_ids": _doc_ids_for_support_ids(merged_support_ids, support_by_id),
        "support_added": list(added_support_ids or []),
        "support_conflicts": [],
        "related_entity_ids": [skill.skill_id for skill in secondaries],
    }
    lifecycle = manager.update_lifecycle(
        skill_id=updated_canonical.skill_id,
        current_state=canonical.status,
        action="temporary_duplicate_merge",
        target_state=updated_canonical.status,
        metadata={"related_entity_ids": [skill.skill_id for skill in secondaries]},
    )
    change_log = manager._change_payload(
        entity_type="skill",
        entity_id=updated_canonical.skill_id,
        action="temporary_duplicate_merge",
        from_version=canonical.version,
        to_version=updated_canonical.version,
        from_state=canonical.status.value,
        to_state=updated_canonical.status.value,
        summary="merge_same_family_same_level_same_node_duplicates",
        provenance=provenance,
        related_entity_ids=[skill.skill_id for skill in secondaries],
    )
    version_history = manager._history_payload(
        entity_type="skill",
        entity_id=updated_canonical.skill_id,
        version=updated_canonical.version,
        action="temporary_duplicate_merge",
        status=updated_canonical.status,
        related_entity_ids=[skill.skill_id for skill in secondaries],
    )
    deprecated_payloads: List[Dict[str, Any]] = []
    for secondary in list(secondaries or []):
        deprecated_skill, deprecated_provenance, deprecated_lifecycle, audit = _mark_deprecated_empty_supports(
            manager=manager,
            skill=secondary,
            reason="temporary_duplicate_group_merge",
            related_ids=[updated_canonical.skill_id],
        )
        deprecated_payloads.append(
            {
                "skill": deprecated_skill,
                "provenance": deprecated_provenance,
                "lifecycle": deprecated_lifecycle,
                "change_log": audit["change_log"],
                "version_history": audit["version_history"],
            }
        )
    return {
        "canonical": updated_canonical,
        "canonical_provenance": provenance,
        "canonical_lifecycle": lifecycle,
        "canonical_change_log": change_log,
        "canonical_version_history": version_history,
        "deprecated": deprecated_payloads,
        "support_updates": support_updates,
    }


def _update_skill_family(
    *,
    manager: VersionManager,
    skill: SkillSpec,
    canonical_family: str,
    support_by_id: Dict[str, SupportRecord],
) -> Dict[str, Any]:
    next_version = manager.create_new_version(current_version=skill.version, action="temporary_dedupe_rehome")
    updated_skill = _replace_skill(
        skill,
        version=next_version,
        metadata_update={
            "family_name": canonical_family,
            "taxonomy_class": canonical_family,
            "change_action": "temporary_dedupe_rehome",
        },
    )
    provenance = {
        "entity_type": "skill",
        "entity_id": updated_skill.skill_id,
        "doc_ids": _doc_ids_for_support_ids(updated_skill.support_ids, support_by_id),
        "support_added": [],
        "support_conflicts": [],
        "related_entity_ids": [],
    }
    lifecycle = manager.update_lifecycle(
        skill_id=updated_skill.skill_id,
        current_state=skill.status,
        action="temporary_dedupe_rehome",
        target_state=updated_skill.status,
        metadata={"family_name": canonical_family},
    )
    change_log = manager._change_payload(
        entity_type="skill",
        entity_id=updated_skill.skill_id,
        action="temporary_dedupe_rehome",
        from_version=skill.version,
        to_version=updated_skill.version,
        from_state=skill.status.value,
        to_state=updated_skill.status.value,
        summary=f"reassign_visible_family_to:{canonical_family}",
        provenance=provenance,
        related_entity_ids=[],
    )
    version_history = manager._history_payload(
        entity_type="skill",
        entity_id=updated_skill.skill_id,
        version=updated_skill.version,
        action="temporary_dedupe_rehome",
        status=updated_skill.status,
        related_entity_ids=[],
    )
    return {
        "skill": updated_skill,
        "provenance": provenance,
        "lifecycle": lifecycle,
        "change_log": change_log,
        "version_history": version_history,
    }


def repair_psychology_domain_global_dedupe(
    *,
    store_path: str,
    domain_root_name: str = "心理咨询",
    user_id: str = DEFAULT_DOC_SKILL_USER_ID,
    apply: bool = False,
) -> PsychologyGlobalDedupeSummary:
    """Repairs one visible psychology domain in-place or returns a dry-run summary."""

    store_root = os.path.abspath(os.path.expanduser(str(store_path or "").strip()))
    if not store_root:
        raise ValueError("store_path must not be empty")
    registry = DocumentRegistry(root_dir=default_registry_root(store_root))
    sdk = _build_sdk(store_path=store_root)
    manager = VersionManager(registry=registry, llm=MockLLM(response="{}"))

    visible_entries = scan_visible_domain(store_path=store_root, domain_root_name=domain_root_name)
    summary = PsychologyGlobalDedupeSummary(
        store_path=store_root,
        domain_root_name=safe_domain_name(domain_root_name),
        dry_run=(not apply),
        visible_skill_count=len(list(visible_entries or [])),
    )

    registry_skills = list(registry.list_skills())
    registry_supports = list(registry.list_supports())
    registry_documents = list(registry.list_documents())
    support_by_id = {support.support_id: support for support in registry_supports}
    skill_by_id = {skill.skill_id: skill for skill in registry_skills}
    domain_skills = _domain_skill_filter(registry_skills, domain_root_name=domain_root_name)
    summary.domain_skill_count = len(domain_skills)

    discovered_family_names = dedupe_strings(
        [entry.family_name for entry in list(visible_entries or [])]
        + [_family_name_for_skill(skill, metadata={}) for skill in domain_skills],
        lower=False,
    )
    family_names = _safe_family_names(discovered_family_names)
    if safe_domain_name(domain_root_name) == safe_domain_name("心理咨询"):
        family_names = _safe_family_names(_PSYCHOLOGY_FAMILY_NAMES)
    if not family_names:
        family_names = ["未分类技能"]

    changed_skills: Dict[str, SkillSpec] = {}
    changed_supports: Dict[str, SupportRecord] = {}
    lifecycles: List[Any] = []
    change_logs: List[Dict[str, Any]] = []
    version_history: List[Dict[str, Any]] = []
    provenance_links: List[Dict[str, Any]] = []

    visible_by_id: Dict[str, List[VisibleSkillArtifact]] = defaultdict(list)
    for entry in list(visible_entries or []):
        visible_by_id[str(entry.skill_id or "").strip()].append(entry)

    for skill_id, entries in sorted(visible_by_id.items()):
        families = dedupe_strings([entry.family_name for entry in entries], lower=False)
        if len(families) <= 1:
            continue
        skill = skill_by_id.get(skill_id)
        if skill is None:
            summary.orphan_visible_skill_ids.append(skill_id)
            summary.cross_family_groups.append(
                {
                    "skill_id": skill_id,
                    "families": families,
                    "canonical_family": "",
                    "orphan_visible_only": True,
                }
            )
            continue
        canonical_family = _choose_canonical_family(
            skill=skill,
            visible_entries=entries,
            support_by_id=support_by_id,
            family_names=family_names,
        )
        current_family = _family_name_for_skill(skill, metadata={})
        summary.cross_family_groups.append(
            {
                "skill_id": skill_id,
                "skill_name": skill.name,
                "families": families,
                "canonical_family": canonical_family,
                "current_family": current_family,
                "removed_families": [family for family in families if family != canonical_family],
            }
        )
        if not canonical_family or canonical_family == current_family:
            continue
        payload = _update_skill_family(
            manager=manager,
            skill=skill,
            canonical_family=canonical_family,
            support_by_id=support_by_id,
        )
        updated_skill = payload["skill"]
        skill_by_id[updated_skill.skill_id] = updated_skill
        changed_skills[updated_skill.skill_id] = updated_skill
        lifecycles.append(payload["lifecycle"])
        change_logs.append(payload["change_log"])
        version_history.append(payload["version_history"])
        provenance_links.append(payload["provenance"])

    current_domain_skills = [
        skill
        for skill in _domain_skill_filter(list(skill_by_id.values()), domain_root_name=domain_root_name)
        if skill.status in _VISIBLE_STATES
    ]
    duplicate_groups: Dict[Tuple[str, int, str, str], List[SkillSpec]] = defaultdict(list)
    for skill in current_domain_skills:
        family_name = _family_name_for_skill(skill, metadata={})
        key = (
            family_name,
            int(skill.asset_level or 0),
            str(skill.asset_node_id or "").strip(),
            normalize_text(str(skill.name or "").strip(), lower=True),
        )
        duplicate_groups[key].append(skill)

    for key, grouped_skills in sorted(duplicate_groups.items(), key=lambda item: item[0]):
        unique_ids = {skill.skill_id for skill in grouped_skills}
        if len(unique_ids) <= 1:
            continue
        merge_payload = _merge_duplicate_group(
            manager=manager,
            skills=grouped_skills,
            support_by_id=support_by_id,
        )
        canonical_skill = merge_payload["canonical"]
        changed_skills[canonical_skill.skill_id] = canonical_skill
        skill_by_id[canonical_skill.skill_id] = canonical_skill
        lifecycles.append(merge_payload["canonical_lifecycle"])
        change_logs.append(merge_payload["canonical_change_log"])
        version_history.append(merge_payload["canonical_version_history"])
        provenance_links.append(merge_payload["canonical_provenance"])
        for support_id, support in dict(merge_payload["support_updates"] or {}).items():
            changed_supports[support_id] = support
            support_by_id[support_id] = support
        for deprecated_payload in list(merge_payload["deprecated"] or []):
            deprecated_skill = deprecated_payload["skill"]
            changed_skills[deprecated_skill.skill_id] = deprecated_skill
            skill_by_id[deprecated_skill.skill_id] = deprecated_skill
            lifecycles.append(deprecated_payload["lifecycle"])
            change_logs.append(deprecated_payload["change_log"])
            version_history.append(deprecated_payload["version_history"])
            provenance_links.append(deprecated_payload["provenance"])
        summary.merged_groups.append(
            {
                "family_name": key[0],
                "asset_level": key[1],
                "asset_node_id": key[2],
                "normalized_name": key[3],
                "canonical_skill_id": canonical_skill.skill_id,
                "canonical_name": canonical_skill.name,
                "secondary_skill_ids": [item["skill"].skill_id for item in list(merge_payload["deprecated"] or [])],
            }
        )

    summary.updated_skill_ids = sorted(changed_skills.keys())
    summary.deprecated_skill_ids = sorted(
        [
            skill_id
            for skill_id, skill in changed_skills.items()
            if skill.status == VersionState.DEPRECATED
        ]
    )
    summary.rebound_support_count = len(changed_supports)

    if not apply:
        return summary

    for support in changed_supports.values():
        registry.upsert_support(support)
    for skill in changed_skills.values():
        registry.upsert_skill(skill)
    for lifecycle in lifecycles:
        registry.append_lifecycle(lifecycle)
    for payload in change_logs:
        registry.append_change_log(str(payload.get("change_id") or ""), payload)
    for entry in version_history:
        registry.append_version_history(
            entity_type=str(entry.get("entity_type") or ""),
            entity_id=str(entry.get("entity_id") or ""),
            entry=entry,
        )
    for payload in provenance_links:
        registry.upsert_provenance_links(
            entity_type=str(payload.get("entity_type") or ""),
            entity_id=str(payload.get("entity_id") or ""),
            payload=payload,
        )

    store_metadata = {
        "channel": "offline_extract_from_doc",
        "source_type": "document",
        "document_registry_root": registry.root_dir,
    }
    effective_user = str(user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID
    for skill in changed_skills.values():
        persisted = _store_skill_from_spec(skill, user_id=effective_user, metadata=store_metadata)
        existing = sdk.store.get(persisted.id)
        if persisted.status.name == "ARCHIVED" and existing is None:
            continue
        sdk.store.upsert(persisted)

    domain_dir = domain_visible_root(base_store_root=store_root, domain_root_name=domain_root_name)
    if os.path.isdir(domain_dir):
        shutil.rmtree(domain_dir)

    refreshed_skills = list(registry.list_skills())
    refreshed_supports = list(registry.list_supports())
    refreshed_documents = list(registry.list_documents())
    active_domain_skills = [
        skill
        for skill in _domain_skill_filter(refreshed_skills, domain_root_name=domain_root_name)
        if skill.status in _VISIBLE_STATES
    ]
    active_support_ids = {
        str(support_id or "").strip()
        for skill in list(active_domain_skills or [])
        for support_id in list(skill.support_ids or [])
        if str(support_id or "").strip()
    }
    active_supports = [support for support in refreshed_supports if support.support_id in active_support_ids]
    active_doc_ids = {str(support.doc_id or "").strip() for support in active_supports if str(support.doc_id or "").strip()}
    active_documents = [document for document in refreshed_documents if document.doc_id in active_doc_ids]
    visible_tree = sync_visible_skill_tree(
        registry=registry,
        store_root=store_root,
        documents=active_documents,
        support_records=active_supports,
        skill_specs=active_domain_skills,
        user_id=effective_user,
        metadata={"domain_root_name": safe_domain_name(domain_root_name)},
        store_skills=list(sdk.store.list(user_id=effective_user) or []),
    )
    summary.visible_tree = visible_tree.to_dict()
    return summary


def _render_summary(summary: PsychologyGlobalDedupeSummary) -> str:
    lines = [
        f"domain={summary.domain_root_name}",
        f"dry_run={str(summary.dry_run).lower()}",
        f"visible_skills={summary.visible_skill_count}",
        f"domain_skills={summary.domain_skill_count}",
        f"cross_family_groups={len(summary.cross_family_groups)}",
        f"merged_groups={len(summary.merged_groups)}",
        f"updated_skills={len(summary.updated_skill_ids)}",
        f"deprecated_skills={len(summary.deprecated_skill_ids)}",
        f"rebound_supports={summary.rebound_support_count}",
    ]
    if summary.cross_family_groups:
        lines.append("")
        lines.append("Cross-family groups:")
        for item in summary.cross_family_groups:
            lines.append(
                f"- {item.get('skill_name') or item.get('skill_id')} :: "
                f"{','.join(item.get('families') or [])} -> {item.get('canonical_family') or '-'}"
            )
    if summary.merged_groups:
        lines.append("")
        lines.append("Merged groups:")
        for item in summary.merged_groups:
            lines.append(
                f"- {item.get('family_name')} / {item.get('normalized_name')} :: "
                f"canonical={item.get('canonical_skill_id')} secondary={','.join(item.get('secondary_skill_ids') or [])}"
            )
    return "\n".join(lines).strip()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-off global dedupe repair for one psychology visible domain.",
    )
    parser.add_argument("--store-path", required=True, help="AutoSkill document store root, e.g. SkillBank/DocSkill")
    parser.add_argument("--domain-root-name", default="心理咨询", help="Visible domain root name to repair.")
    parser.add_argument("--user-id", default=DEFAULT_DOC_SKILL_USER_ID, help="Store user id for final skill sync.")
    parser.add_argument("--apply", action="store_true", help="Write registry/store changes and rebuild the visible tree.")
    parser.add_argument("--json", action="store_true", help="Print the summary as JSON.")
    args = parser.parse_args(None if argv is None else list(argv))

    summary = repair_psychology_domain_global_dedupe(
        store_path=str(args.store_path or "").strip(),
        domain_root_name=str(args.domain_root_name or "").strip() or "心理咨询",
        user_id=str(args.user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID,
        apply=bool(args.apply),
    )
    if args.json:
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
