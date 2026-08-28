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
    POST_TOOL_USE = "posttooluse"
    BEFORE_READ_FILE = "beforereadfile"
    STOP = "stop"
    SESSION_START = "sessionstart"
    SESSION_END = "sessionend"
    POST_COMPACT = "postcompact"

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
    HookEvent.POST_TOOL_USE: "PostToolUse",
    HookEvent.BEFORE_READ_FILE: "PreToolUse",
    HookEvent.SESSION_END: "SessionEnd",
    HookEvent.STOP: "Stop",
    HookEvent.POST_COMPACT: "PostCompact",
}

ALL_HOOK_EVENT_DISPLAY_NAMES = frozenset(_DISPLAY_NAMES.values())


# Antigravity tool names are the lowercased CORTEX_STEP_TYPE_* enum with the
# prefix stripped. Map the security-relevant ones to canonical Claude Code
# names so the existing pattern/policy rules apply unchanged.
ANTIGRAVITY_TOOL_MAP = {
    "run_command": "Bash",
    "shell_exec": "Bash",
    "send_command_input": "Bash",
    "view_file": "Read",
    "view_code_item": "Read",
    "view_file_outline": "Read",
    "read_notebook": "Read",
    "propose_code": "Edit",
    "file_change": "Edit",
    "edit_notebook": "NotebookEdit",
    "write_blob": "Write",
    "delete_directory": "Delete",
    "list_directory": "LS",
    "list_dir": "LS",
    "grep_search": "Grep",
    "code_search": "Grep",
    "find": "Glob",
    "find_by_name": "Glob",
    "read_url_content": "WebFetch",
    "open_browser_url": "WebFetch",
    "search_web": "WebSearch",
}


def antigravity_tool_name(raw_name, args=None):
    """Resolve an Antigravity step name to its canonical tool name.

    MCP calls arrive as ``call_mcp_tool`` with the server and tool in the
    arguments; they are rebuilt as ``mcp__<server>__<tool>`` so the existing
    MCP restriction and ``mcp__*`` permission rules keep applying.
    """
    if not isinstance(raw_name, str) or not raw_name:
        return raw_name

    lowered = raw_name.lower()
    if lowered in ANTIGRAVITY_MCP_STEPS:
        args = args if isinstance(args, dict) else {}
        server = args.get("ServerName") or args.get("server_name")
        tool = args.get("ToolName") or args.get("tool_name")
        if server and tool:
            return f"mcp__{server}__{tool}"
        return "mcp__unknown"

    return ANTIGRAVITY_TOOL_MAP.get(lowered, raw_name)


# Argument keys Antigravity tools use for a path, in preference order.
ANTIGRAVITY_PATH_ARG_KEYS = (
    "TargetFile",
    "AbsolutePath",
    "FilePath",
    "Path",
    "DirectoryPath",
    "SearchDirectory",
    "Url",
)

# The subset that can name a readable file, used when pulling content to scan.
# Directory and URL keys are deliberately excluded.
ANTIGRAVITY_FILE_ARG_KEYS = ("TargetFile", "AbsolutePath", "FilePath", "Path")


# Steps that invoke an MCP tool rather than a built-in one.
ANTIGRAVITY_MCP_STEPS = frozenset({"call_mcp_tool", "mcp_tool"})


AUGMENT_TOOL_MAP = {
    "launch-process": "Bash",
    "str-replace-editor": "Edit",
    "save-file": "Write",
    "view": "Read",
    "remove-files": "Delete",
}

CURSOR_HOOK_EVENTS = (
    "beforeSubmitPrompt",
    "beforeReadFile",
    "beforeShellExecution",
    "afterShellExecution",
    "preToolUse",
    "postToolUse",
)

CRUSH_HOOK_EVENTS = ("PreToolUse",)

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
