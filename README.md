<h1 align="center">MemoryBench</h1>

<p align="center">
  <b>A standardized, extensible benchmark for memory and continual learning in LLM systems.</b>
</p>

<p align="center">
  <a href="https://huggingface.co/datasets/THUIR/MemoryBench">
    <img alt="HF Dataset" src="https://img.shields.io/badge/🤗%20Dataset-THUIR%2FMemoryBench-yellow">
  </a>
  <a href="https://huggingface.co/datasets/THUIR/MemoryBench-Full">
    <img alt="HF Dataset Full" src="https://img.shields.io/badge/🤗%20Dataset-Full-orange">
  </a>
  <a href="https://arxiv.org/abs/2510.17281">
    <img alt="arXiv" src="https://img.shields.io/badge/arXiv-2510.17281-b31b1b">
  </a>
  <a href="#license">
    <img alt="License" src="https://img.shields.io/badge/license-MIT-blue">
  </a>
  <a href="#citation">
    <img alt="ICML 2026" src="https://img.shields.io/badge/ICML-2026%20Spotlight-red">
  </a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-datasets">Datasets</a> •
  <a href="#-baselines">Baselines</a> •
  <a href="#-experiments">Experiments</a> •
  <a href="frontend/README.md">Frontend</a> •
  <a href="#-extending-memorybench">Extending</a> •
  <a href="#citation">Citation</a>
</p>

---

## 📢 News

