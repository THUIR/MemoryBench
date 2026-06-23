"""
Staged offline document pipeline orchestration.

The pipeline is organized as explicit stages so callers can rerun or override
any stage independently:
- ingest_document
- extract_skills
- compile_skills
- register_versions
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from autoskill import AutoSkill

from .core.common import StageLogger, compact_metadata, emit_stage_log, emit_stage_progress
from .core.config import (
    DEFAULT_DOC_SKILL_USER_ID,
    DEFAULT_EXTRACT_STRATEGY,
    DEFAULT_LLM_RATE_LIMIT_REQUESTS,
    DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
    DEFAULT_MAX_CANDIDATES_PER_UNIT,
    DEFAULT_MAX_SECTION_CHARS,
    DEFAULT_RETRIEVAL_SCORE_THRESHOLD,
    DEFAULT_SECTION_OUTLINE_MODE,
    default_store_path,
)
from .core.llm_utils import llm_complete_json, maybe_json_dict
from .core.provider_config import allow_mock_provider, ensure_runtime_llm_provider
from .stages.compiler import (
    SkillCompilationResult,
    SkillCompiler,
    _group_key_for_draft,
    build_skill_compiler,
    compile_skills,
)
from .stages.extractor import (
    LLMDocumentSkillExtractor,
    DocumentSkillExtractor,
    SkillExtractionResult,
    build_document_skill_extractor,
    extract_skills,
)
from .ingest import (
    DocumentIngestResult,
    DocumentIngestor,
    HeuristicDocumentIngestor,
    ingest_document,
)
from .models import DocumentRecord, SkillDraft, SkillSpec, SupportRecord, VersionState
from .models import StrictWindow
from .family_resolver import DocumentFamilyResolver, build_document_family_resolver
from .store.intermediate import (
    IntermediateRunWriter,
    build_resume_key,
    find_intermediate_run_by_resume_key,
    new_intermediate_run_id,
)
from .store.registry import DocumentRegistry, build_registry_from_store_config
from .store.versioning import VersionRegistrationResult, register_versions
from .taxonomy import SkillTaxonomy, load_skill_taxonomy


@dataclass
class DocumentBuildResult:
    """Top-level result of a full offline document build run."""

    ingest: DocumentIngestResult
    extracted: SkillExtractionResult
    compiled: SkillCompilationResult
    registration: VersionRegistrationResult
    dry_run: bool = False
    intermediate: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Returns a compact build summary suitable for CLI/API output."""

        return {
            "dry_run": bool(self.dry_run),
            "documents": len(self.ingest.documents),
            "skipped_documents": len(self.ingest.skipped_documents),
            "windows": len(self.ingest.windows),
            "support_records": len(self.compiled.support_records),
            "skill_drafts": len(self.extracted.skill_drafts),
            "skill_specs": len(self.compiled.skill_specs),
            "lifecycles": len(self.registration.lifecycles),
            "change_logs": len(self.registration.change_logs),
            "version_history_entries": len(self.registration.version_history),
            "provenance_links": len(self.registration.provenance_links),
            "store_upserts": len(self.registration.upserted_store_skills),
            "staging_runs": len(self.registration.staging_runs),
            "visible_families": len(list((self.registration.visible_tree or {}).get("affected_families") or [])),
            "visible_children": len(list((self.registration.visible_tree or {}).get("child_paths") or [])),
            "intermediate": dict(self.intermediate or {}),
            "errors": (
                list(self.ingest.errors)
                + list(self.extracted.errors)
                + list(self.compiled.errors)
                + list(self.registration.errors)
            ),
        }


