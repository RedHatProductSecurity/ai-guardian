"""UX contracts for OpenCode immutable configuration protection (#2425)."""

import json
from io import StringIO
from unittest.mock import patch

import pytest

import ai_guardian
from ai_guardian.setup.hooks import _OPENCODE_PLUGIN_V2_TS
from ai_guardian.tools.policy import ToolPolicyChecker


def _run_opencode_hook(tool_name, tool_input, *, permissions_enabled=True):
    config = {
        "permissions": {"enabled": permissions_enabled, "rules": []},
        "agent_config_protection": {"enabled": True},
    }
    hook_data = {
        "hook_event_name": "tool.execute.before",
        "opencode_version": "1.0.0",
        "hook_source": "opencode",
        "tool_use": {"name": tool_name, "input": tool_input},
    }
    with (
        patch(
            "ai_guardian.hook_processing._load_permissions_config",
            return_value=({"enabled": permissions_enabled, "rules": []}, None),
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


@pytest.mark.parametrize(
    "tool_name,tool_input",
    [
        (
            "read",
            {"filePath": "/home/user/.config/ai-guardian/ai-guardian.json"},
        ),
        (
            "read",
            {"filePath": "/home/user/project/.ai-guardian.json"},
        ),
        (
            "write",
            {
                "filePath": "/home/user/project/.ai-guardian.json",
                "content": "{}",
            },
        ),
        (
            "edit",
            {
                "filePath": "/home/user/project/.ai-guardian.json",
                "oldString": "{}",
                "newString": '{"changed": true}',
            },
        ),
    ],
)
def test_opencode_protected_configuration_is_denied(tool_name, tool_input):
    """
    USER EXPERIENCE: Native OpenCode config access -> denied before execution.

    OpenCode uses lowercase tool names and camelCase arguments. The hook must
    canonicalize those fields before immutable protection evaluates the path.
    """
    result = _run_opencode_hook(tool_name, tool_input)

    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "blocked" in response["systemMessage"].lower()


def test_opencode_safe_file_read_remains_allowed():
    """Safe OpenCode file operations continue through the hook."""
    result = _run_opencode_hook("read", {"filePath": "/tmp/project/README.md"})

    response = json.loads(result.get("output") or "{}")
    assert response.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


def test_opencode_v2_refused_prompt_is_recorded_without_sending_prompt_to_model():
    """
    USER EXPERIENCE: Sensitive prompt -> AI Guardian refusal reaches transcript.

    Scenario:
    1. The user submits a prompt that AI Guardian blocks.
    2. The V2 prompt hook records a fixed refusal notice in the transcript.
    3. OpenCode rejects the original prompt; no blocked text is copied into the
       notice or passed to the model.

    Expected User Experience:
    - The transcript identifies AI Guardian as refusing the previous prompt.
    - OpenCode shows the notice as synthetic user-role input, not an assistant
      answer, and does not start a model run for it.
    - The next model turn sees that the prior request was refused and must not
      continue it.
    - The refused prompt, detection details, and bridge error are not exposed
      in the notice.

    Exact notice:
    "AI Guardian refused the previous prompt. The original prompt was not sent
    to the model. Do not answer or continue that request. Ask the user to
    provide a new prompt without the sensitive or blocked content."

    Manual verification with OpenCode V2:
    1. Start a session with the generated AI Guardian plugin loaded.
    2. Submit a test prompt that triggers a configured AI Guardian block.
    3. Confirm the transcript contains the synthetic refusal notice and the
       original prompt was not processed by the model.
    4. Submit a safe follow-up and confirm the model sees the refusal notice,
       not the blocked text.
    """
    prompt_hook = _OPENCODE_PLUGIN_V2_TS.split(
        "await ctx.session.hook('prompt'", maxsplit=1
    )[1].split("await ctx.tool.hook('execute.before'", maxsplit=1)[0]
    expected_notice = (
        "AI Guardian refused the previous prompt. "
        "The original prompt was not sent to the model. "
        "Do not answer or continue that request. "
        "Ask the user to provide a new prompt without the sensitive or blocked content."
    )

    assert expected_notice in _OPENCODE_PLUGIN_V2_TS
    assert "ctx.session.synthetic({" in prompt_hook
    assert "resume: false" in prompt_hook
    assert "prompt," not in prompt_hook.split("ctx.session.synthetic({", maxsplit=1)[1]
    assert "result.error" not in prompt_hook
    assert "throw new Error('Blocked by ai-guardian')" in prompt_hook
