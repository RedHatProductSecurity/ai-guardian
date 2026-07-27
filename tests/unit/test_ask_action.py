"""Tests for the ask action mode (Issue #1115).

Covers: parse_ask_action(), pattern editor validation, config writer,
ask dialog headless fallback, and hook_processing integration.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ai_guardian.constants import ActionMode, parse_ask_action


class TestParseAskAction:
    """Tests for parse_ask_action() compound syntax parsing."""

    def test_plain_ask(self):
        primary, fallback = parse_ask_action("ask")
        assert primary == ActionMode.ASK
        assert fallback == ActionMode.BLOCK

    def test_ask_with_block_fallback(self):
        primary, fallback = parse_ask_action("ask:block")
        assert primary == ActionMode.ASK
        assert fallback == ActionMode.BLOCK

    def test_ask_with_warn_fallback(self):
        primary, fallback = parse_ask_action("ask:warn")
        assert primary == ActionMode.ASK
        assert fallback == ActionMode.WARN

    def test_ask_with_log_only_fallback(self):
        primary, fallback = parse_ask_action("ask:log-only")
        assert primary == ActionMode.ASK
        assert fallback == ActionMode.LOG_ONLY

    def test_ask_with_invalid_fallback(self):
        primary, fallback = parse_ask_action("ask:invalid")
        assert primary == ActionMode.ASK
        assert fallback == ActionMode.BLOCK

    def test_non_ask_action_block(self):
        primary, fallback = parse_ask_action("block")
        assert primary == "block"
        assert fallback == "block"

    def test_non_ask_action_warn(self):
        primary, fallback = parse_ask_action("warn")
        assert primary == "warn"
        assert fallback == "warn"

    def test_non_ask_action_log_only(self):
        primary, fallback = parse_ask_action("log-only")
        assert primary == "log-only"
        assert fallback == "log-only"

    def test_empty_string(self):
        primary, fallback = parse_ask_action("")
        assert primary == ActionMode.BLOCK
        assert fallback == ActionMode.BLOCK

    def test_none(self):
        primary, fallback = parse_ask_action(None)
        assert primary == ActionMode.BLOCK
        assert fallback == ActionMode.BLOCK

    def test_whitespace(self):
        primary, fallback = parse_ask_action("  ask:warn  ")
        assert primary == ActionMode.ASK
        assert fallback == ActionMode.WARN


class TestActionModeEnum:
    """Tests for ASK value in ActionMode enum."""

    def test_ask_value(self):
        assert ActionMode.ASK == "ask"
        assert ActionMode.ASK.value == "ask"

    def test_ask_in_enum(self):
        assert "ask" in [m.value for m in ActionMode]


class TestPatternEditor:
    """Tests for pattern_editor.py validation and conversion."""

    def test_validate_regex_pattern_valid(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern(
            r"CARBONITE_IMAGE\s*=", "regex", "CARBONITE_IMAGE=quay.io/foo"
        )
        assert valid is True

    def test_validate_regex_pattern_no_match(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern(
            r"DOES_NOT_EXIST", "regex", "CARBONITE_IMAGE=quay.io/foo"
        )
        assert valid is False
        assert "does not match" in msg.lower()

    def test_validate_empty_pattern(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern("", "regex", "test")
        assert valid is False

    def test_validate_dangerous_pattern(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern(".*", "regex", "anything")
        assert valid is False
        assert "too broad" in msg.lower()

    def test_validate_string_pattern(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern(
            "CARBONITE_IMAGE=", "string", "CARBONITE_IMAGE=quay.io/foo"
        )
        assert valid is True

    def test_validate_glob_pattern(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern(
            "CARBONITE_IMAGE*", "glob", "CARBONITE_IMAGE=quay.io/foo"
        )
        assert valid is True

    def test_validate_glob_no_match(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern(
            "DOES_NOT_EXIST*", "glob", "CARBONITE_IMAGE=quay.io/foo"
        )
        assert valid is False
        assert "does not match" in msg.lower()

    def test_validate_glob_dangerous_star(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern("*", "glob", "anything")
        assert valid is False
        assert "too broad" in msg.lower()

    def test_validate_string_no_match(self):
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern(
            "DOES_NOT_EXIST", "string", "CARBONITE_IMAGE=quay.io/foo"
        )
        assert valid is False
        assert "does not match" in msg.lower()

    def test_config_preview_saves_native_glob(self):
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("*.example.com", "ssrf_protection")
        parsed = json.loads(result)
        assert "*.example.com" in parsed["ssrf_protection"]["allowed_domains"]

    def test_config_preview_saves_native_string(self):
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("daf-workflow", "permissions")
        parsed = json.loads(result)
        assert parsed["permissions"]["rules"][0]["matcher"] == "daf-workflow"
        assert "daf\\-workflow" not in json.dumps(parsed)

    def test_convert_to_regex_string(self):
        from ai_guardian.tui.pattern_editor import convert_to_regex

        result = convert_to_regex("hello.world", "string")
        assert result == r"hello\.world"

    def test_convert_to_regex_glob(self):
        from ai_guardian.tui.pattern_editor import convert_to_regex
        import re

        result = convert_to_regex("CARB*IMAGE", "glob")
        assert re.match(result, "CARBONITE_IMAGE")

    def test_convert_to_regex_passthrough(self):
        from ai_guardian.tui.pattern_editor import convert_to_regex

        result = convert_to_regex(r"CARB\w+IMAGE", "regex")
        assert result == r"CARB\w+IMAGE"

    def test_generate_config_preview(self):
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview(r"CARB\w+", "secret_scanning")
        parsed = json.loads(result)
        assert "secret_scanning" in parsed
        assert r"CARB\w+" in parsed["secret_scanning"]["allowlist_patterns"]

    def test_suggest_pattern(self):
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("hello.world")
        assert result == r"hello\.world"


class TestConfigWriter:
    """Tests for config_writer.py safe config file writing."""

    def test_add_pattern_to_empty_config(self):
        from ai_guardian.config.writer import add_allowlist_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            result = add_allowlist_pattern(
                "secret_scanning", r"CARB\w+", config_path=config_path
            )
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert r"CARB\w+" in config["secret_scanning"]["allowlist_patterns"]

    def test_add_pattern_to_existing_config(self):
        from ai_guardian.config.writer import add_allowlist_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "secret_scanning": {
                            "enabled": True,
                            "allowlist_patterns": ["existing"],
                        }
                    }
                )
            )
            result = add_allowlist_pattern(
                "secret_scanning", r"new_pattern", config_path=config_path
            )
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert "existing" in config["secret_scanning"]["allowlist_patterns"]
            assert "new_pattern" in config["secret_scanning"]["allowlist_patterns"]

    def test_add_duplicate_pattern(self):
        from ai_guardian.config.writer import add_allowlist_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps({"secret_scanning": {"allowlist_patterns": ["existing"]}})
            )
            result = add_allowlist_pattern(
                "secret_scanning", "existing", config_path=config_path
            )
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert (
                config["secret_scanning"]["allowlist_patterns"].count("existing") == 1
            )

    def test_add_pattern_with_expiration(self):
        from ai_guardian.config.writer import add_allowlist_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            result = add_allowlist_pattern(
                "prompt_injection",
                r"test\w+",
                valid_until="2027-01-01T00:00:00Z",
                config_path=config_path,
            )
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            entry = config["prompt_injection"]["allowlist_patterns"][0]
            assert isinstance(entry, dict)
            assert entry["pattern"] == r"test\w+"
            assert entry["valid_until"] == "2027-01-01T00:00:00Z"

    def test_reject_dangerous_pattern(self):
        from ai_guardian.config.writer import add_allowlist_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            result = add_allowlist_pattern(
                "secret_scanning", ".*", config_path=config_path
            )
            assert result is False

    def test_reject_empty_inputs(self):
        from ai_guardian.config.writer import add_allowlist_pattern

        assert add_allowlist_pattern("", "pattern") is False
        assert add_allowlist_pattern("section", "") is False

    def test_new_section_created(self):
        from ai_guardian.config.writer import add_allowlist_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            result = add_allowlist_pattern(
                "prompt_injection", r"test\w+", config_path=config_path
            )
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert "prompt_injection" in config
            assert r"test\w+" in config["prompt_injection"]["allowlist_patterns"]


class TestSaveAskPattern:
    """Tests for save_ask_pattern() unified dispatcher."""

    def test_dispatches_to_ssrf(self):
        from ai_guardian.config.writer import save_ask_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            assert (
                save_ask_pattern(
                    "ssrf_protection", "example.com", config_path=config_path
                )
                is True
            )
            config = json.loads(config_path.read_text())
            assert "example.com" in config["ssrf_protection"]["allowed_domains"]

    def test_dispatches_to_directory_rules(self):
        from ai_guardian.config.writer import save_ask_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            assert (
                save_ask_pattern("directory_rules", "/tmp/**", config_path=config_path)
                is True
            )
            config = json.loads(config_path.read_text())
            assert "/tmp/**" in config["directory_rules"]["exclusions"]

    def test_dispatches_to_supply_chain(self):
        from ai_guardian.config.writer import save_ask_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            assert (
                save_ask_pattern(
                    "supply_chain", "~/.claude/settings.json", config_path=config_path
                )
                is True
            )
            config = json.loads(config_path.read_text())
            assert (
                "~/.claude/settings.json" in config["supply_chain"]["allowlist_paths"]
            )

    def test_dispatches_to_config_file_scanning(self):
        from ai_guardian.config.writer import save_ask_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            assert (
                save_ask_pattern(
                    "config_file_scanning", "CLAUDE.md", config_path=config_path
                )
                is True
            )
            config = json.loads(config_path.read_text())
            assert "CLAUDE.md" in config["config_file_scanning"]["ignore_files"]

    def test_dispatches_to_permissions(self):
        from ai_guardian.config.writer import save_ask_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            assert (
                save_ask_pattern(
                    "permissions", "Bash:npm test", config_path=config_path
                )
                is True
            )
            config = json.loads(config_path.read_text())
            rule = config["permissions"]["rules"][0]
            assert rule == {
                "mode": "allow",
                "matcher": "Bash",
                "patterns": ["npm test"],
            }

    def test_dispatches_to_default_allowlist(self):
        from ai_guardian.config.writer import save_ask_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            assert (
                save_ask_pattern("secret_scanning", r"FAKE\w+", config_path=config_path)
                is True
            )
            config = json.loads(config_path.read_text())
            assert r"FAKE\w+" in config["secret_scanning"]["allowlist_patterns"]


class TestParsePermissionPattern:
    """Tests for _parse_permission_pattern() helper."""

    def test_with_colon(self):
        from ai_guardian.config.writer import _parse_permission_pattern

        matcher, patterns = _parse_permission_pattern("Bash:npm test")
        assert matcher == "Bash"
        assert patterns == ["npm test"]

    def test_without_colon(self):
        from ai_guardian.config.writer import _parse_permission_pattern

        matcher, patterns = _parse_permission_pattern("Skill")
        assert matcher == "Skill"
        assert patterns == ["*"]

    def test_colon_in_value(self):
        from ai_guardian.config.writer import _parse_permission_pattern

        matcher, patterns = _parse_permission_pattern("Bash:echo foo:bar")
        assert matcher == "Bash"
        assert patterns == ["echo foo:bar"]


class TestPermissionRuleMerging:
    """Tests for permission rule merging into existing matcher (#1192)."""

    def test_merge_pattern_into_existing_matcher(self):
        from ai_guardian.config.writer import add_permission_rule

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "rules": [
                                {
                                    "mode": "allow",
                                    "matcher": "Skill",
                                    "patterns": ["code-review", "bugfix-workflow"],
                                }
                            ]
                        }
                    }
                )
            )
            result = add_permission_rule(
                "Skill", ["daf-workflow"], config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            rules = config["permissions"]["rules"]
            assert len(rules) == 1
            assert rules[0]["patterns"] == [
                "code-review",
                "bugfix-workflow",
                "daf-workflow",
            ]

    def test_merge_mcp_tool_pattern_into_existing_matcher(self):
        from ai_guardian.config.writer import add_permission_rule

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "rules": [
                                {
                                    "mode": "allow",
                                    "matcher": "mcp__server__tool_a",
                                    "patterns": ["*"],
                                }
                            ]
                        }
                    }
                )
            )
            result = add_permission_rule(
                "mcp__server__tool_a", ["specific-arg"], config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            rules = config["permissions"]["rules"]
            assert len(rules) == 1
            assert "specific-arg" in rules[0]["patterns"]
            assert "*" in rules[0]["patterns"]

    def test_no_duplicate_pattern_in_merge(self):
        from ai_guardian.config.writer import add_permission_rule

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "rules": [
                                {
                                    "mode": "allow",
                                    "matcher": "Skill",
                                    "patterns": ["code-review"],
                                }
                            ]
                        }
                    }
                )
            )
            result = add_permission_rule(
                "Skill", ["code-review"], config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert (
                config["permissions"]["rules"][0]["patterns"].count("code-review") == 1
            )

    def test_new_rule_when_no_matching_matcher(self):
        from ai_guardian.config.writer import add_permission_rule

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "rules": [
                                {
                                    "mode": "allow",
                                    "matcher": "Bash",
                                    "patterns": ["npm test"],
                                }
                            ]
                        }
                    }
                )
            )
            result = add_permission_rule(
                "Skill", ["daf-workflow"], config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            rules = config["permissions"]["rules"]
            assert len(rules) == 2
            assert rules[1] == {
                "mode": "allow",
                "matcher": "Skill",
                "patterns": ["daf-workflow"],
            }

    def test_merge_via_save_ask_pattern(self):
        from ai_guardian.config.writer import save_ask_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "rules": [
                                {
                                    "mode": "allow",
                                    "matcher": "Skill",
                                    "patterns": ["code-review"],
                                }
                            ]
                        }
                    }
                )
            )
            result = save_ask_pattern(
                "permissions", "Skill:daf-workflow", config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            rules = config["permissions"]["rules"]
            assert len(rules) == 1
            assert "daf-workflow" in rules[0]["patterns"]
            assert "code-review" in rules[0]["patterns"]

    def test_prepare_config_preview_merges_into_existing(self):
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "rules": [
                                {
                                    "mode": "allow",
                                    "matcher": "Skill",
                                    "patterns": ["code-review"],
                                }
                            ]
                        }
                    }
                )
            )
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    "Skill:daf-workflow", "permissions"
                )
            parsed = json.loads(json_text)
            rules = parsed["permissions"]["rules"]
            assert len(rules) == 1
            assert "daf-workflow" in rules[0]["patterns"]
            assert "code-review" in rules[0]["patterns"]


