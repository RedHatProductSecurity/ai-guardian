"""Tests for transcript scanner allowed-findings dedup (#1364).

Verifies that findings allowed via the ask dialog are not re-alerted
by the transcript scanner.
"""

import hashlib
import json
import os
from unittest import mock

import pytest


def _finding_fingerprint(finding_type, detail):
    """Mirror of hook_processing._finding_fingerprint for test assertions."""
    return hashlib.sha256(f"{finding_type}:{detail}".encode()).hexdigest()[:16]


class TestScanTranscriptTextAllowedFindings:
    """Tests for allowed_findings filtering in _scan_transcript_text."""

    def test_allowed_secret_skipped(self, tmp_path):
        """Secret fingerprint in allowed set should not produce a warning."""
        from ai_guardian.scanners.transcript import _scan_transcript_text

        # ai-guardian:begin-allow
        content = "my secret key is AKIAIOSFODNN7EXAMPLE and it works"
        # ai-guardian:end-allow

        rule_id = "aws-access-token"
        fp = _finding_fingerprint("secret", rule_id)
        allowed = {fp}

        with mock.patch(
            "ai_guardian.scanners.transcript.common.check_secrets"
        ) as mock_scan:
            mock_scan.return_value = (
                True,
                f"Secret detected\nSecret Type: {rule_id}\n",
            )
            with mock.patch(
                "ai_guardian.scanners.transcript.common._load_seen_findings",
                return_value={},
            ):
                with mock.patch(
                    "ai_guardian.scanners.transcript.common._save_seen_findings"
                ):
                    warnings = _scan_transcript_text(
                        content,
                        "/tmp/test_transcript.jsonl",
                        secret_config={"enabled": True},
                        allowed_findings=allowed,
                    )

        assert len(warnings) == 0

    def test_non_allowed_secret_reported(self, tmp_path):
        """Secret NOT in allowed set should produce a warning."""
        from ai_guardian.scanners.transcript import _scan_transcript_text

        # ai-guardian:begin-allow
        content = "my secret key is AKIAIOSFODNN7EXAMPLE and it works"
        # ai-guardian:end-allow

        with mock.patch(
            "ai_guardian.scanners.transcript.common.check_secrets"
        ) as mock_scan:
            mock_scan.return_value = (
                True,
                "Secret detected\nSecret Type: aws-access-token\n",
            )
            with mock.patch(
                "ai_guardian.scanners.transcript.common._load_seen_findings",
                return_value={},
            ):
                with mock.patch(
                    "ai_guardian.scanners.transcript.common._save_seen_findings"
                ):
                    warnings = _scan_transcript_text(
                        content,
                        "/tmp/test_transcript.jsonl",
                        secret_config={"enabled": True},
                        allowed_findings=None,
                    )

        assert len(warnings) == 1
        assert "SECRET DETECTED" in warnings[0]

    def test_allowed_pii_skipped(self):
        """PII fingerprint in allowed set should not produce a warning."""
        from ai_guardian.scanners.transcript import _scan_transcript_text

        pii_type = "SSN"
        # ai-guardian:begin-allow
        pii_value = "078-05-1120"
        # ai-guardian:end-allow
        fp = _finding_fingerprint("pii", f"{pii_type}:{pii_value}")
        allowed = {fp}

        mock_redactions = [
            {"type": pii_type, "position": 0, "original_length": len(pii_value)}
        ]

        with mock.patch(
            "ai_guardian.scanners.transcript.common.check_secrets",
            return_value=(False, None),
        ):
            with mock.patch("ai_guardian.hook_processing._scan_for_pii") as mock_pii:
                mock_pii.return_value = (True, "***", mock_redactions, "PII found")
                with mock.patch(
                    "ai_guardian.scanners.transcript.common._load_seen_findings",
                    return_value={},
                ):
                    with mock.patch(
                        "ai_guardian.scanners.transcript.common._save_seen_findings"
                    ):
                        warnings = _scan_transcript_text(
                            pii_value + " some other text",
                            "/tmp/test.jsonl",
                            pii_config={"enabled": True},
                            allowed_findings=allowed,
                        )

        assert len(warnings) == 0

    def test_multiple_secrets_produce_summary_warning(self):
        """Multiple per-findings produce one warning with count and types."""
        from ai_guardian.scanners.transcript import _scan_transcript_text
        from ai_guardian.scanners.scan_result import ScanResult

        mock_findings = [
            ScanResult(
                detected=True,
                violation_type="secret_detected",
                rule_id="aws-access-token",
            ),
            ScanResult(
                detected=True, violation_type="secret_detected", rule_id="github-pat"
            ),
        ]

        with mock.patch(
            "ai_guardian.scanners.transcript.common.check_secrets"
        ) as mock_scan:
            mock_scan.return_value = (True, "Secret Type: aws-access-token")
            with mock.patch(
                "ai_guardian.scanners.secret_scanning._last_secret_findings",
                mock_findings,
            ):
                with mock.patch(
                    "ai_guardian.scanners.transcript.common._load_seen_findings",
                    return_value={},
                ):
                    with mock.patch(
                        "ai_guardian.scanners.transcript.common._save_seen_findings"
                    ):
                        warnings = _scan_transcript_text(
                            "content",
                            "/tmp/test.jsonl",
                            secret_config={"enabled": True},
                            allowed_findings=None,
                        )

        assert len(warnings) == 1
        assert "2 SECRETS" in warnings[0]
        assert "aws-access-token" in warnings[0]
        assert "github-pat" in warnings[0]

    def test_multiple_secrets_all_allowed(self):
        """All per-findings allowed → no warning."""
        from ai_guardian.scanners.transcript import _scan_transcript_text
        from ai_guardian.scanners.scan_result import ScanResult

        mock_findings = [
            ScanResult(
                detected=True,
                violation_type="secret_detected",
                rule_id="aws-access-token",
            ),
            ScanResult(
                detected=True, violation_type="secret_detected", rule_id="github-pat"
            ),
        ]
        fp1 = _finding_fingerprint("secret", "aws-access-token")
        fp2 = _finding_fingerprint("secret", "github-pat")

        with mock.patch(
            "ai_guardian.scanners.transcript.common.check_secrets"
        ) as mock_scan:
            mock_scan.return_value = (True, "Secret Type: aws-access-token")
            with mock.patch(
                "ai_guardian.scanners.secret_scanning._last_secret_findings",
                mock_findings,
            ):
                with mock.patch(
                    "ai_guardian.scanners.transcript.common._load_seen_findings",
                    return_value={},
                ):
                    with mock.patch(
                        "ai_guardian.scanners.transcript.common._save_seen_findings"
                    ):
                        warnings = _scan_transcript_text(
                            "content",
                            "/tmp/test.jsonl",
                            secret_config={"enabled": True},
                            allowed_findings={fp1, fp2},
                        )

        assert len(warnings) == 0

    def test_multiple_secrets_partial_allowed(self):
        """Only non-allowed secrets appear in warning."""
        from ai_guardian.scanners.transcript import _scan_transcript_text
        from ai_guardian.scanners.scan_result import ScanResult

        mock_findings = [
            ScanResult(
                detected=True,
                violation_type="secret_detected",
                rule_id="aws-access-token",
            ),
            ScanResult(
                detected=True, violation_type="secret_detected", rule_id="github-pat"
            ),
        ]
        fp1 = _finding_fingerprint("secret", "aws-access-token")

        with mock.patch(
            "ai_guardian.scanners.transcript.common.check_secrets"
        ) as mock_scan:
            mock_scan.return_value = (True, "Secret Type: aws-access-token")
            with mock.patch(
                "ai_guardian.scanners.secret_scanning._last_secret_findings",
                mock_findings,
            ):
                with mock.patch(
                    "ai_guardian.scanners.transcript.common._load_seen_findings",
                    return_value={},
                ):
                    with mock.patch(
                        "ai_guardian.scanners.transcript.common._save_seen_findings"
                    ):
                        warnings = _scan_transcript_text(
                            "content",
                            "/tmp/test.jsonl",
                            secret_config={"enabled": True},
                            allowed_findings={fp1},
                        )

        assert len(warnings) == 1
        assert "1 SECRET" in warnings[0]
        assert "github-pat" in warnings[0]
        assert "aws-access-token" not in warnings[0]

    def test_none_allowed_findings_backward_compat(self):
        """allowed_findings=None should work (backward compat)."""
        from ai_guardian.scanners.transcript import _scan_transcript_text

        with mock.patch(
            "ai_guardian.scanners.transcript.common.check_secrets",
            return_value=(False, None),
        ):
            with mock.patch(
                "ai_guardian.scanners.transcript.common._load_seen_findings",
                return_value={},
            ):
                with mock.patch(
                    "ai_guardian.scanners.transcript.common._save_seen_findings"
                ):
                    warnings = _scan_transcript_text(
                        "clean content",
                        "/tmp/test.jsonl",
                        allowed_findings=None,
                    )

        assert warnings == []


