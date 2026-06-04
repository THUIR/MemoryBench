# Contributing to MemoryBench

This guide explains how to extend MemoryBench with new memory-system
baselines or new datasets. Both extension points are designed to be
single-file changes plus one registry entry — the rest of the system
(CLI argparse, run scripts, frontend dropdowns, evaluation pipeline)
picks the new entry up automatically.

If you only skim one section, read the **Mental model** first.

---

## Mental model

MemoryBench is composed of three loosely-coupled layers:

```
                 +--------------------+
   datasets  ──▶ |  src/dataset/*.py  | ──▶ load_memory_bench() / evaluate()
                 +--------------------+

                 +-------------------+    +-------------------+
   baselines ──▶ |  src/agent/*.py   | ── |  src/solver/*.py  | ──▶ runners (off-policy, on-policy, ...)
                 +-------------------+    +-------------------+

                 +----------------------+
   registry  ──▶ |  src/memory_systems  | ──▶ SolverFactory, get_dialog_key,
                 +----------------------+      argparse choices, frontend dropdowns
```

Two integration points decide whether new code is picked up everywhere:

1. **Datasets** are listed in `configs/datasets/each.json` (plus
   `domain.json` / `task.json` for groupings) and instantiated through
   `BaseDataset` subclasses in `src/dataset/`.
2. **Memory-system baselines** register one `MemorySystemSpec` in
   [`src/memory_systems.py`](src/memory_systems.py) and provide an agent
   class + a solver class. Everything else flows from the spec — the
   CLI's `--memory_system` choices, the frontend's dropdown, the
   per-baseline config-file lookup, the `dialog_<name>` HF-dataset field,
   and the `mem0`-style skip rules for known-incompatible combos.

---

## Adding a new memory-system baseline

The steps below use generic `<name>` / `<Name>` placeholders for your
baseline. The existing baselines on `main` (`mem0`, `memoryos`, `a_mem`,
the `embedder_*` family) are good references to read alongside this guide.

### Step 1 — Vendor the upstream code (optional but recommended)

If your baseline depends on an external codebase (like `mem0`,
`MemoryOS`, or `A_mem`), clone the upstream repo into `baselines/` and
drop the nested `.git` so the outer repo can track the files:

```bash
cd baselines/
git clone --depth 1 https://github.com/<org>/<repo>.git <Name>
rm -rf <Name>/.git
git add <Name>
```

There are two patterns in `baselines/`, and the right choice depends on
whether your MemoryBench agent imports anything from the upstream code:

| Pattern | When to use it | Example |
|---|---|---|
| **Vendored & tracked.** Upstream source is committed in-tree; runs after a fresh `git clone`. | `src/agent/<name>.py` imports from `baselines/<Name>/` (so the source must be present). | `mem0`, `a_mem`, `memoryos`, `raptor` |
| **Reference-only mirror.** Upstream source is cloned locally for reading but `.gitignore`'d. | Your agent reimplements the algorithm in MemoryBench style and doesn't import from the upstream. | Keep the clone on your machine, list the folder in `.gitignore`, and note the upstream URL in [baselines/README.md](baselines/README.md). |

For the reference-only pattern, add the folder to the top-level
[`.gitignore`](.gitignore) so it doesn't pollute `git status`, and add a
short note to [`baselines/README.md`](baselines/README.md) pointing at
the upstream URL.

### Step 2 — Write the agent

The agent class encapsulates the memory store and the chat-completion
path. It must subclass `BaseAgent` and implement the surfaces below.
Each row notes which runner (off-policy / on-policy / stepwise) actually
calls it — that's what `tests/test_refactor.py::TestAllBaselinesContract`
enforces for every registered baseline.

| Method | Used by | Purpose |
|---|---|---|
| `add_conversation_to_memory(messages, conversation_idx)` | off-policy (bulk), on-policy (per-step), stepwise (per-batch) | Ingest a complete dialog. For on-policy this is called *every step* with a freshly generated dialog, so it must be re-entrant. |
| `retrieve_memory(query, k)` | called internally by `generate_response` | Return retrieved context, either as a list of strings or one assembled string. |
| `generate_response(messages, lang, retrieve_k)` | off-policy + on-policy first round (via `solver.predict_single_data`) | Run inference. Must accept both `lang` and an optional `retrieve_k` override. |
| `self.llm.generate_response(messages)` | on-policy follow-up rounds | The inner LLM client. Comes for free as long as you build it via `LlmFactory.create(...)`. |
| `save_memories()` / `load_memories()` | `BaseSolver._create_or_load_memory` | Persist / rehydrate the store across runs. The cache dir is `config.memory_cache_dir`. |

