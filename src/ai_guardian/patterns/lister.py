#!/usr/bin/env python3
"""
Pattern Lister Module

Lists all available detection patterns across the system for discoverability.
Shows built-in pattern counts and configurable keys users can set in ai-guardian.json.
"""

import json
import logging
import re as re_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_guardian.config.utils import get_cache_dir
from ai_guardian.patterns import BUNDLED_FILES
from ai_guardian.patterns.toml_parser import load_toml_file

logger = logging.getLogger(__name__)


def _count_toml_rules(category: str, **filters) -> int:
    """Count rules in a bundled TOML file, optionally filtered by field values."""
    path = BUNDLED_FILES.get(category)
    if not path or not path.exists():
        return 0
    try:
        rules = load_toml_file(path)
        if not filters:
            return len(rules)
        return sum(1 for r in rules if all(r.get(k) == v for k, v in filters.items()))
    except Exception:
        return 0


EXCLUDED_KEYS = {
    "enabled",
    "action",
    "immutable",
    "detector",
    "sensitivity",
    "max_score_threshold",
    "pattern_server",
    "allow_localhost",
    "allow_rtl_languages",
    "allow_emoji",
    "preserve_format",
    "log_redactions",
    "max_entries",
    "retention_days",
}

CATEGORY_ALIASES = {
    "pi": "prompt_injection",
    "injection": "prompt_injection",
    "unicode": "prompt_injection.unicode_detection",
    "pii": "scan_pii",
    "ssrf": "ssrf_protection",
    "config": "config_file_scanning",
    "config_scan": "config_file_scanning",
    "secrets": "secret_redaction",
    "redaction": "secret_redaction",
    "poisoning": "context_poisoning",
    "supply": "supply_chain",
    "logging": "violation_logging",
    "violations": "violation_logging",
}


TESTABLE_MATCH_TYPES = {"regex", "literal"}


def test_rule_matches(rule: "DetectionRule", text: str) -> bool:
    """Test whether a rule's pattern matches the given text."""
    if rule.match_type not in TESTABLE_MATCH_TYPES:
        return False
    try:
        if rule.match_type == "regex":
            return bool(re_mod.search(rule.pattern, text, re_mod.IGNORECASE))
        if rule.match_type == "literal":
            return rule.pattern.lower() in text.lower()
    except re_mod.error:
        return False
    return False


@dataclass
class DetectionRule:
    id: str
    pattern: str
    match_type: str
    source: str
    category: str
    group: str
    description: str
    severity: str


@dataclass
class ConfigurableKey:
    name: str
    description: str
    value_type: str
    default_value: Any
    current_count: int
    enum_values: Optional[List[str]] = None


@dataclass
class BuiltInGroup:
    name: str
    count: int
    note: str = ""


@dataclass
class PatternCategory:
    name: str
    config_key: str
    built_in_groups: List[BuiltInGroup] = field(default_factory=list)
    configurable_keys: List[ConfigurableKey] = field(default_factory=list)
    subcategories: List["PatternCategory"] = field(default_factory=list)

    @property
    def total_built_in(self) -> int:
        return sum(g.count for g in self.built_in_groups)


_CACHE_FILE_INFO = {
    "patterns.toml": ("secrets", "gitleaks"),
    "ssrf-patterns.toml": ("ssrf", "ssrf"),
    "unicode-patterns.toml": ("unicode", "unicode"),
    "config-exfil-patterns.toml": ("config_exfil", "config-exfil"),
    "secrets-patterns.toml": ("secrets", "secrets"),
}


