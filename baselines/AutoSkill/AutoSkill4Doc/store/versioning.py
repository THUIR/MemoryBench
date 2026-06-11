"""
LLM-driven registry/version registration stage for the standalone document pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple

from autoskill import AutoSkill
from autoskill.llm.base import LLM
from autoskill.llm.factory import build_llm
from autoskill.models import Skill, SkillStatus
from autoskill.utils.time import now_iso

from ..core.common import (
    StageLogger,
    StageProgressCallback,
    emit_stage_log,
    emit_stage_progress,
    normalize_text,
    summarize_names,
)
from ..core.config import (
    DEFAULT_DOC_SKILL_USER_ID,
    DEFAULT_LLM_RATE_LIMIT_REQUESTS,
    DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
    DEFAULT_RETRIEVAL_SCORE_THRESHOLD,
)
from ..core.llm_utils import (
    clip_confidence,
    coerce_str_list,
    compact_text_list,
    llm_complete_json,
    llm_complete_json_with_retries,
    maybe_json_dict,
)
from ..core.rate_limit import AUTOSKILL4DOC_LLM_SCOPE, maybe_wrap_llm_with_rate_limit
from ..models import (
    DocumentRecord,
    SkillLifecycle,
    SkillSpec,
    SupportRecord,
    SupportRelation,
    VersionState,
)
from ..stages.compiler import _build_structured_prompt, _coerce_examples
from ..taxonomy import load_skill_taxonomy
from .registry import DocumentRegistry
from .retrieval import DEFAULT_RETRIEVAL_LIMIT, DocumentSkillRetriever, build_document_skill_retriever
from .staging import plain_skill_specs, write_registration_staging
from .visible_tree import sync_visible_skill_tree

if TYPE_CHECKING:
    from .intermediate import IntermediateRunWriter

_ACTIVE_STORE_STATES = {
    VersionState.CANDIDATE,
    VersionState.DRAFT,
    VersionState.EVALUATING,
    VersionState.ACTIVE,
    VersionState.WATCHLIST,
}

_REGISTER_HITS0_TIMEOUT_S = 300
_REGISTER_HITS0_MAX_TOKENS = 256
_REGISTER_HITS0_MAX_INPUT_CHARS = 12000
_REGISTER_FULL_TIMEOUT_S = 300
_REGISTER_FULL_MAX_TOKENS = 768
_REGISTER_FULL_MAX_INPUT_CHARS = 20000
_REGISTER_HIERARCHY_TIMEOUT_S = 180
_REGISTER_HIERARCHY_MAX_TOKENS = 128
_REGISTER_HIERARCHY_MAX_INPUT_CHARS = 8000


def _bump_patch(version: str) -> str:
    """Bumps a semantic version patch number."""

    parts = [p for p in str(version or "").split(".") if p.strip().isdigit()]
    if len(parts) != 3:
        return "0.1.1"
    major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    return f"{major}.{minor}.{patch + 1}"


def _plain_skill(skill: Any) -> Dict[str, Any]:
    """Serializes one persisted AutoSkill store record into a compact dict."""

    return {
        "id": str(getattr(skill, "id", "") or ""),
        "name": str(getattr(skill, "name", "") or ""),
        "description": str(getattr(skill, "description", "") or ""),
        "version": str(getattr(skill, "version", "") or ""),
        "status": str(getattr(getattr(skill, "status", None), "value", getattr(skill, "status", "")) or ""),
    }


def _register_change_decision_llm_config(
    base_config: Dict[str, Any],
    *,
    hits0_branch: bool,
) -> Dict[str, Any]:
    """Clones one provider config with fixed register/classify_change budgets."""

    cloned = dict(base_config or {})
    if hits0_branch:
        cloned["timeout_s"] = _REGISTER_HITS0_TIMEOUT_S
        cloned["max_tokens"] = _REGISTER_HITS0_MAX_TOKENS
        cloned["max_input_chars"] = _REGISTER_HITS0_MAX_INPUT_CHARS
    else:
        cloned["timeout_s"] = _REGISTER_FULL_TIMEOUT_S
        cloned["max_tokens"] = _REGISTER_FULL_MAX_TOKENS
        cloned["max_input_chars"] = _REGISTER_FULL_MAX_INPUT_CHARS
    return cloned


def _resolve_change_decision_llms(
    *,
    sdk: Optional[AutoSkill],
    fallback_llm: LLM,
) -> Tuple[LLM, LLM]:
    """Builds dedicated classify_change llms when sdk llm config is available."""

    llm_config = dict(getattr(getattr(sdk, "config", None), "llm", {}) or {})
    if not llm_config:
        return fallback_llm, fallback_llm
    hits0_llm = build_llm(_register_change_decision_llm_config(llm_config, hits0_branch=True))
    full_llm = build_llm(_register_change_decision_llm_config(llm_config, hits0_branch=False))
    return hits0_llm, full_llm


def _register_hierarchy_llm_config(base_config: Dict[str, Any]) -> Dict[str, Any]:
    """Clones one provider config with fixed register/hierarchy budgets."""

    cloned = dict(base_config or {})
    cloned["timeout_s"] = _REGISTER_HIERARCHY_TIMEOUT_S
    cloned["max_tokens"] = _REGISTER_HIERARCHY_MAX_TOKENS
    cloned["max_input_chars"] = _REGISTER_HIERARCHY_MAX_INPUT_CHARS
    return cloned


def _resolve_hierarchy_link_llm(
    *,
    sdk: Optional[AutoSkill],
    fallback_llm: LLM,
) -> LLM:
    """Builds one dedicated hierarchy-link llm when sdk llm config is available."""

    llm_config = dict(getattr(getattr(sdk, "config", None), "llm", {}) or {})
    if not llm_config:
        return fallback_llm
    return build_llm(_register_hierarchy_llm_config(llm_config))


def _copy_skill(
    skill: SkillSpec,
    *,
    skill_id: Optional[str] = None,
    version: Optional[str] = None,
    status: Optional[VersionState] = None,
    support_ids: Optional[List[str]] = None,
    metadata_update: Optional[Dict[str, Any]] = None,
) -> SkillSpec:
    """Creates a skill copy with updated identity/version/status fields."""

    payload = skill.to_dict()
    if skill_id is not None:
        payload["skill_id"] = str(skill_id or "").strip()
    if version is not None:
        payload["version"] = str(version or "0.1.0")
    if status is not None:
        payload["status"] = status.value
    if support_ids is not None:
        payload["support_ids"] = list(support_ids or [])
    md = dict(payload.get("metadata") or {})
    if metadata_update:
        md.update(dict(metadata_update or {}))
    payload["metadata"] = md
    return SkillSpec.from_dict(payload)


def _copy_skill_hierarchy(
    skill: SkillSpec,
    *,
    parent_skill_id: Optional[str] = None,
    parent_candidate_ids: Optional[List[str]] = None,
    child_skill_ids: Optional[List[str]] = None,
    hierarchy_confidence: Optional[float] = None,
    hierarchy_status: Optional[str] = None,
    visible_role: Optional[str] = None,
) -> SkillSpec:
    """Returns one skill copy with updated hierarchy fields."""

    payload = skill.to_dict()
    if parent_skill_id is not None:
        payload["parent_skill_id"] = str(parent_skill_id or "").strip()
    if parent_candidate_ids is not None:
        payload["parent_candidate_ids"] = list(parent_candidate_ids or [])
    if child_skill_ids is not None:
        payload["child_skill_ids"] = list(child_skill_ids or [])
    if hierarchy_confidence is not None:
        payload["hierarchy_confidence"] = float(hierarchy_confidence or 0.0)
    if hierarchy_status is not None:
        payload["hierarchy_status"] = str(hierarchy_status or "").strip()
    if visible_role is not None:
        payload["visible_role"] = str(visible_role or "").strip()
    md = dict(payload.get("metadata") or {})
    if parent_skill_id is not None:
        md["parent_skill_id"] = str(parent_skill_id or "").strip()
    if parent_candidate_ids is not None:
        md["parent_candidate_ids"] = list(parent_candidate_ids or [])
    if child_skill_ids is not None:
        md["child_skill_ids"] = list(child_skill_ids or [])
    if hierarchy_confidence is not None:
        md["hierarchy_confidence"] = float(hierarchy_confidence or 0.0)
    if hierarchy_status is not None:
        md["hierarchy_status"] = str(hierarchy_status or "").strip()
    if visible_role is not None:
        md["visible_role"] = str(visible_role or "").strip()
    payload["metadata"] = md
    return SkillSpec.from_dict(payload)


def _copy_support(
    support: SupportRecord,
    *,
    skill_id: str,
    relation_type: Optional[SupportRelation] = None,
    metadata_update: Optional[Dict[str, Any]] = None,
) -> SupportRecord:
    """Creates a support copy rebound to one canonical skill id."""

    payload = support.to_dict()
    payload["skill_id"] = str(skill_id or "").strip()
    if relation_type is not None:
        payload["relation_type"] = relation_type.value
    md = dict(payload.get("metadata") or {})
    if metadata_update:
        md.update(dict(metadata_update or {}))
    payload["metadata"] = md
    return SupportRecord.from_dict(payload)


def _prompt_prefix_from_body(value: str) -> str:
    """Extracts the freeform prompt prefix before structured markdown sections."""

    lines: List[str] = []
    for raw_line in str(value or "").splitlines():
        if raw_line.strip().startswith("## "):
            break
        lines.append(raw_line.rstrip())
    return "\n".join(lines).strip()


def _identity_key_parts(skill: SkillSpec) -> Dict[str, str]:
    """Parses stable identity key fields when present on one skill."""

    raw = str((skill.metadata or {}).get("identity_key") or "").strip()
    if not raw:
        return {}
    parts = raw.split("|")
    if len(parts) < 12:
        return {}
    return {
        "taxonomy_id": str(parts[0] or "").strip(),
        "profile_id": str(parts[1] or "").strip(),
        "family_scope": str(parts[2] or "").strip(),
        "asset_type": str(parts[3] or "").strip(),
        "granularity": str(parts[4] or "").strip(),
        "asset_node_id": str(parts[5] or "").strip(),
        "objective": str(parts[6] or "").strip(),
        "domain": str(parts[7] or "").strip(),
        "task_family": str(parts[8] or "").strip(),
        "method_family": str(parts[9] or "").strip(),
        "stage": str(parts[10] or "").strip(),
        "name": str(parts[11] or "").strip(),
    }


def _effective_asset_type(skill: SkillSpec) -> str:
    """Returns the best-known asset type, preferring historical identity metadata."""

    return str(_identity_key_parts(skill).get("asset_type") or skill.asset_type or "").strip()


def _effective_granularity(skill: SkillSpec) -> str:
    """Returns the best-known granularity, preferring historical identity metadata."""

    return str(_identity_key_parts(skill).get("granularity") or skill.granularity or "").strip()


def _effective_asset_node_id(skill: SkillSpec) -> str:
    """Returns the best-known hierarchy node id, preferring historical identity metadata."""

    identity_parts = _identity_key_parts(skill)
    return str(
        identity_parts.get("asset_node_id")
        or getattr(skill, "asset_node_id", "")
        or (skill.metadata or {}).get("asset_node_id")
        or ""
    ).strip()


def _visible_family_name(skill: SkillSpec, *, metadata: Optional[Dict[str, Any]]) -> str:
    """Returns the visible family label used for duplicate-bucket scoping."""

    skill_md = dict(skill.metadata or {})
    candidates = [
        str(skill_md.get("family_name") or "").strip(),
        str(skill_md.get("school_name") or "").strip(),
        str((metadata or {}).get("family_name") or "").strip(),
        str((metadata or {}).get("school_name") or "").strip(),
        str(skill_md.get("taxonomy_class") or "").strip(),
        str(skill.domain or "").strip(),
        str(skill.method_family or "").strip(),
        "未分类技能",
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return "未分类技能"


def _family_scope_key(skill: SkillSpec, *, metadata: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Builds the scope key used when scanning for duplicate visible skills."""

    skill_md = dict(skill.metadata or {})
    profile_id = (
        str(skill_md.get("profile_id") or "").strip()
        or str((metadata or {}).get("profile_id") or "").strip()
        or "document_profile"
    )
    family_key = normalize_text(_visible_family_name(skill, metadata=metadata), lower=True)
    return profile_id, family_key


def _duplicate_group_key(skill: SkillSpec, *, metadata: Optional[Dict[str, Any]]) -> Tuple[str, str, str, str, str, int, str]:
    """Builds the deterministic grouping key for visible duplicate consolidation."""

    profile_id, family_key = _family_scope_key(skill, metadata=metadata)
    return (
        profile_id,
        family_key,
        normalize_text(_effective_asset_type(skill), lower=True),
        normalize_text(_effective_granularity(skill), lower=True),
        normalize_text(_effective_asset_node_id(skill), lower=True),
        max(0, int(skill.asset_level or 0)),
        normalize_text(skill.name, lower=True),
    )


def _semver_sort_key(version: str) -> Tuple[int, int, int]:
    """Parses a semver-like version into a sortable tuple."""

    parts: List[int] = []
    for raw in str(version or "").split("."):
        try:
            parts.append(int(str(raw or "").strip()))
        except Exception:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return int(parts[0]), int(parts[1]), int(parts[2])


def _content_completeness_score(skill: SkillSpec) -> int:
    """Scores how much structured content one skill already carries."""

    return sum(
        [
            len(list(skill.applicable_signals or [])),
            len(list(skill.contraindications or [])),
            len(list(skill.intervention_moves or [])),
            len(list(skill.triggers or [])),
            len(list(skill.workflow_steps or [])),
            len(list(skill.constraints or [])),
            len(list(skill.cautions or [])),
            len(list(skill.output_contract or [])),
            len(list(skill.examples or [])),
            len(list(skill.tags or [])),
            1 if str(skill.description or "").strip() else 0,
            1 if str(skill.skill_body or "").strip() else 0,
        ]
    )


def _duplicate_primary_sort_key(skill: SkillSpec, *, preexisting_ids: Set[str]) -> Tuple[int, int, int, int, int, int, int, int, str]:
    """Builds the stable ordering used to choose one canonical duplicate skill."""

    hierarchy_status = str(skill.hierarchy_status or "").strip().lower()
    hierarchy_rank = 2 if hierarchy_status == "linked" else 1 if hierarchy_status in {"parent", "root"} else 0
    version_major, version_minor, version_patch = _semver_sort_key(skill.version)
    return (
        0 if skill.skill_id in preexisting_ids else 1,
        0 if skill.status == VersionState.ACTIVE else 1,
        -hierarchy_rank,
        -len(list(skill.support_ids or [])),
        -version_major,
        -version_minor,
        -version_patch,
        -_content_completeness_score(skill),
        str(skill.skill_id or "").strip(),
    )


