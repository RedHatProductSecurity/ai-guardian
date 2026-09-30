"""OpenCode hook adapter.

OpenCode uses a JS/TS plugin architecture. The bridge plugin pipes
hook data as JSON to ai-guardian via stdin, using the same protocol
as Claude Code. Detection relies on opencode_version field or env var.
"""

from typing import ClassVar, Dict, List

from ai_guardian.constants import HookEvent, OPENCODE_TOOL_INPUT_MAP, OPENCODE_TOOL_MAP
from ai_guardian.hook_adapters.base import NormalizedHookInput
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

    def get_tool_name_map(self) -> Dict[str, str]:
        """Map OpenCode's native built-in tool names to canonical names."""
        return OPENCODE_TOOL_MAP

    @staticmethod
    def _normalize_tool_input(tool_input: Dict) -> Dict:
        """Add canonical aliases for OpenCode's camelCase tool arguments."""
        normalized = dict(tool_input)
        for native_key, canonical_key in OPENCODE_TOOL_INPUT_MAP.items():
            if canonical_key not in normalized and native_key in normalized:
                normalized[canonical_key] = normalized[native_key]
        return normalized

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        result = super().normalize_input(hook_data)
        event_name = (
            hook_data.get("hook_event_name") or hook_data.get("hookEventName") or ""
        ).lower()
        if event_name == "session.end":
            result.event = HookEvent.SESSION_END
        result.tool_input = self._normalize_tool_input(result.tool_input)
        if not result.file_path:
            result.file_path = result.tool_input.get(
                "file_path"
            ) or result.tool_input.get("path")
        return result
