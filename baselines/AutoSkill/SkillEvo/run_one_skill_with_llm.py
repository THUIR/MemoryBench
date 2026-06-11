from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_skillevo_config
from .evals import EvalCompiler, RuleEngine
from .models import ReplaySample
from .replay_builder import ReplayBuilder
from .sdk import build_evo_llm, build_evo_sdk


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run one stored skill with a configured LLM on a replay sample or custom input."
    )
    p.add_argument("--config", default="", help="Optional SkillEvo TOML config path.")
    p.add_argument("--user-id", required=True, help="Skill owner user_id.")
    p.add_argument("--skill-id", required=True, help="Stored skill_id under SkillBank.")
    p.add_argument("--llm-provider", required=True, help="LLM provider name, e.g. dashscope/openai/glm.")
    p.add_argument("--llm-model", required=True, help="LLM model name, e.g. qwen-plus.")
    p.add_argument("--llm-api-key", default="", help="Optional API key override.")
    p.add_argument("--llm-base-url", default="", help="Optional base_url override.")
    p.add_argument("--llm-response", default="", help="Optional fixed mock response for provider=mock.")
    p.add_argument("--llm-timeout-s", type=int, default=120, help="HTTP timeout in seconds.")
    p.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature.")
    p.add_argument(
        "--sample-split",
        choices=["mutate_dev", "promotion_test", "any"],
        default="mutate_dev",
        help="Replay split to sample from when using stored replay data.",
    )
    p.add_argument("--sample-id", default="", help="Exact replay sample_id to run.")
    p.add_argument("--sample-index", type=int, default=0, help="Replay sample index after split filtering.")
    p.add_argument("--custom-input", default="", help="Run the skill on one ad-hoc user input instead of replay.")
    p.add_argument(
        "--messages-file",
        default="",
        help="Optional JSON file containing full chat messages. Overrides --custom-input when provided.",
    )
    p.add_argument("--evaluate", action="store_true", help="Also compile and run SkillEvo eval rules on the output.")
    p.add_argument(
        "--judge-provider",
        default="",
        help="Optional separate judge LLM provider. Defaults to the responder LLM when omitted.",
    )
    p.add_argument("--judge-model", default="", help="Optional separate judge LLM model.")
    p.add_argument("--judge-api-key", default="", help="Optional separate judge API key override.")
    p.add_argument("--judge-base-url", default="", help="Optional separate judge base_url override.")
    p.add_argument("--judge-response", default="", help="Optional fixed mock response for judge provider=mock.")
    p.add_argument(
        "--print-instructions",
        action="store_true",
        help="Include the full skill instructions in the JSON output.",
    )
    return p


