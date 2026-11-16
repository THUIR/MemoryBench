import os
import json
import pickle
import hashlib
import logging
from pathlib import Path
import numpy as np
from typing import List, Dict, Literal, Union
from pydantic import BaseModel, Field

from src.llms import LlmFactory
from src.agent.base_agent import BaseAgent

from baselines.A_mem.memory_layer import AgenticMemorySystem, FAILURES, MEMORY_VERSION


UPSTREAM_COMMIT = "f9a173dec325d84fcc97e7828775c7b241c33466"
CACHE_VERSION = 2
logger = logging.getLogger(__name__)


class AMemAgentConfig(BaseModel):
    llm_provider: Literal["openai", "vllm"] = Field(
        default="openai", 
        description="The LLM provider to use for the agent inference."
    )
    llm_config: dict = Field(
        default_factory=dict, 
        description="Configuration parameters for the inference LLM."
    )
    retrieve_k: int = Field(
        default=10,
        description="Number of memories to retrieve for a given query."
    )
    memory_cache_dir: str = Field(
        default="./a-mem",
        description="Directory to store cached memory data.",
    )

class AMemAgent(BaseAgent):
    def __init__(self, config: AMemAgentConfig):
        self.config = config
        self.memory_cache_dir = config.memory_cache_dir
        llm_config = dict(config.llm_config)
        if config.llm_provider == "vllm":
            self.api_base = (llm_config.get("vllm_base_url") or
                             os.getenv("VLLM_BASE_URL") or "http://localhost:8000/v1")
            api_key = llm_config.get("api_key") or os.getenv("VLLM_API_KEY") or "EMPTY"
            llm_config["vllm_base_url"] = self.api_base
        else:
            self.api_base = (llm_config.get("openai_base_url") or
                             os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1")
            api_key = llm_config.get("api_key") or os.getenv("OPENAI_API_KEY")
            llm_config["openai_base_url"] = self.api_base
        llm_config["api_key"] = api_key
        self._memory_build_failed = False
        self.memory_input_hash = None
        self.embedding_model = os.getenv("AMEM_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        self.memory_system = AgenticMemorySystem(
            model_name=self.embedding_model,
            llm_backend="openai",  # vLLM serves the same Chat Completions protocol.
            llm_model=llm_config["model"],
            api_key=api_key,
            api_base=self.api_base,
        )
        self.llm = LlmFactory.create(
            provider_name=self.config.llm_provider,
            config=llm_config,
        )

    def add_memory(self, content, time=None):
        if self._memory_build_failed:
            raise RuntimeError("A-Mem memory construction failed; restart with a fresh agent.")
        before = FAILURES.copy()
        try:
            memory_id = self.memory_system.add_note(content, time=time)
        except Exception:
            self._memory_build_failed = True
            raise
        failures = FAILURES - before
        if any(failures[k] for k in ("llm_call", "analyze", "evolve")):
            # Infrastructure/schema failures remain fatal. JSON-only fallback
            # has separate counters and follows upstream's default-note behavior.
            self._memory_build_failed = True
            raise RuntimeError(f"A-Mem failed to construct memory: {dict(failures)}. "
                               "Check the LLM endpoint/schema and restart the build.")
        if failures:
            logger.warning("A-Mem fallback/output warnings: %s", dict(failures))
        return memory_id, content

    def add_conversation_to_memory(self, messages: List[Dict[str, str]], conversation_idx: Union[int, str]):
        """
        Add a conversation to the memory system.
        
        Args:
            messages: List of messages in the conversation. Each message is a dict with 'role' and 'content'.
            conversation_idx: Index of the conversation in the dataset, used to create a unique identifier for the conversation. 
        """
        if isinstance(conversation_idx, int):
            conversation_idx = str(conversation_idx)
        for msg_idx, msg in enumerate(messages):
            conversation_time = f"{conversation_idx}_{msg_idx}"
            content = f"Speaker {msg['role']} says: {msg['content']}"
            self.add_memory(content=content, time=conversation_time)
    
    def retrieve_memory(self, content, k=10):
        if k <= 0 or not self.memory_system.memories:
            return ""
        return self.memory_system.find_related_memories_raw(content, k=k)

    def generate_query_llm(self, question):
        prompt = f"""Given the following question, generate several keywords, using 'cosmos' as the separator.

Question: {question}

Format your response as a JSON object with a "keywords" field containing the selected text. 

Example response format:
{{"keywords": "keyword1, keyword2, keyword3"}}"""
        # Bound retries for malformed model output; SDK handles transport retries.
        for attempt in range(3):
            response = self.llm.generate_response(
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema", 
                    "json_schema": {
                        "name": "response",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "keywords": {
                                    "type": "string",
                                }
                            },
                            "required": ["keywords"],
                            "additionalProperties": False
                        },
                        "strict": True
                    }
                }
            )
            try:
                keywords = json.loads(response)["keywords"]
                if not isinstance(keywords, str) or not keywords.strip():
                    raise ValueError("keywords must be a nonempty string")
                return keywords
            except (ValueError, KeyError, TypeError) as exc:
                if attempt == 2:
                    raise ValueError("A-Mem query generation failed after 3 attempts") from exc

    def generate_response(
        self, 
        messages: List[Dict[str, str]],
        lang: Literal["en", "zh"] = "en",
        retrieve_k: int = None,
    ) -> str:
        """
        Generate a response to the user's question based on retrieved memories.
        
        Args:
            messages: List of messages in the conversation. Each message is a dict with 'role' and 'content'.
            lang: Language of the messages, either 'en' for English or 'zh' for Chinese.
        
        Returns:
            str: The agent's response to the messages.
        """
        if retrieve_k is None:
            retrieve_k = self.config.retrieve_k

        question = messages[-1]['content'] # the last message(from user) is the question
        keywords = self.generate_query_llm(question)
        context = self.retrieve_memory(keywords, k=retrieve_k)

        if lang == "en":
            user_prompt = f"""Context:
{context}

User: 
{question}

Based on the context provided, respond naturally and appropriately to the user's input above."""
        elif lang == "zh":
            user_prompt = f"""相关知识：
{context}

用户输入：
{question}

请根据提供的相关知识准确、自然地回答用户的输入。"""

        messages[-1]["content"] = user_prompt
        response = self.llm.generate_response(messages=messages)
        return response

    def _cache_signature(self):
        # Only memory-building settings; never persist API keys. Answer k and
        # answer sampling parameters do not change the stored memory state.
        return {
            "cache_version": CACHE_VERSION,
            "upstream_commit": UPSTREAM_COMMIT,
            "memory_version": MEMORY_VERSION,
            "model": self.config.llm_config["model"],
            "api_base": self.api_base,
            "embedding_model": self.embedding_model,
            "evo_threshold": self.memory_system.evo_threshold,
            "refresh_index": self.memory_system.refresh_index,
        }

    @staticmethod
    def _file_digest(path):
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _cache_error(self, reason):
        return ValueError(
            f"Incompatible or incomplete A-Mem cache at {self.memory_cache_dir}: {reason}. "
            "Rebuild from the original dialogs using a new --memory_cache_prefix "
            "(for example a_mem_v2_). Old caches cannot be migrated."
        )

    def save_memories(self):
        if self._memory_build_failed:
            raise RuntimeError("Cannot save A-Mem cache after a memory construction failure.")
        directory = Path(self.memory_cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        manifest_path = directory / "a_mem_manifest.json"
        # Invalidate before writing. The manifest is published last so interrupted
        # writes (even with an old saved.txt) cannot be loaded as complete caches.
        if manifest_path.exists():
            manifest_path.unlink()
        with open(directory / "memory_cache.pkl", "wb") as stream:
            pickle.dump(self.memory_system.memories, stream)
        retriever = self.memory_system.retriever
        retriever.save(str(directory / "retriever_cache.pkl"),
                       str(directory / "retriever_cache_embeddings.npy"))
        if not retriever.corpus:
            np.save(directory / "retriever_cache_embeddings.npy", np.empty((0, 0)))
        filenames = ("memory_cache.pkl", "retriever_cache.pkl", "retriever_cache_embeddings.npy")
        manifest = {
            "signature": self._cache_signature(),
            "input_hash": self.memory_input_hash,
            "memory_ids": list(self.memory_system.memories),
            "evo_cnt": self.memory_system.evo_cnt,
            "files": {name: self._file_digest(directory / name) for name in filenames},
        }
        temporary = directory / "a_mem_manifest.json.tmp"
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(temporary, manifest_path)
        print(f"Saved {len(self.memory_system.memories)} A-Mem memories to {directory}")

    def load_memories(self):
        directory = Path(self.memory_cache_dir)
        # Validate provenance before unpickling: legacy pickles reference the
        # removed agentic_memory package and lack working metadata/evolution.
        try:
            manifest = json.loads((directory / "a_mem_manifest.json").read_text(encoding="utf-8"))
            if manifest["signature"] != self._cache_signature():
                raise ValueError("memory implementation or configuration changed")
            if self.memory_input_hash is not None and manifest["input_hash"] != self.memory_input_hash:
                raise ValueError("input dialogs or their order changed")
            for name in ("memory_cache.pkl", "retriever_cache.pkl", "retriever_cache_embeddings.npy"):
                if self._file_digest(directory / name) != manifest["files"][name]:
                    raise ValueError(f"{name} does not match the saved manifest")
            evo_cnt = manifest["evo_cnt"]
            if type(evo_cnt) is not int or evo_cnt < 0:
                raise ValueError("invalid evolution counter")
            with open(directory / "memory_cache.pkl", "rb") as stream:
                memories = pickle.load(stream)
            with open(directory / "retriever_cache.pkl", "rb") as stream:
                state = pickle.load(stream)
            embeddings = np.load(directory / "retriever_cache_embeddings.npy", allow_pickle=False)
            if list(memories) != manifest["memory_ids"]:
                raise ValueError("memory order changed")
            if len(state["corpus"]) != len(memories) or embeddings.ndim != 2 or len(embeddings) != len(memories):
                raise ValueError("memories and embedding rows are misaligned")
            expected_document_ids = {doc: i for i, doc in enumerate(state["corpus"])}
            if state["document_ids"] != expected_document_ids:
                raise ValueError("retriever document indices are misaligned")
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, EOFError, pickle.UnpicklingError) as exc:
            raise self._cache_error(str(exc)) from exc
        # Install the validated state without rebuilding embeddings: upstream
        # intentionally defers neighbour re-embedding until consolidation.
        retriever = self.memory_system.retriever
        self.memory_system.memories = memories
        self.memory_system.evo_cnt = evo_cnt
        retriever.corpus = state["corpus"]
        retriever.document_ids = state["document_ids"]
        retriever.embeddings = embeddings if memories else None
        self.memory_input_hash = manifest["input_hash"]
        self._memory_build_failed = False
        print(f"Loaded {len(memories)} A-Mem memories from {directory}")
