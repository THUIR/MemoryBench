"""
InMemorySkillStore: an in-memory “vector database”.

Key points:
- on upsert: embed skill text and store (skill, vector)
- on search: embed query text and rank by dot product (≈ cosine similarity)
- good for demos/single-machine; not suitable for multi-process or large-scale datasets
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ...embeddings.base import EmbeddingModel
from ...models import Skill, SkillHit, SkillStatus
from ...utils.skill_resources import extract_skill_resource_paths
from ..identity import identity_desc_norm_from_fields, normalize_identity_text
from .hybrid_rank import blend_scores, bm25_normalized_scores
from .base import SkillStore

_USAGE_DUP_WINDOW_MS = 10 * 60 * 1000


def _cosine(a: List[float], b: List[float]) -> float:
    # Assumes vectors are normalized; dot product can be used as cosine similarity.
    """Run cosine."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def _skill_to_text(skill: Skill) -> str:
    # Use structured fields to keep vectors stable across versions/ids and avoid
    # coupling similarity to artifact frontmatter formatting.
    # `examples` are intentionally excluded to avoid duplicated/noisy indexing signals.
    """Run skill to text."""
    triggers = "\n".join(skill.triggers or [])
    tags = " ".join(skill.tags or [])
    resource_paths = extract_skill_resource_paths(skill, max_items=32)
    resources = "\n".join(resource_paths)
    return (
        f"Name: {skill.name}\n"
        f"Description: {skill.description}\n"
        f"Instructions: {skill.instructions}\n"
        f"Triggers:\n{triggers}\n"
        f"Tags: {tags}\n"
        f"Resources:\n{resources}\n"
    )


@dataclass
class _Record:
    skill: Skill
    vector: Optional[List[float]]
    raw: Optional[Dict[str, Any]] = None


