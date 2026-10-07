"""OpenShell v0.1.2 supervisor-middleware gRPC service.

The service is intentionally an external process.  OpenShell remains
authoritative for network/SSRF, filesystem, process, credential injection, and
provider routing; this process owns only semantic content checks at the
provider boundary.
"""

from __future__ import annotations

import json
import logging
import ipaddress
import os
import select
import signal
import socket
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, cast

from ai_guardian import __version__
from .bootstrap import (
    OpenShellBootstrapError,
    bootstrap_openshell,
)
from ...config import (
    MAX_PAYLOAD_BYTES,
    OPEN_SHELL_PROTOCOL_MAJOR,
    OPEN_SHELL_PROTOCOL_MINOR,
    MiddlewarePolicy,
    MiddlewarePolicyError,
    ScannerOwnershipError,
    load_operator_policy,
    resolve_scanner_ownership,
)
from ...dedup import FindingDeduplicator
from ...dedup import FindingKey
from ...semantic import (
    ContentEvaluation,
    ContentFinding,
    SemanticContentScanner,
)

try:  # Optional: normal hook/SDK installations need not carry gRPC.
    import grpc
    import jwt
    from google.protobuf import duration_pb2, json_format, struct_pb2

    from .proto import extension_pb2
    from .proto import supervisor_middleware_pb2 as pb2
    from .proto import supervisor_middleware_pb2_grpc as pb2_grpc

    _GRPC_AVAILABLE = True
except (ImportError, RuntimeError):  # pragma: no cover - optional dependency boundary
    grpc = None
    jwt = None
    duration_pb2 = None
    json_format = None
    struct_pb2 = None
    extension_pb2 = None
    pb2 = None
    pb2_grpc = None
    _GRPC_AVAILABLE = False

logger = logging.getLogger(__name__)

_CONTRACT_CAPABILITY = "openshell.supervisor-middleware.contract"
_SERVICE_CAPABILITIES = frozenset(
    {
        _CONTRACT_CAPABILITY,
        "openshell.middleware.semantic-scanning",
        "openshell.middleware.request-scanning",
        "openshell.middleware.response-redaction",
        "openshell.middleware.websocket-text",
        "openshell.middleware.streaming-response",
    }
)
_PRE_CREDENTIALS = 1
_PRE_RETURN = 2
_ALLOW = 1
_DENY = 2
_INSPECT = 1
_SKIP = 2
_WS_DENY = 3
_WHOLE_BODY = 2
_STREAM_BODY = 3
_JWT_TYP = "openshell-ext+jwt"
_MAX_EXTENSION_TOKEN_TTL_SECONDS = 3600
_REQUEST_IMMUTABLE_POLICY_FIELDS = (
    "profile_id",
    "profile_digest",
    "max_payload_bytes",
    "timeout_ms",
    "response_redaction",
    "require_effective_policy",
    "registration_name",
    "provider_endpoints",
    "hooks_capabilities",
    "shared_correlation_id",
    "pre_persistence_deduplication",
    "allow_binary_websocket",
    "allow_unsupported_responses",
)


def require_grpc() -> None:
    """Raise an actionable error when the middleware extra is not installed."""

    if not _GRPC_AVAILABLE:
        raise RuntimeError(
            "OpenShell middleware requires the optional dependencies; "
            "install with 'pip install ai-guardian[middleware]'"
        )


@dataclass(frozen=True)
class MiddlewareServerSecurity:
    """TLS and JWT settings for the operator-managed service."""

    tls_cert_file: Optional[str] = None
    tls_key_file: Optional[str] = None
    tls_client_ca_file: Optional[str] = None
    jwt_secret: Optional[str] = None
    jwt_public_key_file: Optional[str] = None
    jwt_audience: Optional[str] = None
    jwt_issuer: Optional[str] = None
    jwt_algorithms: tuple[str, ...] = ("EdDSA",)
    jwt_token_type: str = "openshell-ext+jwt"
    allow_insecure_transport: bool = False
    allow_insecure_wildcard_bind: bool = False

    def validate(self) -> None:
        if self.allow_insecure_transport:
            if self.tls_cert_file or self.tls_key_file:
                raise ValueError(
                    "allow_insecure_transport cannot be combined with TLS files"
                )
        elif not self.tls_cert_file or not self.tls_key_file:
            raise ValueError(
                "TLS certificate and key are required unless insecure transport is explicitly enabled"
            )
        if bool(self.tls_cert_file) != bool(self.tls_key_file):
            raise ValueError("tls_cert_file and tls_key_file must be supplied together")
        if not self.allow_insecure_transport and not (
            self.jwt_secret or self.jwt_public_key_file
        ):
            raise ValueError(
                "JWT validation key is required for authenticated middleware transport"
            )
        if self.jwt_secret and self.jwt_public_key_file:
            raise ValueError("configure only one JWT validation key")
        if self.jwt_secret and any(
            algorithm not in {"HS256", "HS384", "HS512"}
            for algorithm in self.jwt_algorithms
        ):
            raise ValueError(
                "shared JWT secrets require an HS256/HS384/HS512 algorithm"
            )
        if self.jwt_public_key_file and any(
            algorithm not in {"EdDSA", "RS256", "RS384", "RS512"}
            for algorithm in self.jwt_algorithms
        ):
            raise ValueError("JWT public keys require an EdDSA or RSA algorithm")
        if not self.allow_insecure_transport:
            if not self.jwt_audience:
                raise ValueError(
                    "jwt_audience is required for OpenShell middleware JWT validation"
                )
            if not self.jwt_issuer:
                raise ValueError(
                    "jwt_issuer is required for OpenShell middleware JWT validation"
                )
            if not self.jwt_algorithms or any(
                algorithm
                not in {
                    "EdDSA",
                    "HS256",
                    "HS384",
                    "HS512",
                    "RS256",
                    "RS384",
                    "RS512",
                }
                for algorithm in self.jwt_algorithms
            ):
                raise ValueError("jwt_algorithms contains an unsupported algorithm")
        if self.jwt_public_key_file and not Path(self.jwt_public_key_file).is_file():
            raise ValueError(
                f"JWT public key file not found: {self.jwt_public_key_file}"
            )
        if self.tls_client_ca_file and not Path(self.tls_client_ca_file).is_file():
            raise ValueError(f"TLS client CA file not found: {self.tls_client_ca_file}")
        if self.jwt_token_type != _JWT_TYP:
            raise ValueError(f"jwt_token_type must be {_JWT_TYP!r}")

    @classmethod
    def from_mapping(
        cls,
        mapping: Optional[Mapping[str, Any]] = None,
        *,
        overrides: Optional[Mapping[str, Any]] = None,
        default_audience: Optional[str] = None,
    ) -> "MiddlewareServerSecurity":
        raw = dict(mapping or {})
        raw.update(dict(overrides or {}))
        tls = raw.get("tls", {})
        jwt_config = raw.get("jwt", {})
        if not isinstance(tls, Mapping) or not isinstance(jwt_config, Mapping):
            raise ValueError("tls and jwt settings must be objects")
        if jwt_config.get("token_type", _JWT_TYP) != _JWT_TYP:
            raise ValueError(f"jwt.token_type must be {_JWT_TYP!r}")
        configured_algorithms = jwt_config.get("algorithms")
        if configured_algorithms is None:
            # OpenShell gateway JWTs use EdDSA and expose a public PEM.  HS256
            # remains available for explicitly configured local test gateways
            # that provide a shared secret instead.
            configured_algorithms = (
                ("HS256",) if jwt_config.get("secret") else ("EdDSA",)
            )
        algorithms = configured_algorithms
        if isinstance(algorithms, str):
            algorithms = (algorithms,)
        if not isinstance(algorithms, (list, tuple)):
            raise ValueError("jwt.algorithms must be a list")
        allow_insecure_transport = raw.get("allow_insecure_transport", False)
        if not isinstance(allow_insecure_transport, bool):
            raise ValueError("allow_insecure_transport must be a boolean")
        allow_insecure_wildcard_bind = raw.get("allow_insecure_wildcard_bind", False)
        if not isinstance(allow_insecure_wildcard_bind, bool):
            raise ValueError("allow_insecure_wildcard_bind must be a boolean")
        return cls(
            tls_cert_file=_optional_string(tls.get("cert_file")),
            tls_key_file=_optional_string(tls.get("key_file")),
            tls_client_ca_file=_optional_string(tls.get("client_ca_file")),
            jwt_secret=_optional_string(jwt_config.get("secret")),
            jwt_public_key_file=_optional_string(jwt_config.get("public_key_file")),
            jwt_audience=_optional_string(jwt_config.get("audience", default_audience)),
            jwt_issuer=_optional_string(
                jwt_config.get("issuer")
                or (
                    f"openshell-gateway:{jwt_config['gateway_id']}"
                    if jwt_config.get("gateway_id")
                    else None
                )
            ),
            jwt_algorithms=tuple(str(item) for item in algorithms),
            jwt_token_type=_JWT_TYP,
            allow_insecure_transport=allow_insecure_transport,
            allow_insecure_wildcard_bind=allow_insecure_wildcard_bind,
        )

    def server_credentials(self):
        """Create gRPC server credentials after validating configuration."""

        require_grpc()
        self.validate()
        if self.allow_insecure_transport:
            return None
        cert = Path(self.tls_cert_file).read_bytes()  # type: ignore[arg-type]
        key = Path(self.tls_key_file).read_bytes()  # type: ignore[arg-type]
        roots = (
            Path(self.tls_client_ca_file).read_bytes()
            if self.tls_client_ca_file
            else None
        )
        return grpc.ssl_server_credentials(
            ((key, cert),),
            root_certificates=roots,
            require_client_auth=roots is not None,
        )

    def jwt_key(self) -> str:
        if self.jwt_public_key_file:
            return Path(self.jwt_public_key_file).read_text(encoding="utf-8")
        if self.jwt_secret:
            return self.jwt_secret
        raise ValueError("JWT validation key is not configured")


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("security string values must be non-empty strings")
    return value


