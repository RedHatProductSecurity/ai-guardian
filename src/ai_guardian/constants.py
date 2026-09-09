"""Constants for AI Guardian.

Centralizes string constants used across multiple modules to prevent
typos and provide IDE discoverability.
"""

from enum import Enum


class ActionMode(str, Enum):
    """Action modes for security policy enforcement."""

    BLOCK = "block"
    WARN = "warn"
    LOG_ONLY = "log-only"
    REDACT = "redact"
    ASK = "ask"


def parse_ask_action(action_str: str):
    """Parse action string, handling 'ask:fallback' compound syntax.

    Returns (primary_action, fallback_action) tuple.
    For non-ask actions, both values are the action itself.

    Examples:
        "ask"          -> ("ask", "block")
        "ask:warn"     -> ("ask", "warn")
        "ask:log-only" -> ("ask", "log-only")
        "block"        -> ("block", "block")
        "warn"         -> ("warn", "warn")
    """
    if not action_str or not isinstance(action_str, str):
        return (ActionMode.BLOCK, ActionMode.BLOCK)

    action_str = action_str.strip()

    if action_str == "ask":
        return (ActionMode.ASK, ActionMode.BLOCK)

    if action_str.startswith("ask:"):
        fallback = action_str[4:]
        valid_fallbacks = {ActionMode.BLOCK, ActionMode.WARN, ActionMode.LOG_ONLY}
        if fallback in valid_fallbacks:
            return (ActionMode.ASK, fallback)
        return (ActionMode.ASK, ActionMode.BLOCK)

    return (action_str, action_str)


class ViolationType(str, Enum):
    """Violation types logged by the violation logger."""

    SECRET_DETECTED = "secret_detected"
    PII_DETECTED = "pii_detected"
    DIRECTORY_BLOCKING = "directory_blocking"
    TOOL_PERMISSION = "tool_permission"
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK_DETECTED = "jailbreak_detected"
    SSRF_BLOCKED = "ssrf_blocked"
    CONFIG_FILE_EXFIL = "config_file_exfil"
    SECRET_REDACTION = "secret_redaction"
    SECRET_IN_TRANSCRIPT = "secret_in_transcript"
    PII_IN_TRANSCRIPT = "pii_in_transcript"
    IMAGE_SECRET_DETECTED = "image_secret_detected"
    IMAGE_PII_DETECTED = "image_pii_detected"
    CONTEXT_POISONING = "context_poisoning"
    SUPPLY_CHAIN = "supply_chain"
    CODE_SECURITY = "code_security"
    OFFENSIVE_LANGUAGE = "offensive_language"
    CANARY_DETECTED = "canary_detected"
    EXFIL_DETECTION = "exfil_detection"


class HookEvent(str, Enum):
    """Hook event types from IDE integrations."""

    PROMPT = "prompt"
    PRE_TOOL_USE = "pretooluse"
    PERMISSION_REQUEST = "permissionrequest"
    POST_TOOL_USE = "posttooluse"
    PRE_COMPACT = "precompact"
    BEFORE_READ_FILE = "beforereadfile"
    STOP = "stop"
    INTERRUPT = "interrupt"
    SESSION_START = "sessionstart"
    SESSION_END = "sessionend"
    POST_COMPACT = "postcompact"
    SUBAGENT_START = "subagentstart"
    SUBAGENT_STOP = "subagentstop"
    POST_TOOL_USE_FAILURE = "posttoolusefailure"
    AFTER_FILE_EDIT = "afterfileedit"
    AFTER_TAB_FILE_EDIT = "aftertabfileedit"
    AFTER_AGENT_RESPONSE = "afteragentresponse"
    AFTER_AGENT_THOUGHT = "afteragentthought"
    WORKSPACE_OPEN = "workspaceopen"

    @property
    def display_name(self) -> str:
        """PascalCase display name used in IDE protocol responses."""
        return _DISPLAY_NAMES.get(self, self.value)

    @classmethod
    def from_display_name(cls, name: str) -> "HookEvent":
        """Look up a HookEvent by its PascalCase display name."""
        for event, display in _DISPLAY_NAMES.items():
            if display == name:
                return event
        raise ValueError(f"Unknown hook event display name: {name}")


