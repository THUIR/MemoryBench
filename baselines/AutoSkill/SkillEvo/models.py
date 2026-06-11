from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SkillSnapshot:
    skill_id: str
    user_id: str
    name: str
    description: str
    instructions: str
    version: str
    tags: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LineageRecord:
    lineage_id: str
    user_id: str
    skill_id: str
    skill_name: str
    current_version: str
    offline_lineage_key: str = ""
    online_available: bool = False
    offline_available: bool = False
    replay_count: int = 0
    replay_dev_count: int = 0
    replay_test_count: int = 0
    version_timeline: List[Dict[str, Any]] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReplaySample:
    sample_id: str
    lineage_id: str
    user_id: str
    skill_id: str
    source_type: str  # online|offline
    split: str  # mutate_dev|promotion_test
    messages: List[Dict[str, str]]
    events: List[Dict[str, Any]] = field(default_factory=list)
    version_anchor: str = ""
    provenance_ref: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def latest_user_message(self) -> str:
        for item in reversed(self.messages):
            if str(item.get("role") or "").strip().lower() == "user":
                return str(item.get("content") or "")
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvalRule:
    rule_id: str
    label: str
    kind: str  # programmatic|llm_binary
    scope: str  # response
    hard: bool
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SkillVariant:
    variant_id: str
    parent_variant_id: str
    lineage_id: str
    label: str
    mutation_type: str
    notes: str
    snapshot: SkillSnapshot

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "parent_variant_id": self.parent_variant_id,
            "lineage_id": self.lineage_id,
            "label": self.label,
            "mutation_type": self.mutation_type,
            "notes": self.notes,
            "snapshot": self.snapshot.to_dict(),
        }


@dataclass
class RuleOutcome:
    rule_id: str
    passed: bool
    hard: bool
    score: float
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SampleEvaluation:
    sample_id: str
    variant_id: str
    response_text: str
    outcomes: List[RuleOutcome] = field(default_factory=list)

    def total_score(self) -> float:
        if not self.outcomes:
            return 0.0
        return float(sum(x.score for x in self.outcomes))

    def hard_failures(self) -> int:
        return sum(1 for item in self.outcomes if item.hard and not item.passed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "variant_id": self.variant_id,
            "response_text": self.response_text,
            "outcomes": [x.to_dict() for x in self.outcomes],
            "total_score": self.total_score(),
            "hard_failures": self.hard_failures(),
        }


@dataclass
class VariantSummary:
    variant_id: str
    label: str
    split: str
    sample_count: int
    total_score: float
    average_score: float
    hard_failures: int
    passed_rules: int
    total_rules: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