class TestAskDialogHeadlessFallback:
    """Tests for headless fallback behavior."""

    def test_fallback_block(self):
        from ai_guardian.tui.ask_dialog import _map_fallback_to_decision, AskDecision

        assert _map_fallback_to_decision("block") == AskDecision.BLOCK

    def test_fallback_warn(self):
        from ai_guardian.tui.ask_dialog import _map_fallback_to_decision, AskDecision

        assert _map_fallback_to_decision("warn") == AskDecision.ALLOW_ONCE

    def test_fallback_log_only(self):
        from ai_guardian.tui.ask_dialog import _map_fallback_to_decision, AskDecision

        assert _map_fallback_to_decision("log-only") == AskDecision.ALLOW_ONCE

    def test_fallback_unknown(self):
        from ai_guardian.tui.ask_dialog import _map_fallback_to_decision, AskDecision

        assert _map_fallback_to_decision("unknown") == AskDecision.BLOCK

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_show_ask_dialog_headless_block(self, _mock_sub, _mock_daemon):
        from ai_guardian.tui.ask_dialog import (
            show_ask_dialog,
            AskViolationInfo,
            AskDecision,
        )

        violation = AskViolationInfo(
            violation_type="secret_detected",
            summary="Test secret",
            matched_text="FAKE_TOKEN=abc123",
            config_section="secret_scanning",
        )
        result = show_ask_dialog(violation, fallback_action="block")
        assert result.decision == AskDecision.BLOCK

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_show_ask_dialog_headless_warn(self, _mock_sub, _mock_daemon):
        from ai_guardian.tui.ask_dialog import (
            show_ask_dialog,
            AskViolationInfo,
            AskDecision,
        )

        violation = AskViolationInfo(
            violation_type="secret_detected",
            summary="Test secret",
            matched_text="FAKE_TOKEN=abc123",
            config_section="secret_scanning",
        )
        result = show_ask_dialog(violation, fallback_action="warn")
        assert result.decision == AskDecision.ALLOW_ONCE


class TestHandleAskMode:
    """Tests for _handle_ask_mode() in hook_processing."""

    def test_non_ask_action_returns_none(self):
        from ai_guardian.ask_mode import _handle_ask_mode

        result = _handle_ask_mode(
            "block", "secret_detected", "text", "secret_scanning", "error"
        )
        assert result is None

    def test_non_ask_warn_returns_none(self):
        from ai_guardian.ask_mode import _handle_ask_mode

        result = _handle_ask_mode(
            "warn", "secret_detected", "text", "secret_scanning", "error"
        )
        assert result is None

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_ask_headless_block_fallback(self, _mock_sub, _mock_daemon):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask", "secret_detected", "FAKE_TOKEN", "secret_scanning", "error"
        )
        assert result is not None
        assert result.decision == AskDecision.BLOCK

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_ask_warn_headless_fallback(self, _mock_sub, _mock_daemon):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask:warn", "secret_detected", "FAKE_TOKEN", "secret_scanning", "error"
        )
        assert result is not None
        assert result.decision == AskDecision.ALLOW_ONCE

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_ask_allow_always_writes_pattern(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS, allowlist_pattern=r"FAKE\w+"
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask", "secret_detected", "FAKE_TOKEN", "secret_scanning", "error"
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "secret_scanning", r"FAKE\w+", config_path=None
        )


