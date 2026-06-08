from __future__ import annotations

import json
import os
import tempfile
import time
import threading
import unittest

from autoskill import AutoSkill, AutoSkillConfig
from autoskill.llm.base import LLM
from AutoSkill4Doc.core.rate_limit import AUTOSKILL4DOC_LLM_SCOPE, maybe_wrap_llm_with_rate_limit
from AutoSkill4Doc.stages.compiler import _identity_key_for_skill, build_skill_compiler, compile_skills
from AutoSkill4Doc.stages.extractor import build_document_skill_extractor, extract_skills
from AutoSkill4Doc.extract import extract_from_doc
from AutoSkill4Doc.models import DocumentRecord, DocumentSection, SkillDraft, SupportRecord, SupportRelation, TextSpan, VersionState
from AutoSkill4Doc.pipeline import build_default_document_pipeline
from AutoSkill4Doc.core.config import DEFAULT_DOC_SKILL_USER_ID
from AutoSkill4Doc.prompts import OFFLINE_CHANNEL_DOC, build_offline_extract_prompt
from AutoSkill4Doc.store.intermediate import IntermediateRunWriter
from AutoSkill4Doc.store.layout import intermediate_runs_root
from AutoSkill4Doc.store.staging import safe_dir_component


_DOC_TEXT = """
# Intake
1. Build rapport before deeper intervention.
2. Clarify the client's immediate concern.

# Constraints
Do not push interpretation before the client is ready.
Always check for acute risk before intensive exploration.

# Output
Output a short session direction summary.
""".strip()


def _default_document_skill_payload(*, document: dict[str, object], excerpt: str, name: str | None = None) -> dict[str, object]:
    """Builds one reusable default skill payload for document extraction tests."""

    return {
        "name": name or f"{document.get('domain') or 'document'} intake workflow",
        "description": "Reusable workflow extracted from the document.",
        "prompt": (
            "# Role & Objective\n"
            "Guide the operator through the reusable workflow.\n\n"
            "# Rules & Constraints\n"
            "- Keep the process safe and structured.\n\n"
            "# Core Workflow\n"
            "1. Build rapport first.\n"
            "2. Clarify the immediate concern.\n"
            "3. Check acute risk before deeper exploration.\n\n"
            "# Output Format\n"
            "- Output a short session direction summary."
        ),
        "asset_type": "session_skill",
        "granularity": "session",
        "objective": "Run a structured first-session intake.",
        "domain": document.get("domain") or "psychology",
        "task_family": "intake",
        "method_family": "structured_interview",
        "stage": "intake",
        "applicable_signals": [
            "When the client is entering an initial consultation.",
        ],
        "intervention_moves": [
            "Reflect the client's main concern before moving deeper.",
        ],
        "contraindications": [
            "Do not skip acute risk screening when crisis cues are present.",
        ],
        "workflow_steps": [
            "Build rapport first.",
            "Clarify the immediate concern.",
            "Check acute risk before deeper exploration.",
        ],
        "constraints": [
            "Keep the process safe and structured.",
        ],
        "cautions": [
            "Avoid intensive interpretation too early.",
        ],
        "output_contract": [
            "Output a short session direction summary.",
        ],
        "examples": [
            {
                "input": "Client says they feel overwhelmed and do not know where to start.",
                "output": "Reflect the overwhelm first, then ask for the most urgent concern to focus the session.",
                "notes": "Use a calm, non-rushing tone.",
            }
        ],
        "relation_type": "conflict" if "do not" in excerpt.lower() else "support",
        "risk_class": "medium",
        "triggers": [
            "When starting intake",
            "When clarifying a first session",
            "When documenting session direction",
        ],
        "tags": ["psychology", "intake", "workflow"],
        "confidence": 0.92,
    }


def _document_llm_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
    _ = system, temperature
    if mode == "document_extract":
        payload = json.loads(user)
        document = payload.get("document", {})
        excerpt = str(payload.get("excerpt") or "").strip()
        candidate = payload.get("candidate")
        if isinstance(candidate, dict):
            return json.dumps(
                {
                    "skill": _default_document_skill_payload(
                        document=document,
                        excerpt=excerpt,
                        name=str(candidate.get("name") or "").strip() or None,
                    )
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "skills": [
                    {
                        "slot": 1,
                        "name": f"{document.get('domain') or 'document'} intake workflow",
                        "description": "Reusable workflow for first-session intake and safety framing.",
                        "asset_type": "session_skill",
                        "granularity": "session",
                        "objective": "Run a structured first-session intake.",
                        "domain": document.get("domain") or "psychology",
                        "task_family": "intake",
                        "method_family": "structured_interview",
                        "stage": "intake",
                        "why_distinct": "The excerpt supports one reusable intake workflow.",
                        "confidence": 0.92,
                    }
                ]
            },
            ensure_ascii=False,
        )
    if mode == "document_compile":
        payload = json.loads(user)
        drafts = list(payload.get("drafts") or [])
        first = drafts[0]
        support_ids: list[str] = []
        for draft in drafts:
            support_ids.extend(list(draft.get("support_ids") or []))
        return json.dumps(
            {
                "skills": [
                    {
                        "name": first.get("name") or "document intake workflow",
                        "description": "Canonical reusable workflow compiled from document drafts.",
                        "prompt": first.get("metadata", {}).get("prompt") or first.get("name") or "prompt",
                        "asset_type": first.get("asset_type") or "session_skill",
                        "granularity": first.get("granularity") or "session",
                        "objective": first.get("objective") or first.get("description") or "objective",
                        "domain": first.get("domain") or "psychology",
                        "task_family": first.get("task_family") or "intake",
                        "method_family": first.get("method_family") or "structured_interview",
                        "stage": first.get("stage") or "intake",
                        "applicable_signals": first.get("applicable_signals") or [],
                        "intervention_moves": first.get("intervention_moves") or [],
                        "contraindications": first.get("contraindications") or [],
                        "triggers": first.get("triggers") or [],
                        "workflow_steps": first.get("workflow_steps") or [],
                        "constraints": first.get("constraints") or [],
                        "cautions": first.get("cautions") or [],
                        "output_contract": first.get("output_contract") or [],
                        "examples": first.get("examples") or [],
                        "tags": first.get("metadata", {}).get("tags") or ["psychology", "intake"],
                        "confidence": 0.9,
                        "risk_class": first.get("risk_class") or "medium",
                        "support_ids": support_ids,
                        "source_draft_ids": [draft.get("draft_id") for draft in drafts],
                    }
                ]
            },
            ensure_ascii=False,
        )
    if mode == "document_version":
        payload = json.loads(user)
        candidate = payload.get("candidate_skill") or {}
        existing = list(payload.get("existing_skills") or [])
        if not existing:
            return json.dumps({"action": "create", "target_skill_ids": [], "reason": "new skill"}, ensure_ascii=False)
        target = existing[0]
        action = "strengthen"
        candidate_steps = list(candidate.get("workflow_steps") or [])
        target_steps = list(target.get("workflow_steps") or [])
        if len(candidate_steps) > len(target_steps):
            action = "revise"
        return json.dumps(
            {
                "action": action,
                "target_skill_ids": [target.get("skill_id")],
                "reason": action,
                "resolved_skill": candidate,
            },
            ensure_ascii=False,
        )
    if mode == "document_conflict":
        return json.dumps({"action": "keep", "reason": "no conflict review needed"}, ensure_ascii=False)
    return json.dumps({"skills": []}, ensure_ascii=False)


class CountingExtractor:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def extract(self, **kwargs):
        self.calls += 1
        return self.delegate.extract(**kwargs)


