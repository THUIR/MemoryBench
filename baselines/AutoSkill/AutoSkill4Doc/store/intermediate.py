"""
Intermediate run persistence for AutoSkill4Doc.

Long-running document extraction should expose observable artifacts before the
final registry/store sync completes. This module writes stage snapshots under
`<store_root>/.runtime/intermediate_runs/<run_id>/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from autoskill.utils.time import now_iso

from ..models import DocumentRecord, SkillDraft, StrictWindow, SupportRecord
from .layout import intermediate_run_dir, normalize_library_root
from .staging import new_staging_run_id, safe_dir_component, safe_run_id

if TYPE_CHECKING:
    from ..ingest import DocumentIngestResult
    from ..stages.compiler import SkillCompilationResult
    from ..stages.extractor import SkillExtractionResult
    from ..store.versioning import ChangeDecision, VersionRegistrationResult


@dataclass
class IntermediateRunSummary:
    """Compact summary for one intermediate persistence run."""

    run_id: str
    run_dir: str
    status_path: str
    files: List[str] = field(default_factory=list)
    status: str = "running"
    current_stage: str = "initialized"
    completed_stages: List[str] = field(default_factory=list)
    completed_doc_ids: List[str] = field(default_factory=list)
    unresolved_doc_ids: List[str] = field(default_factory=list)
    unresolved_nodes: List[str] = field(default_factory=list)
    reused_nodes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Returns a JSON-safe summary payload."""

        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "status_path": self.status_path,
            "files": list(self.files or []),
            "status": str(self.status or "running"),
            "current_stage": self.current_stage,
            "completed_stages": list(self.completed_stages or []),
            "completed_doc_ids": list(self.completed_doc_ids or []),
            "unresolved_doc_ids": list(self.unresolved_doc_ids or []),
            "unresolved_nodes": list(self.unresolved_nodes or []),
            "reused_nodes": list(self.reused_nodes or []),
        }


def new_intermediate_run_id() -> str:
    """Creates a new run id for intermediate persistence."""

    return new_staging_run_id()


def build_resume_key(payload: Dict[str, Any]) -> str:
    """Builds a stable resume key for one pipeline invocation."""

    normalized = json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def find_intermediate_run_by_resume_key(*, base_store_root: str, resume_key: str) -> Optional[Dict[str, Any]]:
    """Returns the latest unfinished intermediate run that matches one resume key."""

    root = os.path.join(normalize_library_root(base_store_root), ".runtime", "intermediate_runs")
    key = str(resume_key or "").strip()
    if not key or not os.path.isdir(root):
        return None
    matches: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(root)):
        status_path = os.path.join(root, name, "status.json")
        if not os.path.isfile(status_path):
            continue
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        metadata = dict(payload.get("metadata") or {})
        if str(metadata.get("resume_key") or "").strip() != key:
            continue
        if str(payload.get("status") or "").strip() == "completed":
            continue
        matches.append(payload)
    if not matches:
        return None
    matches.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
    return matches[-1]


