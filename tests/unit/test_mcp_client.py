"""Tests for MCP client lifecycle management (integrations/mcp_client.py)."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.integrations.mcp_client import (
    MCP_TOOL_PREFIX,
    MCPClientManager,
    _call_tool_result_to_text,
    _mcp_tool_to_anthropic,
    is_mcp_tool,
    parse_mcp_tool_name,
)


class TestIsMCPTool:
    def test_mcp_prefixed(self):
        assert is_mcp_tool("mcp__jira__create_issue") is True

    def test_not_mcp_prefixed(self):
        assert is_mcp_tool("bash") is False
        assert is_mcp_tool("text_editor") is False

    def test_empty(self):
        assert is_mcp_tool("") is False

    def test_partial_prefix(self):
        assert is_mcp_tool("mcp_") is False
        assert is_mcp_tool("mcp") is False


class TestParseMCPToolName:
    def test_valid(self):
        assert parse_mcp_tool_name("mcp__jira__create_issue") == (
            "jira",
            "create_issue",
        )

    def test_server_with_hyphens(self):
        assert parse_mcp_tool_name("mcp__my-server__my-tool") == (
            "my-server",
            "my-tool",
        )

    def test_tool_with_double_underscore(self):
        result = parse_mcp_tool_name("mcp__srv__tool__extra")
        assert result == ("srv", "tool__extra")

    def test_not_mcp(self):
        assert parse_mcp_tool_name("bash") is None

    def test_missing_tool(self):
        assert parse_mcp_tool_name("mcp__server__") is None

    def test_missing_server(self):
        assert parse_mcp_tool_name("mcp____tool") is None

    def test_no_separator(self):
        assert parse_mcp_tool_name("mcp__noseperator") is None


class TestMCPToolToAnthropic:
    def _make_tool(
        self, name="check_path", description="Check path", input_schema=None
    ):
        tool = MagicMock()
        tool.name = name
        tool.description = description
        tool.input_schema = input_schema or {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        return tool

    def test_basic_conversion(self):
        tool = self._make_tool()
        result = _mcp_tool_to_anthropic("my-server", tool)
        assert result["name"] == "mcp__my-server__check_path"
        assert "Check path" in result["description"]
        assert "(MCP server: my-server)" in result["description"]
        assert result["input_schema"]["type"] == "object"
        assert "path" in result["input_schema"]["properties"]

    def test_no_description(self):
        tool = self._make_tool(description=None)
        result = _mcp_tool_to_anthropic("srv", tool)
        assert result["description"] == "(MCP server: srv)"

    def test_no_input_schema(self):
        tool = self._make_tool(input_schema=None)
        tool.input_schema = None
        result = _mcp_tool_to_anthropic("srv", tool)
        assert result["input_schema"] == {"type": "object", "properties": {}}


class TestCallToolResultToText:
    def test_text_content(self):
        block = MagicMock()
        block.text = "hello world"
        result = MagicMock()
        result.content = [block]
        result.structured_content = None
        assert _call_tool_result_to_text(result) == "hello world"

    def test_multiple_text_blocks(self):
        b1 = MagicMock()
        b1.text = "line1"
        b2 = MagicMock()
        b2.text = "line2"
        result = MagicMock()
        result.content = [b1, b2]
        result.structured_content = None
        assert _call_tool_result_to_text(result) == "line1\nline2"

    def test_binary_content(self):
        block = MagicMock(spec=["data", "mimeType"])
        block.text = None
        del block.text
        block.data = b"binary"
        block.mimeType = "image/png"
        result = MagicMock()
        result.content = [block]
        result.structured_content = None
        assert "binary content" in _call_tool_result_to_text(result)

    def test_structured_content_fallback(self):
        result = MagicMock()
        result.content = []
        result.structured_content = {"key": "value"}
        text = _call_tool_result_to_text(result)
        assert '"key"' in text
        assert '"value"' in text

    def test_empty_result(self):
        result = MagicMock()
        result.content = []
        result.structured_content = None
        assert _call_tool_result_to_text(result) == "(no output)"


class TestMCPClientManagerConfig:
    def test_no_enabled_servers(self):
        manager = MCPClientManager(
            {
                "disabled": {"command": "echo", "enabled": False},
            }
        )
        with patch("ai_guardian.integrations.mcp_client.HAS_MCP", True):
            manager.start()
        assert manager.get_tools() == []
        manager.stop()

    def test_get_tools_empty_before_start(self):
        manager = MCPClientManager({"srv": {"command": "echo"}})
        assert manager.get_tools() == []

    def test_stop_idempotent(self):
        manager = MCPClientManager({})
        manager.stop()
        manager.stop()


class TestSkipScanTools:
    def _make_manager(self):
        manager = MCPClientManager(
            {
                "trusted-srv": {
                    "command": "echo",
                    "trust": "trusted",
                },
                "no-scan": {
                    "command": "echo",
                    "scan_results": False,
                },
                "normal": {
                    "command": "echo",
                },
            }
        )
        tool_trusted = MagicMock()
        tool_trusted.name = "tool_a"
        tool_noscan = MagicMock()
        tool_noscan.name = "tool_b"
        tool_normal = MagicMock()
        tool_normal.name = "tool_c"
        manager._tools = {
            "trusted-srv": [tool_trusted],
            "no-scan": [tool_noscan],
            "normal": [tool_normal],
        }
        return manager

    def test_trusted_server_tools_skipped(self):
        manager = self._make_manager()
        skip = manager.get_skip_scan_tools()
        assert "mcp__trusted-srv__tool_a" in skip

    def test_no_scan_results_tools_skipped(self):
        manager = self._make_manager()
        skip = manager.get_skip_scan_tools()
        assert "mcp__no-scan__tool_b" in skip

    def test_normal_tools_not_skipped(self):
        manager = self._make_manager()
        skip = manager.get_skip_scan_tools()
        assert "mcp__normal__tool_c" not in skip


class TestCallToolNotConnected:
    def test_call_tool_not_started(self):
        manager = MCPClientManager({"srv": {"command": "echo"}})
        result = manager.call_tool("srv", "tool", {})
        assert "not connected" in result


@pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason="MCP requires Python >= 3.10",
)
class TestDeferredLoading:
    """Tests for defer_loading MCP server lifecycle."""

    @staticmethod
    def _make_mock_session(tool_names):
        """Create a mock session that discovers the given tool names."""
        mock_tools = []
        for name in tool_names:
            t = MagicMock()
            t.name = name
            t.description = f"Tool {name}"
            t.input_schema = {"type": "object", "properties": {}}
            mock_tools.append(t)

        mock_tools_result = MagicMock()
        mock_tools_result.tools = mock_tools

        mock_session = MagicMock()

        async def _init():
            return None

        async def _list_tools():
            return mock_tools_result

        mock_session.initialize = _init
        mock_session.list_tools = _list_tools

        async def _aenter(self_):
            return mock_session

        async def _aexit(self_, *a):
            return None

        mock_session.__aenter__ = _aenter
        mock_session.__aexit__ = _aexit
        return mock_session

    @patch("ai_guardian.integrations.mcp_client.stdio_client")
    @patch("ai_guardian.integrations.mcp_client.ClientSession")
    def test_deferred_server_tools_discovered(self, mock_session_cls, mock_stdio):
        from contextlib import asynccontextmanager

        mock_session_cls.return_value = self._make_mock_session(["probe_tool"])

        @asynccontextmanager
        async def fake_stdio(params):
            yield (MagicMock(), MagicMock())

        mock_stdio.side_effect = fake_stdio

        manager = MCPClientManager(
            {"deferred-srv": {"command": "test-cmd", "defer_loading": True}}
        )
        try:
            manager.start()
            tools = manager.get_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "mcp__deferred-srv__probe_tool"
        finally:
            manager.stop()

    @patch("ai_guardian.integrations.mcp_client.stdio_client")
    @patch("ai_guardian.integrations.mcp_client.ClientSession")
    def test_deferred_server_not_in_sessions(self, mock_session_cls, mock_stdio):
        from contextlib import asynccontextmanager

        mock_session_cls.return_value = self._make_mock_session(["t1"])

        @asynccontextmanager
        async def fake_stdio(params):
            yield (MagicMock(), MagicMock())

        mock_stdio.side_effect = fake_stdio

        manager = MCPClientManager(
            {"deferred-srv": {"command": "test-cmd", "defer_loading": True}}
        )
        try:
            manager.start()
            assert "deferred-srv" not in manager._sessions
            assert "deferred-srv" in manager._deferred
        finally:
            manager.stop()

    @patch("ai_guardian.integrations.mcp_client.stdio_client")
    @patch("ai_guardian.integrations.mcp_client.ClientSession")
    def test_deferred_server_lazy_connects_on_call(self, mock_session_cls, mock_stdio):
        from contextlib import asynccontextmanager

        call_result = MagicMock()
        call_result.is_error = False
        text_block = MagicMock()
        text_block.text = "tool output"
        call_result.content = [text_block]
        call_result.structured_content = None

        mock_session = self._make_mock_session(["my_tool"])

        async def _call_tool(name, arguments):
            return call_result

        mock_session.call_tool = _call_tool
        mock_session_cls.return_value = mock_session

        @asynccontextmanager
        async def fake_stdio(params):
            yield (MagicMock(), MagicMock())

        mock_stdio.side_effect = fake_stdio

        manager = MCPClientManager(
            {"lazy-srv": {"command": "test-cmd", "defer_loading": True}}
        )
        try:
            manager.start()
            assert "lazy-srv" not in manager._sessions

            result = manager.call_tool("lazy-srv", "my_tool", {})
            assert result == "tool output"
            assert "lazy-srv" in manager._sessions
        finally:
            manager.stop()

    @patch("ai_guardian.integrations.mcp_client.stdio_client")
    @patch("ai_guardian.integrations.mcp_client.ClientSession")
    def test_deferred_and_immediate_mix(self, mock_session_cls, mock_stdio):
        from contextlib import asynccontextmanager

        call_count = {"stdio": 0}

        @asynccontextmanager
        async def fake_stdio(params):
            call_count["stdio"] += 1
            yield (MagicMock(), MagicMock())

        mock_stdio.side_effect = fake_stdio
        mock_session_cls.return_value = self._make_mock_session(["tool_a"])

        manager = MCPClientManager(
            {
                "immediate": {"command": "cmd1"},
                "deferred": {"command": "cmd2", "defer_loading": True},
            }
        )
        try:
            manager.start()
            assert "immediate" in manager._sessions
            assert "deferred" not in manager._sessions
            assert "deferred" in manager._deferred

            tools = manager.get_tools()
            assert len(tools) == 2
        finally:
            manager.stop()

    @patch("ai_guardian.integrations.mcp_client.stdio_client")
    @patch("ai_guardian.integrations.mcp_client.ClientSession")
    def test_deferred_server_stays_connected(self, mock_session_cls, mock_stdio):
        from contextlib import asynccontextmanager

        call_result = MagicMock()
        call_result.is_error = False
        text_block = MagicMock()
        text_block.text = "ok"
        call_result.content = [text_block]
        call_result.structured_content = None

        mock_session = self._make_mock_session(["t"])

        async def _call_tool(name, arguments):
            return call_result

        mock_session.call_tool = _call_tool
        mock_session_cls.return_value = mock_session

        @asynccontextmanager
        async def fake_stdio(params):
            yield (MagicMock(), MagicMock())

        mock_stdio.side_effect = fake_stdio

        manager = MCPClientManager({"srv": {"command": "cmd", "defer_loading": True}})
        try:
            manager.start()

            manager.call_tool("srv", "t", {"a": 1})
            assert "srv" in manager._sessions
            session_after_first = manager._sessions["srv"]

            manager.call_tool("srv", "t", {"a": 2})
            assert manager._sessions["srv"] is session_after_first
        finally:
            manager.stop()


@pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason="MCP requires Python >= 3.10",
)
class TestMCPClientManagerLifecycle:
    """Integration-style tests using mocked MCP transports."""

    @patch("ai_guardian.integrations.mcp_client.stdio_client")
    @patch("ai_guardian.integrations.mcp_client.ClientSession")
    def test_start_connects_stdio_server(self, mock_session_cls, mock_stdio):
        from contextlib import asynccontextmanager

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.input_schema = {"type": "object", "properties": {}}

        mock_tools_result = MagicMock()
        mock_tools_result.tools = [mock_tool]

        mock_session = MagicMock()

        async def _init():
            return None

        async def _list_tools():
            return mock_tools_result

        mock_session.initialize = _init
        mock_session.list_tools = _list_tools

        async def _aenter(self_):
            return mock_session

        async def _aexit(self_, *a):
            return None

        mock_session.__aenter__ = _aenter
        mock_session.__aexit__ = _aexit
        mock_session_cls.return_value = mock_session

        @asynccontextmanager
        async def fake_stdio(params):
            yield (MagicMock(), MagicMock())

        mock_stdio.side_effect = fake_stdio

        manager = MCPClientManager(
            {
                "test-server": {"command": "test-cmd", "args": ["--flag"]},
            }
        )
        try:
            manager.start()
            tools = manager.get_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "mcp__test-server__test_tool"
            assert "A test tool" in tools[0]["description"]
        finally:
            manager.stop()

    @patch("ai_guardian.integrations.mcp_client.sse_client")
    @patch("ai_guardian.integrations.mcp_client.ClientSession")
    def test_start_connects_sse_server(self, mock_session_cls, mock_sse):
        from contextlib import asynccontextmanager

        mock_tool = MagicMock()
        mock_tool.name = "remote_tool"
        mock_tool.description = "Remote"
        mock_tool.input_schema = {"type": "object", "properties": {}}

        mock_tools_result = MagicMock()
        mock_tools_result.tools = [mock_tool]

        mock_session = MagicMock()

        async def _init():
            return None

        async def _list_tools():
            return mock_tools_result

        mock_session.initialize = _init
        mock_session.list_tools = _list_tools

        async def _aenter(self_):
            return mock_session

        async def _aexit(self_, *a):
            return None

        mock_session.__aenter__ = _aenter
        mock_session.__aexit__ = _aexit
        mock_session_cls.return_value = mock_session

        @asynccontextmanager
        async def fake_sse(url, **kw):
            yield (MagicMock(), MagicMock())

        mock_sse.side_effect = fake_sse

        manager = MCPClientManager(
            {
                "remote": {"url": "https://mcp.example.com/sse"},
            }
        )
        try:
            manager.start()
            tools = manager.get_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "mcp__remote__remote_tool"
        finally:
            manager.stop()
