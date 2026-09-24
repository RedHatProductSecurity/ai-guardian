"""
Unit tests for image_scanner module (Issue #720).

Tests OCR-based secret and PII detection in images.
Uses mock OCR engine to avoid model downloads in CI.
"""

import io
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch, MagicMock

import pytest

from PIL import Image, ImageDraw

from ai_guardian.scanners.image_scanner import (
    ImageDetector,
    OCREngine,
    OCRResult,
    TextRegion,
    ImageRedactor,
    ImageScanResult,
    scan_image,
    _box_points_to_bbox,
)


def _create_test_image(width=200, height=100, color="white", fmt="PNG"):
    """Create a minimal test image in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _create_test_image_file(tmpdir, filename="test.png", fmt="PNG"):
    """Create a test image file on disk."""
    data = _create_test_image(fmt=fmt)
    path = os.path.join(tmpdir, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path


class TestImageDetector(TestCase):
    """Test image file detection by extension and magic bytes."""

    def test_image_extensions_detected(self):
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".ico"]:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = _create_test_image_file(tmpdir, f"test{ext}")
                self.assertTrue(
                    ImageDetector.is_image_file(path),
                    f"Should detect {ext} as image",
                )

    def test_non_image_extension_not_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.py")
            with open(path, "w") as f:
                f.write("print('hello')")
            self.assertFalse(ImageDetector.is_image_file(path))

    def test_svg_not_detected_as_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.svg")
            with open(path, "w") as f:
                f.write('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
            self.assertFalse(ImageDetector.is_image_file(path))

    def test_magic_bytes_png(self):
        data = _create_test_image(fmt="PNG")
        self.assertTrue(ImageDetector.is_image_bytes(data))

    def test_magic_bytes_jpeg(self):
        data = _create_test_image(fmt="JPEG")
        self.assertTrue(ImageDetector.is_image_bytes(data))

    def test_magic_bytes_bmp(self):
        data = _create_test_image(fmt="BMP")
        self.assertTrue(ImageDetector.is_image_bytes(data))

    def test_non_image_bytes_not_detected(self):
        self.assertFalse(ImageDetector.is_image_bytes(b"print('hello')"))
        self.assertFalse(ImageDetector.is_image_bytes(b""))
        self.assertFalse(ImageDetector.is_image_bytes(b"\x00\x01\x02"))

    def test_short_bytes_not_detected(self):
        self.assertFalse(ImageDetector.is_image_bytes(b"\x89"))
        self.assertFalse(ImageDetector.is_image_bytes(b""))

    def test_nonexistent_image_path_detected_by_extension(self):
        self.assertTrue(ImageDetector.is_image_file("/nonexistent/path/test.png"))

    def test_nonexistent_non_image_path(self):
        self.assertFalse(ImageDetector.is_image_file("/nonexistent/path/test.py"))

    def test_is_base64_image_valid(self):
        import base64

        data = _create_test_image()
        b64 = base64.b64encode(data).decode()
        text = f"Here is an image: data:image/png;base64,{b64}"
        self.assertTrue(ImageDetector.is_base64_image(text))

    def test_is_base64_image_no_image(self):
        self.assertFalse(ImageDetector.is_base64_image("just some text"))
        self.assertFalse(ImageDetector.is_base64_image(""))

    def test_extract_base64_images(self):
        import base64

        data = _create_test_image()
        b64 = base64.b64encode(data).decode()
        text = f"Image: data:image/png;base64,{b64} end"
        images = ImageDetector.extract_base64_images(text)
        self.assertEqual(len(images), 1)
        self.assertTrue(ImageDetector.is_image_bytes(images[0]))

    def test_extract_multiple_base64_images(self):
        import base64

        data1 = _create_test_image(color="red")
        data2 = _create_test_image(color="blue")
        b64_1 = base64.b64encode(data1).decode()
        b64_2 = base64.b64encode(data2).decode()
        text = f"data:image/png;base64,{b64_1} and data:image/jpeg;base64,{b64_2}"
        images = ImageDetector.extract_base64_images(text)
        self.assertEqual(len(images), 2)

    def test_strip_base64_images_removes_data_uri(self):
        import base64

        data = _create_test_image()
        b64 = base64.b64encode(data).decode()
        text = f"Hello world data:image/png;base64,{b64} some text after"
        result = ImageDetector.strip_base64_images(text)
        self.assertNotIn("base64", result)
        self.assertIn("Hello world", result)
        self.assertIn("some text after", result)

    def test_strip_base64_images_no_images(self):
        text = "Just plain text without images"
        result = ImageDetector.strip_base64_images(text)
        self.assertEqual(result, text)

    def test_strip_base64_images_multiple(self):
        import base64

        data1 = _create_test_image(color="red")
        data2 = _create_test_image(color="blue")
        b64_1 = base64.b64encode(data1).decode()
        b64_2 = base64.b64encode(data2).decode()
        text = f"before data:image/png;base64,{b64_1} middle data:image/jpeg;base64,{b64_2} after"
        result = ImageDetector.strip_base64_images(text)
        self.assertNotIn("base64", result)
        self.assertIn("before", result)
        self.assertIn("middle", result)
        self.assertIn("after", result)

    def test_strip_base64_images_preserves_ocr_text(self):
        """Verify that stripping happens on the original content, not on appended OCR text."""
        import base64

        data = _create_test_image()
        b64 = base64.b64encode(data).decode()
        content = f"User prompt data:image/png;base64,{b64}"
        ocr_text = "OCR extracted: API_KEY=test123"
        content_with_ocr = f"{content}\n{ocr_text}"
        result = ImageDetector.strip_base64_images(content_with_ocr)
        self.assertNotIn("base64", result)
        self.assertIn("User prompt", result)
        self.assertIn(ocr_text, result)


class TestOCREngine(TestCase):
    """Test OCR engine with mocked RapidOCR output."""

    @patch("ai_guardian.scanners.image_scanner.HAS_RAPIDOCR", True)
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="OCR dependencies may not be available on Windows CI",
    )
    def test_extract_text_basic(self):
        mock_engine = MagicMock()
        mock_engine.return_value = SimpleNamespace(
            boxes=[
                [[10, 10], [100, 10], [100, 30], [10, 30]],
                [[10, 40], [100, 40], [100, 60], [10, 60]],
            ],
            txts=("API_KEY=secret123", "normal text"),
            scores=(0.95, 0.88),
        )

        ocr = OCREngine(config={"min_confidence": 0.5})
        ocr._engine = mock_engine
        result = ocr.extract_text(_create_test_image())

        self.assertIn("API_KEY=secret123", result.text)
        self.assertIn("normal text", result.text)
        self.assertEqual(len(result.regions), 2)
        self.assertEqual(result.regions[0].bbox, (10, 10, 90, 20))
        self.assertEqual(result.regions[0].confidence, 0.95)
        self.assertGreaterEqual(result.confidence, 0)
        self.assertGreaterEqual(result.elapsed_ms, 0)

    def test_extract_text_empty_result(self):
        mock_engine = MagicMock()
        mock_engine.return_value = SimpleNamespace(
            boxes=None,
            txts=None,
            scores=None,
        )

        ocr = OCREngine()
        ocr._engine = mock_engine
        result = ocr.extract_text(_create_test_image())

        self.assertEqual(result.text, "")
        self.assertEqual(len(result.regions), 0)

    def test_confidence_filtering(self):
        mock_engine = MagicMock()
        mock_engine.return_value = SimpleNamespace(
            boxes=[
                [[10, 10], [100, 10], [100, 30], [10, 30]],
                [[10, 40], [100, 40], [100, 60], [10, 60]],
            ],
            txts=("high conf", "low conf"),
            scores=(0.9, 0.2),
        )

        ocr = OCREngine(config={"min_confidence": 0.5})
        ocr._engine = mock_engine
        result = ocr.extract_text(_create_test_image())

        self.assertIn("high conf", result.text)
        self.assertNotIn("low conf", result.text)
        self.assertEqual(len(result.regions), 1)

    @patch("ai_guardian.scanners.image_scanner.HAS_RAPIDOCR", False)
    def test_no_rapidocr_raises(self):
        ocr = OCREngine()
        with self.assertRaises(ImportError):
            ocr.extract_text(_create_test_image())

    def test_ocr_exception_returns_empty(self):
        mock_engine = MagicMock()
        mock_engine.side_effect = RuntimeError("OCR failed")

        ocr = OCREngine()
        ocr._engine = mock_engine
        result = ocr.extract_text(_create_test_image())

        self.assertEqual(result.text, "")


class TestImageRedactor(TestCase):
    """Test image redaction with blur/blackout/pixelate."""

    def test_blur_redaction(self):
        data = _create_test_image(200, 100)
        regions = [TextRegion(text="secret", bbox=(10, 10, 50, 20), confidence=0.9)]
        redactor = ImageRedactor(method="blur")
        result = redactor.redact_regions(data, regions)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (200, 100))

    def test_blackout_redaction(self):
        data = _create_test_image(200, 100)
        regions = [TextRegion(text="secret", bbox=(10, 10, 50, 20), confidence=0.9)]
        redactor = ImageRedactor(method="blackout")
        result = redactor.redact_regions(data, regions)
        img = Image.open(io.BytesIO(result))
        pixel = img.getpixel((35, 20))
        self.assertEqual(pixel, (0, 0, 0))

    def test_pixelate_redaction(self):
        data = _create_test_image(200, 100)
        regions = [TextRegion(text="secret", bbox=(10, 10, 50, 20), confidence=0.9)]
        redactor = ImageRedactor(method="pixelate")
        result = redactor.redact_regions(data, regions)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_empty_regions_returns_original(self):
        data = _create_test_image()
        redactor = ImageRedactor(method="blur")
        result = redactor.redact_regions(data, [])
        self.assertEqual(result, data)

    def test_invalid_method_defaults_to_blackout(self):
        redactor = ImageRedactor(method="invalid")
        self.assertEqual(redactor.method, "blackout")

    def test_multiple_regions(self):
        data = _create_test_image(200, 100)
        regions = [
            TextRegion(text="secret1", bbox=(10, 10, 50, 20), confidence=0.9),
            TextRegion(text="secret2", bbox=(80, 40, 60, 25), confidence=0.85),
        ]
        redactor = ImageRedactor(method="blackout")
        result = redactor.redact_regions(data, regions)
        self.assertIsInstance(result, bytes)

    def test_pixelate_produces_coarse_blocks(self):
        """Pixelated region should have very few distinct colors (max 2x2 blocks)."""
        data = _create_test_image(200, 100, color="white")
        img = Image.open(io.BytesIO(data))
        draw = ImageDraw.Draw(img)
        draw.text((15, 12), "AKIAIOSFODNN7EXAMPLE", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data_with_text = buf.getvalue()

        regions = [
            TextRegion(
                text="AKIAIOSFODNN7EXAMPLE", bbox=(10, 10, 100, 20), confidence=0.9
            )
        ]
        redactor = ImageRedactor(method="pixelate")
        result = redactor.redact_regions(data_with_text, regions)
        result_img = Image.open(io.BytesIO(result))
        region = result_img.crop((10, 10, 110, 30))
        colors = region.getcolors(maxcolors=1000)
        self.assertLessEqual(len(colors), 4)

    def test_blackout_fully_opaque_rgba(self):
        """Blackout on RGBA image should produce fully opaque black pixels."""
        img = Image.new("RGBA", (200, 100), (255, 255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        regions = [TextRegion(text="secret", bbox=(10, 10, 50, 20), confidence=0.9)]
        redactor = ImageRedactor(method="blackout")
        result = redactor.redact_regions(data, regions)
        result_img = Image.open(io.BytesIO(result))
        pixel = result_img.getpixel((35, 20))
        self.assertEqual(pixel[:3], (0, 0, 0))

    def test_blur_uses_strong_radius(self):
        """Blur should use a strong enough radius that text is not recognizable."""
        img = Image.new("RGB", (200, 100), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((15, 12), "SECRET_KEY=abc123", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        regions = [
            TextRegion(text="SECRET_KEY=abc123", bbox=(10, 10, 80, 20), confidence=0.9)
        ]
        redactor = ImageRedactor(method="blur")
        result = redactor.redact_regions(data, regions)
        result_img = Image.open(io.BytesIO(result))
        region = result_img.crop((10, 10, 90, 30))
        colors = region.getcolors(maxcolors=10000)
        unique_pixels = colors
        self.assertGreater(len(colors), 1)

    def test_default_method_is_blackout(self):
        """Default redaction method should be blackout (safest)."""
        redactor = ImageRedactor()
        self.assertEqual(redactor.method, "blackout")


class TestBoxPointsToBbox(TestCase):
    """Test coordinate conversion from rapidocr format."""

    def test_normal_box_points(self):
        box = [[10, 20], [110, 20], [110, 50], [10, 50]]
        x, y, w, h = _box_points_to_bbox(box)
        self.assertEqual(x, 10)
        self.assertEqual(y, 20)
        self.assertEqual(w, 100)
        self.assertEqual(h, 30)

    def test_invalid_box_points(self):
        self.assertEqual(_box_points_to_bbox(None), (0, 0, 0, 0))
        self.assertEqual(_box_points_to_bbox([]), (0, 0, 0, 0))
        self.assertEqual(_box_points_to_bbox("invalid"), (0, 0, 0, 0))


class TestScanImage(TestCase):
    """Test the scan_image orchestrator function."""

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="OCR dependencies may not be available on Windows CI",
    )
    @patch("ai_guardian.scanners.image_scanner.OCREngine")
    def test_scan_image_with_text(self, mock_engine_cls):
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine
        mock_engine.extract_text.return_value = OCRResult(
            text="AWS_SECRET=AKIAIOSFODNN7EXAMPLE",
            regions=[
                TextRegion(
                    text="AWS_SECRET=AKIAIOSFODNN7EXAMPLE",
                    bbox=(10, 10, 100, 20),
                    confidence=0.95,
                )
            ],
            confidence=0.95,
            elapsed_ms=200.0,
        )

        config = {
            "enabled": True,
            "max_image_size_mb": 10,
            "qr_scanning": False,
            "face_detection": False,
        }
        result = scan_image(_create_test_image(), config)

        self.assertIn("AWS_SECRET", result.extracted_text)
        self.assertEqual(len(result.text_regions), 1)
        self.assertGreaterEqual(result.elapsed_ms, 0)

    @patch("ai_guardian.scanners.image_scanner.OCREngine")
    def test_scan_image_too_large(self, mock_engine_cls):
        config = {"max_image_size_mb": 0}
        result = scan_image(_create_test_image(), config)
        self.assertEqual(result.extracted_text, "")
        mock_engine_cls.assert_not_called()

    @patch("ai_guardian.scanners.image_scanner.OCREngine")
    def test_scan_image_ocr_failure(self, mock_engine_cls):
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine
        mock_engine.extract_text.side_effect = RuntimeError("OCR crash")

        config = {
            "max_image_size_mb": 10,
            "qr_scanning": False,
            "face_detection": False,
        }
        result = scan_image(_create_test_image(), config)
        self.assertEqual(result.extracted_text, "")

    @patch("ai_guardian.scanners.image_scanner.QRScanner")
    @patch("ai_guardian.scanners.image_scanner.OCREngine")
    def test_scan_image_with_qr(self, mock_engine_cls, mock_qr_cls):
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine
        mock_engine.extract_text.return_value = OCRResult(text="", elapsed_ms=100)

        mock_qr_cls.scan.return_value = ["https://internal.corp/api?token=secret123"]

        config = {
            "max_image_size_mb": 10,
            "qr_scanning": True,
            "face_detection": False,
        }
        result = scan_image(_create_test_image(), config)
        self.assertEqual(len(result.qr_texts), 1)
        self.assertIn("secret123", result.qr_texts[0])


class TestQRScanner(TestCase):
    """Test QR scanner (with mocked pyzbar)."""

    @patch("ai_guardian.scanners.image_scanner.HAS_PYZBAR", False)
    def test_no_pyzbar_returns_empty(self):
        from ai_guardian.scanners.image_scanner import QRScanner

        result = QRScanner.scan(_create_test_image())
        self.assertEqual(result, [])


class TestFaceDetector(TestCase):
    """Test face detector (with mocked opencv)."""

    @patch("ai_guardian.scanners.image_scanner.HAS_OPENCV", False)
    def test_no_opencv_returns_empty(self):
        from ai_guardian.scanners.image_scanner import FaceDetector

        result = FaceDetector.detect_faces(_create_test_image())
        self.assertEqual(result, [])


class TestConfigLoader(TestCase):
    """Test image scanning config loading."""

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_default_config(self, mock_load):
        mock_load.return_value = ({}, None)
        from ai_guardian.config.loaders import _load_image_scanning_config

        config, error = _load_image_scanning_config()
        self.assertIsNone(error)
        self.assertIsNotNone(config)
        self.assertTrue(config["enabled"])
        self.assertEqual(config["action"], "block")
        self.assertIn("secrets", config["scan_types"])

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_custom_config(self, mock_load):
        mock_load.return_value = (
            {"image_scanning": {"enabled": False, "action": "warn"}},
            None,
        )
        from ai_guardian.config.loaders import _load_image_scanning_config

        config, error = _load_image_scanning_config()
        self.assertIsNone(error)
        self.assertFalse(config["enabled"])
        self.assertEqual(config["action"], "warn")


class TestHookIntegration(TestCase):
    """Test image scanning integration in hook processing."""

    @patch("ai_guardian.config.loaders._load_image_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_image_file_triggers_ocr(self, mock_ps, mock_ss, mock_img):
        """When a Read tool accesses an image file, OCR should run."""
        mock_ps.return_value = None
        mock_ss.return_value = ({"enabled": True}, None)
        mock_img.return_value = (
            {
                "enabled": True,
                "action": "block",
                "scan_types": ["secrets"],
                "max_image_size_mb": 10,
                "ignore_files": [],
                "ignore_tools": [],
                "qr_scanning": False,
                "face_detection": False,
                "min_confidence": 0.5,
            },
            None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = _create_test_image_file(tmpdir, "screenshot.png")

            with (
                patch("ai_guardian.hook_events.scanners.HAS_IMAGE_SCANNER", True),
                patch(
                    "ai_guardian.hook_events.scanners.ImageDetector"
                ) as mock_detector,
                patch("ai_guardian.hook_events.scanners.scan_image") as mock_scan,
            ):

                mock_detector.is_image_file.return_value = True
                mock_scan.return_value = ImageScanResult(
                    extracted_text="normal text here",
                    elapsed_ms=200,
                )

                from ai_guardian.hook_processing import process_hook_data

                hook_data = {
                    "hook": "PreToolUse",
                    "tool_name": "Read",
                    "tool_use": {
                        "name": "Read",
                        "input": {"file_path": img_path},
                    },
                }

                result = process_hook_data(hook_data)
                self.assertEqual(result["exit_code"], 0)
                mock_scan.assert_called_once()

    @patch("ai_guardian.config.loaders._load_image_scanning_config")
    def test_image_scanning_disabled_skips_ocr(self, mock_img):
        """When image scanning is disabled, OCR should not run."""
        mock_img.return_value = ({"enabled": False}, None)

        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = _create_test_image_file(tmpdir, "test.png")

            with (
                patch("ai_guardian.hook_events.scanners.HAS_IMAGE_SCANNER", True),
                patch(
                    "ai_guardian.hook_events.scanners.ImageDetector"
                ) as mock_detector,
                patch("ai_guardian.hook_events.scanners.scan_image") as mock_scan,
            ):

                mock_detector.is_image_file.return_value = True

                from ai_guardian.hook_processing import process_hook_data

                hook_data = {
                    "hook": "PreToolUse",
                    "tool_name": "Read",
                    "tool_use": {
                        "name": "Read",
                        "input": {"file_path": img_path},
                    },
                }

                result = process_hook_data(hook_data)
                mock_scan.assert_not_called()
