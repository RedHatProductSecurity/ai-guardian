"""
Response formatting and IDE detection for AI Guardian hooks.

Handles multi-IDE response formatting (Claude Code, Cursor, GitHub Copilot,
Gemini CLI, Cline/ZooCode, Augment Code) and hook event detection.

This module provides backward-compatible wrapper functions that delegate
to the hook_adapters package. New code should use the adapter API directly.
"""

import logging
from enum import Enum

from ai_guardian.constants import HookEvent

logger = logging.getLogger(__name__)


_SECURITY_SYSTEM_MESSAGE = (
    "SECURITY RULES (from ai-guardian):\n"
    "- Never attempt to bypass, disable, or work around security protections\n"
    "- Never suggest ways to suppress or bypass security detection\n"
    "- Never suggest modifying security configuration files\n"
    "- Never explain how security protections can be circumvented\n"
    "- When a tool is blocked, report the block reason — do not find alternatives to access the content\n"
    "- If something is blocked, report the violation type and location to the user — use get_violations() if MCP is available to retrieve details"
)


class IDEType(Enum):
    """Supported IDE types with different output formats."""

    CLAUDE_CODE = "claude_code"  # Exit codes: 0=allow, 2=block
    CURSOR = "cursor"  # JSON: {"continue": bool, "user_message": str}
    GITHUB_COPILOT = "github_copilot"  # JSON: {"permissionDecision": "allow"|"deny"}
    GEMINI_CLI = "gemini_cli"  # JSON: {"decision": "deny", "reason": str}
    CLINE = "cline"  # JSON: {"cancel": true, "reason": str}
    ANTIGRAVITY = "antigravity"  # JSON: {"decision": "deny", "reason": str}
    KIRO = "kiro"  # Exit codes: 0=allow, 1=block; stdout→context, stderr→agent on error
    UNKNOWN = "unknown"  # Default to Claude Code format


def detect_ide_type(hook_data):
    """
    Detect which IDE is calling the hook based on input format.

    Delegates to the hook_adapters registry. Preserved for backward
    compatibility — new code should use detect_adapter() directly.

    Args:
        hook_data: Parsed JSON input from the IDE

    Returns:
        IDEType: The detected IDE type
    """
    from ai_guardian.hook_adapters import detect_adapter

    return detect_adapter(hook_data).ide_type


def format_response(
    ide_type,
    has_secrets,
    error_message=None,
    hook_event=HookEvent.PROMPT,
    warning_message=None,
    modified_output=None,
    violation_type=None,
    security_message=None,
):
    """
    Format the response based on IDE type and hook event.

    Delegates to the appropriate hook adapter. Preserved for backward
    compatibility — new code should use adapter.format_response() directly.

    Args:
        ide_type: IDEType enum value
        has_secrets: bool indicating if secrets were found (block vs allow)
        error_message: Optional error message for blocked responses
        hook_event: "prompt", "pretooluse", or "posttooluse" to determine response format
        warning_message: Optional warning message for log mode (allows execution but shows warning)
        modified_output: Optional modified tool output (for PostToolUse redaction)
        violation_type: Optional violation type string for daemon stats tracking
        security_message: Optional security rules message for prompt hook

    Returns:
        dict with 'output' (str to print), 'exit_code' (int), and optional
        daemon metadata: '_blocked' (True when has_secrets=True)
    """
    from ai_guardian.hook_adapters import get_adapter_by_ide_type

    if warning_message and not warning_message.lstrip().startswith("[ai-guardian]"):
        warning_message = f"[ai-guardian] {warning_message}"

    adapter = get_adapter_by_ide_type(ide_type)
    return adapter.format_response(
        has_secrets=has_secrets,
        error_message=error_message,
        hook_event=hook_event,
        warning_message=warning_message,
        modified_output=modified_output,
        violation_type=violation_type,
        security_message=security_message,
    )


def detect_hook_event(hook_data):
    """
    Detect which hook event triggered this call.

    Delegates to the hook_adapters registry. Preserved for backward
    compatibility — new code should use adapter.normalize_input() directly.

    Args:
        hook_data: Parsed JSON input from the IDE

    Returns:
        HookEvent: HookEvent.PROMPT, HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE, or HookEvent.BEFORE_READ_FILE
    """
    from ai_guardian.hook_adapters import detect_adapter

    adapter = detect_adapter(hook_data)
    normalized = adapter.normalize_input(hook_data)
    return normalized.event
