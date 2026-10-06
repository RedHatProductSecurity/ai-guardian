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
    assert "await recordRefusalNotice(" in prompt_hook
    assert "resume: false" in _OPENCODE_PLUGIN_V2_TS
    assert "result.error" not in prompt_hook
    assert "throw new Error('Blocked by ai-guardian')" in prompt_hook


def test_opencode_v2_pre_and_post_tool_blocks_reach_transcript_and_model():
    """
    USER EXPERIENCE: Blocked tool input/output -> safe AI Guardian notice.

    Scenario:
    1. The model attempts a tool operation that AI Guardian blocks before
       execution, or a completed tool returns output AI Guardian blocks.
    2. OpenCode marks the tool call as failed with a fixed, safe error.
    3. AI Guardian records a stage-specific synthetic transcript notice without
       copying tool arguments or output.

    Expected User Experience:
    - Before-tool notice says the tool did not run.
    - After-tool notice says the tool ran but its result was withheld.
    - The model receives a safe tool failure and later sees the refusal notice.
    - Post-tool blocking does not claim to undo the tool's side effects.
    - Redacted, allowed results still replace the original tool output.

    Manual verification with OpenCode V2:
    1. Configure a tool-input policy that denies a test tool call.
    2. Confirm the tool does not execute and the refusal notice appears.
    3. Configure a post-tool rule that blocks a test result.
    4. Confirm the result is not returned to the model and the notice states
       that the tool already ran.
    """
    before_hook = _OPENCODE_PLUGIN_V2_TS.split(
        "await ctx.tool.hook('execute.before'", maxsplit=1
    )[1].split("await ctx.tool.hook('execute.after'", maxsplit=1)[0]
    after_hook = _OPENCODE_PLUGIN_V2_TS.split(
        "await ctx.tool.hook('execute.after'", maxsplit=1
    )[1].split("const controller = new AbortController()", maxsplit=1)[0]

    assert "The tool did not run." in _OPENCODE_PLUGIN_V2_TS
    assert "its result was withheld from the model." in _OPENCODE_PLUGIN_V2_TS
    assert "await recordRefusalNotice(" in before_hook
    assert "await recordRefusalNotice(" in after_hook
    assert "AI Guardian blocked this tool call before execution" in before_hook
    assert (
        "AI Guardian blocked this tool result after execution; result withheld"
        in after_hook
    )
    assert "result.error" not in before_hook
    assert "result.error" not in after_hook
    assert "event.result = resultWithReplacement(" in after_hook
    notice_helper = _OPENCODE_PLUGIN_V2_TS.split(
        "const recordRefusalNotice = async", maxsplit=1
    )[1].split("await ctx.session.hook('prompt'", maxsplit=1)[0]
    assert "event.input" not in notice_helper
    assert "event.result" not in notice_helper
