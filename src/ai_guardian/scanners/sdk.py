"""
Custom Scanner SDK for ai-guardian.

Provides base classes for writing Python-based scanners that run in-process
alongside subprocess-based engines (gitleaks, betterleaks, etc.).

Usage:
    from ai_guardian.scanners.sdk import Scanner, Finding

    class MyScanner(Scanner):
        name = "my-scanner"
        version = "1.0.0"

        def scan(self, content: str, file_path: str | None = None) -> list[Finding]:
            findings = []
            for i, line in enumerate(content.splitlines(), 1):
                if "secret-pattern" in line:
                    findings.append(Finding(
                        rule_id="my-rule",
                        line_number=i,
                        matched_text=line.strip(),
                        description="Found secret pattern",
                    ))
            return findings
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Finding:
    """A single finding from a Python scanner.

    Attributes:
        rule_id: Identifier for the detection rule (e.g., "internal-api-exposure")
        line_number: Line number where the finding was detected (1-based)
        matched_text: The text that triggered the finding
        description: Human-readable description of the finding
        severity: Severity level — "critical", "warning", or "info"
        end_line: Optional ending line number for multi-line findings
        commit: Optional git commit hash (for git-aware scanners)
        category: Pattern category (e.g., "secrets", "pii") for violation routing
    """

    rule_id: str
    line_number: int
    matched_text: str
    description: str
    severity: str = "warning"
    end_line: Optional[int] = None
    start_column: Optional[int] = None  # 0-based column, None if unavailable
    end_column: Optional[int] = None  # 0-based column, None if unavailable
    commit: Optional[str] = None
    category: Optional[str] = None


class Scanner(ABC):
    """Base class for custom Python-based scanners.

    Subclass this to create a scanner that runs in-process alongside
    subprocess-based engines. Python scanners are faster (~1ms vs ~50ms)
    and require no binary installation.

    Class attributes:
        name: Short identifier for this scanner (used in logs and config)
        version: Semantic version string
    """

    name: str = "custom"
    version: str = "0.0.0"

    @abstractmethod
    def scan(self, content: str, file_path: Optional[str] = None) -> List[Finding]:
        """Scan content and return findings.

        Args:
            content: Text content to scan
            file_path: Optional source file path for context

        Returns:
            List of Finding objects (empty list means no issues found)
        """
        pass

    def configure(self, config: dict) -> None:
        """Receive scanner-specific configuration from ai-guardian.json.

        Override this to accept custom configuration. Called once after
        the scanner is instantiated and before the first scan.

        Args:
            config: Scanner-specific configuration dict
        """
        pass
