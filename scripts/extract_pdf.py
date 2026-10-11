#!/usr/bin/env python3
"""Inspect and selectively extract PDFs for efficient LLM consumption."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote

import pymupdf
import pymupdf4llm


SCANNED_TEXT_THRESHOLD = 40
OUTPUT_TO_NATIVE_MIN_RATIO = 0.2
OCR_DPI = 300
FULL_PAGE_IMAGE_MIN_RATIO = 0.5
OUTPUT_TAG_MAX_LENGTH = 48
MANIFEST_SCHEMA_VERSION = 8
REGISTRY_SCHEMA_VERSION = 1
REGISTRY_FILENAME = "pdf-reader-conversions.json"
COMBINED_MARKDOWN_FILENAME = "document.md"
IMAGE_SOURCE_NAME = "pdf-reader.pdf"
MARKDOWN_IMAGE_OPEN_RE = re.compile(r"!\[[^\]\n]*\]\(")
PAGE_MARKER_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
IGNORED_OUTPUT_FILE_NAMES = {".DS_Store"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CLOCK$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def validate_pdf(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"输入路径不是文件: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"输入文件必须是 PDF: {path}")
    return path


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    """Parse a user-facing 1-based page expression into sorted 0-based pages."""
    if not spec or spec.strip().lower() == "all":
        return list(range(page_count))

    selected: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"页码范围起点不能大于终点: {token}")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(token))

    if not selected:
        raise ValueError("页码范围为空")
    invalid = sorted(page for page in selected if page < 1 or page > page_count)
    if invalid:
        raise ValueError(f"页码超出 1-{page_count} 范围: {invalid}")
    return [page - 1 for page in sorted(selected)]


def page_diagnostics(
    page: pymupdf.Page,
    page_index: int,
    *,
    native_text: str | None = None,
) -> dict[str, Any]:
    """Measure native, hidden, visible, image, and display-list page content."""
    if native_text is None:
        native_text = page.get_text("text", sort=True)

    raw = page.get_text("rawdict")
    spans = [
        span
        for block in raw.get("blocks", [])
        if block.get("type") == 0
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    ]

    hidden_spans = [span for span in spans if span.get("alpha", 255) == 0]
    visible_spans = [span for span in spans if span.get("alpha", 255) != 0]
    hidden_text_chars = sum(len(span.get("chars", [])) for span in hidden_spans)
    visible_text_chars = sum(len(span.get("chars", [])) for span in visible_spans)

    bboxlog = page.get_bboxlog()
    bboxlog_counts = Counter(item[0] for item in bboxlog)
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    image_area_ratios = []
    for item in bboxlog:
        if item[0] != "fill-image":
            continue
        bbox = pymupdf.Rect(item[1]) & page.rect
        image_area_ratios.append(max(0.0, float(bbox.width * bbox.height)) / page_area)

    text_chars = len(native_text.strip())
    image_count = len(page.get_images(full=True))
    largest_image_area_ratio = max(image_area_ratios, default=0.0)
    has_page_image = image_count > 0 or bboxlog_counts["fill-image"] > 0
    hidden_ocr_page = (
        hidden_text_chars >= SCANNED_TEXT_THRESHOLD
        and bboxlog_counts["ignore-text"] > 0
        and largest_image_area_ratio >= FULL_PAGE_IMAGE_MIN_RATIO
    )
    likely_scanned = (
        (text_chars < SCANNED_TEXT_THRESHOLD and has_page_image)
        or hidden_ocr_page
    )

    return {
        "page": page_index + 1,
        "text_chars": text_chars,
        "image_count": image_count,
        "transparent_text_spans": len(hidden_spans),
        "transparent_text_chars": hidden_text_chars,
        "visible_text_spans": len(visible_spans),
        "visible_text_chars": visible_text_chars,
        "bboxlog": {
            "ignore_text": bboxlog_counts["ignore-text"],
            "fill_text": bboxlog_counts["fill-text"],
            "fill_image": bboxlog_counts["fill-image"],
        },
        "largest_image_area_ratio": round(largest_image_area_ratio, 6),
        "hidden_ocr_page": hidden_ocr_page,
        "likely_scanned": likely_scanned,
    }


def inspect_document(pdf_path: Path) -> dict[str, Any]:
    with pymupdf.open(pdf_path) as document:
        if document.needs_pass:
            raise ValueError("PDF 已加密，需要先提供无密码副本")

        page_stats = []
        likely_scanned_pages = []
        hidden_ocr_pages = []
        total_chars = 0
        total_images = 0
        for index, page in enumerate(document):
            native_text = page.get_text("text", sort=True)
            stats = page_diagnostics(page, index, native_text=native_text)
            total_chars += stats["text_chars"]
            total_images += stats["image_count"]
            if stats["likely_scanned"]:
                likely_scanned_pages.append(index + 1)
            if stats["hidden_ocr_page"]:
                hidden_ocr_pages.append(index + 1)
            page_stats.append(stats)

        toc = [
            {"level": level, "title": title, "page": page}
            for level, title, page, *_ in document.get_toc(simple=False)
        ]
        metadata = {key: value for key, value in document.metadata.items() if value}

        return {
            "source": str(pdf_path),
            "page_count": document.page_count,
            "text_chars": total_chars,
            "image_count": total_images,
            "likely_scanned_pages": likely_scanned_pages,
            "hidden_ocr_pages": hidden_ocr_pages,
            "metadata": metadata,
            "toc": toc,
            "pages": page_stats,
        }


def is_windows_reserved_name(value: str) -> bool:
    """Return whether one path component is unusable as a Windows file name."""
    normalized = value.rstrip(". ")
    if not normalized:
        return True
    device_name = normalized.split(".", 1)[0].upper()
    return device_name in WINDOWS_RESERVED_NAMES


def safe_stem(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]+", "-", path.stem).strip("-. ")
    stem = stem[:80].rstrip("-. ") or "document"
    if is_windows_reserved_name(stem):
        stem = f"_{stem}"[:80]
    return stem


def source_key(pdf_path: Path) -> str:
    encoded = str(pdf_path.expanduser().resolve()).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_output_tag(value: str | None) -> str | None:
    """Normalize an explicitly requested English output-folder tag."""
    if value is None or not value.strip():
        return None
    tag = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not tag:
        raise ValueError("--tag 必须包含英文关键词或数字")
    tag = tag[:OUTPUT_TAG_MAX_LENGTH].rstrip("-")
    if not tag:
        raise ValueError("--tag 无法生成有效的英文关键词")
    return tag


def append_output_tag(path: Path, output_tag: str | None) -> Path:
    if not output_tag:
        return path
    suffix = f"-{output_tag}"
    if path.name.lower().endswith(suffix):
        return path
    return path.with_name(f"{path.name}{suffix}")


def default_output_name(pdf_path: Path, output_tag: str | None = None) -> str:
    base_name = safe_stem(pdf_path)
    return append_output_tag(
        Path(base_name),
        normalize_output_tag(output_tag),
    ).name


def markdown_filename(_pdf_path: Path) -> str:
    return COMBINED_MARKDOWN_FILENAME


def make_conversion_id(
    pdf_path: Path,
    output_dir: Path,
    parameters: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    stat = pdf_path.stat()
    identity = {
        "source": str(pdf_path),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "output_dir": str(output_dir),
        "pymupdf_version": pymupdf.__version__,
        "pymupdf4llm_version": pymupdf4llm.__version__,
        "parameters": parameters,
    }
    return source_key(pdf_path), identity


def page_number(chunk: dict[str, Any]) -> int:
    metadata = chunk.get("metadata") or {}
    return int(metadata.get("page_number", 0))


class ImageExtractionDocument(pymupdf.Document):
    """Open the source normally, but expose a short name to the image writer."""

    @property
    def name(self) -> str:
        return IMAGE_SOURCE_NAME


def shorten_generated_image_names(image_dir: Path) -> dict[str, str]:
    """Keep backend page/region numbers and remove the short source prefix."""
    if not image_dir.is_dir():
        return {}
    names = {}
    use_layout = getattr(pymupdf4llm, "_use_layout", True)
    pattern = re.compile(rf"{re.escape(IMAGE_SOURCE_NAME)}-(\d+)-(\d+)\.png")
    for path in sorted(image_dir.iterdir()):
        if not path.is_file():
            continue
        match = pattern.fullmatch(path.name)
        if not match:
            raise ValueError(f"无法识别图片的页码和数字区域编号: {path.name}")
        page, region = map(int, match.groups())
        # The legacy backend uses zero-based page numbers; layout uses one-based.
        if not use_layout:
            page += 1
        target_name = f"{page:04d}-{region:02d}.png"
        if target_name in names.values() or (image_dir / target_name).exists():
            raise ValueError(f"图片名称冲突，拒绝覆盖: {target_name}")
        names[path.name] = target_name
    for original_name, target_name in names.items():
        (image_dir / original_name).rename(image_dir / target_name)
    return names


def convert_pages(
    pdf_path: Path,
    pages: Iterable[int],
    *,
    image_dir: Path,
    write_images: bool,
    use_ocr: bool,
    force_ocr: bool,
    ocr_language: str,
    verbose: bool,
) -> list[dict[str, Any]]:
    page_list = list(pages)
    if not page_list:
        return []

    library_output = io.StringIO()
    # The library derives saved image names from Document.name. A per-document
    # wrapper avoids long filenames before the first save, without copying the PDF
    # or changing the source file or any library-wide naming function.
    with contextlib.redirect_stdout(library_output), ImageExtractionDocument(pdf_path) as document:
        chunks = pymupdf4llm.to_markdown(
            document,
            pages=page_list,
            page_chunks=True,
            page_separators=False,
            write_images=write_images,
            image_path=str(image_dir),
            image_format="png",
            use_ocr=use_ocr,
            force_ocr=force_ocr,
            ocr_language=ocr_language,
            show_progress=False,
        )
    image_names = shorten_generated_image_names(image_dir) if write_images else {}
    for chunk in chunks:
        metadata = chunk.get("metadata")
        if isinstance(metadata, dict):
            metadata["file_path"] = str(pdf_path)
        if image_names:
            chunk["text"] = portable_markdown(
                chunk.get("text", ""), image_dir, image_name_map=image_names
            )
    if verbose and library_output.getvalue():
        print(library_output.getvalue(), file=sys.stderr, end="")
    return chunks


def raster_ocr_page(
    document: pymupdf.Document,
    page_index: int,
    *,
    language: str,
) -> str:
    """OCR an independent rasterized page so existing PDF text cannot interfere."""
    page_number_value = page_index + 1
    try:
        tessdata = resolve_ocr_tessdata(language)
        pixmap = document[page_index].get_pixmap(
            dpi=OCR_DPI,
            colorspace=pymupdf.csRGB,
            alpha=False,
        )
        ocr_pdf = pixmap.pdfocr_tobytes(
            language=language,
            compress=True,
            tessdata=str(tessdata),
        )
        with pymupdf.open(stream=ocr_pdf, filetype="pdf") as ocr_document:
            return ocr_document[0].get_text("text", sort=True).strip()
    except RuntimeError as exc:
        raise RuntimeError(
            f"PDF 第 {page_number_value} 页位图 OCR 失败: {exc}"
        ) from exc


def _tessdata_languages(language: str) -> list[str]:
    languages = [item.strip() for item in language.split("+") if item.strip()]
    if not languages:
        raise ValueError("OCR 语言不能为空")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", item) for item in languages):
        raise ValueError(f"OCR 语言格式无效: {language}")
    return languages


def _usable_tessdata_directory(path: Path, languages: list[str]) -> Path | None:
    for candidate in (path, path / "tessdata"):
        if candidate.is_dir() and all(
            (candidate / f"{item}.traineddata").is_file() for item in languages
        ):
            return candidate.resolve()
    return None


def resolve_ocr_tessdata(language: str) -> Path:
    """Find one tessdata directory containing every requested OCR language."""
    languages = _tessdata_languages(language)
    explicit = os.environ.get("TESSDATA_PREFIX")
    if explicit:
        resolved = _usable_tessdata_directory(
            Path(explicit).expanduser(), languages
        )
        if resolved:
            return resolved
        missing = ", ".join(f"{item}.traineddata" for item in languages)
        raise RuntimeError(
            "TESSDATA_PREFIX 未指向包含所需语言数据的目录: "
            f"{explicit}；需要 {missing}"
        )

    candidates = [
        Path(sys.prefix) / "share" / "tessdata",
        Path(sys.prefix) / "share" / "tesseract-ocr" / "tessdata",
        Path(sys.prefix) / "Library" / "share" / "tessdata",
        Path(sys.prefix) / "Library" / "bin" / "tessdata",
        Path(sys.prefix) / "tessdata",
    ]
    get_tessdata = getattr(pymupdf, "get_tessdata", None)
    if callable(get_tessdata):
        try:
            detected = get_tessdata()
        except (OSError, RuntimeError):
            detected = None
        if detected:
            candidates.append(Path(detected))

    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.expanduser().absolute()))
        if key in seen:
            continue
        seen.add(key)
        resolved = _usable_tessdata_directory(candidate.expanduser(), languages)
        if resolved:
            return resolved

    requested = ", ".join(f"{item}.traineddata" for item in languages)
    raise RuntimeError(
        "未找到可用的 OCR 语言数据。"
        f"需要 {requested}；请安装语言文件并为当前终端设置 TESSDATA_PREFIX。"
    )


def check_ocr(language: str) -> dict[str, str]:
    """Validate language data with a small in-memory Tesseract OCR operation."""
    tessdata = resolve_ocr_tessdata(language)
    with pymupdf.open() as document:
        page = document.new_page(width=180, height=60)
        page.insert_text((12, 35), "OCR test", fontsize=18)
        pixmap = page.get_pixmap(dpi=150, colorspace=pymupdf.csRGB, alpha=False)
        pixmap.pdfocr_tobytes(
            language=language,
            compress=True,
            tessdata=str(tessdata),
        )
    return {"language": language, "tessdata": str(tessdata)}


def markdown_unescape(value: str) -> str:
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!])", r"\1", value)


def markdown_filename_variants(filename: str) -> set[str]:
    escaped = re.sub(r"([\\`*_{}\[\]()#+\-.!])", r"\\\1", filename)
    return {
        filename,
        filename.replace("_", r"\_"),
        escaped,
        quote(filename),
    }


def markdown_image_target_bounds(
    line: str,
    target_start: int,
) -> tuple[int, int, int] | None:
    """Return searchable target bounds and the link-closing parenthesis."""
    if target_start >= len(line):
        return None

    if line[target_start] == "<":
        index = target_start + 1
        while index < len(line):
            if line[index] == "\\":
                index += 2
                continue
            if line[index] == ">":
                closing = line.find(")", index + 1)
                if closing >= 0:
                    return target_start + 1, index, closing
                return None
            index += 1
        return None

    depth = 0
    index = target_start
    while index < len(line):
        if line[index] == "\\":
            index += 2
            continue
        if line[index] == "(":
            depth += 1
        elif line[index] == ")":
            if depth == 0:
                return target_start, index, index
            depth -= 1
        index += 1
    return None


def rewrite_image_links_in_line(
    line: str,
    image_names: set[str],
    image_prefix: str,
    image_name_map: dict[str, str] | None = None,
) -> str:
    search_from = 0
    while True:
        opening = MARKDOWN_IMAGE_OPEN_RE.search(line, search_from)
        if not opening:
            return line

        target_start = opening.end()
        bounds = markdown_image_target_bounds(line, target_start)
        if not bounds:
            search_from = target_start
            continue
        searchable_start, searchable_end, closing = bounds

        candidates: list[tuple[int, str, str]] = []
        for filename in image_names:
            for variant in markdown_filename_variants(filename):
                index = line.find(variant, searchable_start, searchable_end)
                if index < 0:
                    continue
                target_prefix = markdown_unescape(
                    line[searchable_start:index]
                ).replace("\\", "/")
                if "images/" in target_prefix:
                    candidates.append((index, filename, variant))

        if not candidates:
            search_from = target_start
            continue

        filename = min(
            candidates,
            key=lambda candidate: (candidate[0], -len(candidate[2])),
        )[1]
        target_name = image_name_map.get(filename, filename) if image_name_map else filename
        portable_target = f"{image_prefix.rstrip('/')}/{target_name}"
        if any(character.isspace() for character in portable_target) or any(
            character in portable_target for character in "()"
        ):
            portable_target = f"<{portable_target}>"
        line = f"{line[:target_start]}{portable_target}{line[closing:]}"
        search_from = target_start + len(portable_target) + 1


def portable_markdown(
    text: str,
    image_dir: Path,
    *,
    image_prefix: str = "images",
    image_name_map: dict[str, str] | None = None,
) -> str:
    """Rewrite generated image links so no temporary path survives."""
    image_names = (
        {item.name for item in image_dir.iterdir() if item.is_file()}
        if image_dir.exists()
        else set()
    )
    if image_name_map:
        image_names.update(image_name_map)

    rewritten = "".join(
        rewrite_image_links_in_line(line, image_names, image_prefix, image_name_map)
        for line in text.splitlines(keepends=True)
    )
    return rewritten.strip() + "\n"


def remove_markdown_image_links(text: str) -> str:
    """Remove image link targets before measuring actual body text."""
    lines = []
    for original_line in text.splitlines(keepends=True):
        line = original_line
        search_from = 0
        while True:
            opening = MARKDOWN_IMAGE_OPEN_RE.search(line, search_from)
            if not opening:
                break
            bounds = markdown_image_target_bounds(line, opening.end())
            if not bounds:
                search_from = opening.end()
                continue
            closing = bounds[2]
            line = f"{line[:opening.start()]}{line[closing + 1:]}"
            search_from = opening.start()
        lines.append(line)
    return "".join(lines)


def markdown_body_char_count(text: str) -> int:
    """Count non-whitespace body characters, excluding comments and image paths."""
    without_comments = HTML_COMMENT_RE.sub("", text)
    without_images = remove_markdown_image_links(without_comments)
    return len(re.sub(r"\s+", "", without_images))


def markdown_image_references(text: str) -> list[str]:
    """Collect generated Markdown image expressions for a text fallback."""
    references = []
    for line in text.splitlines():
        search_from = 0
        while True:
            opening = MARKDOWN_IMAGE_OPEN_RE.search(line, search_from)
            if not opening:
                break
            bounds = markdown_image_target_bounds(line, opening.end())
            if not bounds:
                search_from = opening.end()
                continue
            closing = bounds[2]
            references.append(line[opening.start() : closing + 1])
            search_from = closing + 1
    return references


def preserve_image_references(replacement: str, generated_markdown: str) -> str:
    references = markdown_image_references(generated_markdown)
    parts = [replacement.strip(), *references]
    return "\n\n".join(part for part in parts if part).strip()


def output_is_far_below_native(output_text: str, native_text: str) -> bool:
    native_chars = markdown_body_char_count(native_text)
    if native_chars < SCANNED_TEXT_THRESHOLD:
        return False
    output_chars = markdown_body_char_count(output_text)
    return output_chars < native_chars * OUTPUT_TO_NATIVE_MIN_RATIO


def extract_page_content(
    pdf_path: Path,
    pages: list[int],
    chunks: list[dict[str, Any]],
    inspection: dict[str, Any],
    *,
    ocr_mode: str,
    ocr_language: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Choose a verified extraction backend independently for every page."""
    chunks_by_page = {page_number(chunk): chunk for chunk in chunks}
    diagnostics_by_page = {
        item["page"]: item for item in inspection.get("pages", [])
    }
    verified_chunks = []
    extraction_records = []

    with pymupdf.open(pdf_path) as document:
        for page_index in pages:
            number = page_index + 1
            original_chunk = chunks_by_page.get(number) or {
                "metadata": {"page_number": number},
                "text": "",
            }
            generated_text = str(original_chunk.get("text") or "")
            native_text = document[page_index].get_text("text", sort=True).strip()
            page_stats = diagnostics_by_page[number]

            backend = "pymupdf4llm"
            fallback_reason = None
            selected_text = generated_text

            needs_raster_ocr = ocr_mode == "force" or (
                ocr_mode == "auto"
                and page_stats["likely_scanned"]
                and markdown_body_char_count(native_text) < SCANNED_TEXT_THRESHOLD
            )
            if needs_raster_ocr:
                selected_text = raster_ocr_page(
                    document,
                    page_index,
                    language=ocr_language,
                )
                selected_text = preserve_image_references(
                    selected_text,
                    generated_text,
                )
                backend = "tesseract_raster_ocr"
                fallback_reason = (
                    "ocr_force" if ocr_mode == "force" else "ocr_auto_scanned_page"
                )
            elif (
                page_stats["hidden_ocr_page"]
                and markdown_body_char_count(native_text) >= SCANNED_TEXT_THRESHOLD
            ):
                selected_text = preserve_image_references(
                    native_text,
                    generated_text,
                )
                backend = "pymupdf_native_text"
                fallback_reason = "hidden_ocr_page_prefers_native_text"

            candidate_backend = backend
            if output_is_far_below_native(selected_text, native_text):
                selected_text = preserve_image_references(
                    native_text,
                    generated_text,
                )
                backend = "pymupdf_native_text"
                fallback_reason = (
                    f"{candidate_backend}_output_below_native_text_ratio"
                )

            native_body_chars = markdown_body_char_count(native_text)
            output_body_chars = markdown_body_char_count(selected_text)
            quality_passed = not (
                native_body_chars >= SCANNED_TEXT_THRESHOLD
                and output_body_chars
                < native_body_chars * OUTPUT_TO_NATIVE_MIN_RATIO
            )
            if not quality_passed:
                raise RuntimeError(
                    "PDF 第 "
                    f"{number} 页正文质量检查失败: 输出 {output_body_chars} 字符，"
                    f"原生文本 {native_body_chars} 字符"
                )

            verified_chunk = dict(original_chunk)
            metadata = dict(verified_chunk.get("metadata") or {})
            metadata["page_number"] = number
            verified_chunk["metadata"] = metadata
            verified_chunk["text"] = selected_text
            verified_chunks.append(verified_chunk)
            extraction_records.append(
                {
                    "page": number,
                    "backend": backend,
                    "native_text_chars": len(native_text),
                    "native_body_chars": native_body_chars,
                    "pymupdf4llm_text_chars": len(generated_text.strip()),
                    "pymupdf4llm_body_chars": markdown_body_char_count(
                        generated_text
                    ),
                    "output_text_chars": len(selected_text.strip()),
                    "output_body_chars": output_body_chars,
                    "hidden_ocr_page": page_stats["hidden_ocr_page"],
                    "quality_passed": quality_passed,
                    "fallback_reason": fallback_reason,
                }
            )

    if pages and not any(record["output_body_chars"] for record in extraction_records):
        attempted_ocr = ocr_mode != "off" and any(
            diagnostics_by_page[page + 1]["likely_scanned"] for page in pages
        )
        if attempted_ocr:
            raise RuntimeError("所有选定页面的 OCR 正文均为空，拒绝登记空转换结果")

    return verified_chunks, extraction_records