class CountingCompiler:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def compile(self, **kwargs):
        self.calls += 1
        return self.delegate.compile(**kwargs)


class FailOnceCompiler:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def compile(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("compile interrupted")
        return self.delegate.compile(**kwargs)


class TimestampLLM(LLM):
    def __init__(self, timestamps: list[float]) -> None:
        self.timestamps = timestamps

    def complete(self, *, system, user, temperature: float = 0.0) -> str:
        _ = system, user, temperature
        self.timestamps.append(time.monotonic())
        return "{}"


class FailThenSucceedLLM(LLM):
    def __init__(self, failures: int, message: str, timestamps: list[float]) -> None:
        self.failures = int(failures or 0)
        self.message = str(message or "")
        self.timestamps = timestamps

    def complete(self, *, system, user, temperature: float = 0.0) -> str:
        _ = system, user, temperature
        self.timestamps.append(time.monotonic())
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError(self.message)
        return "{}"


class DocumentPipelineTest(unittest.TestCase):
    def _build_sdk(self, *, store_path: str) -> AutoSkill:
        return AutoSkill(
            AutoSkillConfig(
                llm={"provider": "mock", "response": _document_llm_response, "allow_mock": True},
                embeddings={"provider": "hashing", "dims": 64},
                store={"provider": "local", "path": store_path},
                maintenance_strategy="heuristic",
            )
        )

    def test_full_build_persists_registry_and_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            logs: list[str] = []
            pipeline = build_default_document_pipeline(sdk=sdk, logger=logs.append)

            result = pipeline.build(
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )

            self.assertEqual(len(result.ingest.documents), 1)
            self.assertGreater(len(result.extracted.support_records), 0)
            self.assertGreater(len(result.extracted.skill_drafts), 0)
            self.assertEqual(len(result.extracted.documents), 1)
            self.assertGreaterEqual(len(result.extracted.windows), 1)
            self.assertGreater(len(result.compiled.skill_specs), 0)
            self.assertGreater(len(result.registration.lifecycles), 0)
            self.assertGreaterEqual(len(result.registration.upserted_store_skills), 1)
            self.assertEqual(pipeline.registry.manifest()["entities"]["documents"]["count"], 1)
            self.assertGreaterEqual(pipeline.registry.manifest()["entities"]["supports"]["count"], 1)
            self.assertGreaterEqual(pipeline.registry.manifest()["entities"]["skills"]["count"], 1)
            stored_skills = sdk.store.list(user_id="u1")
            self.assertGreaterEqual(len(stored_skills), 1)
            self.assertIn("## Applicable Signals", stored_skills[0].instructions)
            self.assertIn("## Example Therapist Responses", stored_skills[0].instructions)
            self.assertGreaterEqual(len(stored_skills[0].examples), 1)
            self.assertTrue(os.path.isdir(result.intermediate.get("run_dir", "")))
            status_path = os.path.join(result.intermediate["run_dir"], "status.json")
            self.assertTrue(os.path.isfile(status_path))
            self.assertTrue(os.path.isfile(os.path.join(result.intermediate["run_dir"], "ingest", "result.json")))
            self.assertTrue(os.path.isfile(os.path.join(result.intermediate["run_dir"], "extract", "result.json")))
            self.assertTrue(os.path.isfile(os.path.join(result.intermediate["run_dir"], "compile", "result.json")))
            self.assertTrue(os.path.isfile(os.path.join(result.intermediate["run_dir"], "register", "result.json")))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        result.intermediate["run_dir"],
                        "extract",
                        "documents",
                        f"{result.ingest.documents[0].doc_id}.json",
                    )
                )
            )
            with open(status_path, "r", encoding="utf-8") as f:
                status_payload = json.load(f)
            self.assertEqual(status_payload.get("metadata", {}).get("domain_root_name"), "心理咨询")
            self.assertEqual(status_payload.get("metadata", {}).get("family_name"), "通用心理咨询")
            self.assertTrue(any("[ingest_document]" in line for line in logs))
            self.assertTrue(any("[extract_skills]" in line for line in logs))

    def test_pipeline_build_rejects_mock_provider_without_explicit_allowance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = AutoSkill(
                AutoSkillConfig(
                    llm={"provider": "mock", "response": _document_llm_response},
                    embeddings={"provider": "hashing", "dims": 64},
                    store={"provider": "local", "path": tmpdir},
                    maintenance_strategy="heuristic",
                )
            )
            pipeline = build_default_document_pipeline(sdk=sdk)

            with self.assertRaises(SystemExit):
                pipeline.build(
                    data=_DOC_TEXT,
                    title="Intake Workflow",
                    domain="psychology",
                    metadata={"channel": "offline_extract_from_doc"},
                    dry_run=True,
                )

    def test_resolve_run_metadata_falls_back_to_default_family_for_mixed_rule_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            cbt_doc = DocumentRecord(
                doc_id="doc-cbt",
                source_type="markdown_document",
                title="CBT automatic thought worksheet",
                domain="psychology",
                raw_text="# 自动思维\n使用 ABC 记录表识别自动思维。\n",
                sections=[],
                content_hash="cbt-hash",
            )
            pd_doc = DocumentRecord(
                doc_id="doc-pd",
                source_type="markdown_document",
                title="Psychodynamic transference interpretation",
                domain="psychology",
                raw_text="# 移情\n围绕移情与防御机制进行解释。\n",
                sections=[],
                content_hash="pd-hash",
            )

            metadata = pipeline.resolve_run_metadata(
                documents=[cbt_doc, pd_doc],
                metadata={"channel": "offline_extract_from_doc", "domain_type": "psychology"},
            )

            self.assertEqual(metadata.get("family_name"), "通用心理咨询")
            self.assertEqual(metadata.get("family_source"), "mixed_rule")
            self.assertEqual(
                sorted(list(metadata.get("family_candidates_detected") or [])),
                ["心理动力学", "认知行为疗法"],
            )

    def test_build_default_pipeline_propagates_llm_rate_limit_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(
                sdk=sdk,
                llm_rate_limit_requests=2000,
                llm_rate_limit_window_s=300.0,
            )

            self.assertEqual(pipeline.llm_rate_limit_requests, 2000)
            self.assertAlmostEqual(pipeline.llm_rate_limit_window_s, 300.0)
            self.assertEqual(getattr(pipeline.document_ingestor, "llm_rate_limit_requests", 0), 2000)
            self.assertEqual(getattr(pipeline.document_skill_extractor, "llm_rate_limit_requests", 0), 2000)
            self.assertEqual(getattr(pipeline.skill_compiler, "llm_rate_limit_requests", 0), 2000)

    def test_shared_llm_rate_limiter_throttles_across_wrappers(self) -> None:
        timestamps: list[float] = []
        wrapped_a = maybe_wrap_llm_with_rate_limit(
            TimestampLLM(timestamps),
            max_requests=1,
            window_s=0.2,
            llm_config={"provider": "test", "model": "unit"},
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
        wrapped_b = maybe_wrap_llm_with_rate_limit(
            TimestampLLM(timestamps),
            max_requests=1,
            window_s=0.2,
            llm_config={"provider": "test", "model": "unit"},
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
        self.assertIsNotNone(wrapped_a)
        self.assertIsNotNone(wrapped_b)

        threads = [
            threading.Thread(target=wrapped_a.complete, kwargs={"system": None, "user": "a"}),
            threading.Thread(target=wrapped_b.complete, kwargs={"system": None, "user": "b"}),
        ]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(timestamps), 2)
        self.assertGreaterEqual(max(timestamps) - min(timestamps), 0.16)
        self.assertGreaterEqual(time.monotonic() - started, 0.16)

    def test_shared_llm_rate_limiter_auto_cools_down_after_retryable_error(self) -> None:
        timestamps: list[float] = []
        wrapped_error = maybe_wrap_llm_with_rate_limit(
            FailThenSucceedLLM(1, "429 too many requests retry after 0.2s", timestamps),
            llm_config={"provider": "test", "model": "unit"},
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
        wrapped_success = maybe_wrap_llm_with_rate_limit(
            TimestampLLM(timestamps),
            llm_config={"provider": "test", "model": "unit"},
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )

        with self.assertRaises(RuntimeError):
            wrapped_error.complete(system=None, user="first")

        started = time.monotonic()
        wrapped_success.complete(system=None, user="second")
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.16)

    def test_intermediate_extract_progress_uses_safe_doc_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)

            result = pipeline.build(
                user_id=DEFAULT_DOC_SKILL_USER_ID,
                data={
                    "doc_id": "folder/doc:1",
                    "title": "Safe File Name",
                    "raw_text": _DOC_TEXT,
                },
                title="Safe File Name",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )

            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        result.intermediate["run_dir"],
                        "extract",
                        "documents",
                        f"{safe_dir_component('folder/doc:1')}.json",
                    )
                )
            )

    def test_incremental_build_skips_unchanged_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)

            first = pipeline.build(
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )
            second = pipeline.build(
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )

            self.assertEqual(len(first.ingest.documents), 1)
            self.assertEqual(len(second.ingest.documents), 0)
            self.assertEqual(len(second.ingest.skipped_documents), 1)
            self.assertEqual(len(second.registration.skill_specs), 0)

    def test_dry_run_does_not_persist_registry_or_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)

            result = pipeline.build(
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
                dry_run=True,
            )

            manifest = pipeline.registry.manifest()
            self.assertTrue(result.dry_run)
            self.assertGreaterEqual(len(result.registration.lifecycles), 0)
            self.assertEqual(manifest["entities"]["documents"]["count"], 0)
            self.assertEqual(manifest["entities"]["skills"]["count"], 0)
            self.assertEqual(len(sdk.store.list(user_id="u1")), 0)
            self.assertEqual(result.intermediate, {})
            self.assertFalse(os.path.isdir(intermediate_runs_root(tmpdir)))

    def test_full_build_writes_visible_parent_child_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)

            result = pipeline.build(
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={
                    "channel": "offline_extract_from_doc",
                    "family_name": "认知行为疗法",
                    "profile_id": "test_therapy_v2",
                    "taxonomy_axis": "疗法",
                },
            )

            parent_md = result.registration.visible_tree["parent_paths"][0]
            child_root = os.path.dirname(os.path.dirname(result.registration.visible_tree["child_paths"][0]))
            self.assertTrue(os.path.isfile(parent_md))
            self.assertTrue(os.path.isdir(child_root))
            self.assertTrue(result.registration.visible_tree.get("parent_paths"))
            self.assertTrue(result.registration.visible_tree.get("child_paths"))
            self.assertGreaterEqual(len(list(result.registration.staging_runs or [])), 1)

    def test_extract_from_doc_returns_stage_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)

            result = extract_from_doc(
                sdk=sdk,
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
                dry_run=True,
            )

            self.assertEqual(result["total_documents"], 1)
            self.assertGreaterEqual(result["total_windows"], 1)
            self.assertGreater(result["total_support_records"], 0)
            self.assertGreater(result["total_skill_drafts"], 0)
            self.assertGreater(result["total_skill_specs"], 0)
            self.assertEqual(result["upserted_count"], 0)
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["skills"][0]["asset_type"], "session_skill")
            self.assertEqual(result["skills"][0]["granularity"], "session")
            self.assertEqual(result["intermediate"], {})

    def test_extract_from_doc_uses_internal_default_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)

            result = extract_from_doc(
                sdk=sdk,
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
                dry_run=False,
            )

            self.assertEqual(result["total_documents"], 1)
            self.assertGreaterEqual(len(sdk.store.list(user_id=DEFAULT_DOC_SKILL_USER_ID)), 1)

    def test_extract_from_doc_derives_profile_and_axis_from_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)

            result = extract_from_doc(
                sdk=sdk,
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                domain_type="psychology",
                family_name="认知行为疗法",
                dry_run=False,
            )

            self.assertEqual(result["visible_tree"]["affected_families"], ["认知行为疗法"])
            manifest_path = os.path.join(tmpdir, ".runtime", "library_manifest.json")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertEqual(manifest.get("active_family_name"), "认知行为疗法")
            self.assertEqual(manifest.get("active_profile_id"), "psychology::认知行为疗法")

    def test_document_build_result_dict_includes_windows_and_compiled_supports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)

            result = pipeline.build(
                user_id="u1",
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
                dry_run=True,
            )
            payload = result.to_dict()

            self.assertGreaterEqual(payload["windows"], 1)
            self.assertEqual(payload["support_records"], len(result.compiled.support_records))
            self.assertEqual(payload["skill_specs"], len(result.compiled.skill_specs))
            self.assertIn("staging_runs", payload)

    def test_document_prompt_requires_multi_asset_single_goal_extraction(self) -> None:
        prompt = build_offline_extract_prompt(channel=OFFLINE_CHANNEL_DOC, max_candidates=3)

        self.assertIn("FIRST plan how many reusable assets", prompt)
        self.assertIn("One document may produce zero, one, or MANY assets", prompt)
        self.assertIn("single-goal", prompt)
        self.assertIn("description (1-2 short sentences", prompt)
        self.assertIn("asset_type (macro_protocol|session_skill|micro_skill|safety_rule|knowledge_reference)", prompt)
        self.assertIn("never merge macro and micro assets", prompt)
        self.assertIn("micro_skill means one therapist move", prompt)
        self.assertIn("Be conservative", prompt)
        self.assertIn("task_family/method_family/stage should use compact reusable labels", prompt)
        self.assertIn("If the text is mainly case narrative", prompt)

    def test_identity_key_distinguishes_macro_and_micro_assets(self) -> None:
        macro = _identity_key_for_skill(
            asset_type="macro_protocol",
            granularity="macro",
            asset_node_id="treatment_framework",
            objective="Run a full intake protocol.",
            domain="psychology",
            task_family="assessment",
            method_family="cbt",
            stage="intake",
            name="intake protocol",
        )
        micro = _identity_key_for_skill(
            asset_type="micro_skill",
            granularity="micro",
            asset_node_id="micro_intervention",
            objective="Deliver one empathic reflection.",
            domain="psychology",
            task_family="assessment",
            method_family="cbt",
            stage="intake",
            name="intake protocol",
        )

        self.assertNotEqual(macro, micro)

    def test_identity_key_distinguishes_same_skill_across_families(self) -> None:
        cbt = _identity_key_for_skill(
            asset_type="session_skill",
            granularity="session",
            asset_node_id="session_framework",
            objective="Run a structured first-session intake.",
            domain="psychology",
            task_family="assessment",
            method_family="cbt",
            stage="intake",
            name="首次咨询结构化摄入会谈流程",
            taxonomy_id="psychology",
            profile_id="psychology::认知行为疗法",
            family_scope="cbt",
        )
        psychodynamic = _identity_key_for_skill(
            asset_type="session_skill",
            granularity="session",
            asset_node_id="session_framework",
            objective="Run a structured first-session intake.",
            domain="psychology",
            task_family="assessment",
            method_family="cbt",
            stage="intake",
            name="首次咨询结构化摄入会谈流程",
            taxonomy_id="psychology",
            profile_id="psychology::Psychodynamic（心理动力学）",
            family_scope="psychodynamic",
        )

        self.assertNotEqual(cbt, psychodynamic)

    def test_short_section_is_used_as_default_extraction_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            text = """
# Intake
Build rapport before deeper intervention.

Clarify the client's immediate concern and summarize the goal for this session.
""".strip()

            ingest_result = pipeline.ingest_document(
                data=text,
                title="Short Intake Section",
                domain="psychology",
                dry_run=True,
            )
            extracted = pipeline.extract_skills(documents=ingest_result.documents)

            self.assertEqual(len(ingest_result.documents), 1)
            self.assertEqual(len(extracted.support_records), 1)
            self.assertEqual(extracted.support_records[0].metadata.get("extraction_unit"), "section")

    def test_compile_assigns_different_skill_ids_for_same_content_in_different_families(self) -> None:
        compiler = build_skill_compiler(llm_config={"provider": "mock", "response": _document_llm_response})
        support = SupportRecord(
            support_id="sup-1",
            doc_id="doc-1",
            source_file="/tmp/doc-1.md",
            section="Method",
            span=TextSpan(start=0, end=32),
            excerpt="Build rapport first and clarify the goal.",
            relation_type=SupportRelation.SUPPORT,
            confidence=0.9,
        )
        common = {
            "name": "首次咨询结构化摄入会谈流程",
            "description": "A reusable intake workflow.",
            "asset_type": "session_skill",
            "granularity": "session",
            "asset_node_id": "session_framework",
            "asset_path": "family_root/treatment_framework/session_framework",
            "asset_level": 2,
            "visible_role": "parent",
            "objective": "Run a structured first-session intake.",
            "domain": "psychology",
            "task_family": "assessment",
            "method_family": "cbt",
            "stage": "intake",
            "workflow_steps": ["建立议程。", "明确问题。", "风险检查。", "总结安排。"],
            "support_ids": ["sup-1"],
            "confidence": 0.9,
        }
        draft_a = SkillDraft(
            draft_id="draft-a",
            doc_id="doc-1",
            metadata={
                "taxonomy_id": "psychology",
                "profile_id": "psychology::认知行为疗法",
                "family_id": "cbt",
                "family_name": "认知行为疗法",
            },
            **common,
        )
        draft_b = SkillDraft(
            draft_id="draft-b",
            doc_id="doc-1",
            metadata={
                "taxonomy_id": "psychology",
                "profile_id": "psychology::Psychodynamic（心理动力学）",
                "family_id": "psychodynamic",
                "family_name": "Psychodynamic（心理动力学）",
            },
            **common,
        )

        compiled = compile_skills(
            skill_drafts=[draft_a, draft_b],
            support_records=[support],
            compiler=compiler,
            target_state=VersionState.ACTIVE,
        )

        self.assertEqual(2, len(compiled.skill_specs))
        self.assertEqual(2, len({spec.skill_id for spec in compiled.skill_specs}))

    def test_pipeline_extract_uses_ingest_windows_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            text = """
# Intake
Build rapport before deeper intervention.

Clarify the client's immediate concern and summarize the goal for this session.
""".strip()

            ingest_result = pipeline.ingest_document(
                data=text,
                title="Window Driven Intake",
                domain="psychology",
                dry_run=True,
            )
            extracted = pipeline.extract_skills(
                documents=ingest_result.documents,
                windows=ingest_result.windows,
            )

            self.assertEqual(len(ingest_result.windows), 1)
            self.assertEqual(len(extracted.support_records), 1)
            self.assertEqual(extracted.support_records[0].metadata.get("extraction_unit"), "window")
            self.assertEqual(
                extracted.support_records[0].metadata.get("window_strategy"),
                ingest_result.windows[0].strategy,
            )
            self.assertEqual(
                extracted.skill_drafts[0].metadata.get("window_id"),
                ingest_result.windows[0].window_id,
            )

    def test_long_section_falls_back_to_multiple_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            text = """
# Intake
Build rapport before deeper intervention.

Clarify the client's immediate concern and summarize the goal for this session.

Always assess acute risk before intensive exploration.

Do not push interpretation before the client is ready.
""".strip()

            ingest_result = pipeline.ingest_document(
                data=text,
                title="Long Intake Section",
                domain="psychology",
                dry_run=True,
            )
            extracted = extract_skills(
                documents=ingest_result.documents,
                extractor=build_document_skill_extractor(
                    "llm",
                    llm_config={"provider": "mock", "response": _document_llm_response},
                    max_section_chars=120,
                    overlap_chars=20,
                ),
            )

            self.assertGreater(len(extracted.support_records), 1)
            self.assertTrue(
                any(record.metadata.get("extraction_unit") == "chunk" for record in extracted.support_records)
            )

    def test_parallel_document_extraction_preserves_input_order(self) -> None:
        def _parallel_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
            _ = system, temperature
            if mode != "document_extract":
                return json.dumps({"skills": []}, ensure_ascii=False)
            payload = json.loads(user)
            title = str((payload.get("document") or {}).get("title") or "").strip()
            if title == "Doc A":
                time.sleep(0.15)
            else:
                time.sleep(0.01)
            return json.dumps(
                {
                    "skills": [
                        {
                            "name": f"{title} skill",
                            "description": f"Reusable workflow for {title}.",
                            "prompt": "# Goal\nRun the workflow.\n\n# Core Workflow\n1. Build rapport.\n2. Clarify the concern.",
                            "asset_type": "session_skill",
                            "granularity": "session",
                            "objective": f"Run the workflow for {title}.",
                            "domain": "psychology",
                            "task_family": "intake",
                            "method_family": "structured_interview",
                            "stage": "intake",
                            "workflow_steps": ["Build rapport.", "Clarify the concern."],
                            "constraints": ["Keep the process structured."],
                            "relation_type": "support",
                            "risk_class": "low",
                            "confidence": 0.9,
                        }
                    ]
                },
                ensure_ascii=False,
            )

        doc_a = DocumentRecord(
            doc_id="doc-a",
            source_type="markdown_document",
            title="Doc A",
            domain="psychology",
            raw_text="# Intake\nBuild rapport first.\n",
            sections=[
                DocumentSection(
                    heading="Intake",
                    text="Build rapport first and clarify the concern.",
                    span=TextSpan(start=0, end=43),
                )
            ],
            content_hash="doc-a-hash",
        )
        doc_b = DocumentRecord(
            doc_id="doc-b",
            source_type="markdown_document",
            title="Doc B",
            domain="psychology",
            raw_text="# Intake\nBuild rapport first.\n",
            sections=[
                DocumentSection(
                    heading="Intake",
                    text="Build rapport first and clarify the concern.",
                    span=TextSpan(start=0, end=43),
                )
            ],
            content_hash="doc-b-hash",
        )
        callback_titles: list[str] = []

        extracted = extract_skills(
            documents=[doc_a, doc_b],
            extractor=build_document_skill_extractor(
                "llm",
                llm_config={"provider": "mock", "response": _parallel_response},
                extract_workers=2,
            ),
            progress_callback=lambda record, supports, drafts, cumulative: callback_titles.append(str(record.title or "")),
        )

        self.assertEqual([draft.name for draft in extracted.skill_drafts], ["Doc A skill", "Doc B skill"])
        self.assertEqual([support.doc_id for support in extracted.support_records], ["doc-a", "doc-b"])
        self.assertEqual(callback_titles, ["Doc A", "Doc B"])

    def test_parallel_document_extraction_retries_transient_rate_limit_errors(self) -> None:
        attempts: dict[str, int] = {}
        lock = threading.Lock()

        def _retryable_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
            _ = system, temperature
            if mode != "document_extract":
                return json.dumps({"skills": []}, ensure_ascii=False)
            payload = json.loads(user)
            title = str((payload.get("document") or {}).get("title") or "").strip()
            candidate = payload.get("candidate")
            if isinstance(candidate, dict):
                return json.dumps(
                    {
                        "skill": {
                            "name": f"{title} skill",
                            "description": f"Reusable workflow for {title}.",
                            "prompt": "# Goal\nRun the workflow.\n\n# Core Workflow\n1. Build rapport.\n2. Clarify the concern.",
                            "asset_type": "session_skill",
                            "granularity": "session",
                            "objective": f"Run the workflow for {title}.",
                            "domain": "psychology",
                            "task_family": "intake",
                            "method_family": "structured_interview",
                            "stage": "intake",
                            "workflow_steps": ["Build rapport.", "Clarify the concern."],
                            "constraints": ["Keep the process structured."],
                            "relation_type": "support",
                            "risk_class": "low",
                            "confidence": 0.9,
                        }
                    },
                    ensure_ascii=False,
                )
            with lock:
                count = int(attempts.get(title, 0))
                attempts[title] = count + 1
            if count == 0:
                raise RuntimeError("429 Too Many Requests")
            return json.dumps(
                {
                    "skills": [
                        {
                            "slot": 1,
                            "name": f"{title} skill",
                            "description": f"Reusable workflow for {title}.",
                            "asset_type": "session_skill",
                            "granularity": "session",
                            "objective": f"Run the workflow for {title}.",
                            "domain": "psychology",
                            "task_family": "intake",
                            "method_family": "structured_interview",
                            "stage": "intake",
                            "why_distinct": "Single workflow in this window.",
                            "confidence": 0.9,
                        }
                    ]
                },
                ensure_ascii=False,
            )

        doc_a = DocumentRecord(
            doc_id="doc-a",
            source_type="markdown_document",
            title="Doc A",
            domain="psychology",
            raw_text="# Intake\nBuild rapport first.\n",
            sections=[
                DocumentSection(
                    heading="Intake",
                    text="Build rapport first and clarify the concern.",
                    span=TextSpan(start=0, end=43),
                )
            ],
            content_hash="doc-a-hash",
        )
        doc_b = DocumentRecord(
            doc_id="doc-b",
            source_type="markdown_document",
            title="Doc B",
            domain="psychology",
            raw_text="# Intake\nBuild rapport first.\n",
            sections=[
                DocumentSection(
                    heading="Intake",
                    text="Build rapport first and clarify the concern.",
                    span=TextSpan(start=0, end=43),
                )
            ],
            content_hash="doc-b-hash",
        )

        extracted = extract_skills(
            documents=[doc_a, doc_b],
            extractor=build_document_skill_extractor(
                "llm",
                llm_config={"provider": "mock", "response": _retryable_response},
                extract_workers=2,
                extract_retries=2,
                extract_retry_backoff_s=0.01,
            ),
        )

        self.assertEqual([draft.name for draft in extracted.skill_drafts], ["Doc A skill", "Doc B skill"])
        self.assertEqual(attempts, {"Doc A": 2, "Doc B": 2})
        self.assertEqual(extracted.errors, [])

    def test_two_stage_extraction_expands_multiple_planned_skills(self) -> None:
        calls: list[str] = []

        def _multi_skill_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
            _ = system, temperature
            if mode != "document_extract":
                return json.dumps({"skills": []}, ensure_ascii=False)
            payload = json.loads(user)
            candidate = payload.get("candidate")
            if isinstance(candidate, dict):
                name = str(candidate.get("name") or "").strip()
                calls.append(f"expand:{name}")
                if "放松" in name:
                    return json.dumps(
                        {
                            "skill": {
                                "name": "放松训练教学流程",
                                "description": "指导来访者完成放松训练。",
                                "prompt": "# Goal\n完成放松训练。\n\n# Core Workflow\n1. 说明目标。\n2. 示范呼吸放松。\n3. 复盘体验。",
                                "asset_type": "session_skill",
                                "asset_node_id": "session_framework",
                                "granularity": "session",
                                "objective": "完成一次放松训练教学。",
                                "domain": "psychology",
                                "task_family": "relaxation_training",
                                "method_family": "cbt",
                                "stage": "intervention",
                                "workflow_steps": ["说明目标。", "示范呼吸放松。", "复盘体验。"],
                                "constraints": ["保持步骤清晰。"],
                                "relation_type": "support",
                                "risk_class": "low",
                                "confidence": 0.9,
                            }
                        },
                        ensure_ascii=False,
                    )
                return json.dumps(
                    {
                        "skill": {
                            "name": "焦虑等级表建构微技能",
                            "description": "帮助来访者建构焦虑等级表。",
                            "prompt": "# Goal\n建构焦虑等级表。\n\n# Core Workflow\n1. 列出场景。\n2. 按强度排序。",
                            "asset_type": "micro_skill",
                            "asset_node_id": "micro_intervention",
                            "granularity": "micro",
                            "objective": "完成焦虑等级表建构。",
                            "domain": "psychology",
                            "task_family": "hierarchy_building",
                            "method_family": "cbt",
                            "stage": "intervention",
                            "workflow_steps": ["列出场景。", "按强度排序。"],
                            "constraints": ["聚焦一个任务。"],
                            "relation_type": "support",
                            "risk_class": "low",
                            "confidence": 0.9,
                        }
                    },
                    ensure_ascii=False,
                )
            calls.append("plan")
            return json.dumps(
                {
                    "skills": [
                        {
                            "slot": 1,
                            "name": "放松训练教学流程",
                            "description": "指导来访者完成一次结构化放松训练。",
                            "asset_type": "session_skill",
                            "asset_node_id": "session_framework",
                            "granularity": "session",
                            "objective": "完成一次放松训练教学。",
                            "task_family": "relaxation_training",
                            "method_family": "cbt",
                            "stage": "intervention",
                            "why_distinct": "这是独立的会谈流程。",
                        },
                        {
                            "slot": 2,
                            "name": "焦虑等级表建构微技能",
                            "description": "帮助来访者列出并排序焦虑场景。",
                            "asset_type": "micro_skill",
                            "asset_node_id": "micro_intervention",
                            "granularity": "micro",
                            "objective": "完成焦虑等级表建构。",
                            "task_family": "hierarchy_building",
                            "method_family": "cbt",
                            "stage": "intervention",
                            "why_distinct": "这是不同目标的微干预。",
                        },
                    ]
                },
                ensure_ascii=False,
            )

        record = DocumentRecord(
            doc_id="doc-multi",
            source_type="markdown_document",
            title="Doc Multi",
            domain="psychology",
            raw_text="# Intervention\n1. 教放松。\n2. 建构焦虑等级表。\n",
            sections=[
                DocumentSection(
                    heading="Intervention",
                    text="先进行放松训练，再帮助来访者建构焦虑等级表。",
                    span=TextSpan(start=0, end=28),
                )
            ],
            content_hash="doc-multi-hash",
        )

        extracted = extract_skills(
            documents=[record],
            extractor=build_document_skill_extractor(
                "llm",
                llm_config={"provider": "mock", "response": _multi_skill_response},
            ),
        )

        self.assertEqual(calls, ["plan", "expand:放松训练教学流程", "expand:焦虑等级表建构微技能"])
        self.assertEqual(
            [draft.name for draft in extracted.skill_drafts],
            ["放松训练教学流程", "焦虑等级表建构微技能"],
        )
        self.assertEqual(len(extracted.support_records), 2)

    def test_two_stage_extraction_uses_planner_contract_hints_as_fallback(self) -> None:
        def _contract_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
            _ = system, temperature
            if mode != "document_extract":
                return json.dumps({"skills": []}, ensure_ascii=False)
            payload = json.loads(user)
            candidate = payload.get("candidate")
            if isinstance(candidate, dict):
                return json.dumps(
                    {
                        "skill": {
                            "name": "结构化抑郁评估流程",
                            "description": "完成一次结构化抑郁评估。",
                            "prompt": "# Goal\n完成抑郁评估。\n\n# Core Workflow\n1. 明确主诉。\n2. 评估症状严重度。\n3. 汇总结论。",
                            "asset_type": "session_skill",
                            "asset_node_id": "session_framework",
                            "granularity": "session",
                            "objective": "完成一次结构化抑郁评估。",
                            "domain": "psychology",
                            "task_family": "assessment",
                            "method_family": "structured_interview",
                            "stage": "assessment",
                            "workflow_steps": ["明确主诉。", "评估症状严重度。", "汇总结论。"],
                            "constraints": ["保持访谈结构化。"],
                            "relation_type": "support",
                            "risk_class": "low",
                            "confidence": 0.9,
                        }
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "skills": [
                        {
                            "slot": 1,
                            "name": "结构化抑郁评估流程",
                            "description": "对抑郁相关主诉进行一次结构化评估。",
                            "asset_type": "session_skill",
                            "asset_node_id": "session_framework",
                            "granularity": "session",
                            "objective": "完成一次结构化抑郁评估。",
                            "task_family": "assessment",
                            "method_family": "structured_interview",
                            "stage": "assessment",
                            "use_when": ["来访者呈现持续情绪低落或兴趣减退。"],
                            "do_not_use_when": ["存在急性自杀危机且需先进入危机分流。"],
                            "success_artifact": "形成结构化评估结论与下一步建议。",
                            "why_distinct": "这是独立的评估工作流。",
                        }
                    ]
                },
                ensure_ascii=False,
            )

        record = DocumentRecord(
            doc_id="doc-contract",
            source_type="markdown_document",
            title="Doc Contract",
            domain="psychology",
            raw_text="# Assessment\n进行一次结构化抑郁评估。\n",
            sections=[
                DocumentSection(
                    heading="Assessment",
                    text="对来访者进行结构化抑郁评估，并给出下一步建议。",
                    span=TextSpan(start=0, end=24),
                )
            ],
            content_hash="doc-contract-hash",
        )

        extracted = extract_skills(
            documents=[record],
            extractor=build_document_skill_extractor(
                "llm",
                llm_config={"provider": "mock", "response": _contract_response},
            ),
        )

        self.assertEqual(len(extracted.skill_drafts), 1)
        draft = extracted.skill_drafts[0]
        self.assertEqual(draft.triggers, ["来访者呈现持续情绪低落或兴趣减退。"])
        self.assertEqual(draft.applicable_signals, ["来访者呈现持续情绪低落或兴趣减退。"])
        self.assertEqual(draft.contraindications, ["存在急性自杀危机且需先进入危机分流。"])
        self.assertEqual(draft.output_contract, ["形成结构化评估结论与下一步建议。"])

    def test_build_records_failed_document_without_aborting_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def _partially_failing_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
                if mode == "document_extract":
                    payload = json.loads(user)
                    title = str((payload.get("document") or {}).get("title") or "").strip()
                    if title == "Doc Fail":
                        raise TimeoutError("SSL handshake timed out")
                return _document_llm_response(system=system, user=user, temperature=temperature, mode=mode)

            sdk = AutoSkill(
                AutoSkillConfig(
                    llm={"provider": "mock", "response": _partially_failing_response, "allow_mock": True},
                    embeddings={"provider": "hashing", "dims": 64},
                    store={"provider": "local", "path": tmpdir},
                    maintenance_strategy="heuristic",
                )
            )
            pipeline = build_default_document_pipeline(
                sdk=sdk,
                extract_workers=2,
                extract_retries=1,
                extract_retry_backoff_s=0.01,
            )

            result = pipeline.build(
                user_id="u1",
                data=[
                    {
                        "doc_id": "doc-ok",
                        "title": "Doc OK",
                        "raw_text": _DOC_TEXT,
                        "source_file": "/tmp/doc-ok.md",
                    },
                    {
                        "doc_id": "doc-fail",
                        "title": "Doc Fail",
                        "raw_text": _DOC_TEXT,
                        "source_file": "/tmp/doc-fail.md",
                    },
                ],
                title="Batch Build",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc", "domain_type": "psychology"},
            )

            self.assertEqual(len(result.extracted.errors), 1)
            self.assertEqual(result.extracted.errors[0]["doc_id"], "doc-fail")
            self.assertEqual(result.extracted.errors[0]["title"], "Doc Fail")
            self.assertEqual(result.extracted.errors[0]["source_file"], "/tmp/doc-fail.md")
            self.assertTrue(bool(result.extracted.errors[0]["retryable"]))
            self.assertGreaterEqual(len(result.compiled.skill_specs), 1)
            self.assertGreaterEqual(len(result.registration.upserted_store_skills), 1)

            error_path = os.path.join(
                result.intermediate["run_dir"],
                "extract",
                "documents",
                f"{safe_dir_component('doc-fail')}.json",
            )
            self.assertTrue(os.path.isfile(error_path))
            with open(error_path, "r", encoding="utf-8") as f:
                error_payload = json.load(f)
            self.assertTrue(bool(error_payload.get("failed")))
            self.assertEqual(str((error_payload.get("error") or {}).get("doc_id") or ""), "doc-fail")
            self.assertIn("SSL handshake timed out", str((error_payload.get("error") or {}).get("error") or ""))
            reloaded = pipeline.registry.root_dir
            self.assertTrue(bool(reloaded))
            from AutoSkill4Doc.store.intermediate import IntermediateRunWriter

            writer = IntermediateRunWriter(base_store_root=tmpdir, run_id=os.path.basename(result.intermediate["run_dir"]), resume_existing=True)
            loaded_extract = writer.load_extract()
            self.assertEqual(len(list(loaded_extract.errors or [])), 1)

    def test_resume_does_not_skip_failed_document_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = IntermediateRunWriter(base_store_root=tmpdir, metadata={"resume_key": "resume-test"})
            ok_record = DocumentRecord(
                doc_id="doc-ok",
                source_type="markdown_document",
                title="Doc OK",
                domain="psychology",
                raw_text=_DOC_TEXT,
                content_hash="doc-ok-hash",
            )
            fail_record = DocumentRecord(
                doc_id="doc-fail",
                source_type="markdown_document",
                title="Doc Fail",
                domain="psychology",
                raw_text=_DOC_TEXT,
                content_hash="doc-fail-hash",
            )

            writer.write_extract_progress(
                record=ok_record,
                supports=[],
                drafts=[],
                total_documents=2,
            )
            writer.write_extract_error(
                record=fail_record,
                error={"doc_id": "doc-fail", "error": "timeout"},
                total_documents=2,
            )

            self.assertEqual(writer.processed_extract_doc_ids(), ["doc-ok"])


    def test_budgeted_extraction_prioritizes_relevant_sections(self) -> None:
        def _budget_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
            _ = system, temperature
            if mode != "document_extract":
                return json.dumps({"skills": []}, ensure_ascii=False)
            payload = json.loads(user)
            excerpt = str(payload.get("excerpt") or "").strip().lower()
            if "scaling question" not in excerpt:
                return json.dumps({"skills": []}, ensure_ascii=False)
            document = payload.get("document") or {}
            return json.dumps(
                {
                    "skills": [
                        {
                            "name": "Scaling question intervention",
                            "description": "Use a scaling question intervention.",
                            "prompt": (
                                "# Role & Objective\n"
                                "Use a scaling question.\n\n"
                                "# Rules & Constraints\n"
                                "- Keep the intervention concise.\n\n"
                                "# Core Workflow\n"
                                "1. Ask the scaling question.\n\n"
                                "# Output Format\n"
                                "- Return the next-step summary."
                            ),
                            "asset_type": "micro_skill",
                            "granularity": "micro",
                            "objective": "Deliver a single scaling-question intervention move.",
                            "domain": document.get("domain") or "psychology",
                            "task_family": "goal_setting",
                            "method_family": "solution_focused",
                            "stage": "intervention",
                            "applicable_signals": ["When progress needs to be scaled concretely."],
                            "intervention_moves": ["Ask the scaling question."],
                            "contraindications": [],
                            "workflow_steps": ["Ask the scaling question."],
                            "constraints": ["Keep the intervention concise."],
                            "cautions": [],
                            "output_contract": ["Return the next-step summary."],
                            "relation_type": "support",
                            "risk_class": "low",
                            "triggers": ["When using a scaling question"],
                            "tags": ["scaling question", "solution focused"],
                            "confidence": 0.9,
                        }
                    ]
                },
                ensure_ascii=False,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)

            text = """
# Demographics
This section only describes age, school, and family facts.

# Growth History
This section only narrates background experiences.

# Session Intervention
Use a scaling question to help the client rate progress and define the next step.
""".strip()

            ingest_result = pipeline.ingest_document(
                data=text,
                title="Budgeted Section Priority",
                domain="psychology",
                dry_run=True,
            )
            extracted = extract_skills(
                documents=ingest_result.documents,
                extractor=build_document_skill_extractor(
                    "llm",
                    llm_config={"provider": "mock", "response": _budget_response},
                    max_units_per_document=1,
                ),
            )

            self.assertEqual(len(extracted.skill_drafts), 1)
            self.assertEqual(extracted.support_records[0].section, "Session Intervention")
            self.assertEqual(extracted.skill_drafts[0].stage, "intervention")
            self.assertEqual(extracted.skill_drafts[0].asset_type, "micro_skill")

    def test_compile_stage_keeps_support_content_outside_skill_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)

            ingest_result = pipeline.ingest_document(
                data=_DOC_TEXT,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
                dry_run=True,
            )
            extracted_result = pipeline.extract_skills(documents=ingest_result.documents)
            compiled_result = pipeline.compile_skills(
                skill_drafts=extracted_result.skill_drafts,
                support_records=extracted_result.support_records,
            )

            spec = compiled_result.skill_specs[0]
            support = next(
                (item for item in compiled_result.support_records if item.support_id in spec.support_ids),
                None,
            )

            self.assertIsNotNone(support)
            assert support is not None
            self.assertIn(support.support_id, spec.support_ids)
            self.assertNotIn(support.support_id, spec.skill_body)
            self.assertNotIn(support.excerpt, spec.metadata.get("identity_key", ""))

    def test_compile_groups_distinct_drafts_from_same_document_separately(self) -> None:
        def _compile_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
            _ = system, temperature
            if mode != "document_compile":
                return json.dumps({"skills": []}, ensure_ascii=False)
            payload = json.loads(user)
            drafts = list(payload.get("drafts") or [])
            first = drafts[0]
            return json.dumps(
                {
                    "skills": [
                        {
                            "name": first.get("name") or "skill",
                            "description": first.get("description") or "desc",
                            "prompt": first.get("metadata", {}).get("prompt") or "# Goal\nPrompt",
                            "asset_type": first.get("asset_type") or "session_skill",
                            "granularity": first.get("granularity") or "session",
                            "objective": first.get("objective") or first.get("description") or "objective",
                            "domain": first.get("domain") or "psychology",
                            "task_family": first.get("task_family") or "intake",
                            "method_family": first.get("method_family") or "structured_interview",
                            "stage": first.get("stage") or "intake",
                            "workflow_steps": first.get("workflow_steps") or [],
                            "constraints": first.get("constraints") or [],
                            "cautions": first.get("cautions") or [],
                            "output_contract": first.get("output_contract") or [],
                            "support_ids": first.get("support_ids") or [],
                            "source_draft_ids": [first.get("draft_id")],
                            "confidence": 0.9,
                            "risk_class": "low",
                        }
                    ]
                },
                ensure_ascii=False,
            )

        support_a = SupportRecord(
            support_id="sup-a",
            doc_id="doc-1",
            source_file="/tmp/doc-1.md",
            section="Session 1",
            span=TextSpan(start=0, end=20),
            excerpt="Build rapport first.",
            relation_type=SupportRelation.SUPPORT,
            confidence=0.9,
        )
        support_b = SupportRecord(
            support_id="sup-b",
            doc_id="doc-1",
            source_file="/tmp/doc-1.md",
            section="Session 2",
            span=TextSpan(start=21, end=45),
            excerpt="Review homework next.",
            relation_type=SupportRelation.SUPPORT,
            confidence=0.9,
        )
        draft_a = SkillDraft(
            draft_id="draft-a",
            doc_id="doc-1",
            name="rapport building / intake",
            description="Build rapport before deeper intervention.",
            asset_type="session_skill",
            granularity="session",
            objective="Establish rapport before deeper intervention.",
            domain="psychology",
            task_family="intake",
            method_family="structured_interview",
            stage="intake",
            workflow_steps=["Build rapport first."],
            constraints=["Do not rush disclosure."],
            support_ids=["sup-a"],
            metadata={
                "prompt": "# Goal\nBuild rapport.",
                "family_name": "认知行为疗法",
                "family_id": "cbt",
                "profile_id": "psychology::认知行为疗法",
                "domain_root_name": "心理咨询",
                "domain_root_id": "psychology",
                "taxonomy_axis": "疗法",
                "family_bucket_label": "Family技能",
                "visible_levels": {"1": "一级技能", "2": "二级技能", "3": "微技能"},
            },
        )
        draft_b = SkillDraft(
            draft_id="draft-b",
            doc_id="doc-1",
            name="homework review / session opening",
            description="Review homework before setting the agenda.",
            asset_type="session_skill",
            granularity="session",
            objective="Review homework before setting the agenda.",
            domain="psychology",
            task_family="homework_review",
            method_family="structured_interview",
            stage="follow_up",
            workflow_steps=["Review homework first."],
            constraints=["Check barriers before assigning more work."],
            support_ids=["sup-b"],
            metadata={
                "prompt": "# Goal\nReview homework.",
                "family_name": "认知行为疗法",
                "family_id": "cbt",
                "profile_id": "psychology::认知行为疗法",
                "domain_root_name": "心理咨询",
                "domain_root_id": "psychology",
                "taxonomy_axis": "疗法",
                "family_bucket_label": "Family技能",
                "visible_levels": {"1": "一级技能", "2": "二级技能", "3": "微技能"},
            },
        )

        compiled = compile_skills(
            skill_drafts=[draft_a, draft_b],
            support_records=[support_a, support_b],
            compiler=build_skill_compiler(
                "llm",
                llm_config={"provider": "mock", "response": _compile_response},
            ),
            target_state=VersionState.DRAFT,
        )

        self.assertEqual(len(compiled.skill_specs), 2)
        self.assertEqual(
            {spec.name for spec in compiled.skill_specs},
            {"rapport building / intake", "homework review / session opening"},
        )
        for spec in compiled.skill_specs:
            self.assertEqual(spec.metadata.get("family_name"), "认知行为疗法")
            self.assertEqual(spec.metadata.get("family_id"), "cbt")
            self.assertEqual(spec.metadata.get("profile_id"), "psychology::认知行为疗法")
            self.assertEqual(spec.metadata.get("domain_root_name"), "心理咨询")
            self.assertEqual(spec.metadata.get("taxonomy_axis"), "疗法")

    def test_compile_falls_back_to_source_asset_type_when_compiler_returns_unknown_type(self) -> None:
        support = SupportRecord(
            support_id="sup-chem-a",
            doc_id="chem-doc",
            source_file="/tmp/chem.md",
            section="Analysis",
            span=TextSpan(start=0, end=20),
            excerpt="Prepare the plate and spot the sample.",
            relation_type=SupportRelation.SUPPORT,
            confidence=0.9,
        )
        draft = SkillDraft(
            draft_id="draft-chem-a",
            doc_id="chem-doc",
            name="TLC workflow",
            description="Run the TLC workflow.",
            asset_type="session_skill",
            granularity="session",
            objective="Run the TLC workflow.",
            domain="chemistry",
            task_family="analysis",
            method_family="tlc",
            stage="analysis",
            workflow_steps=["Prepare the plate.", "Spot the sample."],
            constraints=["Use the configured solvent system."],
            support_ids=["sup-chem-a"],
            metadata={
                "prompt": "# Goal\nRun the TLC workflow.",
                "domain_type": "chemistry",
                "taxonomy_id": "chemistry",
            },
        )
        compile_response = lambda system=None, user="", temperature=0.0, mode="default": json.dumps(
            {
                "skills": [
                    {
                        "name": "TLC workflow",
                        "description": "Run the TLC workflow.",
                        "prompt": "# Goal\nRun the TLC workflow.\n\n# Core Workflow\n1. Prepare the plate.\n2. Spot the sample.",
                        "asset_type": "invalid_new_type",
                        "granularity": "session",
                        "objective": "Run the TLC workflow.",
                        "domain": "chemistry",
                        "task_family": "analysis",
                        "method_family": "tlc",
                        "stage": "analysis",
                        "workflow_steps": ["Prepare the plate.", "Spot the sample."],
                        "constraints": ["Use the configured solvent system."],
                        "support_ids": ["sup-chem-a"],
                        "source_draft_ids": ["draft-chem-a"],
                    }
                ]
            },
            ensure_ascii=False,
        )

        compiled = compile_skills(
            skill_drafts=[draft],
            support_records=[support],
            compiler=build_skill_compiler(
                "llm",
                llm_config={"provider": "mock", "response": compile_response},
            ),
            target_state=VersionState.DRAFT,
        )

        self.assertEqual(len(compiled.skill_specs), 1)
        self.assertEqual(compiled.skill_specs[0].asset_type, "session_skill")

    def test_changed_document_bumps_registry_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            initial_text = """
# Intake
1. Build rapport before deeper intervention.

# Constraints
Do not push interpretation before the client is ready.
""".strip()
            revised_text = """
# Intake
1. Build rapport before deeper intervention.

# Constraints
Do not push interpretation before the client is ready.
Always check for acute risk before intensive exploration.
""".strip()

            first = pipeline.build(
                user_id="u1",
                data=initial_text,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )
            second = pipeline.build(
                user_id="u1",
                data=revised_text,
                title="Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )

            first_versions = {spec.skill_id: spec.version for spec in list(first.registration.skill_specs or [])}
            shared_skills = [
                spec for spec in list(second.registration.skill_specs or []) if spec.skill_id in first_versions
            ]

            self.assertTrue(shared_skills)
            self.assertTrue(any(spec.version != first_versions[spec.skill_id] for spec in shared_skills))
            self.assertTrue(any(spec.version == "0.1.1" for spec in shared_skills))
            self.assertTrue(any(event.reason in {"revise", "strengthen", "merge"} for event in second.registration.lifecycles))

    def test_numbered_subsection_context_reaches_extraction_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            text = """
3 认知重构

3.1 自动思维识别
先识别自动思维和触发事件。

3.2 证据检验
再评估支持证据、反证和替代解释。
""".strip()

            result = pipeline.build(
                user_id="u1",
                data=text,
                title="Hierarchy Intake",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
                dry_run=True,
            )

            self.assertTrue(result.extracted.support_records)
            support = result.extracted.support_records[0]
            self.assertIn("heading_path", support.metadata)
            self.assertEqual(["3 认知重构"], list(support.metadata.get("heading_path") or []))
            self.assertEqual("", support.metadata.get("parent_heading"))
            self.assertIn("3.1 自动思维识别", list(support.metadata.get("subsection_headings") or []))
            self.assertIn("3.2 证据检验", list(support.metadata.get("subsection_headings") or []))

    def test_build_resumes_failed_run_without_reextracting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            pipeline.document_skill_extractor = CountingExtractor(pipeline.document_skill_extractor)
            pipeline.skill_compiler = FailOnceCompiler(pipeline.skill_compiler)

            with self.assertRaises(RuntimeError):
                pipeline.build(
                    data=_DOC_TEXT,
                    title="Resumable Intake Workflow",
                    domain="psychology",
                    metadata={"channel": "offline_extract_from_doc"},
                )

            self.assertEqual(pipeline.document_skill_extractor.calls, 1)

            result = pipeline.build(
                data=_DOC_TEXT,
                title="Resumable Intake Workflow",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )

            self.assertEqual(pipeline.document_skill_extractor.calls, 1)
            self.assertTrue(result.intermediate.get("resumed"))
            self.assertGreaterEqual(len(result.registration.skill_specs), 1)

    def test_build_resumes_streamed_register_without_recompiling_processed_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = self._build_sdk(store_path=tmpdir)
            pipeline = build_default_document_pipeline(sdk=sdk)
            pipeline.skill_compiler = CountingCompiler(pipeline.skill_compiler)
            original_register_versions = pipeline.register_versions
            register_calls = {"count": 0}

            def _interrupting_register_versions(**kwargs):
                register_calls["count"] += 1
                if register_calls["count"] == 2:
                    raise RuntimeError("register interrupted")
                return original_register_versions(**kwargs)

            pipeline.register_versions = _interrupting_register_versions

            documents = [
                {
                    "doc_id": "doc-1",
                    "title": "Doc One",
                    "raw_text": _DOC_TEXT,
                    "source_file": "/tmp/doc-1.md",
                },
                {
                    "doc_id": "doc-2",
                    "title": "Doc Two",
                    "raw_text": _DOC_TEXT,
                    "source_file": "/tmp/doc-2.md",
                },
            ]

            with self.assertRaises(RuntimeError):
                pipeline.build(
                    data=documents,
                    title="Resumable Batch",
                    domain="psychology",
                    metadata={"channel": "offline_extract_from_doc"},
                )

            self.assertEqual(pipeline.skill_compiler.calls, 2)
            self.assertEqual(register_calls["count"], 2)

            pipeline.register_versions = original_register_versions
            result = pipeline.build(
                data=documents,
                title="Resumable Batch",
                domain="psychology",
                metadata={"channel": "offline_extract_from_doc"},
            )

            self.assertEqual(pipeline.skill_compiler.calls, 2)
            self.assertEqual(register_calls["count"], 2)
            self.assertTrue(result.intermediate.get("resumed"))
            compile_docs_dir = os.path.join(result.intermediate["run_dir"], "compile", "documents")
            register_docs_dir = os.path.join(result.intermediate["run_dir"], "register", "documents")
            self.assertEqual(2, len([name for name in os.listdir(compile_docs_dir) if name.endswith(".json")]))
            self.assertEqual(2, len([name for name in os.listdir(register_docs_dir) if name.endswith(".json")]))


if __name__ == "__main__":
    unittest.main()
