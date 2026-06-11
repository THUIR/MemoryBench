from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from autoskill.cli import main as autoskill_main
from AutoSkill4Doc import (
    DocumentRegistry,
    SkillSpec,
    VersionState,
    DocumentFamilyResolver,
    DocumentFamilyResolution,
    TaxonomyAssetNode,
    build_document_family_resolver,
    retrieve_hierarchy,
    resolve_staging_bucket_context,
    skill_retrieval_text,
)
from AutoSkill4Doc.__main__ import main as autoskill4doc_main
from AutoSkill4Doc.core.config import DEFAULT_DOC_SKILL_USER_ID, DEFAULT_SECTION_OUTLINE_MODE, default_store_path, normalize_section_outline_mode
from AutoSkill4Doc.extract import _build_sdk_from_args, build_parser, main


_DOC_TEXT = """
# Intake
1. Build rapport before deeper intervention.
2. Clarify the client's immediate concern.

# Constraints
Do not push interpretation before the client is ready.
""".strip()


class DocumentCliTest(unittest.TestCase):
    def _mock_response(self) -> str:
        return json.dumps(
            {
                "document_extract": {
                    "skills": [
                        {
                            "name": "document intake workflow",
                            "description": "Reusable workflow extracted from the document.",
                            "prompt": "# Role & Objective\nGuide the workflow.\n\n# Rules & Constraints\n- Keep the process safe.\n\n# Core Workflow\n1. Build rapport first.\n2. Clarify the immediate concern.\n\n# Output Format\n- Output a short summary.",
                            "domain": "psychology",
                            "task_family": "intake",
                            "method_family": "structured_interview",
                            "stage": "intake",
                            "workflow_steps": ["Build rapport first.", "Clarify the immediate concern."],
                            "constraints": ["Keep the process safe."],
                            "cautions": ["Avoid premature interpretation."],
                            "output_contract": ["Output a short summary."],
                            "relation_type": "support",
                            "risk_class": "medium",
                            "triggers": ["When starting intake"],
                            "tags": ["psychology", "intake"],
                            "confidence": 0.9,
                        }
                    ]
                },
                "document_compile": {
                    "skills": [
                        {
                            "name": "document intake workflow",
                            "description": "Reusable workflow extracted from the document.",
                            "prompt": "# Role & Objective\nGuide the workflow.\n\n# Rules & Constraints\n- Keep the process safe.\n\n# Core Workflow\n1. Build rapport first.\n2. Clarify the immediate concern.\n\n# Output Format\n- Output a short summary.",
                            "domain": "psychology",
                            "task_family": "intake",
                            "method_family": "structured_interview",
                            "stage": "intake",
                            "workflow_steps": ["Build rapport first.", "Clarify the immediate concern."],
                            "constraints": ["Keep the process safe."],
                            "cautions": ["Avoid premature interpretation."],
                            "output_contract": ["Output a short summary."],
                            "tags": ["psychology", "intake"],
                            "confidence": 0.9,
                            "risk_class": "medium",
                        }
                    ]
                },
                "document_version": {
                    "action": "create",
                    "target_skill_ids": [],
                    "reason": "create"
                }
            },
            ensure_ascii=False,
        )

    def _write_doc(self, *, root: str) -> str:
        path = os.path.join(root, "document.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_DOC_TEXT)
        return path

    def _run_main_json(self, argv: list[str]) -> dict:
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(argv)
        text = buf.getvalue().strip()
        self.assertTrue(text)
        return json.loads(text)

    def _run_text(self, fn, argv: list[str]) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                fn(argv)
            except SystemExit as exc:
                if int(getattr(exc, "code", 0) or 0) not in {0}:
                    raise
        return buf.getvalue()

    def test_default_cli_invocation_routes_to_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            payload = self._run_main_json(
                [
                    "--file",
                    doc_path,
                    "--quiet",
                    "--json",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--family-name",
                    "认知行为疗法",
                    "--profile-id",
                    "test_therapy_v2",
                    "--taxonomy-axis",
                    "疗法",
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(payload["total_documents"], 1)
            self.assertGreater(payload["total_support_records"], 0)
            self.assertGreater(payload["total_skill_drafts"], 0)
            self.assertGreater(payload["total_skill_specs"], 0)
            self.assertEqual(payload["visible_tree"]["affected_families"], ["认知行为疗法"])

    def test_extract_command_returns_support_records_and_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            payload = self._run_main_json(
                [
                    "extract",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--quiet",
                    "--json",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(len(payload["documents"]), 1)
            self.assertGreaterEqual(len(payload["windows"]), 1)
            self.assertGreater(len(payload["support_records"]), 0)
            self.assertGreater(len(payload["skill_drafts"]), 0)
            self.assertIn("relation_type", payload["support_records"][0])

    def test_ingest_command_returns_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            payload = self._run_main_json(
                [
                    "ingest",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--quiet",
                    "--json",
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(len(payload["documents"]), 1)
            self.assertGreaterEqual(len(payload["text_units"]), 1)
            self.assertGreaterEqual(len(payload["windows"]), 1)

    def test_ingest_command_accepts_chunk_window_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            payload = self._run_main_json(
                [
                    "ingest",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--quiet",
                    "--json",
                    "--extract-strategy",
                    "chunk",
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(len(payload["documents"]), 1)
            self.assertGreaterEqual(len(payload["windows"]), 1)
            self.assertTrue(all(window["strategy"] == "chunk" for window in payload["windows"]))

    def test_ingest_command_accepts_section_outline_and_section_size_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            payload = self._run_main_json(
                [
                    "ingest",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--quiet",
                    "--json",
                    "--section-outline-mode",
                    "rule",
                    "--max-section-chars",
                    "10000",
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(len(payload["documents"]), 1)
            self.assertGreaterEqual(len(payload["windows"]), 1)

    def test_section_outline_mode_defaults_to_llm_with_compat_aliases(self) -> None:
        args = build_parser().parse_args(["ingest", "--file", "/tmp/paper.md"])
        self.assertEqual(DEFAULT_SECTION_OUTLINE_MODE, args.section_outline_mode)
        self.assertEqual("llm", normalize_section_outline_mode(args.section_outline_mode))
        self.assertEqual("llm", normalize_section_outline_mode("auto"))
        self.assertEqual("rule", normalize_section_outline_mode("off"))

    def test_compile_command_returns_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            payload = self._run_main_json(
                [
                    "compile",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--quiet",
                    "--json",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(len(payload["documents"]), 1)
            self.assertGreaterEqual(len(payload["windows"]), 1)
            self.assertGreater(len(payload["support_records"]), 0)
            self.assertGreater(len(payload["skill_drafts"]), 0)
            self.assertGreater(len(payload["skills"]), 0)

    def test_parser_accepts_domain_type_custom_taxonomy_and_family_name(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "ingest",
                "--file",
                "/tmp/doc.md",
                "--domain-type",
                "chemistry",
                "--skill-taxonomy",
                "/tmp/custom-taxonomy.yaml",
                "--family-name",
                "有机合成",
            ]
        )

        self.assertEqual(args.domain_type, "chemistry")
        self.assertEqual(args.skill_taxonomy, "/tmp/custom-taxonomy.yaml")
        self.assertEqual(args.family_name, "有机合成")

    def test_standalone_package_cli_routes_to_document_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            buf = io.StringIO()
            with redirect_stdout(buf):
                autoskill4doc_main(
                    [
                        "compile",
                        "--file",
                        doc_path,
                        "--dry-run",
                        "--quiet",
                        "--json",
                        "--llm-provider",
                        "mock",
                        "--allow-mock-provider",
                        "--llm-response",
                        self._mock_response(),
                        "--maintenance-strategy",
                        "llm",
                        "--store-path",
                        tmpdir,
                    ]
                )
            payload = json.loads(buf.getvalue().strip())

            self.assertEqual(len(payload["documents"]), 1)
            self.assertGreater(len(payload["support_records"]), 0)
            self.assertGreater(len(payload["skill_drafts"]), 0)
            self.assertGreater(len(payload["skills"]), 0)

    def test_standalone_package_help_shows_document_subcommands(self) -> None:
        output = self._run_text(autoskill4doc_main, ["-h"])

        self.assertIn("build", output)
        self.assertIn("llm-extract", output)
        self.assertIn("ingest", output)
        self.assertIn("extract", output)
        self.assertIn("compile", output)
        self.assertIn("diag", output)
        self.assertIn("retrieve-hierarchy", output)
        self.assertIn("canonical-merge", output)
        self.assertIn("migrate-layout", output)

    def test_top_level_package_exports_retrieval_and_staging_helpers(self) -> None:
        self.assertTrue(callable(resolve_staging_bucket_context))
        self.assertTrue(callable(skill_retrieval_text))
        self.assertTrue(TaxonomyAssetNode)
        self.assertTrue(DocumentFamilyResolver)
        self.assertTrue(DocumentFamilyResolution)
        self.assertTrue(callable(build_document_family_resolver))

    def test_root_autoskill_cli_rejects_document_route(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            with self.assertRaises(SystemExit) as ctx:
                autoskill_main(["offline", "document", "-h"])

        self.assertIn("AutoSkill4Doc is now standalone", str(ctx.exception))

    def test_build_help_includes_examples_and_registry_help(self) -> None:
        output = self._run_text(main, ["build", "-h"])

        self.assertIn("Examples:", output)
        self.assertIn("--registry-root", output)
        self.assertIn("document registry root", output)

    def test_document_cli_defaults_store_path_to_docskill(self) -> None:
        args = build_parser().parse_args(["build", "--file", "/tmp/paper.md"])
        sdk = _build_sdk_from_args(args)

        self.assertEqual(sdk.config.store.get("path"), default_store_path())
        self.assertEqual(args.user_id, DEFAULT_DOC_SKILL_USER_ID)

    def test_document_cli_defaults_to_continue_on_error_and_recommended_windows(self) -> None:
        args = build_parser().parse_args(["build", "--file", "/tmp/paper.md"])

        self.assertTrue(args.continue_on_error)
        self.assertEqual(args.extract_strategy, "recommended")
        self.assertEqual(args.embeddings_dims, 256)
        self.assertEqual(args.extract_workers, 1)

    def test_document_cli_accepts_extract_workers(self) -> None:
        args = build_parser().parse_args(["build", "--file", "/tmp/paper.md", "--extract-workers", "4"])

        self.assertEqual(args.extract_workers, 4)

    def test_document_cli_accepts_extract_retry_controls(self) -> None:
        args = build_parser().parse_args(
            [
                "build",
                "--file",
                "/tmp/paper.md",
                "--extract-retries",
                "5",
                "--extract-retry-backoff-s",
                "0.25",
            ]
        )

        self.assertEqual(args.extract_retries, 5)
        self.assertAlmostEqual(args.extract_retry_backoff_s, 0.25)

    def test_document_cli_accepts_retrieval_score_threshold(self) -> None:
        args = build_parser().parse_args(
            [
                "build",
                "--file",
                "/tmp/paper.md",
                "--retrieval-score-threshold",
                "0.45",
            ]
        )

        self.assertAlmostEqual(args.retrieval_score_threshold, 0.45)

    def test_document_cli_accepts_llm_rate_limit_controls(self) -> None:
        args = build_parser().parse_args(
            [
                "build",
                "--file",
                "/tmp/paper.md",
                "--llm-rate-limit-requests",
                "2000",
                "--llm-rate-limit-window-s",
                "300",
            ]
        )

        self.assertEqual(args.llm_rate_limit_requests, 2000)
        self.assertAlmostEqual(args.llm_rate_limit_window_s, 300.0)

    def test_document_cli_supports_fail_fast_flag(self) -> None:
        args = build_parser().parse_args(["build", "--file", "/tmp/paper.md", "--fail-fast"])

        self.assertFalse(args.continue_on_error)

    def test_document_cli_rejects_mock_provider_without_dev_override(self) -> None:
        args = build_parser().parse_args(["build", "--file", "/tmp/paper.md", "--llm-provider", "mock"])

        with self.assertRaises(SystemExit):
            _build_sdk_from_args(args, require_real_llm=True)

    def test_document_cli_requires_real_provider_when_env_has_none(self) -> None:
        args = build_parser().parse_args(["build", "--file", "/tmp/paper.md"])
        cleared = {
            "AUTOSKILL_GENERIC_LLM_URL": "",
            "DASHSCOPE_API_KEY": "",
            "ZHIPUAI_API_KEY": "",
            "BIGMODEL_API_KEY": "",
            "INTERNLM_API_KEY": "",
            "INTERN_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
        }
        with patch.dict(os.environ, cleared, clear=False):
            with self.assertRaises(SystemExit):
                _build_sdk_from_args(args, require_real_llm=True)

    def test_build_without_file_shows_parser_error_instead_of_traceback(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            with self.assertRaises(SystemExit) as ctx:
                main(["build", "--json"])

        self.assertEqual(int(getattr(ctx.exception, "code", 0) or 0), 2)
        self.assertIn("--file is required for CLI commands", buf.getvalue())

    def test_build_rejects_family_name_outside_configured_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    main(
                        [
                            "build",
                            "--file",
                            doc_path,
                            "--dry-run",
                            "--quiet",
                            "--json",
                            "--llm-provider",
                            "mock",
                            "--allow-mock-provider",
                            "--llm-response",
                            self._mock_response(),
                            "--maintenance-strategy",
                            "llm",
                            "--domain",
                            "psychology",
                            "--domain-type",
                            "psychology",
                            "--family-name",
                            "不存在的流派",
                            "--store-path",
                            tmpdir,
                        ]
                    )

            self.assertEqual(int(getattr(ctx.exception, "code", 0) or 0), 2)
            self.assertIn("family_name '不存在的流派' is not in configured family_candidates", buf.getvalue())

    def test_build_without_quiet_shows_document_and_skill_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            output = self._run_text(
                main,
                [
                    "build",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--store-path",
                    tmpdir,
                ],
            )

            self.assertIn("[ingest_document] prepared", output)
            self.assertIn("document.md", output)
            self.assertIn("[extract_skills] done", output)
            self.assertIn("[extract_progress]", output)
            self.assertIn("windows=1/1", output)
            self.assertIn("[compile_progress]", output)
            self.assertIn("[register_progress]", output)
            self.assertIn("document intake workflow", output)

    def test_extract_without_quiet_shows_realtime_progress_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            output = self._run_text(
                main,
                [
                    "extract",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--store-path",
                    tmpdir,
                ],
            )

            self.assertIn("[extract_progress]", output)
            self.assertIn("1/1 docs", output)
            self.assertIn("windows=1/1", output)

    def test_compile_without_quiet_shows_compile_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            output = self._run_text(
                main,
                [
                    "compile",
                    "--file",
                    doc_path,
                    "--dry-run",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--store-path",
                    tmpdir,
                ],
            )

            self.assertIn("[extract_progress]", output)
            self.assertIn("[compile_progress]", output)

    def test_llm_extract_alias_behaves_like_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            payload = self._run_main_json(
                [
                    "llm-extract",
                    "--file",
                    doc_path,
                    "--quiet",
                    "--json",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--family-name",
                    "认知行为疗法",
                    "--profile-id",
                    "test_therapy_v2",
                    "--taxonomy-axis",
                    "疗法",
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(payload["total_documents"], 1)
            self.assertEqual(payload["visible_tree"]["affected_families"], ["认知行为疗法"])
            self.assertGreaterEqual(len(list(payload.get("staging_runs") or [])), 1)

    def test_build_json_without_quiet_keeps_stdout_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                main(
                    [
                        "build",
                        "--file",
                        doc_path,
                        "--dry-run",
                        "--json",
                        "--llm-provider",
                        "mock",
                        "--allow-mock-provider",
                        "--llm-response",
                        self._mock_response(),
                        "--maintenance-strategy",
                        "llm",
                        "--store-path",
                        tmpdir,
                    ]
                )

            payload = json.loads(stdout_buf.getvalue().strip())
            self.assertEqual(payload["total_documents"], 1)
            self.assertIn("[extract_progress]", stderr_buf.getvalue())

    def test_diag_command_writes_jsonl_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            report_path = os.path.join(tmpdir, "diag.jsonl")
            payload = self._run_main_json(
                [
                    "diag",
                    "--file",
                    doc_path,
                    "--quiet",
                    "--json",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--report-path",
                    report_path,
                    "--store-path",
                    tmpdir,
                ]
            )

            self.assertEqual(payload["route"], "diag")
            self.assertTrue(payload["dry_run"])
            self.assertTrue(os.path.isfile(report_path))
            self.assertGreaterEqual(len(list(payload.get("windows") or [])), 1)

    def test_retrieve_hierarchy_and_canonical_merge_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            self._run_main_json(
                [
                    "build",
                    "--file",
                    doc_path,
                    "--quiet",
                    "--json",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--family-name",
                    "认知行为疗法",
                    "--profile-id",
                    "test_therapy_v2",
                    "--taxonomy-axis",
                    "疗法",
                    "--store-path",
                    tmpdir,
                ]
            )

            hierarchy = self._run_main_json(
                [
                    "retrieve-hierarchy",
                    "--store-path",
                    tmpdir,
                    "--profile-id",
                    "test_therapy_v2",
                    "--family-name",
                    "认知行为疗法",
                    "--json",
                ]
            )
            self.assertEqual(hierarchy["route"], "family_hierarchy")
            self.assertEqual(hierarchy["profile_id"], "test_therapy_v2")
            self.assertEqual(hierarchy["family_name"], "认知行为疗法")
            self.assertGreaterEqual(len(list(hierarchy.get("hits") or [])), 1)

            merge_payload = self._run_main_json(
                [
                    "canonical-merge",
                    "--store-path",
                    tmpdir,
                    "--json",
                ]
            )
            self.assertEqual(merge_payload["route"], "canonical_merge")
            self.assertEqual(merge_payload["profile_id"], "test_therapy_v2")
            self.assertEqual(merge_payload["family_id"], "认知行为疗法")
            self.assertEqual(merge_payload["family_name"], "认知行为疗法")
            self.assertEqual(merge_payload["child_type"], "intake")
            self.assertGreaterEqual(len(list(merge_payload.get("skills") or [])), 1)

    def test_retrieve_hierarchy_auto_opens_single_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = self._write_doc(root=tmpdir)
            self._run_main_json(
                [
                    "build",
                    "--file",
                    doc_path,
                    "--quiet",
                    "--json",
                    "--llm-provider",
                    "mock",
                    "--allow-mock-provider",
                    "--llm-response",
                    self._mock_response(),
                    "--maintenance-strategy",
                    "llm",
                    "--family-name",
                    "认知行为疗法",
                    "--profile-id",
                    "test_therapy_v2",
                    "--taxonomy-axis",
                    "疗法",
                    "--store-path",
                    tmpdir,
                ]
            )

            hierarchy = self._run_main_json(
                [
                    "retrieve-hierarchy",
                    "--store-path",
                    tmpdir,
                    "--json",
                ]
            )

            self.assertEqual(hierarchy["route"], "family_hierarchy")
            self.assertEqual(hierarchy["family_name"], "认知行为疗法")
            self.assertEqual(hierarchy["profile_id"], "test_therapy_v2")

    def test_retrieve_hierarchy_runtime_fallback_keeps_micro_level_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            registry.upsert_skill(
                SkillSpec(
                    skill_id="micro-1",
                    name="苏格拉底式提问",
                    description="One CBT micro intervention.",
                    skill_body="# Goal\nUse one Socratic question.",
                    asset_type="micro_skill",
                    granularity="micro",
                    asset_node_id="micro_intervention",
                    asset_level=3,
                    visible_role="leaf",
                objective="Use one Socratic question to challenge an automatic thought.",
                domain="psychology",
                task_family="reframing",
                method_family="cbt",
                stage="intervention",
                intervention_moves=["Ask one focused evidence question."],
                support_ids=[],
                status=VersionState.ACTIVE,
                metadata={
                        "family_name": "认知行为疗法",
                        "domain_root_name": "心理咨询",
                        "family_bucket_label": "Family技能",
                    },
                )
            )

            hierarchy = retrieve_hierarchy(store_root=tmpdir, family_name="认知行为疗法")

            self.assertEqual(hierarchy["fallback"], "runtime_scan")
            self.assertEqual(hierarchy["route"], "family_hierarchy")
            self.assertEqual(hierarchy["family_name"], "认知行为疗法")
            self.assertTrue(hierarchy["hits"])
            self.assertIn("微技能", hierarchy["hits"][0]["relative_path"])

    def test_migrate_layout_command_prepares_runtime_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = self._run_main_json(
                [
                    "migrate-layout",
                    "--store-path",
                    tmpdir,
                    "--json",
                ]
            )

            self.assertEqual(payload["route"], "migrate_layout")
            self.assertTrue(os.path.isdir(os.path.join(tmpdir, ".runtime")))

    def test_canonical_merge_returns_resolution_error_when_bucket_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = self._run_main_json(
                [
                    "canonical-merge",
                    "--store-path",
                    tmpdir,
                    "--json",
                ]
            )

            self.assertEqual(payload["route"], "canonical_merge")
            self.assertTrue(payload["errors"])
            self.assertIn("could not resolve a unique staging bucket", payload["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
