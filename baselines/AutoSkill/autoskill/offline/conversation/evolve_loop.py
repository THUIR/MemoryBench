"""Compatibility wrapper for the self-evolve workflow package."""

from __future__ import annotations

from .self_evolve.loop import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    main()
