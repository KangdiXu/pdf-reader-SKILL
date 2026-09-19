"""Backward-compatible entry point for the pdf-reader skill.

New callers should use ``scripts/extract_pdf.py`` with the ``inspect``,
``transfer``, or ``extract`` subcommand. The historical invocation

    python pdf_2_md_main.py INPUT.pdf [OUTPUT_DIR] [OPTIONS]

is translated to the new extractor so existing installations keep working.
The default source-derived output name is owned by ``extract_pdf.py`` so both
entry points always produce the same name.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def translate_args(values: list[str]) -> list[str]:
    args = list(values)
    known_commands = {"inspect", "extract", "transfer", "-h", "--help"}

    if args and args[0] not in known_commands:
        legacy = ["extract", args[0]]
        remaining = args[1:]
        if remaining and remaining[0] and not remaining[0].startswith("-"):
            legacy.extend(["--output-dir", remaining.pop(0)])
        legacy.extend(remaining)
        args = legacy
    return args


def main() -> None:
    script = Path(__file__).resolve().parent / "scripts" / "extract_pdf.py"
    args = translate_args(sys.argv[1:])

    sys.argv = [str(script), *args]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
