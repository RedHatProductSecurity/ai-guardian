#!/usr/bin/env python3
"""
Tests for setup command functionality.
"""

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian.config.utils import get_config_dir
from ai_guardian.setup import (
    IDESetup,
    setup_hooks,
    _create_vbs_wrapper,
    _is_ai_guardian_command,
    _resolve_binary_path,
    _substitute_command,
    _upgrade_ide_flag,
    _walk_commands,
)


class TestIDESetup:
    """Test cases for IDESetup class."""

    def test_detect_ide_none(self, tmp_path):
        """Test IDE detection when no IDE is installed."""
        setup = IDESetup()

        # Mock config paths to non-existent directories
        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {
                    "config_path": str(
                        tmp_path / "nonexistent" / ".claude" / "settings.json"
                    )
                },
                "cursor": {
                    "config_path": str(
                        tmp_path / "nonexistent" / ".cursor" / "hooks.json"
                    )
                },
            },
        ):
            detected = setup.detect_ide()
            assert detected is None

    def test_detect_ide_single(self, tmp_path):
        """Test IDE detection when only one IDE is installed."""
        setup = IDESetup()

        # Create Claude Code directory
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {"config_path": str(claude_dir / "settings.json")},
                "cursor": {
                    "config_path": str(
                        tmp_path / "nonexistent" / ".cursor" / "hooks.json"
                    )
                },
            },
        ):
            detected = setup.detect_ide()
            assert detected == "claude"

    def test_detect_ide_multiple(self, tmp_path):
        """Test IDE detection when multiple IDEs are installed."""
        setup = IDESetup()

        # Create both IDE directories
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir(parents=True)

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {"config_path": str(claude_dir / "settings.json")},
                "cursor": {"config_path": str(cursor_dir / "hooks.json")},
            },
        ):
            detected = setup.detect_ide()
            assert detected is None  # Returns None when multiple detected

    def test_list_detected_ides(self, tmp_path):
        """Test listing all detected IDEs."""
        setup = IDESetup()

        # Create both IDE directories
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir(parents=True)

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {"config_path": str(claude_dir / "settings.json")},
                "cursor": {"config_path": str(cursor_dir / "hooks.json")},
            },
        ):
            detected = setup.list_detected_ides()
            assert set(detected) == {"claude", "cursor"}

    def test_backup_config(self, tmp_path):
        """Test creating backup of config file."""
        setup = IDESetup()

        # Create test config file
        config_file = tmp_path / "test.json"
        config_file.write_text('{"test": "data"}')

        # Create backup
        backup_path = setup.backup_config(config_file)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.name == "test.json.backup"
        assert backup_path.read_text() == '{"test": "data"}'

    def test_backup_config_nonexistent(self, tmp_path):
        """Test backup creation when file doesn't exist."""
        setup = IDESetup()

        config_file = tmp_path / "nonexistent.json"
        backup_path = setup.backup_config(config_file)

        assert backup_path is None

    def test_merge_hooks_claude_existing(self):
        """Test merging Claude Code hooks into existing config."""
        setup = IDESetup()

        existing_config = {
            "hooks": {"OtherHook": [{"existing": "hook"}]},
            "other_setting": "value",
        }
        ai_guardian_hooks = {"UserPromptSubmit": [{"test": "hook"}]}

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "claude"
        )

        assert "hooks" in merged
        assert "OtherHook" in merged["hooks"]  # Preserved
        assert "UserPromptSubmit" in merged["hooks"]  # Added
        assert merged["other_setting"] == "value"  # Preserved

    def test_merge_hooks_claude_includes_session_start(self):
        """SessionStart must be written when merging Claude Code hooks."""
        setup = IDESetup()
        existing_config = {}
        ai_guardian_hooks = IDESetup.IDE_CONFIGS["claude"]["hooks"]

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "claude"
        )

        assert (
            "SessionStart" in merged["hooks"]
        ), "SessionStart hook missing from merged Claude config"
        session_start = merged["hooks"]["SessionStart"]
        assert isinstance(session_start, list)
        assert len(session_start) >= 1

    def test_setup_ide_hooks_already_configured(self, tmp_path):
        """Test setup when hooks already configured without force."""
        setup = IDESetup()

        config_file = tmp_path / "settings.json"
        config = {
            "hooks": {
                "UserPromptSubmit": [
                    {"matcher": "*", "hooks": [{"command": "ai-guardian"}]}
                ]
            }
        }
        config_file.write_text(json.dumps(config))

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {
                    "name": "Claude Code",
                    "config_path": str(config_file),
                    "config_dir_env_var": None,  # Disable env var for test
                    "hooks": {},
                }
            },
        ):
            success, message = setup.setup_ide_hooks(
                "claude", dry_run=False, force=False
            )

            assert success is False
            assert "already configured" in message

    def test_setup_ide_hooks_invalid_json(self, tmp_path):
        """Test setup with invalid JSON in existing config."""
        setup = IDESetup()

        config_file = tmp_path / "settings.json"
        config_file.write_text("invalid json {")

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {
                    "name": "Claude Code",
                    "config_path": str(config_file),
                    "config_dir_env_var": None,  # Disable env var for test
                    "hooks": {},
                }
            },
        ):
            success, message = setup.setup_ide_hooks(
                "claude", dry_run=False, force=False
            )

            assert success is False
            assert "Invalid JSON" in message

    def test_merge_hooks_windsurf_new(self):
        """Test merging Windsurf hooks into new config."""
        setup = IDESetup()

        existing_config = {}
        ai_guardian_hooks = {
            "hooks": {
                "pre_user_prompt": [{"command": "ai-guardian"}],
                "pre_run_command": [{"command": "ai-guardian"}],
                "post_run_command": [{"command": "ai-guardian"}],
            }
        }

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "windsurf"
        )

        assert "hooks" in merged
        assert "pre_user_prompt" in merged["hooks"]
        assert "pre_run_command" in merged["hooks"]
        assert "post_run_command" in merged["hooks"]
        assert len(warnings) == 0

    def test_merge_hooks_windsurf_existing(self):
        """Test merging Windsurf hooks preserves other events."""
        setup = IDESetup()

        existing_config = {
            "hooks": {
                "post_cascade_response": [{"command": "custom-logger"}],
            }
        }
        ai_guardian_hooks = {
            "hooks": {
                "pre_user_prompt": [{"command": "ai-guardian"}],
                "pre_run_command": [{"command": "ai-guardian"}],
            }
        }

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "windsurf"
        )

        assert "post_cascade_response" in merged["hooks"]
        assert "pre_user_prompt" in merged["hooks"]
        assert "pre_run_command" in merged["hooks"]

    def test_setup_ide_hooks_windsurf_new(self, tmp_path):
        """Test setting up Windsurf hooks in new config."""
        setup = IDESetup()

        config_file = tmp_path / "hooks.json"

        with (
            mock.patch.object(
                setup,
                "IDE_CONFIGS",
                {
                    "windsurf": {
                        "name": "Windsurf",
                        "config_path": str(config_file),
                        "config_dir_env_var": None,
                        "config_filename": "hooks.json",
                        "hooks": {
                            "hooks": {
                                "pre_user_prompt": [{"command": "ai-guardian"}],
                                "pre_run_command": [{"command": "ai-guardian"}],
                                "post_run_command": [{"command": "ai-guardian"}],
                                "pre_read_code": [{"command": "ai-guardian"}],
                                "pre_write_code": [{"command": "ai-guardian"}],
                                "pre_mcp_tool_use": [{"command": "ai-guardian"}],
                            }
                        },
                    }
                },
            ),
            mock.patch.object(
                setup, "verify_gitleaks_installed", return_value=(True, "ok")
            ),
        ):
            success, message = setup.setup_ide_hooks(
                "windsurf", dry_run=False, force=False
            )

            assert success is True
            assert "Windsurf" in message

            with open(config_file) as f:
                written = json.load(f)
            assert "hooks" in written
            assert "pre_user_prompt" in written["hooks"]
            assert "pre_run_command" in written["hooks"]
            assert "pre_read_code" in written["hooks"]
            assert "pre_write_code" in written["hooks"]
            assert "pre_mcp_tool_use" in written["hooks"]

    def test_setup_remote_config_new_file(self, tmp_path):
        """Test setting up remote config in new file."""
        setup = IDESetup()

        config_file = tmp_path / "ai-guardian" / "ai-guardian.json"

        with mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": str(tmp_path), "AI_GUARDIAN_CONFIG_DIR": ""}
        ):
            success, message = setup.setup_remote_config(
                "https://example.com/policy.json", dry_run=False
            )

            assert success is True
            assert config_file.exists()

            # Verify config content
            with open(config_file) as f:
                config = json.load(f)

            assert "remote_configs" in config
            assert "urls" in config["remote_configs"]
            assert len(config["remote_configs"]["urls"]) == 1
            assert (
                config["remote_configs"]["urls"][0]["url"]
                == "https://example.com/policy.json"
            )
            assert config["remote_configs"]["urls"][0]["enabled"] is True

    def test_setup_remote_config_existing_file_no_section(self, tmp_path):
        """Test adding remote config section to existing file."""
        setup = IDESetup()

        config_file = tmp_path / "ai-guardian" / "ai-guardian.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Create existing config without remote_configs
        existing_config = {"permissions": []}
        config_file.write_text(json.dumps(existing_config))

        with mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": str(tmp_path), "AI_GUARDIAN_CONFIG_DIR": ""}
        ):
            success, message = setup.setup_remote_config(
                "https://example.com/policy.json", dry_run=False
            )

            assert success is True

            # Verify config content
            with open(config_file) as f:
                config = json.load(f)

            assert "permissions" in config  # Preserved
            assert "remote_configs" in config
            assert len(config["remote_configs"]["urls"]) == 1

    def test_setup_remote_config_append_to_existing(self, tmp_path):
        """Test appending URL to existing remote_configs."""
        setup = IDESetup()

        config_file = tmp_path / "ai-guardian" / "ai-guardian.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Create config with existing remote_configs
        existing_config = {
            "remote_configs": {
                "urls": [{"url": "https://example.com/policy1.json", "enabled": True}]
            }
        }
        config_file.write_text(json.dumps(existing_config))

        with mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": str(tmp_path), "AI_GUARDIAN_CONFIG_DIR": ""}
        ):
            success, message = setup.setup_remote_config(
                "https://example.com/policy2.json", dry_run=False
            )

            assert success is True

            # Verify config content
            with open(config_file) as f:
                config = json.load(f)

            assert len(config["remote_configs"]["urls"]) == 2
            assert (
                config["remote_configs"]["urls"][0]["url"]
                == "https://example.com/policy1.json"
            )
            assert (
                config["remote_configs"]["urls"][1]["url"]
                == "https://example.com/policy2.json"
            )

    def test_setup_remote_config_duplicate_url(self, tmp_path):
        """Test adding duplicate URL fails."""
        setup = IDESetup()

        config_file = tmp_path / "ai-guardian" / "ai-guardian.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Create config with existing URL
        existing_config = {
            "remote_configs": {
                "urls": [{"url": "https://example.com/policy.json", "enabled": True}]
            }
        }
        config_file.write_text(json.dumps(existing_config))

        with mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": str(tmp_path), "AI_GUARDIAN_CONFIG_DIR": ""}
        ):
            success, message = setup.setup_remote_config(
                "https://example.com/policy.json", dry_run=False
            )

            assert success is False
            assert "already exists" in message

    def test_setup_remote_config_dry_run(self, tmp_path):
        """Test dry-run mode for remote config."""
        setup = IDESetup()

        config_file = tmp_path / "ai-guardian" / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
            success, message = setup.setup_remote_config(
                "https://example.com/policy.json", dry_run=True
            )

            assert success is True
            assert "[DRY RUN]" in message
            assert not config_file.exists()

    def test_verify_gitleaks_installed_success(self):
        """Test Gitleaks verification when installed."""
        setup = IDESetup()

        with mock.patch("subprocess.run") as mock_run:
            # Mock successful gitleaks version check
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "gitleaks version 8.18.0\n"
            mock_run.return_value = mock_result

            success, message = setup.verify_gitleaks_installed()

            assert success is True
            assert "✓ Gitleaks is installed" in message
            assert "gitleaks version" in message
            mock_run.assert_called_once_with(
                ["gitleaks", "version"], capture_output=True, text=True, timeout=5
            )

    def test_verify_gitleaks_not_found(self):
        """Test Gitleaks verification when not installed."""
        setup = IDESetup()

        with mock.patch("subprocess.run") as mock_run:
            # Mock FileNotFoundError (gitleaks not installed)
            mock_run.side_effect = FileNotFoundError("gitleaks command not found")

            success, message = setup.verify_gitleaks_installed()

            assert success is False
            assert "❌ Gitleaks not found" in message
            assert "https://github.com/gitleaks/gitleaks#installing" in message
            assert "brew install gitleaks" in message

    def test_verify_gitleaks_timeout(self):
        """Test Gitleaks verification when command times out."""
        import subprocess

        setup = IDESetup()

        with mock.patch("subprocess.run") as mock_run:
            # Mock timeout
            mock_run.side_effect = subprocess.TimeoutExpired("gitleaks", 5)

            success, message = setup.verify_gitleaks_installed()

            assert success is False
            assert "❌ Gitleaks check timed out" in message

    def test_verify_gitleaks_command_failed(self):
        """Test Gitleaks verification when command returns non-zero."""
        setup = IDESetup()

        with mock.patch("subprocess.run") as mock_run:
            # Mock failed command
            mock_result = mock.MagicMock()
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            success, message = setup.verify_gitleaks_installed()

            assert success is False
            assert "❌ Gitleaks command failed" in message

    def test_setup_ide_hooks_shows_gitleaks_warning(self, tmp_path):
        """Test that setup shows warning when Gitleaks is not installed."""
        setup = IDESetup()

        config_file = tmp_path / "settings.json"

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {
                    "name": "Claude Code",
                    "config_path": str(config_file),
                    "hooks": {"UserPromptSubmit": [{"test": "hook"}]},
                }
            },
        ):
            # Mock Gitleaks as not installed
            with mock.patch.object(setup, "verify_gitleaks_installed") as mock_verify:
                mock_verify.return_value = (False, "❌ Gitleaks not found")

                success, message = setup.setup_ide_hooks(
                    "claude", dry_run=False, force=False
                )

                assert success is True
                assert "❌ Gitleaks not found" in message
                assert "WARNING: Secret scanning will be disabled" in message
                assert "install gitleaks" in message.lower()

    # ── supports_hooks ──────────────────────────────────────────────────

    def test_supports_hooks_true_for_claude(self):
        setup = IDESetup()
        assert setup.supports_hooks("claude") is True

    def test_supports_hooks_false_for_mcp_only(self):
        setup = IDESetup()
        assert setup.supports_hooks("junie") is False

    def test_supports_hooks_false_for_unknown(self):
        setup = IDESetup()
        assert setup.supports_hooks("nonexistent-ide") is False

    # ── check_hooks_for_ide ─────────────────────────────────────────────

    def test_check_hooks_for_ide_unknown(self):
        setup = IDESetup()
        configured, detail = setup.check_hooks_for_ide("nonexistent")
        assert configured is False
        assert "Unknown" in detail

    def test_check_hooks_for_ide_mcp_only(self):
        setup = IDESetup()
        configured, detail = setup.check_hooks_for_ide("junie")
        assert configured is True
        assert "MCP-only" in detail

    def test_check_hooks_for_ide_configured(self, tmp_path):
        setup = IDESetup()
        config_file = tmp_path / "settings.json"
        hooks = {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "matcher": "*",
                        "hooks": [{"type": "command", "command": "ai-guardian"}],
                    }
                ]
            }
        }
        config_file.write_text(json.dumps(hooks))
        with mock.patch.object(setup, "get_config_path", return_value=str(config_file)):
            configured, detail = setup.check_hooks_for_ide("claude")
        assert configured is True
        assert "configured" in detail

    def test_check_hooks_for_ide_not_configured(self, tmp_path):
        setup = IDESetup()
        config_file = tmp_path / "settings.json"
        config_file.write_text("{}")
        with mock.patch.object(setup, "get_config_path", return_value=str(config_file)):
            configured, detail = setup.check_hooks_for_ide("claude")
        assert configured is False
        assert "not configured" in detail

    # ── get_ide_for_mcp_client ──────────────────────────────────────────

    def test_get_ide_for_mcp_client_known(self):
        assert IDESetup.get_ide_for_mcp_client("claude-code") == "claude"
        assert IDESetup.get_ide_for_mcp_client("cursor") == "cursor"
        assert IDESetup.get_ide_for_mcp_client("github-copilot") == "copilot"
        assert IDESetup.get_ide_for_mcp_client("codex-cli") == "codex"
        assert IDESetup.get_ide_for_mcp_client("gemini-cli") == "gemini"
        assert IDESetup.get_ide_for_mcp_client("windsurf") == "windsurf"
        assert IDESetup.get_ide_for_mcp_client("opencode") == "opencode"
        assert IDESetup.get_ide_for_mcp_client("augment") == "augment"
        assert IDESetup.get_ide_for_mcp_client("kiro") == "kiro"

    def test_get_ide_for_mcp_client_unknown(self):
        assert IDESetup.get_ide_for_mcp_client("unknown-agent") is None
        assert IDESetup.get_ide_for_mcp_client("") is None


