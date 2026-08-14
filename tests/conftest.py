"""
Pytest configuration and fixtures for AI Guardian tests.

Provides test isolation for configuration directories and common test utilities.
"""

import json
import logging
import os
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _capture_package_logs(caplog):
    """Attach caplog handler to the ai_guardian logger.

    The ai_guardian package logger sets propagate=False so log messages
    don't reach root where caplog's handler lives.  pytest >=9.0 handles
    this automatically; this fixture provides the same behaviour on
    pytest 8.x (used on Python 3.9 CI).
    """
    pkg_logger = logging.getLogger("ai_guardian")
    already_attached = caplog.handler in pkg_logger.handlers
    if not already_attached:
        pkg_logger.addHandler(caplog.handler)
    yield
    if not already_attached:
        pkg_logger.removeHandler(caplog.handler)


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path):
    """
    Automatically isolate every test from the real config directory.

    Prevents tests from writing to the user's real violations.jsonl
    or reading the user's ai-guardian.json. Every test gets its own
    temporary config directory via the AI_GUARDIAN_CONFIG_DIR env var.
    """
    config_dir = tmp_path / "auto_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    state_dir = tmp_path / "auto_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = tmp_path / "auto_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Set a non-existent path to prevent discovery of real project configs
    project_config_sentinel = str(tmp_path / "no_project_config.json")
    # Suppress daemon auto-start in tests (prevents orphan processes on Windows)
    stop_marker = state_dir / "daemon.stop-requested"
    stop_marker.touch()
    env_overrides = {
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_STATE_DIR": str(state_dir),
        "AI_GUARDIAN_CACHE_DIR": str(cache_dir),
        "AI_GUARDIAN_PROJECT_CONFIG": project_config_sentinel,
    }
    # Prevent overlay env vars from leaking between tests
    for key in ("AI_GUARDIAN_CONFIG_OVERLAY", "AI_GUARDIAN_CONFIG_INLINE"):
        if key in os.environ:
            env_overrides[key] = ""
    with mock.patch.dict(os.environ, env_overrides):
        # Clear SDK overlay and caches so tests don't see stale state
        import ai_guardian.config.loaders as _cl

        _cl._sdk_overlay = None
        _cl._clear_config_cache()
        # Clear cached detector instances to prevent cross-test leaks
        from ai_guardian.scanners.prompt_injection import invalidate_detector_cache

        invalidate_detector_cache()
        yield config_dir
        _cl._sdk_overlay = None
        invalidate_detector_cache()


@pytest.fixture
def isolated_config_dir(tmp_path):
    """
    Provide an isolated configuration directory for tests.

    Sets AI_GUARDIAN_CONFIG_DIR environment variable to a temporary directory,
    ensuring tests don't interfere with the user's actual configuration.

    Usage:
        def test_something(isolated_config_dir):
            # Test code here - config will be in temporary directory
            # isolated_config_dir is a Path object to the temp directory
            pass
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Set environment variable for AI Guardian
    with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
        yield config_dir


@pytest.fixture
def isolated_config_with_file(isolated_config_dir):
    """
    Provide an isolated config directory with a default config file.

    Creates a basic ai-guardian.json config file for tests that need one.

    Usage:
        def test_something(isolated_config_with_file):
            config_dir, config_file = isolated_config_with_file
            # config_file contains path to ai-guardian.json
            pass
    """
    config_file = isolated_config_dir / "ai-guardian.json"

    # Create a minimal default config
    default_config = {
        "secret_scanning": {"enabled": True, "scanner": "gitleaks"},
        "prompt_injection": {"enabled": True},
        "permissions": {"enabled": True, "rules": []},
    }

    with open(config_file, "w") as f:
        json.dump(default_config, f, indent=2)

    return isolated_config_dir, config_file


@pytest.fixture
def mock_mcp_server():
    """
    Provide a fresh MockMCPServer instance for testing.

    The server is automatically reset before each test to ensure isolation.

    Usage:
        def test_something(mock_mcp_server):
            response = mock_mcp_server.notebook_create("Test Notebook")
            assert response["status"] == "success"
    """
    from tests.fixtures.mock_mcp_server import MockMCPServer

    server = MockMCPServer()
    server.reset()
    yield server
    # Cleanup after test
    server.reset()


@pytest.fixture
def attack_patterns():
    """
    Provide attack pattern constants for testing.

    Usage:
        def test_ssrf_detection(attack_patterns):
            assert "169.254.169.254" in attack_patterns.SSRF_AWS_METADATA
    """
    from tests.fixtures import attack_constants

    return attack_constants