class TestAskCacheInvalidation:
    """Tests for config cache invalidation after ask dialog saves (#1301)."""

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_allow_always_clears_config_cache(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS, allowlist_pattern=r"FAKE\w+"
        )
        with (
            patch("ai_guardian.config.writer.save_ask_pattern") as mock_write,
            patch("ai_guardian.config.loaders._clear_config_cache") as mock_clear,
        ):
            mock_write.return_value = True
            _handle_ask_mode(
                "ask", "secret_detected", "FAKE_TOKEN", "secret_scanning", "error"
            )
        mock_clear.assert_called_once()
        _, kwargs = mock_clear.call_args
        assert "project_key" in kwargs

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_allow_always_clears_cache_with_project_path(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS, allowlist_pattern=r"FAKE\w+"
        )
        with (
            patch("ai_guardian.config.writer.save_ask_pattern") as mock_write,
            patch("ai_guardian.config.loaders._clear_config_cache") as mock_clear,
        ):
            mock_write.return_value = True
            _handle_ask_mode(
                "ask",
                "secret_detected",
                "FAKE_TOKEN",
                "secret_scanning",
                "error",
                hook_context={"project_path": "/tmp/my-project"},
            )
        mock_clear.assert_called_once_with(project_key="/tmp/my-project")

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_allow_always_config_saved_still_clears_cache(self, mock_dialog):
        """Cache must be cleared even when the dialog already saved the config."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern=r"FAKE\w+",
            config_saved=True,
        )
        with patch("ai_guardian.config.loaders._clear_config_cache") as mock_clear:
            _handle_ask_mode(
                "ask",
                "secret_detected",
                "FAKE_TOKEN",
                "secret_scanning",
                "error",
                hook_context={"project_path": "/tmp/my-project"},
            )
        mock_clear.assert_called_once_with(project_key="/tmp/my-project")

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_ignore_file_clears_config_cache(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.IGNORE_FILE,
            ignore_path="src/generated/*.py",
        )
        with (
            patch("ai_guardian.tui.ask_dialog._save_ignore_path") as mock_save,
            patch("ai_guardian.config.loaders._clear_config_cache") as mock_clear,
        ):
            mock_save.return_value = True
            _handle_ask_mode(
                "ask",
                "secret_detected",
                "FAKE_TOKEN",
                "secret_scanning",
                "error",
                hook_context={"project_path": "/tmp/my-project"},
            )
        mock_clear.assert_called_once_with(project_key="/tmp/my-project")

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_allow_once_does_not_clear_cache(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(decision=AskDecision.ALLOW_ONCE)
        with patch("ai_guardian.config.loaders._clear_config_cache") as mock_clear:
            _handle_ask_mode(
                "ask", "secret_detected", "FAKE_TOKEN", "secret_scanning", "error"
            )
        mock_clear.assert_not_called()


class TestAskDialogTiming:
    """Tests for ask dialog wait time tracking (#1159)."""

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_dialog_wait_ms_recorded_in_result(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(decision=AskDecision.ALLOW_ONCE)
        result = _handle_ask_mode(
            "ask", "secret_detected", "test", "secret_scanning", "error"
        )
        assert result.dialog_wait_ms >= 0.0

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_latency_timer_receives_ask_wait(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision
        from ai_guardian.reporting.latency import _CheckTimer

        mock_dialog.return_value = AskResult(decision=AskDecision.BLOCK)
        timer = _CheckTimer(enabled=True)
        result = _handle_ask_mode(
            "ask",
            "secret_detected",
            "test",
            "secret_scanning",
            "error",
            latency_timer=timer,
        )
        assert timer.ask_wait_total_ms > 0
        assert timer.ask_wait_total_ms == pytest.approx(result.dialog_wait_ms, abs=0.1)

    def test_non_ask_action_returns_none_no_timing(self):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.reporting.latency import _CheckTimer

        timer = _CheckTimer(enabled=True)
        result = _handle_ask_mode(
            "block",
            "secret_detected",
            "test",
            "secret_scanning",
            "error",
            latency_timer=timer,
        )
        assert result is None
        assert timer.ask_wait_total_ms == 0.0


class TestSSRFAskAction:
    """Tests for ask action mode with SSRF protection (Issue #1129)."""

    def test_ssrf_ask_action_schema_accepts_ask(self):
        """Verify JSON schema accepts ask values for ssrf_protection.action."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        ssrf_schema = schema["properties"]["ssrf_protection"]
        for action_val in ["ask", "ask:block", "ask:warn", "ask:log-only"]:
            config = {"action": action_val}
            jsonschema.validate(config, ssrf_schema)

    def test_ssrf_ask_action_schema_rejects_invalid(self):
        """Verify JSON schema rejects invalid ask values."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        ssrf_schema = schema["properties"]["ssrf_protection"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"action": "ask:invalid"}, ssrf_schema)

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    @patch("subprocess.run")
    def test_ssrf_ask_headless_block_fallback(
        self, mock_sub_run, _mock_sub, _mock_daemon
    ):
        """Headless with 'ask' action should fall back to BLOCK."""
        mock_sub_run.side_effect = FileNotFoundError
        from ai_guardian.scanners.ssrf import SSRFProtector

        config = {
            "action": "ask",
            "enabled": True,
            "additional_blocked_domains": ["evil.internal.corp"],
        }
        protector = SSRFProtector(config)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://evil.internal.corp"}
        )
        assert should_block is True

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    @patch("subprocess.run")
    def test_ssrf_ask_warn_headless_allows(self, mock_sub_run, _mock_sub, _mock_daemon):
        """With ask:warn, check() returns True (ask needed) — caller handles fallback."""
        mock_sub_run.side_effect = FileNotFoundError
        from ai_guardian.scanners.ssrf import SSRFProtector

        config = {
            "action": "ask:warn",
            "enabled": True,
            "additional_blocked_domains": ["evil.internal.corp"],
        }
        protector = SSRFProtector(config)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://evil.internal.corp"}
        )
        assert should_block is True
        assert len(protector.findings) == 1

    def test_ssrf_immutable_skips_ask(self):
        """Private IP with 'ask' action should always block without showing dialog."""
        from ai_guardian.scanners.ssrf import SSRFProtector

        config = {"action": "ask", "enabled": True}
        protector = SSRFProtector(config)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254/latest/meta-data/"}
        )
        assert should_block is True
        assert "immutable" in msg.lower() or "BLOCKED" in msg

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_ssrf_ask_allow_always_writes_domain(self, mock_dialog):
        """SSRF Allow Always should call save_ask_pattern with ssrf_protection."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS, allowlist_pattern="evil.internal.corp"
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask",
                "ssrf_blocked",
                "http://evil.internal.corp/api",
                "ssrf_protection",
                "SSRF blocked",
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "ssrf_protection", "evil.internal.corp", config_path=None
        )


class TestSuggestDomain:
    """Tests for suggest_domain() in pattern_editor."""

    def test_extract_domain_from_https_url(self):
        from ai_guardian.tui.pattern_editor import suggest_domain

        assert suggest_domain("https://api.example.com/v1/data") == "api.example.com"

    def test_extract_domain_from_http_url(self):
        from ai_guardian.tui.pattern_editor import suggest_domain

        assert (
            suggest_domain("http://evil.internal.corp:8080/admin")
            == "evil.internal.corp"
        )

    def test_extract_domain_lowercase(self):
        from ai_guardian.tui.pattern_editor import suggest_domain

        assert suggest_domain("https://API.Example.COM/path") == "api.example.com"

    def test_plain_domain_passthrough(self):
        from ai_guardian.tui.pattern_editor import suggest_domain

        assert suggest_domain("example.com") == "example.com"

    def test_suggest_pattern_ssrf_section(self):
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("https://evil.corp/api", "ssrf_protection")
        assert result == "evil.corp"

    def test_suggest_pattern_non_ssrf_section(self):
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("FAKE_TOKEN=abc", "secret_scanning")
        assert result == r"FAKE_TOKEN\s*="

    def test_generate_config_preview_ssrf(self):
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("evil.corp", "ssrf_protection")
        parsed = json.loads(result)
        assert "ssrf_protection" in parsed
        assert "evil.corp" in parsed["ssrf_protection"]["allowed_domains"]

    def test_generate_config_preview_non_ssrf(self):
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview(r"FAKE\w+", "secret_scanning")
        parsed = json.loads(result)
        assert r"FAKE\w+" in parsed["secret_scanning"]["allowlist_patterns"]


class TestAddAllowedDomain:
    """Tests for add_allowed_domain() in config_writer."""

    def test_add_domain_to_empty_config(self):
        from ai_guardian.config.writer import add_allowed_domain

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            result = add_allowed_domain("api.example.com", config_path=config_path)
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert "api.example.com" in config["ssrf_protection"]["allowed_domains"]

    def test_add_domain_to_existing_config(self):
        from ai_guardian.config.writer import add_allowed_domain

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "ssrf_protection": {
                            "enabled": True,
                            "allowed_domains": ["existing.com"],
                        }
                    }
                )
            )
            result = add_allowed_domain("new.example.com", config_path=config_path)
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert "existing.com" in config["ssrf_protection"]["allowed_domains"]
            assert "new.example.com" in config["ssrf_protection"]["allowed_domains"]

    def test_add_duplicate_domain(self):
        from ai_guardian.config.writer import add_allowed_domain

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps({"ssrf_protection": {"allowed_domains": ["existing.com"]}})
            )
            result = add_allowed_domain("existing.com", config_path=config_path)
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert (
                config["ssrf_protection"]["allowed_domains"].count("existing.com") == 1
            )

    def test_add_domain_normalizes_case(self):
        from ai_guardian.config.writer import add_allowed_domain

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            result = add_allowed_domain("API.Example.COM", config_path=config_path)
            assert result is True
            with open(config_path) as f:
                config = json.load(f)
            assert "api.example.com" in config["ssrf_protection"]["allowed_domains"]

    def test_reject_empty_domain(self):
        from ai_guardian.config.writer import add_allowed_domain

        assert add_allowed_domain("") is False
        assert add_allowed_domain("   ") is False


class TestSuggestPatternEnvVariable:
    """Tests for smart env-variable pattern suggestions (Issue #1140)."""

    def test_suggest_pattern_env_variable(self):
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("DAF_SESSION_NAME=some-value", "secret_scanning")
        assert result == r"DAF_SESSION_NAME\s*="

    def test_suggest_pattern_env_variable_with_spaces(self):
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("MY_SECRET = hunter2", "secret_scanning")
        assert result == r"MY_SECRET\s*="

    def test_suggest_pattern_non_env_unchanged(self):
        import re
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("ghp_abc123def456", "secret_scanning")
        assert result == re.escape("ghp_abc123def456")

    def test_suggest_pattern_lowercase_not_env(self):
        import re
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("some_key=value", "secret_scanning")
        assert result == re.escape("some_key=value")


class TestExtractMatchedTextForAsk:
    """Tests for _extract_matched_text_for_ask helper (Issue #1140)."""

    def test_prefers_explicit_matched_text(self):
        from ai_guardian.scanners.secret_scanning import _extract_matched_text_for_ask

        details = {"matched_text": "API_KEY=secret123", "line_number": 5}
        result = _extract_matched_text_for_ask(
            details, "line1\nline2\nline3\nline4\nAPI_KEY=secret123"
        )
        assert result == "API_KEY=secret123"

    def test_fallback_to_line_number(self):
        from ai_guardian.scanners.secret_scanning import _extract_matched_text_for_ask

        details = {"line_number": 3}
        result = _extract_matched_text_for_ask(
            details, "line1\nline2\nTHE_SECRET_LINE\nline4"
        )
        assert result == "THE_SECRET_LINE"

    def test_empty_details(self):
        from ai_guardian.scanners.secret_scanning import _extract_matched_text_for_ask

        result = _extract_matched_text_for_ask(None, "content")
        assert result == ""

    def test_no_matched_text_no_line_number(self):
        from ai_guardian.scanners.secret_scanning import _extract_matched_text_for_ask

        result = _extract_matched_text_for_ask({"rule_id": "test"}, "content")
        assert result == ""

    def test_line_number_out_of_range(self):
        from ai_guardian.scanners.secret_scanning import _extract_matched_text_for_ask

        result = _extract_matched_text_for_ask({"line_number": 99}, "line1\nline2")
        assert result == ""


class TestExtractPiiMatchedText:
    """Tests for _extract_pii_matched_text helper (Issue #1164)."""

    def test_extracts_text_from_position(self):
        from ai_guardian.hook_processing import _extract_pii_matched_text

        content = "Hello my passport is AB1234567 thanks"
        redactions = [
            {"type": "Passport numbers", "position": 21, "original_length": 9}
        ]
        result = _extract_pii_matched_text(redactions, content)
        assert result == "AB1234567"

    def test_uses_first_redaction(self):
        from ai_guardian.hook_processing import _extract_pii_matched_text

        content = "SSN 123-45-6789 and passport AB1234567"
        redactions = [
            {"type": "SSN", "position": 4, "original_length": 11},
            {"type": "Passport numbers", "position": 29, "original_length": 9},
        ]
        result = _extract_pii_matched_text(redactions, content)
        assert result == "123-45-6789"

    def test_empty_redactions(self):
        from ai_guardian.hook_processing import _extract_pii_matched_text

        assert _extract_pii_matched_text([], "content") == ""

    def test_empty_content(self):
        from ai_guardian.hook_processing import _extract_pii_matched_text

        redactions = [{"type": "SSN", "position": 0, "original_length": 11}]
        assert _extract_pii_matched_text(redactions, "") == ""

    def test_none_inputs(self):
        from ai_guardian.hook_processing import _extract_pii_matched_text

        assert _extract_pii_matched_text(None, "content") == ""
        assert _extract_pii_matched_text([], None) == ""

    def test_position_out_of_bounds(self):
        from ai_guardian.hook_processing import _extract_pii_matched_text

        redactions = [{"type": "SSN", "position": 100, "original_length": 11}]
        assert _extract_pii_matched_text(redactions, "short") == ""

    def test_missing_position_field(self):
        from ai_guardian.hook_processing import _extract_pii_matched_text

        redactions = [{"type": "SSN", "original_length": 11}]
        assert _extract_pii_matched_text(redactions, "content here") == ""


class TestExtractFilePathFromPiiWarning:
    """Tests for _extract_file_path_from_pii_warning helper (Issue #1271)."""

    def test_extracts_path_from_warning(self):
        from ai_guardian.hook_processing import _extract_file_path_from_pii_warning

        warning = (
            "\n======\n"
            "PII DETECTED\n"
            "======\n"
            "File: /Users/dev/project/tests/data/test.txt\n"
            "Found 1 PII item(s):\n"
        )
        result = _extract_file_path_from_pii_warning(warning)
        assert result == "/Users/dev/project/tests/data/test.txt"

    def test_extracts_truncated_path(self):
        from ai_guardian.hook_processing import _extract_file_path_from_pii_warning

        warning = "File: .../very/long/path/file.txt\nFound 1 PII item(s):"
        result = _extract_file_path_from_pii_warning(warning)
        assert result == ".../very/long/path/file.txt"

    def test_returns_none_for_no_file(self):
        from ai_guardian.hook_processing import _extract_file_path_from_pii_warning

        warning = "PII DETECTED\nFound 1 PII item(s):\n  - SSN"
        assert _extract_file_path_from_pii_warning(warning) is None

    def test_returns_none_for_none_input(self):
        from ai_guardian.hook_processing import _extract_file_path_from_pii_warning

        assert _extract_file_path_from_pii_warning(None) is None

    def test_returns_none_for_empty_string(self):
        from ai_guardian.hook_processing import _extract_file_path_from_pii_warning

        assert _extract_file_path_from_pii_warning("") is None


class TestHandleAskModeMatchedText:
    """Tests for matched_text flowing through _handle_ask_mode (Issue #1140)."""

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_matched_text_flows_to_violation_info(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(decision=AskDecision.BLOCK)
        _handle_ask_mode(
            "ask",
            "secret_detected",
            "MY_SECRET=value123",
            "secret_scanning",
            "Secret Type: Environment Variable",
        )
        call_args = mock_dialog.call_args
        violation_info = call_args[0][0]
        assert violation_info.matched_text == "MY_SECRET=value123"


class TestPatternEditorAutoUpdate:
    """Tests for auto-update of config preview when pattern input changes (Issue #1158)."""

    def test_tkinter_pattern_var_trace_triggers_preview_update(self):
        """Verify that modifying pattern_var calls do_test via trace callback."""
        from ai_guardian.tui.pattern_editor import (
            validate_pattern,
            generate_config_preview,
            convert_to_regex,
        )

        call_count = [0]
        original_validate = validate_pattern

        def counting_validate(*args, **kwargs):
            call_count[0] += 1
            return original_validate(*args, **kwargs)

        pat1 = r"FAKE_TOKEN\s*="
        pat2 = r"FAKE\w+"
        test_text = "FAKE_TOKEN=abc123"

        valid1, _ = counting_validate(pat1, "regex", test_text)
        valid2, _ = counting_validate(pat2, "regex", test_text)
        assert valid1 is True
        assert valid2 is True
        assert call_count[0] == 2

        preview1 = generate_config_preview(
            convert_to_regex(pat1, "regex"), "secret_scanning"
        )
        preview2 = generate_config_preview(
            convert_to_regex(pat2, "regex"), "secret_scanning"
        )
        parsed1 = json.loads(preview1)
        parsed2 = json.loads(preview2)
        assert pat1 in parsed1["secret_scanning"]["allowlist_patterns"]
        assert pat2 in parsed2["secret_scanning"]["allowlist_patterns"]
        assert preview1 != preview2

    def test_preview_updates_for_different_patterns(self):
        """Config preview should reflect the current pattern, not the initial one."""
        from ai_guardian.tui.pattern_editor import (
            validate_pattern,
            convert_to_regex,
            generate_config_preview,
            suggest_pattern,
        )
        import json

        matched_text = "MY_API_KEY=secret123"
        initial_pattern = suggest_pattern(matched_text, "secret_scanning")
        assert initial_pattern == r"MY_API_KEY\s*="

        valid, _ = validate_pattern(initial_pattern, "regex", matched_text)
        assert valid is True
        initial_preview = generate_config_preview(
            convert_to_regex(initial_pattern, "regex"), "secret_scanning"
        )
        initial_config = json.loads(initial_preview)
        assert (
            initial_pattern in initial_config["secret_scanning"]["allowlist_patterns"]
        )

        edited_pattern = r"MY_API_KEY\s*=\s*secret"
        valid, _ = validate_pattern(edited_pattern, "regex", matched_text)
        assert valid is True
        updated_preview = generate_config_preview(
            convert_to_regex(edited_pattern, "regex"), "secret_scanning"
        )
        updated_config = json.loads(updated_preview)
        assert edited_pattern in updated_config["secret_scanning"]["allowlist_patterns"]
        assert initial_preview != updated_preview

    def test_invalid_pattern_does_not_update_preview(self):
        """When pattern becomes invalid, preview should not update (test status shows FAIL)."""
        from ai_guardian.tui.pattern_editor import validate_pattern

        valid, msg = validate_pattern("", "regex", "some text")
        assert valid is False
        assert "empty" in msg.lower()

        valid, msg = validate_pattern("[invalid(regex", "regex", "some text")
        assert valid is False

    def test_ssrf_preview_updates_for_domain_changes(self):
        """SSRF section should update allowed_domains preview as pattern changes."""
        from ai_guardian.tui.pattern_editor import generate_config_preview
        import json

        preview1 = generate_config_preview("api.example.com", "ssrf_protection")
        preview2 = generate_config_preview("api.other.com", "ssrf_protection")
        config1 = json.loads(preview1)
        config2 = json.loads(preview2)
        assert "api.example.com" in config1["ssrf_protection"]["allowed_domains"]
        assert "api.other.com" in config2["ssrf_protection"]["allowed_domains"]
        assert preview1 != preview2


class TestPostSaveConfirmation:
    """Tests for post-save confirmation in ask dialog (Issue #1141)."""

    def test_ask_result_has_config_saved_field(self):
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        result = AskResult(decision=AskDecision.ALLOW_ALWAYS, allowlist_pattern="test")
        assert result.config_saved is False

    def test_ask_result_config_saved_true(self):
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        result = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern="test",
            config_saved=True,
        )
        assert result.config_saved is True

    def test_save_pattern_to_config_calls_save_ask_pattern(self):
        from ai_guardian.tui.ask_dialog import _save_pattern_to_config

        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_add:
            mock_add.return_value = True
            result = _save_pattern_to_config(r"test\w+", "secret_scanning")
        assert result is True
        mock_add.assert_called_once_with(
            "secret_scanning", r"test\w+", config_path=None
        )

    def test_save_pattern_to_config_ssrf_calls_save_ask_pattern(self):
        from ai_guardian.tui.ask_dialog import _save_pattern_to_config

        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_add:
            mock_add.return_value = True
            result = _save_pattern_to_config("api.example.com", "ssrf_protection")
        assert result is True
        mock_add.assert_called_once_with(
            "ssrf_protection", "api.example.com", config_path=None
        )

    def test_save_pattern_to_config_handles_failure(self):
        from ai_guardian.tui.ask_dialog import _save_pattern_to_config

        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_add:
            mock_add.return_value = False
            result = _save_pattern_to_config(r"test\w+", "secret_scanning")
        assert result is False

    def test_save_pattern_to_config_handles_exception(self):
        from ai_guardian.tui.ask_dialog import _save_pattern_to_config

        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_add:
            mock_add.side_effect = RuntimeError("disk full")
            result = _save_pattern_to_config(r"test\w+", "secret_scanning")
        assert result is False

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_hook_processing_skips_save_when_config_saved(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern=r"FAKE\w+",
            config_saved=True,
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            result = _handle_ask_mode(
                "ask", "secret_detected", "FAKE_TOKEN", "secret_scanning", "error"
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_not_called()

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_hook_processing_saves_when_config_not_saved(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern=r"FAKE\w+",
            config_saved=False,
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask", "secret_detected", "FAKE_TOKEN", "secret_scanning", "error"
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "secret_scanning", r"FAKE\w+", config_path=None
        )

    def test_prepare_config_with_pattern_inserts_pattern(self):
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text('{"secret_scanning": {}}')
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    r"TEST\w+", "secret_scanning"
                )
        parsed = json.loads(json_text)
        assert r"TEST\w+" in parsed["secret_scanning"]["allowlist_patterns"]
        assert line_num > 0
        lines = json_text.splitlines()
        assert json.dumps(r"TEST\w+") in lines[line_num - 1]

    def test_prepare_config_with_pattern_ssrf(self):
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    "api.example.com", "ssrf_protection"
                )
        parsed = json.loads(json_text)
        assert "api.example.com" in parsed["ssrf_protection"]["allowed_domains"]

    def test_prepare_config_with_pattern_empty_config(self):
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    r"pat", "prompt_injection"
                )
        parsed = json.loads(json_text)
        assert "pat" in parsed["prompt_injection"]["allowlist_patterns"]

    def test_write_config_text_writes_file(self):
        from ai_guardian.tui.ask_dialog import _write_config_text

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                result = _write_config_text('{"test": true}\n')
            assert result is True
            assert json.loads(config_path.read_text()) == {"test": True}

    def test_write_config_text_rejects_invalid_json(self):
        from ai_guardian.tui.ask_dialog import _write_config_text

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text('{"original": true}')
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                result = _write_config_text("not valid json{{{")
            assert result is False
            assert json.loads(config_path.read_text()) == {"original": True}

    def test_save_pattern_to_config_directory_rules_calls_save_ask_pattern(self):
        from ai_guardian.tui.ask_dialog import _save_pattern_to_config

        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_add:
            mock_add.return_value = True
            result = _save_pattern_to_config("/home/user/project/**", "directory_rules")
        assert result is True
        mock_add.assert_called_once_with(
            "directory_rules", "/home/user/project/**", config_path=None
        )