Pydantic config goes in the same file. Use `Literal["openai", "vllm", "anthropic"]`
for `llm_provider` if your agent routes through `LlmFactory`; pin it to
`Literal["openai", "vllm"]` if it wires to an upstream provider
abstraction that doesn't understand Anthropic.

Patterns worth borrowing from the existing agents in [`src/agent/`](src/agent/):

- **Vector store + summary embedding.** Embedding an LLM-generated
  summary of each chunk (denser, more queryable) usually retrieves better
  than embedding raw turns.
- **FIFO working memory.** A `collections.deque(maxlen=N)` makes
  bounded-size recent-turn retention free.
- **Defensive embedding loop.** When you pipe long texts at vllm/openai
  embeddings, the body sometimes exceeds the token limit — shrink-and-retry
  (see `_embed` in [`src/agent/embedder.py`](src/agent/embedder.py)).

### Step 3 — Write the solver

The solver is a thin wrapper over the agent that orchestrates ingestion.
For non-corpus datasets it just delegates to `BaseSolver._create_or_load_memory`,
but for corpus datasets (LoCoMo, DialSim) it must implement
`memory_<corpus_format>_conversation`.

Minimum body:

```python
from src.agent.<name> import <Name>Agent, <Name>AgentConfig
from src.solver.base import BaseSolver

class <Name>Solver(BaseSolver):
    AGENT_CLASS = <Name>Agent

    def __init__(self, config, memory_cache_dir):
        super().__init__(config, memory_cache_dir)
        self.method_name = "<Name>"

    def create_or_load_memory(self, dialogs):
        return super()._create_or_load_memory(dialogs, can_thread=False)

    def memory_locomo_conversation(self, conversation, session_cnt):
        ...  # ingest one session at a time

    def memory_dialsim_conversation(self, conversation, session_cnt):
        return self.memory_locomo_conversation(conversation, session_cnt)
```

If you don't ship a `memory_<format>_conversation` for a corpus format,
`load_corpus_to_memory` will raise `NotImplementedError` when someone
runs your baseline on a Locomo/DialSim dataset. That's the right
behavior — failing fast is better than silently skipping the corpus.

For full references, read the existing solvers under [`src/solver/`](src/solver/).

### Step 4 — Default config

Drop a JSON file under `configs/memory_systems/<name>.json` with the
fields your `<Name>AgentConfig` expects. The existing files under
[`configs/memory_systems/`](configs/memory_systems/) are good templates.

### Step 5 — Register in the central registry

Add one entry to [`src/memory_systems.py`](src/memory_systems.py):

```python
register(MemorySystemSpec(
    name="<name>",
    solver_class="src.solver.<name>.<Name>Solver",
    config_class="src.solver.<name>.<Name>AgentConfig",
    config_file="configs/memory_systems/<name>.json",
    paper_name="<Name>",
    # Optional fields:
    # dialog_stem="my_stem"  # → field name "dialog_my_stem" on HF rows;
    #                        # defaults to "dialog_<name>".
    # skip_combinations=[("domain", "Open-Domain"), ("task", "Long-Short")],
))
```

That's it. The registry entry now drives:

- `--memory_system <name>` is accepted by every runner
- `run_scripts/*.py` includes `<name>` in its outer loop
- `SolverFactory.create("<name>", config, ...)` resolves to your classes
- `get_memory_system_config_file("<name>")` returns the JSON path
- `get_dialog_key("<name>")` returns the right field name
- The Streamlit frontend's "Memory system" dropdown lists `<name>`

### Step 6 — Eager-import the config class

This is purely a compatibility step so external code that does
`from src.solver import <Name>AgentConfig` keeps working, and so
missing baseline deps surface immediately at startup:

Edit [`src/solver/__init__.py`](src/solver/__init__.py) and add:

```python
from src.solver.<name> import <Name>AgentConfig
```

next to the other eager imports. Skip this step only if your baseline
has heavy optional dependencies you want to keep lazy.

### Step 7 — Wire frontend hints (only if you need an embedder)

If your baseline consumes a text-embedding model (like `mem0` and the
`embedder_*` family do), add it to `_BASELINES_NEED_EMBEDDER` in
[`frontend/streamlit_app.py`](frontend/streamlit_app.py).
The frontend will auto-show the Embedder section when your baseline is selected.

