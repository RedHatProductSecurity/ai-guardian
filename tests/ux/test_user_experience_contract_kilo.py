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
    - Prompt scanning is provided by a separate `chat.message` callback.

    Native pre-tool enforcement qualification remains pending; this is a
    hook-pipeline and generated-plugin contract, not evidence that Kilo enforces
    this protected-write denial.
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
    assert "async 'chat.message'(input, output)" in _KILO_PLUGIN_TS
    assert project_config.read_bytes() == original


def test_kilo_after_tool_replaces_sensitive_output_or_uses_fixed_refusal():
    """
    USER EXPERIENCE: Kilo post-tool finding -> sanitized result or fixed refusal.

    A user-reported Kilo 7.8.27 native Bash test with a synthetic secret
    returned sanitized output. Broader native result delivery remains
    unqualified. The generated plugin assigns a verified sanitized string to
    Kilo's mutable output, or assigns a fixed refusal when the bridge blocks or
    returns an invalid replacement. It clears the original title and metadata
    with either rewrite. Tool side effects have already occurred.
    """
    after_hook = _KILO_PLUGIN_TS.split("async 'tool.execute.after'", maxsplit=1)[1]
    expected_notice = (
        "AI Guardian blocked this tool result after execution. The tool ran, and "
        "its result was replaced with a fixed refusal. Do not infer that the tool’s "
        "side effects were undone. Tell the user it was flagged and wait for a new "
        "instruction."
    )

    assert expected_notice in _KILO_PLUGIN_TS
    assert "if (result.blocked) {" in after_hook
    assert "output.output = POST_TOOL_REFUSAL_NOTICE;" in after_hook
    assert "typeof result.updatedOutput === 'string'" in after_hook
    assert "output.output = result.updatedOutput;" in after_hook
    assert "output.title = 'AI Guardian sanitized tool result';" in after_hook
    assert "output.metadata = {};" in after_hook
    assert "throw new Error(POST_TOOL_REFUSAL_NOTICE);" not in after_hook
    prompt_hook = _KILO_PLUGIN_TS.split("async 'chat.message'", maxsplit=1)[1].split(
        "async 'tool.execute.after'", maxsplit=1
    )[0]
    assert "hook_event_name: 'UserPromptSubmit'" in prompt_hook
    assert "output.parts.splice(0, output.parts.length" in prompt_hook
