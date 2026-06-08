from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_DIR = _REPO_ROOT / "AutoSkill4OpenClaw"
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from openclaw_prompt_pack import (  # noqa: E402
    get_openclaw_prompt_pack_info,
    render_openclaw_prompt,
)


class OpenClawPromptPackTest(unittest.TestCase):
    def test_default_pack_loaded_and_versioned(self) -> None:
        version, path = get_openclaw_prompt_pack_info()
        self.assertTrue(path.endswith("openclaw_prompt_pack.txt"))
        self.assertTrue(bool(version))

    def test_shared_block_is_used_by_sidecar_and_embedded_extract(self) -> None:
        sidecar_prompt = render_openclaw_prompt(
            "sidecar.extract.system",
            variables={"max_candidates": 2},
            fallback="",
        )
        embedded_prompt = render_openclaw_prompt(
            "embedded.extract.system",
            variables={"max_candidates": 1},
            fallback="",
        )
        marker = "standard agent skill artifact used by OpenClaw"
        self.assertIn(marker, sidecar_prompt)
        self.assertIn(marker, embedded_prompt)
        self.assertIn("at most 2 item(s)", sidecar_prompt)
        self.assertIn("at most 1 reusable skill(s)", embedded_prompt)

    def test_missing_template_returns_fallback(self) -> None:
        out = render_openclaw_prompt("missing.template", fallback="fallback-text")
        self.assertEqual(out, "fallback-text")

    def test_custom_pack_supports_block_and_var_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pack = Path(td) / "pack.txt"
            pack.write_text(
                "\n".join(
                    [
                        "@@version test-v1",
                        "@@block shared.marker",
                        "SHARED-LINE",
                        "@@end",
                        "@@template sidecar.extract.system",
                        "X {{block.shared.marker}} Y {{var.max_candidates}}",
                        "@@end",
                    ]
                ),
                encoding="utf-8",
            )
            out = render_openclaw_prompt(
                "sidecar.extract.system",
                variables={"max_candidates": 5},
                fallback="",
                prompt_pack_path=str(pack),
            )
            self.assertIn("SHARED-LINE", out)
            self.assertIn("5", out)


if __name__ == "__main__":
    unittest.main()

