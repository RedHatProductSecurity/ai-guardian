"""Tests for OpenCode hook adapter support (Issue #819)."""

import json
import os
from unittest import mock

import pytest

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters import detect_adapter
from ai_guardian.hook_adapters.opencode import OpenCodeAdapter
from ai_guardian.opencode_support import (
    clear_opencode_version_cache,
    detect_opencode_runtime,
    detect_opencode_version,
    opencode_generation,
    parse_opencode_version,
)
from ai_guardian.setup.hooks import IDESetup, _OPENCODE_PLUGIN_V2_TS


@pytest.fixture(autouse=True)
def _reset_opencode_version_cache():
    clear_opencode_version_cache()
    yield
    clear_opencode_version_cache()


class TestOpenCodeDetection:
    """Test OpenCode adapter detection."""

    @pytest.fixture(autouse=True)
    def _clear_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AI_GUARDIAN_IDE_TYPE", None)
            yield

    def test_detect_from_opencode_version(self):
        adapter = detect_adapter({"opencode_version": "1.0.0"})
        assert isinstance(adapter, OpenCodeAdapter)

    def test_detect_from_hook_source(self):
        adapter = detect_adapter({"hook_source": "opencode"})
        assert isinstance(adapter, OpenCodeAdapter)

    def test_env_var_override(self):
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_IDE_TYPE": "opencode"}):
            adapter = detect_adapter({})
            assert isinstance(adapter, OpenCodeAdapter)

    def test_ide_type_field(self):
        adapter = detect_adapter({"_ide_type": "opencode"})
        assert isinstance(adapter, OpenCodeAdapter)

    def test_name(self):
        assert OpenCodeAdapter().name == "OpenCode"

    def test_can_handle_false_for_empty(self):
        assert OpenCodeAdapter.can_handle({}) is False

    def test_can_handle_true_for_opencode_version(self):
        assert OpenCodeAdapter.can_handle({"opencode_version": "1.0.0"}) is True

    def test_can_handle_true_for_hook_source(self):
        assert OpenCodeAdapter.can_handle({"hook_source": "opencode"}) is True


