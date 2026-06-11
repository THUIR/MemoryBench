from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Tuple

from .config import load_skillevo_config
from .io_utils import ensure_dir, write_json, write_jsonl
from .registry import (
    ensure_evo_layout,
    get_champion,
    lineage_eval_dir,
    lineage_run_dir,
)
from .runner import SkillEvoRunner


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run the full SkillEvo self-evolution loop with real LLMs: replay, eval, mutate, compare, promote."
    )
    p.add_argument("--config", default="", help="Optional SkillEvo TOML config path.")
    p.add_argument("--user-id", required=True, help="Skill owner user_id.")
    p.add_argument("--skill-id", required=True, help="Stored skill_id under SkillBank.")

    p.add_argument("--llm-provider", required=True, help="Responder LLM provider, e.g. dashscope/openai/glm.")
    p.add_argument("--llm-model", required=True, help="Responder LLM model.")
    p.add_argument("--llm-api-key", default="", help="Optional responder API key override.")
    p.add_argument("--llm-base-url", default="", help="Optional responder base_url override.")
    p.add_argument("--llm-response", default="", help="Optional fixed mock response when provider=mock.")

    p.add_argument("--mutator-provider", default="", help="Optional mutator LLM provider. Defaults to responder.")
    p.add_argument("--mutator-model", default="", help="Optional mutator LLM model.")
    p.add_argument("--mutator-api-key", default="", help="Optional mutator API key override.")
    p.add_argument("--mutator-base-url", default="", help="Optional mutator base_url override.")
    p.add_argument("--mutator-response", default="", help="Optional fixed mock response when mutator provider=mock.")

    p.add_argument("--judge-provider", default="", help="Optional judge LLM provider. Defaults to responder.")
    p.add_argument("--judge-model", default="", help="Optional judge LLM model.")
    p.add_argument("--judge-api-key", default="", help="Optional judge API key override.")
    p.add_argument("--judge-base-url", default="", help="Optional judge base_url override.")
    p.add_argument("--judge-response", default="", help="Optional fixed mock response when judge provider=mock.")

    p.add_argument("--llm-timeout-s", type=int, default=120, help="HTTP timeout in seconds for all LLM clients.")
    p.add_argument("--mutation-mode", choices=["heuristic", "llm", "hybrid"], default="hybrid")
    p.add_argument("--mutation-budget", type=int, default=6)
    p.add_argument("--replay-limit", type=int, default=24)
    p.add_argument("--min-replay-samples", type=int, default=2)
    p.add_argument("--dev-split-ratio", type=float, default=0.7)
    p.add_argument("--mutate-repeats", type=int, default=1)
    p.add_argument("--promotion-repeats", type=int, default=1)
    p.add_argument("--min-score-delta", type=float, default=0.05)
    p.add_argument("--max-eval-rules", type=int, default=6)
    p.add_argument("--response-max-chars", type=int, default=20000)
    p.add_argument("--json-only", action="store_true", help="Suppress stage logs and print only the final JSON report.")
    return p


def _build_llm_config(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    response: str,
    timeout_s: int,
) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
        "timeout_s": int(timeout_s or 120),
    }
    if str(api_key or "").strip():
        cfg["api_key"] = str(api_key).strip()
    if str(base_url or "").strip():
        cfg["base_url"] = str(base_url).strip()
    if str(response or ""):
        cfg["response"] = str(response)
    return cfg


def _pick_optional_llm_config(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    response: str,
    timeout_s: int,
) -> Dict[str, Any] | None:
    if not str(provider or "").strip():
        return None
    return _build_llm_config(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        response=response,
        timeout_s=timeout_s,
    )


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=sys.stderr, flush=True)


