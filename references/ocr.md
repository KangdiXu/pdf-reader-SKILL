# OCR guidance

Read this reference only when the PDF is scanned, automatic OCR fails, or the OCR language must be configured.

- `--ocr auto` first checks native text density and OCRs only likely scanned pages. This is the normal default.
- `--ocr off` avoids OCR entirely and is fastest for digitally generated PDFs.
- `--ocr force` renders and OCRs every selected page. Restrict it with `--pages` because it is substantially slower.
- `--ocr-language` is passed to the available PyMuPDF OCR backend. Common Tesseract examples are `eng`, `chi_sim`, and `chi_sim+eng`, but installed language data varies by machine.

If the requested language is unavailable, report that dependency problem and either use an installed language with the user's consent or ask for a searchable PDF. Do not claim that OCR text is exact; verify names, equations, and numerical tables against the rendered page when accuracy matters.
