"""
Image Scanner Module - OCR-based secret and PII detection in images.

Extracts text from images using OCR (rapidocr-onnxruntime), then the
extracted text is passed through existing secret/PII scanners by the
hook processing pipeline.

Only runs on the inbound path (PreToolUse file reads, UserPromptSubmit
image attachments). PostToolUse is excluded — the AI already converted
image content to text, which existing text scanners handle.

Enabled by default. Requires rapidocr-onnxruntime (regular dependency).

NEW in v1.10.0 (Issue #720)
"""

import base64
import io
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

try:
    from PIL import Image, ImageFilter

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    from rapidocr_onnxruntime import RapidOCR

    HAS_RAPIDOCR = True
except ImportError:
    HAS_RAPIDOCR = False

try:
    from pyzbar import pyzbar

    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False

try:
    import cv2

    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".ico",
    }
)

MAGIC_BYTES = {
    b"\x89PNG": "png",
    b"\xff\xd8\xff": "jpeg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"BM": "bmp",
    b"II\x2a\x00": "tiff",
    b"MM\x00\x2a": "tiff",
    b"RIFF": "webp",
}

_BASE64_IMAGE_RE = re.compile(
    r"data:image/[a-zA-Z0-9+.-]+;base64,([A-Za-z0-9+/=]+)",
)


@dataclass
class TextRegion:
    """A region of text detected by OCR with its bounding box."""

    text: str
    bbox: Tuple[int, int, int, int]  # (x, y, width, height)
    confidence: float


@dataclass
class OCRResult:
    """Result from OCR text extraction."""

    text: str
    regions: List[TextRegion] = field(default_factory=list)
    confidence: float = 0.0
    elapsed_ms: float = 0.0


@dataclass
class ImageScanResult:
    """Combined result from all image scanning operations."""

    extracted_text: str = ""
    text_regions: List[TextRegion] = field(default_factory=list)
    qr_texts: List[str] = field(default_factory=list)
    face_regions: List[Tuple[int, int, int, int]] = field(default_factory=list)
    ocr_confidence: float = 0.0
    elapsed_ms: float = 0.0


class ImageDetector:
    """Detects whether data is an image by extension or magic bytes."""

    @staticmethod
    def is_image_file(file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            return True
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)
            return ImageDetector._check_magic_bytes(header)
        except (OSError, IOError):
            return False

    @staticmethod
    def is_image_bytes(data: bytes) -> bool:
        if len(data) < 4:
            return False
        return ImageDetector._check_magic_bytes(data[:16])

    @staticmethod
    def _check_magic_bytes(header: bytes) -> bool:
        for magic, _ in MAGIC_BYTES.items():
            if header.startswith(magic):
                if magic == b"RIFF" and len(header) >= 12:
                    if header[8:12] != b"WEBP":
                        continue
                return True
        return False

    @staticmethod
    def is_base64_image(text: str) -> bool:
        return bool(_BASE64_IMAGE_RE.search(text))

    @staticmethod
    def strip_base64_images(text: str) -> str:
        """Remove base64 image data URIs from text, leaving only non-image content."""
        return _BASE64_IMAGE_RE.sub("", text)

    @staticmethod
    def extract_base64_images(text: str) -> List[bytes]:
        results = []
        for match in _BASE64_IMAGE_RE.finditer(text):
            try:
                b64_data = (
                    match.group(1).replace("\n", "").replace("\r", "").replace(" ", "")
                )
                image_bytes = base64.b64decode(b64_data)
                if ImageDetector.is_image_bytes(image_bytes):
                    results.append(image_bytes)
            except Exception:
                continue
        return results


class OCREngine:
    """Extracts text from images using rapidocr-onnxruntime."""

    def __init__(self, config: Optional[dict] = None):
        self._engine = None
        self._config = config or {}

    def _get_engine(self):
        if self._engine is None:
            if not HAS_RAPIDOCR:
                raise ImportError(
                    "rapidocr-onnxruntime is required for image scanning "
                    "(available on Python < 3.13)"
                )
            self._engine = RapidOCR()
        return self._engine

    def extract_text(self, image_data: bytes) -> OCRResult:
        start = time.monotonic()
        min_confidence = self._config.get("min_confidence", 0.5)

        try:
            engine = self._get_engine()
            result = engine(image_data)

            if result is None:
                return OCRResult(text="", elapsed_ms=_elapsed(start))

            # rapidocr returns: (list_of_results, elapsed_time)
            # Each item: [[box_points], text, confidence]
            ocr_items = result[0] if result[0] else []
            regions = []
            texts = []
            total_conf = 0.0

            for item in ocr_items:
                box_points, text, confidence = item
                if confidence < min_confidence:
                    continue

                bbox = _box_points_to_bbox(box_points)
                regions.append(
                    TextRegion(
                        text=text,
                        bbox=bbox,
                        confidence=confidence,
                    )
                )
                texts.append(text)
                total_conf += confidence

            avg_conf = total_conf / len(regions) if regions else 0.0
            full_text = "\n".join(texts)

            return OCRResult(
                text=full_text,
                regions=regions,
                confidence=avg_conf,
                elapsed_ms=_elapsed(start),
            )

        except ImportError:
            raise
        except Exception as e:
            logger.warning(f"OCR extraction failed: {e}")
            return OCRResult(text="", elapsed_ms=_elapsed(start))