class TestRecordAllowedForTranscript:
    """Tests for _record_allowed_for_transcript helper (#1439: uses plain set)."""

    def test_secret_fingerprint_recorded(self):
        from ai_guardian.ask_mode import _record_allowed_for_transcript
        from ai_guardian.hook_processing import ViolationType

        result_set = set()
        _record_allowed_for_transcript(
            result_set,
            ViolationType.SECRET_DETECTED,
            "Secret detected\nSecret Type: aws-access-token\n",
            "AKIAIOSFODNN7EXAMPLE",
        )

        expected_fp = _finding_fingerprint("secret", "aws-access-token")
        assert expected_fp in result_set

    def test_pii_fingerprints_recorded(self):
        from ai_guardian.ask_mode import _record_allowed_for_transcript
        from ai_guardian.hook_processing import ViolationType

        # ai-guardian:begin-allow
        pii_value = "078-05-1120"
        # ai-guardian:end-allow
        fp = _finding_fingerprint("pii", f"SSN:{pii_value}")

        result_set = set()
        _record_allowed_for_transcript(
            result_set,
            ViolationType.PII_DETECTED,
            "PII found",
            pii_value,
            finding_fingerprints=[fp],
        )

        assert fp in result_set

    def test_unknown_secret_type_not_recorded(self):
        from ai_guardian.ask_mode import _record_allowed_for_transcript
        from ai_guardian.hook_processing import ViolationType

        result_set = set()
        _record_allowed_for_transcript(
            result_set,
            ViolationType.SECRET_DETECTED,
            "no secret type info here",
            "some_value",
        )

        assert result_set == set()

    def test_non_secret_violation_type_noop(self):
        from ai_guardian.ask_mode import _record_allowed_for_transcript
        from ai_guardian.hook_processing import ViolationType

        result_set = set()
        _record_allowed_for_transcript(
            result_set,
            ViolationType.PROMPT_INJECTION,
            "some error",
            "some text",
        )

        assert result_set == set()