class JwtAuthInterceptor(
    grpc.ServerInterceptor if _GRPC_AVAILABLE else object  # type: ignore[misc]
):
    """Validate the short-lived JWT attached by an OpenShell gateway."""

    def __init__(self, security: MiddlewareServerSecurity):
        require_grpc()
        security.validate()
        self.security = security
        self._key = security.jwt_key()

    def validate_token(self, token: str) -> Dict[str, Any]:
        if not token or jwt is None:
            raise ValueError("missing bearer token")
        header = jwt.get_unverified_header(token)
        if header.get("typ") != self.security.jwt_token_type:
            raise ValueError("unexpected JWT type")
        if header.get("alg") not in self.security.jwt_algorithms:
            raise ValueError("unexpected JWT algorithm")
        options = {
            "require": ["iss", "aud", "sub", "iat", "exp", "jti", "caller_kind"],
        }
        kwargs: Dict[str, Any] = {
            "algorithms": list(self.security.jwt_algorithms),
            "audience": self.security.jwt_audience,
            "options": options,
        }
        kwargs["issuer"] = self.security.jwt_issuer
        claims = jwt.decode(token, self._key, **kwargs)
        if not isinstance(claims, dict):
            raise ValueError("JWT claims must be an object")
        if claims.get("iss") != self.security.jwt_issuer:
            raise ValueError("JWT issuer is invalid")
        if claims.get("aud") != self.security.jwt_audience:
            raise ValueError("JWT audience is invalid")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("JWT subject is invalid")
        if not isinstance(claims.get("jti"), str) or not claims["jti"]:
            raise ValueError("JWT ID is invalid")
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if (
            isinstance(issued_at, bool)
            or isinstance(expires_at, bool)
            or not isinstance(issued_at, int)
            or not isinstance(expires_at, int)
        ):
            raise ValueError("JWT time claims are invalid")
        if expires_at <= issued_at:
            raise ValueError("JWT lifetime is invalid")
        if expires_at - issued_at > _MAX_EXTENSION_TOKEN_TTL_SECONDS:
            raise ValueError("JWT lifetime exceeds the OpenShell extension limit")
        if expires_at <= int(time.time()):
            raise ValueError("JWT is expired")
        caller_kind = claims.get("caller_kind")
        if caller_kind not in {"gateway", "supervisor"}:
            raise ValueError("JWT caller_kind is invalid")
        if caller_kind == "supervisor":
            sandbox_id = claims.get("sandbox_id")
            if not isinstance(sandbox_id, str) or not sandbox_id:
                raise ValueError("supervisor JWT is missing sandbox_id")
        return claims

    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if handler is None:
            return None
        metadata = dict(handler_call_details.invocation_metadata or ())
        authorization = metadata.get("authorization", "")
        prefix = "Bearer "
        token = (
            authorization[len(prefix) :].strip()
            if authorization.startswith(prefix)
            else ""
        )
        try:
            self.validate_token(token)
        except Exception:
            logger.warning("OpenShell middleware JWT validation failed")
            return _unauthenticated_handler(handler)
        return handler


