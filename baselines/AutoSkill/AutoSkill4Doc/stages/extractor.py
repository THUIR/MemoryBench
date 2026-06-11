"""
LLM-driven skill extraction stage for the offline document pipeline.
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import json
import re
import time
import uuid
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from autoskill.llm.base import LLM
from autoskill.llm.factory import build_llm
from autoskill.models import SkillExample

from ..core.common import (
    StageLogger,
    StageProgressCallback,
    document_progress_label,
    emit_stage_log,
    emit_stage_progress,
    normalize_text,
    summarize_names,
)
from ..core.config import DEFAULT_MAX_CANDIDATES_PER_UNIT
from ..core.llm_utils import (
    clip_confidence,
    coerce_str_list,
    compact_text_list,
    llm_complete_json,
    maybe_json_dict,
    section_items_from_prompt,
)
from ..core.rate_limit import AUTOSKILL4DOC_LLM_SCOPE, RateLimitedLLM, maybe_wrap_llm_with_rate_limit
from ..models import (
    DocumentRecord,
    SkillDraft,
    StrictWindow,
    SupportRecord,
    SupportRelation,
    TextSpan,
)
from ..prompts import OFFLINE_CHANNEL_DOC, maybe_offline_prompt
from ..taxonomy import SkillTaxonomy, load_skill_taxonomy

_WORKFLOW_PATTERNS = [r"^\s*[\-\*\u2022]\s+", r"^\s*\d+[\.\)]\s+"]
_DEFAULT_SECTION_CHARS = 2400
_DEFAULT_CHUNK_OVERLAP_CHARS = 200
_DEFAULT_EXTRACT_RETRIES = 3
_DEFAULT_EXTRACT_RETRY_BACKOFF_S = 1.0
_DEFAULT_LLM_RATE_LIMIT_REQUESTS = 0
_DEFAULT_LLM_RATE_LIMIT_WINDOW_S = 300.0
_DEFAULT_SECTION_PRIORITY_TERMS = (
    "goal",
    "session goal",
    "treatment goal",
    "intervention",
    "session intervention",
    "stage",
    "session",
    "homework",
    "worksheet",
    "work sheet",
    "risk",
    "safety",
    "relapse prevention",
    "protocol",
    "procedure",
    "technique",
    "workflow",
    "step-by-step",
    "目标",
    "干预",
    "阶段",
    "会谈",
    "作业",
    "工作表",
    "清单",
    "风险",
    "安全计划",
    "复发预防",
    "技术",
    "流程",
    "步骤",
)
_DEFAULT_SECTION_DEPRIORITIZE_TERMS = (
    "demographics",
    "growth history",
    "background",
    "abstract",
    "summary",
    "keywords",
    "references",
    "reference",
    "bibliography",
    "appendix",
    "author contributions",
    "funding",
    "acknowledg",
    "ethics",
    "conflict of interest",
    "人口统计",
    "成长史",
    "背景",
    "摘要",
    "关键词",
    "参考文献",
    "附录",
    "基金",
    "致谢",
    "伦理",
    "利益冲突",
)


def _split_section_blocks(text: str) -> List[str]:
    """Splits one section into paragraph-like blocks before fallback chunking."""

    src = str(text or "").strip()
    if not src:
        return []
    blocks: List[str] = []
    for paragraph in [p.strip() for p in src.split("\n\n") if p.strip()]:
        lines = [ln.strip() for ln in paragraph.splitlines() if ln.strip()]
        bullet_lines = [ln for ln in lines if any(re.search(pattern, ln) for pattern in _WORKFLOW_PATTERNS)]
        if bullet_lines and len(bullet_lines) == len(lines):
            blocks.extend(bullet_lines)
            continue
        blocks.append(paragraph)
    return blocks


def _is_retryable_extract_error(exc: Exception) -> bool:
    """Returns whether one extraction error looks transient and worth retrying."""

    raw = normalize_text(str(exc or ""), lower=True)
    if not raw:
        return False
    retry_tokens = (
        "429",
        "too many requests",
        "rate limit",
        "rate-limit",
        "throttle",
        "overload",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "connection refused",
        "remote disconnected",
        "try again",
        "retry later",
        "server error",
        "internal server error",
        "502",
        "503",
        "504",
    )
    return any(token in raw for token in retry_tokens)


def _retry_backoff_seconds(*, attempt: int, base_delay_s: float) -> float:
    """Builds one deterministic exponential backoff delay."""

    base = max(0.0, float(base_delay_s or 0.0))
    if base <= 0.0:
        return 0.0
    return min(8.0, base * (2 ** max(0, int(attempt or 0))))


def _text_span(record: DocumentRecord, *, section_start: int, text: str, cursor: int) -> TextSpan:
    """Builds a best-effort source span for one extracted text unit."""

    raw = str(record.raw_text or "")
    target = str(text or "").strip()
    if not target:
        return TextSpan(start=section_start, end=section_start)
    idx = raw.find(target, max(0, int(cursor)))
    if idx < 0:
        idx = raw.find(target, max(0, int(section_start)))
    if idx < 0:
        idx = max(0, int(section_start))
    return TextSpan(start=idx, end=idx + len(target))


def _split_text_windows(text: str, *, max_chars: int, overlap_chars: int) -> List[str]:
    """Splits a long text into overlapping windows."""

    src = str(text or "").strip()
    if not src:
        return []
    if len(src) <= max_chars:
        return [src]

    safe_max = max(80, int(max_chars or 0))
    safe_overlap = max(0, min(int(overlap_chars or 0), safe_max // 3))
    step = max(40, safe_max - safe_overlap)
    out: List[str] = []
    start = 0
    while start < len(src):
        end = min(len(src), start + safe_max)
        chunk = src[start:end].strip()
        if chunk:
            out.append(chunk)
        if end >= len(src):
            break
        start = end - safe_overlap
    return out


def _plan_section_units(
    *,
    record: DocumentRecord,
    section_text: str,
    section_start: int,
    section_span: TextSpan,
    max_section_chars: int,
    overlap_chars: int,
) -> List[Tuple[str, TextSpan, str]]:
    """Plans extraction units for one section."""

    src = str(section_text or "").strip()
    if not src:
        return []
    if len(src) <= max_section_chars:
        return [(src, section_span, "section")]

    blocks = _split_section_blocks(src) or [src]
    grouped_texts: List[str] = []
    current_blocks: List[str] = []
    current_size = 0
    for raw_block in blocks:
        block = str(raw_block or "").strip()
        if not block:
            continue
        if len(block) > max_section_chars:
            if current_blocks:
                grouped_texts.append("\n\n".join(current_blocks))
                current_blocks = []
                current_size = 0
            grouped_texts.extend(
                _split_text_windows(
                    block,
                    max_chars=max_section_chars,
                    overlap_chars=overlap_chars,
                )
            )
            continue
        projected = current_size + (2 if current_blocks else 0) + len(block)
        if current_blocks and projected > max_section_chars:
            grouped_texts.append("\n\n".join(current_blocks))
            current_blocks = [block]
            current_size = len(block)
            continue
        current_blocks.append(block)
        current_size = projected

    if current_blocks:
        grouped_texts.append("\n\n".join(current_blocks))

    units: List[Tuple[str, TextSpan, str]] = []
    cursor = int(section_start or 0)
    for text in grouped_texts or _split_text_windows(src, max_chars=max_section_chars, overlap_chars=overlap_chars):
        span = _text_span(record, section_start=section_start, text=text, cursor=cursor)
        cursor = int(span.end or cursor)
        units.append((text, span, "chunk"))
    return units


def _default_section_priority_terms() -> List[str]:
    """Returns normalized built-in terms for budget-aware section ordering."""

    return compact_text_list(list(_DEFAULT_SECTION_PRIORITY_TERMS), limit=64)


def _default_section_deprioritize_terms() -> List[str]:
    """Returns normalized built-in low-value section terms."""

    return compact_text_list(list(_DEFAULT_SECTION_DEPRIORITIZE_TERMS), limit=64)


def _section_priority_score(
    *,
    heading: str,
    text: str,
    priority_terms: List[str],
    deprioritize_terms: List[str],
) -> int:
    """Scores a section heading/body for budget-aware extraction ordering."""

    heading_text = normalize_text(str(heading or ""), lower=True)
    preview_text = normalize_text(str(text or "")[:600], lower=True)
    score = 0
    for term in priority_terms:
        token = normalize_text(term, lower=True)
        if not token:
            continue
        if token in heading_text:
            score += 6
        elif token in preview_text:
            score += 2
    for term in deprioritize_terms:
        token = normalize_text(term, lower=True)
        if not token:
            continue
        if token in heading_text:
            score -= 6
        elif token in preview_text:
            score -= 2
    return score


def _ordered_sections_for_budget(record: DocumentRecord, *, max_units_per_document: int) -> List[object]:
    """Reorders sections when a unit budget is active so higher-value sections go first."""

    sections = list(record.sections or [])
    if max_units_per_document <= 0 or not sections:
        return sections
    priority_terms = _default_section_priority_terms()
    deprioritize_terms = _default_section_deprioritize_terms()
    if not priority_terms and not deprioritize_terms:
        return sections
    ranked: List[Tuple[int, int, object]] = []
    for idx, section in enumerate(sections):
        score = _section_priority_score(
            heading=getattr(section, "heading", ""),
            text=getattr(section, "text", ""),
            priority_terms=priority_terms,
            deprioritize_terms=deprioritize_terms,
        )
        ranked.append((score, idx, section))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [section for _, _, section in ranked]


def _coerce_relation(value: str) -> SupportRelation:
    """Coerces a model relation label into a supported enum."""

    raw = str(value or "").strip().lower()
    if raw == SupportRelation.CONFLICT.value:
        return SupportRelation.CONFLICT
    if raw == SupportRelation.CONSTRAINT.value:
        return SupportRelation.CONSTRAINT
    if raw == SupportRelation.CASE_VARIANT.value:
        return SupportRelation.CASE_VARIANT
    return SupportRelation.SUPPORT


def _coerce_risk_class(value: str) -> str:
    """Normalizes the risk class label."""

    raw = str(value or "").strip().lower()
    return raw if raw in {"low", "medium", "high"} else "low"


def _objective_from_item(item: Dict[str, object], prompt: str, description: str) -> str:
    """Builds a single-goal objective with prompt fallback."""

    explicit = str(item.get("objective") or "").strip()
    if explicit:
        return explicit
    extracted = section_items_from_prompt(
        prompt,
        [
            "goal",
            "objective",
            "role & objective",
            "target",
            "目标",
            "目的",
        ],
    )
    if extracted:
        return str(extracted[0] or "").strip()
    return str(description or "").strip()


def _applicable_signals_from_item(item: Dict[str, object], prompt: str) -> List[str]:
    """Builds applicable client/context signals with prompt-based fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("applicable_signals")), limit=12)
    if explicit:
        return explicit
    planned = compact_text_list(coerce_str_list(item.get("use_when")), limit=12)
    if planned:
        return planned
    return section_items_from_prompt(
        prompt,
        [
            "applicable signals",
            "signals",
            "when to use",
            "indications",
            "适用信号",
            "适用情形",
            "使用时机",
        ],
    )