class TestComputePiiTranscriptFingerprints:
    """Tests for _compute_pii_transcript_fingerprints helper."""

    def test_computes_from_redactions(self):
        from ai_guardian.ask_mode import _compute_pii_transcript_fingerprints

        # ai-guardian:begin-allow
        content = "SSN is 078-05-1120 and email is test@example.com"
        # ai-guardian:end-allow
        redactions = [
            {"type": "SSN", "position": 7, "original_length": 11},
            {"type": "EMAIL", "position": 32, "original_length": 16},
        ]

        fps = _compute_pii_transcript_fingerprints(redactions, content)

        assert len(fps) == 2
        assert fps[0] == _finding_fingerprint("pii", "SSN:078-05-1120")
        assert fps[1] == _finding_fingerprint("pii", "EMAIL:test@example.com")

    def test_empty_redactions(self):
        from ai_guardian.ask_mode import _compute_pii_transcript_fingerprints

        fps = _compute_pii_transcript_fingerprints([], "some content")
        assert fps == []

    def test_none_redactions(self):
        from ai_guardian.ask_mode import _compute_pii_transcript_fingerprints

        fps = _compute_pii_transcript_fingerprints(None, "some content")
        assert fps == []


class TestLogAskDecisionAllowedFindings:
    """Tests for _log_ask_decision recording to invocation_allowed_findings set (#1439)."""

    def test_allow_once_records_finding(self):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.hook_processing import ViolationType
        from ai_guardian.tui.ask_dialog import AskDecision

        allowed_set = set()
        with mock.patch("ai_guardian.ask_mode.HAS_VIOLATION_LOGGER", True):
            with mock.patch("ai_guardian.ask_mode.ViolationLogger"):
                _log_ask_decision(
                    ViolationType.SECRET_DETECTED,
                    AskDecision.ALLOW_ONCE,
                    matched_text="AKIAIOSFODNN7EXAMPLE",
                    error_msg="Secret Type: aws-access-token",
                    invocation_allowed_findings=allowed_set,
                )

        expected_fp = _finding_fingerprint("secret", "aws-access-token")
        assert expected_fp in allowed_set

    def test_block_does_not_record(self):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.hook_processing import ViolationType
        from ai_guardian.tui.ask_dialog import AskDecision

        allowed_set = set()
        with mock.patch("ai_guardian.ask_mode.HAS_VIOLATION_LOGGER", True):
            with mock.patch("ai_guardian.ask_mode.ViolationLogger"):
                _log_ask_decision(
                    ViolationType.SECRET_DETECTED,
                    AskDecision.BLOCK,
                    matched_text="AKIAIOSFODNN7EXAMPLE",
                    error_msg="Secret Type: aws-access-token",
                    invocation_allowed_findings=allowed_set,
                )

        assert allowed_set == set()

    def test_no_invocation_set_noop(self):
        """Without invocation_allowed_findings, allow decisions log without error."""
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.hook_processing import ViolationType
        from ai_guardian.tui.ask_dialog import AskDecision

        with mock.patch("ai_guardian.ask_mode.HAS_VIOLATION_LOGGER", True):
            with mock.patch("ai_guardian.ask_mode.ViolationLogger"):
                _log_ask_decision(
                    ViolationType.SECRET_DETECTED,
                    AskDecision.ALLOW_ONCE,
                    matched_text="AKIAIOSFODNN7EXAMPLE",
                    error_msg="Secret Type: aws-access-token",
                )
