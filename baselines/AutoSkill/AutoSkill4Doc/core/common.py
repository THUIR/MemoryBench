"""
Common helpers for the offline document pipeline.

These utilities intentionally stay small and dependency-free so stage modules
can share the same naming and behavior without reimplementing the same text and
logging helpers.
"""

from __future__ import annotations

import re
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

StageLogger = Optional[Callable[[str], None]]
StageProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


def emit_stage_log(logger: StageLogger, message: str) -> None:
    """Emits one stage log line when a logger callback is configured."""

    if logger is not None:
        logger(str(message))


def emit_stage_progress(callback: StageProgressCallback, payload: Dict[str, Any]) -> None:
    """Emits one structured stage progress event without breaking the caller."""

    if callback is None:
        return
    try:
        callback(dict(payload or {}))
    except Exception:
        return


def normalize_text(text: str, *, lower: bool = False) -> str:
    """Collapses whitespace while preserving token order."""

    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    return normalized.lower() if lower else normalized


def dedupe_strings(
    items: Iterable[str],
    *,
    lower: bool = True,
) -> List[str]:
    """Deduplicates strings while preserving their first-seen order."""

    out: List[str] = []
    seen = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = normalize_text(value, lower=lower)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def short_source_label(path: str) -> str:
    """Returns a compact source label suitable for progress logs."""

    raw = str(path or "").strip()
    return os.path.basename(raw) if raw else ""


def document_progress_label(*, doc_id: str, title: str, source_file: str) -> str:
    """Builds a concise human-readable document label for progress output."""

    parts: List[str] = []
    title_s = str(title or "").strip()
    source_s = short_source_label(source_file)
    doc_id_s = str(doc_id or "").strip()
    if title_s:
        parts.append(f"title={title_s}")
    if source_s:
        parts.append(f"file={source_s}")
    if doc_id_s:
        parts.append(f"doc={doc_id_s}")
    return " ".join(parts).strip()


def summarize_names(items: Sequence[str], *, limit: int = 5) -> str:
    """Builds a compact name summary for progress logs."""

    names = dedupe_strings([str(item or "").strip() for item in items if str(item or "").strip()], lower=True)
    if not names:
        return "-"
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f", +{len(names) - limit} more"


def should_keep_metadata_value(value: Any) -> bool:
    """Returns whether one metadata value is meaningful enough to persist."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def compact_metadata(mapping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drops only empty-string/None metadata while preserving structured values."""

    out: Dict[str, Any] = {}
    for key, value in dict(mapping or {}).items():
        if should_keep_metadata_value(value):
            out[str(key)] = value
    return out


_SAFETY_HINTS = (
    "自杀",
    "自伤",
    "他伤",
    "伤人",
    "危机",
    "安全计划",
    "安全承诺",
    "不自杀承诺",
    "紧急热线",
    "suicide",
    "self-harm",
    "crisis",
    "safety plan",
    "safety commitment",
    "hotline",
    "violence",
    "homicide",
)

_MACRO_SCOPE_HINTS = (
    "三阶段",
    "多阶段",
    "分阶段",
    "全过程",
    "全程",
    "完整流程",
    "阶段化",
    "phase 1",
    "phase 2",
    "phase 3",
    "multi-stage",
    "end-to-end",
    "from intake to closing",
)

_SESSION_SCOPE_HINTS = (
    "会谈结构",
    "session structure",
    "session flow",
    "结构化会谈",
    "固定环节",
    "agenda",
    "homework review",
    "summary and feedback",
    "组合包",
    "技术集",
    "toolkit",
    "bundle",
    "package",
)

_MICRO_SCOPE_HINTS = (
    "微干预",
    "引导",
    "识别",
    "命名",
    "提问",
    "反映",
    "镜映",
    "重评",
    "prompting",
    "naming",
    "reflection",
    "reframing",
)


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    normalized = normalize_text(text, lower=True)
    return any(str(marker or "").strip().lower() in normalized for marker in markers if str(marker or "").strip())