_DISPLAY_NAMES = {
    HookEvent.SESSION_START: "SessionStart",
    HookEvent.PROMPT: "UserPromptSubmit",
    HookEvent.PRE_TOOL_USE: "PreToolUse",
    HookEvent.PERMISSION_REQUEST: "PermissionRequest",
    HookEvent.POST_TOOL_USE: "PostToolUse",
    HookEvent.PRE_COMPACT: "PreCompact",
    HookEvent.BEFORE_READ_FILE: "PreToolUse",
    HookEvent.SESSION_END: "SessionEnd",
    HookEvent.STOP: "Stop",
    HookEvent.INTERRUPT: "Interrupt",
    HookEvent.POST_COMPACT: "PostCompact",
    HookEvent.SUBAGENT_START: "SubagentStart",
    HookEvent.SUBAGENT_STOP: "SubagentStop",
    HookEvent.POST_TOOL_USE_FAILURE: "PostToolUseFailure",
    HookEvent.AFTER_FILE_EDIT: "AfterFileEdit",
    HookEvent.AFTER_TAB_FILE_EDIT: "AfterTabFileEdit",
    HookEvent.AFTER_AGENT_RESPONSE: "AfterAgentResponse",
    HookEvent.AFTER_AGENT_THOUGHT: "AfterAgentThought",
    HookEvent.WORKSPACE_OPEN: "WorkspaceOpen",
}

ALL_HOOK_EVENT_DISPLAY_NAMES = frozenset(_DISPLAY_NAMES.values())


AUGMENT_TOOL_MAP = {
    "launch-process": "Bash",
    "str-replace-editor": "Edit",
    "save-file": "Write",
    "view": "Read",
    "remove-files": "Delete",
}

# AI Guardian's required hook manifest is the single source of truth used by
# setup, verification, doctor, tray health, and integration tests.  These are
# the events AI Guardian installs for each command-hook adapter; host events
# outside these tuples are not AI Guardian hooks.
CLAUDE_MANAGED_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SessionEnd",
    "PostCompact",
)

CURSOR_MANAGED_HOOK_EVENTS = (
    "beforeSubmitPrompt",
    "beforeReadFile",
    "beforeShellExecution",
    "preToolUse",
    "afterShellExecution",
    "postToolUse",
)

COPILOT_MANAGED_HOOK_EVENTS = ("userPromptSubmitted", "preToolUse")

CODEX_MANAGED_HOOK_EVENTS = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostCompact",
    "SessionEnd",
)

WINDSURF_MANAGED_HOOK_EVENTS = (
    "pre_user_prompt",
    "pre_run_command",
    "post_run_command",
    "pre_read_code",
    "post_read_code",
    "pre_write_code",
    "post_write_code",
    "pre_mcp_tool_use",
    "post_mcp_tool_use",
)

GEMINI_MANAGED_HOOK_EVENTS = (
    "SessionStart",
    "BeforeAgent",
    "BeforeTool",
    "AfterTool",
)

CLINE_MANAGED_HOOK_EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit")
ZOOCODE_MANAGED_HOOK_EVENTS = CLINE_MANAGED_HOOK_EVENTS
KIRO_MANAGED_HOOK_EVENTS = ("PreToolUse", "PostToolUse", "PromptSubmit")
AUGMENT_MANAGED_HOOK_EVENTS = ("PreToolUse", "PostToolUse")
CRUSH_MANAGED_HOOK_EVENTS = ("PreToolUse",)
AIDERDESK_MANAGED_HOOK_EVENTS = ()
OPENCLAW_MANAGED_HOOK_EVENTS = ()
OPENCODE_MANAGED_HOOK_EVENTS = ()
JUNIE_MANAGED_HOOK_EVENTS = ()
DUMMY_AGENT_MANAGED_HOOK_EVENTS = ()

