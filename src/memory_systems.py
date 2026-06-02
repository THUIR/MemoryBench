"""
Central registry for memory-system baselines.

Adding a new baseline is now a single-file change: append a
`MemorySystemSpec` entry below and provide the agent/solver classes plus a
JSON config file under `configs/memory_systems/`.

Everything downstream (`SolverFactory`, `get_memory_system_config_file`,
`get_dialog_key`, the argparse `--memory_system` choices, and the
`run_scripts/*.py` loops) reads from this registry.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class MemorySystemSpec:
    """Metadata describing a memory-system baseline."""

    name: str
    solver_class: str   # dotted import path, e.g. "src.solver.mem0.Mem0Solver"
    config_class: str   # dotted import path
    config_file: str    # default config JSON, relative to repo root

    # Stem used when building the HF-dataset field name for pre-generated dialogs.
    # The final key is `prefix + dialog_stem`. Falls back to `name` when None.
    dialog_stem: Optional[str] = None

    # Human-readable name used in the paper (informational only).
    paper_name: Optional[str] = None

    # Tuples of (dataset_type, set_name) that the run_scripts skip by default
    # — typically because the baseline is too slow for that combination.
    skip_combinations: List[Tuple[str, str]] = field(default_factory=list)

    # Whether this baseline is shown in normal CLI/frontend choices. Experimental
    # baselines that need external, non-vendored assets should stay registered
    # but not advertised by default.
    available_by_default: bool = True

    # Whether the public MemoryBench dataset already contains the pre-generated
    # dialog_<name> fields needed by off-policy/train-performance runs.
    has_public_pregenerated_dialogs: bool = True

    def dialog_key(self, prefix: str = "dialog_") -> str:
        return prefix + (self.dialog_stem or self.name)


_REGISTRY: Dict[str, MemorySystemSpec] = {}


def register(spec: MemorySystemSpec) -> None:
    _REGISTRY[spec.name] = spec


def get(name: str) -> MemorySystemSpec:
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown memory system '{name}'. Registered: {list(_REGISTRY)}"
        )
    return _REGISTRY[name]


def registered_names() -> List[str]:
    """All baselines known to the registry, including experimental ones."""
    return list(_REGISTRY.keys())


def all_names() -> List[str]:
    """Baselines available through normal runner/frontend choices."""
    return [n for n, spec in _REGISTRY.items() if spec.available_by_default]


def names_with_memory() -> List[str]:
    """All registered methods except the no-memory baseline."""
    return [n for n in all_names() if n != "wo_memory"]


def off_policy_names() -> List[str]:
    """Baselines safe for public off-policy data that ships pre-generated dialogs."""
    return [
        n for n, spec in _REGISTRY.items()
        if spec.available_by_default and spec.has_public_pregenerated_dialogs
    ]


def is_registered(name: str) -> bool:
    return name in _REGISTRY


# ---------------------------------------------------------------------------
# Default baselines shipped with MemoryBench.
# ---------------------------------------------------------------------------
register(MemorySystemSpec(
    name="wo_memory",
    solver_class="src.solver.base.BaseSolver",
    config_class="src.solver.base.BaseAgentConfig",
    config_file="configs/memory_systems/base.json",
    paper_name="Vanilla",
))

register(MemorySystemSpec(
    name="bm25_message",
    solver_class="src.solver.bm25.BM25Solver",
    config_class="src.solver.bm25.BM25AgentConfig",
    config_file="configs/memory_systems/bm25.json",
    dialog_stem="bm25",
    paper_name="BM25-M",
))

register(MemorySystemSpec(
    name="bm25_dialog",
    solver_class="src.solver.bm25_dialog.BM25DialogSolver",
    config_class="src.solver.bm25_dialog.BM25DialogAgentConfig",
    config_file="configs/memory_systems/bm25.json",
    paper_name="BM25-S",
))

register(MemorySystemSpec(
    name="embedder_message",
    solver_class="src.solver.embedder.EmbedderSolver",
    config_class="src.solver.embedder.EmbedderAgentConfig",
    config_file="configs/memory_systems/embedder.json",
    dialog_stem="embedder",
    paper_name="Emb-M",
))

register(MemorySystemSpec(
    name="embedder_dialog",
    solver_class="src.solver.embedder_dialog.EmbedderDialogSolver",
    config_class="src.solver.embedder_dialog.EmbedderDialogAgentConfig",
    config_file="configs/memory_systems/embedder.json",
    paper_name="Emb-S",
))

register(MemorySystemSpec(
    name="a_mem",
    solver_class="src.solver.a_mem.AMemSolver",
    config_class="src.solver.a_mem.AMemAgentConfig",
    config_file="configs/memory_systems/a_mem.json",
    paper_name="A-Mem",
))

register(MemorySystemSpec(
    name="mem0",
    solver_class="src.solver.mem0.Mem0Solver",
    config_class="src.solver.mem0.Mem0AgentConfig",
    config_file="configs/memory_systems/mem0.json",
    paper_name="Mem0",
    # Mem0 is too slow on these combinations; run_scripts skip them.
    skip_combinations=[("domain", "Open-Domain"), ("task", "Long-Short")],
))

register(MemorySystemSpec(
    name="memoryos",
    solver_class="src.solver.memoryos.MemoryOSSolver",
    config_class="src.solver.memoryos.MemoryOSAgentConfig",
    config_file="configs/memory_systems/memoryos.json",
    paper_name="MemoryOS",
))

register(MemorySystemSpec(
    name="light",
    solver_class="src.solver.light.LightSolver",
    config_class="src.solver.light.LightAgentConfig",
    config_file="configs/memory_systems/light.json",
    paper_name="LIGHT",
    has_public_pregenerated_dialogs=False,
))

register(MemorySystemSpec(
    name="tencentdb",
    solver_class="src.solver.tencentdb.TencentDBSolver",
    config_class="src.solver.tencentdb.TencentDBAgentConfig",
    config_file="configs/memory_systems/tencentdb.json",
    paper_name="TencentDB",
    available_by_default=False,
    has_public_pregenerated_dialogs=False,
))
