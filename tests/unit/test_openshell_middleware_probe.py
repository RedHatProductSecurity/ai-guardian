"""Tests for the configured OpenShell middleware gRPC liveness probe."""

from concurrent.futures import ThreadPoolExecutor

import pytest

grpc = pytest.importorskip("grpc", reason="gRPC middleware probes require grpcio")

from ai_guardian.tray.openshell_middleware_probe import (
    MiddlewareProbeError,
    _grpc_target,
    _parse_manifest_identity,
    probe_middleware_endpoint,
)


def _varint(value):
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _bytes_field(field_number, value):
    return _varint((field_number << 3) | 2) + _varint(len(value)) + value


def test_describe_probe_returns_live_implementation_and_version():
    captured_requests = []
    extension = _bytes_field(2, b"ai-guardian/rust-middleware") + _bytes_field(
        3, b"1.20.0-dev"
    )
    response = _bytes_field(99, b"ignored") + _bytes_field(5, extension)

    def describe(request, _context):
        captured_requests.append(request)
        return response

    method_handler = grpc.unary_unary_rpc_method_handler(
        describe,
        request_deserializer=lambda message: message,
        response_serializer=lambda message: message,
    )
    executor = ThreadPoolExecutor(max_workers=1)
    server = grpc.server(executor)
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "openshell.middleware.v1.SupervisorMiddleware",
                {"Describe": method_handler},
            ),
        )
    )
    port = server.add_insecure_port("127.0.0.1:0")
    assert port
    server.start()
    try:
        identity = probe_middleware_endpoint(
            f"http://127.0.0.1:{port}",
            openshell_version="OpenShell 0.1.2",
            timeout=2,
        )
    finally:
        server.stop(0).wait()
        executor.shutdown(wait=True)

    assert identity.implementation == "ai-guardian/rust-middleware"
    assert identity.version == "1.20.0-dev"
    protocol_version = _varint(1 << 3) + _varint(1)
    gateway = (
        _bytes_field(1, protocol_version)
        + _bytes_field(2, b"openshell/gateway")
        + _bytes_field(3, b"OpenShell 0.1.2")
        + _bytes_field(4, b"openshell.supervisor-middleware.contract")
    )
    assert captured_requests == [_bytes_field(1, gateway)]


@pytest.mark.parametrize("response", [b"", b"\x2a\x04\x12\x05x"])
def test_parse_manifest_identity_rejects_missing_or_malformed_metadata(response):
    with pytest.raises(MiddlewareProbeError) as error:
        _parse_manifest_identity(response)

    assert error.value.kind == "identity"


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://127.0.0.1:50051",
        "http://user:password@127.0.0.1:50051",
        "http://127.0.0.1:50051/path",
        "http://127.0.0.1:70000",
    ],
)
def test_grpc_target_rejects_invalid_or_credentialed_urls(endpoint):
    with pytest.raises(MiddlewareProbeError) as error:
        _grpc_target(endpoint)

    assert error.value.kind == "configuration"


def test_grpc_target_preserves_ipv6_authority_and_tls_mode():
    target, use_tls = _grpc_target("https://[::1]:50051")

    assert target == "[::1]:50051"
    assert use_tls is True
