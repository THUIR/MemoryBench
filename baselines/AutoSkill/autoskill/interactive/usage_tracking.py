"""
Skill usage tracking helpers.

This module decides (per turn) whether retrieved skills are:
- relevant to the current user query
- actually used in the assistant response
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set

from ..llm.base import LLM
from ..models import SkillHit
from ..utils.json import json_from_llm_text
from ..utils.text import keywords


def _clean_llm_output(text: str) -> str:
    """Strips common wrappers before JSON parsing."""

    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
    for prefix in ("JSON:", "Output:", "Response:"):
        if raw.lower().startswith(prefix.lower()):
            raw = raw[len(prefix) :].strip()
    return raw


def build_query_key(query: str) -> str:
    """
    Builds a stable fingerprint for one user query.

    Used by store-side counter de-noising (duplicate query hits in one session/time window).
    """

    q = re.sub(r"\s+", " ", str(query or "").strip().lower()).strip()
    base = q[:200]
    if not base:
        return ""
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _skill_signal_text(skill: Any) -> str:
    """Builds compact signal text for fallback relevance/usage heuristics."""

    name = str(getattr(skill, "name", "") or "")
    description = str(getattr(skill, "description", "") or "")
    tags = " ".join([str(t) for t in (getattr(skill, "tags", []) or [])[:12]])
    triggers = " ".join([str(t) for t in (getattr(skill, "triggers", []) or [])[:12]])
    instructions = str(getattr(skill, "instructions", "") or "")[:400]
    return "\n".join([name, description, tags, triggers, instructions]).strip()


def _fallback_judgments(
    *,
    query: str,
    assistant_reply: str,
    hits: Sequence[SkillHit],
    selected_for_context_ids: Set[str],
) -> List[Dict[str, Any]]:
    """Deterministic fallback when LLM output is missing/unparseable."""

    q_tokens = {t.lower() for t in keywords(query or "", limit=48) if t}
    a_tokens = {t.lower() for t in keywords(assistant_reply or "", limit=96) if t}

    out: List[Dict[str, Any]] = []
    for hit in hits:
        skill = getattr(hit, "skill", None)
        if skill is None:
            continue
        sid = str(getattr(skill, "id", "") or "").strip()
        if not sid:
            continue
        s_tokens = {t.lower() for t in keywords(_skill_signal_text(skill), limit=96) if t}
        overlap_q = len(q_tokens & s_tokens)
        overlap_a = len(a_tokens & s_tokens)
        injected = sid in selected_for_context_ids
        relevant = bool(overlap_q > 0 or injected)
        used = bool(relevant and injected and overlap_a > 0)
        out.append(
            {
                "id": sid,
                "relevant": bool(relevant),
                "used": bool(used),
                "reason": (
                    "fallback overlap"
                    if (overlap_q > 0 or overlap_a > 0)
                    else ("fallback selected" if injected else "fallback none")
                ),
            }
        )
    return out


@dataclass
class LLMSkillUsageJudge:
    """
    Uses an LLM to judge per-retrieved-skill relevance and actual usage in a reply.
    """

    llm: LLM
    max_candidates: int = 8
    max_reply_chars: int = 6000

    def judge(
        self,
        *,
        query: str,
        assistant_reply: str,
        hits: Sequence[SkillHit],
        selected_for_context_ids: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Returns one judgment row per hit id: {id, relevant, used, reason}."""

        q = str(query or "").strip()
        reply = str(assistant_reply or "").strip()
        candidates = list(hits or [])[: max(1, int(self.max_candidates or 8))]
        if not candidates:
            return []

        selected_set = {
            str(sid).strip() for sid in (selected_for_context_ids or []) if str(sid).strip()
        }
        item_rows: List[Dict[str, Any]] = []
        for hit in candidates:
            skill = getattr(hit, "skill", None)
            if skill is None:
                continue
            sid = str(getattr(skill, "id", "") or "").strip()
            if not sid:
                continue
            item_rows.append(
                {
                    "id": sid,
                    "name": str(getattr(skill, "name", "") or ""),
                    "description": str(getattr(skill, "description", "") or ""),
                    "tags": [str(t) for t in (getattr(skill, "tags", []) or [])[:12]],
                    "triggers": [str(t) for t in (getattr(skill, "triggers", []) or [])[:12]],
                    "retrieval_score": float(getattr(hit, "score", 0.0) or 0.0),
                    "selected_for_context": bool(sid in selected_set),
                }
            )
        if not item_rows:
            return []

        payload = {
            "query": q,
            "assistant_reply": reply[: max(256, int(self.max_reply_chars or 6000))],
            "skills": item_rows,
        }
        system = (
            "You are AutoSkill's skill-usage auditor.\n"
            "Task: for each provided skill id, judge the CURRENT query+CURRENT reply pair only:\n"
            "- relevant: whether the skill matches the current user query intent\n"
            "- used: whether the assistant reply actually depends on and applies this skill's unique constraints/workflow\n"
            "Rules:\n"
            "- Return every provided skill id exactly once.\n"
            "- used=true only when relevant=true.\n"
            "- Be strict: if the reply can be produced well without this skill, set used=false.\n"
            "- Do not mark used=true for generic stylistic overlap or generic assistant behavior.\n"
            "- If uncertain, set false.\n"
            "Output ONLY strict JSON (no Markdown, no commentary):\n"
            "{\"skills\":[{\"id\":\"...\",\"relevant\":true|false,\"used\":true|false,\"reason\":\"...\"}]}"
        )
        user = f"{__name__}.DATA:\n{_json_dumps(payload)}"

        parsed: Any = None
        try:
            out = self.llm.complete(system=system, user=user, temperature=0.0)
            cleaned = _clean_llm_output(out)
            if cleaned:
                parsed = json_from_llm_text(cleaned)
        except Exception:
            parsed = None

        allowed = {str(row.get("id") or "").strip() for row in item_rows}
        judged_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(parsed, dict) and isinstance(parsed.get("skills"), list):
            for raw in parsed.get("skills") or []:
                if not isinstance(raw, dict):
                    continue
                sid = str(raw.get("id") or raw.get("skill_id") or "").strip()
                if not sid or sid not in allowed:
                    continue
                relevant = bool(raw.get("relevant", False))
                used = bool(raw.get("used", False)) and relevant
                judged_map[sid] = {
                    "id": sid,
                    "relevant": bool(relevant),
                    "used": bool(used),
                    "reason": str(raw.get("reason", "") or ""),
                }

        if len(judged_map) < len(allowed):
            fallback = _fallback_judgments(
                query=q,
                assistant_reply=reply,
                hits=candidates,
                selected_for_context_ids=selected_set,
            )
            for row in fallback:
                sid = str(row.get("id") or "").strip()
                if sid and sid not in judged_map:
                    judged_map[sid] = row

        out_rows: List[Dict[str, Any]] = []
        for row in item_rows:
            sid = str(row.get("id") or "").strip()
            judged = judged_map.get(sid)
            if not isinstance(judged, dict):
                continue
            out_rows.append(judged)
        return out_rows


def _json_dumps(obj: Any) -> str:
    """Run json dumps."""

    import json

    return json.dumps(obj, ensure_ascii=False)
