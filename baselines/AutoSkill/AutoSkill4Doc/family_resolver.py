"""Family resolution for taxonomy-constrained document extraction."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional, Sequence

from autoskill.llm.base import LLM
from autoskill.llm.factory import build_llm

from .core.common import dedupe_strings, normalize_text
from .core.llm_utils import clip_confidence, llm_complete_json, maybe_json_dict
from .core.rate_limit import AUTOSKILL4DOC_LLM_SCOPE, maybe_wrap_llm_with_rate_limit
from .models import DocumentRecord
from .taxonomy import SkillTaxonomy


def _normalize_text_match(requested: str, aliases: Sequence[str]) -> bool:
    """Checks whether one requested family label matches any configured alias."""

    raw = normalize_text(requested, lower=True)
    if not raw:
        return False
    return raw in {normalize_text(alias, lower=True) for alias in aliases if str(alias or "").strip()}


@dataclass
class DocumentFamilyResolution:
    """One resolved family assignment for the current batch of documents."""

    family_id: str = ""
    family_name: str = ""
    confidence: float = 0.0
    source: str = "default"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Returns a JSON-safe summary."""

        return {
            "family_id": self.family_id,
            "family_name": self.family_name,
            "confidence": float(self.confidence or 0.0),
            "source": self.source,
            "reason": self.reason,
        }