class InMemorySkillStore(SkillStore):
    def __init__(self, *, embeddings: EmbeddingModel, bm25_weight: float = 0.1) -> None:
        """Run init."""
        self._embeddings = embeddings
        self._embedding_disabled = bool(getattr(embeddings, "disabled", False))
        self._bm25_weight = float(bm25_weight)
        if self._bm25_weight < 0.0:
            self._bm25_weight = 0.0
        if self._bm25_weight > 1.0:
            self._bm25_weight = 1.0
        self._lock = threading.RLock()
        self._records: Dict[str, _Record] = {}
        self._bm25_docs_by_id: Dict[str, str] = {}
        self._usage_stats_by_user: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def upsert(self, skill: Skill, *, raw: Optional[Dict[str, Any]] = None) -> None:
        """Run upsert."""
        vector: Optional[List[float]] = None
        if not self._embedding_disabled:
            text = _skill_to_text(skill)
            try:
                vector = [float(x) for x in self._embeddings.embed([text])[0]]
            except Exception:
                vector = None
        with self._lock:
            self._records[skill.id] = _Record(skill=skill, vector=vector, raw=raw)
            self._bm25_docs_by_id[str(skill.id)] = _skill_to_text(skill)
            uid = str(getattr(skill, "user_id", "") or "").strip()
            sid = str(getattr(skill, "id", "") or "").strip()
            if uid and sid:
                bucket = self._usage_stats_by_user.setdefault(uid, {})
                row = bucket.get(sid)
                if not isinstance(row, dict):
                    key = _usage_identity_key(skill)
                    src_sid = _find_orphan_usage_row(bucket=bucket, identity_key=key, exclude_skill_id=sid)
                    if src_sid:
                        prev = bucket.pop(src_sid, {})
                        row = dict(prev) if isinstance(prev, dict) else {}
                        row["name"] = str(getattr(skill, "name", "") or "")
                        row["description"] = str(getattr(skill, "description", "") or "")
                        row["identity_desc_norm"] = key
                        row["orphaned"] = False
                        row["last_migrated_from_skill_id"] = str(src_sid)
                        bucket[sid] = row
                    else:
                        row = {
                            "retrieved": 0,
                            "relevant": 0,
                            "used": 0,
                            "name": str(getattr(skill, "name", "") or ""),
                            "description": str(getattr(skill, "description", "") or ""),
                            "identity_desc_norm": key,
                            "orphaned": False,
                            "last_retrieved_at": 0,
                            "last_relevant_at": 0,
                            "last_used_at": 0,
                            "last_query_key": "",
                            "last_query_at": 0,
                            "recent_query_ts": {},
                        }
                        bucket[sid] = row
                else:
                    row["name"] = str(getattr(skill, "name", "") or "")
                    row["description"] = str(getattr(skill, "description", "") or "")
                    row["identity_desc_norm"] = _usage_identity_key(skill)
                    row["orphaned"] = False

    def get(self, skill_id: str) -> Optional[Skill]:
        """Run get."""
        with self._lock:
            rec = self._records.get(skill_id)
            return rec.skill if rec else None

    def delete(self, skill_id: str) -> bool:
        """Run delete."""
        with self._lock:
            rec = self._records.pop(skill_id, None)
            removed = rec is not None
            self._bm25_docs_by_id.pop(str(skill_id), None)
            if rec is not None:
                uid = str(getattr(rec.skill, "user_id", "") or "").strip()
                if uid:
                    bucket = self._usage_stats_by_user.get(uid)
                    if isinstance(bucket, dict):
                        sid = str(skill_id or "").strip()
                        row = bucket.get(sid)
                        if isinstance(row, dict):
                            row["orphaned"] = True
                            row["last_deleted_at"] = int(time.time() * 1000)
                        if not bucket:
                            self._usage_stats_by_user.pop(uid, None)
            return removed

    def record_skill_usage_judgments(
        self,
        *,
        user_id: str,
        judgments: List[Dict[str, Any]],
        prune_min_retrieved: int = 0,
        prune_max_used: int = 0,
    ) -> Dict[str, Any]:
        """Records in-memory usage counters and optionally prunes stale skills."""

        uid = str(user_id or "").strip()
        if not uid:
            return {"updated": 0, "deleted_skill_ids": [], "stats": {}}
        min_retrieved = max(0, int(prune_min_retrieved or 0))
        max_used = max(0, int(prune_max_used or 0))
        now_ms = int(time.time() * 1000)
        updated = 0
        touched: List[str] = []
        with self._lock:
            bucket = self._usage_stats_by_user.setdefault(uid, {})
            for item in list(judgments or []):
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("id") or item.get("skill_id") or "").strip()
                if not sid:
                    continue
                rec = self._records.get(sid)
                if rec is None or str(getattr(rec.skill, "user_id", "") or "").strip() != uid:
                    continue
                row = bucket.get(sid)
                if not isinstance(row, dict):
                    row = {
                        "retrieved": 0,
                        "relevant": 0,
                        "used": 0,
                        "name": str(getattr(rec.skill, "name", "") or ""),
                        "description": str(getattr(rec.skill, "description", "") or ""),
                        "last_retrieved_at": 0,
                        "last_relevant_at": 0,
                        "last_used_at": 0,
                        "last_query_key": "",
                        "last_query_at": 0,
                        "recent_query_ts": {},
                    }
                    bucket[sid] = row
                qkey = str(item.get("query_key") or "").strip()
                recent_raw = row.get("recent_query_ts")
                recent_map: Dict[str, int] = {}
                if isinstance(recent_raw, dict):
                    for k, v in recent_raw.items():
                        kk = str(k or "").strip()
                        if not kk:
                            continue
                        try:
                            vv = int(v or 0)
                        except Exception:
                            vv = 0
                        if vv > 0:
                            recent_map[kk] = vv
                cutoff = now_ms - _USAGE_DUP_WINDOW_MS
                recent_map = {k: v for k, v in recent_map.items() if int(v) >= cutoff}
                duplicate_query = bool(
                    qkey
                    and (qkey in recent_map)
                    and int(recent_map.get(qkey, 0)) > 0
                    and (now_ms - int(recent_map.get(qkey, 0))) <= _USAGE_DUP_WINDOW_MS
                )
                if not duplicate_query:
                    row["retrieved"] = int(row.get("retrieved", 0) or 0) + 1
                    row["last_retrieved_at"] = now_ms
                relevant = bool(item.get("relevant", False))
                used = bool(item.get("used", False)) and relevant
                if relevant and (not duplicate_query):
                    row["relevant"] = int(row.get("relevant", 0) or 0) + 1
                    row["last_relevant_at"] = now_ms
                if used:
                    if (not duplicate_query) or int(row.get("used", 0) or 0) <= 0:
                        row["used"] = int(row.get("used", 0) or 0) + 1
                        row["last_used_at"] = now_ms
                row["name"] = str(getattr(rec.skill, "name", "") or "")
                row["description"] = str(getattr(rec.skill, "description", "") or "")
                if qkey:
                    row["last_query_key"] = qkey
                    row["last_query_at"] = now_ms
                    recent_map[qkey] = now_ms
                if len(recent_map) > 64:
                    pairs = sorted(recent_map.items(), key=lambda kv: int(kv[1]), reverse=True)[:32]
                    recent_map = {k: int(v) for k, v in pairs}
                row["recent_query_ts"] = recent_map
                touched.append(sid)
                updated += 1

            deleted: List[str] = []
            if min_retrieved > 0:
                prune_ids: List[str] = []
                for sid, row in list(bucket.items()):
                    rec = self._records.get(sid)
                    if rec is None:
                        continue
                    if str(getattr(rec.skill, "user_id", "") or "").strip() != uid:
                        continue
                    retrieved = int(row.get("retrieved", 0) or 0)
                    used = int(row.get("used", 0) or 0)
                    if retrieved >= min_retrieved and used <= max_used:
                        prune_ids.append(sid)
                for sid in prune_ids:
                    if self.delete(sid):
                        deleted.append(sid)

            stats: Dict[str, Dict[str, int]] = {}
            for sid in touched:
                row = bucket.get(sid)
                if not isinstance(row, dict):
                    continue
                stats[sid] = {
                    "retrieved": int(row.get("retrieved", 0) or 0),
                    "relevant": int(row.get("relevant", 0) or 0),
                    "used": int(row.get("used", 0) or 0),
                }
            return {"updated": int(updated), "deleted_skill_ids": deleted, "stats": stats}

    def get_skill_usage_stats(
        self,
        *,
        user_id: str,
        skill_id: str = "",
    ) -> Dict[str, Any]:
        """Returns in-memory usage counters."""

        uid = str(user_id or "").strip()
        sid = str(skill_id or "").strip()
        with self._lock:
            bucket = dict(self._usage_stats_by_user.get(uid) or {})
            if sid:
                rec = self._records.get(sid)
                if rec is None or str(getattr(rec.skill, "user_id", "") or "").strip() != uid:
                    return {"skills": {}}
                row = bucket.get(sid)
                if not isinstance(row, dict):
                    return {"skills": {}}
                return {"skills": {sid: dict(row)}}
            out: Dict[str, Dict[str, Any]] = {}
            for k, v in bucket.items():
                if not isinstance(v, dict):
                    continue
                rec = self._records.get(str(k))
                if rec is None or str(getattr(rec.skill, "user_id", "") or "").strip() != uid:
                    continue
                out[str(k)] = dict(v)
            return {"skills": out}

    def list(self, *, user_id: str) -> List[Skill]:
        """Run list."""
        with self._lock:
            return [
                r.skill
                for r in self._records.values()
                if r.skill.user_id == user_id and r.skill.status != SkillStatus.ARCHIVED
            ]

    def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SkillHit]:
        """Run search."""
        filters = filters or {}
        want_ids_raw = filters.get("ids")
        if want_ids_raw is None:
            want_id_set = None
        else:
            if isinstance(want_ids_raw, (list, tuple, set)):
                want_ids = list(want_ids_raw)
            else:
                want_ids = [want_ids_raw]
            want_id_set = {str(x).strip() for x in want_ids if str(x).strip()} or None
        with self._lock:
            docs_by_id: Dict[str, str] = {}
            recs: List[_Record] = []
            for rec in self._records.values():
                skill = rec.skill
                if skill.user_id != user_id:
                    continue
                if skill.status == SkillStatus.ARCHIVED:
                    continue
                if want_id_set is not None and skill.id not in want_id_set:
                    continue

                if not _passes_filters(skill, filters):
                    continue
                recs.append(rec)
                sid = str(skill.id)
                txt = self._bm25_docs_by_id.get(sid)
                if not txt:
                    txt = _skill_to_text(skill)
                    self._bm25_docs_by_id[sid] = txt
                docs_by_id[sid] = txt

        if not recs:
            return []

        bm25_scores = bm25_normalized_scores(query=query, docs=docs_by_id)

        vector_scores: Dict[str, float] = {}
        use_vector = False
        if not self._embedding_disabled:
            try:
                qvec = self._embeddings.embed([query])[0]
                use_vector = bool(qvec)
            except Exception:
                qvec = []
                use_vector = False
            if use_vector:
                for rec in recs:
                    vec = rec.vector or []
                    if not vec:
                        continue
                    vector_scores[rec.skill.id] = _cosine(qvec, vec)

        merged_scores = blend_scores(
            vector_scores=vector_scores,
            bm25_scores=bm25_scores,
            bm25_weight=self._bm25_weight,
            use_vector=use_vector,
        )

        candidates: List[Tuple[float, Skill]] = []
        for rec in recs:
            sid = rec.skill.id
            candidates.append((float(merged_scores.get(sid, 0.0)), rec.skill))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [SkillHit(skill=s, score=float(sc)) for sc, s in candidates[:limit]]