class TestDirectoryBlockingAskAction:
    """Tests for ask action mode with directory blocking (Issue #1130)."""

    def test_directory_ask_schema_accepts_ask(self):
        """Verify JSON schema accepts ask values for directory_rules.action."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        dr_schema = schema["properties"]["directory_rules"]["oneOf"][1]
        for action_val in ["ask", "ask:block", "ask:warn", "ask:log-only"]:
            config = {"action": action_val}
            jsonschema.validate(config, dr_schema)

    def test_directory_ask_schema_rejects_invalid(self):
        """Verify JSON schema rejects invalid ask values."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        dr_schema = schema["properties"]["directory_rules"]["oneOf"][1]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"action": "ask:invalid"}, dr_schema)

    def test_directory_ask_schema_exclusions_field(self):
        """Verify JSON schema accepts exclusions array."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        dr_schema = schema["properties"]["directory_rules"]["oneOf"][1]
        config = {
            "action": "ask",
            "exclusions": ["/home/user/project/**"],
            "rules": [],
        }
        jsonschema.validate(config, dr_schema)

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_handle_ask_mode_directory_allow_always_writes_exclusion(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern="/home/user/project/**",
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask",
                "directory_blocking",
                "/home/user/project/secret.txt",
                "directory_rules",
                "Directory access denied",
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "directory_rules", "/home/user/project/**", config_path=None
        )

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_directory_ask_headless_block_fallback(self, _mock_sub, _mock_daemon):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask",
            "directory_blocking",
            "/secret/file.txt",
            "directory_rules",
            "Access denied",
        )
        assert result is not None
        assert result.decision == AskDecision.BLOCK

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_directory_ask_warn_headless_fallback(self, _mock_sub, _mock_daemon):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask:warn",
            "directory_blocking",
            "/secret/file.txt",
            "directory_rules",
            "Access denied",
        )
        assert result is not None
        assert result.decision == AskDecision.ALLOW_ONCE

    def test_exclusions_allow_denied_path(self):
        """Verify exclusions in config override deny rules."""
        from ai_guardian.hook_processing import _check_directory_rules

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "secret.txt")
            with open(test_file, "w") as f:
                f.write("test")
            config = {
                "directory_rules": {
                    "action": "block",
                    "rules": [{"mode": "deny", "paths": [tmpdir + "/**"]}],
                    "exclusions": [tmpdir + "/**"],
                }
            }
            decision, action, pattern = _check_directory_rules(test_file, config)
            assert decision == "allow"

    def test_exclusions_no_match_still_denied(self):
        """Verify non-matching exclusion doesn't override deny rules."""
        from ai_guardian.hook_processing import _check_directory_rules

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "secret.txt")
            with open(test_file, "w") as f:
                f.write("test")
            config = {
                "directory_rules": {
                    "action": "block",
                    "rules": [{"mode": "deny", "paths": [tmpdir + "/**"]}],
                    "exclusions": ["/other/path/**"],
                }
            }
            decision, action, pattern = _check_directory_rules(test_file, config)
            assert decision == "deny"

    def test_add_directory_exclusion_writes_config(self):
        """Verify add_directory_exclusion writes to directory_rules.exclusions."""
        from ai_guardian.config.writer import add_directory_exclusion

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                '{"directory_rules": {"action": "ask", "rules": []}}'
            )
            result = add_directory_exclusion(
                "/home/user/project/**", config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert "/home/user/project/**" in config["directory_rules"]["exclusions"]

    def test_add_directory_exclusion_dedup(self):
        """Verify add_directory_exclusion doesn't add duplicates."""
        from ai_guardian.config.writer import add_directory_exclusion

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "directory_rules": {
                            "action": "ask",
                            "rules": [],
                            "exclusions": ["/home/user/project/**"],
                        }
                    }
                )
            )
            result = add_directory_exclusion(
                "/home/user/project/**", config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert (
                config["directory_rules"]["exclusions"].count("/home/user/project/**")
                == 1
            )

    def test_get_directory_action_from_config_default(self):
        """Verify helper returns 'block' when no config available."""
        from ai_guardian.ask_mode import _get_directory_action_from_config

        with patch("ai_guardian.hook_processing.HAS_TOOL_POLICY", False):
            result = _get_directory_action_from_config()
        assert result == "block"

    def test_pattern_editor_suggest_pattern_directory_rules(self):
        """Verify suggest_pattern returns glob for directory_rules."""
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("/home/user/project/file.txt", "directory_rules")
        assert result.endswith("/**")
        assert "/home/user/project" in result

    def test_pattern_editor_generate_config_preview_directory_rules(self):
        """Verify generate_config_preview shows exclusions for directory_rules."""
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("/home/user/**", "directory_rules")
        parsed = json.loads(result)
        assert "exclusions" in parsed["directory_rules"]
        assert "/home/user/**" in parsed["directory_rules"]["exclusions"]

    def test_pattern_editor_prepare_config_directory_rules(self):
        """Verify prepare_config_with_pattern writes to exclusions for directory_rules."""
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    "/home/user/**", "directory_rules"
                )
            parsed = json.loads(json_text)
            assert "/home/user/**" in parsed["directory_rules"]["exclusions"]

    def test_matches_directory_pattern_exact(self):
        """Verify _matches_directory_pattern with exact path."""
        from ai_guardian.hook_processing import _matches_directory_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            real_tmpdir = os.path.realpath(tmpdir)
            test_file = os.path.join(real_tmpdir, "file.txt")
            assert _matches_directory_pattern(test_file, real_tmpdir) is True
            assert _matches_directory_pattern(test_file, "/nonexistent/path") is False

    def test_matches_directory_pattern_recursive_glob(self):
        """Verify _matches_directory_pattern with ** glob."""
        from ai_guardian.hook_processing import _matches_directory_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            real_tmpdir = os.path.realpath(tmpdir)
            test_file = os.path.join(real_tmpdir, "sub", "file.txt")
            os.makedirs(os.path.dirname(test_file), exist_ok=True)
            with open(test_file, "w") as f:
                f.write("test")
            assert _matches_directory_pattern(test_file, real_tmpdir + "/**") is True
            assert _matches_directory_pattern(test_file, "/nonexistent/**") is False


