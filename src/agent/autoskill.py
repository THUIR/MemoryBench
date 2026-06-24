"""
AutoSkill adapted to MemoryBench with native extraction, retrieval, query rewriting, library retrieval, and context rendering.

The generic MemoryBench/off-policy `--retrieve_k` argument is intentionally ignored by AutoSkill;
use the AutoSkill config JSON to change retrieval settings or run ablations.
"""

import os
import sys
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from src.agent.base_agent import BaseAgent
from src.llms import LlmFactory


def _autoskill_repo_root() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    memorybench_root = os.path.abspath(os.path.join(here, os.pardir, os.pardir))
    return os.path.join(memorybench_root, "baselines", "AutoSkill")


AUTOSKILL_ROOT = _autoskill_repo_root()
if AUTOSKILL_ROOT not in sys.path:
    sys.path.insert(0, AUTOSKILL_ROOT)

from autoskill import AutoSkill, AutoSkillConfig  # noqa: E402
from autoskill.interactive.app import _top_reference_from_hits  # noqa: E402
from autoskill.interactive.retrieval import retrieve_hits_by_scope  # noqa: E402
from autoskill.interactive.rewriting import LLMQueryRewriter  # noqa: E402
from autoskill.llm.factory import build_llm  # noqa: E402
from autoskill.render import _render_one, render_skills_context, select_skills_for_context  # noqa: E402


def _autoskill_default_common_skillbank() -> str:
    return os.path.join(AUTOSKILL_ROOT, "SkillBank", "Common")


class AutoSkillAgentConfig(BaseModel):
    llm_provider: Literal["openai", "vllm", "anthropic"] = Field(
        default="openai",
        description="The LLM provider to use for final answer generation.",
    )
    llm_config: dict = Field(
        default_factory=dict,
        description="Configuration parameters for final answer generation.",
    )
    memory_cache_dir: str = Field(
        default="./autoskill_cache",
        description="Directory where AutoSkill writes its SkillBank cache.",
    )
    retrieve_k: int = Field(
        default=1,
        description="Number of AutoSkill skills to retrieve for each test query. AutoSkill interactive default is 1.",
    )
    user_id: str = Field(
        default="memorybench",
        description="User id used by AutoSkill's user-scoped SkillBank.",
    )
    skill_scope: Literal["user", "library", "all"] = Field(
        default="all",
        description="Retrieval scope. AutoSkill interactive default is all.",
    )
    min_score: float = Field(
        default=0.4,
        description="Minimum retrieval score for skills injected into the prompt. AutoSkill interactive default is 0.4.",
    )
    max_context_chars: int = Field(
        default=6000,
        description="Maximum AutoSkill context size injected into the answer prompt.",
    )
    ingest_window: int = Field(
        default=6,
        description="If >0, keep only the latest N messages of each training dialog for extraction.",
    )
    autoskill_llm_config: Optional[dict] = Field(
        default=None,
        description="AutoSkill extractor/maintainer LLM config. Defaults to llm_config mapped to generic.",
    )
    autoskill_embeddings_config: dict = Field(
        default_factory=lambda: {"provider": "hashing", "dims": 256},
        description="AutoSkill retrieval embedding config.",
    )
    autoskill_store_config: Optional[dict] = Field(
        default=None,
        description="AutoSkill store config. Defaults to local SkillBank under memory_cache_dir.",
    )
    maintenance_strategy: str = Field(
        default="llm",
        description="AutoSkill maintenance strategy.",
    )
    dedupe_similarity_threshold: float = Field(
        default=0.4,
        description="AutoSkill add/merge/discard similarity threshold.",
    )
    bm25_weight: float = Field(
        default=0.1,
        description="Hybrid retrieval BM25 weight inside AutoSkill.",
    )
    include_libraries: Optional[bool] = Field(
        default=None,
        description="Whether to load AutoSkill shared libraries. Defaults to True when skill_scope is all/library.",
    )
    rewrite_mode: Literal["auto", "always", "never"] = Field(
        default="always",
        description="AutoSkill interactive retrieval query rewriting mode.",
    )
    rewrite_history_turns: int = Field(
        default=6,
        description="Recent turns used by AutoSkill's query rewriter.",
    )
    rewrite_history_chars: int = Field(
        default=2000,
        description="Maximum history units used by AutoSkill's query rewriter.",
    )
    rewrite_max_query_chars: int = Field(
        default=256,
        description="Maximum units in the rewritten retrieval query.",
    )