def resolve_output_dir(
    pdf_path: Path,
    value: str | None,
    output_tag: str | None = None,
) -> Path:
    normalized_tag = normalize_output_tag(output_tag)
    base = (
        Path(value).expanduser().resolve()
        if value
        else (Path.cwd() / default_output_name(pdf_path)).resolve()
    )
    result = append_output_tag(base, normalized_tag)
    if value and os.name == "nt" and is_windows_reserved_name(result.name):
        raise ValueError(f"--output-dir 使用了 Windows 保留名称: {result}")
    return result


def _validated_manifest_paths(value: Any, field: str, target: Path) -> set[str]:
    if value is None and field == "generated_dirs":
        return set()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"manifest.json 的 {field} 必须是字符串数组: {target}")
    result = set()
    for item in value:
        path = PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
            raise ValueError(f"manifest.json 的 {field} 包含无效路径: {item}")
        result.add(path.as_posix())
    return result


def validate_replaceable_output(target: Path) -> dict[str, Any] | None:
    """Validate a tool-generated directory and return its manifest when present."""
    if not target.exists():
        return None
    if not target.is_dir():
        raise ValueError(f"输出路径已存在且不是文件夹: {target}")

    if not any(target.iterdir()):
        return None
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(
            f"输出文件夹包含非 pdf-reader 文件，拒绝覆盖: {target}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法验证已有输出文件夹: {target}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest.json 顶层必须是对象: {target}")
    if manifest.get("generator") != "pdf-reader":
        raise ValueError(f"输出文件夹不是 pdf-reader 生成的，拒绝覆盖: {target}")
    expected_files = _validated_manifest_paths(
        manifest.get("generated_files"), "generated_files", target
    )
    expected_dirs = _validated_manifest_paths(
        manifest.get("generated_dirs"), "generated_dirs", target
    )
    actual_files = {
        item.relative_to(target).as_posix()
        for item in target.rglob("*")
        if item.is_file() and item.name not in IGNORED_OUTPUT_FILE_NAMES
    }
    actual_dirs = {
        item.relative_to(target).as_posix()
        for item in target.rglob("*")
        if item.is_dir()
    }
    if actual_files != expected_files or actual_dirs != expected_dirs:
        raise ValueError(
            f"输出文件夹在生成后被修改，拒绝覆盖其中可能存在的用户文件: {target}"
        )
    return manifest


