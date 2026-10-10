"""Tests for the configured OpenShell middleware gRPC liveness probe."""

from concurrent.futures import ThreadPoolExecutor

import pytest

grpc = pytest.importorskip("grpc", reason="gRPC middleware probes require grpcio")

from ai_guardian.tray.openshell_middleware_probe import (
    MiddlewareProbeError,
    _grpc_target,
    _probe_message_types,
    probe_middleware_endpoint,
)


def test_describe_probe_returns_live_implementation_and_version():
    request_type, manifest_type = _probe_message_types()
    captured_requests = []

    def describe(request, _context):
        captured_requests.append(request)
        response = manifest_type()
        response.extension.implementation_name = "ai-guardian/rust-middleware"
        response.extension.implementation_version = "1.20.0-dev"
        return response

    method_handler = grpc.unary_unary_rpc_method_handler(
        describe,
        request_deserializer=request_type.FromString,
        response_serializer=lambda message: message.SerializeToString(),
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
    request = captured_requests[0]
    assert request.gateway.protocol_version.major == 1
    assert request.gateway.protocol_version.minor == 0
    assert "openshell.supervisor-middleware.contract" in (
        request.gateway.supported_capabilities
    )


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
