from __future__ import annotations

import argparse
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "extract_pdf.py"
DEMO_PDF = SKILL_DIR / "transform_demo" / "test_pdf_read_script.pdf"

spec = importlib.util.spec_from_file_location("extract_pdf", SCRIPT)
extract_pdf = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(extract_pdf)


class ExtractPdfTests(unittest.TestCase):
    @staticmethod
    def make_hidden_ocr_pdf(path: Path) -> str:
        hidden_text = "Hidden OCR body text for quality fallback. " * 8
        document = extract_pdf.pymupdf.open()
        page = document.new_page(width=300, height=400)
        pixmap = extract_pdf.pymupdf.Pixmap(
            extract_pdf.pymupdf.csGRAY,
            extract_pdf.pymupdf.IRect(0, 0, 30, 40),
            False,
        )
        pixmap.clear_with(240)
        page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        page.insert_text(
            (20, 40),
            hidden_text,
            fontsize=9,
            render_mode=3,
            fill_opacity=0,
        )
        page.insert_text((5, 390), "note", fontsize=6)
        document.save(path)
        document.close()
        return hidden_text

    def test_parse_pages(self) -> None:
        self.assertEqual(extract_pdf.parse_pages("1-2,2,4", 5), [0, 1, 3])
        with self.assertRaises(ValueError):
            extract_pdf.parse_pages("0", 5)
        with self.assertRaises(ValueError):
            extract_pdf.parse_pages("4-2", 5)

    def test_image_extraction_uses_short_names_and_preserves_region_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            source = root / ("long_source_" * 15 + ".pdf")
            source.write_bytes(DEMO_PDF.read_bytes())
            image_dir = root / "images"
            image_dir.mkdir()

            def fake_markdown(document, **kwargs):
                self.assertIsInstance(document, extract_pdf.pymupdf.Document)
                self.assertEqual(document.name, "pdf-reader.pdf")
                self.assertEqual(kwargs["pages"], [1])
                self.assertEqual(kwargs["image_format"], "png")
                text = ""
                for region in (3, 8):
                    filename = f"{document.name}-0002-{region:02d}.png"
                    (image_dir / filename).write_bytes(str(region).encode())
                    text += f"![]({image_dir.as_posix()}/{filename})\n"
                return [{"metadata": {"page_number": 2, "file_path": document.name}, "text": text}]

            with mock.patch.object(extract_pdf.pymupdf4llm, "to_markdown", side_effect=fake_markdown), mock.patch.object(
                extract_pdf.pymupdf4llm, "_use_layout", True
            ):
                chunks = extract_pdf.convert_pages(
                    source, [1], image_dir=image_dir, write_images=True,
                    use_ocr=False, force_ocr=False, ocr_language="eng", verbose=False,
                )
            self.assertEqual({p.name for p in image_dir.iterdir()}, {"0002-03.png", "0002-08.png"})
            self.assertEqual((image_dir / "0002-03.png").read_bytes(), b"3")
            self.assertEqual(chunks[0]["metadata"]["file_path"], str(source))
            self.assertIn("![](images/0002-03.png)", chunks[0]["text"])
            self.assertNotIn("pdf-reader.pdf", chunks[0]["text"])
            page_text = extract_pdf.portable_markdown(chunks[0]["text"], image_dir, image_prefix="../images")
            self.assertIn("![](../images/0002-08.png)", page_text)

    def test_short_image_names_refuse_collisions_before_renaming(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            image_dir = Path(parent)
            original = image_dir / "pdf-reader.pdf-0002-03.png"
            original.write_bytes(b"original")
            target = image_dir / "0002-03.png"
            target.write_bytes(b"keep")
            with self.assertRaises(ValueError):
                extract_pdf.shorten_generated_image_names(image_dir)
            self.assertEqual(original.read_bytes(), b"original")
            self.assertEqual(target.read_bytes(), b"keep")

    def test_image_links_are_rewritten_out_of_temporary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            temp_path = Path(parent) / ".report-random"
            image_dir = temp_path / "images"
            image_dir.mkdir(parents=True)
            image_name = "report_file.pdf-0003-04.png"
            (image_dir / image_name).write_bytes(b"image")
            raw = (
                "before\n"
                f"![](repo/{temp_path.name}/images/{image_name})\n"
                "after\n"
            )

            document = extract_pdf.portable_markdown(
                raw,
                image_dir,
                image_prefix="images",
            )
            page = extract_pdf.portable_markdown(
                raw,
                image_dir,
                image_prefix="../images",
            )

            self.assertIn(f"![](images/{image_name})", document)
            self.assertIn(f"![](../images/{image_name})", page)
            self.assertNotIn(temp_path.name, document)
            self.assertNotIn(temp_path.name, page)

    def test_image_link_rewrite_handles_markdown_escaped_filename(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            image_dir = Path(parent) / "images"
            image_dir.mkdir()
            image_name = "name_with_underscores.png"
            (image_dir / image_name).write_bytes(b"image")
            raw = r"![](.temporary/images/name\_with\_underscores.png)"
            result = extract_pdf.portable_markdown(raw, image_dir)
            self.assertEqual(result, f"![](images/{image_name})\n")

    def test_image_link_rewrite_handles_complex_names_and_multiple_links(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            image_dir = Path(parent) / "images"
            image_dir.mkdir()
            first_name = "figure (draft)_一.png"
            second_name = "plain-image.png"
            (image_dir / first_name).write_bytes(b"first")
            (image_dir / second_name).write_bytes(b"second")
            raw = (
                f"![](<repo/.temporary/images/{first_name}>) "
                f"![](repo/.temporary/images/{second_name})"
            )

            result = extract_pdf.portable_markdown(raw, image_dir)

            self.assertEqual(
                result,
                (
                    f"![](<images/{first_name}>) "
                    f"![](images/{second_name})\n"
                ),
            )

    def test_image_link_rewrite_does_not_cross_an_unrelated_link(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            image_dir = Path(parent) / "images"
            image_dir.mkdir()
            image_name = "generated.png"
            (image_dir / image_name).write_bytes(b"image")
            raw = (
                "![](https://example.com/external.png) "
                f"![](repo/.temporary/images/{image_name})"
            )

            result = extract_pdf.portable_markdown(raw, image_dir)

            self.assertEqual(
                result,
                (
                    "![](https://example.com/external.png) "
                    f"![](images/{image_name})\n"
                ),
            )

    def test_image_link_rewrite_handles_url_encoded_filename(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            image_dir = Path(parent) / "images"
            image_dir.mkdir()
            image_name = "figure one.png"
            (image_dir / image_name).write_bytes(b"image")
            raw = "![](repo/.temporary/images/figure%20one.png)"

            result = extract_pdf.portable_markdown(raw, image_dir)

            self.assertEqual(result, f"![](<images/{image_name}>)\n")

    def test_existing_output_image_links_are_repaired_without_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "result"
            image_dir = output_dir / "images"
            page_dir = output_dir / "pages"
            image_dir.mkdir(parents=True)
            page_dir.mkdir()
            image_name = "report.pdf-0003-04.png"
            (image_dir / image_name).write_bytes(b"image")
            broken = f"![](repo/.report-random/images/{image_name})\n"
            combined = output_dir / "report.md"
            page = page_dir / "0003.md"
            combined.write_text(broken, encoding="utf-8")
            page.write_text(broken, encoding="utf-8")

            repaired = extract_pdf.repair_output_image_links(
                output_dir,
                {"markdown_file": "report.md"},
            )

            self.assertEqual(repaired, 2)
            self.assertEqual(
                combined.read_text(encoding="utf-8"),
                f"![](images/{image_name})\n",
            )
            self.assertEqual(
                page.read_text(encoding="utf-8"),
                f"![](../images/{image_name})\n",
            )

    def test_inspect_demo(self) -> None:
        result = extract_pdf.inspect_document(DEMO_PDF.resolve())
        self.assertEqual(result["page_count"], 3)
        self.assertGreater(result["text_chars"], 0)

    def test_inspect_detects_transparent_ocr_page(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            pdf_path = Path(parent) / "hidden-ocr.pdf"
            self.make_hidden_ocr_pdf(pdf_path)

            result = extract_pdf.inspect_document(pdf_path.resolve())
            page = result["pages"][0]

            self.assertEqual(result["hidden_ocr_pages"], [1])
            self.assertEqual(result["likely_scanned_pages"], [1])
            self.assertTrue(page["hidden_ocr_page"])
            self.assertGreater(page["transparent_text_chars"], 40)
            self.assertGreater(page["bboxlog"]["ignore_text"], 0)
            self.assertGreater(page["bboxlog"]["fill_image"], 0)
            self.assertGreater(page["largest_image_area_ratio"], 0.9)

    def test_low_layout_output_falls_back_to_native_text(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            pdf_path = Path(parent) / "hidden-ocr.pdf"
            self.make_hidden_ocr_pdf(pdf_path)
            inspection = extract_pdf.inspect_document(pdf_path.resolve())
            chunks = [{"metadata": {"page_number": 1}, "text": "note"}]

            with mock.patch.object(extract_pdf, "raster_ocr_page") as raster_ocr:
                verified, records = extract_pdf.extract_page_content(
                    pdf_path.resolve(),
                    [0],
                    chunks,
                    inspection,
                    ocr_mode="auto",
                    ocr_language="eng",
                )

            raster_ocr.assert_not_called()
            self.assertIn("Hidden OCR body text", verified[0]["text"])
            self.assertEqual(records[0]["backend"], "pymupdf_native_text")
            self.assertEqual(
                records[0]["fallback_reason"],
                "hidden_ocr_page_prefers_native_text",
            )
            self.assertTrue(records[0]["hidden_ocr_page"])
            self.assertTrue(records[0]["quality_passed"])

    def test_quality_gate_falls_back_on_a_normal_text_page(self) -> None:
        inspection = extract_pdf.inspect_document(DEMO_PDF.resolve())
        chunks = [{"metadata": {"page_number": 1}, "text": ""}]

        verified, records = extract_pdf.extract_page_content(
            DEMO_PDF.resolve(),
            [0],
            chunks,
            inspection,
            ocr_mode="off",
            ocr_language="eng",
        )

        self.assertGreater(extract_pdf.markdown_body_char_count(verified[0]["text"]), 40)
        self.assertEqual(records[0]["backend"], "pymupdf_native_text")
        self.assertEqual(
            records[0]["fallback_reason"],
            "pymupdf4llm_output_below_native_text_ratio",
        )
        self.assertTrue(records[0]["quality_passed"])

    def test_force_ocr_uses_independent_raster_backend(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            pdf_path = Path(parent) / "hidden-ocr.pdf"
            self.make_hidden_ocr_pdf(pdf_path)
            inspection = extract_pdf.inspect_document(pdf_path.resolve())
            chunks = [{"metadata": {"page_number": 1}, "text": "baseline"}]
            ocr_text = "Raster OCR output with enough body text to pass quality. " * 3

            with mock.patch.object(
                extract_pdf,
                "raster_ocr_page",
                return_value=ocr_text,
            ) as raster_ocr:
                verified, records = extract_pdf.extract_page_content(
                    pdf_path.resolve(),
                    [0],
                    chunks,
                    inspection,
                    ocr_mode="force",
                    ocr_language="eng",
                )

            raster_ocr.assert_called_once()
            self.assertIn("Raster OCR output", verified[0]["text"])
            self.assertEqual(records[0]["backend"], "tesseract_raster_ocr")
            self.assertEqual(records[0]["fallback_reason"], "ocr_force")

    def test_legacy_empty_result_is_not_reusable_when_native_text_exists(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            pdf_path = root / "hidden-ocr.pdf"
            self.make_hidden_ocr_pdf(pdf_path)
            output_dir = root / "result"
            page_dir = output_dir / "pages"
            page_dir.mkdir(parents=True)
            (page_dir / "0001.md").write_text("\n", encoding="utf-8")
            manifest = {
                "parameters": {"pages": [1]},
                "markdown_file": "hidden-ocr.md",
            }

            self.assertFalse(
                extract_pdf.registered_output_quality_is_valid(
                    output_dir,
                    manifest,
                    pdf_path.resolve(),
                )
            )

    def test_registered_legacy_empty_result_is_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            pdf_path = root / "hidden-ocr.pdf"
            self.make_hidden_ocr_pdf(pdf_path)
            pdf_path = pdf_path.resolve()
            output_dir = root / "result"
            page_dir = output_dir / "pages"
            page_dir.mkdir(parents=True)
            markdown_name = "hidden-ocr.md"
            (output_dir / markdown_name).write_text(
                "<!-- page: 1 -->\n\n",
                encoding="utf-8",
            )
            (page_dir / "0001.md").write_text("\n", encoding="utf-8")
            manifest = {
                "generator": "pdf-reader",
                "schema_version": 6,
                "source": str(pdf_path),
                "markdown_file": markdown_name,
                "parameters": {
                    "pages": [1],
                    "images": "none",
                    "ocr": "auto",
                    "ocr_language": "eng",
                    "page_files": True,
                },
                "generated_files": [
                    markdown_name,
                    "manifest.json",
                    "pages/0001.md",
                ],
                "generated_dirs": ["pages"],
            }
            (output_dir / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            registry_path = root / "registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "conversions": [
                            {
                                "source": str(pdf_path),
                                "output_dir": str(output_dir.resolve()),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                pdf=str(pdf_path),
                output_dir=str(output_dir),
                registry_file=str(registry_path),
                reconvert=False,
                pages="1",
                images="none",
                ocr="auto",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )

            result = extract_pdf.extract_document(args)

            self.assertFalse(result["already_converted"])
            markdown = Path(result["markdown"]).read_text(encoding="utf-8")
            self.assertIn("Hidden OCR body text", markdown)
            regenerated_manifest = json.loads(
                Path(result["manifest"]).read_text(encoding="utf-8")
            )
            self.assertTrue(regenerated_manifest["quality_passed"])
            self.assertEqual(
                regenerated_manifest["page_extractions"][0]["backend"],
                "pymupdf_native_text",
            )

    def test_default_output_names_use_source_stem_and_markdown_name_is_stable(self) -> None:
        first = Path("/tmp/source-a/report.pdf").resolve()
        second = Path("/tmp/source-b/report.pdf").resolve()
        self.assertEqual(extract_pdf.markdown_filename(first), "document.md")
        self.assertEqual(extract_pdf.markdown_filename(second), "document.md")
        first_name = extract_pdf.default_output_name(first)
        second_name = extract_pdf.default_output_name(second)
        self.assertEqual(first_name, "report")
        self.assertEqual(second_name, "report")
        self.assertNotIn("pdf-reader-output", first_name)
        self.assertNotIn("images", first_name)
        self.assertNotIn("ocr", first_name)
        target = Path("/tmp/output/result").resolve()
        self.assertEqual(
            extract_pdf.resolve_registry_file(first, target, None),
            first.parent / extract_pdf.REGISTRY_FILENAME,
        )

    def test_windows_reserved_source_names_are_made_portable(self) -> None:
        expected = {
            "AUX-.pdf": "_AUX",
            "[CON].pdf": "_CON",
            "COM1-.pdf": "_COM1",
            "normal.pdf": "normal",
        }
        for source, stem in expected.items():
            with self.subTest(source=source):
                path = Path(source)
                self.assertEqual(extract_pdf.safe_stem(path), stem)
                self.assertEqual(extract_pdf.markdown_filename(path), "document.md")

    def test_invalid_registry_and_manifest_shapes_raise_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            registry_path = root / "registry.json"
            for value in ([], {"schema_version": 1, "conversions": [None]}):
                registry_path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(registry=value), self.assertRaises(ValueError):
                    extract_pdf.load_registry(registry_path)

            output = root / "output"
            output.mkdir()
            (output / "manifest.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_pdf.validate_replaceable_output(output)

    def test_json_output_falls_back_to_ascii_for_legacy_windows_encoding(self) -> None:
        class LegacyStream(io.StringIO):
            @property
            def encoding(self) -> str:
                return "cp1252"

        stream = LegacyStream()
        value = {"status": "错误", "path": "中文目录"}
        extract_pdf.emit_json(value, stream)
        self.assertEqual(json.loads(stream.getvalue()), value)
        self.assertTrue(stream.getvalue().isascii())

    def test_explicit_tessdata_must_contain_every_requested_language(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            tessdata = Path(parent)
            (tessdata / "eng.traineddata").write_bytes(b"test")
            with mock.patch.dict(
                extract_pdf.os.environ,
                {"TESSDATA_PREFIX": str(tessdata)},
                clear=False,
            ):
                self.assertEqual(
                    extract_pdf.resolve_ocr_tessdata("eng"),
                    tessdata.resolve(),
                )
                with self.assertRaises(RuntimeError):
                    extract_pdf.resolve_ocr_tessdata("chi_sim+eng")

    def test_registry_commit_reloads_and_merges_latest_entries(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            registry_path = root / "registry.json"
            first_source = root / "first.pdf"
            second_source = root / "second.pdf"
            first_identity = {"source": str(first_source), "output_dir": str(root / "one")}
            second_identity = {"source": str(second_source), "output_dir": str(root / "two")}
            extract_pdf.commit_registry_entry(
                registry_path, "one", first_identity, root / "one", "first"
            )
            extract_pdf.commit_registry_entry(
                registry_path, "two", second_identity, root / "two", "second"
            )
            registry = extract_pdf.load_registry(registry_path)
            self.assertEqual(
                {Path(item["source"]).name for item in registry["conversions"]},
                {"first.pdf", "second.pdf"},
            )

    def test_explicit_output_tag_is_normalized_and_appended(self) -> None:
        source = Path("/tmp/source/report.pdf").resolve()
        self.assertEqual(
            extract_pdf.normalize_output_tag(" Needs Review "),
            "needs-review",
        )
        self.assertTrue(
            extract_pdf.default_output_name(source, "Needs Review").endswith(
                "-needs-review"
            )
        )
        tagged = extract_pdf.resolve_output_dir(
            source,
            "/tmp/output/result",
            "Needs Review",
        )
        self.assertEqual(
            tagged,
            Path("/tmp/output/result-needs-review").resolve(),
        )
        self.assertEqual(
            extract_pdf.resolve_output_dir(
                source,
                "/tmp/output/result-needs-review",
                "needs-review",
            ),
            tagged,
        )
        with self.assertRaises(ValueError):
            extract_pdf.normalize_output_tag("组会")

    def test_tag_cli_aliases_share_one_destination(self) -> None:
        parser = extract_pdf.build_parser()
        for option in ("--tag", "--suffix", "--note"):
            with self.subTest(option=option):
                args = parser.parse_args(
                    ["transfer", "input.pdf", option, "Needs Review"]
                )
                self.assertEqual(args.output_tag, "Needs Review")

    def test_conversion_id_depends_only_on_source(self) -> None:
        target = Path("/tmp/pdf-reader-result").resolve()
        options = {
            "pages": [1],
            "images": "none",
            "ocr": "off",
            "ocr_language": "eng",
            "page_files": True,
            "output_tag": None,
        }
        base_id, _ = extract_pdf.make_conversion_id(
            DEMO_PDF.resolve(), target, options
        )
        variants = {
            "pages": [2],
            "images": "all",
            "ocr": "auto",
            "ocr_language": "chi_sim+eng",
            "page_files": False,
            "output_tag": "review",
        }
        for key, value in variants.items():
            with self.subTest(parameter=key):
                changed = {**options, key: value}
                changed_id, _ = extract_pdf.make_conversion_id(
                    DEMO_PDF.resolve(), target, changed
                )
                self.assertEqual(base_id, changed_id)

        other_output_id, _ = extract_pdf.make_conversion_id(
            DEMO_PDF.resolve(), Path("/tmp/pdf-reader-other").resolve(), options
        )
        self.assertEqual(base_id, other_output_id)

    def test_extract_registers_and_reuses_matching_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "result"
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(Path(parent) / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            first = extract_pdf.extract_document(args)
            second = extract_pdf.extract_document(args)
            self.assertEqual(first["output_dir"], str(output_dir.resolve()))
            self.assertEqual(second["output_dir"], str(output_dir.resolve()))
            self.assertFalse(first["already_converted"])
            self.assertTrue(second["already_converted"])
            self.assertEqual(second["status"], "already_converted")
            self.assertEqual(Path(first["markdown"]).name, "document.md")
            self.assertEqual(Path(second["markdown"]).name, "document.md")
            markdown = Path(second["markdown"]).read_text(encoding="utf-8")
            self.assertIn("<!-- page: 1 -->", markdown)
            manifest = json.loads(Path(second["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["generator"], "pdf-reader")
            self.assertEqual(
                manifest["schema_version"],
                extract_pdf.MANIFEST_SCHEMA_VERSION,
            )
            self.assertEqual(manifest["pages_processed"], 1)
            self.assertEqual(manifest["markdown_file"], "document.md")
            self.assertIsNone(manifest["output_tag"])
            self.assertTrue(manifest["quality_passed"])
            self.assertEqual(len(manifest["page_extractions"]), 1)
            self.assertIn("backend", manifest["page_extractions"][0])
            self.assertIn("native_text_chars", manifest["page_extractions"][0])
            self.assertIn("output_text_chars", manifest["page_extractions"][0])
            self.assertIn("manifest.json", manifest["generated_files"])
            registry = json.loads(Path(second["registry"]).read_text(encoding="utf-8"))
            entry = registry["conversions"][0]
            self.assertEqual(entry["source"], str(DEMO_PDF.resolve()))
            self.assertEqual(entry["output_folder"], "result")
            self.assertEqual(entry["parameters"]["pages"], [1])
            self.assertEqual(manifest["conversion_id"], extract_pdf.source_key(DEMO_PDF))
            args.reconvert = True
            third = extract_pdf.extract_document(args)
            self.assertFalse(third["already_converted"])
            self.assertEqual(third["conversion_id"], first["conversion_id"])

    def test_refuses_to_replace_output_owned_by_another_source(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            first_source = root / "source-a" / "report.pdf"
            second_source = root / "source-b" / "report.pdf"
            first_source.parent.mkdir()
            second_source.parent.mkdir()
            first_source.write_bytes(DEMO_PDF.read_bytes())
            second_source.write_bytes(DEMO_PDF.read_bytes())
            output_dir = root / "report"

            def args_for(source: Path) -> argparse.Namespace:
                return argparse.Namespace(
                    pdf=str(source),
                    output_dir=str(output_dir),
                    output_tag=None,
                    registry_file=str(root / "registry.json"),
                    reconvert=False,
                    pages="1",
                    images="none",
                    ocr="off",
                    ocr_language="eng",
                    no_page_files=False,
                    verbose=False,
                )

            extract_pdf.extract_document(args_for(first_source))
            with self.assertRaisesRegex(ValueError, "另一个 source"):
                extract_pdf.extract_document(args_for(second_source))

            manifest = json.loads(
                (output_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["source"], str(first_source.resolve()))

    def test_explicit_tag_creates_tagged_result_instead_of_reusing_untagged(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            output_dir = root / "result"
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                output_tag=None,
                registry_file=str(root / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            untagged = extract_pdf.extract_document(args)
            self.assertEqual(untagged["output_dir"], str(output_dir.resolve()))

            args.output_tag = "Needs Review"
            tagged = extract_pdf.extract_document(args)
            tagged_dir = root / "result-needs-review"
            self.assertFalse(tagged["already_converted"])
            self.assertEqual(tagged["output_dir"], str(tagged_dir.resolve()))
            manifest = json.loads(
                Path(tagged["manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["output_tag"], "needs-review")
            self.assertEqual(
                manifest["parameters"]["output_tag"],
                "needs-review",
            )

            reused = extract_pdf.extract_document(args)
            self.assertTrue(reused["already_converted"])
            self.assertEqual(reused["output_dir"], str(tagged_dir.resolve()))

    def test_same_source_with_different_output_reuses_until_forced(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            first_output = Path(parent) / "first"
            second_output = Path(parent) / "second"
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(first_output),
                registry_file=str(Path(parent) / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            extract_pdf.extract_document(args)
            args.output_dir = str(second_output)
            result = extract_pdf.extract_document(args)
            self.assertTrue(result["already_converted"])
            self.assertEqual(result["output_dir"], str(first_output.resolve()))
            self.assertEqual(result["requested_output_dir"], str(second_output.resolve()))
            self.assertFalse(second_output.exists())
            registry = json.loads(Path(result["registry"]).read_text(encoding="utf-8"))
            self.assertEqual(len(registry["conversions"]), 1)

            args.reconvert = True
            forced = extract_pdf.extract_document(args)
            self.assertFalse(forced["already_converted"])
            self.assertEqual(forced["output_dir"], str(second_output.resolve()))
            self.assertTrue(second_output.exists())
            registry = json.loads(Path(forced["registry"]).read_text(encoding="utf-8"))
            self.assertEqual(len(registry["conversions"]), 1)
            self.assertEqual(registry["conversions"][0]["output_dir"], str(second_output.resolve()))

    def test_matching_output_manifest_recreates_missing_registry(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "result"
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(Path(parent) / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            first = extract_pdf.extract_document(args)
            registry_path = Path(first["registry"])
            registry_path.unlink()
            second = extract_pdf.extract_document(args)
            self.assertTrue(second["already_converted"])
            self.assertTrue(registry_path.is_file())
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(len(registry["conversions"]), 1)

    def test_macos_metadata_does_not_block_existing_output_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "result"
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(Path(parent) / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            extract_pdf.extract_document(args)
            (output_dir / ".DS_Store").write_bytes(b"Finder metadata")

            result = extract_pdf.extract_document(args)

            self.assertTrue(result["already_converted"])
            self.assertTrue((output_dir / ".DS_Store").is_file())

    def test_different_parameters_are_ignored_unless_forced(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "result"
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(Path(parent) / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            first = extract_pdf.extract_document(args)
            args.pages = "999"
            second = extract_pdf.extract_document(args)
            self.assertTrue(second["already_converted"])
            self.assertEqual(first["conversion_id"], second["conversion_id"])
            self.assertTrue(second["parameters_ignored"])
            self.assertEqual(second["registered_parameters"]["pages"], [1])
            self.assertEqual(second["requested_parameters"]["pages"], "999")
            markdown = Path(second["markdown"]).read_text(encoding="utf-8")
            self.assertIn("<!-- page: 1 -->", markdown)

            args.pages = "2"
            args.reconvert = True
            third = extract_pdf.extract_document(args)
            self.assertFalse(third["already_converted"])
            markdown = Path(third["markdown"]).read_text(encoding="utf-8")
            self.assertIn("<!-- page: 2 -->", markdown)
            registry = json.loads(Path(second["registry"]).read_text(encoding="utf-8"))
            self.assertEqual(len(registry["conversions"]), 1)
            self.assertEqual(registry["conversions"][0]["parameters"]["pages"], [2])

    def test_refuses_to_overwrite_unrelated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "result"
            output_dir.mkdir()
            unrelated = output_dir / "notes.txt"
            unrelated.write_text("keep me", encoding="utf-8")
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(Path(parent) / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            with self.assertRaises(ValueError):
                extract_pdf.extract_document(args)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep me")

    def test_refuses_to_replace_modified_generated_output(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "result"
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(Path(parent) / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            extract_pdf.extract_document(args)
            added = output_dir / "pages" / "notes.txt"
            added.write_text("keep me", encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_pdf.extract_document(args)
            self.assertEqual(added.read_text(encoding="utf-8"), "keep me")

    def test_short_transaction_names_preserve_colliding_outputs(self) -> None:
        fixed_ns = 1_791_724_000_123_456_789
        fixed_time = extract_pdf.time.struct_time((2026, 10, 11, 21, 5, 7, 6, 284, -1))
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            for role in ("backup", "failed"):
                first_source = root / "abcdefghijk"
                second_source = root / "abcdefghijl"
                first_source.mkdir()
                second_source.mkdir()
                (first_source / "content").write_bytes(b"first")
                (second_source / "content").write_bytes(b"second")
                with mock.patch.object(extract_pdf.time, "time_ns", return_value=fixed_ns), \
                     mock.patch.object(extract_pdf.time, "localtime", return_value=fixed_time), \
                     mock.patch.object(extract_pdf.os, "getpid", return_value=12345):
                    first = extract_pdf.move_output_aside(first_source, role)
                    second = extract_pdf.move_output_aside(second_source, role)
                self.assertEqual(first.name, f".abcdefghij.{role}-12345-210507123456789")
                self.assertEqual(second.name, first.name + "-1")
                self.assertEqual((first / "content").read_bytes(), b"first")
                self.assertEqual((second / "content").read_bytes(), b"second")

    def test_long_output_name_can_be_reconverted_and_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            output_dir = root / ("a" * 240)
            try:
                output_dir.mkdir()
            except OSError as exc:
                self.skipTest(f"Filesystem does not support this long test path: {exc}")
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(root / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            extract_pdf.extract_document(args)
            args.reconvert = True
            self.assertEqual(extract_pdf.extract_document(args)["status"], "ok")
            original_manifest = (output_dir / "manifest.json").read_bytes()
            original_markdown = (output_dir / "document.md").read_bytes()
            with mock.patch.object(
                extract_pdf, "commit_registry_entry", side_effect=PermissionError("simulated registry failure")
            ):
                with self.assertRaises(PermissionError):
                    extract_pdf.extract_document(args)
            self.assertEqual((output_dir / "manifest.json").read_bytes(), original_manifest)
            self.assertEqual((output_dir / "document.md").read_bytes(), original_markdown)
            self.assertEqual({item.name for item in root.iterdir()}, {output_dir.name, "registry.json"})

    def test_activation_failure_restores_the_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            output_dir = (root / "result").resolve()
            args = argparse.Namespace(
                pdf=str(DEMO_PDF),
                output_dir=str(output_dir),
                registry_file=str(root / "registry.json"),
                reconvert=False,
                pages="1",
                images="none",
                ocr="off",
                ocr_language="eng",
                no_page_files=False,
                verbose=False,
            )
            first = extract_pdf.extract_document(args)
            original = Path(first["markdown"]).read_bytes()
            args.reconvert = True
            real_rename = Path.rename

            def fail_new_output_activation(path: Path, target: Path) -> Path:
                if path.name.startswith(".test_pdf_read_script-") and Path(target) == output_dir:
                    raise PermissionError("simulated activation failure")
                return real_rename(path, target)

            with mock.patch.object(Path, "rename", new=fail_new_output_activation):
                with self.assertRaises(PermissionError):
                    extract_pdf.extract_document(args)

            self.assertTrue(output_dir.is_dir())
            self.assertEqual(Path(first["markdown"]).read_bytes(), original)
            self.assertFalse(list(root.glob(".test_pdf_read_script-*")))


if __name__ == "__main__":
    unittest.main()