def _unauthenticated_handler(handler):
    def abort(context):
        context.abort(
            grpc.StatusCode.UNAUTHENTICATED, "middleware authentication failed"
        )

    if handler.unary_unary:
        return grpc.unary_unary_rpc_method_handler(
            lambda request, context: abort(context),
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.unary_stream:
        return grpc.unary_stream_rpc_method_handler(
            lambda request, context: abort(context),
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.stream_unary:
        return grpc.stream_unary_rpc_method_handler(
            lambda request, context: abort(context),
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    return grpc.stream_stream_rpc_method_handler(
        lambda request, context: abort(context),
        request_deserializer=handler.request_deserializer,
        response_serializer=handler.response_serializer,
    )


def _struct_dict(value: Optional[struct_pb2.Struct]) -> Dict[str, Any]:
    if value is None:
        return {}
    return json_format.MessageToDict(value, preserving_proto_field_name=True)


def _safe_reason_code(value: str, default: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 64
        or not ("a" <= value[0] <= "z")
    ):
        return default
    if not all(
        ("a" <= char <= "z") or ("0" <= char <= "9") or char == "_" for char in value
    ):
        return default
    return value


def _request_id(context_message: Any) -> str:
    context = getattr(context_message, "context", None)
    return getattr(context, "request_id", "") or ""


if _GRPC_AVAILABLE:

    class MiddlewareService(
        pb2_grpc.SupervisorMiddlewareServicer,  # type: ignore[misc]
        pb2_grpc.HttpResponsePreReturnServicer,  # type: ignore[misc]
    ):
        """Implementation of both OpenShell v0.1.2 middleware services."""

        def __init__(
            self,
            policy: MiddlewarePolicy,
            *,
            security: Optional[MiddlewareServerSecurity] = None,
            scanner: Optional[SemanticContentScanner] = None,
            deduplicator: Optional[FindingDeduplicator] = None,
            violation_logger: Optional[Any] = None,
        ) -> None:
            self.policy = policy
            self.security = security
            self.scanner = scanner or SemanticContentScanner(policy.profile)
            self.deduplicator = deduplicator or FindingDeduplicator()
            # The OpenShell middleware is a separate process from any daemon
            # running inside a workload.  Keep its audit sink injectable for
            # tests, and let the CLI provide the normal ViolationLogger in
            # production.  A missing sink must never change a deny decision;
            # structured service logging below remains available regardless.
            self.violation_logger = violation_logger
            self.authenticator = (
                JwtAuthInterceptor(security)
                if security and not security.allow_insecure_transport
                else None
            )
            self.supported_capabilities = frozenset(
                {
                    *_SERVICE_CAPABILITIES,
                    *policy.required_middleware_capabilities,
                    "openshell.middleware.scanner.secrets",
                    "openshell.middleware.scanner.pii",
                    "openshell.middleware.scanner.prompt-injection",
                    "openshell.middleware.scanner.context-poisoning",
                    "openshell.middleware.scanner.redaction",
                    "openshell.middleware.scanner.supply-chain",
                    "openshell.middleware.scanner.offensive-language",
                    "openshell.middleware.scanner.canary",
                    "openshell.middleware.scanner.config-content",
                }
            )

        @staticmethod
        def _safe_audit_value(value: Any, limit: int = 256) -> str:
            """Bound and flatten operator-visible middleware diagnostics."""

            text = " ".join(str(value or "").split())
            return text[:limit]

        def _finding_types(self, findings: Iterable[ContentFinding]) -> tuple[str, ...]:
            """Return stable finding types without copying provider content."""

            values = {
                _safe_reason_code(finding.type, "middleware_finding")
                for finding in findings
                if finding.type
            }
            return tuple(sorted(values))

        def _decision_metadata(
            self,
            reason_code: str,
            findings: Iterable[ContentFinding],
            metadata: Optional[Mapping[str, str]] = None,
        ) -> Dict[str, str]:
            """Build bounded, content-free metadata for OpenShell diagnostics."""

            items = tuple(findings)
            result = {
                str(key): self._safe_audit_value(value, 512)
                for key, value in (metadata or {}).items()
            }
            safe_reason = _safe_reason_code(
                reason_code, "middleware_denied" if reason_code else ""
            )
            if safe_reason:
                result["decision_reason"] = safe_reason
            if items:
                types = self._finding_types(items)
                if types:
                    result["finding_types"] = ",".join(types)[:1024]
                rules = sorted(
                    {
                        self._safe_audit_value(finding.rule_id, 128)
                        for finding in items
                        if finding.rule_id
                    }
                )
                if rules:
                    result["finding_rules"] = ",".join(rules)[:1024]
            if safe_reason or items:
                result["middleware_source"] = "ai-guardian-openshell-middleware"
            return result

        def _decision_message(
            self, reason_code: str, findings: Iterable[ContentFinding]
        ) -> str:
            """Return a safe human-readable message for request diagnostics."""

            types = self._finding_types(findings)
            if types:
                return (
                    "AI Guardian blocks this request: "
                    + ", ".join(types)
                    + " (OpenShell middleware)"
                )
            safe_reason = _safe_reason_code(reason_code, "middleware_denied")
            return (
                f"AI Guardian blocks this request: {safe_reason} (OpenShell middleware)"
            )

        def _record_decision(
            self,
            *,
            decision: int,
            reason_code: str,
            findings: Iterable[ContentFinding] = (),
            metadata: Optional[Mapping[str, str]] = None,
            request_id: str = "",
            phase: str = "",
            direction: str = "",
            middleware_name: str = "",
            target_host: str = "",
            policy: Optional[MiddlewarePolicy] = None,
        ) -> None:
            """Emit an attribution-safe log and persist scanner findings.

            OpenShell may expose only a generic client error for a denied
            provider operation.  The external middleware therefore records a
            second, operator-visible trail.  It contains the stable reason
            code, scanner categories, rule IDs, request correlation ID, and
            direction, but never the request/response body or matched value.
            """

            items = tuple(findings)
            denied = decision == _DENY
            safe_reason = _safe_reason_code(
                reason_code, "middleware_denied" if denied else ""
            )
            types = self._finding_types(items)
            rules = tuple(
                sorted(
                    {
                        self._safe_audit_value(finding.rule_id, 128)
                        for finding in items
                        if finding.rule_id
                    }
                )
            )
            log_method = logger.warning if denied else logger.info
            log_method(
                "OpenShell middleware decision=%s source=ai-guardian-openshell-middleware "
                "reason_code=%s request_id=%s phase=%s direction=%s middleware=%s "
                "target_host=%s finding_types=%s finding_rules=%s",
                "deny" if denied else "allow",
                safe_reason if reason_code else "none",
                self._safe_audit_value(request_id),
                self._safe_audit_value(phase),
                self._safe_audit_value(direction),
                self._safe_audit_value(middleware_name),
                self._safe_audit_value(target_host),
                ",".join(types) or "none",
                ",".join(rules) or "none",
            )

            if self.violation_logger is None or not items:
                return

            from ai_guardian.scanners.scan_result import ScanResult
            from ai_guardian.violations.log_violation import ScanContext, log_violation

            policy_version = None
            if policy is not None:
                policy_version = f"{policy.profile_id}:{policy.profile_digest[:12]}"
            context = ScanContext(
                ide_type="openshell-middleware",
                hook_event=f"{phase}:{direction}".strip(":"),
                correlation_id=self._safe_audit_value(request_id) or None,
                agent="openshell",
                policy_version=policy_version,
            )
            safe_context = {
                "middleware_source": "ai-guardian-openshell-middleware",
                "phase": self._safe_audit_value(phase),
                "direction": self._safe_audit_value(direction),
                "request_id": self._safe_audit_value(request_id),
                "middleware_name": self._safe_audit_value(middleware_name),
                "target_host": self._safe_audit_value(target_host),
                "reason_code": safe_reason,
            }
            for finding in items:
                violation_type = _safe_reason_code(finding.type, "middleware_finding")
                result = ScanResult(
                    detected=True,
                    violation_type=violation_type,
                    severity=self._safe_audit_value(finding.severity, 32) or "high",
                    should_block=denied,
                    rule_id=self._safe_audit_value(finding.rule_id, 128),
                    total_findings=max(1, int(finding.count)),
                    extra={"openshell_middleware": True},
                )
                try:
                    log_violation(
                        result,
                        context,
                        violation_logger=self.violation_logger,
                        blocked_overrides=safe_context,
                        source="openshell-middleware",
                    )
                except Exception:  # pragma: no cover - defensive audit boundary
                    logger.warning(
                        "OpenShell middleware audit persistence failed for %s",
                        violation_type,
                    )

        def Describe(self, request, context):
            try:
                self._authorize_gateway(context)
                self._validate_gateway(request.gateway)
            except ValueError as exc:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
            extension = extension_pb2.PeerMetadata(
                protocol_version=extension_pb2.ProtocolVersion(
                    major=OPEN_SHELL_PROTOCOL_MAJOR,
                    minor=OPEN_SHELL_PROTOCOL_MINOR,
                ),
                implementation_name="ai-guardian/middleware",
                implementation_version=__version__,
                supported_capabilities=sorted(self.supported_capabilities),
                required_capabilities=[_CONTRACT_CAPABILITY],
            )
            return pb2.MiddlewareManifest(
                name="ai-guardian/middleware",
                service_version=__version__,
                bindings=[
                    pb2.MiddlewareBinding(
                        operation=pb2.SUPERVISOR_MIDDLEWARE_OPERATION_HTTP_REQUEST,
                        phase=pb2.SUPERVISOR_MIDDLEWARE_PHASE_PRE_CREDENTIALS,
                        max_payload_bytes=self.policy.max_payload_bytes,
                    ),
                    pb2.MiddlewareBinding(
                        operation=pb2.SUPERVISOR_MIDDLEWARE_OPERATION_HTTP_RESPONSE,
                        phase=pb2.SUPERVISOR_MIDDLEWARE_PHASE_PRE_RETURN,
                        max_payload_bytes=self.policy.max_payload_bytes,
                    ),
                    pb2.MiddlewareBinding(
                        operation=pb2.SUPERVISOR_MIDDLEWARE_OPERATION_WEBSOCKET_MESSAGE,
                        phase=pb2.SUPERVISOR_MIDDLEWARE_PHASE_PRE_CREDENTIALS,
                        max_payload_bytes=self.policy.max_payload_bytes,
                    ),
                ],
                expected_audience=(
                    self.security.jwt_audience
                    if self.security and not self.security.allow_insecure_transport
                    else ""
                ),
                extension=extension,
            )

        def ValidateConfig(self, request, context):
            try:
                policy = self._policy_for_struct(request.config)
                if (
                    policy.registration_name
                    and request.middleware_name != policy.registration_name
                ):
                    raise MiddlewarePolicyError(
                        "middleware_name does not match the operator registration"
                    )
                return pb2.ValidateConfigResponse(valid=True)
            except (MiddlewarePolicyError, ScannerOwnershipError, ValueError) as exc:
                return pb2.ValidateConfigResponse(valid=False, reason=str(exc)[:4096])

        def EvaluateHttpRequest(self, request, context):
            self._authorize_supervisor(context, request.context)
            request_id = _request_id(request)
            middleware_name = request.middleware_name
            target_host = request.target.host
            if request.phase != _PRE_CREDENTIALS:
                context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, "unsupported HTTP request phase"
                )
            if len(request.body) > self.policy.max_payload_bytes:
                return self._denied_result(
                    "payload_limit_exceeded",
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                    middleware_name=middleware_name,
                    target_host=target_host,
                    policy=self.policy,
                )
            try:
                policy = self._policy_for_struct(request.config)
                selected, ownership_error = self._selected_scanners(
                    policy,
                    target_host=target_host,
                    middleware_name=middleware_name,
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                )
            except (MiddlewarePolicyError, ScannerOwnershipError, ValueError) as exc:
                logger.warning(
                    "middleware request policy validation failed: %s",
                    type(exc).__name__,
                )
                return self._denied_result(
                    "effective_policy_invalid",
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                    middleware_name=middleware_name,
                    target_host=target_host,
                    policy=self.policy,
                )
            if ownership_error:
                return self._denied_result(
                    "scanner_ownership_unavailable",
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                    middleware_name=middleware_name,
                    target_host=target_host,
                    policy=policy,
                )
            if not selected or not request.body:
                return pb2.HttpRequestResult(decision=_ALLOW)
            try:
                transformed, evaluation = self.scanner.inspect_payload(
                    bytes(request.body),
                    scanners=selected,
                    redact=policy.response_redaction,
                    filename="provider-request",
                )
            except UnicodeDecodeError:
                return self._denied_result(
                    "unsupported_payload_encoding",
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                    middleware_name=middleware_name,
                    target_host=target_host,
                    policy=policy,
                )
            return self._request_result(
                evaluation,
                transformed,
                bytes(request.body),
                request_id=request_id,
                middleware_name=middleware_name,
                target_host=target_host,
                policy=policy,
            )

        def EvaluateWebSocketSession(self, request_iterator, context):
            started = False
            skipped = False
            sequence = 0
            policy: Optional[MiddlewarePolicy] = None
            selected: set[str] = set()
            request_id = ""
            for event in request_iterator:
                kind = event.WhichOneof("event")
                if kind == "preflight":
                    if policy is not None or started:
                        context.abort(
                            grpc.StatusCode.FAILED_PRECONDITION,
                            "duplicate WebSocket preflight",
                        )
                    preflight = event.preflight
                    self._authorize_supervisor(context, preflight.context)
                    if preflight.phase != _PRE_CREDENTIALS:
                        context.abort(
                            grpc.StatusCode.INVALID_ARGUMENT,
                            "unsupported WebSocket phase",
                        )
                    request_id = preflight.context.request_id or request_id
                    try:
                        policy = self._policy_for_struct(preflight.config)
                        selected, ownership_error = self._selected_scanners(
                            policy,
                            target_host=preflight.target.host,
                            middleware_name=preflight.middleware_name,
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                        )
                    except (MiddlewarePolicyError, ScannerOwnershipError, ValueError):
                        self._record_decision(
                            decision=_DENY,
                            reason_code="effective_policy_invalid",
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            middleware_name=preflight.middleware_name,
                            target_host=preflight.target.host,
                            policy=self.policy,
                        )
                        yield pb2.WebSocketSessionEventResult(
                            preflight_decision=pb2.WebSocketPreflightDecision(
                                action=_WS_DENY,
                                reason_code="effective_policy_invalid",
                            )
                        )
                        return
                    if ownership_error:
                        self._record_decision(
                            decision=_DENY,
                            reason_code="scanner_ownership_unavailable",
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            middleware_name=preflight.middleware_name,
                            target_host=preflight.target.host,
                            policy=policy,
                        )
                        yield pb2.WebSocketSessionEventResult(
                            preflight_decision=pb2.WebSocketPreflightDecision(
                                action=_WS_DENY,
                                reason_code="scanner_ownership_unavailable",
                            )
                        )
                        return
                    if not selected:
                        skipped = True
                        yield pb2.WebSocketSessionEventResult(
                            preflight_decision=pb2.WebSocketPreflightDecision(
                                action=_SKIP
                            )
                        )
                    else:
                        yield pb2.WebSocketSessionEventResult(
                            preflight_decision=pb2.WebSocketPreflightDecision(
                                action=_INSPECT
                            )
                        )
                elif kind == "session_start":
                    if policy is None or skipped or started:
                        context.abort(
                            grpc.StatusCode.FAILED_PRECONDITION,
                            "invalid WebSocket session lifecycle",
                        )
                    started = True
                elif kind == "message":
                    if policy is None or skipped or not started:
                        context.abort(
                            grpc.StatusCode.FAILED_PRECONDITION,
                            "WebSocket message before session start",
                        )
                    assert policy is not None
                    message = event.message
                    if message.sequence <= sequence:
                        context.abort(
                            grpc.StatusCode.INVALID_ARGUMENT,
                            "WebSocket message sequence must increase",
                        )
                    sequence = message.sequence
                    payload = message.WhichOneof("payload")
                    if payload == "binary" and not policy.allow_binary_websocket:
                        self._record_decision(
                            decision=_DENY,
                            reason_code="unsupported_websocket_payload",
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            middleware_name=preflight.middleware_name,
                            target_host=preflight.target.host,
                            policy=policy,
                        )
                        yield pb2.WebSocketSessionEventResult(
                            message_result=pb2.WebSocketMessageResult(
                                sequence=message.sequence,
                                decision=_DENY,
                                reason_code="unsupported_websocket_payload",
                            )
                        )
                        return
                    if payload == "binary":
                        yield pb2.WebSocketSessionEventResult(
                            message_result=pb2.WebSocketMessageResult(
                                sequence=message.sequence,
                                decision=_ALLOW,
                            )
                        )
                        continue
                    if payload != "text":
                        context.abort(
                            grpc.StatusCode.INVALID_ARGUMENT,
                            "WebSocket payload is required",
                        )
                    text = message.text
                    if len(text.encode("utf-8")) > policy.max_payload_bytes:
                        self._record_decision(
                            decision=_DENY,
                            reason_code="payload_limit_exceeded",
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            middleware_name=preflight.middleware_name,
                            target_host=preflight.target.host,
                            policy=policy,
                        )
                        yield pb2.WebSocketSessionEventResult(
                            message_result=pb2.WebSocketMessageResult(
                                sequence=message.sequence,
                                decision=_DENY,
                                reason_code="payload_limit_exceeded",
                            )
                        )
                        return
                    try:
                        transformed, evaluation = self.scanner.inspect_payload(
                            text,
                            scanners=selected,
                            redact=policy.response_redaction,
                            filename="websocket-message",
                        )
                    except UnicodeDecodeError:
                        self._record_decision(
                            decision=_DENY,
                            reason_code="unsupported_payload_encoding",
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            middleware_name=preflight.middleware_name,
                            target_host=preflight.target.host,
                            policy=policy,
                        )
                        yield pb2.WebSocketSessionEventResult(
                            message_result=pb2.WebSocketMessageResult(
                                sequence=message.sequence,
                                decision=_DENY,
                                reason_code="unsupported_payload_encoding",
                            )
                        )
                        return
                    replacement = transformed if transformed != text else None
                    if (
                        replacement is not None
                        and len(replacement.encode("utf-8")) > policy.max_payload_bytes
                    ):
                        yield pb2.WebSocketSessionEventResult(
                            message_result=pb2.WebSocketMessageResult(
                                sequence=message.sequence,
                                decision=_DENY,
                                reason_code="payload_limit_exceeded",
                            )
                        )
                        return
                    message_result = {
                        "sequence": message.sequence,
                        "decision": _DENY if evaluation.blocked else _ALLOW,
                        "reason_code": (
                            _safe_reason_code(
                                evaluation.reason_code,
                                "semantic_content_blocked",
                            )
                            if evaluation.blocked
                            else ""
                        ),
                        "findings": self._findings(
                            evaluation.findings,
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            policy=policy,
                        ),
                        "metadata": self._decision_metadata(
                            (
                                _safe_reason_code(
                                    evaluation.reason_code, "semantic_content_blocked"
                                )
                                if evaluation.blocked
                                else ""
                            ),
                            evaluation.findings,
                            evaluation.metadata,
                        ),
                    }
                    if not evaluation.blocked:
                        self._record_decision(
                            decision=_ALLOW,
                            reason_code="",
                            findings=evaluation.findings,
                            metadata=evaluation.metadata,
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            middleware_name=preflight.middleware_name,
                            target_host=preflight.target.host,
                            policy=policy,
                        )
                    if replacement is not None and not evaluation.blocked:
                        message_result["text"] = replacement
                    if evaluation.blocked:
                        self._record_decision(
                            decision=_DENY,
                            reason_code=_safe_reason_code(
                                evaluation.reason_code, "semantic_content_blocked"
                            ),
                            findings=evaluation.findings,
                            metadata=evaluation.metadata,
                            request_id=request_id,
                            phase="pre_credentials",
                            direction="websocket",
                            middleware_name=preflight.middleware_name,
                            target_host=preflight.target.host,
                            policy=policy,
                        )
                    yield pb2.WebSocketSessionEventResult(
                        message_result=pb2.WebSocketMessageResult(**message_result)
                    )
                    if evaluation.blocked:
                        return
                elif kind == "session_end":
                    return
                else:
                    context.abort(
                        grpc.StatusCode.INVALID_ARGUMENT, "WebSocket event is required"
                    )

        def Evaluate(self, request_iterator, context):
            """Evaluate the ordered HTTP response pre-return stream."""

            state = _ResponseState(self)
            for event in request_iterator:
                kind = event.WhichOneof("event")
                try:
                    if kind == "preflight":
                        result = state.preflight(event.preflight, context)
                        yield result
                        if result.preflight_result.HasField("block_delivery"):
                            return
                    elif kind == "body":
                        result = state.body(event.body, context)
                        yield result
                        if result.body_result.HasField("block_delivery"):
                            return
                    elif kind == "trailers":
                        yield state.trailers(context)
                    elif kind == "session_end":
                        return
                    else:
                        context.abort(
                            grpc.StatusCode.INVALID_ARGUMENT,
                            "response event is required",
                        )
                except UnicodeDecodeError:
                    context.abort(
                        grpc.StatusCode.INVALID_ARGUMENT, "response body must be UTF-8"
                    )

        def _validate_gateway(self, gateway) -> None:
            if gateway is None or not gateway.HasField("protocol_version"):
                raise ValueError("gateway did not provide protocol metadata")
            version = gateway.protocol_version
            if version.major != OPEN_SHELL_PROTOCOL_MAJOR:
                raise ValueError(
                    f"unsupported OpenShell protocol {version.major}.{version.minor}; "
                    f"expected major {OPEN_SHELL_PROTOCOL_MAJOR}"
                )
            if _CONTRACT_CAPABILITY not in gateway.supported_capabilities:
                raise ValueError(
                    "gateway does not support supervisor-middleware contract"
                )
            missing = set(gateway.required_capabilities) - self.supported_capabilities
            if missing:
                raise ValueError(
                    "missing required gateway capabilities: "
                    + ", ".join(sorted(missing))
                )

        def _authorization_claims(self, context) -> Optional[Dict[str, Any]]:
            if self.authenticator is None:
                return None
            metadata = dict(context.invocation_metadata() or ())
            authorization = metadata.get("authorization", "")
            prefix = "Bearer "
            if not isinstance(authorization, str) or not authorization.startswith(
                prefix
            ):
                context.abort(
                    grpc.StatusCode.UNAUTHENTICATED,
                    "middleware authentication failed",
                )
            return self.authenticator.validate_token(
                authorization[len(prefix) :].strip()
            )

        def _authorize_gateway(self, context) -> None:
            claims = self._authorization_claims(context)
            if claims is not None and claims.get("caller_kind") != "gateway":
                context.abort(
                    grpc.StatusCode.PERMISSION_DENIED,
                    "gateway caller identity is required",
                )

        def _authorize_supervisor(self, context, request_context) -> None:
            claims = self._authorization_claims(context)
            if claims is None:
                return
            if claims.get("caller_kind") != "supervisor":
                context.abort(
                    grpc.StatusCode.PERMISSION_DENIED,
                    "supervisor caller identity is required",
                )
            request_sandbox_id = getattr(request_context, "sandbox_id", "")
            if request_sandbox_id != claims.get("sandbox_id"):
                context.abort(
                    grpc.StatusCode.PERMISSION_DENIED,
                    "supervisor sandbox identity does not match request context",
                )

        def _policy_for_struct(self, config) -> MiddlewarePolicy:
            raw = _struct_dict(config)
            if not raw:
                return self.policy
            for field in ("max_payload_bytes", "timeout_ms"):
                value = raw.get(field)
                if isinstance(value, float) and value.is_integer():
                    raw[field] = int(value)
            base = {
                "profile_id": self.policy.profile_id,
                "profile_digest": self.policy.profile_digest,
                "scanner_ownership": self.policy.scanner_ownership,
                "required_middleware_capabilities": list(
                    self.policy.required_middleware_capabilities
                ),
                "max_payload_bytes": self.policy.max_payload_bytes,
                "timeout_ms": self.policy.timeout_ms,
                "response_redaction": self.policy.response_redaction,
                "require_effective_policy": self.policy.require_effective_policy,
                "registration_name": self.policy.registration_name,
                "provider_endpoints": list(self.policy.provider_endpoints),
                "hooks_capabilities": list(self.policy.hooks_capabilities),
                "shared_correlation_id": self.policy.shared_correlation_id,
                "pre_persistence_deduplication": self.policy.pre_persistence_deduplication,
                "allow_binary_websocket": self.policy.allow_binary_websocket,
                "allow_unsupported_responses": self.policy.allow_unsupported_responses,
            }
            for field in _REQUEST_IMMUTABLE_POLICY_FIELDS:
                if field not in raw:
                    continue
                requested = raw[field]
                expected = base[field]
                if field in {"provider_endpoints", "hooks_capabilities"}:
                    requested_items = list(cast(Iterable[Any], requested))
                    expected_items = list(cast(Iterable[Any], expected))
                    if set(requested_items) != set(expected_items):
                        raise MiddlewarePolicyError(
                            f"middleware config cannot override operator field: {field}"
                        )
                    continue
                elif field == "profile_id":
                    requested = str(requested).lstrip("@")
                    expected = str(expected).lstrip("@")
                if requested != expected:
                    raise MiddlewarePolicyError(
                        f"middleware config cannot override operator field: {field}"
                    )
            base.update(raw)
            return MiddlewarePolicy.from_mapping(
                base,
                profile=self.policy.profile,
                default_profile_id=self.policy.profile_id,
                registration_name=self.policy.registration_name,
            )

        def _selected_scanners(
            self,
            policy: MiddlewarePolicy,
            *,
            target_host: str,
            middleware_name: str,
            request_id: str,
            phase: str,
            direction: str,
        ) -> tuple[set[str], str]:
            attached, attachment_reason = policy.validate_effective_policy(
                middleware_name=middleware_name,
                target_host=target_host,
            )
            if not attached:
                # Effective-policy validation is an authorization boundary,
                # not merely a hint for scanner routing.  Even a scanner
                # configured as ``hooks`` must not make an incorrectly
                # attached external service appear healthy.
                return set(), attachment_reason or "effective policy is invalid"
            decisions = resolve_scanner_ownership(
                policy.scanner_ownership,
                capabilities=self.supported_capabilities,
                policy_attached=attached,
                correlation_id_available=bool(request_id),
                deduplication_available=policy.pre_persistence_deduplication,
                hooks_capabilities=policy.hooks_capabilities,
            )
            failed = [
                decision
                for decision in decisions.values()
                if decision.effective_mode == "fail_closed"
            ]
            if failed:
                return set(), failed[0].reason
            return {
                decision.scanner
                for decision in decisions.values()
                if decision.effective_mode in {"middleware", "both"}
            }, ""

        def _request_result(
            self,
            evaluation: ContentEvaluation,
            transformed: str,
            original: bytes,
            *,
            request_id: str = "",
            middleware_name: str = "",
            target_host: str = "",
            policy: Optional[MiddlewarePolicy] = None,
        ):
            if evaluation.blocked:
                return self._denied_result(
                    _safe_reason_code(
                        evaluation.reason_code, "semantic_content_blocked"
                    ),
                    findings=evaluation.findings,
                    metadata=evaluation.metadata,
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                    middleware_name=middleware_name,
                    target_host=target_host,
                    policy=policy,
                )
            transformed_bytes = transformed.encode("utf-8")
            if policy is not None and len(transformed_bytes) > policy.max_payload_bytes:
                return self._denied_result(
                    "payload_limit_exceeded",
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                    middleware_name=middleware_name,
                    target_host=target_host,
                    policy=policy,
                )
            changed = transformed_bytes != original
            decision_metadata = self._decision_metadata(
                "", evaluation.findings, evaluation.metadata
            )
            self._record_decision(
                decision=_ALLOW,
                reason_code="",
                findings=evaluation.findings,
                metadata=evaluation.metadata,
                request_id=request_id,
                phase="pre_credentials",
                direction="request",
                middleware_name=middleware_name,
                target_host=target_host,
                policy=policy,
            )
            return pb2.HttpRequestResult(
                decision=_ALLOW,
                body=transformed_bytes if changed else b"",
                has_body=changed,
                findings=self._findings(
                    evaluation.findings,
                    request_id=request_id,
                    phase="pre_credentials",
                    direction="request",
                    policy=policy,
                ),
                metadata=decision_metadata,
            )

        def _denied_result(
            self,
            reason_code: str,
            *,
            findings=(),
            metadata=None,
            request_id: str = "",
            phase: str = "",
            direction: str = "",
            middleware_name: str = "",
            target_host: str = "",
            policy: Optional[MiddlewarePolicy] = None,
        ):
            finding_items = tuple(findings)
            safe_reason = _safe_reason_code(reason_code, "middleware_denied")
            decision_metadata = self._decision_metadata(
                safe_reason, finding_items, metadata
            )
            self._record_decision(
                decision=_DENY,
                reason_code=safe_reason,
                findings=finding_items,
                metadata=metadata,
                request_id=request_id,
                phase=phase,
                direction=direction,
                middleware_name=middleware_name,
                target_host=target_host,
                policy=policy,
            )
            return pb2.HttpRequestResult(
                decision=_DENY,
                reason=self._decision_message(safe_reason, finding_items),
                reason_code=safe_reason,
                findings=self._findings(
                    finding_items,
                    request_id=request_id,
                    phase=phase,
                    direction=direction,
                    policy=policy,
                ),
                metadata=decision_metadata,
            )

        def _findings(
            self,
            findings: Iterable[ContentFinding],
            *,
            request_id: str = "",
            phase: str = "",
            direction: str = "",
            policy: Optional[MiddlewarePolicy] = None,
        ):
            items = list(findings)
            effective_policy = policy or self.policy
            if (
                effective_policy.shared_correlation_id
                and effective_policy.pre_persistence_deduplication
                and request_id
            ):
                unique: list[ContentFinding] = []
                for index, finding in enumerate(items):
                    key = FindingKey(
                        correlation_id=request_id,
                        scanner=finding.type,
                        phase=phase,
                        direction=direction,
                        segment=str(index),
                        rule_id=finding.rule_id,
                    )
                    if self.deduplicator.first_seen(key):
                        unique.append(finding)
                items = unique
            return [
                pb2.Finding(
                    type=finding.type[:128],
                    label=finding.label[:128],
                    count=min(2**32 - 1, max(1, finding.count)),
                    confidence=finding.confidence[:32],
                    severity=finding.severity[:32],
                )
                for finding in items[:32]
            ]

    class _ResponseState:
        """State machine for one OpenShell response evaluation stream."""

        def __init__(self, service: MiddlewareService):
            self.service = service
            self.policy: Optional[MiddlewarePolicy] = None
            self.scanners: set[str] = set()
            self.mode: Optional[int] = None
            self.next_sequence = 1
            self.body_complete = False
            self.trailers_seen = False
            self.request_id = ""
            self.max_payload_bytes = 0
            self.middleware_name = ""
            self.target_host = ""

        def preflight(self, event, context):
            if self.policy is not None:
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION, "duplicate response preflight"
                )
            self.service._authorize_supervisor(context, event.context)
            try:
                self.policy = self.service._policy_for_struct(event.config)
            except (MiddlewarePolicyError, ScannerOwnershipError, ValueError):
                self.service._record_decision(
                    decision=_DENY,
                    reason_code="effective_policy_invalid",
                    request_id=event.context.request_id,
                    phase="pre_return",
                    direction="response",
                    middleware_name=event.middleware_name,
                    target_host=event.target.host,
                    policy=self.service.policy,
                )
                return pb2.HttpResponseEventResult(
                    preflight_result=pb2.HttpResponsePreflightResult(
                        block_delivery=pb2.HttpResponseBlockDelivery(),
                        reason_code="effective_policy_invalid",
                    )
                )
            assert self.policy is not None
            policy = self.policy
            self.max_payload_bytes = min(
                policy.max_payload_bytes,
                event.max_payload_bytes or policy.max_payload_bytes,
            )
            if event.context.request_id == "":
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "response request_id is required",
                )
            self.request_id = event.context.request_id
            self.middleware_name = event.middleware_name
            self.target_host = event.target.host
            attached, _ = policy.validate_effective_policy(
                middleware_name=event.middleware_name,
                target_host=event.target.host,
            )
            if not attached:
                self.service._record_decision(
                    decision=_DENY,
                    reason_code="effective_policy_invalid",
                    request_id=self.request_id,
                    phase="pre_return",
                    direction="response",
                    middleware_name=event.middleware_name,
                    target_host=event.target.host,
                    policy=policy,
                )
                return pb2.HttpResponseEventResult(
                    preflight_result=pb2.HttpResponsePreflightResult(
                        block_delivery=pb2.HttpResponseBlockDelivery(),
                        reason_code="effective_policy_invalid",
                    )
                )
            decisions = resolve_scanner_ownership(
                policy.scanner_ownership,
                capabilities=self.service.supported_capabilities,
                policy_attached=True,
                correlation_id_available=True,
                deduplication_available=policy.pre_persistence_deduplication,
                hooks_capabilities=policy.hooks_capabilities,
            )
            if any(item.effective_mode == "fail_closed" for item in decisions.values()):
                self.service._record_decision(
                    decision=_DENY,
                    reason_code="scanner_ownership_unavailable",
                    request_id=self.request_id,
                    phase="pre_return",
                    direction="response",
                    middleware_name=event.middleware_name,
                    target_host=event.target.host,
                    policy=policy,
                )
                return pb2.HttpResponseEventResult(
                    preflight_result=pb2.HttpResponsePreflightResult(
                        block_delivery=pb2.HttpResponseBlockDelivery(),
                        reason_code="scanner_ownership_unavailable",
                    )
                )
            self.scanners = {
                item.scanner
                for item in decisions.values()
                if item.effective_mode in {"middleware", "both"}
            }
            if not self.scanners:
                return pb2.HttpResponseEventResult(
                    preflight_result=pb2.HttpResponsePreflightResult(
                        skip=pb2.HttpResponsePreflightSkip()
                    )
                )
            permitted = set(event.permitted_body_modes)
            if _WHOLE_BODY in permitted:
                self.mode = _WHOLE_BODY
            elif _STREAM_BODY in permitted:
                self.mode = _STREAM_BODY
            elif policy.allow_unsupported_responses:
                return pb2.HttpResponseEventResult(
                    preflight_result=pb2.HttpResponsePreflightResult(
                        skip=pb2.HttpResponsePreflightSkip(),
                        reason_code="unsupported_response_body_mode",
                    )
                )
            else:
                self.service._record_decision(
                    decision=_DENY,
                    reason_code="unsupported_response_body_mode",
                    request_id=self.request_id,
                    phase="pre_return",
                    direction="response",
                    middleware_name=event.middleware_name,
                    target_host=event.target.host,
                    policy=policy,
                )
                return pb2.HttpResponseEventResult(
                    preflight_result=pb2.HttpResponsePreflightResult(
                        block_delivery=pb2.HttpResponseBlockDelivery(),
                        reason_code="unsupported_response_body_mode",
                    )
                )
            return pb2.HttpResponseEventResult(
                preflight_result=pb2.HttpResponsePreflightResult(
                    inspect=pb2.HttpResponsePreflightInspect(body_mode=self.mode)
                )
            )

        def body(self, event, context):
            if self.policy is None or self.mode is None:
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "response body before inspection preflight",
                )
            assert self.policy is not None
            policy = self.policy
            if event.sequence != self.next_sequence:
                context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "response body sequence must increase",
                )
            if event.WhichOneof("payload") != "data":
                context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, "response body data is required"
                )
            data = bytes(event.data)
            if len(data) > self.max_payload_bytes:
                return self._block_body("payload_limit_exceeded", event.sequence)
            if self.mode == _WHOLE_BODY and (
                event.sequence != 1 or not event.end_of_stream
            ):
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "WHOLE_BODY_BYTES requires one final body unit",
                )
            try:
                transformed, evaluation = self.service.scanner.inspect_payload(
                    data,
                    scanners=self.scanners,
                    redact=policy.response_redaction,
                    filename="provider-response",
                )
            except UnicodeDecodeError:
                return self._block_body("unsupported_payload_encoding", event.sequence)
            self.next_sequence += 1
            self.body_complete = event.end_of_stream
            transformed_bytes = transformed.encode("utf-8")
            if len(transformed_bytes) > self.max_payload_bytes:
                return self._block_body("payload_limit_exceeded", event.sequence)
            if evaluation.blocked:
                return self._block_body(
                    _safe_reason_code(
                        evaluation.reason_code, "semantic_content_blocked"
                    ),
                    event.sequence,
                    findings=evaluation.findings,
                    metadata=evaluation.metadata,
                )
            self.service._record_decision(
                decision=_ALLOW,
                reason_code="",
                findings=evaluation.findings,
                metadata=evaluation.metadata,
                request_id=self.request_id,
                phase="pre_return",
                direction="response",
                middleware_name=self.middleware_name,
                target_host=self.target_host,
                policy=policy,
            )
            decision_metadata = self.service._decision_metadata(
                "", evaluation.findings, evaluation.metadata
            )
            action = (
                pb2.HttpResponseBodyResult(
                    sequence=event.sequence,
                    transform=pb2.HttpResponseBodyTransform(data=transformed_bytes),
                    findings=self.service._findings(
                        evaluation.findings,
                        request_id=self.request_id,
                        phase="pre_return",
                        direction="response",
                        policy=policy,
                    ),
                    metadata=decision_metadata,
                )
                if transformed_bytes != data
                else pb2.HttpResponseBodyResult(
                    sequence=event.sequence,
                    pass_through=pb2.HttpResponseBodyPassThrough(),
                    findings=self.service._findings(
                        evaluation.findings,
                        request_id=self.request_id,
                        phase="pre_return",
                        direction="response",
                        policy=policy,
                    ),
                    metadata=decision_metadata,
                )
            )
            return pb2.HttpResponseEventResult(body_result=action)

        def trailers(self, context):
            if not self.body_complete or self.trailers_seen:
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "response trailers arrived before the final body",
                )
            self.trailers_seen = True
            return pb2.HttpResponseEventResult(
                trailers_result=pb2.HttpResponseTrailersResult()
            )

        def _block_body(self, reason_code, sequence, *, findings=(), metadata=None):
            policy = self.policy
            finding_items = tuple(findings)
            safe_reason = _safe_reason_code(reason_code, "middleware_denied")
            self.service._record_decision(
                decision=_DENY,
                reason_code=safe_reason,
                findings=finding_items,
                metadata=metadata,
                request_id=self.request_id,
                phase="pre_return",
                direction="response",
                middleware_name=self.middleware_name,
                target_host=self.target_host,
                policy=policy,
            )
            return pb2.HttpResponseEventResult(
                body_result=pb2.HttpResponseBodyResult(
                    sequence=sequence,
                    block_delivery=pb2.HttpResponseBlockDelivery(),
                    reason_code=safe_reason,
                    findings=self.service._findings(
                        finding_items,
                        request_id=self.request_id,
                        phase="pre_return",
                        direction="response",
                        policy=policy,
                    ),
                    metadata=self.service._decision_metadata(
                        safe_reason, finding_items, metadata
                    ),
                )
            )

