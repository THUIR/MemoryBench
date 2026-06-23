"""
Hybrid retrieval helpers for document-skill maintenance.

This module reuses AutoSkill's low-level embedding + BM25 ranking primitives, but
builds a document-pipeline-specific retrieval text that includes execution
metadata such as asset layer, domain type, family, stage, and workflow fields.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence

from autoskill.embeddings.base import EmbeddingModel
from autoskill.embeddings.factory import build_embeddings
from autoskill.management.stores.hybrid_rank import blend_scores, tokenize_for_bm25

from ..core.common import dedupe_strings, normalize_text
from ..core.config import DEFAULT_RETRIEVAL_SCORE_THRESHOLD
from ..models import SkillSpec
from .layout import retrieval_cache_path

DEFAULT_RETRIEVAL_LIMIT = 2
DEFAULT_BM25_WEIGHT = 0.1
_RETRIEVAL_CACHE_SCHEMA = "autoskill.document_skill_retrieval.v2"


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Returns a cosine-ready dot product for normalized vectors."""

    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(float(x) * float(y) for x, y in zip(a, b)))


def _text_hash(text: str) -> str:
    """Builds a stable hash for one retrieval text payload."""

    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _config_signature(config: Dict[str, Any]) -> str:
    """Builds a stable signature for one embedding config payload."""

    raw = json.dumps(dict(config or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _granularity_rank(value: str) -> int:
    """Maps granularity labels into a stable coarse-to-fine rank."""

    raw = str(value or "").strip().lower()
    if raw == "macro":
        return 0
    if raw == "micro":
        return 2
    return 1


def _metadata_value(skill: SkillSpec, key: str) -> str:
    """Reads one string metadata field from a skill spec."""

    return str((skill.metadata or {}).get(key) or "").strip()


def _family_name(skill: SkillSpec) -> str:
    """Returns the normalized family label for one skill."""

    return _metadata_value(skill, "family_name") or _metadata_value(skill, "school_name")


def _domain_type(skill: SkillSpec) -> str:
    """Returns the configured domain type for one skill."""

    return _metadata_value(skill, "domain_type")


def _taxonomy_id(skill: SkillSpec) -> str:
    """Returns the taxonomy id for one skill."""

    return _metadata_value(skill, "taxonomy_id")


def _profile_id(skill: SkillSpec) -> str:
    """Returns the configured profile id for one skill."""

    return _metadata_value(skill, "profile_id")


def _asset_node_id(skill: SkillSpec) -> str:
    """Returns the configured hierarchical asset node id for one skill."""

    return str(getattr(skill, "asset_node_id", "") or _metadata_value(skill, "asset_node_id")).strip()


def _similarity_gate(
    candidate: SkillSpec,
    other: SkillSpec,
    *,
    score: float,
    threshold: float,
) -> bool:
    """Applies a lightweight semantic gate on top of the blended retrieval score."""

    if float(score or 0.0) < float(threshold or DEFAULT_RETRIEVAL_SCORE_THRESHOLD):
        return False
    if (
        str(candidate.asset_type or "").strip() == str(other.asset_type or "").strip()
        and str(candidate.granularity or "").strip() == str(other.granularity or "").strip()
    ):
        return True
    candidate_node = _asset_node_id(candidate)
    other_node = _asset_node_id(other)
    if candidate_node and other_node and candidate_node == other_node:
        return True
    for field in ("task_family", "method_family", "stage"):
        left = normalize_text(getattr(candidate, field, ""), lower=True)
        right = normalize_text(getattr(other, field, ""), lower=True)
        if left and right and left == right:
            return True
    candidate_tokens = {
        token
        for token in normalize_text(f"{candidate.name} {candidate.objective}", lower=True).split()
        if token
    }
    other_tokens = {
        token
        for token in normalize_text(f"{other.name} {other.objective}", lower=True).split()
        if token
    }
    return len(candidate_tokens & other_tokens) >= 2


def _bm25_scores_from_tokens(
    query: str,
    docs: Dict[str, Sequence[str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> Dict[str, float]:
    """Computes normalized BM25 scores from pre-tokenized docs."""

    if not docs:
        return {}

    q_terms = tokenize_for_bm25(query)
    if not q_terms:
        return {str(doc_id): 0.0 for doc_id in docs.keys()}

    q_tf = Counter(q_terms)
    doc_tf: Dict[str, Counter[str]] = {}
    doc_len: Dict[str, int] = {}
    df: Counter[str] = Counter()

    for doc_id, tokens in docs.items():
        did = str(doc_id)
        tf = Counter([str(token or "").strip().lower() for token in list(tokens or []) if str(token or "").strip()])
        doc_tf[did] = tf
        doc_len[did] = sum(tf.values())
        for term in tf.keys():
            df[term] += 1

    n_docs = max(1, len(doc_tf))
    avgdl = (sum(doc_len.values()) / float(n_docs)) if n_docs > 0 else 1.0
    if avgdl <= 0:
        avgdl = 1.0

    raw: Dict[str, float] = {}
    for did, tf in doc_tf.items():
        dl = max(1, int(doc_len.get(did, 0)))
        score = 0.0
        for term, qf in q_tf.items():
            f = int(tf.get(term, 0))
            if f <= 0:
                continue
            n_qi = int(df.get(term, 0))
            idf = math.log(1.0 + ((n_docs - n_qi + 0.5) / (n_qi + 0.5)))
            denom = f + float(k1) * (1.0 - float(b) + float(b) * (dl / avgdl))
            if denom <= 0:
                continue
            score += float(qf) * idf * ((f * (float(k1) + 1.0)) / denom)
        raw[did] = float(score)

    max_score = max(raw.values()) if raw else 0.0
    if max_score <= 0:
        return {did: 0.0 for did in doc_tf.keys()}
    return {did: max(0.0, float(score) / float(max_score)) for did, score in raw.items()}


def skill_retrieval_text(skill: SkillSpec) -> str:
    """Builds one retrieval text that includes execution fields plus metadata."""

    family_name = _family_name(skill)
    lines: List[str] = [
        f"Name: {str(skill.name or '').strip()}",
        f"Description: {str(skill.description or '').strip()}",
        f"Objective: {str(skill.objective or '').strip()}",
        f"Asset Type: {str(skill.asset_type or '').strip()}",
        f"Granularity: {str(skill.granularity or '').strip()}",
        f"Asset Node: {_asset_node_id(skill)}",
        f"Asset Path: {str(getattr(skill, 'asset_path', '') or _metadata_value(skill, 'asset_path')).strip()}",
        f"Asset Level: {str(getattr(skill, 'asset_level', 0) or 0)}",
        f"Domain: {str(skill.domain or '').strip()}",
        f"Domain Type: {_domain_type(skill)}",
        f"Taxonomy ID: {_taxonomy_id(skill)}",
        f"Profile ID: {_profile_id(skill)}",
        f"Family: {family_name}",
        f"Task Family: {str(skill.task_family or '').strip()}",
        f"Method Family: {str(skill.method_family or '').strip()}",
        f"Stage: {str(skill.stage or '').strip()}",
    ]

    def add_block(title: str, values: Iterable[str]) -> None:
        items = dedupe_strings([str(value or "").strip() for value in values if str(value or "").strip()])
        if not items:
            return
        lines.append(f"{title}: {' | '.join(items)}")

    add_block("Applicable Signals", list(skill.applicable_signals or []))
    add_block("Contraindications", list(skill.contraindications or []))
    add_block("Intervention Moves", list(skill.intervention_moves or []))
    add_block("Workflow Steps", list(skill.workflow_steps or []))
    add_block("Constraints", list(skill.constraints or []))
    add_block("Cautions", list(skill.cautions or []))
    add_block("Output Contract", list(skill.output_contract or []))
    add_block("Triggers", list(skill.triggers or []))
    add_block("Tags", list(skill.tags or []))
    return "\n".join(line for line in lines if str(line or "").strip()).strip()


@dataclass(frozen=True)
class SkillRetrievalHit:
    """One ranked similar-skill hit returned by the document retriever."""

    skill: SkillSpec
    score: float
    vector_score: float
    bm25_score: float


class DocumentSkillRetriever:
    """Mutable hybrid retriever used by AutoSkill4Doc version maintenance."""

    def __init__(
        self,
        *,
        embeddings: Optional[EmbeddingModel],
        bm25_weight: float = DEFAULT_BM25_WEIGHT,
        cache_path: str = "",
        embeddings_signature: str = "",
        score_threshold: float = DEFAULT_RETRIEVAL_SCORE_THRESHOLD,
    ) -> None:
        self._embeddings = embeddings
        self._bm25_weight = float(bm25_weight)
        self._cache_path = os.path.abspath(os.path.expanduser(str(cache_path or "").strip())) if str(cache_path or "").strip() else ""
        self._embeddings_signature = str(embeddings_signature or "").strip()
        self._score_threshold = max(0.0, float(score_threshold or DEFAULT_RETRIEVAL_SCORE_THRESHOLD))
        self._skills: Dict[str, SkillSpec] = {}
        self._texts: Dict[str, str] = {}
        self._tokens: Dict[str, List[str]] = {}
        self._vectors: Dict[str, List[float]] = {}
        self._vectors_available = embeddings is not None and not bool(getattr(embeddings, "disabled", False))
        self._load_cache()

    def _load_cache(self) -> None:
        """Loads persisted retrieval texts/vectors/token index from disk."""

        if not self._cache_path or not os.path.isfile(self._cache_path):
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return
        if not isinstance(payload, dict) or str(payload.get("schema") or "").strip() != _RETRIEVAL_CACHE_SCHEMA:
            return
        cached_signature = str(payload.get("embeddings_signature") or "").strip()
        vectors_compatible = bool(cached_signature) and cached_signature == self._embeddings_signature
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return
        for skill_id, item in entries.items():
            if not isinstance(item, dict):
                continue
            skill_id_s = str(skill_id or "").strip()
            text = str(item.get("text") or "").strip()
            if skill_id_s and text:
                self._texts[skill_id_s] = text
            tokens = item.get("tokens")
            if skill_id_s and isinstance(tokens, list):
                self._tokens[skill_id_s] = [str(token or "").strip().lower() for token in tokens if str(token or "").strip()]
            vector = item.get("vector")
            if vectors_compatible and skill_id_s and isinstance(vector, list):
                vec = [float(x) for x in list(vector or []) if x is not None]
                if vec:
                    self._vectors[skill_id_s] = vec

    def _write_cache(self) -> None:
        """Persists retrieval texts/vectors/token index to disk."""

        if not self._cache_path:
            return
        payload = {
            "schema": _RETRIEVAL_CACHE_SCHEMA,
            "embeddings_signature": self._embeddings_signature,
            "entries": {
                skill_id: {
                    "text": self._texts.get(skill_id, ""),
                    "text_hash": _text_hash(self._texts.get(skill_id, "")),
                    "tokens": list(self._tokens.get(skill_id, []) or []),
                    "vector": list(self._vectors.get(skill_id, []) or []),
                }
                for skill_id in sorted(set(list(self._texts.keys()) + list(self._vectors.keys()) + list(self._tokens.keys())))
                if str(skill_id or "").strip()
            },
        }
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)

    def refresh(self, skills: Sequence[SkillSpec]) -> None:
        """Rebuilds the retriever corpus from a skill sequence."""

        self._skills = {}
        previous_texts = dict(self._texts)
        previous_tokens = dict(self._tokens)
        previous_vectors = dict(self._vectors)
        self._texts = {}
        self._tokens = {}
        self._vectors = {}
        ordered_ids: List[str] = []
        texts_to_embed: List[str] = []
        ids_to_embed: List[str] = []
        for skill in list(skills or []):
            skill_id = str(skill.skill_id or "").strip()
            if not skill_id:
                continue
            self._skills[skill_id] = skill
            text = skill_retrieval_text(skill)
            self._texts[skill_id] = text
            self._tokens[skill_id] = previous_tokens.get(skill_id) or tokenize_for_bm25(text)
            cached_text = previous_texts.get(skill_id, "")
            if cached_text and _text_hash(cached_text) == _text_hash(text) and previous_vectors.get(skill_id):
                self._vectors[skill_id] = list(previous_vectors.get(skill_id) or [])
            elif self._vectors_available:
                ids_to_embed.append(skill_id)
                texts_to_embed.append(text)
            ordered_ids.append(skill_id)

        if self._vectors_available and texts_to_embed:
            try:
                embedded = self._embeddings.embed(texts_to_embed)
                for skill_id, vec in zip(ids_to_embed, embedded):
                    values = [float(x) for x in list(vec or []) if x is not None]
                    if values:
                        self._vectors[skill_id] = values
            except Exception:
                self._vectors_available = False
                self._vectors = {skill_id: vec for skill_id, vec in self._vectors.items() if vec}
        if not self._vectors_available:
            self._vectors = {}
        if ordered_ids:
            self._write_cache()
        if not self._vectors_available or not ordered_ids:
            return

    def upsert(self, skill: SkillSpec) -> None:
        """Adds or replaces one skill in the retrieval corpus."""

        skill_id = str(skill.skill_id or "").strip()
        if not skill_id:
            return
        self._skills[skill_id] = skill
        text = skill_retrieval_text(skill)
        self._texts[skill_id] = text
        self._tokens[skill_id] = tokenize_for_bm25(text)
        if not self._vectors_available:
            self._write_cache()
            return
        try:
            embedded = self._embeddings.embed([text])[0]
            self._vectors[skill_id] = [float(x) for x in list(embedded or [])]
        except Exception:
            self._vectors_available = False
            self._vectors = {}
        self._write_cache()

    def remove(self, skill_id: str) -> None:
        """Removes one skill from the retrieval corpus."""

        skill_id_s = str(skill_id or "").strip()
        if not skill_id_s:
            return
        self._skills.pop(skill_id_s, None)
        self._texts.pop(skill_id_s, None)
        self._tokens.pop(skill_id_s, None)
        self._vectors.pop(skill_id_s, None)
        self._write_cache()

    def search(
        self,
        candidate: SkillSpec,
        *,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        exclude_ids: Optional[Iterable[str]] = None,
    ) -> List[SkillRetrievalHit]:
        """Returns top-k similar skills from the current corpus."""

        excluded = {str(item or "").strip() for item in list(exclude_ids or []) if str(item or "").strip()}
        pool: List[SkillSpec] = []
        candidate_domain = normalize_text(candidate.domain, lower=True)
        candidate_domain_type = normalize_text(_domain_type(candidate), lower=True)
        candidate_taxonomy_id = normalize_text(_taxonomy_id(candidate), lower=True)
        candidate_profile_id = normalize_text(_profile_id(candidate), lower=True)
        candidate_family = normalize_text(_family_name(candidate), lower=True)
        candidate_node = normalize_text(_asset_node_id(candidate), lower=True)

        for skill in self._skills.values():
            skill_id = str(skill.skill_id or "").strip()
            if not skill_id or skill_id in excluded:
                continue
            skill_domain = normalize_text(skill.domain, lower=True)
            if candidate_domain and skill_domain and skill_domain != candidate_domain:
                continue
            skill_domain_type = normalize_text(_domain_type(skill), lower=True)
            if candidate_domain_type and skill_domain_type and skill_domain_type != candidate_domain_type:
                continue
            skill_taxonomy_id = normalize_text(_taxonomy_id(skill), lower=True)
            if candidate_taxonomy_id and skill_taxonomy_id and skill_taxonomy_id != candidate_taxonomy_id:
                continue
            skill_profile_id = normalize_text(_profile_id(skill), lower=True)
            if candidate_profile_id and skill_profile_id and skill_profile_id != candidate_profile_id:
                continue
            skill_family = normalize_text(_family_name(skill), lower=True)
            if candidate_family and skill_family and skill_family != candidate_family:
                continue
            skill_node = normalize_text(_asset_node_id(skill), lower=True)
            if candidate_node and skill_node and skill_node != candidate_node:
                if _granularity_rank(skill.granularity) >= _granularity_rank(candidate.granularity):
                    continue
            pool.append(skill)

        if not pool:
            return []

        query = skill_retrieval_text(candidate)
        docs = {
            skill.skill_id: self._tokens.get(skill.skill_id) or tokenize_for_bm25(self._texts.get(skill.skill_id) or skill_retrieval_text(skill))
            for skill in pool
        }
        bm25_scores = _bm25_scores_from_tokens(query=query, docs=docs)

        vector_scores: Dict[str, float] = {}
        use_vector = False
        if self._vectors_available:
            try:
                qvec = self._embeddings.embed([query])[0]
                qvec = [float(x) for x in list(qvec or [])]
                use_vector = bool(qvec)
            except Exception:
                use_vector = False
                qvec = []
            if use_vector:
                for skill in pool:
                    skill_id = str(skill.skill_id or "").strip()
                    vec = self._vectors.get(skill_id)
                    if not vec:
                        continue
                    vector_scores[skill_id] = _dot(qvec, vec)

        merged = blend_scores(
            vector_scores=vector_scores,
            bm25_scores=bm25_scores,
            bm25_weight=self._bm25_weight,
            use_vector=use_vector,
        )
        def boosted_score(item: SkillSpec) -> float:
            score = float(merged.get(item.skill_id, 0.0))
            if (
                str(item.asset_type or "").strip() == str(candidate.asset_type or "").strip()
                and str(item.granularity or "").strip() == str(candidate.granularity or "").strip()
            ):
                score += 0.15
            if _asset_node_id(item) and _asset_node_id(item) == _asset_node_id(candidate):
                score += 0.15
            elif _granularity_rank(item.granularity) < _granularity_rank(candidate.granularity):
                # Keep broader parent skills available for split detection.
                score += 0.05
            return max(0.0, min(1.0, score))

        ranked = sorted(pool, key=boosted_score, reverse=True)
        hits: List[SkillRetrievalHit] = []
        for skill in ranked[: max(1, int(limit or DEFAULT_RETRIEVAL_LIMIT))]:
            skill_id = str(skill.skill_id or "").strip()
            score = float(boosted_score(skill))
            if not _similarity_gate(candidate, skill, score=score, threshold=self._score_threshold):
                continue
            hits.append(
                SkillRetrievalHit(
                    skill=skill,
                    score=score,
                    vector_score=float(vector_scores.get(skill_id, 0.0)),
                    bm25_score=float(bm25_scores.get(skill_id, 0.0)),
                )
            )
        return hits

    def search_parents(
        self,
        candidate: SkillSpec,
        *,
        allowed_parent_nodes: Optional[Iterable[str]] = None,
        limit: int = 5,
        exclude_ids: Optional[Iterable[str]] = None,
    ) -> List[SkillRetrievalHit]:
        """Returns top-k broader parent candidates for one child skill."""

        excluded = {str(item or "").strip() for item in list(exclude_ids or []) if str(item or "").strip()}
        allowed_nodes = {
            normalize_text(str(item or "").strip(), lower=True)
            for item in list(allowed_parent_nodes or [])
            if str(item or "").strip()
        }
        target_level = max(1, int(getattr(candidate, "asset_level", 0) or 0) - 1)
        pool: List[SkillSpec] = []
        candidate_domain = normalize_text(candidate.domain, lower=True)
        candidate_domain_type = normalize_text(_domain_type(candidate), lower=True)
        candidate_taxonomy_id = normalize_text(_taxonomy_id(candidate), lower=True)
        candidate_profile_id = normalize_text(_profile_id(candidate), lower=True)
        candidate_family = normalize_text(_family_name(candidate), lower=True)

        for skill in self._skills.values():
            skill_id = str(skill.skill_id or "").strip()
            if not skill_id or skill_id in excluded:
                continue
            if max(1, int(getattr(skill, "asset_level", 0) or 0)) != target_level:
                continue
            skill_node = normalize_text(_asset_node_id(skill), lower=True)
            if allowed_nodes and skill_node not in allowed_nodes:
                continue
            skill_domain = normalize_text(skill.domain, lower=True)
            if candidate_domain and skill_domain and skill_domain != candidate_domain:
                continue
            skill_domain_type = normalize_text(_domain_type(skill), lower=True)
            if candidate_domain_type and skill_domain_type and skill_domain_type != candidate_domain_type:
                continue
            skill_taxonomy_id = normalize_text(_taxonomy_id(skill), lower=True)
            if candidate_taxonomy_id and skill_taxonomy_id and skill_taxonomy_id != candidate_taxonomy_id:
                continue
            skill_profile_id = normalize_text(_profile_id(skill), lower=True)
            if candidate_profile_id and skill_profile_id and skill_profile_id != candidate_profile_id:
                continue
            skill_family = normalize_text(_family_name(skill), lower=True)
            if candidate_family and skill_family and skill_family != candidate_family:
                continue
            pool.append(skill)

        if not pool:
            return []

        query = skill_retrieval_text(candidate)
        docs = {
            skill.skill_id: self._tokens.get(skill.skill_id) or tokenize_for_bm25(self._texts.get(skill.skill_id) or skill_retrieval_text(skill))
            for skill in pool
        }
        bm25_scores = _bm25_scores_from_tokens(query=query, docs=docs)

        vector_scores: Dict[str, float] = {}
        use_vector = False
        if self._vectors_available:
            try:
                qvec = self._embeddings.embed([query])[0]
                qvec = [float(x) for x in list(qvec or [])]
                use_vector = bool(qvec)
            except Exception:
                use_vector = False
                qvec = []
            if use_vector:
                for skill in pool:
                    skill_id = str(skill.skill_id or "").strip()
                    vec = self._vectors.get(skill_id)
                    if not vec:
                        continue
                    vector_scores[skill_id] = _dot(qvec, vec)

        merged = blend_scores(
            vector_scores=vector_scores,
            bm25_scores=bm25_scores,
            bm25_weight=self._bm25_weight,
            use_vector=use_vector,
        )
        ranked = sorted(pool, key=lambda item: float(merged.get(item.skill_id, 0.0)), reverse=True)
        hits: List[SkillRetrievalHit] = []
        for skill in ranked[: max(1, int(limit or 5))]:
            skill_id = str(skill.skill_id or "").strip()
            score = max(0.0, min(1.0, float(merged.get(skill_id, 0.0))))
            if not _similarity_gate(candidate, skill, score=score, threshold=self._score_threshold):
                continue
            hits.append(
                SkillRetrievalHit(
                    skill=skill,
                    score=score,
                    vector_score=float(vector_scores.get(skill_id, 0.0)),
                    bm25_score=float(bm25_scores.get(skill_id, 0.0)),
                )
            )
        return hits


def build_document_skill_retriever(
    *,
    embeddings_config: Optional[Dict[str, Any]] = None,
    bm25_weight: float = DEFAULT_BM25_WEIGHT,
    score_threshold: float = DEFAULT_RETRIEVAL_SCORE_THRESHOLD,
    base_store_root: str = "",
    cache_path: str = "",
) -> DocumentSkillRetriever:
    """Builds the document retriever from one embedding config."""

    config = dict(embeddings_config or {})
    if not config:
        config = {"provider": "hashing", "dims": 256}
    embeddings = build_embeddings(config)
    resolved_cache_path = str(cache_path or "").strip() or retrieval_cache_path(base_store_root)
    return DocumentSkillRetriever(
        embeddings=embeddings,
        bm25_weight=bm25_weight,
        cache_path=resolved_cache_path,
        embeddings_signature=_config_signature(config),
        score_threshold=score_threshold,
    )
