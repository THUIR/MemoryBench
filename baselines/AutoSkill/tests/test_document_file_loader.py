from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from AutoSkill4Doc.extract import _build_sdk_from_args, build_parser
from AutoSkill4Doc.document.file_loader import load_file_units
from AutoSkill4Doc.ingest import ingest_document


class DocumentFileLoaderTest(unittest.TestCase):
    def test_directory_loader_skips_known_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            text_path = os.path.join(tmpdir, "note.md")
            image_path = os.path.join(tmpdir, "figure.png")

            with open(text_path, "w", encoding="utf-8") as f:
                f.write("# Note\nA reusable workflow section.\n")
            with open(image_path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

            units, root = load_file_units(tmpdir)

            self.assertEqual(root, tmpdir)
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0]["title"], "note.md")
            self.assertIn("workflow", units[0]["text"])

    def test_cli_does_not_override_provider_key_with_unrelated_openai_env(self) -> None:
        parser = build_parser()
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "DASHSCOPE_API_KEY": "dashscope-key",
            },
            clear=False,
        ):
            args = parser.parse_args(
                [
                    "build",
                    "--file",
                    "/tmp/paper.md",
                    "--llm-provider",
                    "dashscope",
                    "--embeddings-provider",
                    "dashscope",
                ]
            )
            sdk = _build_sdk_from_args(args)

        self.assertEqual(sdk.config.llm.get("api_key"), "dashscope-key")
        self.assertEqual(sdk.config.embeddings.get("api_key"), "dashscope-key")

    def test_cli_explicit_api_key_override_still_works(self) -> None:
        parser = build_parser()
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "dashscope-key"}, clear=False):
            args = parser.parse_args(
                [
                    "build",
                    "--file",
                    "/tmp/paper.md",
                    "--llm-provider",
                    "dashscope",
                    "--llm-api-key",
                    "manual-override",
                ]
            )
            sdk = _build_sdk_from_args(args)

        self.assertEqual(sdk.config.llm.get("api_key"), "manual-override")

    def test_single_unreadable_file_reports_ingest_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            binary_path = os.path.join(tmpdir, "report.pdf")
            with open(binary_path, "wb") as f:
                f.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>")

            result = ingest_document(file_path=binary_path, dry_run=True)

            self.assertEqual(len(result.documents), 0)
            self.assertEqual(len(result.errors), 1)
            self.assertIn("no readable text extracted", result.errors[0]["error"])

    def test_directory_with_only_unreadable_files_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            binary_path = os.path.join(tmpdir, "scan.pdf")
            with open(binary_path, "wb") as f:
                f.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>")

            result = ingest_document(file_path=tmpdir, dry_run=True)

            self.assertEqual(len(result.documents), 0)
            self.assertEqual(len(result.errors), 1)
            self.assertIn("no readable text extracted from directory", result.errors[0]["error"])

    def test_directory_loader_uses_stable_sorted_order_before_max_files_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {
                "b.md": os.path.join(tmpdir, "b.md"),
                "a.md": os.path.join(tmpdir, "a.md"),
                "c.md": os.path.join(tmpdir, "c.md"),
            }
            for name, path in paths.items():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"# {name}\ntext\n")

            fake_walk = [(tmpdir, ["zdir", ".runtime"], ["b.md", "a.md", "c.md"])]
            with patch("AutoSkill4Doc.document.file_loader.os.walk", return_value=fake_walk):
                units, _ = load_file_units(tmpdir, max_files=2)

            self.assertEqual([unit["title"] for unit in units], ["a.md", "b.md"])

    def test_directory_loader_skips_generated_visible_skill_tree_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "paper.md")
            generated_readme_path = os.path.join(tmpdir, "README.md")
            runtime_manifest_path = os.path.join(tmpdir, ".runtime", "library_manifest.json")
            parent_skill_path = os.path.join(tmpdir, "心理咨询", "Family技能", "认知行为疗法", "总技能", "SKILL.md")
            child_skill_path = os.path.join(tmpdir, "心理咨询", "Family技能", "认知行为疗法", "二级技能", "认知重构", "SKILL.md")
            children_manifest_path = os.path.join(
                tmpdir,
                "心理咨询",
                "Family技能",
                "认知行为疗法",
                "总技能",
                "references",
                "children_manifest.json",
            )
            os.makedirs(os.path.dirname(parent_skill_path), exist_ok=True)
            os.makedirs(os.path.dirname(child_skill_path), exist_ok=True)
            os.makedirs(os.path.dirname(children_manifest_path), exist_ok=True)
            os.makedirs(os.path.dirname(runtime_manifest_path), exist_ok=True)
            with open(source_path, "w", encoding="utf-8") as f:
                f.write("# Paper\nOriginal source document.\n")
            with open(generated_readme_path, "w", encoding="utf-8") as f:
                f.write("# Generated DocSkill README\n")
            with open(runtime_manifest_path, "w", encoding="utf-8") as f:
                f.write("{}")
            with open(parent_skill_path, "w", encoding="utf-8") as f:
                f.write("# Parent skill\n")
            with open(child_skill_path, "w", encoding="utf-8") as f:
                f.write("# Child skill\n")
            with open(children_manifest_path, "w", encoding="utf-8") as f:
                f.write("{}")

            units, _ = load_file_units(tmpdir)

            self.assertEqual([unit["title"] for unit in units], ["paper.md"])

    def test_single_generated_runtime_or_library_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_manifest_path = os.path.join(tmpdir, ".runtime", "library_manifest.json")
            root_readme_path = os.path.join(tmpdir, "README.md")
            os.makedirs(os.path.dirname(runtime_manifest_path), exist_ok=True)
            with open(runtime_manifest_path, "w", encoding="utf-8") as f:
                f.write("{}")
            with open(root_readme_path, "w", encoding="utf-8") as f:
                f.write("# Generated DocSkill README\n")

            units_readme, _ = load_file_units(root_readme_path)
            units_manifest, _ = load_file_units(runtime_manifest_path)

            self.assertEqual(units_readme, [])
            self.assertEqual(units_manifest, [])


if __name__ == "__main__":
    unittest.main()
