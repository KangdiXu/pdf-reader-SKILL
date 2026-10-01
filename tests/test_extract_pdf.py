from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "extract_pdf.py"
DEMO_PDF = SKILL_DIR / "transform_demo" / "test_pdf_read_script.pdf"

spec = importlib.util.spec_from_file_location("extract_pdf", SCRIPT)
extract_pdf = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(extract_pdf)


class ExtractPdfTests(unittest.TestCase):
    def test_parse_pages(self) -> None:
        self.assertEqual(extract_pdf.parse_pages("1-2,2,4", 5), [0, 1, 3])
        with self.assertRaises(ValueError):
            extract_pdf.parse_pages("0", 5)
        with self.assertRaises(ValueError):
            extract_pdf.parse_pages("4-2", 5)

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

    def test_default_names_are_source_based(self) -> None:
        first = Path("/tmp/source-a/report.pdf").resolve()
        second = Path("/tmp/source-b/report.pdf").resolve()
        self.assertEqual(extract_pdf.markdown_filename(first), "report.md")
        self.assertNotEqual(
            extract_pdf.default_output_name(first),
            extract_pdf.default_output_name(second),
        )
        target = Path("/tmp/output/result").resolve()
        self.assertEqual(
            extract_pdf.resolve_registry_file(first, target, None),
            first.parent / extract_pdf.REGISTRY_FILENAME,
        )

    def test_conversion_id_depends_only_on_source(self) -> None:
        target = Path("/tmp/pdf-reader-result").resolve()
        options = {
            "pages": [1],
            "images": "none",
            "ocr": "off",
            "ocr_language": "eng",
            "page_files": True,
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
            markdown = Path(second["markdown"]).read_text(encoding="utf-8")
            self.assertIn("<!-- page: 1 -->", markdown)
            manifest = json.loads(Path(second["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["generator"], "pdf-reader")
            self.assertEqual(manifest["pages_processed"], 1)
            self.assertIn("manifest.json", manifest["generated_files"])
            registry = json.loads(Path(second["registry"]).read_text(encoding="utf-8"))
            entry = registry["conversions"][0]
            self.assertEqual(entry["source"], str(DEMO_PDF.resolve()))
            self.assertEqual(entry["output_folder"], "result")
            self.assertEqual(entry["parameters"]["pages"], [1])
            args.reconvert = True
            third = extract_pdf.extract_document(args)
            self.assertFalse(third["already_converted"])
            self.assertEqual(third["conversion_id"], first["conversion_id"])

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


if __name__ == "__main__":
    unittest.main()