def _llm_meta(cfg: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    return {
        "provider": str(cfg.get("provider") or ""),
        "model": str(cfg.get("model") or ""),
        "base_url": str(cfg.get("base_url") or ""),
    }


def _top_rule_ids(rules: List[Any]) -> List[str]:
    return [str(rule.rule_id) for rule in rules]


def _variant_brief(summary: Any) -> Dict[str, Any]:
    return {
        "variant_id": str(summary.variant_id),
        "label": str(summary.label),
        "split": str(summary.split),
        "sample_count": int(summary.sample_count),
        "average_score": float(summary.average_score),
        "hard_failures": int(summary.hard_failures),
        "passed_rules": int(summary.passed_rules),
        "total_rules": int(summary.total_rules),
    }


def _save_run_artifacts(
    *,
    runner: SkillEvoRunner,
    lineage_id: str,
    run_id: str,
    report: Dict[str, Any],
    all_outputs: List[Dict[str, Any]],
    all_judgments: List[Dict[str, Any]],
) -> Dict[str, str]:
    run_dir = lineage_run_dir(runner.config, lineage_id, run_id)
    ensure_dir(run_dir)
    outputs_path = run_dir / "outputs.jsonl"
    judgments_path = run_dir / "judgments.jsonl"
    summary_path = run_dir / "summary.json"
    write_jsonl(outputs_path, all_outputs)
    write_jsonl(judgments_path, all_judgments)
    write_json(summary_path, report)
    return {
        "run_dir": str(run_dir),
        "outputs_path": str(outputs_path),
        "judgments_path": str(judgments_path),
        "summary_path": str(summary_path),
    }


def main() -> None:
    args = _parser().parse_args()
    responder_cfg = _build_llm_config(
        provider=args.llm_provider,
        model=args.llm_model,
        api_key=args.llm_api_key,
        base_url=args.llm_base_url,
        response=args.llm_response,
        timeout_s=args.llm_timeout_s,
    )
    mutator_cfg = _pick_optional_llm_config(
        provider=args.mutator_provider,
        model=(args.mutator_model or args.llm_model),
        api_key=args.mutator_api_key,
        base_url=args.mutator_base_url,
        response=args.mutator_response,
        timeout_s=args.llm_timeout_s,
    )
    judge_cfg = _pick_optional_llm_config(
        provider=args.judge_provider,
        model=(args.judge_model or args.llm_model),
        api_key=args.judge_api_key,
        base_url=args.judge_base_url,
        response=args.judge_response,
        timeout_s=args.llm_timeout_s,
    )

    overrides: Dict[str, Any] = {
        "llm": responder_cfg,
        "mutator_llm": mutator_cfg,
        "judge_llm": judge_cfg,
        "mutation_mode": args.mutation_mode,
        "mutation_budget": int(args.mutation_budget),
        "replay_limit": int(args.replay_limit),
        "min_replay_samples": int(args.min_replay_samples),
        "dev_split_ratio": float(args.dev_split_ratio),
        "mutate_repeats": int(args.mutate_repeats),
        "promotion_repeats": int(args.promotion_repeats),
        "min_score_delta": float(args.min_score_delta),
        "max_eval_rules": int(args.max_eval_rules),
        "response_max_chars": int(args.response_max_chars),
    }
    config = load_skillevo_config(path=(args.config or None), overrides=overrides)
    runner = SkillEvoRunner(config=config)
    log_enabled = not bool(args.json_only)

    ensure_evo_layout(config)
    timing: Dict[str, float] = {}

    stage_t0 = time.perf_counter()
    _log(log_enabled, "[1/6] building replay pool")
    lineage, skill_snapshot, samples, online_record, offline_record = runner.replay_builder.build_for_skill(
        user_id=str(args.user_id),
        skill_id=str(args.skill_id),
        max_samples=int(args.replay_limit),
    )
    timing["build_replay_s"] = round(time.perf_counter() - stage_t0, 4)
    dev_samples = [x for x in samples if x.split == "mutate_dev"]
    test_samples = [x for x in samples if x.split == "promotion_test"]
    _log(
        log_enabled,
        f"  replay: total={len(samples)} dev={len(dev_samples)} test={len(test_samples)} online={len(list(online_record.get('history') or []))} offline={len(list(offline_record.get('history') or []))}",
    )

    stage_t0 = time.perf_counter()
    _log(log_enabled, "[2/6] compiling eval rules")
    eval_rules = runner.eval_compiler.compile(skill=skill_snapshot, lineage=lineage)
    eval_dir = lineage_eval_dir(config, lineage.lineage_id)
    ensure_dir(eval_dir)
    write_json(eval_dir / "eval_spec.json", {"rules": [x.to_dict() for x in eval_rules]})
    timing["compile_evals_s"] = round(time.perf_counter() - stage_t0, 4)
    _log(log_enabled, f"  eval rules ({len(eval_rules)}): {', '.join(_top_rule_ids(eval_rules)) or 'none'}")

    champion_item = get_champion(config, lineage.lineage_id)
    champion_snapshot = runner._snapshot_from_registry(champion_item) or skill_snapshot
    champion_variant = runner._variant_from_snapshot(
        lineage_id=lineage.lineage_id,
        snapshot=champion_snapshot,
        label=("current_champion" if champion_item else "baseline"),
        mutation_type=("active_evo" if champion_item else "baseline"),
        notes=("Loaded from SkillEvo champion registry." if champion_item else "Current SkillBank version."),
    )
    baseline_variant = runner._variant_from_snapshot(
        lineage_id=lineage.lineage_id,
        snapshot=skill_snapshot,
        label="baseline",
        mutation_type="baseline",
        notes="Current SkillBank snapshot.",
    )

    stage_t0 = time.perf_counter()
    _log(log_enabled, "[3/6] evaluating baseline on mutate_dev")
    baseline_dev_eval, baseline_dev_summary = runner._evaluate_variant(
        variant=baseline_variant,
        samples=dev_samples,
        rules=eval_rules,
        split="mutate_dev",
        repeats=config.mutate_repeats,
    )
    timing["baseline_dev_s"] = round(time.perf_counter() - stage_t0, 4)
    _log(
        log_enabled,
        f"  baseline: avg={baseline_dev_summary.average_score:.3f} hard_failures={baseline_dev_summary.hard_failures} passed={baseline_dev_summary.passed_rules}/{baseline_dev_summary.total_rules}",
    )

    stage_t0 = time.perf_counter()
    _log(log_enabled, "[4/6] generating mutation candidates")
    failing_samples = runner._pick_failing_samples(sample_evals=baseline_dev_eval, replay_samples=dev_samples)
    candidate_variants = runner.variant_generator.generate(
        lineage_id=lineage.lineage_id,
        base=skill_snapshot,
        eval_rules=eval_rules,
        failing_samples=failing_samples,
    )
    timing["generate_mutations_s"] = round(time.perf_counter() - stage_t0, 4)
    _log(log_enabled, f"  mutations: {len(candidate_variants)} candidates")

    stage_t0 = time.perf_counter()
    _log(log_enabled, "[5/6] evaluating candidates on mutate_dev")
    variant_summaries: List[Dict[str, Any]] = [baseline_dev_summary.to_dict()]
    all_outputs: List[Dict[str, Any]] = [x.to_dict() for x in baseline_dev_eval]
    all_judgments: List[Dict[str, Any]] = runner._flatten_judgments(baseline_dev_eval)
    scored_candidates: List[Tuple[Any, Any, Any]] = []
    candidate_dev_summaries: List[Dict[str, Any]] = []
    for idx, variant in enumerate(candidate_variants, start=1):
        sample_evals, summary = runner._evaluate_variant(
            variant=variant,
            samples=dev_samples,
            rules=eval_rules,
            split="mutate_dev",
            repeats=config.mutate_repeats,
        )
        scored_candidates.append((variant, summary, sample_evals))
        candidate_dev_summaries.append(summary.to_dict())
        variant_summaries.append(summary.to_dict())
        all_outputs.extend(x.to_dict() for x in sample_evals)
        all_judgments.extend(runner._flatten_judgments(sample_evals))
        _log(
            log_enabled,
            f"  candidate[{idx}] {variant.label}: avg={summary.average_score:.3f} hard_failures={summary.hard_failures}",
        )
    best_variant, best_dev_summary = runner._pick_best_variant(
        baseline_variant=baseline_variant,
        baseline_summary=baseline_dev_summary,
        scored_candidates=scored_candidates,
    )
    timing["evaluate_candidates_s"] = round(time.perf_counter() - stage_t0, 4)
    _log(log_enabled, f"  best dev variant: {best_variant.label} ({best_variant.variant_id})")

    stage_t0 = time.perf_counter()
    _log(log_enabled, "[6/6] promotion test against current champion")
    champion_test_eval, champion_test_summary = runner._evaluate_variant(
        variant=champion_variant,
        samples=test_samples,
        rules=eval_rules,
        split="promotion_test",
        repeats=config.promotion_repeats,
    )
    best_test_eval, best_test_summary = runner._evaluate_variant(
        variant=best_variant,
        samples=test_samples,
        rules=eval_rules,
        split="promotion_test",
        repeats=config.promotion_repeats,
    )
    all_outputs.extend(x.to_dict() for x in champion_test_eval)
    all_outputs.extend(x.to_dict() for x in best_test_eval)
    all_judgments.extend(runner._flatten_judgments(champion_test_eval))
    all_judgments.extend(runner._flatten_judgments(best_test_eval))
    insufficient_replay = bool(
        len(samples) < int(config.min_replay_samples) or not dev_samples or not test_samples
    )
    promoted = (not insufficient_replay) and runner._should_promote(
        champion=champion_test_summary,
        candidate=best_test_summary,
    )
    promotion_summary = {
        "promoted": bool(promoted),
        "status": ("incubating" if insufficient_replay else ("active_evo" if promoted else "rejected")),
        "champion_before": champion_test_summary.to_dict(),
        "candidate": best_test_summary.to_dict(),
        "min_score_delta": float(config.min_score_delta),
        "min_replay_samples": int(config.min_replay_samples),
    }
    if promoted:
        runner._persist_champion(lineage_id=lineage.lineage_id, variant=best_variant, promotion_summary=promotion_summary)
    timing["promotion_test_s"] = round(time.perf_counter() - stage_t0, 4)
    _log(
        log_enabled,
        f"  promotion: status={promotion_summary['status']} promoted={promotion_summary['promoted']} candidate_avg={best_test_summary.average_score:.3f} champion_avg={champion_test_summary.average_score:.3f}",
    )

    run_id = runner._run_id()
    report = {
        "run_id": run_id,
        "mode": "autoresearch_skill",
        "config": {
            "mutation_mode": config.mutation_mode,
            "mutation_budget": int(config.mutation_budget),
            "replay_limit": int(config.replay_limit),
            "min_replay_samples": int(config.min_replay_samples),
            "mutate_repeats": int(config.mutate_repeats),
            "promotion_repeats": int(config.promotion_repeats),
            "min_score_delta": float(config.min_score_delta),
            "max_eval_rules": int(config.max_eval_rules),
            "llm": _llm_meta(responder_cfg),
            "mutator_llm": _llm_meta(mutator_cfg) or _llm_meta(responder_cfg),
            "judge_llm": _llm_meta(judge_cfg) or _llm_meta(responder_cfg),
        },
        "lineage": lineage.to_dict(),
        "baseline_variant": baseline_variant.to_dict(),
        "champion_variant": champion_variant.to_dict(),
        "candidate_variants": [x.to_dict() for x in candidate_variants],
        "eval_rules": [x.to_dict() for x in eval_rules],
        "baseline_dev_summary": baseline_dev_summary.to_dict(),
        "candidate_dev_summaries": candidate_dev_summaries,
        "best_dev_summary": best_dev_summary.to_dict(),
        "promotion": promotion_summary,
        "variant_summaries": variant_summaries,
        "replay_counts": {
            "total": len(samples),
            "mutate_dev": len(dev_samples),
            "promotion_test": len(test_samples),
        },
        "provenance": {
            "online_history_count": len(list(online_record.get("history") or [])),
            "offline_history_count": len(list(offline_record.get("history") or [])),
            "offline_source_count": len(list(offline_record.get("sources") or [])),
        },
        "timing_s": timing,
    }
    paths = _save_run_artifacts(
        runner=runner,
        lineage_id=lineage.lineage_id,
        run_id=run_id,
        report=report,
        all_outputs=all_outputs,
        all_judgments=all_judgments,
    )
    report["paths"] = paths
    write_json(lineage_run_dir(config, lineage.lineage_id, run_id) / "summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
