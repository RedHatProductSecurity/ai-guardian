"""Google Antigravity CLI (agy) hook adapter.

Antigravity hooks are configured in hooks.json (``~/.gemini/config/hooks.json``
globally, ``<workspace>/.agents/hooks.json`` per project) and use a protojson
camelCase payload that differs from every other supported agent:

- The tool call is nested: ``{"toolCall": {"name": ..., "args": {...}}}``
- Metadata keys are camelCase: ``conversationId``, ``workspacePaths``,
  ``transcriptPath``
- The response is flat: ``{"decision": "allow|deny|ask|force_ask", "reason": ...}``
  rather than Claude Code's ``hookSpecificOutput.permissionDecision``

Antigravity sends no event name in the payload, and its PreToolUse and
PostToolUse payloads are near-identical, so generated hook commands declare
``--hook-event <Event>``.  That value is stamped into the hook data as
``_hook_event`` so it survives forwarding to the daemon, which runs as a
separate long-lived process.  Hand-written configs fall back to inferring the
event from the payload shape.
"""

import json
import logging
from typing import ClassVar, Dict, List, Optional

from ai_guardian.constants import (
    ANTIGRAVITY_PATH_ARG_KEYS as _PATH_ARG_KEYS,
    HookEvent,
    antigravity_tool_name,
)
from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput

logger = logging.getLogger(__name__)

# Antigravity requires every PreToolUse hook to return a decision — it has no
# "no opinion" value, and an absent/unrecognised decision denies the tool call.
# "ask" is the closest analogue to the silent pass-through used for agents that
# do have one: it hands the choice back to Antigravity's own permission prompt
# and respects its "Always Allow" cache, so ai-guardian never silently widens
# the user's existing permissions.
_CLEAN_PRE_TOOL_DECISION = "ask"


# Argument keys carrying edit/write text, in preference order.
_CONTENT_ARG_KEYS = ("Content", "CodeEdit", "NewContent", "Contents")

_EVENT_BY_NAME = {
    "pretooluse": HookEvent.PRE_TOOL_USE,
    "posttooluse": HookEvent.POST_TOOL_USE,
    "preinvocation": HookEvent.PROMPT,
    "postinvocation": HookEvent.POST_TOOL_USE,
    "stop": HookEvent.STOP,
}


