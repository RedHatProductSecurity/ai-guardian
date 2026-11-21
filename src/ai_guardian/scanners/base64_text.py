"""Bounded extraction and source mapping for Base64-encoded text.

Only canonical UTF-8 text candidates are returned; printable characters,
ordinary whitespace, and Unicode format characters are accepted. Inspection
is limited to one decode layer, 16 candidates, 64 KiB per encoded candidate,
and 256 KiB of decoded text per source. Image data-URI payloads are excluded
and remain owned by the image/OCR scanner.
"""

import base64
import binascii
import re
from heapq import merge
import unicodedata
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple

MAX_CANDIDATES = 16
MAX_ENCODED_CHARS = 64 * 1024
MAX_TOTAL_DECODED_BYTES = 256 * 1024
MIN_ENCODED_CHARS = 12

_BASE64_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9+/_-])"
    rf"([A-Za-z0-9+/_-]{{{MIN_ENCODED_CHARS},{MAX_ENCODED_CHARS}}}={{0,2}})"
    r"(?![A-Za-z0-9+/_=-])"
)
_BASE64_WRAPPED_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9+/_-])"
    r"([A-Za-z0-9+/_-]{4,}(?:[ \t\r\n]+[A-Za-z0-9+/_-]{4,})+"
    r"(?:[ \t\r\n]+[A-Za-z0-9+/_-]{1,3})?[ \t\r\n]*={0,2})"
    r"(?![A-Za-z0-9+/_=-])"
)
_BASE64_WRAP_RE = re.compile(r"[ \t\r\n]+")


@dataclass(frozen=True)
class DecodedBase64Text:
    """A decoded text candidate and its span in the original source."""

    text: str
    encoded: str
    start: int
    end: int

    def source_offset(self, decoded_offset: int) -> int:
        """Map a decoded character offset to its approximate Base64 source offset."""
        bounded_offset = min(max(decoded_offset, 0), len(self.text))
        if bounded_offset == len(self.text):
            return self.end

        byte_offset = len(self.text[:bounded_offset].encode("utf-8"))
        remainder_offsets = (0, 2, 3)
        encoded_offset = (byte_offset // 3) * 4 + remainder_offsets[byte_offset % 3]
        source_offset = 0
        encoded_char_offset = 0
        for source_offset, char in enumerate(self.encoded):
            if char in " \t\r\n":
                continue
            if encoded_char_offset >= encoded_offset:
                return min(self.start + source_offset, self.end)
            encoded_char_offset += 1
        return self.end

    def source_location(self, source: str, decoded_offset: int) -> Tuple[int, int]:
        """Return one-based line and zero-based column in the original source."""
        source_offset = self.source_offset(decoded_offset)
        prefix = source[:source_offset]
        line_number = prefix.count("\n") + prefix.count("\r") - prefix.count("\r\n") + 1
        last_line_break = max(prefix.rfind("\n"), prefix.rfind("\r"))
        return line_number, source_offset - last_line_break - 1

    def decoded_offset(self, line_number: Optional[int], column: Optional[int]) -> int:
        """Convert a detector's line/column pair to a decoded-text offset."""
        if type(line_number) is not int or line_number < 1:
            return 0

        lines = self.text.splitlines(keepends=True)
        if line_number > len(lines):
            return 0

        line_start = sum(len(line) for line in lines[: line_number - 1])
        line = lines[line_number - 1].rstrip("\r\n")
        if type(column) is not int:
            column = 0
        bounded_column = min(max(column, 0), len(line))
        return line_start + bounded_column


def _decode_candidate(encoded: str) -> Optional[Tuple[str, int]]:
    """Decode a canonical Base64 token when it contains text-like UTF-8."""
    if any(
        char
        not in " \t\r\nABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/_-="
        for char in encoded
    ):
        return None

    normalized = _BASE64_WRAP_RE.sub("", encoded)
    if len(normalized) > MAX_ENCODED_CHARS:
        return None

    padding = len(normalized) - len(normalized.rstrip("="))
    unpadded = normalized[:-padding] if padding else normalized
    if padding:
        if len(normalized) % 4:
            return None
        padded = normalized
    else:
        remainder = len(unpadded) % 4
        if remainder == 1:
            return None
        padded = normalized + ("=" * ((4 - remainder) % 4))

    # The exact decoded size is checked after decoding; reject obviously oversized
    # values first so no large temporary allocation is needed.
    estimated_bytes = (len(padded) // 4) * 3 - (len(padded) - len(padded.rstrip("=")))
    if estimated_bytes > (MAX_ENCODED_CHARS * 3 // 4):
        return None

    try:
        decoded_bytes = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return None

    canonical = {
        base64.b64encode(decoded_bytes).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(decoded_bytes).decode("ascii").rstrip("="),
    }
    if unpadded not in canonical or len(decoded_bytes) < 8:
        return None

    try:
        decoded_text = decoded_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None

    if any(
        not char.isprintable()
        and char not in "\r\n\t"
        and unicodedata.category(char) != "Cf"
        for char in decoded_text
    ):
        return None

    return decoded_text, len(decoded_bytes)


def iter_decoded_base64_text(source: str) -> Iterator[DecodedBase64Text]:
    """Yield bounded, text-only Base64 candidates from *source*.

    A single pass is made over source candidates; returned decoded text is never
    recursively decoded. Malformed, binary, image, and over-limit values are
    silently skipped.
    """
    if not isinstance(source, str) or not source:
        return

    from ai_guardian.scanners.image_scanner import ImageDetector

    image_spans = iter(ImageDetector.base64_image_payload_spans(source))
    image_span = next(image_spans, None)
    candidates_seen = 0
    candidate_attempts = 0
    decoded_bytes_total = 0

    matches = merge(
        _BASE64_WRAPPED_TOKEN_RE.finditer(source),
        _BASE64_TOKEN_RE.finditer(source),
        key=lambda item: item.start(1),
    )
    accepted_spans: set[tuple[int, int]] = set()
    accepted_end = -1
    for match in matches:
        start, end = match.span(1)
        if start < accepted_end:
            continue
        if (start, end) in accepted_spans:
            continue
        candidate_attempts += 1
        if candidate_attempts > MAX_CANDIDATES * 4:
            break

        while image_span is not None and image_span[1] <= start:
            image_span = next(image_spans, None)
        if image_span is not None and start < image_span[1] and end > image_span[0]:
            continue

        encoded = match.group(1)
        decoded = _decode_candidate(encoded)
        if decoded is None:
            continue
        candidates_seen += 1
        if candidates_seen > MAX_CANDIDATES:
            break
        decoded_text, decoded_size = decoded
        if decoded_bytes_total + decoded_size > MAX_TOTAL_DECODED_BYTES:
            break

        accepted_spans.add((start, end))
        accepted_end = end
        decoded_bytes_total += decoded_size
        yield DecodedBase64Text(
            text=decoded_text,
            encoded=encoded,
            start=start,
            end=end,
        )