If your baseline can't use the Anthropic provider (e.g. it routes
through an upstream LLM client that doesn't speak Anthropic), add it to
`_BASELINES_NO_ANTHROPIC` so the provider dropdown drops the option
when your baseline is selected.

### Step 8 — Generate `dialog_<name>` fields (corpus baselines only)

Off-policy experiments read **pre-generated** training dialogs from the
HF dataset under the field `dialog_<name>`. For a fresh baseline this
field doesn't exist yet on `THUIR/MemoryBench`. To create it:

```bash
python -m src.generate_dialogs.reading \
    --memory_system <name> \
    --dataset Locomo-0
```

Run that for every Locomo + DialSim split. The script writes new
dialogs to your local cache; you'll need to re-upload them to the
dataset (or distribute them separately) for other users to run
off-policy on your baseline.

For non-corpus datasets the `dialog` field is shared across baselines,
so no re-generation is needed.

### Step 9 — Verify

The repo ships a registry-driven test suite at
[`tests/test_refactor.py`](tests/test_refactor.py). Add your baseline
to the `LEGACY_*` oracle dicts at the top of the file, then run:

```bash
python -m unittest tests.test_refactor -v
```

Adding a new entry to the oracles is a regression catch: if the
registry's `dialog_key()` ever drifts from what runner scripts expect,
this test fails immediately.

For a smoke-test that doesn't need an LLM, you can build the agent
with a dummy provider and exercise `add_memory` / `retrieve_memory`
offline:

```python
from src.agent.<name> import <Name>Agent, <Name>AgentConfig
cfg = <Name>AgentConfig(
    llm_provider="openai",
    llm_config={"model": "noop", "api_key": "noop"},
    embedder_provider="openai",
    embedder_base_url="http://127.0.0.1:1/v1",
    memory_cache_dir="/tmp/<name>-smoke",
    # disable any options that would trigger live LLM calls
)
agent = <Name>Agent(cfg)
```

---

## Adding a new dataset

### Non-corpus dataset (e.g. JRE-L, WritingPrompts)

If your dataset is "one input → one expected output", with no
multi-session conversation corpus, you only need a `BaseDataset`
subclass and a config entry.

### Step 1 — Subclass `BaseDataset`

Put `src/dataset/<MyDataset>.py`:

```python
from typing import Any, Dict, List
from src.dataset.base import BaseDataset

class MyDataset(BaseDataset):
    def __init__(
        self,
        data_path: str = None,
        dataset_name: str = "MyDataset",
        test_metrics: List[str] = ("accuracy",),
        max_output_len: int = 2048,
        eval_mode: bool = True,
    ):
        self.dataset_name = dataset_name
        super().__init__(
            data_path=data_path,
            test_metrics=list(test_metrics),
            max_output_len=max_output_len,
        )

    def evaluate_single(
        self,
        user_prompt: str,
        info: Dict[str, Any],
        llm_response: str,
    ) -> Dict[str, float]:
        # Return a dict containing every key in `self.test_metrics`.
        return {"accuracy": float(...)}
```

Required row shape on the underlying HF dataset (returned by
`load_from_hf`): each row must contain `test_idx`, `dataset_name`,
`info`, `lang`, and either `input_prompt` (string) or
`input_chat_messages` (list of role/content dicts). `BaseDataset`
asserts these in its constructor.

### Step 2 — Register in `configs/datasets/each.json`

Add one entry:

```json
"MyDataset": {
    "dataset_name": "MyDataset",
    "task_tag": "Short-Short",
    "domain_tag": "Open-Domain",
    "test_metrics": ["accuracy"],
    "max_output_len": 2048,
    "class_name": "MyDataset.MyDataset"
}
```

The `class_name` is `<file_stem>.<class_name>` resolved against
`src/dataset/`. If you also want the dataset to participate in domain-
or task-level evaluations, add the same block (with optional
`sample_count`) to `configs/datasets/domain.json` / `task.json`.

### Step 3 — Normalization stats (only for domain/task experiments)

`summary_results(dataset_type="domain", ...)` needs per-dataset
min/max/mu/sigma in
`configs/final_evaluate_summary_wo_details.json`. The simplest way is
to run all baselines on your new dataset first and let
`src/single_summary.py` / `src/summary_evaluate_result.py` regenerate
this file.

### Step 4 — Verify

```python
from memorybench import load_memory_bench, evaluate, summary_results

ds = load_memory_bench("single", "MyDataset", eval_mode=True)
print(ds.dataset_name, len(ds.dataset["train"]), len(ds.dataset["test"]))

predicts = [
    {"test_idx": int(row["test_idx"]), "response": "...", "dataset": "MyDataset"}
    for row in ds.dataset["test"]
]
details = evaluate("single", "MyDataset", predicts)
summary = summary_results("single", "MyDataset", predicts, details)
print(summary["summary"])
```

