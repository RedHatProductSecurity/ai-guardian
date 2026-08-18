"""Kiro (AWS) hook adapter.

Kiro uses exit codes for blocking (0=allow, 1=block) with stdout for
agent context and stderr for error messages.

Also used by AiderDesk and OpenClaw (via env var override).
"""

from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput


class KiroAdapter(HookAdapter):
    """Adapter for Kiro (AWS), AiderDesk, and OpenClaw.

    Detection: kiro_hook_type or kiro_version field in hook data.
    AiderDesk and OpenClaw use this adapter via env var override.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["kiro", "aiderdesk", "openclaw"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.KIRO

    @property
    def name(self) -> str:
        return "Kiro"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return "kiro_hook_type" in hook_data or "kiro_version" in hook_data

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event_name = hook_data.get("hook_event_name", "").lower()

        if event_name in ("prompt_submit", "promptsubmit"):
            event = HookEvent.PROMPT
        elif event_name == "pre_tool_use":
            event = HookEvent.PRE_TOOL_USE
        elif event_name in ("post_tool_use", "agent_stop"):
            event = HookEvent.POST_TOOL_USE
        elif "tool_response" in hook_data:
            event = HookEvent.POST_TOOL_USE
        elif "tool_use" in hook_data or "tool_name" in hook_data:
            event = HookEvent.PRE_TOOL_USE
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
            exit_code = 2 if hook_event == HookEvent.PRE_TOOL_USE else 1
            return self._stderr_block_response(
                error_message,
                warning_message,
                redacted_output,
                exit_code,
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
            parts.append(modified_output)
        output = "\n\n".join(parts) if parts else None

        return self._add_metadata(
            {"output": output, "exit_code": 0},
            has_secrets,
            violation_type,
        )
