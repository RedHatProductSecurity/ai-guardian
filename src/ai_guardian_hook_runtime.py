"""Dependency-light hook launcher and failure-response boundary.

This module intentionally lives outside the ``ai_guardian`` package.  The
package imports most of the scanner stack during initialization, so an
editable-checkout syntax or import error can otherwise prevent the hook
process from reading stdin or applying its configured failure policy.
"""

import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

HOOK_FAILURE_MESSAGE = (
    "AI Guardian hook process failed; operation blocked by " "on_scan_error=block."
)
HOOK_FAILURE_REASON = "Operation blocked by ai-guardian: hook process failure"

_JSON_PROTOCOLS = {
    "claude",
    "codex",
    "cursor",
    "copilot",
    "gemini",
    "cline",
    "antigravity",
    "pi",
    "opencode",
    "augment",
    "crush",
    "unknown",
}


def _read_json_object(path: Path) -> Optional[Dict[str, Any]]:
    """Read a JSON object without importing the application package."""
    try:
        with path.open("r", encoding="utf-8") as config_file:
            value = json.load(config_file)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _global_config_path() -> Path:
    config_dir = os.environ.get("AI_GUARDIAN_CONFIG_DIR")
    if not config_dir:
        config_dir = os.environ.get("AI_GUARDIAN_HOME")
    if config_dir:
        return Path(config_dir).expanduser() / "ai-guardian.json"

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "ai-guardian" / "ai-guardian.json"
    return Path.home() / ".config" / "ai-guardian" / "ai-guardian.json"


def get_on_scan_error_action(config: Optional[Dict[str, Any]] = None) -> str:
    """Return the configured process/scanner error policy.

    ``on_scan_error`` is global-only, so the bootstrap path reads the global
    file and the two supported SDK overlay environment variables.  Invalid or
    unreadable configuration preserves the established fail-open default.
    """
    if config is not None:
        value = config.get("on_scan_error")
        return value if value in ("allow", "block") else "allow"

    effective = _read_json_object(_global_config_path()) or {}

    overlay_path = os.environ.get("AI_GUARDIAN_CONFIG_OVERLAY")
    if overlay_path:
        overlay = _read_json_object(Path(overlay_path).expanduser())
        if overlay is not None:
            effective.update(overlay)

    inline_overlay = os.environ.get("AI_GUARDIAN_CONFIG_INLINE")
    if inline_overlay:
        try:
            overlay = json.loads(inline_overlay)
        except (TypeError, ValueError):
            overlay = None
        if isinstance(overlay, dict):
            effective.update(overlay)

    value = effective.get("on_scan_error")
    return value if value in ("allow", "block") else "allow"


