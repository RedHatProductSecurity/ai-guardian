"""UX contracts for the OpenShell sandbox/middleware ownership boundary."""

from unittest.mock import patch

import pytest


def test_user_experience_sandbox_creation_has_no_middleware_lifecycle_options(
    capsys,
):
    """
    USER EXPERIENCE: Sandbox creation is independent from middleware.

    Expected experience:
    - ``sandbox create`` creates only the sandbox and its normal policy.
    - Middleware deployment and activation are not hidden in sandbox setup.
    - The operator manages middleware through OpenShell's gateway/policy layer.
    """
    from ai_guardian.cli import main

    with patch("sys.argv", ["ai-guardian", "sandbox", "create", "--help"]):
        with pytest.raises(SystemExit) as error:
            main()

    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert "--middleware" not in help_text
    assert "--middleware-policy" not in help_text


def test_user_experience_tray_middleware_flow_preserves_ownership_boundary():
    """
    USER EXPERIENCE: Tray probes the middleware endpoint from gateway TOML.

    Expected experience:
    - The tray reports OpenShell compatibility and gateway health.
    - A live Describe RPC confirms the AI Guardian implementation and version.
    - The endpoint and registration are discovered from gateway TOML.
    - Gateway activation is reported separately from middleware liveness.
    - The report tells the operator that service managers own the process.
    - OpenShell remains responsible for gateway registration and policy activation.
    """
    from ai_guardian.tray.openshell_middleware import (
        MIDDLEWARE_IMPLEMENTATION_NAME,
        OpenShellMiddlewareReadiness,
        format_middleware_readiness,
    )

    report = format_middleware_readiness(
        OpenShellMiddlewareReadiness(
            cli="openshell",
            openshell_version="OpenShell 0.1.2",
            compatibility_status="ready",
            gateway_status="ready",
            gateway_detail="gateway connected",
            middleware_status="running",
            gateway_extension_status="active",
            identity_status="ready",
            middleware_implementation=MIDDLEWARE_IMPLEMENTATION_NAME,
            middleware_version="1.20.0-dev",
            middleware_registration="content-guard",
            middleware_detail=(
                f"{MIDDLEWARE_IMPLEMENTATION_NAME} version 1.20.0-dev; "
                "gateway registration: content-guard"
            ),
        ),
    )

    assert "service manager owns the Rust process" in report
    assert "OpenShell owns gateway registration" in report
    assert "does not install a middleware lifecycle command" in report
    assert "Middleware status: ✓ Running (Describe responded)" in report
    assert "Gateway extension status: ✓ Active (reported by gateway)" in report
    assert f"Middleware implementation: {MIDDLEWARE_IMPLEMENTATION_NAME}" in report
    assert "Middleware version: 1.20.0-dev" in report
    assert "Gateway registration: content-guard" in report
    assert "Binary:" not in report
    assert "Service endpoint" not in report
    assert "OpenShell middleware readiness\n\nOpenShell compatibility:" in report
    assert "Gateway: ✓ gateway connected\n\nMiddleware status:" in report
    assert "Gateway registration: content-guard\n\nOwnership boundary" in report
    assert (
        "- AI Guardian does not install a middleware lifecycle command.\n\nGuide:"
        in report
    )


def test_user_experience_tray_reports_a_wrong_middleware_identity():
    """
    USER EXPERIENCE: A different gateway middleware is not reported as ready.

    Expected experience:
    - The tray names the implementation returned by the configured endpoint.
    - The report names the expected AI Guardian implementation.
    - Readiness remains failed even when the gateway itself is healthy.
    """
    from ai_guardian.tray.openshell_middleware import (
        OpenShellMiddlewareReadiness,
        format_middleware_readiness,
    )

    report = format_middleware_readiness(
        OpenShellMiddlewareReadiness(
            cli="openshell",
            compatibility_status="ready",
            gateway_status="ready",
            gateway_detail="gateway connected",
            middleware_status="wrong_implementation",
            gateway_extension_status="not_active",
            identity_status="error",
            middleware_detail=(
                "Configured middleware responded to Describe, but did not identify "
                "as ai-guardian/rust-middleware: content-guard: "
                "vendor/other-middleware version 2.3.4 "
                "(expected ai-guardian/rust-middleware)"
            ),
        )
    )

    assert "Middleware status: ✗ Wrong implementation" in report
    assert "Gateway extension status: ✗ Not active (reported by gateway)" in report
    assert "did not identify as ai-guardian/rust-middleware" in report
    assert "vendor/other-middleware version 2.3.4" in report


def test_user_experience_gateway_metadata_does_not_mask_a_stopped_service():
    """
    USER EXPERIENCE: Active gateway metadata is distinct from endpoint liveness.

    Expected experience:
    - A failed Describe probe is never shown as a running middleware process.
    - The gateway's cached/negotiated active-extension state remains separate.
    - The operator sees that the process may be stopped or unreachable.
    """
    from ai_guardian.tray.openshell_middleware import (
        OpenShellMiddlewareReadiness,
        format_middleware_readiness,
    )

    report = format_middleware_readiness(
        OpenShellMiddlewareReadiness(
            cli="openshell",
            compatibility_status="ready",
            gateway_status="ready",
            gateway_detail="gateway connected",
            middleware_status="not_responding",
            gateway_extension_status="active",
            identity_status="error",
            middleware_detail=(
                "No configured endpoint verified the AI Guardian middleware. "
                "content-guard: Describe RPC failed (UNAVAILABLE). The service "
                "may be stopped or the configured endpoint may not be reachable"
            ),
            errors=["middleware endpoint unavailable"],
        )
    )

    assert "Middleware status: ✗ Not responding" in report
    assert "Gateway extension status: ✓ Active (reported by gateway)" in report
    assert "may be stopped" in report
    assert "Middleware status: ✓ Running" not in report


