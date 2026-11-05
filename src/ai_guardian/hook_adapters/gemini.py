"""Google Gemini CLI hook adapter.

Gemini CLI uses PascalCase event names (BeforeAgent, BeforeTool, AfterTool)
and JSON responses with decision/systemMessage fields.
"""

import json
import logging
from typing import Any, ClassVar, Dict, List, Optional

from ai_guardian.constants import ALL_HOOK_EVENT_DISPLAY_NAMES, HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput

logger = logging.getLogger(__name__)


class GeminiCLIAdapter(HookAdapter):
    """Adapter for Google Gemini CLI.

    Detection: transcript_path field in hook data.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["gemini"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.GEMINI_CLI

    @property
    def name(self) -> str:
        return "Google Gemini CLI"

    def get_tool_name_map(self) -> Dict[str, str]:
        """Map Gemini's native shell command tool to the canonical Bash tool."""
        return {"run_shell_command": "Bash"}

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if "transcript_path" not in hook_data:
            return False
        # Claude Code also sends transcript_path — distinguish by event names.
        # Gemini uses BeforeTool/AfterTool/BeforeAgent; Claude uses PascalCase
        # UserPromptSubmit/PreToolUse/PostToolUse.
        event = hook_data.get("hook_event_name", "")
        if event in ALL_HOOK_EVENT_DISPLAY_NAMES:
            return False
        return True

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event_name = hook_data.get("hook_event_name", "").lower()

        if event_name in ("beforetool",):
            event = HookEvent.PRE_TOOL_USE
        elif event_name in ("aftertool",):
            event = HookEvent.POST_TOOL_USE
        elif event_name == "sessionstart":
            event = HookEvent.SESSION_START
        elif event_name == "beforeagent":
            event = HookEvent.PROMPT
        else:
            event = HookEvent.PROMPT

        tool_name = self._extract_tool_name(hook_data)
        tool_name_map = self.get_tool_name_map()
        if tool_name in tool_name_map:
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
            transcript_path=hook_data.get("transcript_path"),
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
        response: Dict[str, Any]
        if hook_event == HookEvent.POST_TOOL_USE and modified_output is not None:
            # Gemini does not consume updatedToolOutput. A best-effort field or
            # additionalContext leaves the original result visible to the model.
            # Its native AfterTool denial replaces both model and display output.
            reason = (
                "AI Guardian blocked this tool result because Gemini CLI does not "
                "support safe output replacement."
            )
            logger.info(
                "Gemini tool result denied: safe output replacement unsupported"
            )
            response = {"decision": "deny", "reason": reason}
            has_secrets = True
        elif has_secrets and error_message:
            final_error = self._combine_error_messages(error_message, warning_message)
            response = {
                "decision": "deny",
                "reason": final_error,
                "additionalContext": redacted_output
                or self._sanitize_block_reason(violation_type),
            }
        else:
            response = {}
            parts = []
            if hook_event == HookEvent.PROMPT and security_message:
                parts.append(security_message)
            if warning_message:
                parts.append(warning_message)
            if parts:
                combined = "\n\n".join(parts)
                response["systemMessage"] = combined
                if hook_event != HookEvent.PRE_TOOL_USE:
                    sec = security_message if hook_event == HookEvent.PROMPT else None
                    agent_ctx = self._build_warn_agent_context(
                        warning_message, sec, violation_type
                    )
                    response["hookSpecificOutput"] = {
                        "additionalContext": agent_ctx or combined
                    }
        return self._add_metadata(
            {"output": json.dumps(response), "exit_code": 0},
            has_secrets,
            violation_type,
        )
