"""User-experience contracts for Pi integration (#2325)."""

import json
from unittest.mock import patch

import pytest

from ai_guardian.hook_adapters.pi import PiAdapter
from ai_guardian.hook_processing import process_hook_data
from ai_guardian.setup import _setup_hooks_json_output
from ai_guardian.setup.hooks import IDESetup
from ai_guardian.tools.policy import ToolPolicyChecker


@pytest.fixture
def isolated_pi_prompt_hooks(monkeypatch):
    """Explicit hook configs: never consume the user's security settings."""
    for name in (
        "prompt_injection",
        "config_scanner",
        "permissions",
        "agent_config_protection",
        "secret_scanning",
        "secret_redaction",
        "pii",
        "annotations",
        "image_scanning",
        "security_instructions",
        "context_poisoning",
        "supply_chain",
        "code_scanning",
        "offensive_language",
        "canary_detection",
        "exfil_detection",
    ):
        monkeypatch.setattr(
            f"ai_guardian.hook_processing._load_{name}_config",
            lambda: ({"enabled": False}, None),
        )
    monkeypatch.setattr(
        "ai_guardian.hook_processing._load_pattern_server_config", lambda: None
    )
    monkeypatch.setattr(
        "ai_guardian.hook_processing._load_transcript_scanning_config",
        lambda: ({"enabled": True}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.hook_processing._get_on_scan_error_action", lambda: "block"
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._get_on_scan_error_action", lambda: "block"
    )


def test_pi_first_clean_prompt_does_not_wait_for_its_lazy_transcript(
    isolated_pi_prompt_hooks, tmp_path
):
    """USER EXPERIENCE: a fresh Pi session can send its first clean prompt.

    Pi advertises a session path but persists it only after an assistant message.
    Missing first history is empty, not a scan failure; the hook must not create a
    fake transcript. Once Pi persists it, incremental scanning begins at byte zero.

    Manual verification: run all nine Pi local-mock cases with transcript scanning
    and fail-closed scan errors enabled. Require allowed/clean exits zero, native
    prompt/pre/post events, tool execution and sensitive-output containment.
    """
    path = tmp_path / "new-session.jsonl"
    positions = {}
    hook = {
        "hook_event_name": "UserPromptSubmit",
        "hook_source": "pi",
        "pi_version": "0.86.0",
        "prompt": "Inspect the clean project",
        "cwd": str(tmp_path),
        "session_id": "pi-first-prompt",
        "transcript_path": str(path),
    }
    with (
        patch(
            "ai_guardian.scanners.transcript.common._load_transcript_positions",
            return_value=positions,
        ),
        patch("ai_guardian.scanners.transcript.common._save_transcript_positions"),
        patch(
            "ai_guardian.scanners.transcript.common._scan_transcript_text",
            return_value=[],
        ) as scan,
    ):
        first = process_hook_data(hook)
        assert json.loads(first["output"]).get("decision") != "block"
        assert not first.get("_blocked")
        assert not path.exists()
        assert positions == {f"pi:{path}": 0}
        path.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "first persisted response"}
                        ],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        second = process_hook_data(hook)
        assert json.loads(second["output"]).get("decision") != "block"
        assert scan.call_args.args[0] == "first persisted response"


def test_pi_unexpected_transcript_io_failure_still_blocks(
    isolated_pi_prompt_hooks, tmp_path
):
    """USER EXPERIENCE: a genuine scan failure still produces a native block."""
    with patch(
        "ai_guardian.scanners.transcript.pi._scan_jsonl_incremental",
        side_effect=PermissionError("transcript unreadable"),
    ):
        result = process_hook_data(
            {
                "hook_event_name": "UserPromptSubmit",
                "hook_source": "pi",
                "pi_version": "0.86.0",
                "prompt": "Inspect the clean project",
                "cwd": str(tmp_path),
                "session_id": "pi-io-error",
                "transcript_path": str(tmp_path / "session.jsonl"),
            }
        )
    response = json.loads(result["output"])
    assert response["decision"] == "block"
    assert "Pi transcript scanning failed" in response["systemMessage"]
    assert result["_blocked"] is True


