"""
PatternCache — pre-compiled pattern store for detection and redaction.

Holds compiled match objects in memory. Parse once, compile once, reuse
on every hook call. Recompile only on config reload, pattern server
refresh, or daemon restart.

Used by detection (PreToolUse), redaction (PostToolUse), and prompt
scanning (UserPromptSubmit) through a single shared cache.
"""

import ipaddress
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_guardian.patterns.toml_parser import (
    CompiledRule,
    compile_rule,
    load_and_compile,
)
from ai_guardian.patterns.validators import get_validator

logger = logging.getLogger(__name__)


@dataclass
class ScanFinding:
    """A single finding from scanning content against compiled patterns."""

    rule_id: str
    line_number: int
    matched_text: str
    description: str
    category: str
    match_start: int = 0
    match_end: int = 0
    metadata: dict = field(default_factory=dict)


class PatternCache:
    """Pre-compiled pattern cache for detection, redaction, and prompt scanning.

    Loads patterns from TOML files and/or raw rule dicts, compiles them
    into Python objects, and provides scan/redact operations.

    _IP_PATTERN: Pre-compiled regex for extracting IPv4 addresses in CIDR scanning.

    Usage::

        cache = PatternCache()
        cache.load(Path("patterns/secrets.toml"), Path("patterns/pii.toml"))
        findings = cache.scan("text with sk-abc123xyz...", categories=["secret"])
        result = cache.redact("text with sk-abc123xyz...", categories=["secret"])
    """

    _IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

    def __init__(self):
        self._rules: List[CompiledRule] = []
        self._rules_by_category: Dict[str, List[CompiledRule]] = {}
        self._literal_maps: Dict[str, Dict[str, str]] = {}
        self.loaded_at: Optional[float] = None

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def load(
        self,
        *toml_paths: Path,
        additional_rules: Optional[List[dict]] = None,
        category_override: Optional[str] = None,
    ) -> None:
        """Parse TOML files and compile all rules into memory.

        Args:
            toml_paths: Paths to TOML pattern files
            additional_rules: Extra rule dicts to compile (e.g., from config)
            category_override: If set, override the category for all loaded rules
        """
        self._rules.clear()
        self._rules_by_category.clear()
        self._literal_maps.clear()

        for path in toml_paths:
            category = category_override or path.stem.replace("-", "_")
            try:
                compiled = load_and_compile(path, category)
                self._rules.extend(compiled)
            except (FileNotFoundError, ValueError) as e:
                logger.error(f"Failed to load pattern file {path}: {e}")

        if additional_rules:
            cat = category_override or "custom"
            for raw in additional_rules:
                try:
                    rule = compile_rule(raw, raw.get("category", cat))
                    self._rules.append(rule)
                except ValueError as e:
                    logger.warning(f"Skipping invalid additional rule: {e}")

        self._rebuild_indices()
        self.loaded_at = time.time()
        if toml_paths and not self._rules:
            logger.warning(
                "PatternCache: loaded 0 rules from %d file(s) — scanning will find nothing",
                len(toml_paths),
            )
        logger.debug(
            f"PatternCache loaded: {len(self._rules)} rules across "
            f"{len(self._rules_by_category)} categories"
        )

    def load_rules(self, rules: List[dict], category: str = "custom") -> None:
        """Add pre-parsed rule dicts to the cache without clearing existing rules.

        Args:
            rules: List of raw rule dicts (e.g., from a pattern server parser)
            category: Default category for rules missing a category field
        """
        for raw in rules:
            try:
                rule = compile_rule(raw, raw.get("category", category))
                self._rules.append(rule)
            except ValueError as e:
                logger.warning(f"Skipping invalid rule: {e}")
        self._rebuild_indices()
        self.loaded_at = time.time()

    def _rebuild_indices(self) -> None:
        """Rebuild category index and literal lookup maps."""
        self._rules_by_category.clear()
        self._literal_maps.clear()

        for rule in self._rules:
            cat = rule.category
            if cat not in self._rules_by_category:
                self._rules_by_category[cat] = []
            self._rules_by_category[cat].append(rule)

            if rule.match_type == "literal":
                if cat not in self._literal_maps:
                    self._literal_maps[cat] = {}
                source, target = rule.compiled
                self._literal_maps[cat][source] = target

    def get_rules(self, category: Optional[str] = None) -> List[CompiledRule]:
        """Get compiled rules, optionally filtered by category.

        Args:
            category: If specified, return only rules for this category

        Returns:
            List of CompiledRule objects
        """
        if category is None:
            return list(self._rules)
        return list(self._rules_by_category.get(category, []))

    def get_categories(self) -> List[str]:
        """Return list of loaded category names."""
        return list(self._rules_by_category.keys())

    def scan(
        self,
        content: str,
        categories: Optional[List[str]] = None,
        file_ext: Optional[str] = None,
    ) -> List[ScanFinding]:
        """Scan content against compiled patterns.

        Args:
            content: Text content to scan
            categories: If specified, only scan these categories
            file_ext: Lowercase file extension (e.g. ".py"). When set,
                rules whose ``skip_file_types`` metadata contains this
                extension are skipped.

        Returns:
            List of ScanFinding objects for matches found
        """
        if not content or not self._rules:
            return []

        findings = []
        rules = self._get_filtered_rules(categories)

        for rule in rules:
            if file_ext:
                skip_exts = rule.metadata.get("skip_file_types")
                if skip_exts and file_ext in skip_exts:
                    continue

            if rule.match_type == "regex":
                findings.extend(self._scan_regex(content, rule))
            elif rule.match_type == "literal":
                findings.extend(self._scan_literal(content, rule))
            elif rule.match_type == "cidr":
                findings.extend(self._scan_cidr(content, rule))
            elif rule.match_type == "range":
                findings.extend(self._scan_range(content, rule))

        return findings

    def redact(
        self, content: str, categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Scan content and apply redaction based on rule strategies.

        Args:
            content: Text content to scan and redact
            categories: If specified, only process these categories

        Returns:
            Dict with 'redacted_text' and 'redactions' list
        """
        if not content or not self._rules:
            return {"redacted_text": content, "redactions": []}

        redactions = []
        rules = self._get_filtered_rules(categories)
        regex_rules = [r for r in rules if r.match_type == "regex"]

        intervals = []
        for rule in regex_rules:
            for match in rule.compiled.finditer(content):
                if not self._passes_validation(match.group(), rule):
                    continue
                intervals.append((match.start(), match.end(), rule, match))

        intervals.sort(key=lambda x: x[0])
        merged = self._merge_intervals(intervals)

        result_parts = []
        last_end = 0
        for start, end, rule, match in merged:
            result_parts.append(content[last_end:start])
            strategy = rule.metadata.get("redaction_strategy", "full_redact")
            redacted = self._apply_redaction(match.group(), strategy)
            result_parts.append(redacted)
            redactions.append(
                {
                    "position": start,
                    "original_length": end - start,
                    "type": rule.metadata.get("description", rule.id),
                    "rule_id": rule.id,
                    "strategy": strategy,
                }
            )
            last_end = end

        result_parts.append(content[last_end:])

        return {
            "redacted_text": "".join(result_parts),
            "redactions": redactions,
        }

    def check_literal(
        self, text: str, categories: Optional[List[str]] = None
    ) -> List[Tuple[str, str, str]]:
        """Check text for literal character matches (homoglyphs).

        Args:
            text: Text to check
            categories: If specified, only check these categories

        Returns:
            List of (found_char, target_char, rule_id) tuples
        """
        results = []
        if categories:
            maps_to_check = {
                c: m for c, m in self._literal_maps.items() if c in categories
            }
        else:
            maps_to_check = self._literal_maps

        for category, char_map in maps_to_check.items():
            for char in text:
                if char in char_map:
                    rules = self._rules_by_category.get(category, [])
                    rule_id = "unknown"
                    for r in rules:
                        if r.match_type == "literal" and r.compiled[0] == char:
                            rule_id = r.id
                            break
                    results.append((char, char_map[char], rule_id))

        return results

    def check_cidr(
        self, ip_str: str, categories: Optional[List[str]] = None
    ) -> List[CompiledRule]:
        """Check if an IP address matches any CIDR rules.

        Args:
            ip_str: IP address string
            categories: If specified, only check these categories

        Returns:
            List of matching CompiledRule objects
        """
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return []

        matching = []
        rules = self._get_filtered_rules(categories)
        for rule in rules:
            if rule.match_type == "cidr" and addr in rule.compiled:
                matching.append(rule)
        return matching

    def check_range(
        self, codepoint: int, categories: Optional[List[str]] = None
    ) -> List[CompiledRule]:
        """Check if a Unicode codepoint falls within any range rules.

        Args:
            codepoint: Integer Unicode codepoint
            categories: If specified, only check these categories

        Returns:
            List of matching CompiledRule objects
        """
        matching = []
        rules = self._get_filtered_rules(categories)
        for rule in rules:
            if rule.match_type == "range":
                start, end = rule.compiled
                if start <= codepoint <= end:
                    matching.append(rule)
        return matching

    def _get_filtered_rules(
        self, categories: Optional[List[str]]
    ) -> List[CompiledRule]:
        if categories is None:
            return self._rules
        result = []
        for cat in categories:
            result.extend(self._rules_by_category.get(cat, []))
        return result

    def _scan_regex(self, content: str, rule: CompiledRule) -> List[ScanFinding]:
        keywords = rule.metadata.get("keywords")
        if keywords:
            content_lower = content.lower()
            if not any(kw.lower() in content_lower for kw in keywords):
                return []

        min_entropy = rule.metadata.get("entropy")

        findings = []
        for match in rule.compiled.finditer(content):
            if not self._passes_validation(match.group(), rule):
                continue
            if min_entropy is not None:
                from ai_guardian.patterns.validators import shannon_entropy

                if shannon_entropy(match.group()) < min_entropy:
                    continue
            line_num = content[: match.start()].count("\n") + 1
            findings.append(
                ScanFinding(
                    rule_id=rule.id,
                    line_number=line_num,
                    matched_text=match.group()[:100],
                    description=rule.metadata.get("description", ""),
                    category=rule.category,
                    match_start=match.start(),
                    match_end=match.end(),
                    metadata=rule.metadata,
                )
            )
        return findings

    def _scan_literal(self, content: str, rule: CompiledRule) -> List[ScanFinding]:
        findings = []
        source, target = rule.compiled
        for i, char in enumerate(content):
            if char == source:
                line_num = content[:i].count("\n") + 1
                findings.append(
                    ScanFinding(
                        rule_id=rule.id,
                        line_number=line_num,
                        matched_text=char,
                        description=rule.metadata.get(
                            "description", f"Literal match: {repr(source)}"
                        ),
                        category=rule.category,
                        match_start=i,
                        match_end=i + 1,
                        metadata=rule.metadata,
                    )
                )
        return findings

    def _scan_cidr(self, content: str, rule: CompiledRule) -> List[ScanFinding]:
        findings = []
        for match in self._IP_PATTERN.finditer(content):
            try:
                addr = ipaddress.ip_address(match.group())
                if addr in rule.compiled:
                    line_num = content[: match.start()].count("\n") + 1
                    findings.append(
                        ScanFinding(
                            rule_id=rule.id,
                            line_number=line_num,
                            matched_text=match.group(),
                            description=rule.metadata.get("description", ""),
                            category=rule.category,
                            match_start=match.start(),
                            match_end=match.end(),
                            metadata=rule.metadata,
                        )
                    )
            except ValueError:
                continue
        return findings

    def _scan_range(self, content: str, rule: CompiledRule) -> List[ScanFinding]:
        findings = []
        start, end = rule.compiled
        for i, char in enumerate(content):
            cp = ord(char)
            if start <= cp <= end:
                line_num = content[:i].count("\n") + 1
                findings.append(
                    ScanFinding(
                        rule_id=rule.id,
                        line_number=line_num,
                        matched_text=repr(char),
                        description=rule.metadata.get(
                            "description", f"Codepoint U+{cp:04X} in range"
                        ),
                        category=rule.category,
                        match_start=i,
                        match_end=i + 1,
                        metadata=rule.metadata,
                    )
                )
        return findings

    def _passes_validation(self, matched_text: str, rule: CompiledRule) -> bool:
        validation_name = rule.metadata.get("validation")
        if not validation_name:
            return True
        validator = get_validator(validation_name)
        if validator is None:
            return True
        return validator(matched_text)

    @staticmethod
    def _merge_intervals(intervals):
        if not intervals:
            return []
        merged = [intervals[0]]
        for current in intervals[1:]:
            prev = merged[-1]
            if current[0] < prev[1]:
                if (current[1] - current[0]) > (prev[1] - prev[0]):
                    merged[-1] = current
            else:
                merged.append(current)
        return merged

    @staticmethod
    def _apply_redaction(text: str, strategy: str) -> str:
        if strategy == "full_redact":
            return "[REDACTED]"
        elif strategy == "preserve_prefix_suffix":
            if len(text) <= 8:
                return "[REDACTED]"
            return text[:4] + "..." + text[-4:]
        elif strategy == "credit_card":
            digits = [c for c in text if c.isdigit()]
            if len(digits) >= 4:
                return "****-****-****-" + "".join(digits[-4:])
            return "[REDACTED]"
        elif strategy == "pii_email":
            parts = text.split("@")
            if len(parts) == 2:
                local = parts[0]
                domain = parts[1]
                masked_local = local[0] + "***" if local else "***"
                return f"{masked_local}@{domain}"
            return "[REDACTED]"
        elif strategy == "iban":
            clean = text.replace(" ", "")
            if len(clean) >= 6:
                return clean[:2] + "**" + "****" * ((len(clean) - 6) // 4) + clean[-4:]
            return "[REDACTED]"
        elif strategy == "canada_sin":
            return "***-***-***"
        else:
            return "[REDACTED]"
