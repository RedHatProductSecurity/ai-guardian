"""UX contracts for MCP command checks and their diagnostic categories."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("mcp", reason="MCP SDK requires Python >= 3.10")

from ai_guardian.mcp.server import create_server


class TestMCPCommandUX:
    """Document the safe, context-aware MCP command-check experience."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    @patch("ai_guardian.config.utils.clear_project_dir_override")
    @patch("ai_guardian.config.utils.set_project_dir_override")
    @patch(
        "ai_guardian.developer_session.is_trusted_developer_session", return_value=False
    )
    def test_benign_gh_command_preserves_workspace_context(
        self,
        mock_developer_session,
        mock_set_project_dir,
        mock_clear_project_dir,
        mock_checker_cls,
        tmp_path,
    ):
        """
        USER EXPERIENCE: Benign GitHub command with URL/body -> allowed.

        The command check uses the active workspace context and preserves the
        complete command for the policy layer, including heredoc body text.
        """
        mock_checker = MagicMock()
        mock_checker.check_tool_allowed.return_value = (True, None, "Bash")
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        command = "gh issue create --body <<'EOF'\nSee https://example.com\nEOF"
        result = tool.fn(command=command, project_dir=str(tmp_path))

        assert result["status"] == "allowed"
        mock_developer_session.assert_called_once_with()
        mock_set_project_dir.assert_called_once_with(str(tmp_path.resolve()))
        mock_clear_project_dir.assert_called_once_with()
        hook_data = mock_checker.check_tool_allowed.call_args.args[0]
        assert hook_data["tool_input"]["command"] == command
        assert hook_data["_daemon_cwd"] == str(tmp_path.resolve())

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    def test_permission_denial_is_distinguished_from_command_policy(
        self, mock_checker_cls
    ):
        """
        USER EXPERIENCE: Ordinary permission denial -> permission category.

        The response must not collapse a tool permission result into the old
        generic ``policy_denied`` category.
        """
        mock_checker = MagicMock()
        mock_checker.last_deny_category = "permission_denied"
        mock_checker.check_tool_allowed.return_value = (
            False,
            "Tool is not in the configured allow list",
            "Bash",
        )
        mock_checker_cls.return_value = mock_checker

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        result = tool.fn(command="gh --version")

        assert result["status"] == "blocked"
        assert result["reason"] == "permission_denied"
        assert result["policy_decision"]["reason"] == "permission_denied"