def _merge_text_lists(*groups: Sequence[str]) -> List[str]:
    """Merges multiple string lists while preserving first-seen order."""

    out: List[str] = []
    seen: Set[str] = set()
    for group in groups:
        for item in list(group or []):
            value = str(item or "").strip()
            key = normalize_text(value, lower=True)
            if not value or not key or key in seen:
                continue
            seen.add(key)
            out.append(value)
    return out


def _merge_examples(*groups: Sequence[Any]) -> List[Any]:
    """Merges example payloads while preserving canonical order."""

    out: List[Any] = []
    seen: Set[Tuple[str, str, str]] = set()
    for group in groups:
        for example in list(group or []):
            input_text = str(getattr(example, "input", "") or "").strip()
            output_text = str(getattr(example, "output", "") or "").strip()
            notes_text = str(getattr(example, "notes", "") or "").strip()
            key = (
                normalize_text(input_text, lower=True),
                normalize_text(output_text, lower=True),
                normalize_text(notes_text, lower=True),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            out.append(example)
    return out


def _support_summary_for_skill(skill: SkillSpec, *, support_by_id: Dict[str, SupportRecord]) -> Dict[str, int]:
    """Recomputes support relation counts after local duplicate consolidation."""

    counts = {
        SupportRelation.SUPPORT.value: 0,
        SupportRelation.CONSTRAINT.value: 0,
        SupportRelation.CONFLICT.value: 0,
        SupportRelation.CASE_VARIANT.value: 0,
    }
    for support_id in list(skill.support_ids or []):
        support = support_by_id.get(str(support_id or "").strip())
        if support is None:
            continue
        counts[support.relation_type.value] = counts.get(support.relation_type.value, 0) + 1
    return counts


def _skill_with_frozen_identity(
    *,
    base: SkillSpec,
    content: SkillSpec,
    version: Optional[str] = None,
    status: Optional[VersionState] = None,
    support_ids: Optional[List[str]] = None,
    metadata_update: Optional[Dict[str, Any]] = None,
) -> SkillSpec:
    """Applies content updates onto one skill while preserving its identity surface."""

    payload = base.to_dict()
    payload["description"] = str(content.description or base.description).strip()
    payload["skill_body"] = str(content.skill_body or base.skill_body).strip()
    payload["applicable_signals"] = list(content.applicable_signals or base.applicable_signals or [])
    payload["contraindications"] = list(content.contraindications or base.contraindications or [])
    payload["intervention_moves"] = list(content.intervention_moves or base.intervention_moves or [])
    payload["workflow_steps"] = list(content.workflow_steps or base.workflow_steps or [])
    payload["constraints"] = list(content.constraints or base.constraints or [])
    payload["cautions"] = list(content.cautions or base.cautions or [])
    payload["output_contract"] = list(content.output_contract or base.output_contract or [])
    payload["examples"] = [
        {
            "input": str(example.input or ""),
            "output": str(example.output or ""),
            "notes": str(example.notes or ""),
        }
        for example in list(content.examples or base.examples or [])
    ]
    payload["tags"] = list(content.tags or base.tags or [])
    payload["triggers"] = list(base.triggers or [])
    if version is not None:
        payload["version"] = str(version or "0.1.0")
    if status is not None:
        payload["status"] = status.value
    if support_ids is not None:
        payload["support_ids"] = list(support_ids or [])
    md = dict(payload.get("metadata") or {})
    if metadata_update:
        md.update(dict(metadata_update or {}))
    payload["metadata"] = md
    return SkillSpec.from_dict(payload)


def _rewrite_skill_links(skill: SkillSpec, *, replace_map: Dict[str, str]) -> SkillSpec:
    """Rewrites parent/child references when secondary duplicate ids collapse into a canonical id."""

    if not replace_map:
        return skill
    payload = skill.to_dict()
    parent_skill_id = str(payload.get("parent_skill_id") or "").strip()
    child_skill_ids = [replace_map.get(str(item or "").strip(), str(item or "").strip()) for item in list(payload.get("child_skill_ids") or [])]
    parent_candidate_ids = [
        replace_map.get(str(item or "").strip(), str(item or "").strip())
        for item in list(payload.get("parent_candidate_ids") or [])
    ]
    if parent_skill_id:
        payload["parent_skill_id"] = replace_map.get(parent_skill_id, parent_skill_id)
    payload["child_skill_ids"] = list(dict.fromkeys([item for item in child_skill_ids if item]))
    payload["parent_candidate_ids"] = list(dict.fromkeys([item for item in parent_candidate_ids if item]))
    md = dict(payload.get("metadata") or {})
    if str(md.get("parent_skill_id") or "").strip():
        md["parent_skill_id"] = replace_map.get(str(md.get("parent_skill_id") or "").strip(), str(md.get("parent_skill_id") or "").strip())
    if isinstance(md.get("child_skill_ids"), list):
        md["child_skill_ids"] = list(
            dict.fromkeys(
                [
                    replace_map.get(str(item or "").strip(), str(item or "").strip())
                    for item in list(md.get("child_skill_ids") or [])
                    if str(item or "").strip()
                ]
            )
        )
    if isinstance(md.get("parent_candidate_ids"), list):
        md["parent_candidate_ids"] = list(
            dict.fromkeys(
                [
                    replace_map.get(str(item or "").strip(), str(item or "").strip())
                    for item in list(md.get("parent_candidate_ids") or [])
                    if str(item or "").strip()
                ]
            )
        )
    payload["metadata"] = md
    return SkillSpec.from_dict(payload)


def _same_asset_layer(left: SkillSpec, right: SkillSpec) -> bool:
    """Checks whether two skills live at the same asset type and granularity."""

    return (
        _effective_asset_type(left) == _effective_asset_type(right)
        and _effective_granularity(left) == _effective_granularity(right)
    )


def _same_asset_node(left: SkillSpec, right: SkillSpec) -> bool:
    """Checks whether two skills live under the same configured hierarchy node."""

    left_node = _effective_asset_node_id(left)
    right_node = _effective_asset_node_id(right)
    if left_node and right_node:
        return left_node == right_node
    return True


def _granularity_rank(value: str) -> int:
    """Maps granularity labels into a stable coarse-to-fine rank."""

    raw = str(value or "").strip().lower()
    if raw == "macro":
        return 0
    if raw == "micro":
        return 2
    return 1


def _doc_ids_from_support_ids(support_ids: Sequence[str], support_by_id: Dict[str, SupportRecord]) -> List[str]:
    """Collects source document ids for one support reference set."""

    seen = set()
    out: List[str] = []
    for support_id in support_ids or []:
        support = support_by_id.get(str(support_id or "").strip())
        if support is None:
            continue
        doc_id = str(support.doc_id or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        out.append(doc_id)
    return out


def _plausible_parent_candidate(child: SkillSpec, parent: SkillSpec, *, score: float) -> bool:
    """Returns whether one parent hit is strong enough for automatic fallback attachment."""

    if float(score or 0.0) >= 0.05:
        return True
    for field in ("task_family", "method_family", "stage"):
        left = normalize_text(getattr(child, field, ""), lower=True)
        right = normalize_text(getattr(parent, field, ""), lower=True)
        if left and right and left == right:
            return True
    child_tokens = {token for token in normalize_text(f"{child.name} {child.objective}", lower=True).split() if token}
    parent_tokens = {token for token in normalize_text(f"{parent.name} {parent.objective}", lower=True).split() if token}
    return len(child_tokens & parent_tokens) >= 2


def _needs_peer_context(
    skill: SkillSpec,
    *,
    peer_skills: Sequence[SkillSpec],
    existing_skills: Sequence[SkillSpec],
) -> bool:
    """Returns whether classify_change() should include same-batch peers."""

    if not peer_skills or not existing_skills:
        return False
    child_rank = _granularity_rank(skill.granularity)
    child_level = int(skill.asset_level or 0)
    for existing in existing_skills or []:
        if _granularity_rank(existing.granularity) < child_rank:
            return True
        existing_level = int(existing.asset_level or 0)
        if child_level > 0 and existing_level > 0 and existing_level < child_level:
            return True
    return False


def _conflicting_support_ids(support_ids: Sequence[str], support_by_id: Dict[str, SupportRecord]) -> List[str]:
    """Collects support ids explicitly marked as conflicts."""

    out: List[str] = []
    seen = set()
    for support_id in support_ids or []:
        support = support_by_id.get(str(support_id or "").strip())
        if support is None or support.relation_type != SupportRelation.CONFLICT:
            continue
        if support.support_id in seen:
            continue
        seen.add(support.support_id)
        out.append(support.support_id)
    return out


def _clip_text(value: str, limit: int) -> str:
    """Returns one normalized string clipped to a stable maximum length."""

    text = normalize_text(str(value or ""))
    max_len = max(0, int(limit or 0))
    if not text or max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3].rstrip() + "..."


def _clip_list(values: Sequence[str], limit: int, item_limit: int) -> List[str]:
    """Keeps a short deduplicated list with each item clipped."""

    out: List[str] = []
    for value in compact_text_list(list(values or []), limit=max(1, int(limit or 1))):
        clipped = _clip_text(str(value or ""), item_limit)
        if clipped:
            out.append(clipped)
    return out


def _support_summary_for_change_decision(
    skill: SkillSpec,
    support_by_id: Dict[str, SupportRecord],
) -> Dict[str, Any]:
    """Builds one compact evidence summary for change classification."""

    support_count = 0
    conflict_count = 0
    sections: List[str] = []
    snippets: List[str] = []
    for support_id in list(skill.support_ids or []):
        support = support_by_id.get(str(support_id or "").strip())
        if support is None:
            continue
        if support.relation_type == SupportRelation.CONFLICT:
            conflict_count += 1
        else:
            support_count += 1
        section_label = str(support.section or support.source_file or "").strip()
        if section_label:
            sections.append(section_label)
        excerpt = _clip_text(str(support.excerpt or ""), 180)
        if excerpt:
            relation = str(support.relation_type.value or "").strip().upper()
            if section_label:
                snippets.append(f"{relation} | {section_label}: {excerpt}")
            else:
                snippets.append(f"{relation} | {excerpt}")
    return {
        "support_count": support_count,
        "conflict_count": conflict_count,
        "support_sections": _clip_list(sections, limit=4, item_limit=80),
        "evidence_snippets": _clip_list(snippets, limit=2, item_limit=240),
    }


def _compact_skill_for_change_decision(
    skill: SkillSpec,
    support_by_id: Dict[str, SupportRecord],
    *,
    include_evidence: bool,
) -> Dict[str, Any]:
    """Serializes one skill into the minimal payload needed for change decisions."""

    payload = {
        "skill_id": str(skill.skill_id or "").strip(),
        "name": _clip_text(skill.name, 120),
        "description": _clip_text(skill.description, 280),
        "asset_type": _clip_text(skill.asset_type, 48),
        "granularity": _clip_text(skill.granularity, 32),
        "asset_node_id": _clip_text(skill.asset_node_id, 96),
        "asset_level": int(skill.asset_level or 0),
        "objective": _clip_text(skill.objective, 280),
        "domain": _clip_text(skill.domain, 64),
        "task_family": _clip_text(skill.task_family, 96),
        "method_family": _clip_text(skill.method_family, 96),
        "stage": _clip_text(skill.stage, 96),
        "workflow_steps": _clip_list(skill.workflow_steps, limit=6, item_limit=180),
        "intervention_moves": _clip_list(skill.intervention_moves, limit=6, item_limit=180),
        "constraints": _clip_list(skill.constraints, limit=4, item_limit=180),
        "cautions": _clip_list(skill.cautions, limit=4, item_limit=180),
    }
    if include_evidence:
        payload["support_summary"] = _support_summary_for_change_decision(skill, support_by_id)
    return payload


def _peer_relevance_score(candidate: SkillSpec, peer: SkillSpec) -> float:
    """Ranks same-batch peers by how useful they are for split/discard decisions."""

    if str(peer.skill_id or "").strip() == str(candidate.skill_id or "").strip():
        return float("-inf")

    score = 0.0
    if str(candidate.asset_type or "").strip() == str(peer.asset_type or "").strip():
        score += 10.0
    if str(candidate.granularity or "").strip() == str(peer.granularity or "").strip():
        score += 10.0
    candidate_node = str(candidate.asset_node_id or "").strip()
    peer_node = str(peer.asset_node_id or "").strip()
    if candidate_node and peer_node and candidate_node == peer_node:
        score += 10.0

    for field_name in ("task_family", "method_family", "stage"):
        left = normalize_text(getattr(candidate, field_name, ""), lower=True)
        right = normalize_text(getattr(peer, field_name, ""), lower=True)
        if left and right and left == right:
            score += 4.0

    candidate_tokens = set(normalize_text(f"{candidate.name} {candidate.objective}", lower=True).split())
    peer_tokens = set(normalize_text(f"{peer.name} {peer.objective}", lower=True).split())
    candidate_tokens.discard("")
    peer_tokens.discard("")
    score += min(3.0, float(len(candidate_tokens & peer_tokens)))
    return score


def _support_lookup(
    registry: DocumentRegistry,
    support_records: Sequence[SupportRecord],
) -> Dict[str, SupportRecord]:
    """Builds a combined support index from registry state and the current batch."""

    out = {support.support_id: support for support in registry.list_supports()}
    for support in support_records or []:
        out[support.support_id] = support
    return out


@dataclass
class ChangeDecision:
    """Decision returned by LLM-backed skill change classification."""

    action: str
    skill: SkillSpec
    matched_skill_ids: List[str] = field(default_factory=list)
    reason: str = ""
    split_parent_id: str = ""
    hits: int = 0
    branch: str = ""


@dataclass
class VersionRegistrationResult:
    """Output of the registry/version registration stage."""

    documents: List[DocumentRecord] = field(default_factory=list)
    support_records: List[SupportRecord] = field(default_factory=list)
    skill_specs: List[SkillSpec] = field(default_factory=list)
    hierarchy_updates: List[SkillSpec] = field(default_factory=list)
    lifecycles: List[SkillLifecycle] = field(default_factory=list)
    change_logs: List[Dict[str, Any]] = field(default_factory=list)
    version_history: List[Dict[str, Any]] = field(default_factory=list)
    provenance_links: List[Dict[str, Any]] = field(default_factory=list)
    upserted_store_skills: List[Dict[str, Any]] = field(default_factory=list)
    staging_runs: List[Dict[str, Any]] = field(default_factory=list)
    visible_tree: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, str]] = field(default_factory=list)
    dry_run: bool = False


