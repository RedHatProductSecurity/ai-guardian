"""Direct gRPC Describe probe for configured OpenShell middleware endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Tuple, Union
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


def _encode_varint(value: int) -> bytes:
    """Encode one non-negative protobuf varint."""
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _encode_varint_field(field_number: int, value: int) -> bytes:
    return _encode_varint(field_number << 3) + _encode_varint(value)


def _encode_bytes_field(field_number: int, value: bytes) -> bytes:
    return _encode_varint((field_number << 3) | 2) + _encode_varint(len(value)) + value


def _serialize_describe_request(openshell_version: str) -> bytes:
    """Serialize the fixed OpenShell supervisor Describe request wire fields."""
    protocol_version = _encode_varint_field(1, 1)  # ProtocolVersion.major
    gateway = (
        _encode_bytes_field(1, protocol_version)  # PeerMetadata.protocol_version
        + _encode_bytes_field(2, b"openshell/gateway")
        + _encode_bytes_field(3, openshell_version.encode("utf-8"))
        + _encode_bytes_field(4, _CONTRACT_CAPABILITY.encode("utf-8"))
    )
    return _encode_bytes_field(1, gateway)  # MiddlewareDescribeRequest.gateway


def _read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated protobuf varint")
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise ValueError("protobuf varint exceeds 64 bits")
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise ValueError("protobuf varint exceeds 64 bits")


def _iter_wire_fields(
    data: bytes,
) -> Iterator[Tuple[int, int, Union[int, bytes]]]:
    """Yield protobuf field number, wire type, and value; reject malformed data."""
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field_number, wire_type = tag >> 3, tag & 7
        if field_number == 0:
            raise ValueError("protobuf field number cannot be zero")

        value: Union[int, bytes]
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ValueError("truncated fixed64 protobuf field")
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("truncated length-delimited protobuf field")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ValueError("truncated fixed32 protobuf field")
            value = data[offset:end]
            offset = end
        else:
            raise ValueError("unsupported protobuf wire type")

        yield field_number, wire_type, value


def _parse_manifest_identity(data: bytes) -> MiddlewareProbeIdentity:
    """Extract extension identity fields from an OpenShell Describe response."""
    has_extension = False
    implementation = ""
    version = ""
    try:
        for field_number, wire_type, value in _iter_wire_fields(data):
            if field_number != 5 or wire_type != 2 or not isinstance(value, bytes):
                continue
            has_extension = True  # MiddlewareManifest.extension
            for (
                metadata_number,
                metadata_wire_type,
                metadata_value,
            ) in _iter_wire_fields(value):
                if metadata_wire_type != 2 or not isinstance(metadata_value, bytes):
                    continue
                if metadata_number == 2:
                    implementation = metadata_value.decode("utf-8")
                elif metadata_number == 3:
                    version = metadata_value.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise MiddlewareProbeError(
            "Describe response metadata is malformed", kind="identity"
        ) from exc

    if not has_extension:
        raise MiddlewareProbeError(
            "Describe response has no implementation metadata", kind="identity"
        )
    return MiddlewareProbeIdentity(
        implementation=implementation.strip(),
        version=version.strip(),
    )


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

    request = _serialize_describe_request(openshell_version)

    channel = (
        grpc.secure_channel(target, grpc.ssl_channel_credentials())
        if use_tls
        else grpc.insecure_channel(target)
    )
    try:
        describe = channel.unary_unary(
            _DESCRIBE_METHOD,
            request_serializer=lambda message: message,
            response_deserializer=lambda message: message,
        )
        response = describe(request, timeout=timeout)
    except grpc.RpcError as exc:
        code = exc.code()
        code_name = getattr(code, "name", "UNKNOWN")
        raise MiddlewareProbeError(
            f"Describe RPC failed ({code_name})", kind="unavailable"
        ) from None
    finally:
        channel.close()

    return _parse_manifest_identity(response)


__all__ = [
    "MiddlewareProbeError",
    "MiddlewareProbeIdentity",
    "probe_middleware_endpoint",
]
