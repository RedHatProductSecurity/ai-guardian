"""Explicit, idempotent OpenShell configuration bootstrap helpers.

The middleware server does not mutate OpenShell configuration during normal
startup.  This module is used only by the opt-in ``--bootstrap-openshell``
launcher mode to generate the operator registration and sandbox policy without
silently replacing conflicting configuration.
"""

from __future__ import annotations

import ipaddress
import importlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

import tomli_w
import yaml

try:  # Python 3.11+
    _toml: Any = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    _toml = importlib.import_module("tomli")

from ...config import MiddlewarePolicy

_MIDDLEWARE_HEADER = re.compile(r"(?m)^\[\[openshell\.supervisor\.middleware\]\]\s*$")
_TABLE_HEADER = re.compile(r"(?m)^\s*\[")


class OpenShellBootstrapError(ValueError):
    """Raised when an explicit OpenShell bootstrap cannot be applied safely."""


@dataclass(frozen=True)
class OpenShellBootstrapResult:
    """Files and change state produced by an OpenShell bootstrap."""

    gateway_config: Path
    policy_file: Path
    gateway_changed: bool
    policy_changed: bool
    gateway_endpoint: str


def _bind_host(bind: str) -> str:
    value = bind.strip()
    if value.startswith("["):
        closing = value.find("]")
        if closing > 0:
            return value[1:closing]
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


def _is_wildcard_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"", "*"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_unspecified
    except ValueError:
        return normalized in {"0.0.0.0", "::"}


def _validate_gateway_endpoint(endpoint: str, *, secure: bool) -> str:
    value = endpoint.strip().rstrip("/")
    parsed = urlsplit(value)
    expected_scheme = "https" if secure else "http"
    if parsed.scheme != expected_scheme or not parsed.hostname or parsed.port is None:
        raise OpenShellBootstrapError(
            f"gateway endpoint must be an absolute {expected_scheme} URL with a port"
        )
    if parsed.path or parsed.query or parsed.fragment:
        raise OpenShellBootstrapError(
            "gateway endpoint must not contain a path, query, or fragment"
        )
    if _is_wildcard_host(parsed.hostname):
        raise OpenShellBootstrapError(
            "gateway endpoint cannot use a wildcard host; provide the reachable "
            "OpenShell address with --gateway-endpoint"
        )
    return value


def _advertised_endpoint(
    bind: str,
    *,
    secure: bool,
    gateway_endpoint: Optional[str],
) -> str:
    if gateway_endpoint:
        return _validate_gateway_endpoint(gateway_endpoint, secure=secure)
    host = _bind_host(bind)
    if _is_wildcard_host(host):
        raise OpenShellBootstrapError(
            "--gateway-endpoint is required when --bind uses a wildcard address"
        )
    return _validate_gateway_endpoint(
        f"{'https' if secure else 'http'}://{bind}", secure=secure
    )


def _duration_string(timeout_ms: int) -> str:
    if timeout_ms % 1000 == 0:
        return f"{timeout_ms // 1000}s"
    return f"{timeout_ms}ms"


def _gateway_registration(
    policy: MiddlewarePolicy,
    *,
    gateway_endpoint: str,
    secure: bool,
    gateway_tls_ca_path: Optional[str],
    audience: Optional[str],
) -> Dict[str, Any]:
    registration: Dict[str, Any] = {
        "name": policy.registration_name,
        "grpc_endpoint": gateway_endpoint,
        "max_payload_bytes": policy.max_payload_bytes,
        "timeout": _duration_string(policy.timeout_ms),
    }
    if secure:
        if not gateway_tls_ca_path:
            raise OpenShellBootstrapError(
                "--gateway-tls-ca is required when bootstrapping TLS middleware"
            )
        if not audience:
            raise OpenShellBootstrapError(
                "JWT audience is required when bootstrapping TLS middleware"
            )
        registration["tls_ca_cert_path"] = gateway_tls_ca_path
        registration["audience"] = audience
    else:
        registration["allow_insecure_transport"] = True
    return registration


