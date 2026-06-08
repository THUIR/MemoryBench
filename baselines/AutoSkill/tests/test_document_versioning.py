from __future__ import annotations

import json
import os
import tempfile
import unittest

from autoskill import AutoSkill, AutoSkillConfig
from autoskill.llm.mock import MockLLM
from autoskill.models import Skill, SkillStatus
from AutoSkill4Doc.models import (
    DocumentRecord,
    SkillSpec,
    SupportRecord,
    SupportRelation,
    TextSpan,
    VersionState,
)
from AutoSkill4Doc.store.registry import DocumentRegistry
from AutoSkill4Doc.store.retrieval import SkillRetrievalHit, build_document_skill_retriever
from AutoSkill4Doc.store.layout import retrieval_cache_path
from AutoSkill4Doc.store.visible_tree import sync_visible_skill_tree
from AutoSkill4Doc.store.versioning import VersionManager, register_versions


def _version_llm_response(*, system: str | None, user: str, temperature: float = 0.0, mode: str = "default") -> str:
    _ = system, temperature
    if mode == "document_version":
        payload = json.loads(user)
        candidate = payload.get("candidate_skill") or {}
        existing = list(payload.get("existing_skills") or [])
        peers = list(payload.get("peer_candidates") or [])
        if not existing:
            return json.dumps({"action": "create", "target_skill_ids": [], "reason": "create"}, ensure_ascii=False)

        same_name = [
            skill for skill in existing
            if str(skill.get("name") or "").strip().lower() == str(candidate.get("name") or "").strip().lower()
        ]
        broad_parent = next(
            (
                skill for skill in existing
                if str(skill.get("name") or "").strip().lower() == "intake workflow"
                and len(list(skill.get("workflow_steps") or [])) >= 3
                and peers
            ),
            None,
        )
        if broad_parent is not None:
            return json.dumps(
                {
                    "action": "split",
                    "target_skill_ids": [broad_parent.get("skill_id")],
                    "reason": "split",
                    "resolved_skill": candidate,
                },
                ensure_ascii=False,
            )
        if len(same_name) >= 2:
            return json.dumps(
                {
                    "action": "merge",
                    "target_skill_ids": [skill.get("skill_id") for skill in same_name],
                    "reason": "merge",
                    "resolved_skill": candidate,
                },
                ensure_ascii=False,
            )
        target = same_name[0] if same_name else existing[0]
        candidate_steps = list(candidate.get("workflow_steps") or [])
        target_steps = list(target.get("workflow_steps") or [])
        candidate_constraints = list(candidate.get("constraints") or [])
        target_constraints = list(target.get("constraints") or [])
        support_summary = dict(candidate.get("support_summary") or {})
        has_conflict_support = int(support_summary.get("conflict_count") or 0) > 0
        if has_conflict_support:
            action = "create"
        elif candidate_steps == target_steps and candidate_constraints == target_constraints:
            action = "strengthen"
        elif candidate.get("task_family") == target.get("task_family") and candidate.get("stage") == target.get("stage"):
            action = "revise"
        else:
            action = "create"
        target_ids = [target.get("skill_id")] if action != "create" else []
        return json.dumps(
            {
                "action": action,
                "target_skill_ids": target_ids,
                "reason": action,
                "resolved_skill": candidate,
            },
            ensure_ascii=False,
        )
    if mode == "document_conflict":
        payload = json.loads(user)
        incoming = list(payload.get("incoming_skills") or [])
        has_conflict = any(
            any(item.get("relation_type") == "conflict" for item in list(skill.get("support_excerpt_summaries") or []))
            for skill in incoming
        )
        if has_conflict:
            return json.dumps({"action": "deprecate", "reason": "deprecate"}, ensure_ascii=False)
        return json.dumps({"action": "keep", "reason": "keep"}, ensure_ascii=False)
    return json.dumps({"skills": []}, ensure_ascii=False)


