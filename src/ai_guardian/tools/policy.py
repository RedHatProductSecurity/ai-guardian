#!/usr/bin/env python3
"""
Tool Allow/Deny List Policy Checker

Permission system using matcher-based rules in JSON configuration:
- permissions: Array of {matcher, allow, deny} objects
- Matcher determines which tools the rule applies to
- Allow/deny patterns check against tool-specific values
- Auto-discovery via permissions_directories

Configuration file: ~/.config/ai-guardian/ai-guardian.json
"""

import fnmatch
import json
import logging
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Union

from ai_guardian.constants import AUGMENT_TOOL_MAP, HookEvent

try:
    from jsonschema import Draft7Validator, ValidationError as JsonSchemaValidationError

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    Draft7Validator = None
    JsonSchemaValidationError = None

from ai_guardian.config.utils import (
    format_config_paths,
    get_all_config_paths,
    get_config_dir,
    get_project_config_path,
    is_expired,
    is_feature_enabled,
)
from ai_guardian.config.loaders import _load_json_config
from ai_guardian.constants import ViolationType
from ai_guardian.tools.patterns import (
    IMMUTABLE_DENY_PATTERNS,
    MIXED_SETTINGS_PATTERNS,
    HOOK_INDICATOR_KEYS,
    _HOOK_KEY_PATTERN,
    _strip_bash_heredoc_content,
)

logger = logging.getLogger(__name__)

# Import violation logger
try:
    from ai_guardian.violations.logger import ViolationLogger

    HAS_VIOLATION_LOGGER = True
except ImportError:
    HAS_VIOLATION_LOGGER = False
    logger.debug("violation_logger module not available")

# Import SSRF protector
try:
    from ai_guardian.scanners.ssrf import SSRFProtector

    HAS_SSRF_PROTECTOR = True
except ImportError:
    HAS_SSRF_PROTECTOR = False
    logger.debug("ssrf_protector module not available")

# Import config exfiltration scanner
try:
    from ai_guardian.scanners.config_scanner import ConfigFileScanner

    HAS_CONFIG_SCANNER = True
except ImportError:
    HAS_CONFIG_SCANNER = False
    logger.debug("config_scanner module not available")