def test_pi_block_is_reported_as_a_host_action_block():
    """
    USER EXPERIENCE: Pi tool call detects a violation -> Pi receives a block.

    Scenario:
    1. Pi invokes the generated extension for a tool call.
    2. AI Guardian returns a Claude-compatible deny response.
    3. The extension translates that response into Pi's ``block`` result.

    Expected User Experience:
    - The tool call does not execute.
    - Pi receives the sanitized block reason through the extension.
    """
    result = PiAdapter().format_response(
        has_secrets=True,
        error_message="Operation blocked by ai-guardian",
        hook_event="pretooluse",
    )
    body = json.loads(result["output"])

    assert result["_blocked"] is True
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert body["systemMessage"] == "Operation blocked by ai-guardian"


def test_pi_lowercase_native_shell_uses_bash_permissions(isolated_pi_prompt_hooks):
    """USER EXPERIENCE: native bash must not miss canonical Bash enforcement.

    Pi sends its native tool name unchanged through tool_call. AI Guardian must
    apply the configured Bash policy and return the existing native deny result
    before execution. SSRF/config command checks use the same canonical boundary.

    Manual verification: require both pre-tool smoke probes to record their
    specific finding and pre-tool hook, with no post-tool event. Keep clean and
    sensitive-output execution and correlation assertions unchanged.
    """
    policy = ToolPolicyChecker(
        config={
            "permissions": {
                "enabled": True,
                "rules": [{"matcher": "Bash", "mode": "deny", "patterns": ["*"]}],
            }
        }
    )
    with (
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=({"enabled": True, "rules": []}, None),
        ),
        patch("ai_guardian.hook_processing.ToolPolicyChecker", return_value=policy),
    ):
        result = process_hook_data(
            {
                "hook_event_name": "PreToolUse",
                "hook_source": "pi",
                "pi_version": "0.86.0",
                "tool_name": "bash",
                "tool_use": {"name": "bash", "input": {"command": "printf hello"}},
            }
        )
    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert result["_blocked"] is True


def test_pi_setup_reports_managed_mcp_extension(tmp_path, monkeypatch, capsys):
    """
    USER EXPERIENCE: Pi setup -> hooks and MCP tools share one managed extension.

    Expected User Experience:
    - Setup writes the Pi extension in the configured agent directory.
    - JSON setup reports an extension-backed MCP registration, not a fake MCP file.
    - Missing npm dependencies are diagnosable and do not disable the hook bridge.
    """
    agent_home = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_home))
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))

    with (
        patch.object(IDESetup, "verify_gitleaks_installed", return_value=(True, "ok")),
        patch(
            "ai_guardian.setup.hooks._install_pi_mcp_sdk",
            return_value=(True, "installed the pinned Pi MCP SDK"),
        ),
    ):
        assert _setup_hooks_json_output("pi", force=True) is True

    result = json.loads(capsys.readouterr().out)
    assert result["success"] is True
    assert result["mcp_status"] == "missing_dependencies"
    assert result["mcp_registration"] == "extension"
    assert result["mcp_identity_registered"] is True
    assert (
        "npm install --ignore-scripts --no-audit --no-fund" in result["mcp_diagnostic"]
    )
    assert result["mcp_config_path"] is None
    assert (
        result["mcp_extension_path"]
        .replace("\\", "/")
        .endswith("extensions/ai-guardian/index.ts")
    )
    assert (agent_home / "extensions" / "ai-guardian" / "index.ts").is_file()
    assert not (agent_home / "extensions" / "ai-guardian.ts").exists()


def test_pi_setup_is_idempotent_before_npm_dependencies_are_installed(
    tmp_path, monkeypatch, capsys
):
    """
    USER EXPERIENCE: Re-running Pi setup -> existing hooks remain usable.

    Missing SDK dependencies are reported as a repair diagnostic, not as a
    reason to discard the hook bridge or report a false setup failure.
    """
    agent_home = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_home))
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))

    with (
        patch.object(IDESetup, "verify_gitleaks_installed", return_value=(True, "ok")),
        patch(
            "ai_guardian.setup.hooks._install_pi_mcp_sdk",
            return_value=(False, "npm was not found"),
        ),
    ):
        assert _setup_hooks_json_output("pi", force=True) is True
        capsys.readouterr()

        assert _setup_hooks_json_output("pi") is True
        result = json.loads(capsys.readouterr().out)
    assert result["success"] is True
    assert result["mcp_status"] == "missing_dependencies"
