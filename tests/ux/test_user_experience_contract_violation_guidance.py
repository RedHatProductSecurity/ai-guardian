"""UX contracts for actionable violation resolution guidance.

These contracts describe what a user should see in the Web Console:
specific review steps for each finding, a copyable config snippet when safe,
and explicit investigation-only guidance for findings that must not be
suppressed.
"""

import inspect

import pytest

from ai_guardian.constants import ALL_VIOLATION_TYPES
from ai_guardian.violations.guidance import (
    IMMUTABLE_VIOLATION_NOTICE,
    get_resolution_instructions,
)


@pytest.mark.parametrize("violation_type", ALL_VIOLATION_TYPES)
def test_every_violation_type_has_user_facing_resolution_guidance(violation_type):
    """
    USER EXPERIENCE: every logged violation → actionable Details guidance.

    The Web Console and CLI both call the shared resolver. Enum-backed types
    must not fall through to an empty or generic-only resolution section.
    """
    violation = {
        "violation_type": violation_type,
        "blocked": {
            "file_path": "example.py",
            "pattern": "safe-example",
            "matched_text": "safe-example",
            "rule_id": "EXAMPLE-001",
            "tool_value": "https://example.com",
            "pii_types": ["email"],
            "redacted_types": ["api-key"],
            "secret_type": "api-key",
            "denied_directory": "example-dir",
        },
        "suggestion": {
            "rule": {"matcher": "Read", "mode": "allow", "patterns": ["docs/*"]}
        },
    }

    instructions, snippet = get_resolution_instructions(violation)

    assert instructions
    if violation_type != "canary_detected":
        assert snippet


def test_tool_permission_details_show_rule_instruction_and_snippet():
    """
    USER EXPERIENCE: tool permission violation → permissions.rules guidance.

    The Details view must tell users where the rule belongs and provide the
    suggested JSON rule without changing hook or MCP response payloads.
    """
    instructions, snippet = get_resolution_instructions(
        {
            "violation_type": "tool_permission",
            "blocked": {},
            "suggestion": {
                "rule": {
                    "matcher": "Bash",
                    "mode": "allow",
                    "patterns": ["safe-command"],
                }
            },
        }
    )

    assert "permissions.rules" in instructions
    assert '"matcher": "Bash"' in snippet
    assert '"safe-command"' in snippet


def test_immutable_violation_shows_notice_without_override_guidance():
    """
    USER EXPERIENCE: immutable protection → investigation details only.

    Immutable findings keep their reason and location in the Details view, but
    must not expose remediation snippets or override actions.
    """
    instructions, snippet = get_resolution_instructions(
        {
            "violation_type": "tool_permission",
            "blocked": {
                "is_immutable": True,
                "file_path": "/protected/config.json",
                "reason": "immutable deny: protected path",
            },
            "suggestion": {
                "rule": {"matcher": "Read", "mode": "allow", "patterns": ["*"]}
            },
        }
    )

    assert instructions == IMMUTABLE_VIOLATION_NOTICE
    assert snippet == ""


def test_canary_details_are_investigation_only():
    """
    USER EXPERIENCE: canary finding → investigate, never allowlist.

    Canary detections indicate possible data exposure and must not expose an
    Always Allow or copyable suppression snippet.
    """
    instructions, snippet = get_resolution_instructions(
        {
            "violation_type": "canary_detected",
            "blocked": {"matched_text": "CANARY_VALUE"},
        }
    )

    assert "Do not suppress" in instructions
    assert "canary_detection.tokens" in instructions
    assert snippet == ""


@pytest.mark.parametrize(
    "violation_type",
    ["prompt_injection_in_transcript", "annotation_suppressed"],
)
def test_audit_filter_types_explain_their_status_without_suppression(
    violation_type,
):
    """
    USER EXPERIENCE: audit-only filter → explain status, no misleading action.
    """
    instructions, snippet = get_resolution_instructions(
        {"violation_type": violation_type, "blocked": {}}
    )

    assert instructions
    assert snippet == ""


def test_resolution_guidance_stays_out_of_agent_protocols():
    """Remediation text remains limited to user-facing console surfaces."""
    import ai_guardian.hook_processing as hook_processing
    import ai_guardian.mcp.server as mcp_server

    assert "get_resolution_instructions" not in inspect.getsource(hook_processing)
    assert "get_resolution_instructions" not in inspect.getsource(mcp_server)
