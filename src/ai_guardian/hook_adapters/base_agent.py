"""Base agent adapter (default response format).

Uses PascalCase event names (UserPromptSubmit, PreToolUse, PostToolUse)
and JSON responses on stdout. Exit code is always 0; blocking is
communicated via hookSpecificOutput.permissionDecision.

Serves as the shared base for Claude Code, Codex, Windsurf, Augment,
and OpenCode adapters.
"""

import json
import logging
from typing import ClassVar, Dict, List, Optional

logger = logging.getLogger(__name__)

from ai_guardian.constants import ALL_HOOK_EVENT_DISPLAY_NAMES, HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput

_BLOCK_USES_PERMISSION_DECISION = {HookEvent.PRE_TOOL_USE, HookEvent.BEFORE_READ_FILE}

# SESSION_START omits 'reason' — Claude Code UI shows both reason and
# systemMessage for this event, causing duplicate display.
_BLOCK_OMITS_REASON = {HookEvent.SESSION_START}


class BaseAgentAdapter(HookAdapter):
    """Default adapter and shared base for agents using PascalCase events.

    Detection: hook_event_name in {UserPromptSubmit, PreToolUse, PostToolUse}
    or fallback (default adapter). Also the concrete adapter for Claude Code.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["claude"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.CLAUDE_CODE

    @property
    def name(self) -> str:
        return "Claude Code"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        event = hook_data.get("hook_event_name") or hook_data.get("hookEventName", "")
        return event in ALL_HOOK_EVENT_DISPLAY_NAMES

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event = self._detect_event_from_all_formats(hook_data)

        tool_name = self._extract_tool_name(hook_data)
        tool_name_map = self.get_tool_name_map()
        if tool_name and tool_name in tool_name_map:
            tool_name = tool_name_map[tool_name]

        return NormalizedHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=self._extract_tool_input(hook_data),
            file_path=self._extract_file_path_from_tool_input(hook_data),
            working_dir=hook_data.get("cwd"),
            session_id=hook_data.get("session_id"),
            tool_use_id=hook_data.get("tool_use_id"),
            prompt_text=self._extract_prompt_text(hook_data),
            tool_response=hook_data.get("tool_response"),
            transcript_path=self._extract_transcript_path(hook_data),
            raw_data=hook_data,
        )

    # -- Shared response builders --

    @staticmethod
    def _wrap_tool_output(tool_name: Optional[str], text: str):
        """Wrap modified output in the tool-specific shape for updatedToolOutput.

        Bash requires object form {stdout, stderr, interrupted}.
        Other tools use bare string.
        """
        if tool_name == "Bash":
            return {"stdout": text, "stderr": "", "interrupted": False}
        return text

    @staticmethod
    def _event_name(hook_event: HookEvent) -> str:
        if isinstance(hook_event, HookEvent):
            return hook_event.display_name
        try:
            return HookEvent(hook_event).display_name
        except ValueError:
            return str(hook_event)

    def _block_response(
        self,
        hook_event: HookEvent,
        error_message: str,
        violation_type: Optional[str] = None,
        redacted_output: Optional[str] = None,
    ) -> Dict:
        sanitized = self._sanitize_block_reason(violation_type)
        context = redacted_output if redacted_output is not None else sanitized
        sys_msg = error_message
        if redacted_output is not None:
            sys_msg = f"{error_message}\n\nRedacted output provided in context."
        response: Dict = {
            "systemMessage": sys_msg,
            "hookSpecificOutput": {
                "hookEventName": self._event_name(hook_event),
                "additionalContext": context,
            },
        }
        if hook_event in _BLOCK_USES_PERMISSION_DECISION:
            response["hookSpecificOutput"]["permissionDecision"] = "deny"
        else:
            response["decision"] = "block"
            if hook_event not in _BLOCK_OMITS_REASON:
                response["reason"] = sanitized
        return response

    def _warn_response(
        self,
        hook_event: HookEvent,
        warning_message: Optional[str] = None,
        security_message: Optional[str] = None,
        violation_type: Optional[str] = None,
    ) -> Dict:
        user_msg = "\n\n".join(filter(None, [security_message, warning_message]))
        if not user_msg:
            return {}
        agent_ctx = self._build_warn_agent_context(
            warning_message, security_message, violation_type
        )
        return {
            "systemMessage": user_msg,
            "hookSpecificOutput": {
                "hookEventName": self._event_name(hook_event),
                "additionalContext": agent_ctx or user_msg,
            },
        }

    def _allow_response(
        self,
        hook_event: HookEvent,
        security_message: Optional[str] = None,
    ) -> Dict:
        if not security_message:
            return {}
        return {
            "systemMessage": security_message,
            "hookSpecificOutput": {
                "hookEventName": self._event_name(hook_event),
                "additionalContext": security_message,
            },
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
        if has_secrets and error_message:
            final_error = self._combine_error_messages(error_message, warning_message)
            response = self._block_response(
                hook_event, final_error, violation_type, redacted_output
            )
        elif hook_event == HookEvent.POST_TOOL_USE:
            if has_secrets:
                final_error = self._combine_error_messages(
                    error_message, warning_message
                )
                response = self._block_response(
                    hook_event,
                    final_error or "Secrets detected in tool output",
                    violation_type,
                    redacted_output,
                )
            else:
                response = (
                    self._warn_response(
                        hook_event,
                        warning_message,
                        violation_type=violation_type,
                    )
                    if warning_message
                    else {}
                )
                if modified_output is not None:
                    if "hookSpecificOutput" not in response:
                        response["hookSpecificOutput"] = {
                            "hookEventName": self._event_name(hook_event)
                        }
                    wrapped = self._wrap_tool_output(tool_name, modified_output)
                    response["hookSpecificOutput"]["updatedToolOutput"] = wrapped
                    response["hookSpecificOutput"][
                        "updatedMCPToolOutput"
                    ] = modified_output
        elif warning_message:
            response = self._warn_response(
                hook_event,
                warning_message,
                security_message,
                violation_type=violation_type,
            )
        else:
            response = self._allow_response(hook_event, security_message)

        return self._add_metadata(
            {"output": json.dumps(response), "exit_code": 0},
            has_secrets,
            violation_type,
        )