def _parse_gateway_config(text: str, path: Path) -> Mapping[str, Any]:
    try:
        parsed = _toml.loads(text)
    except _toml.TOMLDecodeError as exc:
        raise OpenShellBootstrapError(
            f"existing gateway config is not valid TOML: {path}"
        ) from exc
    openshell = parsed.get("openshell")
    if not isinstance(openshell, Mapping) or openshell.get("version") != 2:
        raise OpenShellBootstrapError(
            f"existing gateway config must declare [openshell] version = 2: {path}"
        )
    return parsed


def _middleware_registrations(parsed: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    openshell = parsed["openshell"]
    assert isinstance(openshell, Mapping)
    supervisor = openshell.get("supervisor", {})
    if not isinstance(supervisor, Mapping):
        raise OpenShellBootstrapError("openshell.supervisor must be a TOML table")
    registrations = supervisor.get("middleware", [])
    if not isinstance(registrations, list) or not all(
        isinstance(item, Mapping) for item in registrations
    ):
        raise OpenShellBootstrapError(
            "openshell.supervisor.middleware must be an array of tables"
        )
    return registrations


def _normalized_registration(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        value.get("name"),
        value.get("grpc_endpoint"),
        value.get("max_payload_bytes"),
        value.get("timeout"),
        bool(value.get("allow_insecure_transport", False)),
        value.get("tls_ca_cert_path"),
        value.get("audience"),
    )


def _registration_text(registration: Mapping[str, Any]) -> str:
    return (
        "[[openshell.supervisor.middleware]]\n"
        + tomli_w.dumps(dict(registration)).strip()
    )


def _registration_block_range(text: str, *, registration_name: str) -> tuple[int, int]:
    matches = list(_MIDDLEWARE_HEADER.finditer(text))
    for match in matches:
        block_end = len(text)
        next_header = _TABLE_HEADER.search(text, match.end())
        if next_header is not None:
            block_end = next_header.start()
        block = text[match.start() : block_end]
        try:
            parsed = _toml.loads(block)
            registrations = _middleware_registrations(parsed)
        except (KeyError, TypeError, _toml.TOMLDecodeError) as exc:
            raise OpenShellBootstrapError(
                "existing middleware registration block is not valid TOML"
            ) from exc
        if (
            len(registrations) == 1
            and registrations[0].get("name") == registration_name
        ):
            return match.start(), block_end
    raise OpenShellBootstrapError(
        f"middleware registration block {registration_name!r} was not found"
    )


def _replace_registration_block(
    text: str, registration: Mapping[str, Any], *, registration_name: str
) -> str:
    block_start, block_end = _registration_block_range(
        text, registration_name=registration_name
    )
    replacement = _registration_text(registration) + "\n"
    return text[:block_start] + replacement + text[block_end:]


def _prepare_gateway_config(
    path: Path,
    registration: Mapping[str, Any],
    *,
    force: bool,
) -> tuple[str, bool]:
    if not path.exists():
        content = (
            "[openshell]\nversion = 2\n\n" + _registration_text(registration) + "\n"
        )
        return content, True

    try:
        existing = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OpenShellBootstrapError(f"unable to read gateway config: {path}") from exc
    parsed = _parse_gateway_config(existing, path)
    registrations = _middleware_registrations(parsed)
    matching = [
        item for item in registrations if item.get("name") == registration.get("name")
    ]
    if len(matching) > 1:
        raise OpenShellBootstrapError(
            f"gateway config contains duplicate middleware registrations named "
            f"{registration['name']!r}"
        )
    if matching:
        if _normalized_registration(matching[0]) == _normalized_registration(
            registration
        ):
            return existing, False
        if not force:
            raise OpenShellBootstrapError(
                f"middleware registration {registration['name']!r} already exists "
                "with different settings; use --bootstrap-force to replace it"
            )
        return (
            _replace_registration_block(
                existing,
                registration,
                registration_name=str(registration["name"]),
            ),
            True,
        )

    separator = "" if not existing or existing.endswith("\n") else "\n"
    return (
        existing + separator + "\n" + _registration_text(registration) + "\n",
        True,
    )


def _policy_document(policy: MiddlewarePolicy, attachment_name: str) -> Dict[str, Any]:
    if not policy.registration_name:
        raise OpenShellBootstrapError(
            "registration_name is required when generating an OpenShell policy"
        )
    if not policy.provider_endpoints:
        raise OpenShellBootstrapError(
            "provider_endpoints are required when generating an OpenShell policy"
        )
    return {
        "version": 1,
        "network_middlewares": {
            attachment_name: {
                "name": "AI Guardian semantic guard",
                "middleware": policy.registration_name,
                "order": 10,
                "config": {
                    "profile_id": policy.profile_id,
                    "profile_digest": policy.profile_digest,
                    "scanner_ownership": dict(policy.scanner_ownership),
                    "response_redaction": policy.response_redaction,
                },
                "on_error": "fail_closed",
                "endpoints": {"include": list(policy.provider_endpoints)},
            }
        },
    }


def _prepare_policy_file(
    path: Path,
    document: Mapping[str, Any],
    *,
    force: bool,
) -> tuple[str, bool]:
    if path.exists() and not force:
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise OpenShellBootstrapError(
                f"existing policy file is not valid YAML: {path}"
            ) from exc
        if existing == dict(document):
            return path.read_text(encoding="utf-8"), False
        raise OpenShellBootstrapError(
            f"policy file already exists with different settings: {path}; "
            "use --bootstrap-force to replace it"
        )
    return yaml.safe_dump(dict(document), sort_keys=False), True


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, existing_mode)
        else:  # pragma: no cover - Windows lacks os.fchmod
            os.chmod(temporary_name, existing_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def bootstrap_openshell(
    policy: MiddlewarePolicy,
    *,
    bind: str,
    gateway_config: str | Path,
    policy_file: str | Path,
    allow_insecure_transport: bool,
    gateway_endpoint: Optional[str] = None,
    gateway_tls_ca_path: Optional[str] = None,
    audience: Optional[str] = None,
    attachment_name: Optional[str] = None,
    force: bool = False,
) -> OpenShellBootstrapResult:
    """Idempotently generate the gateway registration and sandbox policy.

    Existing settings are never replaced unless ``force`` is explicitly set.
    The gateway is not restarted and no sandbox is created or modified.
    """

    gateway_path = Path(gateway_config).expanduser()
    policy_path = Path(policy_file).expanduser()
    if gateway_path == policy_path:
        raise OpenShellBootstrapError(
            "gateway config and sandbox policy must be different files"
        )
    if not policy.registration_name:
        raise OpenShellBootstrapError(
            "registration_name is required when bootstrapping OpenShell"
        )
    secure = not allow_insecure_transport
    advertised_endpoint = _advertised_endpoint(
        bind,
        secure=secure,
        gateway_endpoint=gateway_endpoint,
    )
    registration = _gateway_registration(
        policy,
        gateway_endpoint=advertised_endpoint,
        secure=secure,
        gateway_tls_ca_path=gateway_tls_ca_path,
        audience=audience,
    )
    attachment = attachment_name or f"{policy.registration_name}-attachment"
    if not attachment.strip() or any(character in attachment for character in "\r\n"):
        raise OpenShellBootstrapError("policy attachment name must be a non-empty line")

    gateway_content, gateway_changed = _prepare_gateway_config(
        gateway_path,
        registration,
        force=force,
    )
    policy_content, policy_changed = _prepare_policy_file(
        policy_path,
        _policy_document(policy, attachment),
        force=force,
    )

    if policy_changed:
        _atomic_write(policy_path, policy_content)
    if gateway_changed:
        _atomic_write(gateway_path, gateway_content)
    return OpenShellBootstrapResult(
        gateway_config=gateway_path,
        policy_file=policy_path,
        gateway_changed=gateway_changed,
        policy_changed=policy_changed,
        gateway_endpoint=advertised_endpoint,
    )


__all__ = [
    "OpenShellBootstrapError",
    "OpenShellBootstrapResult",
    "bootstrap_openshell",
]