class DocumentBuildPipeline:
    """Composable staged pipeline for offline document compilation."""

    def __init__(
        self,
        *,
        registry: DocumentRegistry,
        sdk: Optional[AutoSkill] = None,
        document_ingestor: Optional[DocumentIngestor] = None,
        document_skill_extractor: Optional[DocumentSkillExtractor] = None,
        skill_compiler: Optional[SkillCompiler] = None,
        taxonomy: Optional[SkillTaxonomy] = None,
        family_resolver: Optional[DocumentFamilyResolver] = None,
        logger: StageLogger = None,
        retrieval_score_threshold: float = DEFAULT_RETRIEVAL_SCORE_THRESHOLD,
        llm_rate_limit_requests: int = DEFAULT_LLM_RATE_LIMIT_REQUESTS,
        llm_rate_limit_window_s: float = DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
    ) -> None:
        """Builds a pipeline with replaceable stage implementations."""

        self.registry = registry
        self.sdk = sdk
        self.retrieval_score_threshold = max(0.0, float(retrieval_score_threshold or DEFAULT_RETRIEVAL_SCORE_THRESHOLD))
        self.llm_rate_limit_requests = max(0, int(llm_rate_limit_requests or 0))
        self.llm_rate_limit_window_s = max(0.0, float(llm_rate_limit_window_s or 0.0))
        self.logger = logger
        self.taxonomy = taxonomy or load_skill_taxonomy()
        self.document_ingestor = document_ingestor or HeuristicDocumentIngestor(
            llm_config=dict(getattr(getattr(self.sdk, "config", None), "llm", {}) or {}),
            llm_rate_limit_requests=self.llm_rate_limit_requests,
            llm_rate_limit_window_s=self.llm_rate_limit_window_s,
        )
        self.document_skill_extractor = document_skill_extractor or build_document_skill_extractor(
            "llm",
            llm_config=dict(getattr(getattr(self.sdk, "config", None), "llm", {}) or {}),
            llm_rate_limit_requests=self.llm_rate_limit_requests,
            llm_rate_limit_window_s=self.llm_rate_limit_window_s,
        )
        self.skill_compiler = skill_compiler or build_skill_compiler(
            "llm",
            llm_config=dict(getattr(getattr(self.sdk, "config", None), "llm", {}) or {}),
            llm_rate_limit_requests=self.llm_rate_limit_requests,
            llm_rate_limit_window_s=self.llm_rate_limit_window_s,
        )
        self.family_resolver = family_resolver or build_document_family_resolver(
            taxonomy=self.taxonomy,
            llm_config=dict(getattr(getattr(self.sdk, "config", None), "llm", {}) or {}),
            llm_rate_limit_requests=self.llm_rate_limit_requests,
            llm_rate_limit_window_s=self.llm_rate_limit_window_s,
        )

    def _ensure_runtime_llm(self, *, context: str) -> None:
        """Prevents user-facing extraction paths from silently using mock."""

        llm_cfg = dict(getattr(getattr(self.sdk, "config", None), "llm", {}) or {})
        if not llm_cfg:
            return
        ensure_runtime_llm_provider(
            str(llm_cfg.get("provider") or ""),
            context=context,
            allow_mock=allow_mock_provider(llm_cfg),
        )

    def _run_taxonomy(
        self,
        *,
        documents: Sequence[DocumentRecord],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SkillTaxonomy:
        """Loads the most specific taxonomy for one build run."""

        md = dict(metadata or {})
        requested_domain_type = (
            str(md.get("domain_type") or "").strip()
            or str(md.get("domain") or "").strip()
            or next((str(doc.domain or "").strip() for doc in list(documents or []) if str(doc.domain or "").strip()), "")
        )
        requested_taxonomy_path = str(md.get("skill_taxonomy_path") or md.get("skill_taxonomy") or "").strip()
        if not requested_domain_type and not requested_taxonomy_path:
            return self.taxonomy
        current_path = str(getattr(self.taxonomy, "taxonomy_id", "") or "").strip()
        if not requested_taxonomy_path and requested_domain_type == str(self.taxonomy.domain_type or "").strip():
            return self.taxonomy
        try:
            return load_skill_taxonomy(
                domain_type=requested_domain_type,
                taxonomy_path=requested_taxonomy_path,
            )
        except Exception:
            return self.taxonomy

    def _family_resolver_for_taxonomy(self, taxonomy: SkillTaxonomy) -> DocumentFamilyResolver:
        """Builds one compatible family resolver when the run taxonomy changes."""

        if str(taxonomy.taxonomy_id or "").strip() == str(self.taxonomy.taxonomy_id or "").strip():
            return self.family_resolver
        return build_document_family_resolver(
            taxonomy=taxonomy,
            llm=getattr(self.family_resolver, "llm", None),
            llm_rate_limit_requests=self.llm_rate_limit_requests,
            llm_rate_limit_window_s=self.llm_rate_limit_window_s,
        )

    def _extractor_for_taxonomy(self, taxonomy: SkillTaxonomy) -> DocumentSkillExtractor:
        """Builds one compatible extractor when the run taxonomy differs."""

        current = self.document_skill_extractor
        current_taxonomy_id = str(getattr(getattr(current, "taxonomy", None), "taxonomy_id", "") or "").strip()
        if current_taxonomy_id == str(taxonomy.taxonomy_id or "").strip():
            return current
        if isinstance(current, LLMDocumentSkillExtractor):
            return build_document_skill_extractor(
                "llm",
                llm=getattr(current, "_llm", None),
                max_section_chars=int(getattr(current, "max_section_chars", DEFAULT_MAX_SECTION_CHARS) or DEFAULT_MAX_SECTION_CHARS),
                overlap_chars=int(getattr(current, "overlap_chars", 0) or 0),
                max_candidates_per_unit=int(
                    getattr(current, "max_candidates_per_unit", DEFAULT_MAX_CANDIDATES_PER_UNIT)
                    or DEFAULT_MAX_CANDIDATES_PER_UNIT
                ),
                max_units_per_document=int(getattr(current, "max_units_per_document", 0) or 0),
                extract_workers=int(getattr(current, "extract_workers", 1) or 1),
                extract_retries=int(getattr(current, "extract_retries", 3) or 0),
                extract_retry_backoff_s=float(getattr(current, "extract_retry_backoff_s", 1.0) or 0.0),
                llm_rate_limit_requests=int(getattr(current, "llm_rate_limit_requests", self.llm_rate_limit_requests) or 0),
                llm_rate_limit_window_s=float(
                    getattr(current, "llm_rate_limit_window_s", self.llm_rate_limit_window_s) or 0.0
                ),
                taxonomy=taxonomy,
            )
        return current

    def resolve_run_metadata(
        self,
        *,
        documents: Sequence[DocumentRecord],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolves family/domain display metadata after ingest."""

        md = dict(metadata or {})
        effective_taxonomy = self._run_taxonomy(documents=documents, metadata=md)
        resolved_family = str(md.get("family_name") or "").strip()
        if not resolved_family and self.family_resolver is not None:
            resolver = self._family_resolver_for_taxonomy(effective_taxonomy)
            resolution = resolver.resolve(
                documents=list(documents or []),
                metadata=md,
            )
            if len(list(documents or [])) > 1:
                per_doc_matches = []
                for document in list(documents or []):
                    doc_resolution = resolver.resolve(
                        documents=[document],
                        metadata=md,
                        allow_llm=False,
                    )
                    family_name = str(doc_resolution.family_name or "").strip()
                    if family_name and family_name != str(effective_taxonomy.default_family_name or "").strip():
                        per_doc_matches.append(family_name)
                detected_families = sorted({name for name in per_doc_matches if name})
                if len(detected_families) > 1:
                    default_candidate = effective_taxonomy.resolve_family_candidate(
                        requested=str(effective_taxonomy.default_family_name or "").strip()
                    )
                    resolution.family_id = ""
                    resolution.family_name = str(effective_taxonomy.default_family_name or "").strip()
                    if default_candidate is not None:
                        resolution.family_id = str(default_candidate.get("id") or "").strip()
                        resolution.family_name = str(
                            default_candidate.get("visible_name") or default_candidate.get("name") or resolution.family_name
                        ).strip()
                    resolution.confidence = min(float(resolution.confidence or 0.0), 0.3)
                    resolution.source = "mixed_rule"
                    resolution.reason = (
                        "documents matched multiple configured families; "
                        "fallback to taxonomy default family for this batch"
                    )
                    md["family_candidates_detected"] = detected_families
            if resolution.family_name:
                md["family_name"] = resolution.family_name
            if resolution.family_id:
                md["family_id"] = resolution.family_id
            md["family_confidence"] = float(resolution.confidence or 0.0)
            md["family_source"] = str(resolution.source or "").strip()
            if str(resolution.reason or "").strip():
                md["family_reason"] = str(resolution.reason or "").strip()
        elif resolved_family:
            candidate = effective_taxonomy.resolve_family_candidate(requested=resolved_family, metadata=md)
            if candidate is not None:
                md["family_name"] = str(candidate.get("visible_name") or candidate.get("name") or "").strip()
                if str(candidate.get("id") or "").strip():
                    md["family_id"] = str(candidate.get("id") or "").strip()
        if not str(md.get("taxonomy_axis") or "").strip():
            axis = effective_taxonomy.resolve_axis_label()
            if axis:
                md["taxonomy_axis"] = axis
        if not str(md.get("domain_root_name") or "").strip():
            md["domain_root_name"] = effective_taxonomy.domain_root_name()
        if not str(md.get("domain_root_id") or "").strip():
            md["domain_root_id"] = effective_taxonomy.domain_root_id()
        if not str(md.get("family_bucket_label") or "").strip():
            md["family_bucket_label"] = effective_taxonomy.family_bucket_label()
        if not isinstance(md.get("visible_levels"), dict):
            md["visible_levels"] = dict(effective_taxonomy.to_dict().get("visible_levels") or {})
        if not str(md.get("profile_id") or "").strip():
            md["profile_id"] = effective_taxonomy.derive_profile_id(
                requested="",
                family_name=str(md.get("family_name") or "").strip(),
            )
        md["taxonomy_id"] = str(md.get("taxonomy_id") or effective_taxonomy.taxonomy_id).strip()
        md["domain_type"] = str(md.get("domain_type") or effective_taxonomy.domain_type).strip()
        return md

    def ingest_document(
        self,
        *,
        data: Optional[Any] = None,
        file_path: str = "",
        title: str = "",
        source_type: str = "document",
        domain: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        continue_on_error: bool = True,
        dry_run: bool = False,
        max_documents: int = 0,
        extract_strategy: str = DEFAULT_EXTRACT_STRATEGY,
    ) -> DocumentIngestResult:
        """Runs the ingestion stage only."""

        return ingest_document(
            data=data,
            file_path=file_path,
            title=title,
            source_type=source_type,
            domain=domain,
            metadata=metadata,
            registry=self.registry,
            ingestor=self.document_ingestor,
            continue_on_error=continue_on_error,
            dry_run=dry_run,
            max_documents=max_documents,
            extract_strategy=extract_strategy,
            logger=self.logger,
        )

    def extract_skills(
        self,
        *,
        documents: List[DocumentRecord],
        windows: Optional[List[StrictWindow]] = None,
        taxonomy: Optional[SkillTaxonomy] = None,
        extract_workers: Optional[int] = None,
        progress_callback=None,
        stage_progress_callback=None,
        accumulate_result: bool = True,
    ) -> SkillExtractionResult:
        """Runs the direct skill extraction stage only."""

        self._ensure_runtime_llm(context="AutoSkill4Doc extract_skills")
        extractor = self._extractor_for_taxonomy(taxonomy or self.taxonomy)
        if (
            extract_workers is not None
            and isinstance(extractor, LLMDocumentSkillExtractor)
            and int(getattr(extractor, "extract_workers", 1) or 1) != max(1, int(extract_workers or 1))
        ):
            extractor = build_document_skill_extractor(
                "llm",
                llm=getattr(extractor, "_llm", None),
                llm_config=dict(getattr(extractor, "_llm_config", {}) or {}),
                max_section_chars=int(getattr(extractor, "max_section_chars", DEFAULT_MAX_SECTION_CHARS) or DEFAULT_MAX_SECTION_CHARS),
                overlap_chars=int(getattr(extractor, "overlap_chars", 0) or 0),
                max_candidates_per_unit=int(
                    getattr(extractor, "max_candidates_per_unit", DEFAULT_MAX_CANDIDATES_PER_UNIT)
                    or DEFAULT_MAX_CANDIDATES_PER_UNIT
                ),
                max_units_per_document=int(getattr(extractor, "max_units_per_document", 0) or 0),
                extract_workers=max(1, int(extract_workers or 1)),
                extract_retries=int(getattr(extractor, "extract_retries", 3) or 0),
                extract_retry_backoff_s=float(getattr(extractor, "extract_retry_backoff_s", 1.0) or 0.0),
                llm_rate_limit_requests=int(getattr(extractor, "llm_rate_limit_requests", self.llm_rate_limit_requests) or 0),
                llm_rate_limit_window_s=float(
                    getattr(extractor, "llm_rate_limit_window_s", self.llm_rate_limit_window_s) or 0.0
                ),
                taxonomy=getattr(extractor, "taxonomy", None),
            )
        return extract_skills(
            documents=list(documents or []),
            windows=list(windows or []),
            extractor=extractor,
            logger=self.logger,
            progress_callback=progress_callback,
            stage_progress_callback=stage_progress_callback,
            accumulate_result=accumulate_result,
        )

    def compile_skills(
        self,
        *,
        skill_drafts: List[SkillDraft],
        support_records: List[SupportRecord],
        target_state: VersionState = VersionState.DRAFT,
        progress_callback=None,
    ) -> SkillCompilationResult:
        """Runs the skill compilation stage only."""

        self._ensure_runtime_llm(context="AutoSkill4Doc compile_skills")
        return compile_skills(
            skill_drafts=list(skill_drafts or []),
            support_records=list(support_records or []),
            compiler=self.skill_compiler,
            target_state=target_state,
            logger=self.logger,
            progress_callback=progress_callback,
        )

    def register_versions(
        self,
        *,
        documents: List[DocumentRecord],
        support_records: List[SupportRecord],
        skill_specs: List[SkillSpec],
        user_id: str = DEFAULT_DOC_SKILL_USER_ID,
        metadata: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        target_state: VersionState = VersionState.ACTIVE,
        intermediate_writer: Optional[IntermediateRunWriter] = None,
        progress_callback=None,
    ) -> VersionRegistrationResult:
        """Runs the registry/version registration stage only."""

        self._ensure_runtime_llm(context="AutoSkill4Doc register_versions")
        return register_versions(
            registry=self.registry,
            documents=list(documents or []),
            support_records=list(support_records or []),
            skill_specs=list(skill_specs or []),
            sdk=self.sdk,
            user_id=str(user_id or "").strip() or DEFAULT_DOC_SKILL_USER_ID,
            metadata=metadata,
            dry_run=dry_run,
            target_state=target_state,
            logger=self.logger,
            intermediate_writer=intermediate_writer,
            progress_callback=progress_callback,
            retrieval_score_threshold=self.retrieval_score_threshold,
            llm_rate_limit_requests=self.llm_rate_limit_requests,
            llm_rate_limit_window_s=self.llm_rate_limit_window_s,
        )

    def build(
        self,
        *,
        user_id: str = DEFAULT_DOC_SKILL_USER_ID,
        data: Optional[Any] = None,
        file_path: str = "",
        title: str = "",
        source_type: str = "document",
        domain: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        continue_on_error: bool = True,
        dry_run: bool = False,
        target_state: Optional[VersionState] = None,
        max_documents: int = 0,
        extract_strategy: str = DEFAULT_EXTRACT_STRATEGY,
        extract_progress_callback=None,
        stage_progress_callback=None,
    ) -> DocumentBuildResult:
        """Runs the full offline document build pipeline."""

        self._ensure_runtime_llm(context="AutoSkill4Doc build")
        effective_state = target_state or (VersionState.DRAFT if dry_run else VersionState.ACTIVE)
        intermediate_writer = None
        intermediate_summary: Dict[str, Any] = {}
        resumed_run = False
        if not dry_run:
            store_root = ""
            if self.sdk is not None:
                store_root = str(getattr(getattr(self.sdk, "config", None), "store", {}).get("path") or "").strip()
            if not store_root:
                registry_root = os.path.abspath(os.path.expanduser(str(self.registry.root_dir or "").strip()))
                runtime_dir = os.path.dirname(registry_root)
                if os.path.basename(runtime_dir) == ".runtime":
                    store_root = os.path.dirname(runtime_dir)
            if store_root:
                llm_cfg = dict(getattr(getattr(self.sdk, "config", None), "llm", {}) or {})
                emb_cfg = dict(getattr(getattr(self.sdk, "config", None), "embeddings", {}) or {})
                if file_path:
                    input_signature = self._file_input_signature(file_path=file_path)
                else:
                    input_signature = self._data_input_signature(data)
                resume_payload = {
                    "input_signature": input_signature,
                    "title": str(title or "").strip(),
                    "source_type": str(source_type or "").strip(),
                    "domain": str(domain or "").strip(),
                    "metadata": compact_metadata(dict(metadata or {})),
                    "max_documents": int(max_documents or 0),
                    "extract_strategy": str(extract_strategy or "").strip(),
                    "llm_provider": str(llm_cfg.get("provider") or "").strip(),
                    "llm_model": str(llm_cfg.get("model") or "").strip(),
                    "embeddings_provider": str(emb_cfg.get("provider") or "").strip(),
                    "embeddings_model": str(emb_cfg.get("model") or "").strip(),
                }
                resume_key = build_resume_key(resume_payload)
                resume_metadata = dict(metadata or {})
                resume_metadata["resume_key"] = resume_key
                resumable = find_intermediate_run_by_resume_key(base_store_root=store_root, resume_key=resume_key)
                intermediate_writer = IntermediateRunWriter(
                    base_store_root=store_root,
                    run_id=str((resumable or {}).get("run_id") or new_intermediate_run_id()),
                    metadata=resume_metadata,
                    resume_existing=bool(resumable),
                )
                if resumable:
                    resumed_run = True
                    intermediate_writer.update_metadata({"resumed_from_run_id": str((resumable or {}).get("run_id") or "").strip()})
                intermediate_summary = intermediate_writer.summary().to_dict()
        base_metadata = dict(metadata or {})
        if intermediate_writer is not None:
            base_metadata["resume_key"] = str((intermediate_writer._state.get("metadata") or {}).get("resume_key") or "").strip()
        if intermediate_writer is not None and intermediate_writer.has_completed_stage("ingest"):
            ingest_result = intermediate_writer.load_ingest()
        else:
            ingest_result = self.ingest_document(
                data=data,
                file_path=file_path,
                title=title,
                source_type=source_type,
                domain=domain,
                metadata=base_metadata,
                continue_on_error=continue_on_error,
                dry_run=dry_run,
                max_documents=max_documents,
                extract_strategy=extract_strategy,
            )
            if intermediate_writer is not None:
                intermediate_writer.write_ingest(ingest_result)
                intermediate_summary = intermediate_writer.summary().to_dict()
        resolved_metadata = self.resolve_run_metadata(documents=ingest_result.documents, metadata=base_metadata)
        resolved_metadata = compact_metadata(resolved_metadata)
        if intermediate_writer is not None:
            intermediate_writer.update_metadata(resolved_metadata)
            intermediate_summary = intermediate_writer.summary().to_dict()
        effective_taxonomy = self._run_taxonomy(documents=ingest_result.documents, metadata=resolved_metadata)
        for document in list(ingest_result.documents or []):
            document.metadata.update(resolved_metadata)
        for document in list(ingest_result.skipped_documents or []):
            document.metadata.update(resolved_metadata)
        progress_owner = extract_progress_callback
        if (
            progress_owner is not None
            and not hasattr(progress_owner, "set_total_documents")
            and hasattr(progress_owner, "__self__")
        ):
            progress_owner = getattr(progress_owner, "__self__", progress_owner)
        if progress_owner is not None and hasattr(progress_owner, "set_total_documents"):
            completed_docs = 0
            completed_windows = 0
            if intermediate_writer is not None:
                completed_docs = len(intermediate_writer.processed_extract_doc_ids())
                completed_windows = sum(
                    len(intermediate_writer.processed_extract_window_ids(str(doc.doc_id or "").strip()))
                    for doc in list(ingest_result.documents or [])
                )
            try:
                progress_owner.set_total_documents(
                    len(list(ingest_result.documents or [])),
                    completed=completed_docs,
                    total_windows=len(list(ingest_result.windows or [])),
                    completed_windows=(completed_windows if intermediate_writer is not None else 0),
                )
            except Exception:
                pass
        try:
            if intermediate_writer is not None and intermediate_writer.has_completed_stage("extract"):
                extracted_result = intermediate_writer.load_extract_summary()
            elif intermediate_writer is not None:
                extracted_result = self._resume_or_extract(
                    intermediate_writer=intermediate_writer,
                    ingest_result=ingest_result,
                    taxonomy=effective_taxonomy,
                    extract_progress_callback=extract_progress_callback,
                    stage_progress_callback=stage_progress_callback,
                )
                intermediate_summary = intermediate_writer.summary().to_dict()
            else:
                extracted_result = self.extract_skills(
                    documents=ingest_result.documents,
                    windows=ingest_result.windows,
                    taxonomy=effective_taxonomy,
                    extract_workers=int(getattr(self.document_skill_extractor, "extract_workers", 1) or 1),
                    accumulate_result=True,
                    progress_callback=extract_progress_callback,
                    stage_progress_callback=stage_progress_callback,
                )
            if intermediate_writer is not None and intermediate_writer.has_completed_stage("compile"):
                compiled_result = intermediate_writer.load_compile_summary()
            else:
                if intermediate_writer is not None:
                    compiled_result = self._resume_or_stream_compile(
                        intermediate_writer=intermediate_writer,
                        ingest_result=ingest_result,
                        target_state=effective_state,
                        stage_progress_callback=stage_progress_callback,
                    )
                else:
                    compiled_result = self.compile_skills(
                        skill_drafts=extracted_result.skill_drafts,
                        support_records=extracted_result.support_records,
                        target_state=effective_state,
                        progress_callback=stage_progress_callback,
                    )
            if intermediate_writer is not None:
                extracted_result = SkillExtractionResult(
                    documents=list(ingest_result.documents or []),
                    windows=list(ingest_result.windows or []),
                    errors=list(extracted_result.errors or []),
                    extractor_name=str(extracted_result.extractor_name or "llm"),
                )
                compiled_result = SkillCompilationResult(
                    errors=list(compiled_result.errors or []),
                    compiler_name=str(compiled_result.compiler_name or "llm"),
                )
            if intermediate_writer is not None and intermediate_writer.has_completed_stage("register"):
                registration_result = intermediate_writer.load_registration()
            else:
                if intermediate_writer is not None:
                    registration_result = self._resume_or_stream_register(
                        intermediate_writer=intermediate_writer,
                        ingest_result=ingest_result,
                        user_id=user_id,
                        metadata=resolved_metadata,
                        dry_run=dry_run,
                        target_state=effective_state,
                        stage_progress_callback=stage_progress_callback,
                    )
                else:
                    registration_result = self.register_versions(
                        documents=ingest_result.documents,
                        support_records=compiled_result.support_records,
                        skill_specs=compiled_result.skill_specs,
                        user_id=user_id,
                        metadata=resolved_metadata,
                        dry_run=dry_run,
                        target_state=effective_state,
                        progress_callback=stage_progress_callback,
                    )
            if intermediate_writer is not None:
                extracted_result = intermediate_writer.load_extract()
                compiled_result = intermediate_writer.load_compile()
                registration_result = intermediate_writer.load_registration()
                intermediate_summary = intermediate_writer.summary().to_dict()
            build_result = DocumentBuildResult(
                ingest=ingest_result,
                extracted=extracted_result,
                compiled=compiled_result,
                registration=registration_result,
                dry_run=bool(dry_run),
                intermediate=dict(intermediate_summary or {}),
            )
            if intermediate_writer is not None:
                completed_doc_ids = [
                    doc_id
                    for doc_id in intermediate_writer.successful_register_doc_ids()
                    if doc_id in {str(doc.doc_id or "").strip() for doc in list(ingest_result.documents or [])}
                ]
                unresolved_doc_ids = [
                    str(doc.doc_id or "").strip()
                    for doc in list(ingest_result.documents or [])
                    if str(doc.doc_id or "").strip() and str(doc.doc_id or "").strip() not in set(completed_doc_ids)
                ]
                unresolved_nodes: List[str] = []
                for payload in intermediate_writer.iter_extract_documents(
                    ordered_doc_ids=[str(doc.doc_id or "").strip() for doc in list(ingest_result.documents or [])]
                ):
                    doc_id = str(payload.get("doc_id") or "").strip()
                    if not doc_id or doc_id not in set(unresolved_doc_ids):
                        continue
                    for window_id in list(payload.get("unresolved_window_ids") or []):
                        if str(window_id or "").strip():
                            unresolved_nodes.append(self._extract_window_node_key(str(window_id or "").strip()))
                final_status = "completed"
                if unresolved_doc_ids:
                    final_status = "partial" if completed_doc_ids else "failed"
                intermediate_writer.record_run_outcome(
                    status=final_status,
                    completed_doc_ids=completed_doc_ids,
                    unresolved_doc_ids=unresolved_doc_ids,
                    unresolved_nodes=unresolved_nodes,
                )
                intermediate_summary = intermediate_writer.summary().to_dict()
                build_result.intermediate = dict(intermediate_summary or {})
                if resumed_run:
                    build_result.intermediate["resumed"] = True
                if final_status == "completed":
                    intermediate_writer.complete(summary=build_result.to_dict())
                elif final_status == "partial":
                    intermediate_writer.mark_partial(summary=build_result.to_dict())
                else:
                    intermediate_writer.fail(error="run finished with unresolved documents", summary=build_result.to_dict())
                intermediate_summary = intermediate_writer.summary().to_dict()
                build_result.intermediate = dict(intermediate_summary or {})
                if resumed_run:
                    build_result.intermediate["resumed"] = True
            return build_result
        except Exception as exc:
            if intermediate_writer is not None:
                intermediate_writer.fail(error=str(exc))
            raise

    @staticmethod
    def _data_input_signature(data: Optional[Any]) -> str:
        """Builds a stable content signature for in-memory input payloads."""

        if data is None:
            return ""
        if isinstance(data, bytes):
            raw = data
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _file_input_signature(*, file_path: str) -> Dict[str, Any]:
        """Builds a lightweight change signature for a file or directory input."""

        abs_path = os.path.abspath(os.path.expanduser(str(file_path or "").strip()))
        if not abs_path or not os.path.exists(abs_path):
            return {"path": abs_path, "exists": False}
        if os.path.isfile(abs_path):
            stat = os.stat(abs_path)
            return {"path": abs_path, "type": "file", "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
        items: List[Dict[str, Any]] = []
        for root, _, files in os.walk(abs_path):
            for name in sorted(files):
                path = os.path.join(root, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                items.append(
                    {
                        "relative_path": os.path.relpath(path, abs_path),
                        "size": int(stat.st_size),
                        "mtime_ns": int(stat.st_mtime_ns),
                    }
                )
        return {"path": abs_path, "type": "directory", "files": items}

    @staticmethod
    def _extract_window_node_key(window_id: str) -> str:
        return f"extract.window_plan({str(window_id or '').strip()})"

    @staticmethod
    def _extract_expand_node_key(window_id: str, slot: Any) -> str:
        try:
            slot_value = int(slot or 0)
        except Exception:
            slot_value = 0
        return f"extract.window_expand({str(window_id or '').strip()}, {slot_value})"

    @staticmethod
    def _extract_aggregate_node_key(doc_id: str) -> str:
        return f"extract.document_aggregate({str(doc_id or '').strip()})"

    @staticmethod
    def _extract_audit_node_key(doc_id: str) -> str:
        return f"extract.document_audit({str(doc_id or '').strip()})"

    @staticmethod
    def _compile_group_node_key(group_key: str) -> str:
        return f"compile.group({str(group_key or '').strip()})"

    @staticmethod
    def _register_skill_node_key(skill_id: str) -> str:
        return f"register.skill({str(skill_id or '').strip()})"

    @staticmethod
    def _dedupe_supports(records: Sequence[SupportRecord]) -> List[SupportRecord]:
        by_id: Dict[str, SupportRecord] = {}
        for record in list(records or []):
            by_id[str(record.support_id or "").strip()] = record
        return list(by_id.values())

    @staticmethod
    def _dedupe_drafts(records: Sequence[SkillDraft]) -> List[SkillDraft]:
        by_id: Dict[str, SkillDraft] = {}
        for record in list(records or []):
            by_id[str(record.draft_id or "").strip()] = record
        return list(by_id.values())

    @staticmethod
    def _windows_by_doc(windows: Sequence[StrictWindow]) -> Dict[str, List[StrictWindow]]:
        out: Dict[str, List[StrictWindow]] = {}
        for window in list(windows or []):
            doc_id = str(window.doc_id or "").strip()
            if not doc_id:
                continue
            out.setdefault(doc_id, []).append(window)
        return out

    def _unwrap_llm_extractor(self, extractor: Any) -> Optional[LLMDocumentSkillExtractor]:
        """Unwraps delegating test wrappers until the runtime LLM extractor is visible."""

        current = extractor
        seen = set()
        while current is not None and id(current) not in seen:
            if isinstance(current, LLMDocumentSkillExtractor):
                return current
            seen.add(id(current))
            current = getattr(current, "delegate", None)
        return None

    def _doc_extract_from_window_payloads(
        self,
        *,
        intermediate_writer: IntermediateRunWriter,
        doc_id: str,
        ordered_window_ids: Sequence[str],
    ) -> Dict[str, Any]:
        """Rebuilds one document's extract outputs from persisted window payloads."""

        support_records: List[SupportRecord] = []
        skill_drafts: List[SkillDraft] = []
        errors: List[Dict[str, Any]] = []
        payloads = intermediate_writer.iter_extract_windows(doc_id=doc_id, ordered_window_ids=ordered_window_ids)
        for payload in payloads:
            if isinstance(payload.get("error"), dict):
                errors.append(dict(payload.get("error") or {}))
            if bool(payload.get("failed")):
                continue
            for item in list(payload.get("supports") or []):
                if isinstance(item, dict):
                    support_records.append(SupportRecord.from_dict(item))
            for item in list(payload.get("skill_drafts") or []):
                if isinstance(item, dict):
                    skill_drafts.append(SkillDraft.from_dict(item))
        return {
            "supports": self._dedupe_supports(support_records),
            "drafts": self._dedupe_drafts(skill_drafts),
            "errors": errors,
            "window_payloads": payloads,
        }

    def _audit_document_extract(
        self,
        *,
        record: DocumentRecord,
        windows: Sequence[StrictWindow],
        doc_supports: Sequence[SupportRecord],
        doc_drafts: Sequence[SkillDraft],
        taxonomy: SkillTaxonomy,
        intermediate_writer: IntermediateRunWriter,
    ) -> Dict[str, Any]:
        """Runs one conservative document completeness audit on top of successful window extracts."""

        runtime_extractor = self._unwrap_llm_extractor(self._extractor_for_taxonomy(taxonomy))
        llm = getattr(runtime_extractor, "_llm", None)
        if llm is None:
            return {"status": "no_gap", "missing_window_ids": [], "reason": "audit llm unavailable"}
        ordered_window_ids = [str(window.window_id or "").strip() for window in list(windows or []) if str(window.window_id or "").strip()]
        doc_extract = self._doc_extract_from_window_payloads(
            intermediate_writer=intermediate_writer,
            doc_id=str(record.doc_id or "").strip(),
            ordered_window_ids=ordered_window_ids,
        )
        payload = {
            "audit_request": True,
            "document": {
                "doc_id": str(record.doc_id or "").strip(),
                "title": str(record.title or "").strip(),
                "domain": str(record.domain or "").strip(),
                "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
            },
            "window_summaries": [
                {
                    "window_id": str(window.window_id or "").strip(),
                    "section_heading": str(window.section_heading or "").strip(),
                    "strategy": str(window.strategy or "").strip(),
                    "draft_names": [
                        str(draft.name or "").strip()
                        for draft in list(doc_extract.get("drafts") or [])
                        if str((draft.metadata or {}).get("window_id") or "").strip() == str(window.window_id or "").strip()
                    ],
                    "support_count": len(
                        [
                            support
                            for support in list(doc_extract.get("supports") or [])
                            if str((support.metadata or {}).get("window_id") or "").strip() == str(window.window_id or "").strip()
                        ]
                    ),
                    "draft_count": len(
                        [
                            draft
                            for draft in list(doc_extract.get("drafts") or [])
                            if str((draft.metadata or {}).get("window_id") or "").strip() == str(window.window_id or "").strip()
                        ]
                    ),
                    "excerpt": str(window.text or "").strip()[:800],
                }
                for window in list(windows or [])
            ],
            "document_aggregate": {
                "skill_count": len(list(doc_drafts or [])),
                "skill_names": [str(draft.name or "").strip() for draft in list(doc_drafts or []) if str(draft.name or "").strip()],
                "support_count": len(list(doc_supports or [])),
            },
        }
        system = (
            "You are AutoSkill4Doc's offline document skill extractor.\n"
            "Task: audit whether a finished document extraction still missed reusable skills.\n"
            "Output ONLY strict JSON parseable by json.loads.\n"
            'Return {"status":"no_gap","missing_window_ids":[],"reason":"short reason"} when coverage is complete.\n'
            'Return {"status":"missing_candidates","missing_window_ids":["window-id"],"reason":"short reason"} only when one more targeted re-extract is clearly justified.\n'
            "Be conservative. Only point to windows explicitly present in window_summaries.\n"
        )
        repair_system = (
            "You are a JSON output fixer for AutoSkill4Doc document extract audit.\n"
            "Output ONLY strict JSON with status, missing_window_ids, and reason.\n"
        )
        try:
            parsed = llm_complete_json(
                llm=llm,
                system=system,
                payload=payload,
                repair_system=repair_system,
                repair_payload=f"DATA:\n{json.dumps(payload, ensure_ascii=False)}\n\nDRAFT:\n__DRAFT__",
            )
        except Exception as exc:
            return {"status": "no_gap", "missing_window_ids": [], "reason": f"audit skipped: {exc}"}
        obj = maybe_json_dict(parsed)
        allowed_window_ids = set(ordered_window_ids)
        missing_window_ids = [
            str(item or "").strip()
            for item in list(obj.get("missing_window_ids") or [])
            if str(item or "").strip() in allowed_window_ids
        ]
        status = str(obj.get("status") or "").strip().lower()
        if status not in {"no_gap", "missing_candidates"}:
            status = "missing_candidates" if missing_window_ids else "no_gap"
        if status == "no_gap":
            missing_window_ids = []
        if status == "missing_candidates" and not missing_window_ids:
            status = "no_gap"
        return {
            "status": status,
            "missing_window_ids": missing_window_ids,
            "reason": str(obj.get("reason") or "").strip(),
            "window_summaries": list(payload.get("window_summaries") or []),
        }

    def _resume_or_extract(
        self,
        *,
        intermediate_writer: IntermediateRunWriter,
        ingest_result: DocumentIngestResult,
        taxonomy: SkillTaxonomy,
        extract_progress_callback=None,
        stage_progress_callback=None,
    ) -> SkillExtractionResult:
        """Resumes extract at document/window granularity and blocks incomplete docs from downstream."""

        if intermediate_writer.has_completed_stage("extract"):
            return intermediate_writer.load_extract()

        persisted = intermediate_writer.load_extract()
        support_by_id = {support.support_id: support for support in list(persisted.support_records or [])}
        draft_by_id = {draft.draft_id: draft for draft in list(persisted.skill_drafts or [])}
        ordered_documents = list(ingest_result.documents or [])
        windows_by_doc = self._windows_by_doc(list(ingest_result.windows or []))
        visible_extractor = self._extractor_for_taxonomy(taxonomy)
        runtime_extractor: DocumentSkillExtractor = self._unwrap_llm_extractor(visible_extractor) or visible_extractor
        if runtime_extractor is not visible_extractor and callable(getattr(visible_extractor, "extract", None)):
            try:
                visible_extractor.extract(
                    documents=[],
                    windows=[],
                    logger=self.logger,
                    progress_callback=None,
                    stage_progress_callback=None,
                    accumulate_result=False,
                )
            except Exception:
                pass
        total_documents = len(ordered_documents)
        total_windows = len(list(ingest_result.windows or []))
        completed_window_count = sum(
            len(intermediate_writer.processed_extract_window_ids(str(doc.doc_id or "").strip()))
            for doc in ordered_documents
        )

        for index, record in enumerate(ordered_documents, start=1):
            doc_id = str(record.doc_id or "").strip()
            doc_payload = intermediate_writer.load_extract_document(doc_id)
            doc_windows = list(windows_by_doc.get(doc_id, []))
            expected_window_ids = [str(window.window_id or "").strip() for window in doc_windows if str(window.window_id or "").strip()]
            processed_window_ids = set(intermediate_writer.processed_extract_window_ids(doc_id))
            unresolved_window_ids = {
                str(item or "").strip()
                for item in list(doc_payload.get("unresolved_window_ids") or [])
                if str(item or "").strip()
            }
            windows_to_run = [
                window
                for window in doc_windows
                if str(window.window_id or "").strip() not in processed_window_ids
                or str(window.window_id or "").strip() in unresolved_window_ids
            ]
            reused_window_ids = [
                window_id
                for window_id in expected_window_ids
                if window_id in processed_window_ids and window_id not in {str(item.window_id or "").strip() for item in windows_to_run}
            ]
            if reused_window_ids:
                reused_nodes: List[str] = []
                for payload in intermediate_writer.iter_extract_windows(doc_id=doc_id, ordered_window_ids=reused_window_ids):
                    window_id = str(payload.get("window_id") or "").strip()
                    if not window_id or bool(payload.get("failed")):
                        continue
                    reused_nodes.append(self._extract_window_node_key(window_id))
                    for item in list(payload.get("skill_drafts") or []):
                        if not isinstance(item, dict):
                            continue
                        slot = int((item.get("metadata") or {}).get("candidate_slot") or 0)
                        if slot > 0:
                            reused_nodes.append(self._extract_expand_node_key(window_id, slot))
                if bool(doc_payload.get("complete")):
                    reused_nodes.append(self._extract_aggregate_node_key(doc_id))
                intermediate_writer.add_reused_nodes(reused_nodes)
            if not expected_window_ids:
                if bool(doc_payload.get("complete")):
                    continue
                emit_stage_progress(
                    stage_progress_callback,
                    {
                        "stage": "extract",
                        "kind": "document_start",
                        "document_index": index,
                        "total_documents": total_documents,
                        "doc_id": doc_id,
                        "title": str(record.title or "").strip(),
                        "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                        "total_windows": 0,
                    },
                )
                direct = extract_skills(
                    documents=[record],
                    windows=[],
                    extractor=runtime_extractor,
                    logger=self.logger,
                    accumulate_result=True,
                )
                if list(direct.errors or []):
                    error_payload = dict(list(direct.errors or [])[0] or {})
                    intermediate_writer.write_extract_error(
                        record=record,
                        error=error_payload,
                        total_documents=total_documents,
                        expected_window_ids=[],
                        processed_window_ids=[],
                        unresolved_window_ids=[],
                    )
                    emit_stage_progress(
                        stage_progress_callback,
                        {
                            "stage": "extract",
                            "kind": "document_failed",
                            "doc_id": doc_id,
                            "title": str(record.title or "").strip(),
                            "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                            "total_windows": 0,
                            "error": str(error_payload.get("error") or ""),
                            "retryable": bool(error_payload.get("retryable")),
                        },
                    )
                    continue
                for support in list(direct.support_records or []):
                    support_by_id[support.support_id] = support
                for draft in list(direct.skill_drafts or []):
                    draft_by_id[draft.draft_id] = draft
                intermediate_writer.write_extract_progress(
                    record=record,
                    supports=list(direct.support_records or []),
                    drafts=list(direct.skill_drafts or []),
                    total_documents=total_documents,
                    expected_window_ids=[],
                    processed_window_ids=[],
                    unresolved_window_ids=[],
                    complete=True,
                )
                if extract_progress_callback is not None:
                    extract_progress_callback(
                        record,
                        list(direct.support_records or []),
                        list(direct.skill_drafts or []),
                        SkillExtractionResult(
                            documents=list(ingest_result.documents or []),
                            windows=list(ingest_result.windows or []),
                            support_records=list(support_by_id.values()),
                            skill_drafts=list(draft_by_id.values()),
                            extractor_name=str(direct.extractor_name or "llm"),
                        ),
                    )
                emit_stage_progress(
                    stage_progress_callback,
                    {
                        "stage": "extract",
                        "kind": "document_done",
                        "doc_id": doc_id,
                        "title": str(record.title or "").strip(),
                        "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                        "total_windows": 0,
                        "supports": len(list(direct.support_records or [])),
                        "drafts": len(list(direct.skill_drafts or [])),
                        "total_support_records": len(support_by_id),
                        "total_skill_drafts": len(draft_by_id),
                        "errors": len(list(intermediate_writer.load_extract_summary().errors or [])),
                    },
                )
                continue
            if not windows_to_run and bool(doc_payload.get("complete")):
                continue

            emit_stage_progress(
                stage_progress_callback,
                {
                    "stage": "extract",
                    "kind": "document_start",
                    "document_index": index,
                    "total_documents": total_documents,
                    "doc_id": doc_id,
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "total_windows": len(expected_window_ids),
                },
            )

            failed_window_ids: List[str] = []
            first_failed_error: Dict[str, Any] = {}
            seen_processed_window_ids = set(processed_window_ids)
            for window_index, window in enumerate(windows_to_run):
                window_id = str(window.window_id or "").strip()
                already_counted = window_id in processed_window_ids
                result = extract_skills(
                    documents=[record],
                    windows=[window],
                    extractor=runtime_extractor,
                    logger=self.logger,
                    accumulate_result=True,
                )
                if list(result.errors or []):
                    error_payload = dict(list(result.errors or [])[0] or {})
                    error_payload.setdefault("window_id", window_id)
                    intermediate_writer.write_extract_window_error(
                        record=record,
                        window=window,
                        error=error_payload,
                    )
                    if not first_failed_error:
                        first_failed_error = dict(error_payload)
                    failed_window_ids.append(window_id)
                    failed_window_ids.extend(
                        [
                            str(item.window_id or "").strip()
                            for item in list(windows_to_run[window_index + 1 :])
                            if str(item.window_id or "").strip()
                        ]
                    )
                    break
                intermediate_writer.write_extract_window_progress(
                    record=record,
                    window=window,
                    supports=list(result.support_records or []),
                    drafts=list(result.skill_drafts or []),
                )
                for support in list(result.support_records or []):
                    support_by_id[support.support_id] = support
                for draft in list(result.skill_drafts or []):
                    draft_by_id[draft.draft_id] = draft
                seen_processed_window_ids.add(window_id)
                if not already_counted:
                    completed_window_count += 1
                emit_stage_progress(
                    stage_progress_callback,
                    {
                        "stage": "extract",
                        "kind": "window_progress",
                        "doc_id": doc_id,
                        "title": str(record.title or "").strip(),
                        "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                        "completed_windows": completed_window_count,
                        "total_windows": total_windows,
                        "total_support_records": len(support_by_id),
                        "total_skill_drafts": len(draft_by_id),
                        "window_id": window_id,
                        "section_heading": str(window.section_heading or "").strip(),
                    },
                )

            doc_extract = self._doc_extract_from_window_payloads(
                intermediate_writer=intermediate_writer,
                doc_id=doc_id,
                ordered_window_ids=expected_window_ids,
            )
            doc_supports = list(doc_extract.get("supports") or [])
            doc_drafts = list(doc_extract.get("drafts") or [])
            if failed_window_ids:
                failure_payload = {
                    "doc_id": doc_id,
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "error": str(first_failed_error.get("error") or "extract windows unresolved"),
                    "retryable": bool(first_failed_error.get("retryable")),
                    "window_id": str(first_failed_error.get("window_id") or "").strip(),
                    "unresolved_window_ids": list(dict.fromkeys(failed_window_ids)),
                    "stage": "extract",
                }
                intermediate_writer.write_extract_error(
                    record=record,
                    error=failure_payload,
                    total_documents=total_documents,
                    expected_window_ids=expected_window_ids,
                    processed_window_ids=sorted(seen_processed_window_ids),
                    unresolved_window_ids=list(dict.fromkeys(failed_window_ids)),
                    reused_window_ids=reused_window_ids,
                )
                emit_stage_progress(
                    stage_progress_callback,
                    {
                        "stage": "extract",
                        "kind": "document_failed",
                        "doc_id": doc_id,
                        "title": str(record.title or "").strip(),
                        "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                        "total_windows": len(expected_window_ids),
                        "error": str(failure_payload.get("error") or ""),
                        "retryable": bool(failure_payload.get("retryable")),
                    },
                )
                continue

            intermediate_writer.write_extract_progress(
                record=record,
                supports=doc_supports,
                drafts=doc_drafts,
                total_documents=total_documents,
                expected_window_ids=expected_window_ids,
                processed_window_ids=sorted(seen_processed_window_ids),
                unresolved_window_ids=[],
                reused_window_ids=reused_window_ids,
                complete=True,
                failed=False,
            )
            if extract_progress_callback is not None:
                extract_progress_callback(
                    record,
                    doc_supports,
                    doc_drafts,
                    SkillExtractionResult(
                        documents=list(ingest_result.documents or []),
                        windows=list(ingest_result.windows or []),
                        support_records=list(support_by_id.values()),
                        skill_drafts=list(draft_by_id.values()),
                        extractor_name=str(persisted.extractor_name or "llm"),
                    ),
                )
            emit_stage_progress(
                stage_progress_callback,
                {
                    "stage": "extract",
                    "kind": "document_done",
                    "doc_id": doc_id,
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "total_windows": len(expected_window_ids),
                    "supports": len(doc_supports),
                    "drafts": len(doc_drafts),
                    "total_support_records": len(support_by_id),
                    "total_skill_drafts": len(draft_by_id),
                    "errors": len(list(intermediate_writer.load_extract_summary().errors or [])),
                },
            )

        merged = intermediate_writer.load_extract()
        all_doc_ids = [str(doc.doc_id or "").strip() for doc in ordered_documents]
        extract_complete = len(intermediate_writer.processed_extract_doc_ids()) == len([doc_id for doc_id in all_doc_ids if doc_id])
        intermediate_writer.write_extract(merged, complete_stage=extract_complete)
        return intermediate_writer.load_extract_summary()

    def _resume_or_stream_compile(
        self,
        *,
        intermediate_writer: IntermediateRunWriter,
        ingest_result: DocumentIngestResult,
        target_state: VersionState,
        stage_progress_callback=None,
    ) -> SkillCompilationResult:
        """Compiles per-document extract snapshots sequentially to keep memory bounded."""

        if intermediate_writer.has_completed_stage("compile"):
            loaded = intermediate_writer.load_compile()
            return SkillCompilationResult(errors=list(loaded.errors or []), compiler_name=loaded.compiler_name)
        ordered_doc_ids = [str(doc.doc_id or "").strip() for doc in list(ingest_result.documents or [])]
        documents_by_id = {str(doc.doc_id or "").strip(): doc for doc in list(ingest_result.documents or [])}
        extract_payloads = intermediate_writer.iter_extract_documents(ordered_doc_ids=ordered_doc_ids)
        existing_compile_payloads = intermediate_writer.iter_compile_documents(ordered_doc_ids=ordered_doc_ids)
        processed_doc_ids = {
            str(item.get("doc_id") or "").strip()
            for item in existing_compile_payloads
            if str(item.get("doc_id") or "").strip() and not bool(item.get("skipped"))
        }
        reused_compile_nodes: List[str] = []
        for payload in existing_compile_payloads:
            if bool(payload.get("skipped")):
                continue
            for item in list(payload.get("skill_drafts") or []):
                if not isinstance(item, dict):
                    continue
                try:
                    reused_compile_nodes.append(self._compile_group_node_key(_group_key_for_draft(SkillDraft.from_dict(item))))
                except Exception:
                    continue
        intermediate_writer.add_reused_nodes(reused_compile_nodes)
        completed_groups = sum(int(item.get("group_count") or 0) for item in existing_compile_payloads)
        completed_skills = sum(len(list(item.get("skill_specs") or [])) for item in existing_compile_payloads)
        completed_errors = sum(len(list(item.get("errors") or [])) for item in existing_compile_payloads)
        total_groups = 0
        for payload in extract_payloads:
            if bool(payload.get("failed")) or not bool(payload.get("complete", True)):
                continue
            drafts = [
                SkillDraft.from_dict(item)
                for item in list(payload.get("skill_drafts") or [])
                if isinstance(item, dict)
            ]
            total_groups += len({_group_key_for_draft(draft) for draft in drafts})
        emit_stage_progress(
            stage_progress_callback,
            {
                "stage": "compile",
                "kind": "start",
                "total_groups": total_groups,
                "completed_groups": completed_groups,
                "total_skills": completed_skills,
                "errors": completed_errors,
            },
        )
        processed_documents = len(processed_doc_ids)
        total_documents = len(list(ingest_result.documents or []))
        for doc_id in ordered_doc_ids:
            if doc_id in processed_doc_ids:
                continue
            record = documents_by_id.get(doc_id)
            if record is None:
                continue
            payload = next((item for item in extract_payloads if str(item.get("doc_id") or "").strip() == doc_id), {})
            if bool(payload.get("failed")) or not bool(payload.get("complete", True)):
                intermediate_writer.write_compile_progress(
                    record=record,
                    result=SkillCompilationResult(errors=[dict(payload.get("error") or {})]),
                    total_documents=total_documents,
                    processed_documents=processed_documents + 1,
                    group_count=0,
                    skipped=True,
                )
                processed_documents += 1
                continue
            doc_supports = [
                SupportRecord.from_dict(item)
                for item in list(payload.get("supports") or [])
                if isinstance(item, dict)
            ]
            doc_drafts = [
                SkillDraft.from_dict(item)
                for item in list(payload.get("skill_drafts") or [])
                if isinstance(item, dict)
            ]
            group_count = len({_group_key_for_draft(draft) for draft in doc_drafts})
            local_completed_groups = completed_groups
            local_completed_skills = completed_skills
            local_errors = completed_errors

            def _compile_progress(event: Dict[str, Any]) -> None:
                wrapped = dict(event or {})
                if str(wrapped.get("stage") or "").strip().lower() != "compile":
                    if stage_progress_callback is not None:
                        stage_progress_callback(wrapped)
                    return
                wrapped["total_groups"] = total_groups
                wrapped["completed_groups"] = min(
                    total_groups,
                    local_completed_groups + int(wrapped.get("completed_groups") or 0),
                )
                wrapped["total_skills"] = local_completed_skills + int(wrapped.get("total_skills") or 0)
                wrapped["errors"] = local_errors + int(wrapped.get("errors") or 0)
                if stage_progress_callback is not None:
                    stage_progress_callback(wrapped)

            compiled = self.compile_skills(
                skill_drafts=doc_drafts,
                support_records=doc_supports,
                target_state=target_state,
                progress_callback=_compile_progress,
            )
            intermediate_writer.write_compile_progress(
                record=record,
                result=compiled,
                total_documents=total_documents,
                processed_documents=processed_documents + 1,
                group_count=group_count,
            )
            completed_groups += group_count
            completed_skills += len(list(compiled.skill_specs or []))
            completed_errors += len(list(compiled.errors or []))
            processed_documents += 1
        aggregate = intermediate_writer.load_compile()
        compile_payloads = intermediate_writer.iter_compile_documents(ordered_doc_ids=ordered_doc_ids)
        compile_complete = (
            len(compile_payloads) >= len([doc_id for doc_id in ordered_doc_ids if doc_id])
            and all(not bool(payload.get("skipped")) for payload in compile_payloads if str(payload.get("doc_id") or "").strip())
        )
        intermediate_writer.write_compile(aggregate, complete_stage=compile_complete)
        return SkillCompilationResult(errors=list(aggregate.errors or []), compiler_name=aggregate.compiler_name)

    def _resume_or_stream_register(
        self,
        *,
        intermediate_writer: IntermediateRunWriter,
        ingest_result: DocumentIngestResult,
        user_id: str,
        metadata: Optional[Dict[str, Any]],
        dry_run: bool,
        target_state: VersionState,
        stage_progress_callback=None,
    ) -> VersionRegistrationResult:
        """Registers per-document compiled snapshots sequentially to keep memory bounded."""

        if intermediate_writer.has_completed_stage("register"):
            loaded = intermediate_writer.load_registration()
            return VersionRegistrationResult(
                visible_tree=dict(loaded.visible_tree or {}),
                upserted_store_skills=list(loaded.upserted_store_skills or []),
                staging_runs=list(loaded.staging_runs or []),
                errors=list(loaded.errors or []),
                dry_run=bool(loaded.dry_run),
            )
        ordered_doc_ids = [str(doc.doc_id or "").strip() for doc in list(ingest_result.documents or [])]
        documents_by_id = {str(doc.doc_id or "").strip(): doc for doc in list(ingest_result.documents or [])}
        compile_payloads = intermediate_writer.iter_compile_documents(ordered_doc_ids=ordered_doc_ids)
        existing_register_payloads = intermediate_writer.iter_register_documents(ordered_doc_ids=ordered_doc_ids)
        processed_doc_ids = {
            str(item.get("doc_id") or "").strip()
            for item in existing_register_payloads
            if str(item.get("doc_id") or "").strip() and not bool(item.get("skipped"))
        }
        reused_register_nodes: List[str] = []
        for payload in existing_register_payloads:
            if bool(payload.get("skipped")):
                continue
            for item in list(payload.get("skill_specs") or []):
                if not isinstance(item, dict):
                    continue
                skill_id = str(item.get("skill_id") or "").strip()
                if skill_id:
                    reused_register_nodes.append(self._register_skill_node_key(skill_id))
        intermediate_writer.add_reused_nodes(reused_register_nodes)
        completed_skills = sum(len(list(item.get("skill_specs") or [])) for item in existing_register_payloads)
        total_skills = sum(len(list(item.get("skill_specs") or [])) for item in compile_payloads if not bool(item.get("skipped")))
        completed_errors = sum(len(list(item.get("errors") or [])) for item in existing_register_payloads)
        total_documents = len(list(ingest_result.documents or []))
        processed_documents = len(processed_doc_ids)
        emit_stage_progress(
            stage_progress_callback,
            {
                "stage": "register",
                "kind": "start",
                "phase": "reconcile",
                "completed_skills": completed_skills,
                "total_skills": total_skills,
                "errors": completed_errors,
            },
        )
        for doc_id in ordered_doc_ids:
            if doc_id in processed_doc_ids:
                continue
            record = documents_by_id.get(doc_id)
            if record is None:
                continue
            payload = next((item for item in compile_payloads if str(item.get("doc_id") or "").strip() == doc_id), {})
            if bool(payload.get("skipped")):
                intermediate_writer.write_registration_progress(
                    record=record,
                    result=VersionRegistrationResult(
                        documents=[record],
                        errors=[{"stage": "register_skipped", **dict(item)} for item in list(payload.get("errors") or []) if isinstance(item, dict)],
                        dry_run=bool(dry_run),
                    ),
                    total_documents=total_documents,
                    processed_documents=processed_documents + 1,
                    action_counts={},
                    skipped=True,
                )
                processed_documents += 1
                continue
            doc_supports = [
                SupportRecord.from_dict(item)
                for item in list(payload.get("support_records") or [])
                if isinstance(item, dict)
            ]
            doc_specs = [
                SkillSpec.from_dict(item)
                for item in list(payload.get("skill_specs") or [])
                if isinstance(item, dict)
            ]
            base_completed = completed_skills
            base_errors = completed_errors
            action_counts: Dict[str, int] = {}

            def _register_progress(event: Dict[str, Any]) -> None:
                wrapped = dict(event or {})
                if str(wrapped.get("stage") or "").strip().lower() != "register":
                    if stage_progress_callback is not None:
                        stage_progress_callback(wrapped)
                    return
                if "completed_skills" in wrapped:
                    wrapped["completed_skills"] = min(
                        total_skills,
                        base_completed + int(wrapped.get("completed_skills") or 0),
                    )
                wrapped["total_skills"] = total_skills
                wrapped["errors"] = base_errors + int(wrapped.get("errors") or 0)
                action = str(wrapped.get("action") or "").strip()
                if action:
                    action_counts[action] = int(action_counts.get(action) or 0) + 1
                if stage_progress_callback is not None:
                    stage_progress_callback(wrapped)

            try:
                registered = self.register_versions(
                    documents=[record],
                    support_records=doc_supports,
                    skill_specs=doc_specs,
                    user_id=user_id,
                    metadata=metadata,
                    dry_run=dry_run,
                    target_state=target_state,
                    intermediate_writer=intermediate_writer,
                    progress_callback=_register_progress,
                )
            except Exception as exc:
                error_payload = {
                    "stage": "register_document",
                    "doc_id": doc_id,
                    "title": str(record.title or "").strip(),
                    "source_file": str((record.metadata or {}).get("source_file") or "").strip(),
                    "error": str(exc),
                    "retryable": bool(getattr(exc, "autoskill_retryable", False)),
                    "retry_attempts": int(getattr(exc, "autoskill_retry_attempts", 0) or 0),
                }
                emit_stage_progress(
                    stage_progress_callback,
                    {
                        "stage": "register",
                        "kind": "document_failed",
                        "phase": "reconcile",
                        "completed_skills": base_completed,
                        "total_skills": total_skills,
                        "current_skill_id": "",
                        "current_name": "",
                        "errors": base_errors + 1,
                    },
                )
                emit_stage_log(
                    self.logger,
                    (
                        f"[register_versions] document_error doc={doc_id} "
                        f"retry_attempts={error_payload['retry_attempts']} "
                        f"retryable={int(error_payload['retryable'])} "
                        f"error={error_payload['error']}"
                    ),
                )
                intermediate_writer.write_registration_progress(
                    record=record,
                    result=VersionRegistrationResult(
                        documents=[record],
                        errors=[error_payload],
                        dry_run=bool(dry_run),
                    ),
                    total_documents=total_documents,
                    processed_documents=processed_documents + 1,
                    action_counts=action_counts,
                    skipped=True,
                )
                completed_errors += 1
                processed_documents += 1
                continue
            intermediate_writer.write_registration_progress(
                record=record,
                result=registered,
                total_documents=total_documents,
                processed_documents=processed_documents + 1,
                action_counts=action_counts,
            )
            completed_skills += len(list(doc_specs or []))
            completed_errors += len(list(registered.errors or []))
            processed_documents += 1
        aggregate = intermediate_writer.load_registration()
        register_payloads = intermediate_writer.iter_register_documents(ordered_doc_ids=ordered_doc_ids)
        register_complete = (
            len(register_payloads) >= len([doc_id for doc_id in ordered_doc_ids if doc_id])
            and all(not bool(payload.get("skipped")) for payload in register_payloads if str(payload.get("doc_id") or "").strip())
        )
        intermediate_writer.write_registration(aggregate, complete_stage=register_complete)
        return VersionRegistrationResult(
            visible_tree=dict(aggregate.visible_tree or {}),
            upserted_store_skills=list(aggregate.upserted_store_skills or []),
            staging_runs=list(aggregate.staging_runs or []),
            errors=list(aggregate.errors or []),
            dry_run=bool(aggregate.dry_run),
        )


def build_default_document_pipeline(
    *,
    sdk: Optional[AutoSkill] = None,
    registry_root: str = "",
    logger: StageLogger = None,
    document_ingestor: Optional[DocumentIngestor] = None,
    document_skill_extractor: Optional[DocumentSkillExtractor] = None,
    skill_compiler: Optional[SkillCompiler] = None,
    taxonomy: Optional[SkillTaxonomy] = None,
    family_resolver: Optional[DocumentFamilyResolver] = None,
    extract_workers: int = 1,
    extract_retries: int = 3,
    extract_retry_backoff_s: float = 1.0,
    retrieval_score_threshold: float = DEFAULT_RETRIEVAL_SCORE_THRESHOLD,
    llm_rate_limit_requests: int = DEFAULT_LLM_RATE_LIMIT_REQUESTS,
    llm_rate_limit_window_s: float = DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
) -> DocumentBuildPipeline:
    """Builds the default staged document pipeline."""

    if registry_root:
        registry = DocumentRegistry(root_dir=registry_root)
    elif sdk is not None:
        registry = build_registry_from_store_config(dict(getattr(getattr(sdk, "config", None), "store", {}) or {}))
    else:
        from .store.registry import default_registry_root

        registry = DocumentRegistry(root_dir=default_registry_root(default_store_path()))
    effective_taxonomy = taxonomy or load_skill_taxonomy()
    return DocumentBuildPipeline(
        registry=registry,
        sdk=sdk,
        logger=logger,
        document_ingestor=document_ingestor
        or HeuristicDocumentIngestor(
            llm_config=dict(getattr(getattr(sdk, "config", None), "llm", {}) or {}),
            max_section_chars=DEFAULT_MAX_SECTION_CHARS,
            outline_fallback_mode=DEFAULT_SECTION_OUTLINE_MODE,
            llm_rate_limit_requests=max(0, int(llm_rate_limit_requests or 0)),
            llm_rate_limit_window_s=max(0.0, float(llm_rate_limit_window_s or 0.0)),
        ),
        document_skill_extractor=document_skill_extractor
        or build_document_skill_extractor(
            "llm",
            llm_config=dict(getattr(getattr(sdk, "config", None), "llm", {}) or {}),
            extract_workers=max(1, int(extract_workers or 1)),
            extract_retries=max(0, int(extract_retries or 0)),
            extract_retry_backoff_s=max(0.0, float(extract_retry_backoff_s or 0.0)),
            llm_rate_limit_requests=max(0, int(llm_rate_limit_requests or 0)),
            llm_rate_limit_window_s=max(0.0, float(llm_rate_limit_window_s or 0.0)),
        ),
        skill_compiler=skill_compiler
        or build_skill_compiler(
            "llm",
            llm_config=dict(getattr(getattr(sdk, "config", None), "llm", {}) or {}),
            llm_rate_limit_requests=max(0, int(llm_rate_limit_requests or 0)),
            llm_rate_limit_window_s=max(0.0, float(llm_rate_limit_window_s or 0.0)),
        ),
        taxonomy=effective_taxonomy,
        family_resolver=family_resolver
        or build_document_family_resolver(
            taxonomy=effective_taxonomy,
            llm_config=dict(getattr(getattr(sdk, "config", None), "llm", {}) or {}),
            llm_rate_limit_requests=max(0, int(llm_rate_limit_requests or 0)),
            llm_rate_limit_window_s=max(0.0, float(llm_rate_limit_window_s or 0.0)),
        ),
        retrieval_score_threshold=max(0.0, float(retrieval_score_threshold or DEFAULT_RETRIEVAL_SCORE_THRESHOLD)),
        llm_rate_limit_requests=max(0, int(llm_rate_limit_requests or 0)),
        llm_rate_limit_window_s=max(0.0, float(llm_rate_limit_window_s or 0.0)),
    )
