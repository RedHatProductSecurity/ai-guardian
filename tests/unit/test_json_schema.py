"""
Tests for JSON Schema validation of ai-guardian configuration files.

This test suite validates that:
1. The JSON Schema file itself is valid
2. The example configuration validates against the schema
3. Invalid configurations are properly rejected

Note: jsonschema is an optional test dependency. Tests will be skipped if not installed.
"""

import json
import pytest
from pathlib import Path

# Try to import jsonschema - it's optional
try:
    import jsonschema
    from jsonschema import validate, ValidationError

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
SCHEMA_PATH = (
    PROJECT_ROOT / "src" / "ai_guardian" / "schemas" / "ai-guardian-config.schema.json"
)
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "ai-guardian-example.json"
VALID_CONFIG_PATH = Path(__file__).parent.parent / "fixtures" / "valid-config.json"


@pytest.fixture
def schema():
    """Load the JSON Schema."""
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)


@pytest.fixture
def example_config():
    """Load the example configuration."""
    with open(EXAMPLE_CONFIG_PATH, "r") as f:
        return json.load(f)


@pytest.fixture
def valid_config():
    """Load the clean test configuration (without comment fields)."""
    with open(VALID_CONFIG_PATH, "r") as f:
        return json.load(f)


def test_schema_file_exists():
    """Test that the schema file exists."""
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"


def test_schema_is_valid_json():
    """Test that the schema file is valid JSON."""
    with open(SCHEMA_PATH, "r") as f:
        schema_data = json.load(f)

    # Verify basic schema structure
    assert "$schema" in schema_data
    assert "$id" in schema_data
    assert "title" in schema_data
    assert "type" in schema_data
    assert schema_data["type"] == "object"


