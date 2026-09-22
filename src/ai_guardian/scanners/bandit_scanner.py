"""Bandit Python code security scanner for AI Guardian.

Scans Python source code for insecure patterns:
eval/exec, subprocess shell injection, weak crypto, SQL injection, etc.
"""

import importlib.util
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

from ai_guardian.scanners.code_inspection import (
    CodeInspectionFinding,
    CodeInspector,
    CodeInspectorUnavailableError,
    SEVERITY_ORDER,
)

logger = logging.getLogger(__name__)


class BanditUnavailableError(CodeInspectorUnavailableError):
    """Raised when bandit is not importable in the current environment."""


_SEVERITY_ORDER = SEVERITY_ORDER
CodeSecurityFinding = CodeInspectionFinding


class BanditScanner(CodeInspector):
    """Python code security scanner using Bandit."""

    name = "bandit"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        raw_threshold = str(self.config.get("severity_threshold", "MEDIUM"))
        self._threshold = _SEVERITY_ORDER.get(raw_threshold.upper(), 1)
        self._allowlist: List[Dict[str, Any]] = self.config.get("allowlist", []) or []
        self._available: bool = importlib.util.find_spec("bandit") is not None

    @property
    def available(self) -> bool:
        return self._available

    def scan(
        self, content: str, file_path: str = "unknown.py"
    ) -> List[CodeInspectionFinding]:
        """Scan Python source code for security issues.

        Writes content to a temp file, runs Bandit in-process, then applies
        severity threshold and allowlist filters.

        # nosec / # nosec B101 inline comments in source are honored natively
        by Bandit and those findings never surface.

        Args:
            content: Python source code to scan
            file_path: Original file path for finding attribution

        Returns:
            List of CodeSecurityFinding at or above the severity threshold,
            minus allowlist-suppressed entries.
        """
        if not content.strip():
            return []

        if not self._available:
            raise BanditUnavailableError("No module named 'bandit'")

        try:
            findings = self._run_bandit(content, file_path)
        except Exception as e:
            logger.warning("Bandit scan failed for %s: %s", file_path, e)
            return []

        return [f for f in findings if not self._is_allowlisted(f, file_path)]

    def _run_bandit(self, content: str, file_path: str) -> List[CodeInspectionFinding]:
        from bandit.core import config as b_config
        from bandit.core import manager as b_manager

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="ai-guardian-bandit-")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)

            conf = b_config.BanditConfig()
            mgr = b_manager.BanditManager(
                conf,
                agg_type="file",
                debug=False,
                verbose=False,
                profile=None,
                ignore_nosec=False,
            )
            mgr.discover_files([tmp_path], False)
            mgr.run_tests()

            lines = content.splitlines()
            findings = []
            for issue in mgr.results:
                sev = (issue.severity or "MEDIUM").upper()
                if _SEVERITY_ORDER.get(sev, 0) < self._threshold:
                    continue

                test_id = getattr(issue, "test_id", "") or ""
                if test_id and not test_id.startswith("B"):
                    test_id = f"B{test_id}"
                rule_id = test_id or "BANDIT"

                lineno = getattr(issue, "lineno", 0) or 0
                col = getattr(issue, "col_offset", None)
                confidence = (getattr(issue, "confidence", None) or "MEDIUM").upper()

                snippet = None
                if lineno and 1 <= lineno <= len(lines):
                    line_text = lines[lineno - 1]
                    # Honor inline ai-guardian:allow annotation
                    if "ai-guardian:allow" in line_text:
                        continue
                    snippet = line_text.strip()[:120]

                findings.append(
                    CodeSecurityFinding(
                        rule_id=rule_id,
                        description=issue.text or "Insecure code pattern detected",
                        line_number=lineno,
                        end_line=None,
                        start_column=col,
                        severity=sev,
                        confidence=confidence,
                        file_path=file_path,
                        snippet=snippet,
                        inspector=self.name,
                    )
                )
            return findings
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _is_allowlisted(self, finding: CodeInspectionFinding, file_path: str) -> bool:
        """Check if finding matches any allowlist entry.

        Allowlist entry format:
            {"test_id": "B101", "file": "tests/", "reason": "..."}

        `test_id` is required; `file` is an optional path prefix filter.
        """
        for entry in self._allowlist:
            entry_test_id = entry.get("test_id", "")
            if entry_test_id and entry_test_id != finding.rule_id:
                continue
            entry_file = entry.get("file", "")
            if entry_file and not file_path.startswith(entry_file):
                continue
            return True
        return False


# Keep the historical scanner name while exposing the generic inspector term.
BanditInspector = BanditScanner
