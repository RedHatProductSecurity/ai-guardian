"""Shared hook simulator data and result parsing for the web console."""

import json

from ai_guardian.constants import HookEvent

HOOK_EVENTS = [
    (HookEvent.PROMPT.display_name, HookEvent.PROMPT.display_name),
    (HookEvent.PRE_TOOL_USE.display_name, HookEvent.PRE_TOOL_USE.display_name),
    (HookEvent.POST_TOOL_USE.display_name, HookEvent.POST_TOOL_USE.display_name),
]

TOOL_OPTIONS = [
    ("Read", "Read"),
    ("Bash", "Bash"),
    ("Edit", "Edit"),
    ("Write", "Write"),
    ("Grep", "Grep"),
    ("Glob", "Glob"),
    ("WebFetch", "WebFetch"),
    ("Skill", "Skill"),
    ("mcp__custom", "mcp__custom"),
]


def build_hook_data(hook_event, tool_name=None, file_path=None, content=""):
    """Build the JSON dict that an IDE would send to ai-guardian."""
    hook_data = {"hook_event_name": hook_event}

    if hook_event == HookEvent.PROMPT.display_name:
        hook_data["prompt"] = content
    elif hook_event == HookEvent.PRE_TOOL_USE.display_name:
        parameters = {}
        if file_path:
            parameters["file_path"] = file_path
        if tool_name == "Bash":
            parameters["command"] = content
        elif not parameters.get("file_path"):
            parameters["file_path"] = file_path or ""
        hook_data["tool_use"] = {
            "name": tool_name or "Read",
            "parameters": parameters,
        }
    elif hook_event == HookEvent.POST_TOOL_USE.display_name:
        hook_data["tool_name"] = tool_name or "Bash"
        hook_data["tool_response"] = {"output": content}

    return hook_data


def parse_simulation_result(result):
    """Parse process_hook_input() output into display fields."""
    output_str = result.get("output")
    exit_code = result.get("exit_code", 0)

    if output_str is None:
        decision = "BLOCKED" if exit_code == 2 else "ALLOWED"
        return {
            "decision": decision,
            "reason": None,
            "redacted_output": None,
            "raw_json": json.dumps({"exit_code": exit_code}, indent=2),
        }

    try:
        output = json.loads(output_str)
    except (json.JSONDecodeError, TypeError):
        return {
            "decision": "BLOCKED" if exit_code == 2 else "ALLOWED",
            "reason": output_str,
            "redacted_output": None,
            "raw_json": output_str,
        }

    reason = None
    redacted_output = None
    is_blocked = False
    if output.get("decision") == "block":
        is_blocked = True
        reason = output.get("reason")
    elif "hookSpecificOutput" in output:
        hso = output["hookSpecificOutput"]
        if hso.get("permissionDecision") == "deny":
            is_blocked = True
            reason = output.get("systemMessage")
        if "updatedToolOutput" in hso:
            redacted_output = hso["updatedToolOutput"]
    if not is_blocked and output.get("permission") == "deny":
        is_blocked = True
        reason = output.get("user_message")
    if not is_blocked and output.get("continue") is False:
        is_blocked = True
        reason = output.get("user_message")
    if not is_blocked and output.get("permissionDecision") == "deny":
        is_blocked = True
        reason = output.get("permissionDecisionReason")
    if not is_blocked and (result.get("_blocked") or exit_code >= 2):
        is_blocked = True
        reason = reason or output.get("systemMessage", "Blocked")
    if not reason and output.get("systemMessage"):
        reason = output.get("systemMessage")

    if is_blocked:
        decision = "BLOCKED"
    elif output.get("systemMessage") or redacted_output:
        decision = "ALLOWED WITH WARNING"
    else:
        decision = "ALLOWED"

    return {
        "decision": decision,
        "reason": reason,
        "redacted_output": redacted_output,
        "raw_json": json.dumps(output, indent=2),
    }