def refine_asset_shape(
    *,
    asset_type: str,
    granularity: str,
    name: str,
    description: str,
    objective: str,
    prompt: str,
    risk_class: str,
    task_family: str,
    stage: str,
    intervention_moves: Sequence[str],
    workflow_steps: Sequence[str],
) -> Tuple[str, str]:
    """Corrects asset_type/granularity drift using lightweight scope and safety rules."""

    text = "\n".join(
        [
            str(name or ""),
            str(description or ""),
            str(objective or ""),
            str(task_family or ""),
            str(stage or ""),
        ]
    )
    move_count = len([x for x in intervention_moves if str(x or "").strip()])
    step_count = len([x for x in workflow_steps if str(x or "").strip()])
    task_family_s = str(task_family or "").strip().lower()
    stage_s = str(stage or "").strip().lower()
    risk_class_s = str(risk_class or "").strip().lower()
    asset_type_s = str(asset_type or "").strip() or "session_skill"
    granularity_s = str(granularity or "").strip() or "session"

    has_safety = (
        risk_class_s == "high"
        or task_family_s in {"risk_screening", "de_escalation", "crisis", "crisis_intervention"}
        or stage_s == "crisis"
        or _contains_any(text, _SAFETY_HINTS)
    )
    if has_safety:
        if step_count <= 2 and move_count <= 2 and _contains_any(text, _MICRO_SCOPE_HINTS):
            return "safety_rule", "micro"
        return "safety_rule", "session"

    if asset_type_s == "knowledge_reference":
        return "knowledge_reference", "session"

    if _contains_any(text, _MACRO_SCOPE_HINTS):
        return "macro_protocol", "macro"

    if asset_type_s == "macro_protocol":
        return "macro_protocol", "macro"

    if asset_type_s == "micro_skill":
        if _contains_any(text, _SESSION_SCOPE_HINTS):
            return "session_skill", "session"
        if step_count >= 6 and move_count >= 4:
            return "session_skill", "session"
        return "micro_skill", "micro"

    if asset_type_s == "session_skill":
        if _contains_any(text, _MICRO_SCOPE_HINTS) and not _contains_any(text, _SESSION_SCOPE_HINTS):
            if step_count <= 5 and move_count <= 3:
                return "micro_skill", "micro"
        return "session_skill", "session"

    return asset_type_s, granularity_s


_TASK_FAMILY_ALIASES = {
    "case formulation": "case_formulation",
    "case-formulation": "case_formulation",
    "个案概念化": "case_formulation",
    "treatment framework": "treatment_framework",
    "treatment-framework": "treatment_framework",
    "session framework": "session_framework",
    "session-framework": "session_framework",
    "treatment closure": "treatment_closure",
    "treatment-closure": "treatment_closure",
    "结束整合": "treatment_closure",
}

_GENERIC_TASK_FAMILY_LABELS = {
    "心理咨询",
    "咨询",
    "psychology",
    "psychology counseling",
    "counseling",
    "counselling",
    "therapy",
    "psychotherapy",
    "mental health",
    "心理动力学",
    "psychodynamic",
    "动力性心理治疗",
    "心理动力学治疗",
}


def normalize_task_family(
    task_family: str,
    *,
    asset_node_id: str = "",
    domain: str = "",
    method_family: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Normalizes task_family into a reusable task label instead of a domain/method label."""

    raw = str(task_family or "").strip()
    fallback = str(asset_node_id or "").strip()
    if not raw:
        return fallback
    key = normalize_text(raw, lower=True)
    alias = _TASK_FAMILY_ALIASES.get(key)
    if alias:
        return alias

    generic_labels = set(_GENERIC_TASK_FAMILY_LABELS)
    for value in (
        domain,
        method_family,
        str((metadata or {}).get("family_name") or ""),
        str((metadata or {}).get("family_id") or ""),
        str((metadata or {}).get("domain_root_name") or ""),
    ):
        normalized = normalize_text(str(value or "").strip(), lower=True)
        if normalized:
            generic_labels.add(normalized)

    if key in generic_labels and fallback:
        return fallback
    return raw
