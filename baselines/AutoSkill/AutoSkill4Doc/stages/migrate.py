"""
Layout migration/preparation helpers for AutoSkill4Doc.

The current implementation focuses on safe preparation: it creates the expected
runtime directories and reports legacy top-level locations that may need manual
migration. It does not destructively move the existing AutoSkill local store.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from ..store.layout import (
    legacy_backup_root,
    normalize_library_root,
    previews_root,
    registry_root,
    runtime_root,
    runtime_store_root,
    staging_root,
)


def migrate_layout(
    *,
    store_root: str,
) -> Dict[str, Any]:
    """Prepares the runtime layout and reports legacy directories."""

    root = normalize_library_root(store_root)
    created: List[str] = []
    for path in [
        runtime_root(root),
        runtime_store_root(root),
        registry_root(root),
        staging_root(root),
        previews_root(root),
        legacy_backup_root(root),
    ]:
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            created.append(path)

    legacy_candidates = []
    for name in ["document_registry", "staging", "previews", "library_manifest.json"]:
        path = os.path.join(root, name)
        if os.path.exists(path):
            legacy_candidates.append(path)

    return {
        "route": "migrate_layout",
        "store_root": root,
        "created": created,
        "legacy_candidates": legacy_candidates,
        "errors": [],
    }