def test_user_experience_missing_registration_is_not_reported_as_running():
    """
    USER EXPERIENCE: Missing gateway TOML registration requires operator review.

    Expected experience:
    - No middleware process is claimed to be running without a configured endpoint.
    - The report distinguishes missing registration from endpoint failure.
    - The report names the likely stopped-service/configuration causes.
    """
    from ai_guardian.tray.openshell_middleware import (
        OpenShellMiddlewareReadiness,
        format_middleware_readiness,
    )

    report = format_middleware_readiness(
        OpenShellMiddlewareReadiness(
            cli="openshell",
            middleware_status="not_configured",
            gateway_extension_status="not_active",
            identity_status="error",
            middleware_detail=(
                "No supervisor middleware registration was found in gateway.toml; "
                "AI Guardian middleware may not be running, or its registration "
                "may be missing or malformed"
            ),
            errors=["gateway middleware registration missing"],
        )
    )

    assert "Middleware status: ✗ Not configured" in report
    assert "may not be running" in report
    assert "registration may be missing or malformed" in report
    assert "Middleware status: ✓ Running" not in report


def test_user_experience_missing_probe_dependency_points_to_tray_install():
    """
    USER EXPERIENCE: Missing gRPC dependency is fixed in the tray environment.

    Expected experience:
    - Middleware probe unavailability is not confused with a stopped service.
    - The operator is told to refresh the AI Guardian installation dependencies.
    - Tray and service-manager restart guidance are not conflated.
    """
    from ai_guardian.tray.openshell_middleware import (
        OpenShellMiddlewareReadiness,
        format_middleware_readiness,
    )

    report = format_middleware_readiness(
        OpenShellMiddlewareReadiness(
            cli="openshell",
            middleware_status="probe_unavailable",
            identity_status="error",
            middleware_detail=(
                "grpcio is not installed in the AI Guardian tray's Python environment"
            ),
            errors=[
                "grpcio is not installed in the AI Guardian tray's Python environment"
            ],
        )
    )

    assert "Middleware status: ? Probe unavailable" in report
    assert "refresh AI Guardian" in report
    assert "grpcio is installed" in report
    assert "Restart the tray after dependency changes" in report


def test_user_experience_apply_policy_profile_is_wide_and_descriptive():
    """
    USER EXPERIENCE: Apply policy makes long profile choices readable.

    Expected experience:
    - The policy profile selector is wider than the generic choice field.
    - Its help distinguishes the selected overlay from the complete replacement.
    - The operator can enter a policy file path when needed.
    """
    from ai_guardian.tray.menu_builder import TrayMenuBuilder

    with patch(
        "ai_guardian.tray.menu_builder.discover_openshell_policies",
        return_value=(),
    ):
        fields = TrayMenuBuilder(None)._openshell_policy_apply_fields([])

    profile = next(field for field in fields if field["name"] == "policy")
    assert profile["width"] == 68
    assert "enter a policy file path" in profile["help"]
    assert "overlay merges into the sandbox base" in profile["help"]
    assert "complete policy before replacement" in profile["help"]


def test_user_experience_policy_form_is_scoped_to_its_sandbox_menu():
    """
    USER EXPERIENCE: Apply policy from a sandbox menu stays on that sandbox.

    Expected experience:
    - The menu action carries the selected OpenShell sandbox into the form.
    - The sandbox selector shows only that sandbox and cannot be changed.
    - Policy profile selection and complete-policy review remain available.
    """
    from ai_guardian.tray.menu_builder import TrayMenuBuilder

    with patch(
        "ai_guardian.tray.menu_builder.discover_openshell_policies",
        return_value=(),
    ):
        fields = TrayMenuBuilder(None)._openshell_policy_apply_fields(
            [{"name": "sandbox-two", "phase": "running"}],
            sandbox_name="sandbox-two",
        )

    sandbox = next(field for field in fields if field["name"] == "sandbox")
    assert sandbox["choices"] == ("sandbox-two (running)",)
    assert sandbox["default"] == "sandbox-two (running)"
    assert sandbox["editable"] is False
    assert "scoped to the selected OpenShell sandbox" in sandbox["help"]


def test_user_experience_policy_apply_allows_edit_before_replacement():
    """
    USER EXPERIENCE: The user can edit the merged policy before replacement.

    Expected experience:
    - The selected profile source and full composed YAML are shown in an editor.
    - The edit dialog can scroll through the complete policy document.
    - Clicking Replace policy is the explicit approval to validate and apply.
    """
    from ai_guardian.tray.sandbox_dialog import show_sandbox_form

    preview = (
        "Selected policy profile: github-readwrite.yaml\n\n"
        "Complete merged policy (YAML):\n"
        "filesystem_policy:\n  read_only: false\n"
        "network_policies:\n  github: readwrite\n\n"
    )
    message = "Edit the complete merged YAML below if you wish."
    fields = [
        {
            "name": "policy_yaml",
            "label": "Complete merged policy (YAML)",
            "type": "textarea",
            "default": preview,
            "required": True,
        }
    ]

    with (
        patch("ai_guardian.ui.display.select_ui_provider", return_value="tkinter"),
        patch(
            "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
            return_value={"policy_yaml": preview},
        ) as show_form,
    ):
        result = show_sandbox_form(
            "Apply OpenShell policy",
            message,
            fields,
            submit_label="Replace policy",
        )

    assert result == {"policy_yaml": preview}
    show_form.assert_called_once_with(
        "Apply OpenShell policy",
        message,
        fields,
        submit_label="Replace policy",
    )
