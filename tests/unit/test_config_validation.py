"""
Tests for runtime configuration validation using JSON Schema.

Tests that invalid configurations are loaded with warnings (warn-but-load),
not silently dropped (#1761).
"""

import json
import tempfile
from pathlib import Path

from ai_guardian.tools.policy import ToolPolicyChecker


def test_valid_config_loads_successfully():
    """Test that a valid configuration loads without errors."""
    valid_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*", "gh-cli"]}
            ],
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(valid_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert "permissions" in config
        assert "rules" in config["permissions"]
        assert checker._config_warnings == []
    finally:
        Path(temp_path).unlink()


def test_invalid_mode_loads_with_warning():
    """Test that invalid permission mode loads config with warning (#1761)."""
    invalid_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "invalid_mode",  # Invalid!
                    "patterns": ["daf-*"],
                }
            ],
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(invalid_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert config == invalid_config
        assert len(checker._config_warnings) == 1
        assert "invalid_mode" in checker._config_warnings[0]
    finally:
        Path(temp_path).unlink()


def test_invalid_detector_loads_with_warning():
    """Test that invalid detector type loads config with warning (#1761)."""
    invalid_config = {"prompt_injection": {"detector": "invalid_detector"}}  # Invalid!

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(invalid_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert config == invalid_config
        assert len(checker._config_warnings) == 1
        assert "invalid_detector" in checker._config_warnings[0]
    finally:
        Path(temp_path).unlink()


def test_missing_required_fields_loads_with_warning():
    """Test that missing required fields loads config with warning (#1761)."""
    invalid_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    # Missing "mode" and "patterns" (required)
                }
            ],
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(invalid_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert config == invalid_config
        assert len(checker._config_warnings) >= 1
    finally:
        Path(temp_path).unlink()


def test_empty_config_is_valid():
    """Test that an empty config (all fields optional) is valid."""
    empty_config = {}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(empty_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert config == {}
        assert checker._config_warnings == []
    finally:
        Path(temp_path).unlink()


def test_complex_valid_config_loads():
    """Test that a complex valid configuration loads successfully."""
    complex_config = {
        "permissions": {
            "enabled": {
                "value": False,
                "disabled_until": "2026-04-13T18:00:00Z",
                "reason": "Emergency debugging",
            },
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": [
                        "daf-*",
                        {"pattern": "debug-*", "valid_until": "2026-04-13T12:00:00Z"},
                    ],
                }
            ],
        },
        "prompt_injection": {
            "enabled": True,
            "detector": "heuristic",
            "sensitivity": "medium",
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(complex_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert "permissions" in config
        assert "prompt_injection" in config
        assert checker._config_warnings == []
    finally:
        Path(temp_path).unlink()


def test_immutable_field_in_permissions_is_valid():
    """Test that immutable field in permission rules is valid (Issue #67)."""
    config_with_immutable = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": ["daf-*"],
                    "immutable": True,
                },
                {
                    "matcher": "Bash",
                    "mode": "deny",
                    "patterns": ["*rm -rf*"],
                    "immutable": False,
                },
            ],
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_with_immutable, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert config["permissions"]["rules"][0]["immutable"] is True
        assert config["permissions"]["rules"][1]["immutable"] is False
    finally:
        Path(temp_path).unlink()


def test_immutable_field_in_sections_is_valid():
    """Test that immutable field in top-level sections is valid (Issue #67)."""
    config_with_immutable_sections = {
        "prompt_injection": {"enabled": True, "sensitivity": "high", "immutable": True},
        "pattern_server": {
            "enabled": True,
            "url": "https://company.com/patterns",
            "immutable": True,
        },
        "secret_scanning": {"enabled": True, "immutable": False},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_with_immutable_sections, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert config["prompt_injection"]["immutable"] is True
        assert config["pattern_server"]["immutable"] is True
        assert config["secret_scanning"]["immutable"] is False
    finally:
        Path(temp_path).unlink()


def test_engine_config_without_binary_is_valid():
    """Test that built-in engine config without binary field is valid (#1760)."""
    config = {
        "secret_scanning": {
            "engines": [
                {"type": "toml-patterns"},
                {"type": "leaktk"},
                {"type": "gitleaks", "binary": "gitleaks"},
            ]
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        loaded = checker._load_json_file(Path(temp_path), "test")
        assert loaded is not None
        assert len(loaded["secret_scanning"]["engines"]) == 3
    finally:
        Path(temp_path).unlink()


def test_engine_config_with_binary_is_valid():
    """Test that engine config with explicit binary field still works (#1760)."""
    config = {
        "secret_scanning": {
            "engines": [
                {"type": "gitleaks", "binary": "gitleaks"},
                {"type": "custom", "binary": "/usr/local/bin/my-scanner"},
            ]
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        loaded = checker._load_json_file(Path(temp_path), "test")
        assert loaded is not None
        assert len(loaded["secret_scanning"]["engines"]) == 2
    finally:
        Path(temp_path).unlink()


def test_invalid_immutable_type_loads_with_warning():
    """Test that invalid immutable field type loads with warning (#1761)."""
    invalid_config = {
        "permissions": [
            {
                "matcher": "Skill",
                "mode": "allow",
                "patterns": ["daf-*"],
                "immutable": "yes",  # Invalid: should be boolean
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(invalid_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert config == invalid_config
        assert len(checker._config_warnings) >= 1
    finally:
        Path(temp_path).unlink()


def test_warning_message_includes_path_and_error():
    """Test that config warning message includes location and error details."""
    invalid_config = {"prompt_injection": {"detector": "nonexistent_detector"}}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(invalid_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        checker._load_json_file(Path(temp_path), "test source")
        assert len(checker._config_warnings) == 1
        warning = checker._config_warnings[0]
        assert "test source" in warning
        assert "Location:" in warning
        assert "Error:" in warning
        assert "nonexistent_detector" in warning
    finally:
        Path(temp_path).unlink()


def test_valid_config_no_warnings():
    """Test that valid config produces zero warnings."""
    valid_config = {
        "permissions": {
            "enabled": True,
            "rules": [{"matcher": "Bash", "mode": "deny", "patterns": ["*rm -rf*"]}],
        },
        "ssrf_protection": {"enabled": True},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(valid_config, f)
        temp_path = f.name

    try:
        checker = ToolPolicyChecker()
        config = checker._load_json_file(Path(temp_path), "test")
        assert config is not None
        assert checker._config_warnings == []
    finally:
        Path(temp_path).unlink()


def test_multiple_configs_accumulate_warnings():
    """Test that warnings from multiple config loads accumulate."""
    invalid1 = {"prompt_injection": {"detector": "bad1"}}
    invalid2 = {"prompt_injection": {"detector": "bad2"}}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f1:
        json.dump(invalid1, f1)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f2:
        json.dump(invalid2, f2)
        path2 = f2.name

    try:
        checker = ToolPolicyChecker()
        checker._load_json_file(Path(path1), "config1")
        checker._load_json_file(Path(path2), "config2")
        assert len(checker._config_warnings) == 2
        assert "config1" in checker._config_warnings[0]
        assert "config2" in checker._config_warnings[1]
    finally:
        Path(path1).unlink()
        Path(path2).unlink()
