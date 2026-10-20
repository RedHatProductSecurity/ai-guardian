"""UX contracts for Codex's OpenShell identity/credential separation.

Manual verification (operator-owned): rebuild both the AI Guardian package and
the candidate image, create a dedicated OAuth sandbox, and verify Codex starts
and privately selects the expected account/workspace. Separately verify actual
provider-boundary middleware denial. Never publish auth files or account JSON.
These isolated tests verify the handoff, not live provider qualification.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai_guardian.sandbox import create_sandbox


@pytest.fixture
def oauth_request(tmp_path):
    """No host credentials/configuration or live gateway is used by these tests."""
    args = SimpleNamespace(
        runtime="openshell",
        name="codex-auth-contract",
        cli="codex",
        openshell_auth="oauth",
        environment=[],
        command_args=["/bin/true"],
    )
    with (
        patch.dict(
            os.environ,
            {
                "HOME": str(tmp_path),
                "CODEX_HOME": str(tmp_path / ".codex"),
                "OPENAI_API_KEY": "",
                "CODEX_ACCOUNT_ID": "",
                "CODEX_AUTH_ACCOUNT_ID": "contract-workspace-id",
                "CODEX_AUTH_ACCESS_TOKEN": "contract-access-credential",
                "CODEX_AUTH_REFRESH_TOKEN": "contract-refresh-credential",
                "CODEX_AUTH_ID_TOKEN": "contract-id-credential",
            },
        ),
        patch("ai_guardian.sandbox._sandbox_name_exists", return_value=False),
        patch("ai_guardian.sandbox._initial_config_source", return_value=None),
        patch(
            "ai_guardian.sandbox._openshell_provider_profiles", return_value=["codex"]
        ),
        patch("ai_guardian.sandbox._openshell_providers_v2_enabled", return_value=True),
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
    ):
        yield args


@pytest.mark.parametrize("provider_exists", [False, True])
def test_oauth_creation_separates_identity_from_bearer_credentials(
    oauth_request, provider_exists
):
    """
    USER EXPERIENCE: OAuth creation supplies a locally comparable workspace ID.

    The new/refreshed provider retains the credentials; only identity metadata
    reaches sandbox-create arguments. Logs contain neither credentials nor the
    account identifier. No fallback to API-key authentication occurs.
    """
    oauth_request.environment = [
        "CODEX_AUTH_ACCESS_TOKEN=contract-access-credential",
        "CODEX_AUTH_REFRESH_TOKEN=contract-refresh-credential",
        "CODEX_AUTH_ID_TOKEN=contract-id-credential",
        "OPENAI_API_KEY=contract-api-credential",
    ]
    output = []
    with (
        patch(
            "ai_guardian.sandbox._openshell_provider_exists",
            return_value=provider_exists,
        ),
        patch("ai_guardian.sandbox._run", return_value=0) as run,
    ):
        assert create_sandbox(oauth_request, interactive=False, output=output) == 0

    create_command = next(
        call.args[0]
        for call in run.call_args_list
        if call.args[0][1:3] == ["sandbox", "create"]
    )
    assert "CODEX_ACCOUNT_ID=contract-workspace-id" in create_command
    assert not any(value.startswith("CODEX_AUTH_") for value in create_command)
    for value in (
        "contract-access-credential",
        "contract-refresh-credential",
        "contract-id-credential",
        "contract-api-credential",
    ):
        assert value not in " ".join(create_command)
        assert value not in "".join(output)
    assert "contract-workspace-id" not in "".join(output)


@pytest.mark.parametrize("provider_exists", [False, True])
@pytest.mark.parametrize(
    "account_id", ["", "openshell:resolve:env:CODEX_AUTH_ACCOUNT_ID", "bad\nid"]
)
def test_invalid_oauth_identity_stops_creation_with_a_safe_error(
    oauth_request, provider_exists, account_id
):
    """
    USER EXPERIENCE: Invalid identity fails before provider mutation or creation.

    User sees exactly:
    "Error: Codex OAuth requires a literal account ID for workspace routing"
    No credentials/invalid identity are printed and no alternate auth is tried.
    """
    output = []
    with (
        patch.dict(os.environ, {"CODEX_AUTH_ACCOUNT_ID": account_id}),
        patch(
            "ai_guardian.sandbox._openshell_provider_exists",
            return_value=provider_exists,
        ),
        patch("ai_guardian.sandbox._run") as run,
    ):
        assert create_sandbox(oauth_request, interactive=False, output=output) == 2
    assert output == [
        "Error: Codex OAuth requires a literal account ID for workspace routing\n"
    ]
    run.assert_not_called()


def test_conflicting_oauth_identity_is_not_silently_forwarded(oauth_request):
    """
    USER EXPERIENCE: An identity override cannot misroute a managed provider.

    User sees a mismatch error without either identity or credentials. The
    existing gateway provider is not refreshed and no sandbox is created.
    """
    oauth_request.environment = ["CODEX_ACCOUNT_ID=other-contract-workspace"]
    output = []
    with patch("ai_guardian.sandbox._run") as run:
        assert create_sandbox(oauth_request, interactive=False, output=output) == 2
    assert output == [
        "Error: Codex account identity does not match the selected local OAuth credentials\n"
    ]
    run.assert_not_called()