class AntigravityAdapter(HookAdapter):
    """Adapter for the Google Antigravity CLI (``agy``).

    Detection: camelCase ``conversationId`` plus ``workspacePaths`` — fields no
    other supported agent sends.
    """

    ENV_ALIASES: ClassVar[List[str]] = ["antigravity", "agy"]

    @property
    def ide_type(self):
        from ai_guardian.response_format import IDEType

        return IDEType.ANTIGRAVITY

    @property
    def name(self) -> str:
        return "Antigravity CLI"

    @classmethod
    def can_handle(cls, hook_data: Dict) -> bool:
        if "conversationId" not in hook_data:
            return False
        # Defensive: a payload naming its own event is not Antigravity's, even
        # if a future agent also adopts conversationId.  This adapter is first
        # in the detection order, so it must not claim such payloads.
        if "hook_event_name" in hook_data or "hookEventName" in hook_data:
            return False
        return "workspacePaths" in hook_data or "toolCall" in hook_data

    # -- Input normalization --

    @staticmethod
    def _detect_event(hook_data: Dict) -> HookEvent:
        """Resolve the hook event.

        Antigravity does not name the event in the payload, so prefer the
        event declared by ``--hook-event`` (stamped into the hook data as
        ``_hook_event``), then fall back to the distinguishing payload fields.

        The declared event is read only from the payload, never from the
        environment: the daemon is long-lived and inherits the environment of
        whichever hook invocation happened to start it, so an inherited
        ``AI_GUARDIAN_HOOK_EVENT`` would silently misroute every later payload
        that does not carry its own ``_hook_event`` (a hand-written config).
        The CLI stamps the value into the payload in its own fresh process.
        """
        declared = hook_data.get("_hook_event")
        if isinstance(declared, str) and declared.strip().lower() in _EVENT_BY_NAME:
            return _EVENT_BY_NAME[declared.strip().lower()]

        # PostToolUse carries toolCall too (the documented contract omits it),
        # so the "error" key — present only after a tool has run — is what
        # separates the two.  Check it before the toolCall test.
        if "error" in hook_data:
            return HookEvent.POST_TOOL_USE
        if isinstance(hook_data.get("toolCall"), dict):
            return HookEvent.PRE_TOOL_USE
        if "terminationReason" in hook_data or "executionNum" in hook_data:
            return HookEvent.STOP
        if "invocationNum" in hook_data:
            return HookEvent.PROMPT
        if "stepIdx" in hook_data:
            return HookEvent.POST_TOOL_USE
        return HookEvent.PROMPT

    @staticmethod
    def _tool_call(hook_data: Dict) -> Dict:
        tool_call = hook_data.get("toolCall")
        return tool_call if isinstance(tool_call, dict) else {}

    def _extract_args(self, hook_data: Dict) -> Dict:
        args = self._tool_call(hook_data).get("args")
        return args if isinstance(args, dict) else {}

    def _extract_path(self, hook_data: Dict) -> Optional[str]:
        args = self._extract_args(hook_data)
        if not args:
            return None
        lowered = {k.lower(): v for k, v in args.items()}
        for key in _PATH_ARG_KEYS:
            value = lowered.get(key.lower())
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _working_dir(hook_data: Dict) -> Optional[str]:
        paths = hook_data.get("workspacePaths")
        if isinstance(paths, list):
            for path in paths:
                if isinstance(path, str) and path:
                    return path
        return None

    @staticmethod
    def _extract_content(args: Dict) -> Optional[str]:
        """Pull edit/write text out of Antigravity's PascalCase arguments."""
        lowered = {k.lower(): v for k, v in args.items()}
        for key in _CONTENT_ARG_KEYS:
            value = lowered.get(key.lower())
            if isinstance(value, str) and value:
                return value

        # propose_code sends a list of replacement chunks.
        chunks = args.get("ReplacementChunks")
        if isinstance(chunks, list):
            parts = []
            for chunk in chunks:
                if isinstance(chunk, str):
                    parts.append(chunk)
                elif isinstance(chunk, dict):
                    for chunk_key in ("targetContent", "TargetContent", "content"):
                        text = chunk.get(chunk_key)
                        if isinstance(text, str) and text:
                            parts.append(text)
            if parts:
                return "\n".join(parts)
        return None

    def get_tool_name_map(self) -> Dict[str, str]:
        from ai_guardian.constants import ANTIGRAVITY_TOOL_MAP

        return ANTIGRAVITY_TOOL_MAP

    def normalize_input(self, hook_data: Dict) -> NormalizedHookInput:
        event = self._detect_event(hook_data)

        args = self._extract_args(hook_data)
        tool_name = antigravity_tool_name(self._tool_call(hook_data).get("name"), args)
        tool_input = dict(args)
        # run_command puts the shell command in CommandLine; the scanning
        # pipeline expects it under the canonical "command" key.
        command = args.get("CommandLine") or args.get("command_line")
        if isinstance(command, str) and "command" not in tool_input:
            tool_input["command"] = command

        file_path = self._extract_path(hook_data)
        if file_path and "file_path" not in tool_input:
            tool_input["file_path"] = file_path

        # Write/Edit scanning reads "content"/"new_string"; Antigravity carries
        # the same text under PascalCase argument names.
        content = self._extract_content(args)
        if content is not None:
            tool_input.setdefault("content", content)
            tool_input.setdefault("new_string", content)

        return NormalizedHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=tool_input,
            file_path=file_path,
            working_dir=self._working_dir(hook_data),
            session_id=hook_data.get("conversationId"),
            tool_use_id=(str(hook_data["stepIdx"]) if "stepIdx" in hook_data else None),
            prompt_text=None,
            tool_response=hook_data.get("error"),
            transcript_path=hook_data.get("transcriptPath"),
            raw_data=hook_data,
        )

    # -- Response formatting --

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
        response: Dict = {}

        if has_secrets and error_message:
            final_error = self._combine_error_messages(error_message, warning_message)
            if hook_event == HookEvent.PRE_TOOL_USE:
                response = {"decision": "deny", "reason": final_error}
            else:
                # Only PreToolUse honours a decision. For every other event the
                # best available signal is an injected message.
                response = self._inject_message(hook_event, final_error)
        else:
            parts = [
                part
                for part in (
                    security_message if hook_event == HookEvent.PROMPT else None,
                    warning_message,
                )
                if part
            ]
            if parts:
                response = self._inject_message(hook_event, "\n\n".join(parts))

            if hook_event == HookEvent.POST_TOOL_USE and modified_output is not None:
                logger.warning(
                    "%s: PostToolUse hooks cannot replace tool output — "
                    "redacted content dropped",
                    self.name,
                )

        # A PreToolUse response without a decision is treated as a denial by
        # Antigravity, so a clean check must say so explicitly.  Any advisory
        # text rides along as the reason, which is shown at the prompt.
        if hook_event == HookEvent.PRE_TOOL_USE and "decision" not in response:
            response = {"decision": _CLEAN_PRE_TOOL_DECISION}
            advisory = "\n\n".join(filter(None, (security_message, warning_message)))
            if advisory:
                response["reason"] = advisory

        return self._add_metadata(
            {"output": json.dumps(response), "exit_code": 0},
            has_secrets,
            violation_type,
        )

    @staticmethod
    def _inject_message(hook_event: HookEvent, message: str) -> Dict:
        """Build the event-appropriate carrier for an advisory message.

        PreInvocation/PostInvocation accept injectSteps; PostToolUse expects an
        empty object and has no channel for feedback.
        """
        if hook_event in (HookEvent.PROMPT, HookEvent.SESSION_START):
            return {"injectSteps": [{"ephemeralMessage": message}]}
        # Stop only honours decision == "continue" (which would block the
        # agent from stopping); there is no advisory channel here.
        return {}
