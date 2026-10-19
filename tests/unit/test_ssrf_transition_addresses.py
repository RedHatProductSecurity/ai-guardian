"""No-network regression coverage for embedded IPv4 destination policy (#2559)."""

import ipaddress
import socket

import pytest

from ai_guardian.scanners.ssrf import SSRFProtector

ADDRESS_FORMATS = ["native", "mapped", "6to4", "teredo-server", "teredo-client"]
ENTRY_POINTS = ["literal", "resolved", "redirect-literal", "redirect-resolved"]

# Include range boundaries, metadata singletons, and adjacent allowed controls.
# "Allowed" means allowed by the existing explicit policy, not IANA globalness.
DESTINATION_POLICY = [
    ("0.0.0.0", True),
    ("0.255.255.255", True),
    ("1.0.0.0", False),
    ("9.255.255.255", False),
    ("10.0.0.0", True),
    ("10.255.255.255", True),
    ("11.0.0.0", False),
    ("126.255.255.255", False),
    ("127.0.0.0", True),
    ("127.255.255.255", True),
    ("128.0.0.0", False),
    ("169.253.255.255", False),
    ("169.254.0.0", True),
    ("169.254.169.254", True),
    ("169.254.255.255", True),
    ("169.255.0.0", False),
    ("172.15.255.255", False),
    ("172.16.0.0", True),
    ("172.31.255.255", True),
    ("172.32.0.0", False),
    ("192.167.255.255", False),
    ("192.168.0.0", True),
    ("192.168.255.255", True),
    ("192.169.0.0", False),
    ("100.100.100.199", False),
    ("100.100.100.200", True),
    ("100.100.100.201", False),
    ("192.0.0.191", False),
    ("192.0.0.192", True),
    ("192.0.0.193", False),
    ("8.8.8.8", False),
    ("1.1.1.1", False),
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Classification must never resolve names or execute network requests."""

    def forbidden(*_args, **_kwargs):
        pytest.fail("SSRF classification attempted DNS or network access")

    for name in (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "create_connection",
    ):
        monkeypatch.setattr(socket, name, forbidden)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)


def _teredo_address(server, client, flags=0, port=3544):
    """Encode independent synthetic fixtures from the RFC 4380 address layout."""
    value = (
        (0x20010000 << 96)
        | (int(ipaddress.IPv4Address(server)) << 64)
        | (flags << 48)
        | ((port ^ 0xFFFF) << 32)
        | (int(ipaddress.IPv4Address(client)) ^ 0xFFFFFFFF)
    )
    return str(ipaddress.IPv6Address(value))


def _destination_address(ipv4, address_format):
    if address_format == "native":
        return ipv4
    if address_format == "mapped":
        return str(ipaddress.IPv6Address(f"::ffff:{ipv4}"))
    if address_format == "6to4":
        return str(
            ipaddress.IPv6Address(
                (0x2002 << 112) | (int(ipaddress.IPv4Address(ipv4)) << 80) | 1
            )
        )
    if address_format == "teredo-server":
        return _teredo_address(ipv4, "1.1.1.1")
    if address_format == "teredo-client":
        return _teredo_address("8.8.8.8", ipv4)
    raise AssertionError(f"Unknown address format: {address_format}")


def _url(address):
    host = f"[{address}]" if ":" in address else address
    return f"https://{host}/resource"


def _check_entry_point(protector, address, entry_point):
    public_url = "https://public.example/start"
    target_url = "https://target.example/resource"
    if entry_point == "literal":
        return protector._check_url(_url(address))
    if entry_point == "resolved":
        return protector.check_resolved_destination(target_url, ["1.1.1.1", address])
    if entry_point == "redirect-literal":
        return protector.check_redirect_chain([public_url, _url(address)])
    if entry_point == "redirect-resolved":
        return protector.check_redirect_chain(
            [public_url, target_url],
            {public_url: ["1.1.1.1"], target_url: ["1.1.1.1", address]},
        )
    raise AssertionError(f"Unknown entry point: {entry_point}")


@pytest.mark.parametrize("ipv4,blocked", DESTINATION_POLICY)
@pytest.mark.parametrize("address_format", ADDRESS_FORMATS)
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_embedded_destination_matches_native_policy(
    ipv4, blocked, address_format, entry_point
):
    """All entry points apply native policy to each protocol-defined endpoint."""
    protector = SSRFProtector({"enabled": True})
    address = _destination_address(ipv4, address_format)

    result = _check_entry_point(protector, address, entry_point)

    assert len(result) == 3
    assert result[0] is blocked
    assert result[2] is blocked
    if blocked:
        assert address in result[1]
    else:
        assert result == (False, "", False)


@pytest.mark.parametrize("address_format", ADDRESS_FORMATS)
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_additional_blocked_ipv4_range_applies_to_embedded_endpoints(
    address_format, entry_point
):
    """Configured IP ranges retain the existing immutable IP-check contract."""
    protector = SSRFProtector(
        {"enabled": True, "additional_blocked_ips": ["198.51.100.0/24"]}
    )
    address = _destination_address("198.51.100.42", address_format)

    blocked, reason, immutable = _check_entry_point(protector, address, entry_point)

    assert blocked
    assert immutable
    assert address in reason


@pytest.mark.parametrize("address_format", ADDRESS_FORMATS)
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
@pytest.mark.parametrize("ipv4", ["127.0.0.1", "127.255.255.255"])
def test_supported_localhost_policy_is_preserved(ipv4, address_format, entry_point):
    protector = SSRFProtector({"enabled": True, "allow_localhost": True})
    address = _destination_address(ipv4, address_format)

    assert _check_entry_point(protector, address, entry_point) == (False, "", False)


@pytest.mark.parametrize("action", ["block", "warn", "log-only", "ask"])
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
@pytest.mark.parametrize("address_format", ADDRESS_FORMATS[1:])
def test_domain_and_action_policy_cannot_override_embedded_metadata(
    action, entry_point, address_format
):
    address = _destination_address("169.254.169.254", address_format)
    protector = SSRFProtector(
        {
            "enabled": True,
            "action": action,
            "allow_localhost": True,
            "additional_blocked_domains": ["target.example"],
            "allowed_domains": ["target.example", address],
            "path_based_rules": [{"domain": "target.example", "allowed_paths": ["/*"]}],
        }
    )

    blocked, reason, immutable = _check_entry_point(protector, address, entry_point)

    assert blocked
    assert immutable
    assert address in reason


@pytest.mark.parametrize(
    "server,client", [("127.0.0.1", "10.0.0.1"), ("10.0.0.1", "127.0.0.1")]
)
def test_localhost_policy_does_not_hide_other_teredo_endpoint(server, client):
    protector = SSRFProtector({"enabled": True, "allow_localhost": True})

    assert protector._is_ip_blocked(_teredo_address(server, client))


@pytest.mark.parametrize("address_format", ADDRESS_FORMATS[1:])
def test_explicit_ipv6_range_is_checked_before_embedded_public_addresses(
    address_format,
):
    address = _destination_address("8.8.8.8", address_format)
    protector = SSRFProtector(
        {"enabled": True, "additional_blocked_ips": [f"{address}/128"]}
    )

    assert protector._is_ip_blocked(address)


@pytest.mark.parametrize("flags,port", [(0, 1), (0x8000, 3544), (0x8000, 65535)])
@pytest.mark.parametrize("role", ["server", "client"])
def test_teredo_flags_and_obfuscated_port_do_not_hide_endpoint(flags, port, role):
    server, client = (
        ("169.254.169.254", "1.1.1.1")
        if role == "server"
        else ("8.8.8.8", "169.254.169.254")
    )
    address = _teredo_address(server, client, flags, port)
    protector = SSRFProtector({"enabled": True})

    assert protector._is_ip_blocked(address)
    assert protector._is_ip_blocked(ipaddress.IPv6Address(address).exploded.upper())


@pytest.mark.parametrize("representation", ["string", "ip-object", "getaddrinfo"])
def test_resolved_transition_address_representations(representation):
    address = "2002:a9fe:a9fe::1"
    resolved = address
    if representation == "ip-object":
        resolved = ipaddress.IPv6Address(address)
    elif representation == "getaddrinfo":
        resolved = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0))
    protector = SSRFProtector({"enabled": True})

    blocked, reason, immutable = protector.check_resolved_destination(
        "https://target.example/", iter(["1.1.1.1", resolved])
    )

    assert blocked
    assert immutable
    assert (
        reason == f"domain 'target.example' resolves to blocked IP address '{address}'"
    )


@pytest.mark.parametrize(
    "address",
    [
        "2606:4700:4700::1111",  # Native public IPv6.
        "2001:db8::a00:1",  # Private-looking low bits are not an IPv4 endpoint.
        "2001:1:a00:1::1",  # Adjacent to, but outside, the Teredo /32.
        "2003:a00:1::1",  # Outside the 6to4 /16.
        "2002:808:808::a00:1",  # Only 8.8.8.8 is the 6to4 routing endpoint.
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Known Teredo layout control.
        "::fffe:a00:1",  # Not an IPv4-mapped address.
    ],
)
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_native_and_transition_controls_are_not_blanket_blocked(address, entry_point):
    protector = SSRFProtector({"enabled": True})

    assert _check_entry_point(protector, address, entry_point) == (False, "", False)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("8.8.8.8", ["8.8.8.8"]),
        ("2606:4700:4700::1111", ["2606:4700:4700::1111"]),
        ("::ffff:a00:1", ["::ffff:a00:1", "10.0.0.1"]),
        ("2002:a00:1::1", ["2002:a00:1::1", "10.0.0.1"]),
        (
            "2001:0:4136:e378:8000:63bf:3fff:fdd2",
            ["2001:0:4136:e378:8000:63bf:3fff:fdd2", "65.54.227.120", "192.0.2.45"],
        ),
    ],
)
def test_protocol_defined_destinations_have_fixed_layouts(address, expected):
    assert list(SSRFProtector._ip_destinations(ipaddress.ip_address(address))) == [
        ipaddress.ip_address(destination) for destination in expected
    ]
