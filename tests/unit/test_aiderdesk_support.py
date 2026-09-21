"""Tests for AiderDesk Extension system support (Issue #639)."""

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


class TestAiderDeskIDEDetection:
    """Test IDE detection for AiderDesk."""

    def test_detect_ide_type_aiderdesk_env_var(self):
        """AI_GUARDIAN_IDE_TYPE=aiderdesk maps to KIRO (exit-code format)."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "aiderdesk"}):
            result = detect_ide_type({})
            assert result == IDEType.KIRO


class TestAiderDeskResponseFormat:
    """Test response formatting for AiderDesk (uses Kiro exit-code format)."""

    def test_pretooluse_block(self, capsys):
        """Blocking PreToolUse returns exit code 1 and writes to stderr."""
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "aiderdesk"}):
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
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "aiderdesk"}):
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
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "aiderdesk"}):
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
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "aiderdesk"}):
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
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "aiderdesk"}):
            ide = detect_ide_type({})
        result = format_response(
            ide,
            has_secrets=False,
            hook_event=HookEvent.POST_TOOL_USE,
            modified_output="[REDACTED] file contents",
        )
        assert result["exit_code"] == 0
        assert "[REDACTED] file contents" in result["output"]


class TestAiderDeskSetupConfig:
    """Test IDE setup configuration for AiderDesk."""

    def test_aiderdesk_in_ide_configs(self):
        """AiderDesk has IDE config entry with extension_based flag."""
        from ai_guardian.setup import IDESetup

        assert "aiderdesk" in IDESetup.IDE_CONFIGS
        config = IDESetup.IDE_CONFIGS["aiderdesk"]
        assert config["name"] == "AiderDesk"
        assert config["extension_based"] is True

    def test_aiderdesk_config_path(self):
        """AiderDesk config path points to extension directory."""
        from ai_guardian.setup import IDESetup

        config = IDESetup.IDE_CONFIGS["aiderdesk"]
        assert config["config_path"] == "~/.aider-desk/extensions/ai-guardian"

    def test_aiderdesk_no_hooks_or_scripts(self):
        """AiderDesk config does not define hooks or script_based."""
        from ai_guardian.setup import IDESetup

        config = IDESetup.IDE_CONFIGS["aiderdesk"]
        assert "hooks" not in config
        assert "script_based" not in config
        assert "hook_scripts" not in config
        assert "mcp_only" not in config


class TestAiderDeskSetupFlow:
    """Test setup flow for extension-based IDEs."""

    def test_setup_creates_extension_directory(self):
        """setup_ide_hooks creates the extension directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".aider-desk", "extensions", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("aiderdesk")
                assert success is True
                assert Path(ext_dir).exists()

    def test_setup_creates_index_ts(self):
        """setup_ide_hooks creates index.ts with ai-guardian content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".aider-desk", "extensions", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                setup.setup_ide_hooks("aiderdesk")
                index_path = Path(ext_dir) / "index.ts"
                assert index_path.exists()
                content = index_path.read_text()
                assert "ai-guardian" in content
                assert "AiGuardianExtension" in content
                assert (Path(ext_dir) / "ai-guardian-bridge.ts").exists()

    def test_setup_creates_package_json(self):
        """setup_ide_hooks creates package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".aider-desk", "extensions", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                setup.setup_ide_hooks("aiderdesk")
                pkg_path = Path(ext_dir) / "package.json"
                assert pkg_path.exists()
                content = json.loads(pkg_path.read_text())
                assert content["name"] == "ai-guardian-aiderdesk"
                assert "@aiderdesk/extensions" in content["dependencies"]

    def test_setup_dry_run(self):
        """setup_ide_hooks in dry_run mode does not create files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".aider-desk", "extensions", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("aiderdesk", dry_run=True)
                assert success is True
                assert "DRY RUN" in message
                assert not Path(ext_dir).exists()

    def test_setup_no_overwrite_without_force(self):
        """setup_ide_hooks does not overwrite existing extension without --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".aider-desk", "extensions", "ai-guardian")
            os.makedirs(ext_dir)
            index_path = Path(ext_dir) / "index.ts"
            index_path.write_text("// existing ai-guardian extension")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("aiderdesk")
                assert success is False
                assert "already configured" in message
                assert index_path.read_text() == "// existing ai-guardian extension"

    def test_setup_force_overwrite(self):
        """setup_ide_hooks overwrites existing extension with --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".aider-desk", "extensions", "ai-guardian")
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
                success, message = setup.setup_ide_hooks("aiderdesk", force=True)
                assert success is True
                content = index_path.read_text()
                assert "AiGuardianExtension" in content

    def test_setup_message_includes_npm_install(self):
        """setup_ide_hooks message includes npm install step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = os.path.join(tmpdir, ".aider-desk", "extensions", "ai-guardian")
            with mock.patch.object(
                __import__("ai_guardian.setup", fromlist=["IDESetup"]).IDESetup,
                "get_config_path",
                return_value=ext_dir,
            ):
                setup = __import__(
                    "ai_guardian.setup", fromlist=["IDESetup"]
                ).IDESetup()
                success, message = setup.setup_ide_hooks("aiderdesk")
                assert "npm install" in message


