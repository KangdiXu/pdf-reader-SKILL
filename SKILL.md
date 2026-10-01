---
name: pdf-reader
description: Transfer local PDFs to page-aware Markdown, or read and analyze them after transfer, with selective OCR, optional images, explicit output folders, and source-based duplicate detection. Use for papers, reports, books, manuals, scanned PDFs, and pdf-reader usage questions; do not use for creating or editing PDFs.
---

# PDF Reader

Use `scripts/extract_pdf.py`, resolved relative to this `SKILL.md`. Run it through the `pdf_read` environment. Do not copy the source PDF or load an entire long document into model context unless the task requires it.

## Usage questions

When the user asks how to use `pdf-reader`, which options to choose, what it outputs, or requests usage examples, read [README.md](README.md) completely and answer from it. Treat the README as the canonical usage guide; do not invent commands or options that are not documented there.

## Request format

When suggesting how to invoke this skill, prefer a short parameter block so omitted choices are visible:

```text
Action: <transfer / read>
Object: <a PDF file or a directory>
Pages: <whole document / page range>
Images: <no / selected / all>
OCR: <auto / off / force>
OCR language: <eng / chi_sim+eng / other installed languages>
Output tag: <none / short English keyword requested by the user>
Duplicate handling: <default / ignore duplicates, must transfer>
```

Such a short parameter block can also be expressed in sentence or prose, e.g., "Extract pages 12–18 with selected images and OCR forced in English." or "阅读这篇文献，全文，不生成图片，不使用 OCR". The user may also provide a `--output-dir` path. If omitted, the script uses a predictable default output folder.

The user may add `任务`, `输出目录`, and `后缀` / `tag` / `备注`. Accept equivalent prose; do not require exact wording. Map `全文` to all pages, `不生成图片` to `--images none`, `不使用 OCR` to `--ocr off`, and so on. Only pass `--tag` when the user explicitly asks for a suffix, tag, or note; translate its meaning to a short English kebab-case keyword such as `group-meeting` or `revised`. Never infer a tag from pages, image mode, OCR mode, or other processing options. Put any force directive last when suggesting a request. Map phrases such as `忽略重复`, `必须转换`, `强制转换`, or `重新转换` to `--reconvert` (or its alias `--force`).

## Transfer and read

- **Transfer (`转换`, `transfer`)** means creating Markdown and related files only. Run `scripts/extract_pdf.py transfer ...` and report the result paths; do not interpret, summarize, search, or analyze the generated content. `pdf_2_md_main.py` is a backward-compatible wrapper for the same extractor, not a second conversion step. Never run both entry points for one PDF.
- **Read (`阅读`, `read`)** means ensuring a transferred result exists and then analyzing the generated Markdown, page files, and requested images to answer the user's question. Reading therefore includes transfer when no reusable result exists.
- If the wording is only “转换为 Markdown” or “导出 Markdown”, choose transfer. If it asks to read, summarize, search, compare, extract facts, or explain content, choose read.

## Workflow

1. Resolve the supplied path and mode. For a directory, process every PDF directly inside it by default; include nested directories only when the user asks. Handle each PDF separately.
2. Before inspecting or validating requested extraction parameters, check the conversion registry by the absolute `source` path. If a valid result for that source exists, do not transfer again, even when the requested pages, images, OCR settings, output path, source modification time, or parser version differ. An explicitly requested output tag is a naming requirement: reuse only a result with the same tag, otherwise create the requested tagged result. A registered result whose page text fails the native-text quality check is invalid and must be regenerated; this also prevents reuse of legacy empty conversions. Repair any legacy Markdown image links that still expose a temporary staging path, then report and use the registered result without reconverting the PDF. Only a user force phrase, an explicit `--reconvert` / `--force`, or a different explicit tag bypasses an otherwise valid record.
3. For a new or forced transfer, choose the requested extraction behavior:
   - For a short document or whole-document summary, extract all pages without images.
   - For a long document or a focused question, extract only the relevant page range. If the relevant pages are unknown, use the table of contents or extract text-only page files, search them with `rg`, and read only the matches plus nearby pages.
   - Request images only when the task depends on figures, formulas, diagrams, or layout. Use `--images selected` with `--pages` whenever possible.
