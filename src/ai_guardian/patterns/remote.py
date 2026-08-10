#!/usr/bin/env python3
"""
Remote Configuration Fetcher

Handles fetching and caching remote configuration files from HTTP/HTTPS URLs.

Features:
- HTTP/HTTPS fetching with authentication
- File-based caching with TTL
- Refresh interval vs expiration logic
- Environment variable authentication
- Fail-open on errors
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.warning(
        "requests library not installed - HTTP/HTTPS remote configs not available"
    )

try:
    # Python 3.11+ has tomllib built-in
    import tomllib as toml

    HAS_TOML = True
except ImportError:
    try:
        # Python < 3.11 uses tomli (backport)
        import tomli as toml

        HAS_TOML = True
    except ImportError:
        HAS_TOML = False


class RemoteFetcher:
    """
    Fetch and cache remote configuration files.

    Supports:
    - HTTP/HTTPS URLs with authentication
    - File-based caching with TTL
    - Refresh interval vs expiration logic
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize remote fetcher.

        Args:
            cache_dir: Optional cache directory. If None, uses XDG_CACHE_HOME.
        """
        if cache_dir is None:
            cache_home = os.environ.get(
                "XDG_CACHE_HOME", os.path.expanduser("~/.cache")
            )
            cache_dir = Path(cache_home) / "ai-guardian" / "remote-configs"

        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_config(
        self,
        url: str,
        refresh_interval_hours: Optional[int] = None,
        expire_after_hours: Optional[int] = None,
        headers: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        Fetch remote configuration with caching.

        Local file paths bypass caching (always read fresh).
        HTTPS URLs use cache with TTL logic.

        Args:
            url: URL or local file path to fetch
            refresh_interval_hours: How often to check for updates (staleness threshold).
                                   If None, reads from AI_GUARDIAN_REFRESH_INTERVAL_HOURS env var (default: 12)
            expire_after_hours: How long to use stale cache if refresh fails (expiration threshold).
                               If None, reads from AI_GUARDIAN_EXPIRE_AFTER_HOURS env var (default: 168)
            headers: Optional custom headers for authentication

        Returns:
            dict or None: Parsed configuration or None if failed
        """
        # Local files: no caching, always read fresh
        is_local = (
            url.startswith("file://")
            or url.startswith("/")
            or url.startswith("~")
            or (len(url) >= 3 and url[1] == ":" and url[2] in ("/", "\\"))
        )
        if is_local:
            logger.debug(f"Local file detected, bypassing cache: {url}")
            return self._fetch_from_local_file(url)

        if not HAS_REQUESTS:
            logger.warning(f"Cannot fetch {url}: requests library not installed")
            return None

        # Read from environment variables if not provided
        if refresh_interval_hours is None:
            refresh_interval_hours = int(
                os.environ.get("AI_GUARDIAN_REFRESH_INTERVAL_HOURS", "12")
            )
        if expire_after_hours is None:
            expire_after_hours = int(
                os.environ.get("AI_GUARDIAN_EXPIRE_AFTER_HOURS", "168")
            )

        # Check cache first
        cached_config, cache_age_hours = self._get_cached_config(url)

        if cached_config is not None:
            # Check if cache is fresh (within refresh interval)
            if cache_age_hours < refresh_interval_hours:
                logger.debug(
                    f"Using fresh cache for {url} (age: {cache_age_hours:.1f}h)"
                )
                return cached_config

            # Cache is stale - try to refresh
            logger.info(
                f"Cache stale for {url} (age: {cache_age_hours:.1f}h), attempting refresh..."
            )
            fresh_config = self._fetch_from_url(url, headers)

            if fresh_config is not None:
                # Refresh succeeded
                self._save_to_cache(url, fresh_config)
                logger.info(f"Successfully refreshed {url}")
                return fresh_config

            # Refresh failed - check if cache is still valid (not expired)
            if cache_age_hours < expire_after_hours:
                logger.warning(
                    f"Failed to refresh {url}, using stale cache "
                    f"(age: {cache_age_hours:.1f}h < {expire_after_hours}h)"
                )
                return cached_config
            else:
                logger.error(
                    f"Cache expired for {url} "
                    f"(age: {cache_age_hours:.1f}h >= {expire_after_hours}h) "
                    f"and refresh failed - fail-open"
                )
                return None

        # No cache - fetch from URL
        logger.info(f"No cache for {url}, fetching...")
        config = self._fetch_from_url(url, headers)

        if config is not None:
            self._save_to_cache(url, config)
            logger.info(f"Successfully fetched and cached {url}")
        else:
            logger.error(f"Failed to fetch {url} - fail-open")

        return config

    def _fetch_from_local_file(self, path: str) -> Optional[Dict]:
        """
        Fetch configuration from local file path.

        Supports:
        - file:// URLs (e.g., file:///etc/ai-guardian/config.toml)
        - Absolute paths (e.g., /etc/ai-guardian/config.toml)
        - Tilde expansion (e.g., ~/config.toml, ~user/config.toml)

        Args:
            path: Local file path (file://, absolute, or tilde)

        Returns:
            dict or None: Parsed configuration or None if failed
        """
        try:
            # Normalize path
            if path.startswith("file://"):
                # file:///etc/config.toml -> /etc/config.toml
                actual_path = path[7:]  # Remove "file://"
            else:
                actual_path = path

            # Expand tilde (~/ or ~user/)
            actual_path = os.path.expanduser(actual_path)

            # Convert to Path object
            file_path = Path(actual_path)

            # Security: Resolve to absolute path and check it exists
            try:
                file_path = file_path.resolve(strict=True)
            except (FileNotFoundError, RuntimeError):
                logger.error(f"Local config file not found: {path} -> {actual_path}")
                return None

            # Security: Check file is readable
            if not file_path.is_file():
                logger.error(f"Path is not a regular file: {file_path}")
                return None

            if not os.access(file_path, os.R_OK):
                logger.error(f"Cannot read file (permission denied): {file_path}")
                return None

            # Log warning for symlinks (but still follow them)
            original_path = Path(actual_path)
            if original_path.is_symlink():
                logger.warning(f"Following symlink: {path} -> {file_path}")

            # Read and parse file
            logger.debug(f"Reading local config: {file_path}")
            content = file_path.read_text(encoding="utf-8")

            # Try JSON first, then TOML
            config = None
            try:
                config = json.loads(content)
                logger.debug(f"Successfully parsed as JSON: {file_path}")
            except json.JSONDecodeError:
                if HAS_TOML:
                    try:
                        config = toml.loads(content)
                        logger.debug(f"Successfully parsed as TOML: {file_path}")
                    except Exception as e:
                        logger.error(f"Invalid JSON and TOML in {file_path}: {e}")
                        return None
                else:
                    logger.error(
                        f"Content is not JSON and TOML library not available: {file_path}"
                    )
                    return None

            logger.debug(f"Successfully loaded local config: {file_path}")
            return config

        except Exception as e:
            logger.error(f"Error reading local config {path}: {e}")
            return None

    def _fetch_from_url(
        self, url: str, custom_headers: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Fetch configuration from HTTP/HTTPS URL or local file path.

        Supports:
        - HTTPS URLs: https://example.com/config.toml
        - file:// URLs: file:///etc/ai-guardian/config.toml
        - Absolute paths: /etc/ai-guardian/config.toml
        - Tilde paths: ~/team-configs/config.toml

        Args:
            url: URL or local file path to fetch
            custom_headers: Optional custom headers (e.g., for authentication)

        Returns:
            dict or None: Parsed configuration or None if failed
        """
        # Detect local file paths
        is_local = (
            url.startswith("file://")
            or url.startswith("/")
            or url.startswith("~")
            or (len(url) >= 3 and url[1] == ":" and url[2] in ("/", "\\"))
        )
        if is_local:
            return self._fetch_from_local_file(url)

        try:
            # Prepare headers with authentication
            headers = {}

            # Add custom headers first (highest priority)
            if custom_headers:
                headers.update(custom_headers)

            # Check for GitHub token (if not already in custom headers)
            if "Authorization" not in headers:
                github_token = os.environ.get("GITHUB_TOKEN")
                if github_token and "github.com" in url:
                    headers["Authorization"] = f"token {github_token}"
                    logger.debug("Using GITHUB_TOKEN for authentication")

            # Check for GitLab token (if not already in custom headers)
            if "PRIVATE-TOKEN" not in headers:
                gitlab_token = os.environ.get("GITLAB_TOKEN")
                if gitlab_token and "gitlab" in url:
                    headers["PRIVATE-TOKEN"] = gitlab_token
                    logger.debug("Using GITLAB_TOKEN for authentication")

            # Security: Enforce HTTPS for remote configs (reject http://)
            if url.startswith("http://"):
                logger.error(
                    f"HTTP URLs not allowed for remote configs (use HTTPS): {url}"
                )
                return None

            # Fetch with timeout and TLS verification enabled
            logger.debug(f"Fetching {url}...")
            response = requests.get(url, headers=headers, timeout=10, verify=True)

            # Check HTTP status
            if response.status_code == 401:
                logger.error(f"Authentication failed for {url} (401 Unauthorized)")
                return None
            elif response.status_code == 403:
                logger.error(f"Access forbidden for {url} (403 Forbidden)")
                return None
            elif response.status_code == 404:
                logger.error(f"URL not found: {url} (404 Not Found)")
                return None
            elif response.status_code != 200:
                logger.error(f"HTTP error {response.status_code} for {url}")
                return None

            # Parse content (try JSON first, then TOML for backward compatibility)
            content = response.text
            config = None

            # Try JSON first (preferred format)
            try:
                config = json.loads(content)
                logger.debug(f"Successfully parsed as JSON: {url}")
            except json.JSONDecodeError:
                # Not JSON, try TOML
                if HAS_TOML:
                    try:
                        config = toml.loads(content)
                        logger.debug(f"Successfully parsed as TOML: {url}")
                    except toml.TomlDecodeError as e:
                        logger.error(f"Invalid JSON and TOML in {url}: {e}")
                        return None
                else:
                    logger.error(
                        f"Content is not JSON and TOML library not available: {url}"
                    )
                    return None

            return config

        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {url}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error fetching {url}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return None

    def _get_cached_config(self, url: str) -> Tuple[Optional[Dict], float]:
        """
        Get cached configuration if available.

        Args:
            url: URL that was cached

        Returns:
            tuple: (config dict or None, cache age in hours)
        """
        cache_file = self._get_cache_path(url)

        if not cache_file.exists():
            return None, 0.0

        try:
            # Load cache metadata and content
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            cached_at = cache_data.get("cached_at", 0)
            cached_config = cache_data.get("config", {})

            # Calculate cache age
            now = time.time()
            cache_age_seconds = now - cached_at
            cache_age_hours = cache_age_seconds / 3600.0

            return cached_config, cache_age_hours

        except Exception as e:
            logger.warning(f"Error reading cache for {url}: {e}")
            return None, 0.0

    def _save_to_cache(self, url: str, config: Dict) -> None:
        """
        Save configuration to cache.

        Args:
            url: URL being cached
            config: Configuration dict to cache
        """
        try:
            cache_file = self._get_cache_path(url)

            # Create cache data with metadata
            cache_data = {
                "url": url,
                "cached_at": time.time(),
                "config": config,
            }

            # Write to cache
            with open(cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)

            logger.debug(f"Saved cache for {url}")

        except Exception as e:
            logger.warning(f"Error saving cache for {url}: {e}")

    def _get_cache_path(self, url: str) -> Path:
        """
        Get cache file path for a URL.

        Args:
            url: URL to cache

        Returns:
            Path: Cache file path
        """
        # Create a hash of the URL for the filename
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]

        # Use first part of URL as readable prefix
        url_parts = url.split("//")
        if len(url_parts) > 1:
            domain = url_parts[1].split("/")[0].replace(":", "_").replace(".", "_")
        else:
            domain = "unknown"

        filename = f"{domain}_{url_hash}.json"
        return self.cache_dir / filename

    def clear_cache(self, url: Optional[str] = None) -> None:
        """
        Clear cached configurations.

        Args:
            url: Optional URL to clear. If None, clears all caches.
        """
        try:
            if url is not None:
                # Clear specific URL
                cache_file = self._get_cache_path(url)
                if cache_file.exists():
                    cache_file.unlink()
                    logger.info(f"Cleared cache for {url}")
            else:
                # Clear all caches
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
                logger.info("Cleared all remote config caches")

        except Exception as e:
            logger.error(f"Error clearing cache: {e}")

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            dict: Cache statistics
        """
        stats = {
            "cache_dir": str(self.cache_dir),
            "total_cached": 0,
            "cache_files": [],
        }

        try:
            for cache_file in self.cache_dir.glob("*.json"):
                stats["total_cached"] += 1

                # Load cache metadata
                with open(cache_file, "r") as f:
                    cache_data = json.load(f)

                cached_at = cache_data.get("cached_at", 0)
                url = cache_data.get("url", "unknown")

                # Calculate age
                now = time.time()
                age_hours = (now - cached_at) / 3600.0

                stats["cache_files"].append(
                    {
                        "url": url,
                        "cached_at": cached_at,
                        "age_hours": age_hours,
                        "file": str(cache_file),
                    }
                )

        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")

        return stats
