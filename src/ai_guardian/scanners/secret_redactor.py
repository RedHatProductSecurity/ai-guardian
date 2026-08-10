# ai-guardian:begin-allow
"""
Secret Redactor - Redacts sensitive information from text while preserving context.

This module provides defense-in-depth secret redaction for tool outputs, allowing work
to continue while protecting credentials. Instead of blocking operations entirely when
secrets are detected, the redactor sanitizes outputs by masking sensitive data.

Part of Phase 4: Hermes Security Patterns Integration (Issue #197)
NEW in v1.5.0: Optional pattern server support for enterprise secret pattern management.
NEW in v1.6.0: PII detection for GDPR/CCPA compliance (Issue #262).
"""

# ai-guardian:end-allow

import re
import logging
from typing import List, Dict, Tuple, Optional

from ai_guardian.config.utils import validate_regex_pattern, is_feature_enabled
from ai_guardian import allowlist_utils
from ai_guardian.patterns import load_bundled_rules
from ai_guardian.patterns.validators import luhn_check, iban_check, VALID_CC_PREFIXES

logger = logging.getLogger(__name__)


class SecretRedactor:
    """
    Redacts secrets from text using multiple masking strategies.

    Supports 35+ secret types including API keys, tokens, credentials, and private keys.
    Uses different masking strategies to preserve debugging context while hiding secrets.
    """

    # All secret patterns are loaded from patterns/data/secrets.toml (Issue #841).
    # PII patterns are loaded from patterns/data/pii.toml.
    # Hardcoded PATTERNS and PII_PATTERNS removed — TOML is the sole source.

    @staticmethod
    def _extract_regex_flags(pattern_info: Dict) -> int:
        """Extract regex flags from a pattern dict, matching toml_parser.py logic."""
        flags = 0
        raw_flags = pattern_info.get("flags", "")
        if "i" in raw_flags or pattern_info.get("case_insensitive", False):
            flags |= re.IGNORECASE
        if "m" in raw_flags or pattern_info.get("multiline", False):
            flags |= re.MULTILINE
        if "s" in raw_flags or pattern_info.get("dotall", False):
            flags |= re.DOTALL
        return flags

    def __init__(
        self,
        config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        pii_only: bool = False,
    ):
        """
        Initialize the SecretRedactor.

        Args:
            config: Optional configuration dict with:
                - enabled: bool - whether redaction is enabled (default: True)
                - action: str - "log-only" or "warn" (default: "warn")
                - preserve_format: bool - whether to preserve format in redactions (default: True)
                - additional_patterns: List[Dict] - custom patterns to add
                - log_redactions: bool - whether to log redaction events (default: True)
                - pattern_server: Dict - pattern server configuration (NEW in v1.5.0)
            pii_config: Optional PII scanning configuration dict with:
                - enabled: bool - whether PII detection is enabled (default: True)
                - pii_types: List[str] - PII types to detect (default: all)
                - action: str - "redact", "log-only", or "block" (default: "redact")
        """
        self.config = config or {}
        self.pii_config = pii_config or {}
        self.enabled = self.config.get("enabled", True)
        self.action = self.config.get("action", "warn")
        self.preserve_format = self.config.get("preserve_format", True)
        self.log_redactions = self.config.get("log_redactions", True)

        self.pii_only = pii_only

        # Load patterns using pattern loader if pattern_server configured
        pattern_server_config = self.config.get("pattern_server")
        if pii_only:
            # Skip all secret patterns, only PII patterns will be loaded below
            patterns_to_use = []
        elif pattern_server_config:
            logger.debug("Secret Redaction: Loading patterns via pattern server")
            patterns_to_use = self._load_patterns_via_server(pattern_server_config)
        else:
            # Load from bundled TOML file (primary source)
            patterns_to_use = self._load_patterns_from_toml()

        # Compile all patterns for performance
        self.compiled_patterns = []
        for pattern_info in patterns_to_use:
            try:
                # Handle both tuple format (hardcoded) and dict format (TOML/pattern server)
                if isinstance(pattern_info, tuple):
                    pattern, strategy, secret_type = pattern_info
                    flags = re.IGNORECASE | re.MULTILINE
                else:
                    pattern = pattern_info.get("regex") or pattern_info.get("pattern")
                    strategy = pattern_info.get("strategy", "preserve_prefix_suffix")
                    secret_type = pattern_info.get("secret_type", "Unknown Secret")
                    flags = self._extract_regex_flags(pattern_info)

                # Validate pattern before compilation (protects against ReDoS from pattern server)
                if not validate_regex_pattern(pattern):
                    logger.error(
                        f"Pattern validation failed for {secret_type} (potential ReDoS or invalid syntax) - skipping"
                    )
                    continue

                compiled = re.compile(pattern, flags)
                self.compiled_patterns.append((compiled, strategy, secret_type))
            except (re.error, KeyError, TypeError) as e:
                logger.warning(
                    f"Failed to compile pattern for {secret_type if isinstance(pattern_info, tuple) else pattern_info.get('secret_type', 'unknown')}: {e}"
                )

        # Add custom patterns from local config (always additive, skip in pii_only mode)
        additional = [] if pii_only else self.config.get("additional_patterns", [])
        for custom in additional:
            try:
                pattern = custom.get("pattern") or custom.get("regex")
                strategy = custom.get("strategy", "preserve_prefix_suffix")
                secret_type = custom.get("type") or custom.get(
                    "secret_type", "Custom Secret"
                )

                # Validate pattern before compilation (protects against ReDoS)
                if not validate_regex_pattern(pattern):
                    logger.error(
                        f"Custom pattern validation failed for {secret_type} (potential ReDoS or invalid syntax) - skipping"
                    )
                    continue

                compiled = re.compile(pattern, self._extract_regex_flags(custom))
                self.compiled_patterns.append((compiled, strategy, secret_type))
                logger.debug(f"Added custom pattern: {secret_type}")
            except (re.error, KeyError, TypeError) as e:
                logger.warning(f"Failed to compile custom pattern: {e}")

        # Load PII patterns if enabled (Issue #262, pattern server support #644)
        if is_feature_enabled(self.pii_config.get("enabled"), default=False):
            pii_types = self.pii_config.get(
                "pii_types",
                ["ssn", "credit_card", "phone", "us_passport", "iban", "intl_phone"],
            )
            pii_pattern_server = self.pii_config.get("pattern_server")
            if pii_pattern_server:
                pii_patterns = self._load_pii_patterns_via_server(pii_pattern_server)
            else:
                pii_patterns = self._load_pii_patterns()
            for pii_type in pii_types:
                if pii_type in pii_patterns:
                    pattern, strategy, label = pii_patterns[pii_type]
                    try:
                        if not validate_regex_pattern(pattern):
                            logger.error(
                                f"PII pattern validation failed for {label} - skipping"
                            )
                            continue
                        compiled = re.compile(pattern)
                        self.compiled_patterns.append((compiled, strategy, label))
                        logger.debug(f"Added PII pattern: {label}")
                    except re.error as e:
                        logger.warning(
                            f"Failed to compile PII pattern for {label}: {e}"
                        )
            logger.debug(f"PII Detection: Loaded patterns for {pii_types}")

        # Compile PII allowlist patterns (Issue #357)
        raw_allowlist = self.pii_config.get("allowlist_patterns", [])
        self._compiled_pii_allowlist = allowlist_utils.compile_allowlist(raw_allowlist)
        if self._compiled_pii_allowlist:
            logger.debug(
                f"PII Allowlist: {len(self._compiled_pii_allowlist)} active patterns"
            )

        logger.debug(f"Secret Redaction: Loaded {len(self.compiled_patterns)} patterns")

    def _load_patterns_from_toml(self) -> List:
        """Load secret patterns from bundled TOML file (Issue #841)."""

        def _transform(raw_rules):
            return [
                {
                    "regex": raw.get("regex", ""),
                    "strategy": raw.get("redaction_strategy", "preserve_prefix_suffix"),
                    "secret_type": raw.get("description", ""),
                    "flags": raw.get("flags", ""),
                    "case_insensitive": raw.get("case_insensitive", False),
                    "multiline": raw.get("multiline", False),
                    "dotall": raw.get("dotall", False),
                }
                for raw in raw_rules
                if raw.get("match_type", "regex") == "regex"
            ]

        return load_bundled_rules("secrets", _transform, [], "Secret Redaction")

    def _load_pii_patterns(self) -> Dict:
        """Load PII patterns from bundled TOML file (Issue #841)."""

        def _transform(raw_rules):
            result = {}
            for raw in raw_rules:
                pii_type = raw.get("pii_type")
                if pii_type and raw.get("match_type", "regex") == "regex":
                    result[pii_type] = (
                        raw.get("regex", ""),
                        raw.get("redaction_strategy", "full_redact"),
                        raw.get("description", ""),
                    )
            return result

        return load_bundled_rules("pii", _transform, {}, "PII Detection")

    def _load_pii_patterns_via_server(self, pattern_server_config: Dict) -> Dict:
        """Load PII patterns via pattern server with fallback to bundled TOML."""
        try:
            from ai_guardian.patterns.loader import PIIPatternLoader

            loader = PIIPatternLoader()
            merged = loader.load_patterns(
                pattern_server_config=pattern_server_config,
                local_config=self.pii_config,
            )

            rules = merged.get("rules", [])
            result = {}
            for raw in rules:
                pii_type = raw.get("pii_type")
                if pii_type and raw.get("match_type", "regex") == "regex":
                    result[pii_type] = (
                        raw.get("regex", ""),
                        raw.get("redaction_strategy", "full_redact"),
                        raw.get("description", ""),
                    )

            if result:
                logger.info(
                    f"PII Detection: Loaded {len(result)} patterns via pattern server"
                )
                return result

            logger.warning(
                "PII pattern server returned no patterns, falling back to bundled TOML"
            )
            return self._load_pii_patterns()

        except ImportError:
            logger.error(
                "pattern_loader module not available, falling back to bundled TOML"
            )
            return self._load_pii_patterns()
        except Exception as e:
            logger.error(f"Error loading PII patterns from pattern server: {e}")
            return self._load_pii_patterns()

    def _load_patterns_via_server(self, pattern_server_config: Dict) -> List:
        """
        Load patterns via pattern server with fallback to defaults.

        Args:
            pattern_server_config: Pattern server configuration

        Returns:
            List of patterns (either from server or defaults)
        """
        try:
            from ai_guardian.patterns.loader import SecretPatternLoader

            loader = SecretPatternLoader()
            merged_patterns = loader.load_patterns(
                pattern_server_config=pattern_server_config, local_config=self.config
            )

            # Convert pattern loader format to list of dicts
            server_patterns = merged_patterns.get("patterns", [])

            if server_patterns:
                logger.info(
                    f"Loaded {len(server_patterns)} patterns from pattern server/cache/defaults"
                )
                return server_patterns
            else:
                logger.warning(
                    "Pattern server returned no patterns, falling back to bundled TOML"
                )
                return self._load_patterns_from_toml()

        except ImportError:
            logger.error(
                "pattern_loader module not available, falling back to bundled TOML"
            )
            return self._load_patterns_from_toml()
        except Exception as e:
            logger.error(f"Error loading patterns from pattern server: {e}")
            return self._load_patterns_from_toml()

    def redact(self, text: str) -> Dict:
        """
        Redact secrets from text.

        Args:
            text: Input text that may contain secrets

        Returns:
            Dict with:
                - redacted_text: str - Text with secrets redacted
                - redactions: List[Dict] - List of redaction metadata
                - original_length: int - Length of original text
                - redacted_length: int - Length of redacted text
        """
        if not self.enabled or not text:
            return {
                "redacted_text": text,
                "redactions": [],
                "original_length": len(text) if text else 0,
                "redacted_length": len(text) if text else 0,
            }

        redactions = []

        # Track claimed regions in original-text coordinates
        claimed_regions = []

        # Phase 1: Collect ALL matches from original text across all patterns.
        # Always search the original text so positions are in original coordinates.
        all_pending = []

        for compiled_pattern, strategy, secret_type in self.compiled_patterns:
            matches = list(compiled_pattern.finditer(text))

            for match in matches:
                start, end = match.span()

                if any(
                    start < r_end and r_start < end
                    for r_start, r_end in claimed_regions
                ):
                    continue

                original = match.group(0)

                if self._compiled_pii_allowlist and allowlist_utils.check_allowlist(
                    original, self._compiled_pii_allowlist
                ):
                    logger.debug(f"PII match allowlisted: {secret_type}")
                    continue

                redacted, metadata = self._apply_strategy(match, strategy, secret_type)

                if redacted is None:
                    continue

                all_pending.append(
                    (start, end, original, redacted, metadata, strategy, secret_type)
                )
                claimed_regions.append((start, end))

        # Phase 2: Record metadata with positions from original text
        for (
            start,
            end,
            original,
            redacted,
            metadata,
            strategy,
            secret_type,
        ) in all_pending:
            line_start = text.rfind("\n", 0, start) + 1
            redactions.append(
                {
                    "type": secret_type,
                    "position": start,
                    "line_number": text[:start].count("\n") + 1,
                    "column": start - line_start + 1,
                    "original_length": len(original),
                    "redacted_length": len(redacted),
                    "strategy": strategy,
                    **metadata,
                }
            )

            if self.log_redactions:
                logger.info(
                    f"Redacted {secret_type} at position {start} using {strategy}"
                )

        # Phase 3: Build redacted text in a single forward pass
        segments = []
        pos = 0
        for (
            start,
            end,
            _original,
            redacted,
            _metadata,
            _strategy,
            _secret_type,
        ) in sorted(all_pending, key=lambda x: x[0]):
            segments.append(text[pos:start])
            segments.append(redacted)
            pos = end
        segments.append(text[pos:])
        redacted_text = "".join(segments)

        return {
            "redacted_text": redacted_text,
            "redactions": redactions,
            "original_length": len(text),
            "redacted_length": len(redacted_text),
        }

    _STRATEGY_DISPATCH = {
        "env_assignment": "_redact_env_assignment",
        "json_field": "_redact_json_field",
        "auth_header": "_redact_auth_header",
        "header_value": "_redact_header_value",
        "connection_string": "_redact_connection_string",
        "aws_secret": "_redact_aws_secret",
        "yaml_password": "_redact_yaml_password",
        "context_secret": "_redact_context_secret",
        "credit_card": "_redact_credit_card",
        "pii_email": "_redact_pii_email",
        "iban": "_redact_iban",
        "canada_sin": "_redact_canada_sin",
        "aadhaar": "_redact_aadhaar",
    }

    def _apply_strategy(
        self, match: re.Match, strategy: str, secret_type: str
    ) -> Tuple[str, Dict]:
        """Apply a masking strategy to a matched secret."""
        if strategy == "full_redact":
            return self._full_redact(secret_type)
        if strategy == "private_key":
            return ("[REDACTED PRIVATE KEY]", {"method": "full"})
        method_name = self._STRATEGY_DISPATCH.get(strategy)
        if method_name:
            return getattr(self, method_name)(match)
        return self._preserve_prefix_suffix(match)

    @staticmethod
    def _truncate_secret(secret: str) -> Tuple[str, bool]:
        """Mask a secret string, preserving prefix/suffix for long values.

        Returns (masked_string, was_short).
        """
        if len(secret) <= 18:
            return "***", True
        prefix_len = min(6, len(secret) // 3)
        suffix_len = min(4, len(secret) // 4)
        return f"{secret[:prefix_len]}...{secret[-suffix_len:]}", False

    def _preserve_prefix_suffix(self, match: re.Match) -> Tuple[str, Dict]:
        """Preserve first 6 and last 4 characters, redact middle."""
        secret = (
            match.group(1)
            if match.lastindex and match.lastindex >= 1
            else match.group(0)
        )
        redacted, was_short = self._truncate_secret(secret)
        if was_short:
            return (redacted, {"method": "short"})
        prefix_len = min(6, len(secret) // 3)
        suffix_len = min(4, len(secret) // 4)
        return (
            redacted,
            {
                "method": "preserve_prefix_suffix",
                "preserved_chars": prefix_len + suffix_len,
            },
        )

    def _full_redact(self, secret_type: str) -> Tuple[str, Dict]:
        """
        Completely redact the secret with a placeholder.

        Example: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
                 -> [REDACTED AWS SECRET KEY]
        """
        placeholder = f"[HIDDEN {secret_type.upper()}]"
        return (placeholder, {"method": "full"})

    def _redact_env_assignment(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact environment variable value but keep variable name.

        Example: AWS_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
                 -> AWS_SECRET_KEY=[HIDDEN]
        """
        var_name = match.group(1)
        # Check if there's a quote group
        if match.lastindex >= 3:
            # Has quote marks
            quote = match.group(2) if match.group(2) else ""
            redacted = f"{var_name}={quote}[HIDDEN]{quote}"
        else:
            redacted = f"{var_name}=[HIDDEN]"

        return (redacted, {"method": "env_var", "var_name": var_name})

    def _redact_json_field(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact JSON field value but preserve structure.

        Example: {"api_key": "sk-proj-abc123..."}
                 -> {"api_key": "[HIDDEN]"}
        """
        field_name = match.group(1)
        redacted = f'"{field_name}": "[HIDDEN]"'

        return (redacted, {"method": "json", "field_name": field_name})

    def _redact_auth_header(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact Authorization Bearer token but keep header name.

        Example: Authorization: Bearer sk-proj-abc123...
                 -> Authorization: Bearer [HIDDEN]
        """
        header_prefix = match.group(1)
        token = match.group(2)

        # For long tokens, preserve prefix/suffix
        if len(token) > 18:
            redacted_token = f"{token[:6]}...{token[-4:]}"
        else:
            redacted_token = "[HIDDEN]"

        redacted = f"{header_prefix}{redacted_token}"

        return (redacted, {"method": "auth_header"})

    def _redact_header_value(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact HTTP header value but keep header name.

        Example: X-API-Key: abc123def456
                 -> X-API-Key: [HIDDEN]
        """
        header_name = match.group(1)
        redacted = f"{header_name}[HIDDEN]"

        return (redacted, {"method": "header"})

    def _redact_connection_string(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact credentials in connection string but preserve endpoint.

        Example: mongodb://user:MySecretPass@db.example.com:27017/mydb
                 -> mongodb://user:[HIDDEN]@db.example.com:27017/mydb
        """
        prefix = match.group(1)  # protocol://user:
        # password is group(2)
        suffix = match.group(3)  # @host:port/db

        redacted = f"{prefix}[HIDDEN]{suffix}"

        return (redacted, {"method": "connection_string"})

    def _redact_aws_secret(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact AWS secret access key.

        Example: aws_secret_access_key = wJalrXUtnFEMI...
                 -> aws_secret_access_key = [HIDDEN]
        """
        prefix = match.group(1)  # "aws_secret_access_key = "
        redacted = f"{prefix}[HIDDEN]"

        return (redacted, {"method": "aws_secret"})

    def _redact_yaml_password(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact password in YAML/config format.

        Example: password: MySecretPass123
                 -> password: [HIDDEN]
        """
        prefix = match.group(1)  # "password: "
        redacted = f"{prefix}[HIDDEN]"

        return (redacted, {"method": "yaml_password"})

    def _redact_context_secret(self, match: re.Match) -> Tuple[str, Dict]:
        """Redact secret with context keyword prefix, preserving prefix/suffix."""
        context_prefix = match.group(1)
        secret = match.group(2)
        redacted_secret, _ = self._truncate_secret(secret)
        return (
            f"{context_prefix}{redacted_secret}",
            {"method": "context_secret", "context": context_prefix.strip()},
        )

    def _redact_credit_card(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact credit card number after Luhn and IIN/BIN prefix validation.

        Returns (None, None) if the number fails validation (not a real CC).
        """
        number = match.group(0)
        digits_only = re.sub(r"[- ]", "", number)
        if not luhn_check(digits_only):
            return (None, None)
        if not digits_only.startswith(VALID_CC_PREFIXES):
            return (None, None)
        last_four = digits_only[-4:]
        return (
            f"[HIDDEN CREDIT CARD ****{last_four}]",
            {"method": "credit_card", "last_four": last_four},
        )

    def _redact_pii_email(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact email address, preserving the domain.

        Example: john.doe@example.com -> [HIDDEN]@example.com
        """
        email = match.group(0)
        at_idx = email.rfind("@")
        domain = email[at_idx + 1 :]
        return (f"[HIDDEN]@{domain}", {"method": "pii_email", "domain": domain})

    def _redact_iban(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact IBAN after mod-97 validation.

        Returns (None, None) if the string fails IBAN check.
        """
        iban = match.group(0)
        if not iban_check(iban):
            return (None, None)
        country = iban[:2]
        last_four = iban[-4:]
        return (
            f"[HIDDEN IBAN {country}****{last_four}]",
            {"method": "iban", "country": country},
        )

    def _redact_canada_sin(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact Canadian SIN after Luhn validation.

        Returns (None, None) if the number fails Luhn check.
        """
        sin = match.group(0)
        if not luhn_check(sin, min_digits=9, max_digits=9):
            return (None, None)
        return ("[HIDDEN Canadian SIN]", {"method": "canada_sin"})

    def _redact_aadhaar(self, match: re.Match) -> Tuple[str, Dict]:
        """
        Redact Indian Aadhaar number after validation.

        Returns (None, None) if the number fails validation (issue #876).
        Real Aadhaar numbers start with 2-9 and aren't all-identical digits.
        """
        number = match.group(0)
        digits = re.sub(r"[- ]", "", number)
        if digits[0] in ("0", "1"):
            return (None, None)
        if len(set(digits)) == 1:
            return (None, None)
        return ("[REDACTED Indian Aadhaar Number]", {"method": "full"})
