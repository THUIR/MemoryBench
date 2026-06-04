"""Anthropic-protocol LLM provider.

Targets endpoints that speak the Anthropic Messages API (the official API or
any compatible proxy). Accepts the same OpenAI-style `messages` list the other
providers use; any leading {"role": "system"} entry is pulled out into the
Anthropic `system` field.

Tool-calling is intentionally not surfaced here yet — none of the registered
MemoryBench baselines exercise that path through the LLM layer.
"""
import os
from typing import Dict, List, Optional, Union

from src.llms.base import BaseLlmConfig, LLMBase


class AnthropicConfig(BaseLlmConfig):
    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.1,
        api_key: Optional[str] = None,
        max_tokens: int = 2048,
        top_p: float = 0.1,
        top_k: int = 1,
        enable_vision: bool = False,
        vision_details: Optional[str] = "auto",
        http_client_proxies: Optional[dict] = None,
        anthropic_base_url: Optional[str] = None,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            api_key=api_key,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
            enable_vision=enable_vision,
            vision_details=vision_details,
            http_client_proxies=http_client_proxies,
        )
        self.anthropic_base_url = anthropic_base_url


def _split_system(messages: List[Dict[str, str]]):
    """Extract a system prompt if present and return (system_str, remaining_messages)."""
    system_parts: List[str] = []
    rest: List[Dict[str, str]] = []
    for m in messages:
        if m.get("role") == "system":
            content = m.get("content", "")
            if content:
                system_parts.append(content)
        else:
            rest.append(m)
    return ("\n\n".join(system_parts) if system_parts else None), rest


class AnthropicLLM(LLMBase):
    def __init__(self, config: Optional[Union[BaseLlmConfig, AnthropicConfig, Dict]] = None):
        if config is None:
            config = AnthropicConfig()
        elif isinstance(config, dict):
            config = AnthropicConfig(**config)
        elif isinstance(config, BaseLlmConfig) and not isinstance(config, AnthropicConfig):
            config = AnthropicConfig(
                model=config.model,
                temperature=config.temperature,
                api_key=config.api_key,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                top_k=config.top_k,
                enable_vision=config.enable_vision,
                vision_details=config.vision_details,
                http_client_proxies=config.http_client,
            )
        super().__init__(config)

        if not self.config.model:
            raise ValueError("AnthropicConfig: 'model' is required")

        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' SDK is required to use the anthropic provider. "
                "Install with `pip install anthropic`."
            ) from e

        api_key = self.config.api_key or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
        base_url = self.config.anthropic_base_url or os.getenv("ANTHROPIC_BASE_URL")
        if not api_key:
            raise ValueError(
                "AnthropicConfig: no api_key provided and neither ANTHROPIC_AUTH_TOKEN nor "
                "ANTHROPIC_API_KEY is set."
            )
        request_timeout = float(os.getenv("LLM_REQUEST_TIMEOUT", "180"))

        client_kwargs = {"api_key": api_key, "timeout": request_timeout}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        response_format=None,
        extra_body=None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs,
    ) -> str:
        if tools is not None:
            raise NotImplementedError(
                "AnthropicLLM.generate_response does not yet expose tool calling."
            )

        system, payload_messages = _split_system(messages)
        params = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "messages": payload_messages,
        }
        if system:
            params["system"] = system
        if extra_body:
            params.update(extra_body)

        resp = self.client.messages.create(**params)
        # Anthropic returns a list of content blocks; concatenate the text ones.
        chunks = []
        for block in getattr(resp, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "".join(chunks)