def _to_autoskill_llm_config(
    provider: str,
    llm_config: Dict,
    override: Optional[Dict],
) -> Dict:
    if override:
        return dict(override)

    cfg = dict(llm_config or {})
    provider = str(provider or "").strip().lower()
    try:
        timeout_s = int(float(cfg.get("timeout_s") or os.getenv("LLM_REQUEST_TIMEOUT", 180)))
    except (TypeError, ValueError):
        timeout_s = 180
    if provider == "vllm":
        return {
            "provider": "generic",
            "model": cfg.get("model"),
            "base_url": cfg.get("vllm_base_url"),
            "api_key": cfg.get("api_key") or os.getenv("VLLM_API_KEY") or "vllm-api-key",
            "timeout_s": timeout_s,
            "max_tokens": int(cfg.get("max_tokens", 30000)),
        }
    if provider == "openai":
        return {
            "provider": "openai",
            "model": cfg.get("model", "gpt-4o-mini"),
            "api_key": cfg.get("api_key") or os.getenv("OPENAI_API_KEY"),
            "base_url": cfg.get("base_url", "https://api.openai.com"),
            "timeout_s": timeout_s,
            "max_tokens": int(cfg.get("max_tokens", 30000)),
        }
    if provider == "anthropic":
        return {
            "provider": "anthropic",
            "model": cfg.get("model", "claude-3-5-sonnet-latest"),
            "api_key": cfg.get("api_key") or os.getenv("ANTHROPIC_API_KEY"),
            "base_url": cfg.get("base_url", "https://api.anthropic.com"),
            "timeout_s": timeout_s,
            "max_tokens": int(cfg.get("max_tokens", 30000)),
        }
    return {"provider": "mock"}