class DocumentVersioningTest(unittest.TestCase):
    def _llm(self) -> MockLLM:
        return MockLLM(response=_version_llm_response)

    def _document(self, *, doc_id: str, title: str = "Doc") -> DocumentRecord:
        return DocumentRecord(
            doc_id=doc_id,
            source_type="markdown_document",
            title=title,
            raw_text="placeholder",
            content_hash=f"hash-{doc_id}",
            metadata={"source_file": f"/tmp/{doc_id}.md"},
        )

    def _support(
        self,
        *,
        support_id: str,
        doc_id: str,
        excerpt: str,
        relation_type: SupportRelation = SupportRelation.SUPPORT,
    ) -> SupportRecord:
        return SupportRecord(
            support_id=support_id,
            doc_id=doc_id,
            source_file=f"/tmp/{doc_id}.md",
            section="Method",
            span=TextSpan(start=0, end=len(excerpt)),
            excerpt=excerpt,
            relation_type=relation_type,
            confidence=0.85,
        )

    def _skill(
        self,
        *,
        skill_id: str,
        name: str,
        workflow_steps: list[str],
        support_ids: list[str],
        asset_type: str = "session_skill",
        granularity: str = "session",
        objective: str | None = None,
        domain: str = "psychology",
        task_family: str = "intake",
        method_family: str = "structured_interview",
        stage: str = "intake",
        constraints: list[str] | None = None,
        cautions: list[str] | None = None,
        intervention_moves: list[str] | None = None,
        version: str = "0.1.0",
        status: VersionState = VersionState.ACTIVE,
        asset_node_id: str = "",
        asset_level: int = 0,
        visible_role: str = "",
    ) -> SkillSpec:
        return SkillSpec(
            skill_id=skill_id,
            name=name,
            description=f"{name} description",
            skill_body="# Goal\nSkill body",
            asset_type=asset_type,
            granularity=granularity,
            asset_node_id=asset_node_id,
            asset_level=asset_level,
            visible_role=visible_role,
            objective=objective or f"{name} objective",
            domain=domain,
            task_family=task_family,
            method_family=method_family,
            stage=stage,
            intervention_moves=list(intervention_moves or []),
            workflow_steps=workflow_steps,
            constraints=list(constraints or []),
            cautions=list(cautions or []),
            support_ids=support_ids,
            version=version,
            status=status,
        )

    def _register(
        self,
        *,
        registry: DocumentRegistry,
        documents: list[DocumentRecord],
        supports: list[SupportRecord],
        skills: list[SkillSpec],
        dry_run: bool = False,
        target_state: VersionState = VersionState.ACTIVE,
        metadata: dict[str, str] | None = None,
    ):
        return register_versions(
            registry=registry,
            documents=documents,
            support_records=supports,
            skill_specs=skills,
            llm=self._llm(),
            user_id="u1",
            metadata={"channel": "offline_extract_from_doc", **dict(metadata or {})},
            dry_run=dry_run,
            target_state=target_state,
        )

    def test_create_new_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            document = self._document(doc_id="doc-1")
            support = self._support(support_id="sup-1", doc_id=document.doc_id, excerpt="Build rapport first.")
            skill = self._skill(
                skill_id="cand-1",
                name="rapport building / intake",
                workflow_steps=["Build rapport first."],
                constraints=["Do not push interpretation too early."],
                support_ids=[support.support_id],
            )

            result = self._register(
                registry=registry,
                documents=[document],
                supports=[support],
                skills=[skill],
            )

            self.assertEqual(len(result.skill_specs), 1)
            self.assertEqual(result.skill_specs[0].version, "0.1.0")
            self.assertEqual(result.lifecycles[0].reason, "create")
            self.assertEqual(result.support_records[0].skill_id, result.skill_specs[0].skill_id)

    def test_register_versions_preserves_skill_family_metadata_over_run_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            document = self._document(doc_id="doc-family")
            support = self._support(support_id="sup-family", doc_id=document.doc_id, excerpt="Build rapport first.")
            skill = self._skill(
                skill_id="cand-family",
                name="family specific intake",
                workflow_steps=["Build rapport first."],
                support_ids=[support.support_id],
            )
            skill.metadata.update(
                {
                    "family_name": "认知行为疗法",
                    "family_id": "cbt",
                    "profile_id": "psychology::认知行为疗法",
                    "domain_root_name": "心理咨询",
                }
            )

            result = self._register(
                registry=registry,
                documents=[document],
                supports=[support],
                skills=[skill],
                metadata={
                    "family_name": "通用心理咨询",
                    "profile_id": "psychology::通用心理咨询",
                    "domain_root_name": "心理咨询",
                },
            )

            registered = result.skill_specs[0]
            self.assertEqual(registered.metadata.get("family_name"), "认知行为疗法")
            self.assertEqual(registered.metadata.get("family_id"), "cbt")
            self.assertEqual(registered.metadata.get("profile_id"), "psychology::认知行为疗法")

    def test_classify_parent_link_does_not_force_single_weak_parent_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            manager = VersionManager(registry=registry, llm=self._llm())
            child = self._skill(
                skill_id="child-weak",
                name="苏格拉底式提问",
                asset_type="micro_skill",
                granularity="micro",
                asset_node_id="micro_intervention",
                asset_level=3,
                visible_role="leaf",
                workflow_steps=["提出证据问题。"],
                support_ids=["sup-child"],
                task_family="cognitive_restructuring",
                method_family="cbt",
                stage="session_work",
            )
            parent = self._skill(
                skill_id="parent-weak",
                name="危机转介规则",
                asset_type="session_skill",
                granularity="session",
                asset_node_id="session_framework",
                asset_level=2,
                visible_role="parent",
                workflow_steps=["评估危机。", "安排转介。"],
                support_ids=["sup-parent"],
                task_family="crisis",
                method_family="safety",
                stage="triage",
            )

            decision = manager.classify_parent_link(
                child,
                parent_hits=[SkillRetrievalHit(skill=parent, score=0.0, vector_score=0.0, bm25_score=0.0)],
                allowed_parent_nodes=["session_framework"],
            )

            self.assertEqual(decision.get("decision"), "defer")
            self.assertEqual(decision.get("parent_skill_id"), "")

    def test_classify_change_omits_peer_candidates_without_split_signal(self) -> None:
        manager = VersionManager(registry=DocumentRegistry(root_dir="/tmp/non-persistent"), llm=self._llm())
        support = self._support(support_id="sup-limit", doc_id="doc-limit", excerpt="Build rapport first.")
        skill = self._skill(
            skill_id="cand-limit",
            name="intake candidate",
            workflow_steps=["Build rapport first."],
            support_ids=[support.support_id],
        )
        peers = [
            self._skill(
                skill_id=f"peer-{idx}",
                name=f"peer {idx}",
                workflow_steps=[f"step {idx}"],
                support_ids=[support.support_id],
            )
            for idx in range(5)
        ]

        captured: dict[str, object] = {}

        class CaptureLLM:
            def complete(self, *, system=None, user="", temperature=0.0):
                captured["payload"] = json.loads(user)
                return json.dumps({"action": "create", "reason": "create"}, ensure_ascii=False)

        manager.llm = CaptureLLM()
        decision = manager.classify_change(
            skill,
            peer_skills=peers,
            existing_skills=[],
            support_by_id={support.support_id: support},
        )

        self.assertEqual(decision.action, "create")
        self.assertNotIn("peer_candidates", dict(captured.get("payload") or {}))

    def test_classify_change_hits_zero_uses_compact_create_discard_prompt(self) -> None:
        manager = VersionManager(registry=DocumentRegistry(root_dir="/tmp/non-persistent"), llm=self._llm())
        support = self._support(support_id="sup-create", doc_id="doc-create", excerpt="Build rapport first.")
        skill = self._skill(
            skill_id="cand-create",
            name="intake candidate",
            workflow_steps=["Build rapport first."],
            support_ids=[support.support_id],
        )

        captured: dict[str, object] = {}

        class CaptureLLM:
            def complete(self, *, system=None, user="", temperature=0.0):
                captured["system"] = system
                captured["payload"] = json.loads(user)
                return json.dumps({"action": "create", "reason": "create"}, ensure_ascii=False)

        manager.llm = CaptureLLM()
        decision = manager.classify_change(
            skill,
            peer_skills=[],
            existing_skills=[],
            support_by_id={support.support_id: support},
        )

        self.assertEqual(decision.action, "create")
        self.assertIn("created or discarded", str(captured.get("system") or ""))
        self.assertNotIn("existing_skills", dict(captured.get("payload") or {}))
        self.assertNotIn("peer_candidates", dict(captured.get("payload") or {}))

    def test_classify_change_includes_single_peer_candidate_for_split_signal(self) -> None:
        manager = VersionManager(registry=DocumentRegistry(root_dir="/tmp/non-persistent"), llm=self._llm())
        support = self._support(support_id="sup-split", doc_id="doc-split", excerpt="Build rapport first.")
        child = self._skill(
            skill_id="cand-child",
            name="rapport building / intake",
            asset_type="session_skill",
            granularity="session",
            objective="Establish rapport during intake.",
            workflow_steps=["Build rapport first."],
            support_ids=[support.support_id],
            asset_level=2,
        )
        peer = self._skill(
            skill_id="peer-child",
            name="intake risk screening",
            asset_type="session_skill",
            granularity="session",
            objective="Assess acute risk during intake.",
            workflow_steps=["Assess acute risk."],
            support_ids=[support.support_id],
            asset_level=2,
        )
        parent = self._skill(
            skill_id="existing-parent",
            name="intake workflow",
            asset_type="macro_protocol",
            granularity="macro",
            objective="Run the full intake protocol.",
            workflow_steps=["Build rapport first.", "Assess acute risk.", "Set an agenda."],
            support_ids=[support.support_id],
            asset_level=1,
        )

        captured: dict[str, object] = {}

        class CaptureLLM:
            def complete(self, *, system=None, user="", temperature=0.0):
                captured["payload"] = json.loads(user)
                return json.dumps({"action": "create", "reason": "create"}, ensure_ascii=False)

        manager.llm = CaptureLLM()
        decision = manager.classify_change(
            child,
            peer_skills=[peer],
            existing_skills=[parent],
            support_by_id={support.support_id: support},
        )

        self.assertEqual(decision.action, "create")
        self.assertEqual(len(list((captured.get("payload") or {}).get("peer_candidates") or [])), 1)

    def test_classify_change_payload_includes_contract_fields(self) -> None:
        manager = VersionManager(registry=DocumentRegistry(root_dir="/tmp/non-persistent"), llm=self._llm())
        support = self._support(support_id="sup-contract", doc_id="doc-contract", excerpt="Build rapport first.")
        skill = self._skill(
            skill_id="cand-contract",
            name="structured intake",
            workflow_steps=["Build rapport first."],
            support_ids=[support.support_id],
        )
        skill.applicable_signals = ["来访者首次进入评估阶段。"]
        skill.contraindications = ["急性危机需先分流。"]
        skill.output_contract = ["形成结构化 intake 总结。"]
        existing = self._skill(
            skill_id="existing-contract",
            name="structured intake existing",
            workflow_steps=["Build rapport first."],
            support_ids=[support.support_id],
        )
        existing.applicable_signals = ["首次评估。"]
        existing.contraindications = ["危机需先转介。"]
        existing.output_contract = ["形成 intake 结论。"]

        captured: dict[str, object] = {}

        class CaptureLLM:
            def complete(self, *, system=None, user="", temperature=0.0):
                _ = system, temperature
                captured["payload"] = json.loads(user)
                return json.dumps({"action": "create", "reason": "create"}, ensure_ascii=False)

        manager.llm = CaptureLLM()
        decision = manager.classify_change(
            skill,
            peer_skills=[],
            existing_skills=[existing],
            support_by_id={support.support_id: support},
        )

        self.assertEqual(decision.action, "create")
        payload = dict(captured.get("payload") or {})
        self.assertEqual(payload["candidate_skill"]["applicable_signals"], ["来访者首次进入评估阶段。"])
        self.assertEqual(payload["candidate_skill"]["contraindications"], ["急性危机需先分流。"])
        self.assertEqual(payload["existing_skills"][0]["output_contract"], ["形成 intake 结论。"])

    def test_classify_change_invalid_merge_target_falls_back_to_create(self) -> None:
        manager = VersionManager(registry=DocumentRegistry(root_dir="/tmp/non-persistent"), llm=self._llm())
        support = self._support(support_id="sup-merge", doc_id="doc-merge", excerpt="Build rapport first.")
        skill = self._skill(
            skill_id="cand-merge",
            name="intake candidate",
            workflow_steps=["Build rapport first."],
            support_ids=[support.support_id],
        )
        existing = self._skill(
            skill_id="existing-1",
            name="existing intake",
            workflow_steps=["Build rapport first."],
            support_ids=[support.support_id],
        )

        class CaptureLLM:
            def complete(self, *, system=None, user="", temperature=0.0):
                _ = system, user, temperature
                return json.dumps(
                    {
                        "action": "merge",
                        "target_skill_ids": ["missing-existing-id"],
                        "reason": "merge",
                    },
                    ensure_ascii=False,
                )

        manager.llm = CaptureLLM()
        decision = manager.classify_change(
            skill,
            peer_skills=[],
            existing_skills=[existing],
            support_by_id={support.support_id: support},
        )

        self.assertEqual(decision.action, "create")
        self.assertEqual(decision.matched_skill_ids, [])

    def test_same_skill_strengthens_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            doc1 = self._document(doc_id="doc-1")
            sup1 = self._support(support_id="sup-1", doc_id=doc1.doc_id, excerpt="Build rapport first.")
            skill1 = self._skill(
                skill_id="cand-1",
                name="rapport building / intake",
                workflow_steps=["Build rapport first.", "Clarify the immediate concern."],
                constraints=["Do not push interpretation too early."],
                support_ids=[sup1.support_id],
            )
            first = self._register(registry=registry, documents=[doc1], supports=[sup1], skills=[skill1])
            existing_id = first.skill_specs[0].skill_id

            doc2 = self._document(doc_id="doc-2")
            sup2 = self._support(support_id="sup-2", doc_id=doc2.doc_id, excerpt="Clarify the immediate concern.")
            skill2 = self._skill(
                skill_id="cand-2",
                name="rapport building / intake",
                workflow_steps=["Build rapport first.", "Clarify the immediate concern."],
                constraints=["Do not push interpretation too early."],
                support_ids=[sup2.support_id],
            )
            second = self._register(registry=registry, documents=[doc2], supports=[sup2], skills=[skill2])

            self.assertEqual(len(second.skill_specs), 1)
            updated = second.skill_specs[0]
            self.assertEqual(updated.skill_id, existing_id)
            self.assertEqual(updated.version, "0.1.1")
            self.assertEqual(second.lifecycles[0].reason, "strengthen")
            self.assertEqual(second.support_records[0].skill_id, existing_id)

    def test_split_existing_skill_into_two_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            parent_doc = self._document(doc_id="doc-parent")
            parent_support = self._support(
                support_id="sup-parent",
                doc_id=parent_doc.doc_id,
                excerpt="Build rapport, check acute risk, and set a session agenda.",
            )
            parent_skill = self._skill(
                skill_id="parent-skill",
                name="intake workflow",
                asset_type="macro_protocol",
                granularity="macro",
                objective="Run the full intake protocol.",
                workflow_steps=[
                    "Build rapport first.",
                    "Check acute risk.",
                    "Set a session agenda.",
                ],
                constraints=["Do not rush interpretation."],
                support_ids=[parent_support.support_id],
            )
            first = self._register(registry=registry, documents=[parent_doc], supports=[parent_support], skills=[parent_skill])
            existing_parent = first.skill_specs[0]

            doc_child = self._document(doc_id="doc-child")
            support_a = self._support(support_id="sup-a", doc_id=doc_child.doc_id, excerpt="Build rapport first.")
            support_b = self._support(support_id="sup-b", doc_id=doc_child.doc_id, excerpt="Check acute risk immediately.")
            child_a = self._skill(
                skill_id="child-a",
                name="rapport building / intake",
                asset_type="session_skill",
                granularity="session",
                objective="Establish rapport at the start of intake.",
                workflow_steps=["Build rapport first."],
                constraints=["Do not rush interpretation."],
                support_ids=[support_a.support_id],
            )
            child_b = self._skill(
                skill_id="child-b",
                name="intake workflow / risk screening",
                asset_type="session_skill",
                granularity="session",
                objective="Run the acute risk screening subflow during intake.",
                workflow_steps=["Check acute risk immediately."],
                constraints=["Do not rush interpretation."],
                support_ids=[support_b.support_id],
            )

            second = self._register(
                registry=registry,
                documents=[doc_child],
                supports=[support_a, support_b],
                skills=[child_a, child_b],
            )

            deprecated_parent = [skill for skill in second.skill_specs if skill.skill_id == existing_parent.skill_id and skill.status == VersionState.DEPRECATED]
            active_children = [skill for skill in second.skill_specs if skill.skill_id != existing_parent.skill_id]

            self.assertEqual(len(active_children), 2)
            self.assertTrue(deprecated_parent)
            self.assertTrue(any(event.reason == "split" for event in second.lifecycles))

    def test_merge_multiple_existing_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            doc1 = self._document(doc_id="doc-1")
            sup1 = self._support(support_id="sup-1", doc_id=doc1.doc_id, excerpt="Build rapport and assess risk.")
            skill1 = self._skill(
                skill_id="skill-1",
                name="intake stabilization workflow",
                workflow_steps=["Build rapport first.", "Assess acute risk."],
                support_ids=[sup1.support_id],
            )
            registry.upsert_document(doc1)
            registry.upsert_support(self._support(support_id=sup1.support_id, doc_id=sup1.doc_id, excerpt=sup1.excerpt, relation_type=sup1.relation_type))
            registry.upsert_skill(skill1)

            doc2 = self._document(doc_id="doc-2")
            sup2 = self._support(support_id="sup-2", doc_id=doc2.doc_id, excerpt="Build rapport, assess risk, clarify concern.")
            skill2 = self._skill(
                skill_id="skill-2",
                name="intake stabilization workflow",
                workflow_steps=["Build rapport first.", "Assess acute risk.", "Clarify the immediate concern."],
                support_ids=[sup2.support_id],
            )
            registry.upsert_document(doc2)
            registry.upsert_support(self._support(support_id=sup2.support_id, doc_id=sup2.doc_id, excerpt=sup2.excerpt, relation_type=sup2.relation_type))
            registry.upsert_skill(skill2)

            doc3 = self._document(doc_id="doc-3")
            sup3 = self._support(support_id="sup-3", doc_id=doc3.doc_id, excerpt="Build rapport, assess risk, clarify concern.")
            merged_candidate = self._skill(
                skill_id="cand-merge",
                name="intake stabilization workflow",
                workflow_steps=["Build rapport first.", "Assess acute risk.", "Clarify the immediate concern."],
                support_ids=[sup3.support_id],
            )

            result = self._register(registry=registry, documents=[doc3], supports=[sup3], skills=[merged_candidate])

            self.assertTrue(any(log["action"] == "merge" for log in result.change_logs))
            self.assertTrue(any(skill.status == VersionState.DEPRECATED for skill in result.skill_specs))

    def test_document_retriever_prefers_metadata_and_skill_identity_matches(self) -> None:
        retriever = build_document_skill_retriever(
            embeddings_config={"provider": "hashing", "dims": 64},
            bm25_weight=0.1,
        )
        matching = self._skill(
            skill_id="match",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。", "总结与作业。"],
            support_ids=["sup-match"],
            method_family="cbt",
        )
        matching.metadata["family_name"] = "认知行为疗法"
        matching.metadata["domain_type"] = "psychology"
        distractor = self._skill(
            skill_id="distractor",
            name="认知重评会谈流程",
            objective="Run an interpretive psychodynamic exploration of recurring themes.",
            workflow_steps=["建立自由联想框架。", "追踪移情。", "解释防御。", "总结核心冲突。"],
            support_ids=["sup-distractor"],
            method_family="psychodynamic",
        )
        distractor.metadata["family_name"] = "Psychodynamic（心理动力学）"
        distractor.metadata["domain_type"] = "psychology"
        retriever.refresh([distractor, matching])

        candidate = self._skill(
            skill_id="candidate",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。", "总结与作业。"],
            support_ids=["sup-candidate"],
            method_family="cbt",
        )
        candidate.metadata["family_name"] = "认知行为疗法"
        candidate.metadata["domain_type"] = "psychology"

        hits = retriever.search(candidate, limit=2)

        self.assertEqual(["match"], [hit.skill.skill_id for hit in hits])

    def test_document_retriever_filters_across_profile_ids(self) -> None:
        retriever = build_document_skill_retriever(
            embeddings_config={"provider": "hashing", "dims": 64},
            bm25_weight=0.1,
        )
        matching = self._skill(
            skill_id="match",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。", "总结与作业。"],
            support_ids=["sup-match"],
            method_family="cbt",
        )
        matching.metadata["family_name"] = "认知行为疗法"
        matching.metadata["domain_type"] = "psychology"
        matching.metadata["taxonomy_id"] = "psychology"
        matching.metadata["profile_id"] = "psychology::认知行为疗法"

        other_profile = self._skill(
            skill_id="other-profile",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。", "总结与作业。"],
            support_ids=["sup-other"],
            method_family="cbt",
        )
        other_profile.metadata["family_name"] = "认知行为疗法"
        other_profile.metadata["domain_type"] = "psychology"
        other_profile.metadata["taxonomy_id"] = "psychology"
        other_profile.metadata["profile_id"] = "psychology::人本-存在主义"

        retriever.refresh([matching, other_profile])

        candidate = self._skill(
            skill_id="candidate",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。", "总结与作业。"],
            support_ids=["sup-candidate"],
            method_family="cbt",
        )
        candidate.metadata["family_name"] = "认知行为疗法"
        candidate.metadata["domain_type"] = "psychology"
        candidate.metadata["taxonomy_id"] = "psychology"
        candidate.metadata["profile_id"] = "psychology::认知行为疗法"

        hits = retriever.search(candidate, limit=5)

        self.assertEqual(["match"], [hit.skill.skill_id for hit in hits])

    def test_document_retriever_filters_low_similarity_hits(self) -> None:
        retriever = build_document_skill_retriever(
            embeddings_config={"provider": "hashing", "dims": 64},
            bm25_weight=0.1,
        )
        unrelated = self._skill(
            skill_id="unrelated",
            name="危机转介规则",
            objective="Handle crisis referral and escalation.",
            workflow_steps=["评估危机。", "安排转介。"],
            support_ids=["sup-unrelated"],
            method_family="safety",
            task_family="crisis",
            stage="triage",
        )
        unrelated.metadata["family_name"] = "认知行为疗法"
        unrelated.metadata["domain_type"] = "psychology"

        candidate = self._skill(
            skill_id="candidate",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。"],
            support_ids=["sup-candidate"],
            method_family="cbt",
            task_family="cognitive_restructuring",
            stage="session_work",
        )
        candidate.metadata["family_name"] = "认知行为疗法"
        candidate.metadata["domain_type"] = "psychology"

        retriever.refresh([unrelated])
        hits = retriever.search(candidate)

        self.assertEqual([], hits)

    def test_document_retriever_honors_custom_score_threshold(self) -> None:
        base_kwargs = {
            "embeddings_config": {"provider": "hashing", "dims": 64},
            "bm25_weight": 0.1,
        }
        matching = self._skill(
            skill_id="match",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。", "总结与作业。"],
            support_ids=["sup-match"],
            method_family="cbt",
            task_family="cognitive_restructuring",
            stage="session_work",
        )
        matching.metadata["family_name"] = "认知行为疗法"
        matching.metadata["domain_type"] = "psychology"

        candidate = self._skill(
            skill_id="candidate",
            name="认知重评会谈流程",
            objective="Run an agenda-based CBT cognitive reframing session.",
            workflow_steps=["建立议程。", "识别自动思维。", "进行重评。", "总结与作业。"],
            support_ids=["sup-candidate"],
            method_family="cbt",
            task_family="cognitive_restructuring",
            stage="session_work",
        )
        candidate.metadata["family_name"] = "认知行为疗法"
        candidate.metadata["domain_type"] = "psychology"

        low_threshold = build_document_skill_retriever(score_threshold=0.3, **base_kwargs)
        low_threshold.refresh([matching])
        low_hits = low_threshold.search(candidate, limit=2)

        high_threshold = build_document_skill_retriever(score_threshold=1.01, **base_kwargs)
        high_threshold.refresh([matching])
        high_hits = high_threshold.search(candidate, limit=2)

        self.assertEqual(["match"], [hit.skill.skill_id for hit in low_hits])
        self.assertEqual([], high_hits)

    def test_document_retriever_persists_vectors_and_bm25_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = build_document_skill_retriever(
                embeddings_config={"provider": "hashing", "dims": 64},
                bm25_weight=0.1,
                base_store_root=tmpdir,
            )
            matching = self._skill(
                skill_id="match",
                name="认知重评会谈流程",
                objective="Run an agenda-based CBT cognitive reframing session.",
                workflow_steps=["建立议程。", "识别自动思维。", "进行重评。"],
                support_ids=["sup-match"],
                method_family="cbt",
            )
            matching.metadata["family_name"] = "认知行为疗法"
            matching.metadata["domain_type"] = "psychology"
            retriever.refresh([matching])

            cache_path = retrieval_cache_path(tmpdir)
            self.assertTrue(os.path.isfile(cache_path))
            with open(cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            entry = dict((payload.get("entries") or {}).get("match") or {})
            self.assertTrue(entry.get("text"))
            self.assertTrue(entry.get("tokens"))
            self.assertTrue(entry.get("vector"))

    def test_document_retriever_invalidates_cached_vectors_when_embedding_config_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            matching = self._skill(
                skill_id="match",
                name="认知重评会谈流程",
                objective="Run an agenda-based CBT cognitive reframing session.",
                workflow_steps=["建立议程。", "识别自动思维。", "进行重评。"],
                support_ids=["sup-match"],
                method_family="cbt",
            )
            matching.metadata["family_name"] = "认知行为疗法"
            matching.metadata["domain_type"] = "psychology"

            retriever64 = build_document_skill_retriever(
                embeddings_config={"provider": "hashing", "dims": 64},
                bm25_weight=0.1,
                base_store_root=tmpdir,
            )
            retriever64.refresh([matching])
            self.assertEqual(64, len(retriever64._vectors["match"]))

            retriever16 = build_document_skill_retriever(
                embeddings_config={"provider": "hashing", "dims": 16},
                bm25_weight=0.1,
                base_store_root=tmpdir,
            )
            self.assertEqual({}, retriever16._vectors)
            retriever16.refresh([matching])
            self.assertEqual(16, len(retriever16._vectors["match"]))

    def test_register_versions_retrieves_relevant_existing_skill_beyond_registry_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            base_doc = self._document(doc_id="doc-base", title="Many Existing Skills")

            for index in range(15):
                support = self._support(
                    support_id=f"sup-noise-{index}",
                    doc_id=base_doc.doc_id,
                    excerpt=f"Noise excerpt {index}",
                )
                registry.upsert_support(support)
                noise = self._skill(
                    skill_id=f"noise-{index}",
                    name=f"noise workflow {index}",
                    workflow_steps=["Observe.", "Summarize.", "Close."],
                    support_ids=[support.support_id],
                    task_family="psychoeducation",
                    method_family="general_support",
                    stage="general",
                )
                registry.upsert_skill(noise)

            target_support = self._support(
                support_id="sup-target",
                doc_id=base_doc.doc_id,
                excerpt="Build rapport first and clarify the immediate concern.",
            )
            target_skill = self._skill(
                skill_id="target-skill",
                name="rapport building / intake",
                workflow_steps=["Build rapport first.", "Clarify the immediate concern."],
                constraints=["Do not push interpretation too early."],
                support_ids=[target_support.support_id],
            )
            registry.upsert_support(target_support)
            registry.upsert_skill(target_skill)

            new_doc = self._document(doc_id="doc-new", title="Retrieved Match")
            new_support = self._support(
                support_id="sup-new",
                doc_id=new_doc.doc_id,
                excerpt="Build rapport first and clarify the immediate concern.",
            )
            candidate = self._skill(
                skill_id="cand-new",
                name="rapport building / intake",
                workflow_steps=["Build rapport first.", "Clarify the immediate concern."],
                constraints=["Do not push interpretation too early."],
                support_ids=[new_support.support_id],
            )

            result = self._register(
                registry=registry,
                documents=[new_doc],
                supports=[new_support],
                skills=[candidate],
            )

            self.assertEqual(1, len(result.skill_specs))
            self.assertEqual("target-skill", result.skill_specs[0].skill_id)
            self.assertEqual("0.1.1", result.skill_specs[0].version)
            self.assertTrue(any(event.reason == "strengthen" for event in result.lifecycles))

    def test_conflicting_new_support_can_deprecate_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            base_doc = self._document(doc_id="doc-base")
            base_support = self._support(
                support_id="sup-base",
                doc_id=base_doc.doc_id,
                excerpt="Challenge avoidance directly during crisis intake.",
            )
            base_skill = self._skill(
                skill_id="base-skill",
                name="direct challenge / crisis intake",
                workflow_steps=["Challenge avoidance directly.", "Push for cognitive restructuring."],
                constraints=["Keep the session moving quickly."],
                support_ids=[base_support.support_id],
                task_family="assessment",
                stage="crisis",
            )
            self._register(registry=registry, documents=[base_doc], supports=[base_support], skills=[base_skill])

            new_doc = self._document(doc_id="doc-new")
            conflict_support = self._support(
                support_id="sup-conflict",
                doc_id=new_doc.doc_id,
                excerpt="Do not challenge avoidance directly during acute crisis; stabilize first.",
                relation_type=SupportRelation.CONFLICT,
            )
            new_skill = self._skill(
                skill_id="cand-new",
                name="crisis stabilization / intake",
                workflow_steps=["Stabilize acute distress first.", "Avoid direct confrontation."],
                constraints=["Do not intensify affect before stabilization."],
                support_ids=[conflict_support.support_id],
                task_family="assessment",
                stage="crisis",
            )

            result = self._register(registry=registry, documents=[new_doc], supports=[conflict_support], skills=[new_skill])

            self.assertTrue(any(skill.status in {VersionState.WATCHLIST, VersionState.DEPRECATED} for skill in result.skill_specs))
            self.assertTrue(any(log["action"] == "deprecate" for log in result.change_logs))

    def test_cross_granularity_candidate_does_not_merge_into_existing_macro_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, "registry"))
            base_doc = self._document(doc_id="doc-base")
            base_support = self._support(
                support_id="sup-base",
                doc_id=base_doc.doc_id,
                excerpt="Build rapport, assess risk, and set a session agenda.",
            )
            macro_skill = self._skill(
                skill_id="base-macro",
                name="intake workflow",
                asset_type="macro_protocol",
                granularity="macro",
                objective="Run the full intake protocol.",
                workflow_steps=[
                    "Build rapport first.",
                    "Assess acute risk.",
                    "Set a session agenda.",
                ],
                support_ids=[base_support.support_id],
            )
            self._register(registry=registry, documents=[base_doc], supports=[base_support], skills=[macro_skill])

            new_doc = self._document(doc_id="doc-new")
            micro_support = self._support(
                support_id="sup-micro",
                doc_id=new_doc.doc_id,
                excerpt="Reflect the client's main feeling before asking the next question.",
            )
            micro_skill = self._skill(
                skill_id="cand-micro",
                name="intake workflow",
                asset_type="micro_skill",
                granularity="micro",
                objective="Deliver a single empathic reflection move.",
                workflow_steps=[],
                intervention_moves=["Reflect the client's main feeling before the next question."],
                support_ids=[micro_support.support_id],
            )

            result = self._register(registry=registry, documents=[new_doc], supports=[micro_support], skills=[micro_skill])

            active_created = [
                skill
                for skill in result.skill_specs
                if skill.status == VersionState.ACTIVE and skill.asset_type == "micro_skill"
            ]
            self.assertTrue(active_created)
            self.assertTrue(any(event.reason.startswith("create") for event in result.lifecycles))

    def test_register_versions_writes_visible_parent_child_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="CBT Paper")
            support = self._support(
                support_id="sup-1",
                doc_id=document.doc_id,
                excerpt="Build a collaborative agenda and assign practice homework.",
            )
            skill = self._skill(
                skill_id="cand-1",
                name="认知重构作业布置",
                workflow_steps=["建立议程。", "识别自动思维。", "布置记录表作业。", "说明复盘方式。"],
                constraints=["不要带入具体个案姓名。"],
                support_ids=[support.support_id],
                domain="psychology",
                task_family="homework",
                method_family="cbt",
                stage="intervention",
            )

            result = self._register(
                registry=registry,
                documents=[document],
                supports=[support],
                skills=[skill],
                metadata={
                    "family_name": "认知行为疗法",
                    "profile_id": "test_therapy_v2",
                    "taxonomy_axis": "疗法",
                },
            )

            parent_md = result.visible_tree["parent_paths"][0]
            children_manifest = os.path.join(os.path.dirname(parent_md), "references", "children_manifest.json")
            child_md = result.visible_tree["child_paths"][0]
            evidence_md = os.path.join(os.path.dirname(child_md), "references", "evidence.md")
            evidence_manifest = os.path.join(os.path.dirname(child_md), "references", "evidence_manifest.json")
            library_manifest = os.path.join(tmpdir, ".runtime", "library_manifest.json")

            self.assertTrue(os.path.isfile(parent_md))
            self.assertTrue(os.path.isfile(children_manifest))
            self.assertTrue(os.path.isfile(child_md))
            self.assertTrue(os.path.isfile(evidence_md))
            self.assertTrue(os.path.isfile(evidence_manifest))
            self.assertTrue(os.path.isfile(library_manifest))
            self.assertEqual(result.visible_tree.get("affected_families"), ["认知行为疗法"])
            self.assertEqual(len(list(result.staging_runs or [])), 1)
            self.assertTrue(os.path.isdir(result.staging_runs[0]["run_dir"]))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        result.staging_runs[0]["run_dir"],
                        "canonical_results.json",
                    )
                )
            )

            with open(children_manifest, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload.get("family_name"), "认知行为疗法")
            self.assertEqual(len(list(payload.get("children") or [])), 1)
            self.assertEqual(
                payload["children"][0]["relative_path"],
                os.path.relpath(child_md, tmpdir).replace(os.sep, "/"),
            )

            with open(evidence_md, "r", encoding="utf-8") as f:
                evidence_text = f.read()
            self.assertIn("quote:", evidence_text)
            self.assertIn("Build a collaborative agenda", evidence_text)

            with open(library_manifest, "r", encoding="utf-8") as f:
                manifest_payload = json.load(f)
            self.assertEqual(manifest_payload.get("active_domain_root_name"), "心理咨询")
            self.assertEqual(manifest_payload.get("active_profile_id"), "test_therapy_v2")
            self.assertEqual(manifest_payload.get("active_family_name"), "认知行为疗法")
            self.assertEqual(manifest_payload["profiles"][0]["profile_id"], "test_therapy_v2")

    def test_visible_tree_avoids_reserved_root_name_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="Reserved School")
            support = self._support(
                support_id="sup-1",
                doc_id=document.doc_id,
                excerpt="Build a structured intake agenda.",
            )
            skill = self._skill(
                skill_id="cand-1",
                name="保留目录名测试技能",
                workflow_steps=["建立议程。", "确认目标。", "说明边界。", "安排总结。"],
                support_ids=[support.support_id],
            )

            result = self._register(
                registry=registry,
                documents=[document],
                supports=[support],
                skills=[skill],
                metadata={"family_name": "Users"},
            )

            self.assertEqual(result.visible_tree.get("affected_families"), ["Users-skills"])
            parent_md = result.visible_tree["parent_paths"][0]
            self.assertTrue(os.path.isfile(parent_md))
            self.assertIn("/Users-skills/总技能/SKILL.md", parent_md.replace(os.sep, "/"))
            self.assertNotIn("/Users/总技能/SKILL.md", parent_md.replace(os.sep, "/"))

    def test_visible_tree_prefers_store_final_skills_over_registry_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="Merged Tree")
            support_a = self._support(
                support_id="sup-a",
                doc_id=document.doc_id,
                excerpt="Use ABC mapping to identify belief patterns.",
            )
            support_b = self._support(
                support_id="sup-b",
                doc_id=document.doc_id,
                excerpt="Use diaphragmatic breathing to regulate arousal.",
            )
            skill_a = self._skill(
                skill_id="cand-a",
                name="ABC模型结构化识别与不合理信念标注",
                workflow_steps=["识别A。", "识别B。", "识别C。", "完成标注。"],
                support_ids=[support_a.support_id],
            )
            skill_b = self._skill(
                skill_id="cand-b",
                name="腹式呼吸放松法标准化指导",
                workflow_steps=["调整姿势。", "建立节律。", "完成练习。", "布置作业。"],
                support_ids=[support_b.support_id],
            )
            registry.upsert_document(document)
            registry.upsert_support(support_a)
            registry.upsert_support(support_b)
            registry.upsert_skill(skill_a)
            registry.upsert_skill(skill_b)

            merged_store_skill = Skill(
                id="store-1",
                user_id="u1",
                name="结构化短期咨询框架确立与首次评估会话（5次CBT）",
                description="Merged final store skill.",
                instructions="# Goal\nUse the merged final store skill.",
                triggers=["首次评估", "短期咨询框架"],
                tags=["CBT", "认知行为疗法"],
                status=SkillStatus.ACTIVE,
                version="0.1.3",
                files={},
            )

            result = sync_visible_skill_tree(
                registry=registry,
                store_root=tmpdir,
                documents=[document],
                support_records=[support_a, support_b],
                skill_specs=[skill_a, skill_b],
                user_id="u1",
                metadata={"family_name": "认知行为疗法", "profile_id": "test_therapy_v2", "taxonomy_axis": "疗法"},
                store_skills=[merged_store_skill],
            )

            self.assertEqual(result.affected_families, ["认知行为疗法"])
            child_root = os.path.dirname(os.path.dirname(result.child_paths[0]))
            child_dirs = sorted(name for name in os.listdir(child_root) if os.path.isdir(os.path.join(child_root, name)))
            self.assertEqual(len(child_dirs), 1)
            child_md = os.path.join(child_root, child_dirs[0], "SKILL.md")
            with open(child_md, "r", encoding="utf-8") as f:
                child_text = f.read()
            self.assertIn("结构化短期咨询框架确立与首次评估会话（5次CBT）", child_text)
            self.assertNotIn("ABC模型结构化识别与不合理信念标注", child_text)

    def test_visible_tree_prefers_store_provenance_before_fuzzy_name_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="Precise Evidence")
            support_exact = self._support(
                support_id="sup-exact",
                doc_id=document.doc_id,
                excerpt="Use collaborative agenda setting before deeper intervention.",
            )
            support_distractor = self._support(
                support_id="sup-distractor",
                doc_id=document.doc_id,
                excerpt="Use a different breathing exercise as homework.",
            )
            registry_skill_exact = self._skill(
                skill_id="cand-exact",
                name="结构化首次会谈框架",
                workflow_steps=["建立议程。", "明确目标。", "风险检查。", "总结安排。"],
                support_ids=[support_exact.support_id],
            )
            registry_skill_distractor = self._skill(
                skill_id="cand-distractor",
                name="结构化首次会谈框架与放松练习",
                workflow_steps=["说明呼吸。", "带领练习。", "回顾体验。", "布置作业。"],
                support_ids=[support_distractor.support_id],
            )
            registry.upsert_document(document)
            registry.upsert_support(support_exact)
            registry.upsert_support(support_distractor)
            registry.upsert_skill(registry_skill_exact)
            registry.upsert_skill(registry_skill_distractor)

            store_skill = Skill(
                id="store-precise",
                user_id="u1",
                name="结构化首次会谈框架（最终版）",
                description="Final store skill with explicit provenance.",
                instructions="# Goal\nUse the final skill.",
                triggers=["首次会谈"],
                tags=["CBT", "认知行为疗法"],
                status=SkillStatus.ACTIVE,
                version="0.1.2",
                files={},
                source={
                    "source_type": "document_skill",
                    "skill_spec_id": registry_skill_exact.skill_id,
                    "support_ids": [support_exact.support_id],
                },
            )

            result = sync_visible_skill_tree(
                registry=registry,
                store_root=tmpdir,
                documents=[document],
                support_records=[support_exact, support_distractor],
                skill_specs=[registry_skill_exact, registry_skill_distractor],
                user_id="u1",
                metadata={"family_name": "认知行为疗法", "profile_id": "test_therapy_v2", "taxonomy_axis": "疗法"},
                store_skills=[store_skill],
            )

            self.assertEqual(result.affected_families, ["认知行为疗法"])
            evidence_md = os.path.join(os.path.dirname(result.child_paths[0]), "references", "evidence.md")
            with open(evidence_md, "r", encoding="utf-8") as f:
                evidence_text = f.read()
            self.assertIn("Use collaborative agenda setting", evidence_text)
            self.assertNotIn("different breathing exercise", evidence_text)

    def test_visible_tree_filters_store_skills_to_requested_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="Family Filter")
            support = self._support(
                support_id="sup-cbt",
                doc_id=document.doc_id,
                excerpt="Use agenda-based CBT reframing.",
            )
            registry_skill = self._skill(
                skill_id="cand-cbt",
                name="认知重评会谈流程",
                workflow_steps=["建立议程。", "识别自动想法。", "进行重评。", "总结与作业。"],
                support_ids=[support.support_id],
            )
            registry_skill.metadata["family_name"] = "认知行为疗法"
            registry.upsert_document(document)
            registry.upsert_support(support)
            registry.upsert_skill(registry_skill)

            cbt_store = Skill(
                id="store-cbt",
                user_id="docskill",
                name="认知重评会谈流程",
                description="CBT final skill.",
                instructions="# Goal\nUse CBT reframing.",
                triggers=["认知重评"],
                tags=["CBT"],
                status=SkillStatus.ACTIVE,
                version="0.1.0",
                files={},
                metadata={"family_name": "认知行为疗法"},
                source={"source_type": "document_skill", "skill_spec_id": "cand-cbt"},
            )
            psychodynamic_store = Skill(
                id="store-pd",
                user_id="docskill",
                name="移情解释",
                description="Psychodynamic final skill.",
                instructions="# Goal\nUse psychodynamic interpretation.",
                triggers=["移情"],
                tags=["Psychodynamic"],
                status=SkillStatus.ACTIVE,
                version="0.1.0",
                files={},
                metadata={"family_name": "Psychodynamic（心理动力学）"},
                source={"source_type": "document_skill", "skill_spec_id": "cand-pd"},
            )

            result = sync_visible_skill_tree(
                registry=registry,
                store_root=tmpdir,
                documents=[document],
                support_records=[support],
                skill_specs=[registry_skill],
                user_id="docskill",
                metadata={
                    "family_name": "认知行为疗法",
                    "profile_id": "test_therapy_v2",
                    "taxonomy_axis": "疗法",
                    "domain_root_name": "心理咨询",
                },
                store_skills=[cbt_store, psychodynamic_store],
            )

            child_root = os.path.dirname(os.path.dirname(result.child_paths[0]))
            child_dirs = sorted(name for name in os.listdir(child_root) if os.path.isdir(os.path.join(child_root, name)))
            self.assertEqual(["认知重评会谈流程"], child_dirs)

    def test_register_versions_links_parent_and_child_skill_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="Hierarchical Tree")
            support_parent = self._support(
                support_id="sup-parent",
                doc_id=document.doc_id,
                excerpt="Run a structured first-session CBT framework with agenda setting and case focus.",
            )
            support_child = self._support(
                support_id="sup-child",
                doc_id=document.doc_id,
                excerpt="Ask one Socratic question to challenge the client's automatic thought.",
            )
            parent_skill = self._skill(
                skill_id="cand-parent",
                name="结构化首次会谈框架",
                asset_type="session_skill",
                granularity="session",
                asset_node_id="session_framework",
                asset_level=2,
                visible_role="parent",
                workflow_steps=["建立议程。", "明确目标。", "聚焦自动想法。", "总结安排。"],
                support_ids=[support_parent.support_id],
            )
            child_skill = self._skill(
                skill_id="cand-child",
                name="苏格拉底式提问",
                asset_type="micro_skill",
                granularity="micro",
                asset_node_id="micro_intervention",
                asset_level=3,
                visible_role="leaf",
                workflow_steps=["选定自动想法。", "提出证据问题。", "追问替代解释。", "总结结论。"],
                support_ids=[support_child.support_id],
            )

            result = self._register(
                registry=registry,
                documents=[document],
                supports=[support_parent, support_child],
                skills=[parent_skill, child_skill],
                metadata={
                    "family_name": "认知行为疗法",
                    "profile_id": "test_therapy_v2",
                    "taxonomy_axis": "疗法",
                    "domain_root_name": "心理咨询",
                    "visible_levels": {"1": "一级技能", "2": "二级技能", "3": "微技能"},
                },
            )

            linked_child = next(skill for skill in result.skill_specs if skill.skill_id == "cand-child")
            self.assertEqual(linked_child.parent_skill_id, "cand-parent")
            self.assertEqual(linked_child.hierarchy_status, "linked")

            parent_md = os.path.join(
                tmpdir,
                "心理咨询",
                "Family技能",
                "认知行为疗法",
                "二级技能",
                "结构化首次会谈框架",
                "SKILL.md",
            )
            child_manifest = os.path.join(
                tmpdir,
                "心理咨询",
                "Family技能",
                "认知行为疗法",
                "二级技能",
                "结构化首次会谈框架",
                "references",
                "children_manifest.json",
            )
            child_md = os.path.join(
                tmpdir,
                "心理咨询",
                "Family技能",
                "认知行为疗法",
                "微技能",
                "苏格拉底式提问",
                "SKILL.md",
            )
            self.assertTrue(os.path.isfile(parent_md))
            self.assertTrue(os.path.isfile(child_manifest))
            self.assertTrue(os.path.isfile(child_md))

            with open(parent_md, "r", encoding="utf-8") as f:
                parent_text = f.read()
            self.assertIn("## 子技能目录", parent_text)
            self.assertIn("## 选用规则（微技能目录）", parent_text)
            self.assertIn("苏格拉底式提问", parent_text)

            with open(child_manifest, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload.get("parent_skill_id"), "cand-parent")
            self.assertEqual(payload["children"][0]["name"], "苏格拉底式提问")

    def test_register_versions_persists_child_links_on_existing_parent_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            parent_doc = self._document(doc_id="doc-parent", title="Parent Skill")
            parent_support = self._support(
                support_id="sup-parent",
                doc_id=parent_doc.doc_id,
                excerpt="Run a structured first-session CBT framework with agenda setting and case focus.",
            )
            parent_skill = self._skill(
                skill_id="cand-parent",
                name="结构化首次会谈框架",
                asset_type="session_skill",
                granularity="session",
                asset_node_id="session_framework",
                asset_level=2,
                visible_role="parent",
                workflow_steps=["建立议程。", "明确目标。", "聚焦自动想法。", "总结安排。"],
                support_ids=[parent_support.support_id],
            )

            self._register(
                registry=registry,
                documents=[parent_doc],
                supports=[parent_support],
                skills=[parent_skill],
                metadata={
                    "family_name": "认知行为疗法",
                    "profile_id": "test_therapy_v2",
                    "taxonomy_axis": "疗法",
                    "domain_root_name": "心理咨询",
                },
            )

            child_doc = self._document(doc_id="doc-child", title="Child Skill")
            child_support = self._support(
                support_id="sup-child",
                doc_id=child_doc.doc_id,
                excerpt="Ask one Socratic question to challenge the client's automatic thought.",
            )
            child_skill = self._skill(
                skill_id="cand-child",
                name="苏格拉底式提问",
                asset_type="micro_skill",
                granularity="micro",
                asset_node_id="micro_intervention",
                asset_level=3,
                visible_role="leaf",
                workflow_steps=["选定自动想法。", "提出证据问题。", "追问替代解释。", "总结结论。"],
                support_ids=[child_support.support_id],
            )

            result = self._register(
                registry=registry,
                documents=[child_doc],
                supports=[child_support],
                skills=[child_skill],
                metadata={
                    "family_name": "认知行为疗法",
                    "profile_id": "test_therapy_v2",
                    "taxonomy_axis": "疗法",
                    "domain_root_name": "心理咨询",
                },
            )

            linked_child = next(skill for skill in result.skill_specs if skill.skill_id == "cand-child")
            self.assertEqual(linked_child.parent_skill_id, "cand-parent")
            persisted_parent = registry.get_skill("cand-parent")
            self.assertIsNotNone(persisted_parent)
            self.assertIn("cand-child", list(getattr(persisted_parent, "child_skill_ids", []) or []))

    def test_store_sync_keeps_cross_asset_type_document_skills_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = AutoSkill(
                AutoSkillConfig(
                    llm={"provider": "mock"},
                    embeddings={"provider": "hashing", "dims": 64},
                    store={"provider": "local", "path": tmpdir},
                    maintenance_strategy="heuristic",
                )
            )
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="Asset Layer")
            session_support = self._support(
                support_id="sup-session",
                doc_id=document.doc_id,
                excerpt="Run a full CBT reframing session scaffold.",
            )
            micro_support = self._support(
                support_id="sup-micro",
                doc_id=document.doc_id,
                excerpt="Ask one Socratic question to challenge a belief.",
            )
            session_skill = self._skill(
                skill_id="cand-session",
                name="认知重评",
                asset_type="session_skill",
                granularity="session",
                objective="agenda-based session flow for cognitive reframing",
                workflow_steps=["建立议程。", "识别自动想法。", "进行重评。", "总结与作业。"],
                support_ids=[session_support.support_id],
            )
            micro_skill = self._skill(
                skill_id="cand-micro",
                name="认知重评",
                asset_type="micro_skill",
                granularity="micro",
                workflow_steps=["提出一个苏格拉底式提问。"],
                support_ids=[micro_support.support_id],
            )

            result = register_versions(
                registry=registry,
                documents=[document],
                support_records=[session_support, micro_support],
                skill_specs=[session_skill, micro_skill],
                sdk=sdk,
                llm=self._llm(),
                user_id="u1",
                metadata={
                    "channel": "offline_extract_from_doc",
                    "family_name": "认知行为疗法",
                    "profile_id": "psychology::认知行为疗法",
                },
                dry_run=False,
                target_state=VersionState.ACTIVE,
            )

            stored = sorted(sdk.store.list(user_id="u1"), key=lambda item: item.id)
            self.assertEqual(2, len(stored))
            self.assertEqual(2, len(result.upserted_store_skills))
            self.assertEqual(
                {"session_skill", "micro_skill"},
                {str(skill.metadata.get("_autoskill_asset_type") or "") for skill in stored},
            )
            self.assertEqual(
                {"session", "micro"},
                {str(skill.metadata.get("_autoskill_granularity") or "") for skill in stored},
            )
            self.assertEqual({"cand-session", "cand-micro"}, {skill.id for skill in stored})

    def test_store_sync_does_not_overwrite_same_content_across_different_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = AutoSkill(
                AutoSkillConfig(
                    llm={"provider": "mock"},
                    embeddings={"provider": "hashing", "dims": 64},
                    store={"provider": "local", "path": tmpdir},
                    maintenance_strategy="heuristic",
                )
            )
            registry = DocumentRegistry(root_dir=os.path.join(tmpdir, ".runtime", "document_registry"))
            document = self._document(doc_id="doc-1", title="Family Scoped Skill")
            support_cbt = self._support(
                support_id="sup-cbt",
                doc_id=document.doc_id,
                excerpt="Use agenda-based CBT intake scaffolding.",
            )
            support_pd = self._support(
                support_id="sup-pd",
                doc_id=document.doc_id,
                excerpt="Use psychodynamic intake framing and alliance exploration.",
            )
            cbt_skill = self._skill(
                skill_id="cbt-intake-session",
                name="首次咨询结构化摄入会谈流程",
                asset_type="session_skill",
                granularity="session",
                asset_node_id="session_framework",
                objective="Run a structured first-session intake.",
                workflow_steps=["建立议程。", "明确问题。", "风险检查。", "总结安排。"],
                support_ids=[support_cbt.support_id],
            )
            cbt_skill.metadata.update(
                {
                    "taxonomy_id": "psychology",
                    "profile_id": "psychology::认知行为疗法",
                    "family_id": "cbt",
                    "family_name": "认知行为疗法",
                }
            )
            pd_skill = self._skill(
                skill_id="psychodynamic-intake-session",
                name="首次咨询结构化摄入会谈流程",
                asset_type="session_skill",
                granularity="session",
                asset_node_id="session_framework",
                objective="Run a structured first-session intake.",
                workflow_steps=["建立关系。", "探索来访动机。", "澄清冲突。", "总结安排。"],
                support_ids=[support_pd.support_id],
            )
            pd_skill.metadata.update(
                {
                    "taxonomy_id": "psychology",
                    "profile_id": "psychology::Psychodynamic（心理动力学）",
                    "family_id": "psychodynamic",
                    "family_name": "Psychodynamic（心理动力学）",
                }
            )

            register_versions(
                registry=registry,
                documents=[document],
                support_records=[support_cbt],
                skill_specs=[cbt_skill],
                sdk=sdk,
                llm=self._llm(),
                user_id="docskill",
                metadata={
                    "channel": "offline_extract_from_doc",
                    "family_name": "认知行为疗法",
                    "profile_id": "psychology::认知行为疗法",
                    "taxonomy_id": "psychology",
                },
                dry_run=False,
                target_state=VersionState.ACTIVE,
            )
            register_versions(
                registry=registry,
                documents=[document],
                support_records=[support_pd],
                skill_specs=[pd_skill],
                sdk=sdk,
                llm=self._llm(),
                user_id="docskill",
                metadata={
                    "channel": "offline_extract_from_doc",
                    "family_name": "Psychodynamic（心理动力学）",
                    "profile_id": "psychology::Psychodynamic（心理动力学）",
                    "taxonomy_id": "psychology",
                },
                dry_run=False,
                target_state=VersionState.ACTIVE,
            )

            stored = sorted(sdk.store.list(user_id="docskill"), key=lambda item: item.id)
            self.assertEqual(2, len(stored))
            self.assertEqual(
                {"认知行为疗法", "Psychodynamic（心理动力学）"},
                {str(skill.metadata.get("family_name") or "") for skill in stored},
            )
            self.assertEqual(2, len({skill.id for skill in stored}))


if __name__ == "__main__":
    unittest.main()
