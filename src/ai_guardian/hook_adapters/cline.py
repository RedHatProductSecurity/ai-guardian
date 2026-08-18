"""Cline / ZooCode hook adapter.

Cline uses JSON responses with cancel/reason/message fields.
Detected by clineVersion field in hook data.
"""

import json
import logging
from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput

logger = logging.getLogger(__name__)


class ClineAdapter(HookAdapter):
    """Adapter for Cline (formerly ZooCode).

    Detection: clineVersion field in hook data.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["cline", "zoocode"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.CLINE

    @property
    def name(self) -> str:
        return "Cline"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return "clineVersion" in hook_data

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event_name = (
            hook_data.get("hook_event_name", "") or hook_data.get("hookName", "")
        ).lower()

        if event_name in ("userpromptsubmit",):
            event = HookEvent.PROMPT
        elif event_name in ("pretooluse",):
            event = HookEvent.PRE_TOOL_USE
        elif event_name in ("posttooluse",):
            event = HookEvent.POST_TOOL_USE
        else:
            if "tool_response" in hook_data:
                event = HookEvent.POST_TOOL_USE
            elif "tool_use" in hook_data or "tool_name" in hook_data:
                event = HookEvent.PRE_TOOL_USE
            elif "prompt" in hook_data or "message" in hook_data:
                event = HookEvent.PROMPT
            else:
                event = HookEvent.PROMPT

        return NormalizedHookInput(
            event=event,
            tool_name=self._extract_tool_name(hook_data),
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
            response = {
                "cancel": True,
                "errorMessage": final_error,
                "contextModification": redacted_output
                or self._sanitize_block_reason(violation_type),
            }
        else:
            response = {}
            sec = security_message if hook_event == HookEvent.PROMPT else None
            agent_ctx = self._build_warn_agent_context(
                warning_message, sec, violation_type
            )
            if agent_ctx:
                response["contextModification"] = agent_ctx
            if hook_event == HookEvent.POST_TOOL_USE and modified_output is not None:
                logger.warning(
                    "%s: modified_output provided but output replacement "
                    "may not be supported — redacted content sent as best-effort",
                    self.name,
                )
                response["modifiedResult"] = modified_output

        return self._add_metadata(
            {"output": json.dumps(response), "exit_code": 0},
            has_secrets,
            violation_type,
        )