class TestIDESetupParametrized:
    """Parametrized tests covering common IDE setup patterns across all adapters."""

    # ── Helpers ──────────────────────────────────────────────────────────

    # Config data that makes check_hooks_configured return True for each IDE
    _CONFIGURED_CONFIGS = {
        "claude": {
            "hooks": {
                "UserPromptSubmit": [
                    {"matcher": "*", "hooks": [{"command": "ai-guardian"}]}
                ]
            }
        },
        "cursor": {"hooks": {"beforeSubmitPrompt": [{"command": "ai-guardian"}]}},
        "windsurf": {"hooks": {"pre_user_prompt": [{"command": "ai-guardian"}]}},
        "codex": {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "command", "command": "ai-guardian"}],
                    }
                ]
            }
        },
        "gemini": {
            "hooks": [
                {"event": "BeforeTool", "matcher": ".*", "command": "ai-guardian"}
            ]
        },
        "augment": {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "launch-process|str-replace-editor|save-file|view",
                        "hooks": [{"type": "command", "command": "ai-guardian"}],
                    }
                ]
            }
        },
    }

    # Config data where ai-guardian is NOT present (uses other-tool)
    _NOT_CONFIGURED_CONFIGS = {
        "claude": {"hooks": {}},
        "cursor": {"hooks": {}},
        "windsurf": {"hooks": {"pre_user_prompt": [{"command": "other-tool"}]}},
        "codex": {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    }
                ]
            }
        },
        "gemini": {
            "hooks": [{"event": "BeforeTool", "matcher": ".*", "command": "other-tool"}]
        },
        "augment": {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "launch-process",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    }
                ]
            }
        },
    }

    @staticmethod
    def _make_ide_config_override(setup, ide_name, config_path, **extra):
        """Build a minimal IDE_CONFIGS override for a single IDE."""
        real_cfg = IDESetup.IDE_CONFIGS[ide_name]
        override = {
            "name": real_cfg["name"],
            "config_path": str(config_path),
            "config_dir_env_var": None,
            "config_filename": real_cfg.get("config_filename"),
        }
        if real_cfg.get("script_based"):
            override["script_based"] = True
            override["hook_scripts"] = real_cfg["hook_scripts"]
            override["script_content"] = real_cfg["script_content"]
        else:
            override["hooks"] = real_cfg["hooks"]
        override.update(extra)
        return {ide_name: override}

    # ── IDE registration ─────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "ide_name",
        ["codex", "gemini", "cline", "zoocode", "augment", "kiro"],
        ids=["codex", "gemini", "cline", "zoocode", "augment", "kiro"],
    )
    def test_ide_in_ide_configs(self, ide_name):
        """Verify IDE entry exists in IDE_CONFIGS with a name and hooks/scripts."""
        assert ide_name in IDESetup.IDE_CONFIGS
        cfg = IDESetup.IDE_CONFIGS[ide_name]
        assert "name" in cfg
        assert cfg["name"]  # non-empty
        if cfg.get("script_based"):
            assert "hook_scripts" in cfg
        else:
            assert "hooks" in cfg

    # ── check_hooks_configured (JSON-based IDEs) ─────────────────────────

    @pytest.mark.parametrize(
        "ide_name",
        ["claude", "cursor", "windsurf", "codex", "gemini", "augment"],
        ids=["claude", "cursor", "windsurf", "codex", "gemini", "augment"],
    )
    def test_check_hooks_configured_json(self, tmp_path, ide_name):
        """Verify check_hooks_configured returns True when ai-guardian is present."""
        setup = IDESetup()
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._CONFIGURED_CONFIGS[ide_name]))
        assert setup.check_hooks_configured(config_file, ide_name) is True

    @pytest.mark.parametrize(
        "ide_name",
        ["claude", "cursor", "windsurf", "codex", "gemini", "augment"],
        ids=["claude", "cursor", "windsurf", "codex", "gemini", "augment"],
    )
    def test_check_hooks_not_configured_json(self, tmp_path, ide_name):
        """Verify check_hooks_configured returns False when ai-guardian is absent."""
        setup = IDESetup()
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._NOT_CONFIGURED_CONFIGS[ide_name]))
        assert setup.check_hooks_configured(config_file, ide_name) is False

    # ── check_hooks_configured (script-based IDEs) ───────────────────────

    @pytest.mark.parametrize("ide_name", ["cline", "kiro"], ids=["cline", "kiro"])
    def test_check_hooks_configured_script(self, tmp_path, ide_name):
        """Verify check_hooks_configured returns True when script contains ai-guardian."""
        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir(parents=True)
        script = hooks_dir / "PreToolUse"
        script.write_text("#!/bin/sh\nai-guardian\n")
        assert setup.check_hooks_configured(hooks_dir, ide_name) is True

    @pytest.mark.parametrize("ide_name", ["cline", "kiro"], ids=["cline", "kiro"])
    def test_check_hooks_not_configured_script(self, tmp_path, ide_name):
        """Verify check_hooks_configured returns False when script has other-tool."""
        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir(parents=True)
        script = hooks_dir / "PreToolUse"
        script.write_text("#!/bin/sh\nother-tool\n")
        assert setup.check_hooks_configured(hooks_dir, ide_name) is False

    @pytest.mark.parametrize("ide_name", ["cline", "kiro"], ids=["cline", "kiro"])
    def test_check_hooks_not_configured_script_empty(self, tmp_path, ide_name):
        """Verify check_hooks_configured returns False when hooks dir is absent."""
        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"
        assert setup.check_hooks_configured(hooks_dir, ide_name) is False

    # ── setup_ide_hooks new (JSON-based) ─────────────────────────────────

    @pytest.mark.parametrize(
        "ide_name",
        ["claude", "windsurf", "codex", "augment"],
        ids=["claude", "windsurf", "codex", "augment"],
    )
    def test_setup_ide_hooks_json_new(self, tmp_path, ide_name):
        """Setting up hooks in an empty directory creates valid JSON config."""
        setup = IDESetup()
        config_file = tmp_path / "config.json"
        ide_override = self._make_ide_config_override(setup, ide_name, config_file)

        with mock.patch.object(setup, "IDE_CONFIGS", ide_override):
            success, message = setup.setup_ide_hooks(
                ide_name, dry_run=False, force=False
            )

        assert success is True
        assert config_file.exists()
        with open(config_file) as f:
            config = json.load(f)
        assert "hooks" in config

    # ── setup_ide_hooks new (script-based) ───────────────────────────────

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix script hooks test")
    @pytest.mark.parametrize("ide_name", ["cline", "kiro"], ids=["cline", "kiro"])
    def test_setup_ide_hooks_script_new(self, tmp_path, ide_name):
        """Setting up script-based hooks creates executable scripts."""
        import stat

        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"
        ide_override = self._make_ide_config_override(setup, ide_name, hooks_dir)

        with mock.patch.object(setup, "IDE_CONFIGS", ide_override):
            success, message = setup.setup_ide_hooks(
                ide_name, dry_run=False, force=False
            )

        assert success is True
        assert hooks_dir.exists()
        expected_scripts = IDESetup.IDE_CONFIGS[ide_name]["hook_scripts"]
        for script_name in expected_scripts:
            script_path = hooks_dir / script_name
            assert script_path.exists(), f"Missing script: {script_name}"
            content = script_path.read_text()
            assert "ai-guardian" in content
            assert script_path.stat().st_mode & stat.S_IXUSR

    # ── setup_ide_hooks dry-run ──────────────────────────────────────────

    @pytest.mark.parametrize(
        "ide_name",
        ["claude", "windsurf", "codex", "gemini", "augment", "cline", "kiro"],
        ids=["claude", "windsurf", "codex", "gemini", "augment", "cline", "kiro"],
    )
    def test_setup_ide_hooks_dry_run(self, tmp_path, ide_name):
        """Dry-run mode returns success with DRY RUN and creates no files."""
        setup = IDESetup()
        config_path = tmp_path / "config_or_hooks"
        ide_override = self._make_ide_config_override(setup, ide_name, config_path)

        with mock.patch.object(setup, "IDE_CONFIGS", ide_override):
            success, message = setup.setup_ide_hooks(
                ide_name, dry_run=True, force=False
            )

        assert success is True
        assert "[DRY RUN]" in message
        assert not config_path.exists()

    # ── setup_ide_hooks force overwrite (JSON-based) ─────────────────────

    @pytest.mark.parametrize(
        "ide_name",
        ["claude", "codex", "augment"],
        ids=["claude", "codex", "augment"],
    )
    def test_setup_ide_hooks_json_force_overwrite(self, tmp_path, ide_name):
        """Force overwrite of existing JSON hooks creates backup."""
        setup = IDESetup()
        config_file = tmp_path / "config.json"
        # Write existing config with ai-guardian present
        config_file.write_text(
            json.dumps(
                self._CONFIGURED_CONFIGS.get(
                    ide_name,
                    {
                        "hooks": {
                            "PreToolUse": [{"hooks": [{"command": "ai-guardian"}]}]
                        }
                    },
                )
            )
        )
        ide_override = self._make_ide_config_override(setup, ide_name, config_file)

        with mock.patch.object(setup, "IDE_CONFIGS", ide_override):
            success, message = setup.setup_ide_hooks(
                ide_name, dry_run=False, force=True
            )

        assert success is True
        backup_file = config_file.with_suffix(".json.backup")
        assert backup_file.exists()

    # ── setup_ide_hooks already-configured (JSON-based) ──────────────────

    @pytest.mark.parametrize(
        "ide_name",
        ["codex"],
        ids=["codex"],
    )
    def test_setup_ide_hooks_json_already_configured(self, tmp_path, ide_name):
        """Setup returns failure when hooks already configured without force."""
        setup = IDESetup()
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._CONFIGURED_CONFIGS[ide_name]))
        ide_override = self._make_ide_config_override(setup, ide_name, config_file)

        with mock.patch.object(setup, "IDE_CONFIGS", ide_override):
            success, message = setup.setup_ide_hooks(
                ide_name, dry_run=False, force=False
            )

        assert success is False
        assert "already configured" in message

    # ── merge_hooks new (basic IDEs) ─────────────────────────────────────

    @pytest.mark.parametrize(
        "ide_name",
        ["claude", "cursor"],
        ids=["claude", "cursor"],
    )
    def test_merge_hooks_new(self, ide_name):
        """Merging hooks into empty config creates hooks section."""
        setup = IDESetup()
        ai_guardian_hooks = IDESetup.IDE_CONFIGS[ide_name]["hooks"]
        merged, warnings = setup.merge_hooks({}, ai_guardian_hooks, ide_name)
        assert "hooks" in merged or "version" in merged


