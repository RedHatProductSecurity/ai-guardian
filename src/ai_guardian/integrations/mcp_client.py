"""MCP client lifecycle management for GuardedAgent.

Manages MCP server connections (stdio and SSE transports), tool
discovery, and tool execution.  Bridges the async MCP client library
to GuardedAgent's synchronous run loop via a dedicated background
event-loop thread.

Requires Python >= 3.10 and the ``mcp`` package (``pip install
ai-guardian[mcp]`` or ``pip install mcp>=2.0.0``).
"""

import asyncio
import json
import logging
import threading
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

MCP_TOOL_PREFIX = "mcp__"

try:
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def is_mcp_tool(tool_name: str) -> bool:
    """Return True if *tool_name* uses the MCP naming convention."""
    return tool_name.startswith(MCP_TOOL_PREFIX)


def parse_mcp_tool_name(tool_name: str) -> Optional[Tuple[str, str]]:
    """Extract ``(server_name, tool_name)`` from an MCP-prefixed name.

    Returns ``None`` if the name doesn't match the convention.
    """
    if not tool_name.startswith(MCP_TOOL_PREFIX):
        return None
    rest = tool_name[len(MCP_TOOL_PREFIX) :]
    parts = rest.split("__", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _mcp_tool_to_anthropic(server_name: str, tool: Any) -> Dict[str, Any]:
    """Convert an MCP ``Tool`` object to an Anthropic tool dict."""
    prefixed_name = f"{MCP_TOOL_PREFIX}{server_name}__{tool.name}"
    result: Dict[str, Any] = {
        "name": prefixed_name,
        "input_schema": (
            dict(tool.input_schema)
            if tool.input_schema
            else {"type": "object", "properties": {}}
        ),
    }
    desc_parts = []
    if tool.description:
        desc_parts.append(tool.description)
    desc_parts.append(f"(MCP server: {server_name})")
    result["description"] = " ".join(desc_parts)
    return result


def _call_tool_result_to_text(result: Any) -> str:
    """Extract text content from a ``CallToolResult``."""
    parts: List[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
            continue
        data = getattr(block, "data", None)
        if data:
            parts.append(f"[binary content: {getattr(block, 'mimeType', 'unknown')}]")
    if not parts:
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return json.dumps(structured, indent=2, default=str)
        return "(no output)"
    return "\n".join(parts)


class MCPClientManager:
    """Manages MCP server connections for a single GuardedAgent run.

    Starts a background thread with its own event loop to host the
    async MCP client sessions.  Provides sync methods for tool
    discovery and execution.
    """

    def __init__(self, servers_config: Dict[str, Dict[str, Any]]) -> None:
        self._config = servers_config
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._sessions: Dict[str, Any] = {}
        self._tools: Dict[str, List[Any]] = {}
        self._started = False

    def start(self) -> None:
        """Start background event loop and connect to all enabled servers."""
        if not HAS_MCP:
            raise RuntimeError(
                "MCP client requires Python >= 3.10 and the 'mcp' package. "
                "Install with: pip install mcp>=2.0.0"
            )
        if self._started:
            return

        enabled = {
            name: cfg for name, cfg in self._config.items() if cfg.get("enabled", True)
        }
        if not enabled:
            logger.info("No enabled MCP servers configured")
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_event_loop, daemon=True, name="mcp-client"
        )
        self._thread.start()

        max_startup = max(cfg.get("startup_timeout", 10) for cfg in enabled.values())
        total_timeout = max_startup * len(enabled) + 10

        future = asyncio.run_coroutine_threadsafe(
            self._connect_all(enabled), self._loop
        )
        try:
            future.result(timeout=total_timeout)
        except Exception:
            self.stop()
            raise

        self._started = True
        total_tools = sum(len(t) for t in self._tools.values())
        logger.info(
            "MCP servers started: %d server(s), %d tool(s)",
            len(self._sessions),
            total_tools,
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return discovered tools in Anthropic tool dict format."""
        result: List[Dict[str, Any]] = []
        for server_name, tools in self._tools.items():
            for tool in tools:
                result.append(_mcp_tool_to_anthropic(server_name, tool))
        return result

    def get_skip_scan_tools(self) -> Set[str]:
        """Return tool names that should skip security scanning.

        Based on per-server ``trust`` and ``scan_results`` settings.
        """
        skip: Set[str] = set()
        for server_name, cfg in self._config.items():
            trust = cfg.get("trust", "check")
            scan_results = cfg.get("scan_results", True)
            if trust == "trusted" or not scan_results:
                for tool in self._tools.get(server_name, []):
                    skip.add(f"{MCP_TOOL_PREFIX}{server_name}__{tool.name}")
        return skip

    def call_tool(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """Call a tool on an MCP server (sync wrapper).

        Returns the tool result as a text string.
        """
        if not self._started or server_name not in self._sessions:
            return f"Error: MCP server '{server_name}' is not connected"

        timeout = self._config.get(server_name, {}).get("timeout", 30)
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(server_name, tool_name, arguments),
            self._loop,
        )
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            return f"Error: MCP tool call timed out after {timeout}s"
        except Exception as exc:
            return f"Error calling MCP tool: {exc}"

    def stop(self) -> None:
        """Close all connections and shut down the background event loop."""
        if self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._disconnect_all(), self._loop
                )
                future.result(timeout=10)
            except Exception:
                logger.debug("Error during MCP disconnect", exc_info=True)

            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        if self._loop and not self._loop.is_closed():
            self._loop.close()

        self._sessions.clear()
        self._tools.clear()
        self._started = False
        self._loop = None
        self._thread = None

    def _run_event_loop(self) -> None:
        """Background thread target — runs the event loop until stopped."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect_all(self, servers: Dict[str, Dict[str, Any]]) -> None:
        """Connect to all configured MCP servers."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for name, cfg in servers.items():
            try:
                await self._connect_one(name, cfg)
            except Exception as exc:
                logger.error("Failed to connect to MCP server '%s': %s", name, exc)

    async def _connect_one(self, name: str, cfg: Dict[str, Any]) -> None:
        """Connect to a single MCP server."""
        startup_timeout = cfg.get("startup_timeout", 10)

        if "command" in cfg:
            params = StdioServerParameters(
                command=cfg["command"],
                args=cfg.get("args", []),
                env=cfg.get("env"),
            )
            transport_cm = stdio_client(params)
        elif "url" in cfg:
            transport_cm = sse_client(
                cfg["url"],
                headers=cfg.get("headers"),
                timeout=float(startup_timeout),
            )
        else:
            logger.warning("MCP server '%s': no 'command' or 'url' — skipping", name)
            return

        read_stream, write_stream = await self._exit_stack.enter_async_context(
            transport_cm
        )

        session = ClientSession(read_stream, write_stream)
        await self._exit_stack.enter_async_context(session)

        await asyncio.wait_for(session.initialize(), timeout=startup_timeout)

        tools_result = await asyncio.wait_for(
            session.list_tools(), timeout=startup_timeout
        )

        self._sessions[name] = session
        self._tools[name] = list(tools_result.tools)
        logger.info(
            "MCP server '%s' connected: %d tool(s)",
            name,
            len(tools_result.tools),
        )

    async def _call_tool_async(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """Async implementation of tool calling."""
        session = self._sessions[server_name]
        result = await session.call_tool(tool_name, arguments=arguments)
        if result.is_error:
            text = _call_tool_result_to_text(result)
            return f"Error: {text}"
        return _call_tool_result_to_text(result)

    async def _disconnect_all(self) -> None:
        """Close all MCP sessions and transports."""
        if hasattr(self, "_exit_stack"):
            try:
                await self._exit_stack.aclose()
            except Exception:
                logger.debug("Error closing MCP exit stack", exc_info=True)
