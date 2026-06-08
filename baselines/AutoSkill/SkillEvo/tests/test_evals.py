from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from SkillEvo.config import load_skillevo_config
from SkillEvo.evals import EvalCompiler, RuleEngine
from SkillEvo.models import EvalRule, LineageRecord, ReplaySample, SkillSnapshot


class _FakeStore:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeSDK:
    def __init__(self, path: str) -> None:
        self.store = _FakeStore(path)


class EvalCompilerTests(unittest.TestCase):
    def test_compile_uses_prompt_and_requirement_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "SkillBank"
            index_dir = store / "index"
            index_dir.mkdir(parents=True, exist_ok=True)
            (index_dir / "offline_requirement_stats_u1.json").write_text(
                """{
  "version": 1,
  "user_id": "u1",
  "lineages": {
    "lk-1": {
      "requirements": {
        "r1": {"canonical": "先给结论", "mentions": 3, "hard_mentions": 2},
        "r2": {"canonical": "引用来源", "mentions": 2, "hard_mentions": 2},
        "r3": {"canonical": "避免幻觉式承诺", "mentions": 4, "hard_mentions": 4}
      }
    }
  }
}
""",
                encoding="utf-8",
            )
            config = load_skillevo_config(
                overrides={
                    "evo_root": str(root / "SkillEvo"),
                    "store_path": str(store),
                    "max_eval_rules": 6,
                }
            )
            compiler = EvalCompiler(config=config, sdk=_FakeSDK(str(store)))
            skill = SkillSnapshot(
                skill_id="s1",
                user_id="u1",
                name="test",
                description="Need source-backed concise JSON answers.",
                instructions="先给结论。回答不超过 3 段。引用来源。输出 JSON。不要幻觉。",
                version="0.1.0",
            )
            lineage = LineageRecord(
                lineage_id="lineage-1",
                user_id="u1",
                skill_id="s1",
                skill_name="test",
                current_version="0.1.0",
                offline_lineage_key="lk-1",
            )
            rules = compiler.compile(skill=skill, lineage=lineage)
            rule_ids = {item.rule_id for item in rules}
            self.assertIn("response_nonempty", rule_ids)
            self.assertIn("must_cite_sources", rule_ids)
            self.assertIn("paragraph_limit", rule_ids)
            self.assertIn("lead_with_conclusion", rule_ids)
            self.assertIn("json_parseable", rule_ids)
            self.assertIn("no_unfounded_claims", rule_ids)


class RuleEngineTests(unittest.TestCase):
    def test_programmatic_rules_work(self) -> None:
        engine = RuleEngine(judge_llm=None)
        sample = ReplaySample(
            sample_id="x",
            lineage_id="l1",
            user_id="u1",
            skill_id="s1",
            source_type="online",
            split="mutate_dev",
            messages=[{"role": "user", "content": "Hello"}],
        )
        variant = SkillSnapshot(
            skill_id="s1",
            user_id="u1",
            name="test",
            description="",
            instructions="",
            version="0.1.0",
        )
        outcome = engine.evaluate(
            rule=EvalRule(
                rule_id="paragraph_limit",
                label="Paragraph limit",
                kind="programmatic",
                scope="response",
                hard=True,
                description="",
                params={"mode": "max_paragraphs", "max_paragraphs": 2},
            ),
            response_text="A\n\nB\n\nC",
            sample=sample,
            variant=variant,
        )
        self.assertFalse(outcome.passed)
        cite = engine.evaluate(
            rule=EvalRule(
                rule_id="must_cite_sources",
                label="Sources",
                kind="programmatic",
                scope="response",
                hard=True,
                description="",
                params={"mode": "mentions_sources"},
            ),
            response_text="结论：可以。[paper](https://example.com)",
            sample=sample,
            variant=variant,
        )
        self.assertTrue(cite.passed)


if __name__ == "__main__":
    unittest.main()
