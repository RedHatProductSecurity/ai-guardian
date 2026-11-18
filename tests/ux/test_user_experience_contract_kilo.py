"""User-visible contracts for the Kilo Code CLI plugin bridge."""

import json
from io import StringIO
from unittest.mock import patch

import ai_guardian
from ai_guardian.setup import _KILO_PLUGIN_TS
from ai_guardian.tools.policy import ToolPolicyChecker


def _run_kilo_write(path, cwd):
    config = {
        "permissions": {"enabled": False, "rules": []},
        "agent_config_protection": {"enabled": True},
        "secret_scanning": {"enabled": False},
        "secret_redaction": {"enabled": False},
        "scan_pii": {"enabled": False},
        "prompt_injection": {"enabled": False},
        "ssrf_protection": {"enabled": False},
        "bootstrap_scan": {"enabled": False},
    }
    hook_data = {
        "hook_event_name": "tool.execute.before",
        "hook_source": "kilo",
        "kilo_plugin_api": "v1",
        "tool_use": {
            "name": "write",
            "input": {"filePath": path, "content": '{"replacement": true}'},
        },
        "cwd": str(cwd),
    }
    with (
        patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(config, None),
        ),
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=({"enabled": False, "rules": []}, None),
        ),
        patch(
            "ai_guardian.hook_processing._load_agent_config_protection_config",
            return_value=({"enabled": True}, None),
        ),
        patch(
            "ai_guardian.hook_processing.ToolPolicyChecker",
            side_effect=lambda **kwargs: ToolPolicyChecker(config=config, **kwargs),
        ),
        patch(
            "ai_guardian.hook_processing._load_pattern_server_config",
            return_value=None,
        ),
        patch("sys.stdin", StringIO(json.dumps(hook_data))),
    ):
        return ai_guardian.process_hook_input()


def test_kilo_protected_config_write_is_denied_before_the_tool_runs(tmp_path):
    """
    USER EXPERIENCE: Kilo writes its project config -> AI Guardian denies first.

    Scenario:
    1. Kilo v7.8.27 invokes the V1 ``tool.execute.before`` plugin callback.
    2. Its native ``write``/``filePath`` input targets a protected Kilo config.
    3. AI Guardian returns a Claude-compatible denial to the bridge.
    4. The Kilo plugin throws its fixed notice before the tool is executed.

    Expected User Experience:
    - The protected config is not modified by the tool.
    - The model sees a fixed denial notice, not a successful write result.
    - Prompt interception is not claimed; this plugin registers no prompt hook.

    Native CLI qualification remains pending; this is a hook-pipeline and
    generated-plugin contract, not evidence that Kilo loads or enforces it.
    """
    project_config = tmp_path / ".kilo" / "kilo.json"
    project_config.parent.mkdir(parents=True)
    original = b'{"mcp": {}}\n'
    project_config.write_bytes(original)
    result = _run_kilo_write(".kilo/kilo.json", tmp_path)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "blocked" in response["systemMessage"].lower()
    assert result["_blocked"] is True
    assert "AI Guardian blocked this tool call before execution." in _KILO_PLUGIN_TS
    assert "if (result.blocked) throw new Error(PRE_TOOL_REFUSAL_NOTICE);" in (
        _KILO_PLUGIN_TS
    )
    assert project_config.read_bytes() == original


def test_kilo_after_tool_notice_does_not_claim_result_withholding_or_replacement():
    """
    USER EXPERIENCE: Kilo post-tool finding -> fixed refusal, no sanitized copy.

    Kilo's v7.8.27 source exposes ``tool.execute.after`` after execution, but
    native result-delivery behavior has not been qualified. The generated
    plugin therefore throws a fixed notice whenever AI Guardian blocks or
    returns transformed output; it never assigns a sanitized copy to Kilo's
    result object and does not claim the result was withheld. Tool side effects
    have already occurred.
    """
    after_hook = _KILO_PLUGIN_TS.split("async 'tool.execute.after'", maxsplit=1)[1]
    expected_notice = (
        "AI Guardian flagged a tool result after execution. The tool ran. Native "
        "Kilo result handling is unverified; do not infer that the result was "
        "safely replaced or repeat it. Tell the user it was flagged and wait for "
        "a new instruction."
    )

    assert expected_notice in _KILO_PLUGIN_TS
    assert "if (result.blocked || result.updatedOutput !== undefined)" in after_hook
    assert "throw new Error(POST_TOOL_REFUSAL_NOTICE);" in after_hook
    assert "output.output =" not in after_hook
    assert "withheld from the model" not in expected_notice
    assert "unverified" in expected_notice
    assert "updatedOutput" not in _KILO_PLUGIN_TS.split(
        "async 'tool.execute.after'", maxsplit=1
    )[1].split("export default", maxsplit=1)[0].replace(
        "result.updatedOutput !== undefined", ""
    )
    assert "chat.message" not in _KILO_PLUGIN_TS
