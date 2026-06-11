from __future__ import annotations

import json
import os
import tempfile
import unittest

from autoskill.llm.mock import MockLLM

from AutoSkill4Doc.document.windowing import build_windows_for_record
from AutoSkill4Doc.family_resolver import build_document_family_resolver
from AutoSkill4Doc.models import DocumentRecord, DocumentSection, TextSpan
from AutoSkill4Doc.prompts import OFFLINE_CHANNEL_DOC, build_offline_extract_prompt
from AutoSkill4Doc.stages.extractor import build_document_skill_extractor, extract_skills
from AutoSkill4Doc.taxonomy import list_builtin_skill_taxonomies, load_skill_taxonomy


def _chemistry_extract_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
    _ = system, temperature, user, mode
    return json.dumps(
        {
            "skills": [
                {
                    "name": "TLC analysis workflow",
                    "description": "Run a thin-layer chromatography analysis workflow.",
                    "prompt": "# Goal\nRun the TLC workflow.\n\n# Core Workflow\n1. Prepare the plate.\n2. Spot the sample.\n3. Develop the plate.\n4. Read the bands.\n\n# Output Format\n- Output the Rf summary.",
                    "asset_type": "experiment_workflow",
                    "granularity": "session",
                    "objective": "Run a TLC analysis workflow.",
                    "domain": "chemistry",
                    "task_family": "analysis",
                    "method_family": "tlc",
                    "stage": "analysis",
                    "workflow_steps": [
                        "Prepare the plate.",
                        "Spot the sample.",
                        "Develop the plate.",
                        "Read the bands.",
                    ],
                    "constraints": ["Use the configured solvent system."],
                    "output_contract": ["Output the Rf summary."],
                    "relation_type": "support",
                    "risk_class": "low",
                    "confidence": 0.9,
                }
            ]
        },
        ensure_ascii=False,
    )


