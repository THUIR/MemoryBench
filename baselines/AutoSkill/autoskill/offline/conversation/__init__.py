"""
Offline extraction flow for archived OpenAI-format conversations.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "extract_from_conversation",
    "conversation_provenance_path",
    "load_skill_conversation_provenance",
    "main",
]


def __getattr__(name: str) -> Any:
    """Run getattr."""
    if name == "extract_from_conversation":
        from .extract import extract_from_conversation as fn

        return fn
    if name == "conversation_provenance_path":
        from .provenance_store import conversation_provenance_path as fn

        return fn
    if name == "load_skill_conversation_provenance":
        from .provenance_store import load_skill_conversation_provenance as fn

        return fn
    if name == "main":
        from .extract import main as fn

        return fn
    raise AttributeError(name)
