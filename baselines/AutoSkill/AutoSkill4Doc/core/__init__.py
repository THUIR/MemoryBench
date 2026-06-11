"""Shared core helpers for AutoSkill4Doc."""

from .config import (
    DEFAULT_EXTRACT_STRATEGY,
    SUPPORTED_EXTRACT_STRATEGIES,
    default_registry_root,
    default_runtime_root,
    default_store_path,
    normalize_extract_strategy,
)
from .provider_config import build_embeddings_config, build_llm_config, pick_default_provider

__all__ = [
    "DEFAULT_EXTRACT_STRATEGY",
    "SUPPORTED_EXTRACT_STRATEGIES",
    "default_store_path",
    "default_runtime_root",
    "default_registry_root",
    "normalize_extract_strategy",
    "build_llm_config",
    "build_embeddings_config",
    "pick_default_provider",
]