def _normalize_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant", "tool"}:
            role = "user"
        content = str(msg.get("content") or "").strip()
        if content:
            out.append({"role": role, "content": content})
    return out


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class AutoSkillAgent(BaseAgent):
    def __init__(self, config: AutoSkillAgentConfig = AutoSkillAgentConfig()):
        self.config = config
        self.llm = LlmFactory.create(
            provider_name=config.llm_provider,
            config=config.llm_config,
        )
        os.makedirs(config.memory_cache_dir, exist_ok=True)
        self.skillbank_dir = os.path.join(config.memory_cache_dir, "SkillBank")

        include_libraries = config.include_libraries
        if include_libraries is None:
            include_libraries = str(config.skill_scope or "").strip().lower() in {"all", "library"}

        store_config = dict(
            config.autoskill_store_config
            or {
                "provider": "local",
                "path": self.skillbank_dir,
                "include_libraries": bool(include_libraries),
            }
        )
        store_config.setdefault("provider", "local")
        store_config.setdefault("path", self.skillbank_dir)
        store_config.setdefault("include_libraries", bool(include_libraries))
        if include_libraries and not (store_config.get("library_dirs") or store_config.get("libraries")):
            common_skillbank = _autoskill_default_common_skillbank()
            if os.path.isdir(common_skillbank):
                store_config["library_dirs"] = [{"name": "Common", "path": common_skillbank}]

        autoskill_llm_config = _to_autoskill_llm_config(
            config.llm_provider,
            config.llm_config,
            config.autoskill_llm_config,
        )
        autoskill_config = AutoSkillConfig(
            llm=autoskill_llm_config,
            embeddings=dict(config.autoskill_embeddings_config or {"provider": "hashing", "dims": 256}),
            store=store_config,
            maintenance_strategy=str(config.maintenance_strategy or "llm"),
            dedupe_similarity_threshold=float(config.dedupe_similarity_threshold),
            default_search_limit=int(config.retrieve_k),
            max_context_chars=int(config.max_context_chars),
            bm25_weight=float(config.bm25_weight),
        )
        self.sdk = AutoSkill(autoskill_config)
        self.query_rewriter = None
        if str(config.rewrite_mode or "never").strip().lower() != "never":
            try:
                self.query_rewriter = LLMQueryRewriter(
                    build_llm(autoskill_llm_config),
                    max_history_turns=int(config.rewrite_history_turns),
                    max_history_chars=int(config.rewrite_history_chars),
                    max_query_chars=int(config.rewrite_max_query_chars),
                )
            except Exception:
                self.query_rewriter = None

    def _skill_artifact_path(self, skill) -> str:
        store = getattr(self.sdk, "store", None)
        records = getattr(store, "_records", {}) or {}
        rec = records.get(str(getattr(skill, "id", "") or ""))
        dir_path = getattr(rec, "dir_path", "") if rec is not None else ""
        if dir_path:
            path = os.path.join(dir_path, "SKILL.md")
            if os.path.exists(path):
                return path
        return ""

    def _skill_to_record(
        self,
        skill,
        *,
        score: Optional[float] = None,
        rank: Optional[int] = None,
        include_skill_md: bool = False,
        retrieved_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        artifact_path = self._skill_artifact_path(skill)
        skill_md = ""
        if include_skill_md:
            skill_md = (getattr(skill, "files", {}) or {}).get("SKILL.md", "")
            if not skill_md and artifact_path and os.path.exists(artifact_path):
                with open(artifact_path, "r", encoding="utf-8") as fin:
                    skill_md = fin.read()

        record = {
            "memory_type": "autoskill_skill",
            "id": str(getattr(skill, "id", "") or ""),
            "user_id": str(getattr(skill, "user_id", "") or ""),
            "name": str(getattr(skill, "name", "") or ""),
            "description": str(getattr(skill, "description", "") or ""),
            "version": str(getattr(skill, "version", "") or ""),
            "status": _json_safe(getattr(skill, "status", "")),
            "tags": list(getattr(skill, "tags", []) or []),
            "triggers": list(getattr(skill, "triggers", []) or []),
            "created_at": getattr(skill, "created_at", None),
            "updated_at": getattr(skill, "updated_at", None),
            "artifact_path": artifact_path,
        }
        if score is not None:
            record["score"] = float(score)
        if rank is not None:
            record["rank"] = int(rank)
        if retrieved_text is not None:
            record["retrieved_text"] = str(retrieved_text)
        if include_skill_md:
            record.update({
                "instructions": str(getattr(skill, "instructions", "") or ""),
                "source": _json_safe(getattr(skill, "source", None)),
                "metadata": _json_safe(getattr(skill, "metadata", {}) or {}),
                "skill_md": skill_md,
                "retrieved_text": str(retrieved_text or _render_one(skill, index=1, max_chars=None)),
            })
        return record

    def export_memory_records(self) -> List[Dict[str, Any]]:
        skills = self.sdk.store.list(user_id=self.config.user_id)
        skills = sorted(
            skills,
            key=lambda skill: (
                str(getattr(skill, "name", "") or ""),
                str(getattr(skill, "id", "") or ""),
            ),
        )
        return [self._skill_to_record(skill, include_skill_md=True) for skill in skills]

    def format_memory_records_text(self, records: List[Dict[str, Any]]) -> str:
        lines = [
            "# AutoSkill Memory Records",
            "",
            f"SkillBank: {self.skillbank_dir}",
            f"User: {self.config.user_id}",
            f"Total skills: {len(records)}",
            "",
        ]
        for idx, record in enumerate(records, start=1):
            title = record.get("name") or record.get("id") or f"skill_{idx}"
            lines.extend([
                f"## Skill {idx}: {title}",
                "",
                f"- id: {record.get('id', '')}",
                f"- version: {record.get('version', '')}",
                f"- artifact_path: {record.get('artifact_path', '')}",
                f"- description: {record.get('description', '')}",
                f"- tags: {', '.join(record.get('tags') or [])}",
                f"- triggers: {', '.join(record.get('triggers') or [])}",
                "",
                "### Retrieved Text",
                "",
                record.get("retrieved_text") or "",
                "",
                "### SKILL.md",
                "",
                record.get("skill_md") or record.get("instructions") or "",
                "",
            ])
        return "\n".join(lines).rstrip() + "\n"

    def _render_context_and_trace(self, question: str, hits) -> tuple[str, List[Dict[str, Any]]]:
        skills_for_use = [hit.skill for hit in hits if getattr(hit, "skill", None) is not None]
        selected = select_skills_for_context(
            skills_for_use,
            query=question,
            max_chars=int(self.config.max_context_chars),
        )
        selected_ids = {str(getattr(skill, "id", "") or "") for skill in selected}
        context = render_skills_context(
            selected,
            query=question,
            max_chars=int(self.config.max_context_chars),
        ) if selected else ""

        trace = []
        rank = 0
        for hit in hits:
            skill = getattr(hit, "skill", None)
            if skill is None or str(getattr(skill, "id", "") or "") not in selected_ids:
                continue
            rank += 1
            trace.append(self._skill_to_record(
                skill,
                score=float(getattr(hit, "score", 0.0) or 0.0),
                rank=rank,
                include_skill_md=False,
                retrieved_text=_render_one(skill, index=rank, max_chars=None).strip(),
            ))

        return context, trace

    def _rewrite_query(self, query: str, messages: Optional[List[Dict[str, str]]] = None) -> str:
        q = str(query or "").strip()
        if not q:
            return ""

        rewrite_mode = str(self.config.rewrite_mode or "never").strip().lower()
        if rewrite_mode == "never" or self.query_rewriter is None:
            return q
        if rewrite_mode not in {"auto", "always"}:
            return q
        return self.query_rewriter.rewrite(query=q, messages=_normalize_messages(messages or [])) or q

    def add_conversation_to_memory(
        self,
        messages: List[Dict[str, str]],
        conversation_idx: Union[int, str] = 0,
    ):
        normalized = _normalize_messages(messages)
        if self.config.ingest_window and self.config.ingest_window > 0:
            normalized = normalized[-int(self.config.ingest_window):]
        if not normalized:
            return []
        query = ""
        for msg in reversed(normalized):
            if str(msg.get("role") or "").strip().lower() == "user":
                query = str(msg.get("content") or "").strip()
                break
        hits = self.retrieve_memory(query, k=int(self.config.retrieve_k), messages=normalized) if query else []
        top_ref = _top_reference_from_hits(hits, user_id=self.config.user_id)
        return self.sdk.ingest(
            user_id=self.config.user_id,
            messages=normalized,
            metadata={
                "channel": "memorybench_off_policy",
                "conversation_idx": str(conversation_idx),
                "extraction_reference": top_ref,
            },
        )

    def retrieve_memory(self, content: str, k: int = None, messages: Optional[List[Dict[str, str]]] = None):
        query = self._rewrite_query(str(content or ""), messages) if messages is not None else str(content or "")
        limit = int(self.config.retrieve_k)
        retrieved = retrieve_hits_by_scope(
            sdk=self.sdk,
            query=query,
            user_id=self.config.user_id,
            scope=self.config.skill_scope,
            top_k=limit,
            min_score=float(self.config.min_score),
            allow_partial_vectors=False,
        )
        return list(retrieved.get("hits") or [])

    def save_memories(self):
        # LocalSkillStore persists every upsert immediately. This method exists for BaseSolver.
        return None

    def load_memories(self):
        # Rebuild the SDK so LocalSkillStore reloads SKILL.md artifacts from disk.
        self.__init__(self.config)

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        lang: Literal["en", "zh"] = "en",
        retrieve_k: int = None,
    ) -> str:
        question = messages[-1]["content"]
        search_query = self._rewrite_query(question, messages)
        hits = self.retrieve_memory(search_query, k=retrieve_k)
        context = ""
        if hits:
            context, trace = self._render_context_and_trace(search_query, hits)
            self.set_last_memory_trace(trace)
        else:
            self.set_last_memory_trace([])

        if lang == "en":
            user_prompt = f"""Skill context:
{context}

User:
{question}

Use the skill context only when it is relevant. Respond naturally and appropriately to the user's input above."""
        elif lang == "zh":
            user_prompt = f"""可用技能：
{context}

用户输入：
{question}

仅在技能与当前问题相关时使用它。请准确、自然地回答用户的输入。"""
        else:
            user_prompt = f"{context}\n\nUser:\n{question}"

        messages[-1]["content"] = user_prompt
        return self.llm.generate_response(messages=messages)

    def delete_memory(self, doc_id: str):
        raise NotImplementedError("AutoSkill does not delete memory by MemoryBench doc_id.")

    def clear_all_memories(self):
        raise NotImplementedError("AutoSkill cache clearing is managed by the runner cache directory.")
