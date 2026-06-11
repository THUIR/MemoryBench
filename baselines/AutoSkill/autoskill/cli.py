"""
Top-level AutoSkill CLI router.

This module keeps the root command intentionally thin. It delegates concrete
offline workflows to their existing module-level CLIs so the implementation
logic remains inside the relevant feature packages.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence


def build_parser() -> argparse.ArgumentParser:
    """Builds the minimal top-level AutoSkill CLI parser."""

    parser = argparse.ArgumentParser(
        description="AutoSkill command line interface.",
        epilog="Document extraction is now standalone: use `autoskill4doc -h` or `python -m AutoSkill4Doc -h`.",
    )
    root_subparsers = parser.add_subparsers(dest="namespace")

    offline_parser = root_subparsers.add_parser("offline", help="Offline batch/document processing commands.")
    offline_subparsers = offline_parser.add_subparsers(dest="offline_kind")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Routes root CLI invocations to feature-specific command handlers."""

    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if raw_args[:2] == ["offline", "document"]:
        raise SystemExit(
            "AutoSkill4Doc is now standalone. Use `autoskill4doc ...` or `python -m AutoSkill4Doc ...`."
        )

    args = build_parser().parse_args(raw_args)
    namespace = str(getattr(args, "namespace", "") or "").strip()
    offline_kind = str(getattr(args, "offline_kind", "") or "").strip()

    build_parser().print_help()


if __name__ == "__main__":
    main()
