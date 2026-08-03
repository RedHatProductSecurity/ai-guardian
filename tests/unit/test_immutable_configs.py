"""
Unit tests for immutable config feature (Issue #67)

Tests the ability for remote configs to mark sections and matchers as immutable,
preventing local configs from overriding them.
"""

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch
from ai_guardian.tools.policy import ToolPolicyChecker


@pytest.fixture
def checker():
    return ToolPolicyChecker()


# ============================================================================
# Test: Per-Matcher Immutability
# ============================================================================


def test_immutable_matcher_blocks_local_override(checker):
    """Remote config with immutable matcher blocks local rules for that matcher"""
    remote_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": ["daf-*", "gh-cli"],
                    "immutable": True,
                }
            ],
        }
    }

    local_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {"matcher": "Skill", "mode": "allow", "patterns": ["my-custom-skill"]}
            ],
        }
    }

    immutable_matchers = checker._get_immutable_matchers([remote_config])
    assert "Skill" in immutable_matchers

    result = checker._merge_configs({}, local_config, immutable_matchers, set())
    result = checker._merge_configs(result, remote_config, set(), set())

    skill_patterns = []
    permissions_obj = result.get("permissions", {})
    rules = (
        permissions_obj.get("rules", [])
        if isinstance(permissions_obj, dict)
        else permissions_obj
    )
    for rule in rules:
        if rule.get("matcher") == "Skill":
            skill_patterns.extend(rule.get("patterns", []))

    assert "daf-*" in skill_patterns
    assert "gh-cli" in skill_patterns
    assert "my-custom-skill" not in skill_patterns


def test_non_immutable_matcher_allows_local_rules(checker):
    """Local configs can still add rules for non-immutable matchers"""
    remote_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": ["daf-*"],
                    "immutable": True,
                }
            ],
        }
    }

    local_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "mcp__*",
                    "mode": "allow",
                    "patterns": ["mcp__notebooklm-mcp__*"],
                }
            ],
        }
    }

    immutable_matchers = checker._get_immutable_matchers([remote_config])

    result = checker._merge_configs({}, local_config, immutable_matchers, set())
    result = checker._merge_configs(result, remote_config, set(), set())

    mcp_found = False
    permissions_obj = result.get("permissions", {})
    rules = (
        permissions_obj.get("rules", [])
        if isinstance(permissions_obj, dict)
        else permissions_obj
    )
    for rule in rules:
        if rule.get("matcher") == "mcp__*":
            mcp_found = True
            assert "mcp__notebooklm-mcp__*" in rule.get("patterns", [])

    assert mcp_found


def test_multiple_immutable_matchers(checker):
    """Multiple matchers can be marked as immutable"""
    remote_config = {
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
                    "immutable": True,
                },
            ],
        }
    }

    local_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {"matcher": "Skill", "mode": "allow", "patterns": ["custom-*"]},
                {"matcher": "Bash", "mode": "allow", "patterns": ["*safe-command*"]},
            ],
        }
    }

    immutable_matchers = checker._get_immutable_matchers([remote_config])

    assert "Skill" in immutable_matchers
    assert "Bash" in immutable_matchers

    result = checker._merge_configs({}, local_config, immutable_matchers, set())
    result = checker._merge_configs(result, remote_config, set(), set())

    permissions_obj = result.get("permissions", {})
    rules = (
        permissions_obj.get("rules", [])
        if isinstance(permissions_obj, dict)
        else permissions_obj
    )
    for rule in rules:
        if rule.get("matcher") == "Skill":
            assert "custom-*" not in rule.get("patterns", [])
        if rule.get("matcher") == "Bash":
            assert "*safe-command*" not in rule.get("patterns", [])


# ============================================================================
# Test: Section Immutability
# ============================================================================


def test_immutable_section_blocks_local_override(checker):
    """Remote config with immutable section blocks entire section from local override"""
    remote_config = {
        "prompt_injection": {
            "enabled": True,
            "sensitivity": "high",
            "detector": "heuristic",
            "immutable": True,
        }
    }

    local_config = {"prompt_injection": {"enabled": False, "sensitivity": "low"}}

    immutable_sections = checker._get_immutable_sections([remote_config])

    assert "prompt_injection" in immutable_sections

    result = checker._merge_configs({}, local_config, set(), immutable_sections)
    result = checker._merge_configs(result, remote_config, set(), set())

    assert result["prompt_injection"]["enabled"] is True
    assert result["prompt_injection"]["sensitivity"] == "high"


def test_multiple_immutable_sections(checker):
    """Multiple sections can be marked as immutable"""
    remote_config = {
        "prompt_injection": {"enabled": True, "sensitivity": "high", "immutable": True},
        "pattern_server": {
            "enabled": True,
            "url": "https://company.com/patterns",
            "immutable": True,
        },
    }

    local_config = {
        "prompt_injection": {"enabled": False},
        "pattern_server": {"enabled": False, "url": "https://local.com/patterns"},
    }

    immutable_sections = checker._get_immutable_sections([remote_config])

    assert "prompt_injection" in immutable_sections
    assert "pattern_server" in immutable_sections

    result = checker._merge_configs({}, local_config, set(), immutable_sections)
    result = checker._merge_configs(result, remote_config, set(), set())

    assert result["prompt_injection"]["enabled"] is True
    assert result["pattern_server"]["url"] == "https://company.com/patterns"


