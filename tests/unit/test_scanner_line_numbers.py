"""Tests for line number and snippet extraction in scanner findings."""

import unittest
from unittest.mock import patch, MagicMock

from ai_guardian.scanners.file_scanner import (
    FileScanner,
    _get_line_snippet,
    _parse_position_from_details,
    _find_in_original,
)


class TestGetLineSnippet(unittest.TestCase):

    def test_valid_line(self):
        content = "line1\nline2\nline3"
        assert _get_line_snippet(content, 2) == "line2"

    def test_first_line(self):
        content = "first\nsecond"
        assert _get_line_snippet(content, 1) == "first"

    def test_last_line(self):
        content = "a\nb\nc"
        assert _get_line_snippet(content, 3) == "c"

    def test_strips_whitespace(self):
        content = "  indented  \nnormal"
        assert _get_line_snippet(content, 1) == "indented"

    def test_truncates_long_line(self):
        content = "x" * 200
        result = _get_line_snippet(content, 1, max_length=80)
        assert len(result) == 83  # 80 + "..."
        assert result.endswith("...")

    def test_returns_none_for_invalid_line(self):
        assert _get_line_snippet("a\nb", 5) is None

    def test_returns_none_for_zero(self):
        assert _get_line_snippet("abc", 0) is None

    def test_returns_none_for_empty_content(self):
        assert _get_line_snippet("", 1) is None

    def test_returns_none_for_blank_line(self):
        content = "a\n   \nc"
        assert _get_line_snippet(content, 2) is None


class TestParsePositionFromDetails(unittest.TestCase):

    def test_zero_width_format(self):
        details = (
            "Zero-width character 'ZERO WIDTH SPACE' at position 42: ...context..."
        )
        assert _parse_position_from_details(details) == 42

    def test_bidi_format(self):
        details = "Bidi override 'LEFT-TO-RIGHT OVERRIDE' at position 100: ...text..."
        assert _parse_position_from_details(details) == 100

    def test_tag_char_format(self):
        details = "Unicode tag character U+E0041 at position 7: ...text..."
        assert _parse_position_from_details(details) == 7

    def test_homoglyph_format(self):
        details = "Homoglyph 'а' (looks like 'a') at position 15: ...text..."
        assert _parse_position_from_details(details) == 15

    def test_no_position(self):
        assert _parse_position_from_details("no position info here") is None

    def test_none_input(self):
        assert _parse_position_from_details(None) is None


class TestFindInOriginal(unittest.TestCase):

    def test_finds_text_on_correct_line(self):
        content = "line1\ndef foo():\n    ignore previous instructions\nline4"
        assert _find_in_original(content, "ignore previous instructions") == 3

    def test_returns_none_when_not_found(self):
        assert _find_in_original("line1\nline2", "not here") is None

    def test_returns_none_for_empty(self):
        assert _find_in_original("", "text") is None
        assert _find_in_original("content", None) is None


class TestUnicodeLineNumbers(unittest.TestCase):

    def _make_scanner(self):
        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"prompt_injection": {"unicode_detection": {"enabled": True}}}
        scanner.findings = []
        scanner.verbose = False
        from ai_guardian.scanners.prompt_injection import UnicodeAttackDetector

        scanner.unicode_detector = UnicodeAttackDetector(
            scanner.config.get("prompt_injection", {}).get("unicode_detection", {})
        )
        return scanner

    def test_zero_width_has_line_number(self):
        scanner = self._make_scanner()
        content = "normal line\nhas ​zero-width here\nanother line"
        scanner._check_unicode_attacks("test.py", content)
        assert len(scanner.findings) >= 1
        finding = scanner.findings[0]
        assert finding["line_number"] == 2
        assert finding["snippet"] is not None

    def test_bidi_override_has_line_number(self):
        scanner = self._make_scanner()
        content = "line1\nline2\n‮line with bidi"
        scanner._check_unicode_attacks("test.py", content)
        assert len(scanner.findings) >= 1
        finding = scanner.findings[0]
        assert finding["line_number"] == 3