class ImageRedactor:
    """Redacts regions of an image using blur, blackout, or pixelate."""

    def __init__(self, method: str = "blackout"):
        if method not in ("blur", "blackout", "pixelate"):
            method = "blackout"
        self.method = method

    def redact_regions(
        self,
        image_data: bytes,
        regions: List[TextRegion],
        output_format: str = "PNG",
    ) -> bytes:
        if not HAS_PILLOW:
            raise ImportError("Pillow is required for image redaction")
        if not regions:
            return image_data

        img = Image.open(io.BytesIO(image_data))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        for region in regions:
            x, y, w, h = region.bbox
            if w <= 0 or h <= 0:
                continue
            box = (x, y, x + w, y + h)
            cropped = img.crop(box)

            if self.method == "blur":
                radius = max(w, h) // 2
                if radius < 20:
                    radius = 20
                redacted = cropped.filter(ImageFilter.GaussianBlur(radius=radius))
            elif self.method == "blackout":
                redacted = Image.new("RGB", cropped.size, (0, 0, 0))
            elif self.method == "pixelate":
                small_size = (min(w, 2), min(h, 2))
                small = cropped.resize(small_size, Image.BILINEAR)
                redacted = small.resize(cropped.size, Image.NEAREST)
            else:
                continue

            img.paste(redacted, box)

        buf = io.BytesIO()
        img.save(buf, format=output_format)
        return buf.getvalue()


class QRScanner:
    """Scans QR codes in images for embedded secrets."""

    @staticmethod
    def scan(image_data: bytes) -> List[str]:
        if not HAS_PYZBAR:
            return []
        if not HAS_PILLOW:
            return []
        try:
            img = Image.open(io.BytesIO(image_data))
            decoded = pyzbar.decode(img)
            return [d.data.decode("utf-8", errors="replace") for d in decoded if d.data]
        except Exception as e:
            logger.warning(f"QR scanning failed: {e}")
            return []


class FaceDetector:
    """Detects faces in images (biometric PII)."""

    _cascade = None

    @classmethod
    def detect_faces(cls, image_data: bytes) -> List[Tuple[int, int, int, int]]:
        if not HAS_OPENCV:
            return []
        try:
            import numpy as np

            # OpenCV's optional Python stubs do not expose these runtime APIs
            # consistently across supported environments.
            opencv: Any = cv2
            nparr: Any = np.frombuffer(image_data, np.uint8)
            img = opencv.imdecode(nparr, opencv.IMREAD_GRAYSCALE)
            if img is None:
                return []

            if cls._cascade is None:
                cascade_path = (
                    opencv.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
                cls._cascade = opencv.CascadeClassifier(cascade_path)

            faces = cls._cascade.detectMultiScale(
                img, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            if len(faces) == 0:
                return []
            return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]
        except Exception as e:
            logger.warning(f"Face detection failed: {e}")
            return []


def scan_image(image_data: bytes, config: dict) -> ImageScanResult:
    """
    Scan an image for text (via OCR), QR codes, and faces.

    The extracted text is returned for downstream scanning by the
    existing secret/PII/prompt-injection scanners in hook_processing.py.
    This function does NOT perform secret/PII scanning itself.

    Args:
        image_data: Raw image bytes
        config: image_scanning config dict

    Returns:
        ImageScanResult with extracted text and detected regions
    """
    start = time.monotonic()

    max_size = config.get("max_image_size_mb", 10) * 1024 * 1024
    if len(image_data) > max_size:
        logger.warning(
            f"Image too large ({len(image_data)} bytes > {max_size} bytes), "
            "skipping OCR"
        )
        return ImageScanResult(elapsed_ms=_elapsed(start))

    result = ImageScanResult()

    # OCR text extraction
    try:
        ocr = OCREngine(config)
        ocr_result = ocr.extract_text(image_data)
        result.extracted_text = ocr_result.text
        result.text_regions = ocr_result.regions
        result.ocr_confidence = ocr_result.confidence
    except ImportError:
        logger.warning("rapidocr-onnxruntime not available, skipping OCR")
    except Exception as e:
        logger.warning(f"OCR failed: {e}")

    # QR code scanning (opt-in)
    if config.get("qr_scanning", False):
        result.qr_texts = QRScanner.scan(image_data)
        if result.qr_texts:
            logger.info(f"QR scanner found {len(result.qr_texts)} code(s)")

    # Face detection (opt-in)
    if config.get("face_detection", False):
        result.face_regions = FaceDetector.detect_faces(image_data)
        if result.face_regions:
            logger.info(f"Face detector found {len(result.face_regions)} face(s)")

    result.elapsed_ms = _elapsed(start)
    return result


def _box_points_to_bbox(box_points) -> Tuple[int, int, int, int]:
    """Convert rapidocr box points to (x, y, width, height) bbox."""
    try:
        xs = [p[0] for p in box_points]
        ys = [p[1] for p in box_points]
        x = int(min(xs))
        y = int(min(ys))
        w = int(max(xs)) - x
        h = int(max(ys)) - y
        return (x, y, w, h)
    except (TypeError, IndexError, ValueError):
        return (0, 0, 0, 0)


def _elapsed(start: float) -> float:
    return (time.monotonic() - start) * 1000
