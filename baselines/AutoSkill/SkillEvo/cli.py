from __future__ import annotations

import argparse
import json

from .config import load_skillevo_config
from .evals import EvalCompiler
from .replay_builder import ReplayBuilder
from .runner import SkillEvoRunner
from .sdk import build_evo_sdk


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SkillEvo: replay-driven skill self-evolution and evaluation.")
    p.add_argument("--config", default="", help="Optional SkillEvo TOML config path.")
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Build replay, compile evals, mutate, evaluate, and update the SkillEvo champion.")
    run_p.add_argument("--user-id", required=True)
    run_p.add_argument("--skill-id", required=True)

    replay_p = sub.add_parser("build-replay", help="Build frozen replay pool for one skill lineage.")
    replay_p.add_argument("--user-id", required=True)
    replay_p.add_argument("--skill-id", required=True)

    eval_p = sub.add_parser("compile-evals", help="Compile binary eval rules for one skill lineage.")
    eval_p.add_argument("--user-id", required=True)
    eval_p.add_argument("--skill-id", required=True)
    return p


def main() -> None:
    args = _parser().parse_args()
    overrides = {}
    config = load_skillevo_config(path=(args.config or None), overrides=overrides)

    if args.command == "run":
        runner = SkillEvoRunner(config=config)
        result = runner.run(user_id=str(args.user_id), skill_id=str(args.skill_id))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    sdk = build_evo_sdk(config)
    replay_builder = ReplayBuilder(config=config, sdk=sdk)
    lineage, skill_snapshot, samples, _online, _offline = replay_builder.build_for_skill(
        user_id=str(args.user_id),
        skill_id=str(args.skill_id),
    )
    if args.command == "build-replay":
        print(
            json.dumps(
                {
                    "lineage": lineage.to_dict(),
                    "skill": skill_snapshot.to_dict(),
                    "replay_count": len(samples),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "compile-evals":
        compiler = EvalCompiler(config=config, sdk=sdk)
        rules = compiler.compile(skill=skill_snapshot, lineage=lineage)
        print(json.dumps({"lineage": lineage.to_dict(), "rules": [x.to_dict() for x in rules]}, ensure_ascii=False, indent=2))
        return

    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
