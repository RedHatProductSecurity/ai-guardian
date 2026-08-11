"""
TOML Patterns Scanner — internal Python-based secret scanner.

Runs in-process (~1-5ms) using pre-compiled patterns from bundled TOML
files. No external binary required. Registered as "toml-patterns" in
the engine preset list alongside gitleaks and betterleaks.

Usage in ai-guardian.json:
    "secret_scanning": {
        "engines": ["toml-patterns", "gitleaks"]
    }
"""

import logging
import os
import re
import sys
from typing import List, Optional

if sys.version_info >= (3, 11):
    pass
else:
    pass

from ai_guardian.patterns import BUNDLED_FILES
from ai_guardian.patterns.cache import PatternCache
from ai_guardian.patterns.validators import load_stopwords
from ai_guardian.scanners.sdk import Finding, Scanner

logger = logging.getLogger(__name__)


class TomlPatternsScanner(Scanner):
    """Internal Python scanner using pre-compiled TOML patterns.

    Scans content for secrets using patterns loaded from bundled TOML
    files. PII detection is handled separately by the PII scanner
    (SecretRedactor with pii_only=True). Optionally loads additional
    patterns from pattern servers (multi-format).
    """

    name = "toml-patterns"
    version = "1.0.0"

    def __init__(self):
        self._cache = PatternCache()
        self._compiled_allowlist: List[re.Pattern] = []
        self._ignore_files: List[str] = []
        self._stopwords: List[str] = []
        self._min_entropy: Optional[float] = 3.0
        toml_paths = []
        for key in ("secrets",):
            path = BUNDLED_FILES.get(key)
            if path and path.exists():
                toml_paths.append(path)
        if toml_paths:
            self._cache.load(*toml_paths)
        self._stopwords = load_stopwords()
        logger.debug(
            f"TomlPatternsScanner: loaded {self._cache.rule_count} rules, "
            f"{len(self._stopwords)} stopwords"
        )

    def configure(self, config: dict) -> None:
        """Accept scanner-specific configuration.

        Supports:
            pattern_servers: list of server configs with 'url' and 'format'
            additional_patterns: list of extra rule dicts
        """
        servers = config.get("pattern_servers", [])
        if not servers and "pattern_server" in config:
            servers = [config["pattern_server"]]

        for server_config in servers:
            self._load_from_server(server_config)

        additional = config.get("additional_patterns", [])
        if additional:
            self._cache.load_rules(additional, category="secrets")

        allowlist_raw = config.get("allowlist_patterns")
        if allowlist_raw:
            from ai_guardian.allowlist_utils import compile_allowlist

            self._compiled_allowlist = compile_allowlist(allowlist_raw)
        else:
            self._compiled_allowlist = []

        self._ignore_files = config.get("ignore_files") or []

        min_entropy = config.get("min_entropy")
        if min_entropy is not None:
            self._min_entropy = float(min_entropy)

        self._stopwords = load_stopwords(config)

    def _load_from_server(self, server_config: dict) -> None:
        """Load patterns from a single pattern server."""
        try:
            from ai_guardian.patterns.server import PatternServerClient
            from ai_guardian.patterns.server_parsers import get_parser

            fmt = server_config.get("format", "gitleaks")
            parser = get_parser(fmt)
            if parser is None:
                logger.warning(f"Unsupported pattern server format: {fmt}")
                return

            client = PatternServerClient(server_config)
            raw_data = client.get_patterns()
            if raw_data:
                rules = parser.parse(raw_data)
                if rules:
                    self._cache.load_rules(rules, category="secrets")
                    logger.debug(
                        f"TomlPatternsScanner: loaded {len(rules)} rules from server ({fmt})"
                    )
        except Exception as e:
            logger.warning(f"TomlPatternsScanner: failed to load from server: {e}")

    def scan(self, content: str, file_path: str = None) -> List[Finding]:
        """Scan content for secrets using compiled TOML patterns.

        Args:
            content: Text content to scan
            file_path: Optional source file path (for context)

        Returns:
            List of Finding objects
        """
        if file_path and self._ignore_files:
            from ai_guardian.utils.path_matching import matches_ignore_files

            if matches_ignore_files(file_path, self._ignore_files):
                return []

        file_ext = None
        if file_path:
            file_ext = os.path.splitext(file_path)[1].lower() or None
        raw_findings = self._cache.scan(
            content, categories=["secrets"], file_ext=file_ext
        )
        findings = []
        for f in raw_findings:
            if self._stopwords and f.category == "secrets":
                matched_lower = f.matched_text.lower()
                if any(sw in matched_lower for sw in self._stopwords):
                    continue
            if self._min_entropy is not None and f.category == "secrets":
                from ai_guardian.patterns.validators import shannon_entropy

                if shannon_entropy(f.matched_text) < self._min_entropy:
                    continue
            start_col = None
            end_col = None
            end_line = None
            if f.match_start is not None:
                line_start = content.rfind("\n", 0, f.match_start) + 1
                start_col = f.match_start - line_start
            if f.match_end is not None and f.match_end > 0:
                end_line_start = content.rfind("\n", 0, f.match_end) + 1
                end_col = f.match_end - end_line_start
                if f.match_start is not None and end_line_start != line_start:
                    end_line = content[: f.match_end].count("\n") + 1
            findings.append(
                Finding(
                    rule_id=f.rule_id,
                    line_number=f.line_number,
                    matched_text=f.matched_text,
                    description=f.description or f.rule_id,
                    severity="warning",
                    end_line=end_line,
                    start_column=start_col,
                    end_column=end_col,
                    category=f.category,
                )
            )

        if findings and self._compiled_allowlist:
            from ai_guardian.allowlist_utils import check_allowlist

            content_lines = content.splitlines()
            filtered = []
            for f in findings:
                line_idx = f.line_number - 1
                if 0 <= line_idx < len(content_lines):
                    if check_allowlist(
                        content_lines[line_idx], self._compiled_allowlist
                    ):
                        continue
                filtered.append(f)
            findings = filtered

        return findings