class PatternLister:
    """Lists detection patterns and configurable keys across the system."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._schema: Optional[Dict[str, Any]] = None

    def _load_schema(self) -> Dict[str, Any]:
        if self._schema is not None:
            return self._schema
        try:
            schema_path = (
                Path(__file__).parent.parent
                / "schemas"
                / "ai-guardian-config.schema.json"
            )
            with open(schema_path, "r") as f:
                self._schema = json.load(f)
        except Exception as e:
            logger.warning("Could not load schema: %s", e)
            self._schema = {}
        return self._schema

    def _infer_value_type(self, prop: Dict[str, Any]) -> str:
        prop_type = prop.get("type")
        desc = prop.get("description", "").lower()

        if prop_type == "boolean":
            return "bool"

        if prop_type == "array":
            items = prop.get("items", {})
            if isinstance(items, dict):
                if items.get("type") == "object":
                    return "object list"
                item_enum = items.get("enum")
                if item_enum:
                    return "enum"
                if "glob" in desc:
                    return "glob list"
                if "cidr" in desc:
                    return "CIDR list"
                if "fnmatch" in desc:
                    return "fnmatch list"
                item_desc = items.get("description", "").lower()
                if "wildcard" in desc and "tool name" in desc:
                    return "fnmatch list"
                if "regex" in desc or "detection pattern" in desc:
                    return "regex list"
            return "string list"

        return "string"

    def _get_configurable_keys(
        self, schema_section: Dict[str, Any], config_section: Dict[str, Any]
    ) -> List[ConfigurableKey]:
        props = schema_section.get("properties", {})
        keys = []
        for key_name, prop in props.items():
            if key_name in EXCLUDED_KEYS:
                continue
            if (
                isinstance(prop, dict)
                and prop.get("type") == "object"
                and key_name != "path_based_rules"
            ):
                continue

            value_type = self._infer_value_type(prop)
            default = prop.get("default")
            enum_values = None

            items = prop.get("items", {})
            if isinstance(items, dict):
                item_enum = items.get("enum")
                if item_enum:
                    enum_values = item_enum

            current = config_section.get(key_name)
            if current is not None:
                if isinstance(current, list):
                    current_count = len(current)
                elif isinstance(current, bool):
                    current_count = 0
                else:
                    current_count = 0
            elif default is not None:
                if isinstance(default, list):
                    current_count = len(default)
                else:
                    current_count = 0
            else:
                current_count = 0

            keys.append(
                ConfigurableKey(
                    name=key_name,
                    description=prop.get("description", ""),
                    value_type=value_type,
                    default_value=default,
                    current_count=current_count,
                    enum_values=enum_values,
                )
            )
        return keys

    def _build_prompt_injection_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup(
                "CRITICAL_PATTERNS",
                _count_toml_rules("prompt_injection", group="critical"),
                "always checked",
            ),
            BuiltInGroup(
                "DOCUMENTATION_PATTERNS",
                _count_toml_rules("prompt_injection", group="documentation"),
                "user prompts only",
            ),
            BuiltInGroup(
                "JAILBREAK_PATTERNS",
                _count_toml_rules("prompt_injection", group="jailbreak"),
                "user prompts only",
            ),
            BuiltInGroup(
                "SUSPICIOUS_PATTERNS",
                _count_toml_rules("prompt_injection", group="suspicious"),
                "medium/high sensitivity",
            ),
        ]

        schema = self._load_schema()
        schema_section = schema.get("properties", {}).get("prompt_injection", {})
        config_section = self.config.get("prompt_injection", {})
        configurable = self._get_configurable_keys(schema_section, config_section)

        unicode_sub = self._build_unicode_detection_category()

        return PatternCategory(
            name="Prompt Injection",
            config_key="prompt_injection",
            built_in_groups=groups,
            configurable_keys=configurable,
            subcategories=[unicode_sub],
        )

    def _build_unicode_detection_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup(
                "Zero-width chars",
                _count_toml_rules("unicode", group="zero_width"),
                "invisible characters",
            ),
            BuiltInGroup(
                "Bidi override chars",
                _count_toml_rules("unicode", group="bidi_override"),
                "visual deception",
            ),
            BuiltInGroup(
                "Bidi formatting chars",
                _count_toml_rules("unicode", group="bidi_formatting"),
                "context-aware",
            ),
            BuiltInGroup(
                "Homoglyph patterns",
                _count_toml_rules("unicode", group="homoglyph"),
                "look-alike pairs",
            ),
        ]

        schema = self._load_schema()
        unicode_schema = (
            schema.get("properties", {})
            .get("prompt_injection", {})
            .get("properties", {})
            .get("unicode_detection", {})
        )
        unicode_config = self.config.get("prompt_injection", {}).get(
            "unicode_detection", {}
        )
        configurable = self._get_configurable_keys(unicode_schema, unicode_config)

        return PatternCategory(
            name="Unicode Detection",
            config_key="prompt_injection.unicode_detection",
            built_in_groups=groups,
            configurable_keys=configurable,
        )

    def _build_pii_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup("PII patterns", _count_toml_rules("pii"), ""),
        ]

        schema = self._load_schema()
        schema_section = schema.get("properties", {}).get("scan_pii", {})
        config_section = self.config.get("scan_pii", {})
        configurable = self._get_configurable_keys(schema_section, config_section)

        return PatternCategory(
            name="PII Detection",
            config_key="scan_pii",
            built_in_groups=groups,
            configurable_keys=configurable,
        )

    def _build_ssrf_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup(
                "Blocked IP ranges",
                _count_toml_rules("ssrf", match_type="cidr"),
                "RFC 1918 + loopback",
            ),
            BuiltInGroup(
                "Blocked domains",
                _count_toml_rules("ssrf", group="blocked_domain"),
                "cloud metadata",
            ),
            BuiltInGroup(
                "Dangerous schemes",
                _count_toml_rules("ssrf", group="dangerous_scheme"),
                "file://, gopher://, etc.",
            ),
        ]

        schema = self._load_schema()
        schema_section = schema.get("properties", {}).get("ssrf_protection", {})
        config_section = self.config.get("ssrf_protection", {})
        configurable = self._get_configurable_keys(schema_section, config_section)

        return PatternCategory(
            name="SSRF Protection",
            config_key="ssrf_protection",
            built_in_groups=groups,
            configurable_keys=configurable,
        )

    def _build_config_scanning_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup(
                "Exfiltration patterns",
                _count_toml_rules("config_exfil"),
                "credential theft",
            ),
        ]

        schema = self._load_schema()
        schema_section = schema.get("properties", {}).get("config_file_scanning", {})
        config_section = self.config.get("config_file_scanning", {})
        configurable = self._get_configurable_keys(schema_section, config_section)

        return PatternCategory(
            name="Config File Scanning",
            config_key="config_file_scanning",
            built_in_groups=groups,
            configurable_keys=configurable,
        )

    def _build_secret_redaction_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup(
                "Secret patterns",
                _count_toml_rules("secrets"),
                "API keys, tokens, credentials",
            ),
        ]

        schema = self._load_schema()
        schema_section = schema.get("properties", {}).get("secret_redaction", {})
        config_section = self.config.get("secret_redaction", {})
        configurable = self._get_configurable_keys(schema_section, config_section)

        return PatternCategory(
            name="Secret Redaction",
            config_key="secret_redaction",
            built_in_groups=groups,
            configurable_keys=configurable,
        )

    def _build_context_poisoning_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup(
                "Persistence patterns",
                _count_toml_rules("context_poisoning", group="persistence"),
                "permanent instruction injection",
            ),
            BuiltInGroup(
                "Dangerous action patterns",
                _count_toml_rules("context_poisoning", group="dangerous_action"),
                "risky automated actions",
            ),
        ]

        return PatternCategory(
            name="Context Poisoning",
            config_key="context_poisoning",
            built_in_groups=groups,
        )

    def _build_supply_chain_category(self) -> PatternCategory:
        groups = [
            BuiltInGroup(
                "Download & execute",
                _count_toml_rules("supply_chain", group="download_and_execute"),
                "curl|sh, wget|sh chains",
            ),
            BuiltInGroup(
                "Malicious imports",
                _count_toml_rules("supply_chain", group="malicious_imports"),
                "suspicious pip/npm installs",
            ),
        ]

        return PatternCategory(
            name="Supply Chain",
            config_key="supply_chain",
            built_in_groups=groups,
        )

    def _build_violation_logging_category(self) -> PatternCategory:
        schema = self._load_schema()
        schema_section = schema.get("properties", {}).get("violation_logging", {})
        config_section = self.config.get("violation_logging", {})
        configurable = self._get_configurable_keys(schema_section, config_section)

        return PatternCategory(
            name="Violation Logging",
            config_key="violation_logging",
            built_in_groups=[],
            configurable_keys=configurable,
        )

    def get_categories(
        self, category_filter: Optional[str] = None
    ) -> List[PatternCategory]:
        resolved = category_filter
        if resolved and resolved in CATEGORY_ALIASES:
            resolved = CATEGORY_ALIASES[resolved]

        builders = [
            self._build_prompt_injection_category,
            self._build_pii_category,
            self._build_ssrf_category,
            self._build_config_scanning_category,
            self._build_secret_redaction_category,
            self._build_context_poisoning_category,
            self._build_supply_chain_category,
            self._build_violation_logging_category,
        ]

        categories = []
        for builder in builders:
            cat = builder()
            if resolved:
                if cat.config_key == resolved:
                    categories.append(cat)
                else:
                    for sub in cat.subcategories:
                        if sub.config_key == resolved:
                            categories.append(sub)
            else:
                categories.append(cat)

        return categories

    def _extract_pattern_text(self, rule: Dict[str, Any]) -> str:
        for key in ("regex", "cidr", "source", "glob"):
            if key in rule:
                return str(rule[key])
        return rule.get("id", "")

    def _load_pattern_server_rules(
        self, bundled_ids: set, category_filter: Optional[str] = None
    ) -> List[DetectionRule]:
        """Load rules from pattern server cache files (no network calls)."""
        rules: List[DetectionRule] = []
        try:
            cache_dir = get_cache_dir()
        except Exception:
            return rules

        if not cache_dir.exists():
            return rules

        for filename, (cat_key, engine_type) in _CACHE_FILE_INFO.items():
            if category_filter and cat_key != category_filter:
                continue
            cache_path = cache_dir / filename
            if not cache_path.exists():
                continue
            try:
                raw_rules = load_toml_file(cache_path)
            except Exception:
                logger.debug("Failed to parse pattern server cache %s", cache_path)
                continue
            source_label = f"server:{engine_type}"
            for raw in raw_rules:
                rule_id = raw.get("id", "")
                if rule_id in bundled_ids:
                    continue
                pattern = self._extract_pattern_text(raw)
                match_type = raw.get("match_type", "")
                if not match_type and "regex" in raw:
                    match_type = "regex"
                if not match_type:
                    match_type = "regex"
                group = raw.get("group", raw.get("category", ""))
                if not group:
                    tags = raw.get("tags", [])
                    if tags:
                        group = ", ".join(tags[:2])
                rules.append(
                    DetectionRule(
                        id=rule_id,
                        pattern=pattern,
                        match_type=match_type,
                        source=source_label,
                        category=cat_key,
                        group=group,
                        description=raw.get("description", ""),
                        severity=raw.get("tier", raw.get("severity", "")),
                    )
                )

        return rules

    def get_all_rules(
        self, category_filter: Optional[str] = None
    ) -> List[DetectionRule]:
        """Return all detection rules from TOML files, pattern server cache, and hardcoded patterns."""
        rules: List[DetectionRule] = []

        for cat_key, toml_path in BUNDLED_FILES.items():
            if category_filter and cat_key != category_filter:
                continue
            if not toml_path.exists():
                continue
            try:
                raw_rules = load_toml_file(toml_path)
            except Exception:
                continue
            for raw in raw_rules:
                rules.append(
                    DetectionRule(
                        id=raw.get("id", ""),
                        pattern=self._extract_pattern_text(raw),
                        match_type=raw.get("match_type", "regex"),
                        source="toml",
                        category=cat_key,
                        group=raw.get("group", raw.get("category", "")),
                        description=raw.get("description", ""),
                        severity=raw.get("tier", raw.get("severity", "")),
                    )
                )

        bundled_ids = {r.id for r in rules}
        rules.extend(self._load_pattern_server_rules(bundled_ids, category_filter))

        if not category_filter or category_filter == "self_protection":
            try:
                from ai_guardian.tools.patterns import IMMUTABLE_DENY_PATTERNS

                for tool_name, patterns in IMMUTABLE_DENY_PATTERNS.items():
                    for i, pat in enumerate(patterns):
                        rules.append(
                            DetectionRule(
                                id=f"self-protect-{tool_name.lower()}-{i+1:03d}",
                                pattern=pat,
                                match_type="fnmatch",
                                source="hardcoded",
                                category="self_protection",
                                group=tool_name,
                                description=f"Self-protection: blocks {tool_name} on matching paths",
                                severity="immutable",
                            )
                        )
            except ImportError:
                pass  # intentionally silent — optional dependency

        return rules

    def print_pattern_list(self, verbose: bool = False, category: Optional[str] = None):
        categories = self.get_categories(category_filter=category)

        if not categories:
            print(f"\nNo pattern category found matching '{category}'")
            print("\nAvailable categories:")
            all_cats = self.get_categories()
            for cat in all_cats:
                print(f"  {cat.config_key}")
                for sub in cat.subcategories:
                    print(f"  {sub.config_key}")
            return

        print("\nDetection Patterns:\n")

        for cat in categories:
            self._print_category(cat, verbose=verbose, indent=2)

        if not verbose:
            print("Use --verbose to show pattern group breakdowns")
        print("Use --category <name> to filter (e.g., prompt_injection, scan_pii)")
        print("Use --json for machine-readable output")

    def _print_category(self, cat: PatternCategory, verbose: bool, indent: int):
        prefix = " " * indent
        print(f"{prefix}{cat.name} ({cat.config_key})")

        if cat.built_in_groups:
            total = cat.total_built_in
            group_count = len(cat.built_in_groups)
            if group_count > 1:
                print(f"{prefix}  Built-in: {total} patterns ({group_count} groups)")
            else:
                print(f"{prefix}  Built-in: {total} patterns")

            if verbose:
                for group in cat.built_in_groups:
                    note = f"  ({group.note})" if group.note else ""
                    print(
                        f"{prefix}    {group.name:<30s} {group.count:>3d} patterns{note}"
                    )

        if cat.configurable_keys:
            print(f"{prefix}  Configurable keys (use in ai-guardian.json):")
            for key in cat.configurable_keys:
                if key.value_type == "bool":
                    current_display = (
                        str(key.default_value).lower()
                        if key.default_value is not None
                        else "false"
                    )
                    configured = self.config
                    parts = cat.config_key.split(".")
                    for part in parts:
                        configured = (
                            configured.get(part, {})
                            if isinstance(configured, dict)
                            else {}
                        )
                    if (
                        key.name in configured
                        if isinstance(configured, dict)
                        else False
                    ):
                        current_display = str(configured[key.name]).lower()
                    print(
                        f"{prefix}    {key.name:<30s} {key.value_type:<14s} (current: {current_display})"
                    )
                else:
                    count_label = (
                        f"{key.current_count} configured"
                        if key.current_count > 0
                        else "0 configured"
                    )
                    if key.enum_values and key.current_count > 0:
                        count_label = f"{key.current_count} active"
                    print(
                        f"{prefix}    {key.name:<30s} {key.value_type:<14s} ({count_label})"
                    )
                    if key.enum_values and verbose:
                        print(f"{prefix}      Values: {', '.join(key.enum_values)}")

        for sub in cat.subcategories:
            print()
            self._print_category(sub, verbose=verbose, indent=indent + 2)

        print()

    def get_pattern_list_json(self, category: Optional[str] = None) -> str:
        categories = self.get_categories(category_filter=category)
        data = {"categories": [self._category_to_dict(cat) for cat in categories]}
        return json.dumps(data, indent=2)

    def _category_to_dict(self, cat: PatternCategory) -> Dict[str, Any]:
        return {
            "name": cat.name,
            "config_key": cat.config_key,
            "total_built_in": cat.total_built_in,
            "built_in_groups": [
                {"name": g.name, "count": g.count, "note": g.note}
                for g in cat.built_in_groups
            ],
            "configurable_keys": [
                {
                    "name": k.name,
                    "value_type": k.value_type,
                    "current_count": k.current_count,
                    "default_value": k.default_value,
                    **({"enum_values": k.enum_values} if k.enum_values else {}),
                }
                for k in cat.configurable_keys
            ],
            "subcategories": [self._category_to_dict(sub) for sub in cat.subcategories],
        }
