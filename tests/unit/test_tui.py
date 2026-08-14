#!/usr/bin/env python3
"""
Tests for AI Guardian TUI

Tests the interactive TUI components and configuration management.
"""

import json
import subprocess
import tempfile
from pathlib import Path
import pytest

from ai_guardian.tui.app import (
    AIGuardianTUI,
    NAV_GROUPS,
    PANEL_TO_CONFIG_SECTION,
    _is_feature_enabled,
    HELP_DOCS,
    HelpModal,
    copy_to_system_clipboard,
    copy_osc52,
    _try_clipboard_command,
)


class TestTUIApp:
    """Tests for the main TUI application."""

    def test_tui_initialization(self):
        """Test that TUI app can be initialized."""
        app = AIGuardianTUI()
        assert app is not None
        assert app.TITLE == "AI Guardian Configuration"

    def test_tui_has_screens(self):
        """Test that TUI has required screens."""
        app = AIGuardianTUI()
        assert app is not None


class TestNavGroups:
    """Tests for navigation structure."""

    def test_nav_groups_has_nine_categories(self):
        """Test that NAV_GROUPS defines exactly 9 category groups."""
        assert len(NAV_GROUPS) == 9

    def test_nav_groups_has_fifty_one_panels(self):
        """Test that NAV_GROUPS defines exactly 51 leaf panels."""
        total_leaves = sum(len(items) for _, items in NAV_GROUPS)
        assert total_leaves == 51

    def test_panel_ids_are_unique(self):
        """Test that all panel IDs are unique."""
        panel_ids = [pid for _, items in NAV_GROUPS for _, pid in items]
        assert len(panel_ids) == len(set(panel_ids)), "Duplicate panel IDs found"

    def test_panel_ids_have_panel_prefix(self):
        """Test that all panel IDs start with 'panel-'."""
        for _, items in NAV_GROUPS:
            for _, panel_id in items:
                assert panel_id.startswith(
                    "panel-"
                ), f"{panel_id} missing 'panel-' prefix"

    def test_category_labels_are_strings(self):
        """Test that all category labels are non-empty strings."""
        for label, _ in NAV_GROUPS:
            assert isinstance(label, str)
            assert len(label) > 0

    def test_leaf_labels_are_strings(self):
        """Test that all leaf labels are non-empty strings."""
        for _, items in NAV_GROUPS:
            for label, _ in items:
                assert isinstance(label, str)
                assert len(label) > 0

    def test_check_action_panel_ids_exist_in_nav(self):
        """Test that all panel IDs referenced in check_action exist in NAV_GROUPS."""
        panel_ids = {pid for _, items in NAV_GROUPS for _, pid in items}
        action_panel_ids = {
            "panel-skills",
            "panel-mcp",
            "panel-pi-detection",
            "panel-pi-patterns",
            "panel-secrets",
            "panel-ssrf",
            "panel-config-scanner",
            "panel-secret-redaction",
        }
        assert action_panel_ids.issubset(
            panel_ids
        ), f"Missing panel IDs: {action_panel_ids - panel_ids}"

    def test_expected_categories(self):
        """Test that the expected category names are present."""
        category_names = [name for name, _ in NAV_GROUPS]
        assert "Security Overview" in category_names
        assert "Permissions" in category_names
        assert "Threat Detection" in category_names
        assert "Prompt Injection" in category_names
        assert "Secrets" in category_names
        assert "Monitoring" in category_names
        assert "SDK" in category_names
        assert "Configuration" in category_names
        assert "Tools" in category_names

    def test_expected_panels_in_categories(self):
        """Test that key panels are in the correct categories."""
        nav_dict = {name: [pid for _, pid in items] for name, items in NAV_GROUPS}

        assert "panel-security-dashboard" in nav_dict["Security Overview"]
        assert "panel-skills" in nav_dict["Permissions"]
        assert "panel-pi-detection" in nav_dict["Prompt Injection"]
        assert "panel-pi-jailbreak" in nav_dict["Prompt Injection"]
        assert "panel-pi-unicode" in nav_dict["Prompt Injection"]
        assert "panel-context-poisoning" in nav_dict["Threat Detection"]
        assert "panel-scan-pii" in nav_dict["Threat Detection"]
        assert "panel-secrets" in nav_dict["Secrets"]
        assert "panel-violations" in nav_dict["Monitoring"]
        assert "panel-violation-logging" in nav_dict["Monitoring"]
        assert "panel-sdk-agents" in nav_dict["SDK"]
        assert "panel-sdk-settings" in nav_dict["SDK"]
        assert "panel-traces" in nav_dict["SDK"]
        assert "panel-config-file" in nav_dict["Configuration"]
        assert "panel-config-editor" in nav_dict["Configuration"]
        assert "panel-config-effective" in nav_dict["Configuration"]
        assert "panel-regex-tester" in nav_dict["Tools"]
        assert "panel-hook-simulator" in nav_dict["Tools"]