def _passes_filters(skill: Skill, filters: Dict[str, Any]) -> bool:
    """Run passes filters."""
    want_tags = filters.get("tags")
    if want_tags:
        want_set = {str(t).strip().lower() for t in want_tags if str(t).strip()}
        have_set = {t.strip().lower() for t in (skill.tags or []) if t.strip()}
        if want_set and not (want_set & have_set):
            return False

    want_status = filters.get("status")
    if want_status and str(skill.status.value) != str(want_status):
        return False

    want_meta = filters.get("metadata")
    if isinstance(want_meta, dict):
        for k, v in want_meta.items():
            if skill.metadata.get(k) != v:
                return False

    return True


def _usage_identity_key(skill: Skill) -> str:
    """Stable identity key used for counter carry-over across updated skill ids."""

    md = dict(getattr(skill, "metadata", {}) or {})
    from_md = normalize_identity_text(str(md.get("identity_desc_norm", "") or ""))
    if from_md:
        return from_md
    from_desc = identity_desc_norm_from_fields(
        description=str(getattr(skill, "description", "") or ""),
        name=str(getattr(skill, "name", "") or ""),
    )
    if from_desc:
        return from_desc
    return normalize_identity_text(str(getattr(skill, "name", "") or ""))


def _find_orphan_usage_row(
    *,
    bucket: Dict[str, Dict[str, Any]],
    identity_key: str,
    exclude_skill_id: str,
) -> str:
    """Finds a best orphan row to migrate counters from."""

    key = str(identity_key or "").strip()
    exclude = str(exclude_skill_id or "").strip()
    if not key:
        return ""
    best_sid = ""
    best_score = -1
    for sid, row in (bucket or {}).items():
        s = str(sid or "").strip()
        if not s or s == exclude:
            continue
        if not isinstance(row, dict):
            continue
        if not bool(row.get("orphaned", False)):
            continue
        if str(row.get("identity_desc_norm", "") or "").strip() != key:
            continue
        score = int(row.get("retrieved", 0) or 0) * 10 + int(row.get("used", 0) or 0)
        if score > best_score:
            best_score = score
            best_sid = s
    return best_sid
