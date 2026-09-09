"""Cursor IDE hook adapter.

Cursor exposes both command-hook events and observation-only lifecycle events.
This adapter keeps the event mapping explicit so a newly added Cursor event is
never accidentally treated as a prompt or tool decision.
"""

import json
import logging
from typing import Any, ClassVar, Dict, List, Optional

from ai_guardian.constants import CURSOR_RECOGNIZED_HOOK_EVENTS, HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput

logger = logging.getLogger(__name__)


class CursorAdapter(HookAdapter):
    """Adapter for Cursor IDE.

    Detection: cursor_version field, hook_name field, or camelCase
    hook_event_name values (beforeSubmitPrompt, preToolUse).
    """

    ENV_ALIASES: ClassVar[List[str]] = ["cursor"]

    _EVENT_MAP: ClassVar[Dict[str, HookEvent]] = {
        "beforesubmitprompt": HookEvent.PROMPT,
        "beforereadfile": HookEvent.BEFORE_READ_FILE,
        "beforetabfileread": HookEvent.BEFORE_READ_FILE,
        "pretooluse": HookEvent.PRE_TOOL_USE,
        "beforeshellexecution": HookEvent.PRE_TOOL_USE,
        "beforemcpexecution": HookEvent.PRE_TOOL_USE,
        "subagentstart": HookEvent.SUBAGENT_START,
        "posttooluse": HookEvent.POST_TOOL_USE,
        "aftershellexecution": HookEvent.POST_TOOL_USE,
        "aftermcpexecution": HookEvent.POST_TOOL_USE,
        "posttoolusefailure": HookEvent.POST_TOOL_USE_FAILURE,
        "sessionstart": HookEvent.SESSION_START,
        "sessionend": HookEvent.SESSION_END,
        "subagentstop": HookEvent.SUBAGENT_STOP,
        "precompact": HookEvent.PRE_COMPACT,
        "stop": HookEvent.STOP,
        "afteragentresponse": HookEvent.AFTER_AGENT_RESPONSE,
        "afteragentthought": HookEvent.AFTER_AGENT_THOUGHT,
        "afterfileedit": HookEvent.AFTER_FILE_EDIT,
        "aftertabfileedit": HookEvent.AFTER_TAB_FILE_EDIT,
        "workspaceopen": HookEvent.WORKSPACE_OPEN,
    }

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
        hook_name = hook_data.get("hook_name", "")
        if hook_name:
            return hook_name in CURSOR_RECOGNIZED_HOOK_EVENTS
        event = hook_data.get("hook_event_name", "")
        # Keep Cursor's camelCase spelling distinct from Claude/Codex's
        # PascalCase events (for example, preToolUse vs PreToolUse).
        return event in CURSOR_RECOGNIZED_HOOK_EVENTS

    @classmethod
    def _event_name(cls, hook_data: Dict) -> str:
        """Return the Cursor event name in a case-insensitive form."""
        return str(
            hook_data.get("hook_event_name") or hook_data.get("hook_name") or ""
        ).lower()

    @classmethod
    def event_for_hook(cls, hook_data: Dict) -> HookEvent:
        """Map a Cursor event to the shared event model."""
        return cls._EVENT_MAP.get(cls._event_name(hook_data), HookEvent.PROMPT)

    @classmethod
    def is_mcp_event(cls, hook_data: Dict) -> bool:
        """Return whether a payload belongs to Cursor's MCP hook pair."""
        return cls._event_name(hook_data) in {
            "beforemcpexecution",
            "aftermcpexecution",
        }

    @staticmethod
    def _extract_tool_name(hook_data: Dict) -> Optional[str]:
        """Extract tool name, synthesizing from Cursor event type if needed."""
        name = HookAdapter._extract_tool_name(hook_data)
        event = CursorAdapter._event_name(hook_data)
        if event in ("beforemcpexecution", "aftermcpexecution"):
            server = hook_data.get("mcp_server_name") or hook_data.get("mcpServerName")
            if name and server and not str(name).startswith("mcp__"):
                return f"mcp__{server}__{name}"
            if name:
                return name
        if name:
            return name
        if event in ("beforereadfile", "beforetabfileread"):
            return "Read"
        if event in ("beforeshellexecution", "aftershellexecution"):
            return "Bash"
        if event == "subagentstart":
            return "Task"
        return None

    def _extract_tool_input(self, hook_data: Dict) -> Dict:
        result = super()._extract_tool_input(hook_data)
        if isinstance(hook_data.get("tool_input"), str):
            try:
                decoded = json.loads(hook_data["tool_input"])
            except (TypeError, json.JSONDecodeError):
                decoded = None
            if isinstance(decoded, dict):
                result = decoded
        if not result:
            command = hook_data.get("command")
            if isinstance(command, str) and command:
                result = {"command": command}
        if self._event_name(hook_data) == "subagentstart":
            result = {
                key: hook_data[key]
                for key in ("subagent_id", "subagent_type", "task")
                if key in hook_data
            }
        # Cursor's file-read hooks place the content at the event root rather
        # than inside tool_input.  Preserve it for the shared file scanner.
        if hook_data.get("file_path") and any(
            key in hook_data for key in ("content", "attachments")
        ):
            result = {
                **result,
                "file_path": hook_data.get("file_path"),
            }
            if "content" in hook_data:
                result["content"] = hook_data.get("content")
        return result

    @staticmethod
    def _extract_tool_response(hook_data: Dict) -> Any:
        """Return Cursor's post-tool result without logging or altering it."""
        for key in ("tool_response", "tool_output", "result_json", "output"):
            if key in hook_data:
                return hook_data.get(key)
        return None

    @staticmethod
    def _is_mcp_tool(tool_name: Optional[str]) -> bool:
        return bool(tool_name and str(tool_name).startswith("mcp__"))

    @staticmethod
    def _post_output_payload(modified_output: str) -> Dict[str, str]:
        """Build the documented Cursor MCP replacement shape."""
        return {"modified": modified_output}

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event = self.event_for_hook(hook_data)

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
            tool_response=self._extract_tool_response(hook_data),
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
        if hook_event in (
            HookEvent.PRE_TOOL_USE,
            HookEvent.BEFORE_READ_FILE,
            HookEvent.SUBAGENT_START,
        ):
            response = {"permission": "deny" if has_secrets else "allow"}
            # Cursor documents `permission` for tool/file pre-hooks.  Keep
            # `continue` for beforeReadFile compatibility with older Cursor
            # hook contracts already supported by AI Guardian.
            if hook_event == HookEvent.BEFORE_READ_FILE:
                response["continue"] = not has_secrets
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
        elif hook_event == HookEvent.POST_TOOL_USE_FAILURE:
            # Cursor provides no output channel for this event.  Acknowledge
            # it with an empty JSON object and never echo error_message.
            response = {}
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
                    response["additional_context"] = redacted_output
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
                    response["modifiedToolOutput"] = modified_output
                    # Current Cursor documents this snake_case field for MCP
                    # result replacement.  Keep the older camelCase field for
                    # desktop Cursor versions that already consume it.
                    if self._is_mcp_tool(tool_name):
                        response["updated_mcp_tool_output"] = self._post_output_payload(
                            modified_output
                        )

        return self._add_metadata(
            {"output": json.dumps(response), "exit_code": 0},
            has_secrets,
            violation_type,
        )
