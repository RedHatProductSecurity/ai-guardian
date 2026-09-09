"""Charmbracelet Crush hook adapter.

Crush uses Claude Code's response format (hookSpecificOutput with
permissionDecision). Detection relies on CRUSH=1 env var or
Crush-specific field combination in hook data.
"""

import os
from typing import ClassVar, Dict, List

from ai_guardian.constants import ALL_HOOK_EVENT_DISPLAY_NAMES
from ai_guardian.hook_adapters.base import NormalizedHookInput
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter


class CrushAdapter(BaseAgentAdapter):
    """Adapter for Charmbracelet Crush.

    Crush natively accepts Claude Code's JSON response structure.
    Only PreToolUse is currently implemented by Crush; other events
    are proposed but not yet available.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["crush"]
    AGENT_TYPE: ClassVar[str] = "crush"

    @property
    def name(self) -> str:
        return "Crush"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if os.environ.get("CRUSH") == "1":
            return True
        if os.environ.get("AI_AGENT", "").lower() == "crush":
            return True
        event = hook_data.get("event")
        if (
            isinstance(event, str)
            and event in ALL_HOOK_EVENT_DISPLAY_NAMES
            and "tool_input" in hook_data
            and "hook_event_name" not in hook_data
        ):
            return True
        return False

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        if "event" in hook_data and "hook_event_name" not in hook_data:
            hook_data = dict(hook_data)
            hook_data["hook_event_name"] = hook_data["event"]
        return super().normalize_input(hook_data)