class TestConfigDirEnvironmentVariable:
    """Test cases for AI_GUARDIAN_CONFIG_DIR environment variable."""

    def test_ai_guardian_config_dir_env_var(self, tmp_path):
        """Test that AI_GUARDIAN_CONFIG_DIR environment variable is respected."""
        from ai_guardian.config.manager import ConfigManager

        custom_dir = tmp_path / "custom-config"
        custom_dir.mkdir()

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(custom_dir)}):
            config_mgr = ConfigManager()
            assert config_mgr.config_dir == custom_dir

    def test_ai_guardian_config_dir_takes_priority_over_xdg(self, tmp_path):
        """Test that AI_GUARDIAN_CONFIG_DIR takes priority over XDG_CONFIG_HOME."""
        from ai_guardian.config.manager import ConfigManager

        ai_guardian_dir = tmp_path / "ai-guardian-custom"
        xdg_dir = tmp_path / "xdg-home"
        ai_guardian_dir.mkdir()
        xdg_dir.mkdir()

        env = {
            "AI_GUARDIAN_CONFIG_DIR": str(ai_guardian_dir),
            "XDG_CONFIG_HOME": str(xdg_dir),
        }

        with mock.patch.dict(os.environ, env, clear=True):
            config_mgr = ConfigManager()
            # Should use AI_GUARDIAN_CONFIG_DIR, not XDG_CONFIG_HOME/ai-guardian
            assert config_mgr.config_dir == ai_guardian_dir
            assert config_mgr.config_dir != xdg_dir / "ai-guardian"

    def test_xdg_config_home_fallback(self, tmp_path):
        """Test XDG_CONFIG_HOME is used when AI_GUARDIAN_CONFIG_DIR is not set."""
        from ai_guardian.config.manager import ConfigManager

        xdg_dir = tmp_path / "xdg-home"
        xdg_dir.mkdir()

        # Only set XDG_CONFIG_HOME, not AI_GUARDIAN_CONFIG_DIR
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_dir)}, clear=True):
            config_mgr = ConfigManager()
            assert config_mgr.config_dir == xdg_dir / "ai-guardian"

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows uses APPDATA")
    def test_default_config_dir_when_no_env_vars(self):
        """Test default config directory when no environment variables are set."""
        from ai_guardian.config.manager import ConfigManager

        # Clear both environment variables
        env_backup = os.environ.copy()
        try:
            if "AI_GUARDIAN_CONFIG_DIR" in os.environ:
                del os.environ["AI_GUARDIAN_CONFIG_DIR"]
            if "XDG_CONFIG_HOME" in os.environ:
                del os.environ["XDG_CONFIG_HOME"]

            config_mgr = ConfigManager()
            expected = Path("~/.config/ai-guardian").expanduser()
            assert config_mgr.config_dir == expected
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_config_dir_with_tilde_expansion(self, tmp_path):
        """Test that tilde in AI_GUARDIAN_CONFIG_DIR is expanded."""
        from ai_guardian.config.manager import ConfigManager

        # Use a path with tilde (will be expanded)
        with mock.patch.dict(
            os.environ, {"AI_GUARDIAN_CONFIG_DIR": "~/my-ai-guardian"}
        ):
            config_mgr = ConfigManager()
            # Should be expanded, not contain literal ~
            assert "~" not in str(config_mgr.config_dir)
            assert config_mgr.config_dir == Path("~/my-ai-guardian").expanduser()

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows uses APPDATA")
    def test_get_config_dir_utility_function(self, tmp_path):
        """Test the get_config_dir utility function directly."""
        custom_dir = tmp_path / "test-config"
        custom_dir.mkdir()

        # Test with AI_GUARDIAN_CONFIG_DIR
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(custom_dir)}):
            result = get_config_dir()
            assert result == custom_dir

        # Test with XDG_CONFIG_HOME only
        xdg_dir = tmp_path / "xdg"
        xdg_dir.mkdir()
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_dir)}, clear=True):
            result = get_config_dir()
            assert result == xdg_dir / "ai-guardian"

        # Test default (no env vars)
        with mock.patch.dict(os.environ, {}, clear=True):
            result = get_config_dir()
            assert result == Path("~/.config/ai-guardian").expanduser()

    def test_setup_remote_config_with_custom_config_dir(self, tmp_path):
        """Test that setup_remote_config respects AI_GUARDIAN_CONFIG_DIR."""
        setup = IDESetup()

        custom_dir = tmp_path / "custom-ai-guardian"
        custom_dir.mkdir()
        config_file = custom_dir / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(custom_dir)}):
            success, message = setup.setup_remote_config(
                "https://example.com/policy.json", dry_run=False
            )

            assert success is True
            assert config_file.exists()

            # Verify the URL was added to config
            with open(config_file) as f:
                config = json.load(f)
            assert "remote_configs" in config
            assert any(
                "example.com" in str(entry)
                for entry in config["remote_configs"]["urls"]
            )

    def test_tool_policy_uses_custom_config_dir(self, tmp_path):
        """Test that ToolPolicyChecker respects AI_GUARDIAN_CONFIG_DIR."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        custom_dir = tmp_path / "custom-config"
        custom_dir.mkdir()

        # Create a test config file
        config_file = custom_dir / "ai-guardian.json"
        test_config = {"builtin_tools": {"deny": ["Bash"], "allow": ["Read"]}}
        config_file.write_text(json.dumps(test_config))

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(custom_dir)}):
            checker = ToolPolicyChecker()
            # Verify it loaded from the custom directory
            assert checker.config is not None


class TestCodexSetup:
    """Test cases for Codex IDE setup."""

    def test_codex_hooks_use_regex_matcher(self):
        """Verify Codex PreToolUse/PostToolUse use regex matcher '.*'."""
        hooks = IDESetup.IDE_CONFIGS["codex"]["hooks"]
        assert hooks["PreToolUse"][0]["matcher"] == ".*"
        assert hooks["PostToolUse"][0]["matcher"] == ".*"
        assert "matcher" not in hooks["UserPromptSubmit"][0]

    def test_codex_hooks_have_timeout(self):
        """Verify Codex hooks include timeout field with event-appropriate values."""
        hooks = IDESetup.IDE_CONFIGS["codex"]["hooks"]
        assert hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"] == 300
        assert hooks["PreToolUse"][0]["hooks"][0]["timeout"] == 300
        assert hooks["PostToolUse"][0]["hooks"][0]["timeout"] == 60

    def test_codex_hooks_include_session_end_and_post_compact(self):
        """Verify Codex config includes SessionEnd and PostCompact hooks."""
        hooks = IDESetup.IDE_CONFIGS["codex"]["hooks"]
        assert "SessionEnd" in hooks
        assert "PostCompact" in hooks
        assert hooks["SessionEnd"][0]["hooks"][0]["command"] == "ai-guardian"
        assert hooks["PostCompact"][0]["hooks"][0]["command"] == "ai-guardian"

    def test_codex_has_five_hook_events(self):
        """Verify Codex installs all 5 hook events."""
        hooks = IDESetup.IDE_CONFIGS["codex"]["hooks"]
        expected = {
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "SessionEnd",
            "PostCompact",
        }
        assert set(hooks.keys()) == expected

    def test_merge_hooks_codex_preserves_other_hooks(self, tmp_path):
        """Test that merging Codex hooks preserves existing non-ai-guardian hooks."""
        setup = IDESetup()
        existing_config = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    }
                ]
            }
        }
        ai_guardian_hooks = IDESetup.IDE_CONFIGS["codex"]["hooks"]

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "codex"
        )

        pre_tool_hooks = merged["hooks"]["PreToolUse"][0]["hooks"]
        assert pre_tool_hooks[0]["command"] == "ai-guardian"
        assert pre_tool_hooks[1]["command"] == "other-tool"
        assert len(warnings) > 0


class TestGeminiSetup:
    """Test cases for Gemini CLI setup."""

    def test_gemini_hooks_use_array_format(self):
        """Verify Gemini hooks use array format with event/matcher/command."""
        hooks_config = IDESetup.IDE_CONFIGS["gemini"]["hooks"]
        hooks = hooks_config["hooks"]
        assert isinstance(hooks, list)
        assert len(hooks) == 4

        events = [h["event"] for h in hooks]
        assert "SessionStart" in events
        assert "BeforeAgent" in events
        assert "BeforeTool" in events
        assert "AfterTool" in events

        for h in hooks:
            assert h["command"] == "ai-guardian"

    def test_gemini_tool_hooks_have_matcher(self):
        """Verify BeforeTool and AfterTool hooks have matcher field."""
        hooks = IDESetup.IDE_CONFIGS["gemini"]["hooks"]["hooks"]
        for h in hooks:
            if h["event"] in ("BeforeTool", "AfterTool"):
                assert h["matcher"] == ".*"

    def test_merge_hooks_gemini_new(self):
        """Test merging Gemini hooks into empty config."""
        setup = IDESetup()
        existing_config = {}
        ai_guardian_hooks = IDESetup.IDE_CONFIGS["gemini"]["hooks"]

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "gemini"
        )

        assert "hooks" in merged
        assert isinstance(merged["hooks"], list)
        assert len(merged["hooks"]) == 4
        assert len(warnings) == 0

    def test_merge_hooks_gemini_existing(self):
        """Test merging Gemini hooks preserves other hooks."""
        setup = IDESetup()
        existing_config = {
            "hooks": [{"event": "BeforeTool", "matcher": ".*", "command": "other-tool"}]
        }
        ai_guardian_hooks = IDESetup.IDE_CONFIGS["gemini"]["hooks"]

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "gemini"
        )

        assert len(merged["hooks"]) == 5
        assert merged["hooks"][0]["command"] == "ai-guardian"
        assert merged["hooks"][4]["command"] == "other-tool"
        assert len(warnings) > 0

    def test_merge_hooks_gemini_replaces_existing_ai_guardian(self):
        """Test that merging replaces existing ai-guardian hooks."""
        setup = IDESetup()
        existing_config = {
            "hooks": [
                {"event": "BeforeTool", "matcher": ".*", "command": "ai-guardian"},
                {"event": "BeforeTool", "matcher": ".*", "command": "other-tool"},
            ]
        }
        ai_guardian_hooks = IDESetup.IDE_CONFIGS["gemini"]["hooks"]

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "gemini"
        )

        ag_hooks = [h for h in merged["hooks"] if h.get("command") == "ai-guardian"]
        other_hooks = [h for h in merged["hooks"] if h.get("command") != "ai-guardian"]
        assert len(ag_hooks) == 4
        assert len(other_hooks) == 1


class TestClineSetup:
    """Test cases for Cline/ZooCode setup."""

    def test_cline_hooks_are_script_based(self):
        """Verify Cline uses script-based hooks with correct event names."""
        cline_cfg = IDESetup.IDE_CONFIGS["cline"]
        assert cline_cfg["script_based"] is True
        scripts = cline_cfg["hook_scripts"]
        assert "PreToolUse" in scripts
        assert "PostToolUse" in scripts
        assert "UserPromptSubmit" in scripts

    def test_cline_script_content(self):
        """Verify script content calls ai-guardian."""
        cline_cfg = IDESetup.IDE_CONFIGS["cline"]
        content = cline_cfg["script_content"]
        assert content.startswith("#!/bin/sh")
        assert "ai-guardian" in content

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix script hooks test")
    def test_setup_ide_hooks_cline_force(self, tmp_path):
        """Test force flag overwrites existing Cline scripts."""
        setup = IDESetup()
        hooks_dir = tmp_path / ".clinerules" / "hooks"
        hooks_dir.mkdir(parents=True)
        old_script = hooks_dir / "PreToolUse"
        old_script.write_text("#!/bin/sh\nai-guardian\n")

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "cline": {
                    "name": "Cline",
                    "config_path": str(hooks_dir),
                    "config_dir_env_var": None,
                    "config_filename": None,
                    "script_based": True,
                    "hook_scripts": IDESetup.IDE_CONFIGS["cline"]["hook_scripts"],
                    "script_content": IDESetup.IDE_CONFIGS["cline"]["script_content"],
                }
            },
        ):
            success, message = setup.setup_ide_hooks("cline", dry_run=False, force=True)
            assert success is True

            for script_name in ["PreToolUse", "PostToolUse", "UserPromptSubmit"]:
                assert (hooks_dir / script_name).exists()


class TestAugmentSetup:
    """Test cases for Augment Code setup."""

    def test_augment_hook_structure(self):
        """Verify Augment hooks use nested hooks.hooks structure."""
        hooks = IDESetup.IDE_CONFIGS["augment"]["hooks"]
        assert "hooks" in hooks
        inner = hooks["hooks"]
        assert "PreToolUse" in inner
        assert "PostToolUse" in inner

    def test_augment_hooks_use_pipe_matcher(self):
        """Verify Augment hooks use pipe-separated tool matcher."""
        inner = IDESetup.IDE_CONFIGS["augment"]["hooks"]["hooks"]
        matcher = inner["PreToolUse"][0]["matcher"]
        assert "launch-process" in matcher
        assert "str-replace-editor" in matcher
        assert "save-file" in matcher
        assert "view" in matcher

    def test_augment_hooks_have_timeout(self):
        """Verify Augment hooks include timeout field."""
        inner = IDESetup.IDE_CONFIGS["augment"]["hooks"]["hooks"]
        for event in ["PreToolUse", "PostToolUse"]:
            hook_entry = inner[event][0]["hooks"][0]
            assert hook_entry["timeout"] == 5000

    def test_merge_hooks_augment_preserves_other_hooks(self):
        """Test that merging Augment hooks preserves existing non-ai-guardian hooks."""
        setup = IDESetup()
        existing_config = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "launch-process|str-replace-editor|save-file|view|remove-files",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    }
                ]
            }
        }
        ai_guardian_hooks = IDESetup.IDE_CONFIGS["augment"]["hooks"]

        merged, warnings = setup.merge_hooks(
            existing_config, ai_guardian_hooks, "augment"
        )

        pre_tool_hooks = merged["hooks"]["PreToolUse"][0]["hooks"]
        assert pre_tool_hooks[0]["command"] == "ai-guardian"
        assert pre_tool_hooks[1]["command"] == "other-tool"
        assert len(warnings) > 0


class TestSetupHooks:
    """Test cases for setup_hooks function."""

    def test_setup_hooks_no_ide_detected(self, tmp_path):
        """Test setup when no IDE is detected."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = []

            success = setup_hooks()

            assert success is False

    def test_setup_hooks_auto_detect_single(self, tmp_path):
        """Test auto-detection with single IDE."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            success = setup_hooks(interactive=False)

            assert success is True
            mock_instance.setup_ide_hooks.assert_called_once()

    def test_setup_hooks_explicit_ide(self, tmp_path):
        """Test explicit IDE specification."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {"cursor": {"name": "Cursor IDE"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            success = setup_hooks(ide_type="cursor", interactive=False)

            assert success is True
            mock_instance.setup_ide_hooks.assert_called_once_with(
                "cursor", dry_run=False, force=False
            )

    def test_setup_hooks_with_remote_config(self, tmp_path):
        """Test setup with remote config URL."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_remote_config.return_value = (
                True,
                "Remote config added",
            )
            mock_instance.setup_ide_hooks.return_value = (True, "Hooks configured")

            success = setup_hooks(
                ide_type="claude",
                remote_config_url="https://example.com/policy.json",
                interactive=False,
            )

            assert success is True
            mock_instance.setup_remote_config.assert_called_once()
            mock_instance.setup_ide_hooks.assert_called_once()

    def test_setup_hooks_remote_config_only(self, tmp_path):
        """Test setup with only remote config, no IDE."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.setup_remote_config.return_value = (
                True,
                "Remote config added",
            )

            success = setup_hooks(
                remote_config_url="https://example.com/policy.json", interactive=False
            )

            # Should fail because no IDE detected after remote config
            mock_instance.setup_remote_config.assert_called_once()

    def test_setup_hooks_invalid_ide_type(self):
        """Test setup with invalid IDE type."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {"claude": {}, "cursor": {}}

            success = setup_hooks(ide_type="invalid", interactive=False)

            assert success is False

    def test_setup_hooks_dry_run(self):
        """Test setup in dry-run mode."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "[DRY RUN] Success")

            success = setup_hooks(ide_type="claude", dry_run=True, interactive=False)

            assert success is True
            mock_instance.setup_ide_hooks.assert_called_once_with(
                "claude", dry_run=True, force=False
            )

    def test_setup_hooks_force_mode(self):
        """Test setup with force flag."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            success = setup_hooks(ide_type="claude", force=True, interactive=False)

            assert success is True
            mock_instance.setup_ide_hooks.assert_called_once_with(
                "claude", dry_run=False, force=True
            )

    def test_setup_remote_config_invalid_json(self, tmp_path):
        """Test setup with invalid JSON in existing config."""
        setup = IDESetup()

        config_file = tmp_path / "ai-guardian" / "ai-guardian.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("invalid json {")

        with mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": str(tmp_path), "AI_GUARDIAN_CONFIG_DIR": ""}
        ):
            success, message = setup.setup_remote_config(
                "https://example.com/policy.json", dry_run=False
            )

            assert success is False
            assert "Invalid JSON" in message

    def test_setup_ide_hooks_unknown_ide(self):
        """Test setup with unknown IDE type."""
        setup = IDESetup()

        success, message = setup.setup_ide_hooks(
            "unknown_ide", dry_run=False, force=False
        )

        assert success is False
        assert "Unknown IDE type" in message

    def test_claude_config_dir_env_var(self, tmp_path):
        """Test that CLAUDE_CONFIG_DIR environment variable is respected."""
        setup = IDESetup()

        custom_dir = tmp_path / "custom-claude"
        custom_dir.mkdir(parents=True)

        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(custom_dir)}):
            config_path = setup.get_claude_config_path()
            assert config_path == str(custom_dir / "settings.json")

    def test_claude_config_dir_default(self):
        """Test default Claude config path when env var not set."""
        setup = IDESetup()

        with mock.patch.dict(os.environ, {}, clear=True):
            if "CLAUDE_CONFIG_DIR" in os.environ:
                del os.environ["CLAUDE_CONFIG_DIR"]
            config_path = setup.get_claude_config_path()
            assert config_path == "~/.claude/settings.json"

    def test_setup_claude_with_custom_config_dir(self, tmp_path):
        """Test setup with custom CLAUDE_CONFIG_DIR."""
        setup = IDESetup()

        custom_dir = tmp_path / "custom-claude"
        custom_dir.mkdir(parents=True)
        config_file = custom_dir / "settings.json"

        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(custom_dir)}):
            success, message = setup.setup_ide_hooks(
                "claude", dry_run=False, force=False
            )

            assert success is True
            assert config_file.exists()

            # Verify config content
            with open(config_file) as f:
                config = json.load(f)

            assert "hooks" in config
            assert "UserPromptSubmit" in config["hooks"]

    def test_setup_hooks_interactive_shows_correct_path(self, tmp_path, capsys):
        """Test that interactive confirmation shows correct path with CLAUDE_CONFIG_DIR."""
        custom_dir = tmp_path / "custom-claude"
        custom_dir.mkdir(parents=True)

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {
                "claude": {
                    "name": "Claude Code",
                    "config_path": "~/.claude/settings.json",
                }
            }
            mock_instance.get_config_path.return_value = str(
                custom_dir / "settings.json"
            )
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            # Mock user saying "no" to abort
            with mock.patch("builtins.input", return_value="n"):
                with mock.patch.dict(
                    os.environ, {"CLAUDE_CONFIG_DIR": str(custom_dir)}
                ):
                    success = setup_hooks(
                        ide_type="claude", interactive=True, dry_run=False
                    )

            # Should have aborted
            assert success is False

            # Check that the correct path was shown in output
            captured = capsys.readouterr()
            assert str(custom_dir / "settings.json") in captured.out

    def test_setup_hooks_aborts_when_config_fails_with_ide(self, tmp_path):
        """setup_hooks returns False when create_default_config fails, even with ide_type set."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.setup.create_default_config",
                return_value=(False, "Profile not found: badprofile"),
            ):
                success = setup_hooks(
                    ide_type="claude",
                    create_config=True,
                    profile="badprofile",
                    interactive=False,
                )

            assert success is False
            mock_instance.setup_ide_hooks.assert_not_called()