def _extract_error_key(item: Dict[str, Any]) -> str:
    """Builds a stable dedupe key for persisted extract errors."""

    payload = dict(item or {})
    payload.pop("stage", None)
    signature = {
        "doc_id": str(payload.get("doc_id") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "source_file": str(payload.get("source_file") or "").strip(),
        "path": str(payload.get("path") or "").strip(),
        "error": str(payload.get("error") or "").strip(),
    }
    return json.dumps(signature, ensure_ascii=False, sort_keys=True)


class IntermediateRunWriter:
    """Writes incremental stage snapshots for one document build run."""

    def __init__(
        self,
        *,
        base_store_root: str,
        run_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        resume_existing: bool = False,
    ) -> None:
        store_root = normalize_library_root(base_store_root)
        resolved_run_id = safe_run_id(run_id or new_intermediate_run_id())
        self.run_id = resolved_run_id
        self.run_dir = intermediate_run_dir(base_store_root=store_root, run_id=resolved_run_id)
        self.status_path = os.path.join(self.run_dir, "status.json")
        self._files: List[str] = []
        if resume_existing and os.path.isfile(self.status_path):
            with open(self.status_path, "r", encoding="utf-8") as f:
                self._state = json.load(f)
            if not isinstance(self._state, dict):
                self._state = {}
            self._state["run_id"] = self.run_id
            self._state["run_dir"] = self.run_dir
            self._state["status"] = "running"
            self._state["updated_at"] = now_iso()
            self._files = self._discover_files()
            self._flush_state()
            return
        self._state: Dict[str, Any] = {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "status": "running",
            "current_stage": "initialized",
            "completed_stages": [],
            "metadata": dict(metadata or {}),
            "counts": {},
            "progress_counts": {
                "extract_support_records": 0,
                "extract_skill_drafts": 0,
                "processed_documents": 0,
                "failed_documents": 0,
                "reused_nodes": 0,
            },
            "source_file": "",
            "completed_doc_ids": [],
            "unresolved_doc_ids": [],
            "unresolved_nodes": [],
            "reused_nodes": [],
        }
        os.makedirs(self.run_dir, exist_ok=True)
        self._flush_state()

    def _discover_files(self) -> List[str]:
        """Discovers persisted files already present under the run directory."""

        out: List[str] = []
        if not os.path.isdir(self.run_dir):
            return out
        for root, _, files in os.walk(self.run_dir):
            for name in sorted(files):
                path = os.path.join(root, name)
                if path == self.status_path:
                    continue
                out.append(path)
        return out

    def summary(self) -> IntermediateRunSummary:
        """Builds the latest run summary."""

        return IntermediateRunSummary(
            run_id=self.run_id,
            run_dir=self.run_dir,
            status_path=self.status_path,
            files=list(self._files or []),
            status=str(self._state.get("status") or "running"),
            current_stage=str(self._state.get("current_stage") or "initialized"),
            completed_stages=list(self._state.get("completed_stages") or []),
            completed_doc_ids=list(self._state.get("completed_doc_ids") or []),
            unresolved_doc_ids=list(self._state.get("unresolved_doc_ids") or []),
            unresolved_nodes=list(self._state.get("unresolved_nodes") or []),
            reused_nodes=list(self._state.get("reused_nodes") or []),
        )

    def update_metadata(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Merges resolved run metadata into the persisted status payload."""

        if not isinstance(metadata, dict) or not metadata:
            return
        current = dict(self._state.get("metadata") or {})
        current.update(dict(metadata or {}))
        self._state["metadata"] = current
        self._state["updated_at"] = now_iso()
        self._flush_state()

    def write_ingest(self, result: "DocumentIngestResult") -> None:
        """Writes the completed ingest snapshot."""

        payload = {
            "source_file": result.source_file,
            "text_units": [unit.to_dict() for unit in list(result.text_units or [])],
            "documents": [doc.to_dict() for doc in list(result.documents or [])],
            "skipped_documents": [doc.to_dict() for doc in list(result.skipped_documents or [])],
            "windows": [window.to_dict() for window in list(result.windows or [])],
            "errors": list(result.errors or []),
        }
        self._write_json("ingest/result.json", payload)
        self._set_stage(
            stage="ingest_completed",
            completed_stage="ingest",
            source_file=result.source_file,
            counts={
                "documents": len(result.documents),
                "skipped_documents": len(result.skipped_documents),
                "text_units": len(result.text_units),
                "windows": len(result.windows),
            },
        )

    def _extract_doc_name(self, doc_id: str) -> str:
        return safe_dir_component(str(doc_id or "").strip() or "document")

    def _window_node_key(self, window_id: str) -> str:
        return f"extract.window_plan({str(window_id or '').strip()})"

    def _window_expand_node_key(self, window_id: str, slot: Any) -> str:
        return f"extract.window_expand({str(window_id or '').strip()}, {int(slot or 0)})"

    def _normalize_node_list(self, values: Optional[Sequence[Any]] = None) -> List[str]:
        out: List[str] = []
        seen = set()
        for item in list(values or []):
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _merge_reused_nodes(self, values: Optional[Sequence[Any]] = None) -> None:
        merged = self._normalize_node_list(list(self._state.get("reused_nodes") or []) + list(values or []))
        self._state["reused_nodes"] = merged
        progress = dict(self._state.get("progress_counts") or {})
        progress["reused_nodes"] = len(merged)
        self._state["progress_counts"] = progress

    def _write_extract_document_payload(self, record: DocumentRecord, payload: Dict[str, Any]) -> None:
        doc_name = self._extract_doc_name(record.doc_id)
        self._write_json(f"extract/documents/{doc_name}.json", payload)
        self._write_json(f"extract/aggregate/{doc_name}.json", payload)

    def write_extract_window_progress(
        self,
        *,
        record: DocumentRecord,
        window: StrictWindow,
        supports: List[SupportRecord],
        drafts: List[SkillDraft],
    ) -> None:
        """Writes one successful extract window payload."""

        doc_name = self._extract_doc_name(record.doc_id)
        window_name = safe_dir_component(str(window.window_id or "").strip() or "window")
        payload = {
            "doc_id": record.doc_id,
            "title": record.title,
            "source_file": str((record.metadata or {}).get("source_file") or ""),
            "window_id": str(window.window_id or "").strip(),
            "section_heading": str(window.section_heading or "").strip(),
            "strategy": str(window.strategy or "").strip(),
            "supports": [support.to_dict() for support in list(supports or [])],
            "skill_drafts": [draft.to_dict() for draft in list(drafts or [])],
            "failed": False,
            "complete": True,
            "error": {},
        }
        self._write_json(f"extract/windows/{doc_name}/{window_name}.json", payload)

    def write_extract_window_error(
        self,
        *,
        record: DocumentRecord,
        window: StrictWindow,
        error: Dict[str, Any],
    ) -> None:
        """Writes one failed extract window payload."""

        doc_name = self._extract_doc_name(record.doc_id)
        window_name = safe_dir_component(str(window.window_id or "").strip() or "window")
        payload = {
            "doc_id": record.doc_id,
            "title": record.title,
            "source_file": str((record.metadata or {}).get("source_file") or ""),
            "window_id": str(window.window_id or "").strip(),
            "section_heading": str(window.section_heading or "").strip(),
            "strategy": str(window.strategy or "").strip(),
            "supports": [],
            "skill_drafts": [],
            "failed": True,
            "complete": False,
            "error": dict(error or {}),
        }
        self._write_json(f"extract/windows/{doc_name}/{window_name}.json", payload)

    def write_extract_audit(
        self,
        *,
        record: DocumentRecord,
        status: str,
        missing_window_ids: Optional[Sequence[str]] = None,
        reason: str = "",
        window_summaries: Optional[List[Dict[str, Any]]] = None,
        aggregate_skill_names: Optional[Sequence[str]] = None,
        targeted_window_ids: Optional[Sequence[str]] = None,
        resolved_window_ids: Optional[Sequence[str]] = None,
    ) -> None:
        """Writes one document-level extract audit artifact."""

        doc_name = self._extract_doc_name(record.doc_id)
        payload = {
            "doc_id": record.doc_id,
            "title": record.title,
            "status": str(status or "").strip() or "no_gap",
            "missing_window_ids": [str(item or "").strip() for item in list(missing_window_ids or []) if str(item or "").strip()],
            "reason": str(reason or "").strip(),
            "window_summaries": list(window_summaries or []),
            "aggregate_skill_names": [str(item or "").strip() for item in list(aggregate_skill_names or []) if str(item or "").strip()],
            "targeted_window_ids": [str(item or "").strip() for item in list(targeted_window_ids or []) if str(item or "").strip()],
            "resolved_window_ids": [str(item or "").strip() for item in list(resolved_window_ids or []) if str(item or "").strip()],
        }
        self._write_json(f"extract/audit/{doc_name}.json", payload)

    def write_extract_progress(
        self,
        *,
        record: DocumentRecord,
        supports: List[SupportRecord],
        drafts: List[SkillDraft],
        total_documents: int,
        expected_window_ids: Optional[Sequence[str]] = None,
        processed_window_ids: Optional[Sequence[str]] = None,
        unresolved_window_ids: Optional[Sequence[str]] = None,
        reused_window_ids: Optional[Sequence[str]] = None,
        audit_status: str = "",
        audit_missing_window_ids: Optional[Sequence[str]] = None,
        complete: bool = True,
        failed: bool = False,
    ) -> None:
        """Writes per-document extraction progress as soon as one doc finishes."""

        progress = dict(self._state.get("progress_counts") or {})
        progress["extract_support_records"] = int(progress.get("extract_support_records") or 0) + len(list(supports or []))
        progress["extract_skill_drafts"] = int(progress.get("extract_skill_drafts") or 0) + len(list(drafts or []))
        progress["processed_documents"] = int(progress.get("processed_documents") or 0) + 1
        self._state["progress_counts"] = progress
        reused_nodes: List[str] = []
        for window_id in list(reused_window_ids or []):
            key = str(window_id or "").strip()
            if key:
                reused_nodes.append(self._window_node_key(key))
        self._merge_reused_nodes(reused_nodes)
        payload = {
            "doc_id": record.doc_id,
            "title": record.title,
            "source_file": str((record.metadata or {}).get("source_file") or ""),
            "supports": [support.to_dict() for support in list(supports or [])],
            "skill_drafts": [draft.to_dict() for draft in list(drafts or [])],
            "cumulative_support_records": int(progress.get("extract_support_records") or 0),
            "cumulative_skill_drafts": int(progress.get("extract_skill_drafts") or 0),
            "processed_documents": int(progress.get("processed_documents") or 0),
            "total_documents": int(total_documents or 0),
            "expected_window_ids": [str(item or "").strip() for item in list(expected_window_ids or []) if str(item or "").strip()],
            "processed_window_ids": [str(item or "").strip() for item in list(processed_window_ids or []) if str(item or "").strip()],
            "unresolved_window_ids": [str(item or "").strip() for item in list(unresolved_window_ids or []) if str(item or "").strip()],
            "reused_window_ids": [str(item or "").strip() for item in list(reused_window_ids or []) if str(item or "").strip()],
            "audit_status": str(audit_status or "").strip(),
            "audit_missing_window_ids": [
                str(item or "").strip() for item in list(audit_missing_window_ids or []) if str(item or "").strip()
            ],
            "complete": bool(complete),
            "failed": bool(failed),
        }
        self._write_extract_document_payload(record, payload)
        self._set_stage(
            stage="extract_running",
            counts={
                "documents": total_documents,
                "processed_documents": min(total_documents, int(progress.get("processed_documents") or 0)),
                "support_records": int(progress.get("extract_support_records") or 0),
                "skill_drafts": int(progress.get("extract_skill_drafts") or 0),
            },
        )

    def write_extract_error(
        self,
        *,
        record: DocumentRecord,
        error: Dict[str, Any],
        total_documents: int,
        expected_window_ids: Optional[Sequence[str]] = None,
        processed_window_ids: Optional[Sequence[str]] = None,
        unresolved_window_ids: Optional[Sequence[str]] = None,
        reused_window_ids: Optional[Sequence[str]] = None,
        audit_status: str = "",
        audit_missing_window_ids: Optional[Sequence[str]] = None,
    ) -> None:
        """Writes one per-document extraction failure snapshot."""

        progress = dict(self._state.get("progress_counts") or {})
        progress["processed_documents"] = int(progress.get("processed_documents") or 0) + 1
        progress["failed_documents"] = int(progress.get("failed_documents") or 0) + 1
        self._state["progress_counts"] = progress
        reused_nodes: List[str] = []
        for window_id in list(reused_window_ids or []):
            key = str(window_id or "").strip()
            if key:
                reused_nodes.append(self._window_node_key(key))
        self._merge_reused_nodes(reused_nodes)
        payload = {
            "doc_id": record.doc_id,
            "title": record.title,
            "source_file": str((record.metadata or {}).get("source_file") or ""),
            "supports": [],
            "skill_drafts": [],
            "failed": True,
            "error": dict(error or {}),
            "processed_documents": int(progress.get("processed_documents") or 0),
            "total_documents": int(total_documents or 0),
            "expected_window_ids": [str(item or "").strip() for item in list(expected_window_ids or []) if str(item or "").strip()],
            "processed_window_ids": [str(item or "").strip() for item in list(processed_window_ids or []) if str(item or "").strip()],
            "unresolved_window_ids": [str(item or "").strip() for item in list(unresolved_window_ids or []) if str(item or "").strip()],
            "reused_window_ids": [str(item or "").strip() for item in list(reused_window_ids or []) if str(item or "").strip()],
            "audit_status": str(audit_status or "").strip(),
            "audit_missing_window_ids": [
                str(item or "").strip() for item in list(audit_missing_window_ids or []) if str(item or "").strip()
            ],
            "complete": False,
        }
        self._write_extract_document_payload(record, payload)
        self._set_stage(
            stage="extract_running",
            counts={
                "documents": total_documents,
                "processed_documents": min(total_documents, int(progress.get("processed_documents") or 0)),
                "failed_documents": int(progress.get("failed_documents") or 0),
                "support_records": int(progress.get("extract_support_records") or 0),
                "skill_drafts": int(progress.get("extract_skill_drafts") or 0),
            },
        )

    def write_extract(self, result: "SkillExtractionResult", *, complete_stage: bool = True) -> None:
        """Writes the aggregate extraction snapshot."""

        payload = {
            "documents": [doc.to_dict() for doc in list(result.documents or [])],
            "windows": [window.to_dict() for window in list(result.windows or [])],
            "support_records": [support.to_dict() for support in list(result.support_records or [])],
            "skill_drafts": [draft.to_dict() for draft in list(result.skill_drafts or [])],
            "errors": list(result.errors or []),
        }
        self._write_json("extract/result.json", payload)
        self._set_stage(
            stage="extract_completed",
            completed_stage=("extract" if bool(complete_stage) else ""),
            counts={
                "support_records": len(result.support_records),
                "skill_drafts": len(result.skill_drafts),
                "documents": len(result.documents),
                "windows": len(result.windows),
            },
        )

    def _load_document_stage_payloads(
        self,
        *,
        stage: str,
        ordered_doc_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Loads persisted per-document payloads for one stage in a stable order."""

        stage_dir = os.path.join(self.run_dir, stage, "documents")
        if not os.path.isdir(stage_dir):
            return []
        by_doc_id: Dict[str, Dict[str, Any]] = {}
        extras: List[Dict[str, Any]] = []
        for name in sorted(os.listdir(stage_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(stage_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            doc_id = str(payload.get("doc_id") or "").strip()
            if doc_id:
                by_doc_id[doc_id] = payload
            else:
                extras.append(payload)
        ordered: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for doc_id in list(ordered_doc_ids or []):
            key = str(doc_id or "").strip()
            if key and key in by_doc_id:
                ordered.append(by_doc_id[key])
                seen.add(key)
        for doc_id in sorted(by_doc_id):
            if doc_id in seen:
                continue
            ordered.append(by_doc_id[doc_id])
        ordered.extend(extras)
        return ordered

    def iter_extract_documents(self, *, ordered_doc_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Returns persisted per-document extract payloads."""

        return self._load_document_stage_payloads(stage="extract", ordered_doc_ids=ordered_doc_ids)

    def load_extract_document(self, doc_id: str) -> Dict[str, Any]:
        """Loads one persisted per-document extract payload."""

        key = str(doc_id or "").strip()
        if not key:
            return {}
        for payload in self.iter_extract_documents(ordered_doc_ids=[key]):
            if str(payload.get("doc_id") or "").strip() == key:
                return payload
        return {}

    def iter_extract_windows(
        self,
        *,
        doc_id: str,
        ordered_window_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Loads persisted per-window extract payloads for one document."""

        doc_name = self._extract_doc_name(doc_id)
        stage_dir = os.path.join(self.run_dir, "extract", "windows", doc_name)
        if not os.path.isdir(stage_dir):
            return []
        by_window_id: Dict[str, Dict[str, Any]] = {}
        extras: List[Dict[str, Any]] = []
        for name in sorted(os.listdir(stage_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(stage_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            window_id = str(payload.get("window_id") or "").strip()
            if window_id:
                by_window_id[window_id] = payload
            else:
                extras.append(payload)
        ordered: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for window_id in list(ordered_window_ids or []):
            key = str(window_id or "").strip()
            if key and key in by_window_id:
                ordered.append(by_window_id[key])
                seen.add(key)
        for window_id in sorted(by_window_id):
            if window_id in seen:
                continue
            ordered.append(by_window_id[window_id])
        ordered.extend(extras)
        return ordered

    def load_extract_audit(self, doc_id: str) -> Dict[str, Any]:
        """Loads one persisted document audit payload."""

        path = os.path.join(self.run_dir, "extract", "audit", f"{self._extract_doc_name(doc_id)}.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def processed_extract_window_ids(self, doc_id: str) -> List[str]:
        """Returns successful extract window ids for one document."""

        out: List[str] = []
        for payload in self.iter_extract_windows(doc_id=doc_id):
            if bool(payload.get("failed")) or not bool(payload.get("complete", True)):
                continue
            window_id = str(payload.get("window_id") or "").strip()
            if window_id:
                out.append(window_id)
        return out

    def load_ingest(self) -> "DocumentIngestResult":
        """Loads the completed ingest snapshot."""

        from ..ingest import DocumentIngestResult
        from ..models import TextUnit

        path = os.path.join(self.run_dir, "ingest", "result.json")
        documents: List[DocumentRecord] = []
        skipped_documents: List[DocumentRecord] = []
        text_units: List[TextUnit] = []
        windows: List[StrictWindow] = []
        errors: List[Dict[str, Any]] = []
        source_file = str(self._state.get("source_file") or "").strip()
        if not os.path.isfile(path):
            return DocumentIngestResult(source_file=source_file, errors=[{"stage": "intermediate_ingest_load", "error": "ingest snapshot not found"}])
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                source_file = str(payload.get("source_file") or source_file).strip()
                documents = [DocumentRecord.from_dict(item) for item in list(payload.get("documents") or []) if isinstance(item, dict)]
                skipped_documents = [DocumentRecord.from_dict(item) for item in list(payload.get("skipped_documents") or []) if isinstance(item, dict)]
                text_units = [TextUnit.from_dict(item) for item in list(payload.get("text_units") or []) if isinstance(item, dict)]
                windows = [StrictWindow.from_dict(item) for item in list(payload.get("windows") or []) if isinstance(item, dict)]
                errors = [{"stage": "intermediate_ingest_load", **item} for item in list(payload.get("errors") or []) if isinstance(item, dict)]
        except Exception as exc:
            errors.append({"stage": "intermediate_ingest_load", "path": path, "error": str(exc)})
        return DocumentIngestResult(
            source_file=source_file,
            text_units=text_units,
            documents=documents,
            skipped_documents=skipped_documents,
            windows=windows,
            errors=errors,
        )

    def load_extract(self) -> "SkillExtractionResult":
        """Loads aggregated extraction results from per-document progress files."""

        from ..stages.extractor import SkillExtractionResult
        from ..models import DocumentRecord, StrictWindow

        extract_dir = os.path.join(self.run_dir, "extract", "documents")
        support_records: List[SupportRecord] = []
        skill_drafts: List[SkillDraft] = []
        errors: List[Dict[str, Any]] = []
        documents: List[DocumentRecord] = []
        windows: List[StrictWindow] = []
        aggregate_path = os.path.join(self.run_dir, "extract", "result.json")
        if self.has_completed_stage("extract") and os.path.isfile(aggregate_path):
            try:
                with open(aggregate_path, "r", encoding="utf-8") as f:
                    aggregate = json.load(f)
                if isinstance(aggregate, dict):
                    documents = [
                        DocumentRecord.from_dict(item)
                        for item in list(aggregate.get("documents") or [])
                        if isinstance(item, dict)
                    ]
                    windows = [
                        StrictWindow.from_dict(item)
                        for item in list(aggregate.get("windows") or [])
                        if isinstance(item, dict)
                    ]
                    errors.extend(
                        [{"stage": "intermediate_extract_result_load", **item} for item in list(aggregate.get("errors") or []) if isinstance(item, dict)]
                    )
            except Exception as exc:
                errors.append({"stage": "intermediate_extract_result_load", "path": aggregate_path, "error": str(exc)})
        if not documents or not windows:
            ingest_path = os.path.join(self.run_dir, "ingest", "result.json")
            if os.path.isfile(ingest_path):
                try:
                    with open(ingest_path, "r", encoding="utf-8") as f:
                        ingest_payload = json.load(f)
                    if isinstance(ingest_payload, dict):
                        if not documents:
                            documents = [
                                DocumentRecord.from_dict(item)
                                for item in list(ingest_payload.get("documents") or [])
                                if isinstance(item, dict)
                            ]
                        if not windows:
                            windows = [
                                StrictWindow.from_dict(item)
                                for item in list(ingest_payload.get("windows") or [])
                                if isinstance(item, dict)
                            ]
                except Exception as exc:
                    errors.append({"stage": "intermediate_ingest_result_load", "path": ingest_path, "error": str(exc)})
        used_window_payloads = False
        windows_root = os.path.join(self.run_dir, "extract", "windows")
        if os.path.isdir(windows_root):
            used_window_payloads = True
            for doc_name in sorted(os.listdir(windows_root)):
                doc_dir = os.path.join(windows_root, doc_name)
                if not os.path.isdir(doc_dir):
                    continue
                for name in sorted(os.listdir(doc_dir)):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(doc_dir, name)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            payload = json.load(f)
                    except Exception as exc:
                        errors.append({"path": path, "error": str(exc)})
                        continue
                    if bool(payload.get("failed")):
                        continue
                    for item in list(payload.get("supports") or []):
                        if isinstance(item, dict):
                            support_records.append(SupportRecord.from_dict(item))
                    for item in list(payload.get("skill_drafts") or []):
                        if isinstance(item, dict):
                            skill_drafts.append(SkillDraft.from_dict(item))
        if not used_window_payloads and os.path.isdir(extract_dir):
            for name in sorted(os.listdir(extract_dir)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(extract_dir, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                except Exception as exc:
                    errors.append({"path": path, "error": str(exc)})
                    continue
                if isinstance(payload.get("error"), dict):
                    errors.append(dict(payload.get("error") or {}))
                if bool(payload.get("failed")) or not bool(payload.get("complete", True)):
                    continue
                for item in list(payload.get("supports") or []):
                    if isinstance(item, dict):
                        support_records.append(SupportRecord.from_dict(item))
                for item in list(payload.get("skill_drafts") or []):
                    if isinstance(item, dict):
                        skill_drafts.append(SkillDraft.from_dict(item))
        for payload in self.iter_extract_documents():
            if isinstance(payload.get("error"), dict):
                errors.append(dict(payload.get("error") or {}))
        seen_supports = {}
        for support in support_records:
            seen_supports[support.support_id] = support
        seen_drafts = {}
        for draft in skill_drafts:
            seen_drafts[draft.draft_id] = draft
        return SkillExtractionResult(
            documents=documents,
            windows=windows,
            support_records=list(seen_supports.values()),
            skill_drafts=list(seen_drafts.values()),
            errors=[
                {"stage": "intermediate_extract_load", **item}
                for item in {
                    _extract_error_key(dict(item or {})): dict(item or {})
                    for item in errors
                    if isinstance(item, dict)
                }.values()
            ],
            extractor_name="llm",
        )

    def load_extract_summary(self) -> "SkillExtractionResult":
        """Loads only lightweight extract metadata without materializing all supports/drafts."""

        from ..stages.extractor import SkillExtractionResult

        documents: List[DocumentRecord] = []
        windows: List[StrictWindow] = []
        errors: List[Dict[str, Any]] = []
        aggregate_path = os.path.join(self.run_dir, "extract", "result.json")
        if self.has_completed_stage("extract") and os.path.isfile(aggregate_path):
            try:
                with open(aggregate_path, "r", encoding="utf-8") as f:
                    aggregate = json.load(f)
                if isinstance(aggregate, dict):
                    documents = [
                        DocumentRecord.from_dict(item)
                        for item in list(aggregate.get("documents") or [])
                        if isinstance(item, dict)
                    ]
                    windows = [
                        StrictWindow.from_dict(item)
                        for item in list(aggregate.get("windows") or [])
                        if isinstance(item, dict)
                    ]
                    errors.extend(
                        [{"stage": "intermediate_extract_result_load", **item} for item in list(aggregate.get("errors") or []) if isinstance(item, dict)]
                    )
            except Exception as exc:
                errors.append({"stage": "intermediate_extract_result_load", "path": aggregate_path, "error": str(exc)})
        if not documents or not windows:
            ingest_loaded = self.load_ingest()
            documents = list(ingest_loaded.documents or [])
            windows = list(ingest_loaded.windows or [])
            errors.extend(list(ingest_loaded.errors or []))
        for payload in self.iter_extract_documents():
            if isinstance(payload.get("error"), dict):
                errors.append(dict(payload.get("error") or {}))
        deduped = {
            _extract_error_key(dict(item or {})): dict(item or {})
            for item in errors
            if isinstance(item, dict)
        }
        return SkillExtractionResult(
            documents=documents,
            windows=windows,
            errors=[{"stage": "intermediate_extract_load", **item} for item in deduped.values()],
            extractor_name="llm",
        )

    def processed_extract_doc_ids(self) -> List[str]:
        """Returns document ids with successful per-document extract snapshots."""

        return [
            str(payload.get("doc_id") or "").strip()
            for payload in self.iter_extract_documents()
            if str(payload.get("doc_id") or "").strip()
            and not bool(payload.get("failed"))
            and bool(payload.get("complete", True))
            and not list(payload.get("unresolved_window_ids") or [])
        ]

    def write_compile_progress(
        self,
        *,
        record: DocumentRecord,
        result: "SkillCompilationResult",
        total_documents: int,
        processed_documents: int,
        group_count: int,
        skipped: bool = False,
    ) -> None:
        """Writes one per-document compile snapshot."""

        payload = {
            "doc_id": record.doc_id,
            "title": record.title,
            "source_file": str((record.metadata or {}).get("source_file") or ""),
            "support_records": [support.to_dict() for support in list(result.support_records or [])],
            "skill_drafts": [draft.to_dict() for draft in list(result.skill_drafts or [])],
            "skill_specs": [skill.to_dict() for skill in list(result.skill_specs or [])],
            "errors": list(result.errors or []),
            "group_count": int(group_count or 0),
            "processed_documents": int(processed_documents or 0),
            "total_documents": int(total_documents or 0),
            "skipped": bool(skipped),
        }
        doc_name = safe_dir_component(str(record.doc_id or "").strip() or "document")
        self._write_json(f"compile/documents/{doc_name}.json", payload)
        self._set_stage(
            stage="compile_running",
            counts={
                "compile_processed_documents": int(processed_documents or 0),
                "compile_total_documents": int(total_documents or 0),
            },
        )

    def iter_compile_documents(self, *, ordered_doc_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Returns persisted per-document compile payloads."""

        return self._load_document_stage_payloads(stage="compile", ordered_doc_ids=ordered_doc_ids)

    def processed_compile_doc_ids(self) -> List[str]:
        """Returns document ids with persisted per-document compile snapshots."""

        return [
            str(payload.get("doc_id") or "").strip()
            for payload in self.iter_compile_documents()
            if str(payload.get("doc_id") or "").strip() and not bool(payload.get("skipped"))
        ]

    def write_compile(self, result: "SkillCompilationResult", *, complete_stage: bool = True) -> None:
        """Writes the completed compile snapshot."""

        payload = {
            "support_records": [support.to_dict() for support in list(result.support_records or [])],
            "skill_drafts": [draft.to_dict() for draft in list(result.skill_drafts or [])],
            "skill_specs": [skill.to_dict() for skill in list(result.skill_specs or [])],
            "errors": list(result.errors or []),
        }
        self._write_json("compile/result.json", payload)
        self._set_stage(
            stage="compile_completed",
            completed_stage=("compile" if bool(complete_stage) else ""),
            counts={
                "compiled_support_records": len(result.support_records),
                "compiled_skill_drafts": len(result.skill_drafts),
                "skill_specs": len(result.skill_specs),
            },
        )

    def load_compile(self) -> "SkillCompilationResult":
        """Loads the completed compile snapshot."""

        from ..models import SkillSpec
        from ..stages.compiler import SkillCompilationResult

        path = os.path.join(self.run_dir, "compile", "result.json")
        support_records: List[SupportRecord] = []
        skill_drafts: List[SkillDraft] = []
        skill_specs: List[SkillSpec] = []
        errors: List[Dict[str, Any]] = []
        if not self.has_completed_stage("compile") or not os.path.isfile(path):
            payloads = self.iter_compile_documents()
            if not payloads:
                return SkillCompilationResult(errors=[{"stage": "intermediate_compile_load", "error": "compile snapshot not found"}])
            for payload in payloads:
                if bool(payload.get("skipped")):
                    continue
                support_records.extend(
                    [SupportRecord.from_dict(item) for item in list(payload.get("support_records") or []) if isinstance(item, dict)]
                )
                skill_drafts.extend(
                    [SkillDraft.from_dict(item) for item in list(payload.get("skill_drafts") or []) if isinstance(item, dict)]
                )
                skill_specs.extend(
                    [SkillSpec.from_dict(item) for item in list(payload.get("skill_specs") or []) if isinstance(item, dict)]
                )
                errors.extend(
                    [
                        {"stage": "intermediate_compile_load", **item}
                        for item in list(payload.get("errors") or [])
                        if isinstance(item, dict)
                    ]
                )
            support_by_id = {item.support_id: item for item in support_records}
            draft_by_id = {item.draft_id: item for item in skill_drafts}
            return SkillCompilationResult(
                support_records=list(support_by_id.values()),
                skill_drafts=list(draft_by_id.values()),
                skill_specs=skill_specs,
                errors=errors,
                compiler_name="llm",
            )
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                support_records = [SupportRecord.from_dict(item) for item in list(payload.get("support_records") or []) if isinstance(item, dict)]
                skill_drafts = [SkillDraft.from_dict(item) for item in list(payload.get("skill_drafts") or []) if isinstance(item, dict)]
                skill_specs = [SkillSpec.from_dict(item) for item in list(payload.get("skill_specs") or []) if isinstance(item, dict)]
                errors = [{"stage": "intermediate_compile_load", **item} for item in list(payload.get("errors") or []) if isinstance(item, dict)]
        except Exception as exc:
            errors.append({"stage": "intermediate_compile_load", "path": path, "error": str(exc)})
        return SkillCompilationResult(
            support_records=support_records,
            skill_drafts=skill_drafts,
            skill_specs=skill_specs,
            errors=errors,
            compiler_name="llm",
        )

    def load_compile_summary(self) -> "SkillCompilationResult":
        """Loads only lightweight compile metadata without materializing all supports/specs."""

        from ..stages.compiler import SkillCompilationResult

        path = os.path.join(self.run_dir, "compile", "result.json")
        errors: List[Dict[str, Any]] = []
        if self.has_completed_stage("compile") and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    errors.extend(
                        [{"stage": "intermediate_compile_load", **item} for item in list(payload.get("errors") or []) if isinstance(item, dict)]
                    )
            except Exception as exc:
                errors.append({"stage": "intermediate_compile_load", "path": path, "error": str(exc)})
        else:
            for payload in self.iter_compile_documents():
                errors.extend(
                    [
                        {"stage": "intermediate_compile_load", **item}
                        for item in list(payload.get("errors") or [])
                        if isinstance(item, dict)
                    ]
                )
        return SkillCompilationResult(errors=errors, compiler_name="llm")

    def write_registration_progress(
        self,
        *,
        record: DocumentRecord,
        result: "VersionRegistrationResult",
        total_documents: int,
        processed_documents: int,
        action_counts: Optional[Dict[str, int]] = None,
        skipped: bool = False,
    ) -> None:
        """Writes one per-document registration snapshot."""

        payload = {
            "doc_id": record.doc_id,
            "title": record.title,
            "source_file": str((record.metadata or {}).get("source_file") or ""),
            "documents": [doc.to_dict() for doc in list(result.documents or [])],
            "support_records": [support.to_dict() for support in list(result.support_records or [])],
            "skill_specs": [skill.to_dict() for skill in list(result.skill_specs or [])],
            "hierarchy_updates": [skill.to_dict() for skill in list(result.hierarchy_updates or [])],
            "lifecycles": [item.to_dict() for item in list(result.lifecycles or [])],
            "change_logs": list(result.change_logs or []),
            "version_history": list(result.version_history or []),
            "provenance_links": list(result.provenance_links or []),
            "upserted_store_skills": list(result.upserted_store_skills or []),
            "staging_runs": list(result.staging_runs or []),
            "visible_tree": dict(result.visible_tree or {}),
            "errors": list(result.errors or []),
            "dry_run": bool(result.dry_run),
            "processed_documents": int(processed_documents or 0),
            "total_documents": int(total_documents or 0),
            "action_counts": {str(key): int(value or 0) for key, value in dict(action_counts or {}).items()},
            "skipped": bool(skipped),
        }
        doc_name = safe_dir_component(str(record.doc_id or "").strip() or "document")
        self._write_json(f"register/documents/{doc_name}.json", payload)
        self._set_stage(
            stage="register_running",
            counts={
                "register_processed_documents": int(processed_documents or 0),
                "register_total_documents": int(total_documents or 0),
            },
        )

    def iter_register_documents(self, *, ordered_doc_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Returns persisted per-document register payloads."""

        return self._load_document_stage_payloads(stage="register", ordered_doc_ids=ordered_doc_ids)

    def processed_register_doc_ids(self) -> List[str]:
        """Returns document ids with persisted per-document registration snapshots."""

        return [
            str(payload.get("doc_id") or "").strip()
            for payload in self.iter_register_documents()
            if str(payload.get("doc_id") or "").strip() and not bool(payload.get("skipped"))
        ]

    def successful_register_doc_ids(self) -> List[str]:
        """Returns document ids that fully completed register."""

        return self.processed_register_doc_ids()

    def write_register_decision(
        self,
        decision: "ChangeDecision",
        *,
        hits: int,
        branch: str,
        total_skills: int,
    ) -> None:
        """Writes one completed ChangeDecision checkpoint for register recovery."""

        payload = {
            "skill_id": str(getattr(decision.skill, "skill_id", "") or "").strip(),
            "action": str(decision.action or "").strip(),
            "matched_skill_ids": list(decision.matched_skill_ids or []),
            "reason": str(decision.reason or "").strip(),
            "split_parent_id": str(decision.split_parent_id or "").strip(),
            "skill": decision.skill.to_dict(),
            "hits": int(hits or 0),
            "branch": str(branch or "").strip(),
        }
        skill_id = str(payload.get("skill_id") or "").strip()
        if not skill_id:
            return
        self._write_json(f"register/decisions/{safe_dir_component(skill_id)}.json", payload)
        self._set_stage(
            stage="register_running",
            counts={
                "register_total_skills": max(int(total_skills or 0), len(self.processed_register_decision_ids())),
                "register_decisions_completed": len(self.processed_register_decision_ids()),
            },
        )

    def load_register_decisions(self) -> Dict[str, "ChangeDecision"]:
        """Loads persisted register/classify ChangeDecision checkpoints."""

        from ..models import SkillSpec
        from ..store.versioning import ChangeDecision

        decisions_dir = os.path.join(self.run_dir, "register", "decisions")
        out: Dict[str, ChangeDecision] = {}
        if not os.path.isdir(decisions_dir):
            return out
        for name in sorted(os.listdir(decisions_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(decisions_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            skill_id = str(payload.get("skill_id") or "").strip()
            skill_payload = payload.get("skill")
            if not skill_id or not isinstance(skill_payload, dict):
                continue
            try:
                out[skill_id] = ChangeDecision(
                    action=str(payload.get("action") or "").strip(),
                    skill=SkillSpec.from_dict(skill_payload),
                    matched_skill_ids=list(payload.get("matched_skill_ids") or []),
                    reason=str(payload.get("reason") or "").strip(),
                    split_parent_id=str(payload.get("split_parent_id") or "").strip(),
                    hits=int(payload.get("hits", 0) or 0),
                    branch=str(payload.get("branch") or "").strip(),
                )
            except Exception:
                continue
        return out

    def processed_register_decision_ids(self) -> List[str]:
        """Returns skill ids that already have persisted ChangeDecision checkpoints."""

        return list(self.load_register_decisions().keys())

    def write_registration(self, result: "VersionRegistrationResult", *, complete_stage: bool = True) -> None:
        """Writes the completed registration snapshot."""

        payload = {
            "documents": [doc.to_dict() for doc in list(result.documents or [])],
            "support_records": [support.to_dict() for support in list(result.support_records or [])],
            "skill_specs": [skill.to_dict() for skill in list(result.skill_specs or [])],
            "hierarchy_updates": [skill.to_dict() for skill in list(result.hierarchy_updates or [])],
            "lifecycles": [item.to_dict() for item in list(result.lifecycles or [])],
            "change_logs": list(result.change_logs or []),
            "version_history": list(result.version_history or []),
            "provenance_links": list(result.provenance_links or []),
            "upserted_store_skills": list(result.upserted_store_skills or []),
            "staging_runs": list(result.staging_runs or []),
            "visible_tree": dict(result.visible_tree or {}),
            "errors": list(result.errors or []),
            "dry_run": bool(result.dry_run),
        }
        self._write_json("register/result.json", payload)
        self._set_stage(
            stage="register_completed",
            completed_stage=("register" if bool(complete_stage) else ""),
            counts={
                "lifecycles": len(result.lifecycles),
                "change_logs": len(result.change_logs),
                "version_history_entries": len(result.version_history),
                "provenance_links": len(result.provenance_links),
                "upserted_store_skills": len(result.upserted_store_skills),
                "staging_runs": len(result.staging_runs),
            },
        )

    def load_registration(self) -> "VersionRegistrationResult":
        """Loads the completed registration snapshot."""

        from ..models import SkillLifecycle, SkillSpec
        from ..store.versioning import VersionRegistrationResult

        path = os.path.join(self.run_dir, "register", "result.json")
        documents: List[DocumentRecord] = []
        support_records: List[SupportRecord] = []
        skill_specs: List[SkillSpec] = []
        hierarchy_updates: List[SkillSpec] = []
        lifecycles: List[SkillLifecycle] = []
        change_logs: List[Dict[str, Any]] = []
        version_history: List[Dict[str, Any]] = []
        provenance_links: List[Dict[str, Any]] = []
        upserted_store_skills: List[Dict[str, Any]] = []
        staging_runs: List[Dict[str, Any]] = []
        visible_tree: Dict[str, Any] = {}
        errors: List[Dict[str, Any]] = []
        dry_run = False
        if not self.has_completed_stage("register") or not os.path.isfile(path):
            payloads = self.iter_register_documents()
            if not payloads:
                return VersionRegistrationResult(errors=[{"stage": "intermediate_register_load", "error": "register snapshot not found"}])
            document_by_id: Dict[str, DocumentRecord] = {}
            support_by_id: Dict[str, SupportRecord] = {}
            skill_by_id: Dict[str, SkillSpec] = {}
            hierarchy_by_id: Dict[str, SkillSpec] = {}
            upserted_by_id: Dict[str, Dict[str, Any]] = {}
            visible_lists = {"affected_families": set(), "parent_paths": set(), "child_paths": set()}
            for payload in payloads:
                errors.extend(
                    [
                        {"stage": "intermediate_register_load", **item}
                        for item in list(payload.get("errors") or [])
                        if isinstance(item, dict)
                    ]
                )
                if bool(payload.get("skipped")):
                    continue
                for item in list(payload.get("documents") or []):
                    if not isinstance(item, dict):
                        continue
                    document = DocumentRecord.from_dict(item)
                    document_by_id[document.doc_id] = document
                for item in list(payload.get("support_records") or []):
                    if not isinstance(item, dict):
                        continue
                    support = SupportRecord.from_dict(item)
                    support_by_id[support.support_id] = support
                for item in list(payload.get("skill_specs") or []):
                    if not isinstance(item, dict):
                        continue
                    skill = SkillSpec.from_dict(item)
                    skill_by_id[skill.skill_id] = skill
                for item in list(payload.get("hierarchy_updates") or []):
                    if not isinstance(item, dict):
                        continue
                    skill = SkillSpec.from_dict(item)
                    hierarchy_by_id[skill.skill_id] = skill
                lifecycles.extend(
                    [SkillLifecycle.from_dict(item) for item in list(payload.get("lifecycles") or []) if isinstance(item, dict)]
                )
                change_logs.extend([dict(item) for item in list(payload.get("change_logs") or []) if isinstance(item, dict)])
                version_history.extend([dict(item) for item in list(payload.get("version_history") or []) if isinstance(item, dict)])
                provenance_links.extend([dict(item) for item in list(payload.get("provenance_links") or []) if isinstance(item, dict)])
                for item in list(payload.get("upserted_store_skills") or []):
                    if not isinstance(item, dict):
                        continue
                    item_id = str(item.get("id") or "").strip()
                    if item_id:
                        upserted_by_id[item_id] = dict(item)
                    else:
                        upserted_store_skills.append(dict(item))
                staging_runs.extend([dict(item) for item in list(payload.get("staging_runs") or []) if isinstance(item, dict)])
                tree = dict(payload.get("visible_tree") or {})
                if str(tree.get("store_root") or "").strip():
                    visible_tree["store_root"] = str(tree.get("store_root") or "").strip()
                if str(tree.get("library_manifest_path") or "").strip():
                    visible_tree["library_manifest_path"] = str(tree.get("library_manifest_path") or "").strip()
                if str(tree.get("readme_path") or "").strip():
                    visible_tree["readme_path"] = str(tree.get("readme_path") or "").strip()
                for key in ("affected_families", "parent_paths", "child_paths"):
                    visible_lists[key].update(str(item or "").strip() for item in list(tree.get(key) or []) if str(item or "").strip())
                dry_run = dry_run or bool(payload.get("dry_run"))
            for key, values in visible_lists.items():
                visible_tree[key] = sorted(values)
            upserted_store_skills.extend(list(upserted_by_id.values()))
            return VersionRegistrationResult(
                documents=list(document_by_id.values()),
                support_records=list(support_by_id.values()),
                skill_specs=list(skill_by_id.values()),
                hierarchy_updates=list(hierarchy_by_id.values()),
                lifecycles=lifecycles,
                change_logs=change_logs,
                version_history=version_history,
                provenance_links=provenance_links,
                upserted_store_skills=upserted_store_skills,
                staging_runs=staging_runs,
                visible_tree=visible_tree,
                errors=errors,
                dry_run=dry_run,
            )
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                documents = [DocumentRecord.from_dict(item) for item in list(payload.get("documents") or []) if isinstance(item, dict)]
                support_records = [SupportRecord.from_dict(item) for item in list(payload.get("support_records") or []) if isinstance(item, dict)]
                skill_specs = [SkillSpec.from_dict(item) for item in list(payload.get("skill_specs") or []) if isinstance(item, dict)]
                hierarchy_updates = [SkillSpec.from_dict(item) for item in list(payload.get("hierarchy_updates") or []) if isinstance(item, dict)]
                lifecycles = [SkillLifecycle.from_dict(item) for item in list(payload.get("lifecycles") or []) if isinstance(item, dict)]
                change_logs = [dict(item) for item in list(payload.get("change_logs") or []) if isinstance(item, dict)]
                version_history = [dict(item) for item in list(payload.get("version_history") or []) if isinstance(item, dict)]
                provenance_links = [dict(item) for item in list(payload.get("provenance_links") or []) if isinstance(item, dict)]
                upserted_store_skills = [dict(item) for item in list(payload.get("upserted_store_skills") or []) if isinstance(item, dict)]
                staging_runs = [dict(item) for item in list(payload.get("staging_runs") or []) if isinstance(item, dict)]
                visible_tree = dict(payload.get("visible_tree") or {})
                dry_run = bool(payload.get("dry_run"))
                errors = [{"stage": "intermediate_register_load", **item} for item in list(payload.get("errors") or []) if isinstance(item, dict)]
        except Exception as exc:
            errors.append({"stage": "intermediate_register_load", "path": path, "error": str(exc)})
        return VersionRegistrationResult(
            documents=documents,
            support_records=support_records,
            skill_specs=skill_specs,
            hierarchy_updates=hierarchy_updates,
            lifecycles=lifecycles,
            change_logs=change_logs,
            version_history=version_history,
            provenance_links=provenance_links,
            upserted_store_skills=upserted_store_skills,
            staging_runs=staging_runs,
            visible_tree=visible_tree,
            errors=errors,
            dry_run=dry_run,
        )

    def record_run_outcome(
        self,
        *,
        status: str,
        completed_doc_ids: Optional[Sequence[str]] = None,
        unresolved_doc_ids: Optional[Sequence[str]] = None,
        unresolved_nodes: Optional[Sequence[str]] = None,
        reused_nodes: Optional[Sequence[str]] = None,
    ) -> None:
        """Updates machine-readable run outcome fields without finalizing status."""

        self._state["completed_doc_ids"] = self._normalize_node_list(completed_doc_ids)
        self._state["unresolved_doc_ids"] = self._normalize_node_list(unresolved_doc_ids)
        self._state["unresolved_nodes"] = self._normalize_node_list(unresolved_nodes)
        if reused_nodes is not None:
            self._merge_reused_nodes(reused_nodes)
        self._state["status"] = str(status or "").strip() or str(self._state.get("status") or "running")
        self._state["updated_at"] = now_iso()
        self._flush_state()

    def add_reused_nodes(self, nodes: Optional[Sequence[str]] = None) -> None:
        """Appends reused node ids to the persisted run state."""

        self._merge_reused_nodes(nodes)
        self._state["updated_at"] = now_iso()
        self._flush_state()

    def complete(self, *, summary: Optional[Dict[str, Any]] = None) -> None:
        """Marks the intermediate run as completed and optionally writes a summary."""

        if summary:
            self._write_json("final/summary.json", dict(summary or {}))
        self._state["status"] = "completed"
        self._state["updated_at"] = now_iso()
        self._flush_state()

    def mark_partial(self, *, summary: Optional[Dict[str, Any]] = None) -> None:
        """Marks the intermediate run as partial and optionally writes a summary."""

        if summary:
            self._write_json("final/summary.json", dict(summary or {}))
        self._state["status"] = "partial"
        self._state["updated_at"] = now_iso()
        self._flush_state()

    def fail(self, *, error: str, summary: Optional[Dict[str, Any]] = None) -> None:
        """Marks the intermediate run as failed."""

        if summary:
            self._write_json("final/summary.json", dict(summary or {}))
        self._state["status"] = "failed"
        self._state["updated_at"] = now_iso()
        self._state["last_error"] = str(error or "").strip()
        self._flush_state()

    def has_completed_stage(self, stage: str) -> bool:
        """Returns whether one stage was already completed in this run."""

        return str(stage or "").strip() in {str(item or "").strip() for item in list(self._state.get("completed_stages") or [])}

    def _write_json(self, relative_path: str, payload: Any) -> str:
        path = os.path.join(self.run_dir, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False)
        if path not in self._files:
            self._files.append(path)
        self._state["updated_at"] = now_iso()
        self._flush_state()
        return path

    def _set_stage(
        self,
        *,
        stage: str,
        completed_stage: str = "",
        source_file: str = "",
        counts: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._state["current_stage"] = str(stage or "").strip() or self._state.get("current_stage") or "initialized"
        if completed_stage:
            existing = list(self._state.get("completed_stages") or [])
            if completed_stage not in existing:
                existing.append(completed_stage)
            self._state["completed_stages"] = existing
        if source_file:
            self._state["source_file"] = str(source_file or "").strip()
        if counts:
            merged = dict(self._state.get("counts") or {})
            merged.update(dict(counts or {}))
            self._state["counts"] = merged
        self._state["updated_at"] = now_iso()
        self._flush_state()

    def _flush_state(self) -> None:
        os.makedirs(os.path.dirname(self.status_path), exist_ok=True)
        with open(self.status_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2, sort_keys=False)
