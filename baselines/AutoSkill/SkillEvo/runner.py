from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
import json

from autoskill.management.formats.agent_skill import build_agent_skill_files
from autoskill.models import Skill

from .config import SkillEvoConfig
from .evals import EvalCompiler, RuleEngine
from .io_utils import ensure_dir, write_json, write_jsonl
from .models import EvalRule, ReplaySample, SampleEvaluation, SkillSnapshot, SkillVariant, VariantSummary
from .mutators import VariantGenerator
from .registry import (
    ensure_evo_layout,
    get_champion,
    lineage_champion_dir,
    lineage_eval_dir,
    lineage_run_dir,
    set_champion,
)
from .replay_builder import ReplayBuilder
from .sdk import build_evo_llm, build_evo_sdk


class SkillEvoRunner:
    def __init__(self, *, config: SkillEvoConfig) -> None:
        self.config = config
        self.sdk = build_evo_sdk(config)
        self.responder_llm = build_evo_llm(config.llm)
        self.mutator_llm = build_evo_llm(config.mutator_llm) or self.responder_llm
        self.judge_llm = build_evo_llm(config.judge_llm) or self.responder_llm
        self.replay_builder = ReplayBuilder(config=config, sdk=self.sdk)
        self.eval_compiler = EvalCompiler(config=config, sdk=self.sdk)
        self.rule_engine = RuleEngine(judge_llm=self.judge_llm)
        self.variant_generator = VariantGenerator(config=config, mutator_llm=self.mutator_llm)

    def run(self, *, user_id: str, skill_id: str) -> Dict[str, Any]:
        ensure_evo_layout(self.config)
        lineage, skill_snapshot, samples, online_record, offline_record = self.replay_builder.build_for_skill(
            user_id=user_id,
            skill_id=skill_id,
        )
        eval_rules = self.eval_compiler.compile(skill=skill_snapshot, lineage=lineage)
        eval_dir = lineage_eval_dir(self.config, lineage.lineage_id)
        ensure_dir(eval_dir)
        write_json(eval_dir / "eval_spec.json", {"rules": [x.to_dict() for x in eval_rules]})

        run_id = self._run_id()
        run_dir = lineage_run_dir(self.config, lineage.lineage_id, run_id)
        ensure_dir(run_dir)

        dev_samples = [x for x in samples if x.split == "mutate_dev"]
        test_samples = [x for x in samples if x.split == "promotion_test"]
        insufficient_replay = bool(
            len(samples) < int(self.config.min_replay_samples)
            or not dev_samples
            or not test_samples
        )

        champion_item = get_champion(self.config, lineage.lineage_id)
        champion_snapshot = self._snapshot_from_registry(champion_item) or skill_snapshot
        champion_variant = self._variant_from_snapshot(
            lineage_id=lineage.lineage_id,
            snapshot=champion_snapshot,
            label=("current_champion" if champion_item else "baseline"),
            mutation_type=("active_evo" if champion_item else "baseline"),
            notes=("Loaded from SkillEvo champion registry." if champion_item else "Current SkillBank version."),
        )
        baseline_variant = self._variant_from_snapshot(
            lineage_id=lineage.lineage_id,
            snapshot=skill_snapshot,
            label="baseline",
            mutation_type="baseline",
            notes="Current SkillBank snapshot.",
        )

        baseline_dev_eval, baseline_dev_summary = self._evaluate_variant(
            variant=baseline_variant,
            samples=dev_samples,
            rules=eval_rules,
            split="mutate_dev",
            repeats=self.config.mutate_repeats,
        )
        failing_samples = self._pick_failing_samples(sample_evals=baseline_dev_eval, replay_samples=dev_samples)

        candidate_variants = self.variant_generator.generate(
            lineage_id=lineage.lineage_id,
            base=skill_snapshot,
            eval_rules=eval_rules,
            failing_samples=failing_samples,
        )

        variant_summaries: List[Dict[str, Any]] = [baseline_dev_summary.to_dict()]
        all_outputs: List[Dict[str, Any]] = [x.to_dict() for x in baseline_dev_eval]
        all_judgments: List[Dict[str, Any]] = self._flatten_judgments(baseline_dev_eval)

        scored_candidates: List[Tuple[SkillVariant, VariantSummary, List[SampleEvaluation]]] = []
        for variant in candidate_variants:
            sample_evals, summary = self._evaluate_variant(
                variant=variant,
                samples=dev_samples,
                rules=eval_rules,
                split="mutate_dev",
                repeats=self.config.mutate_repeats,
            )
            scored_candidates.append((variant, summary, sample_evals))
            variant_summaries.append(summary.to_dict())
            all_outputs.extend(x.to_dict() for x in sample_evals)
            all_judgments.extend(self._flatten_judgments(sample_evals))

        best_variant, best_dev_summary = self._pick_best_variant(
            baseline_variant=baseline_variant,
            baseline_summary=baseline_dev_summary,
            scored_candidates=scored_candidates,
        )

        champion_test_eval, champion_test_summary = self._evaluate_variant(
            variant=champion_variant,
            samples=test_samples,
            rules=eval_rules,
            split="promotion_test",
            repeats=self.config.promotion_repeats,
        )
        best_test_eval, best_test_summary = self._evaluate_variant(
            variant=best_variant,
            samples=test_samples,
            rules=eval_rules,
            split="promotion_test",
            repeats=self.config.promotion_repeats,
        )
        all_outputs.extend(x.to_dict() for x in champion_test_eval)
        all_outputs.extend(x.to_dict() for x in best_test_eval)
        all_judgments.extend(self._flatten_judgments(champion_test_eval))
        all_judgments.extend(self._flatten_judgments(best_test_eval))

        promoted = (not insufficient_replay) and self._should_promote(
            champion=champion_test_summary,
            candidate=best_test_summary,
        )
        promotion_summary = {
            "promoted": bool(promoted),
            "status": ("incubating" if insufficient_replay else ("active_evo" if promoted else "rejected")),
            "champion_before": champion_test_summary.to_dict(),
            "candidate": best_test_summary.to_dict(),
            "min_score_delta": self.config.min_score_delta,
            "min_replay_samples": self.config.min_replay_samples,
        }

        if promoted:
            self._persist_champion(lineage_id=lineage.lineage_id, variant=best_variant, promotion_summary=promotion_summary)

        write_jsonl(run_dir / "outputs.jsonl", all_outputs)
        write_jsonl(run_dir / "judgments.jsonl", all_judgments)
        report = {
            "run_id": run_id,
            "lineage": lineage.to_dict(),
            "baseline_variant": baseline_variant.to_dict(),
            "champion_variant": champion_variant.to_dict(),
            "candidate_variants": [x.to_dict() for x in candidate_variants],
            "variant_summaries": variant_summaries,
            "promotion": promotion_summary,
            "replay_counts": {
                "total": len(samples),
                "mutate_dev": len(dev_samples),
                "promotion_test": len(test_samples),
            },
            "provenance": {
                "online_history_count": len(list(online_record.get("history") or [])),
                "offline_history_count": len(list(offline_record.get("history") or [])),
            },
        }
        write_json(run_dir / "summary.json", report)
        return report

    def _evaluate_variant(
        self,
        *,
        variant: SkillVariant,
        samples: List[ReplaySample],
        rules: List[EvalRule],
        split: str,
        repeats: int,
    ) -> Tuple[List[SampleEvaluation], VariantSummary]:
        outputs: List[SampleEvaluation] = []
        for repeat_idx in range(max(1, int(repeats or 1))):
            for sample in samples:
                response_text = self._generate_response(snapshot=variant.snapshot, sample=sample)
                sample_eval = SampleEvaluation(
                    sample_id=(f"{sample.sample_id}:r{repeat_idx + 1}" if repeats > 1 else sample.sample_id),
                    variant_id=variant.variant_id,
                    response_text=response_text,
                    outcomes=[
                        self.rule_engine.evaluate(
                            rule=rule,
                            response_text=response_text,
                            sample=sample,
                            variant=variant.snapshot,
                        )
                        for rule in rules
                    ],
                )
                outputs.append(sample_eval)
        total_score = float(sum(x.total_score() for x in outputs))
        total_rules = sum(len(x.outcomes) for x in outputs)
        passed_rules = sum(1 for x in outputs for rule in x.outcomes if rule.passed)
        hard_failures = sum(x.hard_failures() for x in outputs)
        average_score = total_score / float(max(1, len(outputs)))
        summary = VariantSummary(
            variant_id=variant.variant_id,
            label=variant.label,
            split=split,
            sample_count=len(outputs),
            total_score=total_score,
            average_score=average_score,
            hard_failures=hard_failures,
            passed_rules=passed_rules,
            total_rules=total_rules,
        )
        return outputs, summary

    def _generate_response(self, *, snapshot: SkillSnapshot, sample: ReplaySample) -> str:
        if self.responder_llm is None:
            return ""
        history = self._format_conversation(sample.messages)
        user = (
            "Replay the following conversation with the skill instructions already injected.\n\n"
            f"Conversation:\n{history}\n\n"
            "Respond to the latest user message."
        )
        text = self.responder_llm.complete(
            system=snapshot.instructions,
            user=user,
            temperature=0.0,
        )
        return str(text or "")[: self.config.response_max_chars]

    def _format_conversation(self, messages: List[Dict[str, str]]) -> str:
        lines: List[str] = []
        for item in messages:
            role = str(item.get("role") or "").strip().lower() or "user"
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"[{role}] {content}")
        return "\n\n".join(lines).strip()

    def _pick_failing_samples(
        self,
        *,
        sample_evals: List[SampleEvaluation],
        replay_samples: List[ReplaySample],
    ) -> List[ReplaySample]:
        lookup = {sample.sample_id: sample for sample in replay_samples}
        out: List[ReplaySample] = []
        for item in sample_evals:
            if item.hard_failures() <= 0 and item.total_score() > 0:
                continue
            base_sample_id = str(item.sample_id or "").split(":r", 1)[0]
            sample = lookup.get(base_sample_id)
            if sample is not None:
                out.append(sample)
        if out:
            return out
        return list(replay_samples[:4])

    def _pick_best_variant(
        self,
        *,
        baseline_variant: SkillVariant,
        baseline_summary: VariantSummary,
        scored_candidates: List[Tuple[SkillVariant, VariantSummary, List[SampleEvaluation]]],
    ) -> Tuple[SkillVariant, VariantSummary]:
        best_variant = baseline_variant
        best_summary = baseline_summary
        for variant, summary, _sample_evals in scored_candidates:
            if summary.average_score > best_summary.average_score + 1e-9:
                best_variant = variant
                best_summary = summary
                continue
            if abs(summary.average_score - best_summary.average_score) <= 1e-9 and summary.hard_failures < best_summary.hard_failures:
                best_variant = variant
                best_summary = summary
        return best_variant, best_summary

    def _should_promote(self, *, champion: VariantSummary, candidate: VariantSummary) -> bool:
        if candidate.sample_count <= 0:
            return False
        if candidate.average_score < champion.average_score + float(self.config.min_score_delta):
            return False
        if candidate.hard_failures > champion.hard_failures:
            return False
        return True

    def _persist_champion(self, *, lineage_id: str, variant: SkillVariant, promotion_summary: Dict[str, Any]) -> None:
        path = lineage_champion_dir(self.config, lineage_id)
        ensure_dir(path)
        skill = Skill(
            id=variant.snapshot.skill_id,
            user_id=variant.snapshot.user_id,
            name=variant.snapshot.name,
            description=variant.snapshot.description,
            instructions=variant.snapshot.instructions,
            version=variant.snapshot.version,
            tags=list(variant.snapshot.tags),
            triggers=list(variant.snapshot.triggers),
            metadata=dict(variant.snapshot.metadata),
        )
        files = build_agent_skill_files(skill)
        for rel_path, content in files.items():
            target = path / rel_path
            ensure_dir(target.parent)
            target.write_text(str(content), encoding="utf-8")
        write_json(path / "champion.json", {"variant": variant.to_dict(), "promotion": promotion_summary})
        set_champion(self.config, lineage_id=lineage_id, variant=variant, summary=promotion_summary)

    def _variant_from_snapshot(
        self,
        *,
        lineage_id: str,
        snapshot: SkillSnapshot,
        label: str,
        mutation_type: str,
        notes: str,
    ) -> SkillVariant:
        variant_id = f"{mutation_type}-{snapshot.version or 'v'}-{lineage_id[-6:]}"
        return SkillVariant(
            variant_id=variant_id,
            parent_variant_id="",
            lineage_id=lineage_id,
            label=label,
            mutation_type=mutation_type,
            notes=notes,
            snapshot=snapshot,
        )

    def _snapshot_from_registry(self, item: Dict[str, Any]) -> SkillSnapshot | None:
        variant = dict(item.get("variant") or {})
        snapshot = dict(variant.get("snapshot") or {})
        if not snapshot:
            return None
        return SkillSnapshot(
            skill_id=str(snapshot.get("skill_id") or ""),
            user_id=str(snapshot.get("user_id") or ""),
            name=str(snapshot.get("name") or ""),
            description=str(snapshot.get("description") or ""),
            instructions=str(snapshot.get("instructions") or ""),
            version=str(snapshot.get("version") or ""),
            tags=[str(x).strip() for x in (snapshot.get("tags") or []) if str(x).strip()],
            triggers=[str(x).strip() for x in (snapshot.get("triggers") or []) if str(x).strip()],
            metadata=dict(snapshot.get("metadata") or {}),
        )

    def _flatten_judgments(self, sample_evals: List[SampleEvaluation]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for sample_eval in sample_evals:
            for outcome in sample_eval.outcomes:
                rows.append(
                    {
                        "sample_id": sample_eval.sample_id,
                        "variant_id": sample_eval.variant_id,
                        "rule_id": outcome.rule_id,
                        "passed": outcome.passed,
                        "hard": outcome.hard,
                        "score": outcome.score,
                        "details": dict(outcome.details),
                    }
                )
        return rows

    def _run_id(self) -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
