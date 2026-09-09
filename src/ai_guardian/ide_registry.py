"""Canonical metadata for supported AI coding-agent integrations.

The setup implementation contains the host-specific configuration schema, while
the hook adapter and transcript packages contain their own implementation
registries.  This module owns the cross-cutting support list and the evidence
plan used by tests and documentation.  The executable parity tests make sure
those implementation registries cannot silently drift from this list.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from ai_guardian.constants import MANAGED_HOOK_EVENTS_BY_IDE


@dataclass(frozen=True)
class IDEIntegration:
    """Support and validation metadata for one integration.

    ``adapter_aliases`` contains every value accepted by the explicit
    ``--ide``/``AI_GUARDIAN_IDE_TYPE`` path for the integration.  Shared
    implementations are represented by multiple entries (for example,
    Cline/ZooCode and Kiro/AiderDesk/OpenClaw) so each public integration key
    still has an auditable row.

    ``event_cases`` is the deterministic isolated-E2E plan.  Every managed
    event must appear exactly once and each value contains one or more of the
    E2E cases: ``allow``, ``block``, or ``post``.
    """

    key: str
    display_name: str
    adapter_class: str
    adapter_aliases: Tuple[str, ...]
    setup_mode: str
    mcp_registration: str
    transcript_formats: Tuple[str, ...]
    session_support: str
    event_cases: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    rules_supported: bool = False
    project_scope: bool = False
    platform_contract: str = "all supported platforms"
    external: bool = True

    @property
    def managed_hook_events(self) -> Tuple[str, ...]:
        """Return the events AI Guardian installs for this integration."""
        return tuple(MANAGED_HOOK_EVENTS_BY_IDE.get(self.key, ()))

    @property
    def supports_hooks(self) -> bool:
        """Whether the integration has an installed hook surface."""
        return self.setup_mode in {
            "command-hooks",
            "script-hooks",
            "extension",
            "plugin",
        }

    @property
    def supports_mcp(self) -> bool:
        """Whether the integration has an MCP advisor registration path."""
        return self.mcp_registration != "none"

    @property
    def e2e_events(self) -> Dict[str, Tuple[str, ...]]:
        """Return the isolated-E2E event plan as a convenient mapping."""
        return dict(self.event_cases)


# Keep this tuple ordered in the order presented to users by setup, the
# release-readiness workflow, and the support documentation.  ``dummy-agent``
# is deliberately kept out: it is an internal test harness, not an external
# IDE that users install.
SUPPORTED_IDE_REGISTRY: Tuple[IDEIntegration, ...] = (
    IDEIntegration(
        "claude",
        "Claude Code",
        "BaseAgentAdapter",
        ("claude",),
        "command-hooks",
        "local",
        ("JSONL",),
        "browser",
        (
            ("SessionStart", ("allow",)),
            ("UserPromptSubmit", ("allow",)),
            ("PreToolUse", ("allow", "block")),
            ("PostToolUse", ("post",)),
            ("SessionEnd", ("allow",)),
            ("PostCompact", ("allow",)),
        ),
    ),
    IDEIntegration(
        "cursor",
        "Cursor IDE",
        "CursorAdapter",
        ("cursor",),
        "command-hooks",
        "local",
        ("Cursor SQLite",),
        "browser",
        (
            ("beforeSubmitPrompt", ("allow",)),
            ("beforeReadFile", ("allow", "block")),
            # Cursor's shell hook is a decision point, but directory rules
            # apply to file-reading tools. Tool-policy blocking for this
            # shell event is covered by the adapter/pipeline contract tests;
            # the isolated matrix verifies its host-shaped allow payload.
            ("beforeShellExecution", ("allow",)),
            ("preToolUse", ("allow", "block")),
            ("afterShellExecution", ("post",)),
            ("postToolUse", ("post",)),
        ),
        project_scope=True,
        platform_contract="user and explicit project/cloud setup; runtime E2E on Linux",
    ),
    IDEIntegration(
        "copilot",
        "GitHub Copilot",
        "CopilotAdapter",
        ("copilot", "github_copilot"),
        "command-hooks",
        "none",
        ("JSONL", "Copilot Chat delta journal"),
        "browser",
        (
            ("userPromptSubmitted", ("allow",)),
            ("preToolUse", ("allow", "block")),
        ),
    ),
    IDEIntegration(
        "codex",
        "OpenAI Codex (CLI + Desktop)",
        "CodexAdapter",
        ("codex",),
        "command-hooks",
        "local",
        ("JSONL",),
        "browser",
        (
            ("UserPromptSubmit", ("allow",)),
            ("PreToolUse", ("allow", "block")),
            ("PostToolUse", ("post",)),
            ("PostCompact", ("allow",)),
            ("SessionEnd", ("allow",)),
        ),
        platform_contract="Codex CLI and desktop Codex mode; not regular ChatGPT mode",
    ),
    IDEIntegration(
        "windsurf",
        "Windsurf",
        "WindsurfAdapter",
        ("windsurf",),
        "command-hooks",
        "none",
        ("Windsurf JSONL",),
        "browser",
        (
            ("pre_user_prompt", ("allow",)),
            ("pre_run_command", ("allow", "block")),
            ("post_run_command", ("post",)),
            ("pre_read_code", ("allow", "block")),
            ("post_read_code", ("post",)),
            ("pre_write_code", ("allow", "block")),
            ("post_write_code", ("post",)),
            ("pre_mcp_tool_use", ("allow", "block")),
            ("post_mcp_tool_use", ("post",)),
        ),
    ),
    IDEIntegration(
        "gemini",
        "Google Gemini CLI",
        "GeminiCLIAdapter",
        ("gemini",),
        "command-hooks",
        "none",
        ("JSONL (explicit path)",),
        "browser",
        (
            ("SessionStart", ("allow",)),
            ("BeforeAgent", ("allow",)),
            ("BeforeTool", ("allow", "block")),
            ("AfterTool", ("post",)),
        ),
    ),
    IDEIntegration(
        "antigravity",
        "Antigravity CLI",
        "AntigravityAdapter",
        ("antigravity", "agy"),
        "command-hooks",
        "local",
        (),
        "none",
        (
            ("PreToolUse", ("allow", "block")),
            # Antigravity's PostToolUse payload has no tool output, so the
            # event is exercised as a clean observation rather than a
            # redaction case.
            ("PostToolUse", ("allow",)),
            ("PreInvocation", ("allow",)),
        ),
        platform_contract="Antigravity CLI; PostToolUse has no output transform surface",
    ),
    IDEIntegration(
        "cline",
        "Cline",
        "ClineAdapter",
        ("cline",),
        "script-hooks",
        "local",
        ("Cline JSON array",),
        "shared:cline",
        (
            ("PreToolUse", ("allow", "block")),
            ("PostToolUse", ("post",)),
            ("UserPromptSubmit", ("allow",)),
        ),
    ),
    IDEIntegration(
        "zoocode",
        "ZooCode",
        "ClineAdapter",
        ("zoocode",),
        "script-hooks",
        "local",
        ("Cline JSON array",),
        "shared:cline",
        (
            ("PreToolUse", ("allow", "block")),
            ("PostToolUse", ("post",)),
            ("UserPromptSubmit", ("allow",)),
        ),
    ),
    IDEIntegration(
        "kiro",
        "Kiro",
        "KiroAdapter",
        ("kiro",),
        "script-hooks",
        "local",
        ("Kiro JSONL",),
        "browser",
        (
            ("PreToolUse", ("allow", "block")),
            ("PostToolUse", ("post",)),
            ("PromptSubmit", ("allow",)),
        ),
    ),
    IDEIntegration(
        "aiderdesk",
        "AiderDesk",
        "KiroAdapter",
        ("aiderdesk",),
        "extension",
        "local",
        ("AiderDesk Markdown",),
        "none",
    ),
    IDEIntegration(
        "openclaw",
        "OpenClaw",
        "KiroAdapter",
        ("openclaw",),
        "extension",
        "local",
        ("OpenClaw JSONL",),
        "none",
        rules_supported=True,
    ),
    IDEIntegration(
        "opencode",
        "OpenCode",
        "OpenCodeAdapter",
        ("opencode",),
        "plugin",
        "local",
        ("OpenCode SQLite",),
        "browser",
    ),
    IDEIntegration(
        "augment",
        "Augment Code",
        "AugmentAdapter",
        ("augment",),
        "command-hooks",
        "local",
        (),
        "none",
        (
            ("PreToolUse", ("allow", "block")),
            ("PostToolUse", ("post",)),
        ),
        platform_contract="local command hooks; transcript storage is server-side",
    ),
    IDEIntegration(
        "crush",
        "Crush",
        "CrushAdapter",
        ("crush",),
        "command-hooks",
        "local",
        (),
        "none",
        (("PreToolUse", ("allow", "block")),),
        platform_contract="PreToolUse only; generated project hook is structurally checked on Windows",
    ),
    IDEIntegration(
        "junie",
        "Junie",
        "JunieAdapter",
        ("junie",),
        "mcp-only",
        "local",
        (),
        "none",
        rules_supported=True,
    ),
)


INTERNAL_IDE_REGISTRY: Tuple[IDEIntegration, ...] = (
    IDEIntegration(
        "dummy-agent",
        "Dummy Agent",
        "DummyAgentAdapter",
        ("dummy-agent", "dummy_agent"),
        "test-harness",
        "none",
        (),
        "none",
        external=False,
    ),
)

ALL_IDE_REGISTRY: Tuple[IDEIntegration, ...] = (
    *SUPPORTED_IDE_REGISTRY,
    *INTERNAL_IDE_REGISTRY,
)

SUPPORTED_IDE_TYPES: Tuple[str, ...] = tuple(
    integration.key for integration in SUPPORTED_IDE_REGISTRY
)
ALL_IDE_TYPES: Tuple[str, ...] = tuple(
    integration.key for integration in ALL_IDE_REGISTRY
)
SUPPORTED_IDES = SUPPORTED_IDE_TYPES

_REGISTRY_BY_KEY = {integration.key: integration for integration in ALL_IDE_REGISTRY}


def get_ide_integration(ide_type: str) -> Optional[IDEIntegration]:
    """Return metadata for an IDE key, or ``None`` when unknown."""
    return _REGISTRY_BY_KEY.get(ide_type)


def iter_supported_ide_integrations(
    include_internal: bool = False,
) -> Iterable[IDEIntegration]:
    """Iterate supported integrations in stable presentation order."""
    return ALL_IDE_REGISTRY if include_internal else SUPPORTED_IDE_REGISTRY


def get_e2e_event_cases(ide_type: str) -> Dict[str, Tuple[str, ...]]:
    """Return the isolated E2E plan for an IDE key."""
    integration = get_ide_integration(ide_type)
    return integration.e2e_events if integration else {}


__all__ = [
    "ALL_IDE_REGISTRY",
    "ALL_IDE_TYPES",
    "IDEIntegration",
    "INTERNAL_IDE_REGISTRY",
    "SUPPORTED_IDES",
    "SUPPORTED_IDE_REGISTRY",
    "SUPPORTED_IDE_TYPES",
    "get_e2e_event_cases",
    "get_ide_integration",
    "iter_supported_ide_integrations",
]
