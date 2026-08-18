"""Windsurf hook adapter.

Windsurf uses snake_case agent_action_name field instead of
hook_event_name. Windsurf communicates via exit codes and streams:
exit 2 blocks (stderr reaches the agent), exit 0 allows.
"""

import logging
from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters.base import NormalizedHookInput
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter

logger = logging.getLogger(__name__)

_ACTION_MAP = {
    "pre_user_prompt": HookEvent.PROMPT,
    "pre_read_code": HookEvent.BEFORE_READ_FILE,
    "pre_run_command": HookEvent.PRE_TOOL_USE,
    "pre_write_code": HookEvent.PRE_TOOL_USE,
    "pre_mcp_tool_use": HookEvent.PRE_TOOL_USE,
    "post_run_command": HookEvent.POST_TOOL_USE,
    "post_read_code": HookEvent.POST_TOOL_USE,
    "post_write_code": HookEvent.POST_TOOL_USE,
    "post_mcp_tool_use": HookEvent.POST_TOOL_USE,
}


class WindsurfAdapter(BaseAgentAdapter):
    """Adapter for Windsurf (Codeium).

    Detection: agent_action_name field in hook data.
    Windsurf uses exit codes + streams: exit 2 blocks (stderr reaches
    the Cascade agent), exit 0 allows. No structured JSON response.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["windsurf"]

    @property
    def name(self) -> str:
        return "Windsurf"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return "agent_action_name" in hook_data

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        action = hook_data.get("agent_action_name", "").lower()
        event = _ACTION_MAP.get(action, HookEvent.PROMPT)

        tool_info = hook_data.get("tool_info", {})
        tool_name = self._extract_tool_name(hook_data) or (
            tool_info.get("name") if isinstance(tool_info, dict) else None
        )
        tool_input = self._extract_tool_input(hook_data)
        if not tool_input and isinstance(tool_info, dict):
            tool_input = tool_info

        return NormalizedHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=tool_input,
            file_path=self._extract_file_path_from_tool_input(hook_data),
            working_dir=hook_data.get("cwd"),
            session_id=hook_data.get("trajectory_id") or hook_data.get("session_id"),
            tool_use_id=hook_data.get("tool_use_id"),
            prompt_text=self._extract_prompt_text(hook_data),
            tool_response=hook_data.get("tool_response"),
            transcript_path=self._extract_transcript_path(hook_data),
            raw_data=hook_data,
        )

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
        if has_secrets and error_message:
            return self._stderr_block_response(
                error_message,
                warning_message,
                redacted_output,
                2,
                has_secrets,
                violation_type,
            )

        parts = []
        if hook_event == HookEvent.PROMPT and security_message:
            parts.append(security_message)
        if warning_message:
            if violation_type:
                parts.append(self._sanitize_warn_reason(violation_type))
            else:
                parts.append(warning_message)
        if hook_event == HookEvent.POST_TOOL_USE and modified_output is not None:
            logger.warning(
                "%s: output replacement via stdout (no structured field)",
                self.name,
            )
            parts.append(modified_output)
        output = "\n\n".join(parts) if parts else None

        return self._add_metadata(
            {"output": output, "exit_code": 0},
            has_secrets,
            violation_type,
        )
