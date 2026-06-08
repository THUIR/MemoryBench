from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .config import SkillEvoConfig
from .io_utils import ensure_dir, read_json, read_jsonl, write_json, write_jsonl
from .models import LineageRecord, SkillVariant


def lineage_registry_path(config: SkillEvoConfig) -> Path:
    return config.registry_dir / "lineages.jsonl"


def champions_registry_path(config: SkillEvoConfig) -> Path:
    return config.registry_dir / "champions.json"


def lineage_dataset_dir(config: SkillEvoConfig, lineage_id: str) -> Path:
    return config.datasets_dir / lineage_id


def lineage_eval_dir(config: SkillEvoConfig, lineage_id: str) -> Path:
    return config.evals_dir / lineage_id


def lineage_run_dir(config: SkillEvoConfig, lineage_id: str, run_id: str) -> Path:
    return config.runs_dir / lineage_id / run_id


def lineage_champion_dir(config: SkillEvoConfig, lineage_id: str) -> Path:
    return config.champions_dir / lineage_id


def upsert_lineage_record(config: SkillEvoConfig, record: LineageRecord) -> None:
    path = lineage_registry_path(config)
    rows = read_jsonl(path)
    out: List[Dict[str, Any]] = []
    replaced = False
    for item in rows:
        if str(item.get("lineage_id") or "") == record.lineage_id:
            out.append(record.to_dict())
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(record.to_dict())
    write_jsonl(path, out)


def get_lineage_record(config: SkillEvoConfig, lineage_id: str) -> Dict[str, Any]:
    for item in read_jsonl(lineage_registry_path(config)):
        if str(item.get("lineage_id") or "") == str(lineage_id or ""):
            return item
    return {}


def set_champion(config: SkillEvoConfig, *, lineage_id: str, variant: SkillVariant, summary: Dict[str, Any]) -> None:
    path = champions_registry_path(config)
    payload = read_json(path, default={"version": 1, "champions": {}})
    champs = dict(payload.get("champions") or {})
    champs[str(lineage_id)] = {
        "variant": variant.to_dict(),
        "summary": dict(summary or {}),
    }
    payload["champions"] = champs
    write_json(path, payload)


def get_champion(config: SkillEvoConfig, lineage_id: str) -> Dict[str, Any]:
    payload = read_json(champions_registry_path(config), default={"champions": {}})
    champs = dict(payload.get("champions") or {})
    item = champs.get(str(lineage_id))
    return dict(item or {})


def ensure_evo_layout(config: SkillEvoConfig) -> None:
    for path in (
        config.evo_root,
        config.registry_dir,
        config.datasets_dir,
        config.evals_dir,
        config.runs_dir,
        config.champions_dir,
        config.reports_dir,
    ):
        ensure_dir(path)
