import importlib
from typing import Optional, Union, Dict

from src import memory_systems

# Eager imports preserve the original behavior of failing fast at import time
# if a baseline's dependencies are missing.
from src.solver.base import BaseAgentConfig
from src.solver.bm25 import BM25AgentConfig
from src.solver.bm25_dialog import BM25DialogAgentConfig
from src.solver.embedder import EmbedderAgentConfig
from src.solver.embedder_dialog import EmbedderDialogAgentConfig
from src.solver.a_mem import AMemAgentConfig
from src.solver.mem0 import Mem0AgentConfig
from src.solver.memoryos import MemoryOSAgentConfig
# from src.solver.raptor import RAPTORAgentConfig


def load_class(class_type):
    module_path, class_name = class_type.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class SolverFactory:
    """Solver factory backed by `src.memory_systems`.

    The `method_to_class` dict is kept as a backward-compatible view; the
    source of truth is the registry.
    """

    @classmethod
    def _build_method_to_class(cls):
        return {
            name: (spec.solver_class, spec.config_class)
            for name, spec in memory_systems._REGISTRY.items()
        }

    # Snapshot at class-definition time so external code that reads
    # SolverFactory.method_to_class continues to work.
    method_to_class = None  # populated below

    @classmethod
    def create(cls, method_name: str, config: Dict, **kwargs):
        spec = memory_systems.get(method_name)
        solver_class = load_class(spec.solver_class)
        config_class = load_class(spec.config_class)

        memory_cache_dir = kwargs.get("memory_cache_dir", None)
        if memory_cache_dir is not None and "memory_cache_dir" in config_class.__init__.__code__.co_varnames:
            config["memory_cache_dir"] = memory_cache_dir
        for key, value in kwargs.items():
            if key in config_class.__init__.__code__.co_varnames:
                config[key] = value
        agent_config = config_class(**config)
        return solver_class(agent_config, memory_cache_dir=memory_cache_dir)


SolverFactory.method_to_class = SolverFactory._build_method_to_class()
