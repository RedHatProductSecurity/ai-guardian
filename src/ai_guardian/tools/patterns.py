#!/usr/bin/env python3
"""
Tool policy pattern data and matching utilities.

Pure data constants (immutable deny patterns, mixed settings patterns,
hook indicator keys) and the heredoc-stripping utility used by the
tool policy checker and other modules.

Split from tool_policy.py (Issue #1494) to separate pattern data from
policy enforcement logic.
"""

import re
import shlex
from typing import List, Optional

from ai_guardian.constants import HookEvent

_HEREDOC_START_RE = re.compile(r"<<(-)?(?:(['\"])([\w-]+)\2|([\w-]+))", re.MULTILINE)

# Hardcoded critical protections - cannot be disabled or bypassed
#
# Dev source patterns removed (Issue #369) - redundant with git/PR workflow.
# AI can't push to main; all changes go through PR review.
#
# BYPASS BEHAVIOR (via _should_skip_immutable_protection):
# - Edit/Write on development source: BYPASSED (enables contributor workflow)
# - Edit/Write on config/hooks/cache/pip: ALWAYS blocked (no bypass)
# - Bash/PowerShell on config/hooks/cache/pip: ALWAYS blocked (no bypass)
#
# These patterns are checked FIRST, before any user-configured permissions
_WRITE_EDIT_DENY = [
    # Config files - ALWAYS protected (even for repo owners)
    "*ai-guardian.json",
    "*/.config/ai-guardian/*",
    "*/.ai-guardian.json",
    # Cache files - ALWAYS protected (prevents cache poisoning)
    "*/.cache/ai-guardian/*",
    # IDE hooks - ALWAYS protected (prevents disabling ai-guardian)
    # Note: */.claude/settings.json removed — handled by content-aware check (Issue #807)
    "*/.claude/hooks.json",
    "*/.cursor/hooks.json",
    "*/Cursor/hooks.json",  # Windows
    "*/.github/hooks/hooks.json",  # GitHub Copilot
    "*/.codex/hooks.json",  # OpenAI Codex (CLI + Desktop)
    "*/.codeium/windsurf/hooks.json",  # Windsurf
    # Script-based hooks - ALWAYS protected (prevents disabling ai-guardian)
    "*/.clinerules/hooks/*",  # Cline / ZooCode
    "*/.kiro/hooks/*",  # Kiro
    # Extension/plugin hooks - ALWAYS protected (prevents disabling ai-guardian)
    "*/.aider-desk/extensions/ai-guardian/*",  # AiderDesk
    "*/.openclaw/plugins/ai-guardian/*",  # OpenClaw
    # Pip-installed package code - ALWAYS protected (no git/PR review for installed packages)
    "*/site-packages/ai_guardian/*",
    # Directory markers - ALWAYS protected (prevents bypass of directory rules)
    "*/.ai-read-deny",
    "**/.ai-read-deny",
]

