"""Placeholder adapter for regular ChatGPT desktop mode.

Regular ChatGPT mode has no AI Guardian hook surface. Its desktop-only local
plugin exposes the MCP advisor, which ChatGPT calls only when the user invokes
it. This adapter exists to give the MCP-only integration a distinct identity;
it never matches hook input.
"""

from typing import ClassVar, List

from ai_guardian.hook_adapters.junie import JunieAdapter


class ChatGPTAdapter(JunieAdapter):
    """Known-agent placeholder for regular ChatGPT desktop mode."""

    ENV_ALIASES: ClassVar[List[str]] = ["chatgpt"]
    AGENT_TYPE: ClassVar[str] = "chatgpt"

    @property
    def name(self) -> str:
        return "ChatGPT desktop (regular mode)"
