"""Tests for OpenClaw plugin system support (Issue #640)."""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock


from ai_guardian.response_format import (
    detect_ide_type,
    format_response,
    IDEType,
)
from ai_guardian.constants import HookEvent


class TestOpenClawIDEDetection:
    """Test IDE detection for OpenClaw."""

    def test_detect_ide_type_openclaw_env_var(self):
        """AI_GUARDIAN_IDE_TYPE=openclaw maps to KIRO (exit-code format)."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "openclaw"}):
            result = detect_ide_type({})
            assert result == IDEType.KIRO


class TestOpenClawResponseFormat:
    """Test response formatting for OpenClaw (uses Kiro exit-code format)."""

    def test_pretooluse_block(self, capsys):
        """Blocking PreToolUse returns exit code 1 and writes to stderr."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "openclaw"}):
            ide = detect_ide_type({})
        result = format_response(
            ide,
            has_secrets=True,
            error_message="Secret detected in command",
            hook_event=HookEvent.PRE_TOOL_USE,
        )
        assert result["exit_code"] == 2
        assert result["output"] is None
        assert result["_blocked"] is True
        captured = capsys.readouterr()
        assert "Secret detected in command" in captured.err

    def test_pretooluse_allow(self):
        """Allowing PreToolUse returns exit code 0."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "openclaw"}):
            ide = detect_ide_type({})
        result = format_response(
            ide,
            has_secrets=False,
            hook_event=HookEvent.PRE_TOOL_USE,
        )
        assert result["exit_code"] == 0
        assert result["output"] is None

    def test_prompt_block(self, capsys):
        """Blocking prompt returns exit code 1."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "openclaw"}):
            ide = detect_ide_type({})
        result = format_response(
            ide,
            has_secrets=True,
            error_message="Prompt injection detected",
            hook_event=HookEvent.PROMPT,
        )
        assert result["exit_code"] == 1
        captured = capsys.readouterr()
        assert "Prompt injection detected" in captured.err

    def test_posttooluse_allow(self):
        """PostToolUse allow returns exit code 0."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "openclaw"}):
            ide = detect_ide_type({})
        result = format_response(
            ide,
            has_secrets=False,
            hook_event=HookEvent.POST_TOOL_USE,
        )
        assert result["exit_code"] == 0
        assert result["output"] is None

    def test_posttooluse_with_modified_output(self):
        """PostToolUse with modified output sends redacted content via stdout."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "openclaw"}):
            ide = detect_ide_type({})
        result = format_response(
            ide,
            has_secrets=False,
            hook_event=HookEvent.POST_TOOL_USE,
            modified_output="[REDACTED] file contents",
        )
        assert result["exit_code"] == 0
        assert "[REDACTED] file contents" in result["output"]


class TestOpenClawSetupConfig:
    """Test IDE setup configuration for OpenClaw."""

    def test_openclaw_in_ide_configs(self):
        """OpenClaw has IDE config entry with extension_based flag."""
        from ai_guardian.setup import IDESetup

        assert "openclaw" in IDESetup.IDE_CONFIGS
        config = IDESetup.IDE_CONFIGS["openclaw"]
        assert config["name"] == "OpenClaw"
        assert config["extension_based"] is True

    def test_openclaw_config_path(self):
        """OpenClaw config path points to plugin directory."""
        from ai_guardian.setup import IDESetup

        config = IDESetup.IDE_CONFIGS["openclaw"]
        assert config["config_path"] == "~/.openclaw/plugins/ai-guardian"

    def test_openclaw_no_hooks_or_scripts(self):
        """OpenClaw config does not define hooks or script_based."""
        from ai_guardian.setup import IDESetup

        config = IDESetup.IDE_CONFIGS["openclaw"]
        assert "hooks" not in config
        assert "script_based" not in config
        assert "hook_scripts" not in config
        assert "mcp_only" not in config