IMMUTABLE_DENY_PATTERNS = {
    "Write": _WRITE_EDIT_DENY,
    "Edit": _WRITE_EDIT_DENY,
    "Read": [
        # Config files - block reading security rules, patterns, allowlists (Issue #512)
        "*ai-guardian.json",
        "*/.config/ai-guardian/*",
        "*/.ai-guardian.json",
        # State files - block reading violations, logs, scanning state (Issue #512)
        "*/.local/state/ai-guardian/*",
        # Cache files - block reading cached patterns and regex (Issue #512)
        "*/.cache/ai-guardian/*",
    ],
    "Bash": [
        # Block commands that could modify protected files
        # Dev source patterns removed (Issue #369) - redundant with git/PR workflow
        # Patterns are path-specific to avoid blocking legitimate content mentioning "ai-guardian" (Issue #188)
        # sed protection - specific paths only
        "*sed*ai-guardian.json*",
        "*sed*.ai-guardian.json*",  # Config files
        "*sed*.config/ai-guardian/*",  # Config directory
        "*sed*site-packages/ai_guardian*",  # Pip-installed package
        "*sed*.claude/settings.json*",
        "*sed*.gemini/settings.json*",
        "*sed*.augment/settings.json*",
        "*sed*.cursor/hooks.json*",
        "*sed*.github/hooks/hooks.json*",  # Copilot
        "*sed*.codex/hooks.json*",  # Codex
        "*sed*.codeium/windsurf/hooks.json*",  # Windsurf
        "*sed*.clinerules/hooks/*",  # Cline / ZooCode
        "*sed*.kiro/hooks/*",  # Kiro
        "*sed*.aider-desk/extensions/ai-guardian*",  # AiderDesk
        "*sed*.openclaw/plugins/ai-guardian*",  # OpenClaw
        # awk protection - specific paths only
        "*awk*ai-guardian.json*",
        "*awk*.ai-guardian.json*",  # Config files
        "*awk*.config/ai-guardian/*",  # Config directory
        "*awk*site-packages/ai_guardian*",  # Pip-installed package
        "*awk*.claude/settings.json*",
        "*awk*.gemini/settings.json*",
        "*awk*.augment/settings.json*",
        "*awk*.cursor/hooks.json*",
        "*awk*.github/hooks/hooks.json*",  # Copilot
        "*awk*.codex/hooks.json*",  # Codex
        "*awk*.codeium/windsurf/hooks.json*",  # Windsurf
        "*awk*.clinerules/hooks/*",  # Cline / ZooCode
        "*awk*.kiro/hooks/*",  # Kiro
        "*awk*.aider-desk/extensions/ai-guardian*",  # AiderDesk
        "*awk*.openclaw/plugins/ai-guardian*",  # OpenClaw
        # vim/nano protection - specific paths only
        "*vim*ai-guardian.json*",
        "*vim*.ai-guardian.json*",  # Config files
        "*vim*.config/ai-guardian/*",  # Config directory
        "*vim*.claude/settings.json*",
        "*vim*.gemini/settings.json*",
        "*vim*.augment/settings.json*",
        "*vim*.cursor/hooks.json*",
        "*vim*.github/hooks/hooks.json*",  # Copilot
        "*vim*.codex/hooks.json*",  # Codex
        "*vim*.codeium/windsurf/hooks.json*",  # Windsurf
        "*vim*.clinerules/hooks/*",  # Cline / ZooCode
        "*vim*.kiro/hooks/*",  # Kiro
        "*nano*ai-guardian.json*",
        "*nano*.ai-guardian.json*",  # Config files
        "*nano*.config/ai-guardian/*",  # Config directory
        "*nano*.claude/settings.json*",
        "*nano*.gemini/settings.json*",
        "*nano*.augment/settings.json*",
        "*nano*.cursor/hooks.json*",
        "*nano*.github/hooks/hooks.json*",  # Copilot
        "*nano*.codex/hooks.json*",  # Codex
        "*nano*.codeium/windsurf/hooks.json*",  # Windsurf
        "*nano*.clinerules/hooks/*",  # Cline / ZooCode
        "*nano*.kiro/hooks/*",  # Kiro
        # chmod protection - specific paths only
        "*chmod*ai-guardian.json*",
        "*chmod*.ai-guardian.json*",  # Config files
        "*chmod*.config/ai-guardian/*",  # Config directory
        "*chmod*site-packages/ai_guardian*",  # Pip-installed package
        "*chmod*.claude/settings.json*",
        "*chmod*.gemini/settings.json*",
        "*chmod*.augment/settings.json*",
        "*chmod*.cursor/hooks.json*",
        "*chmod*.github/hooks/hooks.json*",  # Copilot
        "*chmod*.codex/hooks.json*",  # Codex
        "*chmod*.codeium/windsurf/hooks.json*",  # Windsurf
        "*chmod*.clinerules/hooks/*",  # Cline / ZooCode
        "*chmod*.kiro/hooks/*",  # Kiro
        "*chmod*.aider-desk/extensions/ai-guardian*",  # AiderDesk
        "*chmod*.openclaw/plugins/ai-guardian*",  # OpenClaw
        # chattr protection - specific paths only
        "*chattr*ai-guardian.json*",
        "*chattr*.ai-guardian.json*",  # Config files
        "*chattr*.config/ai-guardian/*",  # Config directory
        "*chattr*.claude*",
        "*chattr*.cursor*",
        "*chattr*.gemini*",
        "*chattr*.augment*",
        "*chattr*.github/hooks*",  # Copilot
        "*chattr*.codex*",  # Codex
        "*chattr*.codeium*",  # Windsurf
        "*chattr*.clinerules*",  # Cline / ZooCode
        "*chattr*.kiro*",  # Kiro
        # Redirect protection - specific paths only
        "*>*ai-guardian.json*",
        "*>*.ai-guardian.json*",  # Config files
        "*>*.config/ai-guardian/*",  # Config directory
        "*>*site-packages/ai_guardian*",  # Pip-installed package
        "*>*.claude/settings.json*",
        "*>*.gemini/settings.json*",
        "*>*.augment/settings.json*",
        "*>*.cursor/hooks.json*",
        "*>*.github/hooks/hooks.json*",  # Copilot
        "*>*.codex/hooks.json*",  # Codex
        "*>*.codeium/windsurf/hooks.json*",  # Windsurf
        "*>*.clinerules/hooks/*",  # Cline / ZooCode
        "*>*.kiro/hooks/*",  # Kiro
        "*>*.aider-desk/extensions/ai-guardian*",  # AiderDesk
        "*>*.openclaw/plugins/ai-guardian*",  # OpenClaw
        # rm/mv protection - specific paths only
        "*rm*ai-guardian.json*",
        "*rm*.claude/settings.json*",
        "*rm*.gemini/settings.json*",
        "*rm*.augment/settings.json*",
        "*rm*.cursor/hooks.json*",
        "*rm*.github/hooks/hooks.json*",  # Copilot
        "*rm*.codex/hooks.json*",  # Codex
        "*rm*.codeium/windsurf/hooks.json*",  # Windsurf
        "*rm*.clinerules/hooks*",  # Cline / ZooCode
        "*rm*.kiro/hooks*",  # Kiro
        "*rm*.aider-desk/extensions/ai-guardian*",  # AiderDesk
        "*rm*.openclaw/plugins/ai-guardian*",  # OpenClaw
        "*mv*ai-guardian.json*",
        "*mv*.claude/settings.json*",
        "*mv*.gemini/settings.json*",
        "*mv*.augment/settings.json*",
        "*mv*.cursor/hooks.json*",
        "*mv*.github/hooks/hooks.json*",  # Copilot
        "*mv*.codex/hooks.json*",  # Codex
        "*mv*.codeium/windsurf/hooks.json*",  # Windsurf
        "*mv*.clinerules/hooks*",  # Cline / ZooCode
        "*mv*.kiro/hooks*",  # Kiro
        "*mv*.aider-desk/extensions/ai-guardian*",  # AiderDesk
        "*mv*.openclaw/plugins/ai-guardian*",  # OpenClaw
        # Protect ai-guardian cache from manipulation (prevents cache poisoning)
        "*rm*.cache/ai-guardian/*",
        "*mv*.cache/ai-guardian/*",
        "*sed*.cache/ai-guardian/*",
        "*awk*.cache/ai-guardian/*",
        "*>*.cache/ai-guardian/*",
        "*chmod*.cache/ai-guardian/*",
        "*chattr*.cache/ai-guardian/*",
        "*vim*.cache/ai-guardian/*",
        "*nano*.cache/ai-guardian/*",
        # Protect .ai-read-deny marker files from bash manipulation
        "*rm*.ai-read-deny*",  # Block: rm .ai-read-deny
        "*rm*/.ai-read-deny*",  # Block: rm /path/.ai-read-deny
        "*mv*.ai-read-deny*",  # Block: mv .ai-read-deny
        "*sed*.ai-read-deny*",  # Block: sed on .ai-read-deny
        "*awk*.ai-read-deny*",  # Block: awk on .ai-read-deny
        "*>*.ai-read-deny*",  # Block: echo > .ai-read-deny
        "*chmod*.ai-read-deny*",  # Block: chmod .ai-read-deny
        "*chattr*.ai-read-deny*",  # Block: chattr .ai-read-deny
        "*vim*.ai-read-deny*",  # Block: vim .ai-read-deny
        "*nano*.ai-read-deny*",  # Block: nano .ai-read-deny
        # Block reading ai-guardian config/state/cache via Bash (Issue #512)
        # Prevents agent from reading security rules, patterns, violations, logs
        "*cat*/.config/ai-guardian/*",
        "*cat*/.local/state/ai-guardian/*",
        "*cat*/.cache/ai-guardian/*",
        "*cat*ai-guardian.json*",
        "*grep*/.config/ai-guardian/*",
        "*grep*/.local/state/ai-guardian/*",
        "*head*ai-guardian.log*",
        "*tail*ai-guardian.log*",
        "*less*ai-guardian.json*",
        "*more*ai-guardian.json*",
        "*python*/.config/ai-guardian/*",
        "*python3*/.config/ai-guardian/*",
        "*python*ai-guardian.json*",
        "*python3*ai-guardian.json*",
        "*xxd*/.config/ai-guardian/*",
        "*xxd*ai-guardian.json*",
        "*od*/.config/ai-guardian/*",
        "*strings*/.config/ai-guardian/*",
        "*strings*ai-guardian.json*",
        "*base64*/.config/ai-guardian/*",
        "*base64*ai-guardian.json*",
        "*tee*/.config/ai-guardian/*",
        "*tee*ai-guardian.json*",
        "*curl*file://*ai-guardian*",
    ],
    "PowerShell": [
        # Dev source patterns removed (Issue #369) - redundant with git/PR workflow
        # Patterns are path-specific to avoid blocking legitimate content mentioning "ai-guardian" (Issue #188)
        # Protect ai-guardian config files - specific paths only
        "*Remove-Item*ai-guardian.json*",
        "*Remove-Item*.ai-guardian.json*",
        "*Remove-Item*.config/ai-guardian/*",
        "*Remove-Item*.config\\ai-guardian\\*",
        "*Move-Item*ai-guardian.json*",
        "*Move-Item*.ai-guardian.json*",
        "*Move-Item*.config/ai-guardian/*",
        "*Move-Item*.config\\ai-guardian\\*",
        "*Rename-Item*ai-guardian.json*",
        "*Rename-Item*.ai-guardian.json*",
        "*Rename-Item*.config/ai-guardian/*",
        "*Rename-Item*.config\\ai-guardian\\*",
        "*Set-Content*ai-guardian.json*",
        "*Set-Content*.ai-guardian.json*",
        "*Set-Content*.config/ai-guardian/*",
        "*Set-Content*.config\\ai-guardian\\*",
        "*Clear-Content*ai-guardian.json*",
        "*Clear-Content*.ai-guardian.json*",
        "*Clear-Content*.config/ai-guardian/*",
        "*Clear-Content*.config\\ai-guardian\\*",
        "*Out-File*ai-guardian.json*",
        "*Out-File*.ai-guardian.json*",
        "*Out-File*.config/ai-guardian/*",
        "*Out-File*.config\\ai-guardian\\*",
        "*Copy-Item*ai-guardian.json*",
        "*Copy-Item*.ai-guardian.json*",
        "*Copy-Item*.config/ai-guardian/*",
        "*Copy-Item*.config\\ai-guardian\\*",
        # Protect ai-guardian cache (prevents cache poisoning)
        "*Remove-Item*.cache/ai-guardian/*",
        "*Remove-Item*.cache\\ai-guardian\\*",
        "*Move-Item*.cache/ai-guardian/*",
        "*Move-Item*.cache\\ai-guardian\\*",
        "*Set-Content*.cache/ai-guardian/*",
        "*Set-Content*.cache\\ai-guardian\\*",
        "*Clear-Content*.cache/ai-guardian/*",
        "*Clear-Content*.cache\\ai-guardian\\*",
        "*Out-File*.cache/ai-guardian/*",
        "*Out-File*.cache\\ai-guardian\\*",
        "*>*.cache/ai-guardian/*",
        "*>*.cache\\ai-guardian\\*",
        # Protect IDE settings/hook files (Unix paths)
        "*Remove-Item*.claude/settings.json*",
        "*Remove-Item*.cursor/hooks.json*",
        "*Remove-Item*Claude/settings.json*",
        "*Remove-Item*Cursor/hooks.json*",
        "*Remove-Item*.gemini/settings.json*",
        "*Remove-Item*.augment/settings.json*",
        "*Move-Item*.claude/settings.json*",
        "*Move-Item*.cursor/hooks.json*",
        "*Move-Item*Claude/settings.json*",
        "*Move-Item*Cursor/hooks.json*",
        "*Move-Item*.gemini/settings.json*",
        "*Move-Item*.augment/settings.json*",
        "*Rename-Item*.claude/settings.json*",
        "*Rename-Item*.cursor/hooks.json*",
        "*Rename-Item*Claude/settings.json*",
        "*Rename-Item*Cursor/hooks.json*",
        "*Rename-Item*.gemini/settings.json*",
        "*Rename-Item*.augment/settings.json*",
        "*Set-Content*.claude/settings.json*",
        "*Set-Content*.cursor/hooks.json*",
        "*Set-Content*Claude/settings.json*",
        "*Set-Content*Cursor/hooks.json*",
        "*Set-Content*.gemini/settings.json*",
        "*Set-Content*.augment/settings.json*",
        "*Clear-Content*.claude/settings.json*",
        "*Clear-Content*.cursor/hooks.json*",
        "*Clear-Content*Claude/settings.json*",
        "*Clear-Content*Cursor/hooks.json*",
        "*Clear-Content*.gemini/settings.json*",
        "*Clear-Content*.augment/settings.json*",
        "*Out-File*.claude/settings.json*",
        "*Out-File*.cursor/hooks.json*",
        "*Out-File*Claude/settings.json*",
        "*Out-File*Cursor/hooks.json*",
        "*Out-File*.gemini/settings.json*",
        "*Out-File*.augment/settings.json*",
        # Protect additional IDE hook files (Copilot, Codex, Windsurf)
        "*Remove-Item*.github/hooks/hooks.json*",
        "*Remove-Item*.codex/hooks.json*",
        "*Remove-Item*.codeium/windsurf/hooks.json*",
        "*Move-Item*.github/hooks/hooks.json*",
        "*Move-Item*.codex/hooks.json*",
        "*Move-Item*.codeium/windsurf/hooks.json*",
        "*Rename-Item*.github/hooks/hooks.json*",
        "*Rename-Item*.codex/hooks.json*",
        "*Rename-Item*.codeium/windsurf/hooks.json*",
        "*Set-Content*.github/hooks/hooks.json*",
        "*Set-Content*.codex/hooks.json*",
        "*Set-Content*.codeium/windsurf/hooks.json*",
        "*Clear-Content*.github/hooks/hooks.json*",
        "*Clear-Content*.codex/hooks.json*",
        "*Clear-Content*.codeium/windsurf/hooks.json*",
        "*Out-File*.github/hooks/hooks.json*",
        "*Out-File*.codex/hooks.json*",
        "*Out-File*.codeium/windsurf/hooks.json*",
        # Protect script-based hook directories (Cline/ZooCode, Kiro)
        "*Remove-Item*.clinerules/hooks*",
        "*Remove-Item*.kiro/hooks*",
        "*Move-Item*.clinerules/hooks*",
        "*Move-Item*.kiro/hooks*",
        "*Rename-Item*.clinerules/hooks*",
        "*Rename-Item*.kiro/hooks*",
        "*Set-Content*.clinerules/hooks*",
        "*Set-Content*.kiro/hooks*",
        "*Clear-Content*.clinerules/hooks*",
        "*Clear-Content*.kiro/hooks*",
        "*Out-File*.clinerules/hooks*",
        "*Out-File*.kiro/hooks*",
        # Protect extension/plugin hooks (AiderDesk, OpenClaw)
        "*Remove-Item*.aider-desk/extensions/ai-guardian*",
        "*Remove-Item*.openclaw/plugins/ai-guardian*",
        "*Move-Item*.aider-desk/extensions/ai-guardian*",
        "*Move-Item*.openclaw/plugins/ai-guardian*",
        "*Set-Content*.aider-desk/extensions/ai-guardian*",
        "*Set-Content*.openclaw/plugins/ai-guardian*",
        "*Clear-Content*.aider-desk/extensions/ai-guardian*",
        "*Clear-Content*.openclaw/plugins/ai-guardian*",
        "*Out-File*.aider-desk/extensions/ai-guardian*",
        "*Out-File*.openclaw/plugins/ai-guardian*",
        # Protect IDE hook files (Windows backslash paths)
        "*Remove-Item*Claude\\settings.json*",
        "*Remove-Item*Cursor\\hooks.json*",
        "*Move-Item*Claude\\settings.json*",
        "*Move-Item*Cursor\\hooks.json*",
        "*Rename-Item*Claude\\settings.json*",
        "*Rename-Item*Cursor\\hooks.json*",
        "*Set-Content*Claude\\settings.json*",
        "*Set-Content*Cursor\\hooks.json*",
        "*Clear-Content*Claude\\settings.json*",
        "*Clear-Content*Cursor\\hooks.json*",
        "*Out-File*Claude\\settings.json*",
        "*Out-File*Cursor\\hooks.json*",
        # Protect pip-installed package (no git/PR review for installed packages)
        "*Remove-Item*site-packages/ai_guardian/*",
        "*Remove-Item*site-packages\\ai_guardian\\*",
        "*Set-Content*site-packages/ai_guardian/*",
        "*Set-Content*site-packages\\ai_guardian\\*",
        "*Clear-Content*site-packages/ai_guardian/*",
        "*Clear-Content*site-packages\\ai_guardian\\*",
        "*Out-File*site-packages/ai_guardian/*",
        "*Out-File*site-packages\\ai_guardian\\*",
        # Protect against PowerShell redirections - specific paths only
        "*>*ai-guardian.json*",
        "*>*.ai-guardian.json*",
        "*>*.config/ai-guardian/*",
        "*>*.config\\ai-guardian\\*",
        "*>>*ai-guardian.json*",
        "*>>*.ai-guardian.json*",
        "*>>*.config/ai-guardian/*",
        "*>>*.config\\ai-guardian\\*",
        "*>*.claude/settings.json*",
        "*>*.cursor/hooks.json*",
        "*>*Claude/settings.json*",
        "*>*Cursor/hooks.json*",
        "*>*.gemini/settings.json*",
        "*>*.augment/settings.json*",
        "*>*.github/hooks/hooks.json*",
        "*>*.codex/hooks.json*",
        "*>*.codeium/windsurf/hooks.json*",
        "*>*.clinerules/hooks*",
        "*>*.kiro/hooks*",
        "*>*.aider-desk/extensions/ai-guardian*",
        "*>*.openclaw/plugins/ai-guardian*",
        # Protect .ai-read-deny marker files from PowerShell manipulation
        "*Remove-Item*.ai-read-deny*",
        "*Move-Item*.ai-read-deny*",
        "*Rename-Item*.ai-read-deny*",
        "*Set-Content*.ai-read-deny*",
        "*Clear-Content*.ai-read-deny*",
        "*Out-File*.ai-read-deny*",
        "*Copy-Item*.ai-read-deny*",
        "*>*.ai-read-deny*",
        # PowerShell aliases (del, erase, rm, mv, etc.) - specific paths only
        "*del *ai-guardian.json*",
        "*del *.ai-guardian.json*",
        "*del *.config/ai-guardian/*",
        "*del *.config\\ai-guardian\\*",
        "*erase *ai-guardian.json*",
        "*erase *.ai-guardian.json*",
        "*erase *.config/ai-guardian/*",
        "*erase *.config\\ai-guardian\\*",
        "*rm *ai-guardian.json*",
        "*rm *.ai-guardian.json*",
        "*rm *.config/ai-guardian/*",
        "*rm *.config\\ai-guardian\\*",
        "*rmdir *ai-guardian.json*",
        "*rmdir *.ai-guardian.json*",
        "*rmdir *.config/ai-guardian/*",
        "*rmdir *.config\\ai-guardian\\*",
        "*mv *ai-guardian.json*",
        "*mv *.ai-guardian.json*",
        "*mv *.config/ai-guardian/*",
        "*mv *.config\\ai-guardian\\*",
        "*move *ai-guardian.json*",
        "*move *.ai-guardian.json*",
        "*move *.config/ai-guardian/*",
        "*move *.config\\ai-guardian\\*",
        "*ren *ai-guardian.json*",
        "*ren *.ai-guardian.json*",
        "*ren *.config/ai-guardian/*",
        "*ren *.config\\ai-guardian\\*",
        "*copy *ai-guardian.json*",
        "*copy *.ai-guardian.json*",
        "*copy *.config/ai-guardian/*",
        "*copy *.config\\ai-guardian\\*",
        "*rm *.claude/settings.json*",
        "*del *.claude/settings.json*",
        "*rm *.gemini/settings.json*",
        "*del *.gemini/settings.json*",
        "*rm *.augment/settings.json*",
        "*del *.augment/settings.json*",
        "*rm *.cursor/hooks.json*",
        "*del *.cursor/hooks.json*",
        "*rm *.github/hooks/hooks.json*",
        "*del *.github/hooks/hooks.json*",
        "*rm *.codex/hooks.json*",
        "*del *.codex/hooks.json*",
        "*rm *.codeium/windsurf/hooks.json*",
        "*del *.codeium/windsurf/hooks.json*",
        "*rm *.clinerules/hooks*",
        "*del *.clinerules/hooks*",
        "*rm *.kiro/hooks*",
        "*del *.kiro/hooks*",
        "*rm *.aider-desk/extensions/ai-guardian*",
        "*del *.aider-desk/extensions/ai-guardian*",
        "*rm *.openclaw/plugins/ai-guardian*",
        "*del *.openclaw/plugins/ai-guardian*",
        "*rm *.ai-read-deny*",
        "*del *.ai-read-deny*",
        "*mv *.ai-read-deny*",
        "*move *.ai-read-deny*",
        # Block reading ai-guardian config/state/cache via PowerShell (Issue #512)
        "*Get-Content*/.config/ai-guardian/*",
        "*Get-Content*.config\\ai-guardian\\*",
        "*Get-Content*/.local/state/ai-guardian/*",
        "*Get-Content*.local\\state\\ai-guardian\\*",
        "*Get-Content*/.cache/ai-guardian/*",
        "*Get-Content*.cache\\ai-guardian\\*",
        "*Get-Content*ai-guardian.json*",
        "*Select-String*/.config/ai-guardian/*",
        "*Select-String*.config\\ai-guardian\\*",
        "*Select-String*/.local/state/ai-guardian/*",
        "*Select-String*.local\\state\\ai-guardian\\*",
        "*type*ai-guardian.json*",
    ],
}