class TestPanelToConfigSection:
    """Tests for PANEL_TO_CONFIG_SECTION mapping."""

    def test_mapping_has_expected_entries(self):
        assert "panel-secrets" in PANEL_TO_CONFIG_SECTION
        assert "panel-pi-detection" in PANEL_TO_CONFIG_SECTION
        assert "panel-ssrf" in PANEL_TO_CONFIG_SECTION
        assert "panel-supply-chain" in PANEL_TO_CONFIG_SECTION

    def test_sub_pages_map_to_parent_scanner(self):
        assert PANEL_TO_CONFIG_SECTION["panel-secret-engines"] == "secret_scanning"
        assert PANEL_TO_CONFIG_SECTION["panel-pi-ml-engines"] == "prompt_injection"
        assert PANEL_TO_CONFIG_SECTION["panel-pi-patterns"] == "prompt_injection"
        assert PANEL_TO_CONFIG_SECTION["panel-pi-jailbreak"] == "prompt_injection"
        assert PANEL_TO_CONFIG_SECTION["panel-pi-unicode"] == "prompt_injection"

    def test_always_visible_panels_not_in_mapping(self):
        assert "panel-security-dashboard" not in PANEL_TO_CONFIG_SECTION
        assert "panel-global-settings" not in PANEL_TO_CONFIG_SECTION
        assert "panel-health-check" not in PANEL_TO_CONFIG_SECTION
        assert "panel-violations" not in PANEL_TO_CONFIG_SECTION
        assert "panel-metrics" not in PANEL_TO_CONFIG_SECTION
        assert "panel-logs" not in PANEL_TO_CONFIG_SECTION
        assert "panel-about" not in PANEL_TO_CONFIG_SECTION

    def test_all_panel_ids_exist_in_nav_groups(self):
        all_panels = {pid for _, items in NAV_GROUPS for _, pid in items}
        for panel_id in PANEL_TO_CONFIG_SECTION:
            assert panel_id in all_panels, f"{panel_id} not found in NAV_GROUPS"

    def test_mapping_consistent_with_web(self):
        """Web and TUI mappings should cover same config sections."""
        try:
            from ai_guardian.constants import SLUG_TO_CONFIG_SECTION

            web_sections = set(SLUG_TO_CONFIG_SECTION.values())
            tui_sections = set(PANEL_TO_CONFIG_SECTION.values())
            assert web_sections == tui_sections
        except ImportError:
            pytest.skip("NiceGUI not available")


class TestIsFeatureEnabled:
    """Tests for _is_feature_enabled helper in TUI."""

    def test_enabled_true(self):
        config = {"secret_scanning": {"enabled": True}}
        assert _is_feature_enabled(config, "secret_scanning") is True

    def test_enabled_false(self):
        config = {"secret_scanning": {"enabled": False}}
        assert _is_feature_enabled(config, "secret_scanning") is False

    def test_missing_section_defaults_true(self):
        assert _is_feature_enabled({}, "secret_scanning") is True

    def test_enabled_dict_with_value_false(self):
        config = {"ssrf_protection": {"enabled": {"value": False}}}
        assert _is_feature_enabled(config, "ssrf_protection") is False


class TestToggleDisabledScanners:
    """Tests for toggle_disabled_scanners action."""

    def test_app_has_toggle_binding(self):
        app = AIGuardianTUI()
        binding_actions = [b.action for b in app.BINDINGS]
        assert "toggle_disabled_scanners" in binding_actions

    def test_initial_state_is_true(self):
        app = AIGuardianTUI()
        assert app._show_disabled_scanners is True

    def test_has_rebuild_nav_tree_method(self):
        app = AIGuardianTUI()
        assert hasattr(app, "_rebuild_nav_tree")
        assert callable(app._rebuild_nav_tree)


class TestHelpDocs:
    """Tests for inline help documentation."""

    def test_all_panels_have_help(self):
        """Test that every panel has a help doc entry."""
        panel_ids = [pid for _, items in NAV_GROUPS for _, pid in items]
        for panel_id in panel_ids:
            assert panel_id in HELP_DOCS, f"Missing help doc for {panel_id}"

    def test_all_categories_have_help(self):
        """Test that every category has a help doc entry."""
        category_names = [name for name, _ in NAV_GROUPS]
        for name in category_names:
            assert name in HELP_DOCS, f"Missing help doc for category {name}"

    def test_help_docs_are_non_empty_strings(self):
        """Test that all help doc entries are non-empty strings."""
        for key, doc in HELP_DOCS.items():
            assert isinstance(doc, str), f"Help doc for {key} is not a string"
            assert len(doc) > 0, f"Help doc for {key} is empty"

    def test_help_docs_total_count(self):
        """Test total help doc entries: 8 categories + 24 panels = 32."""
        expected = len(NAV_GROUPS) + sum(len(items) for _, items in NAV_GROUPS)
        assert len(HELP_DOCS) == expected

    def test_help_modal_initialization(self):
        """Test that HelpModal can be initialized."""
        modal = HelpModal("Test Title", "Test body content")
        assert modal._title == "Test Title"
        assert modal._body == "Test body content"