else:

    class MiddlewareService:  # type: ignore[no-redef]  # pragma: no cover - error path
        """Placeholder that keeps normal installations importable."""

        def __init__(self, *args, **kwargs):
            require_grpc()


def _duration(timeout_ms: int):
    total_nanos = timeout_ms * 1_000_000
    seconds, nanos = divmod(total_nanos, 1_000_000_000)
    return duration_pb2.Duration(seconds=seconds, nanos=nanos)


def _bind_host(bind: str) -> str:
    """Extract the host portion from a gRPC ``HOST:PORT`` bind address."""

    value = bind.strip()
    if value.startswith("["):
        closing = value.find("]")
        if closing > 0:
            return value[1:closing]
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


def _is_wildcard_bind(bind: str) -> bool:
    """Return whether a bind address listens on every local interface."""

    host = _bind_host(bind).strip().lower()
    if host in {"", "*"}:
        return True
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return host in {"0.0.0.0", "::"}


def _validate_bind_security(bind: str, security: MiddlewareServerSecurity) -> None:
    """Prevent unauthenticated plaintext services from using wildcard binds."""

    if (
        security.allow_insecure_transport
        and _is_wildcard_bind(bind)
        and not security.allow_insecure_wildcard_bind
    ):
        raise ValueError(
            "insecure middleware transport cannot bind to wildcard address "
            f"{bind!r}; bind to a specific trusted interface, explicitly enable "
            "allow_insecure_wildcard_bind for local development, or configure TLS/JWT"
        )


