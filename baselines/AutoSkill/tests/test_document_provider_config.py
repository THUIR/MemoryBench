from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from AutoSkill4Doc.core.provider_config import build_embeddings_config, build_llm_config


class DocumentProviderConfigTest(unittest.TestCase):
    def test_generic_llm_requires_explicit_url(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            old = os.environ.pop("AUTOSKILL_GENERIC_LLM_URL", None)
            try:
                with self.assertRaises(SystemExit):
                    build_llm_config("generic", model=None)
            finally:
                if old is not None:
                    os.environ["AUTOSKILL_GENERIC_LLM_URL"] = old

    def test_generic_embeddings_require_explicit_url(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            old = os.environ.pop("AUTOSKILL_GENERIC_EMBED_URL", None)
            try:
                with self.assertRaises(SystemExit):
                    build_embeddings_config("generic", model=None, llm_provider="generic")
            finally:
                if old is not None:
                    os.environ["AUTOSKILL_GENERIC_EMBED_URL"] = old

    def test_generic_provider_uses_explicit_env_urls(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUTOSKILL_GENERIC_LLM_URL": "http://localhost:8000/v1",
                "AUTOSKILL_GENERIC_EMBED_URL": "http://localhost:9000/v1",
            },
            clear=False,
        ):
            llm_cfg = build_llm_config("generic", model="demo-llm")
            emb_cfg = build_embeddings_config("generic", model="demo-emb", llm_provider="generic")

        self.assertEqual(llm_cfg["base_url"], "http://localhost:8000/v1")
        self.assertEqual(emb_cfg["base_url"], "http://localhost:9000/v1")


if __name__ == "__main__":
    unittest.main()