class TestInstallScannerMultiple:
    """Test cases for --install-scanner accepting multiple scanners."""

    def test_install_single_scanner(self):
        """Single scanner installs successfully."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                mock_inst = MockInstaller.return_value
                mock_inst.install.return_value = True
                mock_inst.verify_installation.return_value = True

                success = setup_hooks(install_scanner=["gitleaks"], interactive=False)

                assert success is True
                mock_inst.install.assert_called_once_with(
                    "gitleaks", use_pinned=False, ensure_only=True
                )
                mock_inst.verify_installation.assert_called_once_with("gitleaks")

    def test_install_multiple_scanners(self):
        """Multiple scanners install in sequence."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                mock_inst = MockInstaller.return_value
                mock_inst.install.return_value = True
                mock_inst.verify_installation.return_value = True

                success = setup_hooks(
                    install_scanner=["gitleaks", "betterleaks"], interactive=False
                )

                assert success is True
                assert mock_inst.install.call_count == 2
                mock_inst.install.assert_any_call(
                    "gitleaks", use_pinned=False, ensure_only=True
                )
                mock_inst.install.assert_any_call(
                    "betterleaks", use_pinned=False, ensure_only=True
                )

    def test_install_no_scanner_when_none(self):
        """No scanner installation when install_scanner is None."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                success = setup_hooks(install_scanner=None, interactive=False)

                assert success is True
                MockInstaller.assert_not_called()

    def test_install_scanner_dry_run(self, capsys):
        """Dry run prints scanner names without installing."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            success = setup_hooks(
                install_scanner=["gitleaks", "betterleaks"],
                dry_run=True,
                interactive=False,
            )

            assert success is True
            captured = capsys.readouterr()
            assert "gitleaks" in captured.out
            assert "betterleaks" in captured.out

    def test_install_scanner_failure_continues_with_yes(self):
        """When a scanner fails and not interactive, setup continues."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                mock_inst = MockInstaller.return_value
                mock_inst.install.side_effect = [False, True]
                mock_inst.verify_installation.return_value = True

                success = setup_hooks(
                    install_scanner=["gitleaks", "betterleaks"], interactive=False
                )

                assert success is True
                assert mock_inst.install.call_count == 2

    def test_install_scanner_verification_failure(self, capsys):
        """Verification failure prints warning."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                mock_inst = MockInstaller.return_value
                mock_inst.install.return_value = True
                mock_inst.verify_installation.return_value = False

                success = setup_hooks(install_scanner=["gitleaks"], interactive=False)

                assert success is True
                captured = capsys.readouterr()
                assert "verification failed" in captured.out

    def test_install_all_three_scanners(self):
        """All three scanners install in sequence."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                mock_inst = MockInstaller.return_value
                mock_inst.install.return_value = True
                mock_inst.verify_installation.return_value = True

                success = setup_hooks(
                    install_scanner=["gitleaks", "betterleaks", "leaktk"],
                    interactive=False,
                )

                assert success is True
                assert mock_inst.install.call_count == 3
                mock_inst.install.assert_any_call(
                    "leaktk", use_pinned=False, ensure_only=True
                )

    def test_install_scanner_with_use_pinned(self):
        """--use-pinned passes use_pinned=True and ensure_only=False to installer."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                mock_inst = MockInstaller.return_value
                mock_inst.install.return_value = True
                mock_inst.verify_installation.return_value = True

                success = setup_hooks(
                    install_scanner=["gitleaks"], use_pinned=True, interactive=False
                )

                assert success is True
                mock_inst.install.assert_called_once_with(
                    "gitleaks", use_pinned=True, ensure_only=False
                )

    def test_install_scanner_without_use_pinned_default(self):
        """Without --use-pinned, ensure_only=True and use_pinned=False (default)."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch(
                "ai_guardian.scanners.installer.ScannerInstaller"
            ) as MockInstaller:
                mock_inst = MockInstaller.return_value
                mock_inst.install.return_value = True
                mock_inst.verify_installation.return_value = True

                success = setup_hooks(install_scanner=["gitleaks"], interactive=False)

                assert success is True
                mock_inst.install.assert_called_once_with(
                    "gitleaks", use_pinned=False, ensure_only=True
                )

    def test_install_scanner_use_pinned_dry_run(self, capsys):
        """Dry run with --use-pinned prints 'pinned' in output."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            success = setup_hooks(
                install_scanner=["gitleaks"],
                use_pinned=True,
                dry_run=True,
                interactive=False,
            )

            assert success is True
            captured = capsys.readouterr()
            assert "pinned" in captured.out
            assert "gitleaks" in captured.out