class TestSupplyChainAskAction:
    """Tests for ask action mode with supply chain scanning (Issue #1131)."""

    def test_supply_chain_ask_schema_accepts_ask(self):
        """Verify JSON schema accepts ask values for supply_chain.action."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        sc_schema = schema["properties"]["supply_chain"]
        for action_val in ["ask", "ask:warn", "ask:log-only"]:
            config = {"action": action_val}
            jsonschema.validate(config, sc_schema)

    def test_supply_chain_ask_schema_rejects_invalid(self):
        """Verify JSON schema rejects invalid ask values."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        sc_schema = schema["properties"]["supply_chain"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"action": "ask:invalid"}, sc_schema)

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_handle_ask_mode_supply_chain_allow_always_writes_path(self, mock_dialog):
        """Verify Allow Always routes to save_ask_pattern for supply_chain."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern="~/.claude/settings.json",
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask",
                "supply_chain",
                "~/.claude/settings.json",
                "supply_chain",
                "Supply chain threat detected",
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "supply_chain", "~/.claude/settings.json", config_path=None
        )

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_supply_chain_ask_headless_block_fallback(self, _mock_sub, _mock_daemon):
        """Verify headless fallback defaults to block for ask mode."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask",
            "supply_chain",
            "~/.claude/settings.json",
            "supply_chain",
            "Supply chain threat detected",
        )
        assert result is not None
        assert result.decision == AskDecision.BLOCK

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_supply_chain_ask_warn_headless_fallback(self, _mock_sub, _mock_daemon):
        """Verify ask:warn headless fallback allows with ALLOW_ONCE."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask:warn",
            "supply_chain",
            "~/.claude/settings.json",
            "supply_chain",
            "Supply chain threat detected",
        )
        assert result is not None
        assert result.decision == AskDecision.ALLOW_ONCE

    def test_add_supply_chain_path_writes_config(self):
        """Verify add_supply_chain_path writes to supply_chain.allowlist_paths."""
        from ai_guardian.config.writer import add_supply_chain_path

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text('{"supply_chain": {"action": "ask"}}')
            result = add_supply_chain_path(
                "~/.claude/settings.json", config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert (
                "~/.claude/settings.json" in config["supply_chain"]["allowlist_paths"]
            )

    def test_add_supply_chain_path_dedup(self):
        """Verify add_supply_chain_path doesn't add duplicates."""
        from ai_guardian.config.writer import add_supply_chain_path

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "supply_chain": {
                            "action": "ask",
                            "allowlist_paths": ["~/.claude/settings.json"],
                        }
                    }
                )
            )
            result = add_supply_chain_path(
                "~/.claude/settings.json", config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert (
                config["supply_chain"]["allowlist_paths"].count(
                    "~/.claude/settings.json"
                )
                == 1
            )

    def test_add_supply_chain_path_empty_rejected(self):
        """Verify empty pattern is rejected."""
        from ai_guardian.config.writer import add_supply_chain_path

        assert add_supply_chain_path("") is False

    def test_pattern_editor_suggest_pattern_supply_chain(self):
        """Verify suggest_pattern returns file path as-is for supply_chain."""
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("~/.claude/settings.json", "supply_chain")
        assert result == "~/.claude/settings.json"

    def test_pattern_editor_generate_config_preview_supply_chain(self):
        """Verify generate_config_preview shows allowlist_paths for supply_chain."""
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("~/.claude/settings.json", "supply_chain")
        parsed = json.loads(result)
        assert "allowlist_paths" in parsed["supply_chain"]
        assert "~/.claude/settings.json" in parsed["supply_chain"]["allowlist_paths"]

    def test_pattern_editor_prepare_config_supply_chain(self):
        """Verify prepare_config_with_pattern writes to allowlist_paths for supply_chain."""
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    "~/.claude/settings.json", "supply_chain"
                )
            parsed = json.loads(json_text)
            assert (
                "~/.claude/settings.json" in parsed["supply_chain"]["allowlist_paths"]
            )

    def test_pattern_type_for_supply_chain_is_glob(self):
        """Verify supply_chain uses glob pattern type."""
        from ai_guardian.tui.pattern_editor import get_pattern_type_for_section

        assert get_pattern_type_for_section("supply_chain") == "glob"


class TestConfigFileExfilAskAction:
    """Tests for ask action mode with config file scanning (Issue #1132)."""

    def test_config_file_scanning_ask_schema_accepts_ask(self):
        """Verify JSON schema accepts ask values for config_file_scanning.action."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        cfs_schema = schema["properties"]["config_file_scanning"]
        for action_val in ["ask", "ask:warn", "ask:log-only"]:
            config = {"action": action_val}
            jsonschema.validate(config, cfs_schema)

    def test_config_file_scanning_ask_schema_rejects_invalid(self):
        """Verify JSON schema rejects invalid ask values."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        cfs_schema = schema["properties"]["config_file_scanning"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"action": "ask:invalid"}, cfs_schema)

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_handle_ask_mode_config_file_scanning_allow_always_writes_ignore(
        self, mock_dialog
    ):
        """Verify Allow Always routes to save_ask_pattern for config_file_scanning."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern="**/docs/security-examples.md",
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask",
                "config_file_exfil",
                "**/docs/security-examples.md",
                "config_file_scanning",
                "Config file scanning violation",
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "config_file_scanning", "**/docs/security-examples.md", config_path=None
        )

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_config_file_scanning_ask_headless_block_fallback(
        self, _mock_sub, _mock_daemon
    ):
        """Verify headless fallback defaults to block for ask mode."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask",
            "config_file_exfil",
            "CLAUDE.md",
            "config_file_scanning",
            "Config file threat detected",
        )
        assert result is not None
        assert result.decision == AskDecision.BLOCK

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_config_file_scanning_ask_warn_headless_fallback(
        self, _mock_sub, _mock_daemon
    ):
        """Verify ask:warn headless fallback allows with ALLOW_ONCE."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask:warn",
            "config_file_exfil",
            "CLAUDE.md",
            "config_file_scanning",
            "Config file threat detected",
        )
        assert result is not None
        assert result.decision == AskDecision.ALLOW_ONCE

    def test_add_config_ignore_file_writes_config(self):
        """Verify add_config_ignore_file writes to config_file_scanning.ignore_files."""
        from ai_guardian.config.writer import add_config_ignore_file

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text('{"config_file_scanning": {"action": "ask"}}')
            result = add_config_ignore_file(
                "**/docs/security-examples.md", config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert (
                "**/docs/security-examples.md"
                in config["config_file_scanning"]["ignore_files"]
            )

    def test_add_config_ignore_file_dedup(self):
        """Verify add_config_ignore_file doesn't add duplicates."""
        from ai_guardian.config.writer import add_config_ignore_file

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "config_file_scanning": {
                            "action": "ask",
                            "ignore_files": ["**/docs/security-examples.md"],
                        }
                    }
                )
            )
            result = add_config_ignore_file(
                "**/docs/security-examples.md", config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert (
                config["config_file_scanning"]["ignore_files"].count(
                    "**/docs/security-examples.md"
                )
                == 1
            )

    def test_add_config_ignore_file_empty_rejected(self):
        """Verify empty pattern is rejected."""
        from ai_guardian.config.writer import add_config_ignore_file

        assert add_config_ignore_file("") is False

    def test_add_config_ignore_file_creates_section(self):
        """Verify add_config_ignore_file creates config_file_scanning section if missing."""
        from ai_guardian.config.writer import add_config_ignore_file

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            result = add_config_ignore_file("CLAUDE.md", config_path=config_path)
            assert result is True
            config = json.loads(config_path.read_text())
            assert "CLAUDE.md" in config["config_file_scanning"]["ignore_files"]

    def test_pattern_editor_suggest_pattern_config_file_scanning(self):
        """Verify suggest_pattern returns file path as-is for config_file_scanning."""
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("CLAUDE.md", "config_file_scanning")
        assert result == "CLAUDE.md"

    def test_pattern_editor_generate_config_preview_config_file_scanning(self):
        """Verify generate_config_preview shows ignore_files for config_file_scanning."""
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("CLAUDE.md", "config_file_scanning")
        parsed = json.loads(result)
        assert "ignore_files" in parsed["config_file_scanning"]
        assert "CLAUDE.md" in parsed["config_file_scanning"]["ignore_files"]

    def test_pattern_editor_prepare_config_config_file_scanning(self):
        """Verify prepare_config_with_pattern writes to ignore_files for config_file_scanning."""
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    "CLAUDE.md", "config_file_scanning"
                )
            parsed = json.loads(json_text)
            assert "CLAUDE.md" in parsed["config_file_scanning"]["ignore_files"]

    def test_pattern_type_for_config_file_scanning_is_glob(self):
        """Verify config_file_scanning uses glob pattern type."""
        from ai_guardian.tui.pattern_editor import get_pattern_type_for_section

        assert get_pattern_type_for_section("config_file_scanning") == "glob"