MANAGED_HOOK_EVENTS_BY_IDE = {
    "claude": CLAUDE_MANAGED_HOOK_EVENTS,
    "cursor": CURSOR_MANAGED_HOOK_EVENTS,
    "copilot": COPILOT_MANAGED_HOOK_EVENTS,
    "codex": CODEX_MANAGED_HOOK_EVENTS,
    "windsurf": WINDSURF_MANAGED_HOOK_EVENTS,
    "gemini": GEMINI_MANAGED_HOOK_EVENTS,
    "cline": CLINE_MANAGED_HOOK_EVENTS,
    "zoocode": ZOOCODE_MANAGED_HOOK_EVENTS,
    "kiro": KIRO_MANAGED_HOOK_EVENTS,
    "augment": AUGMENT_MANAGED_HOOK_EVENTS,
    "crush": CRUSH_MANAGED_HOOK_EVENTS,
    "aiderdesk": AIDERDESK_MANAGED_HOOK_EVENTS,
    "openclaw": OPENCLAW_MANAGED_HOOK_EVENTS,
    "opencode": OPENCODE_MANAGED_HOOK_EVENTS,
    "junie": JUNIE_MANAGED_HOOK_EVENTS,
    "dummy-agent": DUMMY_AGENT_MANAGED_HOOK_EVENTS,
}

# Cursor's adapter recognizes the complete upstream event vocabulary. This is
# deliberately not the AI Guardian installation manifest: the managed set is
# separate from this adapter vocabulary. Events below the managed set are
# simply upstream events that a user may already have configured; they are not
# AI Guardian hooks and must never be reported as missing setup.
CURSOR_RECOGNIZED_HOOK_EVENTS = (
    *CURSOR_MANAGED_HOOK_EVENTS,
    "beforeTabFileRead",
    "beforeMCPExecution",
    "afterMCPExecution",
    "postToolUseFailure",
    "subagentStart",
    "sessionStart",
    "sessionEnd",
    "subagentStop",
    "preCompact",
    "stop",
    "afterAgentResponse",
    "afterAgentThought",
    "afterFileEdit",
    "afterTabFileEdit",
    "workspaceOpen",
)

# Keep the historical name as an alias for callers that only need the
# adapter-recognized Cursor vocabulary. It is not a managed-hook manifest.
CURSOR_HOOK_EVENTS = CURSOR_RECOGNIZED_HOOK_EVENTS

# Historical compatibility alias; new setup/health code uses the explicit
# managed name above.
CRUSH_HOOK_EVENTS = CRUSH_MANAGED_HOOK_EVENTS

VIOLATION_FILTER_TYPES = [
    (
        "Tool Permission",
        "tool_permission",
        "Blocked tool/MCP server execution (permission rules)",
    ),
    (
        "Secrets",
        "secret_detected",
        "Hard-coded secrets detected in files or prompts (API keys, tokens, passwords)",
    ),
    (
        "Secret Redaction",
        "secret_redaction",
        "Secrets found in tool output and redacted before reaching the AI model",
    ),
    (
        "Directories",
        "directory_blocking",
        "File access blocked by directory protection rules",
    ),
    (
        "Prompt Injection",
        "prompt_injection",
        "Attempts to manipulate AI behavior detected in prompts or files",
    ),
    ("Jailbreak", "jailbreak_detected", "Attempts to bypass AI safety constraints"),
    (
        "SSRF Blocked",
        "ssrf_blocked",
        "Blocked access to private networks, metadata endpoints, or dangerous URLs",
    ),
    (
        "Config Exfil",
        "config_file_exfil",
        "Credential exfiltration commands detected in AI config files",
    ),
    (
        "PII Detected",
        "pii_detected",
        "Personal Identifiable Information found in files or prompts",
    ),
    (
        "Transcript Secret",
        "secret_in_transcript",
        "Secret found in conversation history",
    ),
    (
        "Transcript PII",
        "pii_in_transcript",
        "Personal Identifiable Information found in conversation history",
    ),
    (
        "Transcript PI",
        "prompt_injection_in_transcript",
        "Prompt injection pattern found in conversation history",
    ),
    (
        "Annotation",
        "annotation_suppressed",
        "Finding suppressed by an inline annotation",
    ),
    (
        "Image Secret",
        "image_secret_detected",
        "Secret detected in image via OCR scanning",
    ),
    ("Image PII", "image_pii_detected", "PII detected in image via OCR scanning"),
    (
        "Code Security",
        "code_security",
        "Insecure Python code patterns detected by Bandit",
    ),
    (
        "Offensive Language",
        "offensive_language",
        "Profanity, slurs, or non-inclusive terminology detected",
    ),
    (
        "Canary Detected",
        "canary_detected",
        "User-registered canary token found in AI output",
    ),
    (
        "Exfil Detection",
        "exfil_detection",
        "Bash command blocked due to credential exfiltration behavior",
    ),
]