class TestCreateDefaultConfig:
    """Test cases for create_default_config functionality."""

    def test_create_default_config_success(self, tmp_path):
        """Test creating default config successfully."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=False, dry_run=False)

            assert success is True
            assert "✓ Created default config" in message
            assert "Secret scanning: Enabled" in message
            assert "Prompt injection: Enabled" in message
            assert "Permissions: Enabled" in message
            assert config_file.exists()

            # Verify config content
            with open(config_file) as f:
                config = json.load(f)

            assert "secret_scanning" in config
            assert config["secret_scanning"]["enabled"] is True
            assert "prompt_injection" in config
            assert config["prompt_injection"]["enabled"] is True
            assert "permissions" in config
            assert config["permissions"]["enabled"] is True
            assert (
                len(config["permissions"]["rules"]) == 4
            )  # catch-all allow + MCP deny(warn) + ai-guardian allow + Skill deny(warn)

    def test_create_default_config_permissive(self, tmp_path):
        """Test creating permissive config."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=True, dry_run=False)

            assert success is True
            assert "✓ Created default config" in message
            assert "Permissions: Disabled" in message
            assert config_file.exists()

            # Verify config content
            with open(config_file) as f:
                config = json.load(f)

            assert config["permissions"]["enabled"] is False
            assert (
                len(config["permissions"]["rules"]) == 1
            )  # catch-all allow rule in permissive mode

    def test_create_default_config_already_exists_preserves(self, tmp_path):
        """Test creating config when file already exists preserves it."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"existing": "config"}')

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=False, dry_run=False)

            assert success is True
            assert "preserving" in message

            with open(config_file) as f:
                config = json.load(f)
            assert config == {"existing": "config"}

    def test_create_default_config_force_overwrite(self, tmp_path):
        """Test --force overwrites existing config."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"existing": "config"}')

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(
                permissive=False, dry_run=False, force=True
            )

            assert success is True
            assert "✓ Created default config" in message

            with open(config_file) as f:
                config = json.load(f)
            assert "secret_scanning" in config
            assert "existing" not in config

    def test_force_strips_deprecated_pattern_server(self, tmp_path):
        """Issue #914: --force must not preserve deprecated secret_scanning.pattern_server."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"
        old_config = {
            "secret_scanning": {
                "enabled": True,
                "pattern_server": {
                    "url": "https://example.com",
                    "patterns_endpoint": "/patterns/gitleaks/8.27.0",
                },
                "engines": [{"type": "toml-patterns"}],
            },
            "prompt_injection": {"enabled": True},
        }
        config_file.write_text(json.dumps(old_config))

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(force=True)

            assert success is True
            with open(config_file) as f:
                config = json.load(f)
            assert "pattern_server" not in config.get("secret_scanning", {})
            assert "pattern_server" not in config

    def test_force_with_profile_strips_deprecated_pattern_server(self, tmp_path):
        """Issue #914: --force --profile @standard must produce clean config."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"
        old_config = {
            "secret_scanning": {
                "pattern_server": {"url": "https://old.example.com"},
            },
        }
        config_file.write_text(json.dumps(old_config))

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(profile="@standard", force=True)

            assert success is True
            with open(config_file) as f:
                config = json.load(f)
            ss = config.get("secret_scanning", {})
            assert "pattern_server" not in ss
            assert "engines" in ss

    def test_force_creates_config_that_passes_doctor(self, tmp_path):
        """Issue #914: config from --force must pass doctor check_global_pattern_server."""
        from ai_guardian.setup import create_default_config
        from ai_guardian.doctor import Doctor, CheckStatus

        config_file = tmp_path / "ai-guardian.json"
        old_config = {
            "secret_scanning": {
                "pattern_server": {"url": "https://stale.example.com"},
            },
        }
        config_file.write_text(json.dumps(old_config))

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, _ = create_default_config(force=True)
            assert success is True

            with open(config_file) as f:
                config = json.load(f)

            doctor = Doctor(fix=False)
            doctor._config = config
            doctor._config_loaded = True
            result = doctor.check_global_pattern_server()
            assert result.status == CheckStatus.PASS

    def test_custom_profile_deprecated_key_stripped(self, tmp_path):
        """Issue #914: even custom profiles with deprecated keys get stripped."""
        from ai_guardian.setup import create_default_config

        profile_file = tmp_path / "custom.json"
        profile_config = {
            "secret_scanning": {
                "enabled": True,
                "pattern_server": {"url": "https://custom.example.com"},
                "engines": [{"type": "toml-patterns"}],
            },
            "prompt_injection": {"enabled": True, "sensitivity": "low"},
        }
        profile_file.write_text(json.dumps(profile_config))

        config_dir = tmp_path / "config"
        config_dir.mkdir()

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            success, message = create_default_config(profile=str(profile_file))

            assert success is True
            config_file = config_dir / "ai-guardian.json"
            with open(config_file) as f:
                config = json.load(f)
            assert "pattern_server" not in config.get("secret_scanning", {})

    def test_create_default_config_dry_run(self, tmp_path):
        """Test dry-run mode for config creation."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=False, dry_run=True)

            assert success is True
            assert "[DRY RUN]" in message
            assert "Would create" in message
            assert not config_file.exists()  # File should not be created

            # Verify JSON is in the message
            assert '"secret_scanning"' in message
            assert '"prompt_injection"' in message
            assert '"permissions"' in message

    def test_create_default_config_dry_run_permissive(self, tmp_path):
        """Test dry-run mode with permissive config."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=True, dry_run=True)

            assert success is True
            assert "[DRY RUN]" in message
            assert not config_file.exists()

            # Verify permissive settings in dry-run output
            assert (
                '"enabled": false' in message or '"enabled":false' in message
            )  # permissions disabled

    def test_setup_hooks_with_create_config(self, tmp_path):
        """Test setup with --create-config flag."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success = setup_hooks(
                ide_type=None,
                create_config=True,
                permissive=False,
                dry_run=False,
                interactive=False,
            )

            assert success is True
            assert config_file.exists()

    def test_setup_hooks_with_create_config_and_ide(self, tmp_path):
        """Test setup with both --create-config and IDE setup."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
                success = setup_hooks(
                    ide_type="claude",
                    create_config=True,
                    permissive=False,
                    dry_run=False,
                    interactive=False,
                )

                assert success is True
                assert config_file.exists()
                mock_instance.setup_ide_hooks.assert_called_once()

    def test_setup_multiple_ides_preserves_config(self, tmp_path):
        """Test setting up multiple IDEs sequentially preserves config (Issue #668)."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)},
                "cursor": {
                    "name": "Cursor",
                    "config_path": str(tmp_path / "hooks.json"),
                },
            }
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
                # First IDE: creates config
                success1 = setup_hooks(
                    ide_type="claude",
                    create_config=True,
                    dry_run=False,
                    interactive=False,
                )
                assert success1 is True
                assert config_file.exists()

                with open(config_file) as f:
                    original_config = json.load(f)

                # Second IDE: should preserve config
                success2 = setup_hooks(
                    ide_type="cursor",
                    create_config=True,
                    dry_run=False,
                    interactive=False,
                )
                assert success2 is True

                with open(config_file) as f:
                    preserved_config = json.load(f)
                assert preserved_config == original_config

    def test_setup_hooks_create_config_only(self, tmp_path):
        """Test setup with only --create-config (no IDE or remote config)."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success = setup_hooks(
                ide_type=None,
                remote_config_url=None,
                create_config=True,
                permissive=False,
                dry_run=False,
                interactive=False,
            )

            assert success is True
            assert config_file.exists()

    def test_setup_hooks_creates_cache_dir(self, tmp_path):
        """setup --create-config creates cache dir proactively (Issue #1499)."""
        from ai_guardian.setup import setup_hooks

        cache_dir = tmp_path / "cache" / "ai-guardian"

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(tmp_path),
                "AI_GUARDIAN_CACHE_DIR": str(cache_dir),
            },
        ):
            setup_hooks(
                ide_type=None,
                remote_config_url=None,
                create_config=True,
                permissive=False,
                dry_run=False,
                interactive=False,
            )

        assert (
            cache_dir.exists()
        ), "cache dir should be created proactively during setup"

    def test_create_config_exists_does_not_block_ide_hooks(self, tmp_path):
        """Test --create-config failure (config exists) does not block --ide hook setup (Issue #561)."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text("{}")
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.setup_ide_hooks.return_value = (True, "Success")

            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
                success = setup_hooks(
                    ide_type="claude",
                    create_config=True,
                    permissive=False,
                    dry_run=False,
                    interactive=False,
                )

                assert success is True
                mock_instance.setup_ide_hooks.assert_called_once()

    def test_create_config_exists_does_not_block_mcp(self, tmp_path):
        """Test --create-config failure (config exists) does not block MCP installation (Issue #561)."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text("{}")
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance.get_config_path.return_value = str(ide_config_file)

            with mock.patch("ai_guardian.setup._handle_mcp_setup") as mock_mcp:
                with mock.patch.dict(
                    os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}
                ):
                    success = setup_hooks(
                        ide_type="claude",
                        create_config=True,
                        permissive=False,
                        dry_run=False,
                        interactive=False,
                    )

                    assert success is True
                    mock_instance.setup_ide_hooks.assert_called_once()
                    mock_mcp.assert_called_once()

    def test_create_config_only_preserves_when_exists(self, tmp_path):
        """Test --create-config alone succeeds with preserving message when config exists (Issue #668)."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"custom": "value"}')

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success = setup_hooks(
                ide_type=None,
                remote_config_url=None,
                create_config=True,
                permissive=False,
                dry_run=False,
                interactive=False,
            )

            assert success is True
            with open(config_file) as f:
                config = json.load(f)
            assert config == {"custom": "value"}

    def test_create_config_force_overwrites_when_exists(self, tmp_path):
        """Test --create-config --force overwrites existing config (Issue #668)."""
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"custom": "value"}')

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success = setup_hooks(
                ide_type=None,
                remote_config_url=None,
                create_config=True,
                force=True,
                permissive=False,
                dry_run=False,
                interactive=False,
            )

            assert success is True
            with open(config_file) as f:
                config = json.load(f)
            assert "secret_scanning" in config
            assert "custom" not in config

    def test_get_default_config_template_secure(self):
        """Test _get_default_config_template returns secure config by default."""
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template(permissive=False)

        assert config["secret_scanning"]["enabled"] is True
        assert config["prompt_injection"]["enabled"] is True
        assert config["permissions"]["enabled"] is True
        assert len(config["permissions"]["rules"]) == 4
        assert config["permissions"]["rules"][0]["matcher"] == "*"
        assert config["permissions"]["rules"][0]["mode"] == "allow"
        assert config["permissions"]["rules"][1]["matcher"] == "mcp__*"
        assert config["permissions"]["rules"][1]["mode"] == "deny"
        assert config["permissions"]["rules"][2]["matcher"] == "mcp__ai-guardian__*"
        assert config["permissions"]["rules"][2]["mode"] == "allow"
        assert config["permissions"]["rules"][3]["matcher"] == "Skill"
        assert config["permissions"]["rules"][3]["mode"] == "deny"

    def test_get_default_config_template_permissive(self):
        """Test _get_default_config_template returns permissive config."""
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template(permissive=True)

        assert config["secret_scanning"]["enabled"] is True
        assert config["prompt_injection"]["enabled"] is True
        assert config["permissions"]["enabled"] is False
        assert len(config["permissions"]["rules"]) == 1
        assert config["permissions"]["rules"][0]["matcher"] == "*"
        assert config["permissions"]["rules"][0]["mode"] == "allow"

    def test_default_config_omits_absolute_cache_path(self, tmp_path):
        """Test that generated config does not contain absolute cache paths (issue #492)."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=False, dry_run=False)

            assert success is True

            with open(config_file) as f:
                config = json.load(f)

            engines = config["secret_scanning"]["engines"]
            gitleaks = next(
                e
                for e in engines
                if isinstance(e, dict) and e.get("type") == "gitleaks"
            )
            cache = gitleaks["pattern_server"]["cache"]
            assert "path" not in cache, (
                "cache.path should not be in default config; "
                "let get_cache_dir() resolve it at runtime"
            )
            assert (
                "pattern_server" not in config["secret_scanning"]
            ), "Top-level pattern_server is deprecated; must use per-engine format"

    def test_default_config_template_no_absolute_paths(self):
        """Test that _get_default_config_template has no absolute paths in cache."""
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template(permissive=False)
        engines = config["secret_scanning"]["engines"]
        gitleaks = next(
            e for e in engines if isinstance(e, dict) and e.get("type") == "gitleaks"
        )
        cache = gitleaks["pattern_server"]["cache"]
        assert "path" not in cache

    def test_default_config_uses_per_engine_pattern_server(self):
        """Test that default config uses per-engine pattern_server, not legacy format (issue #558)."""
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template(permissive=False)
        ss = config["secret_scanning"]

        assert "pattern_server" not in ss, (
            "Top-level secret_scanning.pattern_server is deprecated; "
            "use per-engine format instead"
        )

        engines = ss["engines"]
        assert len(engines) == 2
        assert engines[0]["type"] == "toml-patterns"
        engine = engines[1]
        assert isinstance(engine, dict)
        assert engine["type"] == "gitleaks"
        assert "pattern_server" in engine
        ps = engine["pattern_server"]
        assert (
            ps["url"] == "https://raw.githubusercontent.com/leaktk/patterns/main/target"
        )
        assert ps["patterns_endpoint"] == "/patterns/gitleaks/8.27.0"
        assert ps["warn_on_failure"] is True
        assert ps["cache"]["refresh_interval_hours"] == 12
        assert ps["cache"]["expire_after_hours"] == 168

    def test_existing_config_with_absolute_cache_path_still_works(self, tmp_path):
        """Test backward compat: existing configs with absolute cache.path still load."""
        from ai_guardian.config.utils import get_cache_dir

        abs_path = str(get_cache_dir() / "patterns.toml")
        cache_config = {"path": abs_path, "refresh_interval_hours": 12}
        from pathlib import Path

        resolved = Path(
            cache_config.get("path", str(get_cache_dir() / "patterns.toml"))
        ).expanduser()
        assert resolved == Path(abs_path).expanduser()

    def test_create_default_config_with_schema(self, tmp_path):
        """Test that default config includes schema reference."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=False, dry_run=False)

            assert success is True

            # Verify schema is included
            with open(config_file) as f:
                config = json.load(f)

            assert "$schema" in config
            assert "ai-guardian-config.schema.json" in config["$schema"]

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows file:// URI format differs"
    )
    def test_schema_uses_bundled_file_uri(self):
        """Test that $schema uses a file:// URI pointing to the bundled schema."""
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template(permissive=False)

        assert config["$schema"].startswith("file://")
        assert config["$schema"].endswith("ai-guardian-config.schema.json")
        # Verify the file actually exists at the resolved path
        from urllib.parse import urlparse, unquote

        parsed = urlparse(config["$schema"])
        schema_file = Path(unquote(parsed.path))
        assert schema_file.is_file(), f"Schema file does not exist: {schema_file}"

    def test_json_output_returns_valid_json(self, tmp_path):
        """Test that --json flag outputs only valid JSON."""
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(
                permissive=False, dry_run=False, json_output=True
            )

            assert success is True
            # Message should be parseable as valid JSON
            config = json.loads(message)
            assert "$schema" in config
            assert "secret_scanning" in config
            # Should not contain non-JSON text
            assert "[DRY RUN]" not in message
            assert "✓" not in message

    def test_json_output_with_permissive(self):
        """Test that --json with --permissive outputs permissive config."""
        from ai_guardian.setup import create_default_config

        success, message = create_default_config(
            permissive=True, dry_run=False, json_output=True
        )

        assert success is True
        config = json.loads(message)
        assert config["permissions"]["enabled"] is False

    def test_json_output_skips_exists_check(self, tmp_path):
        """Test that --json doesn't fail when config already exists."""
        from ai_guardian.setup import create_default_config

        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text("{}")

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(
                permissive=False, dry_run=False, json_output=True
            )

            assert success is True
            config = json.loads(message)


class TestCreateConfigWithProfile:
    """Test create_default_config() with profile parameter."""

    def test_create_config_with_profile_minimal(self, tmp_path):
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(profile="@minimal")
            assert success is True
            assert "profile" in message.lower()

            config_file = tmp_path / "ai-guardian.json"
            with open(config_file) as f:
                config = json.load(f)
            assert config["permissions"]["enabled"] is False
            assert config["prompt_injection"]["sensitivity"] == "low"

    def test_create_config_with_profile_standard(self, tmp_path):
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(profile="@standard")
            assert success is True

            config_file = tmp_path / "ai-guardian.json"
            with open(config_file) as f:
                config = json.load(f)
            assert config["permissions"]["enabled"] is True
            assert config["prompt_injection"]["sensitivity"] == "medium"

    def test_create_config_with_profile_strict(self, tmp_path):
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(profile="@strict")
            assert success is True

            config_file = tmp_path / "ai-guardian.json"
            with open(config_file) as f:
                config = json.load(f)
            assert config["on_scan_error"] == "block"
            assert config["prompt_injection"]["sensitivity"] == "high"
            assert config["annotations"]["enabled"] is False

    def test_create_config_profile_not_found(self, tmp_path):
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(profile="@nonexistent")
            assert success is False
            assert "Unknown built-in profile" in message

    def test_create_config_profile_dry_run(self, tmp_path):
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(profile="@strict", dry_run=True)
            assert success is True
            assert "[DRY RUN]" in message
            assert not (tmp_path / "ai-guardian.json").exists()

    def test_create_config_profile_json_output(self, tmp_path):
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(
                profile="@minimal", json_output=True
            )
            assert success is True
            config = json.loads(message)
            assert config["permissions"]["enabled"] is False

    def test_profile_does_not_break_permissive(self, tmp_path):
        from ai_guardian.setup import create_default_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
            success, message = create_default_config(permissive=True)
            assert success is True
            config_file = tmp_path / "ai-guardian.json"
            with open(config_file) as f:
                config = json.load(f)
            assert config["permissions"]["enabled"] is False


class TestSetupHooksProfiles:
    """Test setup_hooks() with profile-related parameters."""

    def test_list_profiles(self, capsys):
        from ai_guardian.setup import setup_hooks

        success = setup_hooks(list_profiles=True)
        assert success is True
        captured = capsys.readouterr()
        assert "@minimal" in captured.out
        assert "@standard" in captured.out
        assert "@strict" in captured.out

    def test_save_profile(self, tmp_path):
        from ai_guardian.setup import setup_hooks

        config_file = tmp_path / "auto_config" / "ai-guardian.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"test": True}))

        success = setup_hooks(save_profile="my-team")
        assert success is True

        profiles_dir = tmp_path / "auto_config" / "profiles"
        saved = json.loads((profiles_dir / "my-team.json").read_text())
        assert saved["test"] is True

    def test_save_profile_no_config(self, tmp_path, capsys):
        from ai_guardian.setup import setup_hooks

        success = setup_hooks(save_profile="my-team")
        assert success is False

    def test_profile_without_create_config(self, capsys):
        from ai_guardian.setup import setup_hooks

        success = setup_hooks(profile="@strict")
        assert success is False
        captured = capsys.readouterr()
        assert "--profile requires --create-config" in captured.err


class TestSetupJsonOutput:
    """Test that setup --json outputs clean JSON with no log text (Issue #518)."""

    def test_json_output_ide_explicit(self, tmp_path, capsys):
        """setup --ide claude --json outputs parseable JSON only."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.get_config_path.return_value = str(ide_config_file)
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance._last_merged_config = {"hooks": {"PreToolUse": []}}

            success = setup_hooks(
                ide_type="claude",
                json_output=True,
                interactive=False,
            )

        assert success is True
        captured = capsys.readouterr()
        # stdout must be valid JSON
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["ide"] == "claude"
        assert "hooks" in result
        # No log text on stderr
        assert "AI Guardian" not in captured.err
        assert "initialized" not in captured.err

    def test_json_output_ide_dry_run(self, tmp_path, capsys):
        """setup --ide claude --json --dry-run outputs clean JSON."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.get_config_path.return_value = str(ide_config_file)
            mock_instance.setup_ide_hooks.return_value = (
                True,
                "[DRY RUN] Would configure...",
            )
            mock_instance._last_merged_config = {
                "hooks": {"PreToolUse": [{"type": "command", "command": "ai-guardian"}]}
            }

            success = setup_hooks(
                ide_type="claude",
                json_output=True,
                dry_run=True,
            )

        assert success is True
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert "hooks" in result
        # No human-readable messages mixed in
        assert "[DRY RUN]" not in captured.out.split("{", 1)[0]

    def test_json_output_no_log_text(self, tmp_path, capsys):
        """stdout contains only JSON — no version banner, no progress messages."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.get_config_path.return_value = str(ide_config_file)
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance._last_merged_config = {"hooks": {}}

            setup_hooks(
                ide_type="claude",
                json_output=True,
                interactive=False,
            )

        captured = capsys.readouterr()
        # First non-whitespace char must be '{'
        stripped = captured.out.strip()
        assert stripped.startswith("{"), f"Output starts with non-JSON: {stripped[:80]}"
        assert stripped.endswith("}")
        # Must be valid JSON
        json.loads(stripped)

    def test_json_output_includes_mcp(self, tmp_path, capsys):
        """setup --ide claude --json always includes MCP server config."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.get_config_path.return_value = str(ide_config_file)
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance._last_merged_config = {"hooks": {}}

            setup_hooks(
                ide_type="claude",
                json_output=True,
                interactive=False,
            )

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "mcp_servers" in result
        assert "ai-guardian" in result["mcp_servers"]
        assert _is_ai_guardian_command(result["mcp_servers"]["ai-guardian"]["command"])
        assert result["mcp_servers"]["ai-guardian"]["args"] == ["mcp-server"]

    def test_json_output_no_mcp_excludes_mcp(self, tmp_path, capsys):
        """setup --ide claude --no-mcp --json excludes MCP server config."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.get_config_path.return_value = str(ide_config_file)
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance._last_merged_config = {"hooks": {}}

            with mock.patch("ai_guardian.setup._handle_mcp_setup"):
                setup_hooks(
                    ide_type="claude",
                    json_output=True,
                    interactive=False,
                    no_mcp=True,
                )

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "mcp_servers" not in result

    def test_json_output_with_create_config(self, tmp_path, capsys):
        """setup --ide claude --create-config --json includes ai_guardian_config."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.get_config_path.return_value = str(ide_config_file)
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance._last_merged_config = {"hooks": {}}

            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
                setup_hooks(
                    ide_type="claude",
                    json_output=True,
                    interactive=False,
                    create_config=True,
                )

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert "ai_guardian_config" in result
        assert "hooks" in result

    def test_json_output_error_invalid_ide(self, capsys):
        """setup --ide invalid --json outputs JSON error."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.IDE_CONFIGS = {"claude": {"name": "Claude Code"}}

            success = setup_hooks(
                ide_type="invalid",
                json_output=True,
                interactive=False,
            )

        assert success is False
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert "error" in result

    def test_json_output_error_no_ide_detected(self, capsys):
        """setup --json with no IDE detected outputs JSON error."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = []

            success = setup_hooks(json_output=True, interactive=False)

        assert success is False
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert "No IDE detected" in result["error"]

    def test_json_output_create_config_only(self, tmp_path, capsys):
        """--json --create-config (without --ide) uses consistent JSON format."""
        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = []

            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}):
                success = setup_hooks(
                    create_config=True,
                    json_output=True,
                    interactive=False,
                )

        assert success is True
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert "ai_guardian_config" in result
        assert "$schema" in result["ai_guardian_config"]


