"""Pi hook adapter.

Pi extensions delegate hook payloads to ai-guardian using the shared
PascalCase response protocol.  This adapter keeps Pi attribution distinct
while reusing the established normalization and response boundary.
"""

from typing import ClassVar, Dict, List

from ai_guardian.response_format import IDEType
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter


class PiAdapter(BaseAgentAdapter):
    """Adapter for Pi's TypeScript extension lifecycle."""

    ENV_ALIASES: ClassVar[List[str]] = ["pi"]
    AGENT_TYPE: ClassVar[str] = "pi"

    @property
    def name(self) -> str:
        return "Pi"

    @property
    def ide_type(self):
        return IDEType.PI

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if hook_data.get("pi_version"):
            return True
        return hook_data.get("hook_source") == "pi"
