"""
Remote engine configuration fetcher.

Fetches engine configuration from a remote URL for centralized management.
Supports config versioning, auto-updates on TTL expiry, and merge strategies.
"""

import logging
import os
from typing import Optional, Dict, Any, List

try:
    from ai_guardian.patterns.remote import RemoteFetcher

    HAS_REMOTE_FETCHER = True
except ImportError:
    HAS_REMOTE_FETCHER = False

logger = logging.getLogger(__name__)


def fetch_remote_engine_config(
    remote_config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Fetch engine configuration from a remote URL.

    Args:
        remote_config: Dict with keys:
            - url: HTTPS URL to fetch engine config JSON from
            - refresh_interval_hours: How often to refresh (default 12)
            - expire_after_hours: Cache expiration (default 168)
            - auth_token_env: Optional env var name for auth token

    Returns:
        Engine configuration dict or None on failure
    """
    url = remote_config.get("url")
    if not url:
        return None

    try:
        if not HAS_REMOTE_FETCHER:
            logger.warning("RemoteFetcher not available, skipping remote engine config")
            return None

        fetcher = RemoteFetcher()

        headers = {}
        auth_env = remote_config.get("auth_token_env")
        if auth_env:
            token = os.environ.get(auth_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"

        result = fetcher.fetch_config(
            url=url,
            refresh_interval_hours=remote_config.get("refresh_interval_hours", 12),
            expire_after_hours=remote_config.get("expire_after_hours", 168),
            headers=headers or None,
            expected_sha256=remote_config.get("sha256"),
        )

        return result

    except Exception as e:
        logger.warning(f"Failed to fetch remote engine config: {e}")
        return None


def merge_engine_configs(
    local_engines: List[Any],
    remote_engines: List[Any],
    immutable: bool = False,
) -> List[Any]:
    """
    Merge local and remote engine configurations.

    Args:
        local_engines: Local engine specs from config file
        remote_engines: Remote engine specs from URL
        immutable: If True, remote completely replaces local

    Returns:
        Merged engine list
    """
    if immutable:
        logger.info("Remote engine config is immutable — using remote only")
        return remote_engines

    remote_types = set()
    for eng in remote_engines:
        if isinstance(eng, str):
            remote_types.add(eng)
        elif isinstance(eng, dict):
            remote_types.add(eng.get("type", ""))

    merged = list(remote_engines)
    for eng in local_engines:
        eng_type = eng if isinstance(eng, str) else eng.get("type", "")
        if eng_type not in remote_types:
            merged.append(eng)

    return merged
