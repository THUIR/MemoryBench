import os
import asyncio
import threading
from datetime import datetime, timezone
from typing import List, Dict, Optional, Literal, Union, Iterable
from pydantic import BaseModel, Field

from src.llms import LlmFactory
from src.agent.base_agent import BaseAgent

from graphiti_core import Graphiti
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.nodes import EpisodeType


class _AsyncLoopThread:
    """Dedicated event loop running in a background thread.

    Graphiti is fully async while MemoryBench solvers are sync and may call
    the agent from multiple worker threads; funnelling every coroutine into a
    single persistent loop keeps Graphiti's clients (AsyncAnthropic, Kuzu
    AsyncConnection) on the loop they were created for.
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()


class SentenceTransformerEmbedder(EmbedderClient):
    """Local embedder so Graphiti does not require an embeddings API."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self._lock = threading.Lock()

    def _encode(self, texts: List[str]) -> List[List[float]]:
        with self._lock:
            return self.model.encode(texts, show_progress_bar=False).tolist()

    async def create(
        self, input_data: Union[str, List[str], Iterable[int], Iterable[Iterable[int]]]
    ) -> List[float]:
        if isinstance(input_data, str):
            texts = [input_data]
        else:
            texts = [str(t) for t in input_data]
        embeddings = await asyncio.to_thread(self._encode, texts)
        return embeddings[0]

    async def create_batch(self, input_data_list: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self._encode, list(input_data_list))


class GraphitiAgentConfig(BaseModel):
    llm_provider: Literal["openai", "vllm", "anthropic"] = Field(
        default="anthropic",
        description="The LLM provider used both for Graphiti's graph extraction and for response generation."
    )
    llm_config: dict = Field(
        default={},
        description="Configuration parameters for the LLM (model, base url, api key, ...)."
    )
    embedder_provider: Literal["huggingface", "openai", "vllm"] = Field(
        default="huggingface",
        description="Provider of the embedding model. 'huggingface' runs a local sentence-transformers model."
    )
    embedder_config: dict = Field(
        default={},
        description="Configuration for the embedding model (model, base_url, api_key)."
    )
    retrieve_k: int = Field(
        default=20,
        description="Number of graph facts to retrieve for a given query."
    )
    messages_per_episode: int = Field(
        default=20,
        description="How many consecutive dialog messages are grouped into one Graphiti episode."
    )
    memory_cache_dir: str = Field(
        default=os.path.join(os.getcwd(), "graphiti_cache"),
        description="Directory holding the Kuzu graph database."
    )


