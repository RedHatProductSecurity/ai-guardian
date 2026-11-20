"""Kilo Code CLI hook adapter.

Kilo 7.8.x exposes the OpenCode V1 plugin callback payload and tool argument
shapes. Keep Kilo's identity marker and attribution separate while reusing the
verified native-input normalization and Claude-compatible hook response.
"""

from typing import ClassVar, Dict, List, Optional

from ai_guardian.hook_adapters.opencode import OpenCodeAdapter


class KiloAdapter(OpenCodeAdapter):
    """Adapter for Kilo Code's ``@kilocode/plugin`` hook bridge."""

    ENV_ALIASES: ClassVar[List[str]] = ["kilo"]
    AGENT_TYPE: ClassVar[str] = "kilo"

    @property
    def name(self) -> str:
        return "Kilo Code"

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.KILO

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return bool(
            hook_data.get("kilo_plugin_api") or hook_data.get("hook_source") == "kilo"
        )

    @staticmethod
    def _wrap_tool_output(tool_name: Optional[str], text: str) -> str:
        """Return Kilo's string-shaped ``tool.execute.after`` replacement."""
        return text