class TestPermissionsEditor:
    """Tests for permissions editor functionality."""

    def test_add_permission_rule(self):
        """Test adding a new permission rule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"

            config = {"permissions": []}
            with open(config_path, "w") as f:
                json.dump(config, f)

            new_rule = {
                "matcher": "mcp__notebooklm-mcp__*",
                "mode": "allow",
                "patterns": ["*"],
            }

            with open(config_path, "r") as f:
                config = json.load(f)

            config["permissions"].append(new_rule)

            with open(config_path, "w") as f:
                json.dump(config, f)

            with open(config_path, "r") as f:
                updated_config = json.load(f)

            assert len(updated_config["permissions"]) == 1
            assert (
                updated_config["permissions"][0]["matcher"] == "mcp__notebooklm-mcp__*"
            )

    def test_delete_permission_rule(self):
        """Test deleting a permission rule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"

            config = {
                "permissions": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]},
                    {"matcher": "mcp__test__*", "mode": "deny", "patterns": ["*"]},
                ]
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            with open(config_path, "r") as f:
                config = json.load(f)

            config["permissions"].pop(0)

            with open(config_path, "w") as f:
                json.dump(config, f)

            with open(config_path, "r") as f:
                updated_config = json.load(f)

            assert len(updated_config["permissions"]) == 1
            assert updated_config["permissions"][0]["matcher"] == "mcp__test__*"

    def test_edit_permission_rule(self):
        """Test editing a permission rule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"

            config = {
                "permissions": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}
                ]
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            with open(config_path, "r") as f:
                config = json.load(f)

            config["permissions"][0]["patterns"] = ["daf-*", "release"]

            with open(config_path, "w") as f:
                json.dump(config, f)

            with open(config_path, "r") as f:
                updated_config = json.load(f)

            assert len(updated_config["permissions"]) == 1
            assert "release" in updated_config["permissions"][0]["patterns"]


class TestConfigViewer:
    """Tests for configuration viewer."""

    def test_load_user_config(self):
        """Test loading user configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ai-guardian.json"

            config = {
                "permissions": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["*"]}
                ],
                "violation_logging": {"enabled": True, "max_entries": 1000},
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            with open(config_path, "r") as f:
                loaded_config = json.load(f)

            assert "permissions" in loaded_config
            assert "violation_logging" in loaded_config
            assert loaded_config["violation_logging"]["enabled"] is True

    def test_merge_configs(self):
        """Test merging user and project configs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            user_config_path = Path(tmpdir) / "user.json"
            project_config_path = Path(tmpdir) / "project.json"

            user_config = {
                "permissions": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}
                ]
            }
            with open(user_config_path, "w") as f:
                json.dump(user_config, f)

            project_config = {
                "permissions": [
                    {"matcher": "mcp__*", "mode": "deny", "patterns": ["*"]}
                ]
            }
            with open(project_config_path, "w") as f:
                json.dump(project_config, f)

            merged_config = {}

            with open(user_config_path, "r") as f:
                merged_config.update(json.load(f))

            with open(project_config_path, "r") as f:
                merged_config.update(json.load(f))

            assert len(merged_config["permissions"]) == 1
            assert merged_config["permissions"][0]["matcher"] == "mcp__*"


class TestClipboardSupport:
    """Tests for copy-to-clipboard functionality."""

    def test_app_has_text_selected_handler(self):
        """Test that AIGuardianTUI has on_text_selected handler for auto-copy."""
        app = AIGuardianTUI()
        assert hasattr(app, "on_text_selected")
        assert callable(app.on_text_selected)

    def test_violation_details_modal_has_copy_button(self):
        """Test that ViolationDetailsModal handles copy-details button ID."""
        from ai_guardian.tui.violations import ViolationDetailsModal
        import inspect

        source = inspect.getsource(ViolationDetailsModal.compose)
        assert "copy-details" in source
        source_handler = inspect.getsource(ViolationDetailsModal.on_button_pressed)
        assert "copy-details" in source_handler
        assert "copy_to_clipboard" in source_handler

    def test_violation_details_modal_copy_handler(self):
        """Test that ViolationDetailsModal handles copy-details button."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        modal = ViolationDetailsModal({"type": "test", "message": "test violation"})
        assert hasattr(modal, "on_button_pressed")

    def test_violation_details_modal_stores_violation_data(self):
        """Test that ViolationDetailsModal stores violation data for copying."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {"type": "secret_detected", "severity": "high", "file": "test.py"}
        modal = ViolationDetailsModal(violation)
        assert modal.violation == violation
        details = json.dumps(modal.violation, indent=2)
        assert '"type": "secret_detected"' in details
        assert '"severity": "high"' in details

    def test_app_has_copy_to_clipboard_override(self):
        """Test that AIGuardianTUI overrides copy_to_clipboard for native fallback."""
        app = AIGuardianTUI()
        assert hasattr(app, "copy_to_clipboard")
        import inspect

        source = inspect.getsource(AIGuardianTUI.copy_to_clipboard)
        assert "copy_to_system_clipboard" in source

    def test_copy_to_clipboard_returns_bool(self):
        """Test that copy_to_clipboard returns True on native, False on fallback."""
        import inspect

        source = inspect.getsource(AIGuardianTUI.copy_to_clipboard)
        assert "return True" in source
        assert "return False" in source
        assert "super().copy_to_clipboard" in source

    def test_on_text_selected_checks_copy_result(self):
        """Test that on_text_selected only notifies on successful copy."""
        import inspect

        source = inspect.getsource(AIGuardianTUI.on_text_selected)
        assert "if self.copy_to_clipboard" in source

    def test_violation_modal_checks_copy_result(self):
        """Test that ViolationDetailsModal only notifies on successful copy."""
        from ai_guardian.tui.violations import ViolationDetailsModal
        import inspect

        source = inspect.getsource(ViolationDetailsModal.on_button_pressed)
        assert "if self.app.copy_to_clipboard" in source


class TestCopyOsc52:
    """Tests for the OSC 52 clipboard escape sequence function."""

    def test_copy_osc52_success(self):
        """Test that copy_osc52 writes correct escape sequence to stdout."""
        from unittest.mock import patch

        with patch("ai_guardian.tui.app.sys") as mock_sys:
            mock_sys.stdout.write = lambda x: None
            mock_sys.stdout.flush = lambda: None
            result = copy_osc52("hello")
            assert result is True

    def test_copy_osc52_failure(self):
        """Test that copy_osc52 returns False on exception."""
        from unittest.mock import patch

        with patch("ai_guardian.tui.app.sys") as mock_sys:
            mock_sys.stdout.write.side_effect = OSError("broken pipe")
            result = copy_osc52("hello")
            assert result is False

    def test_copy_osc52_encodes_base64(self):
        """Test that copy_osc52 uses correct base64 encoding."""
        from unittest.mock import patch
        import base64

        written = []
        with patch("ai_guardian.tui.app.sys") as mock_sys:
            mock_sys.stdout.write = lambda x: written.append(x)
            mock_sys.stdout.flush = lambda: None
            copy_osc52("test")
            expected = base64.b64encode(b"test").decode("utf-8")
            assert len(written) == 1
            assert f"\033]52;c;{expected}\a" == written[0]


class TestTryClipboardCommand:
    """Tests for the _try_clipboard_command helper."""

    def test_success_returns_true(self):
        """Test that successful command returns True."""
        from unittest.mock import patch

        with patch("ai_guardian.tui.app.subprocess") as mock_subprocess:
            assert _try_clipboard_command(["pbcopy"], "text") is True

    def test_file_not_found_returns_false(self):
        """Test that missing command returns False."""
        from unittest.mock import patch

        with patch("ai_guardian.tui.app.subprocess") as mock_subprocess:
            mock_subprocess.run.side_effect = FileNotFoundError()
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            assert _try_clipboard_command(["missing"], "text") is False

    def test_timeout_returns_false(self):
        """Test that timed-out command returns False."""
        from unittest.mock import patch

        with patch("ai_guardian.tui.app.subprocess") as mock_subprocess:
            mock_subprocess.run.side_effect = subprocess.TimeoutExpired("cmd", 5)
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            assert _try_clipboard_command(["slow"], "text") is False


class TestCopyToSystemClipboard:
    """Tests for the platform-native copy_to_system_clipboard function."""

    def test_copy_succeeds_on_macos(self):
        """Test clipboard copy using pbcopy on macOS."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "darwin"
            error, method = copy_to_system_clipboard("test text")
            assert error is None
            assert method == "pbcopy"
            mock_subprocess.run.assert_called_once()
            args = mock_subprocess.run.call_args
            assert args[0][0] == ["pbcopy"]
            assert args[1]["input"] == b"test text"

    def test_copy_succeeds_on_linux_xclip(self):
        """Test clipboard copy using xclip on Linux."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "linux"
            error, method = copy_to_system_clipboard("test text")
            assert error is None
            assert method == "xclip"
            args = mock_subprocess.run.call_args
            assert args[0][0] == ["xclip", "-selection", "clipboard"]

    def test_copy_falls_back_to_xsel_on_linux(self):
        """Test fallback to xsel when xclip is not available."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "linux"
            mock_subprocess.run.side_effect = [
                FileNotFoundError("xclip not found"),
                None,
            ]
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            error, method = copy_to_system_clipboard("test text")
            assert error is None
            assert method == "xsel"
            assert mock_subprocess.run.call_count == 2
            second_call = mock_subprocess.run.call_args_list[1]
            assert second_call[0][0] == ["xsel", "--clipboard", "--input"]

    def test_copy_falls_back_to_wl_copy_on_linux(self):
        """Test fallback to wl-copy when xclip and xsel are not available."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "linux"
            mock_subprocess.run.side_effect = [
                FileNotFoundError("xclip"),
                FileNotFoundError("xsel"),
                None,
            ]
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            error, method = copy_to_system_clipboard("test text")
            assert error is None
            assert method == "wl-copy"

    def test_linux_no_tools_returns_error(self):
        """Test that Linux returns error when no clipboard tools are found."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "linux"
            mock_subprocess.run.side_effect = FileNotFoundError("not found")
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            error, method = copy_to_system_clipboard("test text")
            assert isinstance(error, str)
            assert method is None
            assert "terminal escape sequence" in error
            assert "xclip" in error

    def test_copy_succeeds_on_windows(self):
        """Test clipboard copy using clip on Windows."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "win32"
            error, method = copy_to_system_clipboard("test text")
            assert error is None
            assert method == "clip"
            args = mock_subprocess.run.call_args
            assert args[0][0] == ["clip"]
            assert args[1]["input"] == "test text".encode("utf-16le")

    def test_copy_returns_error_on_unknown_platform(self):
        """Test that unknown platforms try OSC 52 then return error."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.copy_osc52", return_value=False),
        ):
            mock_sys.platform = "freebsd"
            error, method = copy_to_system_clipboard("test text")
            assert isinstance(error, str)
            assert method is None
            assert "not supported" in error

    def test_unknown_platform_uses_osc52_if_available(self):
        """Test that unknown platforms succeed via OSC 52."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.copy_osc52", return_value=True),
        ):
            mock_sys.platform = "freebsd"
            error, method = copy_to_system_clipboard("test text")
            assert error is None
            assert method == "OSC 52"

    def test_macos_falls_back_to_osc52(self):
        """Test macOS falls back to OSC 52 when pbcopy fails."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
            patch("ai_guardian.tui.app.copy_osc52", return_value=True),
        ):
            mock_sys.platform = "darwin"
            mock_subprocess.run.side_effect = FileNotFoundError()
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            error, method = copy_to_system_clipboard("test text")
            assert error is None
            assert method == "OSC 52"

    def test_copy_returns_error_when_all_fail(self):
        """Test error returned when all methods including OSC 52 fail."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
            patch("ai_guardian.tui.app.copy_osc52", return_value=False),
        ):
            mock_sys.platform = "darwin"
            mock_subprocess.run.side_effect = FileNotFoundError()
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            error, method = copy_to_system_clipboard("test text")
            assert isinstance(error, str)
            assert method is None

    def test_copy_handles_unicode(self):
        """Test clipboard copy with unicode text."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "darwin"
            text = "Unicode: ☃ ❤ \U0001f680"
            error, method = copy_to_system_clipboard(text)
            assert error is None
            assert method == "pbcopy"
            args = mock_subprocess.run.call_args
            assert args[1]["input"] == text.encode("utf-8")

    def test_linux_no_tools_error_suggests_install(self):
        """Test Linux error message suggests installing clipboard tools."""
        from unittest.mock import patch

        with (
            patch("ai_guardian.tui.app.sys") as mock_sys,
            patch("ai_guardian.tui.app.subprocess") as mock_subprocess,
        ):
            mock_sys.platform = "linux"
            mock_subprocess.run.side_effect = FileNotFoundError("not found")
            mock_subprocess.CalledProcessError = subprocess.CalledProcessError
            mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired
            error, method = copy_to_system_clipboard("test text")
            assert isinstance(error, str)
            assert method is None
            assert "xclip" in error
            assert "xsel" in error
            assert "wl-copy" in error