class TestOpenClawSetupFlow:
    """Test setup flow for OpenClaw extension-based IDE."""

    def test_setup_creates_extension_directory(self):
        """setup_ide_hooks creates the plugin directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".openclaw", "plugins", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("openclaw")
                assert success is True
                assert Path(ext_dir).exists()

    def test_setup_creates_index_ts(self):
        """setup_ide_hooks creates index.ts with ai-guardian plugin content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".openclaw", "plugins", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                setup.setup_ide_hooks("openclaw")
                index_path = Path(ext_dir) / "index.ts"
                assert index_path.exists()
                content = index_path.read_text()
                assert "ai-guardian" in content
                assert "definePluginEntry" in content
                assert (Path(ext_dir) / "ai-guardian-bridge.ts").exists()

    def test_setup_creates_package_json(self):
        """setup_ide_hooks creates package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".openclaw", "plugins", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                setup.setup_ide_hooks("openclaw")
                pkg_path = Path(ext_dir) / "package.json"
                assert pkg_path.exists()
                content = json.loads(pkg_path.read_text())
                assert content["name"] == "ai-guardian-openclaw"
                assert "openclaw" in content["dependencies"]

    def test_setup_dry_run(self):
        """setup_ide_hooks in dry_run mode does not create files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".openclaw", "plugins", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("openclaw", dry_run=True)
                assert success is True
                assert "DRY RUN" in message
                assert not Path(ext_dir).exists()

    def test_setup_no_overwrite_without_force(self):
        """setup_ide_hooks does not overwrite existing plugin without --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".openclaw", "plugins", "ai-guardian")
            os.makedirs(ext_dir)
            index_path = Path(ext_dir) / "index.ts"
            index_path.write_text("// existing ai-guardian plugin")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("openclaw")
                assert success is False
                assert "already configured" in message
                assert index_path.read_text() == "// existing ai-guardian plugin"

    def test_setup_force_overwrite(self):
        """setup_ide_hooks overwrites existing plugin with --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".openclaw", "plugins", "ai-guardian")
            os.makedirs(ext_dir)
            index_path = Path(ext_dir) / "index.ts"
            index_path.write_text("// old content")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("openclaw", force=True)
                assert success is True
                content = index_path.read_text()
                assert "definePluginEntry" in content

    def test_setup_message_includes_npm_install(self):
        """setup_ide_hooks message includes npm install step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".openclaw", "plugins", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("openclaw")
                assert "npm install" in message


class TestOpenClawHooksConfigured:
    """Test hook detection for OpenClaw."""

    def test_check_hooks_configured_true(self):
        """Returns True when index.ts contains ai-guardian."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = Path(tmpdir) / "ai-guardian"
            ext_dir.mkdir()
            index_path = ext_dir / "index.ts"
            index_path.write_text("// ai-guardian plugin code")
            (ext_dir / "ai-guardian-bridge.ts").write_text("// shared bridge")
            from ai_guardian.setup import IDESetup

            setup = IDESetup()
            assert setup.check_hooks_configured(ext_dir, "openclaw") is True

    def test_check_hooks_configured_false_no_dir(self):
        """Returns False when directory does not exist."""
        from ai_guardian.setup import IDESetup

        setup = IDESetup()
        assert (
            setup.check_hooks_configured(Path("/nonexistent/path"), "openclaw") is False
        )

    def test_check_hooks_configured_false_no_index(self):
        """Returns False when directory exists but no index.ts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = Path(tmpdir) / "ai-guardian"
            ext_dir.mkdir()
            from ai_guardian.setup import IDESetup

            setup = IDESetup()
            assert setup.check_hooks_configured(ext_dir, "openclaw") is False

    def test_check_hooks_configured_false_unrelated_content(self):
        """Returns False when index.ts exists but does not contain ai-guardian."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = Path(tmpdir) / "ai-guardian"
            ext_dir.mkdir()
            index_path = ext_dir / "index.ts"
            index_path.write_text("// some other plugin")
            from ai_guardian.setup import IDESetup

            setup = IDESetup()
            assert setup.check_hooks_configured(ext_dir, "openclaw") is False


