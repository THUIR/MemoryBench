"""
Offline extraction entrypoints.

This package provides batch/offline skill extraction flows for:
- archived conversations
- agentic execution trajectories
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "extract_from_conversation",
    "extract_from_agentic_trajectory",
]


def __getattr__(name: str) -> Any:
    """Run getattr."""
    if name == "extract_from_conversation":
        from .conversation.extract import extract_from_conversation as fn

        return fn
    if name == "extract_from_agentic_trajectory":
        from .trajectory.extract import extract_from_agentic_trajectory as fn

        return fn
    raise AttributeError(name)
