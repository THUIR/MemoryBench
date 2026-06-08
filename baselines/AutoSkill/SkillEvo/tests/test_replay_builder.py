from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autoskill.models import Skill

from SkillEvo.config import load_skillevo_config
from SkillEvo.replay_builder import ReplayBuilder


class _FakeSDK:
    def __init__(self, skill: Skill, online_record: dict) -> None:
        self._skill = skill
        self._online_record = online_record

    def get(self, skill_id: str):
        if skill_id == self._skill.id:
            return self._skill
        return None

    def get_skill_provenance(self, *, user_id: str, skill_id: str, max_sources: int, max_history: int, include_messages: bool):
        return dict(self._online_record)


class ReplayBuilderTests(unittest.TestCase):
    def test_build_merges_online_and_offline_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "SkillBank"
            skill = Skill(
                id="skill-1",
                user_id="u1",
                name="demo",
                description="demo skill",
                instructions="demo instructions",
                version="0.1.0",
            )
            online_record = {
                "history": [
                    {
                        "source_key": "sk1",
                        "source_label": "online-session",
                        "timestamp_ms": 10,
                        "version": "0.1.0",
                        "channel": "ingest",
                        "trigger": "test",
                        "messages": [
                            {"role": "user", "content": "Need a concise answer."},
                            {"role": "assistant", "content": "Sure."},
                        ],
                        "events": [],
                    }
                ],
                "version_timeline": [{"version": "0.1.0", "is_current": True}],
            }
            sdk = _FakeSDK(skill, online_record)
            config = load_skillevo_config(
                overrides={
                    "evo_root": str(root / "SkillEvo"),
                    "store_path": str(store),
                    "sample_history_turns": 8,
                }
            )
            builder = ReplayBuilder(config=config, sdk=sdk)

            source_file = root / "conv.json"
            source_file.write_text(
                json.dumps(
                    {
                        "messages": [
                            {"role": "user", "content": "Please cite sources."},
                            {"role": "assistant", "content": "Okay."},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            offline_record = {
                "lineage_key": "lk-demo",
                "sources": [
                    {
                        "conversation_key": "ck1",
                        "source_file": str(source_file),
                        "conversation_index": 0,
                        "locator": "conv.json#conv_1",
                        "last_seen_at_ms": 20,
                        "title": "conv.json#conv_1",
                    }
                ],
                "history": [
                    {
                        "conversation_key": "ck1",
                        "version": "0.1.0",
                        "timestamp_ms": 20,
                    }
                ],
            }

            with patch("SkillEvo.replay_builder.load_skill_conversation_provenance", return_value=offline_record):
                lineage, _snapshot, samples, _online, _offline = builder.build_for_skill(
                    user_id="u1",
                    skill_id="skill-1",
                )

            self.assertEqual(lineage.offline_lineage_key, "lk-demo")
            self.assertGreaterEqual(len(samples), 2)
            self.assertTrue(any(item.source_type == "online" for item in samples))
            self.assertTrue(any(item.source_type == "offline" for item in samples))
            self.assertTrue((root / "SkillEvo" / "datasets" / lineage.lineage_id / "replay_pool.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