### Corpus dataset (LoCoMo-style)

For datasets that ship a multi-session conversation corpus you need a
few extra hooks.

#### Step 1 — Set the class attribute

```python
class MyCorpusDataset(BaseDataset):
    corpus_format = "my_corpus"          # used to route to per-solver methods
    summary_group_name = "MyCorpus"      # optional: collapse "MyCorpus-0..9"
                                         # under one normalization key
```

`corpus_format` is the dispatch key. When someone calls
`load_corpus_to_memory(solver, dataset)`, MemoryBench invokes
`solver.memory_my_corpus_conversation(corpus, session_cnt=...)`.

#### Step 2 — Update `src/dataset/utils.py`'s `load_from_hf`

The default loader handles LoCoMo and DialSim corpus shapes. For a
new corpus shape, extend `load_from_hf` (or override `_load_data` in
your subclass) to populate `dataset.corpus` and `dataset.session_cnt`.

The dataset class should set `self.has_corpus = True` on
its instance — that's already done by `BaseDataset._load_data` when
the loader returns a non-None corpus.

#### Step 3 — Implement `memory_<format>_conversation` on every solver

Each baseline you want to support on this dataset needs a
`memory_<corpus_format>_conversation(corpus, session_cnt)` method on
its solver class. This is the only per-baseline code change required
to onboard a new corpus shape — and it's why MemoryBench keeps the
corpus-loading API attribute-driven rather than dataset-name-driven.

If a baseline doesn't implement it, `load_corpus_to_memory` raises
`NotImplementedError` at runtime.

#### Step 4 — Generate per-baseline training dialogs (optional)

Run `python -m src.generate_dialogs.reading --dataset MyCorpus-0 --memory_system <baseline>`
to materialize `dialog_<baseline>` fields. This is only required for
off-policy / stepwise-off-policy experiments; on-policy generates
dialogs at runtime.

---

## Project conventions worth knowing

- **Don't add parallel hardcoded dicts.** Every method-name list lives
  in the registry. New baselines must not introduce a "list of all
  memory systems" anywhere else. The CI test
  [`tests/test_refactor.py::TestRegistry`](tests/test_refactor.py)
  catches drift.
- **Don't string-match on dataset names.** Use `dataset.corpus_format`
  and `dataset.summary_group_name` instead of
  `dataset.dataset_name.startswith("Locomo")`.
- **Don't commit secrets.** `API_config.json`, `.env*` (except
  `.env.example`), and `frontend/runtime_configs/` are all gitignored —
  see [`.gitignore`](.gitignore). The audit done in
  [`tests/test_refactor.py::TestOptionalLLMPing`](tests/test_refactor.py)
  also avoids printing tokens in failure messages.
- **Defaults should not require a paid API.** Default configs in
  `configs/memory_systems/*.json` point at vllm/local endpoints. If
  your baseline needs an OpenAI/Anthropic key, document it but don't
  hardcode it.
- **TinyDataset is the smoke-test target.** It lives outside the repo
  at `../TinyDataset/` and contains 3 train + 2 test rows per dataset.
  Set `MEMORY_BENCH_PATH=../TinyDataset` to develop without
  downloading the full 200 MB hub dataset.

---

## Where to start reading the code

| If you want to... | Read these files in this order |
|---|---|
| Add a memory baseline | [`src/memory_systems.py`](src/memory_systems.py) → [`src/agent/embedder.py`](src/agent/embedder.py) → [`src/solver/embedder.py`](src/solver/embedder.py) → [`src/solver/base.py`](src/solver/base.py) |
| Add a dataset | [`src/dataset/base.py`](src/dataset/base.py) → [`src/dataset/Locomo.py`](src/dataset/Locomo.py) → [`src/dataset/utils.py`](src/dataset/utils.py) |
| Understand the evaluation pipeline | [`memorybench.py`](memorybench.py) → [`src/dataset/base.py`](src/dataset/base.py) (`evaluate`, `evaluate_test`) |
| Understand how runners are wired | [`src/off-policy.py`](src/off-policy.py) → [`src/solver/base.py`](src/solver/base.py) (`predict_test`, `predict_test_with_corpus`) |
| Understand frontend wiring | [`frontend/streamlit_app.py`](frontend/streamlit_app.py) (`run_page`, `build_runtime_memory_config`) |