def _canonical_protocol(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("-", "_")
    aliases = {
        "agy": "antigravity",
        "antigravity_cli": "antigravity",
        "claude_code": "claude",
        "github_copilot": "copilot",
        "gemini_cli": "gemini",
        "zoocode": "cline",
        "aiderdesk": "kiro",
        "openclaw": "kiro",
    }
    return aliases.get(key, key) if key else None


def _compact(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(char for char in value.lower() if char.isalnum())


def _protocol_for_hook(hook_data: Optional[Dict[str, Any]]) -> str:
    """Identify a response protocol using only fields safe to inspect here."""
    hook_data = hook_data if isinstance(hook_data, dict) else {}

    for key in ("_ide_type", "ide_type"):
        protocol = _canonical_protocol(hook_data.get(key))
        if protocol:
            return protocol

    protocol = _canonical_protocol(os.environ.get("AI_GUARDIAN_IDE_TYPE"))
    if protocol:
        return protocol

    if "conversationId" in hook_data and (
        "workspacePaths" in hook_data or "toolCall" in hook_data
    ):
        return "antigravity"
    if "cursor_version" in hook_data or "hook_name" in hook_data:
        return "cursor"
    if "toolName" in hook_data or ("timestamp" in hook_data and "cwd" in hook_data):
        return "copilot"
    if "clineVersion" in hook_data:
        return "cline"
    if "agent_action_name" in hook_data:
        return "windsurf"
    if "kiro_hook_type" in hook_data or "kiro_version" in hook_data:
        return "kiro"

    source = _canonical_protocol(hook_data.get("hook_source"))
    if source in ("opencode", "pi"):
        return source
    if "opencode_version" in hook_data:
        return "opencode"
    if "pi_version" in hook_data:
        return "pi"

    event = _compact(
        hook_data.get("hook_event_name")
        or hook_data.get("hookEventName")
        or hook_data.get("hookName")
    )
    if any(key in hook_data for key in ("model", "turn_id")) and event:
        return "codex"
    if "transcript_path" in hook_data and event not in {
        "userpromptsubmit",
        "pretooluse",
        "posttooluse",
        "sessionstart",
        "sessionend",
        "postcompact",
    }:
        return "gemini"

    return "claude"


def _event_kind(hook_data: Optional[Dict[str, Any]]) -> str:
    hook_data = hook_data if isinstance(hook_data, dict) else {}
    raw_event = (
        hook_data.get("hook_event_name")
        or hook_data.get("hookEventName")
        or hook_data.get("hook_name")
        or hook_data.get("hookName")
        or hook_data.get("agent_action_name")
        or hook_data.get("event")
        or hook_data.get("_hook_event")
        or os.environ.get("AI_GUARDIAN_HOOK_EVENT")
    )
    event = _compact(raw_event)

    if event in {"posttoolusefailure"}:
        return "failure"
    if event in {
        "pretooluse",
        "beforeshellexecution",
        "beforemcpexecution",
        "beforetool",
        "permissionrequest",
        "prereadcode",
        "prewritecode",
        "preruncommand",
    }:
        return "pre"
    if event in {"beforereadfile", "beforetabfileread"}:
        return "read"
    if event in {
        "posttooluse",
        "aftershellexecution",
        "aftermcpexecution",
        "aftertool",
        "postinvocation",
        "postruncommand",
        "postreadcode",
        "postwritecode",
        "postmcptooluse",
        "agentstop",
    }:
        return "post"
    if event in {
        "userspromptsubmit",
        "userpromptsubmit",
        "beforesubmitprompt",
        "beforeagent",
        "preinvocation",
        "preuserprompt",
    }:
        return "prompt"
    if event in {
        "sessionstart",
        "sessionend",
        "postcompact",
        "precompact",
        "stop",
        "interrupt",
        "subagentstart",
        "subagentstop",
        "afterfileedit",
        "aftertabfileedit",
        "afteragentresponse",
        "afteragentthought",
        "workspaceopen",
    }:
        return "lifecycle"
    if not event:
        if any(key in hook_data for key in ("tool_response", "tool_output")):
            return "post"
        if any(key in hook_data for key in ("toolName", "tool_name", "tool_use")):
            return "pre"
        if "toolCall" in hook_data:
            return "pre"
    return "prompt"


def _event_display_name(kind: str) -> str:
    return {
        "pre": "PreToolUse",
        "read": "PreToolUse",
        "post": "PostToolUse",
        "failure": "PostToolUseFailure",
        "prompt": "UserPromptSubmit",
        "lifecycle": "SessionStart",
    }.get(kind, "UserPromptSubmit")


def _json(value: Dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"))


def _base_failure_response(kind: str, blocked: bool) -> Tuple[Optional[str], int]:
    if not blocked:
        return None, 0
    event_name = _event_display_name(kind)
    if kind in ("pre", "read"):
        response = {
            "systemMessage": HOOK_FAILURE_MESSAGE,
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "permissionDecision": "deny",
                "additionalContext": HOOK_FAILURE_REASON,
            },
        }
    else:
        response = {"decision": "block", "reason": HOOK_FAILURE_REASON}
    return _json(response), 0


def build_failure_response(
    hook_data: Optional[Dict[str, Any]], action: Optional[str] = None
) -> Dict[str, Any]:
    """Build a protocol-safe result for an import, daemon, or pipeline failure."""
    action = action if action in ("allow", "block") else get_on_scan_error_action()
    blocked = action == "block"
    protocol = _protocol_for_hook(hook_data)
    kind = _event_kind(hook_data)
    result: Dict[str, Any] = {"output": None, "exit_code": 0, "_hook_failure": True}

    if protocol == "cursor":
        if kind in ("pre", "read"):
            payload: Dict[str, Any] = {"permission": "deny" if blocked else "allow"}
            if kind == "read":
                payload["continue"] = not blocked
            if blocked:
                payload["user_message"] = HOOK_FAILURE_MESSAGE
                payload["agent_message"] = HOOK_FAILURE_REASON
        elif kind == "failure" or kind == "lifecycle":
            payload = {}
        else:
            payload = {"continue": not blocked}
            if blocked:
                payload["user_message"] = HOOK_FAILURE_MESSAGE
        result["output"] = _json(payload)
    elif protocol == "codex":
        if blocked:
            result["output"], result["exit_code"] = _base_failure_response(kind, True)
        else:
            result["output"] = "{}"
    elif protocol == "copilot":
        if kind == "pre":
            payload = {}
            if blocked:
                payload = {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": HOOK_FAILURE_MESSAGE,
                    "additionalContext": HOOK_FAILURE_REASON,
                }
            result["output"] = _json(payload)
        elif blocked:
            result["exit_code"] = 2
            result["_failure_message"] = HOOK_FAILURE_MESSAGE
    elif protocol == "gemini":
        result["output"] = (
            _json({"decision": "deny", "reason": HOOK_FAILURE_MESSAGE})
            if blocked
            else "{}"
        )
    elif protocol == "cline":
        result["output"] = (
            _json({"cancel": True, "errorMessage": HOOK_FAILURE_MESSAGE})
            if blocked
            else "{}"
        )
    elif protocol == "antigravity":
        if kind == "pre":
            result["output"] = _json(
                {
                    "decision": "deny" if blocked else "ask",
                    **({"reason": HOOK_FAILURE_MESSAGE} if blocked else {}),
                }
            )
        else:
            result["output"] = "{}"
    elif protocol in ("kiro", "windsurf"):
        if blocked:
            result["exit_code"] = 2 if kind in ("pre", "read") else 1
            result["_failure_message"] = HOOK_FAILURE_MESSAGE
    elif protocol in {"pi", "opencode", "augment", "crush"}:
        result["output"], result["exit_code"] = _base_failure_response(kind, blocked)
        if not blocked:
            result["output"] = "{}"
    else:
        result["output"], result["exit_code"] = _base_failure_response(kind, blocked)

    if blocked:
        result["_blocked"] = True
    return result


def ensure_hook_response(
    hook_data: Optional[Dict[str, Any]],
    response: Any,
    action: Optional[str] = None,
) -> Dict[str, Any]:
    """Reject malformed daemon responses before they reach the host agent."""
    if not isinstance(response, dict):
        return build_failure_response(hook_data, action)

    exit_code = response.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return build_failure_response(hook_data, action)

    normalized = dict(response)
    output = normalized.get("output")
    protocol = _protocol_for_hook(hook_data)
    kind = _event_kind(hook_data)
    json_protocol = protocol in _JSON_PROTOCOLS

    if isinstance(output, dict):
        if not json_protocol:
            return build_failure_response(hook_data, action)
        normalized["output"] = _json(output)
        output = normalized["output"]
    elif output is not None and not isinstance(output, str):
        return build_failure_response(hook_data, action)

    if json_protocol and output:
        try:
            parsed = json.loads(output)
        except (TypeError, ValueError):
            return build_failure_response(hook_data, action)
        if not isinstance(parsed, dict):
            return build_failure_response(hook_data, action)
    elif json_protocol and output == "":
        return build_failure_response(hook_data, action)

    if protocol == "cursor" and output is None:
        return build_failure_response(hook_data, action)
    if protocol == "codex" and kind == "post" and not output:
        return build_failure_response(hook_data, action)
    if protocol in {"gemini", "cline", "antigravity"} and output is None:
        return build_failure_response(hook_data, action)

    return normalized


def _is_hook_invocation(argv: list) -> bool:
    if not argv:
        return True
    if any(arg in ("--help", "-h", "--version", "-v") for arg in argv):
        return False
    option_with_value = {"--ide", "--hook-event"}
    skip_value = False
    for arg in argv:
        if skip_value:
            skip_value = False
            continue
        if arg in option_with_value:
            skip_value = True
            continue
        if arg.startswith("-"):
            continue
        return False
    return True


def _set_hook_overrides(argv: list) -> None:
    for index, arg in enumerate(argv):
        if arg == "--ide" and index + 1 < len(argv):
            os.environ["AI_GUARDIAN_IDE_TYPE"] = argv[index + 1]
        elif arg == "--hook-event" and index + 1 < len(argv):
            os.environ["AI_GUARDIAN_HOOK_EVENT"] = argv[index + 1]


def _emit_result(result: Dict[str, Any]) -> int:
    failure_message = result.get("_failure_message")
    if failure_message:
        print(failure_message, file=sys.stderr)
    output = result.get("output")
    if isinstance(output, dict):
        output = _json(output)
    if output:
        print(output, flush=True)
    return int(result.get("exit_code", 0))


def main():
    """Run the normal CLI, with a protocol-safe startup fallback for hooks."""
    argv = sys.argv[1:]
    if not _is_hook_invocation(argv):
        try:
            from ai_guardian.cli import main as cli_main
        except Exception:
            print("AI Guardian could not start.", file=sys.stderr)
            return 1
        return cli_main()

    _set_hook_overrides(argv)
    hook_data = None
    stdin_content = ""
    try:
        stdin_content = sys.stdin.read()
        parsed = json.loads(stdin_content)
        if isinstance(parsed, dict):
            hook_data = parsed
    except (OSError, TypeError, ValueError):
        hook_data = None

    action = get_on_scan_error_action()
    original_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_content)
    try:
        try:
            from ai_guardian.cli import main as cli_main
        except Exception:
            return _emit_result(build_failure_response(hook_data, action))

        try:
            return cli_main()
        except Exception:
            return _emit_result(build_failure_response(hook_data, action))
    finally:
        sys.stdin = original_stdin


__all__ = [
    "HOOK_FAILURE_MESSAGE",
    "build_failure_response",
    "ensure_hook_response",
    "get_on_scan_error_action",
    "main",
]
