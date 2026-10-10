"""Direct gRPC Describe probe for configured OpenShell middleware endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Tuple
from urllib.parse import urlsplit

_CONTRACT_CAPABILITY = "openshell.supervisor-middleware.contract"
_DESCRIBE_METHOD = "/openshell.middleware.v1.SupervisorMiddleware/Describe"


class MiddlewareProbeError(RuntimeError):
    """A configured middleware endpoint could not be verified."""

    def __init__(self, message: str, *, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class MiddlewareProbeIdentity:
    """Implementation identity returned by a live middleware Describe RPC."""

    implementation: str
    version: str


def _add_field(
    message: Any,
    name: str,
    number: int,
    field_type: int,
    *,
    repeated: bool = False,
    type_name: str = "",
) -> None:
    field = message.field.add()
    field.name = name
    field.number = number
    field.type = field_type
    field.label = field.LABEL_REPEATED if repeated else field.LABEL_OPTIONAL
    if type_name:
        field.type_name = type_name


@lru_cache(maxsize=1)
def _probe_message_types() -> Tuple[Any, Any]:
    """Build only the protobuf messages needed for the Describe handshake."""
    try:
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    except ImportError as exc:
        raise MiddlewareProbeError(
            "protobuf runtime is unavailable", kind="dependency"
        ) from exc

    # Field numbers/types mirror the vendored OpenShell v0.1.2 proto contract.
    field_types = descriptor_pb2.FieldDescriptorProto
    pool = descriptor_pool.DescriptorPool()

    extension_file = descriptor_pb2.FileDescriptorProto(
        name="ai_guardian_openshell_extension.proto",
        package="openshell.extension.v1",
        syntax="proto3",
    )
    protocol_version = extension_file.message_type.add()
    protocol_version.name = "ProtocolVersion"
    _add_field(
        protocol_version,
        "major",
        1,
        field_types.TYPE_UINT32,
    )
    _add_field(
        protocol_version,
        "minor",
        2,
        field_types.TYPE_UINT32,
    )

    peer_metadata = extension_file.message_type.add()
    peer_metadata.name = "PeerMetadata"
    _add_field(
        peer_metadata,
        "protocol_version",
        1,
        field_types.TYPE_MESSAGE,
        type_name=".openshell.extension.v1.ProtocolVersion",
    )
    _add_field(
        peer_metadata,
        "implementation_name",
        2,
        field_types.TYPE_STRING,
    )
    _add_field(
        peer_metadata,
        "implementation_version",
        3,
        field_types.TYPE_STRING,
    )
    _add_field(
        peer_metadata,
        "supported_capabilities",
        4,
        field_types.TYPE_STRING,
        repeated=True,
    )
    _add_field(
        peer_metadata,
        "required_capabilities",
        5,
        field_types.TYPE_STRING,
        repeated=True,
    )
    pool.Add(extension_file)

    middleware_file = descriptor_pb2.FileDescriptorProto(
        name="ai_guardian_openshell_middleware_probe.proto",
        package="openshell.middleware.v1",
        dependency=[extension_file.name],
        syntax="proto3",
    )
    describe_request = middleware_file.message_type.add()
    describe_request.name = "MiddlewareDescribeRequest"
    _add_field(
        describe_request,
        "gateway",
        1,
        field_types.TYPE_MESSAGE,
        type_name=".openshell.extension.v1.PeerMetadata",
    )

    manifest = middleware_file.message_type.add()
    manifest.name = "MiddlewareManifest"
    _add_field(manifest, "name", 1, field_types.TYPE_STRING)
    _add_field(manifest, "service_version", 2, field_types.TYPE_STRING)
    _add_field(
        manifest,
        "extension",
        5,
        field_types.TYPE_MESSAGE,
        type_name=".openshell.extension.v1.PeerMetadata",
    )

    service = middleware_file.service.add()
    service.name = "SupervisorMiddleware"
    describe = service.method.add()
    describe.name = "Describe"
    describe.input_type = ".openshell.middleware.v1.MiddlewareDescribeRequest"
    describe.output_type = ".openshell.middleware.v1.MiddlewareManifest"
    pool.Add(middleware_file)

    request_type = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("openshell.middleware.v1.MiddlewareDescribeRequest")
    )
    manifest_type = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("openshell.middleware.v1.MiddlewareManifest")
    )
    return request_type, manifest_type


def _grpc_target(endpoint: str) -> Tuple[str, bool]:
    """Validate an HTTP(S) gRPC endpoint and return its target and TLS mode."""
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise MiddlewareProbeError(
            "middleware endpoint URL is invalid", kind="configuration"
        ) from exc

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MiddlewareProbeError(
            "middleware endpoint must use an HTTP(S) URL", kind="configuration"
        )
    if parsed.username is not None or parsed.password is not None:
        raise MiddlewareProbeError(
            "middleware endpoint URL must not contain credentials",
            kind="configuration",
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise MiddlewareProbeError(
            "middleware endpoint URL must contain only a host and optional port",
            kind="configuration",
        )
    if port is not None and not 1 <= port <= 65535:
        raise MiddlewareProbeError(
            "middleware endpoint port is outside the valid range",
            kind="configuration",
        )

    target = parsed.netloc
    if port is None:
        target = f"{target}:{443 if parsed.scheme == 'https' else 80}"
    return target, parsed.scheme == "https"


def probe_middleware_endpoint(
    endpoint: str,
    *,
    openshell_version: str,
    timeout: float = 2.0,
) -> MiddlewareProbeIdentity:
    """Call Describe and return its declared implementation identity/version."""
    target, use_tls = _grpc_target(endpoint)
    try:
        import grpc
    except ImportError as exc:
        raise MiddlewareProbeError(
            "grpcio is not installed in the AI Guardian tray's Python environment",
            kind="dependency",
        ) from exc

    request_type, manifest_type = _probe_message_types()
    request = request_type()
    request.gateway.protocol_version.major = 1
    request.gateway.protocol_version.minor = 0
    request.gateway.implementation_name = "openshell/gateway"
    request.gateway.implementation_version = openshell_version
    request.gateway.supported_capabilities.append(_CONTRACT_CAPABILITY)

    channel = (
        grpc.secure_channel(target, grpc.ssl_channel_credentials())
        if use_tls
        else grpc.insecure_channel(target)
    )
    try:
        describe = channel.unary_unary(
            _DESCRIBE_METHOD,
            request_serializer=lambda message: message.SerializeToString(),
            response_deserializer=manifest_type.FromString,
        )
        manifest = describe(request, timeout=timeout)
    except grpc.RpcError as exc:
        code = exc.code()
        code_name = getattr(code, "name", "UNKNOWN")
        raise MiddlewareProbeError(
            f"Describe RPC failed ({code_name})", kind="unavailable"
        ) from None
    finally:
        channel.close()

    if not manifest.HasField("extension"):
        raise MiddlewareProbeError(
            "Describe response has no implementation metadata", kind="identity"
        )

    return MiddlewareProbeIdentity(
        implementation=str(manifest.extension.implementation_name).strip(),
        version=str(manifest.extension.implementation_version).strip(),
    )


__all__ = [
    "MiddlewareProbeError",
    "MiddlewareProbeIdentity",
    "probe_middleware_endpoint",
]