ALL_VIOLATION_TYPES = tuple(v.value for v in ViolationType)
ALL_HOOK_EVENTS = tuple(e.value for e in HookEvent)
ALL_ACTION_MODES = tuple(a.value for a in ActionMode)

# --- Rule ID mappings ---

RULE_ID_LABELS = {
    "SECRET-001": "Secrets",
    "PII-001": "PII",
    "PROMPT-INJECTION-001": "Prompt Injection",
    "SSRF-001": "SSRF",
    "CONFIG-001": "Config Exfiltration",
    "SUPPLY-CHAIN-001": "Supply Chain",
    "UNICODE-001": "Unicode Attacks",
    "CODE-SECURITY-001": "Code Security",
    "OFFENSIVE-001": "Offensive Language",
    "EXFIL-001": "Exfil Detection",
    "CANARY-001": "Canary Token",
}

RULE_ID_TO_SCANNER = {
    "SECRET-001": "secret_scanning",
    "PII-001": "scan_pii",
    "PROMPT-INJECTION-001": "prompt_injection",
    "SSRF-001": "ssrf_protection",
    "CONFIG-001": "config_file_scanning",
    "SUPPLY-CHAIN-001": "supply_chain",
    "EXFIL-DETECTION-001": "exfil_detection",
}

RULE_ID_TO_VIOLATION_TYPE = {
    "SECRET-001": "secret_detected",
    "PII-001": "pii_detected",
    "PROMPT-INJECTION-001": "prompt_injection",
    "SSRF-001": "ssrf_blocked",
    "CONFIG-001": "config_file_exfil",
    "SUPPLY-CHAIN-001": "supply_chain",
    "UNICODE-001": "prompt_injection",
    "CODE-SECURITY-001": "code_security",
    "OFFENSIVE-001": "offensive_language",
    "EXFIL-001": "exfil_detection",
    "CANARY-001": "canary_detected",
}

RULE_ID_TO_CONFIG_SECTION = {
    "SECRET-001": "secret_scanning",
    "PII-001": "scan_pii",
    "PROMPT-INJECTION-001": "prompt_injection",
    "SSRF-001": "ssrf_protection",
    "CONFIG-001": "config_file_scanning",
    "SUPPLY-CHAIN-001": "supply_chain",
    "UNICODE-001": "prompt_injection",
    "CODE-SECURITY-001": "code_scanning",
    "OFFENSIVE-001": "scan_offensive",
    "EXFIL-001": "exfil_detection",
    "CANARY-001": "canary_detection",
}

SLUG_TO_CONFIG_SECTION = {
    "/secrets": "secret_scanning",
    "/secret-engines": "secret_scanning",
    "/secret-redaction": "secret_redaction",
    "/scan-pii": "scan_pii",
    "/pi-detection": "prompt_injection",
    "/pi-ml-engines": "prompt_injection",
    "/pi-patterns": "prompt_injection",
    "/pi-jailbreak": "prompt_injection",
    "/pi-unicode": "prompt_injection",
    "/ssrf": "ssrf_protection",
    "/config-scanner": "config_file_scanning",
    "/context-poisoning": "context_poisoning",
    "/supply-chain": "supply_chain",
    "/code-security": "code_scanning",
    "/offensive-language": "scan_offensive",
    "/canary-detection": "canary_detection",
    "/exfil-detection": "exfil_detection",
    "/annotations": "annotations",
    "/permission-rules": "permissions",
    "/directory-rules": "directory_rules",
    "/violation-logging": "violation_logging",
    "/performance": "latency_tracking",
}

_SECTION_TO_SLUG: dict[str, str] = {}
for _slug, _section in SLUG_TO_CONFIG_SECTION.items():
    _SECTION_TO_SLUG.setdefault(_section, _slug)
del _slug, _section

RULE_ID_TO_SLUG = {
    rule_id: ("/pi-unicode" if rule_id == "UNICODE-001" else _SECTION_TO_SLUG[section])
    for rule_id, section in RULE_ID_TO_CONFIG_SECTION.items()
}
del _SECTION_TO_SLUG