def _contraindications_from_item(item: Dict[str, object], prompt: str) -> List[str]:
    """Builds contraindications with prompt-based fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("contraindications")), limit=12)
    if explicit:
        return explicit
    planned = compact_text_list(coerce_str_list(item.get("do_not_use_when")), limit=12)
    if planned:
        return planned
    return section_items_from_prompt(
        prompt,
        [
            "contraindications",
            "do not use when",
            "avoid when",
            "not for",
            "禁忌",
            "不适用",
        ],
    )


def _intervention_moves_from_item(item: Dict[str, object], prompt: str) -> List[str]:
    """Builds therapist intervention moves with prompt-based fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("intervention_moves")), limit=12)
    if explicit:
        return explicit
    return section_items_from_prompt(
        prompt,
        [
            "intervention moves",
            "micro skills",
            "techniques",
            "response moves",
            "intervention",
            "干预动作",
            "微技能",
            "技术要点",
        ],
    )


def _workflow_steps_from_item(item: Dict[str, object], prompt: str) -> List[str]:
    """Builds workflow steps with prompt-based fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("workflow_steps")), limit=12)
    if explicit:
        return explicit
    return section_items_from_prompt(
        prompt,
        [
            "workflow",
            "core workflow",
            "step-by-step",
            "步骤",
            "流程",
            "核心流程",
        ],
    )


def _constraint_items_from_item(item: Dict[str, object], prompt: str) -> List[str]:
    """Builds constraint items with prompt-based fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("constraints")), limit=12)
    if explicit:
        return explicit
    return section_items_from_prompt(
        prompt,
        [
            "rules",
            "constraints",
            "rules & constraints",
            "约束",
            "规则",
            "限制",
        ],
    )