def _layout_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Collects visible-layout metadata carried by one run."""

    md = dict(metadata or {})
    family_name = str(md.get("family_name") or md.get("school_name") or "").strip()
    return {
        "family_name": family_name,
        "family_id": str(md.get("family_id") or "").strip(),
        "profile_id": str(md.get("profile_id") or "").strip(),
        "taxonomy_axis": str(md.get("taxonomy_axis") or "").strip(),
        "taxonomy_class": str(md.get("taxonomy_class") or "").strip(),
        "domain_root_name": str(md.get("domain_root_name") or "").strip(),
        "domain_root_id": str(md.get("domain_root_id") or "").strip(),
        "family_bucket_label": str(md.get("family_bucket_label") or "").strip(),
        "visible_levels": dict(md.get("visible_levels") or {}) if isinstance(md.get("visible_levels"), dict) else {},
        "child_type": str(md.get("child_type") or "").strip(),
    }


def _merge_layout_metadata(
    skill: SkillSpec,
    *,
    metadata: Optional[Dict[str, Any]],
) -> SkillSpec:
    """Attaches run-level layout metadata to a skill spec for later visible-tree sync."""

    layout_md = {key: value for key, value in _layout_metadata(metadata).items() if value}
    if not layout_md:
        return skill
    existing = dict(skill.metadata or {})
    merged_update: Dict[str, Any] = {}
    for key, value in layout_md.items():
        current = existing.get(key)
        if isinstance(current, dict) and current:
            continue
        if isinstance(current, list) and current:
            continue
        if str(current or "").strip():
            continue
        merged_update[key] = value
    if not merged_update:
        return skill
    return _copy_skill(skill, metadata_update=merged_update)


def _store_root_from_context(*, registry: DocumentRegistry, sdk: Optional[AutoSkill]) -> str:
    """Infers the visible skill library root from the SDK or registry location."""

    if sdk is not None:
        raw = str(getattr(getattr(sdk, "config", None), "store", {}).get("path") or "").strip()
        if raw:
            return os.path.abspath(os.path.expanduser(raw))
    registry_root = os.path.abspath(os.path.expanduser(str(registry.root_dir or "").strip()))
    runtime_dir = os.path.dirname(registry_root)
    if os.path.basename(runtime_dir) == ".runtime":
        return os.path.dirname(runtime_dir)
    if os.path.basename(registry_root) == ".runtime":
        return os.path.dirname(registry_root)
    return os.path.dirname(registry_root)


def _store_status_for_skill(skill: SkillSpec) -> SkillStatus:
    """Maps one document lifecycle state into the final AutoSkill store status."""

    return SkillStatus.ACTIVE if skill.status in _ACTIVE_STORE_STATES else SkillStatus.ARCHIVED


def _store_metadata_for_skill(skill: SkillSpec, *, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Builds final store metadata from one reconciled document skill."""

    merged = dict(metadata or {})
    merged.update(dict(skill.metadata or {}))
    merged["_autoskill_asset_type"] = str(skill.asset_type or "").strip()
    merged["_autoskill_granularity"] = str(skill.granularity or "").strip()
    merged["_autoskill_asset_node_id"] = str(skill.asset_node_id or "").strip()
    merged["asset_type"] = str(skill.asset_type or "").strip()
    merged["granularity"] = str(skill.granularity or "").strip()
    merged["asset_node_id"] = str(skill.asset_node_id or "").strip()
    merged["asset_path"] = str(skill.asset_path or "").strip()
    merged["asset_level"] = int(skill.asset_level or 0)
    merged["parent_skill_id"] = str(skill.parent_skill_id or "").strip()
    merged["child_skill_ids"] = list(skill.child_skill_ids or [])
    merged["hierarchy_confidence"] = float(skill.hierarchy_confidence or 0.0)
    merged["hierarchy_status"] = str(skill.hierarchy_status or "").strip()
    merged["visible_role"] = str(skill.visible_role or "").strip()
    merged["source_type"] = "document_skill"
    return merged


def _store_source_for_skill(skill: SkillSpec) -> Dict[str, Any]:
    """Builds stable source metadata carried into the final store skill."""

    return {
        "source_type": "document_skill",
        "skill_spec_id": skill.skill_id,
        "asset_type": skill.asset_type,
        "granularity": skill.granularity,
        "asset_node_id": skill.asset_node_id,
        "asset_path": skill.asset_path,
        "asset_level": skill.asset_level,
        "parent_skill_id": skill.parent_skill_id,
        "child_skill_ids": list(skill.child_skill_ids or []),
        "hierarchy_confidence": skill.hierarchy_confidence,
        "hierarchy_status": skill.hierarchy_status,
        "visible_role": skill.visible_role,
        "objective": skill.objective,
        "support_ids": list(skill.support_ids or []),
        "domain": skill.domain,
        "task_family": skill.task_family,
        "method_family": skill.method_family,
        "stage": skill.stage,
        "version": skill.version,
        "status": skill.status.value,
    }


def _store_files_for_skill(skill: SkillSpec) -> Dict[str, str]:
    """Returns any extra files that should be persisted with the final store skill."""

    files = maybe_json_dict((skill.metadata or {}).get("files"))
    if not isinstance(files, dict):
        return {}
    return {str(path): str(content) for path, content in files.items()}