class TestAiderDeskHooksConfigured:
    """Test hook detection for AiderDesk."""

    def test_check_hooks_configured_true(self):
        """Returns True when index.ts contains ai-guardian."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = Path(tmpdir) / "ai-guardian"
            ext_dir.mkdir()
            index_path = ext_dir / "index.ts"
            index_path.write_text("// ai-guardian extension code")
            (ext_dir / "ai-guardian-bridge.ts").write_text("// shared bridge")
            from ai_guardian.setup import IDESetup

            setup = IDESetup()
            assert setup.check_hooks_configured(ext_dir, "aiderdesk") is True

    def test_check_hooks_configured_false_no_dir(self):
        """Returns False when directory does not exist."""
        from ai_guardian.setup import IDESetup

        setup = IDESetup()
        assert (
            setup.check_hooks_configured(Path("/nonexistent/path"), "aiderdesk")
            is False
        )

    def test_check_hooks_configured_false_no_index(self):
        """Returns False when directory exists but no index.ts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = Path(tmpdir) / "ai-guardian"
            ext_dir.mkdir()
            from ai_guardian.setup import IDESetup

            setup = IDESetup()
            assert setup.check_hooks_configured(ext_dir, "aiderdesk") is False

    def test_check_hooks_configured_false_unrelated_content(self):
        """Returns False when index.ts exists but does not contain ai-guardian."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ext_dir = Path(tmpdir) / "ai-guardian"
            ext_dir.mkdir()
            index_path = ext_dir / "index.ts"
            index_path.write_text("// some other extension")
            from ai_guardian.setup import IDESetup

            setup = IDESetup()
            assert setup.check_hooks_configured(ext_dir, "aiderdesk") is False


class TestAiderDeskMCPConfig:
    """Test MCP configuration for AiderDesk."""

    def test_aiderdesk_in_mcp_ide_configs(self):
        """AiderDesk has MCP config entry."""
        from ai_guardian.setup import _MCP_IDE_CONFIGS

        assert "aiderdesk" in _MCP_IDE_CONFIGS
        config = _MCP_IDE_CONFIGS["aiderdesk"]
        assert config["config_file"] == "~/.aider-desk/settings.json"
        assert config["config_key"] == "mcpServers"
        assert config["skill_dir"] == ".aider-desk/skills"


class TestAiderDeskCLI:
    """Test CLI integration for AiderDesk."""

    def test_aiderdesk_in_cli_choices(self):
        """'aiderdesk' is a valid --ide choice."""
        from ai_guardian.setup import IDESetup

        assert "aiderdesk" in IDESetup.IDE_CONFIGS


class TestAiderDeskExtensionContent:
    """Test the embedded extension TypeScript content."""

    def test_extension_has_metadata(self):
        """Extension TS has static metadata."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "static metadata" in _AIDERDESK_EXTENSION_TS
        assert "'AI Guardian'" in _AIDERDESK_EXTENSION_TS

    def test_extension_has_tool_approval_handler(self):
        """Extension TS hooks onToolApproval."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "onToolApproval" in _AIDERDESK_EXTENSION_TS

    def test_extension_has_tool_called_handler(self):
        """Extension TS hooks onToolCalled."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "onToolCalled" in _AIDERDESK_EXTENSION_TS

    def test_extension_has_tool_finished_handler(self):
        """Extension TS hooks onToolFinished."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "onToolFinished" in _AIDERDESK_EXTENSION_TS

    def test_extension_has_prompt_started_handler(self):
        """Extension TS hooks onPromptStarted."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "onPromptStarted" in _AIDERDESK_EXTENSION_TS

    def test_extension_has_files_added_handler(self):
        """Extension TS hooks onFilesAdded."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "onFilesAdded" in _AIDERDESK_EXTENSION_TS

    def test_extension_has_before_commit_handler(self):
        """Extension TS hooks onBeforeCommit."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "onBeforeCommit" in _AIDERDESK_EXTENSION_TS

    def test_extension_uses_shared_bridge(self):
        """Extension delegates process and response handling to the shared bridge."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "./ai-guardian-bridge" in _AIDERDESK_EXTENSION_TS
        assert "createGuardianBridge" in _AIDERDESK_EXTENSION_TS
        assert "aiderdesk" in _AIDERDESK_EXTENSION_TS

    def test_extension_does_not_spawn_process_directly(self):
        """The extension does not duplicate the process bridge."""
        from ai_guardian.setup import _AIDERDESK_EXTENSION_TS

        assert "execSync" not in _AIDERDESK_EXTENSION_TS
        assert "execFileSync" not in _AIDERDESK_EXTENSION_TS

    def test_package_json_has_dependency(self):
        """Package JSON includes @aiderdesk/extensions dependency."""
        from ai_guardian.setup import _AIDERDESK_PACKAGE_JSON

        content = json.loads(_AIDERDESK_PACKAGE_JSON)
        assert "@aiderdesk/extensions" in content["dependencies"]