def _is_loopback_bind(bind: str) -> bool:
    """Return whether a bind address listens only on loopback."""

    host = _bind_host(bind).strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _needs_macos_tcp_relay(bind: str, security: MiddlewareServerSecurity) -> bool:
    """Use a host-interface relay for macOS plaintext gRPC services.

    grpcio on macOS can accept a non-loopback listener but close incoming HTTP/2
    connections.  OpenShell's Podman supervisor needs a host-reachable endpoint,
    so keep grpcio on loopback and relay only the explicitly selected interface.
    TLS deployments do not use this development-only relay.
    """

    return (
        sys.platform == "darwin"
        and security.allow_insecure_transport
        and not _is_loopback_bind(bind)
        and not _is_wildcard_bind(bind)
    )


def _rust_middleware_binary() -> Optional[Path]:
    """Locate the Rust middleware executable for the explicit Rust runtime."""

    configured = os.environ.get("AI_GUARDIAN_RUST_MIDDLEWARE")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() and os.access(path, os.X_OK) else None
    discovered = shutil.which("ai-guardian-openshell-middleware")
    if discovered:
        return Path(discovered)
    repository_root = Path(__file__).resolve().parents[5]
    for profile in ("release", "debug"):
        candidate = (
            repository_root
            / "rust"
            / "openshell-middleware"
            / "target"
            / profile
            / "ai-guardian-openshell-middleware"
        )
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _bind_port(bind: str) -> int:
    """Extract and validate TCP port from a gRPC bind address."""

    value = bind.strip()
    if value.startswith("["):
        closing = value.find("]")
        if closing > 0 and value[closing + 1 :].startswith(":"):
            return int(value[closing + 2 :])
    if value.count(":") == 1:
        return int(value.rsplit(":", 1)[1])
    raise ValueError(f"middleware bind address must include a TCP port: {bind!r}")


