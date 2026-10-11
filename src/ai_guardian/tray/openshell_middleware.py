"""OpenShell middleware readiness checks used by the system tray.

This module deliberately does not install a service, edit gateway TOML, or
apply a policy.  Those resources remain owned by the operator's service
manager and OpenShell.  The tray only checks readiness and produces guided,
copyable setup information.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_guardian.tray.openshell_middleware_probe import (
    MiddlewareProbeError,
    MiddlewareProbeIdentity,
    probe_middleware_endpoint,
)

MIDDLEWARE_IMPLEMENTATION_NAME = "ai-guardian/rust-middleware"
_VERSION_RE = re.compile(r"(?:OpenShell|openshell)?\s*v?(\d+)\.(\d+)\.(\d+)")


@dataclass
class OpenShellMiddlewareReadiness:
    """Non-sensitive status values for the tray readiness report."""

    cli: str
    openshell_version: Optional[str] = None
    compatibility_status: str = "not checked"
    gateway_status: str = "not checked"
    gateway_detail: str = ""
    middleware_status: str = "unknown"
    gateway_extension_status: str = "unknown"
    identity_status: str = "not checked"
    middleware_implementation: Optional[str] = None
    middleware_version: Optional[str] = None
    middleware_registration: Optional[str] = None
    middleware_detail: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """Return whether all required deployment checks passed."""
        return all(
            status.startswith("ready")
            for status in (
                self.compatibility_status,
                self.gateway_status,
                "ready" if self.middleware_status == "running" else "error",
                "ready" if self.gateway_extension_status == "active" else "error",
                self.identity_status,
            )
        )


def _version(value: Any) -> Optional[Tuple[int, int, int]]:
    match = _VERSION_RE.search(str(value or ""))
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _compatible(version: Optional[Tuple[int, int, int]]) -> bool:
    return bool(version and version[:2] == (0, 1) and version[2] >= 2)


def _run_json(
    command: Sequence[str], *, timeout: float = 10
) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout or "command failed").strip()
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {exc}"
    return payload if isinstance(payload, dict) else None, "unexpected JSON shape"


def _default_gateway_config_path() -> Path:
    """Locate the gateway TOML using its environment and common install paths."""
    override = os.environ.get("OPENSHELL_GATEWAY_CONFIG")
    if override:
        return Path(override).expanduser()

    config_home_value = os.environ.get("XDG_CONFIG_HOME")
    config_home = (
        Path(config_home_value).expanduser()
        if config_home_value
        else Path.home() / ".config"
    )
    default_path = config_home / "openshell" / "gateway.toml"
    if default_path.is_file():
        return default_path

    if sys.platform == "darwin":
        alternatives = (
            Path("/opt/homebrew/var/openshell/gateway.toml"),
            Path("/usr/local/var/openshell/gateway.toml"),
        )
    else:
        alternatives = (Path("/var/snap/openshell/common/gateway.toml"),)
    return next((path for path in alternatives if path.is_file()), default_path)


def _read_gateway_middleware_config(
    path: Path,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Read configured supervisor endpoints without exposing other TOML data."""
    try:
        with path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except FileNotFoundError as exc:
        raise ValueError(f"gateway TOML was not found at {path}") from exc
    except OSError as exc:
        raise ValueError(f"gateway TOML could not be read at {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"gateway TOML is invalid at {path}") from exc

    openshell = config.get("openshell", {})
    if not isinstance(openshell, dict):
        raise ValueError("gateway TOML [openshell] value is not a table")
    supervisor = openshell.get("supervisor", {})
    if not isinstance(supervisor, dict):
        raise ValueError("gateway TOML [openshell.supervisor] value is not a table")
    middleware = supervisor.get("middleware", [])
    if not isinstance(middleware, list):
        raise ValueError("gateway TOML middleware registrations are not an array")

    registrations = []
    invalid_entries = []
    for index, entry in enumerate(middleware, start=1):
        if not isinstance(entry, dict):
            invalid_entries.append(f"entry {index} is not a table")
            continue
        name = str(entry.get("name", "")).strip()
        endpoint = str(entry.get("grpc_endpoint", "")).strip()
        if not name or not endpoint:
            missing = []
            if not name:
                missing.append("name")
            if not endpoint:
                missing.append("grpc_endpoint")
            invalid_entries.append(f"entry {index} is missing {', '.join(missing)}")
            continue
        registrations.append((name, endpoint))
    return registrations, invalid_entries


def _gateway_extension_status(info: Optional[Dict[str, Any]]) -> str:
    """Return the gateway-reported activation state, not process liveness."""
    extensions = info.get("extensions") if info else None
    if not isinstance(extensions, list):
        return "unknown"
    if any(
        isinstance(extension, dict)
        and extension.get("kind") == "supervisor-middleware"
        and extension.get("implementation_name") == MIDDLEWARE_IMPLEMENTATION_NAME
        for extension in extensions
    ):
        return "active"
    return "not_active"


def _check_configured_middleware(
    readiness: OpenShellMiddlewareReadiness,
    config_path: Path,
    openshell_version: str,
) -> None:
    """Probe each configured gRPC endpoint and accept only verified identity."""
    try:
        registrations, invalid_entries = _read_gateway_middleware_config(config_path)
    except ValueError as exc:
        readiness.middleware_status = "configuration_error"
        readiness.identity_status = "error"
        readiness.middleware_detail = str(exc)
        readiness.errors.append(readiness.middleware_detail)
        return

    if invalid_entries:
        readiness.errors.extend(
            f"Invalid gateway middleware configuration: {entry}"
            for entry in invalid_entries
        )
    if not registrations:
        readiness.middleware_status = (
            "configuration_error" if invalid_entries else "not_configured"
        )
        readiness.identity_status = "error"
        if invalid_entries:
            readiness.middleware_detail = (
                "No valid supervisor middleware registration was found in "
                f"{config_path}: " + "; ".join(invalid_entries)
            )
        else:
            readiness.middleware_detail = (
                "No supervisor middleware registration was found in "
                f"{config_path}; AI Guardian middleware may not be running, "
                "or its gateway.toml registration may be missing or malformed"
            )
        readiness.errors.append(readiness.middleware_detail)
        return

    responding: List[Tuple[str, MiddlewareProbeIdentity]] = []
    failures: List[Tuple[str, MiddlewareProbeError]] = []
    for registration, endpoint in registrations:
        try:
            identity = probe_middleware_endpoint(
                endpoint,
                openshell_version=openshell_version,
            )
        except MiddlewareProbeError as exc:
            failures.append((registration, exc))
        else:
            responding.append((registration, identity))

    matching = [
        (registration, identity)
        for registration, identity in responding
        if identity.implementation == MIDDLEWARE_IMPLEMENTATION_NAME
    ]
    if matching:
        readiness.middleware_implementation = MIDDLEWARE_IMPLEMENTATION_NAME
        readiness.middleware_registration = ", ".join(
            registration for registration, _identity in matching
        )
        versions = [identity.version for _registration, identity in matching]
        if any(not version for version in versions):
            readiness.middleware_status = "identity_incomplete"
            readiness.identity_status = "error"
            readiness.middleware_detail = (
                "Describe responded with the AI Guardian implementation but did "
                "not report its implementation version"
            )
            readiness.errors.append(readiness.middleware_detail)
            return
        readiness.middleware_status = "running"
        readiness.identity_status = "ready"
        readiness.middleware_version = ", ".join(versions)
        readiness.middleware_detail = (
            f"Live Describe responded for {readiness.middleware_registration}: "
            f"{MIDDLEWARE_IMPLEMENTATION_NAME} version "
            f"{readiness.middleware_version}"
        )
        return

    if failures:
        failure_kinds = {error.kind for _name, error in failures}
        if "configuration" in failure_kinds:
            readiness.middleware_status = "configuration_error"
        elif failure_kinds == {"dependency"}:
            readiness.middleware_status = "probe_unavailable"
        elif "identity" in failure_kinds and "unavailable" not in failure_kinds:
            readiness.middleware_status = "identity_incomplete"
        else:
            readiness.middleware_status = "not_responding"
        readiness.identity_status = "error"
        failure_details = [f"{name}: {error}" for name, error in failures]
        if responding:
            failure_details.extend(
                f"{name}: {identity.implementation or 'implementation not reported'}"
                + (f" version {identity.version}" if identity.version else "")
                for name, identity in responding
            )
        readiness.middleware_detail = (
            "No configured endpoint verified the AI Guardian middleware. "
            + "; ".join(failure_details)
        )
        if readiness.middleware_status == "not_responding":
            readiness.middleware_detail += (
                ". The service may be stopped or the configured endpoint may "
                "not be reachable from this host"
            )
        elif readiness.middleware_status == "identity_incomplete":
            readiness.middleware_detail += (
                ". The endpoint responded, but its identity could not be verified"
            )
        readiness.errors.append(readiness.middleware_detail)
        return

    if responding:
        readiness.middleware_status = "wrong_implementation"
        readiness.identity_status = "error"
        readiness.middleware_implementation = ", ".join(
            identity.implementation or "unknown implementation"
            for _name, identity in responding
        )
        versions = [
            identity.version for _name, identity in responding if identity.version
        ]
        readiness.middleware_version = ", ".join(versions) or None
        readiness.middleware_registration = ", ".join(
            registration for registration, _identity in responding
        )
        reported = "; ".join(
            f"{registration}: {identity.implementation or 'unknown implementation'}"
            + (f" version {identity.version}" if identity.version else "")
            for registration, identity in responding
        )
        readiness.middleware_detail = (
            f"Configured middleware responded to Describe, but did not identify "
            f"as {MIDDLEWARE_IMPLEMENTATION_NAME}: {reported}"
        )
        readiness.errors.append(readiness.middleware_detail)
        return

    readiness.middleware_status = "not_responding"
    readiness.identity_status = "error"
    readiness.middleware_detail = "No configured middleware endpoint was probed"
    readiness.errors.append(readiness.middleware_detail)


def check_openshell_middleware(
    *,
    cli: str = "openshell",
    gateway_config_path: Optional[Path] = None,
) -> OpenShellMiddlewareReadiness:
    """Check gateway health and probe middleware endpoints from gateway TOML."""
    result = OpenShellMiddlewareReadiness(cli=cli)
    cli_available = shutil.which(cli) is not None or Path(cli).expanduser().is_file()
    if not cli_available:
        result.gateway_status = "error"
        result.compatibility_status = "error"
        result.errors.append(f"OpenShell CLI was not found: {cli}")
        version_text = ""
        status = None
        info = None
        status_error = "OpenShell CLI is unavailable"
        info_error = "OpenShell CLI is unavailable"
    else:
        version_result = None
        try:
            version_result = subprocess.run(
                [cli, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            version_text = (
                version_result.stdout or version_result.stderr or ""
            ).strip()
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            version_text = ""
            result.errors.append(f"Unable to determine the OpenShell version: {exc}")
        parsed_version = _version(version_text)
        result.openshell_version = version_text or None
        if version_result is not None and version_result.returncode != 0:
            result.compatibility_status = "error"
            result.errors.append(
                "OpenShell version command failed"
                + (f": {version_text}" if version_text else "")
            )
        elif _compatible(parsed_version):
            result.compatibility_status = "ready"
        elif parsed_version is None:
            result.compatibility_status = "error"
            if not any("Unable to determine" in error for error in result.errors):
                result.errors.append("Unable to determine the OpenShell version")
        else:
            result.compatibility_status = "error"
            result.errors.append(
                f"OpenShell {version_text} is outside the qualified 0.1.2+ / 0.1.x range"
            )

        status, status_error = _run_json([cli, "status", "--output", "json"])
        info, info_error = _run_json([cli, "gateway", "info", "--output", "json"])

    status_payload = status if isinstance(status, dict) else {}
    info_payload = info if isinstance(info, dict) else {}
    connected = str(status_payload.get("status", "")).casefold() == "connected"
    healthy = str(info_payload.get("status", "")).casefold() == "healthy"
    if connected and healthy:
        result.gateway_status = "ready"
        result.gateway_detail = (
            f"{status_payload.get('gateway', 'gateway')} connected; "
            f"server {status_payload.get('server', 'unknown')}"
        )
    else:
        result.gateway_status = "error"
        result.gateway_detail = status_error or info_error or "gateway is not ready"
        result.errors.append(f"OpenShell gateway is not ready: {result.gateway_detail}")

    result.gateway_extension_status = _gateway_extension_status(info)
    if result.gateway_extension_status == "not_active":
        result.errors.append(
            "OpenShell gateway does not report the AI Guardian middleware as active"
        )
    elif result.gateway_extension_status == "unknown":
        result.errors.append(
            "OpenShell gateway extension activation status is unavailable"
        )

    _check_configured_middleware(
        result,
        gateway_config_path or _default_gateway_config_path(),
        version_text or "unknown",
    )
    return result


def format_middleware_readiness(
    readiness: OpenShellMiddlewareReadiness,
) -> str:
    """Format direct endpoint liveness and separately reported gateway state."""
    symbol = lambda status: "✓" if status == "ready" else "✗"
    middleware_status_labels = {
        "running": ("✓", "Running (Describe responded)"),
        "not_configured": ("✗", "Not configured"),
        "not_responding": ("✗", "Not responding"),
        "wrong_implementation": ("✗", "Wrong implementation"),
        "identity_incomplete": ("?", "Identity incomplete"),
        "probe_unavailable": ("?", "Probe unavailable"),
        "configuration_error": ("✗", "Gateway configuration error"),
        "unknown": ("?", "Not verified"),
    }
    gateway_extension_labels = {
        "active": ("✓", "Active (reported by gateway)"),
        "not_active": ("✗", "Not active (reported by gateway)"),
        "unknown": ("?", "Unknown"),
    }
    middleware_symbol, middleware_label = middleware_status_labels.get(
        readiness.middleware_status, ("?", "Not verified")
    )
    extension_symbol, extension_label = gateway_extension_labels.get(
        readiness.gateway_extension_status, ("?", "Unknown")
    )
    lines = [
        "OpenShell middleware readiness",
        "",
        f"OpenShell compatibility: {symbol(readiness.compatibility_status)} "
        f"{readiness.openshell_version or 'unknown'}",
        f"Gateway: {symbol(readiness.gateway_status)} "
        f"{readiness.gateway_detail or 'not checked'}",
        "",
        f"Middleware status: {middleware_symbol} {middleware_label}",
        f"Gateway extension status: {extension_symbol} {extension_label}",
    ]
    if readiness.middleware_implementation:
        lines.append(
            f"Middleware implementation: {readiness.middleware_implementation}"
        )
    if readiness.middleware_version:
        lines.append(f"Middleware version: {readiness.middleware_version}")
    if readiness.middleware_registration:
        lines.append(f"Gateway registration: {readiness.middleware_registration}")
    if readiness.identity_status != "ready" and readiness.middleware_detail:
        lines.extend(
            [
                "",
                "Middleware check details:",
                f"  {readiness.middleware_detail}",
            ]
        )
    lines.extend(
        [
            "",
            "Ownership boundary",
            "- The service manager owns the Rust process and cleanup.",
            "- OpenShell owns gateway registration and network_middlewares activation.",
            "- AI Guardian does not install a middleware lifecycle command.",
        ]
    )
    if readiness.errors:
        additional_errors = [
            error for error in readiness.errors if error != readiness.middleware_detail
        ]
        lines.extend(
            [
                "",
                "Operator setup if checks are not ready",
                "1. If the status is Probe unavailable, refresh AI Guardian so",
                "   grpcio is installed in the tray's Python environment.",
                "2. Otherwise ensure the service manager runs the Rust middleware.",
                "3. Check the gRPC endpoint in the effective gateway TOML and make",
                "   it reachable from this host and the OpenShell gateway.",
                "4. Restart the tray after dependency changes or the gateway after",
                "   TOML changes, then apply a complete sandbox policy.",
            ]
        )
        if additional_errors:
            lines.extend(["", "Required follow-up"])
            lines.extend(f"- {error}" for error in additional_errors)
    lines.extend(["", "Guide: docs/OPENSHELL_MIDDLEWARE.md"])
    return "\n".join(lines)


__all__ = [
    "MIDDLEWARE_IMPLEMENTATION_NAME",
    "OpenShellMiddlewareReadiness",
    "check_openshell_middleware",
    "format_middleware_readiness",
]