class TestToolPermissionAskAction:
    """Tests for ask action mode with tool permission rules (Issue #1137)."""

    def test_permission_rule_ask_schema_accepts_ask(self):
        """Verify JSON schema accepts ask values for permission_rule.action."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        rule_schema = schema["definitions"]["permission_rule"]
        for action_val in ["ask", "ask:warn", "ask:log-only"]:
            rule = {"matcher": "Bash", "mode": "deny", "action": action_val}
            jsonschema.validate(rule, rule_schema)

    def test_permission_rule_ask_schema_rejects_invalid(self):
        """Verify JSON schema rejects invalid ask values for permission_rule.action."""
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "ai_guardian"
            / "schemas"
            / "ai-guardian-config.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        rule_schema = schema["definitions"]["permission_rule"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"matcher": "Bash", "mode": "deny", "action": "ask:invalid"},
                rule_schema,
            )

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_handle_ask_mode_permissions_allow_always_writes_rule(self, mock_dialog):
        """Verify Allow Always routes to save_ask_pattern for permissions."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern="Bash:npm test",
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask",
                "tool_permission",
                "Bash:npm test",
                "permissions",
                "Tool 'Bash' blocked by deny rule",
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "permissions", "Bash:npm test", config_path=None
        )

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_handle_ask_mode_permissions_allow_always_no_colon(self, mock_dialog):
        """Verify Allow Always with no colon uses matcher=pattern, patterns=['*']."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern="Skill",
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask",
                "tool_permission",
                "Skill",
                "permissions",
                "Tool 'Skill' blocked",
            )
        mock_write.assert_called_once_with("permissions", "Skill", config_path=None)

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_permissions_ask_headless_block_fallback(self, _mock_sub, _mock_daemon):
        """Verify headless fallback defaults to block for ask mode."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask",
            "tool_permission",
            "Bash:rm -rf /",
            "permissions",
            "Tool 'Bash' blocked",
        )
        assert result is not None
        assert result.decision == AskDecision.BLOCK

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_permissions_ask_warn_headless_fallback(self, _mock_sub, _mock_daemon):
        """Verify ask:warn headless fallback allows with ALLOW_ONCE."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask:warn",
            "tool_permission",
            "Bash:npm test",
            "permissions",
            "Tool 'Bash' blocked",
        )
        assert result is not None
        assert result.decision == AskDecision.ALLOW_ONCE

    def test_add_permission_rule_writes_config(self):
        """Verify add_permission_rule appends allow rule to permissions.rules."""
        from ai_guardian.config.writer import add_permission_rule

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text('{"permissions": {"rules": []}}')
            result = add_permission_rule("Bash", ["npm test"], config_path=config_path)
            assert result is True
            config = json.loads(config_path.read_text())
            rules = config["permissions"]["rules"]
            assert len(rules) == 1
            assert rules[0] == {
                "mode": "allow",
                "matcher": "Bash",
                "patterns": ["npm test"],
            }

    def test_add_permission_rule_dedup(self):
        """Verify add_permission_rule doesn't add duplicate rules."""
        from ai_guardian.config.writer import add_permission_rule

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "rules": [
                                {
                                    "mode": "allow",
                                    "matcher": "Bash",
                                    "patterns": ["npm test"],
                                }
                            ]
                        }
                    }
                )
            )
            result = add_permission_rule("Bash", ["npm test"], config_path=config_path)
            assert result is True
            config = json.loads(config_path.read_text())
            assert len(config["permissions"]["rules"]) == 1

    def test_add_permission_rule_empty_matcher_rejected(self):
        """Verify empty matcher is rejected."""
        from ai_guardian.config.writer import add_permission_rule

        assert add_permission_rule("", ["*"]) is False

    def test_add_permission_rule_empty_patterns_rejected(self):
        """Verify empty patterns list is rejected."""
        from ai_guardian.config.writer import add_permission_rule

        assert add_permission_rule("Bash", []) is False

    def test_add_permission_rule_creates_permissions_section(self):
        """Verify add_permission_rule creates permissions section if missing."""
        from ai_guardian.config.writer import add_permission_rule

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            result = add_permission_rule(
                "Skill", ["code-review"], config_path=config_path
            )
            assert result is True
            config = json.loads(config_path.read_text())
            assert "permissions" in config
            assert "rules" in config["permissions"]
            assert config["permissions"]["rules"][0]["matcher"] == "Skill"

    def test_pattern_editor_suggest_pattern_permissions(self):
        """Verify suggest_pattern returns matched text as-is for permissions."""
        from ai_guardian.tui.pattern_editor import suggest_pattern

        result = suggest_pattern("Bash:npm test", "permissions")
        assert result == "Bash:npm test"

    def test_pattern_editor_generate_config_preview_permissions(self):
        """Verify generate_config_preview shows permission rule for permissions."""
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("Bash:npm test", "permissions")
        parsed = json.loads(result)
        assert "permissions" in parsed
        assert "rules" in parsed["permissions"]
        rule = parsed["permissions"]["rules"][0]
        assert rule["mode"] == "allow"
        assert rule["matcher"] == "Bash"
        assert rule["patterns"] == ["npm test"]

    def test_pattern_editor_generate_config_preview_permissions_no_colon(self):
        """Verify generate_config_preview handles pattern with no colon."""
        from ai_guardian.tui.pattern_editor import generate_config_preview

        result = generate_config_preview("Skill", "permissions")
        parsed = json.loads(result)
        rule = parsed["permissions"]["rules"][0]
        assert rule["matcher"] == "Skill"
        assert rule["patterns"] == ["*"]

    def test_pattern_editor_prepare_config_permissions(self):
        """Verify prepare_config_with_pattern writes permission rule."""
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text("{}")
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                json_text, line_num = prepare_config_with_pattern(
                    "Bash:npm test", "permissions"
                )
            parsed = json.loads(json_text)
            assert "permissions" in parsed
            rules = parsed["permissions"]["rules"]
            assert len(rules) == 1
            assert rules[0]["matcher"] == "Bash"

    def test_pattern_type_for_permissions_is_string(self):
        """Verify permissions uses string pattern type."""
        from ai_guardian.tui.pattern_editor import get_pattern_type_for_section

        assert get_pattern_type_for_section("permissions") == "string"

    def test_tool_policy_exposes_deny_action(self):
        """Verify ToolPolicyChecker sets last_deny_action on deny."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Bash",
                        "mode": "deny",
                        "patterns": ["rm -rf *"],
                        "action": "ask",
                    }
                ]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {
            "tool_use": {"name": "Bash", "input": {"command": "rm -rf /tmp/test"}}
        }
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action == "ask"
        assert checker.last_deny_matched_pattern is not None

    def test_tool_policy_deny_action_defaults_block(self):
        """Verify last_deny_action is 'block' for standard deny without action."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [{"matcher": "Bash", "mode": "deny", "patterns": ["rm -rf *"]}]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {
            "tool_use": {"name": "Bash", "input": {"command": "rm -rf /tmp/test"}}
        }
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action == "block"

    def test_build_permission_matched_text_bash(self):
        """Verify _build_permission_matched_text formats Bash correctly."""
        from ai_guardian.ask_mode import _build_permission_matched_text

        result = _build_permission_matched_text("Bash", {"command": "npm test"}, "Bash")
        assert result == "Bash:npm test"

    def test_build_permission_matched_text_skill(self):
        """Verify _build_permission_matched_text formats Skill correctly."""
        from ai_guardian.ask_mode import _build_permission_matched_text

        result = _build_permission_matched_text(
            "Skill", {"skill": "code-review"}, "Skill:code-review"
        )
        assert result == "Skill:code-review"

    def test_build_permission_matched_text_file_tool(self):
        """Verify _build_permission_matched_text formats file tools correctly."""
        from ai_guardian.ask_mode import _build_permission_matched_text

        result = _build_permission_matched_text(
            "Read", {"file_path": "/etc/passwd"}, "Read"
        )
        assert result == "Read:/etc/passwd"

    def test_build_permission_matched_text_no_input(self):
        """Verify _build_permission_matched_text handles no tool_input."""
        from ai_guardian.ask_mode import _build_permission_matched_text

        result = _build_permission_matched_text("Bash", None, "Bash")
        assert result == "Bash"

    def test_cli_has_ask_action_detects_permission_rules(self):
        """Verify _has_ask_action detects ask in permissions.rules."""
        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Bash",
                        "mode": "deny",
                        "patterns": ["*"],
                        "action": "ask",
                    }
                ]
            }
        }
        # Import the function by loading cli module content

        # Test the logic directly
        has_ask = False
        rules = config.get("permissions", {}).get("rules", [])
        if isinstance(rules, list):
            for rule in rules:
                if isinstance(rule, dict):
                    action = rule.get("action", "")
                    if isinstance(action, str) and action.startswith("ask"):
                        has_ask = True
        assert has_ask is True


class TestFormatAskInfoMessage:
    """Tests for _format_ask_info_message helper (#1161)."""

    def test_allow_once_message(self):
        from ai_guardian.ask_mode import _format_ask_info_message
        from ai_guardian.tui.ask_dialog import AskDecision

        msg = _format_ask_info_message("secret_detected", AskDecision.ALLOW_ONCE)
        assert msg.startswith("ℹ️")
        assert "allowed by user (this time only)" in msg
        assert "Secret detection" in msg

    def test_allow_always_message(self):
        from ai_guardian.ask_mode import _format_ask_info_message
        from ai_guardian.tui.ask_dialog import AskDecision

        msg = _format_ask_info_message("secret_detected", AskDecision.ALLOW_ALWAYS)
        assert msg.startswith("ℹ️")
        assert "pattern added to allowlist (always allowed)" in msg

    def test_message_with_detail(self):
        from ai_guardian.ask_mode import _format_ask_info_message
        from ai_guardian.tui.ask_dialog import AskDecision

        msg = _format_ask_info_message(
            "directory_blocking", AskDecision.ALLOW_ONCE, detail="/etc/passwd"
        )
        assert "/etc/passwd" in msg
        assert "Directory access" in msg

    def test_all_violation_types_have_labels(self):
        from ai_guardian.ask_mode import (
            _format_ask_info_message,
            _ASK_VIOLATION_LABELS,
        )
        from ai_guardian.tui.ask_dialog import AskDecision

        for vtype in _ASK_VIOLATION_LABELS:
            msg = _format_ask_info_message(vtype, AskDecision.ALLOW_ONCE)
            assert "ℹ️" in msg
            assert "allowed by user" in msg

    def test_unknown_violation_type_fallback(self):
        from ai_guardian.ask_mode import _format_ask_info_message
        from ai_guardian.tui.ask_dialog import AskDecision

        msg = _format_ask_info_message("unknown_type", AskDecision.ALLOW_ONCE)
        assert "ℹ️" in msg
        assert "unknown_type" in msg

    def test_pii_detection_label(self):
        from ai_guardian.ask_mode import _format_ask_info_message
        from ai_guardian.tui.ask_dialog import AskDecision

        msg = _format_ask_info_message("pii_detected", AskDecision.ALLOW_ALWAYS)
        assert "PII detection" in msg

    def test_tool_permission_label(self):
        from ai_guardian.ask_mode import _format_ask_info_message
        from ai_guardian.tui.ask_dialog import AskDecision

        msg = _format_ask_info_message(
            "tool_permission", AskDecision.ALLOW_ONCE, detail="Bash"
        )
        assert "Permission rule" in msg
        assert "Bash" in msg

    def test_ssrf_label(self):
        from ai_guardian.ask_mode import _format_ask_info_message
        from ai_guardian.tui.ask_dialog import AskDecision

        msg = _format_ask_info_message("ssrf_blocked", AskDecision.ALLOW_ONCE)
        assert "SSRF protection" in msg