def _free_loopback_bind() -> str:
    """Reserve a currently free loopback port for the local gRPC listener."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{probe.getsockname()[1]}"


class _MiddlewareTcpRelay:
    """Relay one selected host interface to a loopback gRPC listener."""

    def __init__(self, external_bind: str, internal_bind: str) -> None:
        self.external_bind = external_bind
        self.internal_host = _bind_host(internal_bind)
        self.internal_port = _bind_port(internal_bind)
        self._listener: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()
        self._connections: set[tuple[socket.socket, socket.socket]] = set()
        self._connections_lock = threading.Lock()

    def start(self) -> None:
        host = _bind_host(self.external_bind)
        port = _bind_port(self.external_bind)
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        listener = socket.socket(family, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            listener.bind((host, port, 0, 0))
        else:
            listener.bind((host, port))
        listener.listen(64)
        listener.settimeout(0.5)
        self._listener = listener
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="openshell-middleware-relay",
            daemon=True,
        )
        self._thread.start()

    def _accept_loop(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stopping.is_set():
            try:
                client, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._proxy_connection,
                args=(client,),
                name="openshell-middleware-relay-connection",
                daemon=True,
            ).start()

    def _proxy_connection(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(
                (self.internal_host, self.internal_port), timeout=5
            )
        except OSError as exc:
            logger.debug(
                "middleware relay could not connect to loopback gRPC listener: %s",
                type(exc).__name__,
            )
            client.close()
            return

        connection = (client, upstream)
        with self._connections_lock:
            self._connections.add(connection)
        try:
            client.settimeout(None)
            upstream.settimeout(None)
            workers = (
                threading.Thread(
                    target=self._copy_stream,
                    args=(client, upstream),
                    daemon=True,
                ),
                threading.Thread(
                    target=self._copy_stream,
                    args=(upstream, client),
                    daemon=True,
                ),
            )
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        finally:
            with self._connections_lock:
                self._connections.discard(connection)
            client.close()
            upstream.close()

    @staticmethod
    def _copy_stream(source: socket.socket, target: socket.socket) -> None:
        try:
            while True:
                readable, _writeable, _exceptional = select.select([source], [], [], 1)
                if not readable:
                    continue
                data = source.recv(64 * 1024)
                if not data:
                    try:
                        target.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    return
                target.sendall(data)
        except OSError as exc:
            logger.debug("middleware relay connection closed: %s", type(exc).__name__)

    def stop(self) -> None:
        self._stopping.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._connections_lock:
            connections = tuple(self._connections)
        for client, upstream in connections:
            for connection in (client, upstream):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    connection.close()
                except OSError:
                    pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2)


def create_server(
    service: "MiddlewareService",
    *,
    bind: str,
    security: MiddlewareServerSecurity,
    workers: int = 16,
):
    """Create, register, and bind the external middleware gRPC server."""

    require_grpc()
    if workers < 1:
        raise ValueError("workers must be positive")
    security.validate()
    _validate_bind_security(bind, security)
    options = [
        # OpenShell allows a 4 MiB payload plus the surrounding protobuf
        # message.  Keep the transport ceiling at the documented 4.5 MiB
        # minimum so a maximum-size body is not rejected before policy code
        # can return a fail-closed decision.
        ("grpc.max_receive_message_length", MAX_PAYLOAD_BYTES + 512 * 1024),
        ("grpc.max_send_message_length", MAX_PAYLOAD_BYTES + 512 * 1024),
    ]
    interceptors = (
        [] if security.allow_insecure_transport else [JwtAuthInterceptor(security)]
    )
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=workers),
        options=options,
        interceptors=interceptors,
    )
    pb2_grpc.add_SupervisorMiddlewareServicer_to_server(service, server)
    pb2_grpc.add_HttpResponsePreReturnServicer_to_server(service, server)
    credentials = security.server_credentials()
    if credentials is None:
        if server.add_insecure_port(bind) == 0:
            raise ValueError(f"unable to bind middleware server to {bind}")
    else:
        if server.add_secure_port(bind, credentials) == 0:
            raise ValueError(f"unable to bind middleware server to {bind}")
    return server


def _middleware_state_path(args, suffix: str) -> Path:
    """Return an explicit or per-user state path for middleware lifecycle data."""

    option = f"{suffix}_file"
    configured = getattr(args, option, None)
    if configured:
        return Path(configured).expanduser()
    from ai_guardian.daemon import get_state_dir

    return get_state_dir() / f"openshell-middleware.{suffix}"


def _read_middleware_pid_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("unable to read middleware PID file %s: %s", path, exc)
        return {}
    if not isinstance(value, dict):
        logger.warning("middleware PID file does not contain an object: %s", path)
        return {}
    return value


def _middleware_pid(value: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not value:
        return None
    pid = value.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    return pid


_MIDDLEWARE_LIFECYCLE_COMMANDS = frozenset({"start", "stop", "status", "restart"})
_MIDDLEWARE_LIFECYCLE_FLAGS = frozenset(
    {"--background", "-b", "--stop", "--restart", "--status"}
)
_MIDDLEWARE_RESTART_VALUE_OPTIONS = frozenset(
    {
        "--config",
        "--implementation",
        "--openshell-version",
        "--gateway-config",
        "--gateway-endpoint",
        "--gateway-tls-ca",
        "--policy-out",
        "--policy-name",
        "--profile",
        "--bind",
        "--workers",
        "--violation-log",
        "--tls-cert",
        "--tls-key",
        "--tls-client-ca",
        "--jwt-secret",
        "--jwt-public-key",
        "--jwt-audience",
        "--pid-file",
        "--log-file",
    }
)
_MIDDLEWARE_RESTART_BOOLEAN_OPTIONS = frozenset(
    {
        "--bootstrap-openshell",
        "--bootstrap-force",
        "--allow-insecure-transport",
        "--allow-insecure-wildcard-bind",
    }
)


def _middleware_option_value(values: Sequence[str], option: str) -> Optional[str]:
    """Return an option value from an argv-style sequence."""

    for index, value in enumerate(values):
        if value == option:
            if index + 1 < len(values):
                return values[index + 1]
            return None
        prefix = f"{option}="
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def _replace_middleware_option(
    values: Sequence[str], option: str, replacement: str
) -> list[str]:
    """Replace one option in saved middleware arguments, preserving its form."""

    replaced: list[str] = []
    found = False
    index = 0
    while index < len(values):
        value = values[index]
        if value == option:
            replaced.extend((option, replacement))
            found = True
            index += 2 if index + 1 < len(values) else 1
            continue
        prefix = f"{option}="
        if value.startswith(prefix):
            replaced.append(f"{option}={replacement}")
            found = True
            index += 1
            continue
        replaced.append(value)
        index += 1
    if not found:
        replaced.extend((option, replacement))
    return replaced


def _merge_middleware_restart_args(
    saved_values: Sequence[str], current_values: Sequence[str]
) -> list[str]:
    """Apply explicitly supplied restart options to the saved start command."""

    merged = list(saved_values)
    for option in _MIDDLEWARE_RESTART_VALUE_OPTIONS:
        value = _middleware_option_value(current_values, option)
        if value is not None:
            merged = _replace_middleware_option(merged, option, value)
    for option in _MIDDLEWARE_RESTART_BOOLEAN_OPTIONS:
        if option in current_values and option not in merged:
            merged.append(option)
    return merged


def _safe_middleware_restart_args(values: Sequence[str]) -> list[str]:
    """Remove secret values before persisting a background restart command."""

    safe_values: list[str] = []
    skip_secret_value = False
    for value in values:
        if skip_secret_value:
            skip_secret_value = False
            continue
        if value == "--jwt-secret":
            skip_secret_value = True
            continue
        if value.startswith("--jwt-secret="):
            continue
        safe_values.append(value)
    return safe_values


def _saved_middleware_restart_args(
    info: Optional[Mapping[str, Any]],
) -> Optional[list[str]]:
    """Validate restart arguments loaded from the private middleware state file."""

    if not info:
        return None
    values = info.get("restart_args")
    if not isinstance(values, list) or not values:
        return None
    if any(not isinstance(value, str) for value in values):
        return None
    return list(values)


def _middleware_process_matches(pid: int) -> bool:
    """Check that a live PID appears to be an OpenShell middleware process."""

    from ai_guardian.daemon import is_pid_active

    if not is_pid_active(pid):
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # Windows does not expose /proc; the PID file is private and the
        # process was created by this launcher, so liveness is the available
        # portable identity check here.
        return True
    try:
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except OSError:
        # Some POSIX systems restrict command-line inspection.  Do not treat a
        # live PID as stale merely because that optional check is unavailable.
        return True
    return (
        b"openshell-middleware" in command_line or b"middleware-server" in command_line
    )


def _write_middleware_pid_file(
    path: Path,
    pid: int,
    *,
    restart_args: Optional[Sequence[str]] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    try:
        payload = {
            "pid": pid,
            "started_at": int(time.time()),
            "service": "openshell-middleware",
        }
        if restart_args is not None:
            safe_restart_args = _safe_middleware_restart_args(restart_args)
            payload["restart_args"] = safe_restart_args
            config_path = _middleware_option_value(safe_restart_args, "--config")
            if config_path:
                payload["config"] = config_path
        try:
            os.chmod(temporary_name, 0o600)
        except OSError:
            logger.warning(
                "unable to restrict middleware PID file permissions: %s", path
            )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _remove_middleware_pid_file(
    path: Path, *, expected_pid: Optional[int] = None
) -> None:
    if expected_pid is not None:
        current = _middleware_pid(_read_middleware_pid_file(path))
        if current != expected_pid:
            return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("unable to remove middleware PID file: %s", path)


def _claim_middleware_pid_file(
    path: Path, *, restart_args: Optional[Sequence[str]] = None
) -> None:
    existing = _read_middleware_pid_file(path)
    existing_pid = _middleware_pid(existing)
    if existing_pid and existing_pid != os.getpid():
        from ai_guardian.daemon import is_pid_active

        if is_pid_active(existing_pid):
            if _middleware_process_matches(existing_pid):
                raise RuntimeError(
                    f"OpenShell middleware is already running (pid {existing_pid})"
                )
            raise RuntimeError(
                f"middleware PID file points to an unrelated active process (pid {existing_pid})"
            )
        _remove_middleware_pid_file(path, expected_pid=existing_pid)
    _write_middleware_pid_file(path, os.getpid(), restart_args=restart_args)


def _middleware_command_without_lifecycle_flags(
    *,
    pid_path: Path,
    log_path: Path,
    argv: Optional[Sequence[str]] = None,
) -> list[str]:
    values = _middleware_command_arguments(
        pid_path=pid_path,
        log_path=log_path,
        argv=argv,
    )
    from ai_guardian.daemon import get_executable_command

    return get_executable_command() + values


def _middleware_command_arguments(
    *,
    pid_path: Path,
    log_path: Path,
    argv: Optional[Sequence[str]] = None,
) -> list[str]:
    """Build foreground middleware arguments from current or saved argv."""

    source_values = list(sys.argv[1:] if argv is None else argv)
    values = [
        value
        for value in source_values
        if value not in _MIDDLEWARE_LIFECYCLE_COMMANDS
        and value not in _MIDDLEWARE_LIFECYCLE_FLAGS
    ]
    if not any(
        value == "--pid-file" or value.startswith("--pid-file=") for value in values
    ):
        values.extend(("--pid-file", str(pid_path)))
    if not any(
        value == "--log-file" or value.startswith("--log-file=") for value in values
    ):
        values.extend(("--log-file", str(log_path)))
    return values


def _start_middleware_background(
    args,
    *,
    restart_args: Optional[Sequence[str]] = None,
) -> int:
    pid_path = _middleware_state_path(args, "pid")
    log_path = _middleware_state_path(args, "log")
    existing_pid = _middleware_pid(_read_middleware_pid_file(pid_path))
    if existing_pid:
        from ai_guardian.daemon import is_pid_active

        if is_pid_active(existing_pid):
            if _middleware_process_matches(existing_pid):
                print(
                    f"ai-guardian openshell-middleware is already running (pid {existing_pid})"
                )
            else:
                print(
                    f"Refusing to start: middleware PID file belongs to active process {existing_pid}",
                    file=sys.stderr,
                )
            return 1
        _remove_middleware_pid_file(pid_path, expected_pid=existing_pid)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    command_values = _middleware_command_arguments(
        pid_path=pid_path,
        log_path=log_path,
        argv=restart_args,
    )
    if restart_args is not None and not getattr(args, "log_file", None):
        saved_log_path = _middleware_option_value(command_values, "--log-file")
        if saved_log_path:
            log_path = Path(saved_log_path).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
    from ai_guardian.daemon import get_executable_command

    command = get_executable_command() + command_values
    log_handle = None
    try:
        log_descriptor = os.open(
            str(log_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.chmod(log_path, 0o600)
        except OSError:
            logger.warning(
                "unable to restrict middleware log permissions: %s", log_path
            )
        log_handle = os.fdopen(log_descriptor, "a", encoding="utf-8")
        process_kwargs: Dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if os.name == "nt":
            process_kwargs["creationflags"] = getattr(
                subprocess, "DETACHED_PROCESS", 0
            ) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **process_kwargs)
    except OSError as exc:
        print(
            f"Failed to start OpenShell middleware in background: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if log_handle is not None:
            log_handle.close()

    try:
        _write_middleware_pid_file(
            pid_path,
            process.pid,
            restart_args=command_values,
        )
    except OSError as exc:
        try:
            process.terminate()
        except OSError:
            pass
        print(f"Failed to write middleware PID file: {exc}", file=sys.stderr)
        return 1

    time.sleep(0.1)
    from ai_guardian.daemon import is_pid_active

    if not is_pid_active(process.pid):
        _remove_middleware_pid_file(pid_path, expected_pid=process.pid)
        print(
            f"OpenShell middleware exited during startup; inspect {log_path}",
            file=sys.stderr,
        )
        return 1
    print(
        f"ai-guardian openshell-middleware started in background "
        f"(pid {process.pid}, log {log_path})"
    )
    return 0


def _stop_middleware_background(args, *, quiet: bool = False) -> int:
    pid_path = _middleware_state_path(args, "pid")
    info = _read_middleware_pid_file(pid_path)
    pid = _middleware_pid(info)
    if pid is None:
        if not quiet:
            print("ai-guardian openshell-middleware is not running")
        return 0
    from ai_guardian.daemon import is_pid_active

    if not is_pid_active(pid):
        _remove_middleware_pid_file(pid_path, expected_pid=pid)
        if not quiet:
            print("ai-guardian openshell-middleware is not running (stale PID removed)")
        return 0
    if not _middleware_process_matches(pid):
        print(
            f"Refusing to stop unrelated active process {pid} from {pid_path}",
            file=sys.stderr,
        )
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        print(f"Failed to stop OpenShell middleware: {exc}", file=sys.stderr)
        return 1

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and is_pid_active(pid):
        time.sleep(0.1)
    if is_pid_active(pid):
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except ProcessLookupError:
            pass
        except OSError as exc:
            print(f"Failed to force-stop OpenShell middleware: {exc}", file=sys.stderr)
            return 1
        if is_pid_active(pid):
            print(
                f"OpenShell middleware (pid {pid}) did not exit within 10 seconds",
                file=sys.stderr,
            )
            return 1
    _remove_middleware_pid_file(pid_path, expected_pid=pid)
    if not quiet:
        print(f"ai-guardian openshell-middleware stopped (pid {pid})")
    return 0


def _status_middleware_background(args) -> int:
    pid_path = _middleware_state_path(args, "pid")
    log_path = _middleware_state_path(args, "log")
    info = _read_middleware_pid_file(pid_path)
    pid = _middleware_pid(info)
    from ai_guardian.daemon import is_pid_active

    if pid is None or not is_pid_active(pid):
        if pid is not None:
            _remove_middleware_pid_file(pid_path, expected_pid=pid)
        print("ai-guardian openshell-middleware: not running")
        return 1
    if not _middleware_process_matches(pid):
        print(
            f"ai-guardian openshell-middleware: PID {pid} is an unrelated process",
            file=sys.stderr,
        )
        return 1
    print(f"ai-guardian openshell-middleware: running (pid {pid})")
    print(f"PID file: {pid_path}")
    print(f"Log: {log_path}")
    config_path = info.get("config") if info else None
    if isinstance(config_path, str) and config_path:
        print(f"Config: {config_path}")
    return 0


def run_middleware_server(args) -> int:
    """CLI handler for ``ai-guardian openshell-middleware``."""

    lifecycle_command = getattr(args, "middleware_command", None)
    if lifecycle_command == "stop" or getattr(args, "stop", False):
        return _stop_middleware_background(args)
    if lifecycle_command == "status" or getattr(args, "status", False):
        return _status_middleware_background(args)
    restart_requested = lifecycle_command == "restart" or getattr(
        args, "restart", False
    )
    restart_args: Optional[list[str]] = None
    if restart_requested:
        pid_path = _middleware_state_path(args, "pid")
        saved_info = _read_middleware_pid_file(pid_path)
        saved_args = _saved_middleware_restart_args(saved_info)
        if getattr(args, "config", None):
            if saved_args is not None:
                restart_args = _merge_middleware_restart_args(saved_args, sys.argv[1:])
        else:
            restart_args = saved_args
            if restart_args is None or not _middleware_option_value(
                restart_args, "--config"
            ):
                print(
                    "Error: no saved middleware configuration is available; "
                    "provide --config or start the service with a background command",
                    file=sys.stderr,
                )
                return 1
    if not getattr(args, "config", None) and not restart_requested:
        print(
            "Error: --config is required when starting OpenShell middleware",
            file=sys.stderr,
        )
        return 1
    if restart_requested:
        if _stop_middleware_background(args, quiet=True) != 0:
            return 1
        return _start_middleware_background(args, restart_args=restart_args)
    if getattr(args, "background", False):
        return _start_middleware_background(args)

    claimed_pid = False
    pid_path = _middleware_state_path(args, "pid")
    relay: Optional[_MiddlewareTcpRelay] = None
    try:
        if getattr(args, "implementation", None) != "rust":
            require_grpc()
        _claim_middleware_pid_file(
            pid_path,
            restart_args=_middleware_command_arguments(
                pid_path=pid_path,
                log_path=_middleware_state_path(args, "log"),
            ),
        )
        claimed_pid = True
        policy, raw = load_operator_policy(args.config, profile_override=args.profile)
        security_overrides: Dict[str, Any] = {}
        raw_tls = raw.get("tls", {})
        if raw_tls is None:
            raw_tls = {}
        if not isinstance(raw_tls, Mapping):
            raise ValueError("tls settings must be an object")
        tls_override = dict(raw_tls)
        for option, field in (
            ("tls_cert", "cert_file"),
            ("tls_key", "key_file"),
            ("tls_client_ca", "client_ca_file"),
        ):
            value = getattr(args, option, None)
            if value:
                tls_override[field] = value
        if tls_override != raw_tls:
            security_overrides["tls"] = tls_override
        raw_jwt = raw.get("jwt", {})
        if raw_jwt is None:
            raw_jwt = {}
        if not isinstance(raw_jwt, Mapping):
            raise ValueError("jwt settings must be an object")
        jwt_override = dict(raw_jwt)
        if getattr(args, "jwt_secret", None) or getattr(args, "jwt_public_key", None):
            if args.jwt_secret:
                jwt_override["secret"] = args.jwt_secret
                jwt_override.pop("public_key_file", None)
            else:
                jwt_override["public_key_file"] = args.jwt_public_key
                jwt_override.pop("secret", None)
        if getattr(args, "jwt_audience", None):
            jwt_override["audience"] = args.jwt_audience
        if jwt_override != raw_jwt:
            security_overrides["jwt"] = jwt_override
        if getattr(args, "allow_insecure_transport", False):
            security_overrides["allow_insecure_transport"] = True
        if getattr(args, "allow_insecure_wildcard_bind", False):
            security_overrides["allow_insecure_wildcard_bind"] = True
        security = MiddlewareServerSecurity.from_mapping(
            raw,
            overrides=security_overrides,
            default_audience=(
                f"urn:openshell:extension:middleware:{policy.registration_name}"
                if policy.registration_name
                else None
            ),
        )
        _validate_bind_security(args.bind, security)
        bootstrap_requested = bool(getattr(args, "bootstrap_openshell", False))
        bootstrap_options_supplied = any(
            getattr(args, option, None)
            for option in (
                "gateway_config",
                "gateway_endpoint",
                "gateway_tls_ca",
                "policy_out",
                "policy_name",
            )
        ) or bool(getattr(args, "bootstrap_force", False))
        if bootstrap_options_supplied and not bootstrap_requested:
            raise OpenShellBootstrapError(
                "OpenShell bootstrap options require --bootstrap-openshell"
            )
        bootstrap_result = None
        if bootstrap_requested:
            gateway_config = getattr(args, "gateway_config", None) or (
                Path.home() / ".config" / "openshell" / "gateway.toml"
            )
            policy_file = getattr(args, "policy_out", None) or (
                Path(args.config).expanduser().with_name("openshell-policy.yaml")
            )
            bootstrap_result = bootstrap_openshell(
                policy,
                bind=args.bind,
                gateway_config=gateway_config,
                policy_file=policy_file,
                allow_insecure_transport=security.allow_insecure_transport,
                gateway_endpoint=getattr(args, "gateway_endpoint", None),
                gateway_tls_ca_path=getattr(args, "gateway_tls_ca", None),
                audience=security.jwt_audience,
                attachment_name=getattr(args, "policy_name", None),
                force=bool(getattr(args, "bootstrap_force", False)),
            )
        if getattr(args, "implementation", None) == "rust":
            if not security.allow_insecure_transport:
                raise ValueError(
                    "the Rust middleware runtime currently requires explicit "
                    "allow_insecure_transport; use the Python runtime for TLS/JWT"
                )
            rust_binary = _rust_middleware_binary()
            if rust_binary is None:
                raise RuntimeError(
                    "Rust middleware binary not found; build "
                    "rust/openshell-middleware or set AI_GUARDIAN_RUST_MIDDLEWARE"
                )
            rust_environment = os.environ.copy()
            rust_environment["AI_GUARDIAN_MIDDLEWARE_BIND"] = args.bind
            rust_environment["AI_GUARDIAN_MIDDLEWARE_REGISTRATION"] = (
                policy.registration_name
            )
            rust_environment["AI_GUARDIAN_MIDDLEWARE_PID_FILE"] = str(pid_path)
            os.execve(str(rust_binary), [str(rust_binary)], rust_environment)
        from ai_guardian.violations.logger import ViolationLogger

        violation_log_path = getattr(args, "violation_log", None)
        violation_logger = (
            ViolationLogger(log_path=Path(violation_log_path).expanduser())
            if violation_log_path
            else ViolationLogger()
        )
        service = MiddlewareService(
            policy,
            security=security,
            violation_logger=violation_logger,
        )
        server_bind = args.bind
        if _needs_macos_tcp_relay(args.bind, security):
            internal_bind = _free_loopback_bind()
            relay = _MiddlewareTcpRelay(args.bind, internal_bind)
            server_bind = internal_bind
            logger.info(
                "using macOS loopback relay for middleware endpoint %s via %s",
                args.bind,
                internal_bind,
            )
        server = create_server(
            service,
            bind=server_bind,
            security=security,
            workers=args.workers,
        )
    except (
        OSError,
        ValueError,
        MiddlewarePolicyError,
        ScannerOwnershipError,
        RuntimeError,
    ) as exc:
        logger.error("unable to start OpenShell middleware: %s", type(exc).__name__)
        print(f"Error starting OpenShell middleware: {exc}", file=sys.stderr)
        if claimed_pid:
            _remove_middleware_pid_file(pid_path, expected_pid=os.getpid())
        return 1

    try:
        transport = "insecure" if security.allow_insecure_transport else "TLS/JWT"
        if bootstrap_result is not None:
            gateway_state = (
                "updated" if bootstrap_result.gateway_changed else "unchanged"
            )
            policy_state = "updated" if bootstrap_result.policy_changed else "unchanged"
            print(
                "OpenShell bootstrap: "
                f"gateway={bootstrap_result.gateway_config} ({gateway_state}), "
                f"policy={bootstrap_result.policy_file} ({policy_state}), "
                f"endpoint={bootstrap_result.gateway_endpoint}. "
                "Restart the OpenShell gateway to load a changed registration.",
                flush=True,
            )
        print(
            f"AI Guardian OpenShell middleware listening on {args.bind} "
            f"({transport}, profile={policy.profile_id}, digest={policy.profile_digest[:12]})",
            flush=True,
        )
        shutdown_requested = False
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def _handle_sigterm(_signum, _frame):
            nonlocal shutdown_requested
            shutdown_requested = True
            server.stop(grace=1)

        signal.signal(signal.SIGTERM, _handle_sigterm)
        try:
            server.start()
            if relay is not None:
                relay.start()
            if shutdown_requested:
                server.stop(grace=1)
            server.wait_for_termination()
        except KeyboardInterrupt:
            server.stop(grace=1)
        finally:
            if relay is not None:
                relay.stop()
            signal.signal(signal.SIGTERM, previous_sigterm)
        return 0
    except (OSError, RuntimeError) as exc:
        if relay is not None:
            relay.stop()
        logger.error(
            "OpenShell middleware stopped during startup: %s", type(exc).__name__
        )
        print(f"Error running OpenShell middleware: {exc}", file=sys.stderr)
        return 1
    finally:
        if claimed_pid:
            _remove_middleware_pid_file(pid_path, expected_pid=os.getpid())


__all__ = [
    "JwtAuthInterceptor",
    "MiddlewareServerSecurity",
    "MiddlewareService",
    "create_server",
    "require_grpc",
    "run_middleware_server",
]