def resolve_registry_file(pdf_path: Path, target: Path, value: str | None) -> Path:
    registry = (
        Path(value).expanduser().resolve()
        if value
        else (pdf_path.parent / REGISTRY_FILENAME).resolve()
    )
    try:
        registry.relative_to(target)
    except ValueError:
        return registry
    raise ValueError("转换登记 JSON 不能放在输出文件夹内部")


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "conversions": []}
    if not path.is_file():
        raise ValueError(f"转换登记路径不是文件: {path}")
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"转换登记 JSON 无法读取: {path}") from exc
    if not isinstance(registry, dict):
        raise ValueError(f"转换登记 JSON 顶层必须是对象: {path}")
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"不支持的转换登记 JSON 版本: {path}")
    conversions = registry.get("conversions")
    if not isinstance(conversions, list):
        raise ValueError(f"转换登记 JSON 缺少 conversions 数组: {path}")
    for index, entry in enumerate(conversions):
        if not isinstance(entry, dict):
            raise ValueError(f"转换登记 JSON 第 {index + 1} 项必须是对象: {path}")
        for field in ("source", "output_dir"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise ValueError(
                    f"转换登记 JSON 第 {index + 1} 项的 {field} 必须是非空字符串: {path}"
                )
    return registry


def write_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}-",
            delete=False,
        ) as temp_file:
            json.dump(registry, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_name = temp_file.name
        Path(temp_name).replace(path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


@contextlib.contextmanager
def exclusive_file_lock(path: Path, timeout: float = 60.0) -> Iterable[None]:
    """Acquire a small cross-platform advisory lock file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"等待文件锁超时: {path}")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def lock_file_for(*values: Path | str) -> Path:
    key = "\0".join(os.path.normcase(str(value)) for value in values).encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return Path(tempfile.gettempdir()) / "pdf-reader-locks" / f"{digest}.lock"


def same_source(value: Any, pdf_path: Path) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return Path(value).expanduser().resolve() == pdf_path


def manifest_markdown_path(output_dir: Path, manifest: dict[str, Any]) -> Path:
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest.json 顶层必须是对象: {output_dir}")
    markdown_file = manifest.get("markdown_file")
    if isinstance(markdown_file, str) and markdown_file:
        path = PurePosixPath(markdown_file)
        if not path.is_absolute() and ".." not in path.parts:
            return output_dir / Path(*path.parts)
        raise ValueError(f"manifest.json 的 markdown_file 路径无效: {output_dir}")
    default = output_dir / COMBINED_MARKDOWN_FILENAME
    if default.is_file():
        return default
    generated = manifest.get("generated_files") or []
    if not isinstance(generated, list):
        raise ValueError(f"manifest.json 的 generated_files 必须是数组: {output_dir}")
    for relative in generated:
        if not isinstance(relative, str):
            raise ValueError(
                f"manifest.json 的 generated_files 必须是字符串数组: {output_dir}"
            )
        path = Path(relative)
        if len(path.parts) == 1 and path.suffix.lower() == ".md":
            return output_dir / path
    raise ValueError(f"manifest.json 未记录合并 Markdown: {output_dir}")


def split_combined_markdown_pages(text: str) -> dict[int, str]:
    matches = list(PAGE_MARKER_RE.finditer(text))
    pages = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages[int(match.group(1))] = text[match.end() : end]
    return pages


def output_page_texts(
    output_dir: Path,
    manifest: dict[str, Any],
) -> dict[int, str]:
    page_dir = output_dir / "pages"
    if page_dir.is_dir():
        result = {}
        for page_path in page_dir.glob("*.md"):
            try:
                number = int(page_path.stem)
            except ValueError:
                continue
            result[number] = page_path.read_text(encoding="utf-8")
        return result

    combined = manifest_markdown_path(output_dir, manifest).read_text(
        encoding="utf-8"
    )
    return split_combined_markdown_pages(combined)


def registered_output_quality_is_valid(
    output_dir: Path,
    manifest: dict[str, Any],
    pdf_path: Path,
) -> bool:
    """Reject both new failed manifests and legacy low-text conversion results."""
    if manifest.get("quality_passed") is False:
        return False
    extraction_records = manifest.get("page_extractions")
    if isinstance(extraction_records, list) and extraction_records:
        if not all(isinstance(record, dict) for record in extraction_records):
            return False
        return all(
            record.get("quality_passed") is not False
            for record in extraction_records
        )

    try:
        page_texts = output_page_texts(output_dir, manifest)
        parameters = manifest.get("parameters") or {}
        if not isinstance(parameters, dict):
            return False
        selected_pages = parameters.get("pages") or sorted(page_texts)
        if not isinstance(selected_pages, list) or not selected_pages:
            return False
        with pymupdf.open(pdf_path) as document:
            for number in selected_pages:
                if not isinstance(number, int) or not 1 <= number <= document.page_count:
                    return False
                output_text = page_texts.get(number)
                if output_text is None:
                    return False
                native_text = document[number - 1].get_text("text", sort=True)
                if output_is_far_below_native(output_text, native_text):
                    return False
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def repair_output_image_links(output_dir: Path, manifest: dict[str, Any]) -> int:
    """Repair temporary image paths in an otherwise valid existing result."""
    image_dir = output_dir / "images"
    if not image_dir.is_dir():
        return 0

    markdown_files = [(manifest_markdown_path(output_dir, manifest), "images")]
    page_dir = output_dir / "pages"
    if page_dir.is_dir():
        markdown_files.extend(
            (page_path, "../images")
            for page_path in sorted(page_dir.glob("*.md"))
        )

    repaired = 0
    for markdown_path, image_prefix in markdown_files:
        original = markdown_path.read_text(encoding="utf-8")
        normalized = portable_markdown(
            original,
            image_dir,
            image_prefix=image_prefix,
        )
        if normalized != original:
            markdown_path.write_text(normalized, encoding="utf-8")
            repaired += 1
    return repaired


def find_registered_conversion(
    registry: dict[str, Any], pdf_path: Path
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for entry in reversed(registry["conversions"]):
        if not same_source(entry.get("source"), pdf_path):
            continue
        output_dir = Path(entry.get("output_dir", "")).expanduser().resolve()
        try:
            manifest = validate_replaceable_output(output_dir)
        except (OSError, ValueError):
            continue
        if manifest and same_source(manifest.get("source"), pdf_path):
            repair_output_image_links(output_dir, manifest)
            if registered_output_quality_is_valid(output_dir, manifest, pdf_path):
                return entry, manifest
    return None


def registry_entry(
    conversion_id: str,
    identity: dict[str, Any],
    target: Path,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "conversion_id": conversion_id,
        **identity,
        "output_folder": target.name,
        "manifest": str(target / "manifest.json"),
        "generated_at": generated_at,
    }


def upsert_registry_entry(
    registry: dict[str, Any],
    conversion_id: str,
    identity: dict[str, Any],
    target: Path,
    generated_at: str,
) -> None:
    registry["conversions"] = [
        entry
        for entry in registry["conversions"]
        if not same_source(entry.get("source"), Path(identity["source"]))
    ]
    registry["conversions"].append(
        registry_entry(conversion_id, identity, target, generated_at)
    )


def commit_registry_entry(
    path: Path,
    conversion_id: str,
    identity: dict[str, Any],
    target: Path,
    generated_at: str,
) -> dict[str, Any]:
    """Merge one entry into the latest registry while holding its lock."""
    with exclusive_file_lock(lock_file_for("registry", path)):
        registry = load_registry(path)
        upsert_registry_entry(
            registry, conversion_id, identity, target, generated_at
        )
        write_registry(path, registry)
    return registry_entry(conversion_id, identity, target, generated_at)


def extract_document(args: argparse.Namespace) -> dict[str, Any]:
    pdf_path = validate_pdf(args.pdf)
    output_tag = normalize_output_tag(getattr(args, "output_tag", None))
    target = resolve_output_dir(pdf_path, args.output_dir, output_tag)
    registry_path = resolve_registry_file(pdf_path, target, args.registry_file)
    lock_paths = sorted(
        {
            lock_file_for("source", pdf_path),
            lock_file_for("target", target),
        },
        key=str,
    )
    with contextlib.ExitStack() as stack:
        for lock_path in lock_paths:
            stack.enter_context(exclusive_file_lock(lock_path, timeout=300.0))
        return _extract_document_locked(
            args,
            pdf_path=pdf_path,
            output_tag=output_tag,
            target=target,
            registry_path=registry_path,
        )


def _extract_document_locked(
    args: argparse.Namespace,
    *,
    pdf_path: Path,
    output_tag: str | None,
    target: Path,
    registry_path: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    requested_options = {
        "pages": args.pages or "all",
        "images": args.images,
        "ocr": args.ocr,
        "ocr_language": args.ocr_language,
        "page_files": not args.no_page_files,
        "output_tag": output_tag,
    }
    registry = load_registry(registry_path)
    registered = (
        None
        if args.reconvert
        else find_registered_conversion(registry, pdf_path)
    )
    if registered and output_tag:
        registered_tag = registered[1].get("output_tag") or (
            registered[1].get("parameters") or {}
        ).get("output_tag")
        if registered_tag != output_tag:
            registered = None
    existing_manifest = None
    if not registered:
        existing_manifest = validate_replaceable_output(target)
        if existing_manifest and not same_source(
            existing_manifest.get("source"), pdf_path
        ):
            raise ValueError(
                "输出文件夹已属于另一个 source，拒绝覆盖: "
                f"{target}；请指定其他 --output-dir 或显式 --tag"
            )
    if not registered and not args.reconvert and existing_manifest:
        if same_source(existing_manifest.get("source"), pdf_path):
            repair_output_image_links(target, existing_manifest)
        if (
            same_source(existing_manifest.get("source"), pdf_path)
            and registered_output_quality_is_valid(
                target,
                existing_manifest,
                pdf_path,
            )
        ):
            stat = pdf_path.stat()
            registered_parameters = existing_manifest.get("parameters") or {}
            conversion_id = source_key(pdf_path)
            identity = {
                "source": str(pdf_path),
                "source_size": existing_manifest.get("source_size", stat.st_size),
                "source_mtime_ns": existing_manifest.get(
                    "source_mtime_ns", stat.st_mtime_ns
                ),
                "output_dir": str(target),
                "pymupdf_version": existing_manifest.get(
                    "pymupdf_version", pymupdf.__version__
                ),
                "pymupdf4llm_version": existing_manifest.get(
                    "pymupdf4llm_version", pymupdf4llm.__version__
                ),
                "parameters": registered_parameters,
            }
            generated_at = str(existing_manifest.get("generated_at", ""))
            committed_entry = commit_registry_entry(
                registry_path, conversion_id, identity, target, generated_at
            )
            registered = (
                committed_entry,
                existing_manifest,
            )
    if registered:
        registered_entry, registered_manifest = registered
        registered_output = Path(registered_entry["output_dir"]).expanduser().resolve()
        registered_markdown = manifest_markdown_path(
            registered_output, registered_manifest
        )
        registered_parameters = registered_manifest.get("parameters") or {}
        return {
            "status": "already_converted",
            "already_converted": True,
            "message": f"该 source 已转换过；未重新转换。结果位于: {registered_output}",
            "output_dir": str(registered_output),
            "requested_output_dir": str(target),
            "markdown": str(registered_markdown),
            "manifest": str(registered_output / "manifest.json"),
            "registry": str(registry_path),
            "conversion_id": source_key(pdf_path),
            "parameters_ignored": True,
            "registered_parameters": registered_parameters,
            "requested_parameters": requested_options,
            "output_tag": registered_manifest.get("output_tag"),
        }

    inspection = inspect_document(pdf_path)
    pages = parse_pages(args.pages, inspection["page_count"])
    if args.images == "selected" and not args.pages:
        raise ValueError("--images selected 必须与 --pages 一起使用")

    options = {
        "pages": [page + 1 for page in pages],
        "images": args.images,
        "ocr": args.ocr,
        "ocr_language": args.ocr_language,
        "page_files": not args.no_page_files,
        "output_tag": output_tag,
    }
    conversion_id, identity = make_conversion_id(pdf_path, target, options)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path = Path(tempfile.mkdtemp(prefix=f".{safe_stem(pdf_path)}-", dir=target.parent))
    image_dir = temp_path / "images"
    page_dir = temp_path / "pages"
    write_images = args.images != "none"
    if write_images:
        image_dir.mkdir()

    try:
        chunks = convert_pages(
            pdf_path,
            pages,
            image_dir=image_dir,
            write_images=write_images,
            use_ocr=False,
            force_ocr=False,
            ocr_language=args.ocr_language,
            verbose=args.verbose,
        )
        chunks, page_extractions = extract_page_content(
            pdf_path,
            pages,
            chunks,
            inspection,
            ocr_mode=args.ocr,
            ocr_language=args.ocr_language,
        )

        chunks.sort(key=page_number)
        document_parts = []
        if not args.no_page_files:
            page_dir.mkdir()
        for chunk in chunks:
            number = page_number(chunk)
            raw_text = chunk.get("text", "")
            document_text = portable_markdown(
                raw_text,
                image_dir,
                image_prefix="images",
            )
            page_text = portable_markdown(
                raw_text,
                image_dir,
                image_prefix="../images",
            )
            document_parts.append(f"<!-- page: {number} -->\n\n{document_text}")
            if not args.no_page_files:
                (page_dir / f"{number:04d}.md").write_text(
                    page_text,
                    encoding="utf-8",
                )

        markdown_name = markdown_filename(pdf_path)
        document_path = temp_path / markdown_name
        document_path.write_text("\n".join(document_parts), encoding="utf-8")
        image_count = sum(1 for item in image_dir.iterdir() if item.is_file()) if image_dir.exists() else 0
        if image_dir.exists() and image_count == 0:
            image_dir.rmdir()

        generated_files = sorted(
            item.relative_to(temp_path).as_posix()
            for item in temp_path.rglob("*")
            if item.is_file()
        )
        generated_dirs = sorted(
            item.relative_to(temp_path).as_posix()
            for item in temp_path.rglob("*")
            if item.is_dir()
        )
        manifest = {
            "generator": "pdf-reader",
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "conversion_id": conversion_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **identity,
            "markdown_file": markdown_name,
            "pages_processed": len(chunks),
            "likely_scanned_pages": inspection["likely_scanned_pages"],
            "hidden_ocr_pages": inspection["hidden_ocr_pages"],
            "quality_passed": True,
            "page_extractions": page_extractions,
            "output_tag": output_tag,
            "image_count": image_count,
            "metadata": inspection["metadata"],
            "toc": inspection["toc"],
            "generated_files": [*generated_files, "manifest.json"],
            "generated_dirs": generated_dirs,
        }
        (temp_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        validate_replaceable_output(target)
    except Exception:
        shutil.rmtree(temp_path, ignore_errors=True)
        raise

    backup_path: Path | None = None
    if target.exists():
        backup_path = target.with_name(
            f".{target.name}.backup-{os.getpid()}-{time.time_ns()}"
        )
        try:
            target.rename(backup_path)
        except Exception:
            shutil.rmtree(temp_path, ignore_errors=True)
            raise
    try:
        temp_path.rename(target)
    except Exception:
        if backup_path and backup_path.exists() and not target.exists():
            try:
                backup_path.rename(target)
            except Exception as rollback_error:
                raise RuntimeError(
                    "激活新输出失败，且旧输出回滚失败；"
                    f"旧输出备份保留在: {backup_path}"
                ) from rollback_error
        shutil.rmtree(temp_path, ignore_errors=True)
        raise

    try:
        commit_registry_entry(
            registry_path,
            conversion_id,
            identity,
            target,
            manifest["generated_at"],
        )
    except Exception:
        if backup_path and backup_path.exists():
            failed_output = target.with_name(
                f".{target.name}.failed-{os.getpid()}-{time.time_ns()}"
            )
            try:
                target.rename(failed_output)
                backup_path.rename(target)
                shutil.rmtree(failed_output, ignore_errors=True)
            except Exception as rollback_error:
                raise RuntimeError(
                    "登记转换结果失败，且旧输出回滚失败；"
                    f"旧输出备份保留在: {backup_path}"
                ) from rollback_error
        raise
    if backup_path and backup_path.exists():
        shutil.rmtree(backup_path)

    return {
        "status": "ok",
        "already_converted": False,
        "output_dir": str(target),
        "markdown": str(target / markdown_filename(pdf_path)),
        "manifest": str(target / "manifest.json"),
        "registry": str(registry_path),
        "conversion_id": conversion_id,
        "page_count": len(chunks),
        "image_count": image_count,
        "output_tag": output_tag,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="高效检查和提取 PDF 内容")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="快速检查页数、目录和扫描页")
    inspect_parser.add_argument("pdf", help="PDF 文件路径")
    inspect_parser.add_argument(
        "--include-pages",
        action="store_true",
        help="在 JSON 中包含逐页文字和图片统计",
    )

    extract_parser = subparsers.add_parser(
        "extract",
        aliases=["transfer"],
        help="转换 PDF 为 Markdown，并写入结果文件夹",
    )
    extract_parser.add_argument("pdf", help="PDF 文件路径")
    extract_parser.add_argument(
        "--output-dir",
        help="最终结果文件夹；默认创建 <PDF文件名>",
    )
    extract_parser.add_argument(
        "--tag",
        "--suffix",
        "--note",
        dest="output_tag",
        help="仅在用户显式要求时追加到输出文件夹末尾的英文关键词",
    )
    extract_parser.add_argument(
        "--registry-file",
        help=f"转换登记 JSON；默认在源 PDF 所在目录创建 {REGISTRY_FILENAME}",
    )
    extract_parser.add_argument(
        "--reconvert",
        "--force",
        action="store_true",
        help="忽略 source 重复记录，必须重新转换并更新登记",
    )
    extract_parser.add_argument("--pages", help="1-based 页码，例如 1-10,18,25-30")
    extract_parser.add_argument(
        "--images",
        choices=("none", "selected", "all"),
        default="none",
        help="默认不提取图片；selected 仅用于显式指定的页码",
    )
    extract_parser.add_argument(
        "--ocr",
        choices=("auto", "off", "force"),
        default="auto",
        help="auto 按页选择原生文本或位图 OCR；off 禁用 OCR；force 强制位图 OCR",
    )
    extract_parser.add_argument("--ocr-language", default="eng", help="OCR 语言")
    extract_parser.add_argument("--no-page-files", action="store_true", help="不生成逐页 Markdown")
    extract_parser.add_argument("--verbose", action="store_true", help="将解析器日志写入 stderr")
    return parser


def configure_standard_streams() -> None:
    """Prefer UTF-8 for Windows consoles and redirected standard streams."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def emit_json(value: Any, stream: Any, *, indent: int | None = None) -> None:
    """Write exactly one complete JSON value, escaping when the stream needs it."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    rendered = json.dumps(value, ensure_ascii=False, indent=indent)
    try:
        rendered.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        rendered = json.dumps(value, ensure_ascii=True, indent=indent)
    stream.write(rendered + "\n")


def main() -> int:
    configure_standard_streams()
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect_document(validate_pdf(args.pdf))
            if not args.include_pages:
                result.pop("pages", None)
        else:
            result = extract_document(args)
        emit_json(result, sys.stdout, indent=2)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        emit_json({"status": "error", "error": str(exc)}, sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