class TestOpenClawMCPConfig:
    """Test MCP configuration for OpenClaw."""

    def test_openclaw_in_mcp_ide_configs(self):
        """OpenClaw has MCP config entry."""
        from ai_guardian.setup import _MCP_IDE_CONFIGS

        assert "openclaw" in _MCP_IDE_CONFIGS
        config = _MCP_IDE_CONFIGS["openclaw"]
        assert config["config_file"] == "~/.openclaw/settings.json"
        assert config["config_key"] == "mcpServers"
        assert config["skill_dir"] == ".openclaw/skills"


class TestOpenClawRulesConfig:
    """Test rules/guidelines configuration for OpenClaw."""

    def test_openclaw_in_rules_ide_configs(self):
        """OpenClaw has rules config entry for SOUL.md."""
        from ai_guardian.setup import _RULES_IDE_CONFIGS

        assert "openclaw" in _RULES_IDE_CONFIGS
        config = _RULES_IDE_CONFIGS["openclaw"]
        assert config["rules_file"] == "SOUL.md"
        assert config["rules_dir"] == "."


class TestOpenClawCLI:
    """Test CLI integration for OpenClaw."""

    def test_openclaw_in_cli_choices(self):
        """'openclaw' is a valid --ide choice."""
        from ai_guardian.setup import IDESetup

        assert "openclaw" in IDESetup.IDE_CONFIGS


class TestOpenClawPluginContent:
    """Test the embedded plugin TypeScript content."""

    def test_plugin_has_define_plugin_entry(self):
        """Plugin TS uses definePluginEntry from openclaw SDK."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "definePluginEntry" in _OPENCLAW_PLUGIN_TS

    def test_plugin_has_before_tool_call(self):
        """Plugin TS registers before_tool_call hook."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "before_tool_call" in _OPENCLAW_PLUGIN_TS

    def test_plugin_has_after_tool_call(self):
        """Plugin TS registers after_tool_call hook."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "after_tool_call" in _OPENCLAW_PLUGIN_TS

    def test_plugin_has_message_received(self):
        """Plugin TS registers message_received hook."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "message_received" in _OPENCLAW_PLUGIN_TS

    def test_plugin_has_session_hooks(self):
        """Plugin TS registers session_start and session_end hooks."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "session_start" in _OPENCLAW_PLUGIN_TS
        assert "session_end" in _OPENCLAW_PLUGIN_TS

    def test_plugin_uses_shared_bridge(self):
        """Plugin TS delegates process and response handling to the shared bridge."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "./ai-guardian-bridge" in _OPENCLAW_PLUGIN_TS
        assert "createGuardianBridge" in _OPENCLAW_PLUGIN_TS
        assert "guardian.run" in _OPENCLAW_PLUGIN_TS

    def test_plugin_selects_ide_type(self):
        """Plugin configures the shared bridge for OpenClaw."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "ideType: 'openclaw'" in _OPENCLAW_PLUGIN_TS
        assert "openclaw" in _OPENCLAW_PLUGIN_TS

    def test_plugin_does_not_spawn_process_directly(self):
        """The plugin does not duplicate the process bridge."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "execSync" not in _OPENCLAW_PLUGIN_TS
        assert "execFileSync" not in _OPENCLAW_PLUGIN_TS

    def test_plugin_returns_block_result(self):
        """Plugin returns block: true with blockReason on tool call blocking."""
        from ai_guardian.setup import _OPENCLAW_PLUGIN_TS

        assert "block: true" in _OPENCLAW_PLUGIN_TS
        assert "blockReason" in _OPENCLAW_PLUGIN_TS

    def test_package_json_has_dependency(self):
        """Package JSON includes openclaw dependency."""
        from ai_guardian.setup import _OPENCLAW_PACKAGE_JSON

        content = json.loads(_OPENCLAW_PACKAGE_JSON)
        assert "openclaw" in content["dependencies"]
        assert content["name"] == "ai-guardian-openclaw"

    def test_package_json_has_hooks_metadata(self):
        """Package JSON includes openclaw hooks metadata."""
        from ai_guardian.setup import _OPENCLAW_PACKAGE_JSON

        content = json.loads(_OPENCLAW_PACKAGE_JSON)
        assert "openclaw" in content
        assert "hooks" in content["openclaw"]
