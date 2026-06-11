from __future__ import annotations

import os
import tempfile
import unittest

import AutoSkill4Doc
from AutoSkill4Doc.core.config import default_registry_root as default_registry_root_from_config
from AutoSkill4Doc.core.config import default_store_path
from AutoSkill4Doc.models import (
    DocumentRecord,
    SkillLifecycle,
    SkillSpec,
    SupportRecord,
    SupportRelation,
    TextSpan,
    VersionState,
)
from AutoSkill4Doc.store.registry import (
    DocumentRegistry,
    build_registry_from_store_config,
    default_registry_root,
)


class DocumentRegistryTest(unittest.TestCase):
    def test_top_level_package_exports_runtime_and_staging_helpers(self) -> None:
        self.assertTrue(callable(AutoSkill4Doc.normalize_library_root))
        self.assertTrue(callable(AutoSkill4Doc.runtime_root))
        self.assertTrue(callable(AutoSkill4Doc.staging_root))
        self.assertTrue(callable(AutoSkill4Doc.library_manifest_path))
        self.assertTrue(callable(AutoSkill4Doc.latest_run_id))
        self.assertTrue(callable(AutoSkill4Doc.list_child_types))
        self.assertTrue(callable(AutoSkill4Doc.read_run_payload))

    def test_default_registry_root_uses_store_root(self) -> None:
        root = default_registry_root("/tmp/SkillBank")
        self.assertEqual(root, os.path.join("/tmp/SkillBank", ".runtime", "document_registry"))

    def test_default_registry_root_defaults_to_docskill_store(self) -> None:
        root = default_registry_root("")
        self.assertEqual(
            root,
            default_registry_root_from_config(default_store_path()),
        )

    def test_default_store_path_stays_under_repo_root_not_package_dir(self) -> None:
        import AutoSkill4Doc.core.config as doc_config

        repo_root = os.path.abspath(os.path.join(os.path.dirname(doc_config.__file__), os.pardir, os.pardir))
        self.assertEqual(default_store_path(), os.path.join(repo_root, "SkillBank", "DocSkill"))

    def test_registry_persists_entities_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))

            document = DocumentRecord(
                doc_id="doc-1",
                source_type="paper",
                title="Workflow extraction",
                raw_text="A reproducible method.",
                content_hash="hash-1",
            )
            support = SupportRecord(
                support_id="sup-1",
                doc_id=document.doc_id,
                source_file="/tmp/paper.md",
                section="Method",
                span=TextSpan(start=0, end=12),
                excerpt="Collect input before applying rules.",
                relation_type=SupportRelation.SUPPORT,
                confidence=0.9,
            )
            skill = SkillSpec(
                skill_id="skill-1",
                name="rule-grounded transformation",
                description="Compiles a rule-grounded transformation workflow.",
                skill_body="# Goal\nTransform with rules.",
                domain="geography",
                task_family="planning",
                method_family="workflow",
                stage="intervention",
                workflow_steps=["Collect input", "Apply rules"],
                constraints=["Stop when required input is missing."],
                support_ids=[support.support_id],
                status=VersionState.DRAFT,
            )
            lifecycle = SkillLifecycle(
                lifecycle_id="life-1",
                skill_id=skill.skill_id,
                to_state=VersionState.DRAFT,
            )

            registry.upsert_document(document)
            registry.upsert_support(support)
            registry.upsert_skill(skill)
            registry.append_lifecycle(lifecycle)
            registry.append_version_history(
                entity_type="skill",
                entity_id=skill.skill_id,
                entry={"entity_type": "skill", "entity_id": skill.skill_id, "version": "0.1.0"},
            )
            registry.append_change_log(
                "chg-1",
                {"change_id": "chg-1", "entity_type": "skill", "entity_id": skill.skill_id, "action": "create"},
            )
            registry.upsert_provenance_links(
                entity_type="skill",
                entity_id=skill.skill_id,
                payload={"entity_type": "skill", "entity_id": skill.skill_id, "doc_ids": [document.doc_id]},
            )

            self.assertEqual(registry.get_document(document.doc_id).title, document.title)
            self.assertEqual(registry.get_support(support.support_id).doc_id, document.doc_id)
            self.assertEqual(registry.get_skill(skill.skill_id).name, skill.name)
            self.assertEqual(registry.get_lifecycle(lifecycle.lifecycle_id).to_state, VersionState.DRAFT)
            self.assertEqual(len(registry.get_version_history(entity_type="skill", entity_id=skill.skill_id)), 1)
            self.assertEqual(len(registry.list_change_logs(entity_type="skill", entity_id=skill.skill_id)), 1)
            self.assertEqual(
                registry.get_provenance_links(entity_type="skill", entity_id=skill.skill_id).get("doc_ids"),
                [document.doc_id],
            )
            self.assertEqual(len(registry.list_supports_by_skill_id("")), 0)

            manifest = registry.manifest()
            self.assertEqual(manifest["entities"]["documents"]["count"], 1)
            self.assertEqual(manifest["entities"]["supports"]["count"], 1)
            self.assertEqual(manifest["entities"]["skills"]["count"], 1)

    def test_registry_handles_ids_with_path_like_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))

            document = DocumentRecord(
                doc_id="folder/doc-1",
                source_type="paper",
                title="Path-like id document",
                raw_text="Document body.",
                content_hash="hash-path",
            )

            registry.upsert_document(document)
            loaded = registry.get_document("folder/doc-1")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.doc_id, "folder/doc-1")

    def test_build_registry_from_store_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = build_registry_from_store_config({"provider": "local", "path": tmpdir})
            self.assertTrue(registry.root_dir.startswith(tmpdir))
            self.assertTrue(os.path.isdir(registry.root_dir))


if __name__ == "__main__":
    unittest.main()
