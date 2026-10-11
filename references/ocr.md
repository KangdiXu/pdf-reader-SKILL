# OCR guidance

Read this reference only when the PDF is scanned, automatic OCR fails, or the OCR language must be configured.

- `--ocr auto` checks native text density, transparent span alpha, display-list text/image types, and full-page image coverage. A full-page scan with a sufficiently populated hidden OCR layer uses PyMuPDF native text; only pages without a usable native layer go through OCR. This is the normal default.
- `--ocr off` avoids Tesseract entirely and is fastest for digitally generated PDFs. The extractor may still fall back from incomplete PyMuPDF4LLM output to an existing native PDF text layer; that is text extraction, not OCR.
- `--ocr force` renders every selected PDF page to a separate 300-DPI bitmap and sends that bitmap to Tesseract. Restrict it with `--pages` because it is substantially slower.
- `--ocr-language` is passed to the PyMuPDF/Tesseract bitmap OCR backend. Common examples are `eng`, `chi_sim`, and `chi_sim+eng`, but installed language data varies by machine.

The extractor resolves language data only when a page actually needs OCR. It checks, in order:

1. `TESSDATA_PREFIX` from the current process;
2. common `tessdata` locations inside the active Python/Conda environment;
3. the path reported by PyMuPDF.

The selected directory must contain every requested `<language>.traineddata` file. For example, `chi_sim+eng` requires both `chi_sim.traineddata` and `eng.traineddata`; the extractor never silently falls back to English. An explicitly set but invalid `TESSDATA_PREFIX` is reported as an error instead of being ignored.

Configure the current terminal after installing the required Tesseract language files:

```bash
export TESSDATA_PREFIX="/absolute/path/to/tessdata"
```

PowerShell:

```powershell
$env:TESSDATA_PREFIX = "C:\absolute\path\to\tessdata"
```

Windows CMD:

```bat
set "TESSDATA_PREFIX=C:\absolute\path\to\tessdata"
```

Prefer a current-terminal setting while diagnosing the skill. Do not change a machine-wide environment variable unless the user explicitly requests that broader change. Re-run the installer to execute a small in-memory OCR probe, or call `check_ocr(language)` from `scripts/extract_pdf.py`, after changing the language data.

Each `manifest.json` records the backend, input/output character counts, hidden-OCR decision, quality result, and fallback reason for every processed page. A measurable loss against a sufficiently populated native layer is rejected rather than registered as a successful conversion.

If the requested language is unavailable, report that dependency problem and either use an installed language with the user's consent or ask for a searchable PDF. Do not claim that OCR text is exact; verify names, equations, and numerical tables against the rendered page when accuracy matters.