class DocumentTaxonomyTest(unittest.TestCase):
    def test_builtin_taxonomies_are_listed(self) -> None:
        names = list_builtin_skill_taxonomies()
        self.assertIn("default", names)
        self.assertIn("psychology", names)
        self.assertIn("chemistry", names)

    def test_builtin_taxonomy_maps_aliases_to_internal_base_type(self) -> None:
        taxonomy = load_skill_taxonomy(domain_type="chemistry")
        self.assertEqual(taxonomy.domain_type, "chemistry")
        self.assertEqual(taxonomy.normalize_asset_type("experiment_workflow"), "session_skill")
        self.assertEqual(taxonomy.normalize_asset_type("reagent_safety_rule"), "safety_rule")
        self.assertEqual(taxonomy.strict_normalize_asset_type("experiment_workflow"), "session_skill")
        self.assertEqual(taxonomy.strict_normalize_asset_type("unknown_type"), "")
        self.assertEqual(taxonomy.resolve_axis_label(), "实验路线")
        self.assertEqual(taxonomy.resolve_family_name(), "通用化学流程")
        self.assertEqual(taxonomy.resolve_asset_node(asset_type="safety_rule").node_id, "reagent_safety_rule_node")

    def test_psychology_taxonomy_uses_expected_family_candidates(self) -> None:
        taxonomy = load_skill_taxonomy(domain_type="psychology")

        self.assertEqual(
            [str(item.get("id") or "") for item in taxonomy.family_candidates],
            [
                "psychodynamic",
                "behaviorism",
                "cbt",
                "humanistic_existentialist",
                "postmodernist",
            ],
        )
        self.assertEqual(taxonomy.family_candidates[0]["name"], "Psychodynamic（心理动力学）")
        self.assertIn("行为主义", list(taxonomy.family_candidates[1].get("aliases") or []))
        self.assertIn("认知行为疗法", list(taxonomy.family_candidates[2].get("aliases") or []))
        self.assertIn("人本-存在主义", list(taxonomy.family_candidates[3].get("aliases") or []))
        self.assertIn("后现代主义", list(taxonomy.family_candidates[4].get("aliases") or []))
        self.assertEqual(taxonomy.visible_root_label(), "总技能")
        self.assertEqual(taxonomy.visible_level_label(1), "一级技能")
        self.assertEqual(taxonomy.visible_level_label(2), "二级技能")
        self.assertEqual(taxonomy.visible_level_label(3), "微技能")
        self.assertEqual(taxonomy.resolve_asset_node(asset_type="session_skill").node_id, "session_framework")
        self.assertEqual(taxonomy.resolve_asset_node(asset_type="micro_skill").node_id, "micro_intervention")
        self.assertEqual(taxonomy.resolve_asset_node(asset_type="macro_protocol").node_id, "treatment_framework")
        self.assertEqual(taxonomy.resolve_asset_node(asset_type="safety_rule").node_id, "safety_micro")
        self.assertEqual(taxonomy.asset_path("micro_intervention"), "family_root/treatment_framework/session_framework/micro_intervention")

    def test_builtin_taxonomies_expose_consistent_asset_tree_relationships(self) -> None:
        for domain_type in ("default", "psychology", "chemistry"):
            taxonomy = load_skill_taxonomy(domain_type=domain_type)
            node_map = taxonomy.asset_node_map
            self.assertTrue(node_map)
            self.assertIn("family_root", node_map)
            for node in taxonomy.asset_tree:
                if node.parent:
                    self.assertIn(node.parent, node_map)
                    self.assertIn(node.node_id, list(node_map[node.parent].allowed_children or []))
                for child_id in list(node.allowed_children or []):
                    self.assertIn(child_id, node_map)

    def test_builtin_taxonomies_expose_all_stable_base_asset_types(self) -> None:
        expected = {
            "macro_protocol",
            "session_skill",
            "micro_skill",
            "safety_rule",
            "knowledge_reference",
        }
        for domain_type in ("default", "psychology", "chemistry"):
            taxonomy = load_skill_taxonomy(domain_type=domain_type)
            actual = {item.base_type for item in taxonomy.asset_types}
            self.assertEqual(actual, expected)

    def test_family_resolver_prefers_configured_rule_match(self) -> None:
        taxonomy = load_skill_taxonomy(domain_type="psychology")
        resolver = build_document_family_resolver(taxonomy=taxonomy)
        record = DocumentRecord(
            doc_id="psych-doc-1",
            source_type="markdown_document",
            title="CBT automatic thought restructuring",
            domain="psychology",
            raw_text="# 自动思维\n使用 ABC 记录表识别自动思维，并布置认知重评作业。\n",
            sections=[
                DocumentSection(
                    heading="自动思维",
                    text="使用 ABC 记录表识别自动思维，并布置认知重评作业。",
                    span=TextSpan(start=0, end=29),
                )
            ],
            content_hash="psych-doc-1-hash",
        )

        resolved = resolver.resolve(documents=[record], metadata={})

        self.assertEqual(resolved.family_id, "cbt")
        self.assertEqual(resolved.family_name, "认知行为疗法")
        self.assertEqual(resolved.source, "rule")
        self.assertGreater(resolved.confidence, 0.5)

    def test_taxonomy_rejects_explicit_family_outside_configured_candidates(self) -> None:
        taxonomy = load_skill_taxonomy(domain_type="psychology")

        with self.assertRaises(ValueError):
            taxonomy.ensure_configured_family_candidate(requested="不存在的流派")

    def test_family_resolver_uses_taxonomy_default_when_signal_is_weak(self) -> None:
        taxonomy = load_skill_taxonomy(domain_type="psychology")
        resolver = build_document_family_resolver(taxonomy=taxonomy)
        record = DocumentRecord(
            doc_id="psych-doc-weak",
            source_type="markdown_document",
            title="General counseling notes",
            domain="psychology",
            raw_text="This paper discusses broad counseling process factors without naming a specific school.",
            sections=[],
            content_hash="psych-doc-weak-hash",
        )

        resolved = resolver.resolve(documents=[record], metadata={})

        self.assertEqual(resolved.family_name, "通用心理咨询")
        self.assertEqual(resolved.family_id, "")
        self.assertEqual(resolved.source, "default")

    def test_family_resolver_keeps_default_family_id_when_default_matches_candidate(self) -> None:
        payload = """
{
  "taxonomy_id": "demo_family",
  "domain_type": "demo",
  "display_name": "Demo",
  "default_family_name": "通用流程",
  "family_candidates": [
    {
      "id": "general_process",
      "name": "General Process（通用流程）",
      "visible_name": "通用流程",
      "aliases": ["general process", "通用流程"]
    },
    {
      "id": "specialized_process",
      "name": "Specialized Process（专项流程）",
      "visible_name": "专项流程",
      "aliases": ["specialized process", "专项流程"]
    }
  ]
}
""".strip()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "taxonomy.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
            taxonomy = load_skill_taxonomy(domain_type="demo", taxonomy_path=path)
        resolver = build_document_family_resolver(taxonomy=taxonomy)
        record = DocumentRecord(
            doc_id="demo-doc-weak",
            source_type="markdown_document",
            title="General notes",
            domain="demo",
            raw_text="This text does not contain strong signals for a specific family.",
            sections=[],
            content_hash="demo-doc-weak-hash",
        )

        resolved = resolver.resolve(documents=[record], metadata={})

        self.assertEqual(resolved.family_name, "通用流程")
        self.assertEqual(resolved.family_id, "general_process")
        self.assertEqual(resolved.source, "default")

    def test_family_resolver_falls_back_to_default_when_llm_times_out(self) -> None:
        taxonomy = load_skill_taxonomy(domain_type="psychology")

        class BrokenLLM:
            def complete(self, *, system=None, user="", temperature=0.0):
                raise TimeoutError("upstream timeout")

        resolver = build_document_family_resolver(taxonomy=taxonomy, llm=BrokenLLM())
        record = DocumentRecord(
            doc_id="psych-doc-llm-timeout",
            source_type="markdown_document",
            title="General counseling notes",
            domain="psychology",
            raw_text="This text does not contain strong signals for a specific family.",
            sections=[],
            content_hash="psych-doc-llm-timeout-hash",
        )

        resolved = resolver.resolve(documents=[record], metadata={}, allow_llm=True)

        self.assertEqual(resolved.family_name, "通用心理咨询")
        self.assertEqual(resolved.source, "default")

    def test_custom_taxonomy_path_overrides_aliases(self) -> None:
        payload = """
{
  "taxonomy_id": "geo_custom",
  "domain_type": "geography",
  "display_name": "Geography",
  "default_base_type": "knowledge_reference",
  "asset_types": [
    {
      "base_type": "session_skill",
      "label": "field_workflow",
      "description": "One reusable field workflow.",
      "aliases": ["field_workflow", "survey_workflow"]
    }
  ]
}
""".strip()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "taxonomy.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
            taxonomy = load_skill_taxonomy(domain_type="geography", taxonomy_path=path)

        self.assertEqual(taxonomy.taxonomy_id, "geo_custom")
        self.assertEqual(taxonomy.domain_type, "geography")
        self.assertEqual(taxonomy.normalize_asset_type("field_workflow"), "session_skill")
        self.assertEqual(taxonomy.normalize_asset_type(""), "knowledge_reference")
        self.assertEqual(taxonomy.derive_profile_id(family_name="地理专题"), "geo_custom::地理专题")

    def test_prompt_includes_domain_type_guidance(self) -> None:
        taxonomy = load_skill_taxonomy(domain_type="psychology")
        prompt = build_offline_extract_prompt(
            channel=OFFLINE_CHANNEL_DOC,
            max_candidates=2,
            taxonomy=taxonomy,
        )

        self.assertIn("Domain type is externally provided as `psychology`", prompt)
        self.assertIn("Do not infer or output domain_type", prompt)
        self.assertIn("session_intervention -> session_skill", prompt)

    def test_extractor_normalizes_taxonomy_alias_into_stable_asset_type(self) -> None:
        record = DocumentRecord(
            doc_id="chem-doc-1",
            source_type="markdown_document",
            title="TLC Notes",
            domain="chemistry",
            raw_text="# Analysis\nRun a TLC workflow.\n",
            sections=[
                DocumentSection(
                    heading="Analysis",
                    text="Run a TLC workflow with plate prep, spotting, development, and reading.",
                    span=TextSpan(start=0, end=72),
                )
            ],
            content_hash="chem-doc-1-hash",
        )
        windows = build_windows_for_record(record=record, strategy="strict")
        extractor = build_document_skill_extractor(
            "llm",
            llm=MockLLM(response=_chemistry_extract_response),
            domain_type="chemistry",
        )

        result = extract_skills(documents=[record], windows=windows, extractor=extractor)

        self.assertEqual(len(result.skill_drafts), 1)
        draft = result.skill_drafts[0]
        self.assertEqual(draft.asset_type, "session_skill")
        self.assertEqual(draft.asset_node_id, "experiment_workflow")
        self.assertEqual(draft.asset_level, 2)
        self.assertEqual(draft.asset_path, "family_root/experiment_protocol/experiment_workflow")
        self.assertEqual(draft.metadata.get("domain_type"), "chemistry")
        self.assertEqual(draft.metadata.get("taxonomy_id"), "chemistry")

    def test_extractor_drops_unknown_asset_type_in_strict_taxonomy_mode(self) -> None:
        record = DocumentRecord(
            doc_id="chem-doc-invalid-type",
            source_type="markdown_document",
            title="Invalid TLC Notes",
            domain="chemistry",
            raw_text="# Analysis\nRun a TLC workflow.\n",
            sections=[
                DocumentSection(
                    heading="Analysis",
                    text="Run a TLC workflow with plate prep, spotting, development, and reading.",
                    span=TextSpan(start=0, end=72),
                )
            ],
            content_hash="chem-doc-invalid-type-hash",
        )
        windows = build_windows_for_record(record=record, strategy="strict")
        extractor = build_document_skill_extractor(
            "llm",
            llm=MockLLM(
                response=json.dumps(
                    {
                        "skills": [
                            {
                                "name": "TLC analysis workflow",
                                "description": "Run a thin-layer chromatography analysis workflow.",
                                "prompt": "# Goal\nRun the TLC workflow.\n\n# Core Workflow\n1. Prepare the plate.\n2. Spot the sample.",
                                "asset_type": "invalid_new_type",
                                "granularity": "session",
                                "objective": "Run a TLC analysis workflow.",
                                "domain": "chemistry",
                                "task_family": "analysis",
                                "method_family": "tlc",
                                "stage": "analysis",
                                "workflow_steps": ["Prepare the plate.", "Spot the sample."],
                                "constraints": ["Use the configured solvent system."],
                                "relation_type": "support",
                                "risk_class": "low",
                                "confidence": 0.9,
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            ),
            domain_type="chemistry",
        )

        result = extract_skills(documents=[record], windows=windows, extractor=extractor)

        self.assertEqual(result.skill_drafts, [])
        self.assertEqual(result.support_records, [])