class TestSetupDaemonReload:
    """Test daemon reload notification after setup operations (Issue #680)."""

    def test_create_config_calls_daemon_reload(self, tmp_path, capsys):
        with (
            mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}),
            mock.patch(
                "ai_guardian.daemon.client.send_reload_config", return_value=True
            ) as mock_reload,
        ):
            success = setup_hooks(create_config=True, interactive=False)

        assert success is True
        mock_reload.assert_called_once()
        assert "Daemon reloaded" in capsys.readouterr().out

    def test_create_config_no_reload_when_daemon_not_running(self, tmp_path, capsys):
        with (
            mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}),
            mock.patch(
                "ai_guardian.daemon.client.send_reload_config", return_value=False
            ) as mock_reload,
        ):
            success = setup_hooks(create_config=True, interactive=False)

        assert success is True
        mock_reload.assert_called_once()
        assert "Daemon reloaded" not in capsys.readouterr().out

    def test_reload_silences_exceptions(self, tmp_path, capsys):
        with (
            mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(tmp_path)}),
            mock.patch(
                "ai_guardian.daemon.client.send_reload_config",
                side_effect=Exception("fail"),
            ),
        ):
            success = setup_hooks(create_config=True, interactive=False)

        assert success is True


class TestKiroSetup:
    """Test cases for Kiro (AWS) setup."""

    def test_kiro_hooks_are_script_based(self):
        """Verify Kiro uses script-based hooks with correct event names."""
        kiro_cfg = IDESetup.IDE_CONFIGS["kiro"]
        assert kiro_cfg["script_based"] is True
        scripts = kiro_cfg["hook_scripts"]
        assert "PreToolUse" in scripts
        assert "PostToolUse" in scripts
        assert "PromptSubmit" in scripts

    def test_kiro_script_content(self):
        """Verify script content calls ai-guardian."""
        kiro_cfg = IDESetup.IDE_CONFIGS["kiro"]
        content = kiro_cfg["script_content"]
        assert content.startswith("#!/bin/sh")
        assert "ai-guardian" in content

    def test_kiro_in_mcp_ide_configs(self):
        """Verify Kiro MCP config entry."""
        from ai_guardian.setup import _MCP_IDE_CONFIGS

        assert "kiro" in _MCP_IDE_CONFIGS
        kiro_mcp = _MCP_IDE_CONFIGS["kiro"]
        assert kiro_mcp["config_file"] == "~/.kiro/settings.json"
        assert kiro_mcp["config_key"] == "mcpServers"
        assert kiro_mcp["skill_dir"] == ".kiro/skills"


class TestMcpMigrationWarning:
    """Tests for MCP migration warning when MCP entry found in settings.json (#756)."""

    def test_warn_when_mcp_in_settings_json(self, tmp_path, capsys):
        """Warns when ai-guardian MCP entry found in ~/.claude/settings.json."""
        from ai_guardian.setup import _install_mcp_config, _MCP_IDE_CONFIGS, IDESetup

        claude_json = tmp_path / ".claude.json"
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_json = settings_dir / "settings.json"
        settings_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ai-guardian": {
                            "command": "ai-guardian",
                            "args": ["mcp-server"],
                        }
                    }
                }
            )
        )

        with mock.patch.dict(
            _MCP_IDE_CONFIGS,
            {"claude": {**_MCP_IDE_CONFIGS["claude"], "config_file": str(claude_json)}},
        ):
            with mock.patch(
                "ai_guardian.setup.mcp.Path",
                side_effect=lambda p: Path(
                    str(p).replace("~/.claude/settings.json", str(settings_json))
                ),
            ):
                setup = IDESetup()
                _install_mcp_config(setup, "claude", dry_run=False)

        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "settings.json" in captured.out

    def test_no_warn_when_mcp_only_in_claude_json(self, tmp_path, capsys):
        """No warning when MCP only in ~/.claude.json (correct location)."""
        from ai_guardian.setup import _install_mcp_config, _MCP_IDE_CONFIGS, IDESetup

        claude_json = tmp_path / ".claude.json"
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_json = settings_dir / "settings.json"
        settings_json.write_text(json.dumps({"hooks": {}}))

        with mock.patch.dict(
            _MCP_IDE_CONFIGS,
            {"claude": {**_MCP_IDE_CONFIGS["claude"], "config_file": str(claude_json)}},
        ):
            with mock.patch(
                "ai_guardian.setup.mcp.Path",
                side_effect=lambda p: Path(
                    str(p).replace("~/.claude/settings.json", str(settings_json))
                ),
            ):
                setup = IDESetup()
                _install_mcp_config(setup, "claude", dry_run=False)

        captured = capsys.readouterr()
        assert "Warning" not in captured.out

    def test_no_warn_for_non_claude_ide(self, tmp_path, capsys):
        """No migration check runs for non-claude IDEs."""
        from ai_guardian.setup import _install_mcp_config, _MCP_IDE_CONFIGS, IDESetup

        cursor_json = tmp_path / "mcp.json"

        with mock.patch.dict(
            _MCP_IDE_CONFIGS,
            {"cursor": {**_MCP_IDE_CONFIGS["cursor"], "config_file": str(cursor_json)}},
        ):
            setup = IDESetup()
            _install_mcp_config(setup, "cursor", dry_run=False)

        captured = capsys.readouterr()
        assert "Warning" not in captured.out


class TestMcpDefaultOn:
    """Tests for MCP server always installed by default (Issue #808, #1377)."""

    def test_mcp_installed_by_default(self, tmp_path):
        """MCP server is always installed by default."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance.get_config_path.return_value = str(ide_config_file)

            with mock.patch("ai_guardian.setup._handle_mcp_setup") as mock_mcp:
                success = setup_hooks(
                    ide_type="claude",
                    interactive=False,
                )

                assert success is True
                mock_mcp.assert_called_once_with(
                    mock_instance,
                    "claude",
                    dry_run=False,
                )

    def test_no_mcp_skips_installation(self, tmp_path):
        """--no-mcp removes MCP server instead of installing it."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance.get_config_path.return_value = str(ide_config_file)

            with mock.patch("ai_guardian.setup._handle_mcp_setup") as mock_mcp:
                success = setup_hooks(
                    ide_type="claude",
                    interactive=False,
                    no_mcp=True,
                )

                assert success is True
                mock_mcp.assert_called_once_with(
                    mock_instance,
                    "claude",
                    no_mcp=True,
                    dry_run=False,
                )

    @pytest.mark.parametrize("ide_type", ["claude", "cursor", "windsurf", "gemini"])
    def test_mcp_default_for_multiple_ides(self, tmp_path, ide_type):
        """MCP is installed by default for all supported IDEs."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = [ide_type]
            mock_instance.IDE_CONFIGS = {
                ide_type: {
                    "name": ide_type.title(),
                    "config_path": str(ide_config_file),
                }
            }
            mock_instance.setup_ide_hooks.return_value = (True, "Success")
            mock_instance.get_config_path.return_value = str(ide_config_file)

            with mock.patch("ai_guardian.setup._handle_mcp_setup") as mock_mcp:
                success = setup_hooks(
                    ide_type=ide_type,
                    interactive=False,
                )

                assert success is True
                mock_mcp.assert_called_once()

    def test_mcp_not_installed_when_hooks_fail(self, tmp_path):
        """MCP setup is skipped when hook setup fails."""
        ide_config_file = tmp_path / "settings.json"

        with mock.patch("ai_guardian.setup.IDESetup") as MockSetup:
            mock_instance = MockSetup.return_value
            mock_instance.list_detected_ides.return_value = ["claude"]
            mock_instance.IDE_CONFIGS = {
                "claude": {"name": "Claude Code", "config_path": str(ide_config_file)}
            }
            mock_instance.setup_ide_hooks.return_value = (False, "Failed")
            mock_instance.get_config_path.return_value = str(ide_config_file)

            with mock.patch("ai_guardian.setup._handle_mcp_setup") as mock_mcp:
                setup_hooks(
                    ide_type="claude",
                    interactive=False,
                )

                mock_mcp.assert_not_called()


class TestOpenCodeMcpConfig:
    """Tests for OpenCode MCP config handling (#1377)."""

    def test_writes_to_existing_json_not_jsonc(self, tmp_path):
        """When opencode.json exists but .jsonc does not, write to .json."""
        from ai_guardian.setup import _install_mcp_config

        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)
        legacy = opencode_dir / "opencode.json"
        legacy.write_text('{"mcp": {}}')

        with mock.patch(
            "ai_guardian.setup.mcp._resolve_opencode_config",
            return_value=legacy,
        ):
            with mock.patch(
                "ai_guardian.setup.mcp._resolve_binary_path",
                return_value="/usr/bin/ai-guardian",
            ):
                _install_mcp_config(mock.MagicMock(), "opencode")

        assert legacy.exists()
        jsonc_path = opencode_dir / "opencode.jsonc"
        assert not jsonc_path.exists()
        config = json.loads(legacy.read_text())
        assert "ai-guardian" in config["mcp"]

    def test_prefers_json_when_both_exist(self, tmp_path):
        """When both .json and .jsonc exist, write to .json."""
        from ai_guardian.setup import _install_mcp_config

        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)
        json_file = opencode_dir / "opencode.json"
        json_file.write_text('{"mcp": {}}')
        jsonc = opencode_dir / "opencode.jsonc"
        jsonc.write_text('{"old": true}')

        with mock.patch(
            "ai_guardian.setup.mcp._resolve_opencode_config",
            return_value=json_file,
        ):
            with mock.patch(
                "ai_guardian.setup.mcp._resolve_binary_path",
                return_value="/usr/bin/ai-guardian",
            ):
                _install_mcp_config(mock.MagicMock(), "opencode")

        config = json.loads(json_file.read_text())
        assert "ai-guardian" in config["mcp"]
        # jsonc untouched
        assert json.loads(jsonc.read_text()) == {"old": True}

    def test_creates_jsonc_when_neither_exists(self, tmp_path):
        """When no config exists, create opencode.jsonc."""
        from ai_guardian.setup import _install_mcp_config

        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)
        jsonc_path = opencode_dir / "opencode.jsonc"

        with mock.patch(
            "ai_guardian.setup.mcp._resolve_opencode_config",
            return_value=jsonc_path,
        ):
            with mock.patch(
                "ai_guardian.setup.mcp._resolve_binary_path",
                return_value="/usr/bin/ai-guardian",
            ):
                _install_mcp_config(mock.MagicMock(), "opencode")

        assert jsonc_path.exists()
        config = json.loads(jsonc_path.read_text())
        assert "ai-guardian" in config["mcp"]

    def test_skip_silently_when_no_config_path(self):
        """IDEs without MCP config path skip silently (no output)."""
        from ai_guardian.setup import _install_mcp_config

        with mock.patch(
            "ai_guardian.setup.mcp._MCP_IDE_CONFIGS",
            {
                "copilot": {"config_key": "mcpServers"},
            },
        ):
            _install_mcp_config(mock.MagicMock(), "copilot")

    def test_skip_silently_when_unknown_ide(self):
        """Unknown IDE types skip silently."""
        from ai_guardian.setup import _install_mcp_config

        _install_mcp_config(mock.MagicMock(), "unknown_ide")


