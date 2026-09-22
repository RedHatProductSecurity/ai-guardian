"""User-facing contract tests for pluggable code security inspection."""

from types import SimpleNamespace

from ai_guardian.hook_events.scanners import run_code_security_scan
from ai_guardian.scanners.post_scan_filters import build_detailed_warn_message

CODE = "result = eval(user_input)\n"


def test_warn_mode_allows_the_operation_with_a_visible_warning():
    """
    USER EXPERIENCE: code finding in warn mode -> operation is allowed with warning.

    The hook response layer owns the final allow/block decision. The normalized
    result must retain the configured action and enough location data for the
    standard warning shown to the user.
    """
    result = run_code_security_scan(
        CODE,
        "example.py",
        config={"enabled": True, "action": "warn", "inspectors": ["ast"]},
    )
    message = build_detailed_warn_message(
        SimpleNamespace(violation_type="code_security"), result, "example.py"
    )

    assert result.detected
    assert result.extra["action"] == "warn"
    assert "example.py:1" in message
    assert "execution allowed" in message


def test_block_mode_retains_blocking_decision():
    """
    USER EXPERIENCE: code finding in block mode -> the hook can deny the write.
    """
    result = run_code_security_scan(
        CODE,
        "example.py",
        config={"enabled": True, "action": "block", "inspectors": ["ast"]},
    )

    assert result.detected
    assert result.should_block
    assert result.extra["action"] == "block"
