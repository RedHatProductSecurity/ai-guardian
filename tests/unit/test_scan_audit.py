"""Tests for scan audit logging."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_guardian.scanners.audit import ScanAuditLogger
from ai_guardian.scanners.strategies import ScanResult, SecretMatch


class TestScanAuditLogger(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.log_path = Path(self.tmp.name) / "audit.jsonl"
        self.logger = ScanAuditLogger(log_path=self.log_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _sample_result(self, has_secrets=False):
        secrets = []
        if has_secrets:
            secrets.append(
                SecretMatch(
                    rule_id="test-key",
                    description="Test key",
                    file="test.py",
                    line_number=1,
                    engine="gitleaks",
                )
            )
        return ScanResult(
            has_secrets=has_secrets,
            secrets=secrets,
            engine="gitleaks",
            scan_time_ms=50.0,
        )

    def test_log_scan_creates_entry(self):
        self.logger.log_scan(self._sample_result(), "test.py")
        entries = self.logger.get_recent_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event"], "scan_completed")
        self.assertEqual(entries[0]["engine"], "gitleaks")
        self.assertEqual(entries[0]["filename"], "test.py")
        self.assertEqual(entries[0]["policy_decision"]["decision"], "allow")
        self.assertEqual(entries[0]["policy_decision"]["event"], "scan_completed")

    def test_log_engine_failure(self):
        self.logger.log_engine_failure("trufflehog", "binary not found", "test.py")
        entries = self.logger.get_recent_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event"], "engine_failure")

    def test_disabled_does_not_write(self):
        logger = ScanAuditLogger(log_path=self.log_path, enabled=False)
        logger.log_scan(self._sample_result(), "test.py")
        self.assertFalse(self.log_path.exists())

    def test_get_recent_entries_limits(self):
        for i in range(10):
            self.logger.log_scan(self._sample_result(), f"file{i}.py")
        entries = self.logger.get_recent_entries(limit=3)
        self.assertEqual(len(entries), 3)

    def test_engine_filter(self):
        r1 = ScanResult(
            has_secrets=False, secrets=[], engine="gitleaks", scan_time_ms=10
        )
        r2 = ScanResult(
            has_secrets=False, secrets=[], engine="trufflehog", scan_time_ms=20
        )
        self.logger.log_scan(r1, "a.py")
        self.logger.log_scan(r2, "b.py")
        entries = self.logger.get_recent_entries(engine_filter="gitleaks")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["engine"], "gitleaks")

    def test_handles_corrupt_entries(self):
        with open(self.log_path, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"event": "test", "engine": "x"}) + "\n")
        entries = self.logger.get_recent_entries()
        self.assertEqual(len(entries), 1)

    def test_scan_with_context(self):
        self.logger.log_scan(
            self._sample_result(),
            "test.py",
            strategy="any-match",
            context={"ide_type": "claude-code"},
        )
        entries = self.logger.get_recent_entries()
        self.assertEqual(entries[0]["strategy"], "any-match")
        self.assertEqual(entries[0]["context"]["ide_type"], "claude-code")
        self.assertEqual(entries[0]["policy_decision"]["agent"], "claude-code")


if __name__ == "__main__":
    unittest.main()