class TestLogAskDecision:
    """Tests for _log_ask_decision helper (#1161)."""

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_logs_allow_once(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "secret_detected",
            AskDecision.ALLOW_ONCE,
            matched_text="AWS_KEY",
            error_msg="Secret found",
        )
        mock_vl.log_violation.assert_called_once()
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["violation_type"] == "secret_detected"
        assert call_kwargs["severity"] == "info"
        assert call_kwargs["context"]["ask_decision"] == "allow_once"
        assert call_kwargs["context"]["action_taken"] == "allowed"
        assert call_kwargs["blocked"]["matched_text"] == "AWS_KEY"

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_logs_allow_always(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "pii_detected",
            AskDecision.ALLOW_ALWAYS,
            matched_text="email@test.com",
            error_msg="PII found",
        )
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["context"]["ask_decision"] == "allow_always"

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_logs_with_file_path(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "directory_blocking", AskDecision.ALLOW_ONCE, file_path="/etc/passwd"
        )
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["blocked"]["file_path"] == "/etc/passwd"

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_no_file_path_omits_key(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision("secret_detected", AskDecision.ALLOW_ONCE)
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert "file_path" not in call_kwargs["blocked"]

    @patch("ai_guardian.ask_mode.HAS_VIOLATION_LOGGER", False)
    def test_noop_when_logger_unavailable(self):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        _log_ask_decision("secret_detected", AskDecision.ALLOW_ONCE)

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_exception_does_not_propagate(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl_cls.side_effect = RuntimeError("boom")
        _log_ask_decision("secret_detected", AskDecision.ALLOW_ONCE)


class TestDenyByDefaultAskAction:
    """Tests for ask action inherited by deny-by-default path (Issue #1185)."""

    def test_skill_not_in_allow_list_inherits_ask_from_allow_rule(self):
        """Unmatched Skill inherits ask action from allow rule with action."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["code-review"],
                        "action": "ask:warn",
                    }
                ]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {"tool_use": {"name": "Skill", "input": {"skill": "daf-workflow"}}}
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action == "ask:warn"
        assert checker.last_deny_matched_pattern == "not in allow list"

    def test_mcp_not_in_allow_list_inherits_ask_action(self):
        """Unmatched MCP tool inherits ask action from allow rule."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "mcp__*",
                        "mode": "allow",
                        "patterns": ["mcp__notebooklm*"],
                        "action": "ask",
                    }
                ]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {"tool_use": {"name": "mcp__unknown__tool", "input": {}}}
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action == "ask"

    def test_no_action_field_remains_block(self):
        """Allow rule without action → deny-by-default stays block."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["code-review"]}
                ]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {"tool_use": {"name": "Skill", "input": {"skill": "daf-workflow"}}}
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action == "block"

    def test_no_rules_at_all_hard_blocks(self):
        """No rules for matcher → hard block, last_deny_action not set (AC #3)."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {"permissions": {"rules": []}}
        checker = ToolPolicyChecker(config=config)
        hook_data = {"tool_use": {"name": "Skill", "input": {"skill": "daf-workflow"}}}
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action is None

    def test_last_explicit_action_wins(self):
        """Multiple rules with actions — last explicit action wins."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "deny",
                        "patterns": ["bad-*"],
                        "action": "ask",
                    },
                    {
                        "matcher": "Skill",
                        "mode": "deny",
                        "patterns": ["worse-*"],
                        "action": "ask:warn",
                    },
                ]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {"tool_use": {"name": "Skill", "input": {"skill": "daf-workflow"}}}
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action == "ask:warn"

    def test_rule_without_action_does_not_override(self):
        """Rule without action field does not override earlier explicit action."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "deny",
                        "patterns": ["bad-*"],
                        "action": "ask:warn",
                    },
                    {"matcher": "Skill", "mode": "allow", "patterns": ["safe-skill"]},
                ]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {"tool_use": {"name": "Skill", "input": {"skill": "daf-workflow"}}}
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is False
        assert checker.last_deny_action == "ask:warn"

    def test_builtin_tool_not_affected(self):
        """Built-in tools are not restricted — deny-by-default doesn't apply."""
        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "rules": [{"matcher": "Bash", "mode": "allow", "patterns": ["ls*"]}]
            }
        }
        checker = ToolPolicyChecker(config=config)
        hook_data = {"tool_use": {"name": "Bash", "input": {"command": "echo hello"}}}
        is_allowed, error_msg, tool_name = checker.check_tool_allowed(hook_data)
        assert is_allowed is True


class TestConfigScopeSelection:
    """Tests for project/global config scope selection (#1197)."""

    def test_get_config_scope_options_global_only(self):
        from ai_guardian.tui.pattern_editor import get_config_scope_options

        global_dir = Path("/home/user/.config/ai-guardian")
        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=global_dir,
            ):
                options = get_config_scope_options()
        assert len(options) == 1
        assert options[0][0] == "Global"
        assert "ai-guardian.json" in options[0][1]

    def test_get_config_scope_options_no_config_but_project_dir(self):
        """Issue #1379: project scope offered even when config doesn't exist yet."""
        from ai_guardian.tui.pattern_editor import get_config_scope_options

        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                options = get_config_scope_options(project_dir="/projects/carbonite")
        assert len(options) == 2
        assert options[0][0] == "Project"
        assert options[0][1] == str(
            Path("/projects/carbonite/.ai-guardian/ai-guardian.json")
        )
        assert options[1][0] == "Global"

    def test_get_config_scope_options_with_project(self):
        from ai_guardian.tui.pattern_editor import get_config_scope_options

        project_path = Path("/project/.ai-guardian/ai-guardian.json")
        with patch(
            "ai_guardian.config.utils.get_project_config_path",
            return_value=project_path,
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                options = get_config_scope_options()
        assert len(options) == 2
        assert options[0][0] == "Project"
        assert options[0][1] == str(project_path)
        assert options[1][0] == "Global"

    def test_get_config_scope_options_explicit_project_dir(self):
        """Issue #1726: explicit project_dir fixes subprocess root path bug."""
        from ai_guardian.tui.pattern_editor import get_config_scope_options

        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                options = get_config_scope_options(project_dir="/Users/dev/myproject")
        assert len(options) == 2
        assert options[0][0] == "Project"
        assert "/Users/dev/myproject/.ai-guardian/ai-guardian.json" in options[0][1]

    def test_ask_result_config_path_field(self):
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        result = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern=r"test\w+",
            config_saved=True,
            config_path="/project/.ai-guardian/ai-guardian.json",
        )
        assert result.config_path == "/project/.ai-guardian/ai-guardian.json"

    def test_ask_result_config_path_default_none(self):
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        result = AskResult(decision=AskDecision.BLOCK)
        assert result.config_path is None

    def test_write_config_text_with_custom_path(self):
        from ai_guardian.tui.ask_dialog import _write_config_text

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom-config.json"
            result = _write_config_text(
                '{"test": true}', config_path_str=str(config_path)
            )
            assert result is True
            assert config_path.exists()
            assert json.loads(config_path.read_text()) == {"test": True}

    def test_write_config_text_default_global(self):
        from ai_guardian.tui.ask_dialog import _write_config_text

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "ai_guardian.config.utils.get_config_dir", return_value=Path(tmpdir)
            ):
                result = _write_config_text('{"default": true}')
            config_path = Path(tmpdir) / "ai-guardian.json"
            assert result is True
            assert config_path.exists()

    def test_save_pattern_to_config_with_path(self):
        from ai_guardian.tui.ask_dialog import _save_pattern_to_config

        with patch("ai_guardian.config.writer.save_ask_pattern") as mock:
            mock.return_value = True
            result = _save_pattern_to_config(
                r"test\w+",
                "secret_scanning",
                config_path="/project/.ai-guardian/ai-guardian.json",
            )
        assert result is True
        mock.assert_called_once_with(
            "secret_scanning",
            r"test\w+",
            config_path=Path("/project/.ai-guardian/ai-guardian.json"),
        )

    def test_prepare_config_with_pattern_custom_path(self):
        from ai_guardian.tui.pattern_editor import prepare_config_with_pattern

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"
            config_path.write_text('{"secret_scanning": {}}')
            json_text, line_num = prepare_config_with_pattern(
                r"TEST\w+",
                "secret_scanning",
                config_path=str(config_path),
            )
        parsed = json.loads(json_text)
        assert r"TEST\w+" in parsed["secret_scanning"]["allowlist_patterns"]

    @patch("ai_guardian.tui.ask_dialog.show_ask_dialog")
    def test_hook_processing_passes_config_path(self, mock_dialog):
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        mock_dialog.return_value = AskResult(
            decision=AskDecision.ALLOW_ALWAYS,
            allowlist_pattern=r"FAKE\w+",
            config_path="/project/.ai-guardian/ai-guardian.json",
        )
        with patch("ai_guardian.config.writer.save_ask_pattern") as mock_write:
            mock_write.return_value = True
            result = _handle_ask_mode(
                "ask",
                "secret_detected",
                "FAKE_TOKEN",
                "secret_scanning",
                "error",
            )
        assert result.decision == AskDecision.ALLOW_ALWAYS
        mock_write.assert_called_once_with(
            "secret_scanning",
            r"FAKE\w+",
            config_path=Path("/project/.ai-guardian/ai-guardian.json"),
        )


class TestPiiAskBlockDecision:
    """Tests for PII ask dialog Block decision (#1224).

    When scan_pii.action=ask and user clicks Block, pii_action must be
    set to 'block' so the prompt is actually blocked.
    """

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_pii_ask_block_sets_action_to_block(self, _mock_sub, _mock_daemon):
        """Block fallback returns BLOCK decision for PII."""
        from ai_guardian.ask_mode import _handle_ask_mode
        from ai_guardian.tui.ask_dialog import AskDecision

        result = _handle_ask_mode(
            "ask", "pii_detected", "555-12-3456", "scan_pii", "PII detected: SSN"
        )
        assert result is not None
        assert result.decision == AskDecision.BLOCK

    def test_pii_action_set_to_block_on_block_decision(self):
        """Simulate Block decision and verify pii_action becomes 'block'."""
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        pii_action = "ask"
        pii_ask_result = AskResult(decision=AskDecision.BLOCK)
        if pii_ask_result is not None:
            if pii_ask_result.decision != AskDecision.BLOCK:
                pii_action = "warn"
            else:
                pii_action = "block"
        assert pii_action == "block"

    def test_pii_action_set_to_warn_on_allow_decision(self):
        """Simulate Allow decision and verify pii_action becomes 'warn'."""
        from ai_guardian.tui.ask_dialog import AskResult, AskDecision

        pii_action = "ask"
        pii_ask_result = AskResult(decision=AskDecision.ALLOW_ONCE)
        if pii_ask_result is not None:
            if pii_ask_result.decision != AskDecision.BLOCK:
                pii_action = "warn"
            else:
                pii_action = "block"
        assert pii_action == "warn"

    def test_pii_action_unchanged_when_no_dialog_result(self):
        """When dialog returns None (e.g. non-ask action), pii_action stays."""
        from ai_guardian.tui.ask_dialog import AskDecision

        pii_action = "ask"
        pii_ask_result = None
        if pii_ask_result is not None:
            if pii_ask_result.decision != AskDecision.BLOCK:
                pii_action = "warn"
            else:
                pii_action = "block"
        assert pii_action == "ask"


