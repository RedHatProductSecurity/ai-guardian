#!/usr/bin/env python3
"""
Configuration Inspector - Display effective configuration with source attribution.

Provides transparency into AI Guardian's three-tier pattern system:
- Tier 1: IMMUTABLE (hardcoded, cannot be overridden)
- Tier 2: SERVER/DEFAULT (pattern server or hardcoded defaults)
- Tier 3: LOCAL_CONFIG (user additions)

NEW in v1.5.0: Part of pattern server support for enterprise pattern management.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

from ai_guardian.config.utils import get_cache_dir, is_feature_enabled

logger = logging.getLogger(__name__)


class ConfigInspector:
    """
    Inspects and displays effective AI Guardian configuration.

    Shows which patterns are active and where they came from for
    transparency and debugging.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize config inspector.

        Args:
            config: AI Guardian configuration dict
        """
        self.config = config

    def show_ssrf_config(
        self, show_sources: bool = False, show_diff: bool = False
    ) -> str:
        """
        Display SSRF protection configuration.

        Args:
            show_sources: Include source attribution (IMMUTABLE, SERVER, etc.)
            show_diff: Show what pattern server changed from defaults

        Returns:
            Formatted configuration display
        """
        output = []
        output.append("=" * 70)
        output.append("SSRF Protection Configuration")
        output.append("=" * 70)
        output.append("")

        ssrf_config = self.config.get("ssrf_protection", {})

        # Basic settings
        enabled = is_feature_enabled(ssrf_config.get("enabled"), default=True)
        action = ssrf_config.get("action", "block")
        allow_localhost = ssrf_config.get("allow_localhost", False)

        output.append(f"Status: {'ENABLED' if enabled else 'DISABLED'}")
        output.append(f"Action: {action}")
        output.append(f"Allow Localhost: {allow_localhost}")
        output.append("")

        # Pattern server status
        pattern_server = ssrf_config.get("pattern_server")
        if pattern_server:
            output.append("Pattern Server: CONFIGURED")
            output.append(f"  URL: {pattern_server.get('url', 'N/A')}")
            output.append(
                f"  Endpoint: {pattern_server.get('patterns_endpoint', '/patterns/ssrf/v1')}"
            )

            # Check cache
            cache_config = pattern_server.get("cache", {})
            cache_path = Path(
                cache_config.get("path", str(get_cache_dir() / "ssrf-patterns.toml"))
            ).expanduser()
            if cache_path.exists():
                import time

                mtime = cache_path.stat().st_mtime
                age_hours = (time.time() - mtime) / 3600
                output.append(f"  Cache: {cache_path} ({age_hours:.1f}h old)")
            else:
                output.append("  Cache: Not present")
        else:
            output.append("Pattern Server: NOT CONFIGURED (using hardcoded defaults)")

        output.append("")

        # Load effective patterns
        try:
            from ai_guardian.scanners.ssrf import SSRFProtector

            protector = SSRFProtector(ssrf_config)

            output.append(
                f"Blocked IP Ranges: {len(protector._blocked_ip_networks)} ranges"
            )
            if show_sources:
                output.append("")
                for network in protector._blocked_ip_networks:
                    cidr = str(network)
                    # Determine source based on CIDR
                    if cidr in ["169.254.0.0/16"]:
                        source = "IMMUTABLE"
                    elif pattern_server:
                        source = "SERVER"
                    else:
                        source = "DEFAULT"
                    output.append(f"  • {cidr:20s} [{source}]")

            output.append("")
            output.append(f"Blocked Domains: {len(protector._blocked_domains)} domains")
            if show_sources:
                output.append("")
                for domain in sorted(protector._blocked_domains):
                    # Determine source
                    if domain in [
                        "metadata.google.internal",
                        "metadata.goog",
                        "169.254.169.254",
                        "fd00:ec2::254",
                    ]:
                        source = "IMMUTABLE"
                    elif pattern_server:
                        source = "SERVER"
                    else:
                        source = "DEFAULT"
                    output.append(f"  • {domain:30s} [{source}]")

            output.append("")
            output.append(
                f"Dangerous URL Schemes: {len(protector.DANGEROUS_SCHEMES)} schemes (IMMUTABLE)"
            )
            if show_sources:
                output.append("")
                for scheme in protector.DANGEROUS_SCHEMES:
                    output.append(f"  • {scheme}:// [IMMUTABLE]")

        except Exception as e:
            output.append(f"Error loading SSRF configuration: {e}")

        output.append("")
        output.append("=" * 70)

        return "\n".join(output)

    def show_secret_config(self, show_sources: bool = False) -> str:
        """
        Display secret redaction configuration.

        Args:
            show_sources: Include pattern source attribution

        Returns:
            Formatted configuration display
        """
        output = []
        output.append("=" * 70)
        output.append("Secret Redaction Configuration")
        output.append("=" * 70)
        output.append("")

        secret_config = self.config.get("secret_redaction", {})

        # Basic settings
        enabled = secret_config.get("enabled", True)
        action = secret_config.get("action", "log-only")
        preserve_format = secret_config.get("preserve_format", True)

        output.append(f"Status: {'ENABLED' if enabled else 'DISABLED'}")
        output.append(f"Action: {action}")
        output.append(f"Preserve Format: {preserve_format}")
        output.append("")

        # Pattern server status
        pattern_server = secret_config.get("pattern_server")
        if pattern_server:
            output.append("Pattern Server: CONFIGURED")
            output.append(f"  URL: {pattern_server.get('url', 'N/A')}")

            # Check cache
            cache_config = pattern_server.get("cache", {})
            cache_path = Path(
                cache_config.get("path", str(get_cache_dir() / "secrets-patterns.toml"))
            ).expanduser()
            if cache_path.exists():
                import time

                mtime = cache_path.stat().st_mtime
                age_hours = (time.time() - mtime) / 3600
                output.append(f"  Cache: {cache_path} ({age_hours:.1f}h old)")
            else:
                output.append("  Cache: Not present")
        else:
            output.append("Pattern Server: NOT CONFIGURED (using hardcoded defaults)")

        output.append("")

        # Load effective patterns
        try:
            from ai_guardian.scanners.secret_redactor import SecretRedactor

            redactor = SecretRedactor(secret_config)

            output.append(
                f"Secret Patterns: {len(redactor.compiled_patterns)} patterns loaded"
            )

            if show_sources:
                output.append("")
                output.append("Pattern Types:")
                # Group by secret type
                types_seen = set()
                for compiled, strategy, secret_type in redactor.compiled_patterns:
                    if secret_type not in types_seen:
                        types_seen.add(secret_type)
                        source = "SERVER" if pattern_server else "DEFAULT"
                        output.append(
                            f"  • {secret_type:40s} [{source}] Strategy: {strategy}"
                        )

        except Exception as e:
            output.append(f"Error loading secret redaction configuration: {e}")

        output.append("")
        output.append("=" * 70)

        return "\n".join(output)

    def show_unicode_config(self, show_sources: bool = False) -> str:
        """
        Display Unicode attack detection configuration.

        Args:
            show_sources: Include pattern source attribution

        Returns:
            Formatted configuration display
        """
        output = []
        output.append("=" * 70)
        output.append("Unicode Attack Detection Configuration")
        output.append("=" * 70)
        output.append("")

        unicode_config = self.config.get("prompt_injection", {}).get(
            "unicode_detection", {}
        )

        # Basic settings
        enabled = unicode_config.get("enabled", True)
        detect_zero_width = unicode_config.get("detect_zero_width", True)
        detect_bidi = unicode_config.get("detect_bidi_override", True)
        detect_homoglyphs = unicode_config.get("detect_homoglyphs", True)

        output.append(f"Status: {'ENABLED' if enabled else 'DISABLED'}")
        output.append(f"Detect Zero-Width: {detect_zero_width}")
        output.append(f"Detect Bidi Override: {detect_bidi}")
        output.append(f"Detect Homoglyphs: {detect_homoglyphs}")
        output.append("")

        # Pattern server status
        pattern_server = unicode_config.get("pattern_server")
        if pattern_server:
            output.append("Pattern Server: CONFIGURED (homoglyphs only)")
            output.append(f"  URL: {pattern_server.get('url', 'N/A')}")
        else:
            output.append("Pattern Server: NOT CONFIGURED")

        output.append("")

        # Load effective patterns
        try:
            from ai_guardian.scanners.prompt_injection import (
                get_cached_unicode_detector,
            )

            detector = get_cached_unicode_detector(unicode_config)

            output.append(
                f"Zero-Width Characters: {len(detector._zero_width_set)} chars (IMMUTABLE)"
            )
            output.append(
                f"Bidi Override Characters: {len(detector._bidi_override_set)} chars (IMMUTABLE)"
            )
            output.append(f"Homoglyph Patterns: {len(detector._homoglyph_map)} pairs")

            if show_sources:
                output.append("")
                output.append("Sample Homoglyphs:")
                count = 0
                for homoglyph, latin in list(detector._homoglyph_map.items())[:10]:
                    source = "SERVER" if pattern_server else "DEFAULT"
                    output.append(f"  • '{homoglyph}' → '{latin}' [{source}]")
                    count += 1
                if len(detector._homoglyph_map) > 10:
                    output.append(f"  ... and {len(detector._homoglyph_map) - 10} more")

        except Exception as e:
            output.append(f"Error loading Unicode configuration: {e}")

        output.append("")
        output.append("=" * 70)

        return "\n".join(output)

    def show_config_scanner_config(self, show_sources: bool = False) -> str:
        """
        Display config file scanner configuration.

        Args:
            show_sources: Include pattern source attribution

        Returns:
            Formatted configuration display
        """
        output = []
        output.append("=" * 70)
        output.append("Config File Scanner Configuration")
        output.append("=" * 70)
        output.append("")

        scanner_config = self.config.get("config_file_scanning", {})

        # Basic settings
        enabled = scanner_config.get("enabled", True)
        action = scanner_config.get("action", "block")

        output.append(f"Status: {'ENABLED' if enabled else 'DISABLED'}")
        output.append(f"Action: {action}")
        output.append("")

        # Pattern server status
        pattern_server = scanner_config.get("pattern_server")
        if pattern_server:
            output.append("Pattern Server: CONFIGURED")
            output.append(f"  URL: {pattern_server.get('url', 'N/A')}")
        else:
            output.append("Pattern Server: NOT CONFIGURED")

        output.append("")

        # Load effective patterns
        try:
            from ai_guardian.scanners.config_scanner import ConfigFileScanner

            scanner = ConfigFileScanner(scanner_config)

            output.append(
                f"Exfiltration Patterns: {len(scanner._compiled_patterns)} patterns loaded"
            )

            if show_sources:
                output.append("")
                output.append("Patterns:")
                for pattern_info in scanner._compiled_patterns:
                    name = pattern_info.get("name", "unknown")
                    desc = pattern_info.get("description", "")
                    # Core patterns are immutable
                    if name in [
                        "curl_with_env_vars",
                        "wget_with_env_vars",
                        "env_piped_to_curl",
                        "printenv_exfil",
                        "file_exfil",
                        "base64_exfil",
                        "aws_s3_exfil",
                        "gcp_storage_exfil",
                    ]:
                        source = "IMMUTABLE"
                    elif pattern_server:
                        source = "SERVER"
                    else:
                        source = "DEFAULT"
                    output.append(f"  • {name:30s} [{source}] - {desc}")

        except Exception as e:
            output.append(f"Error loading config scanner configuration: {e}")

        output.append("")
        output.append("=" * 70)

        return "\n".join(output)

    def show_all(self, show_sources: bool = False) -> str:
        """
        Display all configuration sections.

        Args:
            show_sources: Include source attribution

        Returns:
            Formatted configuration display
        """
        output = []
        output.append(self.show_ssrf_config(show_sources=show_sources))
        output.append("")
        output.append(self.show_secret_config(show_sources=show_sources))
        output.append("")
        output.append(self.show_unicode_config(show_sources=show_sources))
        output.append("")
        output.append(self.show_config_scanner_config(show_sources=show_sources))
        return "\n".join(output)

    def export_json(self) -> str:
        """
        Export effective configuration as JSON.

        Returns:
            JSON string of effective configuration
        """
        effective_config = {
            "ssrf_protection": {},
            "secret_redaction": {},
            "unicode_detection": {},
            "config_file_scanning": {},
        }

        # SSRF
        try:
            from ai_guardian.scanners.ssrf import SSRFProtector

            ssrf_config = self.config.get("ssrf_protection", {})
            protector = SSRFProtector(ssrf_config)

            effective_config["ssrf_protection"] = {
                "enabled": is_feature_enabled(ssrf_config.get("enabled"), default=True),
                "action": ssrf_config.get("action", "block"),
                "blocked_ip_ranges": [
                    str(net) for net in protector._blocked_ip_networks
                ],
                "blocked_domains": sorted(protector._blocked_domains),
                "dangerous_schemes": protector.DANGEROUS_SCHEMES,
                "pattern_server_configured": "pattern_server" in ssrf_config,
            }
        except Exception as e:
            effective_config["ssrf_protection"]["error"] = str(e)

        # Secret Redaction
        try:
            from ai_guardian.scanners.secret_redactor import SecretRedactor

            secret_config = self.config.get("secret_redaction", {})

            # Validate action - reject "block" mode (removed in v1.5)
            action = secret_config.get("action", "warn")
            if action == "block":
                raise ValueError(
                    'secret_redaction.action="block" is no longer supported. '
                    'Valid values are: "warn", "log-only". '
                    "See documentation for migration options."
                )

            redactor = SecretRedactor(secret_config)

            effective_config["secret_redaction"] = {
                "enabled": secret_config.get("enabled", True),
                "action": action,
                "pattern_count": len(redactor.compiled_patterns),
                "pattern_server_configured": "pattern_server" in secret_config,
            }
        except Exception as e:
            effective_config["secret_redaction"]["error"] = str(e)

        # Unicode Detection
        try:
            from ai_guardian.scanners.prompt_injection import (
                get_cached_unicode_detector,
            )

            unicode_config = self.config.get("prompt_injection", {}).get(
                "unicode_detection", {}
            )
            detector = get_cached_unicode_detector(unicode_config)

            effective_config["unicode_detection"] = {
                "enabled": unicode_config.get("enabled", True),
                "zero_width_chars": len(detector._zero_width_set),
                "bidi_override_chars": len(detector._bidi_override_set),
                "homoglyph_patterns": len(detector._homoglyph_map),
                "pattern_server_configured": "pattern_server" in unicode_config,
            }
        except Exception as e:
            effective_config["unicode_detection"]["error"] = str(e)

        # Config Scanner
        try:
            from ai_guardian.scanners.config_scanner import ConfigFileScanner

            scanner_config = self.config.get("config_file_scanning", {})
            scanner = ConfigFileScanner(scanner_config)

            effective_config["config_file_scanning"] = {
                "enabled": scanner_config.get("enabled", True),
                "action": scanner_config.get("action", "block"),
                "pattern_count": len(scanner._compiled_patterns),
                "pattern_server_configured": "pattern_server" in scanner_config,
            }
        except Exception as e:
            effective_config["config_file_scanning"]["error"] = str(e)

        return json.dumps(effective_config, indent=2)
