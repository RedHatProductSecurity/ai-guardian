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
    if violation_type not in {"canary_detected", "suspected_password"}:
        assert snippet
    else:
        assert snippet == ""


def test_heuristic_details_offer_private_review_not_candidate_enrollment():
    """USER EXPERIENCE: suspected content → private review, not a confirmed secret.

    No raw value, source pattern, or persistent exception snippet is displayed.
    This guidance is only for the trusted Details view, never an agent protocol.
    """
    instructions, snippet = get_resolution_instructions(
        {
            "violation_type": "suspected_password",
            "blocked": {
                "matched_text": "SYNTHETIC_CANDIDATE",
                "file_path": "SYNTHETIC_CANDIDATE",
            },
            "suggestion": {"pattern": "SYNTHETIC_CANDIDATE"},
        }
    )
    assert instructions == (
        "Review the reported location privately. This is suspected password-like "
        "content, not a confirmed secret; candidate values are withheld. "
        "Use the trusted Console for policy review. No source or persistent "
        "exception is generated for this finding."
    )
    assert snippet == ""
    assert "SYNTHETIC_CANDIDATE" not in instructions


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


@pytest.mark.parametrize(
    "subreason",
    [
        "missing_argument",
        "empty_argument",
        "invalid_argument",
        "conflicting_arguments",
        "normalization_failure",
        "workspace_unavailable",
    ],
)
def test_input_failure_mcp_guidance_explains_validation_not_admin_permission(subreason):
    """USER EXPERIENCE: input failure -> safe cause, not misleading admin advice.

    Manual verification: inspect an isolated malformed-input fixture in Console,
    then query its exact violation ID through MCP. Both must show the same vetted
    classification. OpenCode's model-facing refusal stays fixed and stage-specific;
    it must not forward the bridge's private error or suggest another attempt.
    """
    from unittest.mock import patch

    pytest.importorskip("mcp")
    from ai_guardian.mcp.server import create_server
    from ai_guardian.violations.tool_diagnostics import INPUT_FAILURE_GUIDANCE

    violation = {
        "violation_type": "tool_permission",
        "blocked": {
            "tool_name": "Read",
            "is_immutable": True,
            "reason": "PRIVATE_REASON",
            "input_diagnostics": {
                "schema_version": 1,
                "subreason": subreason,
                "native_tool_name": "read",
                "canonical_tool_name": "Read",
                "expected_field": "path",
                "argument_shape": {"limit": "integer"},
                "raw_payload": "PRIVATE_PAYLOAD",
            },
        },
    }
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        logger.return_value.get_recent_violations.return_value = [violation]
        entry = (
            create_server()._tool_manager._tools["get_violations"].fn()["violations"][0]
        )
    assert entry["tool"] == "Read"
    assert entry["input_diagnostics"]["subreason"] == subreason
    assert entry["suggestion"] == INPUT_FAILURE_GUIDANCE
    assert "admin" not in entry["suggestion"]
    assert "PRIVATE_" not in str(entry)


def test_input_diagnostic_console_copy_keeps_correlation_and_unknown_metadata():
    """USER EXPERIENCE: Details/copy -> useful safe shape and explicit unknowns.

    Legacy records stay readable. Immutable input failures never gain permission
    override actions or a copyable suppression rule from these diagnostics.
    """
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.web.pages.violations import _format_violation_markdown

    text = _format_violation_markdown(
        {
            "id": "viol_2627abcd",
            "violation_type": "tool_permission",
            "blocked": {
                "tool_name": "Read",
                "reason": "missing required parameter",
                "is_immutable": True,
            },
            "context": {"tool_use_id": "call_2627test", "session_id": "ses_2627test"},
        }
    )
    assert "**Input Subreason:** missing_argument" in text
    assert "**Argument Shape:** unknown" in text
    assert "**Host Version:** unknown" in text
    assert "call_2627test" in text
    assert "ses_2627test" in text
    assert "Suggested Rule" not in text
