"""User experience contracts for SSRF destination policy (#2482)."""

from ai_guardian.scanners.ssrf import SSRFProtector


def test_user_experience_unspecified_ipv4_destination_is_blocked():
    """
    USER EXPERIENCE: a URL targeting 0.0.0.0/8 is denied as immutable SSRF.

    The user sees the normal SSRF block message and the detected destination.
    """
    protector = SSRFProtector()

    should_block, message = protector.check("Bash", {"command": "curl http://0.0.0.1/"})

    assert should_block
    assert message is not None
    assert "SSRF PATTERN DETECTED" in message
    assert "0.0.0.1" in message
    assert "Reason: private IP address '0.0.0.1'" in message


def test_user_experience_bind_address_is_allowed():
    """A bind/listen command using 0.0.0.0 is not treated as a URL request."""
    protector = SSRFProtector()

    should_block, message = protector.check(
        "Bash", {"command": "python -m http.server --bind 0.0.0.0 8000"}
    )

    assert not should_block
    assert message is None