# Mixed-settings files: contain BOTH hooks AND user preferences (Issue #807).
# For these files, only block modifications to the hooks section via Edit/Write.
# Bash/PowerShell still block the entire file (can't do content-aware checks).
MIXED_SETTINGS_PATTERNS = [
    "*/.claude/settings.json",
    "*/Claude/settings.json",  # Windows
    "*/.gemini/settings.json",
    "*/.augment/settings.json",
]

# Hook-related JSON keys that indicate hook modification.
HOOK_INDICATOR_KEYS = {
    "hooks",
    HookEvent.PROMPT.display_name,
    HookEvent.PRE_TOOL_USE.display_name,
    HookEvent.POST_TOOL_USE.display_name,
    "BeforeAgent",
    "BeforeTool",
    "AfterTool",
    "PromptSubmit",
}

# Regex matching hook-related JSON keys (e.g. "hooks": or 'PreToolUse':)
_HOOK_KEY_PATTERN = re.compile(
    r'["\'](' + "|".join(re.escape(k) for k in sorted(HOOK_INDICATOR_KEYS)) + r')["\']'
    r"\s*:",
)


def _strip_bash_heredoc_content(command: str) -> str:
    """
    Strip heredoc content from bash commands for pattern matching.

    This prevents false positives when heredoc content contains protected
    keywords or patterns. Only the command structure is checked, not the
    heredoc data.

    Supports heredoc formats:
    - <<EOF ... EOF
    - <<'EOF' ... EOF (quoted)
    - <<"EOF" ... EOF (quoted)
    - <<-EOF ... EOF (dash format for tab stripping)

    Args:
        command: The bash command string (may be multi-line)

    Returns:
        Command with heredoc content replaced by placeholders

    Example:
        Input:  cat <<'EOF'\\nrm ai-guardian.json\\nEOF
        Output: cat <<'EOF'\\nEOF
    """
    if not command or "<<" not in command:
        return command

    # Find all heredocs and their positions
    replacements = []

    for match in _HEREDOC_START_RE.finditer(command):
        # Extract delimiter (group 3 if quoted, group 4 if unquoted)
        delimiter = match.group(3) if match.group(3) else match.group(4)
        heredoc_start = match.end()  # Position after the delimiter

        # Find the first newline after the heredoc delimiter
        # The heredoc content starts AFTER this newline (commands can follow on same line)
        first_newline = command.find("\n", heredoc_start)
        if first_newline == -1:
            # No newline found, no heredoc content to strip
            continue

        content_start = first_newline  # Position of the newline before content

        # Find the end delimiter (must be on its own line)
        # Pattern: newline + optional whitespace + delimiter + end of line
        end_pattern = re.compile(
            rf"\n\s*{re.escape(delimiter)}\s*(?=\n|$)", re.MULTILINE
        )

        end_match = end_pattern.search(command, content_start)
        if end_match:
            # Mark this range for removal (content between newlines)
            # Remove from after the first newline to before the delimiter newline
            replacements.append((content_start, end_match.start()))

    # Apply replacements in reverse order to maintain positions
    result = command
    for start, end in reversed(replacements):
        result = result[:start] + result[end:]

    return result