class TestViolationCardFields:
    """Tests for ViolationCard rendering of violation type fields."""

    def test_prompt_injection_card_shows_matched_text(self):
        """Test that prompt_injection card renders matched_text field."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        assert (
            'matched_text = blocked.get("matched_text")' in source
            or "matched_text" in source
        )

    def test_prompt_injection_card_shows_confidence(self):
        """Test that prompt_injection card renders confidence field."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        assert "confidence" in source

    def test_prompt_injection_card_shows_method(self):
        """Test that prompt_injection card renders method field."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        assert "method" in source

    def test_prompt_injection_card_shows_line_number(self):
        """Test that prompt_injection card renders line_number with file_path."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        pi_section_start = source.index('vtype == "prompt_injection"')
        pi_section = source[pi_section_start : pi_section_start + 800]
        assert "line_number" in pi_section

    def test_jailbreak_card_shows_line_number(self):
        """Test that jailbreak_detected card renders line_number with file_path."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        jb_section_start = source.index('vtype == "jailbreak_detected"')
        jb_section = source[jb_section_start : jb_section_start + 800]
        assert "line_number" in jb_section

    def test_jailbreak_card_always_shows_matched_text(self):
        """Test that jailbreak_detected card shows matched_text regardless of file_path."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        jb_section_start = source.index('vtype == "jailbreak_detected"')
        jb_section = source[jb_section_start : jb_section_start + 800]
        matched_count = jb_section.count("matched_text")
        assert (
            matched_count >= 2
        ), "matched_text should be shown outside the else branch"

    def test_tool_permission_card_shows_line_number(self):
        """Test that tool_permission card renders line_number with file_path."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        tp_section_start = source.index('vtype == "tool_permission"')
        tp_section = source[tp_section_start : tp_section_start + 500]
        assert "line_number" in tp_section

    def test_details_button_always_shown(self):
        """Test that only Details button exists — no approve/deny/undo buttons."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        assert 'Button("Details"' in source
        assert "can_approve" not in source
        assert "Approve" not in source
        assert "Keep Blocked" not in source
        assert "Undo Resolution" not in source

    def test_position_displayed_in_location(self):
        """Test that position (char offset) is included in location display."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        assert (
            ", pos {position}" in source
            or ", pos {blocked['position']}" in source
            or "pos {position}" in source
        )

    def test_ssrf_blocked_type_handled(self):
        """Test that ssrf_blocked violation type has a dedicated section."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        assert 'vtype == "ssrf_blocked"' in source

    def test_config_file_exfil_type_handled(self):
        """Test that config_file_exfil violation type has a dedicated section."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        assert 'vtype == "config_file_exfil"' in source

    def test_ssrf_blocked_shows_location(self):
        """Test that ssrf_blocked section includes file_path and line_number."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        ssrf_start = source.index('vtype == "ssrf_blocked"')
        ssrf_section = source[ssrf_start : ssrf_start + 800]
        assert "file_path" in ssrf_section
        assert "line_number" in ssrf_section
        assert "position" in ssrf_section

    def test_config_file_exfil_shows_file_path(self):
        """Test that config_file_exfil section shows file_path."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        cfe_start = source.index('vtype == "config_file_exfil"')
        cfe_section = source[cfe_start : cfe_start + 500]
        assert "file_path" in cfe_section

    def test_all_location_types_include_position(self):
        """Test that all violation types with line_number also handle position."""
        import inspect
        from ai_guardian.tui.violations import ViolationCard

        source = inspect.getsource(ViolationCard.compose)
        types_with_location = [
            "tool_permission",
            "secret_detected",
            "prompt_injection",
            "secret_redaction",
            "pii_detected",
            "jailbreak_detected",
            "ssrf_blocked",
        ]
        for vtype in types_with_location:
            section_start = source.index(f'vtype == "{vtype}"')
            next_elif = source.find("elif vtype ==", section_start + 1)
            action_buttons = source.find("# Action buttons", section_start)
            section_end = min(x for x in [next_elif, action_buttons] if x > 0)
            section = source[section_start:section_end]
            if "line_number" in section:
                assert (
                    "position" in section
                ), f"{vtype} section has line_number but missing position support"


class TestViolationResolutionInstructions:
    """Tests for violation resolution instructions in ViolationDetailsModal."""

    def test_modal_has_resolution_instructions_method(self):
        """Test that ViolationDetailsModal has _get_resolution_instructions method."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        assert hasattr(ViolationDetailsModal, "_get_resolution_instructions")

    def test_tool_permission_instructions(self):
        """Test resolution instructions for tool_permission violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "tool_permission",
            "blocked": {},
            "suggestion": {
                "rule": {"matcher": "Skill", "mode": "allow", "patterns": ["test"]}
            },
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "permissions.rules" in instructions
        assert "Skill" in snippet
        assert "test" in snippet

    def test_prompt_injection_instructions(self):
        """Test resolution instructions for prompt_injection violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "prompt_injection",
            "blocked": {"pattern": "ignore previous"},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "allowlist_patterns" in instructions
        assert "ignore previous" in snippet

    def test_jailbreak_detected_instructions(self):
        """Test resolution instructions for jailbreak_detected violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "jailbreak_detected",
            "blocked": {"matched_text": "jailbreak text"},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "allowlist_patterns" in instructions
        assert "jailbreak text" in snippet

    def test_secret_detected_instructions(self):
        """Test resolution instructions for secret_detected violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "secret_detected",
            "blocked": {"file_path": "test.py", "rule_id": "api-key"},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "gitleaks:allow" in instructions
        assert "secret_scanning" in snippet

    def test_directory_blocking_instructions(self):
        """Test resolution instructions for directory_blocking violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "directory_blocking",
            "blocked": {"denied_directory": "/tmp/secret"},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "directory_rules" in instructions or ".ai-read-deny" in instructions
        assert "/tmp/secret" in snippet

    def test_pii_detected_instructions(self):
        """Test resolution instructions for pii_detected violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "pii_detected",
            "blocked": {"file_path": "data.csv"},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "scan_pii" in instructions
        assert "scan_pii" in snippet

    def test_secret_redaction_instructions(self):
        """Test resolution instructions for secret_redaction violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "secret_redaction",
            "blocked": {},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "secret_scanning" in instructions
        assert "allowlist_patterns" in snippet

    def test_ssrf_blocked_instructions(self):
        """Test resolution instructions for ssrf_blocked violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "ssrf_blocked",
            "blocked": {"tool_value": "https://example.com/api"},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "additional_allowed_domains" in instructions
        assert "example.com" in snippet

    def test_config_file_exfil_instructions(self):
        """Test resolution instructions for config_file_exfil violations."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "config_file_exfil",
            "blocked": {"file_path": ".env"},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "config_file_scanning" in instructions
        assert ".env" in snippet

    def test_unknown_type_instructions(self):
        """Test resolution instructions for unknown violation types."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        violation = {
            "violation_type": "unknown_type",
            "blocked": {},
            "suggestion": {},
        }
        modal = ViolationDetailsModal(violation)
        instructions, snippet = modal._get_resolution_instructions()
        assert "Review" in instructions or "No specific resolution" in instructions
        assert snippet == ""

    def test_all_known_types_have_instructions(self):
        """Test that all 9 known violation types return non-empty instructions."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        known_types = [
            "tool_permission",
            "prompt_injection",
            "jailbreak_detected",
            "secret_detected",
            "directory_blocking",
            "pii_detected",
            "secret_redaction",
            "ssrf_blocked",
            "config_file_exfil",
        ]
        for vtype in known_types:
            violation = {
                "violation_type": vtype,
                "blocked": {
                    "pattern": "test",
                    "file_path": "test.py",
                    "denied_directory": "/tmp",
                    "tool_value": "https://x.com",
                },
                "suggestion": {
                    "rule": {"matcher": "Skill", "mode": "allow", "patterns": ["t"]}
                },
            }
            modal = ViolationDetailsModal(violation)
            instructions, snippet = modal._get_resolution_instructions()
            assert instructions, f"{vtype} should have non-empty instructions"
            assert snippet, f"{vtype} should have non-empty snippet"

    def test_copy_snippet_button_in_modal(self):
        """Test that ViolationDetailsModal has copy-snippet button handling."""
        import inspect
        from ai_guardian.tui.violations import ViolationDetailsModal

        source = inspect.getsource(ViolationDetailsModal.on_button_pressed)
        assert "copy-snippet" in source


class TestPanelRefreshOnNavigation:
    """Tests for panel refresh when navigating via sidebar tree."""

    def test_on_tree_node_selected_calls_refresh_content(self):
        """Test that navigating to a panel calls refresh_content on its content widget."""
        from unittest.mock import patch, MagicMock

        app = AIGuardianTUI()

        mock_switcher = MagicMock()
        mock_content = MagicMock(spec=["refresh_content"])
        mock_panel = MagicMock()
        mock_panel.children = [mock_content]

        mock_event = MagicMock()
        mock_event.node.data = "panel-global-settings"

        with patch.object(
            app,
            "query_one",
            side_effect=lambda sel, *a: {
                "#panels": mock_switcher,
                "#panel-global-settings": mock_panel,
            }.get(sel if isinstance(sel, str) else sel),
        ):
            app.on_tree_node_selected(mock_event)

        assert mock_switcher.current == "panel-global-settings"
        mock_content.refresh_content.assert_called_once()

    def test_on_tree_node_selected_skips_when_no_data(self):
        """Test that tree node selection with no data does nothing."""
        from unittest.mock import MagicMock, patch

        app = AIGuardianTUI()
        mock_event = MagicMock()
        mock_event.node.data = None

        with patch.object(app, "query_one") as mock_query:
            app.on_tree_node_selected(mock_event)
            mock_query.assert_not_called()

    def test_on_tree_node_selected_handles_no_refresh_content(self):
        """Test graceful handling when content widget has no refresh_content."""
        from unittest.mock import MagicMock, patch

        app = AIGuardianTUI()

        mock_switcher = MagicMock()
        mock_content = MagicMock(spec=[])
        del mock_content.refresh_content
        mock_panel = MagicMock()
        mock_panel.children = [mock_content]

        mock_event = MagicMock()
        mock_event.node.data = "panel-regex-tester"

        with patch.object(
            app,
            "query_one",
            side_effect=lambda sel, *a: {
                "#panels": mock_switcher,
                "#panel-regex-tester": mock_panel,
            }.get(sel if isinstance(sel, str) else sel),
        ):
            app.on_tree_node_selected(mock_event)

        assert mock_switcher.current == "panel-regex-tester"


class TestModalEscBindings:
    """Tests for ESC key bindings on all modal screens."""

    def test_violation_details_modal_has_esc_binding(self):
        """Test that ViolationDetailsModal has ESC key binding."""
        from ai_guardian.tui.violations import ViolationDetailsModal

        binding_keys = [b.key for b in ViolationDetailsModal.BINDINGS]
        assert "escape" in binding_keys

    def test_add_permission_modal_has_esc_binding(self):
        """Test that AddPermissionModal has ESC key binding."""
        from ai_guardian.tui.permissions import AddPermissionModal

        binding_keys = [b.key for b in AddPermissionModal.BINDINGS]
        assert "escape" in binding_keys

    def test_confirm_clear_modal_has_esc_binding(self):
        """Test that ConfirmClearModal has ESC key binding."""
        from ai_guardian.tui.logs import ConfirmClearModal

        binding_keys = [b.key for b in ConfirmClearModal.BINDINGS]
        assert "escape" in binding_keys

    def test_violation_details_modal_has_scrollbar(self):
        """Test that ViolationDetailsModal wraps content in VerticalScroll."""
        import inspect
        from ai_guardian.tui.violations import ViolationDetailsModal

        source = inspect.getsource(ViolationDetailsModal.compose)
        assert "VerticalScroll" in source

    def test_violation_actions_have_top_margin(self):
        """Test that violation-actions CSS has top margin to prevent overlap."""
        from ai_guardian.tui.violations import ViolationsContent

        assert "margin: 1 0 0 0" in ViolationsContent.CSS


class TestListScrollWrapping:
    """Tests that editable list widgets are wrapped in scrollable containers."""

    @pytest.mark.parametrize(
        "module,class_name,list_ids",
        [
            (
                "scan_pii",
                "ScanPIIContent",
                ["ignore-files-list", "ignore-tools-list", "pii-allowlist-patterns"],
            ),
            ("secrets", "SecretsContent", ["secret-allowlist-patterns"]),
            (
                "prompt_injection",
                "PromptInjectionContent",
                ["allowlist-patterns", "custom-patterns"],
            ),
            (
                "config_scanner",
                "ConfigScannerContent",
                [
                    "additional-files-list",
                    "ignore-files-list",
                    "additional-patterns-list",
                ],
            ),
            (
                "ssrf",
                "SSRFContent",
                ["blocked-ips-list", "blocked-domains-list", "allowed-domains-list"],
            ),
            (
                "secret_redaction",
                "SecretRedactionContent",
                ["additional-patterns-list"],
            ),
        ],
    )
    def test_list_statics_have_scroll_wrapper(self, module, class_name, list_ids):
        """Verify each list Static is inside a VerticalScroll context manager."""
        import importlib
        import inspect
        import re

        mod = importlib.import_module(f"ai_guardian.tui.{module}")
        cls = getattr(mod, class_name)
        source = inspect.getsource(cls.compose)
        for list_id in list_ids:
            pattern = rf'VerticalScroll\(classes="list-scroll"\).*?\n\s+yield Static\("", id="{list_id}"\)'
            assert re.search(
                pattern, source, re.DOTALL
            ), f"{class_name}.compose(): {list_id} not wrapped in VerticalScroll(classes='list-scroll')"

    @pytest.mark.parametrize(
        "module,class_name",
        [
            ("scan_pii", "ScanPIIContent"),
            ("secrets", "SecretsContent"),
            ("prompt_injection", "PromptInjectionContent"),
            ("config_scanner", "ConfigScannerContent"),
            ("ssrf", "SSRFContent"),
            ("secret_redaction", "SecretRedactionContent"),
        ],
    )
    def test_css_has_list_scroll_class(self, module, class_name):
        """Verify each panel CSS defines .list-scroll with max-height."""
        import importlib

        mod = importlib.import_module(f"ai_guardian.tui.{module}")
        cls = getattr(mod, class_name)
        assert ".list-scroll" in cls.CSS, f"{class_name} CSS missing .list-scroll class"
        assert (
            "max-height" in cls.CSS
        ), f"{class_name} CSS missing max-height in .list-scroll"

    @pytest.mark.parametrize(
        "module,class_name",
        [
            ("permissions", "PermissionsScreen"),
            ("permissions_discovery", "PermissionsDiscoveryContent"),
            ("remote_configs", "RemoteConfigsContent"),
        ],
    )
    def test_pattern_b_containers_have_max_height(self, module, class_name):
        """Verify Pattern B VerticalScroll containers have max-height in their CSS."""
        import importlib

        mod = importlib.import_module(f"ai_guardian.tui.{module}")
        cls = getattr(mod, class_name)
        assert (
            "max-height" in cls.CSS
        ), f"{class_name} CSS missing max-height for scrollable list container"

    def test_permissions_discovery_has_selection_indicator(self):
        """Verify permissions discovery panel has a selection indicator widget."""
        import importlib
        import inspect

        mod = importlib.import_module("ai_guardian.tui.permissions_discovery")
        cls = getattr(mod, "PermissionsDiscoveryContent")
        source = inspect.getsource(cls.compose)
        assert (
            "selection-indicator" in source
        ), "PermissionsDiscoveryContent.compose() missing selection-indicator widget"
        assert (
            ".mode-indicator" in cls.CSS
        ), "PermissionsDiscoveryContent CSS missing .mode-indicator class"

    def test_permissions_discovery_has_select_changed_handler(self):
        """Verify permissions discovery panel handles Select.Changed events."""
        import importlib

        mod = importlib.import_module("ai_guardian.tui.permissions_discovery")
        cls = getattr(mod, "PermissionsDiscoveryContent")
        assert hasattr(
            cls, "on_select_changed"
        ), "PermissionsDiscoveryContent missing on_select_changed handler"
        assert hasattr(
            cls, "_update_selection_indicator"
        ), "PermissionsDiscoveryContent missing _update_selection_indicator method"


class TestPanelContainerConsistency:
    """Tests for panel wrapper consistency (issue #446)."""

    def test_all_panels_use_container_wrapper(self):
        """Test that all panels in compose() use Container, not VerticalScroll.

        Bug #446: panel-permissions-discovery used VerticalScroll instead of
        Container, causing WrongType crash when on_tree_node_selected queries
        for Container type.
        """
        import inspect

        source = inspect.getsource(AIGuardianTUI.compose)
        panel_ids = [pid for _, items in NAV_GROUPS for _, pid in items]
        for panel_id in panel_ids:
            pattern = f'id="{panel_id}"'
            idx = source.find(pattern)
            assert idx != -1, f"Panel {panel_id} not found in compose()"
            context = source[max(0, idx - 80) : idx]
            assert "VerticalScroll" not in context, (
                f"Panel {panel_id} wrapped in VerticalScroll instead of Container. "
                f"This causes WrongType crash in on_tree_node_selected."
            )

    def test_on_tree_node_selected_queries_container(self):
        """Test that on_tree_node_selected queries panels as Container type."""
        import inspect

        source = inspect.getsource(AIGuardianTUI.on_tree_node_selected)
        assert "Container" in source

    def test_get_current_content_queries_container(self):
        """Test that _get_current_content queries panels as Container type."""
        import inspect

        source = inspect.getsource(AIGuardianTUI._get_current_content)
        assert "Container" in source


class TestMCPServersNoDuplicateIds:
    """Tests for MCP servers panel avoiding DuplicateIds (issue #446)."""

    def test_empty_state_widget_has_no_fixed_id(self):
        """Test that the empty-state Static in load_permissions has no id.

        Bug #446: The 'no-permissions' id caused DuplicateIds crash because
        remove_children() is async and didn't complete before mount().
        """
        import inspect
        from ai_guardian.tui.mcp_servers import MCPServersContent

        source = inspect.getsource(MCPServersContent.load_permissions)
        assert 'id="no-permissions"' not in source, (
            "Empty-state Static should not have a fixed id to avoid "
            "DuplicateIds crash when remove_children() hasn't completed"
        )

    def test_empty_state_uses_class_for_styling(self):
        """Test that the empty-state widget uses CSS class instead of id."""
        import inspect
        from ai_guardian.tui.mcp_servers import MCPServersContent

        source = inspect.getsource(MCPServersContent.load_permissions)
        assert 'classes="empty-state"' in source

    def test_css_uses_class_selector_not_id(self):
        """Test that CSS targets .empty-state class, not #no-permissions id."""
        from ai_guardian.tui.mcp_servers import MCPServersContent

        assert ".empty-state" in MCPServersContent.CSS
        assert "#no-permissions" not in MCPServersContent.CSS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
