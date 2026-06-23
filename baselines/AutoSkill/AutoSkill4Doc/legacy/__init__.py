"""Legacy compatibility helpers kept for older callers."""

from .inducer import CapabilityInductionResult, CapabilityInducer, build_capability_inducer, induce_capabilities

__all__ = [
    "CapabilityInductionResult",
    "CapabilityInducer",
    "build_capability_inducer",
    "induce_capabilities",
]
