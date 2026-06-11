import importlib
from typing import Optional, Union, Dict

from src import memory_systems

# Baseline classes are loaded lazily by SolverFactory.create. This keeps one
# baseline's optional dependency (for example mem0) from blocking unrelated
# baselines such as AutoSkill at import time.


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

    @staticmethod
    def _config_accepts(config_class, key: str) -> bool:
        fields = getattr(config_class, "model_fields", None) or getattr(config_class, "__fields__", None)
        if isinstance(fields, dict) and key in fields:
            return True
        init = getattr(config_class, "__init__", None)
        code = getattr(init, "__code__", None)
        return bool(code is not None and key in code.co_varnames)

    @classmethod
    def create(cls, method_name: str, config: Dict, **kwargs):
        spec = memory_systems.get(method_name)
        solver_class = load_class(spec.solver_class)
        config_class = load_class(spec.config_class)

        memory_cache_dir = kwargs.get("memory_cache_dir", None)
        if memory_cache_dir is not None and cls._config_accepts(config_class, "memory_cache_dir"):
            config["memory_cache_dir"] = memory_cache_dir
        for key, value in kwargs.items():
            if cls._config_accepts(config_class, key):
                config[key] = value
        agent_config = config_class(**config)
        return solver_class(agent_config, memory_cache_dir=memory_cache_dir)


SolverFactory.method_to_class = SolverFactory._build_method_to_class()
