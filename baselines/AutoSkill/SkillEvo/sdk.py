from __future__ import annotations

from typing import Any, Dict, Optional

from autoskill import AutoSkill, AutoSkillConfig
from autoskill.llm.factory import build_llm

from .config import SkillEvoConfig


def build_evo_sdk(config: SkillEvoConfig) -> AutoSkill:
    sdk_config = AutoSkillConfig(
        llm={"provider": "mock"},
        embeddings={"provider": "hashing", "dims": 64},
        store={"provider": "local", "path": str(config.store_path)},
        maintenance_strategy="heuristic",
        bm25_weight=0.0,
    )
    return AutoSkill(sdk_config)


def build_evo_llm(cfg: Optional[Dict[str, Any]]) -> Any:
    if not isinstance(cfg, dict):
        return None
    return build_llm(dict(cfg))