def test_non_immutable_section_allows_local_override(checker):
    """Sections without immutable flag can be overridden locally"""
    remote_config = {"secret_scanning": {"enabled": True}}

    local_config = {"secret_scanning": {"enabled": False}}

    immutable_sections = checker._get_immutable_sections([remote_config])

    assert "secret_scanning" not in immutable_sections

    result = checker._merge_configs({}, local_config, set(), immutable_sections)
    result = checker._merge_configs(result, remote_config, set(), set())

    assert "secret_scanning" in result


# ============================================================================
# Parametrized: Backward compatibility - immutable field value variations
# ============================================================================

IMMUTABLE_FIELD_CONFIGS = [
    pytest.param(
        {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["daf-*"],
                        # No immutable field
                    }
                ],
            }
        },
        id="missing-immutable-field",
    ),
    pytest.param(
        {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["daf-*"],
                        "immutable": False,
                    }
                ],
            },
            "prompt_injection": {"enabled": True, "immutable": False},
        },
        id="immutable-false",
    ),
]


@pytest.mark.parametrize("config", IMMUTABLE_FIELD_CONFIGS)
def test_non_immutable_configs_have_no_constraints(checker, config):
    """Configs without immutable: true produce no immutable constraints"""
    immutable_matchers = checker._get_immutable_matchers([config])
    immutable_sections = checker._get_immutable_sections([config])

    assert "Skill" not in immutable_matchers
    assert len(immutable_matchers) == 0
    if "prompt_injection" in config:
        assert "prompt_injection" not in immutable_sections


# ============================================================================
# Test: Integration with Config Loading
# ============================================================================


def test_get_immutable_matchers_extracts_correct_matchers(checker):
    """_get_immutable_matchers correctly identifies immutable matchers"""
    remote_configs = [
        {
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
    ]

    immutable_matchers = checker._get_immutable_matchers(remote_configs)

    assert "Skill" in immutable_matchers
    assert "Bash" not in immutable_matchers


def test_get_immutable_sections_extracts_correct_sections(checker):
    """_get_immutable_sections correctly identifies immutable sections"""
    remote_configs = [
        {
            "prompt_injection": {"enabled": True, "immutable": True},
            "pattern_server": {"enabled": True, "immutable": False},
            "secret_scanning": {"enabled": True},
        }
    ]

    immutable_sections = checker._get_immutable_sections(remote_configs)

    assert "prompt_injection" in immutable_sections
    assert "pattern_server" not in immutable_sections
    assert "secret_scanning" not in immutable_sections


# ============================================================================
# Test: Schema Validation
# ============================================================================


def test_immutable_field_validates_in_schema(checker):
    """Configs with immutable field pass schema validation"""
    config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": ["daf-*"],
                    "immutable": True,
                }
            ],
        },
        "prompt_injection": {"enabled": True, "immutable": True},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        temp_path = f.name

    try:
        loaded_config = checker._load_json_file(Path(temp_path), "test")

        assert loaded_config is not None
        assert loaded_config["permissions"]["rules"][0]["immutable"] is True
        assert loaded_config["prompt_injection"]["immutable"] is True
    finally:
        Path(temp_path).unlink()


def test_invalid_immutable_type_rejected(checker):
    """Invalid immutable field type is rejected by schema"""
    config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": ["daf-*"],
                    "immutable": "yes",  # Invalid: should be boolean
                }
            ],
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        temp_path = f.name

    try:
        loaded_config = checker._load_json_file(Path(temp_path), "test")

        # Config loaded with warnings (warn-but-load, #1761)
        assert loaded_config is not None
        assert len(checker._config_warnings) >= 1
    finally:
        Path(temp_path).unlink()


# ============================================================================
# Test: Enterprise Use Cases
# ============================================================================


def test_enterprise_skill_allowlist_enforcement(checker):
    """Enterprise can enforce skill allowlist that users cannot extend"""
    enterprise_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "Skill",
                    "mode": "allow",
                    "patterns": ["daf-*", "gh-cli"],
                    "immutable": True,
                }
            ],
        }
    }

    user_config = {
        "permissions": {
            "enabled": True,
            "rules": [
                {"matcher": "Skill", "mode": "allow", "patterns": ["my-custom-skill"]}
            ],
        }
    }

    immutable_matchers = checker._get_immutable_matchers([enterprise_config])

    result = checker._merge_configs({}, user_config, immutable_matchers, set())
    result = checker._merge_configs(result, enterprise_config, set(), set())

    hook_data_allowed = {"tool_use": {"name": "Skill", "input": {"skill": "daf-jira"}}}

    hook_data_blocked = {
        "tool_use": {"name": "Skill", "input": {"skill": "my-custom-skill"}}
    }

    checker_with_config = ToolPolicyChecker(config=result)

    is_allowed, error_msg, _ = checker_with_config.check_tool_allowed(hook_data_allowed)
    assert is_allowed

    is_allowed, error_msg, _ = checker_with_config.check_tool_allowed(hook_data_blocked)
    assert not is_allowed


