"""UX contracts for OpenCode immutable configuration protection (#2425)."""

import json
from io import StringIO
from unittest.mock import patch

import pytest

import ai_guardian
from ai_guardian.setup.hooks import _OPENCODE_PLUGIN_TS, _OPENCODE_PLUGIN_V2_TS
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


def test_opencode_v1_blocked_first_prompt_keeps_a_safe_nonempty_session_turn():
    """
    USER EXPERIENCE: OpenCode V1 blocked first prompt -> safe refusal, same session.

    Scenario:
    1. The user opens a new session while an older session exists.
    2. The first prompt triggers an AI Guardian block.
    3. V1's chat.message hook replaces every submitted part with a fixed refusal
       notice before OpenCode constructs the model request.
    4. The user submits a safe follow-up, then compares a later blocked prompt.

    Expected User Experience:
    - OpenCode receives a nonempty safe message for the new session rather than
      an empty prompt that can discard the newly selected session.
    - The original text, attachments, scanner reason, and other prompt data are
      absent from the replacement, toast, and refusal text.
    - A safe follow-up is scanned and remains in that same session.
    - V1 has no supported prompt-cancel/noReply result, so it may run a model turn
      on the fixed, non-sensitive refusal notice; the original prompt is withheld.

    Manual verification with OpenCode V1 (1.x):
    1. Keep an older session available, then create a new session.
    2. Submit a synthetic test prompt that triggers the configured block.
    3. Confirm the new session stays selected, the toast explains the refusal,
       and no original text or attachment reaches the model.
    4. Submit a safe follow-up and confirm it works in the same session.
    5. Trigger a later block and compare that the same safe replacement is used.
    6. Record the exact V1 version when manually validating this compatibility path.
    """
    prompt_hook = _OPENCODE_PLUGIN_TS.split("async 'chat.message'", maxsplit=1)[
        1
    ].split("async 'tool.execute.after'", maxsplit=1)[0]
    expected_notice = (
        "AI Guardian refused the previous prompt. "
        "The original prompt was not sent to the model. "
        "Do not answer or continue that request. "
        "Ask the user to provide a new prompt without the sensitive or blocked content."
    )

    assert expected_notice in _OPENCODE_PLUGIN_TS
    assert "output.parts.splice(0, output.parts.length, {" in prompt_hook
    assert "id: firstPart.id" in prompt_hook
    assert "sessionID: input.sessionID" in prompt_hook
    assert "messageID: firstPart.messageID" in prompt_hook
    assert "synthetic: true" in prompt_hook
    assert "output.parts.length = 0" not in prompt_hook
    assert "result.error" not in prompt_hook
    assert "fixed refusal notice was substituted" in prompt_hook


def test_opencode_v2_blocked_prompt_is_replaced_before_admission():
    """
    USER EXPERIENCE: Blocked OpenCode V2 prompt -> safe input admitted to same session.

    Scenario:
    1. An older session exists; the user creates a new V2 session and submits a
       first prompt that AI Guardian blocks.
    2. The V2 prompt hook replaces the owned prompt draft with one fixed refusal
       notice and removes files, agent mentions, and selected skills.
    3. OpenCode admits only that safe replacement into the requested session; the
       hook does not throw or add a duplicate synthetic entry.
    4. The user sends a safe follow-up in that same session, then compares a later
       blocked prompt.

    Expected User Experience:
    - The transcript contains the fixed refusal as the admitted user input, not
      as a separate synthetic entry.
    - The blocked text, attachments, agent/skill selections, detection details,
      and bridge error are absent from admitted input.
    - OpenCode may run the model on the fixed notice and produce a generic
      response; the original prompt is never processed by the model.
    - A safe follow-up and any later block remain in the same selected session.

    Exact notice:
    "AI Guardian refused the previous prompt. The original prompt was not sent
    to the model. Do not answer or continue that request. Ask the user to
    provide a new prompt without the sensitive or blocked content."

    Manual verification with OpenCode V2 (the reporter confirmed V2; exact patch
    version and OS are not yet known):
    1. Keep an older session available and create a new session with the generated
       AI Guardian plugin loaded.
    2. Submit a synthetic test prompt that triggers a configured AI Guardian block.
    3. Confirm the new session remains selected and its user transcript contains
       only the fixed refusal notice; no original text or attachment is admitted.
    4. Confirm OpenCode may generate a response to that safe notice, then submit a
       safe follow-up and verify it stays in the same session.
    5. Trigger a later block and confirm it does not switch sessions either.
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
    assert "event.prompt = {" in prompt_hook
    assert "files: []" in prompt_hook
    assert "agents: []" in prompt_hook
    assert "skills: []" in prompt_hook
    assert "await recordRefusalNotice(" not in prompt_hook
    assert "result.error" not in prompt_hook
    assert "throw new Error('Blocked by ai-guardian')" not in prompt_hook


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
