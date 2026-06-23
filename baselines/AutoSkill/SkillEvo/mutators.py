from __future__ import annotations

from typing import Any, Dict, Iterable, List
import json

from .config import SkillEvoConfig
from .io_utils import stable_hash
from .models import EvalRule, ReplaySample, SkillSnapshot, SkillVariant


class VariantGenerator:
    def __init__(self, *, config: SkillEvoConfig, mutator_llm: Any = None) -> None:
        self.config = config
        self.mutator_llm = mutator_llm

    def generate(
        self,
        *,
        lineage_id: str,
        base: SkillSnapshot,
        eval_rules: List[EvalRule],
        failing_samples: Iterable[ReplaySample],
    ) -> List[SkillVariant]:
        variants: List[SkillVariant] = []
        for rule in eval_rules:
            variant = self._heuristic_variant(lineage_id=lineage_id, base=base, rule=rule)
            if variant is not None:
                variants.append(variant)
            if len(variants) >= self.config.mutation_budget:
                break

        if (
            self.config.mutation_mode in {"llm", "hybrid"}
            and self.mutator_llm is not None
            and len(variants) < self.config.mutation_budget
        ):
            llm_variant = self._llm_variant(
                lineage_id=lineage_id,
                base=base,
                eval_rules=eval_rules,
                failing_samples=list(failing_samples),
            )
            if llm_variant is not None:
                variants.append(llm_variant)

        deduped: List[SkillVariant] = []
        seen = set()
        for item in variants:
            key = stable_hash(item.snapshot.to_dict())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[: self.config.mutation_budget]

    def _heuristic_variant(
        self,
        *,
        lineage_id: str,
        base: SkillSnapshot,
        rule: EvalRule,
    ) -> SkillVariant | None:
        additions: List[str] = []
        notes = ""
        mutation_type = f"heuristic:{rule.rule_id}"
        if rule.rule_id == "must_cite_sources":
            additions.append("- Always cite concrete sources or links for factual claims.")
            notes = "Strengthen source-grounding."
        elif rule.rule_id == "paragraph_limit":
            n = int(rule.params.get("max_paragraphs", 3) or 3)
            additions.append(f"- Keep the final answer within {n} short paragraphs.")
            notes = "Make paragraph limit explicit."
        elif rule.rule_id == "lead_with_conclusion":
            additions.append("- Open with a direct conclusion or answer before elaboration.")
            notes = "Move answer-first behavior into explicit constraints."
        elif rule.rule_id == "json_parseable":
            additions.append("- Output valid JSON only, with no markdown fences or extra commentary.")
            notes = "Tighten JSON output contract."
        elif rule.rule_id == "markdown_table":
            additions.append("- Include a markdown table when presenting the final answer structure.")
            notes = "Enforce markdown table output."
        elif rule.rule_id == "no_unfounded_claims":
            additions.append("- Do not invent facts; if evidence is missing, state uncertainty explicitly.")
            notes = "Add anti-hallucination guardrail."
        elif str(rule.params.get("requirement_text") or "").strip():
            additions.append(f"- Requirement to preserve: {str(rule.params.get('requirement_text') or '').strip()}")
            notes = "Promote one durable lineage requirement."
        else:
            return None

        new_instructions = self._append_constraints(base.instructions, additions)
        if new_instructions.strip() == base.instructions.strip():
            return None
        snapshot = SkillSnapshot(
            skill_id=base.skill_id,
            user_id=base.user_id,
            name=base.name,
            description=base.description,
            instructions=new_instructions,
            version=base.version,
            tags=list(base.tags),
            triggers=list(base.triggers),
            metadata=dict(base.metadata),
        )
        return SkillVariant(
            variant_id=self._variant_id(lineage_id=lineage_id, parent_variant_id="baseline", label=mutation_type, snapshot=snapshot),
            parent_variant_id="baseline",
            lineage_id=lineage_id,
            label=mutation_type,
            mutation_type=mutation_type,
            notes=notes,
            snapshot=snapshot,
        )

    def _llm_variant(
        self,
        *,
        lineage_id: str,
        base: SkillSnapshot,
        eval_rules: List[EvalRule],
        failing_samples: List[ReplaySample],
    ) -> SkillVariant | None:
        top_rules = [rule.to_dict() for rule in eval_rules[:4]]
        sample_payload = []
        for item in failing_samples[:4]:
            sample_payload.append(
                {
                    "sample_id": item.sample_id,
                    "latest_user_message": item.latest_user_message(),
                    "version_anchor": item.version_anchor,
                }
            )
        system = (
            "You improve a skill prompt for replay evaluation.\n"
            "Output ONLY strict JSON parseable by json.loads.\n"
            'Schema: {"name": "...", "description": "...", "instructions": "...", "tags": ["..."], "triggers": ["..."], "notes": "..."}\n'
            "Rules:\n"
            "- Keep the same skill identity and user scope.\n"
            "- Only make small durable improvements.\n"
            "- Strengthen requirements that failed evaluation.\n"
            "- Do not invent new capabilities.\n"
        )
        user = json.dumps(
            {
                "base_skill": base.to_dict(),
                "eval_rules": top_rules,
                "failing_samples": sample_payload,
            },
            ensure_ascii=False,
        )
        try:
            raw = self.mutator_llm.complete(system=system, user=user, temperature=0.2)
            obj = json.loads(raw)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        instructions = str(obj.get("instructions") or "").strip()
        if not instructions:
            return None
        snapshot = SkillSnapshot(
            skill_id=base.skill_id,
            user_id=base.user_id,
            name=str(obj.get("name") or base.name).strip() or base.name,
            description=str(obj.get("description") or base.description).strip() or base.description,
            instructions=instructions,
            version=base.version,
            tags=[str(x).strip() for x in (obj.get("tags") or base.tags) if str(x).strip()],
            triggers=[str(x).strip() for x in (obj.get("triggers") or base.triggers) if str(x).strip()],
            metadata=dict(base.metadata),
        )
        return SkillVariant(
            variant_id=self._variant_id(lineage_id=lineage_id, parent_variant_id="baseline", label="llm_mutation", snapshot=snapshot),
            parent_variant_id="baseline",
            lineage_id=lineage_id,
            label="llm_mutation",
            mutation_type="llm_mutation",
            notes=str(obj.get("notes") or "LLM-guided mutation").strip() or "LLM-guided mutation",
            snapshot=snapshot,
        )

    def _append_constraints(self, instructions: str, additions: List[str]) -> str:
        body = str(instructions or "").rstrip()
        if not additions:
            return body
        marker = "## SkillEvo Mutation Guards"
        if marker in body:
            for item in additions:
                if item not in body:
                    body += "\n" + item
            return body + "\n"
        lines = [body, "", marker, ""]
        for item in additions:
            if item not in body:
                lines.append(item)
        return "\n".join(lines).strip() + "\n"

    def _variant_id(
        self,
        *,
        lineage_id: str,
        parent_variant_id: str,
        label: str,
        snapshot: SkillSnapshot,
    ) -> str:
        return stable_hash(
            {
                "lineage_id": lineage_id,
                "parent_variant_id": parent_variant_id,
                "label": label,
                "snapshot": snapshot.to_dict(),
            }
        )[:16]
