"""
Offline conversation extraction from OpenAI-format datasets.
"""

from __future__ import annotations

import argparse
import copy
import os
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, List, Optional

from autoskill import AutoSkill, AutoSkillConfig
from autoskill.utils.skill_resources import extract_resource_paths_from_files
from .file_loader import load_openai_units
from .prompt_runtime import activate_offline_prompt_runtime
from .skill_normalizer import extract_examples_from_instruction, normalize_instruction_body
from .provenance_store import (
    ConversationProvenanceStore,
    conversation_provenance_path,
)
from .requirement_memory import (
    RequirementStatsStore,
    extract_user_requirements,
    infer_requirement_llm,
    refine_candidate_by_requirement_policy,
    requirement_stats_path,
    resolve_lineage_key,
)
from ..provider_config import (
    build_embeddings_config as _build_provider_embeddings_config,
    build_llm_config as _build_provider_llm_config,
    pick_default_provider as _pick_default_provider,
)
from .utils.ban_mock import ensure_llm_config_not_mock, ensure_not_mock


def _normalize_extract_mode(mode: Any) -> str:
    """Normalize extract prompt mode."""
    s = str(mode or "").strip().lower()
    if not s:
        return "specific"
    if s not in {"common", "specific"}:
        raise ValueError(f"extract_mode must be one of: common, specific (got {mode!r})")
    return s


def _offline_extract_channel(*, extract_mode: Any) -> str:
    """Build offline extract prompt channel with optional mode suffix."""
    mode = _normalize_extract_mode(extract_mode)
    if mode == "specific":
        return "offline_extract_from_conversation"
    return f"offline_extract_from_conversation:{mode}"