class ToolPolicyChecker:
    """
    Check if tool invocations are allowed based on matcher-based permissions.

    Permission format (array of rules):
    [
      {
        "matcher": "Skill",      # Tool name pattern to match
        "allow": ["daf-*"],      # Patterns to allow
        "deny": []               # Patterns to deny
      }
    ]

    Default: deny-wins (deny patterns override allow patterns)
    """

    # Class-level schema validator (loaded once and cached)
    _schema_validator = None

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize policy checker.

        Args:
            config: Optional configuration dict. If None, loads from disk.
        """
        self._config_warnings: List[str] = []
        self.config = config or self._load_config()
        self.last_deny_action = None
        self.last_deny_matched_pattern = None
        self.last_deny_check_value = None

    def _should_skip_immutable_protection(self, file_path: str, tool_name: str) -> bool:
        """
        Check if immutable protection should be bypassed for this file.

        Bypass allows:
        - Editing source code files IN the ai-guardian development repository
        - Does NOT allow editing config files, hooks, or cache (NEVER bypassed)
        - Does NOT allow editing pip-installed packages (production code)

        Security model:
        - Config/hooks/cache: ALWAYS protected (even for repo owners)
        - Pip-installed code: ALWAYS protected (production deployment)
        - Development source: ALLOWED for contributors (fork + PR workflow)
          - Changes only affect local development environment
          - Relies on PR review process for security
          - Enables standard open-source contribution workflow

        Args:
            file_path: Path to the file being accessed
            tool_name: Name of the tool being used

        Returns:
            bool: True if bypass should apply, False otherwise
        """
        # PRIORITY 1: Config/hook/cache files - NEVER bypass (even for repo owners)
        # Note: Mixed settings files (settings.json for Claude/Gemini/Augment) are NOT
        # listed here — they are handled by content-aware checking in check_tool_allowed()
        config_patterns = [
            "*ai-guardian.json",  # Config files
            "*/.ai-guardian.json",  # Project config
            "*/.config/ai-guardian/*",  # Config directory
            "*/.cache/ai-guardian/*",  # Cache files (prevents poisoning)
            "*/.claude/hooks.json",  # IDE hooks-only files
            "*/.cursor/hooks.json",
            "*/Cursor/hooks.json",
            "*/.github/hooks/hooks.json",  # Copilot
            "*/.codex/hooks.json",  # Codex
            "*/.codeium/windsurf/hooks.json",  # Windsurf
            "*/.clinerules/hooks/*",  # Cline / ZooCode (script-based)
            "*/.kiro/hooks/*",  # Kiro (script-based)
            "*/.aider-desk/extensions/ai-guardian/*",  # AiderDesk
            "*/.openclaw/plugins/ai-guardian/*",  # OpenClaw
            "*/.ai-read-deny",  # Directory markers
            "**/.ai-read-deny",
        ]

        file_path_obj = Path(file_path)
        for pattern in config_patterns:
            # Use Path.match() for ** patterns, fnmatch for simple * patterns
            if "**" in pattern:
                matches = file_path_obj.match(pattern)
            else:
                matches = fnmatch.fnmatch(file_path, pattern)

            if matches:
                logger.debug(f"Config file always protected: {file_path}")
                return False  # Always protected, even for repo owners

        # PRIORITY 2: Is this a source code file IN the ai-guardian development repo?
        # Only applies to file-path tools (Edit, Write, Read), NOT command tools (Bash, PowerShell)
        # Command tools are checked by immutable patterns to prevent rm/Remove-Item/etc.
        is_file_path_tool = tool_name in ["Edit", "Write", "Read", "NotebookEdit"]

        if not is_file_path_tool:
            logger.debug(f"Command tool {tool_name} - not checking source patterns")
            return False  # Command tools always check immutable patterns

        source_patterns = [
            "*/ai-guardian/src/ai_guardian/*",  # Source directory
            "*/ai-guardian/tests/*",  # Tests
            "*/ai-guardian/*.md",  # Documentation
            "*/ai-guardian/*.py",  # Root Python files
            "*/ai-guardian/*.toml",  # Config files like pyproject.toml
            "*/ai-guardian/*.txt",  # Requirements, etc.
            "*/ai-guardian/.github/*",  # GitHub workflows
            "*/ai-guardian/CHANGELOG.md",  # Changelog
            "*/ai-guardian/RELEASING.md",  # Release docs
        ]

        is_source_file = any(fnmatch.fnmatch(file_path, p) for p in source_patterns)
        if not is_source_file:
            logger.debug(f"Not a source file: {file_path}")
            return False  # Not a source file, keep protected

        # PRIORITY 3: Allow editing development source code with file-path tools
        # This enables standard open-source workflow (fork + PR + review)
        # Security relies on:
        # - PR review process (maintainers review all changes)
        # - CI/CD testing (detects behavior changes)
        # - Public review (community scrutiny)
        # - Pip-installed code still protected (production deployments)
        logger.info(f"✅ Development source file: allowing {tool_name} on {file_path}")
        logger.info(
            "   Note: Changes affect local development only, not pip-installed versions"
        )
        return True

    def _check_mixed_settings_hook_modification(
        self, file_path: str, tool_name: str, tool_input: Dict
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an Edit or Write to a mixed-settings file modifies hooks.

        Mixed-settings files (Claude, Gemini, Augment) contain both hooks
        and user preferences. Only hook modifications are blocked.

        Returns:
            tuple: (should_block, error_message) — True blocks the operation
        """
        if tool_name == "Edit":
            old_string = tool_input.get("old_string", "")
            new_string = tool_input.get("new_string", "")
            combined = (old_string or "") + (new_string or "")

            if _HOOK_KEY_PATTERN.search(combined):
                return True, self._format_hook_protection_message(
                    file_path, tool_name, "hook key detected in edit strings"
                )
            if "ai-guardian" in combined and "command" in combined:
                return True, self._format_hook_protection_message(
                    file_path, tool_name, "hook command modification detected"
                )
            return False, None

        if tool_name == "Write":
            content = tool_input.get("content", "")
            try:
                new_json = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return True, self._format_hook_protection_message(
                    file_path,
                    tool_name,
                    "cannot parse new content as JSON — fail-closed",
                )

            new_hooks = new_json.get("hooks")

            expanded = os.path.expanduser(file_path)
            try:
                with open(expanded, "r") as f:
                    old_json = json.load(f)
                old_hooks = old_json.get("hooks")
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                if new_hooks is not None:
                    return True, self._format_hook_protection_message(
                        file_path, tool_name, "new file contains hooks section"
                    )
                return False, None

            if new_hooks != old_hooks:
                return True, self._format_hook_protection_message(
                    file_path, tool_name, "hooks section modified"
                )
            return False, None

        return False, None

    def _format_hook_protection_message(
        self, file_path: str, tool_name: str, reason: str
    ) -> str:
        """Format error message for blocked hook modification in mixed-settings file."""
        display_path = file_path if len(file_path) <= 100 else file_path[:97] + "..."
        msg = "🛡️ Hook Protection\n\n"
        msg += "Protection: IDE Hook Configuration\n"
        msg += f"Tool: {tool_name}\n"
        msg += f"File Path: {display_path}\n"
        msg += f"Reason: {reason}\n"
        msg += "\nWhy blocked: This file contains AI agent hook configuration.\n"
        msg += "Modifying hooks could disable security protections (ai-guardian).\n"
        msg += "Non-hook settings (permissions, theme, model, MCP) CAN be modified.\n"
        msg += "\nThis operation has been blocked for security.\n"
        msg += "DO NOT attempt to bypass this protection - it prevents security control tampering.\n"
        msg += "\nRecommendation:\n"
        msg += (
            "- Modify only non-hook settings (permissions, theme, model, MCP, etc.)\n"
        )
        msg += "- Avoid including the 'hooks' key or hook event names in your edit\n"
        msg += "- Hook configuration must be edited manually (not by AI agents)\n"
        msg += "\n⚠️ This protection is immutable and cannot be disabled via configuration.\n"
        return msg

    def check_tool_allowed(
        self, hook_data: Dict
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if a tool invocation is allowed.

        Args:
            hook_data: Hook data from PreToolUse event

        Returns:
            tuple: (is_allowed: bool, error_message: str or None, tool_name: str or None)
        """
        try:
            # Extract tool name and parameters
            tool_name, tool_input = self._extract_tool_info(hook_data)
            if not tool_name:
                logger.warning("Could not extract tool name from hook data")
                # Fail-closed: block if we can't determine the tool (security-critical path)
                return False, "Policy check error: unable to determine tool name", None

            logger.info(f"Checking if tool '{tool_name}' is allowed...")

            # PRIORITY 0: Check SSRF protection (before all other checks)
            # Prevents accessing private networks, metadata endpoints, and dangerous URL schemes
            if HAS_SSRF_PROTECTOR:
                ssrf_config = self.config.get("ssrf_protection", {})
                if is_feature_enabled(
                    ssrf_config.get("enabled"), datetime.now(timezone.utc), default=True
                ):
                    ssrf_protector = SSRFProtector(ssrf_config)
                    should_block, error_msg = ssrf_protector.check(
                        tool_name, tool_input
                    )

                    if should_block:
                        # SSRF detected and blocked
                        logger.error(f"🚨 BLOCKED: {tool_name} - SSRF attack detected")
                        self._log_violation(
                            tool_name=tool_name,
                            check_value=tool_input.get("command", str(tool_input)),
                            reason="SSRF attack detected",
                            matcher=tool_name,
                            hook_data=hook_data,
                            violation_type=ViolationType.SSRF_BLOCKED,
                        )
                        return False, error_msg, tool_name

                    elif error_msg:
                        # Warning mode - log but allow
                        logger.warning(f"SSRF warning for {tool_name}: {error_msg}")
                        self._log_violation(
                            tool_name=tool_name,
                            check_value=tool_input.get("command", str(tool_input)),
                            reason="SSRF warning (allowed)",
                            matcher=tool_name,
                            hook_data=hook_data,
                            violation_type=ViolationType.SSRF_BLOCKED,
                        )
                        # Continue to other checks (warning is logged, execution allowed)

            # PRIORITY 0.5: Check config exfiltration patterns in Bash commands
            # Detects credential exfiltration (env|curl, aws s3 cp, etc.)
            if HAS_CONFIG_SCANNER and tool_name == "Bash":
                exfil_config = self.config.get("config_file_scanning", {})
                if is_feature_enabled(
                    exfil_config.get("enabled"),
                    datetime.now(timezone.utc),
                    default=True,
                ):
                    exfil_scanner = ConfigFileScanner(exfil_config)
                    bash_command = tool_input.get("command", "")
                    exfil_block, exfil_msg, exfil_details = exfil_scanner.check_command(
                        bash_command
                    )

                    if exfil_block:
                        logger.error(
                            f"🚨 BLOCKED: {tool_name} - credential exfiltration detected"
                        )
                        self._log_violation(
                            tool_name=tool_name,
                            check_value=bash_command,
                            reason="Credential exfiltration detected in Bash command",
                            matcher=tool_name,
                            hook_data=hook_data,
                            violation_type=ViolationType.CONFIG_FILE_EXFIL,
                        )
                        return False, exfil_msg, tool_name

                    elif exfil_msg:
                        logger.warning(
                            f"Config exfil warning for {tool_name}: {exfil_msg}"
                        )
                        self._log_violation(
                            tool_name=tool_name,
                            check_value=bash_command,
                            reason="Config exfil warning (allowed)",
                            matcher=tool_name,
                            hook_data=hook_data,
                            violation_type=ViolationType.CONFIG_FILE_EXFIL,
                        )

            # PRIORITY 1: Check immutable deny patterns (cannot be overridden)
            # These protect ai-guardian config, IDE hooks, and pip-installed package code
            # EXCEPT: Development source code can be edited (fork + PR workflow)
            check_value = self._extract_check_value(tool_name, tool_input, tool_name)

            # For Bash/Shell: also check immutable deny patterns against the raw
            # (un-stripped) command to prevent heredoc bypass (#1350)
            raw_check_value = None
            if tool_name in ("Bash", "Shell"):
                raw_cmd = tool_input.get("command")
                if raw_cmd and raw_cmd != check_value:
                    raw_check_value = raw_cmd

            # For file-path tools (Edit/Write/Read/NotebookEdit), require check_value
            # If we can't extract file_path, fail-closed to prevent bypass (Issue #113)
            is_file_path_tool = tool_name in ["Write", "Read", "Edit", "NotebookEdit"]
            if is_file_path_tool and not check_value:
                error_msg = (
                    f"\n{'='*70}\n"
                    f"🚨 BLOCKED BY POLICY\n"
                    f"{'='*70}\n"
                    f"Tool: {tool_name}\n"
                    f"Reason: Missing required parameter (file_path)\n"
                    f"\n"
                    f"File-path tools require a file_path parameter for security checks.\n"
                    f"This operation has been blocked to prevent bypassing immutable\n"
                    f"file protections.\n"
                    f"{'='*70}\n"
                )
                logger.error(f"🚨 BLOCKED: {tool_name} - missing file_path parameter")
                self._log_violation(
                    tool_name=tool_name,
                    check_value="<missing file_path>",
                    reason="missing required parameter",
                    matcher=tool_name,
                    hook_data=hook_data,
                )
                return False, error_msg, tool_name

            if check_value:
                # Check if this is development source code (allowed for contributors)
                if self._should_skip_immutable_protection(check_value, tool_name):
                    logger.info(
                        f"✅ Development source code: allowing {tool_name} on {check_value}"
                    )
                    return True, None, tool_name

                # PRIORITY 1b: Content-aware check for mixed settings files (Issue #807)
                # These files contain both hooks (protected) and user preferences (editable)
                if tool_name in ("Edit", "Write"):
                    is_mixed = any(
                        fnmatch.fnmatch(check_value, pat)
                        for pat in MIXED_SETTINGS_PATTERNS
                    )
                    if is_mixed:
                        should_block, block_msg = (
                            self._check_mixed_settings_hook_modification(
                                check_value, tool_name, tool_input
                            )
                        )
                        if should_block:
                            self._log_violation(
                                tool_name=tool_name,
                                check_value=check_value,
                                reason="hook modification in mixed settings file",
                                matcher=tool_name,
                                hook_data=hook_data,
                            )
                            return False, block_msg, tool_name
                        else:
                            logger.info(
                                f"✅ Mixed settings: allowing {tool_name} on {check_value} "
                                f"(non-hook modification)"
                            )
                            return True, None, tool_name

                immutable_denies = IMMUTABLE_DENY_PATTERNS.get(tool_name, [])
                # Use Path.match() for file path tools with ** patterns, fnmatch otherwise
                is_file_path_tool = tool_name in [
                    "Write",
                    "Read",
                    "Edit",
                    "NotebookEdit",
                ]
                for pattern in immutable_denies:
                    # For file path tools with ** patterns: use Path.match()
                    # Otherwise: use fnmatch to match patterns within command strings or simple globs
                    if is_file_path_tool and "**" in pattern:
                        matches = Path(check_value).match(pattern)
                    else:
                        matches = fnmatch.fnmatch(check_value, pattern)

                    if not matches and raw_check_value:
                        matches = fnmatch.fnmatch(raw_check_value, pattern)

                    if matches:
                        error_msg = self._format_immutable_deny_message(
                            check_value, tool_name, pattern
                        )
                        self._log_violation(
                            tool_name=tool_name,
                            check_value=check_value,
                            reason=f"immutable deny: {pattern}",
                            matcher=tool_name,
                            hook_data=hook_data,
                        )
                        return False, error_msg, tool_name

            # PRIORITY 2: Check user-configured permissions
            # Skip if permissions are disabled
            permissions_config = self.config.get("permissions", {})
            if isinstance(permissions_config, dict) and not is_feature_enabled(
                permissions_config.get("enabled"),
                datetime.now(timezone.utc),
                default=True,
            ):
                logger.info(f"✓ Tool '{tool_name}' allowed (permissions disabled)")
                return True, None, tool_name

            # Find all matching permission rules (evaluated in order, last match wins)
            permission_rules = self._find_permission_rules(tool_name)

            if not permission_rules:
                # No matching rules — check tool type
                if self._is_restricted_tool(tool_name):
                    # MCP tools and Skills require explicit allow
                    logger.warning(
                        f"Tool '{tool_name}' requires explicit permission but no rule found"
                    )
                    error_msg = self._format_deny_message(
                        tool_name,
                        "no permission rule",
                        None,
                        tool_value=check_value if check_value else tool_name,
                    )
                    self._log_violation(
                        tool_name=tool_name,
                        check_value=check_value if check_value else tool_name,
                        reason="no permission rule",
                        matcher=tool_name,
                        hook_data=hook_data,
                    )
                    return False, error_msg, tool_name

                # Built-in tools allowed by default when no rules target them
                logger.info(
                    f"✓ Tool '{tool_name}' is allowed by default (no matching rule)"
                )
                return True, None, tool_name

            # Expand legacy rules (action on allow rules → split into allow + deny)
            expanded_rules = self._expand_legacy_permission_rules(permission_rules)

            # Evaluate rules in order, last match wins (same as directory_rules)
            final_decision = None  # "allow" or "deny"
            final_action = "block"  # Only meaningful for deny: block/warn/log-only
            matched_pattern = None
            matched_matcher = None
            is_file_path_tool = tool_name in ["Write", "Read", "Edit", "NotebookEdit"]

            for rule in expanded_rules:
                mode = rule.get("mode")
                patterns = rule.get("patterns", [])

                # Legacy format support
                if mode is None:
                    allow_patterns = rule.get("allow", [])
                    deny_patterns = rule.get("deny", [])
                    if allow_patterns:
                        mode = "allow"
                        patterns = allow_patterns
                    elif deny_patterns:
                        mode = "deny"
                        patterns = deny_patterns
                    else:
                        continue

                if mode not in ("allow", "deny"):
                    continue

                # Extract the value to check against this rule's patterns
                rule_check_value = self._extract_check_value(
                    tool_name, tool_input, rule.get("matcher", tool_name)
                )
                if rule_check_value is None:
                    continue

                # Check if check_value matches any pattern in this rule
                pattern_matched = False
                for pattern_entry in patterns:
                    pattern_str = self._extract_pattern_string(pattern_entry)
                    if is_file_path_tool and "**" in pattern_str:
                        matches = Path(rule_check_value).match(pattern_str)
                    else:
                        matches = fnmatch.fnmatch(rule_check_value, pattern_str)

                    if matches:
                        pattern_matched = True
                        final_decision = mode
                        final_action = (
                            rule.get("action", "block") if mode == "deny" else "allow"
                        )
                        matched_pattern = pattern_str
                        matched_matcher = rule.get("matcher")
                        logger.debug(
                            f"Rule matched: matcher={matched_matcher}, mode={mode}, pattern={pattern_str} (last-match-wins, continuing)"
                        )
                        break  # Break inner pattern loop, continue outer rule loop

                # Legacy backward compat: allow rule with action field
                # When no pattern matched but _legacy_fallback_action is set,
                # apply it as a deny decision (the old "not in allow list" behavior).
                # Skip if a prior rule already explicitly allowed — a project-level
                # allow rule's fallback must not override a global allow (#1748).
                if (
                    not pattern_matched
                    and rule.get("_legacy_fallback_action")
                    and final_decision != "allow"
                ):
                    fallback_action = rule["_legacy_fallback_action"]
                    final_decision = "deny"
                    final_action = fallback_action
                    matched_pattern = "not in allow list"
                    matched_matcher = rule.get("matcher")
                    logger.debug(
                        f"Legacy fallback: matcher={matched_matcher}, action={fallback_action}"
                    )

            # Apply final decision
            if final_decision == "allow":
                logger.info(
                    f"✓ Tool '{tool_name}' allowed by rule (matcher={matched_matcher}, pattern={matched_pattern})"
                )
                return True, None, tool_name

            if final_decision == "deny":
                self._log_violation(
                    tool_name=tool_name,
                    check_value=check_value if check_value else tool_name,
                    reason=f"matched deny pattern: {matched_pattern}",
                    matcher=matched_matcher,
                    hook_data=hook_data,
                )

                if final_action == "warn":
                    logger.warning(
                        f"Policy violation (warn mode): {tool_name} - {matched_pattern} - execution allowed"
                    )
                    return (
                        True,
                        "⚠️  Tool policy violation (warn mode) - execution allowed",
                        tool_name,
                    )
                elif final_action == "log-only":
                    logger.warning(
                        f"Policy violation (log-only mode): {tool_name} - {matched_pattern} - execution allowed (silent)"
                    )
                    return True, None, tool_name
                else:
                    self.last_deny_action = final_action
                    self.last_deny_matched_pattern = matched_pattern
                    self.last_deny_check_value = (
                        check_value if check_value else tool_name
                    )
                    logger.error(
                        f"Tool '{tool_name}' blocked by deny rule: {matched_pattern}"
                    )
                    error_msg = self._format_deny_message(
                        tool_name,
                        f"matched deny pattern: {matched_pattern}",
                        matched_matcher,
                        tool_value=check_value if check_value else tool_name,
                    )
                    return False, error_msg, tool_name

            # No rule matched any pattern — check tool type
            if self._is_restricted_tool(tool_name):
                # Determine action from matching rules (last explicit action wins)
                deny_default_action = "block"
                for rule in expanded_rules:
                    rule_action = rule.get("action") or rule.get(
                        "_legacy_fallback_action"
                    )
                    if rule_action:
                        deny_default_action = rule_action

                self.last_deny_action = deny_default_action
                self.last_deny_matched_pattern = "not in allow list"
                self.last_deny_check_value = check_value if check_value else tool_name
                logger.warning(
                    f"Tool '{tool_name}' has no matching pattern in rules — {deny_default_action}"
                )
                error_msg = self._format_deny_message(
                    tool_name,
                    "not in allow list",
                    None,
                    tool_value=check_value if check_value else tool_name,
                )
                self._log_violation(
                    tool_name=tool_name,
                    check_value=check_value if check_value else tool_name,
                    reason="not in allow list",
                    matcher=tool_name,
                    hook_data=hook_data,
                )
                return False, error_msg, tool_name

            # Built-in tool with rules that matched by matcher but no pattern matched
            logger.info(f"✓ Tool '{tool_name}' allowed (no matching pattern in rules)")
            return True, None, tool_name

        except Exception as e:
            logger.error(f"Error checking tool policy: {e}")
            import traceback

            logger.error(traceback.format_exc())
            # Fail-closed: block on errors (security-critical path)
            return False, f"Policy check error: {e}", None

    _AUGMENT_TOOL_MAP = AUGMENT_TOOL_MAP

    def _extract_tool_info(self, hook_data: Dict) -> Tuple[Optional[str], Dict]:
        """
        Extract tool name and input from hook data.

        Returns:
            tuple: (tool_name, tool_input)
        """
        try:
            tool_name = None
            tool_input = {}

            # Claude Code format: tool_use.name + tool_use.input or tool_use.parameters
            if "tool_use" in hook_data and isinstance(hook_data["tool_use"], dict):
                tool_name = hook_data["tool_use"].get("name")
                # Try both "input" (PostToolUse) and "parameters" (PreToolUse)
                tool_input = hook_data["tool_use"].get("input") or hook_data[
                    "tool_use"
                ].get("parameters", {})
            # Cursor format: tool.name
            elif "tool" in hook_data and isinstance(hook_data["tool"], dict):
                tool_name = hook_data["tool"].get("name")
                tool_input = hook_data.get("tool_input", {})
            # GitHub Copilot format: toolName + toolArgs (JSON string)
            elif "toolName" in hook_data:
                tool_name = hook_data["toolName"]
                # toolArgs is a JSON string in Copilot format
                if "toolArgs" in hook_data:
                    try:
                        tool_input = json.loads(hook_data["toolArgs"])
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
            # Alternative: direct tool_name field
            elif "tool_name" in hook_data:
                tool_name = hook_data["tool_name"]
                tool_input = hook_data.get("tool_input", {})

            # Cursor/Windsurf: synthesize from event-based hook names
            if not tool_name:
                event_name = hook_data.get("hook_event_name", "").lower()
                hook_name_val = hook_data.get("hook_name", "").lower()
                effective_event = event_name or hook_name_val
                if effective_event in ("beforereadfile", "pre_read_code"):
                    tool_name = "Read"
                    file_path = hook_data.get("file_path", "")
                    if file_path:
                        tool_input = {"file_path": file_path}
                elif effective_event in ("beforeshellexecution",):
                    tool_name = "Bash"
                    tool_input = hook_data.get("tool_input", {})

            # Augment Code: normalize tool names and mcp: prefix
            if tool_name and tool_name in self._AUGMENT_TOOL_MAP:
                tool_name = self._AUGMENT_TOOL_MAP[tool_name]
            elif tool_name and tool_name.startswith("mcp:"):
                tool_name = "mcp__" + tool_name[4:].replace(":", "__")

            return tool_name, tool_input

        except Exception as e:
            logger.error(f"Error extracting tool info: {e}")
            return None, {}

    def _extract_pattern_string(self, pattern_entry: Union[str, Dict]) -> str:
        """
        Extract the pattern string from a pattern entry.

        Args:
            pattern_entry: Either a string pattern or dict with 'pattern' field

        Returns:
            str: The pattern string

        Examples:
            >>> self._extract_pattern_string("daf-*")
            "daf-*"

            >>> self._extract_pattern_string({"pattern": "debug-*", "valid_until": "2026-04-13T12:00:00Z"})
            "debug-*"
        """
        if isinstance(pattern_entry, str):
            return pattern_entry
        elif isinstance(pattern_entry, dict) and "pattern" in pattern_entry:
            return pattern_entry["pattern"]
        else:
            # Fallback - return string representation
            return str(pattern_entry)

    def _is_pattern_valid(
        self, pattern_entry: Union[str, Dict], current_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if a pattern entry is still valid (not expired).

        Supports both simple format (string) and extended format (dict with valid_until).

        Args:
            pattern_entry: Either a string pattern or dict with 'pattern' and 'valid_until'
            current_time: Optional current time for testing (defaults to now in UTC)

        Returns:
            bool: True if pattern is valid, False if expired

        Examples:
            >>> self._is_pattern_valid("daf-*")
            True

            >>> self._is_pattern_valid({"pattern": "debug-*", "valid_until": "2099-12-31T23:59:59Z"})
            True

            >>> self._is_pattern_valid({"pattern": "temp-*", "valid_until": "2020-01-01T00:00:00Z"})
            False
        """
        # Simple format (string) - never expires
        if isinstance(pattern_entry, str):
            return True

        # Extended format (dict) - check for valid_until field
        if isinstance(pattern_entry, dict):
            # No valid_until field - treat as non-expiring
            if "valid_until" not in pattern_entry:
                return True

            valid_until = pattern_entry.get("valid_until")
            if not valid_until:
                return True

            # Check if expired
            return not is_expired(valid_until, current_time)

        # Unknown format - treat as valid (fail-safe)
        logger.warning(f"Unknown pattern entry format: {type(pattern_entry)}")
        return True

    def _filter_valid_patterns(
        self, patterns: List[Union[str, Dict]], current_time: Optional[datetime] = None
    ) -> List[Union[str, Dict]]:
        """
        Filter out expired patterns from a list.

        Args:
            patterns: List of pattern entries (strings or dicts)
            current_time: Optional current time for testing

        Returns:
            list: Filtered list with only valid (non-expired) patterns
        """
        valid_patterns = []
        for pattern_entry in patterns:
            if self._is_pattern_valid(pattern_entry, current_time):
                valid_patterns.append(pattern_entry)
            else:
                # Log when we skip an expired pattern
                pattern_str = (
                    pattern_entry.get("pattern")
                    if isinstance(pattern_entry, dict)
                    else str(pattern_entry)
                )
                valid_until = (
                    pattern_entry.get("valid_until")
                    if isinstance(pattern_entry, dict)
                    else None
                )
                logger.info(
                    f"Skipping expired pattern '{pattern_str}' (expired: {valid_until})"
                )

        return valid_patterns

    def _expand_legacy_permission_rules(self, rules: List[Dict]) -> List[Dict]:
        """
        Process legacy permission rules with action on allow rules.

        Old format (deprecated): mode=allow + action=warn meant "allow listed patterns,
        warn on non-matches". The action field is stripped from allow rules (it's only
        meaningful on deny rules). The action is stored as _legacy_fallback_action for
        use when no pattern matches after all rules are evaluated.

        Args:
            rules: List of matching permission rules

        Returns:
            list: Processed list with clean allow/deny semantics
        """
        processed = []
        for rule in rules:
            mode = rule.get("mode")
            action = rule.get("action")

            if mode == "allow" and action and action != "block":
                logger.warning(
                    f"Deprecated: action '{action}' on allow rule (matcher={rule.get('matcher')}). "
                    f"Prefer separate deny rule with action instead."
                )
                clean_rule = {k: v for k, v in rule.items() if k != "action"}
                clean_rule["_legacy_fallback_action"] = action
                processed.append(clean_rule)
            else:
                processed.append(rule)

        return processed

    def _find_permission_rules(self, tool_name: str) -> List[Dict]:
        """
        Find all permission rules that match the tool name.

        Filters out expired patterns from the rules.

        Args:
            tool_name: Name of the tool (e.g., "Skill", "mcp__notebooklm__notebook_list")

        Returns:
            list: List of matching permission rules (may be empty)
        """
        permissions = self.config.get("permissions", {})

        # New unified format: object with enabled, immutable, rules
        if isinstance(permissions, dict):
            rules = permissions.get("rules", [])
        # Legacy format: array of rules directly (pre-v1.4.0)
        elif isinstance(permissions, list):
            logger.debug(
                "Legacy permissions format detected (array) - consider updating to new structure"
            )
            rules = permissions
        else:
            logger.warning(f"Invalid permissions format: {type(permissions)}")
            return []

        if not isinstance(rules, list):
            logger.warning(f"Invalid permissions.rules format: {type(rules)}")
            return []

        logger.debug(
            f"Searching {len(rules)} permission rule(s) for tool '{tool_name}'"
        )

        matching_rules = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue

            matcher = rule.get("matcher")
            if not matcher:
                continue

            # Check if tool_name matches the matcher pattern
            if fnmatch.fnmatch(tool_name, matcher):
                logger.debug(
                    f"Found matching rule: matcher={matcher}, mode={rule.get('mode')}, action={rule.get('action', 'block')}, patterns={len(rule.get('patterns', []))}"
                )

                # Filter expired patterns from the rule
                filtered_rule = rule.copy()
                if "patterns" in filtered_rule:
                    filtered_rule["patterns"] = self._filter_valid_patterns(
                        filtered_rule["patterns"]
                    )

                # Legacy format support - filter allow/deny lists
                if "allow" in filtered_rule:
                    filtered_rule["allow"] = self._filter_valid_patterns(
                        filtered_rule["allow"]
                    )
                if "deny" in filtered_rule:
                    filtered_rule["deny"] = self._filter_valid_patterns(
                        filtered_rule["deny"]
                    )

                matching_rules.append(filtered_rule)

        if not matching_rules and tool_name.startswith("mcp__"):
            logger.warning(
                f"No permission rules found for MCP tool '{tool_name}' (checked {len(rules)} rules)"
            )

        return matching_rules

    def _extract_check_value(
        self, tool_name: str, tool_input: Dict, matcher: str
    ) -> Optional[str]:
        """
        Extract the value to check against allow/deny patterns.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters
            matcher: The matcher pattern from the permission rule

        Returns:
            str or None: Value to check
        """
        # Skill: extract skill name from input
        if matcher == "Skill" or tool_name == "Skill":
            skill = tool_input.get("skill")
            return skill if skill else None

        # Bash/Shell/PowerShell: extract command from input
        if matcher == "Bash" or matcher == "Shell" or matcher == "PowerShell":
            command = tool_input.get("command")
            if not command:
                return None
            # For Bash/Shell, strip heredoc content to avoid false positives
            # PowerShell doesn't use heredocs, so we skip this for PowerShell
            if matcher in ["Bash", "Shell"]:
                return _strip_bash_heredoc_content(command)
            return command

        # Write: extract file_path from input
        if matcher == "Write":
            file_path = tool_input.get("file_path")
            return file_path if file_path else None

        # Read: extract file_path from input
        if matcher == "Read":
            file_path = tool_input.get("file_path")
            return file_path if file_path else None

        # Edit: extract file_path from input
        if matcher == "Edit":
            file_path = tool_input.get("file_path")
            return file_path if file_path else None

        # NotebookEdit: extract file_path from input
        if matcher == "NotebookEdit":
            file_path = tool_input.get("file_path")
            return file_path if file_path else None

        # MCP and other tools: use tool_name directly
        return tool_name

    def _is_restricted_tool(self, tool_name: str) -> bool:
        """
        Check if a tool type is restricted (requires explicit allow rule).

        Skills and MCP tools (except ai-guardian's own) are restricted.
        Built-in tools (Bash, Read, Write, Edit, etc.) are allowed by default
        when no permission rule targets them.
        """
        if tool_name == "Skill":
            return True
        if tool_name.startswith("mcp__"):
            if tool_name.startswith("mcp__ai-guardian__"):
                return False
            return True
        return False

    def _format_deny_message(
        self,
        tool_name: str,
        reason: str,
        matcher: Optional[str],
        tool_value: Optional[str] = None,
    ) -> str:
        """
        Format error message for denied tools.

        Args:
            tool_name: Name of the denied tool
            reason: Reason for denial (pattern that blocked it)
            matcher: The matcher from the permission rule (if found)
            tool_value: The specific value that was checked (e.g., skill name, file path)

        Returns:
            str: Formatted error message
        """
        # Generate suggested configuration
        suggested_matcher, suggested_patterns = self._suggest_permission_rule(tool_name)

        paths = get_all_config_paths()
        config_path = str(paths["global"])

        # Start with header
        msg = "🛡️ Tool Access Denied\n\n"
        msg += "Protection: Tool Permission Policy\n"
        msg += f"Tool: {tool_name}\n"

        # Show matcher if available
        if matcher:
            msg += f"Matcher: {matcher}\n"

        # Show the specific value that was blocked (if available)
        if tool_value:
            # Determine the label based on tool type
            if tool_name == "Skill":
                label = "Skill Name"
            elif matcher in ["Edit", "Read", "Write"]:
                label = "File Path"
            elif tool_name == "Bash":
                label = "Command"
            else:
                label = "Value"
            # Truncate very long values
            display_value = (
                tool_value if len(tool_value) <= 100 else tool_value[:97] + "..."
            )
            msg += f"{label}: {display_value}\n"

        # Add blocked pattern
        if reason:
            # Truncate very long patterns
            display_reason = reason if len(reason) <= 100 else reason[:97] + "..."
            msg += f"Pattern: {display_reason}\n"

        # Why blocked section
        if reason == "no permission rule" and (
            tool_name.startswith("mcp__") or tool_name == "Skill"
        ):
            msg += "\nWhy blocked: MCP servers and Skills are blocked by default (deny-by-default policy).\n"
            if tool_name.startswith("mcp__"):
                msg += "MCP servers run third-party code that may bypass hook-based scanning.\n"
                msg += "Add an explicit allow rule in permissions to use this MCP server.\n"
            else:
                msg += "Skills can override AI behavior and instructions.\n"
                msg += "Add an explicit allow rule in permissions to use this Skill.\n"
        else:
            msg += f"\nWhy blocked: This {tool_name.lower()} operation matches a denied pattern in your tool policy.\n"

            # Add context-specific explanation
            if tool_name == "Bash":
                if (
                    "install" in (tool_value or "").lower()
                    or "install" in (reason or "").lower()
                ):
                    msg += "Package installation requires explicit approval to prevent supply chain attacks.\n"
                elif (
                    "rm" in (tool_value or "").lower()
                    or "delete" in (tool_value or "").lower()
                ):
                    msg += "Destructive commands require explicit approval to prevent data loss.\n"
                else:
                    msg += "This command requires explicit approval in your security policy.\n"
            elif tool_name == "Skill":
                msg += "Skill execution requires explicit approval in your security policy.\n"
            elif matcher in ["Edit", "Write"]:
                msg += "File modifications require explicit approval to prevent unauthorized changes.\n"
            elif matcher == "Read":
                msg += "File access requires explicit approval to prevent information disclosure.\n"
            else:
                msg += "This operation requires explicit approval in your security policy.\n"

        # Security warnings
        msg += "\nThis operation has been blocked for security.\n"
        msg += "DO NOT attempt to bypass this protection - it prevents unauthorized tool use.\n"

        # Recommendations section
        msg += "\nRecommendation:\n"

        # Context-specific recommendations
        if tool_name == "Bash" and "install" in (tool_value or "").lower():
            # Extract package name if possible
            if tool_value and "npm install" in tool_value:
                parts = tool_value.split()
                if len(parts) > 2:
                    pkg_name = parts[2].strip()
                    msg += f"- Review the package at https://npmjs.com/package/{pkg_name}\n"
                    msg += "- Check package reputation and downloads\n"
            msg += "- Add to allowed_patterns if trusted\n"
            msg += "- Use package-lock.json for reproducible builds\n"
        elif tool_name == "Skill":
            msg += "- Review the skill documentation and source code\n"
            msg += "- Verify the skill is from a trusted source\n"
            msg += "- Add to allowed_patterns if safe\n"
        elif matcher in ["Edit", "Write", "Read"]:
            msg += "- Verify you need to access this file path\n"
            msg += "- Check if the file contains sensitive information\n"
            msg += "- Add to allowed_patterns if the path is safe\n"
        else:
            msg += "- Review what this operation does\n"
            msg += "- Verify it's safe and necessary\n"
            msg += "- Add to allowed_patterns if trusted\n"

        msg += "- Or ask your administrator to update the enterprise policy\n"

        # Configuration help
        msg += "\nTo allow this, add to your config:\n"
        msg += format_config_paths() + "\n\n"
        msg += "{\n"
        msg += '  "permissions": [\n'
        msg += "    {\n"
        msg += f'      "matcher": "{suggested_matcher}",\n'
        msg += '      "mode": "allow",\n'
        msg += '      "patterns": [\n'

        # Show patterns with comments
        for i, pattern in enumerate(suggested_patterns):
            if i == 0:
                msg += f'        "{pattern["pattern"]}"  # {pattern["comment"]}\n'
            else:
                msg += f'        # "{pattern["pattern"]}"  # {pattern["comment"]}\n'

        msg += "      ]\n"
        msg += "    }\n"
        msg += "  ]\n"
        msg += "}\n"

        # Config path
        msg += "\nConfig:\n" + format_config_paths() + "\n"
        msg += f"Section: permissions[matcher={suggested_matcher}].deny_patterns\n"

        return msg

    def _format_immutable_deny_message(
        self, check_value: str, tool_name: str, matched_pattern: str = None
    ) -> str:
        """
        Format error message for immutable deny (cannot be overridden).

        Args:
            check_value: The value that was blocked (file path, command, etc.)
            tool_name: The tool that was blocked
            matched_pattern: The specific immutable pattern that triggered the block

        Returns:
            str: Formatted error message
        """
        # Determine the appropriate label based on tool type
        if tool_name == "Bash":
            value_label = "Command"
            protection_context = "command pattern"
        elif tool_name == "Skill":
            value_label = "Skill"
            protection_context = "skill name"
        elif tool_name.startswith("mcp__"):
            value_label = "MCP Tool"
            protection_context = "tool name"
        else:
            value_label = "File Path"
            protection_context = "file path"

        # First, check if this is a config/state/cache file (these are NEVER source files)
        config_patterns = [
            "*ai-guardian.json",
            "*/.ai-guardian.json",
            "*/.config/ai-guardian/*",
            "*/.local/state/ai-guardian/*",
            "*/.cache/ai-guardian/*",
            "*/.claude/hooks.json",
            "*/.cursor/hooks.json",
            "*/Cursor/hooks.json",
            "*/.claude/settings.json",
            "*/Claude/settings.json",
            "*/.gemini/settings.json",
            "*/.augment/settings.json",
        ]
        is_config_file = any(fnmatch.fnmatch(check_value, p) for p in config_patterns)

        # Detect state files specifically (for Read-specific messaging)
        state_patterns = ["*/.local/state/ai-guardian/*"]
        is_state_file = any(fnmatch.fnmatch(check_value, p) for p in state_patterns)

        # Detect cache files specifically (for Read-specific messaging)
        cache_file_patterns = ["*/.cache/ai-guardian/*"]
        is_cache_file = any(
            fnmatch.fnmatch(check_value, p) for p in cache_file_patterns
        )

        # Check if this is ai-guardian source code (development or pip-installed)
        # ONLY if it's NOT a config file
        source_patterns = [
            # Development repository patterns
            "*/ai-guardian/src/ai_guardian/*",
            "*/ai-guardian/tests/*",
            "*/ai-guardian/*.md",
            "*/ai-guardian/*.py",
            "*/ai-guardian/*.toml",
            "*/ai-guardian/*.txt",
            "*/ai-guardian/.github/*",
            # Pip-installed package patterns
            "*/site-packages/ai_guardian/*",
        ]
        is_source_file = (not is_config_file) and any(
            fnmatch.fnmatch(check_value, p) for p in source_patterns
        )

        # Check if this is a .ai-read-deny marker file
        is_marker_file = (
            check_value.endswith(".ai-read-deny")
            or "/.ai-read-deny" in check_value
            or "\\.ai-read-deny" in check_value
            or ".ai-read-deny" in check_value
        )

        # Check if this looks like documentation/discussion vs. actual config
        is_likely_documentation = (
            check_value.endswith(".md")
            or check_value.endswith(".txt")
            or "/docs/" in check_value
            or "/documentation/" in check_value
            or "README" in check_value.upper()
        )

        # Start with consistent header
        msg = "🛡️ Immutable Protection\n\n"

        # Determine protection type for header
        if is_source_file:
            msg += "Protection: Package Source Code (Pip-installed)\n"
        elif is_marker_file:
            msg += "Protection: Directory Protection Marker\n"
        elif is_config_file:
            msg += "Protection: Configuration File\n"
        else:
            msg += "Protection: Immutable File\n"

        # Show tool and value
        msg += f"Tool: {tool_name}\n"
        # Truncate very long values
        display_value = (
            check_value if len(check_value) <= 100 else check_value[:97] + "..."
        )
        msg += f"{value_label}: {display_value}\n"

        # Show pattern if available
        if matched_pattern:
            display_pattern = (
                matched_pattern
                if len(matched_pattern) <= 100
                else matched_pattern[:97] + "..."
            )
            msg += f"Pattern: {display_pattern}\n"

        # Why blocked section - varies by type and tool
        msg += "\nWhy blocked: "

        is_read_operation = tool_name == "Read" or (
            tool_name == "Bash"
            and any(
                cmd in check_value
                for cmd in ["cat ", "grep ", "head ", "tail ", "less ", "more "]
            )
        )

        if is_source_file:
            msg += "This file is part of the pip-installed ai-guardian package.\n"
            msg += "Modifying package source code would bypass security controls in production.\n"
        elif is_marker_file:
            msg += "This is a directory protection marker file (.ai-read-deny).\n"
            msg += "Modifying marker files would bypass directory protection.\n"
        elif is_config_file and is_read_operation:
            if is_state_file:
                msg += "This file contains ai-guardian security state (violations, logs, scanning data).\n"
                msg += "Reading it exposes detection results that could help craft evasion attacks.\n"
            elif is_cache_file:
                msg += "This file contains cached security patterns and regex.\n"
                msg += "Reading it exposes detection logic that could help craft evasion attacks.\n"
            else:
                msg += "This file contains ai-guardian security configuration.\n"
                msg += "Reading it exposes security rules, patterns, and allowlists to the agent.\n"
        elif is_config_file:
            msg += "This is an ai-guardian or IDE hook configuration file.\n"
            msg += "Modifying these files could disable security protections.\n"
        elif tool_name == "Bash":
            msg += "This command matches a critical protection pattern.\n"
            msg += "Executing it could compromise system security.\n"
        else:
            msg += "This file is protected by immutable file protection.\n"
            msg += "Modifying it could bypass ai-guardian security controls.\n"

        # Security warnings
        msg += "\nThis operation has been blocked for security.\n"
        msg += "DO NOT attempt to bypass this protection - it prevents security control tampering.\n"

        # Recommendations section - varies by type and tool
        msg += "\nRecommendation:\n"

        if is_source_file:
            msg += "- This file is pip-installed and cannot be modified\n"
            msg += "- If developing ai-guardian:\n"
            msg += "  1. Clone: git clone https://github.com/RedHatProductSecurity/ai-guardian\n"
            msg += "  2. Install in dev mode: pip install -e .\n"
            msg += "  3. Edit source files in cloned repository\n"
            msg += "- Development source files CAN be edited (only pip-installed are protected)\n"
        elif is_marker_file:
            msg += "- .ai-read-deny markers enforce directory protection\n"
            msg += "- To remove directory protection, delete .ai-read-deny manually\n"
            msg += "- This cannot be done by AI agents (intentional security design)\n"
        elif is_config_file and is_read_operation:
            msg += "- Use ai-guardian MCP tools to query security status safely:\n"
            msg += "  - get_config() returns feature status (no rule details)\n"
            msg += "  - get_violations() returns metadata (no pattern internals)\n"
            msg += "  - doctor() returns health check results\n"
            msg += "- Users can access files directly via terminal, editor, or CLI\n"
        elif is_config_file:
            msg += "- Configuration files must be edited manually (not by AI agents)\n"
            msg += "- Use your text editor to modify these files\n"
            msg += "- This prevents AI from disabling its own security controls\n"
        else:
            msg += "- This file must be edited manually (not by AI agents)\n"
            msg += "- Use your text editor to make changes\n"
            msg += "- This protection cannot be disabled via configuration\n"

        # Add workaround tip if this looks like documentation mentioning the tool
        if is_likely_documentation:
            check_value_lower = check_value.lower()
            mentions_tool = (
                "ai-guardian" in check_value_lower or "ai_guardian" in check_value_lower
            )
            if mentions_tool:
                msg += "\n💡 TIP: Writing ABOUT the tool (not modifying it)?\n"
                msg += '   Use "ai - guardian" (with spaces) to avoid triggering patterns.\n'
                msg += '   Example: "The ai - guardian tool protects..."\n'

        # Protected file categories
        msg += "\nProtected categories:\n"
        msg += "- ai-guardian configuration files\n"
        msg += "- IDE hook configuration (Claude, Gemini, Augment, Cursor)\n"
        msg += "- ai-guardian package source code\n"
        msg += "- .ai-read-deny marker files\n"

        # Config note - immutable can't be changed
        msg += "\n⚠️ This protection is immutable and cannot be disabled via configuration.\n"
        msg += "It ensures ai-guardian security controls cannot be bypassed.\n"

        return msg

    def _suggest_permission_rule(self, tool_name: str) -> Tuple[str, List[Dict]]:
        """
        Suggest permission rule for a blocked tool.

        Args:
            tool_name: The blocked tool name

        Returns:
            tuple: (matcher, list of {pattern, comment} dicts)
        """
        # Skills
        if tool_name == "Skill":
            return "Skill", [
                {"pattern": "*", "comment": "Allow all skills"},
            ]

        # MCP tools
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__")
            patterns = [{"pattern": tool_name, "comment": "Allow only this tool"}]
            if len(parts) >= 3:
                patterns.append(
                    {
                        "pattern": f"{parts[0]}__{parts[1]}__*",
                        "comment": "Or allow all tools from this server",
                    }
                )
            return "mcp__*", patterns

        # Other tools
        return tool_name, [
            {"pattern": "*", "comment": f"Allow all {tool_name} operations"}
        ]

    def _log_violation(
        self,
        tool_name: str,
        check_value: str,
        reason: str,
        matcher: str,
        hook_data: Dict,
        violation_type: str = ViolationType.TOOL_PERMISSION,
    ):
        """Log a tool permission violation via unified ``log_violation``."""
        if not HAS_VIOLATION_LOGGER:
            return

        from ai_guardian.scanners.scan_result import ScanResult, generate_violation_id
        from ai_guardian.violations.log_violation import ScanContext, log_violation

        file_path_tools = {"Write", "Read", "Edit", "NotebookEdit"}
        file_path = check_value if tool_name in file_path_tools else None
        suggested_matcher, suggested_patterns = self._suggest_permission_rule(tool_name)
        all_paths = get_all_config_paths()

        result = ScanResult(
            detected=True,
            violation_type=violation_type,
            id=generate_violation_id(),
            severity="warning",
            file_path=file_path,
            error_message=reason,
        )
        log_violation(
            result,
            ScanContext(
                ide_type=self._detect_ide_type(hook_data),
                hook_event=hook_data.get("hook_event_name", ""),
                project_path=os.getcwd(),
                session_id=hook_data.get("session_id"),
                tool_use_id=hook_data.get("tool_use_id"),
            ),
            blocked_overrides={
                "tool_name": tool_name,
                "tool_value": check_value,
                "matcher": matcher,
            },
            suggestion={
                "action": "add_allow_pattern",
                "config_path": str(all_paths["global"]),
                "config_paths": {k: str(v) for k, v in all_paths.items()},
                "rule": {
                    "matcher": suggested_matcher,
                    "mode": "allow",
                    "patterns": [p["pattern"] for p in suggested_patterns],
                },
            },
        )

    def _detect_ide_type(self, hook_data: Dict) -> str:
        """
        Detect IDE type from hook data.

        Args:
            hook_data: Hook data from PreToolUse event

        Returns:
            str: IDE type (claude_code, cursor, github_copilot, unknown)
        """
        # Check for environment variable override
        ide_override = os.environ.get("AI_GUARDIAN_IDE_TYPE", "").lower()
        if ide_override:
            return ide_override

        # GitHub Copilot detection
        if "toolName" in hook_data or ("timestamp" in hook_data and "cwd" in hook_data):
            return "github_copilot"

        # Cursor detection
        if "cursor_version" in hook_data or "hook_name" in hook_data:
            return "cursor"

        # Claude Code detection
        if "hook_event_name" in hook_data and hook_data.get("hook_event_name") in [
            HookEvent.PROMPT.display_name,
            HookEvent.PRE_TOOL_USE.display_name,
        ]:
            return "claude_code"

        return "unknown"

    def _load_config(self) -> Dict:
        """
        Load and merge tool policy configurations.

        Priority (highest to lowest):
        1. Remote configs (from remote_configs URLs)
        2. User global config
        3. Project local config
        4. Defaults

        Immutability enforcement:
        - Remote configs can mark sections/matchers as immutable
        - Local/user configs cannot override immutable sections or add rules for immutable matchers

        Returns:
            dict: Merged configuration
        """
        # Start with defaults
        config = self._get_defaults()

        # Load all configs first
        local_config, local_config_path = self._load_local_config()
        user_config, user_config_path = self._load_user_config()
        remote_configs = self._load_remote_configs(
            local_config, local_config_path, user_config, user_config_path
        )

        # Extract immutability constraints from remote configs
        immutable_matchers = self._get_immutable_matchers(remote_configs)
        immutable_sections = self._get_immutable_sections(remote_configs)

        # Merge project local config (with immutability filtering)
        if local_config:
            config = self._merge_configs(
                config, local_config, immutable_matchers, immutable_sections
            )

        # Merge user global config (with immutability filtering)
        if user_config:
            config = self._merge_configs(
                config, user_config, immutable_matchers, immutable_sections
            )

        # Merge remote configs (highest priority, no filtering needed)
        for remote_config in remote_configs:
            config = self._merge_configs(config, remote_config, set(), set())

        # Discover and add patterns from permissions_directories
        self._discover_from_directories(config)

        # Auto-generate directory rules from skill permissions (if enabled)
        self._auto_generate_directory_rules(config)

        permissions = config.get("permissions", {})
        rule_count = len(
            permissions.get("rules", [])
            if isinstance(permissions, dict)
            else permissions if isinstance(permissions, list) else []
        )
        logger.debug(f"Config loaded: {rule_count} permission rule(s)")

        return config

    def _get_immutable_matchers(self, remote_configs: List[Dict]) -> Set[str]:
        """
        Extract set of matchers marked as immutable in remote configs.

        Args:
            remote_configs: List of remote configuration dictionaries

        Returns:
            set: Set of matcher names that are immutable (e.g., {"Skill", "Bash"})
        """
        immutable_matchers = set()

        for remote_config in remote_configs:
            permissions = remote_config.get("permissions", [])
            # Handle new unified structure (permissions is an object with rules)
            if isinstance(permissions, dict):
                rules = permissions.get("rules", [])
            else:
                # Legacy format (permissions is an array)
                rules = permissions

            for rule in rules:
                if rule.get("immutable", False):
                    matcher = rule.get("matcher")
                    if matcher:
                        immutable_matchers.add(matcher)
                        logger.debug(
                            f"Matcher '{matcher}' marked as immutable in remote config"
                        )

        return immutable_matchers

    def _get_immutable_sections(self, remote_configs: List[Dict]) -> Set[str]:
        """
        Extract set of section names marked as immutable in remote configs.

        Args:
            remote_configs: List of remote configuration dictionaries

        Returns:
            set: Set of section names that are immutable (e.g., {"prompt_injection", "pattern_server"})
        """
        immutable_sections = set()

        # Sections that can be marked as immutable
        section_names = [
            "prompt_injection",
            "pattern_server",
            "secret_scanning",
            "directory_exclusions",
            "permissions",
        ]

        for remote_config in remote_configs:
            for section_name in section_names:
                section = remote_config.get(section_name)
                if isinstance(section, dict) and section.get("immutable", False):
                    immutable_sections.add(section_name)
                    logger.debug(
                        f"Section '{section_name}' marked as immutable in remote config"
                    )

        return immutable_sections

    def _get_defaults(self) -> Dict:
        """Get default empty configuration."""
        return {
            "permissions": {"enabled": True, "immutable": False, "rules": []},
            "permissions_directories": {"deny": [], "allow": []},
            "remote_configs": [],
            "directory_exclusions": {"enabled": False, "paths": []},
        }

    def _load_local_config(self) -> Tuple[Optional[Dict], Optional[Path]]:
        """Load project local configuration from ai-guardian.json.

        Delegates path discovery to get_project_config_path(), which handles
        AI_GUARDIAN_PROJECT_CONFIG env var, IDE env vars (CURSOR_PROJECT_PATH,
        VSCODE_CWD), git root, and CWD fallback.
        """
        config_path = get_project_config_path()
        if not config_path:
            config_path = Path.cwd() / "ai-guardian.json"
        logger.debug(f"Project config path: {config_path}")

        config = self._load_json_file(config_path, "project local")
        return config, config_path if config else None

    def _load_user_config(self) -> Tuple[Optional[Dict], Optional[Path]]:
        """Load user global configuration from ai-guardian config directory."""
        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"
        config = self._load_json_file(config_path, "user global")
        return config, config_path if config else None

    @classmethod
    def _get_schema_validator(cls):
        """
        Get or create the JSON Schema validator (cached).

        Returns:
            Draft7Validator or None: Validator instance or None if jsonschema not available
        """
        if not HAS_JSONSCHEMA:
            return None

        if cls._schema_validator is None:
            try:
                # Load schema from package
                schema_path = (
                    Path(__file__).parent.parent
                    / "schemas"
                    / "ai-guardian-config.schema.json"
                )
                with open(schema_path, "r") as f:
                    schema = json.load(f)

                # Create and cache validator
                cls._schema_validator = Draft7Validator(schema)
                logger.debug("JSON Schema validator loaded and cached")
            except Exception as e:
                logger.warning(f"Failed to load JSON Schema: {e}")
                return None

        return cls._schema_validator

    def _validate_config(self, config: Dict, source_name: str, path: Path) -> bool:
        """
        Validate configuration against JSON Schema.

        Collects all validation errors as warnings in self._config_warnings
        but always returns True so the config is loaded (warn-but-load).
        A schema mismatch in one section is far less dangerous than losing
        all permission rules by dropping the entire config.

        Args:
            config: Configuration dictionary to validate
            source_name: Human-readable source name for error messages
            path: Path to config file (for error messages)

        Returns:
            bool: Always True (config is always loaded; errors are warnings)
        """
        validator = self._get_schema_validator()
        if not validator:
            return True

        try:
            validator.validate(config)
            logger.debug(f"{source_name} config passed schema validation")
            return True
        except JsonSchemaValidationError:
            warnings = []
            for error in validator.iter_errors(config):
                error_path = (
                    " -> ".join(str(p) for p in error.absolute_path)
                    if error.absolute_path
                    else "root"
                )
                warnings.append(
                    f"  Location: {error_path}\n" f"  Error: {error.message}"
                )

            warning_header = (
                f"[ai-guardian] Config validation warning in {source_name} "
                f"config at {path}"
            )
            warning_detail = "\n".join(warnings)
            warning_footer = (
                "Config loaded despite errors. Fix the file to silence this warning."
            )
            full_warning = f"{warning_header}\n{warning_detail}\n{warning_footer}"

            self._config_warnings.append(full_warning)
            print(f"\n{full_warning}\n", flush=True)
            logger.warning(
                f"Schema validation warnings for {source_name} config: "
                f"{len(warnings)} error(s)"
            )
            return True

    def _load_json_file(self, path: Path, source_name: str) -> Optional[Dict]:
        """
        Load and parse a JSON configuration file.

        Delegates JSON parsing to shared _load_json_config(), then adds
        schema validation on top.

        Args:
            path: Path to JSON file
            source_name: Human-readable source name for logging

        Returns:
            dict or None: Parsed JSON config or None if error/not found
        """
        if not path.exists():
            logger.debug(f"No {source_name} config found at {path}")
            return None

        logger.info(f"Loading {source_name} config from {path}")

        config, error_msg = _load_json_config(path)
        if error_msg:
            logger.warning(
                f"Error loading {source_name} config from {path}: {error_msg}"
            )
            return None

        logger.debug(f"Loaded {source_name} config: {config}")

        # Validate against JSON Schema (warn-but-load: warnings collected,
        # config always loaded)
        self._validate_config(config, source_name, path)

        return config

    def _merge_permissions(
        self,
        base_value,
        override_value,
        immutable_matchers: Set[str],
        immutable_sections: Set[str],
    ):
        """
        Merge the "permissions" key from override into base, filtering
        immutable matchers and handling both new (dict) and legacy (list)
        formats.

        Args:
            base_value: Current value of result["permissions"] (may be dict, list, or missing)
            override_value: The override["permissions"] value
            immutable_matchers: Set of matchers that cannot be overridden
            immutable_sections: Set of sections that cannot be overridden

        Returns:
            Merged permissions value
        """
        if isinstance(override_value, dict):
            # New unified format: permissions is an object with enabled, immutable, rules
            base_permissions = (
                base_value
                if isinstance(base_value, dict)
                else {"enabled": True, "immutable": False, "rules": []}
            )

            merged_permissions = base_permissions.copy()

            # Merge enabled field (if not immutable at section level)
            if "enabled" in override_value and "permissions" not in immutable_sections:
                merged_permissions["enabled"] = override_value["enabled"]

            # Merge immutable field (always take from override)
            if "immutable" in override_value:
                merged_permissions["immutable"] = override_value["immutable"]

            # Merge auto_directory_rules field (NEW in v1.8.0, Issue #144)
            if "auto_directory_rules" in override_value:
                merged_permissions["auto_directory_rules"] = override_value[
                    "auto_directory_rules"
                ]

            # Merge rules array with matcher-level immutability filtering
            if "rules" in override_value:
                override_rules = override_value["rules"]
                if isinstance(override_rules, list):
                    # Filter out rules for immutable matchers
                    filtered_rules = []
                    for rule in override_rules:
                        matcher = rule.get("matcher")
                        if matcher in immutable_matchers:
                            logger.info(
                                f"Skipping override for immutable matcher: {matcher}"
                            )
                        else:
                            filtered_rules.append(rule)

                    # Concatenate with existing rules
                    existing_rules = merged_permissions.get("rules", [])
                    if isinstance(existing_rules, list):
                        merged_permissions["rules"] = existing_rules + filtered_rules
                    else:
                        merged_permissions["rules"] = filtered_rules

            return merged_permissions

        elif isinstance(override_value, list):
            # Legacy format: permissions is array of rules directly (pre-v1.4.0)
            logger.debug(
                "Legacy permissions array format in override - converting to new structure"
            )
            # Filter out rules for immutable matchers
            filtered_rules = []
            for rule in override_value:
                matcher = rule.get("matcher")
                if matcher in immutable_matchers:
                    logger.info(f"Skipping override for immutable matcher: {matcher}")
                else:
                    filtered_rules.append(rule)

            # If base is new format (dict), merge into rules
            if isinstance(base_value, dict):
                base_permissions = base_value
                existing_rules = base_permissions.get("rules", [])
                if isinstance(existing_rules, list):
                    base_permissions["rules"] = existing_rules + filtered_rules
                else:
                    base_permissions["rules"] = filtered_rules
                return base_permissions
            # If base is also legacy format (list), just concatenate
            elif isinstance(base_value, list):
                return base_value + filtered_rules
            else:
                # Base is missing or invalid - create new structure
                return {"enabled": True, "immutable": False, "rules": filtered_rules}

        else:
            return override_value

    def _merge_configs(
        self,
        base: Dict,
        override: Dict,
        immutable_matchers: Optional[Set[str]] = None,
        immutable_sections: Optional[Set[str]] = None,
    ) -> Dict:
        """
        Merge two configuration dictionaries with immutability enforcement.

        For permissions: delegates to _merge_permissions() for format handling
        For other lists: concatenate
        For dicts: recursively merge
        For immutable sections: skip override entirely

        Args:
            base: Base configuration
            override: Override configuration (higher priority)
            immutable_matchers: Set of matchers that cannot be overridden (e.g., {"Skill", "Bash"})
            immutable_sections: Set of sections that cannot be overridden (e.g., {"prompt_injection"})

        Returns:
            dict: Merged configuration
        """
        if immutable_matchers is None:
            immutable_matchers = set()
        if immutable_sections is None:
            immutable_sections = set()

        result = base.copy()

        for key, value in override.items():
            # Skip immutable sections entirely
            if key in immutable_sections:
                logger.info(f"Skipping override of immutable section: {key}")
                continue

            if key == "permissions":
                result[key] = self._merge_permissions(
                    result.get(key), value, immutable_matchers, immutable_sections
                )
            elif key in result:
                # If both are lists, concatenate
                if isinstance(result[key], list) and isinstance(value, list):
                    result[key] = result[key] + value
                # If both are dicts, recursively merge (pass through immutability for nested merges)
                elif isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = self._merge_configs(result[key], value, set(), set())
                # Otherwise, override replaces base
                else:
                    result[key] = value
            else:
                result[key] = value

        return result

    def _load_remote_configs(
        self,
        local_config: Optional[Dict],
        local_config_path: Optional[Path],
        user_config: Optional[Dict],
        user_config_path: Optional[Path],
    ) -> List[Dict]:
        """
        Load remote configurations from URLs.

        Uses cascading priority - first source found wins:
        1. System config (/etc/ai-guardian/remote-configs.json)
        2. Environment variable (AI_GUARDIAN_REMOTE_CONFIG_URLS)
        3. User config (~/.config/ai-guardian/ai-guardian.json)
        4. Local config (~/.ai-guardian.json)

        If a higher priority source is found, lower priority sources are ignored.
        This prevents users from bypassing enterprise policies by adding their own
        remote URLs when an enterprise system config is deployed.
        """
        remote_entries = []

        # Priority 1: System-wide config (enterprise deployment)
        system_config_path = self._get_system_config_path()
        if system_config_path and system_config_path.exists():
            try:
                with open(system_config_path) as f:
                    system_config = json.load(f)
                    urls = system_config.get("urls", [])
                    if urls:
                        logger.info(
                            f"Using {len(urls)} enterprise remote URLs (system config)"
                        )
                        for url in urls:
                            remote_entries.append((url, system_config_path))
                        # STOP HERE - ignore user/local configs
                        return self._fetch_remote_configs(remote_entries)
            except Exception as e:
                logger.error(
                    f"Failed to load system config from {system_config_path}: {e}"
                )

        # Priority 2: Environment variable
        env_urls = os.environ.get("AI_GUARDIAN_REMOTE_CONFIG_URLS", "")
        if env_urls:
            logger.info("Using remote URLs from environment variable")
            for url in env_urls.split(","):
                url = url.strip()
                if url:
                    remote_entries.append((url, None))
            if remote_entries:
                # STOP HERE - ignore user/local configs
                return self._fetch_remote_configs(remote_entries)

        # Priority 3: User config
        if user_config and "remote_configs" in user_config:
            remote_config_data = user_config["remote_configs"]
            if isinstance(remote_config_data, dict):
                # New format: {"urls": [...], "refresh_interval_hours": 12, ...}
                urls = remote_config_data.get("urls", [])
                if urls:
                    logger.info(f"Using {len(urls)} remote URLs from user config")
                    for entry in urls:
                        remote_entries.append((entry, user_config_path))
                    # STOP HERE - ignore local config
                    return self._fetch_remote_configs(remote_entries)
            else:
                # Old format: direct list
                for entry in remote_config_data:
                    remote_entries.append((entry, user_config_path))
                if remote_entries:
                    return self._fetch_remote_configs(remote_entries)

        # Priority 4: Local config (lowest priority)
        if local_config and "remote_configs" in local_config:
            remote_config_data = local_config["remote_configs"]
            if isinstance(remote_config_data, dict):
                # New format: {"urls": [...], "refresh_interval_hours": 12, ...}
                urls = remote_config_data.get("urls", [])
                if urls:
                    logger.info(f"Using {len(urls)} remote URLs from local config")
                    for entry in urls:
                        remote_entries.append((entry, local_config_path))
            else:
                # Old format: direct list
                for entry in remote_config_data:
                    remote_entries.append((entry, local_config_path))

        return self._fetch_remote_configs(remote_entries)

    def _load_remote_config(
        self, url: str, base_config_path: Optional[Path], token_env: Optional[str]
    ) -> Optional[Dict]:
        """
        Load a remote configuration from URL.

        Args:
            url: URL or file path
            base_config_path: Base config file path (for relative paths)
            token_env: Optional environment variable name for auth token

        Returns:
            dict or None: Parsed config or None if failed
        """
        try:
            if url.startswith("http://") or url.startswith("https://"):
                # Remote URL - use RemoteFetcher
                logger.info(f"Fetching remote config from: {url}")
                from ai_guardian.patterns.remote import RemoteFetcher

                fetcher = RemoteFetcher()

                # Get token if token_env specified
                headers = {}
                if token_env:
                    token = os.environ.get(token_env)
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                        logger.debug(f"Using token from {token_env}")

                # Fetch config
                config = fetcher.fetch_config(url, headers=headers)

                if not config:
                    return None

                # Validate remote config against JSON schema (warn-but-load)
                self._validate_config(config, f"remote ({url})", Path(url))

                # Security check: prevent remote configs from disabling security features
                # Remote configs MUST NOT be able to disable critical security enforcement
                security_critical_keys = [
                    ("secret_scanning", "enabled"),
                    ("prompt_injection", "enabled"),
                    ("permissions", "enabled"),
                ]

                for key_path in security_critical_keys:
                    # Navigate nested dict
                    current = config
                    for key in key_path[:-1]:
                        if key in current:
                            current = current[key]
                        else:
                            current = None
                            break

                    # Check if final key attempts to disable feature
                    if current is not None and key_path[-1] in current:
                        if current[key_path[-1]] is False:
                            logger.error(
                                f"Remote config {url} attempts to disable security feature: "
                                f"{'.'.join(key_path)}. This is not allowed. Skipping remote config."
                            )
                            return None

                logger.info(
                    f"Remote config validated and passed security checks: {url}"
                )
                return config
            else:
                # Local file path
                file_path = Path(url)
                if not file_path.is_absolute() and base_config_path:
                    file_path = base_config_path.parent / url

                logger.info(f"Loading remote config from local file: {file_path}")
                return self._load_json_file(file_path, f"remote ({url})")

        except Exception as e:
            logger.warning(f"Error loading remote config from {url}: {e}")
            return None

    def _get_system_config_path(self) -> Optional[Path]:
        """
        Get platform-specific system config path for enterprise deployment.

        Returns:
            Path to system config file or None if platform not supported
        """
        system_platform = platform.system()

        if system_platform == "Windows":
            return Path("C:/ProgramData/ai-guardian/remote-configs.json")
        elif system_platform in ("Linux", "Darwin"):
            # Linux and macOS use /etc
            return Path("/etc/ai-guardian/remote-configs.json")
        else:
            logger.warning(f"Unsupported platform for system config: {system_platform}")
            return None

    def _fetch_remote_configs(self, remote_entries: List[Tuple]) -> List[Dict]:
        """
        Fetch configs from remote URLs.

        Args:
            remote_entries: List of (url, base_path) tuples

        Returns:
            List of successfully loaded config dicts
        """
        remote_configs = []

        for entry, base_path in remote_entries:
            try:
                # Parse entry (string or dict with token_env)
                if isinstance(entry, str):
                    url = entry
                    token_env = None
                elif isinstance(entry, dict):
                    url = entry.get("url")
                    token_env = entry.get("token_env")
                else:
                    logger.warning(f"Invalid remote_configs entry: {entry}")
                    continue

                if not url:
                    continue

                config = self._load_remote_config(url, base_path, token_env)
                if config:
                    remote_configs.append(config)
            except Exception as e:
                logger.warning(f"Failed to load remote config: {e}")

        return remote_configs

    def _discover_from_directories(self, config: Dict) -> None:
        """
        Discover patterns from permissions_directories and add to config.

        Supports both old format (allow/deny arrays) and new format (array with matcher/mode).

        Modifies config in-place by adding permission rules.

        Args:
            config: Configuration dict
        """
        try:
            from ai_guardian.skill_discovery import SkillDiscovery

            discovery = SkillDiscovery()
            cache_ttl = int(os.environ.get("AI_GUARDIAN_SKILL_CACHE_TTL_HOURS", "24"))

            permissions_dirs = config.get("permissions_directories", {})

            # New format: array with matcher/mode
            if isinstance(permissions_dirs, list):
                for dir_entry in permissions_dirs:
                    matcher = dir_entry.get("matcher", "Skill")
                    mode = dir_entry.get("mode", "allow")

                    discovered_items = self._discover_directory_items(
                        discovery, dir_entry, cache_ttl
                    )
                    if discovered_items:
                        self._add_to_permission_rule(
                            config, matcher, mode, discovered_items
                        )
                return

            # Old format: dict with allow/deny arrays (backward compatibility)
            # Process allow directories
            allow_dirs = permissions_dirs.get("allow", [])
            for dir_entry in allow_dirs:
                discovered_items = self._discover_directory_items(
                    discovery, dir_entry, cache_ttl
                )
                if discovered_items:
                    matcher = dir_entry.get("matcher", "Skill")
                    self._add_to_permission_rule(
                        config, matcher, "allow", discovered_items
                    )

            # Process deny directories
            deny_dirs = permissions_dirs.get("deny", [])
            for dir_entry in deny_dirs:
                discovered_items = self._discover_directory_items(
                    discovery, dir_entry, cache_ttl
                )
                if discovered_items:
                    matcher = dir_entry.get("matcher", "Skill")
                    self._add_to_permission_rule(
                        config, matcher, "deny", discovered_items
                    )

        except ImportError:
            logger.debug("Skill discovery not available")
        except Exception as e:
            logger.error(f"Error discovering from directories: {e}")

    def _discover_directory_items(
        self, discovery, dir_entry: Dict, cache_ttl: int
    ) -> List[str]:
        """
        Discover items from a single directory entry.

        Args:
            discovery: SkillDiscovery instance
            dir_entry: Directory entry dict with url, matcher, token_env
            cache_ttl: Cache TTL in hours

        Returns:
            list: List of item names (without matcher prefix)
        """
        try:
            url = dir_entry.get("url")
            token_env = dir_entry.get("token_env")

            if not url:
                return []

            # Discover items from directory
            items = discovery.discover_skills(
                url, cache_ttl_hours=cache_ttl, token_env=token_env
            )

            # Extract just the names (remove category prefix if present)
            names = []
            for item in items:
                if ":" in item:
                    name = item.split(":", 1)[1]
                else:
                    name = item
                names.append(name)

            return names

        except Exception as e:
            logger.error(f"Error discovering items from {dir_entry}: {e}")
            return []

    def _add_to_permission_rule(
        self, config: Dict, matcher: str, list_type: str, items: List[str]
    ) -> None:
        """
        Add items to a permission rule (or create one if needed).

        Args:
            config: Configuration dict
            matcher: Matcher pattern (e.g., "Skill", "mcp__*")
            list_type: "allow" or "deny"
            items: List of patterns to add
        """
        # Ensure permissions is the new unified structure
        if "permissions" not in config:
            config["permissions"] = {"enabled": True, "immutable": False, "rules": []}

        permissions = config["permissions"]

        # Handle new unified format
        if isinstance(permissions, dict):
            if "rules" not in permissions:
                permissions["rules"] = []
            rules = permissions["rules"]
        # Legacy format: array directly
        elif isinstance(permissions, list):
            rules = permissions
        else:
            # Invalid format - create new structure
            config["permissions"] = {"enabled": True, "immutable": False, "rules": []}
            rules = config["permissions"]["rules"]

        # Find existing rule with this matcher and mode
        mode = list_type  # "allow" or "deny"
        for rule in rules:
            if rule.get("matcher") == matcher and rule.get("mode") == mode:
                # Add to existing rule's patterns
                if "patterns" not in rule:
                    rule["patterns"] = []
                rule["patterns"].extend(items)
                return

        # No existing rule - create new one
        new_rule = {"matcher": matcher, "mode": mode, "patterns": items}
        rules.append(new_rule)

    def _auto_generate_directory_rules(self, config: Dict) -> None:
        """
        Auto-generate directory rules from skill permissions.

        If auto_directory_rules.enabled is true, generates directory rules
        for allowed skills and inserts them AFTER user rules but BEFORE
        immutable rules (so generated rules override broad user denies).

        Rule order (last-match-wins):
          Position 0-N:     User rules (broadest scope)
          Position N+1-M:   Generated rules (specific exceptions from auto_directory_rules)
          Final positions:  Immutable rules (strongest - override all)

        Args:
            config: Configuration dict (modified in-place)
        """
        try:
            # Check if auto-generation is enabled
            permissions = config.get("permissions", {})
            auto_config = permissions.get("auto_directory_rules", {})

            if not auto_config.get("enabled", False):
                logger.debug("Auto-generation of directory rules is disabled")
                return

            # Generate directory rules
            from ai_guardian.tools.directory_rules import (
                DirectoryRuleGenerator,
                insert_generated_rules,
            )

            generator = DirectoryRuleGenerator(config)
            generated_rules = generator.generate_directory_rules()

            if generated_rules:
                # Insert AFTER user rules, BEFORE immutable rules
                insert_generated_rules(config, generated_rules)
                logger.info(
                    f"Auto-generated {len(generated_rules)} directory rules from skill permissions"
                )
            else:
                logger.debug("No directory rules generated (no matching skills found)")

        except ImportError:
            logger.debug("Directory rule generator not available")
        except Exception as e:
            logger.error(f"Error auto-generating directory rules: {e}")
            import traceback

            logger.debug(traceback.format_exc())
