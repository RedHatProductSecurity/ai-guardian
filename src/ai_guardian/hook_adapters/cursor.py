"""Cursor IDE hook adapter.

Cursor uses camelCase event names (beforeSubmitPrompt, preToolUse, etc.)
and JSON responses with decision/permission/continue fields.
"""

import json
import logging
from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import CURSOR_HOOK_EVENTS, HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput

logger = logging.getLogger(__name__)


class CursorAdapter(HookAdapter):
    """Adapter for Cursor IDE.

    Detection: cursor_version field, hook_name field, or camelCase
    hook_event_name values (beforeSubmitPrompt, preToolUse).
    """

    ENV_ALIASES: ClassVar[List[str]] = ["cursor"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.CURSOR

    @property
    def name(self) -> str:
        return "Cursor IDE"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if "cursor_version" in hook_data:
            return True
        if "hook_name" in hook_data:
            return True
        event = hook_data.get("hook_event_name", "")
        return event in CURSOR_HOOK_EVENTS

    @staticmethod
    def _extract_tool_name(hook_data: Dict) -> Optional[str]:
        """Extract tool name, synthesizing from Cursor event type if needed."""
        name = HookAdapter._extract_tool_name(hook_data)
        if name:
            return name
        event = hook_data.get("hook_event_name", "").lower()
        hook_name = hook_data.get("hook_name", "").lower()
        effective = event or hook_name
        if effective == "beforereadfile":
            return "Read"
        if effective in ("beforeshellexecution", "aftershellexecution"):
            return "Bash"
        return None

    def _extract_tool_input(self, hook_data: Dict) -> Dict:
        result = super()._extract_tool_input(hook_data)
        if not result:
            command = hook_data.get("command")
            if isinstance(command, str) and command:
                return {"command": command}
        return result

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event_name = hook_data.get("hook_event_name", "").lower()
        hook_name = hook_data.get("hook_name", "").lower()

        effective = event_name or hook_name

        if effective == "beforesubmitprompt":
            event = HookEvent.PROMPT
        elif effective == "beforereadfile":
            event = HookEvent.BEFORE_READ_FILE
        elif effective in ("pretooluse", "beforeshellexecution"):
            event = HookEvent.PRE_TOOL_USE
        elif effective in ("posttooluse", "aftershellexecution"):
            event = HookEvent.POST_TOOL_USE
        else:
            event = HookEvent.PROMPT

        return NormalizedHookInput(
            event=event,
            tool_name=self._extract_tool_name(hook_data),
            tool_input=self._extract_tool_input(hook_data),
            file_path=(
                hook_data.get("file_path")
                or self._extract_file_path_from_tool_input(hook_data)
            ),
            working_dir=hook_data.get("cwd"),
            session_id=hook_data.get("conversation_id") or hook_data.get("session_id"),
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
        if hook_event == HookEvent.PRE_TOOL_USE:
            response = {"permission": "deny" if has_secrets else "allow"}
            if has_secrets:
                final_error = self._combine_error_messages(
                    error_message, warning_message
                )
                if final_error:
                    response["user_message"] = final_error
                response["agent_message"] = self._sanitize_block_reason(violation_type)
            else:
                agent_ctx = self._build_warn_agent_context(
                    warning_message, security_message, violation_type
                )
                if agent_ctx:
                    response["agent_message"] = agent_ctx
                if warning_message:
                    response["user_message"] = warning_message
        else:
            response = {"continue": not has_secrets}
            if has_secrets:
                final_error = self._combine_error_messages(
                    error_message, warning_message
                )
                if final_error:
                    response["user_message"] = final_error
                if redacted_output:
                    response["agent_message"] = redacted_output
            else:
                agent_ctx = self._build_warn_agent_context(
                    warning_message, security_message, violation_type
                )
                if agent_ctx:
                    response["agent_message"] = agent_ctx
                if warning_message:
                    response["user_message"] = warning_message
                if (
                    hook_event == HookEvent.POST_TOOL_USE
                    and modified_output is not None
                ):
                    logger.warning(
                        "%s: modified_output provided but output replacement "
                        "may not be supported — redacted content sent as best-effort",
                        self.name,
                    )
                    response["modifiedToolOutput"] = modified_output

        return self._add_metadata(
            {"output": json.dumps(response), "exit_code": 0},
            has_secrets,
            violation_type,
        )
