"""Dummy Agent hook adapter.

Reuses Claude Code (BaseAgentAdapter) response format.
The dummy agent is a simulated IDE — it fires hooks itself
rather than being called by an external IDE.
"""

from typing import ClassVar, Dict, List

from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter


class DummyAgentAdapter(BaseAgentAdapter):
    """Adapter for the built-in dummy agent (simulated IDE for testing).

    Detection: _ide_type == "dummy-agent" or dummy_agent field present.
    Same response format as Claude Code / BaseAgentAdapter.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["dummy-agent", "dummy_agent"]
    AGENT_TYPE: ClassVar[str] = "dummy_agent"

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.CLAUDE_CODE

    @property
    def name(self) -> str:
        return "Dummy Agent"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return "dummy_agent" in hook_data