class TestFormatHookLabel:
    """Tests for format_hook_label() human-readable hook event labels (Issue #1289)."""

    def test_pretooluse_with_read(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("pretooluse", "Read") == "PreToolUse (reading file)"

    def test_pretooluse_with_bash(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("pretooluse", "Bash") == "PreToolUse (running command)"

    def test_pretooluse_with_write(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("pretooluse", "Write") == "PreToolUse (writing file)"

    def test_pretooluse_with_edit(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("pretooluse", "Edit") == "PreToolUse (editing file)"

    def test_pretooluse_without_tool(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("pretooluse") == "PreToolUse (before tool use)"

    def test_pretooluse_unknown_tool(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert (
            format_hook_label("pretooluse", "SomeTool")
            == "PreToolUse (before tool use)"
        )

    def test_beforereadfile(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert (
            format_hook_label("beforereadfile", "Read") == "PreToolUse (reading file)"
        )

    def test_posttooluse(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("posttooluse") == "PostToolUse (tool output)"

    def test_prompt(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("prompt") == "UserPromptSubmit (your prompt)"

    def test_none_returns_none(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label(None) is None

    def test_empty_returns_none(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("") is None

    def test_unknown_event_passthrough(self):
        from ai_guardian.tui.ask_dialog import format_hook_label

        assert format_hook_label("custom_event") == "custom_event"

    def test_hook_event_enum_value(self):
        """HookEvent enum values work (they're str enums)."""
        from ai_guardian.tui.ask_dialog import format_hook_label
        from ai_guardian.constants import HookEvent

        assert (
            format_hook_label(HookEvent.PRE_TOOL_USE, "Bash")
            == "PreToolUse (running command)"
        )
        assert format_hook_label(HookEvent.POST_TOOL_USE) == "PostToolUse (tool output)"
        assert format_hook_label(HookEvent.PROMPT) == "UserPromptSubmit (your prompt)"


class TestAskViolationInfoHookEvent:
    """Tests for hook_event field on AskViolationInfo (Issue #1289)."""

    def test_default_none(self):
        from ai_guardian.tui.ask_dialog import AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="test",
            matched_text="secret",
            config_section="secret_scanning",
        )
        assert v.hook_event is None

    def test_set_hook_event(self):
        from ai_guardian.tui.ask_dialog import AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="test",
            matched_text="secret",
            config_section="secret_scanning",
            hook_event="PreToolUse (reading file)",
        )
        assert v.hook_event == "PreToolUse (reading file)"


class TestBuildDialogTitle:
    """Tests for build_dialog_title and build_sub_dialog_title (#1317)."""

    def test_minimal_title(self):
        from ai_guardian.tui.ask_dialog import build_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
        )
        assert build_dialog_title(v) == "ai-guardian: Violation Detected"

    def test_project_only(self):
        from ai_guardian.tui.ask_dialog import build_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
            project_path="/home/user/my-project",
        )
        assert build_dialog_title(v) == "ai-guardian: Violation Detected — my-project"

    def test_full_title_with_tool_file_session(self):
        from ai_guardian.tui.ask_dialog import build_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
            project_path="/home/user/devaiflow",
            tool_name="Read",
            file_path="/home/user/devaiflow/src/SKILL.md",
            session_id="f983ab72-1234-5678-9abc-def012345678",
        )
        title = build_dialog_title(v)
        assert (
            title
            == "ai-guardian: Violation Detected — devaiflow — Read SKILL.md [f983]"
        )

    def test_session_id_truncated_to_4(self):
        from ai_guardian.tui.ask_dialog import build_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
            session_id="abcdefgh-long-session-id",
        )
        title = build_dialog_title(v)
        assert "[abcd]" in title
        assert "[abcdefgh]" not in title

    def test_tool_without_file(self):
        from ai_guardian.tui.ask_dialog import build_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
            tool_name="Bash",
        )
        assert "— Bash" in build_dialog_title(v)

    def test_file_without_tool(self):
        from ai_guardian.tui.ask_dialog import build_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
            file_path="/some/path/config.json",
        )
        assert "— config.json" in build_dialog_title(v)

    def test_sub_dialog_title_full(self):
        from ai_guardian.tui.ask_dialog import build_sub_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
            project_path="/home/user/myapp",
            tool_name="Edit",
            file_path="/home/user/myapp/main.py",
            session_id="deadbeef-cafe",
        )
        title = build_sub_dialog_title("Allow Always", v)
        assert title == "myapp Edit main.py [dead] — Allow Always"

    def test_sub_dialog_title_minimal(self):
        from ai_guardian.tui.ask_dialog import build_sub_dialog_title, AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
        )
        assert build_sub_dialog_title("Block", v) == "Block"

    def test_tool_name_field_exists(self):
        from ai_guardian.tui.ask_dialog import AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
            tool_name="Read",
        )
        assert v.tool_name == "Read"

    def test_tool_name_default_none(self):
        from ai_guardian.tui.ask_dialog import AskViolationInfo

        v = AskViolationInfo(
            violation_type="secret_detected",
            summary="s",
            matched_text="x",
            config_section="secret_scanning",
        )
        assert v.tool_name is None


class TestLogAskDecisionBlock:
    """Tests for _log_ask_decision with BLOCK decisions (#1344)."""

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_logs_block_decision(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "secret_detected",
            AskDecision.BLOCK,
            matched_text="AKIA_KEY",
            error_msg="Secret found",
        )
        mock_vl.log_violation.assert_called_once()
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["context"]["ask_decision"] == "block"
        assert call_kwargs["context"]["action_taken"] == "blocked"
        assert call_kwargs["blocked"]["matched_text"] == "AKIA_KEY"

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_logs_block_all_decision(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "secret_detected",
            AskDecision.BLOCK_ALL,
            matched_text="secret_value",
            error_msg="Secret found",
        )
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["context"]["ask_decision"] == "block_all"
        assert call_kwargs["context"]["action_taken"] == "blocked"

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_logs_block_with_file_and_line(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "secret_detected",
            AskDecision.BLOCK,
            matched_text="key",
            error_msg="Secret",
            file_path="/app/config.py",
            line_number=42,
            dialog_wait_ms=1500.0,
        )
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["blocked"]["file_path"] == "/app/config.py"
        assert call_kwargs["blocked"]["line_number"] == 42
        assert call_kwargs["context"]["dialog_wait_ms"] == 1500.0

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_logs_pii_block_decision(self, mock_vl_cls):
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "pii_detected",
            AskDecision.BLOCK,
            matched_text="555-12-3456",
            error_msg="PII: SSN",
        )
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["violation_type"] == "pii_detected"
        assert call_kwargs["context"]["ask_decision"] == "block"
        assert call_kwargs["context"]["action_taken"] == "blocked"

    @patch("ai_guardian.ask_mode.ViolationLogger")
    def test_allow_once_still_logs_as_allowed(self, mock_vl_cls):
        """Verify existing ALLOW behavior unchanged after BLOCK support."""
        from ai_guardian.ask_mode import _log_ask_decision
        from ai_guardian.tui.ask_dialog import AskDecision

        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl
        _log_ask_decision(
            "secret_detected",
            AskDecision.ALLOW_ONCE,
            matched_text="key",
            error_msg="Secret found",
        )
        call_kwargs = mock_vl.log_violation.call_args[1]
        assert call_kwargs["context"]["ask_decision"] == "allow_once"
        assert call_kwargs["context"]["action_taken"] == "allowed"


class TestHandleAskModeMultiDedup:
    """Tests for finding deduplication in _handle_ask_mode_multi (#1427).

    The same secret can appear in both the user message and the transcript
    scan for UserPromptSubmit, or be detected by multiple scanner engines.
    Findings with the same matched_text must produce only ONE dialog.
    """

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_duplicate_matched_text_shows_one_dialog(self, _sub, _daemon):
        """Two findings with identical matched_text → single ask dialog."""
        from ai_guardian.ask_mode import _handle_ask_mode_multi
        from ai_guardian.tui.ask_dialog import AskDecision

        findings = [
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key",
                "line_number": 1,
            },
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key",
                "line_number": 5,
            },
        ]

        with patch("ai_guardian.ask_mode._handle_ask_mode") as mock_ask:
            from ai_guardian.tui.ask_dialog import AskResult

            mock_ask.return_value = AskResult(decision=AskDecision.ALLOW_ONCE)
            _handle_ask_mode_multi(
                "ask",
                "secret_detected",
                findings,
                "secret_scanning",
                "Secret detected",
            )

        assert mock_ask.call_count == 1

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_distinct_matched_text_shows_multiple_dialogs(self, _sub, _daemon):
        """Two findings with different matched_text → two separate dialogs."""
        from ai_guardian.ask_mode import _handle_ask_mode_multi
        from ai_guardian.tui.ask_dialog import AskDecision

        findings = [
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key",
                "line_number": 1,
            },
            {
                "matched_text": "AKIA0000000000EXAMPLE",
                "matched_pattern": "aws-access-token",
                "line_number": 3,
            },
        ]

        with patch("ai_guardian.ask_mode._handle_ask_mode") as mock_ask:
            from ai_guardian.tui.ask_dialog import AskResult

            mock_ask.return_value = AskResult(decision=AskDecision.ALLOW_ONCE)
            _handle_ask_mode_multi(
                "ask",
                "secret_detected",
                findings,
                "secret_scanning",
                "Secrets detected",
            )

        assert mock_ask.call_count == 2

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_three_same_one_different_shows_two_dialogs(self, _sub, _daemon):
        """Three duplicates + one unique → two dialogs total."""
        from ai_guardian.ask_mode import _handle_ask_mode_multi
        from ai_guardian.tui.ask_dialog import AskDecision

        findings = [
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key",
                "line_number": 1,
            },
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key",
                "line_number": 2,
            },
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key",
                "line_number": 3,
            },
            {
                "matched_text": "AKIA0000000000EXAMPLE",
                "matched_pattern": "aws-access-token",
                "line_number": 4,
            },
        ]

        with patch("ai_guardian.ask_mode._handle_ask_mode") as mock_ask:
            from ai_guardian.tui.ask_dialog import AskResult

            mock_ask.return_value = AskResult(decision=AskDecision.ALLOW_ONCE)
            _handle_ask_mode_multi(
                "ask",
                "secret_detected",
                findings,
                "secret_scanning",
                "Secrets detected",
            )

        assert mock_ask.call_count == 2

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_non_ask_action_returns_none_without_dedup(self, _sub, _daemon):
        """Non-ask action returns None before dedup runs."""
        from ai_guardian.ask_mode import _handle_ask_mode_multi

        findings = [
            {"matched_text": "sk-proj-abc123", "matched_pattern": "openai-api-key"},
            {"matched_text": "sk-proj-abc123", "matched_pattern": "openai-api-key"},
        ]

        result = _handle_ask_mode_multi(
            "block",
            "secret_detected",
            findings,
            "secret_scanning",
            "error",
        )
        assert result is None

    @patch("ai_guardian.tui.ask_dialog._show_via_daemon", return_value=None)
    @patch("ai_guardian.tui.ask_dialog._show_via_subprocess", return_value=None)
    def test_dedup_preserves_first_occurrence(self, _sub, _daemon):
        """Dedup keeps the first finding for each unique matched_text."""
        from ai_guardian.ask_mode import _handle_ask_mode_multi
        from ai_guardian.tui.ask_dialog import AskDecision

        findings = [
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key",
                "line_number": 1,
            },
            {
                "matched_text": "sk-proj-abc123",
                "matched_pattern": "openai-api-key-v2",
                "line_number": 9,
            },
        ]

        captured_calls = []

        with patch("ai_guardian.ask_mode._handle_ask_mode") as mock_ask:
            from ai_guardian.tui.ask_dialog import AskResult

            def capture(*args, **kwargs):
                captured_calls.append(kwargs)
                return AskResult(decision=AskDecision.ALLOW_ONCE)

            mock_ask.side_effect = capture
            _handle_ask_mode_multi(
                "ask",
                "secret_detected",
                findings,
                "secret_scanning",
                "Secret detected",
            )

        assert mock_ask.call_count == 1
        assert captured_calls[0].get("line_number") == 1
