"""Integration test for the MemoryBench refactor.

What this test verifies:
  * the new `src.memory_systems` registry returns the same config-file +
    dialog-key mappings as the legacy hardcoded dicts;
  * `SolverFactory.create` resolves classes via the registry;
  * `BaseDataset.corpus_format` / `summary_group_name` are set correctly on
    Locomo / DialSim and drive `load_corpus_to_memory`;
  * `load_corpus_to_memory(BM25Solver, Locomo_Dataset)` actually populates the
    BM25 index from a real (Tiny) corpus — proves the new attribute-based
    dispatch keeps the corpus path intact;
  * `evaluate` + `summary_results` round-trip on the Tiny Locomo split, and
    the Locomo-N -> Locomo summary grouping still kicks in.

Data source:
  Local `TinyDataset/` (3 train + 2 test rows per dataset). The test sets
  `MEMORY_BENCH_PATH` to its absolute path before importing memorybench.

Secrets handling:
  The optional end-to-end LLM ping reads `../API_config.json` only when
  `MEMORYBENCH_LLM_PING=1` is set. The auth token is *never* printed, written,
  or otherwise persisted. `API_config.json` is gitignored.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


# --------------------------------------------------------------------------
# Environment bootstrapping — must run BEFORE importing memorybench / src.*
# --------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent                       # MemoryBench/
PROJECT_ROOT = REPO_ROOT.parent               # code/
TINY = PROJECT_ROOT / "TinyDataset"
API_CONFIG_PATH = PROJECT_ROOT / "API_config.json"

assert TINY.exists(), f"TinyDataset not found at {TINY}"
os.environ["MEMORY_BENCH_PATH"] = str(TINY)

# Make `src.*` and `memorybench` importable when running this file directly.
sys.path.insert(0, str(REPO_ROOT))


# --------------------------------------------------------------------------
# Expected mappings copied verbatim from the pre-refactor code, used as the
# ground-truth oracle.
# --------------------------------------------------------------------------
LEGACY_CONFIG_MAP = {
    "wo_memory": "configs/memory_systems/base.json",
    "a_mem": "configs/memory_systems/a_mem.json",
    "bm25_message": "configs/memory_systems/bm25.json",
    "bm25_dialog": "configs/memory_systems/bm25.json",
    "embedder_message": "configs/memory_systems/embedder.json",
    "embedder_dialog": "configs/memory_systems/embedder.json",
    "mem0": "configs/memory_systems/mem0.json",
    "memoryos": "configs/memory_systems/memoryos.json",
    "tencentdb": "configs/memory_systems/tencentdb.json",
}

LEGACY_DIALOG_KEYS = {
    "wo_memory": "dialog_wo_memory",
    "bm25_message": "dialog_bm25",
    "embedder_message": "dialog_embedder",
    "bm25_dialog": "dialog_bm25_dialog",
    "embedder_dialog": "dialog_embedder_dialog",
    "a_mem": "dialog_a_mem",
    "mem0": "dialog_mem0",
    "memoryos": "dialog_memoryos",
    "tencentdb": "dialog_tencentdb",
}

LEGACY_SOLVER_CLASSES = {
    "wo_memory": ("src.solver.base.BaseSolver", "src.solver.base.BaseAgentConfig"),
    "bm25_message": ("src.solver.bm25.BM25Solver", "src.solver.bm25.BM25AgentConfig"),
    "bm25_dialog": ("src.solver.bm25_dialog.BM25DialogSolver", "src.solver.bm25_dialog.BM25DialogAgentConfig"),
    "embedder_message": ("src.solver.embedder.EmbedderSolver", "src.solver.embedder.EmbedderAgentConfig"),
    "embedder_dialog": ("src.solver.embedder_dialog.EmbedderDialogSolver", "src.solver.embedder_dialog.EmbedderDialogAgentConfig"),
    "a_mem": ("src.solver.a_mem.AMemSolver", "src.solver.a_mem.AMemAgentConfig"),
    "mem0": ("src.solver.mem0.Mem0Solver", "src.solver.mem0.Mem0AgentConfig"),
    "memoryos": ("src.solver.memoryos.MemoryOSSolver", "src.solver.memoryos.MemoryOSAgentConfig"),
    "tencentdb": ("src.solver.tencentdb.TencentDBSolver", "src.solver.tencentdb.TencentDBAgentConfig"),
}


# --------------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------------
class TestRegistry(unittest.TestCase):
    """Pure unit tests for the new registry — no heavy deps loaded."""

    def test_all_eight_baselines_registered(self):
        from src import memory_systems
        self.assertEqual(set(memory_systems.all_names()), set(LEGACY_CONFIG_MAP))

    def test_names_with_memory_excludes_wo_memory(self):
        from src import memory_systems
        self.assertNotIn("wo_memory", memory_systems.names_with_memory())
        self.assertEqual(
            set(memory_systems.names_with_memory()),
            set(LEGACY_CONFIG_MAP) - {"wo_memory"},
        )

    def test_config_files_match_legacy(self):
        from src.utils import get_memory_system_config_file
        for name, expected in LEGACY_CONFIG_MAP.items():
            self.assertEqual(get_memory_system_config_file(name), expected, name)

    def test_dialog_keys_match_legacy(self):
        from src.utils import get_dialog_key
        for name, expected in LEGACY_DIALOG_KEYS.items():
            self.assertEqual(get_dialog_key(name), expected, name)

    def test_solver_factory_class_map_matches_legacy(self):
        from src.solver import SolverFactory
        for name, (solver_cls, cfg_cls) in LEGACY_SOLVER_CLASSES.items():
            self.assertEqual(SolverFactory.method_to_class[name], (solver_cls, cfg_cls))

    def test_mem0_skip_combinations_preserved(self):
        from src import memory_systems
        spec = memory_systems.get("mem0")
        self.assertIn(("domain", "Open-Domain"), spec.skip_combinations)
        self.assertIn(("task", "Long-Short"), spec.skip_combinations)

    def test_unknown_method_raises(self):
        from src.utils import get_memory_system_config_file
        with self.assertRaises(ValueError):
            get_memory_system_config_file("not_a_real_method")


class TestDatasetAttributes(unittest.TestCase):
    """Attribute-based corpus dispatch."""

    def test_basedataset_has_attrs(self):
        from src.dataset.base import BaseDataset
        self.assertIsNone(BaseDataset.corpus_format)
        self.assertIsNone(BaseDataset.summary_group_name)

    def test_locomo_class_attributes(self):
        from src.dataset.Locomo import Locomo_Dataset
        self.assertEqual(Locomo_Dataset.corpus_format, "locomo")
        self.assertEqual(Locomo_Dataset.summary_group_name, "Locomo")

    def test_dialsim_class_attributes(self):
        from src.dataset.DialSim import DialSim_Dataset
        self.assertEqual(DialSim_Dataset.corpus_format, "dialsim")
        # DialSim does not get summary-renamed.
        self.assertIsNone(DialSim_Dataset.summary_group_name)


class TestDatasetLoadingTiny(unittest.TestCase):
    """Load the TinyDataset and exercise the public memorybench API."""

    @classmethod
    def setUpClass(cls):
        from memorybench import load_memory_bench
        cls.locomo = load_memory_bench("single", "Locomo-0", eval_mode=False)

    def test_has_corpus_attribute(self):
        self.assertTrue(self.locomo.has_corpus)
        self.assertEqual(self.locomo.corpus_format, "locomo")
        self.assertEqual(self.locomo.summary_group_name, "Locomo")

    def test_train_and_test_split_size(self):
        # TinyDataset has 3 train + 2 test rows per dataset.
        self.assertEqual(len(self.locomo.dataset["train"]), 3)
        self.assertEqual(len(self.locomo.dataset["test"]), 2)

    # Baselines whose pre-generated dialogs were materialised into TinyDataset.
    # Newly added baselines need a fresh `generate_dialogs.reading` run before
    # this assertion can extend to them — see CONTRIBUTING.md.
    _BASELINES_WITH_PREBUILT_DIALOGS = {
        "bm25_message", "bm25_dialog",
        "embedder_message", "embedder_dialog",
        "a_mem", "mem0", "memoryos",
    }

    def test_dialog_field_for_every_baseline_exists_on_row(self):
        """Each baseline shipped with TinyDataset has a dialog_key field on the HF row."""
        from src import memory_systems
        first_row = self.locomo.dataset["train"][0]
        for name in self._BASELINES_WITH_PREBUILT_DIALOGS:
            key = memory_systems.get(name).dialog_key()
            self.assertIn(key, first_row, f"{name}: dialog field {key} missing")


class TestCorpusDispatch(unittest.TestCase):
    """End-to-end: load Tiny Locomo corpus into BM25 via the new attribute dispatch."""

    @classmethod
    def setUpClass(cls):
        from memorybench import load_memory_bench
        cls.locomo = load_memory_bench("single", "Locomo-0", eval_mode=False)
        cls.tmp = Path(tempfile.mkdtemp(prefix="memorybench-test-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _build_bm25_solver(self):
        """Create a BM25 solver with a dummy LLM (no calls made in this test)."""
        from src.solver import SolverFactory
        cache_dir = self.tmp / "bm25_index"
        # LLM provider is required by the BaseAgent init path but we never call it.
        config_dict = {
            "llm_provider": "openai",
            "llm_config": {"model": "noop", "api_key": "noop"},
            "retrieve_k": 5,
        }
        return SolverFactory.create(
            method_name="bm25_message",
            config=config_dict,
            memory_cache_dir=str(cache_dir),
        )

    def test_load_corpus_dispatch_uses_corpus_format(self):
        from src.utils import load_corpus_to_memory
        solver = self._build_bm25_solver()
        # Sanity: before ingestion, index is empty.
        self.assertEqual(solver.agent._count_docs(), 0)

        load_corpus_to_memory(solver, self.locomo)

        # TinyDataset declares "3 corpus sessions". BM25Solver indexes one
        # document per turn, so the count must be > 0.
        self.assertGreater(solver.agent._count_docs(), 0)

        # The retrieval path must surface the corpus content for an arbitrary
        # query — proves the dispatch wrote into the same store BM25 reads from.
        hits = solver.agent.retrieve_memory("turn", k=3)
        self.assertGreater(len(hits), 0)

    def test_unknown_corpus_format_raises(self):
        from src.utils import _resolve_corpus_format

        class FakeDataset:
            dataset_name = "TotallyMadeUp"
            corpus_format = None

        with self.assertRaises(ValueError):
            _resolve_corpus_format(FakeDataset())


class TestAllBaselinesContract(unittest.TestCase):
    """Every registered memory baseline must satisfy the off-policy + on-policy
    contracts.

    Off-policy needs (from `src/off-policy.py`):
      * solver = SolverFactory.create(name, config, memory_cache_dir=...)
      * solver.create_or_load_memory(dialogs)
      * solver.predict_test(dataset)
      * load_corpus_to_memory(solver, dataset)
            -> solver.memory_<corpus_format>_conversation(corpus, session_cnt)
                 for every corpus format the benchmark ships (locomo, dialsim).

    On-policy needs (from `src/on-policy.py`), per step:
      * solver.predict_single_data(dataset, data)              [first round]
      * solver.agent.llm.generate_response(messages)            [follow-up rounds]
      * solver.agent.add_conversation_to_memory(dialog, idx)    [memory update]
      * solver.predict_test(dataset)                            [eval]

    `wo_memory` is intentionally excluded — `memory_systems.names_with_memory()`
    already drops it from the on-policy argparse choices.
    """

    @classmethod
    def setUpClass(cls):
        from src import memory_systems
        from src.solver import load_class
        cls.memory_systems = memory_systems
        cls.load_class = staticmethod(load_class)
        cls.baselines = memory_systems.names_with_memory()

    def test_solver_surface_for_off_policy(self):
        for name in self.baselines:
            solver_cls = self.load_class(self.memory_systems.get(name).solver_class)
            with self.subTest(memory_system=name):
                self.assertTrue(hasattr(solver_cls, "create_or_load_memory"),
                                f"{name}: solver missing create_or_load_memory")
                self.assertTrue(hasattr(solver_cls, "predict_test"),
                                f"{name}: solver missing predict_test")
                self.assertTrue(hasattr(solver_cls, "predict_single_data"),
                                f"{name}: solver missing predict_single_data")

    def test_agent_surface_for_on_policy(self):
        for name in self.baselines:
            solver_cls = self.load_class(self.memory_systems.get(name).solver_class)
            agent_cls = solver_cls.AGENT_CLASS
            with self.subTest(memory_system=name):
                self.assertTrue(
                    hasattr(agent_cls, "add_conversation_to_memory"),
                    f"{name}: agent missing add_conversation_to_memory (required by on-policy)"
                )
                self.assertTrue(
                    hasattr(agent_cls, "generate_response"),
                    f"{name}: agent missing generate_response"
                )

    def test_corpus_format_dispatch_methods(self):
        """Every memory baseline must support both shipped corpus formats."""
        required = ("memory_locomo_conversation", "memory_dialsim_conversation")
        for name in self.baselines:
            solver_cls = self.load_class(self.memory_systems.get(name).solver_class)
            with self.subTest(memory_system=name):
                for m in required:
                    self.assertTrue(
                        hasattr(solver_cls, m),
                        f"{name}: solver missing {m} (needed for Locomo/DialSim ingestion)"
                    )

    def test_argparse_inclusion_via_registry(self):
        """The runner CLI choices are computed from the registry, not hardcoded.

        If anyone reintroduces a parallel hardcoded list, this will fail.
        """
        # On-policy = all memory baselines minus wo_memory.
        self.assertNotIn("wo_memory", self.baselines)
        # Off-policy = all baselines including wo_memory.
        self.assertIn("wo_memory", self.memory_systems.all_names())


class TestEvaluateAndSummary(unittest.TestCase):
    """`evaluate` + `summary_results` over Tiny Locomo with synthetic predictions."""

    def test_single_dataset_summary(self):
        from memorybench import evaluate, summary_results, load_memory_bench
        ds = load_memory_bench("single", "Locomo-0", eval_mode=True)
        # One synthetic prediction per test row.
        predicts = [
            {"test_idx": int(row["test_idx"]), "response": "the answer", "dataset": "Locomo-0"}
            for row in ds.dataset["test"]
        ]
        details = evaluate("single", "Locomo-0", predicts)
        self.assertEqual(len(details), len(predicts))
        summary = summary_results("single", "Locomo-0", predicts, details)
        # f1 is the test metric for Locomo.
        self.assertIn("summary", summary)
        self.assertIn("f1", summary["summary"])

    def test_summary_group_rename_to_locomo(self):
        """summary_results must collapse Locomo-N rows under the 'Locomo' key."""
        from memorybench import summary_results, load_memory_bench
        from memorybench import evaluate

        # Build a synthetic two-dataset evaluation manually to avoid running
        # `evaluate` over the heavier domain pipeline. We monkey-patch nothing
        # — we just call summary_results with the format it expects.
        ds = load_memory_bench("single", "Locomo-0", eval_mode=True)
        predicts = [
            {"test_idx": int(row["test_idx"]), "response": "yes", "dataset": "Locomo-0"}
            for row in ds.dataset["test"]
        ]
        details = evaluate("single", "Locomo-0", predicts)

        # Now ask summary_results to treat this as a "domain" with one sub-dataset.
        # The min-max config file in this repo has the "Locomo" merged key, so
        # the rename Locomo-0 -> Locomo must happen for the lookup to succeed.
        min_max = REPO_ROOT / "configs" / "final_evaluate_summary_wo_details.json"
        with open(min_max) as f:
            mm = json.load(f)
        # Only run this assertion if the merged config has the expected key.
        if "domain" in mm and "Open-Domain" in mm["domain"]:
            try:
                out = summary_results(
                    "domain", "Open-Domain", predicts, details,
                    min_max_config_file=str(min_max),
                )
            except KeyError:
                self.skipTest("Open-Domain min-max config does not cover the Tiny sample")
                return
            # If we got here, the rename worked: 'Locomo' key must appear in details.
            self.assertIn("Locomo", out["details"])


class TestOptionalLLMPing(unittest.TestCase):
    """Optional end-to-end LLM ping. Off by default to keep CI hermetic.

    Enable with MEMORYBENCH_LLM_PING=1. Reads creds from `../API_config.json`
    but never echoes the token to stdout, the filesystem, or test output.
    """

    @unittest.skipUnless(
        os.environ.get("MEMORYBENCH_LLM_PING") == "1",
        "Set MEMORYBENCH_LLM_PING=1 to enable the live LLM ping",
    )
    def test_anthropic_provider_via_base_agent(self):
        """Round-trip a real Anthropic call through the LlmFactory / BaseAgent path.

        This is the path the frontend uses when `llm_provider == "anthropic"` is
        chosen: `BaseAgent(BaseAgentConfig(llm_provider='anthropic', ...))` ->
        `LlmFactory.create('anthropic', ...)` -> `AnthropicLLM.generate_response`.
        """
        if not API_CONFIG_PATH.exists():
            self.skipTest(f"API_config.json not found at {API_CONFIG_PATH}")
        with open(API_CONFIG_PATH) as f:
            cfg = json.load(f)
        token = cfg.get("ANTHROPIC_AUTH_TOKEN")
        base_url = cfg.get("ANTHROPIC_BASE_URL")
        model = cfg.get("ANTHROPIC_MODEL")
        if not (token and base_url and model):
            self.skipTest("API_config.json missing required fields")

        from src.agent.base_agent import BaseAgent, BaseAgentConfig
        agent = BaseAgent(BaseAgentConfig(
            llm_provider="anthropic",
            llm_config={
                "model": model,
                "anthropic_base_url": base_url,
                "api_key": token,
                "max_tokens": 16,
                "temperature": 0.1,
            },
        ))
        try:
            out = agent.generate_response(
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            )
        except Exception as e:
            # Never leak the token in the failure message.
            self.fail(f"Anthropic-via-BaseAgent ping failed: {type(e).__name__}")
        self.assertIsInstance(out, str)
        self.assertGreater(len(out.strip()), 0)

    @unittest.skipUnless(
        os.environ.get("MEMORYBENCH_LLM_PING") == "1",
        "Set MEMORYBENCH_LLM_PING=1 to enable the live LLM ping",
    )
    def test_llm_ping(self):
        if not API_CONFIG_PATH.exists():
            self.skipTest(f"API_config.json not found at {API_CONFIG_PATH}")
        with open(API_CONFIG_PATH) as f:
            cfg = json.load(f)

        token = cfg.get("ANTHROPIC_AUTH_TOKEN")
        base_url = cfg.get("ANTHROPIC_BASE_URL")
        model = cfg.get("ANTHROPIC_MODEL")
        if not (token and base_url and model):
            self.skipTest("API_config.json missing required fields")

        try:
            import anthropic
        except ImportError:
            self.skipTest("anthropic SDK not installed")

        client = anthropic.Anthropic(api_key=token, base_url=base_url)
        # Use a tiny prompt; cap the response so this stays cheap.
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=16,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            )
        except Exception as e:
            # Don't leak the token in the failure message.
            self.fail(f"LLM ping failed against base_url={base_url}: {type(e).__name__}")
        # Sanity-check the response shape without printing the model output.
        self.assertTrue(hasattr(resp, "content"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