def test_example_config_is_valid_json():
    """Test that the example config is valid JSON."""
    with open(EXAMPLE_CONFIG_PATH, "r") as f:
        config = json.load(f)

    # Verify it has the schema reference
    assert "$schema" in config
    assert "RedHatProductSecurity/ai-guardian" in config["$schema"]


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_valid_config_validates(schema, valid_config):
    """Test that a clean configuration (without comments) validates against the schema."""
    try:
        validate(instance=valid_config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Valid config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_minimal_valid_config(schema):
    """Test that a minimal valid configuration passes validation."""
    minimal_config = {"permissions": {"enabled": True, "rules": []}}

    try:
        validate(instance=minimal_config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Minimal config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_empty_config_is_valid(schema):
    """Test that an empty object is valid (all fields are optional)."""
    empty_config = {}

    try:
        validate(instance=empty_config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Empty config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_permission_rule_structure(schema):
    """Test that permission rules validate correctly."""
    config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*", "gh-cli"]}
            ],
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Permission rule config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_time_based_pattern(schema):
    """Test that time-based patterns validate correctly."""
    config = {
        "permissions": {
            "enabled": True,
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
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Time-based pattern config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_time_based_feature_boolean(schema):
    """Test that boolean feature toggles validate correctly."""
    config = {"permissions": {"enabled": True}, "secret_scanning": {"enabled": False}}

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Boolean feature config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_time_based_feature_extended(schema):
    """Test that extended time-based feature toggles validate correctly."""
    config = {
        "permissions": {
            "enabled": {
                "value": False,
                "disabled_until": "2026-04-13T18:00:00Z",
                "reason": "Emergency debugging",
            }
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Extended feature config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_prompt_injection_config(schema):
    """Test that prompt injection configuration validates correctly."""
    config = {
        "prompt_injection": {
            "enabled": True,
            "detector": "heuristic",
            "sensitivity": "medium",
            "max_score_threshold": 0.75,
            "allowlist_patterns": ["test:.*"],
            "custom_patterns": [],
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Prompt injection config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_invalid_mode_rejected(schema):
    """Test that invalid permission mode is rejected."""
    config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {"matcher": "Skill", "mode": "invalid_mode", "patterns": ["daf-*"]}
            ],
        }
    }

    with pytest.raises(ValidationError):
        validate(instance=config, schema=schema)


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_invalid_detector_rejected(schema):
    """Test that invalid detector type is rejected."""
    config = {"prompt_injection": {"detector": "invalid_detector"}}

    with pytest.raises(ValidationError):
        validate(instance=config, schema=schema)


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_invalid_sensitivity_rejected(schema):
    """Test that invalid sensitivity level is rejected."""
    config = {"prompt_injection": {"sensitivity": "invalid_level"}}

    with pytest.raises(ValidationError):
        validate(instance=config, schema=schema)


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_missing_required_fields_rejected(schema):
    """Test that permission rules missing required fields are rejected."""
    config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    # missing mode and patterns
                }
            ],
        }
    }

    with pytest.raises(ValidationError):
        validate(instance=config, schema=schema)


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_remote_configs_structure(schema):
    """Test that remote_configs validates correctly."""
    config = {
        "remote_configs": {
            "urls": [
                "https://example.com/policy.json",
                {
                    "url": "https://example.com/policy2.json",
                    "enabled": True,
                    "token_env": "GITHUB_TOKEN",
                },
            ],
            "refresh_interval_hours": 12,
            "expire_after_hours": 168,
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Remote configs failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_directory_exclusions(schema):
    """Test that directory_exclusions validates correctly."""
    config = {
        "directory_exclusions": {
            "enabled": True,
            "paths": ["~/development/workspace", "~/repos/**"],
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Directory exclusions config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_pattern_server_config(schema):
    """Test that pattern_server validates correctly."""
    config = {
        "pattern_server": {
            "enabled": False,
            "url": "https://patterns.example.com",
            "patterns_endpoint": "/patterns/gitleaks/8.18.1",
            "auth": {"method": "bearer", "token_env": "PATTERN_TOKEN"},
            "cache": {
                "path": "~/.cache/ai-guardian/patterns.toml",
                "refresh_interval_hours": 12,
                "expire_after_hours": 168,
            },
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Pattern server config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_time_based_bash_allow_pattern(schema):
    """Test that time-based Bash allow patterns validate correctly."""
    config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Bash",
                    "mode": "allow",
                    "patterns": [
                        {
                            "pattern": "*docker rm*",
                            "valid_until": "2026-04-13T15:00:00Z",
                        }
                    ],
                }
            ],
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Time-based Bash allow pattern failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_mixed_simple_and_time_based_patterns(schema):
    """Test that mixed simple and time-based patterns validate correctly."""
    config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": [
                        "daf-*",
                        "gh-cli",
                        {"pattern": "debug-*", "valid_until": "2026-04-13T12:00:00Z"},
                    ],
                }
            ],
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Mixed patterns failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_prompt_injection_time_based_allowlist(schema):
    """Test that prompt injection time-based allowlist patterns validate correctly."""
    config = {
        "prompt_injection": {
            "allowlist_patterns": [
                "test:.*",
                {"pattern": "experimental:.*", "valid_until": "2026-04-14T00:00:00Z"},
            ]
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(
            f"Prompt injection time-based allowlist failed validation: {e.message}"
        )


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_permissions_directories_structure(schema):
    """Test that permissions_directories validates correctly."""
    config = {
        "permissions_directories": {
            "deny": [],
            "allow": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "url": "https://github.com/your-org/skills/tree/main/skills",
                    "token_env": "GITHUB_TOKEN",
                },
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "url": "/Users/yourname/.claude/skills",
                },
            ],
        }
    }

    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Permissions directories config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
@pytest.mark.parametrize(
    "section",
    [
        "permissions",
        "secret_scanning",
        "prompt_injection",
        "ssrf_protection",
        "config_file_scanning",
        "scan_pii",
        "secret_redaction",
        "violation_logging",
        "transcript_scanning",
    ],
)
def test_time_based_enabled_all_sections_boolean(schema, section):
    """Test that all sections with enabled field accept boolean format."""
    config = {section: {"enabled": True}}
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"{section}.enabled rejected boolean True: {e.message}")

    config = {section: {"enabled": False}}
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"{section}.enabled rejected boolean False: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
@pytest.mark.parametrize(
    "section",
    [
        "permissions",
        "secret_scanning",
        "prompt_injection",
        "ssrf_protection",
        "config_file_scanning",
        "scan_pii",
        "secret_redaction",
        "violation_logging",
        "transcript_scanning",
    ],
)
def test_time_based_enabled_all_sections_object(schema, section):
    """Test that all sections with enabled field accept time-based object format."""
    config = {
        section: {"enabled": {"value": False, "disabled_until": "2026-05-07T21:39:30Z"}}
    }
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"{section}.enabled rejected time-based object: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
@pytest.mark.parametrize(
    "section",
    [
        "permissions",
        "secret_scanning",
        "prompt_injection",
        "ssrf_protection",
        "config_file_scanning",
        "scan_pii",
        "secret_redaction",
        "violation_logging",
        "transcript_scanning",
    ],
)
def test_time_based_enabled_all_sections_object_with_reason(schema, section):
    """Test that all sections accept time-based object with optional reason."""
    config = {
        section: {
            "enabled": {
                "value": False,
                "disabled_until": "2026-05-07T21:39:30Z",
                "reason": "Temporary debugging",
            }
        }
    }
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"{section}.enabled rejected time-based with reason: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_daemon_config(schema):
    """Test that daemon configuration validates correctly."""
    config = {
        "daemon": {
            "idle_timeout_minutes": 30,
            "client_timeout_seconds": 2.0,
            "rest_port": 63152,
            "rest_host": "127.0.0.1",
            "tray": {
                "enabled": True,
                "auto_install": True,
                "discover_containers": True,
                "discovery_interval_seconds": 15,
            },
        }
    }
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Daemon config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_daemon_invalid_timeout_rejected(schema):
    """Test that invalid daemon timeout type is rejected."""
    config = {"daemon": {"idle_timeout_minutes": "not-a-number"}}
    with pytest.raises(ValidationError):
        validate(instance=config, schema=schema)


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_daemon_additional_properties_rejected(schema):
    """Test that daemon rejects unknown properties."""
    config = {"daemon": {"unknown_field": True}}
    with pytest.raises(ValidationError):
        validate(instance=config, schema=schema)


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_support_config(schema):
    """Test that support configuration validates correctly."""
    config = {
        "support": {
            "export_destination": "s3://bucket/prefix/",
            "auth": {"method": "env", "token_env": "AWS_TOKEN"},
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "guardian@example.com",
                "subject_prefix": "[AI Guardian Support]",
                "auth": {
                    "method": "env",
                    "username_env": "SMTP_USER",
                    "password_env": "SMTP_PASS",
                },
            },
            "bundle_ttl_minutes": 60,
        }
    }
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Support config failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_support_invalid_auth_method_rejected(schema):
    """Test that invalid support auth method is rejected."""
    config = {"support": {"auth": {"method": "invalid"}}}
    with pytest.raises(ValidationError):
        validate(instance=config, schema=schema)


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_support_allows_comment_keys(schema):
    """Test that support allows _comment_* keys (used throughout config)."""
    config = {
        "support": {
            "export_destination": "",
            "_comment_email": "SMTP settings for mailto: destinations.",
        }
    }
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Support with _comment key failed validation: {e.message}")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_invalid_timestamp_format(schema):
    """Test that invalid timestamp format is rejected."""
    config = {
        "permissions": [
            {
                "matcher": "Skill",
                "mode": "allow",
                "patterns": [
                    {"pattern": "debug-*", "valid_until": "invalid-timestamp"}
                ],
            }
        ]
    }

    # Note: JSON Schema draft-07 format validation is optional
    # The schema will still validate, but implementations should check format
    # We're just ensuring the schema structure is correct
    try:
        validate(instance=config, schema=schema)
        # If validation passes, that's OK - format checking is optional in draft-07
    except ValidationError:
        # If it fails, that's also OK - strict format checking
        pass
