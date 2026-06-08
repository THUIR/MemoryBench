import os
import sys
from typing import Dict, List, Literal, Optional, Union

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
        default=5,
        description="Number of AutoSkill skills to retrieve for each test query.",
    )
    user_id: str = Field(
        default="memorybench",
        description="User id used by AutoSkill's user-scoped SkillBank.",
    )
    skill_scope: Literal["user", "library", "all"] = Field(
        default="user",
        description="Retrieval scope. Off-policy baseline defaults to train-derived user skills only.",
    )
    min_score: float = Field(
        default=0.0,
        description="Minimum retrieval score for skills injected into the prompt.",
    )
    max_context_chars: int = Field(
        default=6000,
        description="Maximum AutoSkill context size injected into the answer prompt.",
    )
    ingest_window: int = Field(
        default=0,
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


class AutoSkillAgent(BaseAgent):
    def __init__(self, config: AutoSkillAgentConfig = AutoSkillAgentConfig()):
        self.config = config
        self.llm = LlmFactory.create(
            provider_name=config.llm_provider,
            config=config.llm_config,
        )
        os.makedirs(config.memory_cache_dir, exist_ok=True)
        self.skillbank_dir = os.path.join(config.memory_cache_dir, "SkillBank")

        store_config = dict(
            config.autoskill_store_config
            or {
                "provider": "local",
                "path": self.skillbank_dir,
                "include_libraries": False,
            }
        )
        store_config.setdefault("provider", "local")
        store_config.setdefault("path", self.skillbank_dir)

        autoskill_config = AutoSkillConfig(
            llm=_to_autoskill_llm_config(
                config.llm_provider,
                config.llm_config,
                config.autoskill_llm_config,
            ),
            embeddings=dict(config.autoskill_embeddings_config or {"provider": "hashing", "dims": 256}),
            store=store_config,
            maintenance_strategy=str(config.maintenance_strategy or "llm"),
            dedupe_similarity_threshold=float(config.dedupe_similarity_threshold),
            default_search_limit=int(config.retrieve_k),
            max_context_chars=int(config.max_context_chars),
            bm25_weight=float(config.bm25_weight),
        )
        self.sdk = AutoSkill(autoskill_config)

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
        return self.sdk.ingest(
            user_id=self.config.user_id,
            messages=normalized,
            metadata={
                "channel": "memorybench_off_policy",
                "conversation_idx": str(conversation_idx),
            },
        )

    def retrieve_memory(self, content: str, k: int = None):
        limit = int(k or self.config.retrieve_k)
        hits = self.sdk.search(
            str(content or ""),
            user_id=self.config.user_id,
            limit=limit,
            scope=self.config.skill_scope,
        )
        return [h for h in hits if float(getattr(h, "score", 0.0) or 0.0) >= self.config.min_score]

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
        hits = self.retrieve_memory(question, k=retrieve_k)
        context = ""
        if hits:
            context = self.sdk.render_context(
                question,
                user_id=self.config.user_id,
                limit=int(retrieve_k or self.config.retrieve_k),
                scope=self.config.skill_scope,
                filters={"ids": [h.skill.id for h in hits]},
            )

        if lang == "en":
            user_prompt = f"""AutoSkill context:
{context}

User:
{question}

Use the AutoSkill context only when it is relevant. Respond naturally and appropriately to the user's input above."""
        elif lang == "zh":
            user_prompt = f"""AutoSkill 记忆技能：
{context}

用户输入：
{question}

仅在 AutoSkill 技能与当前问题相关时使用它。请准确、自然地回答用户的输入。"""
        else:
            user_prompt = f"{context}\n\nUser:\n{question}"

        messages[-1]["content"] = user_prompt
        return self.llm.generate_response(messages=messages)

    def delete_memory(self, doc_id: str):
        raise NotImplementedError("AutoSkill does not delete memory by MemoryBench doc_id.")

    def clear_all_memories(self):
        raise NotImplementedError("AutoSkill cache clearing is managed by the runner cache directory.")
