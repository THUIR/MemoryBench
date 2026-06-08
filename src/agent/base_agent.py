import json
import os
import threading
from typing import Any, List, Dict, Optional, Literal

from pydantic import BaseModel, Field

from src.llms import LlmFactory


class BaseAgentConfig(BaseModel):
    llm_provider: Literal["openai", "vllm", "anthropic"] = Field(
        default="openai",
        description="The LLM provider to use for the agent."
    )
    llm_config: dict = Field(
        default_factory=dict, 
        description="Configuration parameters for the LLM."
    )


class BaseAgent:
    def __init__(self, config: BaseAgentConfig = BaseAgentConfig()):
        self.config = config
        self._memory_trace_local = threading.local()
        self.llm = LlmFactory.create(
            provider_name=config.llm_provider,
            config=config.llm_config,
        )

    def _get_memory_trace_local(self):
        if not hasattr(self, "_memory_trace_local"):
            self._memory_trace_local = threading.local()
        return self._memory_trace_local

    def clear_last_memory_trace(self) -> None:
        self._get_memory_trace_local().records = []

    def set_last_memory_trace(self, records: List[Dict[str, Any]]) -> None:
        self._get_memory_trace_local().records = list(records or [])

    def get_last_memory_trace(self) -> List[Dict[str, Any]]:
        records = getattr(self._get_memory_trace_local(), "records", [])
        return list(records or [])

    def export_memory_records(self) -> List[Dict[str, Any]]:
        """Return all stored memories in a system-specific structured form."""
        return []

    def memory_records_storage_format(self) -> str:
        """Return text, json, or both for full-memory record artifacts."""
        return "text"

    def format_memory_records_text(self, records: List[Dict[str, Any]]) -> str:
        """Render memory records as a human-readable text artifact."""
        lines = [f"# {type(self).__name__} Memory Records", "", f"Total memories: {len(records)}", ""]
        for idx, record in enumerate(records, start=1):
            title = record.get("name") or record.get("id") or f"memory_{idx}"
            lines.append(f"## Memory {idx}: {title}")
            lines.append(json.dumps(record, ensure_ascii=False, indent=2, default=str))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def write_memory_records(
        self,
        output_dir: str,
        text_filename: str = "memory_records.txt",
        json_filename: str = "memory_records.json",
    ) -> List[str]:
        records = self.export_memory_records()
        if not records:
            return []
        os.makedirs(output_dir, exist_ok=True)
        fmt = str(self.memory_records_storage_format() or "text").strip().lower()
        if fmt not in {"text", "json", "both"}:
            fmt = "text"

        paths = []
        if fmt in {"text", "both"}:
            text_path = os.path.join(output_dir, text_filename)
            with open(text_path, "w", encoding="utf-8") as fout:
                fout.write(self.format_memory_records_text(records))
            paths.append(text_path)
        if fmt in {"json", "both"}:
            json_path = os.path.join(output_dir, json_filename)
            with open(json_path, "w", encoding="utf-8") as fout:
                json.dump(records, fout, ensure_ascii=False, indent=2, default=str)
            paths.append(json_path)
        return paths

    def write_memory_records_text(
        self,
        output_dir: str,
        filename: str = "memory_records.txt",
    ) -> Optional[str]:
        records = self.export_memory_records()
        if not records:
            return None
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename)
        with open(output_path, "w", encoding="utf-8") as fout:
            fout.write(self.format_memory_records_text(records))
        return output_path
    
    
    def generate_response(
        self,
        messages: List[Dict[str, str]],
        response_format=None,
        extra_body=None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        lang: Literal["en", "zh"] = "en",
        retrieve_k: int = None,
        **kwargs,
    ):
        """
        Generate a response based on the given messages.

        Args:
            messages (list): List of message dicts containing 'role' and 'content'.
            response_format (str or object, optional): Format of the response. Defaults to "text". See https://docs.vllm.ai/en/latest/features/structured_outputs.html#online-serving-openai-api
            extra_body: Additional body parameters for the request, defaults to None. See https://docs.vllm.ai/en/latest/features/structured_outputs.html#online-serving-openai-api
            tools (list, optional): List of tools that the model can call. Defaults to None.
            tool_choice (str, optional): Tool choice method. Defaults to "auto".
            **kwargs: Additional vLLM-specific parameters.

        Returns:
            str: The generated response.
        """
        return self.llm.generate_response(
            messages=messages, 
            response_format=response_format,
            extra_body=extra_body,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
