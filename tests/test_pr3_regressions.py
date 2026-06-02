import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class TestMemorySystemRegistryVisibility(unittest.TestCase):
    def test_tencentdb_is_registered_but_not_advertised_without_vendor_dir(self):
        from src import memory_systems

        self.assertIn("tencentdb", memory_systems.registered_names())
        self.assertNotIn("tencentdb", memory_systems.all_names())
        self.assertNotIn("tencentdb", memory_systems.names_with_memory())

    def test_off_policy_names_only_include_public_dialog_baselines(self):
        from src import memory_systems

        self.assertIn("bm25_message", memory_systems.off_policy_names())
        self.assertNotIn("light", memory_systems.off_policy_names())
        self.assertNotIn("tencentdb", memory_systems.off_policy_names())


class TestLightFrontendRuntimeConfig(unittest.TestCase):
    def test_light_runtime_config_preserves_embedder_settings(self):
        if "streamlit" not in sys.modules:
            sys.modules["streamlit"] = types.SimpleNamespace()
        from frontend.streamlit_app import build_runtime_memory_config

        cfg = build_runtime_memory_config(
            memory_system="light",
            provider="vllm",
            llm_model="chat-model",
            llm_base_url="http://llm/v1",
            llm_api_key="llm-key",
            temperature=0.2,
            retrieve_k=9,
            embedder_provider="openai",
            embedder_model="embed-model",
            embedder_base_url="http://embed/v1",
            embedder_dim=1536,
            embedder_api_key="embed-key",
        )

        self.assertEqual(cfg["embedder_provider"], "openai")
        self.assertEqual(cfg["embedder_model"], "embed-model")
        self.assertEqual(cfg["embedder_base_url"], "http://embed/v1")
        self.assertEqual(cfg["embedding_dim"], 1536)
        self.assertEqual(cfg["embedder_api_key"], "embed-key")


class TestDependencies(unittest.TestCase):
    def test_anthropic_sdk_is_declared(self):
        requirements = (REPO_ROOT / "requirements.txt").read_text()
        self.assertIn("anthropic", requirements)


class TestTinyDatasetTestsAreCollectable(unittest.TestCase):
    def test_refactor_test_module_imports_without_tiny_dataset(self):
        project_root = REPO_ROOT.parent
        tiny = project_root / "TinyDataset"
        if tiny.exists():
            self.skipTest("TinyDataset exists; this regression only covers missing data")

        __import__("tests.test_refactor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
