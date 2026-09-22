#!/usr/bin/env python3
"""
Pattern Server Integration

Optional integration with external pattern servers for enhanced security pattern detection.
Fetches and caches pattern configurations from a configured server.

Supports multiple pattern types:
- Gitleaks secret detection patterns (original)
- SSRF protection patterns (NEW in v1.5.0)
- Unicode attack detection patterns (NEW in v1.5.0)
- Config file scanner patterns (NEW in v1.5.0)
- Secret redaction patterns (NEW in v1.5.0)

This is a generic implementation that can work with any pattern server
implementing a compatible API.
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from ai_guardian.config.utils import get_cache_dir, is_feature_enabled

logger = logging.getLogger(__name__)

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.debug("requests library not available - pattern server disabled")

# TOML parsing support (Python 3.11+ has tomllib built-in)
try:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore
    HAS_TOML = True
except ImportError:
    HAS_TOML = False
    logger.debug("TOML library not available - pattern parsing disabled")


class PatternServerClient:
    """
    Client for fetching security patterns from a pattern server.

    Supports:
    - Bearer token authentication
    - Pattern caching with configurable TTL
    - Auto-refresh on expiration
    - Fail-safe fallback to cached patterns
    - Multiple pattern types (gitleaks, ssrf, unicode, config-exfil, secrets)

    NEW in v1.5.0: Support for multiple pattern types beyond Gitleaks.
    """

    # Default endpoints for different pattern types
    DEFAULT_ENDPOINTS = {
        "gitleaks": "/patterns/gitleaks/8.18.1",
        "ssrf": "/patterns/ssrf/v1",
        "unicode": "/patterns/unicode/v1",
        "config-exfil": "/patterns/config-exfil/v1",
        "secrets": "/patterns/secrets/v1",
    }

    # Default cache filenames for different pattern types
    DEFAULT_CACHE_FILES = {
        "gitleaks": "patterns.toml",
        "ssrf": "ssrf-patterns.toml",
        "unicode": "unicode-patterns.toml",
        "config-exfil": "config-exfil-patterns.toml",
        "secrets": "secrets-patterns.toml",
    }

    def __init__(self, config: dict, pattern_type: str = "gitleaks"):
        """
        Initialize pattern server client.

        Args:
            config: Pattern server configuration from ai-guardian.json
            pattern_type: Type of patterns to fetch (gitleaks, ssrf, unicode, config-exfil, secrets)

        NEW in v1.7.0: 'enabled' field is deprecated. Presence of config = enabled.
        NEW in v1.5.0: 'pattern_type' parameter for multi-pattern support.
        Still supports 'enabled' field for backward compatibility (with warning).
        """
        self.pattern_type = pattern_type

        # Store enabled config (supports both boolean and time-based formats)
        # Default to True since config presence = enabled (v1.7.0+)
        # Only False if explicitly set (backward compatibility)
        self.enabled_config = config.get("enabled", True)
        self.base_url: Optional[str] = config.get("url")

        # Get endpoint - use config value or default for pattern type
        default_endpoint = self.DEFAULT_ENDPOINTS.get(
            pattern_type, f"/patterns/{pattern_type}/v1"
        )
        self.patterns_endpoint = config.get("patterns_endpoint", default_endpoint)

        # Warning configuration - enabled by default, can be disabled
        self.warn_on_failure = config.get("warn_on_failure", True)

        # Auth configuration
        auth_config = config.get("auth", {})
        self.token_env = auth_config.get("token_env", "AI_GUARDIAN_PATTERN_TOKEN")
        self.token_file = Path(
            auth_config.get("token_file", "~/.config/ai-guardian/pattern-token")
        ).expanduser()

        # Cache configuration
        cache_config = config.get("cache", {})

        # Get cache path - use config value or default for pattern type
        default_cache_file = self.DEFAULT_CACHE_FILES.get(
            pattern_type, f"{pattern_type}-patterns.toml"
        )
        default_cache_path = str(get_cache_dir() / default_cache_file)
        self.cache_path = Path(
            cache_config.get("path", default_cache_path)
        ).expanduser()

        self.refresh_interval = (
            cache_config.get("refresh_interval_hours", 12) * 3600
        )  # hours to seconds
        self.expire_after = (
            cache_config.get("expire_after_hours", 168) * 3600
        )  # hours to seconds

    def get_patterns_path(self) -> Optional[Path]:
        """
        Get path to patterns file, fetching from server if needed.

        Returns:
            Path to patterns file, or None if unavailable

        NOTE: This method returns the path to the TOML file for consumers that
        parse it themselves (e.g., Gitleaks). For parsed patterns, use get_patterns().
        """
        # Check if pattern server is enabled (supports time-based disabling)
        if not is_feature_enabled(
            self.enabled_config, datetime.now(timezone.utc), default=False
        ):
            logger.debug("Pattern server is disabled or temporarily disabled")
            return None

        if not HAS_REQUESTS:
            logger.warning("Pattern server enabled but requests library not available")
            return None

        if not self.base_url:
            logger.warning("Pattern server enabled but no URL configured")
            return None

        # Check if patterns need refresh
        if self._needs_refresh():
            logger.debug("Patterns need refresh, fetching from server")
            if not self._fetch_patterns():
                # Fetch failed, check if cached patterns are still usable
                if self._is_expired():
                    logger.error("Cached patterns expired and refresh failed")
                    return None
                logger.warning("Pattern refresh failed, using cached patterns")

        # Return cached patterns if they exist
        if self.cache_path.exists():
            return self.cache_path

        return None

    def get_patterns(self) -> Optional[Dict[str, Any]]:
        """
        Get patterns as a parsed dictionary, fetching from server if needed.

        Returns:
            Parsed TOML patterns as dict, or None if unavailable

        NEW in v1.5.0: Returns parsed patterns for use in Python code.
        Implements fallback chain: server → cache → None
        """
        # Get path to patterns file (handles fetching/caching)
        patterns_path = self.get_patterns_path()
        if not patterns_path:
            return None

        # Parse TOML file
        if not HAS_TOML:
            logger.warning(
                f"TOML library not available, cannot parse {self.pattern_type} patterns"
            )
            return None

        try:
            # Read and parse TOML
            with open(patterns_path, "rb") as f:
                patterns = tomllib.load(f)

            logger.debug(
                f"Successfully parsed {self.pattern_type} patterns from {patterns_path}"
            )
            return patterns

        except Exception as e:
            logger.error(
                f"Error parsing {self.pattern_type} patterns from {patterns_path}: {e}"
            )
            import traceback

            logger.debug(traceback.format_exc())
            return None

    def _needs_refresh(self) -> bool:
        """Check if patterns need to be refreshed."""
        if not self.cache_path.exists():
            return True

        # Check file age
        file_age = time.time() - self.cache_path.stat().st_mtime
        return file_age > self.refresh_interval

    def _is_expired(self) -> bool:
        """Check if cached patterns are expired (too old to use)."""
        if not self.cache_path.exists():
            return True

        file_age = time.time() - self.cache_path.stat().st_mtime
        return file_age > self.expire_after

    def _get_auth_token(self) -> Optional[str]:
        """
        Get authentication token from environment or file.

        Returns:
            Bearer token or None if not found
        """
        # Try environment variable first
        token = os.environ.get(self.token_env)
        if token:
            logger.debug(f"Using auth token from {self.token_env}")
            return token

        # Try token file
        if self.token_file.exists():
            try:
                token = self.token_file.read_text().strip()
                if token:
                    logger.debug(f"Using auth token from {self.token_file}")
                    return token
            except Exception as e:
                logger.warning(f"Error reading token file {self.token_file}: {e}")

        return None

    def _fetch_patterns(self) -> bool:
        """
        Fetch patterns from the pattern server.

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.base_url:
                logger.error("Pattern server enabled but no URL configured")
                return False

            # Build URL
            url = f"{self.base_url.rstrip('/')}{self.patterns_endpoint}"

            # Prepare headers
            headers = {
                "User-Agent": "ai-guardian/1.0.0",
            }

            # Get authentication token (optional)
            token = self._get_auth_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                logger.debug("Using authentication for pattern server")
            else:
                logger.debug(
                    "No authentication token - attempting unauthenticated request"
                )

            # Security: Enforce HTTPS for pattern server (reject http://)
            if url.startswith("http://"):
                logger.error(
                    f"HTTP URLs not allowed for pattern server (use HTTPS): {url}"
                )
                return False

            logger.info(
                f"Fetching {self.pattern_type} patterns from pattern server: {self.base_url}"
            )

            # Fetch patterns with TLS verification enabled
            response = requests.get(url, headers=headers, timeout=10, verify=True)

            if response.status_code == 401:
                if token:
                    logger.error(
                        "Pattern server authentication failed (401 Unauthorized)"
                    )
                    logger.info("Please check your authentication token")
                else:
                    logger.error(
                        "Pattern server requires authentication but no token configured"
                    )
                    logger.info(
                        f"Set token via environment variable: export {self.token_env}='your-token'"
                    )
                    logger.info(f"Or save to file: {self.token_file}")
                return False
            elif response.status_code == 403:
                logger.error("Pattern server access forbidden (403 Forbidden)")
                return False
            elif response.status_code == 404:
                logger.error(f"Patterns not found (404): {url}")
                return False
            elif response.status_code != 200:
                logger.error(f"Pattern server returned error: {response.status_code}")
                return False

            # Validate TOML before caching (prevents caching HTML error pages or invalid content)
            try:
                tomllib.loads(response.text)
            except tomllib.TOMLDecodeError as e:
                logger.error(f"Pattern server returned invalid TOML: {e}")
                return False

            # Save patterns to cache
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(response.text)

            logger.info(
                f"Successfully fetched and cached {self.pattern_type} patterns to {self.cache_path}"
            )
            return True

        except requests.exceptions.Timeout:
            logger.error("Timeout fetching patterns from server")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error fetching patterns: {e}")
            return False
        except Exception as e:
            logger.error(f"Error fetching patterns: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return False

    def save_token(self, token: str) -> bool:
        """
        Save authentication token to file.

        Args:
            token: Bearer token to save

        Returns:
            True if successful, False otherwise
        """
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(token)
            self.token_file.chmod(0o600)  # Restrict permissions
            logger.info(f"Token saved to {self.token_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving token: {e}")
            return False
