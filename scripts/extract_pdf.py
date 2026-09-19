#!/usr/bin/env python3
"""Inspect and selectively extract PDFs for efficient LLM consumption."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pymupdf
import pymupdf4llm


SCANNED_TEXT_THRESHOLD = 40
MANIFEST_SCHEMA_VERSION = 6
REGISTRY_SCHEMA_VERSION = 1
REGISTRY_FILENAME = "pdf-reader-conversions.json"


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


def inspect_document(pdf_path: Path) -> dict[str, Any]:
    with pymupdf.open(pdf_path) as document:
        if document.needs_pass:
            raise ValueError("PDF 已加密，需要先提供无密码副本")

        page_stats = []
        likely_scanned_pages = []
        total_chars = 0
        total_images = 0
        for index, page in enumerate(document):
            text_chars = len(page.get_text("text").strip())
            image_count = len(page.get_images(full=True))
            total_chars += text_chars
            total_images += image_count
            likely_scanned = text_chars < SCANNED_TEXT_THRESHOLD and image_count > 0
            if likely_scanned:
                likely_scanned_pages.append(index + 1)
            page_stats.append(
                {
                    "page": index + 1,
                    "text_chars": text_chars,
                    "image_count": image_count,
                    "likely_scanned": likely_scanned,
                }
            )

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
            "metadata": metadata,
            "toc": toc,
            "pages": page_stats,
        }


def safe_stem(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]+", "-", path.stem).strip("-.")
    return (stem or "document")[:80]


def source_key(pdf_path: Path) -> str:
    encoded = str(pdf_path.expanduser().resolve()).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def default_output_name(pdf_path: Path) -> str:
    return f"{safe_stem(pdf_path)}-{source_key(pdf_path)[:8]}-pdf-reader-output"


def markdown_filename(pdf_path: Path) -> str:
    return f"{safe_stem(pdf_path)}.md"


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
        "pymupdf4llm_version": pymupdf4llm.__version__,
        "parameters": parameters,
    }
    return source_key(pdf_path), identity


def page_number(chunk: dict[str, Any]) -> int:
    metadata = chunk.get("metadata") or {}
    return int(metadata.get("page_number", 0))


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
    with contextlib.redirect_stdout(library_output):
        chunks = pymupdf4llm.to_markdown(
            pdf_path,
            pages=page_list,
            page_chunks=True,
            page_separators=False,
            write_images=write_images,
            image_path=str(image_dir),
            use_ocr=use_ocr,
            force_ocr=force_ocr,
            ocr_language=ocr_language,
            show_progress=False,
        )
    if verbose and library_output.getvalue():
        print(library_output.getvalue(), file=sys.stderr, end="")
    return chunks


def portable_markdown(text: str, image_dir: Path) -> str:
    """Replace temporary absolute image paths with portable relative links."""
    replacements = {
        str(image_dir): "images",
        image_dir.as_posix(): "images",
        str(image_dir).replace("\\", "/"): "images",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.strip() + "\n"


def resolve_output_dir(pdf_path: Path, value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return (Path.cwd() / default_output_name(pdf_path)).resolve()


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
    if manifest.get("generator") != "pdf-reader":
        raise ValueError(f"输出文件夹不是 pdf-reader 生成的，拒绝覆盖: {target}")
    expected_files = set(manifest.get("generated_files") or [])
    expected_dirs = set(manifest.get("generated_dirs") or [])
    actual_files = {
        item.relative_to(target).as_posix()
        for item in target.rglob("*")
        if item.is_file()
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
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"不支持的转换登记 JSON 版本: {path}")
    if not isinstance(registry.get("conversions"), list):
        raise ValueError(f"转换登记 JSON 缺少 conversions 数组: {path}")
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


def same_source(value: Any, pdf_path: Path) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return Path(value).expanduser().resolve() == pdf_path


def manifest_markdown_path(output_dir: Path, manifest: dict[str, Any]) -> Path:
    markdown_file = manifest.get("markdown_file")
    if isinstance(markdown_file, str) and markdown_file:
        return output_dir / markdown_file
    legacy = output_dir / "document.md"
    if legacy.is_file():
        return legacy
    generated = manifest.get("generated_files") or []
    for relative in generated:
        path = Path(relative)
        if len(path.parts) == 1 and path.suffix.lower() == ".md":
            return output_dir / path
    raise ValueError(f"manifest.json 未记录合并 Markdown: {output_dir}")


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


def extract_document(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    pdf_path = validate_pdf(args.pdf)
    requested_options = {
        "pages": args.pages or "all",
        "images": args.images,
        "ocr": args.ocr,
        "ocr_language": args.ocr_language,
        "page_files": not args.no_page_files,
    }
    target = resolve_output_dir(pdf_path, args.output_dir)
    registry_path = resolve_registry_file(pdf_path, target, args.registry_file)
    registry = load_registry(registry_path)
    registered = (
        None
        if args.reconvert
        else find_registered_conversion(registry, pdf_path)
    )
    existing_manifest = None
    if not registered:
        existing_manifest = validate_replaceable_output(target)
    if not registered and not args.reconvert and existing_manifest:
        if same_source(existing_manifest.get("source"), pdf_path):
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
                "pymupdf4llm_version": existing_manifest.get(
                    "pymupdf4llm_version", pymupdf4llm.__version__
                ),
                "parameters": registered_parameters,
            }
            generated_at = str(existing_manifest.get("generated_at", ""))
            upsert_registry_entry(
                registry, conversion_id, identity, target, generated_at
            )
            write_registry(registry_path, registry)
            registered = (
                registry_entry(conversion_id, identity, target, generated_at),
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
    }
    conversion_id, identity = make_conversion_id(pdf_path, target, options)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path = Path(tempfile.mkdtemp(prefix=f".{safe_stem(pdf_path)}-", dir=target.parent))
    image_dir = temp_path / "images"
    page_dir = temp_path / "pages"
    write_images = args.images != "none"
    if write_images:
        image_dir.mkdir()

    scanned = {page - 1 for page in inspection["likely_scanned_pages"]}
    try:
        if args.ocr == "off":
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
        elif args.ocr == "force":
            chunks = convert_pages(
                pdf_path,
                pages,
                image_dir=image_dir,
                write_images=write_images,
                use_ocr=True,
                force_ocr=True,
                ocr_language=args.ocr_language,
                verbose=args.verbose,
            )
        else:
            native_pages = [page for page in pages if page not in scanned]
            scanned_pages = [page for page in pages if page in scanned]
            chunks = convert_pages(
                pdf_path,
                native_pages,
                image_dir=image_dir,
                write_images=write_images,
                use_ocr=False,
                force_ocr=False,
                ocr_language=args.ocr_language,
                verbose=args.verbose,
            )
            chunks.extend(
                convert_pages(
                    pdf_path,
                    scanned_pages,
                    image_dir=image_dir,
                    write_images=write_images,
                    use_ocr=True,
                    force_ocr=True,
                    ocr_language=args.ocr_language,
                    verbose=args.verbose,
                )
            )

        chunks.sort(key=page_number)
        document_parts = []
        if not args.no_page_files:
            page_dir.mkdir()
        for chunk in chunks:
            number = page_number(chunk)
            text = portable_markdown(chunk.get("text", ""), image_dir)
            document_parts.append(f"<!-- page: {number} -->\n\n{text}")
            if not args.no_page_files:
                (page_dir / f"{number:04d}.md").write_text(text, encoding="utf-8")

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
        if target.exists():
            shutil.rmtree(target)
        temp_path.rename(target)
    except Exception:
        shutil.rmtree(temp_path, ignore_errors=True)
        raise

    upsert_registry_entry(
        registry,
        conversion_id,
        identity,
        target,
        manifest["generated_at"],
    )
    write_registry(registry_path, registry)

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
        help="最终结果文件夹；默认创建 <PDF文件名>-<source短标识>-pdf-reader-output",
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
        help="auto 仅对疑似扫描页 OCR；off 最快；force 强制 OCR",
    )
    extract_parser.add_argument("--ocr-language", default="eng", help="OCR 语言")
    extract_parser.add_argument("--no-page-files", action="store_true", help="不生成逐页 Markdown")
    extract_parser.add_argument("--verbose", action="store_true", help="将解析器日志写入 stderr")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect_document(validate_pdf(args.pdf))
            if not args.include_pages:
                result.pop("pages", None)
        else:
            result = extract_document(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
