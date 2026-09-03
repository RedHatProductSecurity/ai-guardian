"""
Multi-agent hook adapter registry.

Provides detect_adapter() to auto-detect the right adapter from hook
input JSON, and get_adapter_by_ide_type() for lookup by IDEType enum.
"""

import logging
import os
from typing import Dict, Optional

from ai_guardian.hook_adapters.base import HookAdapter, NormalizedHookInput
from ai_guardian.hook_adapters.antigravity import AntigravityAdapter
from ai_guardian.hook_adapters.cline import ClineAdapter
from ai_guardian.hook_adapters.gemini import GeminiCLIAdapter
from ai_guardian.hook_adapters.windsurf import WindsurfAdapter
from ai_guardian.hook_adapters.copilot import CopilotAdapter
from ai_guardian.hook_adapters.cursor import CursorAdapter
from ai_guardian.hook_adapters.kiro import KiroAdapter
from ai_guardian.hook_adapters.augment import AugmentAdapter
from ai_guardian.hook_adapters.codex import CodexAdapter
from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter
from ai_guardian.hook_adapters.opencode import OpenCodeAdapter
from ai_guardian.hook_adapters.crush import CrushAdapter
from ai_guardian.hook_adapters.junie import JunieAdapter
from ai_guardian.hook_adapters.dummy_agent import DummyAgentAdapter

logger = logging.getLogger(__name__)

# Ordered by detection specificity: most unique fields first.
# Claude Code is last because it is the default fallback.
ADAPTER_CLASSES = [
    AntigravityAdapter,  # conversationId + workspacePaths (camelCase protojson)
    ClineAdapter,  # clineVersion field
    GeminiCLIAdapter,  # transcript_path field
    WindsurfAdapter,  # agent_action_name field
    CopilotAdapter,  # toolName field or timestamp+cwd
    CursorAdapter,  # cursor_version or hook_name
    KiroAdapter,  # kiro_hook_type or kiro_version
    AugmentAdapter,  # is_mcp_tool + tool_name
    OpenCodeAdapter,  # opencode_version or hook_source
    CrushAdapter,  # CRUSH env var or event+tool_input fields
    DummyAgentAdapter,  # dummy_agent field (simulated IDE)
    BaseAgentAdapter,  # PascalCase hook_event_name (fallback)
]

# Env var value → adapter class (includes aliases like "copilot" → CopilotAdapter)
_ENV_ALIAS_MAP: Dict[str, type] = {}
for _cls in ADAPTER_CLASSES + [CodexAdapter, JunieAdapter, DummyAgentAdapter]:
    for _alias in _cls.ENV_ALIASES:
        _ENV_ALIAS_MAP[_alias] = _cls


def detect_adapter(hook_data: Dict) -> HookAdapter:
    """Detect and return the appropriate adapter for the given hook input.

    Priority:
    1. Explicit _ide_type field in hook_data (from --ide CLI parameter)
    2. AI_GUARDIAN_IDE_TYPE environment variable override
    3. Auto-detection via each adapter's can_handle() method
    4. BaseAgentAdapter as default fallback

    Args:
        hook_data: Parsed JSON hook input from the IDE

    Returns:
        An instantiated HookAdapter subclass
    """
    # 1. Check explicit _ide_type field (set by --ide CLI flag, survives daemon forwarding)
    explicit_ide = hook_data.get("_ide_type", "")
    if isinstance(explicit_ide, str):
        explicit_ide = explicit_ide.lower()
    if explicit_ide and explicit_ide in _ENV_ALIAS_MAP:
        adapter = _ENV_ALIAS_MAP[explicit_ide]()
        logger.debug("Adapter selected via --ide=%s: %s", explicit_ide, adapter.name)
        return adapter

    # 2. Check environment variable override
    ide_override = os.environ.get("AI_GUARDIAN_IDE_TYPE", "").lower()
    if ide_override and ide_override in _ENV_ALIAS_MAP:
        adapter = _ENV_ALIAS_MAP[ide_override]()
        logger.debug(
            "Adapter selected via AI_GUARDIAN_IDE_TYPE=%s: %s",
            ide_override,
            adapter.name,
        )
        return adapter

    # 3. Auto-detect from hook data structure
    for adapter_cls in ADAPTER_CLASSES:
        if adapter_cls.can_handle(hook_data):
            adapter = adapter_cls()
            logger.debug("Adapter auto-detected: %s", adapter.name)
            return adapter

    # 4. Default fallback
    logger.debug("No adapter matched, falling back to BaseAgentAdapter")
    return BaseAgentAdapter()


def get_adapter_by_ide_type(ide_type) -> HookAdapter:
    """Look up an adapter by IDEType enum value.

    Used by backward-compatible wrapper functions in response_format.py.

    Args:
        ide_type: IDEType enum value

    Returns:
        An instantiated HookAdapter subclass
    """
    from ai_guardian.response_format import IDEType

    _IDE_TYPE_MAP = {
        IDEType.CLAUDE_CODE: BaseAgentAdapter,
        IDEType.CURSOR: CursorAdapter,
        IDEType.GITHUB_COPILOT: CopilotAdapter,
        IDEType.GEMINI_CLI: GeminiCLIAdapter,
        IDEType.CLINE: ClineAdapter,
        IDEType.KIRO: KiroAdapter,
        IDEType.ANTIGRAVITY: AntigravityAdapter,
        IDEType.UNKNOWN: BaseAgentAdapter,
    }
    adapter_cls = _IDE_TYPE_MAP.get(ide_type, BaseAgentAdapter)
    return adapter_cls()


__all__ = [
    "HookAdapter",
    "NormalizedHookInput",
    "detect_adapter",
    "get_adapter_by_ide_type",
    "BaseAgentAdapter",
    "CursorAdapter",
    "CopilotAdapter",
    "CodexAdapter",
    "WindsurfAdapter",
    "GeminiCLIAdapter",
    "ClineAdapter",
    "KiroAdapter",
    "AugmentAdapter",
    "AntigravityAdapter",
    "OpenCodeAdapter",
    "CrushAdapter",
    "JunieAdapter",
    "DummyAgentAdapter",
    "ADAPTER_CLASSES",
]