def extract_from_conversation(
    *,
    sdk: AutoSkill,
    user_id: str,
    data: Optional[Any] = None,
    file_path: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    hint: Optional[str] = None,
    continue_on_error: bool = True,
    max_messages_per_conversation: int = 0,
    max_workers: int = 0,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    extract_mode: str = "specific",
) -> Dict[str, Any]:
    """
    Runs offline extraction from archived OpenAI-format conversations.
    """

    units, abs_input = load_openai_units(data=data, file_path=file_path)
    if not units:
        return {
            "total_conversations": 0,
            "processed": 0,
            "failed": 0,
            "upserted_count": 0,
            "skills": [],
            "errors": [],
            "source_file": abs_input or None,
        }

    user = str(user_id or "").strip() or "u1"
    channel = _offline_extract_channel(extract_mode=extract_mode)
    limit_msgs = max(0, int(max_messages_per_conversation or 0))
    base_md = dict(metadata or {})
    base_md.setdefault("channel", channel)
    base_md.setdefault("source_type", "conversation")
    if abs_input:
        base_md.setdefault("source_file", abs_input)

    processed = 0
    failed = 0
    errors: List[Dict[str, Any]] = []
    upserted_by_id: Dict[str, Any] = {}
    req_llm = infer_requirement_llm(sdk)
    req_stats = RequirementStatsStore(
        path=requirement_stats_path(sdk=sdk, user_id=user),
        user_id=user,
    )
    provenance_store = ConversationProvenanceStore(
        path=conversation_provenance_path(sdk=sdk, user_id=user),
        user_id=user,
    )
    worker_count = _resolve_max_workers(max_workers=max_workers, total_units=len(units))
    unit_infos = [_unit_info(unit=unit, index=idx) for idx, unit in enumerate(units)]

    with activate_offline_prompt_runtime(sdk=sdk, channel=channel):
        # Parallelize LLM-bound extraction work, but keep apply/merge serial and ordered.
        # This preserves deterministic merge/version behavior for the local skill bank.
        prepared_by_index: Dict[int, Dict[str, Any]] = {}
        next_apply_idx = 0
        future_map: Dict[Future, int] = {}
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="autoskill-offline-conv",
        ) as pool:
            next_submit_idx = 0
            while next_submit_idx < len(units) and len(future_map) < worker_count:
                future_map[
                    pool.submit(
                        _prepare_conversation_unit,
                        sdk=sdk,
                        user_id=user,
                        unit=units[next_submit_idx],
                        index=next_submit_idx,
                        base_md=base_md,
                        limit_msgs=limit_msgs,
                        hint=hint,
                        req_llm=req_llm,
                    )
                ] = next_submit_idx
                next_submit_idx += 1

            while future_map:
                done, _pending = wait(set(future_map.keys()), return_when=FIRST_COMPLETED)
                for fut in done:
                    idx = int(future_map.pop(fut))
                    if next_submit_idx < len(units):
                        future_map[
                            pool.submit(
                                _prepare_conversation_unit,
                                sdk=sdk,
                                user_id=user,
                                unit=units[next_submit_idx],
                                index=next_submit_idx,
                                base_md=base_md,
                                limit_msgs=limit_msgs,
                                hint=hint,
                                req_llm=req_llm,
                            )
                        ] = next_submit_idx
                        next_submit_idx += 1
                    info = unit_infos[idx]
                    try:
                        prepared = fut.result()
                    except Exception as e:
                        prepared = {
                            "index": idx,
                            "status": "error",
                            "error": str(e),
                            "file_name": info["file_name"],
                            "file_path": info["file_path"],
                        }
                    prepared_by_index[idx] = prepared

                while next_apply_idx in prepared_by_index:
                    item = prepared_by_index.pop(next_apply_idx)
                    info2 = unit_infos[next_apply_idx]
                    next_apply_idx += 1
                    if str(item.get("status") or "") == "error":
                        failed += 1
                        errors.append({"index": int(item.get("index", info2["index"])), "error": str(item.get("error") or "")})
                        if progress_callback is not None:
                            progress_callback(
                                {
                                    "index": int(item.get("index", info2["index"])),
                                    "total": int(len(units)),
                                    "file_name": str(item.get("file_name") or info2["file_name"]),
                                    "file_path": item.get("file_path") or info2["file_path"],
                                    "status": "error",
                                    "error": str(item.get("error") or "unknown error"),
                                    "skills": [],
                                }
                            )
                        if not continue_on_error:
                            raise RuntimeError(str(item.get("error") or "offline conversation extraction failed"))
                        continue

                    idx2 = int(item["index"])
                    try:
                        candidate_count = len(list(item.get("candidates") or []))
                        updated = _apply_candidates_with_requirement_policy(
                            sdk=sdk,
                            user_id=user,
                            metadata=dict(item.get("metadata") or {}),
                            candidates=list(item.get("candidates") or []),
                            requirements=list(item.get("requirements") or []),
                            source_ref=dict(item.get("source_ref") or {}),
                            llm=req_llm,
                            req_stats=req_stats,
                            provenance_store=provenance_store,
                        )
                        processed += 1
                        for s in (updated or []):
                            sid = str(getattr(s, "id", "") or "")
                            if sid:
                                upserted_by_id[sid] = s
                        if progress_callback is not None:
                            progress_callback(
                                {
                                        "index": idx2,
                                        "total": int(len(units)),
                                        "file_name": str(item.get("file_name") or info2["file_name"]),
                                        "file_path": item.get("file_path") or info2["file_path"],
                                        "status": ("ok" if updated else "no_skill"),
                                        "candidate_count": int(candidate_count),
                                        "skills": _skills_compact_list(updated),
                                    }
                                )
                    except Exception as e:
                        failed += 1
                        errors.append({"index": idx2, "error": str(e)})
                        if progress_callback is not None:
                            progress_callback(
                                {
                                    "index": idx2,
                                    "total": int(len(units)),
                                    "file_name": str(item.get("file_name") or info2["file_name"]),
                                    "file_path": item.get("file_path") or info2["file_path"],
                                    "status": "error",
                                    "error": str(e),
                                    "skills": [],
                                }
                            )
                        if not continue_on_error:
                            raise

    try:
        req_stats.save()
    except Exception:
        pass
    try:
        provenance_store.save()
    except Exception:
        pass

    return {
        "total_conversations": len(units),
        "processed": processed,
        "failed": failed,
        "upserted_count": len(upserted_by_id),
        "skills": [_skill_to_plain_dict(s, provenance_store=provenance_store) for s in upserted_by_id.values()],
        "errors": errors,
        "source_file": abs_input or None,
        "requirement_stats": req_stats.summary(),
        "conversation_provenance": provenance_store.summary(),
    }