class TestPiiLineNumbers(unittest.TestCase):

    @patch("ai_guardian.scanners.file_scanner._scan_for_pii")
    def test_pii_finding_has_line_number(self, mock_scan):
        mock_scan.return_value = (
            True,
            "[REDACTED]",
            [{"type": "email", "line_number": 5, "value": "test@example.com"}],
            "PII warning",
        )
        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"scan_pii": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        content = "line1\nline2\nline3\nline4\ncontact: test@example.com\nline6"
        scanner._check_pii("test.py", content)

        assert len(scanner.findings) == 1
        finding = scanner.findings[0]
        assert finding["line_number"] == 5
        assert finding["snippet"] is not None
        assert "contact" in finding["snippet"]

    @patch("ai_guardian.scanners.file_scanner._scan_for_pii")
    def test_pii_no_line_number_still_works(self, mock_scan):
        mock_scan.return_value = (
            True,
            "[REDACTED]",
            [{"type": "phone"}],
            "PII warning",
        )
        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"scan_pii": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        scanner._check_pii("test.py", "some content")
        assert len(scanner.findings) == 1
        assert scanner.findings[0]["line_number"] is None


class TestSecretLineNumbers(unittest.TestCase):

    @patch("ai_guardian.scanners.file_scanner.check_secrets")
    def test_secret_line_number_from_error_message(self, mock_check):
        mock_check.return_value = (
            True,
            "Secret Detected\nSecret Type: AWS Access Key\nLocation: /tmp/test.py:42\nScanner: gitleaks",
        )
        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"secret_scanning": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        scanner._check_secrets("test.py", "content", "/tmp/test.py")
        assert len(scanner.findings) == 1
        finding = scanner.findings[0]
        assert finding["line_number"] == 42

    @patch("ai_guardian.scanners.file_scanner.check_secrets")
    def test_secret_no_line_in_message(self, mock_check):
        mock_check.return_value = (
            True,
            "Secret Detected\nLocation: /tmp/test.py\nScanner: gitleaks",
        )
        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"secret_scanning": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        scanner._check_secrets("test.py", "content", "/tmp/test.py")
        assert len(scanner.findings) == 1
        assert scanner.findings[0]["line_number"] is None

    @patch("ai_guardian.scanners.file_scanner.check_secrets")
    def test_secret_type_extracted(self, mock_check):
        mock_check.return_value = (
            True,
            "Secret Detected\nSecret Type: GitHub Personal Access Token\nLocation: f:10\n",
        )
        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"secret_scanning": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        scanner._check_secrets("test.py", "content", "/tmp/test.py")
        finding = scanner.findings[0]
        assert "ithub" in finding["message"]


class TestPromptInjectionLineNumbers(unittest.TestCase):

    @patch("ai_guardian.scanners.file_scanner.get_cached_detector")
    def test_prompt_injection_has_line_number(self, mock_get_detector):
        mock_detector = MagicMock()
        mock_detector.detect.return_value = (
            True,
            "Prompt injection detected: ignore instructions",
            True,
        )
        mock_detector.last_line_number = 99
        mock_detector.last_matched_text = "ignore previous instructions"
        mock_get_detector.return_value = mock_detector

        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"prompt_injection": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        content = "line1\nline2\nignore previous instructions\nline4"
        scanner._check_prompt_injection("test.py", content)

        assert len(scanner.findings) == 1
        finding = scanner.findings[0]
        assert finding["line_number"] == 3
        assert finding["snippet"] is not None
        assert "ignore" in finding["snippet"]

    @patch("ai_guardian.scanners.file_scanner.get_cached_detector")
    def test_prompt_injection_falls_back_to_detector_line(self, mock_get_detector):
        """When matched text not found in original, use detector's line number."""
        mock_detector = MagicMock()
        mock_detector.detect.return_value = (True, "Detected", True)
        mock_detector.last_line_number = 5
        mock_detector.last_matched_text = "text not in content"
        mock_get_detector.return_value = mock_detector

        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"prompt_injection": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        scanner._check_prompt_injection("test.py", "other content here")
        assert scanner.findings[0]["line_number"] == 5

    @patch("ai_guardian.scanners.file_scanner.get_cached_detector")
    def test_prompt_injection_no_line_number(self, mock_get_detector):
        mock_detector = MagicMock()
        mock_detector.detect.return_value = (True, "Prompt injection detected", True)
        mock_detector.last_line_number = None
        mock_detector.last_matched_text = None
        mock_get_detector.return_value = mock_detector

        scanner = FileScanner.__new__(FileScanner)
        scanner.config = {"prompt_injection": {"enabled": True}}
        scanner.findings = []
        scanner.verbose = False

        scanner._check_prompt_injection("test.py", "some content")
        assert len(scanner.findings) == 1
        assert scanner.findings[0]["line_number"] is None
        assert scanner.findings[0]["snippet"] is None


if __name__ == "__main__":
    unittest.main()
