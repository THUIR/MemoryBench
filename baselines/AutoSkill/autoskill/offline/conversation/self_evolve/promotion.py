"""
Promotion comparison, safety gate, and terminal decision rendering.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .eval import _print_detail


def _promotion_cmp_key(metrics: Dict[str, Any]) -> Tuple[float, float, float]:
    return (
        float(metrics.get("precision_yes", 0.0) or 0.0),
        float(metrics.get("f1_yes", 0.0) or 0.0),
        float(metrics.get("recall_yes", 0.0) or 0.0),
    )


def _safety_gate(
    *,
    candidate_metrics: Dict[str, Any],
    best_metrics: Dict[str, Any],
) -> Tuple[bool, str]:
    gold_total = int(candidate_metrics.get("gold_total", 0) or 0)
    coverage = int(candidate_metrics.get("coverage", 0) or 0)
    warnings: List[str] = []
    if gold_total > 0 and coverage != gold_total:
        warnings.append(f"coverage_incomplete:{coverage}/{gold_total}")
    trace_error_count = int(candidate_metrics.get("trace_error_count", 0) or 0)
    if trace_error_count > 0:
        warnings.append(f"trace_errors_present:{trace_error_count}")

    p_delta = float(candidate_metrics.get("precision_yes", 0.0) or 0.0) - float(best_metrics.get("precision_yes", 0.0) or 0.0)
    recall_drop = float(best_metrics.get("recall_yes", 0.0) or 0.0) - float(candidate_metrics.get("recall_yes", 0.0) or 0.0)
    best_ny = int(best_metrics.get("ny", 0) or 0)
    cand_ny = int(candidate_metrics.get("ny", 0) or 0)
    if p_delta < 0.005 and recall_drop > 0.10:
        return False, "recall_drop_too_large_for_small_precision_gain"
    if cand_ny > max(best_ny + 5, int(best_ny * 1.5)) and p_delta < 0.01:
        return False, "ny_spike_without_meaningful_precision_gain"
    if warnings:
        return True, "passed_with_warnings:" + ",".join(warnings)
    return True, "passed"


def _print_promote_decision(
    *,
    round_index: int,
    best_metrics_before: Dict[str, Any],
    candidate_metrics: Dict[str, Any],
    better: bool,
    gate_ok: bool,
    gate_reason: str,
    auto_promote_enabled: bool,
    promoted: bool,
    promotion_reason: str,
) -> None:
    def _metric_text(metrics: Dict[str, Any]) -> str:
        return (
            f"p={float(metrics.get('precision_yes', 0.0) or 0.0):.4f} "
            f"f1={float(metrics.get('f1_yes', 0.0) or 0.0):.4f} "
            f"r={float(metrics.get('recall_yes', 0.0) or 0.0):.4f} "
            f"ny={int(metrics.get('ny', 0) or 0)} "
            f"coverage={int(metrics.get('coverage', 0) or 0)}/{int(metrics.get('gold_total', 0) or 0)} "
            f"errors={int(metrics.get('trace_error_count', 0) or 0)}"
        )

    _print_detail(f"[promote-check] round={round_index:03d}")
    _print_detail(f"best_before: {_metric_text(best_metrics_before)}")
    _print_detail(f"candidate:   {_metric_text(candidate_metrics)}")
    _print_detail(
        "decision: "
        f"better={'yes' if better else 'no'} "
        f"gate={'pass' if gate_ok else 'reject'} "
        f"auto_promote={'on' if auto_promote_enabled else 'off'} "
        f"promoted={'yes' if promoted else 'no'}"
    )
    _print_detail(f"reason: {promotion_reason} (gate={gate_reason})")
