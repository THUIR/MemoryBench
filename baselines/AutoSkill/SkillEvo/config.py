from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - Python 3.10 fallback
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except Exception:  # pragma: no cover - optional dependency fallback
        tomllib = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SkillEvoConfig:
    evo_root: Path
    store_path: Path
    llm: Dict[str, Any] = field(default_factory=lambda: {"provider": "mock"})
    mutator_llm: Optional[Dict[str, Any]] = None
    judge_llm: Optional[Dict[str, Any]] = None
    mutation_mode: str = "hybrid"  # heuristic|llm|hybrid
    mutation_budget: int = 8
    replay_limit: int = 40
    min_replay_samples: int = 8
    dev_split_ratio: float = 0.7
    promotion_repeats: int = 3
    mutate_repeats: int = 1
    min_score_delta: float = 0.05
    max_eval_rules: int = 6
    sample_history_turns: int = 8
    response_max_chars: int = 20000

    @property
    def registry_dir(self) -> Path:
        return self.evo_root / "registry"

    @property
    def datasets_dir(self) -> Path:
        return self.evo_root / "datasets"

    @property
    def evals_dir(self) -> Path:
        return self.evo_root / "evals"

    @property
    def runs_dir(self) -> Path:
        return self.evo_root / "runs"

    @property
    def champions_dir(self) -> Path:
        return self.evo_root / "champions"

    @property
    def reports_dir(self) -> Path:
        return self.evo_root / "reports"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_evo_root() -> Path:
    return _repo_root() / "SkillEvo"


def _default_store_path() -> Path:
    return _repo_root() / "SkillBank"


def load_skillevo_config(
    *,
    path: str | None = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> SkillEvoConfig:
    raw: Dict[str, Any] = {}
    cfg_path = Path(path).expanduser().resolve() if path else (_default_evo_root() / "config.toml")
    if cfg_path.is_file() and tomllib is not None:
        with open(cfg_path, "rb") as f:
            obj = tomllib.load(f)
        if isinstance(obj, dict):
            raw = dict(obj)
    if overrides:
        raw.update(dict(overrides))

    evo_root = Path(str(raw.get("evo_root") or raw.get("lab_root") or _default_evo_root())).expanduser().resolve()
    store_path = Path(str(raw.get("store_path") or _default_store_path())).expanduser().resolve()

    judge_llm = raw.get("judge_llm")
    if not isinstance(judge_llm, dict):
        judge_llm = None

    mutator_llm = raw.get("mutator_llm")
    if not isinstance(mutator_llm, dict):
        mutator_llm = None

    llm = raw.get("llm")
    if not isinstance(llm, dict):
        llm = {"provider": "mock"}

    return SkillEvoConfig(
        evo_root=evo_root,
        store_path=store_path,
        llm=dict(llm),
        mutator_llm=(dict(mutator_llm) if mutator_llm is not None else None),
        judge_llm=(dict(judge_llm) if judge_llm is not None else None),
        mutation_mode=str(raw.get("mutation_mode") or "hybrid").strip().lower() or "hybrid",
        mutation_budget=max(1, int(raw.get("mutation_budget", 8) or 8)),
        replay_limit=max(4, int(raw.get("replay_limit", 40) or 40)),
        min_replay_samples=max(2, int(raw.get("min_replay_samples", 8) or 8)),
        dev_split_ratio=min(0.95, max(0.5, float(raw.get("dev_split_ratio", 0.7) or 0.7))),
        promotion_repeats=max(1, int(raw.get("promotion_repeats", 3) or 3)),
        mutate_repeats=max(1, int(raw.get("mutate_repeats", 1) or 1)),
        min_score_delta=max(0.0, float(raw.get("min_score_delta", 0.05) or 0.05)),
        max_eval_rules=max(2, int(raw.get("max_eval_rules", 6) or 6)),
        sample_history_turns=max(1, int(raw.get("sample_history_turns", 8) or 8)),
        response_max_chars=max(1000, int(raw.get("response_max_chars", 20000) or 20000)),
    )
