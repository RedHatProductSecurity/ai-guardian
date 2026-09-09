"""Augment Code hook adapter.

Augment Code uses the same response format as Claude Code but has
different tool names that need mapping to canonical names.
"""

from typing import ClassVar, Dict, List

from ai_guardian.constants import AUGMENT_TOOL_MAP
from ai_guardian.hook_adapters.base import NormalizedHookInput
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter

_AUGMENT_TOOL_MAP = AUGMENT_TOOL_MAP


class AugmentAdapter(BaseAgentAdapter):
    """Adapter for Augment Code.

    Detection: is_mcp_tool + tool_name fields in hook data.
    Uses Claude Code response format with tool name mapping.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["augment"]
    AGENT_TYPE: ClassVar[str] = "augment"

    @property
    def name(self) -> str:
        return "Augment Code"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return "is_mcp_tool" in hook_data and "tool_name" in hook_data

    def get_tool_name_map(self) -> Dict[str, str]:
        return _AUGMENT_TOOL_MAP

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        result = super().normalize_input(hook_data)
        if result.tool_name and result.tool_name in _AUGMENT_TOOL_MAP:
            result.tool_name = _AUGMENT_TOOL_MAP[result.tool_name]
        return result
