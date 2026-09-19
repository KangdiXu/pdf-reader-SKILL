from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
WRAPPER = SKILL_DIR / "pdf_2_md_main.py"

spec = importlib.util.spec_from_file_location("pdf_2_md_main", WRAPPER)
pdf_2_md_main = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(pdf_2_md_main)


class LegacyEntryTests(unittest.TestCase):
    def test_legacy_output_and_force_options_are_preserved(self) -> None:
        translated = pdf_2_md_main.translate_args(
            ["input.pdf", "/tmp/result", "--pages", "2", "--force"]
        )
        self.assertEqual(
            translated,
            [
                "extract",
                "input.pdf",
                "--output-dir",
                "/tmp/result",
                "--pages",
                "2",
                "--force",
            ],
        )

    def test_transfer_subcommand_is_not_rewritten(self) -> None:
        values = ["transfer", "input.pdf", "--force"]
        self.assertEqual(pdf_2_md_main.translate_args(values), values)


if __name__ == "__main__":
    unittest.main()