class DocumentFamilyResolver:
    """Resolves one family bucket for a document batch using rules first, then one LLM pass."""

    def __init__(self, *, taxonomy: SkillTaxonomy, llm: Optional[LLM] = None) -> None:
        self.taxonomy = taxonomy
        self.llm = llm

    def resolve(
        self,
        *,
        documents: Sequence[DocumentRecord],
        metadata: Optional[Dict[str, Any]] = None,
        allow_llm: bool = True,
    ) -> DocumentFamilyResolution:
        """Resolves one family for the current batch."""

        md = dict(metadata or {})
        explicit = self.taxonomy.ensure_configured_family_candidate(metadata=md)
        if explicit is not None:
            return DocumentFamilyResolution(
                family_id=str(explicit.get("id") or "").strip(),
                family_name=str(explicit.get("visible_name") or explicit.get("name") or "").strip(),
                confidence=1.0,
                source="manual",
                reason="explicit family matched configured candidate",
            )

        if not self.taxonomy.family_candidates:
            for raw_manual in (
                str(md.get("family_name") or "").strip(),
                str(md.get("school_name") or "").strip(),
            ):
                if raw_manual:
                    return DocumentFamilyResolution(
                        family_id="",
                        family_name=raw_manual,
                        confidence=1.0,
                        source="manual",
                        reason="explicit family kept as provided",
                    )

        candidates = [dict(item) for item in list(self.taxonomy.family_candidates or []) if isinstance(item, dict)]
        if not candidates:
            return DocumentFamilyResolution(
                family_id="",
                family_name=str(self.taxonomy.default_family_name or "").strip(),
                confidence=0.5,
                source="default",
                reason="taxonomy has no constrained family candidates",
            )
        if len(candidates) == 1:
            item = candidates[0]
            return DocumentFamilyResolution(
                family_id=str(item.get("id") or "").strip(),
                family_name=str(item.get("visible_name") or item.get("name") or "").strip(),
                confidence=0.9,
                source="single_candidate",
                reason="taxonomy exposes exactly one family candidate",
            )

        rule_match = self._resolve_by_rules(documents=documents, candidates=candidates)
        if rule_match is not None:
            return rule_match

        if allow_llm:
            llm_match = self._resolve_by_llm(documents=documents, candidates=candidates)
            if llm_match is not None:
                return llm_match

        fallback = self._default_family_candidate(candidates=candidates)
        fallback_name = str((fallback or {}).get("visible_name") or (fallback or {}).get("name") or self.taxonomy.default_family_name or "").strip()
        if not fallback_name:
            fallback = candidates[0]
            fallback_name = str(fallback.get("visible_name") or fallback.get("name") or "").strip()
        return DocumentFamilyResolution(
            family_id=str((fallback or {}).get("id") or "").strip(),
            family_name=fallback_name,
            confidence=0.25,
            source="default",
            reason="no confident rule or LLM family match; fallback to taxonomy default family",
        )

    def _default_family_candidate(self, *, candidates: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Returns the configured default family candidate when it exists."""

        requested = str(self.taxonomy.default_family_name or "").strip()
        if not requested:
            return None
        for item in list(candidates or []):
            aliases = [
                str(item.get("id") or "").strip(),
                str(item.get("name") or "").strip(),
                str(item.get("visible_name") or "").strip(),
                *list(item.get("aliases") or []),
            ]
            if _normalize_text_match(requested, aliases):
                return dict(item)
        return None

    def _resolve_by_rules(
        self,
        *,
        documents: Sequence[DocumentRecord],
        candidates: Sequence[Dict[str, Any]],
    ) -> Optional[DocumentFamilyResolution]:
        """Scores configured candidates by aliases and keywords across the batch."""

        title_text = normalize_text(
            "\n".join(str(doc.title or "").strip() for doc in list(documents or []) if str(doc.title or "").strip()),
            lower=True,
        )
        heading_text = normalize_text(
            "\n".join(
                str(section.heading or "").strip()
                for doc in list(documents or [])
                for section in list(doc.sections or [])[:16]
                if str(section.heading or "").strip()
            ),
            lower=True,
        )
        preview_text = normalize_text(
            "\n".join(
                str(section.text or "").strip()[:220]
                for doc in list(documents or [])
                for section in list(doc.sections or [])[:6]
                if str(section.text or "").strip()
            )
            or "\n".join(str(doc.raw_text or "").strip()[:600] for doc in list(documents or []) if str(doc.raw_text or "").strip()),
            lower=True,
        )
        if not (title_text or heading_text or preview_text):
            return None

        scored: List[tuple[float, Dict[str, Any], List[str]]] = []
        for item in list(candidates or []):
            matched_terms: List[str] = []
            score = 0.0
            aliases = dedupe_strings(
                [
                    str(item.get("id") or "").strip(),
                    str(item.get("name") or "").strip(),
                    *list(item.get("aliases") or []),
                ],
                lower=False,
            )
            keywords = dedupe_strings(list(item.get("keywords") or []), lower=False)
            for alias in aliases:
                term = normalize_text(alias, lower=True)
                if not term:
                    continue
                if term in title_text:
                    score += 4.0
                    matched_terms.append(alias)
                elif term in heading_text:
                    score += 3.0
                    matched_terms.append(alias)
                elif term in preview_text:
                    score += 2.0
                    matched_terms.append(alias)
            for keyword in keywords:
                term = normalize_text(keyword, lower=True)
                if not term:
                    continue
                if term in heading_text:
                    score += 1.5
                    matched_terms.append(keyword)
                elif term in preview_text:
                    score += 1.0
                    matched_terms.append(keyword)
            if score > 0.0:
                scored.append((score, item, dedupe_strings(matched_terms, lower=False)))

        if not scored:
            return None
        scored.sort(key=lambda value: (-value[0], str(value[1].get("name") or "").lower()))
        top_score, top_item, matched_terms = scored[0]
        second_score = float(scored[1][0]) if len(scored) > 1 else 0.0
        if top_score < 2.0 or top_score < second_score + 1.0:
            return None
        return DocumentFamilyResolution(
            family_id=str(top_item.get("id") or "").strip(),
            family_name=str(top_item.get("visible_name") or top_item.get("name") or "").strip(),
            confidence=min(0.95, 0.55 + top_score / 10.0),
            source="rule",
            reason=f"matched family aliases/keywords: {', '.join(matched_terms[:6])}",
        )

    def _resolve_by_llm(
        self,
        *,
        documents: Sequence[DocumentRecord],
        candidates: Sequence[Dict[str, Any]],
    ) -> Optional[DocumentFamilyResolution]:
        """Runs one constrained LLM family classification pass for the batch."""

        if self.llm is None:
            return None
        doc_summaries = []
        for doc in list(documents or [])[:8]:
            headings = [
                str(section.heading or "").strip()
                for section in list(doc.sections or [])[:12]
                if str(section.heading or "").strip()
            ]
            previews = [
                str(section.text or "").strip()[:180]
                for section in list(doc.sections or [])[:4]
                if str(section.text or "").strip()
            ]
            doc_summaries.append(
                {
                    "title": str(doc.title or "").strip(),
                    "headings": headings,
                    "previews": previews,
                }
            )
        payload = {
            "domain_type": self.taxonomy.domain_type,
            "documents": doc_summaries,
            "family_candidates": [
                {
                    "id": str(item.get("id") or "").strip(),
                    "name": str(item.get("visible_name") or item.get("name") or "").strip(),
                    "aliases": list(item.get("aliases") or []),
                    "keywords": list(item.get("keywords") or []),
                }
                for item in list(candidates or [])
            ],
        }
        system = (
            "You are AutoSkill4Doc's constrained family classifier.\n"
            "Task: select the single best family candidate for this document batch.\n"
            "Rules:\n"
            "- Choose ONLY one family_id from family_candidates.\n"
            "- Do not invent new family names.\n"
            "- Prefer explicit modality terminology, headings, and method cues over vague topical similarity.\n"
            "- Family is a routing container for a dominant framework, not a symptom/topic tag.\n"
            "- Do not choose a family only because the document is generally about the same domain.\n"
            "- Do not choose a family only because the case topic or diagnosis matches a family keyword.\n"
            "- Use aliases/keywords as clues, but resolve conflicts by the dominant therapeutic method or framework described across the batch.\n"
            "- If the evidence is weak, still pick the closest configured family but lower confidence substantially.\n"
            "Return ONLY strict JSON:\n"
            "{\n"
            '  "family_id": "candidate-id",\n'
            '  "confidence": 0.0,\n'
            '  "reason": "short reason"\n'
            "}\n"
        )
        repair_system = (
            "You are a JSON fixer for AutoSkill4Doc family classification.\n"
            "Return ONLY strict JSON with fields family_id, confidence, reason.\n"
        )
        repaired_payload = f"DATA:\n{json.dumps(payload, ensure_ascii=False)}\n\nDRAFT:\n__DRAFT__"
        try:
            parsed = llm_complete_json(
                llm=self.llm,
                system=system,
                payload=payload,
                repair_system=repair_system,
                repair_payload=repaired_payload,
            )
        except Exception:
            return None
        obj = maybe_json_dict(parsed)
        family_id = str(obj.get("family_id") or "").strip()
        if not family_id:
            return None
        chosen = next((item for item in list(candidates or []) if str(item.get("id") or "").strip() == family_id), None)
        if chosen is None:
            return None
        return DocumentFamilyResolution(
            family_id=family_id,
            family_name=str(chosen.get("visible_name") or chosen.get("name") or "").strip(),
            confidence=clip_confidence(obj.get("confidence"), default=0.55),
            source="llm",
            reason=str(obj.get("reason") or "").strip() or "llm family classification",
        )


def build_document_family_resolver(
    *,
    taxonomy: SkillTaxonomy,
    llm: Optional[LLM] = None,
    llm_config: Optional[Dict[str, Any]] = None,
    llm_rate_limit_requests: int = 0,
    llm_rate_limit_window_s: float = 300.0,
) -> DocumentFamilyResolver:
    """Builds the default constrained family resolver."""

    effective_llm = llm
    if effective_llm is None and isinstance(llm_config, dict) and llm_config:
        effective_llm = build_llm(dict(llm_config or {}))
    effective_llm = maybe_wrap_llm_with_rate_limit(
        effective_llm,
        max_requests=llm_rate_limit_requests,
        window_s=llm_rate_limit_window_s,
        llm_config=llm_config,
        scope=AUTOSKILL4DOC_LLM_SCOPE,
    )
    return DocumentFamilyResolver(taxonomy=taxonomy, llm=effective_llm)
