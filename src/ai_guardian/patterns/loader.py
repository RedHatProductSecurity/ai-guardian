#!/usr/bin/env python3
"""
Pattern Loader - Abstract base class and implementations for loading security patterns.

Supports three-tier pattern system:
- Tier 1: IMMUTABLE - Core security baselines (cannot be disabled)
- Tier 2: OVERRIDABLE - Pattern server can replace/modify
- Tier 3: ADDITIONS - Local config additions (always additive)

Implements fallback chain: pattern server → cache → hardcoded defaults

NEW in v1.5.0: Pattern server support for SSRF, Unicode, Config Scanner, and Secret Redaction.
NEW in v1.9.0: Pattern server support for PII Detection.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from ai_guardian.patterns.server import PatternServerClient
from ai_guardian.patterns import BUNDLED_FILES

logger = logging.getLogger(__name__)


class PatternLoader(ABC):
    """
    Abstract base class for loading patterns from pattern server.

    Each security feature (SSRF, Unicode, Config Scanner, Secret Redaction)
    implements a concrete pattern loader that defines:
    - Which patterns are immutable (cannot be overridden)
    - Which patterns are overridable (pattern server can replace)
    - How to merge three tiers into effective configuration
    """

    def __init__(self, feature_name: str, pattern_type: str):
        """
        Initialize pattern loader.

        Args:
            feature_name: Human-readable feature name (e.g., "SSRF Protection")
            pattern_type: Pattern type for server API (e.g., "ssrf", "unicode")
        """
        self.feature_name = feature_name
        self.pattern_type = pattern_type
        self.pattern_sources = {}  # Track where each pattern came from

    @abstractmethod
    def get_immutable_patterns(self) -> Dict[str, Any]:
        """
        Get patterns that cannot be overridden by pattern server.

        These are core security baselines that must always be enforced.

        Returns:
            Dict of immutable patterns specific to this feature
        """
        pass

    @abstractmethod
    def get_default_patterns(self) -> Dict[str, Any]:
        """
        Get default patterns (hardcoded fallback).

        These are used when pattern server is unavailable or disabled.
        Can be overridden by pattern server.

        Returns:
            Dict of default patterns
        """
        pass

    @abstractmethod
    def merge_patterns(
        self,
        immutable: Dict[str, Any],
        server: Optional[Dict[str, Any]],
        local: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Merge three tiers of patterns into effective configuration.

        Args:
            immutable: Tier 1 - Immutable patterns (always included)
            server: Tier 2 - Pattern server patterns (optional, can replace defaults)
            local: Tier 3 - Local config additions (optional, always additive)

        Returns:
            Final merged configuration
        """
        pass

    def load_patterns(
        self,
        pattern_server_config: Optional[Dict[str, Any]] = None,
        local_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Load and merge patterns from all three tiers.

        Implements fallback chain: server → cache → defaults

        Args:
            pattern_server_config: Pattern server configuration (if enabled)
            local_config: Local config additions

        Returns:
            Effective pattern configuration with source attribution
        """
        # Tier 1: Immutable patterns (always included)
        immutable = self.get_immutable_patterns()
        self._mark_sources(immutable, "IMMUTABLE")

        # Tier 2: Pattern server (optional)
        server_patterns = None
        if pattern_server_config:
            try:
                client = PatternServerClient(
                    pattern_server_config, pattern_type=self.pattern_type
                )
                server_patterns = client.get_patterns()

                if server_patterns:
                    logger.info(
                        f"{self.feature_name}: Loaded patterns from pattern server"
                    )
                    self._mark_sources(server_patterns, "SERVER")
                else:
                    logger.debug(
                        f"{self.feature_name}: Pattern server unavailable, using defaults"
                    )
            except Exception as e:
                logger.warning(
                    f"{self.feature_name}: Error loading from pattern server: {e}"
                )
                logger.debug(f"{self.feature_name}: Falling back to default patterns")

        # If no server patterns, use defaults
        if server_patterns is None:
            default_patterns = self.get_default_patterns()
            self._mark_sources(default_patterns, "DEFAULT")
        else:
            default_patterns = server_patterns

        # Tier 3: Local config additions (always additive)
        self._mark_sources(local_config or {}, "LOCAL_CONFIG")

        # Merge all tiers
        final_patterns = self.merge_patterns(immutable, default_patterns, local_config)

        # Store source attribution for 'config show --summary' command
        final_patterns["_pattern_sources"] = self.pattern_sources

        logger.debug(
            f"{self.feature_name}: Pattern loading complete (sources: {len(self.pattern_sources)} entries)"
        )

        return final_patterns

    def _mark_sources(self, patterns: Dict[str, Any], source: str) -> None:
        """
        Track where patterns came from for transparency.

        Args:
            patterns: Pattern dictionary
            source: Source identifier (IMMUTABLE, SERVER, DEFAULT, LOCAL_CONFIG)
        """
        if not patterns:
            return

        # Mark each top-level key with its source
        for key in patterns.keys():
            if not key.startswith("_"):  # Skip internal keys
                self.pattern_sources[key] = source


class SSRFPatternLoader(PatternLoader):
    """
    Pattern loader for SSRF Protection.

    Immutable: Cloud metadata endpoints, dangerous URL schemes
    Overridable: RFC 1918 private ranges
    """

    def __init__(self):
        super().__init__("SSRF Protection", "ssrf")

    def get_immutable_patterns(self) -> Dict[str, Any]:
        """
        Get immutable SSRF patterns (cannot be overridden).

        Includes:
        - Cloud metadata endpoints: 169.254.169.254, metadata.google.internal
        - Dangerous URL schemes: file://, gopher://, etc.
        - IPv6 metadata: fd00:ec2::254
        """
        return {
            "blocked_ip_ranges": [
                {
                    "cidr": "169.254.0.0/16",
                    "description": "AWS/Azure metadata (link-local)",
                    "immutable": True,
                }
            ],
            "blocked_domains": [
                {
                    "domain": "metadata.google.internal",
                    "description": "GCP metadata",
                    "immutable": True,
                },
                {
                    "domain": "metadata.goog",
                    "description": "GCP metadata (alt)",
                    "immutable": True,
                },
                {
                    "domain": "169.254.169.254",
                    "description": "AWS/Azure metadata IP",
                    "immutable": True,
                },
                {
                    "domain": "fd00:ec2::254",
                    "description": "AWS IPv6 metadata",
                    "immutable": True,
                },
            ],
            "dangerous_schemes": [
                "file",
                "gopher",
                "ftp",
                "ftps",
                "data",
                "dict",
                "ldap",
                "ldaps",
            ],
        }

    def get_default_patterns(self) -> Dict[str, Any]:
        """
        Get default SSRF patterns (overridable by pattern server).

        Includes:
        - RFC 1918 private ranges: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
        - Loopback: 127.0.0.0/8, ::1/128
        - IPv6 private: fc00::/7, fe80::/10
        """
        return {
            "blocked_ip_ranges": [
                {
                    "cidr": "10.0.0.0/8",
                    "description": "Private network Class A (RFC 1918)",
                },
                {
                    "cidr": "172.16.0.0/12",
                    "description": "Private network Class B (RFC 1918)",
                },
                {
                    "cidr": "192.168.0.0/16",
                    "description": "Private network Class C (RFC 1918)",
                },
                {"cidr": "127.0.0.0/8", "description": "Loopback"},
                {"cidr": "::1/128", "description": "IPv6 loopback"},
                {"cidr": "fc00::/7", "description": "IPv6 private network"},
                {"cidr": "fe80::/10", "description": "IPv6 link-local"},
            ],
            "blocked_domains": [
                {"domain": "localhost", "description": "Localhost"},
                {"domain": "instance-data", "description": "AWS instance metadata"},
            ],
        }

    def merge_patterns(
        self,
        immutable: Dict[str, Any],
        server: Optional[Dict[str, Any]],
        local: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Merge SSRF patterns: immutable + (server OR default) + local.

        Args:
            immutable: Always-enforced patterns
            server: Pattern server patterns (can replace defaults)
            local: Local config additions

        Returns:
            Merged SSRF configuration
        """
        # Start with immutable patterns
        merged = {
            "blocked_ip_ranges": immutable.get("blocked_ip_ranges", []).copy(),
            "blocked_domains": immutable.get("blocked_domains", []).copy(),
            "dangerous_schemes": immutable.get("dangerous_schemes", []).copy(),
        }

        # Add server patterns (or defaults if server unavailable)
        if server:
            merged["blocked_ip_ranges"].extend(server.get("blocked_ip_ranges", []))
            merged["blocked_domains"].extend(server.get("blocked_domains", []))
            # Schemes are immutable, don't add from server

        # Add local config additions
        if local:
            # Handle additional_blocked_ips (legacy format)
            if "additional_blocked_ips" in local:
                for ip in local["additional_blocked_ips"]:
                    merged["blocked_ip_ranges"].append(
                        {"cidr": ip, "description": "Local config addition"}
                    )

            # Handle additional_blocked_domains (legacy format)
            if "additional_blocked_domains" in local:
                for domain in local["additional_blocked_domains"]:
                    merged["blocked_domains"].append(
                        {"domain": domain, "description": "Local config addition"}
                    )

        return merged


class UnicodePatternLoader(PatternLoader):
    """
    Pattern loader for Unicode Attack Detection.

    Immutable: Zero-width chars, bidi overrides (based on Unicode spec)
    Overridable: Homoglyph patterns (new scripts emerge)
    """

    def __init__(self):
        super().__init__("Unicode Attack Detection", "unicode")

    def get_immutable_patterns(self) -> Dict[str, Any]:
        """
        Get immutable Unicode patterns (based on Unicode spec).

        Includes:
        - Zero-width characters (9 types)
        - Bidirectional override characters (2 types)
        - Tag character range
        """
        return {
            "zero_width_chars": ["​", "‌", "‍", "﻿", "⁠", "⁡", "⁢", "⁣", "⁤"],
            "bidi_override_chars": ["‮", "‭"],
            "tag_char_range": {"start": 0xE0000, "end": 0xE007F},
        }

    def get_default_patterns(self) -> Dict[str, Any]:
        """
        Get default homoglyph patterns (overridable).

        Includes 80+ Cyrillic/Greek/Math symbol → Latin confusables.
        """
        # Abbreviated version - full list in prompt_injection.py
        return {
            "homoglyph_patterns": [
                {"source": "а", "target": "a", "script": "Cyrillic"},
                {"source": "е", "target": "e", "script": "Cyrillic"},
                {"source": "о", "target": "o", "script": "Cyrillic"},
                # ... (full list would be imported from prompt_injection.py)
            ]
        }

    def merge_patterns(
        self,
        immutable: Dict[str, Any],
        server: Optional[Dict[str, Any]],
        local: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Merge Unicode patterns: immutable + (server OR default) + local.
        """
        merged = {
            "zero_width_chars": immutable.get("zero_width_chars", []),
            "bidi_override_chars": immutable.get("bidi_override_chars", []),
            "tag_char_range": immutable.get("tag_char_range", {}),
            "homoglyph_patterns": [],
        }

        # Add server homoglyphs (or defaults)
        if server:
            merged["homoglyph_patterns"].extend(server.get("homoglyph_patterns", []))

        # Add local homoglyphs
        if local and "additional_homoglyphs" in local:
            merged["homoglyph_patterns"].extend(local["additional_homoglyphs"])

        return merged


class ConfigExfilPatternLoader(PatternLoader):
    """
    Pattern loader for Config File Scanner.

    Immutable: Core exfiltration patterns (env|curl, aws s3, gcp storage)
    Overridable: Additional patterns
    """

    def __init__(self):
        super().__init__("Config File Scanner", "config-exfil")

    def get_immutable_patterns(self) -> Dict[str, Any]:
        """
        Get immutable config exfiltration patterns.

        Includes core credential theft vectors.
        """
        return {
            "patterns": [
                {
                    "name": "env_piped_to_curl",
                    "pattern": r"\benv\s*\|.*\bcurl\b",
                    "description": "env piped to curl (credential exfiltration)",
                    "immutable": True,
                },
                {
                    "name": "aws_s3_exfil",
                    "pattern": r"\baws\s+s3\s+(?:cp|sync)\b",
                    "description": "AWS S3 upload",
                    "immutable": True,
                },
                {
                    "name": "gcp_storage_exfil",
                    "pattern": r"\bgcloud\s+storage\s+cp\b",
                    "description": "GCP Cloud Storage upload",
                    "immutable": True,
                },
            ]
        }

    def get_default_patterns(self) -> Dict[str, Any]:
        """
        Get default config scanner patterns (overridable).
        """
        return {
            "patterns": [
                {
                    "name": "curl_with_env_vars",
                    "pattern": r"curl.*\$\{?[A-Z_][A-Z0-9_]*\}?",
                    "description": "curl with environment variable",
                },
                {
                    "name": "wget_with_env_vars",
                    "pattern": r"wget.*\$\{?[A-Z_][A-Z0-9_]*\}?",
                    "description": "wget with environment variable",
                },
                # ... (full list in config_scanner.py)
            ]
        }

    def merge_patterns(
        self,
        immutable: Dict[str, Any],
        server: Optional[Dict[str, Any]],
        local: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Merge config scanner patterns: immutable + (server OR default) + local.
        """
        merged = {"patterns": immutable.get("patterns", []).copy()}

        # Add server patterns
        if server:
            merged["patterns"].extend(server.get("patterns", []))

        # Add local patterns
        if local and "additional_patterns" in local:
            for pattern in local["additional_patterns"]:
                # Convert string pattern to dict format
                if isinstance(pattern, str):
                    pattern = {
                        "name": "custom",
                        "pattern": pattern,
                        "description": "Local config addition",
                    }
                merged["patterns"].append(pattern)

        return merged


class SecretPatternLoader(PatternLoader):
    """
    Pattern loader for Secret Redaction.

    Immutable: None (all patterns can be enterprise-customized)
    Overridable: All 35+ secret types
    """

    def __init__(self):
        super().__init__("Secret Redaction", "secrets")

    def get_immutable_patterns(self) -> Dict[str, Any]:
        """
        Get immutable secret patterns.

        No immutable patterns - all can be customized by enterprise.
        """
        return {"patterns": []}

    def get_default_patterns(self) -> Dict[str, Any]:
        """
        Get default secret patterns from bundled TOML (Issue #841).

        These are all overridable by pattern server.
        """
        toml_path = BUNDLED_FILES.get("secrets")
        if toml_path and toml_path.exists():
            try:
                from ai_guardian.patterns.toml_parser import load_toml_file

                raw_rules = load_toml_file(toml_path)
                return {
                    "patterns": [
                        {
                            "regex": r.get("regex", ""),
                            "strategy": r.get(
                                "redaction_strategy", "preserve_prefix_suffix"
                            ),
                            "secret_type": r.get("description", ""),
                        }
                        for r in raw_rules
                        if r.get("match_type", "regex") == "regex"
                    ]
                }
            except Exception as e:
                logger.error(f"Failed to load bundled secrets.toml: {e}")
        return {"patterns": []}

    def merge_patterns(
        self,
        immutable: Dict[str, Any],
        server: Optional[Dict[str, Any]],
        local: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Merge secret patterns.

        Supports two modes:
        - replace: Pattern server replaces all defaults
        - extend: Pattern server adds to defaults (default)
        """
        # Check override mode from server metadata
        override_mode = "extend"
        if server and "metadata" in server:
            override_mode = server["metadata"].get("override_mode", "extend")

        if override_mode == "replace" and server:
            # Replace mode: use only server patterns
            merged = {"patterns": server.get("patterns", [])}
            logger.info(
                f"{self.feature_name}: Using pattern server patterns (replace mode)"
            )
        else:
            # Extend mode: defaults + server + local
            default_patterns = self.get_default_patterns()
            merged = {"patterns": default_patterns["patterns"].copy()}

            if server:
                merged["patterns"].extend(server.get("patterns", []))

        # Always add local patterns (additive)
        if local and "additional_patterns" in local:
            merged["patterns"].extend(local["additional_patterns"])

        return merged


class PIIPatternLoader(PatternLoader):
    """
    Pattern loader for PII Detection.

    Immutable: None (all PII patterns can be enterprise-customized)
    Overridable: All PII types (SSN, credit card, phone, email, etc.)
    """

    def __init__(self):
        super().__init__("PII Detection", "pii")

    def get_immutable_patterns(self) -> Dict[str, Any]:
        return {"rules": []}

    def get_default_patterns(self) -> Dict[str, Any]:
        toml_path = BUNDLED_FILES.get("pii")
        if toml_path and toml_path.exists():
            try:
                from ai_guardian.patterns.toml_parser import load_toml_file

                raw_rules = load_toml_file(toml_path)
                return {"rules": raw_rules}
            except Exception as e:
                logger.error(f"Failed to load bundled pii.toml: {e}")
        return {"rules": []}

    def merge_patterns(
        self,
        immutable: Dict[str, Any],
        server: Optional[Dict[str, Any]],
        local: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        override_mode = "extend"
        if server and "metadata" in server:
            override_mode = server["metadata"].get("override_mode", "extend")

        if override_mode == "replace" and server:
            merged = {"rules": list(server.get("rules", []))}
            logger.info(
                f"{self.feature_name}: Using pattern server patterns (replace mode)"
            )
        else:
            # Load defaults explicitly: the base class passes server data (not defaults)
            # as `server` when a pattern server is configured, so defaults must be loaded
            # here for the extend merge.
            default_patterns = self.get_default_patterns()
            merged = {"rules": list(default_patterns.get("rules", []))}

            if server:
                server_rules = server.get("rules", [])
                existing_ids = {r.get("id") for r in merged["rules"] if r.get("id")}
                for rule in server_rules:
                    rule_id = rule.get("id")
                    if rule_id and rule_id in existing_ids:
                        merged["rules"] = [
                            r if r.get("id") != rule_id else rule
                            for r in merged["rules"]
                        ]
                    else:
                        merged["rules"].append(rule)

        if local and "additional_pii_patterns" in local:
            merged["rules"].extend(local["additional_pii_patterns"])

        return merged
