"""xAI Grok Build hook adapter.

Grok uses Claude-compatible lifecycle event names with camelCase payload fields.
Its only blocking hook is ``PreToolUse``; passive hook stdout is ignored.
"""

import json
import logging
from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import ALL_HOOK_EVENT_DISPLAY_NAMES, HookEvent
from ai_guardian.hook_adapters.base import NormalizedHookInput
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter

logger = logging.getLogger(__name__)


class GrokAdapter(BaseAgentAdapter):
    """Adapter for the xAI Grok Build CLI."""

    ENV_ALIASES: ClassVar[List[str]] = ["grok"]
    AGENT_TYPE: ClassVar[str] = "grok"

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.GROK

    @property
    def name(self) -> str:
        return "Grok Build"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        """Recognize Grok's named camelCase hook payloads.

        The distinctive fields avoid claiming generic ``hookEventName`` payloads
        that are already handled by another adapter.
        """
        event_name = hook_data.get("hookEventName")
        if event_name not in ALL_HOOK_EVENT_DISPLAY_NAMES:
            return False
        return any(
            key in hook_data
            for key in ("workspaceRoot", "toolName", "toolInput", "sessionId")
        )

    @staticmethod
    def _parse_tool_input(value) -> Dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _file_path(tool_input: Dict) -> Optional[str]:
        for key in ("file_path", "filePath", "path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event = self._detect_event_from_all_formats(hook_data)
        tool_name = hook_data.get("toolName") or hook_data.get("tool_name")
        if not isinstance(tool_name, str):
            tool_name = None
        tool_input = self._parse_tool_input(hook_data.get("toolInput"))
        if not tool_input:
            tool_input = self._parse_tool_input(hook_data.get("tool_input"))
        tool_name_map = self.get_tool_name_map()
        if tool_name in tool_name_map:
            tool_name = tool_name_map[tool_name]

        tool_response = None
        for key in ("toolOutput", "toolResult", "toolResponse", "tool_response"):
            if key in hook_data:
                tool_response = hook_data[key]
                break

        prompt_text = self._extract_prompt_text(hook_data)
        if prompt_text is None and isinstance(hook_data.get("userPrompt"), str):
            prompt_text = hook_data["userPrompt"]

        return NormalizedHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=tool_input,
            file_path=self._file_path(tool_input),
            working_dir=hook_data.get("workspaceRoot") or hook_data.get("cwd"),
            session_id=hook_data.get("sessionId") or hook_data.get("session_id"),
            tool_use_id=hook_data.get("toolUseId") or hook_data.get("tool_use_id"),
            prompt_text=prompt_text,
            tool_response=tool_response,
            transcript_path=hook_data.get("transcriptPath")
            or self._extract_transcript_path(hook_data),
            raw_data=hook_data,
        )

    def get_tool_name_map(self) -> Dict[str, str]:
        return {
            "run_terminal_command": "Bash",
            "read_file": "Read",
            "search_replace": "Edit",
            "write_file": "Write",
            "list_directory": "LS",
            "search_files": "Grep",
        }

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
        """Return Grok's native PreToolUse decision response.

        Grok ignores stdout for passive events, so output transformations cannot
        be advertised or sent for PostToolUse.
        """
        if (
            hook_event in (HookEvent.PRE_TOOL_USE, HookEvent.BEFORE_READ_FILE)
            and has_secrets
        ):
            reason = self._combine_error_messages(error_message, warning_message)
            response = {
                "decision": "deny",
                "reason": reason or self._sanitize_block_reason(violation_type),
            }
            return self._add_metadata(
                {"output": json.dumps(response), "exit_code": 0},
                has_secrets,
                violation_type,
            )

        # A non-empty stdout value is not consumed for prompt, post-tool, or
        # lifecycle events. Keep the command quiet and allow the host to proceed.
        return self._add_metadata(
            {"output": None, "exit_code": 0},
            has_secrets,
            violation_type,
        )
