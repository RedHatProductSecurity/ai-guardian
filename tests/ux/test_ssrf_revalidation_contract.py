"""User experience contracts for SSRF destination policy (#2482, #2559).

These checks classify synthetic inputs only; no URL is ever executed.
Manual verification: use a mocked tool executor in an isolated agent environment,
submit the tool inputs below, confirm the normal SSRF denial identifies the URL,
and confirm public controls pass this scanner without executing any request.
These contracts do not establish live exploitability.
"""

import socket

import pytest

from ai_guardian.scanners.ssrf import SSRFProtector


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("SSRF UX classification attempted DNS or network access")

    for name in (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "create_connection",
    ):
        monkeypatch.setattr(socket, name, forbidden)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)


def test_user_experience_unspecified_ipv4_destination_is_blocked():
    """
    USER EXPERIENCE: a URL targeting 0.0.0.0/8 is denied as immutable SSRF.

    The user sees the normal SSRF block message and the detected destination.
    """
    protector = SSRFProtector({"enabled": True})

    should_block, message = protector.check("Bash", {"command": "curl http://0.0.0.1/"})

    assert should_block
    assert message is not None
    assert "SSRF PATTERN DETECTED" in message
    assert "0.0.0.1" in message
    assert "Reason: private IP address '0.0.0.1'" in message


def test_user_experience_bind_address_is_allowed():
    """A bind/listen command using 0.0.0.0 is not treated as a URL request."""
    protector = SSRFProtector({"enabled": True})

    should_block, message = protector.check(
        "Bash", {"command": "python -m http.server --bind 0.0.0.0 8000"}
    )

    assert not should_block
    assert message is None


@pytest.mark.parametrize(
    "address",
    [
        "::ffff:a9fe:a9fe",  # Mapped IPv4 control.
        "2002:a9fe:a9fe::1",  # 6to4 routing endpoint.
        "2001:0:a9fe:a9fe:0:f227:fefe:fefe",  # Teredo server.
        "2001:0:808:808:0:f227:5601:5601",  # Teredo client.
    ],
)
@pytest.mark.parametrize("action", ["block", "warn", "log-only"])
@pytest.mark.parametrize("tool_name", ["Bash", "WebFetch"])
def test_user_experience_embedded_metadata_is_denied(address, action, tool_name):
    """USER EXPERIENCE: embedded protected endpoints show the normal immutable denial.

    1. An agent proposes a Bash or WebFetch call with a transition-format URL.
    2. The scanner recognizes an embedded protected IPv4 endpoint.
    3. The operation is denied without a downgrade or approval prompt.
    The user sees the existing SSRF heading, reason, and original IPv6 URL.
    """
    protector = SSRFProtector({"enabled": True, "action": action})
    url = f"https://[{address}]/resource"
    tool_input = (
        {"command": f'curl --url "{url}"'} if tool_name == "Bash" else {"url": url}
    )

    should_block, message = protector.check(tool_name, tool_input)

    assert should_block
    assert protector.last_is_immutable
    assert message is not None
    assert "🚨 BLOCKED BY POLICY" in message
    assert "🚨 SSRF PATTERN DETECTED" in message
    assert f"Reason: private IP address '{address}'" in message
    assert f"URL: {url}" in message
    if action != "block":
        assert "(immutable — cannot be downgraded to warn/log-only)" in message
    if tool_name == "Bash":
        assert protector.findings[0]["is_immutable"] is True
        assert protector.findings[0]["effective_action"] == "block"


@pytest.mark.parametrize(
    "address",
    [
        "2606:4700:4700::1111",
        "2002:808:808::a00:1",
        "2001:0:808:808:0:f227:fefe:fefe",
        "2001:db8::a00:1",
    ],
)
@pytest.mark.parametrize("tool_name", ["Bash", "WebFetch"])
def test_user_experience_public_and_native_ipv6_controls_are_allowed(
    address, tool_name
):
    """USER EXPERIENCE: public endpoints get no SSRF warning or denial."""
    protector = SSRFProtector({"enabled": True})
    url = f"https://[{address}]/resource"
    tool_input = {"command": f"curl {url}"} if tool_name == "Bash" else {"url": url}

    assert protector.check(tool_name, tool_input) == (False, None)
    assert not protector.last_is_immutable


def test_user_experience_allowed_hostname_cannot_hide_embedded_redirect_destination():
    """A network-aware caller gets an immutable denial for a resolved redirect hop.

    The hook does not discover redirects. The caller supplies fresh addresses
    before each connection and must enforce the returned denial itself.
    """
    protector = SSRFProtector(
        {"enabled": True, "allowed_domains": ["public.example", "redirect.example"]}
    )
    initial = "https://public.example/start"
    redirect = "https://redirect.example/resource"
    address = "2002:a9fe:a9fe::1"

    result = protector.check_redirect_chain(
        [initial, redirect], {initial: ["1.1.1.1"], redirect: ["8.8.8.8", address]}
    )

    assert result == (
        True,
        f"domain 'redirect.example' resolves to blocked IP address '{address}'",
        True,
    )
