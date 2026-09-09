"""OpenCode hook adapter.

OpenCode uses a JS/TS plugin architecture. The bridge plugin pipes
hook data as JSON to ai-guardian via stdin, using the same protocol
as Claude Code. Detection relies on opencode_version field or env var.
"""

from typing import ClassVar, Dict, List

from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter


class OpenCodeAdapter(BaseAgentAdapter):
    """Adapter for OpenCode.

    OpenCode shares Claude Code's JSON response structure via the bridge
    plugin. Detection uses opencode_version field or env var override.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["opencode"]
    AGENT_TYPE: ClassVar[str] = "opencode"

    @property
    def name(self) -> str:
        return "OpenCode"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if hook_data.get("opencode_version"):
            return True
        if hook_data.get("hook_source") == "opencode":
            return True
        return False