class TestOpenCodeNormalization:
    """Test OpenCode event normalization."""

    def test_tool_execute_before(self):
        data = {
            "hook_event_name": "tool.execute.before",
            "opencode_version": "1.0.0",
            "tool_name": "Bash",
            "tool_use": {"input": {"command": "ls"}},
            "cwd": "/home/user",
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.event == HookEvent.PRE_TOOL_USE
        assert n.tool_name == "Bash"
        assert n.tool_input == {"command": "ls"}
        assert n.working_dir == "/home/user"

    def test_tool_execute_after(self):
        data = {
            "hook_event_name": "tool.execute.after",
            "opencode_version": "1.0.0",
            "tool_name": "Read",
            "tool_response": {"output": "file contents"},
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.event == HookEvent.POST_TOOL_USE
        assert n.tool_name == "Read"
        assert n.tool_response == {"output": "file contents"}

    def test_message_submit(self):
        data = {
            "hook_event_name": "message.submit",
            "opencode_version": "1.0.0",
            "prompt": "help me fix the bug",
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.event == HookEvent.PROMPT
        assert n.prompt_text == "help me fix the bug"

    def test_session_end_is_a_terminal_event(self):
        data = {
            "hook_event_name": "session.end",
            "opencode_version": "1.0.0",
            "hook_source": "opencode",
            "session_id": "session-123",
        }

        normalized = OpenCodeAdapter().normalize_input(data)

        assert normalized.event == HookEvent.SESSION_END
        assert normalized.session_id == "session-123"

    def test_file_path_extraction(self):
        data = {
            "hook_event_name": "tool.execute.before",
            "opencode_version": "1.0.0",
            "tool_name": "Read",
            "tool_use": {"input": {"file_path": "/tmp/secret.py"}},
        }
        n = OpenCodeAdapter().normalize_input(data)
        assert n.file_path == "/tmp/secret.py"

    @pytest.mark.parametrize(
        "native_name,canonical_name,tool_input,canonical_key",
        [
            ("read", "Read", {"filePath": "/tmp/secret.py"}, "file_path"),
            ("write", "Write", {"filePath": "/tmp/secret.py"}, "file_path"),
            (
                "edit",
                "Edit",
                {
                    "filePath": "/tmp/secret.py",
                    "oldString": "old",
                    "newString": "new",
                },
                "file_path",
            ),
            ("bash", "Bash", {"command": "printf safe"}, "command"),
        ],
    )
    def test_native_tools_are_canonicalized(
        self, native_name, canonical_name, tool_input, canonical_key
    ):
        data = {
            "hook_event_name": "tool.execute.before",
            "opencode_version": "1.0.0",
            "tool_use": {"name": native_name, "input": tool_input},
        }

        normalized = OpenCodeAdapter().normalize_input(data)

        assert normalized.tool_name == canonical_name
        expected_value = tool_input.get(canonical_key, tool_input.get("filePath"))
        assert normalized.tool_input[canonical_key] == expected_value

    def test_v2_malformed_payload_is_safe(self):
        normalized = OpenCodeAdapter().normalize_input(
            {
                "hook_event_name": "unknown.v2.event",
                "opencode_version": "2.0.22",
                "tool_use": {"input": "not-an-object"},
            }
        )

        assert normalized.event == HookEvent.PRE_TOOL_USE
        assert normalized.tool_input == {}


class TestOpenCodeResponseFormatting:
    """Test OpenCode response formatting (inherits BaseAgentAdapter format)."""

    def test_pretooluse_block(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Secret found in file",
            hook_event=HookEvent.PRE_TOOL_USE,
        )
        assert result["exit_code"] == 0
        data = json.loads(result["output"])
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["_blocked"] is True

    def test_pretooluse_allow(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=False,
            hook_event=HookEvent.PRE_TOOL_USE,
        )
        assert result["exit_code"] == 0
        data = json.loads(result["output"])
        assert data == {}

    def test_posttooluse_block(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Secret in output",
            hook_event=HookEvent.POST_TOOL_USE,
        )
        data = json.loads(result["output"])
        assert data["decision"] == "block"
        assert result["_blocked"] is True

    def test_posttooluse_redaction(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=False,
            hook_event=HookEvent.POST_TOOL_USE,
            modified_output="[REDACTED]",
        )
        data = json.loads(result["output"])
        assert data["hookSpecificOutput"]["updatedToolOutput"] == "[REDACTED]"

    def test_prompt_block(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Prompt injection detected",
            hook_event=HookEvent.PROMPT,
        )
        data = json.loads(result["output"])
        assert data["decision"] == "block"

    def test_prompt_security_message(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=False,
            hook_event=HookEvent.PROMPT,
            security_message="SECURITY RULES",
        )
        data = json.loads(result["output"])
        assert "SECURITY RULES" in data["systemMessage"]

    def test_posttooluse_warning_is_allowed(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=False,
            hook_event=HookEvent.POST_TOOL_USE,
            warning_message="Review this output",
            violation_type="secret_detected",
        )
        data = json.loads(result["output"])
        assert result.get("_blocked", False) is False
        assert data["systemMessage"] == "Review this output"

    def test_violation_type_metadata(self):
        result = OpenCodeAdapter().format_response(
            has_secrets=True,
            error_message="Secret found",
            hook_event=HookEvent.PRE_TOOL_USE,
            violation_type="secret_detected",
        )
        assert result["_violation_type"] == "secret_detected"


def test_parse_opencode_version_accepts_cli_prefixes():
    assert parse_opencode_version("opencode 2.0.22") == "2.0.22"
    assert parse_opencode_version("OpenCode v1.18.31") == "1.18.31"


def test_parse_opencode_version_rejects_missing_version():
    assert parse_opencode_version("OpenCode development build") is None


def test_opencode_generation_boundaries():
    assert opencode_generation("1.18.31") == "v1"
    assert opencode_generation("2.0.0") == "v2"
    assert opencode_generation(None) == "unknown"


def test_detect_opencode_version_uses_cli_output_without_override(monkeypatch):
    monkeypatch.delenv("AI_GUARDIAN_OPENCODE_VERSION", raising=False)
    completed = mock.Mock(stdout="2.0.22\n", stderr="", returncode=0)
    with mock.patch(
        "ai_guardian.opencode_support.shutil.which", return_value="opencode"
    ):
        with mock.patch(
            "ai_guardian.opencode_support.subprocess.run", return_value=completed
        ) as run:
            assert detect_opencode_version() == "2.0.22"
    run.assert_called_once()
    assert run.call_args.args[0] == ["opencode", "--version"]


def test_detect_opencode_version_caches_and_invalidates_runtime_context(monkeypatch):
    monkeypatch.delenv("AI_GUARDIAN_OPENCODE_VERSION", raising=False)
    completed = mock.Mock(stdout="2.0.22\n", stderr="", returncode=0)
    with (
        mock.patch(
            "ai_guardian.opencode_support.shutil.which",
            return_value="/usr/local/bin/opencode",
        ),
        mock.patch(
            "ai_guardian.opencode_support.subprocess.run", return_value=completed
        ) as run,
    ):
        assert detect_opencode_version() == "2.0.22"
        assert detect_opencode_version() == "2.0.22"
        monkeypatch.setenv("AI_GUARDIAN_OPENCODE_VERSION", "1.18.34")
        assert detect_opencode_version() == "1.18.34"
        assert run.call_count == 1

        clear_opencode_version_cache()
        monkeypatch.delenv("AI_GUARDIAN_OPENCODE_VERSION")
        assert detect_opencode_version() == "2.0.22"

    assert run.call_count == 2


def test_detect_opencode_runtime_reports_v2_package():
    with mock.patch(
        "ai_guardian.opencode_support.detect_opencode_version",
        return_value="2.0.22",
    ):
        with mock.patch(
            "ai_guardian.opencode_support.shutil.which", return_value="opencode"
        ):
            assert detect_opencode_runtime() == {
                "executable": "opencode",
                "version": "2.0.22",
                "generation": "v2",
                "package": "@opencode/cli",
                "supported": True,
            }


def test_v2_plugin_template_uses_domain_hooks():
    assert "from '@opencode/plugin'" in _OPENCODE_PLUGIN_V2_TS
    assert "Plugin.define" in _OPENCODE_PLUGIN_V2_TS
    assert "ctx.session.hook('prompt'" in _OPENCODE_PLUGIN_V2_TS
    assert "ctx.tool.hook('execute.before'" in _OPENCODE_PLUGIN_V2_TS
    assert "ctx.tool.hook('execute.after'" in _OPENCODE_PLUGIN_V2_TS
    assert "tool_use_id: event.id" in _OPENCODE_PLUGIN_V2_TS
    assert "event.callID" not in _OPENCODE_PLUGIN_V2_TS
    assert "event.status === 'completed'" in _OPENCODE_PLUGIN_V2_TS
    assert "const error = event.error as unknown" in _OPENCODE_PLUGIN_V2_TS
    assert "'message' in error" in _OPENCODE_PLUGIN_V2_TS
    assert "event.result =" in _OPENCODE_PLUGIN_V2_TS


def test_v2_registration_uses_plural_plugins_key(tmp_path):
    config_file = tmp_path / "opencode.json"
    config_file.write_text('{"plugin": ["/old/plugin.ts"]}\n', encoding="utf-8")
    plugin_file = tmp_path / "plugins" / "ai-guardian.ts"
    plugin_file.parent.mkdir()
    plugin_file.write_text("// generated plugin\n", encoding="utf-8")

    setup = IDESetup()
    with mock.patch(
        "ai_guardian.setup.hooks._resolve_opencode_config", return_value=config_file
    ):
        setup._register_opencode_plugin(
            plugin_file, plugin_file.parent, generation="v2"
        )

    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert "plugin" not in config
    assert config["plugins"] == ["/old/plugin.ts", str(plugin_file)]


def test_v2_verification_requires_plural_plugins_key(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin_file = plugins_dir / "ai-guardian.ts"
    plugin_file.write_text(_OPENCODE_PLUGIN_V2_TS, encoding="utf-8")
    config_file = tmp_path / "opencode.json"
    config_file.write_text(json.dumps({"plugin": [str(plugin_file)]}), encoding="utf-8")

    setup = IDESetup()
    with (
        mock.patch(
            "ai_guardian.setup.hooks._resolve_opencode_config", return_value=config_file
        ),
        mock.patch(
            "ai_guardian.setup.hooks.detect_opencode_runtime",
            return_value={"generation": "v2", "version": "2.0.22"},
        ),
    ):
        assert setup.check_hooks_configured(plugins_dir, "opencode") is False

    config_file.write_text(
        json.dumps({"plugins": [str(plugin_file)]}), encoding="utf-8"
    )
    with (
        mock.patch(
            "ai_guardian.setup.hooks._resolve_opencode_config", return_value=config_file
        ),
        mock.patch(
            "ai_guardian.setup.hooks.detect_opencode_runtime",
            return_value={"generation": "v2", "version": "2.0.22"},
        ),
    ):
        assert setup.check_hooks_configured(plugins_dir, "opencode") is True


def test_setup_renders_v2_plugin_and_keeps_v1_bridge_location(tmp_path):
    plugins_dir = tmp_path / "plugins"
    config_file = tmp_path / "opencode.jsonc"

    setup = IDESetup()
    with (
        mock.patch(
            "ai_guardian.setup.hooks._resolve_opencode_config", return_value=config_file
        ),
        mock.patch(
            "ai_guardian.setup.hooks.detect_opencode_runtime",
            return_value={
                "version": "2.0.22",
                "generation": "v2",
                "package": "@opencode/cli",
            },
        ),
        mock.patch(
            "ai_guardian.setup.hooks._resolve_binary_path", return_value="ai-guardian"
        ),
        mock.patch.object(
            setup, "verify_gitleaks_installed", return_value=(True, "gitleaks ok")
        ),
    ):
        success, message = setup._setup_plugin_file(
            "opencode",
            IDESetup.IDE_CONFIGS["opencode"],
            plugins_dir,
        )

    assert success is True
    assert "OpenCode v2 2.0.22" in message
    source = (plugins_dir / "ai-guardian.ts").read_text(encoding="utf-8")
    assert "@opencode/plugin" in source
    assert (tmp_path / "ai-guardian" / "ai-guardian-bridge.ts").is_file()
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert config["plugins"] == [str(plugins_dir / "ai-guardian.ts")]