def _llm_config_from_args(
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


def _normalize_messages(items: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if not role or not content.strip():
            continue
        out.append({"role": role, "content": content})
    return out


def _load_messages_from_file(path: str) -> List[Dict[str, str]]:
    raw = Path(path).read_text(encoding="utf-8")
    obj = json.loads(raw)
    messages = _normalize_messages(obj)
    if not messages:
        raise ValueError(f"messages file has no valid chat messages: {path}")
    return messages


def _build_ad_hoc_sample(*, user_id: str, skill_id: str, lineage_id: str, messages: List[Dict[str, str]]) -> ReplaySample:
    return ReplaySample(
        sample_id="ad-hoc",
        lineage_id=lineage_id,
        user_id=user_id,
        skill_id=skill_id,
        source_type="adhoc",
        split="mutate_dev",
        messages=messages,
        events=[],
        version_anchor="",
        provenance_ref={"mode": "adhoc"},
        tags=["adhoc"],
    )


def _select_replay_sample(
    *,
    samples: List[ReplaySample],
    sample_split: str,
    sample_id: str,
    sample_index: int,
) -> ReplaySample:
    filtered = list(samples)
    if sample_split != "any":
        filtered = [x for x in filtered if x.split == sample_split]
    if not filtered:
        raise ValueError(f"no replay samples available for split={sample_split}")
    if sample_id:
        for sample in filtered:
            if sample.sample_id == sample_id:
                return sample
        raise ValueError(f"sample_id not found in filtered replay set: {sample_id}")
    if sample_index < 0 or sample_index >= len(filtered):
        raise ValueError(f"sample_index out of range: {sample_index} (available={len(filtered)})")
    return filtered[sample_index]


def _format_conversation(messages: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for item in messages:
        role = str(item.get("role") or "").strip().lower() or "user"
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{role}] {content}")
    return "\n\n".join(lines).strip()


def _build_user_prompt(messages: List[Dict[str, str]]) -> str:
    return (
        "Replay the following conversation with the skill instructions already injected.\n\n"
        f"Conversation:\n{_format_conversation(messages)}\n\n"
        "Respond to the latest user message."
    )


def _choose_messages(args: argparse.Namespace, sample: Optional[ReplaySample]) -> List[Dict[str, str]]:
    if str(args.messages_file or "").strip():
        return _load_messages_from_file(str(args.messages_file))
    if str(args.custom_input or "").strip():
        return [{"role": "user", "content": str(args.custom_input)}]
    if sample is None:
        raise ValueError("custom input or replay sample is required")
    return list(sample.messages)


def main() -> None:
    args = _parser().parse_args()
    llm_cfg = _llm_config_from_args(
        provider=args.llm_provider,
        model=args.llm_model,
        api_key=args.llm_api_key,
        base_url=args.llm_base_url,
        response=args.llm_response,
        timeout_s=args.llm_timeout_s,
    )
    overrides: Dict[str, Any] = {"llm": llm_cfg}
    config = load_skillevo_config(path=(args.config or None), overrides=overrides)

    sdk = build_evo_sdk(config)
    replay_builder = ReplayBuilder(config=config, sdk=sdk)
    lineage, skill_snapshot, samples, _online, _offline = replay_builder.build_for_skill(
        user_id=str(args.user_id),
        skill_id=str(args.skill_id),
    )

    selected_sample: Optional[ReplaySample] = None
    if not str(args.messages_file or "").strip() and not str(args.custom_input or "").strip():
        selected_sample = _select_replay_sample(
            samples=samples,
            sample_split=str(args.sample_split),
            sample_id=str(args.sample_id),
            sample_index=int(args.sample_index),
        )

    messages = _choose_messages(args, selected_sample)
    ad_hoc_sample = None
    if selected_sample is None:
        ad_hoc_sample = _build_ad_hoc_sample(
            user_id=str(args.user_id),
            skill_id=str(args.skill_id),
            lineage_id=lineage.lineage_id,
            messages=messages,
        )

    responder_llm = build_evo_llm(llm_cfg)
    if responder_llm is None:
        raise ValueError("failed to build responder LLM")
    response_text = responder_llm.complete(
        system=skill_snapshot.instructions,
        user=_build_user_prompt(messages),
        temperature=float(args.temperature),
    )

    evaluation: Optional[Dict[str, Any]] = None
    if bool(args.evaluate):
        compiler = EvalCompiler(config=config, sdk=sdk)
        rules = compiler.compile(skill=skill_snapshot, lineage=lineage)
        judge_cfg = llm_cfg
        if str(args.judge_provider or "").strip():
            judge_cfg = _llm_config_from_args(
                provider=args.judge_provider,
                model=(args.judge_model or args.llm_model),
                api_key=args.judge_api_key,
                base_url=args.judge_base_url,
                response=args.judge_response,
                timeout_s=args.llm_timeout_s,
            )
        judge_llm = build_evo_llm(judge_cfg)
        engine = RuleEngine(judge_llm=judge_llm)
        eval_sample = selected_sample or ad_hoc_sample
        if eval_sample is None:
            raise ValueError("evaluation sample is missing")
        outcomes = [
            engine.evaluate(
                rule=rule,
                response_text=str(response_text or ""),
                sample=eval_sample,
                variant=skill_snapshot,
            )
            for rule in rules
        ]
        evaluation = {
            "rules": [rule.to_dict() for rule in rules],
            "outcomes": [outcome.to_dict() for outcome in outcomes],
            "total_score": float(sum(x.score for x in outcomes)),
            "hard_failures": int(sum(1 for x in outcomes if x.hard and not x.passed)),
        }

    result = {
        "lineage": lineage.to_dict(),
        "skill": {
            "skill_id": skill_snapshot.skill_id,
            "name": skill_snapshot.name,
            "description": skill_snapshot.description,
            "version": skill_snapshot.version,
        },
        "llm": {
            "provider": llm_cfg.get("provider"),
            "model": llm_cfg.get("model"),
            "base_url": llm_cfg.get("base_url", ""),
        },
        "selected_sample": (
            {
                "sample_id": selected_sample.sample_id,
                "split": selected_sample.split,
                "source_type": selected_sample.source_type,
                "version_anchor": selected_sample.version_anchor,
                "provenance_ref": selected_sample.provenance_ref,
            }
            if selected_sample is not None
            else {
                "sample_id": "ad-hoc",
                "split": "mutate_dev",
                "source_type": "adhoc",
                "version_anchor": "",
                "provenance_ref": {"mode": "adhoc"},
            }
        ),
        "messages": messages,
        "response_text": str(response_text or ""),
    }
    if args.print_instructions:
        result["skill"]["instructions"] = skill_snapshot.instructions
    if evaluation is not None:
        result["evaluation"] = evaluation
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
