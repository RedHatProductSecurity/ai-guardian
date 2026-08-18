"""GitHub Copilot hook adapter.

Copilot uses camelCase event/field names. PreToolUse returns JSON with
permissionDecision; other events use exit code 2 for blocking.

Copilot CLI stores JSONL transcripts at:
    ~/.copilot/session-state/events.jsonl
"""

import json
import logging
import os
from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput

logger = logging.getLogger(__name__)


class CopilotAdapter(HookAdapter):
    """Adapter for GitHub Copilot.

    Detection: toolName field, or timestamp+cwd pattern.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["github_copilot", "copilot"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.GITHUB_COPILOT

    @property
    def name(self) -> str:
        return "GitHub Copilot"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if "toolName" in hook_data:
            return True
        if "timestamp" in hook_data and "cwd" in hook_data:
            event = hook_data.get("hook_event_name", "")
            if event in ("userPromptSubmitted", "preToolUse", "postToolUse"):
                return True
        return False

    # Default transcript location for Copilot CLI
    TRANSCRIPT_PATH = os.path.expanduser("~/.copilot/session-state/events.jsonl")

    def get_default_transcript_paths(self) -> List[str]:
        """Return Copilot CLI transcript path if it exists."""
        if os.path.isfile(self.TRANSCRIPT_PATH):
            return [self.TRANSCRIPT_PATH]
        return []

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event_name = hook_data.get("hook_event_name", "").lower()

        if event_name in ("userpromptsubmitted",):
            event = HookEvent.PROMPT
        elif event_name in ("pretooluse",):
            event = HookEvent.PRE_TOOL_USE
        elif event_name in ("posttooluse",):
            event = HookEvent.POST_TOOL_USE
        elif "toolName" in hook_data:
            event = HookEvent.PRE_TOOL_USE
        else:
            event = HookEvent.PROMPT

        # Copilot uses toolName + toolArgs (JSON string)
        tool_name = hook_data.get("toolName") or hook_data.get("tool_name")
        tool_input = {}
        tool_args_str = hook_data.get("toolArgs")
        if tool_args_str and isinstance(tool_args_str, str):
            try:
                tool_input = json.loads(tool_args_str)
            except json.JSONDecodeError:
                pass  # intentionally silent — best-effort operation
        if not tool_input:
            tool_input = self._extract_tool_input(hook_data)

        file_path = tool_input.get("file_path") or tool_input.get("path")
        if not file_path:
            file_path = self._extract_file_path_from_tool_input(hook_data)

        return NormalizedHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=tool_input,
            file_path=file_path,
            working_dir=hook_data.get("cwd"),
            session_id=hook_data.get("sessionId") or hook_data.get("session_id"),
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
            response = {}
            if has_secrets:
                response["permissionDecision"] = "deny"
                final_error = self._combine_error_messages(
                    error_message, warning_message
                )
                if final_error:
                    response["permissionDecisionReason"] = final_error
                response["additionalContext"] = self._sanitize_block_reason(
                    violation_type
                )
            else:
                agent_ctx = self._build_warn_agent_context(
                    warning_message, security_message, violation_type
                )
                if agent_ctx:
                    response["additionalContext"] = agent_ctx
            return self._add_metadata(
                {"output": json.dumps(response), "exit_code": 0},
                has_secrets,
                violation_type,
            )
        else:
            if has_secrets and error_message:
                output = (
                    json.dumps({"additionalContext": redacted_output})
                    if redacted_output
                    else None
                )
                return self._stderr_block_response(
                    error_message,
                    warning_message,
                    output,
                    2,
                    has_secrets,
                    violation_type,
                )
            response = {}
            agent_ctx = self._build_warn_agent_context(
                warning_message, security_message, violation_type
            )
            if agent_ctx:
                response["additionalContext"] = agent_ctx
            if hook_event == HookEvent.POST_TOOL_USE and modified_output is not None:
                logger.warning(
                    "%s: modified_output provided but output replacement "
                    "may not be supported — redacted content sent as best-effort",
                    self.name,
                )
                response["modifiedResult"] = modified_output
            output = json.dumps(response) if response else None
            return self._add_metadata(
                {"output": output, "exit_code": 0},
                has_secrets,
                violation_type,
            )