def _caution_items_from_item(item: Dict[str, object], prompt: str) -> List[str]:
    """Builds caution items with prompt-based fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("cautions")), limit=12)
    if explicit:
        return explicit
    return section_items_from_prompt(
        prompt,
        [
            "cautions",
            "anti-patterns",
            "warnings",
            "注意",
            "风险",
            "禁忌",
        ],
    )


def _output_contract_from_item(item: Dict[str, object], prompt: str) -> List[str]:
    """Builds output requirements with prompt-based fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("output_contract")), limit=12)
    if explicit:
        return explicit
    success_artifact = str(item.get("success_artifact") or "").strip()
    if success_artifact:
        return [success_artifact]
    return section_items_from_prompt(
        prompt,
        [
            "output",
            "output format",
            "deliverable",
            "输出",
            "输出格式",
            "交付",
        ],
    )


def _examples_from_item(item: Dict[str, object]) -> List[SkillExample]:
    """Builds short therapist-response examples from the model payload."""

    raw = item.get("examples")
    if raw is None:
        return []
    items = list(raw) if isinstance(raw, list) else [raw]
    out: List[SkillExample] = []
    for entry in items[:3]:
        if isinstance(entry, SkillExample):
            out.append(entry)
            continue
        if not isinstance(entry, dict):
            continue
        input_text = str(entry.get("input") or entry.get("client") or entry.get("scenario") or "").strip()
        output_text = str(entry.get("output") or entry.get("therapist") or "").strip()
        notes_text = str(entry.get("notes") or "").strip()
        if not input_text or not output_text:
            continue
        out.append(
            SkillExample(
                input=input_text,
                output=output_text,
                notes=notes_text or None,
            )
        )
    return out


def _triggers_from_item(item: Dict[str, object]) -> List[str]:
    """Builds routing triggers with planner-level fallback."""

    explicit = compact_text_list(coerce_str_list(item.get("triggers")), limit=5)
    if explicit:
        return explicit
    return compact_text_list(coerce_str_list(item.get("use_when")), limit=5)


def _draft_identity_seed(*, doc_id: str, section: str, name: str, prompt: str, unit_key: str = "") -> str:
    """Builds a stable UUID seed for one extracted draft."""

    normalized = "|".join(
        [
            str(doc_id or "").strip(),
            normalize_text(section, lower=True),
            normalize_text(name, lower=True),
            normalize_text(prompt, lower=True),
            normalize_text(unit_key, lower=True),
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"autoskill-document-draft:{normalized}"))


def _planned_skill_key(item: Dict[str, object]) -> str:
    """Builds a stable dedupe key for one planned/extracted skill item."""

    return "|".join(
        [
            normalize_text(str(item.get("name") or ""), lower=True),
            normalize_text(str(item.get("asset_type") or ""), lower=True),
            normalize_text(str(item.get("asset_node_id") or ""), lower=True),
            normalize_text(str(item.get("granularity") or ""), lower=True),
            normalize_text(str(item.get("objective") or ""), lower=True),
        ]
    )


def _skill_item_richness(item: Dict[str, object]) -> int:
    """Scores how complete one extracted skill payload looks."""

    score = 0
    for key in (
        "description",
        "prompt",
        "objective",
        "task_family",
        "method_family",
        "stage",
        "asset_type",
        "asset_node_id",
    ):
        if str(item.get(key) or "").strip():
            score += 2
    for key in (
        "workflow_steps",
        "constraints",
        "cautions",
        "output_contract",
        "triggers",
        "tags",
        "intervention_moves",
        "applicable_signals",
        "contraindications",
        "examples",
    ):
        value = item.get(key)
        if isinstance(value, list) and value:
            score += min(3, len(value))
    if item.get("resources"):
        score += 1
    if item.get("files"):
        score += 1
    return score


@dataclass
class SkillExtractionResult:
    """Output of the direct skill extraction stage."""

    documents: List[DocumentRecord] = field(default_factory=list)
    windows: List[StrictWindow] = field(default_factory=list)
    support_records: List[SupportRecord] = field(default_factory=list)
    skill_drafts: List[SkillDraft] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    extractor_name: str = "llm"


ExtractionProgressCallback = Optional[
    Callable[[DocumentRecord, List[SupportRecord], List[SkillDraft], SkillExtractionResult], None]
]


class DocumentSkillExtractor(Protocol):
    """Pluggable document-to-skill extractor interface."""

    def extract(
        self,
        *,
        documents: List[DocumentRecord],
        windows: Optional[List[StrictWindow]],
        logger: StageLogger,
        progress_callback: ExtractionProgressCallback = None,
        stage_progress_callback: StageProgressCallback = None,
        accumulate_result: bool = True,
    ) -> SkillExtractionResult:
        """Extracts support records and skill drafts from normalized documents."""