_SHELL_COMMAND_SEPARATORS = frozenset(
    {";", "&&", "||", "|", "&", "(", ")", "`", "{", "}"}
)
_SHELL_CONTROL_WORDS = frozenset(
    {"do", "then", "else", "elif", "if", "while", "until", "case"}
)
_AI_GUARDIAN_EXECUTABLES = frozenset(
    {"ai-guardian", "ai-guardian.exe", "ai-guardian.cmd", "ai-guardian.bat"}
)
_AI_GUARDIAN_MODULE_PREFIX = "ai_guardian"
_DIRECT_COMMAND_WRAPPERS = frozenset(
    {
        "command",
        "exec",
        "env",
        "eval",
        "ionice",
        "nice",
        "nohup",
        "npx",
        "doas",
        "runuser",
        "setsid",
        "stdbuf",
        "sudo",
        "time",
        "timeout",
        "unbuffer",
        "uvx",
        "bunx",
        "xargs",
    }
)
_SCRIPT_COMMAND_WRAPPERS = frozenset(
    {
        "bash",
        "cmd",
        "dash",
        "fish",
        "ksh",
        "powershell",
        "pwsh",
        "sh",
        "su",
        "zsh",
    }
)
_LAUNCHER_ACTIONS = {
    "conda": frozenset({"run"}),
    "npm": frozenset({"exec", "run"}),
    "pdm": frozenset({"run"}),
    "pipenv": frozenset({"run"}),
    "pipx": frozenset({"run"}),
    "pnpm": frozenset({"dlx", "exec", "run"}),
    "poetry": frozenset({"run"}),
    "uv": frozenset({"run", "tool"}),
    "yarn": frozenset({"dlx", "exec", "run"}),
}
_OPTION_ARGUMENTS = frozenset(
    {
        "-c",
        "-d",
        "-D",
        "-e",
        "-f",
        "-g",
        "-G",
        "-h",
        "-n",
        "-o",
        "-p",
        "-r",
        "-t",
        "-u",
        "-w",
        "--chdir",
        "--directory",
        "--file",
        "--group",
        "--host",
        "--project",
        "--prompt",
        "--python",
        "--spec",
        "--user",
        "--with",
    }
)