class GraphitiAgent(BaseAgent):
    def __init__(self, config: GraphitiAgentConfig = GraphitiAgentConfig()):
        self.config = config
        os.makedirs(config.memory_cache_dir, exist_ok=True)

        self._loop = _AsyncLoopThread()

        driver = KuzuDriver(db=os.path.join(config.memory_cache_dir, "graphiti_kuzu"))
        graph_llm_client = self._build_graph_llm_client()
        embedder = self._build_embedder()
        # The default Graphiti.search() recipe (EDGE_HYBRID_SEARCH_RRF) never
        # invokes the cross encoder, so a placeholder key is fine here.
        cross_encoder = OpenAIRerankerClient(config=LLMConfig(api_key="unused"))

        self.graphiti = Graphiti(
            graph_driver=driver,
            llm_client=graph_llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )
        # KuzuDriver.build_indices_and_constraints is a no-op; the FTS indices
        # Graphiti's search relies on are created by the driver's graph_ops.
        # Ignore failures when reopening a cached DB whose indices already exist.
        try:
            self._run(driver.graph_ops.build_indices_and_constraints(driver))
        except Exception as e:
            print(f"[Graphiti] build_indices_and_constraints: {e}")
        self._checkpoint()

        self.llm = LlmFactory.create(
            provider_name=self.config.llm_provider,
            config=self.config.llm_config,
        )

    def _run(self, coro):
        return self._loop.run(coro)

    def _build_graph_llm_client(self):
        cfg = self.config.llm_config
        model = cfg.get("model")
        if self.config.llm_provider == "anthropic":
            from anthropic import AsyncAnthropic
            api_key = cfg.get("api_key") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
            base_url = cfg.get("anthropic_base_url") or os.environ.get("ANTHROPIC_BASE_URL")
            client_kwargs = {"api_key": api_key, "max_retries": 3}
            if base_url:
                client_kwargs["base_url"] = base_url
            client = AsyncAnthropic(**client_kwargs)
            if cfg.get("disable_thinking", True):
                # Graphiti forces tool use (tool_choice: required) for structured
                # extraction, which thinking-mode models reject; turn thinking off.
                original_create = client.messages.create

                async def _create_no_thinking(*args, **kwargs):
                    extra_body = dict(kwargs.get("extra_body") or {})
                    extra_body.setdefault("thinking", {"type": "disabled"})
                    kwargs["extra_body"] = extra_body
                    return await original_create(*args, **kwargs)

                client.messages.create = _create_no_thinking
            return AnthropicClient(
                config=LLMConfig(api_key=api_key, model=model, small_model=model),
                client=client,
            )
        elif self.config.llm_provider == "openai":
            api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
            base_url = cfg.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL")
            return OpenAIClient(
                config=LLMConfig(api_key=api_key, model=model, small_model=model, base_url=base_url),
            )
        else:  # vllm: any OpenAI-compatible endpoint without structured-output support
            api_key = cfg.get("api_key", "EMPTY")
            base_url = cfg.get("vllm_base_url", "http://localhost:12366/v1")
            return OpenAIGenericClient(
                config=LLMConfig(api_key=api_key, model=model, small_model=model, base_url=base_url),
            )

    def _build_embedder(self):
        cfg = self.config.embedder_config
        if self.config.embedder_provider == "huggingface":
            return SentenceTransformerEmbedder(
                model_name=cfg.get("model", "sentence-transformers/all-MiniLM-L6-v2"),
            )
        else:  # openai / vllm: OpenAI-compatible embeddings endpoint
            api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
            base_url = cfg.get("base_url") or cfg.get("vllm_base_url") or os.environ.get("OPENAI_BASE_URL")
            return OpenAIEmbedder(
                config=OpenAIEmbedderConfig(
                    embedding_model=cfg.get("model", "text-embedding-3-small"),
                    api_key=api_key,
                    base_url=base_url,
                )
            )

    def add_episode(
        self,
        name: str,
        episode_body: str,
        source_description: str = "dialog history",
        reference_time: Optional[datetime] = None,
    ) -> str:
        """Ingest one episode into the graph and return its uuid."""
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)
        result = self._run(self.graphiti.add_episode(
            name=name,
            episode_body=episode_body,
            source_description=source_description,
            reference_time=reference_time,
            source=EpisodeType.message,
        ))
        return result.episode.uuid

    def remove_episode(self, episode_uuid: str):
        self._run(self.graphiti.remove_episode(episode_uuid))

    def retrieve_memory(
        self,
        query: str,
        retrieve_k: Optional[int] = None,
    ) -> str:
        """
        Retrieve relevant facts from the temporal knowledge graph.

        Args:
            query: The query string to search for relevant memories.
            retrieve_k: Optional; number of facts to retrieve. If None, uses the default from config.

        Returns:
            str: A formatted string of relevant graph facts.
        """
        if retrieve_k is None:
            retrieve_k = self.config.retrieve_k
        edges = self._run(self.graphiti.search(query=query, num_results=retrieve_k))
        lines = []
        for edge in edges:
            line = f"- {edge.fact}"
            if edge.valid_at:
                line += f" (valid from {edge.valid_at.strftime('%Y-%m-%d')}"
                if edge.invalid_at:
                    line += f" until {edge.invalid_at.strftime('%Y-%m-%d')}"
                line += ")"
            lines.append(line)
        return "\n".join(lines)

    def add_conversation_to_memory(
        self,
        messages: List[Dict[str, str]],
        conversation_idx: Union[int, str] = 0,
    ):
        """
        Add a completed conversation to the graph as one or more episodes.

        Args:
            messages: List of messages in the conversation. Each message is a dict with 'role' and 'content'.
        """
        if isinstance(conversation_idx, int):
            conversation_idx = str(conversation_idx)
        chunk_size = self.config.messages_per_episode
        for chunk_idx in range(0, len(messages), chunk_size):
            chunk = messages[chunk_idx:chunk_idx + chunk_size]
            episode_body = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}" for m in chunk
            )
            for attempt in range(5):
                try:
                    self.add_episode(
                        name=f"dialog-{conversation_idx}-part-{chunk_idx // chunk_size}",
                        episode_body=episode_body,
                    )
                    break
                except Exception as e:
                    print(f"[Graphiti] Error adding episode (attempt {attempt + 1}): {e}")

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        lang: Literal["en", "zh"] = "en",
        retrieve_k: int = None,
    ) -> str:
        """
        Generate a response to the user's question based on facts retrieved from the graph.

        Args:
            messages: List of messages in the conversation. Each message is a dict with 'role' and 'content'.
            lang: Language of the messages, either "en" for English or "zh" for Chinese.

        Returns:
            str: The agent's response to the messages.
        """
        if retrieve_k is None:
            retrieve_k = self.config.retrieve_k

        query = messages[-1]['content']  # the last message (from user) is the question
        memories_str = self.retrieve_memory(query, retrieve_k=retrieve_k)
        if lang == "en":
            user_prompt = f"""Facts about the user from a temporal knowledge graph:
{memories_str}

User input:
{query}

Based on the facts provided, respond naturally and appropriately to the user's input above."""
        elif lang == "zh":
            user_prompt = f"""来自时序知识图谱的用户相关事实：
{memories_str}

用户输入：
{query}

请根据提供的事实，自然且恰当地回应用户的上述输入。"""

        messages[-1]["content"] = user_prompt
        response = self.llm.generate_response(messages=messages)
        return response

    def _checkpoint(self):
        """Flush the Kuzu WAL into the database file.

        The off-policy runner copies the memory cache directory while this
        process still holds the database open; opening a copy that carries a
        dirty WAL segfaults inside Kuzu. Checkpointing keeps the on-disk file
        copy-safe.
        """
        try:
            self._run(self.graphiti.driver.execute_query("CHECKPOINT;"))
        except Exception as e:
            print(f"[Graphiti] checkpoint failed: {e}")

    def save_memories(self):
        # Kuzu persists writes as it goes; just make the on-disk file copy-safe.
        self._checkpoint()

    def load_memories(self):
        # The graph is loaded from memory_cache_dir when KuzuDriver opens the database.
        pass