class TestResolveBinaryPath:
    """Tests for _resolve_binary_path helper."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows prefers pythonw path")
    def test_returns_shutil_which_result(self):
        with mock.patch(
            "ai_guardian.setup.utils.shutil.which",
            return_value="/usr/local/bin/ai-guardian",
        ):
            assert _resolve_binary_path() == "/usr/local/bin/ai-guardian"

    def test_falls_back_to_bare_ai_guardian(self, tmp_path):
        with mock.patch("ai_guardian.setup.utils.shutil.which", return_value=None):
            assert _resolve_binary_path() == "ai-guardian"

    def test_falls_back_to_bare_command(self):
        with mock.patch("ai_guardian.setup.utils.shutil.which", return_value=None):
            assert _resolve_binary_path() == "ai-guardian"


class TestIsAiGuardianCommand:
    """Tests for _is_ai_guardian_command helper."""

    def test_bare_command(self):
        assert _is_ai_guardian_command("ai-guardian") is True

    def test_absolute_path(self):
        assert _is_ai_guardian_command("/usr/local/bin/ai-guardian") is True

    def test_venv_path(self):
        assert _is_ai_guardian_command("/home/user/.venv/bin/ai-guardian") is True

    def test_other_command(self):
        assert _is_ai_guardian_command("other-tool") is False

    def test_empty_string(self):
        assert _is_ai_guardian_command("") is False

    def test_none_like(self):
        assert _is_ai_guardian_command(None) is False

    def test_bare_command_with_ide_flag(self):
        assert _is_ai_guardian_command("ai-guardian --ide cursor") is True

    def test_absolute_path_with_ide_flag(self):
        assert (
            _is_ai_guardian_command("/usr/local/bin/ai-guardian --ide claude") is True
        )

    def test_venv_path_with_ide_flag(self):
        assert (
            _is_ai_guardian_command("/home/user/.venv/bin/ai-guardian --ide gemini")
            is True
        )


class TestWalkCommands:
    """Tests for _walk_commands generalized tree walker."""

    def test_copy_preserves_original(self):
        original = {"command": "ai-guardian"}
        result = _walk_commands(
            original, lambda v: v == "ai-guardian", lambda _: "/new", copy=True
        )
        assert result == {"command": "/new"}
        assert original == {"command": "ai-guardian"}

    def test_mutate_changes_in_place(self):
        obj = {"command": "ai-guardian"}
        _walk_commands(obj, lambda v: v == "ai-guardian", lambda _: "/new", copy=False)
        assert obj == {"command": "/new"}

    def test_predicate_filters(self):
        obj = {"command": "other-tool"}
        result = _walk_commands(
            obj, lambda v: v == "ai-guardian", lambda _: "/new", copy=True
        )
        assert result == {"command": "other-tool"}

    def test_nested_dict_and_list(self):
        obj = {"hooks": [{"command": "ai-guardian"}, {"command": "other"}]}
        result = _walk_commands(
            obj, lambda v: v == "ai-guardian", lambda _: "/new", copy=True
        )
        assert result == {"hooks": [{"command": "/new"}, {"command": "other"}]}

    def test_scalar_passthrough(self):
        assert _walk_commands(42, lambda v: True, lambda _: 0, copy=True) == 42
        assert _walk_commands("text", lambda v: True, lambda _: "", copy=True) == "text"

    def test_mutate_nested(self):
        obj = {"hooks": {"pre": [{"command": "ai-guardian"}]}}
        _walk_commands(
            obj, lambda v: v == "ai-guardian", lambda v: f"{v} --ide test", copy=False
        )
        assert obj["hooks"]["pre"][0]["command"] == "ai-guardian --ide test"


class TestSubstituteCommand:
    """Tests for _substitute_command helper."""

    def test_replaces_command_in_dict(self):
        result = _substitute_command({"command": "ai-guardian"}, "/abs/ai-guardian")
        assert result == {"command": "/abs/ai-guardian"}

    def test_leaves_other_keys(self):
        result = _substitute_command(
            {"command": "ai-guardian", "timeout": 30},
            "/abs/ai-guardian",
        )
        assert result == {"command": "/abs/ai-guardian", "timeout": 30}

    def test_nested_dict(self):
        result = _substitute_command(
            {"hooks": [{"command": "ai-guardian"}]},
            "/abs/ai-guardian",
        )
        assert result == {"hooks": [{"command": "/abs/ai-guardian"}]}

    def test_does_not_replace_non_ai_guardian(self):
        result = _substitute_command({"command": "other-tool"}, "/abs/ai-guardian")
        assert result == {"command": "other-tool"}

    def test_does_not_mutate_original(self):
        original = {"command": "ai-guardian"}
        _substitute_command(original, "/abs/ai-guardian")
        assert original["command"] == "ai-guardian"

    def test_ide_type_appended(self):
        result = _substitute_command(
            {"command": "ai-guardian"}, "/abs/ai-guardian", ide_type="cursor"
        )
        assert result == {"command": "/abs/ai-guardian --ide cursor"}

    def test_ide_type_nested(self):
        result = _substitute_command(
            {"hooks": [{"command": "ai-guardian"}]},
            "/abs/ai-guardian",
            ide_type="gemini",
        )
        assert result == {"hooks": [{"command": "/abs/ai-guardian --ide gemini"}]}

    def test_ide_type_none_omitted(self):
        result = _substitute_command(
            {"command": "ai-guardian"}, "/abs/ai-guardian", ide_type=None
        )
        assert result == {"command": "/abs/ai-guardian"}


class TestUpgradeIdeFlag:
    """Tests for _upgrade_ide_flag helper."""

    def test_adds_ide_flag_to_bare_command(self):
        config = {"command": "ai-guardian"}
        _upgrade_ide_flag(config, "cursor")
        assert config["command"] == "ai-guardian --ide cursor"

    def test_adds_ide_flag_to_absolute_path(self):
        config = {"command": "/usr/bin/ai-guardian"}
        _upgrade_ide_flag(config, "claude")
        assert config["command"] == "/usr/bin/ai-guardian --ide claude"

    def test_skips_command_already_having_ide(self):
        config = {"command": "/usr/bin/ai-guardian --ide cursor"}
        _upgrade_ide_flag(config, "cursor")
        assert config["command"] == "/usr/bin/ai-guardian --ide cursor"

    def test_nested_in_hooks(self):
        config = {"hooks": {"preToolUse": [{"command": "/usr/bin/ai-guardian"}]}}
        _upgrade_ide_flag(config, "cursor")
        assert (
            config["hooks"]["preToolUse"][0]["command"]
            == "/usr/bin/ai-guardian --ide cursor"
        )

    def test_leaves_non_ai_guardian_command(self):
        config = {"command": "other-tool"}
        _upgrade_ide_flag(config, "cursor")
        assert config["command"] == "other-tool"


class TestAbsolutePathWritten:
    """Tests that setup writes absolute paths to hook configs."""

    def test_claude_hooks_use_absolute_path(self, tmp_path):
        setup = IDESetup()
        config_file = tmp_path / "settings.json"

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {
                    **IDESetup.IDE_CONFIGS["claude"],
                    "config_path": str(config_file),
                }
            },
        ):
            with mock.patch(
                "ai_guardian.setup.hooks._resolve_binary_path",
                return_value="/mock/bin/ai-guardian",
            ):
                success, _ = setup.setup_ide_hooks("claude", dry_run=False, force=False)

        assert success
        config = json.loads(config_file.read_text())
        cmd = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert cmd == "/mock/bin/ai-guardian --ide claude"

    def test_cursor_hooks_use_absolute_path(self, tmp_path):
        """Cursor hooks installed in ~/.cursor/hooks.json with --ide cursor."""
        setup = IDESetup()
        config_file = tmp_path / "hooks.json"

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "cursor": {
                    **IDESetup.IDE_CONFIGS["cursor"],
                    "config_path": str(config_file),
                }
            },
        ):
            with mock.patch(
                "ai_guardian.setup.hooks._resolve_binary_path",
                return_value="/mock/bin/ai-guardian",
            ):
                success, _ = setup.setup_ide_hooks("cursor", dry_run=False, force=False)

        assert success
        config = json.loads(config_file.read_text())
        hooks = config["hooks"]["beforeSubmitPrompt"]
        assert hooks[0]["command"] == "/mock/bin/ai-guardian --ide cursor"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix shebang test")
    def test_script_based_hooks_use_absolute_path(self, tmp_path):
        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {"cline": {**IDESetup.IDE_CONFIGS["cline"], "config_path": str(hooks_dir)}},
        ):
            with mock.patch(
                "ai_guardian.setup.hooks._resolve_binary_path",
                return_value="/mock/bin/ai-guardian",
            ):
                success, _ = setup.setup_ide_hooks("cline", dry_run=False, force=False)

        assert success
        script = (hooks_dir / "PreToolUse").read_text()
        assert "/mock/bin/ai-guardian --ide cline" in script
        assert script.startswith("#!/bin/sh")

    def test_check_hooks_configured_recognizes_absolute_path(self, tmp_path):
        setup = IDESetup()
        config_file = tmp_path / "settings.json"
        config_file.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "*",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "/usr/bin/ai-guardian",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        )

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                "claude": {
                    **IDESetup.IDE_CONFIGS["claude"],
                    "config_path": str(config_file),
                }
            },
        ):
            assert setup.check_hooks_configured(config_file, "claude") is True

    def test_mcp_config_uses_absolute_path(self, tmp_path):
        from ai_guardian.setup import _install_mcp_config, _MCP_IDE_CONFIGS

        mcp_file = tmp_path / "claude.json"
        setup = IDESetup()

        with mock.patch.dict(
            _MCP_IDE_CONFIGS,
            {"claude": {**_MCP_IDE_CONFIGS["claude"], "config_file": str(mcp_file)}},
        ):
            with mock.patch(
                "ai_guardian.setup.mcp._resolve_binary_path",
                return_value="/mock/bin/ai-guardian",
            ):
                _install_mcp_config(setup, "claude", dry_run=False)

        config = json.loads(mcp_file.read_text())
        assert config["mcpServers"]["ai-guardian"]["command"] == "/mock/bin/ai-guardian"


class TestWindowsSetup:
    """Tests for Windows-specific setup behavior (issue #902)."""

    # -- _resolve_binary_path on Windows --

    def test_resolve_binary_path_uses_pythonw_on_windows(self, tmp_path):
        """On Windows, prefer pythonw.exe -m ai_guardian over bare binary."""
        fake_pythonw = str(tmp_path / "pythonw.exe")

        def mock_which(cmd):
            if cmd == "pythonw":
                return fake_pythonw
            return None

        with mock.patch(
            "ai_guardian.setup.utils.platform.system", return_value="Windows"
        ):
            with mock.patch(
                "ai_guardian.setup.utils.shutil.which", side_effect=mock_which
            ):
                result = _resolve_binary_path()

        assert result == f"{fake_pythonw} -m ai_guardian"

    def test_resolve_binary_path_fallback_when_no_pythonw(self, tmp_path):
        """On Windows without pythonw.exe, fall back to standard resolution."""

        def mock_which(cmd):
            if cmd == "pythonw":
                return None
            if cmd == "ai-guardian":
                return "C:\\bin\\ai-guardian.exe"
            return None

        with mock.patch(
            "ai_guardian.setup.utils.platform.system", return_value="Windows"
        ):
            with mock.patch(
                "ai_guardian.setup.utils.shutil.which", side_effect=mock_which
            ):
                result = _resolve_binary_path()

        assert result == "C:\\bin\\ai-guardian.exe"

    def test_resolve_binary_path_unchanged_on_macos(self):
        """macOS behavior is unchanged."""
        with mock.patch(
            "ai_guardian.setup.utils.platform.system", return_value="Darwin"
        ):
            with mock.patch(
                "ai_guardian.setup.utils.shutil.which",
                return_value="/usr/local/bin/ai-guardian",
            ):
                assert _resolve_binary_path() == "/usr/local/bin/ai-guardian"

    def test_resolve_binary_path_unchanged_on_linux(self):
        """Linux behavior is unchanged."""
        with mock.patch(
            "ai_guardian.setup.utils.platform.system", return_value="Linux"
        ):
            with mock.patch(
                "ai_guardian.setup.utils.shutil.which",
                return_value="/usr/bin/ai-guardian",
            ):
                assert _resolve_binary_path() == "/usr/bin/ai-guardian"

    # -- _is_ai_guardian_command with Windows paths --

    def test_windows_backslash_path(self):
        assert _is_ai_guardian_command("C:\\Python312\\Scripts\\ai-guardian") is True

    def test_windows_exe_suffix(self):
        assert (
            _is_ai_guardian_command("C:\\Python312\\Scripts\\ai-guardian.exe") is True
        )

    def test_windows_backslash_with_ide_flag(self):
        assert (
            _is_ai_guardian_command("C:\\Python312\\Scripts\\ai-guardian --ide claude")
            is True
        )

    def test_pythonw_module_invocation(self):
        assert (
            _is_ai_guardian_command(
                "C:\\Python312\\pythonw.exe -m ai_guardian --ide claude"
            )
            is True
        )

    def test_pythonw_module_bare(self):
        assert _is_ai_guardian_command("pythonw.exe -m ai_guardian") is True

    # -- _substitute_command with Windows values --

    def test_substitute_replaces_exe_variant(self):
        result = _substitute_command(
            {"command": "ai-guardian.exe"}, "C:\\Python312\\pythonw.exe -m ai_guardian"
        )
        assert result == {"command": "C:\\Python312\\pythonw.exe -m ai_guardian"}

    def test_substitute_exe_with_ide_type(self):
        result = _substitute_command(
            {"command": "ai-guardian.exe"},
            "C:\\Python312\\pythonw.exe -m ai_guardian",
            ide_type="cursor",
        )
        assert result == {
            "command": "C:\\Python312\\pythonw.exe -m ai_guardian --ide cursor"
        }

    # -- VBS wrapper --

    def test_vbs_wrapper_created_on_windows(self, tmp_path):
        with mock.patch(
            "ai_guardian.setup.hooks.platform.system", return_value="Windows"
        ):
            vbs_path = _create_vbs_wrapper(
                "C:\\Python312\\pythonw.exe -m ai_guardian --ide claude", tmp_path
            )

        assert vbs_path is not None
        assert vbs_path.exists()
        content = vbs_path.read_text()
        assert "WScript.Shell" in content
        assert "pythonw.exe -m ai_guardian --ide claude" in content
        assert ", 0, True" in content

    def test_vbs_wrapper_not_created_on_macos(self, tmp_path):
        with mock.patch(
            "ai_guardian.setup.hooks.platform.system", return_value="Darwin"
        ):
            result = _create_vbs_wrapper("ai-guardian", tmp_path)

        assert result is None

    def test_vbs_wrapper_not_created_on_linux(self, tmp_path):
        with mock.patch(
            "ai_guardian.setup.hooks.platform.system", return_value="Linux"
        ):
            result = _create_vbs_wrapper("ai-guardian", tmp_path)

        assert result is None

    # -- _upgrade_ide_flag with Windows paths --

    def test_upgrade_ide_flag_windows_exe_path(self):
        config = {"command": "C:\\Python312\\Scripts\\ai-guardian.exe"}
        _upgrade_ide_flag(config, "claude")
        assert (
            config["command"] == "C:\\Python312\\Scripts\\ai-guardian.exe --ide claude"
        )

    def test_upgrade_ide_flag_pythonw_command(self):
        config = {"command": "C:\\Python312\\pythonw.exe -m ai_guardian"}
        _upgrade_ide_flag(config, "cursor")
        assert (
            config["command"]
            == "C:\\Python312\\pythonw.exe -m ai_guardian --ide cursor"
        )

    # -- End-to-end: setup_ide_hooks uses pythonw on Windows --

    @pytest.mark.parametrize(
        "ide_type",
        ["claude", "cursor", "copilot", "codex", "windsurf", "gemini", "augment"],
    )
    def test_hooks_use_pythonw_on_windows(self, tmp_path, ide_type):
        """All agent adapters use pythonw.exe on Windows."""
        setup = IDESetup()
        config_file = tmp_path / "settings.json"

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                ide_type: {
                    **IDESetup.IDE_CONFIGS[ide_type],
                    "config_path": str(config_file),
                }
            },
        ):
            with mock.patch(
                "ai_guardian.setup.hooks._resolve_binary_path",
                return_value="C:\\Python312\\pythonw.exe -m ai_guardian",
            ):
                with mock.patch(
                    "ai_guardian.setup.hooks.platform.system", return_value="Windows"
                ):
                    with mock.patch.object(
                        setup, "verify_gitleaks_installed", return_value=(True, "ok")
                    ):
                        success, msg = setup.setup_ide_hooks(ide_type)

        assert success, msg
        config = json.loads(config_file.read_text())
        config_str = json.dumps(config)
        assert "pythonw.exe -m ai_guardian" in config_str

    # -- Script-based hooks generate .bat on Windows --

    @pytest.mark.parametrize("ide_type", ["cline", "zoocode", "kiro"])
    def test_script_hooks_create_bat_on_windows(self, tmp_path, ide_type):
        """Script-based IDEs create .bat files on Windows."""
        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {
                ide_type: {
                    **IDESetup.IDE_CONFIGS[ide_type],
                    "config_path": str(hooks_dir),
                }
            },
        ):
            with mock.patch(
                "ai_guardian.setup.hooks._resolve_binary_path",
                return_value=r"C:\Python312\pythonw.exe -m ai_guardian",
            ):
                with mock.patch(
                    "ai_guardian.setup.hooks.platform.system", return_value="Windows"
                ):
                    with mock.patch.object(
                        setup, "verify_gitleaks_installed", return_value=(True, "ok")
                    ):
                        success, msg = setup.setup_ide_hooks(
                            ide_type, dry_run=False, force=False
                        )

        assert success, msg
        for script_name in IDESetup.IDE_CONFIGS[ide_type]["hook_scripts"]:
            bat_path = hooks_dir / f"{script_name}.bat"
            assert bat_path.exists(), f"{bat_path} not created"
            content = bat_path.read_text()
            assert content.startswith("@echo off")
            assert "ai_guardian" in content

    def test_script_hooks_no_bat_on_unix(self, tmp_path):
        """Script-based IDEs create shebang scripts on Unix."""
        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {"cline": {**IDESetup.IDE_CONFIGS["cline"], "config_path": str(hooks_dir)}},
        ):
            with mock.patch(
                "ai_guardian.setup.hooks._resolve_binary_path",
                return_value="/mock/bin/ai-guardian",
            ):
                with mock.patch(
                    "ai_guardian.setup.hooks.platform.system", return_value="Linux"
                ):
                    with mock.patch.object(
                        setup, "verify_gitleaks_installed", return_value=(True, "ok")
                    ):
                        success, _ = setup.setup_ide_hooks(
                            "cline", dry_run=False, force=False
                        )

        assert success
        script = (hooks_dir / "PreToolUse").read_text()
        assert script.startswith("#!/bin/sh")

    def test_is_already_configured_detects_bat(self, tmp_path):
        """check_hooks_configured finds .bat hooks on Windows."""
        setup = IDESetup()
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "PreToolUse.bat").write_text(
            "@echo off\r\nai-guardian --ide cline\r\n"
        )

        with mock.patch.object(
            setup,
            "IDE_CONFIGS",
            {"cline": {**IDESetup.IDE_CONFIGS["cline"], "config_path": str(hooks_dir)}},
        ):
            with mock.patch(
                "ai_guardian.setup.hooks.platform.system", return_value="Windows"
            ):
                result = setup.check_hooks_configured(hooks_dir, "cline")

        assert result is True