def _unit_info(*, unit: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Run unit info."""
    unit_source_file = str(unit.get("source_file") or "").strip()
    unit_title = str(unit.get("title") or "").strip() or f"conversation_{index + 1}"
    file_name = os.path.basename(unit_source_file) if unit_source_file else unit_title
    return {
        "index": int(index),
        "file_name": file_name,
        "file_path": (unit_source_file or None),
    }


def _prepare_conversation_unit(
    *,
    sdk: AutoSkill,
    user_id: str,
    unit: Dict[str, Any],
    index: int,
    base_md: Dict[str, Any],
    limit_msgs: int,
    hint: Optional[str],
    req_llm: Any,
) -> Dict[str, Any]:
    """Run prepare conversation unit."""
    info = _unit_info(unit=unit, index=index)
    unit_messages = list(unit.get("messages") or [])
    if not unit_messages:
        raise ValueError("empty openai messages")

    window = list(unit_messages[-limit_msgs:]) if limit_msgs > 0 else list(unit_messages)
    user_questions = _collect_user_questions(window)
    if not window:
        raise ValueError("empty conversation after normalization")

    md = dict(base_md)
    md["import_index"] = int(index)
    md["conversation_index"] = int(unit.get("conversation_index", 0))
    unit_source_file = str(unit.get("source_file") or "").strip()
    if unit_source_file:
        md["source_file"] = unit_source_file

    reqs = extract_user_requirements(
        user_questions=user_questions,
        llm=req_llm,
        max_items=12,
    )
    candidates = sdk.extract_candidates(
        user_id=user_id,
        messages=window,
        events=None,
        hint=(str(hint).strip() if hint and str(hint).strip() else None),
        max_candidates=1,
        retrieved_reference=None,
    )
    candidates = _normalize_candidates(candidates)
    return {
        "index": int(index),
        "status": "ready",
        "file_name": info["file_name"],
        "file_path": info["file_path"],
        "metadata": md,
        "requirements": reqs,
        "source_ref": _build_source_ref(
            unit=unit,
            index=index,
            messages=window,
            user_questions=user_questions,
        ),
        "candidates": candidates,
        "candidate_count": int(len(candidates or [])),
    }


def _collect_user_questions(messages: List[Dict[str, str]]) -> str:
    """Run collect user questions."""
    parts: List[str] = []
    for m in list(messages or []):
        role = str(m.get("role") or "").strip().lower()
        if role != "user":
            continue
        txt = str(m.get("content") or "").strip()
        if not txt:
            continue
        parts.append(txt)
    if not parts:
        return "(none)"
    return "\n\n".join(parts)


def _normalize_candidates(candidates: List[Any]) -> List[Any]:
    """Normalizes offline extracted candidate bodies without touching core autoskill code."""
    out: List[Any] = []
    for cand in list(candidates or []):
        try:
            name = str(getattr(cand, "name", "") or "").strip()
            desc = str(getattr(cand, "description", "") or "").strip()
            raw_instr = str(getattr(cand, "instructions", "") or "").strip()
            examples = extract_examples_from_instruction(raw_instr)
            instr = normalize_instruction_body(
                raw_instr,
                skill_name=name,
                skill_description=desc or name,
            )
            if not instr:
                continue
            setattr(cand, "instructions", instr)
            if examples:
                setattr(cand, "examples", examples)
            out.append(cand)
        except Exception:
            out.append(cand)
    return out


def _format_full_conversation(messages: List[Dict[str, str]]) -> str:
    """Run format full conversation."""
    out: List[str] = []
    for m in list(messages or []):
        role = str(m.get("role") or "").strip().lower() or "user"
        txt = str(m.get("content") or "").strip()
        if not txt:
            continue
        out.append(f"[{role}] {txt}")
    return "\n\n".join(out).strip() or "(empty)"


def _skill_to_plain_dict(skill: Any, *, provenance_store: Optional[ConversationProvenanceStore] = None) -> Dict[str, Any]:
    """Run skill to plain dict."""
    try:
        examples = []
        files = dict(getattr(skill, "files", {}) or {})
        for e in list(getattr(skill, "examples", []) or []):
            examples.append(
                {
                    "input": str(getattr(e, "input", "") or ""),
                    "output": (str(getattr(e, "output", "") or "") or None),
                    "notes": (str(getattr(e, "notes", "") or "") or None),
                }
            )
        out = {
            "id": str(getattr(skill, "id", "") or ""),
            "name": str(getattr(skill, "name", "") or ""),
            "description": str(getattr(skill, "description", "") or ""),
            "instructions": str(getattr(skill, "instructions", "") or ""),
            "prompt": str(getattr(skill, "instructions", "") or ""),
            "version": str(getattr(skill, "version", "") or ""),
            "triggers": list(getattr(skill, "triggers", []) or []),
            "tags": list(getattr(skill, "tags", []) or []),
            "examples": examples,
            "resource_paths": extract_resource_paths_from_files(files, max_items=32),
            "files": {str(k): str(v) for k, v in files.items() if str(k or "").strip() and str(k) != "SKILL.md"},
        }
        if provenance_store is not None:
            out["conversation_provenance"] = provenance_store.get_skill_record(
                skill_id=str(getattr(skill, "id", "") or ""),
                max_sources=20,
                max_history=20,
            )
        return out
    except Exception:
        return {"id": "", "name": "", "description": "", "version": ""}


def _skills_compact_list(skills: Any) -> List[Dict[str, str]]:
    """Run skills compact list."""
    out: List[Dict[str, str]] = []
    seen = set()
    for s in list(skills or []):
        sid = str(getattr(s, "id", "") or "").strip()
        name = str(getattr(s, "name", "") or "").strip()
        key = (sid, name)
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": sid, "name": name})
    return out


def _build_source_ref(
    *,
    unit: Dict[str, Any],
    index: int,
    messages: List[Dict[str, str]],
    user_questions: str,
) -> Dict[str, Any]:
    """Builds one compact source reference for provenance indexing."""

    source_file = str(unit.get("source_file") or "").strip()
    title = str(unit.get("title") or "").strip() or f"conversation_{int(index) + 1}"
    conv_idx = int(unit.get("conversation_index", index) or index)
    user_turn_count = 0
    for m in list(messages or []):
        if str(m.get("role") or "").strip().lower() == "user":
            user_turn_count += 1
    file_name = os.path.basename(source_file) if source_file else title
    locator = f"{file_name}#conv_{conv_idx + 1}"
    return {
        "source_file": source_file,
        "conversation_index": conv_idx,
        "import_index": int(index),
        "title": title,
        "locator": locator,
        "message_count": int(len(list(messages or []))),
        "user_turn_count": int(user_turn_count),
        "primary_user_questions_preview": str(user_questions or "").strip(),
    }


def _apply_candidates_with_requirement_policy(
    *,
    sdk: AutoSkill,
    user_id: str,
    metadata: Dict[str, Any],
    candidates: List[Any],
    requirements: List[Dict[str, str]],
    source_ref: Dict[str, Any],
    llm: Any,
    req_stats: RequirementStatsStore,
    provenance_store: ConversationProvenanceStore,
) -> List[Any]:
    """
    Applies candidate updates with offline requirement-memory policy.

    Flow:
    1) resolve candidate lineage
    2) update requirement counters with LLM-assisted requirement matching
    3) refine candidate by keep/drop policy
    4) apply maintainer update
    """

    out: List[Any] = []
    for cand in list(candidates or []):
        stats_before = copy.deepcopy(req_stats.data)
        lineage_key = resolve_lineage_key(
            sdk=sdk,
            user_id=user_id,
            candidate=cand,
            min_score=0.40,
        )
        policy = req_stats.register_update(
            lineage_key=lineage_key,
            requirements=requirements,
            llm=llm,
        )
        cand2 = refine_candidate_by_requirement_policy(
            candidate=cand,
            policy=policy.to_dict(),
            llm=llm,
        )
        md2 = dict(metadata or {})
        md2["offline_requirement_lineage"] = str(lineage_key)
        md2["offline_requirement_policy"] = policy.to_dict()
        try:
            updated = sdk.maintainer.apply(
                [cand2],
                user_id=str(user_id or "").strip() or "u1",
                metadata=md2,
            )
        except Exception:
            req_stats.data = stats_before
            raise
        for skill in list(updated or []):
            try:
                provenance_store.record_skill_update(
                    skill=skill,
                    lineage_key=str(lineage_key),
                    source_ref=dict(source_ref or {}),
                )
                # Persist immediately so partially processed long imports still leave
                # a recoverable skill-to-conversation mapping on disk.
                provenance_store.save()
            except Exception:
                pass
        out.extend(list(updated or []))
    return out


def _env(name: str, default: str = "") -> str:
    """Run env."""
    val = os.getenv(name)
    return val if val is not None and val.strip() else default


def _resolve_max_workers(*, max_workers: int, total_units: int) -> int:
    """Run resolve max workers."""
    total = max(1, int(total_units or 0))
    raw = int(max_workers or 0)
    if raw > 0:
        return max(1, min(raw, total))
    cpu = max(1, int(os.cpu_count() or 1))
    return max(1, min(total, max(4, min(16, cpu * 2))))


def _parse_bool_text(v: Any, default: bool) -> bool:
    """Parse loose bool-like CLI/env text into a boolean."""
    if v is None:
        return bool(default)
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _build_llm_config(args: argparse.Namespace) -> Dict[str, Any]:
    """Run build llm config."""
    provider = str(args.llm_provider or _pick_default_provider()).strip() or "mock"
    ensure_not_mock(provider, where="extract:_build_llm_config(provider)")
    model = str(args.llm_model or "").strip() or None
    cfg = _build_provider_llm_config(provider, model=model)
    ensure_llm_config_not_mock(cfg, where="extract:_build_llm_config(cfg)")
    if str(args.llm_base_url or "").strip():
        cfg["base_url"] = str(args.llm_base_url).strip()
    if str(args.llm_api_key or "").strip():
        cfg["api_key"] = str(args.llm_api_key).strip()
    if str(args.auth_mode or "").strip():
        cfg["auth_mode"] = str(args.auth_mode).strip()
    return cfg


def _build_embeddings_config(args: argparse.Namespace) -> Dict[str, Any]:
    """Run build embeddings config."""
    llm_provider = str(args.llm_provider or "mock").strip().lower() or "mock"
    provider = str(args.embeddings_provider or "").strip()
    model = str(args.embeddings_model or "").strip() or None
    cfg = _build_provider_embeddings_config(provider, model=model, llm_provider=llm_provider)
    if str(args.embeddings_base_url or "").strip():
        cfg["base_url"] = str(args.embeddings_base_url).strip()
    if str(args.embeddings_api_key or "").strip():
        cfg["api_key"] = str(args.embeddings_api_key).strip()
    if str(args.embeddings_auth_mode or "").strip():
        cfg["auth_mode"] = str(args.embeddings_auth_mode).strip()
    dims = int(args.embeddings_dims or 0)
    provider_norm = str(cfg.get("provider") or "").strip().lower()
    if provider_norm == "hashing":
        cfg["dims"] = int(dims) if dims > 0 else 256
    elif dims > 0 and provider_norm != "none":
        cfg["dimensions"] = int(dims)
        cfg["extra_body"] = {"dimensions": int(dims)}
    return cfg


def _build_sdk_from_args(args: argparse.Namespace) -> AutoSkill:
    """Run build sdk from args."""
    llm_cfg = _build_llm_config(args)
    emb_cfg = _build_embeddings_config(args)
    store_cfg: Dict[str, Any] = {"provider": "local"}
    if str(args.store_path or "").strip():
        store_cfg["path"] = str(args.store_path).strip()
    return AutoSkill(
        AutoSkillConfig(
            llm=llm_cfg,
            embeddings=emb_cfg,
            store=store_cfg,
            extra={
                "raise_on_llm_extract_error": _parse_bool_text(
                    getattr(args, "strict_llm_errors", "1"),
                    True,
                )
            },
        )
    )


def build_parser() -> argparse.ArgumentParser:
    """Run build parser."""
    parser = argparse.ArgumentParser(
        description="Extract skills from OpenAI-format conversation JSON/JSONL files (or a directory of them)."
    )
    parser.add_argument("--file", required=True, help="Path to an OpenAI-format .json/.jsonl file or directory.")
    parser.add_argument("--user-id", default="u1", help="Target user id.")
    parser.add_argument("--hint", default="", help="Optional extraction hint.")
    parser.add_argument(
        "--extract-mode",
        default=_env("AUTOSKILL_OFFLINE_EXTRACT_MODE", "common"),
        help="Prompt mode for extract stage: common|specific. Default specific.",
    )
    parser.add_argument("--max-messages-per-conversation", type=int, default=0, help="0 means no clipping.")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=int(_env("AUTOSKILL_OFFLINE_MAX_WORKERS", "50") or 50),
        help="Parallel extraction workers. Default is 50; 0 means auto.",
    )
    parser.add_argument(
        "--strict-llm-errors",
        default=_env("AUTOSKILL_OFFLINE_STRICT_LLM_ERRORS", "1"),
        help="1|0. When enabled, LLM extract/repair failures surface as errors instead of silent empty skills.",
    )
    parser.add_argument(
        "--llm-provider",
        default=_env("AUTOSKILL_LLM_PROVIDER", _pick_default_provider()),
        help="mock|generic|glm|internlm|dashscope|openai|anthropic",
    )
    parser.add_argument("--llm-model", default=_env("AUTOSKILL_LLM_MODEL", ""), help="LLM model id.")
    parser.add_argument("--llm-base-url", default=_env("AUTOSKILL_LLM_BASE_URL", ""), help="LLM base URL.")
    parser.add_argument("--llm-api-key", default=_env("AUTOSKILL_LLM_API_KEY", ""), help="LLM API key.")
    parser.add_argument("--auth-mode", default=_env("AUTOSKILL_LLM_AUTH_MODE", ""), help="Optional auth mode.")
    parser.add_argument(
        "--embeddings-provider",
        default=_env("AUTOSKILL_EMBEDDINGS_PROVIDER", _env("AUTOSKILL_EMBEDDING_PROVIDER", "")),
        help="hashing|none|openai|generic|dashscope|glm",
    )
    parser.add_argument("--embeddings-model", default=_env("AUTOSKILL_EMBEDDINGS_MODEL", ""), help="Embedding model id.")
    parser.add_argument("--embeddings-base-url", default=_env("AUTOSKILL_EMBEDDINGS_BASE_URL", ""), help="Embedding base URL.")
    parser.add_argument("--embeddings-api-key", default=_env("AUTOSKILL_EMBEDDINGS_API_KEY", ""), help="Embedding API key.")
    parser.add_argument(
        "--embeddings-auth-mode",
        default=_env("AUTOSKILL_EMBEDDINGS_AUTH_MODE", ""),
        help="Optional embedding auth mode.",
    )
    parser.add_argument(
        "--embeddings-dims",
        type=int,
        default=int(_env("AUTOSKILL_EMBEDDINGS_DIMS", "0") or 0),
        help="Embedding dimension override (hashing uses dims; API providers use dimensions).",
    )
    parser.add_argument(
        "--store-path",
        default=_env("AUTOSKILL_STORE_PATH", ""),
        help="Optional local SkillBank path. Empty means config default.",
    )
    return parser


def main() -> None:
    """Run main."""
    args = build_parser().parse_args()
    extract_mode = _normalize_extract_mode(getattr(args, "extract_mode", "specific"))
    sdk = _build_sdk_from_args(args)
    llm_provider = str(((getattr(sdk, "config", None) or AutoSkillConfig()).llm or {}).get("provider") or "mock")
    llm_model = str(((getattr(sdk, "config", None) or AutoSkillConfig()).llm or {}).get("model") or "")
    ensure_not_mock(llm_provider, where="extract:main(sdk.config.llm.provider)")
    print(
        f"[config] llm_provider={llm_provider} "
        f"llm_model={llm_model or '-'} "
        f"extract_mode={extract_mode} "
        f"max_workers={int(args.max_workers or 0)} "
        f"strict_llm_errors={_parse_bool_text(args.strict_llm_errors, True)}",
        flush=True,
    )

    def _on_progress(evt: Dict[str, Any]) -> None:
        """Run on progress."""
        idx = int(evt.get("index", 0)) + 1
        total = int(evt.get("total", 0))
        fname = str(evt.get("file_name") or "")
        status = str(evt.get("status") or "ok")
        if status == "error":
            err = str(evt.get("error") or "unknown error")
            print(f"[{idx}/{total}] {fname} -> ERROR: {err}", flush=True)
            return
        skills = list(evt.get("skills") or [])
        if not skills:
            cand_n = int(evt.get("candidate_count", 0) or 0)
            if cand_n <= 0:
                print(f"[{idx}/{total}] {fname} -> no candidate extracted", flush=True)
            else:
                print(f"[{idx}/{total}] {fname} -> candidate discarded during maintenance", flush=True)
            return
        names = [str(x.get("name") or "").strip() for x in skills if str(x.get("name") or "").strip()]
        if not names:
            print(f"[{idx}/{total}] {fname} -> skills: {len(skills)}", flush=True)
            return
        print(f"[{idx}/{total}] {fname} -> skills: {', '.join(names)}", flush=True)

    result = extract_from_conversation(
        sdk=sdk,
        user_id=str(args.user_id).strip() or "u1",
        file_path=str(args.file),
        hint=(str(args.hint).strip() or None),
        continue_on_error=True,
        max_messages_per_conversation=int(args.max_messages_per_conversation or 0),
        max_workers=int(args.max_workers or 0),
        metadata={"channel": _offline_extract_channel(extract_mode=extract_mode)},
        progress_callback=_on_progress,
        extract_mode=extract_mode,
    )

    print("Offline conversation extraction completed.")
    print(
        f"conversations={result.get('total_conversations', 0)} "
        f"processed={result.get('processed', 0)} "
        f"failed={result.get('failed', 0)} "
        f"upserted={result.get('upserted_count', 0)}"
    )
    skills = list(result.get("skills") or [])
    for i, s in enumerate(skills, start=1):
        print(f"{i}. {s.get('name', '')} ({s.get('version', '')})")
    errors = list(result.get("errors") or [])
    if errors:
        print("Errors:")
        for e in errors[:20]:
            print(f"- #{e.get('index')}: {e.get('error')}")
    req_summary = dict(result.get("requirement_stats") or {})
    if req_summary:
        print(
            f"requirement_stats: lineages={req_summary.get('lineage_count', 0)} "
            f"path={req_summary.get('path', '')}"
        )
    prov_summary = dict(result.get("conversation_provenance") or {})
    if prov_summary:
        print(
            f"conversation_provenance: skills={prov_summary.get('skill_count', 0)} "
            f"path={prov_summary.get('path', '')}"
        )


if __name__ == "__main__":
    main()