class LLMDocumentSkillExtractor:
    """Model-driven document-to-skill extractor."""

    def __init__(
        self,
        *,
        llm: Optional[LLM] = None,
        llm_config: Optional[Dict[str, object]] = None,
        max_section_chars: int = _DEFAULT_SECTION_CHARS,
        overlap_chars: int = _DEFAULT_CHUNK_OVERLAP_CHARS,
        max_candidates_per_unit: int = DEFAULT_MAX_CANDIDATES_PER_UNIT,
        max_units_per_document: int = 0,
        extract_workers: int = 1,
        extract_retries: int = _DEFAULT_EXTRACT_RETRIES,
        extract_retry_backoff_s: float = _DEFAULT_EXTRACT_RETRY_BACKOFF_S,
        llm_rate_limit_requests: int = _DEFAULT_LLM_RATE_LIMIT_REQUESTS,
        llm_rate_limit_window_s: float = _DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
        domain_type: str = "",
        skill_taxonomy_path: str = "",
        taxonomy: Optional[SkillTaxonomy] = None,
    ) -> None:
        self._llm_config = dict(llm_config or {})
        self.llm_rate_limit_requests = max(0, int(llm_rate_limit_requests or 0))
        self.llm_rate_limit_window_s = max(0.0, float(llm_rate_limit_window_s or 0.0))
        self._llm = maybe_wrap_llm_with_rate_limit(
            llm or build_llm(dict(self._llm_config or {"provider": "mock"})),
            max_requests=self.llm_rate_limit_requests,
            window_s=self.llm_rate_limit_window_s,
            llm_config=self._llm_config,
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
        self.max_section_chars = max(200, int(max_section_chars or _DEFAULT_SECTION_CHARS))
        self.overlap_chars = max(0, int(overlap_chars or 0))
        self.max_candidates_per_unit = max(1, int(max_candidates_per_unit or DEFAULT_MAX_CANDIDATES_PER_UNIT))
        self.max_units_per_document = max(0, int(max_units_per_document or 0))
        self.extract_workers = max(1, int(extract_workers or 1))
        self.extract_retries = max(0, int(extract_retries or 0))
        self.extract_retry_backoff_s = max(0.0, float(extract_retry_backoff_s or 0.0))
        self.taxonomy = taxonomy or load_skill_taxonomy(
            domain_type=str(domain_type or "").strip(),
            taxonomy_path=str(skill_taxonomy_path or "").strip(),
        )

    def _clone_llm(self) -> LLM:
        """Builds one worker-local LLM instance for document-level parallel extraction."""

        if self._llm_config:
            return maybe_wrap_llm_with_rate_limit(
                build_llm(dict(self._llm_config)),
                max_requests=self.llm_rate_limit_requests,
                window_s=self.llm_rate_limit_window_s,
                llm_config=self._llm_config,
                scope=AUTOSKILL4DOC_LLM_SCOPE,
            )
        source_llm = self._llm.base_llm if isinstance(self._llm, RateLimitedLLM) else self._llm
        try:
            cloned = copy.deepcopy(source_llm)
        except Exception as exc:
            raise ValueError(
                "extract_workers>1 requires llm_config or a deepcopy-compatible llm instance"
            ) from exc
        return maybe_wrap_llm_with_rate_limit(
            cloned,
            max_requests=self.llm_rate_limit_requests,
            window_s=self.llm_rate_limit_window_s,
            llm_config=self._llm_config,
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )

    def _spawn_worker_extractor(self) -> "LLMDocumentSkillExtractor":
        """Creates one worker-local extractor so concurrent documents do not share one LLM client."""

        return LLMDocumentSkillExtractor(
            llm=self._clone_llm(),
            max_section_chars=self.max_section_chars,
            overlap_chars=self.overlap_chars,
            max_candidates_per_unit=self.max_candidates_per_unit,
            max_units_per_document=self.max_units_per_document,
            extract_workers=1,
            extract_retries=self.extract_retries,
            extract_retry_backoff_s=self.extract_retry_backoff_s,
            llm_rate_limit_requests=self.llm_rate_limit_requests,
            llm_rate_limit_window_s=self.llm_rate_limit_window_s,
            taxonomy=self.taxonomy,
        )

    def _build_unit_payload(
        self,
        *,
        record: DocumentRecord,
        section_heading: str,
        section_level: int,
        span: TextSpan,
        unit_text: str,
        unit_type: str,
        unit_metadata: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        unit_md = dict(unit_metadata or {})
        return {
            "document": {
                "doc_id": record.doc_id,
                "title": record.title,
                "domain": record.domain,
                "source_type": record.source_type,
                "authors": list(record.authors or []),
                "year": record.year,
                "metadata": dict(record.metadata or {}),
            },
            "section": {
                "heading": section_heading,
                "level": section_level,
                "span": span.to_dict(),
                "unit_type": unit_type,
                "heading_path": list(unit_md.get("heading_path") or []),
                "parent_heading": str(unit_md.get("parent_heading") or "").strip(),
                "sibling_headings": list(unit_md.get("sibling_headings") or []),
                "subsection_headings": list(unit_md.get("subsection_headings") or []),
                "context_snippets": list(unit_md.get("context_snippets") or []),
                "heading_number": str(unit_md.get("heading_number") or "").strip(),
                "heading_kind": str(unit_md.get("heading_kind") or "").strip(),
                "section_summary": str(unit_md.get("section_summary") or "").strip(),
            },
            "excerpt": str(unit_text or "").strip(),
            "max_candidates": self.max_candidates_per_unit,
            "taxonomy": self.taxonomy.to_dict(),
        }

    def _complete_extract_json(
        self,
        *,
        payload: Dict[str, object],
        kind: str,
        repair_kind: str,
        max_candidates: int,
        record: DocumentRecord,
        section_heading: str,
        logger: StageLogger = None,
    ) -> object:
        """Runs one LLM extraction step with retries and repair."""

        system = maybe_offline_prompt(
            channel=OFFLINE_CHANNEL_DOC,
            kind=kind,
            max_candidates=max_candidates,
            taxonomy=self.taxonomy,
        )
        repair_system = maybe_offline_prompt(
            channel=OFFLINE_CHANNEL_DOC,
            kind=repair_kind,
            max_candidates=max_candidates,
            taxonomy=self.taxonomy,
        )
        repaired_payload = (
            f"DATA:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            f"DRAFT:\n__DRAFT__"
        )
        parsed: object = None
        last_exc: Optional[Exception] = None
        for attempt in range(max(0, self.extract_retries) + 1):
            try:
                parsed = llm_complete_json(
                    llm=self._llm,
                    system=system,
                    payload=payload,
                    repair_system=repair_system,
                    repair_payload=repaired_payload,
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= self.extract_retries or not _is_retryable_extract_error(exc):
                    raise
                delay = _retry_backoff_seconds(attempt=attempt, base_delay_s=self.extract_retry_backoff_s)
                emit_stage_log(
                    logger,
                    (
                        f"[extract_skills] retry {kind} doc={record.doc_id} section={section_heading} "
                        f"attempt={attempt + 1}/{self.extract_retries + 1} delay_s={delay:.2f} error={exc}"
                    ),
                )
                if delay > 0.0:
                    time.sleep(delay)
        if last_exc is not None and parsed is None:
            raise last_exc
        return parsed

    def _plan_unit_skills(
        self,
        *,
        payload: Dict[str, object],
        record: DocumentRecord,
        section_heading: str,
        logger: StageLogger = None,
    ) -> List[Dict[str, object]]:
        """Plans how many distinct skills one window should expand into."""

        parsed = self._complete_extract_json(
            payload=payload,
            kind="extract_plan",
            repair_kind="extract_plan_repair",
            max_candidates=self.max_candidates_per_unit,
            record=record,
            section_heading=section_heading,
            logger=logger,
        )
        obj = maybe_json_dict(parsed)
        raw_skills = obj.get("skills") if isinstance(obj.get("skills"), list) else parsed
        if not isinstance(raw_skills, list):
            return []
        out: List[Dict[str, object]] = []
        for idx, item in enumerate(raw_skills[: self.max_candidates_per_unit], start=1):
            if not isinstance(item, dict):
                continue
            planned = maybe_json_dict(item)
            if not str(planned.get("name") or "").strip():
                continue
            slot_value = planned.get("slot")
            try:
                slot = int(slot_value or idx)
            except Exception:
                slot = idx
            planned["slot"] = max(1, slot)
            out.append(planned)
        return out

    def _expand_planned_skill(
        self,
        *,
        payload: Dict[str, object],
        planned_skill: Dict[str, object],
        record: DocumentRecord,
        section_heading: str,
        logger: StageLogger = None,
    ) -> Dict[str, object]:
        """Expands one planned skill into a detailed skill payload."""

        expand_payload = dict(payload)
        expand_payload["candidate"] = dict(planned_skill or {})
        parsed = self._complete_extract_json(
            payload=expand_payload,
            kind="extract_expand",
            repair_kind="extract_expand_repair",
            max_candidates=1,
            record=record,
            section_heading=section_heading,
            logger=logger,
        )
        obj = maybe_json_dict(parsed)
        if isinstance(obj.get("skill"), dict):
            return maybe_json_dict(obj.get("skill"))
        if obj.get("skill") is None:
            return {}
        raw_skills = obj.get("skills")
        if isinstance(raw_skills, list) and raw_skills:
            return maybe_json_dict(raw_skills[0])
        if obj:
            return obj
        return {}

    def _dedupe_unit_skills(self, items: List[Dict[str, object]]) -> List[Dict[str, object]]:
        """Keeps the strongest local skill when planner/expander emit near-duplicates."""

        best_by_key: Dict[str, Dict[str, object]] = {}
        order: List[str] = []
        for item in list(items or []):
            current = maybe_json_dict(item)
            if not str(current.get("name") or "").strip():
                continue
            key = _planned_skill_key(current)
            if not key:
                key = str(uuid.uuid4())
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = current
                order.append(key)
                continue
            if _skill_item_richness(current) > _skill_item_richness(existing):
                best_by_key[key] = current
        return [best_by_key[key] for key in order if key in best_by_key]

    def _extract_unit_skills(
        self,
        *,
        record: DocumentRecord,
        section_heading: str,
        section_level: int,
        span: TextSpan,
        unit_text: str,
        unit_type: str,
        unit_metadata: Optional[Dict[str, object]] = None,
        logger: StageLogger = None,
    ) -> List[Dict[str, object]]:
        payload = self._build_unit_payload(
            record=record,
            section_heading=section_heading,
            section_level=section_level,
            span=span,
            unit_text=unit_text,
            unit_type=unit_type,
            unit_metadata=unit_metadata,
        )
        planned = self._plan_unit_skills(
            payload=payload,
            record=record,
            section_heading=section_heading,
            logger=logger,
        )
        if not planned:
            return []
        expanded_items: List[Dict[str, object]] = []
        for planned_skill in planned[: self.max_candidates_per_unit]:
            expanded = self._expand_planned_skill(
                payload=payload,
                planned_skill=planned_skill,
                record=record,
                section_heading=section_heading,
                logger=logger,
            )
            merged = dict(planned_skill)
            merged.update(maybe_json_dict(expanded))
            if not str(merged.get("name") or "").strip():
                continue
            expanded_items.append(merged)
        return self._dedupe_unit_skills(expanded_items)

    def _build_support_and_draft(
        self,
        *,
        record: DocumentRecord,
        section_heading: str,
        span: TextSpan,
        unit_text: str,
        unit_type: str,
        item: Dict[str, object],
        unit_metadata: Optional[Dict[str, object]] = None,
    ) -> Tuple[Optional[SupportRecord], Optional[SkillDraft]]:
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        prompt = str(item.get("prompt") or item.get("skill_body") or "").strip()
        if not name or not description or not prompt:
            return None, None

        objective = _objective_from_item(item, prompt, description)
        applicable_signals = _applicable_signals_from_item(item, prompt)
        contraindications = _contraindications_from_item(item, prompt)
        intervention_moves = _intervention_moves_from_item(item, prompt)
        workflow_steps = _workflow_steps_from_item(item, prompt)
        constraints = _constraint_items_from_item(item, prompt)
        cautions = _caution_items_from_item(item, prompt)
        output_contract = _output_contract_from_item(item, prompt)
        examples = _examples_from_item(item)
        if not workflow_steps and not intervention_moves and not constraints and not cautions:
            return None, None

        support_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"autoskill-document-support:{record.doc_id}:{section_heading}:{span.start}:{span.end}:{name}:{normalize_text(unit_text, lower=True)}",
            )
        )
        tags = compact_text_list(coerce_str_list(item.get("tags")), limit=6)
        triggers = _triggers_from_item(item)
        raw_asset_type = str(item.get("asset_type") or "").strip()
        asset_type = self.taxonomy.strict_normalize_asset_type(raw_asset_type)
        if raw_asset_type and not asset_type:
            return None, None
        asset_node = self.taxonomy.resolve_asset_node(
            requested=item.get("asset_node_id"),
            asset_type=asset_type,
            metadata=dict(item),
        )
        asset_node_id = str(getattr(asset_node, "node_id", "") or "").strip()
        asset_path = self.taxonomy.asset_path(asset_node_id)
        asset_level = int(getattr(asset_node, "level", 0) or 0)
        visible_role = str(getattr(asset_node, "visible_role", "") or "").strip()
        draft = SkillDraft(
            draft_id=_draft_identity_seed(
                doc_id=record.doc_id,
                section=section_heading,
                name=name,
                prompt=prompt,
                unit_key=f"{unit_type}:{int(span.start or 0)}:{int(span.end or 0)}",
            ),
            doc_id=record.doc_id,
            name=name,
            description=description,
            asset_type=asset_type,
            granularity=str(item.get("granularity") or "").strip(),
            asset_node_id=asset_node_id,
            asset_path=asset_path,
            asset_level=asset_level,
            visible_role=visible_role,
            hierarchy_status="unresolved",
            objective=objective,
            domain=str(item.get("domain") or record.domain or "").strip(),
            task_family=str(item.get("task_family") or "").strip(),
            method_family=str(item.get("method_family") or "").strip(),
            stage=str(item.get("stage") or "").strip(),
            applicable_signals=applicable_signals,
            contraindications=contraindications,
            intervention_moves=intervention_moves,
            workflow_steps=workflow_steps,
            triggers=triggers,
            constraints=constraints,
            cautions=cautions,
            output_contract=output_contract,
            examples=examples,
            risk_class=_coerce_risk_class(str(item.get("risk_class") or "")),
            confidence=clip_confidence(item.get("confidence"), default=0.75),
            support_ids=[support_id],
            metadata={
                "prompt": prompt,
                "tags": tags,
                "files": maybe_json_dict(item.get("files")),
                "resources": maybe_json_dict(item.get("resources")),
                "source_sections": [section_heading],
                "extraction_unit": unit_type,
                "domain_type": self.taxonomy.domain_type,
                "taxonomy_id": self.taxonomy.taxonomy_id,
                "asset_node_id": asset_node_id,
                "asset_path": asset_path,
                "asset_level": asset_level,
                "visible_role": visible_role,
                "candidate_slot": int(item.get("slot") or 0) if str(item.get("slot") or "").strip() else 0,
                **dict(unit_metadata or {}),
            },
        )
        relation_type = _coerce_relation(str(item.get("relation_type") or "support"))
        support = SupportRecord(
            support_id=support_id,
            doc_id=record.doc_id,
            source_file=str((record.metadata or {}).get("source_file") or ""),
            section=section_heading,
            span=span,
            excerpt=str(unit_text or "").strip(),
            relation_type=relation_type,
            confidence=clip_confidence(item.get("confidence"), default=0.75),
            metadata={
                "document_title": record.title,
                "domain": record.domain,
                "extraction_unit": unit_type,
                "skill_name": name,
                "asset_type": draft.asset_type,
                "granularity": draft.granularity,
                "asset_node_id": asset_node_id,
                "asset_path": asset_path,
                "asset_level": asset_level,
                "visible_role": visible_role,
                "objective": draft.objective,
                "task_family": draft.task_family,
                "method_family": draft.method_family,
                "stage": draft.stage,
                "domain_type": self.taxonomy.domain_type,
                "taxonomy_id": self.taxonomy.taxonomy_id,
                "candidate_slot": int(item.get("slot") or 0) if str(item.get("slot") or "").strip() else 0,
                **dict(unit_metadata or {}),
            },
        )
        return support, draft

    def _extract_from_windows(
        self,
        *,
        record: DocumentRecord,
        windows: List[StrictWindow],
        logger: StageLogger = None,
        stage_progress_callback: StageProgressCallback = None,
    ) -> Tuple[List[SupportRecord], List[SkillDraft]]:
        supports: List[SupportRecord] = []
        drafts: List[SkillDraft] = []
        active_windows = list(windows or [])
        if self.max_units_per_document > 0:
            active_windows = active_windows[: self.max_units_per_document]
        total_windows = len(active_windows)
        for idx, window in enumerate(active_windows, start=1):
            raw_skills = self._extract_unit_skills(
                record=record,
                section_heading=window.section_heading,
                section_level=window.section_level,
                span=window.span,
                unit_text=window.text,
                unit_type="window",
                unit_metadata=dict(window.metadata or {}),
                logger=logger,
            )
            for item in raw_skills:
                support, draft = self._build_support_and_draft(
                    record=record,
                    section_heading=window.section_heading,
                    span=window.span,
                    unit_text=window.text,
                    unit_type="window",
                    item=item,
                    unit_metadata={
                        "window_id": window.window_id,
                        "window_strategy": window.strategy,
                        "anchor_hits": list(window.anchor_hits or []),
                        "paragraph_start": window.paragraph_start,
                        "paragraph_end": window.paragraph_end,
                        "heading_path": list((window.metadata or {}).get("heading_path") or []),
                        "parent_heading": str((window.metadata or {}).get("parent_heading") or "").strip(),
                        "sibling_headings": list((window.metadata or {}).get("sibling_headings") or []),
                        "subsection_headings": list((window.metadata or {}).get("subsection_headings") or []),
                        "context_snippets": list((window.metadata or {}).get("context_snippets") or []),
                        "heading_number": str((window.metadata or {}).get("heading_number") or "").strip(),
                        "heading_kind": str((window.metadata or {}).get("heading_kind") or "").strip(),
                        "section_summary": str((window.metadata or {}).get("section_summary") or "").strip(),
                    },
                )
                if support is None or draft is None:
                    continue
                supports.append(support)
                drafts.append(draft)
            emit_stage_progress(
                stage_progress_callback,
                {
                    "stage": "extract",
                    "kind": "window_progress",
                    "doc_id": str(record.doc_id or "").strip(),
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "completed_windows": idx,
                    "total_windows": total_windows,
                    "total_support_records": len(supports),
                    "total_skill_drafts": len(drafts),
                    "window_id": str(window.window_id or "").strip(),
                    "section_heading": str(window.section_heading or "").strip(),
                },
            )
        deduped_supports = {support.support_id: support for support in supports}
        deduped_drafts = {draft.draft_id: draft for draft in drafts}
        return list(deduped_supports.values()), list(deduped_drafts.values())

    def _extract_from_document(
        self,
        record: DocumentRecord,
        *,
        logger: StageLogger = None,
        stage_progress_callback: StageProgressCallback = None,
    ) -> Tuple[List[SupportRecord], List[SkillDraft]]:
        supports: List[SupportRecord] = []
        drafts: List[SkillDraft] = []
        units_seen = 0
        ordered_sections = _ordered_sections_for_budget(
            record,
            max_units_per_document=self.max_units_per_document,
        )
        planned_units: List[Tuple[object, str, TextSpan, str]] = []
        for section in ordered_sections:
            section_text = str(section.text or "").strip()
            if not section_text:
                continue
            extraction_units = _plan_section_units(
                record=record,
                section_text=section_text,
                section_start=int(section.span.start or 0),
                section_span=section.span,
                max_section_chars=self.max_section_chars,
                overlap_chars=self.overlap_chars,
            )
            for unit_text, span, unit_type in extraction_units:
                if self.max_units_per_document > 0 and units_seen >= self.max_units_per_document:
                    break
                units_seen += 1
                planned_units.append((section, unit_text, span, unit_type))
            if self.max_units_per_document > 0 and units_seen >= self.max_units_per_document:
                break

        total_units = len(planned_units)
        for idx, (section, unit_text, span, unit_type) in enumerate(planned_units, start=1):
            raw_skills = self._extract_unit_skills(
                record=record,
                section_heading=section.heading,
                section_level=section.level,
                span=span,
                unit_text=unit_text,
                unit_type=unit_type,
                logger=logger,
            )
            for item in raw_skills:
                support, draft = self._build_support_and_draft(
                    record=record,
                    section_heading=section.heading,
                    span=span,
                    unit_text=unit_text,
                    unit_type=unit_type,
                    item=item,
                )
                if support is None or draft is None:
                    continue
                supports.append(support)
                drafts.append(draft)
            emit_stage_progress(
                stage_progress_callback,
                {
                    "stage": "extract",
                    "kind": "window_progress",
                    "doc_id": str(record.doc_id or "").strip(),
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "completed_windows": idx,
                    "total_windows": total_units,
                    "total_support_records": len(supports),
                    "total_skill_drafts": len(drafts),
                    "window_id": "",
                    "section_heading": str(section.heading or "").strip(),
                },
            )

        deduped_supports = {support.support_id: support for support in supports}
        deduped_drafts = {draft.draft_id: draft for draft in drafts}
        return list(deduped_supports.values()), list(deduped_drafts.values())

    def _extract_document(
        self,
        *,
        record: DocumentRecord,
        doc_windows: List[StrictWindow],
        logger: StageLogger = None,
        stage_progress_callback: StageProgressCallback = None,
    ) -> Tuple[List[SupportRecord], List[SkillDraft]]:
        """Extracts one document using one extractor instance."""

        if doc_windows:
            return self._extract_from_windows(
                record=record,
                windows=doc_windows,
                logger=logger,
                stage_progress_callback=stage_progress_callback,
            )
        return self._extract_from_document(
            record,
            logger=logger,
            stage_progress_callback=stage_progress_callback,
        )

    def _extract_document_with_retries(
        self,
        *,
        record: DocumentRecord,
        doc_windows: List[StrictWindow],
        logger: StageLogger = None,
        stage_progress_callback: StageProgressCallback = None,
    ) -> Tuple[List[SupportRecord], List[SkillDraft]]:
        """Retries one document extraction when provider overload causes transient failures."""

        last_exc: Optional[Exception] = None
        for attempt in range(max(0, self.extract_retries) + 1):
            try:
                return self._extract_document(
                    record=record,
                    doc_windows=doc_windows,
                    logger=logger,
                    stage_progress_callback=stage_progress_callback,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= self.extract_retries or not _is_retryable_extract_error(exc):
                    raise
                delay = _retry_backoff_seconds(attempt=attempt, base_delay_s=self.extract_retry_backoff_s)
                emit_stage_log(
                    logger,
                    (
                        f"[extract_skills] retry document doc={record.doc_id} "
                        f"attempt={attempt + 1}/{self.extract_retries + 1} delay_s={delay:.2f} error={exc}"
                    ),
                )
                if delay > 0.0:
                    time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        return [], []

    def extract(
        self,
        *,
        documents: List[DocumentRecord],
        windows: Optional[List[StrictWindow]],
        logger: StageLogger,
        progress_callback: ExtractionProgressCallback = None,
        stage_progress_callback: StageProgressCallback = None,
        accumulate_result: bool = True,
    ) -> SkillExtractionResult:
        result = SkillExtractionResult(
            documents=list(documents or []) if accumulate_result else [],
            windows=list(windows or []) if accumulate_result else [],
            extractor_name="llm",
        )
        windows_by_doc: Dict[str, List[StrictWindow]] = {}
        for window in list(windows or []):
            doc_id = str(window.doc_id or "").strip()
            if doc_id:
                windows_by_doc.setdefault(doc_id, []).append(window)

        def _commit_success(record: DocumentRecord, doc_windows: List[StrictWindow], supports: List[SupportRecord], drafts: List[SkillDraft]) -> None:
            if accumulate_result:
                result.support_records.extend(supports)
                result.skill_drafts.extend(drafts)
            if progress_callback is not None:
                progress_callback(record, list(supports or []), list(drafts or []), result)
            emit_stage_progress(
                stage_progress_callback,
                {
                    "stage": "extract",
                    "kind": "document_done",
                    "doc_id": str(record.doc_id or "").strip(),
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "total_windows": len(doc_windows),
                    "supports": len(supports),
                    "drafts": len(drafts),
                    "total_support_records": len(list(result.support_records or [])),
                    "total_skill_drafts": len(list(result.skill_drafts or [])),
                    "errors": len(list(result.errors or [])),
                },
            )
            emit_stage_log(
                logger,
                f"[extract_skills] done {document_progress_label(doc_id=record.doc_id, title=record.title, source_file=str((record.metadata or {}).get('source_file') or ''))} windows={len(doc_windows)} supports={len(supports)} drafts={len(drafts)} names={summarize_names([draft.name for draft in drafts])}",
            )

        def _commit_error(record: DocumentRecord, error: Exception) -> None:
            result.errors.append(
                {
                    "doc_id": record.doc_id,
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "error": str(error),
                    "retryable": bool(_is_retryable_extract_error(error)),
                    "stage": "extract",
                }
            )
            emit_stage_progress(
                stage_progress_callback,
                {
                    "stage": "extract",
                    "kind": "document_failed",
                    "doc_id": str(record.doc_id or "").strip(),
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "error": str(error),
                    "retryable": bool(_is_retryable_extract_error(error)),
                    "errors": len(list(result.errors or [])),
                },
            )
            emit_stage_log(logger, f"[extract_skills] error doc={record.doc_id}: {error}")

        doc_items = [
            (
                idx,
                record,
                list(windows_by_doc.get(str(record.doc_id or "").strip(), [])),
            )
            for idx, record in enumerate(list(documents or []))
        ]
        total_documents = len(doc_items)
        if self.extract_workers <= 1 or len(doc_items) <= 1:
            for idx, record, doc_windows in doc_items:
                emit_stage_progress(
                    stage_progress_callback,
                    {
                        "stage": "extract",
                        "kind": "document_start",
                        "document_index": idx + 1,
                        "total_documents": total_documents,
                        "doc_id": str(record.doc_id or "").strip(),
                        "title": str(record.title or "").strip(),
                        "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                        "total_windows": len(doc_windows),
                    },
                )
                emit_stage_log(
                    logger,
                    f"[extract_skills] start {document_progress_label(doc_id=record.doc_id, title=record.title, source_file=str((record.metadata or {}).get('source_file') or ''))}",
                )
                try:
                    supports, drafts = self._extract_document_with_retries(
                        record=record,
                        doc_windows=doc_windows,
                        logger=logger,
                        stage_progress_callback=stage_progress_callback,
                    )
                    _commit_success(record, doc_windows, supports, drafts)
                except Exception as e:
                    _commit_error(record, e)
            return result

        for idx, record, doc_windows in doc_items:
            emit_stage_progress(
                stage_progress_callback,
                {
                    "stage": "extract",
                    "kind": "document_start",
                    "document_index": idx + 1,
                    "total_documents": total_documents,
                    "doc_id": str(record.doc_id or "").strip(),
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "total_windows": len(doc_windows),
                },
            )
            emit_stage_log(
                logger,
                f"[extract_skills] start {document_progress_label(doc_id=record.doc_id, title=record.title, source_file=str((record.metadata or {}).get('source_file') or ''))}",
            )

        max_workers = max(1, min(int(self.extract_workers or 1), len(doc_items)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    self._spawn_worker_extractor()._extract_document_with_retries,
                    record=record,
                    doc_windows=doc_windows,
                    logger=logger,
                    stage_progress_callback=stage_progress_callback,
                ): (idx, record, doc_windows)
                for idx, record, doc_windows in doc_items
            }
            for future in as_completed(future_map):
                _, record, doc_windows = future_map[future]
                try:
                    supports_ready, drafts_ready = future.result()
                    _commit_success(record, doc_windows, list(supports_ready or []), list(drafts_ready or []))
                except Exception as exc:
                    if _is_retryable_extract_error(exc):
                        try:
                            emit_stage_log(
                                logger,
                                f"[extract_skills] fallback sequential retry doc={record.doc_id} error={exc}",
                            )
                            supports_ready, drafts_ready = self._extract_document_with_retries(
                                record=record,
                                doc_windows=doc_windows,
                                logger=logger,
                                stage_progress_callback=stage_progress_callback,
                            )
                            _commit_success(record, doc_windows, list(supports_ready or []), list(drafts_ready or []))
                        except Exception as fallback_exc:
                            _commit_error(record, fallback_exc)
                    else:
                        _commit_error(record, exc)
        return result


HeuristicDocumentSkillExtractor = LLMDocumentSkillExtractor


def build_document_skill_extractor(
    kind: str = "llm",
    *,
    llm: Optional[LLM] = None,
    llm_config: Optional[Dict[str, object]] = None,
    max_section_chars: int = _DEFAULT_SECTION_CHARS,
    overlap_chars: int = _DEFAULT_CHUNK_OVERLAP_CHARS,
    max_candidates_per_unit: int = DEFAULT_MAX_CANDIDATES_PER_UNIT,
    max_units_per_document: int = 0,
    extract_workers: int = 1,
    extract_retries: int = _DEFAULT_EXTRACT_RETRIES,
    extract_retry_backoff_s: float = _DEFAULT_EXTRACT_RETRY_BACKOFF_S,
    llm_rate_limit_requests: int = _DEFAULT_LLM_RATE_LIMIT_REQUESTS,
    llm_rate_limit_window_s: float = _DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
    domain_type: str = "",
    skill_taxonomy_path: str = "",
    taxonomy: Optional[SkillTaxonomy] = None,
) -> DocumentSkillExtractor:
    """Builds a concrete document-to-skill extractor implementation."""

    name = str(kind or "").strip().lower() or "llm"
    if name in {"llm", "heuristic", "stub", "rule-based", "rule_based"}:
        return LLMDocumentSkillExtractor(
            llm=llm,
            llm_config=llm_config,
            max_section_chars=max_section_chars,
            overlap_chars=overlap_chars,
            max_candidates_per_unit=max_candidates_per_unit,
            max_units_per_document=max_units_per_document,
            extract_workers=extract_workers,
            extract_retries=extract_retries,
            extract_retry_backoff_s=extract_retry_backoff_s,
            llm_rate_limit_requests=llm_rate_limit_requests,
            llm_rate_limit_window_s=llm_rate_limit_window_s,
            domain_type=domain_type,
            skill_taxonomy_path=skill_taxonomy_path,
            taxonomy=taxonomy,
        )
    raise ValueError(f"unsupported document skill extractor: {kind}")


def extract_skills(
    *,
    documents: List[DocumentRecord],
    windows: Optional[List[StrictWindow]] = None,
    extractor: DocumentSkillExtractor | None = None,
    logger: StageLogger = None,
    progress_callback: ExtractionProgressCallback = None,
    stage_progress_callback: StageProgressCallback = None,
    accumulate_result: bool = True,
) -> SkillExtractionResult:
    """Public functional wrapper for the direct skill extraction stage."""

    impl = extractor or LLMDocumentSkillExtractor()
    return impl.extract(
        documents=list(documents or []),
        windows=list(windows or []),
        logger=logger,
        progress_callback=progress_callback,
        stage_progress_callback=stage_progress_callback,
        accumulate_result=accumulate_result,
    )
