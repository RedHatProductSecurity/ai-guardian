"""OpenCode hook adapter.

OpenCode uses a JS/TS plugin architecture. The bridge plugin pipes
hook data as JSON to ai-guardian via stdin, using the same protocol
as Claude Code. Detection relies on opencode_version field or env var.
"""

import json
from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import HookEvent, OPENCODE_TOOL_MAP
from ai_guardian.hook_adapters.base import NormalizedHookInput
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter
from ai_guardian.tools.input import (
    OPENCODE_FILE_TOOLS,
    normalize_opencode_input,
    opencode_native_input,
    opencode_native_name,
)


class OpenCodeAdapter(BaseAgentAdapter):
    """Adapter for OpenCode.

    OpenCode shares Claude Code's JSON response structure via the bridge
    plugin. Detection uses opencode_version field or env var override.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["opencode"]
    AGENT_TYPE: ClassVar[str] = "opencode"

    @property
    def name(self) -> str:
        return "OpenCode"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if hook_data.get("opencode_version"):
            return True
        if hook_data.get("hook_source") == "opencode":
            return True
        return False

    def get_tool_name_map(self) -> Dict[str, str]:
        """Map OpenCode's native built-in tool names to canonical names."""
        return OPENCODE_TOOL_MAP

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
        modified_prompt: Optional[str] = None,
    ) -> Dict:
        """Return a host-owned sanitized prompt replacement when verified."""
        response = super().format_response(
            has_secrets=has_secrets,
            error_message=error_message,
            hook_event=hook_event,
            warning_message=warning_message,
            modified_output=modified_output,
            violation_type=violation_type,
            security_message=security_message,
            redacted_output=redacted_output,
            tool_name=tool_name,
        )
        if modified_prompt is None:
            return response

        if has_secrets or hook_event != HookEvent.PROMPT or not modified_prompt:
            return super().format_response(
                has_secrets=True,
                error_message=(
                    "AI Guardian could not safely replace the prompt; submission blocked."
                ),
                hook_event=HookEvent.PROMPT,
                violation_type=violation_type,
            )

        try:
            payload = json.loads(response.get("output", ""))
            if not isinstance(payload, dict):
                raise ValueError("Unexpected OpenCode response shape")
            payload["updatedPrompt"] = modified_prompt
            response["output"] = json.dumps(payload)
        except (TypeError, ValueError):
            return super().format_response(
                has_secrets=True,
                error_message=(
                    "AI Guardian could not safely replace the prompt; submission blocked."
                ),
                hook_event=HookEvent.PROMPT,
                violation_type=violation_type,
            )
        return response

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        result = super().normalize_input(hook_data)
        event_name = (
            hook_data.get("hook_event_name") or hook_data.get("hookEventName") or ""
        ).lower()
        if event_name == "session.end":
            result.event = HookEvent.SESSION_END
        native_name = opencode_native_name(hook_data)
        if isinstance(native_name, str):
            result.tool_name = OPENCODE_TOOL_MAP.get(
                native_name.casefold(), native_name
            )
        result.tool_input = normalize_opencode_input(
            result.tool_name, opencode_native_input(hook_data), result.working_dir
        )
        result.file_path = (
            result.tool_input.get("file_path")
            if result.tool_name in OPENCODE_FILE_TOOLS
            else None
        )
        return result