class TestOpenCodePluginRegistration:
    """Tests for OpenCode plugin registration in opencode.json (#2139)."""

    def _mock_resolve(self, config_file):
        return mock.patch(
            "ai_guardian.setup.hooks._resolve_opencode_config",
            return_value=config_file,
        )

    def test_registers_plugin_in_existing_json(self, tmp_path):
        """Plugin path added to plugins array in existing opencode.json."""
        opencode_dir = tmp_path / ".config" / "opencode"
        plugins_dir = opencode_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        config_file = opencode_dir / "opencode.json"
        config_file.write_text('{"mcp": {}}')

        plugin_file = plugins_dir / "ai-guardian.ts"
        plugin_file.write_text("// plugin")

        setup = IDESetup()
        with self._mock_resolve(config_file):
            setup._register_opencode_plugin(plugin_file, plugins_dir)

        config = json.loads(config_file.read_text())
        assert str(plugin_file) in config["plugins"]

    def test_registers_plugin_in_jsonc(self, tmp_path):
        """When only opencode.jsonc exists, register plugin there."""
        opencode_dir = tmp_path / ".config" / "opencode"
        plugins_dir = opencode_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        config_file = opencode_dir / "opencode.jsonc"
        config_file.write_text('{"mcp": {}}')

        plugin_file = plugins_dir / "ai-guardian.ts"
        plugin_file.write_text("// plugin")

        setup = IDESetup()
        with self._mock_resolve(config_file):
            setup._register_opencode_plugin(plugin_file, plugins_dir)

        config = json.loads(config_file.read_text())
        assert str(plugin_file) in config["plugins"]

    def test_creates_jsonc_when_neither_exists(self, tmp_path):
        """When no config exists, create opencode.jsonc with plugins."""
        opencode_dir = tmp_path / ".config" / "opencode"
        plugins_dir = opencode_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        config_file = opencode_dir / "opencode.jsonc"

        plugin_file = plugins_dir / "ai-guardian.ts"
        plugin_file.write_text("// plugin")

        setup = IDESetup()
        with self._mock_resolve(config_file):
            setup._register_opencode_plugin(plugin_file, plugins_dir)

        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert str(plugin_file) in config["plugins"]

    def test_idempotent_no_duplicates(self, tmp_path):
        """Running setup twice does not duplicate plugin entry."""
        opencode_dir = tmp_path / ".config" / "opencode"
        plugins_dir = opencode_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        config_file = opencode_dir / "opencode.json"
        config_file.write_text("{}")

        plugin_file = plugins_dir / "ai-guardian.ts"
        plugin_file.write_text("// plugin")

        setup = IDESetup()
        with self._mock_resolve(config_file):
            setup._register_opencode_plugin(plugin_file, plugins_dir)
            setup._register_opencode_plugin(plugin_file, plugins_dir)

        config = json.loads(config_file.read_text())
        assert config["plugins"].count(str(plugin_file)) == 1

    def test_preserves_existing_plugins(self, tmp_path):
        """Existing plugins array entries preserved."""
        opencode_dir = tmp_path / ".config" / "opencode"
        plugins_dir = opencode_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        config_file = opencode_dir / "opencode.json"
        config_file.write_text(json.dumps({"plugins": ["/some/other-plugin.ts"]}))

        plugin_file = plugins_dir / "ai-guardian.ts"
        plugin_file.write_text("// plugin")

        setup = IDESetup()
        with self._mock_resolve(config_file):
            setup._register_opencode_plugin(plugin_file, plugins_dir)

        config = json.loads(config_file.read_text())
        assert "/some/other-plugin.ts" in config["plugins"]
        assert str(plugin_file) in config["plugins"]

    def test_dry_run_returns_message(self, tmp_path):
        """Dry run returns registration message without modifying config."""
        opencode_dir = tmp_path / ".config" / "opencode"
        plugins_dir = opencode_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        config_file = opencode_dir / "opencode.json"
        config_file.write_text("{}")

        plugin_file = plugins_dir / "ai-guardian.ts"

        setup = IDESetup()
        with self._mock_resolve(config_file):
            msg = setup._register_opencode_plugin(
                plugin_file, plugins_dir, dry_run=True
            )

        assert "Register plugin in" in msg
        assert json.loads(config_file.read_text()) == {}

    def test_preserves_existing_config_keys(self, tmp_path):
        """Existing config keys (mcp, theme, etc.) preserved."""
        opencode_dir = tmp_path / ".config" / "opencode"
        plugins_dir = opencode_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        config_file = opencode_dir / "opencode.json"
        config_file.write_text(
            json.dumps({"mcp": {"some-server": {}}, "theme": "dark"})
        )

        plugin_file = plugins_dir / "ai-guardian.ts"
        plugin_file.write_text("// plugin")

        setup = IDESetup()
        with self._mock_resolve(config_file):
            setup._register_opencode_plugin(plugin_file, plugins_dir)

        config = json.loads(config_file.read_text())
        assert config["mcp"] == {"some-server": {}}
        assert config["theme"] == "dark"
        assert str(plugin_file) in config["plugins"]


class TestResolveOpenCodeConfig:
    """Tests for _resolve_opencode_config shared helper (#2139)."""

    def _with_home(self, monkeypatch, tmp_path):
        """Set HOME/USERPROFILE to tmp_path for cross-platform expanduser."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def test_prefers_json_when_both_exist(self, tmp_path, monkeypatch):
        """When both .json and .jsonc exist, prefer .json."""
        from ai_guardian.setup.utils import _resolve_opencode_config

        self._with_home(monkeypatch, tmp_path)
        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)
        json_file = opencode_dir / "opencode.json"
        json_file.write_text("{}")
        (opencode_dir / "opencode.jsonc").write_text("{}")

        result = _resolve_opencode_config()
        assert result == json_file

    def test_falls_back_to_jsonc(self, tmp_path, monkeypatch):
        """When only .jsonc exists, use it."""
        from ai_guardian.setup.utils import _resolve_opencode_config

        self._with_home(monkeypatch, tmp_path)
        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)
        jsonc_file = opencode_dir / "opencode.jsonc"
        jsonc_file.write_text("{}")

        result = _resolve_opencode_config()
        assert result == jsonc_file

    def test_creates_jsonc_path_when_none_exist(self, tmp_path, monkeypatch):
        """When neither exists, return .jsonc path."""
        from ai_guardian.setup.utils import _resolve_opencode_config

        self._with_home(monkeypatch, tmp_path)
        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)

        result = _resolve_opencode_config()
        assert result == opencode_dir / "opencode.jsonc"
        assert not result.exists()

    def test_prefers_json_over_jsonc(self, tmp_path, monkeypatch):
        """Only .json exists — returns .json, not .jsonc."""
        from ai_guardian.setup.utils import _resolve_opencode_config

        self._with_home(monkeypatch, tmp_path)
        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)
        json_file = opencode_dir / "opencode.json"
        json_file.write_text("{}")

        result = _resolve_opencode_config()
        assert result == json_file
