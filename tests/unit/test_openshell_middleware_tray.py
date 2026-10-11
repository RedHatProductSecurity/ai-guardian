"""Tests for the tray's OpenShell middleware readiness guidance."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai_guardian.tray.openshell_middleware_probe import (
    MiddlewareProbeError,
    MiddlewareProbeIdentity,
)

from ai_guardian.tray.openshell_middleware import (
    MIDDLEWARE_IMPLEMENTATION_NAME,
    check_openshell_middleware,
    format_middleware_readiness,
)


def _write_gateway_config(tmp_path, registrations=()):
    lines = ["[openshell]", "version = 2", ""]
    for name, endpoint in registrations:
        lines.extend(
            [
                "[[openshell.supervisor.middleware]]",
                f"name = {json.dumps(name)}",
                f"grpc_endpoint = {json.dumps(endpoint)}",
                "",
            ]
        )
    path = tmp_path / "gateway.toml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _check_with_cli(version, responses, config_path, probe_responses=None):
    def run(command, **_kwargs):
        if command == ["openshell", "--version"]:
            return SimpleNamespace(returncode=0, stdout=version, stderr="")
        payload = responses.get(tuple(command))
        if payload is None:
            return SimpleNamespace(
                returncode=1, stdout="", stderr="gateway unavailable"
            )
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    def probe(endpoint, **_kwargs):
        value = (probe_responses or {}).get(endpoint)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise MiddlewareProbeError("Describe RPC failed (UNAVAILABLE)")
        return value

    with (
        patch(
            "ai_guardian.tray.openshell_middleware.shutil.which",
            return_value="/bin/openshell",
        ),
        patch("ai_guardian.tray.openshell_middleware.subprocess.run", side_effect=run),
        patch(
            "ai_guardian.tray.openshell_middleware.probe_middleware_endpoint",
            side_effect=probe,
        ),
    ):
        return check_openshell_middleware(gateway_config_path=config_path)


def _healthy_gateway(extensions):
    return {
        ("openshell", "status", "--output", "json"): {
            "gateway": "local",
            "server": "https://127.0.0.1:17670",
            "status": "connected",
        },
        ("openshell", "gateway", "info", "--output", "json"): {
            "status": "healthy",
            "extensions": extensions,
        },
    }


def test_check_probes_configured_endpoint_and_verifies_ai_guardian_identity(
    tmp_path,
):
    endpoint = "http://127.0.0.1:50051"
    regex_endpoint = "http://127.0.0.1:50052"
    config_path = _write_gateway_config(
        tmp_path,
        [("content-guard", endpoint), ("regex", regex_endpoint)],
    )
    responses = _healthy_gateway(
        [
            {
                "kind": "supervisor-middleware",
                "configured_name": "content-guard",
                "implementation_name": MIDDLEWARE_IMPLEMENTATION_NAME,
                "implementation_version": "1.20.0-dev",
            },
            {
                "kind": "supervisor-middleware",
                "configured_name": "openshell/regex",
                "implementation_name": "openshell/regex",
                "implementation_version": "0.1.2",
            },
        ]
    )

    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        responses,
        config_path,
        {
            endpoint: MiddlewareProbeIdentity(
                MIDDLEWARE_IMPLEMENTATION_NAME,
                "1.20.0-dev",
            ),
            regex_endpoint: MiddlewareProbeIdentity("openshell/regex", "0.1.2"),
        },
    )

    assert readiness.ready is True
    assert readiness.middleware_status == "running"
    assert readiness.gateway_extension_status == "active"
    assert readiness.identity_status == "ready"
    report = format_middleware_readiness(readiness)
    assert "Middleware status: ✓ Running (Describe responded)" in report
    assert "Gateway extension status: ✓ Active (reported by gateway)" in report
    assert f"Middleware implementation: {MIDDLEWARE_IMPLEMENTATION_NAME}" in report
    assert "Middleware version: 1.20.0-dev" in report
    assert "Gateway registration: content-guard" in report
    assert "Binary:" not in report
    assert "Service endpoint" not in report


def test_check_reports_wrong_registered_middleware_identity(tmp_path):
    endpoint = "http://127.0.0.1:50051"
    config_path = _write_gateway_config(tmp_path, [("content-guard", endpoint)])
    responses = _healthy_gateway(
        [
            {
                "kind": "supervisor-middleware",
                "configured_name": "content-guard",
                "implementation_name": "vendor/other-middleware",
                "implementation_version": "2.3.4",
            }
        ]
    )

    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        responses,
        config_path,
        {
            endpoint: MiddlewareProbeIdentity(
                "vendor/other-middleware",
                "2.3.4",
            )
        },
    )

    assert readiness.gateway_status == "ready"
    assert readiness.middleware_status == "wrong_implementation"
    assert readiness.gateway_extension_status == "not_active"
    assert readiness.identity_status == "error"
    assert readiness.ready is False
    assert "did not identify as" in readiness.middleware_detail
    assert "vendor/other-middleware" in readiness.middleware_detail
    assert MIDDLEWARE_IMPLEMENTATION_NAME in readiness.middleware_detail


def test_check_reports_when_gateway_toml_has_no_middleware_registration(tmp_path):
    config_path = _write_gateway_config(tmp_path)
    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        _healthy_gateway([]),
        config_path,
    )

    assert readiness.middleware_status == "not_configured"
    assert (
        "No supervisor middleware registration was found" in readiness.middleware_detail
    )
    assert "may not be running" in readiness.middleware_detail


def test_check_requires_live_endpoint_to_report_middleware_version(tmp_path):
    endpoint = "http://127.0.0.1:50051"
    config_path = _write_gateway_config(tmp_path, [("content-guard", endpoint)])
    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        _healthy_gateway([]),
        config_path,
        {endpoint: MiddlewareProbeIdentity(MIDDLEWARE_IMPLEMENTATION_NAME, "")},
    )

    assert readiness.middleware_status == "identity_incomplete"
    assert readiness.identity_status == "error"
    assert "did not report its implementation version" in readiness.middleware_detail


def test_check_does_not_call_an_incomplete_describe_response_running(tmp_path):
    endpoint = "http://127.0.0.1:50051"
    config_path = _write_gateway_config(tmp_path, [("content-guard", endpoint)])
    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        _healthy_gateway([]),
        config_path,
        {
            endpoint: MiddlewareProbeError(
                "Describe response has no implementation metadata",
                kind="identity",
            )
        },
    )

    assert readiness.middleware_status == "identity_incomplete"
    assert "endpoint responded" in readiness.middleware_detail
    assert "may be stopped" not in readiness.middleware_detail


def test_missing_grpc_dependency_recommends_refreshing_tray_dependencies(tmp_path):
    endpoint = "http://127.0.0.1:50051"
    config_path = _write_gateway_config(tmp_path, [("content-guard", endpoint)])
    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        _healthy_gateway([]),
        config_path,
        {
            endpoint: MiddlewareProbeError(
                "grpcio is not installed in the AI Guardian tray's Python environment",
                kind="dependency",
            )
        },
    )

    report = format_middleware_readiness(readiness)
    assert readiness.middleware_status == "probe_unavailable"
    assert "grpcio is not installed" in report
    assert "refresh AI Guardian" in report
    assert "grpcio is installed" in report
    assert "Restart the tray after dependency changes" in report
    assert "Ensure a service manager runs the Rust middleware" not in report


def test_active_gateway_metadata_does_not_mask_a_stopped_middleware(tmp_path):
    endpoint = "http://127.0.0.1:50051"
    config_path = _write_gateway_config(tmp_path, [("content-guard", endpoint)])
    responses = _healthy_gateway(
        [
            {
                "kind": "supervisor-middleware",
                "configured_name": "content-guard",
                "implementation_name": MIDDLEWARE_IMPLEMENTATION_NAME,
                "implementation_version": "1.20.0-dev",
            }
        ]
    )
    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        responses,
        config_path,
        {endpoint: MiddlewareProbeError("Describe RPC failed (UNAVAILABLE)")},
    )

    assert readiness.middleware_status == "not_responding"
    assert readiness.gateway_extension_status == "active"
    assert readiness.ready is False
    report = format_middleware_readiness(readiness)
    assert "Middleware status: ✗ Not responding" in report
    assert "Gateway extension status: ✓ Active (reported by gateway)" in report
    assert "service may be stopped" in report
    assert "Middleware status: ✓ Running" not in report


def test_gateway_config_environment_override_is_discovered(monkeypatch, tmp_path):
    from ai_guardian.tray.openshell_middleware import _default_gateway_config_path

    override = tmp_path / "custom-gateway.toml"
    monkeypatch.setenv("OPENSHELL_GATEWAY_CONFIG", str(override))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert _default_gateway_config_path() == override


def test_invalid_gateway_toml_is_reported_as_configuration_error(tmp_path):
    config_path = tmp_path / "gateway.toml"
    config_path.write_text("[openshell\n", encoding="utf-8")

    readiness = _check_with_cli(
        "OpenShell 0.1.2\n",
        _healthy_gateway([]),
        config_path,
    )

    assert readiness.middleware_status == "configuration_error"
    assert "gateway TOML is invalid" in readiness.middleware_detail


def test_check_surfaces_gateway_and_openshell_compatibility_errors(tmp_path):
    config_path = _write_gateway_config(tmp_path)
    readiness = _check_with_cli("OpenShell 0.2.0\n", {}, config_path)

    assert readiness.ready is False
    assert readiness.compatibility_status == "error"
    assert readiness.gateway_status == "error"
    assert readiness.middleware_status == "not_configured"
    assert any("gateway" in error.lower() for error in readiness.errors)
