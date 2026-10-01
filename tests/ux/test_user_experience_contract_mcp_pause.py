"""UX contracts for pause-aware MCP action-gating checks."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("mcp", reason="MCP SDK requires Python >= 3.10")

from ai_guardian.mcp.server import create_server


class TestMCPPauseUX:
    """Document the paused response and preserved observability experience."""

    @patch("ai_guardian.tools.policy.ToolPolicyChecker")
    @patch(
        "ai_guardian.daemon.state.DaemonState.is_paused_on_disk",
        return_value=True,
    )
    def test_paused_action_check_is_explicit_and_fail_safe(
        self, mock_paused, mock_checker_cls, tmp_path
    ):
        """
        USER EXPERIENCE: Daemon pause -> MCP action-gating check is skipped.

        The response distinguishes a skipped proactive check from an allow or
        block result and reminds the agent that hooks still enforce security.
        """
        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        result = tool.fn(command="git status", project_dir=str(tmp_path))

        assert result["status"] == "paused"
        assert result["skipped"] is True
        assert result["reason"] == "proactive_checks_paused"
        assert result["pause_source"] == "daemon"
        assert result["message"] == (
            "MCP action-gating check skipped because AI Guardian is paused. "
            "Hooks remain active and enforce security."
        )
        assert "policy_decision" not in result
        mock_paused.assert_called_once_with(cwd=str(tmp_path.resolve()))
        mock_checker_cls.assert_not_called()

    @patch("ai_guardian.violations.logger.ViolationLogger")
    @patch(
        "ai_guardian.daemon.state.DaemonState.is_paused_on_disk",
        return_value=True,
    )
    @patch(
        "ai_guardian.config.loaders._load_config_file",
        return_value=(
            {"mcp_server": {"proactive_level": "medium"}},
            None,
        ),
    )
    def test_query_tools_remain_available_and_report_effective_pause(
        self, mock_config, mock_paused, mock_logger
    ):
        """
        USER EXPERIENCE: Daemon pause -> diagnostics remain available.

        ``get_config`` reports the effective paused level while retaining the
        configured level, and ``get_violations`` remains callable.
        """
        mock_violation_logger = MagicMock()
        mock_violation_logger.get_recent_violations.return_value = []
        mock_logger.return_value = mock_violation_logger

        server = create_server()
        config_result = server._tool_manager._tools["get_config"].fn(
            project_dir="/workspace/paused-project"
        )
        violations_result = server._tool_manager._tools["get_violations"].fn()

        features = config_result["features"]
        assert features["proactive_level"] == "paused"
        assert features["configured_proactive_level"] == "medium"
        assert features["proactive_pause_source"] == "daemon"
        assert violations_result == {"violations": [], "count": 0}
        mock_config.assert_called_once()
        mock_paused.assert_called_once_with(cwd="/workspace/paused-project")
