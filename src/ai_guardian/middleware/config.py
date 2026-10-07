"""Configuration and scanner-ownership rules for supervisor middleware.

The OpenShell middleware is an operator-managed boundary.  It deliberately
does not load the sandbox's ``ai-guardian.json`` file, and it never treats a
workload-provided profile as authority.  The operator selects one of the
existing AI Guardian profiles and this module projects only its semantic
scanner settings into the middleware process.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

import yaml

from ai_guardian.profile_manager import load_profile

logger = logging.getLogger(__name__)

OPEN_SHELL_PROTOCOL_MAJOR = 1
OPEN_SHELL_PROTOCOL_MINOR = 0
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MIN_TIMEOUT_MS = 10
MAX_TIMEOUT_MS = 30_000

# These names are intentionally stable.  They are used in policy files and
# in the capability handshake, so changing them would silently change scanner
# ownership for an existing deployment.
SEMANTIC_SCANNERS = (
    "secret_scanning",
    "scan_pii",
    "prompt_injection",
    "context_poisoning",
    "secret_redaction",
    "supply_chain",
    "scan_offensive",
    "canary_detection",
    "config_file_scanning",
)

SCANNER_CAPABILITIES = {
    "secret_scanning": "openshell.middleware.scanner.secrets",
    "scan_pii": "openshell.middleware.scanner.pii",
    "prompt_injection": "openshell.middleware.scanner.prompt-injection",
    "context_poisoning": "openshell.middleware.scanner.context-poisoning",
    "secret_redaction": "openshell.middleware.scanner.redaction",
    "supply_chain": "openshell.middleware.scanner.supply-chain",
    "scan_offensive": "openshell.middleware.scanner.offensive-language",
    "canary_detection": "openshell.middleware.scanner.canary",
    "config_file_scanning": "openshell.middleware.scanner.config-content",
}

SUPPORTED_MIDDLEWARE_CAPABILITIES = frozenset(
    {
        "openshell.supervisor-middleware.contract",
        "openshell.middleware.semantic-scanning",
        "openshell.middleware.request-scanning",
        "openshell.middleware.response-redaction",
        "openshell.middleware.websocket-text",
        "openshell.middleware.streaming-response",
        *SCANNER_CAPABILITIES.values(),
    }
)

ROUTING_MODES = frozenset({"hooks", "middleware", "auto", "both"})
_MIDDLEWARE_POLICY_FIELDS = {
    "profile_id",
    "profile_digest",
    "scanner_ownership",
    "required_middleware_capabilities",
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
}

# Filesystem, network, process, credential, and host-tool controls remain with
# OpenShell and hooks.  These sections must never cross the middleware trust
# boundary through profile projection.
_MIDDLEWARE_PROFILE_SECTIONS = (
    "secret_scanning",
    "secret_redaction",
    "scan_pii",
    "prompt_injection",
    "context_poisoning",
    "supply_chain",
    "scan_offensive",
    "canary_detection",
    "config_file_scanning",
)


class ScannerOwnershipError(ValueError):
    """Raised when scanner routing cannot be made safe and explicit."""


class MiddlewarePolicyError(ValueError):
    """Raised for invalid operator-managed middleware policy."""


def _without_comments(value: Any) -> Any:
    """Copy a profile value while dropping documentation-only comment keys."""

    if isinstance(value, dict):
        return {
            key: _without_comments(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_without_comments(item) for item in value]
    return copy.deepcopy(value)


def _find_ask_actions(value: Any, path: str = "") -> list[str]:
    """Return semantic config paths that request interactive ``ask`` mode."""

    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if key in {"action", "mode"} and item == "ask":
                found.append(item_path)
            found.extend(_find_ask_actions(item, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_ask_actions(item, f"{path}[{index}]"))
    return found


def project_profile_for_middleware(
    profile: Mapping[str, Any] | str,
    *,
    profile_loader: Callable[[str], Dict[str, Any]] = load_profile,
) -> Dict[str, Any]:
    """Project an AI Guardian profile onto semantic middleware scanners.

    ``profile`` may be an already loaded profile mapping or a profile name
    accepted by :func:`ai_guardian.profile_manager.load_profile`.  The result
    excludes hook-only and OpenShell-authoritative controls.  Interactive
    ``ask`` actions are rejected because a gRPC middleware cannot open a
    user-facing approval dialog.
    """

    if isinstance(profile, str):
        loaded = profile_loader(profile)
    elif isinstance(profile, Mapping):
        loaded = dict(profile)
    else:
        raise MiddlewarePolicyError("middleware profile must be a name or object")

    projected = {
        section: _without_comments(loaded[section])
        for section in _MIDDLEWARE_PROFILE_SECTIONS
        if section in loaded
    }
    ask_paths = _find_ask_actions(projected)
    if ask_paths:
        raise MiddlewarePolicyError(
            "middleware profiles cannot use interactive 'ask' actions: "
            + ", ".join(ask_paths)
        )
    return projected


def profile_digest(profile: Mapping[str, Any]) -> str:
    """Return the stable digest used to bind policy to an operator profile."""

    encoded = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _as_string_list(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise MiddlewarePolicyError(f"{field} must be a list of non-empty strings")
    return tuple(dict.fromkeys(item.strip() for item in value))


def _as_bool(value: Any, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise MiddlewarePolicyError(f"{field} must be a boolean")
    return value


def _as_int(value: Any, field: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise MiddlewarePolicyError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise MiddlewarePolicyError(f"{field} must be between {minimum} and {maximum}")
    return value


def _validate_capabilities(capabilities: Iterable[str]) -> frozenset[str]:
    values = tuple(capabilities)
    unknown = sorted(set(values) - SUPPORTED_MIDDLEWARE_CAPABILITIES)
    if unknown:
        raise ScannerOwnershipError(
            "unsupported middleware capabilities: " + ", ".join(unknown)
        )
    return frozenset(values)


def _normalize_scanner_ownership(value: Any) -> Dict[str, str]:
    routes: Dict[str, str] = {scanner: "auto" for scanner in SEMANTIC_SCANNERS}
    if value is None:
        return routes
    if not isinstance(value, Mapping):
        raise ScannerOwnershipError("scanner_ownership must be an object")
    unknown = sorted(
        str(key)
        for key in value
        if not isinstance(key, str) or key not in set(SEMANTIC_SCANNERS) | {"default"}
    )
    if unknown:
        raise ScannerOwnershipError(
            "unknown scanner ownership entries: " + ", ".join(unknown)
        )
    default = value.get("default", "auto")
    if not isinstance(default, str) or default not in ROUTING_MODES:
        raise ScannerOwnershipError(
            f"scanner_ownership.default must be one of {sorted(ROUTING_MODES)}"
        )
    routes = {scanner: default for scanner in SEMANTIC_SCANNERS}
    for scanner, mode in value.items():
        if scanner == "default":
            continue
        if not isinstance(mode, str) or mode not in ROUTING_MODES:
            raise ScannerOwnershipError(
                f"scanner_ownership.{scanner} must be one of {sorted(ROUTING_MODES)}"
            )
        routes[scanner] = mode
    return routes


def _normalize_endpoints(value: Any) -> tuple[str, ...]:
    endpoints = _as_string_list(value, "provider_endpoints")
    for endpoint in endpoints:
        if any(character in endpoint for character in "\r\n"):
            raise MiddlewarePolicyError("provider_endpoints cannot contain newlines")
    return endpoints


def endpoint_matches(host: str, endpoint_patterns: Sequence[str]) -> bool:
    """Match a target host against exact or ``*`` endpoint patterns."""

    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        return False
    return any(
        fnmatch.fnmatchcase(normalized, pattern.lower().rstrip("."))
        for pattern in endpoint_patterns
    )


@dataclass(frozen=True)
class ScannerOwnershipDecision:
    """Resolved ownership for one scanner at one middleware invocation."""

    scanner: str
    requested_mode: str
    effective_mode: str
    reason: str = ""


@dataclass(frozen=True)
class MiddlewarePolicy:
    """Validated, operator-owned policy used by a middleware service."""

    profile_id: str
    profile_digest: str
    profile: Dict[str, Any]
    scanner_ownership: Dict[str, str]
    required_middleware_capabilities: frozenset[str]
    max_payload_bytes: int = 256 * 1024
    timeout_ms: int = 500
    response_redaction: bool = True
    require_effective_policy: bool = True
    registration_name: str = ""
    provider_endpoints: tuple[str, ...] = ()
    hooks_capabilities: frozenset[str] = frozenset()
    shared_correlation_id: bool = False
    pre_persistence_deduplication: bool = False
    allow_binary_websocket: bool = False
    allow_unsupported_responses: bool = False

    @classmethod
    def from_mapping(
        cls,
        mapping: Optional[Mapping[str, Any]] = None,
        *,
        profile: Optional[Mapping[str, Any]] = None,
        default_profile_id: str = "standard",
        registration_name: str = "",
    ) -> "MiddlewarePolicy":
        """Build a policy without reading sandbox configuration.

        ``profile`` is supplied by the operator-side loader.  A request-level
        OpenShell ``Struct`` may select only the same profile ID and digest;
        it cannot supply a replacement profile object.
        """

        raw = dict(mapping or {})
        unknown = sorted(
            str(key)
            for key in raw
            if not isinstance(key, str) or key not in _MIDDLEWARE_POLICY_FIELDS
        )
        if unknown:
            raise MiddlewarePolicyError(
                "unknown middleware policy fields: " + ", ".join(unknown)
            )

        profile_id = raw.get("profile_id", default_profile_id)
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise MiddlewarePolicyError("profile_id must be a non-empty string")
        profile_id = profile_id.strip().lstrip("@")
        if profile is None:
            profile = load_profile(profile_id)
        projected = project_profile_for_middleware(profile)
        digest = profile_digest(projected)
        requested_digest = raw.get("profile_digest")
        if requested_digest is not None and requested_digest != digest:
            raise MiddlewarePolicyError(
                "profile_digest does not match the operator profile"
            )

        routes = _normalize_scanner_ownership(raw.get("scanner_ownership"))
        required = _validate_capabilities(
            _as_string_list(
                raw.get("required_middleware_capabilities"),
                "required_middleware_capabilities",
            )
        )
        for scanner, mode in routes.items():
            if mode in {"middleware", "auto", "both"}:
                required = frozenset((*required, SCANNER_CAPABILITIES[scanner]))

        response_redaction = raw.get("response_redaction", True)
        if isinstance(response_redaction, Mapping):
            response_redaction = response_redaction.get("enabled", True)
        response_redaction = _as_bool(response_redaction, "response_redaction", True)

        require_effective_policy = _as_bool(
            raw.get("require_effective_policy"), "require_effective_policy", True
        )
        registration = raw.get("registration_name", registration_name)
        if not isinstance(registration, str):
            raise MiddlewarePolicyError("registration_name must be a string")
        registration = registration.strip()
        if require_effective_policy and not registration:
            raise MiddlewarePolicyError(
                "registration_name is required when effective policy validation is enabled"
            )
        endpoints = _normalize_endpoints(raw.get("provider_endpoints"))
        if require_effective_policy and not endpoints:
            raise MiddlewarePolicyError(
                "provider_endpoints are required when effective policy validation is enabled"
            )

        hooks = _validate_capabilities(
            _as_string_list(raw.get("hooks_capabilities"), "hooks_capabilities")
        )
        shared_correlation_id = _as_bool(
            raw.get("shared_correlation_id"), "shared_correlation_id", False
        )
        pre_persistence_deduplication = _as_bool(
            raw.get("pre_persistence_deduplication"),
            "pre_persistence_deduplication",
            False,
        )
        if any(mode == "both" for mode in routes.values()):
            if not shared_correlation_id or not pre_persistence_deduplication:
                raise ScannerOwnershipError(
                    "scanner ownership 'both' requires shared_correlation_id and "
                    "pre_persistence_deduplication"
                )

        return cls(
            profile_id=profile_id,
            profile_digest=digest,
            profile=projected,
            scanner_ownership=routes,
            required_middleware_capabilities=required,
            max_payload_bytes=_as_int(
                raw.get("max_payload_bytes"),
                "max_payload_bytes",
                256 * 1024,
                1,
                MAX_PAYLOAD_BYTES,
            ),
            timeout_ms=_as_int(
                raw.get("timeout_ms"),
                "timeout_ms",
                500,
                MIN_TIMEOUT_MS,
                MAX_TIMEOUT_MS,
            ),
            response_redaction=response_redaction,
            require_effective_policy=require_effective_policy,
            registration_name=registration,
            provider_endpoints=endpoints,
            hooks_capabilities=hooks,
            shared_correlation_id=shared_correlation_id,
            pre_persistence_deduplication=pre_persistence_deduplication,
            allow_binary_websocket=_as_bool(
                raw.get("allow_binary_websocket"), "allow_binary_websocket", False
            ),
            allow_unsupported_responses=_as_bool(
                raw.get("allow_unsupported_responses"),
                "allow_unsupported_responses",
                False,
            ),
        )

    def validate_effective_policy(
        self,
        *,
        middleware_name: str,
        target_host: str,
    ) -> tuple[bool, str]:
        """Verify that the call is attached to the intended provider policy."""

        if not self.require_effective_policy:
            return True, ""
        if not middleware_name:
            return False, "middleware_name is required for effective policy validation"
        if self.registration_name and middleware_name != self.registration_name:
            return False, "middleware_name does not match the operator registration"
        if not endpoint_matches(target_host, self.provider_endpoints):
            return (
                False,
                "target host is not attached to a configured provider endpoint",
            )
        return True, ""


def resolve_scanner_ownership(
    scanner_ownership: Mapping[str, str],
    *,
    middleware_healthy: bool = True,
    protocol_compatible: bool = True,
    capabilities: Iterable[str] = SUPPORTED_MIDDLEWARE_CAPABILITIES,
    policy_attached: bool = True,
    correlation_id_available: bool = False,
    deduplication_available: bool = False,
    hooks_capabilities: Iterable[str] = (),
) -> Dict[str, ScannerOwnershipDecision]:
    """Resolve ``hooks``, ``middleware``, ``auto``, and explicit ``both``.

    ``auto`` falls back to hooks when the hook surface advertises the selected
    scanner.  Explicit middleware ownership fails closed when its prerequisites
    are not met; it never silently disables both surfaces.
    """

    available = set(capabilities)
    hooks = set(hooks_capabilities)
    decisions: Dict[str, ScannerOwnershipDecision] = {}
    for scanner, requested in scanner_ownership.items():
        if scanner not in SCANNER_CAPABILITIES:
            raise ScannerOwnershipError(f"unknown scanner: {scanner}")
        if requested not in ROUTING_MODES:
            raise ScannerOwnershipError(
                f"scanner ownership for {scanner} must be one of {sorted(ROUTING_MODES)}"
            )
        capability = SCANNER_CAPABILITIES[scanner]
        ready = (
            middleware_healthy
            and protocol_compatible
            and policy_attached
            and capability in available
        )
        if requested == "hooks":
            if capability in hooks:
                effective, reason = "hooks", "hooks explicitly own scanner"
            else:
                effective, reason = (
                    "fail_closed",
                    "hooks explicitly own scanner but capability is unavailable",
                )
        elif requested == "middleware":
            effective = "middleware" if ready else "fail_closed"
            reason = (
                "middleware prerequisites satisfied"
                if ready
                else "middleware prerequisites unsatisfied"
            )
        elif requested == "auto":
            if ready:
                effective, reason = (
                    "middleware",
                    "auto-selected after capability and policy validation",
                )
            elif capability in hooks:
                effective, reason = (
                    "hooks",
                    "middleware unavailable; hooks retain scanner ownership",
                )
            else:
                effective, reason = (
                    "fail_closed",
                    "no validated scanner owner is available",
                )
        else:  # both
            if (
                ready
                and capability in hooks
                and correlation_id_available
                and deduplication_available
            ):
                effective, reason = (
                    "both",
                    "explicit defense-in-depth with deduplication",
                )
            else:
                effective, reason = (
                    "fail_closed",
                    "both requires validated middleware and deduplication",
                )
        decisions[scanner] = ScannerOwnershipDecision(
            scanner=scanner,
            requested_mode=requested,
            effective_mode=effective,
            reason=reason,
        )
    return decisions


def load_operator_policy(
    path: str | Path,
    *,
    profile_override: Optional[str] = None,
) -> tuple[MiddlewarePolicy, Dict[str, Any]]:
    """Load an operator-owned JSON/YAML policy and its raw server settings."""

    config_path = Path(path).expanduser()
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MiddlewarePolicyError(f"unable to read middleware config: {exc}") from exc
    try:
        raw = (
            json.loads(raw_text)
            if config_path.suffix.lower() == ".json"
            else yaml.safe_load(raw_text)
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise MiddlewarePolicyError(f"invalid middleware config: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise MiddlewarePolicyError("middleware config must contain an object")

    policy_raw = raw.get("policy")
    if policy_raw is None:
        # Keep transport/server settings separate when a compact, single-level
        # config is used.  The preferred format is still an explicit ``policy``
        # object so accidental additions fail validation loudly.
        policy_raw = {
            key: value
            for key, value in raw.items()
            if key
            not in {
                "bind",
                "workers",
                "tls",
                "jwt",
                "allow_insecure_transport",
                "allow_insecure_wildcard_bind",
                "openshell_version",
            }
        }
    if not isinstance(policy_raw, Mapping):
        raise MiddlewarePolicyError("middleware policy must contain an object")
    policy_values = dict(policy_raw)
    if profile_override:
        policy_values["profile_id"] = profile_override
    profile_id = policy_values.get("profile_id", "standard")
    profile_ref = str(profile_id)
    profile = load_profile(profile_ref)
    policy = MiddlewarePolicy.from_mapping(
        policy_values,
        profile=profile,
        default_profile_id=str(profile_id).lstrip("@"),
        registration_name=str(raw.get("registration_name", "")),
    )
    return policy, dict(raw)