def test_enterprise_prompt_injection_enforcement(checker):
    """Enterprise can enforce prompt injection settings that cannot be weakened"""
    enterprise_config = {
        "prompt_injection": {
            "enabled": True,
            "sensitivity": "high",
            "detector": "heuristic",
            "immutable": True,
        }
    }

    user_config = {"prompt_injection": {"enabled": False, "sensitivity": "low"}}

    immutable_sections = checker._get_immutable_sections([enterprise_config])

    result = checker._merge_configs({}, user_config, set(), immutable_sections)
    result = checker._merge_configs(result, enterprise_config, set(), set())

    assert result["prompt_injection"]["enabled"] is True
    assert result["prompt_injection"]["sensitivity"] == "high"


# ============================================================================
# Parametrized: Cascading priority for remote config URLs (Issue #255)
# ============================================================================

CASCADING_PRIORITY_CASES = [
    pytest.param(
        # system_config_path creates a file, env_var is None, user_config has URL
        # Expected: only system URL fetched, user URL blocked
        {
            "system_urls": ["https://enterprise.com/policy.json"],
            "env_var": None,
            "user_config": {
                "remote_configs": {"urls": ["https://user.com/bypass.json"]}
            },
            "local_config": {},
            "expected_fetched": ["https://enterprise.com/policy.json"],
            "expected_not_fetched": ["https://user.com/bypass.json"],
        },
        id="system-config-blocks-user-urls",
    ),
    pytest.param(
        {
            "system_urls": None,
            "env_var": "https://env.com/policy.json",
            "user_config": {
                "remote_configs": {"urls": ["https://user.com/config.json"]}
            },
            "local_config": {},
            "expected_fetched": ["https://env.com/policy.json"],
            "expected_not_fetched": ["https://user.com/config.json"],
        },
        id="env-var-over-user-config",
    ),
    pytest.param(
        {
            "system_urls": None,
            "env_var": None,
            "user_config": {
                "remote_configs": {"urls": ["https://user.com/patterns.json"]}
            },
            "local_config": {},
            "expected_fetched": ["https://user.com/patterns.json"],
            "expected_not_fetched": [],
        },
        id="user-urls-without-system-config",
    ),
    pytest.param(
        {
            "system_urls": None,
            "env_var": None,
            "user_config": {
                "remote_configs": {"urls": ["https://user.com/user-config.json"]}
            },
            "local_config": {
                "remote_configs": {"urls": ["https://local.com/local-config.json"]}
            },
            "expected_fetched": ["https://user.com/user-config.json"],
            "expected_not_fetched": ["https://local.com/local-config.json"],
        },
        id="local-config-lowest-priority",
    ),
    pytest.param(
        {
            "system_urls": None,
            "env_var": None,
            "user_config": {"remote_configs": ["https://user.com/old-format.json"]},
            "local_config": {},
            "expected_fetched": ["https://user.com/old-format.json"],
            "expected_not_fetched": [],
        },
        id="legacy-format-still-works",
    ),
]


@pytest.mark.parametrize("case", CASCADING_PRIORITY_CASES)
def test_cascading_priority(case):
    """Remote config URL cascading priority is enforced correctly"""
    checker = ToolPolicyChecker()

    system_config_path = None
    try:
        # Set up system config file if needed
        if case["system_urls"] is not None:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump({"urls": case["system_urls"]}, f)
                system_config_path = f.name

        # Set up env var if needed
        if case["env_var"] is not None:
            os.environ["AI_GUARDIAN_REMOTE_CONFIG_URLS"] = case["env_var"]

        fetched_urls = []

        def mock_load(url, base_path, token_env):
            fetched_urls.append(url)
            return None

        with patch.object(checker, "_load_remote_config", side_effect=mock_load):
            with patch.object(
                checker,
                "_get_system_config_path",
                return_value=Path(system_config_path) if system_config_path else None,
            ):
                checker._load_remote_configs(
                    case["local_config"], None, case["user_config"], None
                )

        for url in case["expected_fetched"]:
            assert url in fetched_urls, f"Expected {url} to be fetched"
        for url in case["expected_not_fetched"]:
            assert url not in fetched_urls, f"Expected {url} NOT to be fetched"

    finally:
        if system_config_path and os.path.exists(system_config_path):
            Path(system_config_path).unlink()
        if case["env_var"] is not None:
            os.environ.pop("AI_GUARDIAN_REMOTE_CONFIG_URLS", None)


if __name__ == "__main__":
    pytest.main([__file__])
