"""User-experience contracts for Pi integration (#2325)."""

import json
from unittest.mock import patch

from ai_guardian.hook_adapters.pi import PiAdapter
from ai_guardian.setup import _setup_hooks_json_output
from ai_guardian.setup.hooks import IDESetup


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


def test_pi_setup_reports_native_mcp_as_unsupported(tmp_path, monkeypatch, capsys):
    """
    USER EXPERIENCE: Pi setup -> extension is installed without fake MCP config.

    Expected User Experience:
    - Setup writes the Pi extension in the configured agent directory.
    - JSON setup output explicitly reports MCP as unsupported.
    - AI Guardian does not create an invented Pi MCP configuration file.
    """
    agent_home = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_home))
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))

    with patch.object(IDESetup, "verify_gitleaks_installed", return_value=(True, "ok")):
        assert _setup_hooks_json_output("pi", force=True) is True

    result = json.loads(capsys.readouterr().out)
    assert result["success"] is True
    assert result["mcp_status"] == "unsupported"
    assert result["mcp_registration"] == "none"
    assert result["mcp_config_path"] is None
    assert (agent_home / "extensions" / "ai-guardian.ts").is_file()