4. Keep `--ocr auto` unless the document is known to have usable native text (`--ocr off`) or is a scan that needs OCR on every selected page (`--ocr force`). Inspection detects full-page scans with transparent OCR text from span alpha and display-list signals. Such pages use the existing native layer when it is sufficiently populated. Pages that truly need OCR are first rendered to independent bitmaps and then passed to Tesseract so an existing hidden layer cannot suppress OCR output. For non-English scans, choose an installed OCR language. Read [references/ocr.md](references/ocr.md) only when OCR fails or language setup is relevant.
5. Write a new result directly to the requested `--output-dir`. Without one, use `<PDF文件名>` in the current working directory. Keep source identity and all processing options in `manifest.json`, not in the folder name. If and only if the user explicitly requested a tag, append `-<english-tag>` to either the automatic or explicit output folder name. If that folder already belongs to a different source, do not overwrite it; require another `--output-dir` or an explicit tag. The combined Markdown is named `<PDF文件名>.md`. Store every extracted image under the final output's `images/` directory. Combined Markdown must link to `images/<文件名>` and files under `pages/` must link to `../images/<文件名>`; never expose the temporary staging directory in generated Markdown. For directory input, use one output subfolder per PDF.
6. In transfer mode, stop after reporting generated or reused paths. In read mode, read generated files selectively, answer the user's question, and cite PDF page numbers. If a source-only duplicate lacks the pages or images needed for the requested analysis, explain that a forced transfer is required; do not force it implicitly.

## Commands

Set the script path from this skill's directory, then run:

```bash
conda run --no-capture-output -n pdf_read python "/absolute/path/to/pdf-reader/scripts/extract_pdf.py" inspect "/absolute/path/input.pdf"
```

Transfer with page-aware output:

```bash
conda run --no-capture-output -n pdf_read python "/absolute/path/to/pdf-reader/scripts/extract_pdf.py" transfer "/absolute/path/input.pdf" --output-dir "/absolute/path/output"
```

Focused extraction with figures:

```bash
conda run --no-capture-output -n pdf_read python "/absolute/path/to/pdf-reader/scripts/extract_pdf.py" extract "/absolute/path/input.pdf" --output-dir "/absolute/path/output" --pages "12-18" --images selected
```

Explicitly tagged output:

```bash
conda run --no-capture-output -n pdf_read python "/absolute/path/to/pdf-reader/scripts/extract_pdf.py" transfer "/absolute/path/input.pdf" --tag "group-meeting"
```

The command prints a compact JSON result. The specified output folder contains source-named Markdown, optional `pages/`, optional `images/`, and `manifest.json`. The manifest records all processing parameters, the explicit output tag if any, each page's extraction backend, native/layout/output character counts, hidden-OCR status, quality result, and fallback reason. By default, `pdf-reader-conversions.json` is stored beside the source PDF so the same source is recognized across requested output locations. Re-running a registered source returns `status: already_converted` regardless of processing parameters unless the registered text fails quality validation or the user explicitly requested a different tag. Use `--reconvert` or `--force` only for an explicit force request. Image filenames are not printed unless `--verbose` is used.

## Failure handling

- If the command cannot import its dependencies, then check whether the `pdf_read` environment exists. Do not run an environment inventory before every successful extraction.
- If auto OCR gives poor results and the user asks to redo it, retry only the affected pages with `--ocr force`, an appropriate `--ocr-language`, and `--reconvert`. Forced OCR uses a separately rendered page bitmap.
- If the registry entry exists but its output folder or manifest is missing or inconsistent, do not reuse it; regenerate or report a protected-output conflict.
- If extraction fails, report the failing command and error. Do not silently fall back to an unverified full-document conversion.
