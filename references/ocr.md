# OCR guidance

Read this reference only when the PDF is scanned, automatic OCR fails, or the OCR language must be configured.

- `--ocr auto` checks native text density, transparent span alpha, display-list text/image types, and full-page image coverage. A full-page scan with a sufficiently populated hidden OCR layer uses PyMuPDF native text; only pages without a usable native layer go through OCR. This is the normal default.
- `--ocr off` avoids Tesseract entirely and is fastest for digitally generated PDFs. The extractor may still fall back from incomplete PyMuPDF4LLM output to an existing native PDF text layer; that is text extraction, not OCR.
- `--ocr force` renders every selected PDF page to a separate 300-DPI bitmap and sends that bitmap to Tesseract. Restrict it with `--pages` because it is substantially slower.
- `--ocr-language` is passed to the PyMuPDF/Tesseract bitmap OCR backend. Common examples are `eng`, `chi_sim`, and `chi_sim+eng`, but installed language data varies by machine.

Each `manifest.json` records the backend, input/output character counts, hidden-OCR decision, quality result, and fallback reason for every processed page. A measurable loss against a sufficiently populated native layer is rejected rather than registered as a successful conversion.

If the requested language is unavailable, report that dependency problem and either use an installed language with the user's consent or ask for a searchable PDF. Do not claim that OCR text is exact; verify names, equations, and numerical tables against the rendered page when accuracy matters.
