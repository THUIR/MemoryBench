"""
Store interface.

Minimal capabilities for the SDK:
- upsert/get/list/delete: manage skills
- search: similarity search powered by embeddings
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ...models import Skill, SkillHit


class SkillStore(ABC):
    @abstractmethod
    def upsert(self, skill: Skill, *, raw: Optional[Dict[str, Any]] = None) -> None:
        """Run upsert."""
        raise NotImplementedError

    @abstractmethod
    def get(self, skill_id: str) -> Optional[Skill]:
        """Run get."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, skill_id: str) -> bool:
        """Run delete."""
        raise NotImplementedError

    @abstractmethod
    def list(self, *, user_id: str) -> List[Skill]:
        """Run list."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SkillHit]:
        """Run search."""
        raise NotImplementedError

    def record_skill_usage_judgments(
        self,
        *,
        user_id: str,
        judgments: List[Dict[str, Any]],
        prune_min_retrieved: int = 0,
        prune_max_used: int = 0,
    ) -> Dict[str, Any]:
        """
        Records retrieval/relevance/usage judgments for one turn.

        Default implementation is a no-op so custom stores remain backward compatible.
        """

        _ = user_id
        _ = judgments
        _ = prune_min_retrieved
        _ = prune_max_used
        return {"updated": 0, "deleted_skill_ids": [], "stats": {}}

    def get_skill_usage_stats(
        self,
        *,
        user_id: str,
        skill_id: str = "",
    ) -> Dict[str, Any]:
        """
        Returns usage counters for one user (and optionally one skill).

        Default implementation is a no-op so custom stores remain backward compatible.
        """

        _ = user_id
        _ = skill_id
        return {"skills": {}}
