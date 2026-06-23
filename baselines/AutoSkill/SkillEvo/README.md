# SkillEvo

`SkillEvo` is a replay-driven skill self-evolution runner for AutoSkill.

It does not modify `autoskill/` or write back to the main `SkillBank`.
It reads:

- online skill provenance
- offline conversation provenance
- offline requirement stats
- current skill snapshots from `SkillBank`

Then it runs a local self-evolution loop:

1. build a frozen replay pool for one skill lineage
2. compile 3-6 binary eval rules
3. generate small mutations under a fixed budget
4. evaluate on `mutate_dev`
5. promote only if the candidate beats the current SkillEvo champion on `promotion_test`

## Layout

```text
SkillEvo/
  registry/
  datasets/
  evals/
  runs/
  champions/
  reports/
```

## Commands

Build replay:

```bash
python3 -m SkillEvo.cli build-replay --user-id u1 --skill-id <skill_id>
```

Compile evals:

```bash
python3 -m SkillEvo.cli compile-evals --user-id u1 --skill-id <skill_id>
```

Run the full self-evolution loop:

```bash
python3 -m SkillEvo.cli run --user-id u1 --skill-id <skill_id>
```

Run one stored skill with a real LLM on one replay sample:

```bash
python3 -m SkillEvo.run_one_skill_with_llm \
  --user-id WildChat_4.8M_qwen \
  --skill-id 2158daa6-570a-485f-8e0b-ea0a1e1632e5 \
  --llm-provider dashscope \
  --llm-model qwen-plus \
  --sample-split mutate_dev \
  --sample-index 0
```

Run one stored skill on ad-hoc input:

```bash
python3 -m SkillEvo.run_one_skill_with_llm \
  --user-id WildChat_4.8M_qwen \
  --skill-id 2158daa6-570a-485f-8e0b-ea0a1e1632e5 \
  --llm-provider dashscope \
  --llm-model qwen-plus \
  --custom-input 'input_template：请看这个句子：{{sentence}}，这句话里有没有人名？'
```

Run the full autoresearch loop with real LLMs:

```bash
python3 -m SkillEvo.run_autoresearch_skill \
  --user-id WildChat_4.8M_qwen \
  --skill-id 2158daa6-570a-485f-8e0b-ea0a1e1632e5 \
  --llm-provider dashscope \
  --llm-model qwen-plus \
  --judge-provider dashscope \
  --judge-model qwen-plus \
  --mutation-mode hybrid \
  --mutation-budget 6 \
  --min-replay-samples 2
```

## Current MVP

Implemented:

- online replay reconstruction from stored `history[].messages`
- offline replay reconstruction via `source_file + conversation_index`
- lineage registry and replay dataset persistence
- heuristic eval compilation from prompt + requirement stats
- programmatic + judge-LLM binary rule engine
- heuristic mutations plus optional LLM-guided mutation
- local champion registry under `SkillEvo/champions/`

Not implemented yet:

- retrieval-only evals
- automatic write-back into the main `SkillBank`
- large-scale tournament scheduling across many lineages

## Notes

- If replay data is too small, the runner keeps the lineage in `incubating`.
- The default config uses the AutoSkill store at `./SkillBank`.
- TOML config loading is optional; when TOML support is unavailable the default config still works.
