"""UX contracts for built-in AI Guardian MCP identity verification."""

from unittest.mock import patch

from ai_guardian.tools.policy import ToolPolicyChecker
from tests.fixtures.mock_mcp_server import create_hook_data


def _config():
    return {
        "permissions": {
            "enabled": True,
            "rules": [
                {
                    "matcher": "mcp__ai-guardian__*",
                    "mode": "allow",
                    "patterns": ["*"],
                }
            ],
        }
    }


class TestMCPIdentityUX:
    """Document the fail-closed identity boundary for built-in MCP tools."""

    @patch("ai_guardian.tools.policy.verify_active_attestation", return_value=False)
    def test_spoofed_registration_is_blocked(self, mock_verify):
        """
        USER EXPERIENCE: Same-name MCP registration without attestation -> blocked.

        The namespace alone must not auto-allow a server that claims to be
        ``ai-guardian``.
        """
        checker = ToolPolicyChecker(config=_config())
        allowed, message, _ = checker.check_tool_allowed(
            create_hook_data(
                tool_name="mcp__ai-guardian__get_config",
                tool_input={},
                hook_event="PreToolUse",
            )
        )

        assert mock_verify.called
        assert allowed is False
        assert message is not None
        assert "MCP Identity Verification Failed" in message
        assert "allowlist" not in message.lower()

    @patch("ai_guardian.tools.policy.verify_active_attestation", return_value=True)
    def test_verified_registration_passes(self, mock_verify):
        """
        USER EXPERIENCE: Verified AI Guardian MCP process -> allowed.
        """
        checker = ToolPolicyChecker(config=_config())
        allowed, message, _ = checker.check_tool_allowed(
            create_hook_data(
                tool_name="mcp__ai-guardian__get_config",
                tool_input={},
                hook_event="PreToolUse",
            )
        )

        assert mock_verify.called
        assert allowed is True
        assert message is None

    @patch("ai_guardian.tools.policy.verify_active_attestation", return_value=False)
    def test_identity_gate_remains_active_when_permissions_are_disabled(
        self, mock_verify
    ):
        """Disabling ordinary permission rules cannot disable identity verification."""
        config = {"permissions": {"enabled": False, "rules": []}}
        checker = ToolPolicyChecker(config=config)
        allowed, message, _ = checker.check_tool_allowed(
            create_hook_data(
                tool_name="mcp__ai-guardian__check_path",
                tool_input={},
                hook_event="PreToolUse",
            )
        )

        assert mock_verify.called
        assert allowed is False
        assert "identity" in message.lower()

    @patch("ai_guardian.mcp.server.HAS_MCP", True)
    @patch("ai_guardian.mcp.identity.ensure_mcp_identity", return_value=True)
    @patch("ai_guardian.mcp.identity.attest_mcp_server", return_value=False)
    @patch("ai_guardian.mcp.server.create_server")
    def test_unverified_server_refuses_startup(
        self, mock_create_server, mock_attest, mock_ensure, capsys
    ):
        """
        USER EXPERIENCE: Unverified AI Guardian MCP process -> startup fails closed.

        The server must not expose tools when its local identity attestation fails.
        """
        from ai_guardian.mcp.server import run_mcp_server

        assert run_mcp_server() == 1
        mock_ensure.assert_called_once_with()
        mock_attest.assert_called_once_with()
        mock_create_server.assert_not_called()
        assert (
            "Error: AI Guardian MCP server identity verification failed."
            in capsys.readouterr().err
        )

    @patch("ai_guardian.mcp.server.HAS_MCP", True)
    @patch("ai_guardian.mcp.server.create_server")
    def test_existing_mcp_registration_migrates_identity_before_startup(
        self, mock_create_server
    ):
        """
        USER EXPERIENCE: Existing MCP registration -> automatic identity migration.

        All supported clients launch the same server entry point, so a manual,
        upgraded, or ``uvx`` registration must recover without client-specific
        setup steps.
        """
        from ai_guardian.mcp.identity import get_identity_manifest_path
        from ai_guardian.mcp.server import run_mcp_server

        assert not get_identity_manifest_path().exists()
        assert run_mcp_server() == 0
        assert get_identity_manifest_path().is_file()
        mock_create_server.return_value.run.assert_called_once_with(transport="stdio")
