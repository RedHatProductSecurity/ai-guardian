"""Junie (JetBrains) hook adapter.

Junie is MCP-only — it has no hook support. This placeholder adapter
exists so the registry can report Junie as a known agent type.
"""

from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput


class JunieAdapter(HookAdapter):
    """Placeholder adapter for Junie (JetBrains).

    Junie provides no hooks — AI Guardian integrates via MCP server only.
    This adapter never matches real hook input.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["junie"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.UNKNOWN

    @property
    def name(self) -> str:
        return "Junie"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return False

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        return NormalizedHookInput(event=HookEvent.PROMPT, raw_data=hook_data)

    def format_response(
        self,
        has_secrets: bool,
        error_message: Optional[str] = None,
        hook_event: HookEvent = HookEvent.PROMPT,
        warning_message: Optional[str] = None,
        modified_output: Optional[str] = None,
        violation_type: Optional[str] = None,
        security_message: Optional[str] = None,
        redacted_output: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> Dict:
        return self._add_metadata(
            {"output": None, "exit_code": 0},
            has_secrets,
            violation_type,
        )
