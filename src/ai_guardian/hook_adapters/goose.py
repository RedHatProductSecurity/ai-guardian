"""Goose Open Plugins command hooks (v1.59.0 contract).

Only PreToolUse is an enforcement surface in this integration. Stop means
continue the turn, not withhold a response, and is deliberately not installed.
"""

import json
from pathlib import Path
from typing import ClassVar, Dict, List, Optional
from urllib.parse import unquote, urlsplit

from ai_guardian.constants import GOOSE_MANAGED_HOOK_EVENTS, HookEvent
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput


class GooseAdapter(HookAdapter):
    ENV_ALIASES: ClassVar[List[str]] = ["goose"]
    AGENT_TYPE = "goose"
    EVENTS: ClassVar[Dict[str, HookEvent]] = {
        "SessionStart": HookEvent.SESSION_START,
        "UserPromptSubmit": HookEvent.PROMPT,
        "PreToolUse": HookEvent.PRE_TOOL_USE,
        "PostToolUse": HookEvent.POST_TOOL_USE,
        "SessionEnd": HookEvent.SESSION_END,
        "Stop": HookEvent.STOP,
    }
    TOOL_MAP: ClassVar[Dict[str, str]] = {
        "shell": "Bash",
        "write": "Write",
        "edit": "Edit",
        "tree": "LS",
        "read_image": "Read",
    }

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.GOOSE

    @property
    def name(self) -> str:
        return "Goose"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        return (
            isinstance(hook_data.get("event"), str)
            and hook_data["event"] in (*GOOSE_MANAGED_HOOK_EVENTS, "Stop")
            and isinstance(hook_data.get("session_id"), str)
            and "hook_event_name" not in hook_data
        )

    @staticmethod
    def _string(value) -> Optional[str]:
        return value if isinstance(value, str) and value else None

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event_name = hook_data.get("event")
        if not isinstance(event_name, str) or event_name not in self.EVENTS:
            raise ValueError("Unsupported or missing Goose hook event")
        event = self.EVENTS[event_name]
        native_name = self._string(hook_data.get("tool_name"))
        args = hook_data.get("tool_input")
        if event == HookEvent.PRE_TOOL_USE and (
            not native_name or not isinstance(args, dict)
        ):
            raise ValueError("Goose PreToolUse requires a tool name and object input")
        tool_input = dict(args) if isinstance(args, dict) else {}
        tool_name = self.TOOL_MAP.get(native_name or "", native_name)
        if native_name and "__" in native_name and not native_name.startswith("mcp__"):
            # Namespaced extension tools are MCP tools, not developer built-ins.
            tool_name = "mcp__" + native_name
            if native_name.startswith("ai-guardian-goose_ai-guardian__"):
                tool_name = "mcp__ai-guardian__" + native_name.split("__", 1)[1]
        # Native schemas use path/source, not file_path. Never let an unknown
        # alias select a different target than Goose will actually open.
        path = self._string(tool_input.get("path"))
        if native_name == "tree" and path is None:
            path = "."
        elif native_name not in self.TOOL_MAP:
            path = self._string(tool_input.get("file_path")) or path
        if native_name == "read_image":
            path = self._string(tool_input.get("source"))
            if path and urlsplit(path).scheme in ("http", "https"):
                tool_name = "WebFetch"
                tool_input["url"] = path
                path = None
            elif path and urlsplit(path).scheme == "file":
                parsed = urlsplit(path)
                if parsed.netloc not in ("", "localhost"):
                    raise ValueError("Unsupported Goose image file URL")
                path = unquote(parsed.path)
        if path:
            # Goose's developer file tools treat '~' literally, unlike a shell.
            target = (
                Path(path) if native_name in self.TOOL_MAP else Path(path).expanduser()
            )
            working_dir = self._string(hook_data.get("working_dir"))
            if not target.is_absolute() and working_dir:
                if not Path(working_dir).is_absolute():
                    raise ValueError("Goose working directory must be absolute")
                target = Path(working_dir) / target
            path = str(target.resolve())
            tool_input["file_path"] = path
        if native_name == "edit":
            tool_input["old_string"] = tool_input.get("before")
            tool_input["new_string"] = tool_input.get("after")
        return NormalizedHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=tool_input,
            file_path=path,
            working_dir=self._string(hook_data.get("working_dir")),
            session_id=self._string(hook_data.get("session_id")),
            tool_use_id=self._string(hook_data.get("tool_call_id")),
            prompt_text=self._string(hook_data.get("message")),
            tool_response=hook_data.get("tool_output"),
            raw_data=hook_data,
        )

    def get_tool_name_map(self) -> Dict[str, str]:
        return dict(self.TOOL_MAP)

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
        if hook_event != HookEvent.PRE_TOOL_USE:
            # Goose ignores decisions/output replacements on passive events.
            # Stop's block protocol only resumes generation; do not use it.
            return {"output": None, "exit_code": 0}
        blocked = bool(has_secrets)
        payload = {"decision": "block" if blocked else "allow"}
        if blocked:
            # Goose forwards reasons verbatim to the model: never echo findings,
            # tool arguments, paths, scanner errors, or remediation instructions.
            payload["reason"] = self._sanitize_block_reason(violation_type)
        return self._add_metadata(
            {"output": json.dumps(payload), "exit_code": 0}, blocked, violation_type
        )