def _clean_command_token(token: str) -> str:
    """Remove shell quoting that remains in non-POSIX tokenization."""
    value = str(token).strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    return value.rstrip(",")


def _command_basename(token: str) -> str:
    """Return a cross-platform executable basename."""
    value = _clean_command_token(token).replace("\\", "/").rstrip("/")
    return value.rsplit("/", 1)[-1].lower()


def _is_ai_guardian_executable(token: str) -> bool:
    return _command_basename(token) in _AI_GUARDIAN_EXECUTABLES


def _is_python_executable(token: str) -> bool:
    basename = _command_basename(token)
    return bool(
        re.fullmatch(
            r"(?:python(?:3(?:\.\d+)?)?|py|pypy(?:3(?:\.\d+)?))(?:\.exe)?", basename
        )
    )


def _is_script_shell(token: str) -> bool:
    basename = _command_basename(token)
    return basename in _SCRIPT_COMMAND_WRAPPERS or basename in {"cmd.exe"}


def _tokenize_shell_command(command: str, *, posix: bool) -> List[str]:
    """Tokenize a shell command without evaluating it."""
    normalized = command.replace("\r\n", "\n").replace("\r", "\n").replace("\n", ";")
    try:
        lexer = shlex.shlex(
            normalized,
            posix=posix,
            punctuation_chars=";&|()<>`{}",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except (TypeError, ValueError):
        # An incomplete quote will not be executed as a valid shell command.
        # Returning no tokens also avoids falling back to substring matching.
        return []


def _command_segments(tokens: List[str]) -> List[List[str]]:
    """Split shell tokens at operators that start another command."""
    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in _SHELL_COMMAND_SEPARATORS:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _skip_option_arguments(tokens: List[str], start: int) -> int:
    """Skip common wrapper options and their values."""
    index = start
    while index < len(tokens):
        token = _clean_command_token(tokens[index])
        if token == "--":
            return index + 1
        if not token.startswith("-") or token == "-":
            return index
        if "=" not in token and token in _OPTION_ARGUMENTS:
            index += 2
        else:
            index += 1
    return index


def _skip_env_arguments(tokens: List[str], start: int) -> int:
    """Find the command after env assignments/options."""
    index = start
    while index < len(tokens):
        token = _clean_command_token(tokens[index])
        if token == "--":
            return index + 1
        if "=" in token and not token.startswith("="):
            index += 1
            continue
        if token.startswith("-") and token != "-":
            if "=" not in token and token in _OPTION_ARGUMENTS:
                index += 2
            else:
                index += 1
            continue
        return index
    return index


def _launcher_child_index(tokens: List[str], start: int, command: str) -> Optional[int]:
    """Return the index of the child command for a known launcher."""
    if command == "env":
        return _skip_env_arguments(tokens, start)

    if command in {
        "command",
        "doas",
        "exec",
        "ionice",
        "nice",
        "nohup",
        "runuser",
        "setsid",
        "stdbuf",
        "sudo",
        "time",
        "unbuffer",
        "npx",
        "uvx",
        "bunx",
    }:
        return _skip_option_arguments(tokens, start)

    if command == "timeout":
        index = _skip_option_arguments(tokens, start)
        if index < len(tokens):
            index += 1  # timeout duration
        return _skip_option_arguments(tokens, index)

    if command == "xargs":
        return _skip_option_arguments(tokens, start)

    actions = _LAUNCHER_ACTIONS.get(command)
    if actions:
        index = start
        while index < len(tokens):
            token = _clean_command_token(tokens[index]).lower()
            if token in actions:
                # `uv tool run` has one additional action before the command.
                if command == "uv" and token == "tool":
                    index += 1
                    continue
                return _skip_option_arguments(tokens, index + 1)
            if token == "--":
                return index + 1
            if token.startswith("-"):
                index = _skip_option_arguments(tokens, index)
            else:
                index += 1
        return None

    return None


def _script_child_index(tokens: List[str], start: int) -> Optional[int]:
    """Return the argument containing a script for sh/powershell/cmd."""
    for index in range(start, len(tokens)):
        token = _clean_command_token(tokens[index]).lower()
        if token in {"-c", "-lc", "-ic", "/c", "/k", "-command", "-cmd"}:
            return index + 1 if index + 1 < len(tokens) else None
    return None


def _contains_cli_in_tokens(tokens: List[str], depth: int = 0) -> bool:
    """Check one shell command segment for a real CLI invocation."""
    if depth > 8 or not tokens:
        return False

    index = 0
    while (
        index < len(tokens)
        and _clean_command_token(tokens[index]) in _SHELL_CONTROL_WORDS
    ):
        index += 1
    if index >= len(tokens):
        return False

    command_token = _clean_command_token(tokens[index])
    command = _command_basename(command_token)
    if _is_ai_guardian_executable(command_token):
        return True

    if _is_python_executable(command_token):
        for module_index in range(index + 1, len(tokens) - 1):
            option = _clean_command_token(tokens[module_index]).lower()
            if option == "-m" or option == "-m=":
                module = _clean_command_token(tokens[module_index + 1]).lower()
                if module == _AI_GUARDIAN_MODULE_PREFIX or module.startswith(
                    f"{_AI_GUARDIAN_MODULE_PREFIX}."
                ):
                    return True
            if option in {"-c", "-c="}:
                break
        return False

    if _is_script_shell(command_token):
        child_index = _script_child_index(tokens, index + 1)
        if child_index is not None:
            return _contains_cli_in_command_string(tokens[child_index], depth + 1)
        return False

    if command in _DIRECT_COMMAND_WRAPPERS:
        child_index = _launcher_child_index(tokens, index + 1, command)
        if child_index is not None:
            return _contains_cli_in_tokens(tokens[child_index:], depth + 1)
        return False

    if command in _LAUNCHER_ACTIONS:
        child_index = _launcher_child_index(tokens, index + 1, command)
        if child_index is not None:
            return _contains_cli_in_tokens(tokens[child_index:], depth + 1)
        return False

    if command in _SHELL_CONTROL_WORDS:
        return _contains_cli_in_tokens(tokens[index + 1 :], depth + 1)

    if command in {"invoke-expression", "iex", "start-process"}:
        for child_token in tokens[index + 1 :]:
            if _contains_cli_in_command_string(child_token, depth + 1):
                return True
        return False

    return False


def _contains_cli_in_command_string(value: str, depth: int) -> bool:
    """Recursively inspect a command string passed to a shell wrapper."""
    if not isinstance(value, str):
        return False
    for posix in (True, False):
        tokens = _tokenize_shell_command(value, posix=posix)
        if any(
            _contains_cli_in_tokens(segment, depth)
            for segment in _command_segments(tokens)
        ):
            return True
    return False


def is_ai_guardian_cli_command(command: str) -> bool:
    """Return whether *command* launches the AI Guardian CLI.

    Detection is command-position aware. It covers direct and path-qualified
    executables, Python module launches, common environment/package launchers,
    and shell wrappers while ignoring ordinary arguments and documentation
    text that merely mentions AI Guardian.
    """
    if not isinstance(command, str) or not command.strip():
        return False

    command = _strip_bash_heredoc_content(command)
    for posix in (True, False):
        tokens = _tokenize_shell_command(command, posix=posix)
        if any(
            _contains_cli_in_tokens(segment) for segment in _command_segments(tokens)
        ):
            return True
    return False
