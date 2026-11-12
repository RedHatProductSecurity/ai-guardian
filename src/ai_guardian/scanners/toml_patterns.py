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
from typing import Any, List, Optional, Set, Tuple

from ai_guardian.patterns import BUNDLED_FILES
from ai_guardian.patterns.cache import PatternCache
from ai_guardian.patterns.validators import load_stopwords
from ai_guardian.scanners.sdk import Finding, Scanner

logger = logging.getLogger(__name__)

_CUSTOM_SECRET_RULE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CUSTOM_SECRET_RULE_FIELDS = {
    "id",
    "match_type",
    "regex",
    "description",
    "keywords",
    "flags",
}


def validate_custom_secret_patterns(
    patterns: Any, existing_rule_ids: Optional[Set[str]] = None
) -> Tuple[List[dict], List[str]]:
    """Validate user-managed regex rules for the built-in secret scanner.

    Returns valid rules and value-free diagnostics. The Console and runtime use
    this validation; the JSON schema mirrors its structural constraints so
    malformed rules cannot reach the scanner or leak regex contents in diagnostics.
    """
    if not isinstance(patterns, list):
        return [], [
            "secret_scanning.additional_patterns must be an array; custom rules were ignored"
        ]

    valid_rules: List[dict] = []
    errors: List[str] = []
    seen_ids = set(existing_rule_ids or ())

    for index, raw_rule in enumerate(patterns):
        location = f"secret_scanning.additional_patterns[{index}]"
        rule_errors: List[str] = []
        if not isinstance(raw_rule, dict):
            errors.append(f"{location} must be an object; this rule was ignored")
            continue

        unknown_fields = any(
            not isinstance(field, str) or field not in _CUSTOM_SECRET_RULE_FIELDS
            for field in raw_rule
        )
        if unknown_fields:
            rule_errors.append(
                "contains unsupported fields; supported fields are id, match_type, "
                "regex, description, keywords, and flags"
            )

        rule_id = raw_rule.get("id")
        if not isinstance(rule_id, str) or not _CUSTOM_SECRET_RULE_ID.fullmatch(
            rule_id
        ):
            rule_errors.append(
                "id must start with a letter or digit and contain only letters, "
                "digits, '.', '_' or '-' (maximum 128 characters)"
            )
        else:
            location += f" ({rule_id})"
            if rule_id in seen_ids:
                rule_errors.append("id must be unique among bundled and custom rules")

        if raw_rule.get("match_type") != "regex":
            rule_errors.append("match_type must be 'regex'")

        regex = raw_rule.get("regex")
        if not isinstance(regex, str) or not regex:
            rule_errors.append("regex must be a non-empty string")

        description = raw_rule.get("description")
        if "description" in raw_rule and not isinstance(description, str):
            rule_errors.append("description must be a string")

        keywords = raw_rule.get("keywords")
        if "keywords" in raw_rule and (
            not isinstance(keywords, list)
            or any(not isinstance(keyword, str) or not keyword for keyword in keywords)
        ):
            rule_errors.append("keywords must be an array of non-empty strings")

        flags = raw_rule.get("flags", "")
        if not isinstance(flags, str) or re.fullmatch(r"[ims]*", flags) is None:
            rule_errors.append("flags may contain only 'i', 'm' and 's'")
            flags = ""

        if isinstance(regex, str) and regex:
            regex_flags = 0
            if "i" in flags:
                regex_flags |= re.IGNORECASE
            if "m" in flags:
                regex_flags |= re.MULTILINE
            if "s" in flags:
                regex_flags |= re.DOTALL
            try:
                re.compile(regex, regex_flags)
            except re.error as exc:
                position = getattr(exc, "pos", None)
                suffix = f" at position {position}" if position is not None else ""
                rule_errors.append(
                    f"regex is invalid{suffix}; correct the regex syntax"
                )
            else:
                from ai_guardian.patterns.toml_parser import validate_re2_compatible

                compatible, reason = validate_re2_compatible(regex)
                if not compatible:
                    rule_errors.append(f"regex uses unsupported syntax: {reason}")

        if rule_errors:
            errors.extend(
                f"{location}: {message}; this rule was ignored"
                for message in rule_errors
            )
            continue

        valid_rules.append(
            {
                field: value
                for field, value in raw_rule.items()
                if field in _CUSTOM_SECRET_RULE_FIELDS
            }
        )
        if isinstance(rule_id, str):
            seen_ids.add(rule_id)

    return valid_rules, errors


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

        if "additional_patterns" in config:
            existing_rule_ids = {
                rule.id for rule in self._cache.get_rules(category="secrets")
            }
            additional, errors = validate_custom_secret_patterns(
                config["additional_patterns"], existing_rule_ids
            )
            if errors:
                logger.warning(
                    "Invalid custom secret detection rules were skipped. Check "
                    "secret_scanning.additional_patterns in the Console or config."
                )
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

    def scan(self, content: str, file_path: Optional[str] = None) -> List[Finding]:
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
        findings: List[Finding] = []
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
            filtered: List[Finding] = []
            for finding in findings:
                line_idx = finding.line_number - 1
                if 0 <= line_idx < len(content_lines):
                    if check_allowlist(
                        content_lines[line_idx], self._compiled_allowlist
                    ):
                        continue
                filtered.append(finding)
            findings = filtered

        return findings