def _store_skill_from_spec(
    skill: SkillSpec,
    *,
    user_id: str,
    metadata: Optional[Dict[str, Any]],
) -> Skill:
    """Builds one final AutoSkill store skill directly from a reconciled document skill."""

    return Skill(
        id=str(skill.skill_id or "").strip(),
        user_id=str(user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID,
        name=str(skill.name or "").strip(),
        description=str(skill.description or "").strip(),
        instructions=str(skill.skill_body or "").strip(),
        triggers=list(skill.triggers or []),
        examples=list(skill.examples or []),
        tags=list(skill.tags or []),
        version=str(skill.version or "0.1.0"),
        status=_store_status_for_skill(skill),
        files=_store_files_for_skill(skill),
        source=_store_source_for_skill(skill),
        metadata=_store_metadata_for_skill(skill, metadata=metadata),
        updated_at=now_iso(),
    )


def _sync_store_skills(
    *,
    sdk: AutoSkill,
    skill_specs: Sequence[SkillSpec],
    user_id: str,
    metadata: Optional[Dict[str, Any]],
    logger: StageLogger,
) -> Tuple[List[Skill], List[Skill]]:
    """
    Persists reconciled document skills directly into the final store.

    This bypasses the generic SDK maintainer so AutoSkill4Doc keeps control over
    asset-layer boundaries such as `asset_type` and `granularity`.
    """

    effective_user = str(user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID
    deduped: Dict[str, SkillSpec] = {}
    for item in list(skill_specs or []):
        key = str(item.skill_id or "").strip()
        if key:
            deduped[key] = item

    touched: List[Skill] = []
    for item in deduped.values():
        persisted = _store_skill_from_spec(item, user_id=effective_user, metadata=metadata)
        existing = sdk.store.get(persisted.id)
        if persisted.status == SkillStatus.ARCHIVED and existing is None:
            continue
        sdk.store.upsert(persisted)
        touched.append(persisted)

    try:
        current_active = list(sdk.store.list(user_id=effective_user) or [])
    except Exception:
        current_active = []

    emit_stage_log(
        logger,
        f"[register_versions] store_sync touched={len(touched)} active={len(current_active)} names={summarize_names([skill.name for skill in touched])}",
    )
    return touched, current_active


def _staging_bucket_for_skill(skill: SkillSpec, *, metadata: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    """Builds one `(profile_id, family_id, child_type)` staging bucket tuple."""

    md = dict(metadata or {})
    skill_md = dict(skill.metadata or {})
    profile_id = (
        str(skill_md.get("profile_id") or "").strip()
        or str(md.get("profile_id") or "").strip()
        or "document_profile"
    )
    family_id = (
        str(skill_md.get("family_name") or "").strip()
        or str(skill_md.get("school_name") or "").strip()
        or str(md.get("family_name") or "").strip()
        or str(skill_md.get("taxonomy_class") or "").strip()
        or str(md.get("school_name") or "").strip()
        or str(skill.domain or "").strip()
        or str(skill.method_family or "").strip()
        or "unknown_family"
    )
    child_type = (
        str(skill_md.get("child_type") or "").strip()
        or str(skill.task_family or "").strip()
        or str(skill.asset_type or "").strip()
        or str(md.get("child_type") or "").strip()
        or "general_child"
    )
    return profile_id, family_id, child_type


class VersionManager:
    """LLM-backed version and lifecycle manager for document builds."""

    def __init__(
        self,
        *,
        registry: DocumentRegistry,
        llm: LLM,
        hits0_change_llm: Optional[LLM] = None,
        full_change_llm: Optional[LLM] = None,
        hierarchy_link_llm: Optional[LLM] = None,
        retriever: Optional[DocumentSkillRetriever] = None,
        retrieval_limit: int = DEFAULT_RETRIEVAL_LIMIT,
        logger: StageLogger = None,
        progress_callback: StageProgressCallback = None,
    ) -> None:
        self.registry = registry
        self.llm = llm
        self.hits0_change_llm = hits0_change_llm or llm
        self.full_change_llm = full_change_llm or llm
        self.hierarchy_link_llm = hierarchy_link_llm or llm
        self.retriever = retriever
        self.retrieval_limit = max(1, int(retrieval_limit or DEFAULT_RETRIEVAL_LIMIT))
        self.logger = logger
        self.progress_callback = progress_callback

    @staticmethod
    def _compact_text(value: Any, *, limit: int = 240) -> str:
        """Returns one short normalized text field suitable for hot-path LLM payloads."""

        text = normalize_text(str(value or ""))
        if len(text) <= max(0, int(limit or 0)):
            return text
        return text[: max(0, int(limit or 0))].rstrip() + "..."

    def _support_summary_for_llm(self, skill: SkillSpec, *, support_by_id: Dict[str, SupportRecord]) -> Dict[str, Any]:
        """Builds one compact support summary for version decisions."""

        supports = [
            support_by_id.get(str(support_id or "").strip())
            for support_id in list(skill.support_ids or [])
        ]
        resolved = [support for support in supports if support is not None]
        relation_counts: Dict[str, int] = {}
        conflict_count = 0
        for support in resolved:
            relation = str(support.relation_type.value or "").strip()
            relation_counts[relation] = int(relation_counts.get(relation) or 0) + 1
            if support.relation_type == SupportRelation.CONFLICT:
                conflict_count += 1
        return {
            "count": len(resolved),
            "conflict_count": conflict_count,
            "relation_counts": relation_counts,
            "sections": compact_text_list([str(support.section or "").strip() for support in resolved], limit=4),
        }

    def _skill_for_llm(self, skill: SkillSpec, *, support_by_id: Dict[str, SupportRecord]) -> Dict[str, Any]:
        return {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "prompt": skill.skill_body,
            "asset_type": skill.asset_type,
            "granularity": skill.granularity,
            "asset_node_id": skill.asset_node_id,
            "asset_path": skill.asset_path,
            "asset_level": skill.asset_level,
            "visible_role": skill.visible_role,
            "objective": skill.objective,
            "domain": skill.domain,
            "task_family": skill.task_family,
            "method_family": skill.method_family,
            "stage": skill.stage,
            "applicable_signals": list(skill.applicable_signals or []),
            "contraindications": list(skill.contraindications or []),
            "intervention_moves": list(skill.intervention_moves or []),
            "triggers": list(skill.triggers or []),
            "workflow_steps": list(skill.workflow_steps or []),
            "constraints": list(skill.constraints or []),
            "cautions": list(skill.cautions or []),
            "output_contract": list(skill.output_contract or []),
            "examples": [
                {
                    "input": str(example.input or ""),
                    "output": str(example.output or ""),
                    "notes": str(example.notes or ""),
                }
                for example in list(skill.examples or [])
            ],
            "tags": list(skill.tags or []),
            "support_ids": list(skill.support_ids or []),
            "support_excerpt_summaries": [
                {
                    "support_id": support.support_id,
                    "relation_type": support.relation_type.value,
                    "section": support.section,
                    "excerpt": support.excerpt,
                }
                for support_id in list(skill.support_ids or [])
                for support in [support_by_id.get(str(support_id or "").strip())]
                if support is not None
            ],
            "version": skill.version,
            "status": skill.status.value,
            "metadata": dict(skill.metadata or {}),
        }

    def _skill_for_change_llm(self, skill: SkillSpec, *, support_by_id: Dict[str, SupportRecord]) -> Dict[str, Any]:
        """Builds one compact skill payload for high-frequency classify_change() calls."""

        return {
            "skill_id": skill.skill_id,
            "name": self._compact_text(skill.name, limit=120),
            "description": self._compact_text(skill.description, limit=220),
            "asset_type": str(skill.asset_type or "").strip(),
            "granularity": str(skill.granularity or "").strip(),
            "asset_node_id": str(skill.asset_node_id or "").strip(),
            "asset_level": int(skill.asset_level or 0),
            "visible_role": str(skill.visible_role or "").strip(),
            "objective": self._compact_text(skill.objective, limit=220),
            "domain": str(skill.domain or "").strip(),
            "task_family": str(skill.task_family or "").strip(),
            "method_family": str(skill.method_family or "").strip(),
            "stage": str(skill.stage or "").strip(),
            "applicable_signals": list(skill.applicable_signals or [])[:3],
            "contraindications": list(skill.contraindications or [])[:3],
            "triggers": list(skill.triggers or [])[:3],
            "workflow_steps": list(skill.workflow_steps or [])[:6],
            "constraints": list(skill.constraints or [])[:4],
            "cautions": list(skill.cautions or [])[:3],
            "output_contract": list(skill.output_contract or [])[:3],
            "tags": list(skill.tags or [])[:4],
            "support_summary": self._support_summary_for_llm(skill, support_by_id=support_by_id),
            "version": str(skill.version or "").strip(),
            "status": skill.status.value,
        }

    def _resolved_skill(self, raw: Any, *, fallback: SkillSpec) -> SkillSpec:
        item = maybe_json_dict(raw)
        if not item:
            return fallback
        prompt = _prompt_prefix_from_body(str(item.get("prompt") or item.get("skill_body") or "").strip()) or _prompt_prefix_from_body(
            fallback.skill_body
        )
        intervention_moves = compact_text_list(coerce_str_list(item.get("intervention_moves")), limit=12) or list(
            fallback.intervention_moves or []
        )
        workflow_steps = compact_text_list(coerce_str_list(item.get("workflow_steps")), limit=12) or list(fallback.workflow_steps or [])
        constraints = compact_text_list(coerce_str_list(item.get("constraints")), limit=12) or list(fallback.constraints or [])
        cautions = compact_text_list(coerce_str_list(item.get("cautions")), limit=12) or list(fallback.cautions or [])
        applicable_signals = compact_text_list(coerce_str_list(item.get("applicable_signals")), limit=12) or list(
            fallback.applicable_signals or []
        )
        contraindications = compact_text_list(coerce_str_list(item.get("contraindications")), limit=12) or list(
            fallback.contraindications or []
        )
        output_contract = compact_text_list(coerce_str_list(item.get("output_contract")), limit=12) or list(
            fallback.output_contract or []
        )
        examples = _coerce_examples(item.get("examples")) or list(fallback.examples or [])
        if not prompt or (not workflow_steps and not intervention_moves and not constraints and not cautions):
            return fallback
        objective = str(fallback.objective or fallback.description).strip()
        structured_prompt = _build_structured_prompt(
            prompt=prompt,
            objective=objective,
            applicable_signals=applicable_signals,
            contraindications=contraindications,
            intervention_moves=intervention_moves,
            workflow_steps=workflow_steps,
            constraints=constraints,
            cautions=cautions,
            output_contract=output_contract,
            examples=examples,
        )
        return SkillSpec(
            skill_id=fallback.skill_id,
            name=str(fallback.name or "").strip(),
            description=str(item.get("description") or fallback.description).strip(),
            skill_body=structured_prompt,
            asset_type=str(fallback.asset_type or "").strip(),
            granularity=str(fallback.granularity or "").strip(),
            asset_node_id=str(fallback.asset_node_id or "").strip(),
            asset_path=str(fallback.asset_path or "").strip(),
            asset_level=int(fallback.asset_level or 0),
            visible_role=str(fallback.visible_role or "").strip(),
            objective=objective,
            domain=str(fallback.domain or "").strip(),
            task_family=str(fallback.task_family or "").strip(),
            method_family=str(fallback.method_family or "").strip(),
            stage=str(fallback.stage or "").strip(),
            applicable_signals=applicable_signals,
            contraindications=contraindications,
            intervention_moves=intervention_moves,
            triggers=list(fallback.triggers or []),
            workflow_steps=workflow_steps,
            constraints=constraints,
            cautions=cautions,
            output_contract=output_contract,
            examples=examples,
            tags=compact_text_list(coerce_str_list(item.get("tags")), limit=6) or list(fallback.tags or []),
            support_ids=list(fallback.support_ids or []),
            metadata={
                **dict(fallback.metadata or {}),
                "files": maybe_json_dict(item.get("files")) or maybe_json_dict((fallback.metadata or {}).get("files")),
                "resources": maybe_json_dict(item.get("resources")) or maybe_json_dict((fallback.metadata or {}).get("resources")),
                "llm_reason": str(item.get("reason") or "").strip(),
            },
            version=fallback.version,
            status=fallback.status,
        )

    def classify_change(
        self,
        skill: SkillSpec,
        *,
        peer_skills: Sequence[SkillSpec],
        existing_skills: Sequence[SkillSpec],
        support_by_id: Dict[str, SupportRecord],
    ) -> ChangeDecision:
        """Uses an LLM to classify how one candidate should affect registry state."""

        ranked_peers = sorted(
            [
                (index, peer, _peer_relevance_score(skill, peer))
                for index, peer in enumerate(list(peer_skills or []))
                if peer.skill_id != skill.skill_id
            ],
            key=lambda item: (-item[2], item[0]),
        )
        payload = {
            "candidate_skill": _compact_skill_for_change_decision(
                skill,
                support_by_id,
                include_evidence=True,
            ),
            "peer_candidates": [
                _compact_skill_for_change_decision(peer, support_by_id, include_evidence=False)
                for _, peer, _ in ranked_peers[:3]
            ],
            "existing_skills": [
                _compact_skill_for_change_decision(existing, support_by_id, include_evidence=False)
                for existing in list(existing_skills or [])
            ][:12],
        }
        payload_chars = len(json.dumps(payload, ensure_ascii=False))
        if payload["existing_skills"]:
            change_llm = self.full_change_llm
            allowed_actions = {"create", "strengthen", "revise", "merge", "split", "unchanged", "discard"}
            branch = "full"
            system = (
                "You are AutoSkill's Document Skill Version Manager.\n"
                "Task: decide how one candidate document skill should update the registry.\n"
                "Output ONLY strict JSON parseable by json.loads.\n"
                "Actions:\n"
                "- create: a new distinct capability\n"
                "- strengthen: same capability, mostly stronger evidence or minor additive guidance\n"
                "- revise: same capability, materially updated instructions or constraints\n"
                "- merge: candidate should merge into one or more existing skills and may deprecate overlapping older skills\n"
                "- split: candidate is one child workflow split out from an older broader parent skill\n"
                "- unchanged: candidate does not materially change the existing skill\n"
                "- discard: do not persist candidate\n"
                "Rules:\n"
                "- Decide from semantic capability identity, not lexical similarity.\n"
                "- Do not merge, strengthen, revise, or mark unchanged across different asset_type, granularity, or asset_node_id.\n"
                "- Treat macro_protocol, session_skill, micro_skill, safety_rule, and knowledge_reference as different asset layers unless there is an explicit split relationship.\n"
                "- Use peer_candidates to detect split cases where multiple narrower candidates replace one broad existing skill.\n"
                "- Use support conflict evidence to avoid preserving outdated or unsafe guidance.\n"
                "- If action is strengthen/revise/unchanged/split, target_skill_ids should contain exactly one existing skill id.\n"
                "- If action is merge, target_skill_ids may contain one or more existing skill ids.\n"
                "- Provide resolved_skill only to refine executable content.\n"
                "- Do not change name, objective, asset_type, granularity, asset_node_id, asset_path, asset_level, visible_role, domain, task_family, method_family, stage, triggers, or support_ids inside resolved_skill.\n"
                "Return schema:\n"
                "{\n"
                '  "action": "create"|"strengthen"|"revise"|"merge"|"split"|"unchanged"|"discard",\n'
                '  "target_skill_ids": ["..."],\n'
                '  "reason": "short reason",\n'
                '  "resolved_skill": {optional canonical skill payload}\n'
                "}\n"
            )
            repair_system = (
                "You are a JSON output fixer for document skill version decisions.\n"
                "Given DATA and DRAFT, output ONLY strict JSON with fields action, target_skill_ids, reason, resolved_skill.\n"
            )
        else:
            change_llm = self.hits0_change_llm
            allowed_actions = {"create", "discard"}
            branch = "hits0"
            system = (
                "You are AutoSkill's Document Skill Version Manager.\n"
                "Task: judge whether one candidate document skill should be kept as a new skill or discarded.\n"
                "Output ONLY strict JSON parseable by json.loads.\n"
                "Actions:\n"
                "- create: keep this candidate as a new distinct capability\n"
                "- discard: do not persist this candidate\n"
                "Rules:\n"
                "- There are no retrieved existing_skills in this branch, so target_skill_ids must be empty.\n"
                "- Use peer_candidates only to detect same-batch redundancy or obvious overlap that makes the candidate unnecessary.\n"
                "- Use support conflict evidence to avoid preserving outdated or unsafe guidance.\n"
                "- Provide resolved_skill only to refine executable content.\n"
                "- Do not change name, objective, asset_type, granularity, asset_node_id, asset_path, asset_level, visible_role, domain, task_family, method_family, stage, triggers, or support_ids inside resolved_skill.\n"
                "Return schema:\n"
                "{\n"
                '  "action": "create"|"discard",\n'
                '  "target_skill_ids": [],\n'
                '  "reason": "short reason",\n'
                '  "resolved_skill": {optional canonical skill payload}\n'
                "}\n"
            )
            repair_system = (
                "You are a JSON output fixer for document skill keep-or-discard decisions.\n"
                "Given DATA and DRAFT, output ONLY strict JSON with fields action, target_skill_ids, reason, resolved_skill.\n"
                'The action must be either "create" or "discard", and target_skill_ids must be an empty list.\n'
            )
        repaired_payload = (
            f"DATA:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "DRAFT:\n__DRAFT__"
        )
        emit_stage_log(
            self.logger,
            (
                f"[register_versions] classify_change skill={skill.skill_id} "
                f"branch={branch} "
                f"hits={len(payload['existing_skills'])} "
                f"peer_count={len(payload['peer_candidates'])} "
                f"payload_chars={payload_chars} "
                f"timeout_s={getattr(change_llm, 'timeout_s', '')} "
                f"max_tokens={getattr(change_llm, 'max_tokens', '')}"
            ),
        )
        parsed = llm_complete_json_with_retries(
            llm=change_llm,
            system=system,
            payload=payload,
            repair_system=repair_system,
            repair_payload=repaired_payload,
        )
        obj = maybe_json_dict(parsed)
        action = str(obj.get("action") or "").strip().lower()
        if action not in allowed_actions:
            action = "create"
        matched = compact_text_list(coerce_str_list(obj.get("target_skill_ids")), limit=8) if payload["existing_skills"] else []
        resolved = self._resolved_skill(obj.get("resolved_skill"), fallback=skill)
        reason = str(obj.get("reason") or "").strip() or action
        existing_by_id = {existing.skill_id: existing for existing in list(existing_skills or [])}
        matched_existing = [existing_by_id[skill_id] for skill_id in matched if skill_id in existing_by_id]
        if action in {"strengthen", "revise", "merge", "unchanged"} and not matched_existing and payload["existing_skills"]:
            legal_retrieved = [
                existing
                for existing in list(existing_skills or [])
                if _same_asset_layer(skill, existing) and _same_asset_node(skill, existing)
            ]
            if legal_retrieved:
                matched = [legal_retrieved[0].skill_id]
                matched_existing = [legal_retrieved[0]]
                emit_stage_log(
                    self.logger,
                    f"[register_versions] local_retarget skill={skill.skill_id} action={action} target={matched[0]} reason=missing_target",
                )
        if action in {"strengthen", "revise", "merge", "unchanged"} and matched_existing:
            legal_retrieved = [
                existing
                for existing in list(existing_skills or [])
                if _same_asset_layer(skill, existing) and _same_asset_node(skill, existing)
            ]
            legal_matched = [existing for existing in matched_existing if existing.skill_id in {item.skill_id for item in legal_retrieved}]
            if action == "merge":
                if legal_matched:
                    matched = [existing.skill_id for existing in legal_matched]
                elif legal_retrieved:
                    matched = [legal_retrieved[0].skill_id]
                    emit_stage_log(
                        self.logger,
                        f"[register_versions] local_retarget skill={skill.skill_id} action=merge target={matched[0]}",
                    )
                elif any(not _same_asset_layer(skill, existing) for existing in matched_existing):
                    action = "create"
                    matched = []
                    reason = "create (cross-layer merge blocked)"
                elif any(not _same_asset_node(skill, existing) for existing in matched_existing):
                    action = "create"
                    matched = []
                    reason = "create (cross-node merge blocked)"
                else:
                    action = "create"
                    matched = []
            else:
                if legal_matched:
                    matched = [legal_matched[0].skill_id]
                elif legal_retrieved:
                    matched = [legal_retrieved[0].skill_id]
                    emit_stage_log(
                        self.logger,
                        f"[register_versions] local_retarget skill={skill.skill_id} action={action} target={matched[0]}",
                    )
                elif any(not _same_asset_layer(skill, existing) for existing in matched_existing):
                    action = "create"
                    matched = []
                    reason = "create (cross-layer merge blocked)"
                elif any(not _same_asset_node(skill, existing) for existing in matched_existing):
                    action = "create"
                    matched = []
                    reason = "create (cross-node merge blocked)"
                else:
                    action = "create"
                    matched = []
        if action == "split" and matched_existing:
            parent = matched_existing[0]
            if _granularity_rank(resolved.granularity) <= _granularity_rank(parent.granularity):
                action = "create"
                matched = []
                reason = "create (split requires narrower child)"
        return ChangeDecision(
            action=action,
            skill=resolved,
            matched_skill_ids=matched,
            reason=reason,
            split_parent_id=(matched[0] if action == "split" and matched else ""),
            hits=len(payload["existing_skills"]),
            branch=branch,
        )

    def _taxonomy_for_skill(self, skill: SkillSpec) -> Any:
        """Loads the configured taxonomy used by one persisted skill."""

        md = dict(skill.metadata or {})
        requested_path = str(md.get("skill_taxonomy_path") or md.get("skill_taxonomy") or "").strip()
        requested_domain = str(md.get("domain_type") or skill.domain or "").strip()
        try:
            return load_skill_taxonomy(domain_type=requested_domain, taxonomy_path=requested_path)
        except Exception:
            return load_skill_taxonomy()

    def classify_parent_link(
        self,
        child: SkillSpec,
        *,
        parent_hits: Sequence[Any],
        allowed_parent_nodes: Sequence[str],
    ) -> Dict[str, Any]:
        """Chooses one parent candidate for a skill using constrained LLM + safe fallback."""

        hits = [item for item in list(parent_hits or []) if getattr(item, "skill", None) is not None]
        if not hits:
            return {"decision": "defer", "parent_skill_id": "", "confidence": 0.0, "reason": "no parent candidates"}

        payload = {
            "child_skill": {
                "skill_id": child.skill_id,
                "name": child.name,
                "asset_type": child.asset_type,
                "asset_node_id": child.asset_node_id,
                "asset_level": child.asset_level,
                "objective": child.objective,
                "applicable_signals": list(child.applicable_signals or [])[:3],
                "contraindications": list(child.contraindications or [])[:3],
                "workflow_steps": list(child.workflow_steps or []),
                "constraints": list(child.constraints or []),
                "triggers": list(child.triggers or []),
                "output_contract": list(child.output_contract or [])[:3],
            },
            "allowed_parent_nodes": list(allowed_parent_nodes or []),
            "parent_candidates": [
                {
                    "skill_id": hit.skill.skill_id,
                    "name": hit.skill.name,
                    "asset_node_id": hit.skill.asset_node_id,
                    "asset_level": hit.skill.asset_level,
                    "objective": hit.skill.objective,
                    "applicable_signals": list(hit.skill.applicable_signals or [])[:3],
                    "workflow_steps": list(hit.skill.workflow_steps or [])[:6],
                    "output_contract": list(hit.skill.output_contract or [])[:3],
                    "score": float(getattr(hit, "score", 0.0) or 0.0),
                }
                for hit in hits[:5]
            ],
        }
        system = (
            "You are AutoSkill4Doc's hierarchy linker.\n"
            "Task: attach one child skill to the best broader parent candidate.\n"
            "Rules:\n"
            "- Choose ONLY one parent_skill_id from parent_candidates when a clear broader parent exists.\n"
            "- Parent must be a broader reusable skill that should call or contain the child skill.\n"
            "- allowed_parent_nodes is a hard constraint; never attach outside that set.\n"
            "- Prefer a parent whose workflow has a natural handoff point for the child and whose output or stage makes the child callable as a sub-skill.\n"
            "- Do not attach merely because domain, family, or wording is similar.\n"
            "- Prefer defer when multiple parents are similarly plausible or when the best score is still weak.\n"
            "- If no parent is clearly suitable, return decision=defer.\n"
            "- Do not invent ids.\n"
            "Return ONLY strict JSON:\n"
            "{\n"
            '  "decision": "attach"|"defer",\n'
            '  "parent_skill_id": "candidate-id-or-empty",\n'
            '  "confidence": 0.0,\n'
            '  "reason": "short reason"\n'
            "}\n"
        )
        repair_system = (
            "You are a JSON fixer for AutoSkill4Doc hierarchy linking.\n"
            "Return ONLY strict JSON with decision, parent_skill_id, confidence, reason.\n"
        )
        repaired_payload = f"DATA:\n{json.dumps(payload, ensure_ascii=False)}\n\nDRAFT:\n__DRAFT__"
        try:
            parsed = llm_complete_json_with_retries(
                llm=self.hierarchy_link_llm or self.llm,
                system=system,
                payload=payload,
                repair_system=repair_system,
                repair_payload=repaired_payload,
            )
            obj = maybe_json_dict(parsed)
            decision = str(obj.get("decision") or "").strip().lower()
            parent_skill_id = str(obj.get("parent_skill_id") or "").strip()
            confidence = clip_confidence(obj.get("confidence"), default=0.0)
            reason = str(obj.get("reason") or "").strip()
            valid_ids = {str(hit.skill.skill_id or "").strip() for hit in hits}
            if decision == "attach" and parent_skill_id in valid_ids:
                return {
                    "decision": "attach",
                    "parent_skill_id": parent_skill_id,
                    "confidence": confidence,
                    "reason": reason or "llm hierarchy attachment",
                }
        except Exception as exc:
            fallback = self._classify_parent_link_fallback(child=child, hits=hits, base_reason="")
            fallback["hierarchy_error"] = {
                "stage": "hierarchy_parent_link",
                "skill_id": str(child.skill_id or "").strip(),
                "candidate_count": len(hits),
                "allowed_parent_nodes": list(allowed_parent_nodes or []),
                "error": str(exc),
                "retry_attempts": int(getattr(exc, "autoskill_retry_attempts", 0) or 0),
                "fallback_decision": str(fallback.get("decision") or "").strip(),
            }
            return fallback

        return self._classify_parent_link_fallback(child=child, hits=hits, base_reason=reason)

    def _classify_parent_link_fallback(
        self,
        *,
        child: SkillSpec,
        hits: Sequence[Any],
        base_reason: str,
    ) -> Dict[str, Any]:
        """Applies the safe local parent-link fallback used after LLM failure or ambiguity."""

        if len(hits) == 1 and _plausible_parent_candidate(child, hits[0].skill, score=float(hits[0].score or 0.0)):
            return {
                "decision": "attach",
                "parent_skill_id": str(hits[0].skill.skill_id or "").strip(),
                "confidence": 0.6,
                "reason": base_reason or "single eligible parent candidate",
            }
        if (
            len(hits) >= 2
            and float(hits[0].score or 0.0) >= float(hits[1].score or 0.0) + 0.15
            and _plausible_parent_candidate(child, hits[0].skill, score=float(hits[0].score or 0.0))
        ):
            return {
                "decision": "attach",
                "parent_skill_id": str(hits[0].skill.skill_id or "").strip(),
                "confidence": 0.55,
                "reason": base_reason or "top parent candidate clearly outranks remaining hits",
            }
        return {"decision": "defer", "parent_skill_id": "", "confidence": 0.0, "reason": base_reason or "no confident parent"}

    def link_hierarchy(
        self,
        *,
        skills: Sequence[SkillSpec],
        existing_skills: Sequence[SkillSpec],
        error_sink: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[SkillSpec], List[SkillSpec]]:
        """Assigns parent-child links and returns current skills plus touched existing parents."""

        current = [skill for skill in list(skills or []) if isinstance(skill, SkillSpec)]
        if not current:
            return [], []

        corpus_by_id: Dict[str, SkillSpec] = {}
        for skill in list(existing_skills or []):
            if skill.status in {VersionState.DEPRECATED, VersionState.RETIRED}:
                continue
            corpus_by_id[skill.skill_id] = skill
        for skill in current:
            if skill.status in {VersionState.DEPRECATED, VersionState.RETIRED}:
                continue
            corpus_by_id[skill.skill_id] = skill

        hierarchy_retriever = self.retriever or build_document_skill_retriever()
        hierarchy_retriever.refresh(list(corpus_by_id.values()))

        updated: Dict[str, SkillSpec] = {}
        touched_existing: Dict[str, SkillSpec] = {}
        hierarchy_errors: List[Dict[str, Any]] = []
        for skill in current:
            if skill.status in {VersionState.DEPRECATED, VersionState.RETIRED}:
                updated[skill.skill_id] = skill
                continue
            taxonomy = self._taxonomy_for_skill(skill)
            asset_level = max(0, int(skill.asset_level or 0))
            visible_role = str(skill.visible_role or "").strip()
            if asset_level <= 1:
                updated[skill.skill_id] = _copy_skill_hierarchy(
                    skill,
                    parent_skill_id="",
                    parent_candidate_ids=[],
                    hierarchy_confidence=1.0 if asset_level == 1 else 0.0,
                    hierarchy_status="root",
                    visible_role=visible_role or "parent",
                )
                continue

            node = taxonomy.get_asset_node(skill.asset_node_id)
            allowed_parent_nodes = [str(node.parent or "").strip()] if node is not None and str(node.parent or "").strip() else []
            hits = hierarchy_retriever.search_parents(
                skill,
                allowed_parent_nodes=allowed_parent_nodes,
                limit=min(5, self.retrieval_limit),
                exclude_ids={skill.skill_id},
            )
            linked = self.classify_parent_link(
                skill,
                parent_hits=hits,
                allowed_parent_nodes=allowed_parent_nodes,
            )
            hierarchy_error = linked.pop("hierarchy_error", None) if isinstance(linked, dict) else None
            if isinstance(hierarchy_error, dict):
                hierarchy_errors.append(dict(hierarchy_error))
                if error_sink is not None:
                    error_sink.append(hierarchy_error)
            parent_skill_id = str(linked.get("parent_skill_id") or "").strip()
            confidence = clip_confidence(linked.get("confidence"), default=0.0)
            status = "linked" if parent_skill_id else "unresolved"
            if parent_skill_id:
                parent_skill = corpus_by_id.get(parent_skill_id)
                parent_level = max(1, int(getattr(parent_skill, "asset_level", 0) or 0)) if parent_skill is not None else asset_level - 1
                if parent_level != max(1, asset_level - 1):
                    parent_skill_id = ""
                    status = "unresolved"
                    confidence = 0.0
            updated[skill.skill_id] = _copy_skill_hierarchy(
                skill,
                parent_skill_id=parent_skill_id,
                parent_candidate_ids=[str(hit.skill.skill_id or "").strip() for hit in hits],
                hierarchy_confidence=confidence,
                hierarchy_status=status,
                visible_role=visible_role or ("leaf" if asset_level >= 3 else "parent"),
            )

        children_by_parent: Dict[str, List[str]] = {}
        for skill in updated.values():
            parent_skill_id = str(skill.parent_skill_id or "").strip()
            if not parent_skill_id:
                continue
            children_by_parent.setdefault(parent_skill_id, []).append(skill.skill_id)
        for parent_skill_id, child_ids in children_by_parent.items():
            parent = updated.get(parent_skill_id) or corpus_by_id.get(parent_skill_id)
            if parent is None:
                continue
            merged_child_ids = sorted(set(list(parent.child_skill_ids or []) + list(child_ids or [])))
            linked_parent = _copy_skill_hierarchy(
                parent,
                child_skill_ids=merged_child_ids,
                hierarchy_status="parent",
                visible_role=str(parent.visible_role or "").strip() or "parent",
            )
            if parent_skill_id in updated:
                updated[parent_skill_id] = linked_parent
            else:
                touched_existing[parent_skill_id] = linked_parent

        if hierarchy_errors:
            fallback_counts: Dict[str, int] = {}
            total_retry_attempts = 0
            for item in hierarchy_errors:
                decision = str(item.get("fallback_decision") or "defer").strip() or "defer"
                fallback_counts[decision] = int(fallback_counts.get(decision) or 0) + 1
                total_retry_attempts += int(item.get("retry_attempts", 0) or 0)
            fallback_summary = " ".join(
                f"{key}={value}"
                for key, value in sorted(fallback_counts.items())
                if int(value or 0) > 0
            )
            emit_stage_log(
                self.logger,
                (
                    f"[register_versions] hierarchy_errors count={len(hierarchy_errors)} "
                    f"retry_attempts={total_retry_attempts}"
                    + (f" {fallback_summary}" if fallback_summary else "")
                ),
            )

        return [updated.get(skill.skill_id, skill) for skill in current], list(touched_existing.values())

    def create_new_version(self, *, current_version: str, action: str) -> str:
        """Creates the next version string for one lifecycle action."""

        action_s = str(action or "").strip().lower()
        if action_s in {"", "create"}:
            return str(current_version or "").strip() or "0.1.0"
        if action_s == "unchanged":
            return str(current_version or "").strip() or "0.1.0"
        return _bump_patch(str(current_version or "").strip() or "0.1.0")

    def update_lifecycle(
        self,
        *,
        skill_id: str,
        current_state: Optional[VersionState],
        action: str,
        target_state: VersionState,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SkillLifecycle:
        """Creates one lifecycle transition consistent with the requested action."""

        action_s = str(action or "").strip().lower()
        if action_s == "deprecate":
            next_state = (
                target_state
                if target_state in {VersionState.WATCHLIST, VersionState.DEPRECATED, VersionState.RETIRED}
                else VersionState.DEPRECATED
            )
        else:
            next_state = target_state
        from_state = current_state if current_state is not None and current_state != next_state else None
        return SkillLifecycle(
            lifecycle_id=str(uuid.uuid4()),
            skill_id=str(skill_id or "").strip(),
            from_state=from_state,
            to_state=next_state,
            reason=action_s or "update",
            metadata=dict(metadata or {}),
        )

    def mark_deprecated(
        self,
        *,
        skill: SkillSpec,
        reason: str,
        state: VersionState = VersionState.DEPRECATED,
        related_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Marks one skill as deprecated/watchlist/retired."""

        related = list(related_ids or [])
        next_version = self.create_new_version(current_version=skill.version, action="deprecate")
        updated_skill = _copy_skill(
            skill,
            version=next_version,
            status=state,
            metadata_update={
                "change_action": "deprecate",
                "deprecation_reason": str(reason or "").strip(),
                "related_skill_ids": related,
            },
        )
        provenance = {
            "entity_type": "skill",
            "entity_id": updated_skill.skill_id,
            "doc_ids": [],
            "support_added": [],
            "support_conflicts": [],
            "related_entity_ids": related,
        }
        lifecycle = self.update_lifecycle(
            skill_id=updated_skill.skill_id,
            current_state=skill.status,
            action="deprecate",
            target_state=state,
            metadata={"reason": str(reason or "").strip(), "related_entity_ids": related},
        )
        change_log = self._change_payload(
            entity_type="skill",
            entity_id=updated_skill.skill_id,
            action="deprecate",
            from_version=skill.version,
            to_version=updated_skill.version,
            from_state=skill.status.value,
            to_state=updated_skill.status.value,
            summary=str(reason or "").strip(),
            provenance=provenance,
            related_entity_ids=related,
        )
        history = self._history_payload(
            entity_type="skill",
            entity_id=updated_skill.skill_id,
            version=updated_skill.version,
            action="deprecate",
            status=updated_skill.status,
            related_entity_ids=related,
        )
        return {
            "skill": updated_skill,
            "lifecycle": lifecycle,
            "change_log": change_log,
            "version_history": history,
            "provenance_links": provenance,
        }

    def merge_skills(
        self,
        *,
        decision: ChangeDecision,
        skill: SkillSpec,
        existing_skills_by_id: Dict[str, SkillSpec],
        target_state: VersionState,
    ) -> Dict[str, Any]:
        """Merges multiple existing skills into one updated primary skill."""

        matched_ids = [skill_id for skill_id in decision.matched_skill_ids if skill_id in existing_skills_by_id]
        if not matched_ids:
            raise ValueError("merge requires at least one existing matched skill")
        primary_existing = existing_skills_by_id[matched_ids[0]]
        secondary_existing = [existing_skills_by_id[skill_id] for skill_id in matched_ids[1:]]
        next_version = self.create_new_version(current_version=primary_existing.version, action="merge")
        merged_skill = _skill_with_frozen_identity(
            base=primary_existing,
            content=skill,
            version=next_version,
            status=target_state,
            support_ids=list(primary_existing.support_ids or []) + list(skill.support_ids or []),
            metadata_update={
                "change_action": "merge",
                "merged_from_skill_ids": [existing.skill_id for existing in secondary_existing],
                "llm_reason": decision.reason,
            },
        )
        deprecated_secondary = [
            self.mark_deprecated(
                skill=secondary,
                reason="merged_into_other_skill",
                state=VersionState.DEPRECATED,
                related_ids=[primary_existing.skill_id],
            )
            for secondary in secondary_existing
        ]
        return {
            "primary_skill": merged_skill,
            "secondary": deprecated_secondary,
        }

    def split_skill(
        self,
        *,
        parent_skill: SkillSpec,
        child_skills: Sequence[SkillSpec],
        target_state: VersionState,
    ) -> Dict[str, Any]:
        """Splits one existing skill into multiple more focused skills."""

        updated_children: List[SkillSpec] = []
        lifecycles: List[SkillLifecycle] = []
        change_logs: List[Dict[str, Any]] = []
        version_history: List[Dict[str, Any]] = []
        provenance_links: List[Dict[str, Any]] = []

        for child in list(child_skills or []):
            updated_child = _copy_skill(
                child,
                version="0.1.0",
                status=target_state,
                metadata_update={
                    "change_action": "split",
                    "split_from_skill_id": parent_skill.skill_id,
                },
            )
            updated_children.append(updated_child)
            lifecycles.append(
                self.update_lifecycle(
                    skill_id=updated_child.skill_id,
                    current_state=None,
                    action="split",
                    target_state=target_state,
                    metadata={"split_from_skill_id": parent_skill.skill_id},
                )
            )
            provenance = {
                "entity_type": "skill",
                "entity_id": updated_child.skill_id,
                "doc_ids": [],
                "support_added": list(updated_child.support_ids or []),
                "support_conflicts": [],
                "related_entity_ids": [parent_skill.skill_id],
            }
            provenance_links.append(provenance)
            version_history.append(
                self._history_payload(
                    entity_type="skill",
                    entity_id=updated_child.skill_id,
                    version=updated_child.version,
                    action="split",
                    status=updated_child.status,
                    related_entity_ids=[parent_skill.skill_id],
                )
            )
            change_logs.append(
                self._change_payload(
                    entity_type="skill",
                    entity_id=updated_child.skill_id,
                    action="split",
                    from_version="",
                    to_version=updated_child.version,
                    from_state="",
                    to_state=updated_child.status.value,
                    summary="split_from_existing_skill",
                    provenance=provenance,
                    related_entity_ids=[parent_skill.skill_id],
                )
            )

        deprecated_parent = self.mark_deprecated(
            skill=parent_skill,
            reason="split_into_more_specific_skills",
            state=VersionState.DEPRECATED,
            related_ids=[child.skill_id for child in updated_children],
        )
        return {
            "children": updated_children,
            "deprecated_parent": deprecated_parent,
            "lifecycles": lifecycles,
            "change_logs": change_logs,
            "version_history": version_history,
            "provenance_links": provenance_links,
        }

    def _change_payload(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        from_version: str,
        to_version: str,
        from_state: str,
        to_state: str,
        summary: str,
        provenance: Dict[str, Any],
        related_entity_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Builds one normalized change log payload."""

        return {
            "change_id": str(uuid.uuid4()),
            "entity_type": str(entity_type or "").strip(),
            "entity_id": str(entity_id or "").strip(),
            "action": str(action or "").strip(),
            "changed_at": now_iso(),
            "from_version": str(from_version or "").strip(),
            "to_version": str(to_version or "").strip(),
            "from_state": str(from_state or "").strip(),
            "to_state": str(to_state or "").strip(),
            "summary": str(summary or "").strip(),
            "related_entity_ids": list(related_entity_ids or []),
            "provenance": dict(provenance or {}),
        }

    def _history_payload(
        self,
        *,
        entity_type: str,
        entity_id: str,
        version: str,
        action: str,
        status: VersionState,
        related_entity_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Builds one normalized version history entry."""

        return {
            "entity_type": str(entity_type or "").strip(),
            "entity_id": str(entity_id or "").strip(),
            "version": str(version or "").strip(),
            "action": str(action or "").strip(),
            "changed_at": now_iso(),
            "status": status.value,
            "related_entity_ids": list(related_entity_ids or []),
        }

    def _merge_duplicate_group_skill(
        self,
        *,
        primary: SkillSpec,
        secondary_skills: Sequence[SkillSpec],
        support_by_id: Dict[str, SupportRecord],
    ) -> SkillSpec:
        """Builds one consolidated canonical skill without changing identity surface."""

        secondary_list = [skill for skill in list(secondary_skills or []) if isinstance(skill, SkillSpec)]
        merged_support_ids = _merge_text_lists(
            list(primary.support_ids or []),
            *[list(skill.support_ids or []) for skill in secondary_list],
        )
        merged_examples = _merge_examples(
            list(primary.examples or []),
            *[list(skill.examples or []) for skill in secondary_list],
        )
        prompt = _prompt_prefix_from_body(primary.skill_body)
        if not prompt:
            for skill in secondary_list:
                prompt = _prompt_prefix_from_body(skill.skill_body)
                if prompt:
                    break
        merged_payload = primary.to_dict()
        merged_payload["support_ids"] = merged_support_ids
        merged_payload["applicable_signals"] = _merge_text_lists(
            list(primary.applicable_signals or []),
            *[list(skill.applicable_signals or []) for skill in secondary_list],
        )
        merged_payload["contraindications"] = _merge_text_lists(
            list(primary.contraindications or []),
            *[list(skill.contraindications or []) for skill in secondary_list],
        )
        merged_payload["intervention_moves"] = _merge_text_lists(
            list(primary.intervention_moves or []),
            *[list(skill.intervention_moves or []) for skill in secondary_list],
        )
        merged_payload["triggers"] = _merge_text_lists(
            list(primary.triggers or []),
            *[list(skill.triggers or []) for skill in secondary_list],
        )
        merged_payload["workflow_steps"] = _merge_text_lists(
            list(primary.workflow_steps or []),
            *[list(skill.workflow_steps or []) for skill in secondary_list],
        )
        merged_payload["constraints"] = _merge_text_lists(
            list(primary.constraints or []),
            *[list(skill.constraints or []) for skill in secondary_list],
        )
        merged_payload["cautions"] = _merge_text_lists(
            list(primary.cautions or []),
            *[list(skill.cautions or []) for skill in secondary_list],
        )
        merged_payload["output_contract"] = _merge_text_lists(
            list(primary.output_contract or []),
            *[list(skill.output_contract or []) for skill in secondary_list],
        )
        merged_payload["tags"] = _merge_text_lists(
            list(primary.tags or []),
            *[list(skill.tags or []) for skill in secondary_list],
        )
        merged_payload["child_skill_ids"] = _merge_text_lists(
            list(primary.child_skill_ids or []),
            *[list(skill.child_skill_ids or []) for skill in secondary_list],
        )
        merged_payload["examples"] = [
            {
                "input": str(example.input or ""),
                "output": str(example.output or ""),
                "notes": str(example.notes or ""),
            }
            for example in merged_examples
        ]
        merged_payload["skill_body"] = _build_structured_prompt(
            prompt=prompt,
            objective=str(primary.objective or primary.description).strip(),
            applicable_signals=list(merged_payload.get("applicable_signals") or []),
            contraindications=list(merged_payload.get("contraindications") or []),
            intervention_moves=list(merged_payload.get("intervention_moves") or []),
            workflow_steps=list(merged_payload.get("workflow_steps") or []),
            constraints=list(merged_payload.get("constraints") or []),
            cautions=list(merged_payload.get("cautions") or []),
            output_contract=list(merged_payload.get("output_contract") or []),
            examples=merged_examples,
        )
        merged_metadata = dict(merged_payload.get("metadata") or {})
        merged_metadata["merged_from_skill_ids"] = _merge_text_lists(
            list(merged_metadata.get("merged_from_skill_ids") or []),
            [skill.skill_id for skill in secondary_list],
        )
        merged_metadata["duplicate_consolidation_ids"] = [skill.skill_id for skill in secondary_list]
        merged_metadata["support_summary"] = _support_summary_for_skill(
            SkillSpec.from_dict({**merged_payload, "metadata": merged_metadata}),
            support_by_id=support_by_id,
        )
        merged_source_drafts = _merge_text_lists(
            list(merged_metadata.get("source_draft_ids") or []),
            *[list((skill.metadata or {}).get("source_draft_ids") or []) for skill in secondary_list],
        )
        if merged_source_drafts:
            merged_metadata["source_draft_ids"] = merged_source_drafts
        merged_payload["metadata"] = merged_metadata
        return SkillSpec.from_dict(merged_payload)

    def consolidate_duplicate_skills(
        self,
        *,
        result: VersionRegistrationResult,
        existing_skills: Sequence[SkillSpec],
        existing_supports: Sequence[SupportRecord],
        target_state: VersionState,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VersionRegistrationResult:
        """Collapses same-level visible duplicates into one canonical skill before persistence."""

        touched_scopes = {
            _family_scope_key(skill, metadata=metadata)
            for skill in list(result.skill_specs or []) + list(result.hierarchy_updates or [])
            if isinstance(skill, SkillSpec)
        }
        if not touched_scopes:
            return result

        preexisting_by_id = {skill.skill_id: skill for skill in list(existing_skills or []) if isinstance(skill, SkillSpec)}
        support_by_id = {support.support_id: support for support in list(existing_supports or []) if isinstance(support, SupportRecord)}
        for support in list(result.support_records or []):
            support_by_id[support.support_id] = support

        effective_by_id: Dict[str, SkillSpec] = {}
        for skill in list(existing_skills or []):
            if (
                isinstance(skill, SkillSpec)
                and _family_scope_key(skill, metadata=metadata) in touched_scopes
            ):
                effective_by_id[skill.skill_id] = skill
        for skill in list(result.skill_specs or []) + list(result.hierarchy_updates or []):
            if (
                isinstance(skill, SkillSpec)
                and _family_scope_key(skill, metadata=metadata) in touched_scopes
            ):
                effective_by_id[skill.skill_id] = skill

        groups: Dict[Tuple[str, str, str, str, str, int, str], List[SkillSpec]] = {}
        for skill in effective_by_id.values():
            if skill.status in {VersionState.DEPRECATED, VersionState.RETIRED}:
                continue
            group_key = _duplicate_group_key(skill, metadata=metadata)
            if not group_key[-1]:
                continue
            groups.setdefault(group_key, []).append(skill)

        duplicate_groups = {key: value for key, value in groups.items() if len(value) > 1}
        if not duplicate_groups:
            return result

        current_result_ids = {
            skill.skill_id
            for skill in list(result.skill_specs or []) + list(result.hierarchy_updates or [])
            if isinstance(skill, SkillSpec)
        }
        preexisting_ids = set(preexisting_by_id.keys())
        remove_skill_ids: Set[str] = set()
        remove_event_skill_ids: Set[str] = set()
        replace_map: Dict[str, str] = {}
        added_skill_specs: List[SkillSpec] = []
        added_supports: List[SupportRecord] = []
        added_lifecycles: List[SkillLifecycle] = []
        added_change_logs: List[Dict[str, Any]] = []
        added_version_history: List[Dict[str, Any]] = []
        added_provenance_links: List[Dict[str, Any]] = []

        for _, bucket in sorted(duplicate_groups.items(), key=lambda item: item[0]):
            ordered = sorted(bucket, key=lambda skill: _duplicate_primary_sort_key(skill, preexisting_ids=preexisting_ids))
            primary = ordered[0]
            secondary_skills = ordered[1:]
            secondary_ids = [skill.skill_id for skill in secondary_skills]
            primary_in_result = primary.skill_id in current_result_ids
            preexisting_secondary = [skill for skill in secondary_skills if skill.skill_id in preexisting_by_id]

            for secondary in secondary_skills:
                replace_map[secondary.skill_id] = primary.skill_id
                if secondary.skill_id in current_result_ids:
                    remove_skill_ids.add(secondary.skill_id)
                    remove_event_skill_ids.add(secondary.skill_id)
                for support_id in list(secondary.support_ids or []):
                    support = support_by_id.get(str(support_id or "").strip())
                    if support is None:
                        continue
                    rebound = _copy_support(support, skill_id=primary.skill_id)
                    support_by_id[rebound.support_id] = rebound
                    added_supports.append(rebound)

            merged_primary = self._merge_duplicate_group_skill(
                primary=primary,
                secondary_skills=secondary_skills,
                support_by_id=support_by_id,
            )
            if primary.skill_id in current_result_ids:
                remove_skill_ids.add(primary.skill_id)
            if primary.skill_id in preexisting_by_id and not primary_in_result and preexisting_secondary:
                next_version = self.create_new_version(current_version=primary.version, action="merge")
                merged_primary = _copy_skill(
                    merged_primary,
                    version=next_version,
                    status=target_state,
                    metadata_update={
                        "change_action": "merge",
                        "llm_reason": "local duplicate consolidation",
                    },
                )
                provenance = {
                    "entity_type": "skill",
                    "entity_id": merged_primary.skill_id,
                    "doc_ids": _doc_ids_from_support_ids(merged_primary.support_ids, support_by_id),
                    "support_added": [
                        support.support_id
                        for support in added_supports
                        if str(support.skill_id or "").strip() == merged_primary.skill_id
                    ],
                    "support_conflicts": _conflicting_support_ids(merged_primary.support_ids, support_by_id),
                    "related_entity_ids": secondary_ids,
                }
                added_lifecycles.append(
                    self.update_lifecycle(
                        skill_id=merged_primary.skill_id,
                        current_state=preexisting_by_id[merged_primary.skill_id].status,
                        action="merge",
                        target_state=target_state,
                        metadata={"merged_from_skill_ids": secondary_ids, "llm_reason": "local duplicate consolidation"},
                    )
                )
                added_change_logs.append(
                    self._change_payload(
                        entity_type="skill",
                        entity_id=merged_primary.skill_id,
                        action="merge",
                        from_version=preexisting_by_id[merged_primary.skill_id].version,
                        to_version=merged_primary.version,
                        from_state=preexisting_by_id[merged_primary.skill_id].status.value,
                        to_state=merged_primary.status.value,
                        summary="local duplicate consolidation",
                        provenance=provenance,
                        related_entity_ids=secondary_ids,
                    )
                )
                added_version_history.append(
                    self._history_payload(
                        entity_type="skill",
                        entity_id=merged_primary.skill_id,
                        version=merged_primary.version,
                        action="merge",
                        status=merged_primary.status,
                        related_entity_ids=secondary_ids,
                    )
                )
                added_provenance_links.append(provenance)
            added_skill_specs.append(merged_primary)

            for secondary in preexisting_secondary:
                deprecated = self.mark_deprecated(
                    skill=_copy_skill(secondary, support_ids=[]),
                    reason="merged_into_other_skill",
                    state=VersionState.DEPRECATED,
                    related_ids=[merged_primary.skill_id],
                )
                added_skill_specs.append(deprecated["skill"])
                added_lifecycles.append(deprecated["lifecycle"])
                added_change_logs.append(deprecated["change_log"])
                added_version_history.append(deprecated["version_history"])
                added_provenance_links.append(deprecated["provenance_links"])

            emit_stage_log(
                self.logger,
                f"[register_versions] consolidate_duplicates canonical={merged_primary.skill_id} absorbed={secondary_ids}",
            )

        result.skill_specs = [
            _rewrite_skill_links(skill, replace_map=replace_map)
            for skill in list(result.skill_specs or [])
            if skill.skill_id not in remove_skill_ids
        ]
        result.hierarchy_updates = [
            _rewrite_skill_links(skill, replace_map=replace_map)
            for skill in list(result.hierarchy_updates or [])
            if skill.skill_id not in remove_skill_ids
        ]
        result.skill_specs.extend([_rewrite_skill_links(skill, replace_map=replace_map) for skill in added_skill_specs])
        result.support_records.extend(list(added_supports or []))
        result.lifecycles = [
            lifecycle
            for lifecycle in list(result.lifecycles or [])
            if str(lifecycle.skill_id or "").strip() not in remove_event_skill_ids
        ] + list(added_lifecycles or [])
        result.change_logs = [
            payload
            for payload in list(result.change_logs or [])
            if str(payload.get("entity_id") or "").strip() not in remove_event_skill_ids
        ] + list(added_change_logs or [])
        result.version_history = [
            payload
            for payload in list(result.version_history or [])
            if str(payload.get("entity_id") or "").strip() not in remove_event_skill_ids
        ] + list(added_version_history or [])
        result.provenance_links = [
            payload
            for payload in list(result.provenance_links or [])
            if str(payload.get("entity_id") or "").strip() not in remove_event_skill_ids
        ] + list(added_provenance_links or [])
        deduped_skill_specs: Dict[str, SkillSpec] = {}
        for skill in list(result.skill_specs or []):
            deduped_skill_specs[f"{skill.skill_id}:{skill.status.value}"] = skill
        result.skill_specs = list(deduped_skill_specs.values())
        deduped_hierarchy_updates: Dict[str, SkillSpec] = {}
        for skill in list(result.hierarchy_updates or []):
            deduped_hierarchy_updates[f"{skill.skill_id}:{skill.status.value}"] = skill
        result.hierarchy_updates = list(deduped_hierarchy_updates.values())
        deduped_supports: Dict[str, SupportRecord] = {}
        for support in list(result.support_records or []):
            deduped_supports[support.support_id] = support
        result.support_records = list(deduped_supports.values())
        return result

    def _conflict_review(
        self,
        *,
        existing_skill: SkillSpec,
        incoming_skills: Sequence[SkillSpec],
        support_by_id: Dict[str, SupportRecord],
    ) -> Dict[str, str]:
        """Asks the LLM whether incoming conflicting evidence should downgrade an existing skill."""

        payload = {
            "existing_skill": self._skill_for_llm(existing_skill, support_by_id=support_by_id),
            "incoming_skills": [
                self._skill_for_llm(skill, support_by_id=support_by_id)
                for skill in list(incoming_skills or [])
            ][:8],
        }
        system = (
            "You are AutoSkill's Document Conflict Judge.\n"
            "Task: decide whether new incoming document skills/support should keep, watchlist, or deprecate an existing skill.\n"
            "Output ONLY strict JSON parseable by json.loads.\n"
            "Use watchlist when conflict signals are meaningful but not strong enough for deprecation.\n"
            "Use deprecate when newer evidence materially contradicts or replaces the older skill's invocation boundary, guardrails, or output guidance.\n"
            "Prefer keep when the difference is only wording, detail level, or complementary refinement.\n"
            "Return schema: {\"action\": \"keep\"|\"watchlist\"|\"deprecate\", \"reason\": \"short reason\"}\n"
        )
        repair_system = (
            "You are a JSON output fixer for document conflict review.\n"
            "Given DATA and DRAFT, output ONLY strict JSON with fields action and reason.\n"
        )
        repaired_payload = (
            f"DATA:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "DRAFT:\n__DRAFT__"
        )
        parsed = llm_complete_json(
            llm=self.llm,
            system=system,
            payload=payload,
            repair_system=repair_system,
            repair_payload=repaired_payload,
        )
        obj = maybe_json_dict(parsed)
        action = str(obj.get("action") or "").strip().lower()
        if action not in {"keep", "watchlist", "deprecate"}:
            action = "keep"
        return {"action": action, "reason": str(obj.get("reason") or "").strip() or action}

    def reconcile(
        self,
        *,
        skills: Sequence[SkillSpec],
        support_records: Sequence[SupportRecord],
        target_state: VersionState,
        intermediate_writer: Optional["IntermediateRunWriter"] = None,
    ) -> VersionRegistrationResult:
        """Reconciles one compiled batch against registry state."""

        result = VersionRegistrationResult(support_records=[], dry_run=False)
        skills_list = list(skills or [])
        support_by_id = _support_lookup(self.registry, support_records)
        existing_skills = list(self.registry.list_skills())
        existing_skills_by_id = {skill.skill_id: skill for skill in existing_skills}
        retriever = self.retriever or build_document_skill_retriever()
        retriever.refresh(existing_skills)

        cached_decisions = intermediate_writer.load_register_decisions() if intermediate_writer is not None else {}
        decisions: List[ChangeDecision] = []
        total_skills = len(skills_list)
        emit_stage_progress(
            self.progress_callback,
            {
                "stage": "register",
                "kind": "start",
                "phase": "reconcile",
                "completed_skills": 0,
                "total_skills": total_skills,
                "errors": 0,
            },
        )
        for idx, skill in enumerate(skills_list, start=1):
            cached = cached_decisions.get(skill.skill_id)
            if cached is not None:
                decision = cached
                decisions.append(decision)
                emit_stage_log(
                    self.logger,
                    (
                        f"[register_versions] classify_resume skill={skill.skill_id} "
                        f"action={decision.action} "
                        f"branch={decision.branch or '-'}"
                    ),
                )
            else:
                hits = retriever.search(
                    skill,
                    limit=self.retrieval_limit,
                )
                retrieved_existing = [hit.skill for hit in list(hits or [])]
                emit_stage_log(
                    self.logger,
                    (
                        f"[register_versions] retrieve skill={skill.skill_id} "
                        f"hits={len(retrieved_existing)} "
                        f"names={summarize_names([item.name for item in retrieved_existing])}"
                    ),
                )
                decision = self.classify_change(
                    skill,
                    peer_skills=skills_list,
                    existing_skills=retrieved_existing,
                    support_by_id=support_by_id,
                )
                decisions.append(decision)
                if intermediate_writer is not None:
                    intermediate_writer.write_register_decision(
                        decision,
                        hits=len(retrieved_existing),
                        branch=str(decision.branch or "").strip() or ("full" if retrieved_existing else "hits0"),
                        total_skills=total_skills,
                    )
            emit_stage_progress(
                self.progress_callback,
                {
                    "stage": "register",
                    "kind": "reconcile_progress",
                    "phase": "reconcile",
                    "completed_skills": idx,
                    "total_skills": total_skills,
                    "current_skill_id": str(skill.skill_id or "").strip(),
                    "current_name": str(skill.name or "").strip(),
                    "hits": int(decision.hits or 0),
                    "action": str(decision.action or "").strip(),
                    "errors": len(list(result.errors or [])),
                },
            )

        processed_split_parents: Set[str] = set()
        consumed_existing_ids: Set[str] = set()
        consumed_new_ids: Set[str] = set()
        incoming_support_by_id = {support.support_id: support for support in list(support_records or [])}

        for decision in [item for item in decisions if item.action == "merge" and item.matched_skill_ids]:
            new_skill = decision.skill
            application = self.merge_skills(
                decision=decision,
                skill=new_skill,
                existing_skills_by_id=existing_skills_by_id,
                target_state=target_state,
            )
            merged_skill = application["primary_skill"]
            bound_supports = [
                _copy_support(support, skill_id=merged_skill.skill_id)
                for support in list(incoming_support_by_id.values())
                if support.support_id in set(new_skill.support_ids or [])
            ]
            merged_skill = _copy_skill(
                merged_skill,
                support_ids=list(dict.fromkeys(list(merged_skill.support_ids or []) + [support.support_id for support in bound_supports])),
                metadata_update={"llm_reason": decision.reason},
            )
            provenance = {
                "entity_type": "skill",
                "entity_id": merged_skill.skill_id,
                "doc_ids": _doc_ids_from_support_ids(merged_skill.support_ids, support_by_id),
                "support_added": [support.support_id for support in bound_supports],
                "support_conflicts": _conflicting_support_ids(merged_skill.support_ids, support_by_id),
                "related_entity_ids": decision.matched_skill_ids,
            }
            result.skill_specs.append(merged_skill)
            result.support_records.extend(bound_supports)
            result.lifecycles.append(
                self.update_lifecycle(
                    skill_id=merged_skill.skill_id,
                    current_state=existing_skills_by_id[merged_skill.skill_id].status,
                    action="merge",
                    target_state=target_state,
                    metadata={"merged_from_skill_ids": decision.matched_skill_ids, "llm_reason": decision.reason},
                )
            )
            result.provenance_links.append(provenance)
            result.change_logs.append(
                self._change_payload(
                    entity_type="skill",
                    entity_id=merged_skill.skill_id,
                    action="merge",
                    from_version=existing_skills_by_id[merged_skill.skill_id].version,
                    to_version=merged_skill.version,
                    from_state=existing_skills_by_id[merged_skill.skill_id].status.value,
                    to_state=merged_skill.status.value,
                    summary=decision.reason,
                    provenance=provenance,
                    related_entity_ids=decision.matched_skill_ids,
                )
            )
            result.version_history.append(
                self._history_payload(
                    entity_type="skill",
                    entity_id=merged_skill.skill_id,
                    version=merged_skill.version,
                    action="merge",
                    status=merged_skill.status,
                    related_entity_ids=decision.matched_skill_ids,
                )
            )
            for secondary in list(application["secondary"] or []):
                result.skill_specs.append(secondary["skill"])
                result.lifecycles.append(secondary["lifecycle"])
                result.change_logs.append(secondary["change_log"])
                result.version_history.append(secondary["version_history"])
                result.provenance_links.append(secondary["provenance_links"])
            consumed_new_ids.add(new_skill.skill_id)
            consumed_existing_ids.update(decision.matched_skill_ids)
            emit_stage_log(
                self.logger,
                f"[register_versions] merge name={merged_skill.name} skill={merged_skill.skill_id} from={decision.matched_skill_ids}",
            )

        split_groups: Dict[str, List[ChangeDecision]] = {}
        for decision in decisions:
            if decision.action != "split" or not decision.matched_skill_ids:
                continue
            split_groups.setdefault(decision.matched_skill_ids[0], []).append(decision)

        for parent_id, bucket in split_groups.items():
            if parent_id in processed_split_parents:
                continue
            parent = existing_skills_by_id.get(parent_id)
            if parent is None:
                continue
            application = self.split_skill(
                parent_skill=parent,
                child_skills=[item.skill for item in bucket],
                target_state=target_state,
            )
            processed_split_parents.add(parent_id)
            consumed_existing_ids.add(parent_id)
            for item in bucket:
                consumed_new_ids.add(item.skill.skill_id)
                bound_supports = [
                    _copy_support(support, skill_id=item.skill.skill_id)
                    for support in list(incoming_support_by_id.values())
                    if support.support_id in set(item.skill.support_ids or [])
                ]
                result.support_records.extend(bound_supports)
            result.skill_specs.extend(list(application["children"] or []))
            result.skill_specs.append(application["deprecated_parent"]["skill"])
            result.lifecycles.extend(list(application["lifecycles"] or []))
            result.lifecycles.append(application["deprecated_parent"]["lifecycle"])
            result.change_logs.extend(list(application["change_logs"] or []))
            result.change_logs.append(application["deprecated_parent"]["change_log"])
            result.version_history.extend(list(application["version_history"] or []))
            result.version_history.append(application["deprecated_parent"]["version_history"])
            result.provenance_links.extend(list(application["provenance_links"] or []))
            result.provenance_links.append(application["deprecated_parent"]["provenance_links"])
            emit_stage_log(
                self.logger,
                f"[register_versions] split parent={parent_id} children={len(bucket)} names={summarize_names([item.skill.name for item in bucket])}",
            )

        for decision in decisions:
            if decision.skill.skill_id in consumed_new_ids or decision.action == "discard":
                continue
            if decision.action not in {"create", "strengthen", "revise", "unchanged"}:
                continue

            new_skill = decision.skill
            incoming_supports = [
                support
                for support in list(incoming_support_by_id.values())
                if support.support_id in set(new_skill.support_ids or [])
            ]

            if decision.action == "create" or not decision.matched_skill_ids:
                updated_skill = _copy_skill(
                    new_skill,
                    version=self.create_new_version(current_version=new_skill.version, action="create"),
                    status=target_state,
                    metadata_update={"change_action": "create", "llm_reason": decision.reason},
                )
                bound_supports = [_copy_support(support, skill_id=updated_skill.skill_id) for support in incoming_supports]
                updated_skill = _copy_skill(updated_skill, support_ids=[support.support_id for support in bound_supports])
                provenance = {
                    "entity_type": "skill",
                    "entity_id": updated_skill.skill_id,
                    "doc_ids": _doc_ids_from_support_ids(updated_skill.support_ids, support_by_id),
                    "support_added": list(updated_skill.support_ids or []),
                    "support_conflicts": _conflicting_support_ids(updated_skill.support_ids, support_by_id),
                    "related_entity_ids": [],
                }
                result.skill_specs.append(updated_skill)
                result.support_records.extend(bound_supports)
                result.lifecycles.append(
                    self.update_lifecycle(
                        skill_id=updated_skill.skill_id,
                        current_state=None,
                        action="create",
                        target_state=target_state,
                        metadata={"doc_ids": provenance["doc_ids"], "llm_reason": decision.reason},
                    )
                )
                result.change_logs.append(
                    self._change_payload(
                        entity_type="skill",
                        entity_id=updated_skill.skill_id,
                        action="create",
                        from_version="",
                        to_version=updated_skill.version,
                        from_state="",
                        to_state=updated_skill.status.value,
                        summary=decision.reason,
                        provenance=provenance,
                    )
                )
                result.version_history.append(
                    self._history_payload(
                        entity_type="skill",
                        entity_id=updated_skill.skill_id,
                        version=updated_skill.version,
                        action="create",
                        status=updated_skill.status,
                    )
                )
                result.provenance_links.append(provenance)
                emit_stage_log(
                    self.logger,
                    f"[register_versions] create name={updated_skill.name} skill={updated_skill.skill_id}",
                )
                continue

            existing_skill = existing_skills_by_id.get(decision.matched_skill_ids[0])
            if existing_skill is None:
                result.errors.append({"skill_id": new_skill.skill_id, "error": "matched skill missing from registry"})
                continue
            current_version = existing_skill.version
            next_version = self.create_new_version(current_version=current_version, action=decision.action)
            if decision.action == "unchanged":
                next_version = current_version
            bound_supports = [_copy_support(support, skill_id=existing_skill.skill_id) for support in incoming_supports]
            merged_support_ids = list(dict.fromkeys(list(existing_skill.support_ids or []) + [support.support_id for support in bound_supports]))
            updated_skill = _skill_with_frozen_identity(
                base=existing_skill,
                content=new_skill,
                version=next_version,
                status=(existing_skill.status if decision.action == "unchanged" else target_state),
                support_ids=merged_support_ids,
                metadata_update={
                    "change_action": decision.action,
                    "previous_skill_id": existing_skill.skill_id,
                    "llm_reason": decision.reason,
                },
            )
            provenance = {
                "entity_type": "skill",
                "entity_id": updated_skill.skill_id,
                "doc_ids": _doc_ids_from_support_ids(updated_skill.support_ids, support_by_id),
                "support_added": [support.support_id for support in bound_supports],
                "support_conflicts": _conflicting_support_ids(updated_skill.support_ids, support_by_id),
                "related_entity_ids": [existing_skill.skill_id],
            }
            result.skill_specs.append(updated_skill)
            result.support_records.extend(bound_supports)
            consumed_existing_ids.add(existing_skill.skill_id)
            if decision.action != "unchanged":
                result.lifecycles.append(
                    self.update_lifecycle(
                        skill_id=updated_skill.skill_id,
                        current_state=existing_skill.status,
                        action=decision.action,
                        target_state=target_state,
                        metadata={**provenance, "llm_reason": decision.reason},
                    )
                )
                result.change_logs.append(
                    self._change_payload(
                        entity_type="skill",
                        entity_id=updated_skill.skill_id,
                        action=decision.action,
                        from_version=existing_skill.version,
                        to_version=updated_skill.version,
                        from_state=existing_skill.status.value,
                        to_state=updated_skill.status.value,
                        summary=decision.reason,
                        provenance=provenance,
                        related_entity_ids=[existing_skill.skill_id],
                    )
                )
                result.version_history.append(
                    self._history_payload(
                        entity_type="skill",
                        entity_id=updated_skill.skill_id,
                        version=updated_skill.version,
                        action=decision.action,
                        status=updated_skill.status,
                        related_entity_ids=[existing_skill.skill_id],
                    )
                )
                result.provenance_links.append(provenance)
                emit_stage_log(
                    self.logger,
                    f"[register_versions] {decision.action} name={updated_skill.name} skill={updated_skill.skill_id}",
                )

        incoming_related = [decision.skill for decision in decisions if decision.action != "discard"]
        if any(support.relation_type == SupportRelation.CONFLICT for support in support_records or []):
            for existing_skill in existing_skills:
                if existing_skill.skill_id in consumed_existing_ids:
                    continue
                if existing_skill.status in {VersionState.DEPRECATED, VersionState.RETIRED}:
                    continue
                review = self._conflict_review(
                    existing_skill=existing_skill,
                    incoming_skills=incoming_related,
                    support_by_id=support_by_id,
                )
                if review["action"] == "keep":
                    continue
                deprecated_state = (
                    VersionState.WATCHLIST if review["action"] == "watchlist" else VersionState.DEPRECATED
                )
                deprecated = self.mark_deprecated(
                    skill=existing_skill,
                    reason=review["reason"],
                    state=deprecated_state,
                    related_ids=[skill.skill_id for skill in incoming_related],
                )
                result.skill_specs.append(deprecated["skill"])
                result.lifecycles.append(deprecated["lifecycle"])
                result.change_logs.append(deprecated["change_log"])
                result.version_history.append(deprecated["version_history"])
                result.provenance_links.append(deprecated["provenance_links"])
                consumed_existing_ids.add(existing_skill.skill_id)
                emit_stage_log(
                    self.logger,
                    f"[register_versions] deprecate name={existing_skill.name} skill={existing_skill.skill_id}",
                )

        deduped_skills: Dict[str, SkillSpec] = {}
        for skill in result.skill_specs:
            deduped_skills[f"{skill.skill_id}:{skill.status.value}"] = skill
        result.skill_specs = list(deduped_skills.values())

        deduped_supports: Dict[str, SupportRecord] = {}
        for support in result.support_records:
            deduped_supports[support.support_id] = support
        result.support_records = list(deduped_supports.values())
        emit_stage_progress(
            self.progress_callback,
            {
                "stage": "register",
                "kind": "reconcile_done",
                "phase": "reconcile",
                "completed_skills": total_skills,
                "total_skills": total_skills,
                "actions": {
                    "create": len([item for item in decisions if item.action == "create"]),
                    "strengthen": len([item for item in decisions if item.action == "strengthen"]),
                    "revise": len([item for item in decisions if item.action == "revise"]),
                    "merge": len([item for item in decisions if item.action == "merge"]),
                    "split": len([item for item in decisions if item.action == "split"]),
                    "unchanged": len([item for item in decisions if item.action == "unchanged"]),
                    "discard": len([item for item in decisions if item.action == "discard"]),
                },
                "errors": len(list(result.errors or [])),
            },
        )
        return result


def register_versions(
    *,
    registry: DocumentRegistry,
    documents: Sequence[DocumentRecord],
    support_records: Sequence[SupportRecord],
    skill_specs: Sequence[SkillSpec],
    sdk: Optional[AutoSkill] = None,
    llm: Optional[LLM] = None,
    user_id: str = DEFAULT_DOC_SKILL_USER_ID,
    metadata: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    target_state: VersionState = VersionState.ACTIVE,
    logger: StageLogger = None,
    intermediate_writer: Optional["IntermediateRunWriter"] = None,
    progress_callback: StageProgressCallback = None,
    retrieval_score_threshold: float = DEFAULT_RETRIEVAL_SCORE_THRESHOLD,
    llm_rate_limit_requests: int = DEFAULT_LLM_RATE_LIMIT_REQUESTS,
    llm_rate_limit_window_s: float = DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
) -> VersionRegistrationResult:
    """
    Registers a compiled batch into the document registry and optionally the skill store.
    """

    effective_state = VersionState.DRAFT if dry_run else target_state
    preexisting_skills = list(registry.list_skills())
    llm_config = dict(getattr(getattr(sdk, "config", None), "llm", {}) or {"provider": "mock"})

    raw_base_llm = llm or build_llm(dict(llm_config))
    raw_hits0_change_llm, raw_full_change_llm = _resolve_change_decision_llms(
        sdk=sdk,
        fallback_llm=raw_base_llm,
    )
    raw_hierarchy_link_llm = _resolve_hierarchy_link_llm(
        sdk=sdk,
        fallback_llm=raw_base_llm,
    )

    llm_impl = maybe_wrap_llm_with_rate_limit(
        raw_base_llm,
        max_requests=llm_rate_limit_requests,
        window_s=llm_rate_limit_window_s,
        llm_config=llm_config,
        scope=AUTOSKILL4DOC_LLM_SCOPE,
    )
    hits0_change_llm = (
        llm_impl
        if raw_hits0_change_llm is raw_base_llm
        else maybe_wrap_llm_with_rate_limit(
            raw_hits0_change_llm,
            max_requests=llm_rate_limit_requests,
            window_s=llm_rate_limit_window_s,
            llm_config=_register_change_decision_llm_config(llm_config, hits0_branch=True),
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
    )
    full_change_llm = (
        llm_impl
        if raw_full_change_llm is raw_base_llm
        else maybe_wrap_llm_with_rate_limit(
            raw_full_change_llm,
            max_requests=llm_rate_limit_requests,
            window_s=llm_rate_limit_window_s,
            llm_config=_register_change_decision_llm_config(llm_config, hits0_branch=False),
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
    )
    hierarchy_link_llm = (
        llm_impl
        if raw_hierarchy_link_llm is raw_base_llm
        else maybe_wrap_llm_with_rate_limit(
            raw_hierarchy_link_llm,
            max_requests=llm_rate_limit_requests,
            window_s=llm_rate_limit_window_s,
            llm_config=_register_hierarchy_llm_config(llm_config),
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
    )
    sdk_config = getattr(sdk, "config", None)
    embeddings_config = dict(getattr(sdk_config, "embeddings", {}) or {"provider": "hashing", "dims": 256})
    bm25_weight = float(getattr(sdk_config, "bm25_weight", 0.1) or 0.1)
    store_root = _store_root_from_context(registry=registry, sdk=sdk)
    retriever = build_document_skill_retriever(
        embeddings_config=embeddings_config,
        bm25_weight=bm25_weight,
        score_threshold=max(0.0, float(retrieval_score_threshold or DEFAULT_RETRIEVAL_SCORE_THRESHOLD)),
        base_store_root=store_root,
    )
    manager = VersionManager(
        registry=registry,
        llm=llm_impl,
        hits0_change_llm=hits0_change_llm,
        full_change_llm=full_change_llm,
        hierarchy_link_llm=hierarchy_link_llm,
        retriever=retriever,
        retrieval_limit=DEFAULT_RETRIEVAL_LIMIT,
        logger=logger,
        progress_callback=progress_callback,
    )
    reconciled = manager.reconcile(
        skills=skill_specs,
        support_records=support_records,
        target_state=effective_state,
        intermediate_writer=intermediate_writer,
    )
    reconciled.skill_specs = [_merge_layout_metadata(skill, metadata=metadata) for skill in list(reconciled.skill_specs or [])]
    reconciled.skill_specs, reconciled.hierarchy_updates = manager.link_hierarchy(
        skills=reconciled.skill_specs,
        existing_skills=preexisting_skills,
        error_sink=reconciled.errors,
    )
    reconciled = manager.consolidate_duplicate_skills(
        result=reconciled,
        existing_skills=preexisting_skills,
        existing_supports=list(registry.list_supports()),
        target_state=effective_state,
        metadata=metadata,
    )
    emit_stage_progress(
        progress_callback,
        {
            "stage": "register",
            "kind": "hierarchy_done",
            "phase": "hierarchy",
            "completed_skills": len(list(reconciled.skill_specs or [])),
            "total_skills": len(list(reconciled.skill_specs or [])),
            "hierarchy_updates": len(list(reconciled.hierarchy_updates or [])),
            "errors": len(list(reconciled.errors or [])),
        },
    )
    reconciled.documents = list(documents or [])
    reconciled.dry_run = bool(dry_run)
    current_store_skills: List[Any] = []

    if not dry_run:
        for document in documents or []:
            registry.upsert_document(document)
        for support in reconciled.support_records:
            registry.upsert_support(support)
        seen_skills: Set[str] = set()
        for skill in list(reconciled.skill_specs or []) + list(reconciled.hierarchy_updates or []):
            key = f"{skill.skill_id}:{skill.status.value}"
            if key in seen_skills:
                continue
            registry.upsert_skill(skill)
            seen_skills.add(key)
        for lifecycle in reconciled.lifecycles:
            registry.append_lifecycle(lifecycle)
        for payload in reconciled.change_logs:
            registry.append_change_log(str(payload.get("change_id") or str(uuid.uuid4())), payload)
        for entry in reconciled.version_history:
            registry.append_version_history(
                entity_type=str(entry.get("entity_type") or ""),
                entity_id=str(entry.get("entity_id") or ""),
                entry=entry,
            )
        for payload in reconciled.provenance_links:
            registry.upsert_provenance_links(
                entity_type=str(payload.get("entity_type") or ""),
                entity_id=str(payload.get("entity_id") or ""),
                payload=payload,
            )
        try:
            retriever.refresh(list(registry.list_skills()))
        except Exception as e:
            reconciled.errors.append({"stage": "retrieval_cache_refresh", "error": str(e)})
            emit_stage_log(logger, f"[register_versions] retrieval cache refresh error: {e}")

    if sdk is not None and reconciled.skill_specs:
        md = dict(metadata or {})
        md.setdefault("channel", "offline_extract_from_doc")
        md.setdefault("source_type", "document")
        md["document_registry_root"] = registry.root_dir
        if reconciled.skill_specs:
            if not dry_run:
                try:
                    touched_store_skills, current_store_skills = _sync_store_skills(
                        sdk=sdk,
                        skill_specs=list(reconciled.skill_specs or []) + list(reconciled.hierarchy_updates or []),
                        user_id=str(user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID,
                        metadata=md,
                        logger=logger,
                    )
                    reconciled.upserted_store_skills = [_plain_skill(skill) for skill in list(touched_store_skills or [])]
                    emit_stage_log(
                        logger,
                        f"[register_versions] store_upserts={len(reconciled.upserted_store_skills)} names={summarize_names([str(skill.get('name') or '') for skill in reconciled.upserted_store_skills])}",
                    )
                    emit_stage_progress(
                        progress_callback,
                        {
                            "stage": "register",
                            "kind": "store_done",
                            "phase": "store_sync",
                            "completed_skills": len(list(reconciled.skill_specs or [])),
                            "total_skills": len(list(reconciled.skill_specs or [])),
                            "store_upserts": len(list(reconciled.upserted_store_skills or [])),
                            "errors": len(list(reconciled.errors or [])),
                        },
                    )
                except Exception as e:
                    reconciled.errors.append({"stage": "store_upsert", "error": str(e)})
                    emit_stage_log(logger, f"[register_versions] store upsert error: {e}")
            else:
                emit_stage_log(
                    logger,
                    f"[register_versions] dry-run store_upserts={len(reconciled.skill_specs)} names={summarize_names([spec.name for spec in reconciled.skill_specs])}",
                )
        if not dry_run and not current_store_skills:
            try:
                current_store_skills = list(sdk.store.list(user_id=str(user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID) or [])
            except Exception:
                current_store_skills = []

    if not dry_run:
        store_root = _store_root_from_context(registry=registry, sdk=sdk)
        if reconciled.skill_specs:
            bucketed: Dict[Tuple[str, str, str], List[SkillSpec]] = {}
            for skill in list(reconciled.skill_specs or []):
                bucket = _staging_bucket_for_skill(skill, metadata=metadata)
                bucketed.setdefault(bucket, []).append(skill)
            raw_bucketed: Dict[Tuple[str, str, str], List[SkillSpec]] = {}
            for skill in list(skill_specs or []):
                merged = _merge_layout_metadata(skill, metadata=metadata)
                bucket = _staging_bucket_for_skill(merged, metadata=metadata)
                raw_bucketed.setdefault(bucket, []).append(merged)

            support_by_id = {support.support_id: support for support in list(reconciled.support_records or [])}
            document_by_id = {document.doc_id: document for document in list(documents or [])}
            for (profile_id, family_id, child_type), bucket_skills in bucketed.items():
                bucket_skill_ids = {skill.skill_id for skill in list(bucket_skills or [])}
                bucket_support_ids = {
                    str(support_id or "").strip()
                    for skill in list(bucket_skills or [])
                    for support_id in list(skill.support_ids or [])
                    if str(support_id or "").strip()
                }
                bucket_supports = [
                    support.to_dict()
                    for support_id, support in support_by_id.items()
                    if support_id in bucket_support_ids
                ]
                bucket_documents = [
                    document.to_dict()
                    for document_id, document in document_by_id.items()
                    if document_id in {
                        str(support.doc_id or "").strip()
                        for support in support_by_id.values()
                        if support.support_id in bucket_support_ids
                    }
                ]
                bucket_existing_active = [
                    skill.to_dict()
                    for skill in preexisting_skills
                    if skill.status in _ACTIVE_STORE_STATES and _staging_bucket_for_skill(skill, metadata=metadata) == (profile_id, family_id, child_type)
                ]
                bucket_change_logs = [
                    dict(payload)
                    for payload in list(reconciled.change_logs or [])
                    if str(payload.get("entity_id") or "").strip() in bucket_skill_ids
                ]
                staging_summary = write_registration_staging(
                    base_store_root=store_root,
                    profile_id=profile_id,
                    family_id=family_id,
                    child_type=child_type,
                    run_id="",
                    documents=bucket_documents,
                    support_records=bucket_supports,
                    raw_candidates=plain_skill_specs(raw_bucketed.get((profile_id, family_id, child_type)) or []),
                    existing_active=bucket_existing_active,
                    canonical_results=plain_skill_specs(bucket_skills),
                    change_logs=bucket_change_logs,
                )
                reconciled.staging_runs.append(staging_summary.to_dict())
                emit_stage_log(
                    logger,
                    f"[register_versions] staging profile={profile_id} family={family_id} child_type={child_type} skills={len(bucket_skills)}",
                )
                emit_stage_progress(
                    progress_callback,
                    {
                        "stage": "register",
                        "kind": "staging_progress",
                        "phase": "staging",
                        "completed_buckets": len(list(reconciled.staging_runs or [])),
                        "total_buckets": len(bucketed),
                        "family_name": family_id,
                        "child_type": child_type,
                        "errors": len(list(reconciled.errors or [])),
                    },
                )

        try:
            visible_tree = sync_visible_skill_tree(
                registry=registry,
                store_root=store_root,
                documents=documents,
                support_records=reconciled.support_records,
                skill_specs=reconciled.skill_specs,
                user_id=str(user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID,
                metadata=metadata,
                store_skills=(current_store_skills if sdk is not None else None),
                logger=logger,
            )
            reconciled.visible_tree = visible_tree.to_dict()
            emit_stage_progress(
                progress_callback,
                {
                    "stage": "register",
                    "kind": "visible_tree_done",
                    "phase": "visible_tree",
                    "completed_skills": len(list(reconciled.skill_specs or [])),
                    "total_skills": len(list(reconciled.skill_specs or [])),
                    "affected_families": len(list((reconciled.visible_tree or {}).get("affected_families") or [])),
                    "visible_children": len(list((reconciled.visible_tree or {}).get("child_paths") or [])),
                    "errors": len(list(reconciled.errors or [])),
                },
            )
        except Exception as e:
            reconciled.errors.append({"stage": "visible_tree_sync", "error": str(e)})
            emit_stage_log(logger, f"[register_versions] visible tree sync error: {e}")

    return reconciled