- **2026-05-26** — 🌟 Accepted to **ICML 2026** as a **Spotlight paper**.
- **2026-04-15** — Streamlit frontend released. Configure and run experiments without touching any YAML. See [frontend/README.md](frontend/README.md).
- **2025-12-08** — Extended version released: [`THUIR/MemoryBench-Full`](https://huggingface.co/datasets/THUIR/MemoryBench-Full).
- **2025-12-05** — User-feedback simulator upgraded to `Mistral-Small-3.2-24B-Instruct-2506`.

---

## 🔍 Overview

Scaling data, parameters, and test-time compute is hitting diminishing returns for LLM systems (LLMsys). MemoryBench evaluates a complementary axis: **can LLM systems learn from accumulated user feedback during service time?** Memory and continual-learning frameworks claim to enable this, but most existing benchmarks reduce the problem to long-form reading comprehension — a poor proxy for real feedback-driven adaptation.

MemoryBench tests the harder regime: **multi-task, multi-domain, multilingual evaluation with simulated user feedback**, across both **off-policy** (replay pre-recorded dialogs) and **on-policy** (generate dialogs on the fly) settings.

### Highlights

- **28 datasets** across 3 domains (Academic & Knowledge, Legal, Open-Domain) and 4 task shapes (Long-Long, Long-Short, Short-Long, Short-Short).
- **8 memory-system baselines** with a one-call registry interface (vanilla, BM25-M/S, Emb-M/S, A-Mem, Mem0, MemoryOS).
- **4 experiment regimes**: off-policy, stepwise off-policy, on-policy, and training-set performance.
- **User-feedback simulator** based on `Mistral-Small-3.2-24B-Instruct-2506`.
- **LLM providers**: vLLM, OpenAI-compatible, and Anthropic — wired through one `LlmFactory`.
- **Streamlit frontend** with conditional UI and explicit dataset-path support.
- **Plug-and-play extension** via a single registry entry. See [CONTRIBUTING.md](CONTRIBUTING.md).

> This repository hosts the lightweight benchmark interface and baseline implementations. The full reproduction code for the paper lives at [LittleDinoC/MemoryBench-code](https://github.com/LittleDinoC/MemoryBench-code).

---

## 📚 Table of Contents

- [Quick Start](#-quick-start)
- [Datasets](#-datasets)
- [Baselines](#-baselines)
- [Experiments](#-experiments)
- [Python API](#-python-api)
- [Frontend](frontend/README.md)
- [Extending MemoryBench](#-extending-memorybench)
- [Repository Layout](#-repository-layout)
- [Citation](#citation)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## 🚀 Quick Start

### Installation

```bash
conda create -n memorybench python=3.10 -y
conda activate memorybench

git clone https://github.com/QingyaoAi/MemoryBench.git
cd MemoryBench

pip install -r requirements.txt
pip install -e baselines/mem0          # editable install required by Mem0

python -c "import nltk; [nltk.download(p) for p in ('punkt','wordnet','stopwords')]"
```

### Quick Start

```python
from memorybench import load_memory_bench, evaluate, summary_results

dataset = load_memory_bench(dataset_type="single", name="JRE-L")
predicts = [
    {"test_idx": int(row["test_idx"]), "response": "...", "dataset": "JRE-L"}
    for row in dataset.dataset["test"]
]
details = evaluate("single", "JRE-L", predicts)
print(summary_results("single", "JRE-L", predicts, details)["summary"])
```

### Run an experiment

```bash
# Off-policy with BM25 on the Open-Domain split
python -m src.off-policy \
    --memory_system bm25_message \
    --dataset_type domain \
    --set_name Open-Domain
```

---

## 📊 Datasets

The full dataset is on Hugging Face: **[`THUIR/MemoryBench`](https://huggingface.co/datasets/THUIR/MemoryBench)**.

| Domain                | Task Shape  | Datasets                                                                     |
|-----------------------|-------------|-------------------------------------------------------------------------------|
| **Open-Domain**       | Long-Short  | Locomo-0 … Locomo-9, DialSim-friends, DialSim-bigbang, DialSim-theoffice     |
| Open-Domain           | Long-Long   | HelloBench-Creative&Design, WritingBench-Creative&Design                     |
| Open-Domain           | Short-Long  | WritingPrompts                                                                |
| Open-Domain           | Short-Short | NFCats                                                                        |
| **Academic & Knowledge** | Long-Short  | LimitGen-Syn, IdeaBench                                                       |
| Academic & Knowledge | Long-Long   | HelloBench-Academic&Knowledge-Writing, WritingBench-Academic&Engineering     |
| Academic & Knowledge | Short-Long  | HelloBench-Academic&Knowledge-QA                                              |
| Academic & Knowledge | Short-Short | JRE-L                                                                         |
| **Legal**             | Long-Short  | LexEval-Summarization                                                         |
| Legal                 | Long-Long   | LexEval-Judge, WritingBench-Politics&Law                                      |
| Legal                 | Short-Long  | JuDGE                                                                         |
| Legal                 | Short-Short | LexEval-QA                                                                    |

The full list (28 datasets) lives in [`configs/datasets/each.json`](configs/datasets/each.json); domain and task groupings are in `domain.json` / `task.json`.

**Corpus datasets.** LoCoMo and DialSim ship a multi-session conversation corpus that the memory system must ingest before answering. MemoryBench dispatches per-corpus loading by an attribute on the dataset class:

```python
class Locomo_Dataset(BaseDataset):
    corpus_format = "locomo"      # → solver.memory_locomo_conversation
    summary_group_name = "Locomo" # → collapse Locomo-0..9 under one normalization key
```

---

## 🧠 Baselines

All baselines are registered in [`src/memory_systems.py`](src/memory_systems.py). The runner CLI (`--memory_system <name>`), the frontend dropdown, and the run scripts all derive their lists from this single source of truth.

| Paper Name | Code Name           | Type                       | Config File                                          |
|------------|---------------------|----------------------------|------------------------------------------------------|
| Vanilla    | `wo_memory`         | No memory (baseline)       | [`base.json`](configs/memory_systems/base.json)      |
| BM25-M     | `bm25_message`      | Lexical, message-level     | [`bm25.json`](configs/memory_systems/bm25.json)      |
| BM25-S     | `bm25_dialog`       | Lexical, session-level     | [`bm25.json`](configs/memory_systems/bm25.json)      |
| Emb-M      | `embedder_message`  | Dense, message-level       | [`embedder.json`](configs/memory_systems/embedder.json) |
| Emb-S      | `embedder_dialog`   | Dense, session-level       | [`embedder.json`](configs/memory_systems/embedder.json) |
| A-Mem      | `a_mem`             | Note-based associative     | [`a_mem.json`](configs/memory_systems/a_mem.json)    |
| Mem0       | `mem0`              | Fact-extraction memory     | [`mem0.json`](configs/memory_systems/mem0.json)      |
| MemoryOS   | `memoryos`          | Hierarchical OS-style      | [`memoryos.json`](configs/memory_systems/memoryos.json) |

Upstream sources for `a_mem`, `mem0`, and `memoryos` are vendored under [`baselines/`](baselines/).

---

## 🧪 Experiments

MemoryBench evaluates memory systems under four complementary regimes. Each one ships with both a per-experiment Python entry point (`src/<experiment>.py`) and a sweep driver (`run_scripts/<experiment>.py`) that iterates every registered memory system.

| Regime                | Train→Memory  | Test access     | When to use                                              | Entry point                       |
|-----------------------|---------------|-----------------|----------------------------------------------------------|-----------------------------------|
| **Off-policy**        | Bulk replay   | Read only       | Compare baselines on a fixed training-dialog corpus      | `python -m src.off-policy`        |
| **Stepwise off-policy** | Replay in batches | Read between batches | Track scaling with training data                    | `python -m src.stepwise_off-policy` |
| **On-policy**         | Live generation | Read between steps | Realistic continual-learning loop                      | `python -m src.on-policy`         |
| **Training perf.**    | Bulk replay   | Re-eval on train | Detect overfit / catastrophic forgetting               | `python -m src.train_performance` |

Common arguments: `--memory_system <name>`, `--dataset_type single|domain|task`, `--set_name <name>`. See `--help` on any entry point for the full list.

<details>
<summary><b>Example: off-policy run on the Open-Domain split</b></summary>

```bash
python -m src.off-policy \
    --memory_system bm25_message \
    --dataset_type domain \
    --set_name Open-Domain \
    --retrieve_k 5
```

Results are written to `off-policy/results/domain/Open-Domain/bm25_message/start_at_<timestamp>/`.

</details>

<details>
<summary><b>Example: full sweep across all baselines × domains</b></summary>

```bash
python run_scripts/off-policy.py
```

The sweep iterates `memory_systems.all_names()` × `domain.json` and `task.json`, automatically skipping known-incompatible combinations declared in the registry (e.g. `mem0` on `Open-Domain`).

</details>

<details>
<summary><b>Example: on-policy with live feedback generation</b></summary>

```bash
python -m src.on-policy \
    --memory_system mem0 \
    --dataset_type domain \
    --set_name Legal \
    --step 10 --batch_size 100 --max_rounds 3
```

</details>

<details>
<summary><b>Default vLLM deployment (only required to reproduce paper results)</b></summary>

```bash
vllm serve Qwen/Qwen3-32B  --port 12345 --chat-template qwen3_nonthinking.jinja   # Main LLM
vllm serve Qwen/Qwen3-8B   --port 12366 --chat-template qwen3_nonthinking.jinja   # Memory-system LLM
vllm serve Qwen/Qwen3-Embedding-0.6B --port 12377 --task embed                    # Embedder
vllm serve AQuarterMile/WritingBench-Critic-Model-Qwen-7B --port 12388            # WritingBench evaluator
```

With these ports the default `configs/memory_systems/*.json` files work as-is.

</details>

---

## 🐍 Python API

The benchmark exposes three top-level functions in [`memorybench.py`](memorybench.py).

### `load_memory_bench(dataset_type, name, eval_mode=False)`

Returns a `BaseDataset` (when `dataset_type="single"`) or a `list[BaseDataset]` (for `"domain"` / `"task"`).

```python
ds = load_memory_bench("single", "JRE-L")
ds.dataset_name           # "JRE-L"
ds.dataset                # HF DatasetDict with "train" and "test" splits
ds.has_corpus             # bool — True for LoCoMo/DialSim
ds.get_data(test_idx=42)  # → row dict
```

### `evaluate(dataset_type, name, predicts) → list[dict]`

```python
predicts = [{"test_idx": 0, "response": "...", "dataset": "JRE-L"}, ...]
details  = evaluate("single", "JRE-L", predicts)
# [{"dataset": "JRE-L", "test_idx": 0, "metrics": {"Rouge-L": ..., ...}}, ...]
```

### `summary_results(dataset_type, name, predicts, evaluate_details)`

Mean metrics for a single dataset; min-max-normalized + z-normalized aggregates for a domain or task.

```python
summary = summary_results("domain", "Open-Domain", predicts, details)
summary["summary"]["weighted_average"]
summary["minmax_normalized_average"]
```

### Local dataset path

By default `load_memory_bench` pulls from `THUIR/MemoryBench` and caches under `~/.cache/huggingface/`. Override either via `MEMORY_BENCH_PATH=/abs/path/to/local/dataset` or the **Dataset source** selector in the frontend.

---

## 🖥 Frontend

```bash
python -m streamlit run frontend/streamlit_app.py
# → http://localhost:8501
```

The frontend covers off-policy and on-policy runs end to end. It auto-hides irrelevant fields:

- **LLM provider** dropdown is filtered per baseline — `mem0` / `a_mem` / `memoryos` don't expose the Anthropic option because they route through their own provider abstractions.
- **LLM base URL** default updates when you switch providers (vllm / openai / anthropic).
- **Embedder section** only appears for baselines that consume embeddings (`embedder_*`, `mem0`).
- **Retrieve k** is hidden for `wo_memory`.
- **Dataset source** is an explicit radio: Hugging Face Hub vs Local path, with live path validation.

See [`frontend/README.md`](frontend/README.md) for the full walkthrough.

---

## 🧰 Extending MemoryBench

Adding a new baseline or dataset is a single-file change plus one registry entry.

**Add a new memory-system baseline**:
1. Write `src/agent/<name>.py` (agent + pydantic config) and `src/solver/<name>.py` (solver).
2. Drop `configs/memory_systems/<name>.json`.
3. Add one `register(MemorySystemSpec(...))` call in `src/memory_systems.py`.

Everything else — CLI choices, frontend dropdowns, sweep scripts, dialog-field lookups, skip rules — picks the new entry up automatically.

**Add a new dataset**: subclass `BaseDataset`, add one entry to `configs/datasets/each.json`, and (for corpus-style datasets) set `corpus_format = "<name>"` on the class.

Full step-by-step walkthrough: **[CONTRIBUTING.md](CONTRIBUTING.md)**.

The parametric test [`tests/test_refactor.py::TestAllBaselinesContract`](tests/test_refactor.py) walks every registered baseline and asserts the off-policy + on-policy method contract — your new baseline is auto-tested.

---

## 🏗 Repository Layout

```text
MemoryBench/
├── memorybench.py              # Public API: load_memory_bench, evaluate, summary_results
├── configs/
│   ├── datasets/               # each.json, domain.json, task.json
│   ├── memory_systems/         # one JSON per baseline
│   └── final_evaluate_summary_wo_details.json  # min/max/mu/sigma stats
├── src/
│   ├── memory_systems.py       # ← central registry of baselines
│   ├── dataset/                # BaseDataset + per-dataset subclasses
│   ├── agent/                  # Agent implementations
│   ├── solver/                 # Per-baseline solvers
│   ├── llms/                   # OpenAI / vLLM / Anthropic clients
│   ├── generate_dialogs/       # Dialog-generation scripts
│   ├── off-policy.py · on-policy.py · stepwise_off-policy.py · train_performance.py
│   └── utils.py
├── run_scripts/                # Sweep drivers (loops over every registered baseline)
├── baselines/                  # Vendored upstream baselines (mem0, A-Mem, MemoryOS)
├── frontend/                   # Streamlit app
├── tests/                      # Unit + integration tests
├── CONTRIBUTING.md             # How to add baselines / datasets
└── README.md
```

---

## 📝 Notes & Caveats

- **`bert_score` truncation bug.** Some datasets (e.g. `JRE-L`) evaluate with [`bert_score`](https://github.com/Tiiiger/bert_score). Locally-loaded models don't truncate inputs — load from Hugging Face Hub to avoid "exceeding max length" errors.
- **WritingBench evaluator.** Long-form writing datasets use a 7 B critic; we recommend serving [WritingBench-Critic-Model-Qwen-7B](https://huggingface.co/AQuarterMile/WritingBench-Critic-Model-Qwen-7B) via vLLM and pointing `WRITINGBENCH_EVAL_BASE_URL` at it.
- **Mem0 cost.** `mem0` is slow on `Open-Domain` and `Long-Short`; the run scripts skip these combinations by default — `skip_combinations` in the registry entry.
- **Secrets.** `API_config.json`, `.env*` (except `.env.example`), and `frontend/runtime_configs/` are all gitignored — see [`.gitignore`](.gitignore).

---

## Citation

If you use MemoryBench in your research, please cite:

```bibtex
@inproceedings{memorybench2026,
  title     = {MemoryBench: A Benchmark for Memory and Continual Learning in LLM Systems},
  author    = {Qingyao Ai, Yichen Tang, Changyue Wang, Jianming Long, Weihang Su, Yiqun Liu},
  booktitle = {Proceedings of the 43rd International Conference on Machine Learning},
  year      = {2026},
  note      = {Spotlight}
}
```

(Full BibTeX will be updated once the camera-ready DOI is available.)

---

## License

Released under the MIT License. Upstream baseline code under [`baselines/`](baselines/) retains its original license — see each subdirectory's `LICENSE` file.

---

## Acknowledgements

MemoryBench builds on prior datasets and memory systems from many open-source efforts: [LoCoMo](https://snap-research.github.io/locomo/), [DialSim](https://dialsim.github.io/), [HelloBench](https://github.com/Quehry/HelloBench), [WritingBench](https://github.com/X-PLUG/WritingBench), [IdeaBench](https://github.com/IdeaBench/IdeaBench), [LimitGen](https://github.com/zhenfenglu/LimitGen), [JRE-L](https://github.com/JRE-L), [JuDGE](https://github.com/JuDGE), [LexEval](https://github.com/CSHaitao/LexEval), [NFCats](https://github.com/NFCats), [WritingPrompts](https://github.com/aitorparra/writingprompts), [A-Mem](https://github.com/agiresearch/A-mem), [Mem0](https://github.com/mem0ai/mem0), and [MemoryOS](https://github.com/BAI-LAB/MemoryOS). Thank you to all upstream authors.

For questions and feedback, open an issue on GitHub or contact the maintainers.
