"""IDE hook setup and pre-commit hook management for ai-guardian."""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_guardian.config.utils import get_config_dir
from ai_guardian.constants import CRUSH_HOOK_EVENTS, CURSOR_HOOK_EVENTS, HookEvent
from ai_guardian.setup.utils import (
    _create_vbs_wrapper,
    _is_ai_guardian_command,
    _resolve_binary_path,
    _resolve_opencode_config,
    _strip_jsonc_comments,
    _substitute_command,
    _upgrade_ide_flag,
)


class IDESetup:
    """Handle IDE hook setup and configuration."""

    # IDE configuration paths (base config)
    # Each IDE can specify:
    # - config_path: Default path to config file
    # - config_dir_env_var: Optional environment variable for custom config directory
    # - config_filename: Filename to use with custom config directory
    IDE_CONFIGS = {
        "claude": {
            "name": "Claude Code",
            "mcp_client_name": "claude-code",
            "config_path": "~/.claude/settings.json",
            "config_dir_env_var": "CLAUDE_CONFIG_DIR",  # Respects this env var
            "config_filename": "settings.json",
            # CRITICAL: ai-guardian MUST be the FIRST PostToolUse hook.
            # Claude Code only displays the first hook's systemMessage field.
            # Log mode warnings are displayed in PostToolUse - if ai-guardian is not first, warnings are suppressed.
            # See docs/HOOK_ORDERING.md for details.
            "hooks": {
                HookEvent.PROMPT.display_name: [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ai-guardian",
                                "statusMessage": "🛡️ Scanning prompt...",
                            }
                        ],
                    }
                ],
                HookEvent.PRE_TOOL_USE.display_name: [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ai-guardian",
                                "statusMessage": "🛡️ Checking tool permissions...",
                            }
                        ],
                    }
                ],
                HookEvent.POST_TOOL_USE.display_name: [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ai-guardian",
                                "statusMessage": "🛡️ Scanning tool output...",
                            }
                        ],
                    }
                ],
                HookEvent.SESSION_START.display_name: [
                    {
                        "matcher": "startup",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ai-guardian",
                                "statusMessage": "🛡️ Scanning agent config files...",
                            }
                        ],
                    }
                ],
                HookEvent.SESSION_END.display_name: [
                    {"hooks": [{"type": "command", "command": "ai-guardian"}]}
                ],
                HookEvent.POST_COMPACT.display_name: [
                    {"hooks": [{"type": "command", "command": "ai-guardian"}]}
                ],
            },
        },
        "cursor": {
            "name": "Cursor IDE",
            "mcp_client_name": "cursor",
            "config_path": "~/.cursor/hooks.json",
            "config_dir_env_var": None,
            "config_filename": "hooks.json",
            "hooks": {
                "version": 1,
                "beforeSubmitPrompt": [{"command": "ai-guardian"}],
                "beforeReadFile": [{"command": "ai-guardian"}],
                "beforeShellExecution": [{"command": "ai-guardian"}],
                "afterShellExecution": [{"command": "ai-guardian"}],
                "preToolUse": [{"command": "ai-guardian"}],
                "postToolUse": [{"command": "ai-guardian"}],
            },
        },
        "copilot": {
            "name": "GitHub Copilot",
            "mcp_client_name": "github-copilot",
            "config_path": "~/.github/hooks/hooks.json",
            "config_dir_env_var": None,
            "config_filename": "hooks.json",
            "hooks": {
                "userPromptSubmitted": [{"command": "ai-guardian"}],
                "preToolUse": [{"command": "ai-guardian"}],
            },
        },
        "codex": {
            "name": "OpenAI Codex",
            "mcp_client_name": "codex-cli",
            "config_path": "~/.codex/hooks.json",
            "config_dir_env_var": None,
            "config_filename": "hooks.json",
            "hooks": {
                HookEvent.PROMPT.display_name: [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ai-guardian",
                                "timeout": 300,
                                "statusMessage": "🛡️ Scanning prompt...",
                            }
                        ]
                    }
                ],
                HookEvent.PRE_TOOL_USE.display_name: [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ai-guardian",
                                "timeout": 300,
                                "statusMessage": "🛡️ Checking tool permissions...",
                            }
                        ],
                    }
                ],
                HookEvent.POST_TOOL_USE.display_name: [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ai-guardian",
                                "timeout": 60,
                                "statusMessage": "🛡️ Scanning tool output...",
                            }
                        ],
                    }
                ],
            },
        },
        "windsurf": {
            "name": "Windsurf",
            "mcp_client_name": "windsurf",
            "config_path": "~/.codeium/windsurf/hooks.json",
            "config_dir_env_var": None,
            "config_filename": "hooks.json",
            "hooks": {
                "hooks": {
                    "pre_user_prompt": [{"command": "ai-guardian"}],
                    "pre_run_command": [{"command": "ai-guardian"}],
                    "post_run_command": [{"command": "ai-guardian"}],
                    "pre_read_code": [{"command": "ai-guardian"}],
                    "post_read_code": [{"command": "ai-guardian"}],
                    "pre_write_code": [{"command": "ai-guardian"}],
                    "post_write_code": [{"command": "ai-guardian"}],
                    "pre_mcp_tool_use": [{"command": "ai-guardian"}],
                    "post_mcp_tool_use": [{"command": "ai-guardian"}],
                }
            },
        },
        "gemini": {
            "name": "Google Gemini CLI",
            "mcp_client_name": "gemini-cli",
            "config_path": "~/.gemini/settings.json",
            "config_dir_env_var": None,
            "config_filename": "settings.json",
            "hooks": {
                "hooks": [
                    {
                        "event": HookEvent.SESSION_START.display_name,
                        "command": "ai-guardian",
                    },
                    {"event": "BeforeAgent", "command": "ai-guardian"},
                    {"event": "BeforeTool", "matcher": ".*", "command": "ai-guardian"},
                    {"event": "AfterTool", "matcher": ".*", "command": "ai-guardian"},
                ]
            },
        },
        "cline": {
            "name": "Cline",
            "config_path": ".clinerules/hooks",
            "config_dir_env_var": None,
            "config_filename": None,
            "script_based": True,
            "hook_scripts": [
                HookEvent.PRE_TOOL_USE.display_name,
                HookEvent.POST_TOOL_USE.display_name,
                HookEvent.PROMPT.display_name,
            ],
            "script_content": "#!/bin/sh\nai-guardian\n",
        },
        "zoocode": {
            "name": "ZooCode",
            "config_path": ".clinerules/hooks",
            "config_dir_env_var": None,
            "config_filename": None,
            "script_based": True,
            "hook_scripts": [
                HookEvent.PRE_TOOL_USE.display_name,
                HookEvent.POST_TOOL_USE.display_name,
                HookEvent.PROMPT.display_name,
            ],
            "script_content": "#!/bin/sh\nai-guardian\n",
        },
        "kiro": {
            "name": "Kiro",
            "mcp_client_name": "kiro",
            "config_path": ".kiro/hooks",
            "config_dir_env_var": None,
            "config_filename": None,
            "script_based": True,
            "hook_scripts": [
                HookEvent.PRE_TOOL_USE.display_name,
                HookEvent.POST_TOOL_USE.display_name,
                "PromptSubmit",
            ],
            "script_content": "#!/bin/sh\nai-guardian\n",
        },
        "junie": {
            "name": "Junie",
            "config_path": ".junie/guidelines",
            "config_dir_env_var": None,
            "config_filename": None,
            "mcp_only": True,
        },
        "aiderdesk": {
            "name": "AiderDesk",
            "config_path": "~/.aider-desk/extensions/ai-guardian",
            "config_dir_env_var": None,
            "config_filename": None,
            "extension_based": True,
        },
        "openclaw": {
            "name": "OpenClaw",
            "config_path": "~/.openclaw/plugins/ai-guardian",
            "config_dir_env_var": None,
            "config_filename": None,
            "extension_based": True,
        },
        "opencode": {
            "name": "OpenCode",
            "mcp_client_name": "opencode",
            "config_path": "~/.config/opencode/plugins",
            "config_dir_env_var": None,
            "config_filename": None,
            "plugin_file": True,
        },
        "augment": {
            "name": "Augment Code",
            "mcp_client_name": "augment",
            "config_path": "~/.augment/settings.json",
            "config_dir_env_var": None,
            "config_filename": "settings.json",
            "hooks": {
                "hooks": {
                    HookEvent.PRE_TOOL_USE.display_name: [
                        {
                            "matcher": "launch-process|str-replace-editor|save-file|view|remove-files",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "ai-guardian",
                                    "timeout": 5000,
                                }
                            ],
                            "metadata": {
                                "includeUserContext": False,
                                "includeMCPMetadata": False,
                                "includeConversationData": False,
                            },
                        }
                    ],
                    HookEvent.POST_TOOL_USE.display_name: [
                        {
                            "matcher": "launch-process|str-replace-editor|save-file|view|remove-files",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "ai-guardian",
                                    "timeout": 5000,
                                }
                            ],
                            "metadata": {
                                "includeUserContext": False,
                                "includeMCPMetadata": False,
                                "includeConversationData": False,
                            },
                        }
                    ],
                }
            },
        },
        "crush": {
            "name": "Crush",
            "config_path": ".crush.json",
            "config_dir_env_var": None,
            "config_filename": "crush.json",
            "hooks": {
                "hooks": {
                    event: [
                        {
                            "name": "ai-guardian",
                            "command": "ai-guardian",
                            "timeout": 30,
                        }
                    ]
                    for event in CRUSH_HOOK_EVENTS
                }
            },
        },
        "dummy-agent": {
            "name": "Dummy Agent",
            # No external config file — the dummy agent fires hooks internally.
            "config_path": None,
            "config_dir_env_var": None,
            "config_filename": None,
            "hooks": {},
        },
    }

    @staticmethod
    def get_claude_config_path() -> str:
        """
        Get Claude Code config path, respecting CLAUDE_CONFIG_DIR environment variable.

        Returns:
            str: Path to Claude Code settings.json
        """
        claude_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if claude_config_dir:
            return os.path.join(claude_config_dir, "settings.json")
        return "~/.claude/settings.json"

    def get_config_path(self, ide_type: str) -> str:
        """
        Get IDE config path, respecting IDE-specific environment variables.

        This method checks for IDE-specific environment variables that allow users
        to customize the config directory location (e.g., CLAUDE_CONFIG_DIR).

        Args:
            ide_type: IDE type ('claude' or 'cursor')

        Returns:
            str: Path to IDE config file, or None if IDE type unknown
        """
        if ide_type not in self.IDE_CONFIGS:
            return None

        ide_config = self.IDE_CONFIGS[ide_type]
        base_config_path = ide_config["config_path"]

        # Check if this IDE supports a custom config directory via env var
        # Only use env var if the config_path is still the default value
        env_var_name = ide_config.get("config_dir_env_var")
        if env_var_name:
            default_path = ide_config["config_path"]
            if base_config_path == default_path:
                # Check environment variable
                custom_config_dir = os.environ.get(env_var_name)
                if custom_config_dir:
                    config_filename = ide_config.get("config_filename", "settings.json")
                    return os.path.join(custom_config_dir, config_filename)

        return base_config_path

    def __init__(self):
        """Initialize IDE setup manager."""
        self._last_merged_config: Optional[Dict] = None

    def supports_hooks(self, ide_type: str) -> bool:
        """Check if an IDE supports hook installation.

        Returns False for mcp_only IDEs and unknown IDE types.
        """
        ide_config = self.IDE_CONFIGS.get(ide_type)
        if not ide_config:
            return False
        return not ide_config.get("mcp_only", False)

    def check_hooks_for_ide(self, ide_type: str) -> Tuple[bool, str]:
        """Check if hooks are configured for a specific IDE.

        Returns (configured: bool, detail: str).
        """
        ide_config = self.IDE_CONFIGS.get(ide_type)
        if not ide_config:
            return False, f"Unknown IDE type: {ide_type}"

        ide_name = ide_config.get("name", ide_type)

        if ide_config.get("mcp_only"):
            return True, f"{ide_name}: MCP-only (no hooks needed)"

        config_path_str = self.get_config_path(ide_type)
        if not config_path_str:
            return False, f"{ide_name}: no config path"

        config_path = Path(config_path_str).expanduser()
        configured = self.check_hooks_configured(config_path, ide_type)
        if configured:
            return True, f"{ide_name}: configured"
        return False, f"{ide_name}: not configured"

    @classmethod
    def get_ide_for_mcp_client(cls, client_name: str) -> Optional[str]:
        """Reverse-lookup IDE type from an MCP client name.

        Returns the IDE key (e.g. 'claude') or None if no match.
        """
        for ide_type, ide_config in cls.IDE_CONFIGS.items():
            if ide_config.get("mcp_client_name") == client_name:
                return ide_type
        return None

    def verify_gitleaks_installed(self) -> Tuple[bool, str]:
        """
        Check if Gitleaks binary is installed and accessible.

        Returns:
            tuple: (success: bool, message: str)
                - success: True if Gitleaks is installed, False otherwise
                - message: Status message with details or installation instructions
        """
        try:
            result = subprocess.run(
                ["gitleaks", "version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Extract version from output (first line typically contains version)
                version_line = (
                    result.stdout.strip().split("\n")[0]
                    if result.stdout
                    else "unknown version"
                )
                return True, f"✓ Gitleaks is installed: {version_line}"
            else:
                return False, "❌ Gitleaks command failed - please reinstall"
        except FileNotFoundError:
            return False, (
                "❌ Gitleaks not found\n"
                "   Install from: https://github.com/gitleaks/gitleaks#installing\n"
                "   Or use: brew install gitleaks (macOS)"
            )
        except subprocess.TimeoutExpired:
            return False, "❌ Gitleaks check timed out - installation may be corrupted"
        except Exception as e:
            return False, f"❌ Error checking Gitleaks: {e}"

    def detect_ide(self) -> Optional[str]:
        """
        Auto-detect installed IDE based on config files.

        Returns:
            str or None: IDE type ('claude' or 'cursor') or None if not detected
        """
        detected_ides = []

        for ide_type in self.IDE_CONFIGS.keys():
            raw_path = self.get_config_path(ide_type)
            if not raw_path:
                continue
            config_path = Path(raw_path).expanduser()
            if config_path.parent.exists():
                detected_ides.append(ide_type)

        if not detected_ides:
            return None
        elif len(detected_ides) == 1:
            return detected_ides[0]
        else:
            # Multiple IDEs detected - return None to prompt user
            return None

    def list_detected_ides(self) -> List[str]:
        """
        List all detected IDEs.

        Returns:
            list: List of detected IDE types
        """
        detected = []
        for ide_type in self.IDE_CONFIGS.keys():
            raw_path = self.get_config_path(ide_type)
            if not raw_path:
                continue
            config_path = Path(raw_path).expanduser()
            if config_path.parent.exists():
                detected.append(ide_type)
        return detected

    def backup_config(self, config_path: Path) -> Optional[Path]:
        """
        Create backup of existing config file.

        Args:
            config_path: Path to config file

        Returns:
            Path or None: Path to backup file or None if failed
        """
        try:
            if not config_path.exists():
                return None

            backup_path = config_path.with_suffix(config_path.suffix + ".backup")

            # Read and write to create backup
            with open(config_path, "r", encoding="utf-8") as src:
                content = src.read()

            with open(backup_path, "w", encoding="utf-8") as dst:
                dst.write(content)

            return backup_path

        except Exception as e:
            print(f"Error creating backup: {e}", file=sys.stderr)
            return None

    def merge_hooks(
        self, existing_config: Dict, ai_guardian_hooks: Dict, ide_type: str
    ) -> Tuple[Dict, List[str]]:
        """
        Merge ai-guardian hooks into existing config, ensuring ai-guardian is first.

        CRITICAL: ai-guardian MUST be first in PostToolUse for log mode warning visibility.
        Recommended first in UserPromptSubmit/PreToolUse for consistency.

        Args:
            existing_config: Existing IDE configuration
            ai_guardian_hooks: AI Guardian hooks to add
            ide_type: IDE type ('claude' or 'cursor')

        Returns:
            tuple: (merged_config: dict, warnings: list of str)
                - merged_config: Updated configuration
                - warnings: List of warning messages if multiple hooks detected
        """
        warnings = []

        if ide_type == "claude":
            # Claude Code: merge into hooks section
            if "hooks" not in existing_config:
                existing_config["hooks"] = {}

            for hook_name in [
                HookEvent.SESSION_START.display_name,
                HookEvent.PROMPT.display_name,
                HookEvent.PRE_TOOL_USE.display_name,
                HookEvent.POST_TOOL_USE.display_name,
                HookEvent.SESSION_END.display_name,
                HookEvent.POST_COMPACT.display_name,
            ]:
                if hook_name not in ai_guardian_hooks:
                    continue

                # Get or create the hook type array
                if hook_name not in existing_config["hooks"]:
                    existing_config["hooks"][hook_name] = []

                # Find or create the "*" matcher entry
                hook_list = existing_config["hooks"][hook_name]
                star_matcher = None
                star_matcher_idx = -1

                for idx, entry in enumerate(hook_list):
                    if isinstance(entry, dict) and entry.get("matcher") == "*":
                        star_matcher = entry
                        star_matcher_idx = idx
                        break

                # If no "*" matcher exists, create it from ai_guardian_hooks
                if star_matcher is None:
                    # Use the template from ai_guardian_hooks
                    existing_config["hooks"][hook_name] = ai_guardian_hooks[hook_name]
                    continue

                # Get or create hooks array within the matcher
                if "hooks" not in star_matcher:
                    star_matcher["hooks"] = []

                hooks_array = star_matcher["hooks"]

                # Find other hooks (not ai-guardian)
                ai_guardian_exists = False
                other_hooks = []

                for idx, hook in enumerate(hooks_array):
                    if isinstance(hook, dict) and _is_ai_guardian_command(
                        hook.get("command", "")
                    ):
                        ai_guardian_exists = True
                    else:
                        other_hooks.append(hook)

                # Always use the ai-guardian hook from template for consistency
                template_matcher = ai_guardian_hooks[hook_name][0]
                ai_guardian_hook = template_matcher["hooks"][0]

                # Check if there are other hooks (warn user about ordering)
                if other_hooks:
                    hook_names = []
                    for h in other_hooks:
                        if isinstance(h, dict):
                            cmd = h.get("command", "unknown")
                            hook_names.append(cmd)

                    warnings.append(
                        f"⚠️  {hook_name}: Found other hooks [{', '.join(hook_names)}]. "
                        f"ai-guardian has been placed first to ensure warnings display correctly."
                    )

                # Rebuild hooks array with ai-guardian first
                star_matcher["hooks"] = [ai_guardian_hook] + other_hooks
                existing_config["hooks"][hook_name][star_matcher_idx] = star_matcher

            return existing_config, warnings

        elif ide_type == "cursor":
            # Cursor: merge hooks at top level
            if "hooks" not in existing_config:
                existing_config["hooks"] = {}

            # Ensure version is set
            if "version" not in existing_config:
                existing_config["version"] = 1

            # Merge all Cursor hooks
            for hook_name in CURSOR_HOOK_EVENTS:
                if hook_name in ai_guardian_hooks:
                    existing_config["hooks"][hook_name] = ai_guardian_hooks[hook_name]

            return existing_config, warnings

        elif ide_type == "codex":
            # Codex: same nested structure as Claude Code (hooks.json)
            if "hooks" not in existing_config:
                existing_config["hooks"] = {}

            for hook_name in [
                HookEvent.PROMPT.display_name,
                HookEvent.PRE_TOOL_USE.display_name,
                HookEvent.POST_TOOL_USE.display_name,
            ]:
                if hook_name not in ai_guardian_hooks:
                    continue

                if hook_name not in existing_config["hooks"]:
                    existing_config["hooks"][hook_name] = []

                hook_list = existing_config["hooks"][hook_name]
                template_entry = ai_guardian_hooks[hook_name][0]
                target_matcher = template_entry.get("matcher")

                matched_entry = None
                matched_idx = -1
                for idx, entry in enumerate(hook_list):
                    if (
                        isinstance(entry, dict)
                        and entry.get("matcher") == target_matcher
                    ):
                        matched_entry = entry
                        matched_idx = idx
                        break

                if matched_entry is None:
                    existing_config["hooks"][hook_name] = ai_guardian_hooks[hook_name]
                    continue

                if "hooks" not in matched_entry:
                    matched_entry["hooks"] = []

                hooks_array = matched_entry["hooks"]
                other_hooks = []
                for hook in hooks_array:
                    if isinstance(hook, dict) and _is_ai_guardian_command(
                        hook.get("command", "")
                    ):
                        continue
                    other_hooks.append(hook)

                ai_guardian_hook = template_entry["hooks"][0]

                if other_hooks:
                    hook_names = [
                        h.get("command", "unknown")
                        for h in other_hooks
                        if isinstance(h, dict)
                    ]
                    warnings.append(
                        f"⚠️  {hook_name}: Found other hooks [{', '.join(hook_names)}]. "
                        f"ai-guardian has been placed first to ensure warnings display correctly."
                    )

                matched_entry["hooks"] = [ai_guardian_hook] + other_hooks
                existing_config["hooks"][hook_name][matched_idx] = matched_entry

            return existing_config, warnings

        elif ide_type == "windsurf":
            if "hooks" not in existing_config:
                existing_config["hooks"] = {}

            windsurf_events = [
                "pre_user_prompt",
                "pre_run_command",
                "post_run_command",
                "pre_read_code",
                "post_read_code",
                "pre_write_code",
                "post_write_code",
                "pre_mcp_tool_use",
                "post_mcp_tool_use",
            ]
            template_hooks = ai_guardian_hooks.get("hooks", ai_guardian_hooks)
            for event_name in windsurf_events:
                if event_name in template_hooks:
                    existing_config["hooks"][event_name] = template_hooks[event_name]

            return existing_config, warnings

        elif ide_type == "gemini":
            if "hooks" not in existing_config:
                existing_config["hooks"] = []

            template_hooks = ai_guardian_hooks.get("hooks", [])

            other_hooks = [
                h
                for h in existing_config["hooks"]
                if not (
                    isinstance(h, dict)
                    and _is_ai_guardian_command(h.get("command", ""))
                )
            ]

            ag_events = {h.get("event") for h in template_hooks if isinstance(h, dict)}
            other_same_event = [
                h
                for h in other_hooks
                if isinstance(h, dict) and h.get("event") in ag_events
            ]
            if other_same_event:
                hook_names = [h.get("command", "unknown") for h in other_same_event]
                warnings.append(
                    f"⚠️  Found other hooks for same events [{', '.join(hook_names)}]. "
                    f"ai-guardian has been placed first to ensure warnings display correctly."
                )

            existing_config["hooks"] = template_hooks + other_hooks
            return existing_config, warnings

        elif ide_type == "augment":
            if "hooks" not in existing_config:
                existing_config["hooks"] = {}

            template_hooks = ai_guardian_hooks.get("hooks", ai_guardian_hooks)
            for hook_name in [
                HookEvent.PRE_TOOL_USE.display_name,
                HookEvent.POST_TOOL_USE.display_name,
            ]:
                if hook_name not in template_hooks:
                    continue

                if hook_name not in existing_config["hooks"]:
                    existing_config["hooks"][hook_name] = []

                hook_list = existing_config["hooks"][hook_name]
                template_entry = template_hooks[hook_name][0]
                target_matcher = template_entry.get("matcher")

                matched_entry = None
                matched_idx = -1
                for idx, entry in enumerate(hook_list):
                    if (
                        isinstance(entry, dict)
                        and entry.get("matcher") == target_matcher
                    ):
                        matched_entry = entry
                        matched_idx = idx
                        break

                if matched_entry is None:
                    existing_config["hooks"][hook_name] = template_hooks[hook_name]
                    continue

                if "hooks" not in matched_entry:
                    matched_entry["hooks"] = []

                hooks_array = matched_entry["hooks"]
                other_hooks_list = []
                for hook in hooks_array:
                    if isinstance(hook, dict) and _is_ai_guardian_command(
                        hook.get("command", "")
                    ):
                        continue
                    other_hooks_list.append(hook)

                ai_guardian_hook = template_entry["hooks"][0]

                if other_hooks_list:
                    hook_names = [
                        h.get("command", "unknown")
                        for h in other_hooks_list
                        if isinstance(h, dict)
                    ]
                    warnings.append(
                        f"⚠️  {hook_name}: Found other hooks [{', '.join(hook_names)}]. "
                        f"ai-guardian has been placed first to ensure warnings display correctly."
                    )

                matched_entry["hooks"] = [ai_guardian_hook] + other_hooks_list
                existing_config["hooks"][hook_name][matched_idx] = matched_entry

            return existing_config, warnings

        elif ide_type == "crush":
            if "hooks" not in existing_config:
                existing_config["hooks"] = {}

            template_hooks = ai_guardian_hooks.get("hooks", ai_guardian_hooks)
            for event_name in CRUSH_HOOK_EVENTS:
                if event_name not in template_hooks:
                    continue
                if event_name not in existing_config["hooks"]:
                    existing_config["hooks"][event_name] = []

                hook_list = existing_config["hooks"][event_name]
                other_hooks = [
                    h
                    for h in hook_list
                    if not (
                        isinstance(h, dict)
                        and _is_ai_guardian_command(h.get("command", ""))
                    )
                ]
                ag_hook = template_hooks[event_name][0]
                if other_hooks:
                    hook_names = [
                        h.get("command", "unknown")
                        for h in other_hooks
                        if isinstance(h, dict)
                    ]
                    warnings.append(
                        f"⚠️  {event_name}: Found other hooks [{', '.join(hook_names)}]. "
                        f"ai-guardian has been placed first to ensure warnings display correctly."
                    )
                existing_config["hooks"][event_name] = [ag_hook] + other_hooks

            return existing_config, warnings

        return existing_config, warnings

    def check_hooks_configured(self, config_path: Path, ide_type: str) -> bool:
        """
        Check if ai-guardian hooks are already configured.

        Args:
            config_path: Path to IDE config file
            ide_type: IDE type ('claude' or 'cursor')

        Returns:
            bool: True if hooks already configured
        """
        try:
            if not config_path.exists():
                return False

            ide_config = self.IDE_CONFIGS.get(ide_type, {})

            # Plugin-file hooks (OpenCode): check for ai-guardian.ts AND registration
            if ide_config.get("plugin_file"):
                plugin_file = config_path / "ai-guardian.ts"
                if not plugin_file.exists():
                    return False
                try:
                    content = plugin_file.read_text(encoding="utf-8")
                    if "ai-guardian" not in content:
                        return False
                except Exception:
                    return False
                config_file = _resolve_opencode_config()
                if not config_file.exists():
                    return False
                try:
                    raw = config_file.read_text(encoding="utf-8")
                    if config_file.suffix == ".jsonc":
                        raw = _strip_jsonc_comments(raw)
                    cfg = json.loads(raw) if raw.strip() else {}
                    return str(plugin_file) in cfg.get("plugins", [])
                except (json.JSONDecodeError, OSError):
                    return False

            # Extension-based hooks (AiderDesk, OpenClaw): check directory for index.ts
            if ide_config.get("extension_based"):
                ext_dir = config_path if config_path.is_dir() else config_path.parent
                index_path = ext_dir / "index.ts"
                if index_path.exists():
                    try:
                        content = index_path.read_text(encoding="utf-8")
                        if "ai-guardian" in content:
                            return True
                    except Exception:
                        pass  # intentionally silent — best-effort operation
                return False

            # Script-based hooks (Cline, ZooCode, Kiro): check directory for scripts
            if ide_type in ("cline", "zoocode", "kiro"):
                hooks_dir = config_path if config_path.is_dir() else config_path.parent
                ide_config = self.IDE_CONFIGS.get(ide_type, {})
                for script_name in ide_config.get("hook_scripts", []):
                    candidates = [hooks_dir / script_name]
                    if platform.system() == "Windows":
                        candidates.append(hooks_dir / f"{script_name}.bat")
                        candidates.append(hooks_dir / f"{script_name}.ps1")
                    for script_path in candidates:
                        if script_path.exists():
                            try:
                                content = script_path.read_text(encoding="utf-8")
                                if "ai-guardian" in content:
                                    return True
                            except Exception:
                                pass  # intentionally silent — best-effort operation
                return False

            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            if ide_type in ("claude", "codex"):
                hooks = config.get("hooks", {})
                for hook_name in [
                    HookEvent.PROMPT.display_name,
                    HookEvent.PRE_TOOL_USE.display_name,
                    HookEvent.POST_TOOL_USE.display_name,
                ]:
                    if hook_name in hooks:
                        hook_list = hooks[hook_name]
                        if isinstance(hook_list, list):
                            for hook_entry in hook_list:
                                if (
                                    isinstance(hook_entry, dict)
                                    and "hooks" in hook_entry
                                ):
                                    for h in hook_entry["hooks"]:
                                        if isinstance(
                                            h, dict
                                        ) and _is_ai_guardian_command(
                                            h.get("command", "")
                                        ):
                                            return True

            elif ide_type == "cursor":
                hooks = config.get("hooks", {})
                # Check if any Cursor hooks contain ai-guardian
                for hook_name in CURSOR_HOOK_EVENTS:
                    if hook_name in hooks:
                        hook_list = hooks[hook_name]
                        if isinstance(hook_list, list):
                            for h in hook_list:
                                if isinstance(h, dict) and _is_ai_guardian_command(
                                    h.get("command", "")
                                ):
                                    return True

            elif ide_type == "windsurf":
                hooks = config.get("hooks", {})
                for event_name in [
                    "pre_user_prompt",
                    "pre_run_command",
                    "pre_read_code",
                    "pre_write_code",
                    "pre_mcp_tool_use",
                    "post_run_command",
                    "post_read_code",
                    "post_write_code",
                    "post_mcp_tool_use",
                ]:
                    if event_name in hooks:
                        hook_list = hooks[event_name]
                        if isinstance(hook_list, list):
                            for h in hook_list:
                                if isinstance(h, dict) and _is_ai_guardian_command(
                                    h.get("command", "")
                                ):
                                    return True

            elif ide_type == "gemini":
                hooks = config.get("hooks", [])
                if isinstance(hooks, list):
                    for h in hooks:
                        if isinstance(h, dict) and _is_ai_guardian_command(
                            h.get("command", "")
                        ):
                            return True

            elif ide_type == "augment":
                hooks = config.get("hooks", {})
                for hook_name in [
                    HookEvent.PRE_TOOL_USE.display_name,
                    HookEvent.POST_TOOL_USE.display_name,
                ]:
                    if hook_name in hooks:
                        hook_list = hooks[hook_name]
                        if isinstance(hook_list, list):
                            for hook_entry in hook_list:
                                if (
                                    isinstance(hook_entry, dict)
                                    and "hooks" in hook_entry
                                ):
                                    for h in hook_entry["hooks"]:
                                        if isinstance(
                                            h, dict
                                        ) and _is_ai_guardian_command(
                                            h.get("command", "")
                                        ):
                                            return True

            elif ide_type == "crush":
                hooks = config.get("hooks", {})
                for event_name in CRUSH_HOOK_EVENTS:
                    if event_name in hooks:
                        hook_list = hooks[event_name]
                        if isinstance(hook_list, list):
                            for h in hook_list:
                                if isinstance(h, dict) and _is_ai_guardian_command(
                                    h.get("command", "")
                                ):
                                    return True

            return False

        except Exception:
            return False

    def _setup_script_based_hooks(
        self,
        ide_type: str,
        ide_config: Dict,
        hooks_dir: Path,
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        """
        Setup script-based hooks (Cline, ZooCode).

        Creates executable scripts in the hooks directory instead of merging
        into a JSON config file.

        Args:
            ide_type: IDE type ('cline' or 'zoocode')
            ide_config: IDE configuration from IDE_CONFIGS
            hooks_dir: Path to hooks directory
            dry_run: If True, show what would be changed without applying

        Returns:
            tuple: (success: bool, message: str)
        """
        ide_name = ide_config["name"]
        hook_scripts = ide_config.get("hook_scripts", [])
        is_windows = platform.system() == "Windows"

        abs_path = _resolve_binary_path()
        cmd = f"{abs_path} --ide {ide_type}"

        if is_windows:
            script_content = f"@echo off\r\n{cmd}\r\n"
        else:
            script_content = ide_config.get(
                "script_content", "#!/bin/sh\nai-guardian\n"
            )
            script_content = script_content.replace("ai-guardian", cmd, 1)

        if dry_run:
            message = f"[DRY RUN] Would configure {ide_name} hooks at {hooks_dir}:\n"
            for script_name in hook_scripts:
                fname = f"{script_name}.bat" if is_windows else script_name
                message += f"  Create: {hooks_dir / fname}\n"
            message += f"  Script content:\n    {script_content.strip()}\n"
            return True, message

        hooks_dir.mkdir(parents=True, exist_ok=True)

        created = []
        for script_name in hook_scripts:
            fname = f"{script_name}.bat" if is_windows else script_name
            script_path = hooks_dir / fname
            script_path.write_text(script_content, encoding="utf-8")
            if not is_windows:
                script_path.chmod(0o755)
            created.append(fname)

        gitleaks_installed, gitleaks_message = self.verify_gitleaks_installed()

        message = f"✓ Successfully configured {ide_name} hooks at {hooks_dir}\n"
        message += f"  Created scripts: {', '.join(created)}\n"
        message += f"\n  {gitleaks_message}\n"

        if not gitleaks_installed:
            message += (
                "\n  ⚠️  WARNING: Secret scanning will be disabled without Gitleaks!\n"
                "      AI Guardian requires Gitleaks for secret detection.\n"
            )

        message += "\n  Next steps:\n"
        if not gitleaks_installed:
            message += "  1. Install Gitleaks (see above)\n"
            message += f"  2. Restart {ide_name} for changes to take effect\n"
        else:
            message += f"  1. Restart {ide_name} for changes to take effect\n"

        return True, message

    @staticmethod
    def _strip_jsonc_comments(text: str) -> str:
        """Strip single-line (//) and multi-line (/* */) comments from JSONC.

        Quote-aware: skips // and /* inside JSON string literals.
        Delegates to setup_utils._strip_jsonc_comments.
        """
        return _strip_jsonc_comments(text)

    def _register_opencode_plugin(
        self,
        plugin_file: Path,
        plugins_dir: Path,
        dry_run: bool = False,
    ) -> Optional[str]:
        """Register plugin in opencode.json/opencode.jsonc config.

        Returns a status message, or None if registration was skipped.
        """
        config_file = _resolve_opencode_config()
        plugin_path = str(plugin_file)

        if dry_run:
            return f"  Register plugin in: {config_file}\n"

        config: Dict[str, Any] = {}
        if config_file.exists():
            try:
                raw = config_file.read_text(encoding="utf-8")
                if config_file.suffix == ".jsonc":
                    raw = _strip_jsonc_comments(raw)
                if raw.strip():
                    config = json.loads(raw)
            except (json.JSONDecodeError, OSError):
                pass

        plugins = config.get("plugins", [])
        if plugin_path not in plugins:
            plugins.append(plugin_path)
            config["plugins"] = plugins
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(
                json.dumps(config, indent=2) + "\n", encoding="utf-8"
            )

        return None

    def _setup_plugin_file(
        self,
        ide_type: str,
        ide_config: Dict,
        plugins_dir: Path,
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        """Setup plugin-file based hooks (OpenCode).

        Drops a single .ts file into the IDE's plugins directory and
        registers it in opencode.json so OpenCode loads it.
        """
        ide_name = ide_config["name"]
        plugin_file = plugins_dir / "ai-guardian.ts"

        if dry_run:
            message = f"[DRY RUN] Would configure {ide_name} plugin:\n"
            message += f"  Create: {plugin_file}\n"
            reg_msg = self._register_opencode_plugin(
                plugin_file, plugins_dir, dry_run=True
            )
            if reg_msg:
                message += reg_msg
            return True, message

        plugins_dir.mkdir(parents=True, exist_ok=True)

        abs_path = _resolve_binary_path()
        cmd = f"{abs_path} --ide {ide_type}"
        plugin_file.write_text(
            _OPENCODE_PLUGIN_TS.replace("execSync('ai-guardian'", f"execSync('{cmd}'"),
            encoding="utf-8",
        )

        self._register_opencode_plugin(plugin_file, plugins_dir)

        gitleaks_installed, gitleaks_message = self.verify_gitleaks_installed()

        message = f"✓ Successfully configured {ide_name} plugin at {plugin_file}\n"
        message += f"\n  {gitleaks_message}\n"

        if not gitleaks_installed:
            message += (
                "\n  ⚠️  WARNING: Secret scanning will be disabled without Gitleaks!\n"
                "      AI Guardian requires Gitleaks for secret detection.\n"
            )

        message += "\n  Next steps:\n"
        step = 1
        if not gitleaks_installed:
            message += f"  {step}. Install Gitleaks (see above)\n"
            step += 1
        message += f"  {step}. Restart {ide_name} for the plugin to load\n"

        return True, message

    def _setup_extension_based_hooks(
        self,
        ide_type: str,
        ide_config: Dict,
        ext_dir: Path,
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        """
        Setup extension-based hooks (AiderDesk, OpenClaw).

        Creates a TypeScript extension/plugin that delegates to ai-guardian CLI.

        Args:
            ide_type: IDE type ('aiderdesk', 'openclaw')
            ide_config: IDE configuration from IDE_CONFIGS
            ext_dir: Path to extension directory
            dry_run: If True, show what would be changed without applying

        Returns:
            tuple: (success: bool, message: str)
        """
        ide_name = ide_config["name"]
        index_path = ext_dir / "index.ts"
        package_path = ext_dir / "package.json"

        if dry_run:
            message = f"[DRY RUN] Would configure {ide_name} extension at {ext_dir}:\n"
            message += f"  Create: {index_path}\n"
            message += f"  Create: {package_path}\n"
            return True, message

        ext_dir.mkdir(parents=True, exist_ok=True)

        abs_path = _resolve_binary_path()
        cmd = f"{abs_path} --ide {ide_type}"
        if ide_type == "openclaw":
            package_path.write_text(_OPENCLAW_PACKAGE_JSON, encoding="utf-8")
            index_path.write_text(
                _OPENCLAW_PLUGIN_TS.replace(
                    "execSync('ai-guardian'", f"execSync('{cmd}'"
                ),
                encoding="utf-8",
            )
        else:
            package_path.write_text(_AIDERDESK_PACKAGE_JSON, encoding="utf-8")
            index_path.write_text(
                _AIDERDESK_EXTENSION_TS.replace(
                    "execSync('ai-guardian'", f"execSync('{cmd}'"
                ),
                encoding="utf-8",
            )

        gitleaks_installed, gitleaks_message = self.verify_gitleaks_installed()

        message = f"✓ Successfully configured {ide_name} extension at {ext_dir}\n"
        message += "  Created: index.ts, package.json\n"
        message += f"\n  {gitleaks_message}\n"

        if not gitleaks_installed:
            message += (
                "\n  ⚠️  WARNING: Secret scanning will be disabled without Gitleaks!\n"
                "      AI Guardian requires Gitleaks for secret detection.\n"
            )

        message += "\n  Next steps:\n"
        step = 1
        if not gitleaks_installed:
            message += f"  {step}. Install Gitleaks (see above)\n"
            step += 1
        message += f"  {step}. Run: cd {ext_dir} && npm install\n"
        step += 1
        message += (
            f"  {step}. Restart {ide_name} (extension hot-reloads automatically)\n"
        )

        return True, message

    def setup_ide_hooks(
        self, ide_type: str, dry_run: bool = False, force: bool = False
    ) -> Tuple[bool, str]:
        """
        Setup IDE hooks for the specified IDE.

        Args:
            ide_type: IDE type ('claude' or 'cursor')
            dry_run: If True, show what would be changed without applying
            force: If True, overwrite existing hooks

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            if ide_type not in self.IDE_CONFIGS:
                return False, f"Unknown IDE type: {ide_type}"

            # Dummy agent fires hooks internally — no config file to write.
            if ide_type == "dummy-agent":
                import shutil

                binary = shutil.which("ai-guardian")
                if binary:
                    return (
                        True,
                        "Dummy Agent is built into ai-guardian. Run: ai-guardian dummy-agent",
                    )
                return False, "ai-guardian binary not found in PATH"

            ide_config = self.IDE_CONFIGS[ide_type]
            config_path = Path(self.get_config_path(ide_type)).expanduser()
            ide_name = ide_config["name"]

            if ide_config.get("mcp_only"):
                msg = (
                    f"{ide_name} does not support hooks.\n"
                    f"MCP server will be installed. Use --no-mcp to skip.\n"
                    f"Use --rules to install guidelines file.\n"
                    f"  ai-guardian setup --ide {ide_type} --rules"
                )
                return True, msg

            # Check if hooks already configured
            if not force and self.check_hooks_configured(config_path, ide_type):
                return (
                    False,
                    f"ai-guardian hooks already configured for {ide_name}. Use --force to overwrite.",
                )

            # Plugin-file IDEs (OpenCode): drop a single .ts file in plugins dir
            if ide_config.get("plugin_file"):
                return self._setup_plugin_file(
                    ide_type, ide_config, config_path, dry_run
                )

            # Extension-based IDEs (AiderDesk): create TypeScript extension
            if ide_config.get("extension_based"):
                return self._setup_extension_based_hooks(
                    ide_type, ide_config, config_path, dry_run
                )

            # Script-based IDEs (Cline, ZooCode): create executable scripts
            if ide_config.get("script_based"):
                return self._setup_script_based_hooks(
                    ide_type, ide_config, config_path, dry_run
                )

            # Load existing config or create new
            existing_config = {}
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        existing_config = json.load(f)
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON in {config_path}: {e}"

            # Resolve absolute path and substitute into hook templates
            abs_path = _resolve_binary_path()
            resolved_hooks = _substitute_command(
                ide_config["hooks"], abs_path, ide_type
            )

            # Merge hooks
            hook_warnings = []
            if ide_type == "claude":
                merged_config, hook_warnings = self.merge_hooks(
                    existing_config, resolved_hooks, ide_type
                )
            elif ide_type == "cursor":
                merged_config, hook_warnings = self.merge_hooks(
                    existing_config, resolved_hooks, ide_type
                )
            elif ide_type == "copilot":
                # GitHub Copilot: merge hooks at top level
                merged_config = existing_config.copy()
                merged_config["userPromptSubmitted"] = resolved_hooks[
                    "userPromptSubmitted"
                ]
                merged_config["preToolUse"] = resolved_hooks["preToolUse"]
                # Fall through to common config-write path (don't return early)
            elif ide_type == "codex":
                merged_config, hook_warnings = self.merge_hooks(
                    existing_config, resolved_hooks, ide_type
                )
            elif ide_type == "windsurf":
                merged_config, hook_warnings = self.merge_hooks(
                    existing_config, resolved_hooks, ide_type
                )
            elif ide_type == "gemini":
                merged_config, hook_warnings = self.merge_hooks(
                    existing_config, resolved_hooks, ide_type
                )
            elif ide_type == "augment":
                merged_config, hook_warnings = self.merge_hooks(
                    existing_config, resolved_hooks, ide_type
                )
            elif ide_type == "crush":
                merged_config, hook_warnings = self.merge_hooks(
                    existing_config, resolved_hooks, ide_type
                )

            # Upgrade any pre-existing ai-guardian commands to include --ide
            _upgrade_ide_flag(merged_config, ide_type)

            self._last_merged_config = merged_config

            if dry_run:
                # Show what would be changed
                message = (
                    f"[DRY RUN] Would configure {ide_name} hooks at {config_path}:\n"
                )
                message += json.dumps(merged_config, indent=2)
                return True, message

            # Create backup if file exists
            if config_path.exists():
                backup_path = self.backup_config(config_path)
                if backup_path:
                    print(f"✓ Backup created: {backup_path}", file=sys.stderr)

            # Ensure parent directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Write merged config
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(merged_config, f, indent=2)
                f.write("\n")  # Add trailing newline

            # Generate VBS wrapper on Windows for fully hidden execution
            vbs_path = _create_vbs_wrapper(
                f"{abs_path} --ide {ide_type}", config_path.parent
            )

            # Verify Gitleaks installation
            gitleaks_installed, gitleaks_message = self.verify_gitleaks_installed()

            message = f"✓ Successfully configured {ide_name} hooks at {config_path}\n"
            message += f"\n  {gitleaks_message}\n"

            if vbs_path:
                message += (
                    f"\n  Windows: VBS wrapper created at {vbs_path}\n"
                    f"  To fully hide console windows, change the hook command to:\n"
                    f'    wscript.exe "{vbs_path}"\n'
                )

            # Display hook ordering warnings if any
            if hook_warnings:
                message += "\n  Hook Ordering:\n"
                for warning in hook_warnings:
                    message += f"  {warning}\n"
                message += (
                    "\n  📚 For more information about hook ordering, see:\n"
                    "     https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/HOOK_ORDERING.md\n"
                )

            if not gitleaks_installed:
                message += (
                    "\n  ⚠️  WARNING: Secret scanning will be disabled without Gitleaks!\n"
                    "      AI Guardian requires Gitleaks for secret detection.\n"
                )

            message += "\n  Next steps:\n"
            if not gitleaks_installed:
                message += "  1. Install Gitleaks (see above)\n"
                message += f"  2. Restart {ide_name} for changes to take effect\n"
                message += '  3. Test with: echo \'{"prompt": "test"}\' | ai-guardian\n'
            else:
                message += f"  1. Restart {ide_name} for changes to take effect\n"
                message += '  2. Test with: echo \'{"prompt": "test"}\' | ai-guardian\n'

            return True, message

        except Exception as e:
            return False, f"Error setting up IDE hooks: {e}"

    def migrate_pattern_server_config(self, config: Dict) -> Tuple[bool, Dict]:
        """
        Migrate pattern_server config to per-engine format (Issue #530).

        Two-stage migration:
          Stage 1: root pattern_server → secret_scanning.pattern_server
          Stage 2: secret_scanning.pattern_server → engines[].pattern_server

        Args:
            config: Configuration dictionary to migrate

        Returns:
            tuple: (migrated: bool, updated_config: dict)
        """
        migrated = False

        # Stage 1: root pattern_server → secret_scanning.pattern_server
        if "pattern_server" in config:
            root_ps = config.pop("pattern_server")
            if "secret_scanning" not in config:
                config["secret_scanning"] = {}
            ss = config["secret_scanning"]
            if "pattern_server" not in ss:
                ss["pattern_server"] = root_ps
            migrated = True

        # Stage 2: secret_scanning.pattern_server → per-engine
        ss = config.get("secret_scanning", {})
        if isinstance(ss, dict) and "pattern_server" in ss:
            ps_config = ss.pop("pattern_server")
            migrated = True

            if ps_config is None:
                return migrated, config

            engines = ss.get("engines", ["gitleaks"])
            inserted = False
            for i, engine_spec in enumerate(engines):
                is_gitleaks_str = (
                    isinstance(engine_spec, str) and engine_spec == "gitleaks"
                )
                is_gitleaks_dict = (
                    isinstance(engine_spec, dict)
                    and engine_spec.get("type") == "gitleaks"
                )

                if is_gitleaks_str:
                    engines[i] = {"type": "gitleaks", "pattern_server": ps_config}
                    inserted = True
                    break
                elif is_gitleaks_dict:
                    if "pattern_server" not in engine_spec:
                        engine_spec["pattern_server"] = ps_config
                    inserted = True
                    break

            if not inserted:
                engines.insert(0, {"type": "gitleaks", "pattern_server": ps_config})

            ss["engines"] = engines

        return migrated, config

    def setup_remote_config(self, url: str, dry_run: bool = False) -> Tuple[bool, str]:
        """
        Add remote config URL to ai-guardian config.

        Args:
            url: Remote config URL to add
            dry_run: If True, show what would be changed without applying

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Get config path
            config_dir = get_config_dir()
            config_path = config_dir / "ai-guardian.json"

            # Load existing config or create new
            config = {}
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON in {config_path}: {e}"

            # Check if remote_configs section exists
            if "remote_configs" not in config:
                config["remote_configs"] = {"urls": []}
            elif "urls" not in config["remote_configs"]:
                config["remote_configs"]["urls"] = []

            # Check if URL already exists
            existing_urls = [
                entry.get("url") if isinstance(entry, dict) else entry
                for entry in config["remote_configs"]["urls"]
            ]
            if url in existing_urls:
                return False, f"Remote config URL already exists: {url}"

            # Add new URL with enabled flag
            new_entry = {"url": url, "enabled": True}
            config["remote_configs"]["urls"].append(new_entry)

            if dry_run:
                message = f"[DRY RUN] Would add remote config to {config_path}:\n"
                message += json.dumps(config, indent=2)
                return True, message

            # Ensure parent directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Create backup if file exists
            if config_path.exists():
                backup_path = self.backup_config(config_path)
                if backup_path:
                    print(f"✓ Backup created: {backup_path}", file=sys.stderr)

            # Write config
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
                f.write("\n")  # Add trailing newline

            message = f"✓ Successfully added remote config URL to {config_path}\n"
            message += f"  URL: {url}\n"

            return True, message

        except Exception as e:
            return False, f"Error setting up remote config: {e}"

    def check_and_migrate_pattern_server(
        self, dry_run: bool = False, interactive: bool = True
    ) -> Tuple[bool, str]:
        """
        Check for deprecated pattern_server config and migrate to per-engine format.

        Handles both:
        - Root-level pattern_server (deprecated in v1.7.0)
        - secret_scanning.pattern_server (deprecated in v1.7.x, Issue #530)

        Args:
            dry_run: If True, show what would be changed without applying
            interactive: If True, prompt user for confirmation

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            config_dir = get_config_dir()
            config_path = config_dir / "ai-guardian.json"

            if not config_path.exists():
                return True, "No ai-guardian.json found - nothing to migrate"

            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except json.JSONDecodeError as e:
                return False, f"Invalid JSON in {config_path}: {e}"

            migrated, updated_config = self.migrate_pattern_server_config(config)

            if not migrated:
                return (
                    True,
                    "✓ Configuration already using per-engine pattern_server format",
                )

            message = "Found deprecated pattern_server configuration.\n"
            message += "Will migrate to per-engine format: secret_scanning.engines[].pattern_server\n\n"

            if dry_run:
                message += f"[DRY RUN] Would update {config_path}:\n"
                message += json.dumps(updated_config, indent=2)
                return True, message

            if interactive:
                print(message)
                print(f"Config file: {config_path}")
                try:
                    response = input("\nMigrate now? [y/N]: ")
                    if response.lower() not in ["y", "yes"]:
                        return False, "Migration cancelled"
                except KeyboardInterrupt:
                    return False, "\nMigration cancelled"

            backup_path = self.backup_config(config_path)
            if backup_path:
                print(f"✓ Backup created: {backup_path}", file=sys.stderr)

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(updated_config, f, indent=2)
                f.write("\n")

            message = "✓ Successfully migrated pattern_server configuration\n"
            message += f"  Config file: {config_path}\n"
            message += f"  Backup: {backup_path}\n"
            message += "\n  Changes:\n"
            message += "  • Moved pattern_server to per-engine format (engines[].pattern_server)\n"

            return True, message

        except Exception as e:
            return False, f"Error migrating pattern_server config: {e}"


# --- Pre-commit hook functions ---


def _auto_install_hook(
    git_root_path: Path,
    hooks_dir: Path,
    git_template: Path,
    yaml_template: Path,
    log_violations: bool = False,
) -> Tuple[bool, str]:
    """
    Automatically install pre-commit hook.

    Only called when allow_auto_install=True and no existing hooks detected.

    Args:
        git_root_path: Git repository root
        hooks_dir: .git/hooks directory
        git_template: Path to git hook template
        yaml_template: Path to YAML template

    Returns:
        Tuple of (success, message)
    """
    import shutil

    # Check if pre-commit framework is available
    try:
        subprocess.run(["pre-commit", "--version"], capture_output=True, check=True)
        has_precommit_framework = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_precommit_framework = False

    try:
        if has_precommit_framework:
            # Install pre-commit framework config
            dest = git_root_path / ".pre-commit-config.yaml"
            content = yaml_template.read_text(encoding="utf-8")
            if log_violations:
                content = content.replace(
                    "scan --exit-code", "scan --exit-code --log-violations"
                )
            dest.write_text(content, encoding="utf-8")

            # Run pre-commit install
            try:
                subprocess.run(
                    ["pre-commit", "install"],
                    cwd=git_root_path,
                    check=True,
                    capture_output=True,
                )
                return True, (
                    f"✅ Auto-installed pre-commit framework hook!\n"
                    f"  Config: {dest}\n"
                    f"\n"
                    f"The hook will run automatically on 'git commit'.\n"
                    f"To skip: git commit --no-verify"
                )
            except subprocess.CalledProcessError as e:
                return True, (
                    f"✅ Created {dest}\n"
                    f"⚠️  Run 'pre-commit install' to activate\n"
                    f"Error: {e}"
                )
        else:
            # Install git hook
            dest = hooks_dir / "pre-commit"
            content = git_template.read_text(encoding="utf-8")
            if log_violations:
                content = content.replace(
                    "scan --diff --staged --exit-code",
                    "scan --diff --staged --exit-code --log-violations",
                )
            dest.write_text(content, encoding="utf-8")
            os.chmod(dest, 0o755)

            return True, (
                f"✅ Auto-installed git hook!\n"
                f"  Location: {dest}\n"
                f"\n"
                f"The hook will run automatically on 'git commit'.\n"
                f"To skip: git commit --no-verify"
            )
    except Exception as e:
        return False, f"Error auto-installing hook: {e}"


def uninstall_precommit_hooks(
    dry_run: bool = False, interactive: bool = True
) -> Tuple[bool, str]:
    """
    Remove AI Guardian pre-commit hooks.

    Only removes hooks that were installed by AI Guardian.
    For integrated hooks, shows instructions for manual removal.

    Args:
        dry_run: If True, show what would be removed without doing it
        interactive: If True, prompt for confirmation

    Returns:
        Tuple of (success, message)
    """
    # Find git root
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False, "Error: Not in a git repository"

    git_root_path = Path(git_root)
    hooks_dir = git_root_path / ".git" / "hooks"
    git_hook = hooks_dir / "pre-commit"
    yaml_config = git_root_path / ".pre-commit-config.yaml"

    removed = []
    cannot_remove = []

    # Check git hook
    if git_hook.exists():
        try:
            with open(git_hook, "r") as f:
                content = f.read()
                # Check if this is our hook
                if (
                    "AI Guardian pre-commit hook" in content
                    or "ai-guardian scan" in content
                ):
                    if interactive and not dry_run:
                        response = input(f"Remove git hook at {git_hook}? [y/N]: ")
                        if response.lower() != "y":
                            return False, "Removal cancelled"

                    if not dry_run:
                        git_hook.unlink()
                        removed.append(f"Git hook: {git_hook}")
                    else:
                        removed.append(f"Would remove git hook: {git_hook}")
                else:
                    cannot_remove.append(
                        f"Git hook at {git_hook} doesn't appear to be AI Guardian's.\n"
                        f"  To remove AI Guardian from this hook, manually edit and remove:\n"
                        f"  'ai-guardian scan --exit-code .'"
                    )
        except Exception as e:
            cannot_remove.append(f"Error checking git hook: {e}")

    # Check pre-commit config
    if yaml_config.exists():
        try:
            with open(yaml_config, "r") as f:
                content = f.read()
                # Check if this is entirely our config or mixed
                if "# AI Guardian pre-commit hook configuration" in content:
                    # This is our file
                    if interactive and not dry_run:
                        response = input(
                            f"Remove pre-commit config at {yaml_config}? [y/N]: "
                        )
                        if response.lower() != "y":
                            return False, "Removal cancelled"

                    if not dry_run:
                        yaml_config.unlink()
                        removed.append(f"Pre-commit config: {yaml_config}")
                    else:
                        removed.append(f"Would remove config: {yaml_config}")
                elif "ai-guardian" in content.lower():
                    cannot_remove.append(
                        f"Found ai-guardian in {yaml_config}\n"
                        f"  This appears to be a mixed configuration.\n"
                        f"  To remove AI Guardian, manually edit {yaml_config} and remove the ai-guardian entry."
                    )
        except Exception as e:
            cannot_remove.append(f"Error checking pre-commit config: {e}")

    # Build message
    if not removed and not cannot_remove:
        return True, "No AI Guardian pre-commit hooks found."

    message = []
    if removed:
        message.append("✅ Removed AI Guardian hooks:\n")
        for item in removed:
            message.append(f"  • {item}")
        message.append("")

    if cannot_remove:
        message.append("⚠️  Manual removal required:\n")
        for item in cannot_remove:
            message.append(f"  {item}\n")

    return True, "\n".join(message)


def _is_sample_hook(content: str) -> bool:
    """Return True if content looks like a git sample hook (not a real hook)."""
    return (
        content.startswith("#!/bin/sh")
        and "sample" in content.lower()
        and len(content) < 500
    )


def _has_ai_guardian_line(content: str) -> bool:
    """Return True if content already contains an ai-guardian scan command."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "ai-guardian" in stripped and "scan" in stripped:
            return True
    return False


_AG_SCAN_LINE = "ai-guardian scan --exit-code ."


def _build_scan_line(log_violations: bool = False) -> str:
    """Build the ai-guardian scan command line with resolved binary path."""
    from ai_guardian.setup.utils import _resolve_binary_path

    abs_path = _resolve_binary_path()
    lv = " --log-violations" if log_violations else ""
    if abs_path != "ai-guardian":
        return f"{abs_path} scan --exit-code{lv} ."
    return f"ai-guardian scan --exit-code{lv} ."


def _update_ai_guardian_line(content: str, log_violations: bool = False) -> str:
    """Replace existing ai-guardian scan line with current resolved path."""
    scan_line = _build_scan_line(log_violations=log_violations)
    lines = content.splitlines(keepends=True)
    updated = []
    for line in lines:
        stripped = line.strip()
        if (
            not stripped.startswith("#")
            and "ai-guardian" in stripped
            and "scan" in stripped
        ):
            indent = line[: len(line) - len(line.lstrip())]
            updated.append(f"{indent}{scan_line}\n")
        else:
            updated.append(line)
    return "".join(updated)


def _append_ai_guardian_line(content: str, log_violations: bool = False) -> str:
    """Append ai-guardian scan command to existing hook content."""
    scan_line = _build_scan_line(log_violations=log_violations)
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n# AI Guardian security scan\n{scan_line}\n"
    return content


def install_precommit_hooks(
    dry_run: bool = False,
    interactive: bool = True,
    allow_auto_install: bool = False,
    log_violations: bool = False,
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Install pre-commit hook for git workflow.

    Behavior matrix:
      - No existing hook         → install fresh
      - Existing, has ai-guardian → update ai-guardian line in place
      - Existing, no ai-guardian  → append ai-guardian scan line
      - --force with existing     → backup + replace entire hook

    Args:
        dry_run: If True, show what would be done without applying
        interactive: If True, show interactive prompts (unused, kept for compat)
        allow_auto_install: Deprecated, kept for backward compat (ignored)
        force: If True, replace existing hook entirely (backup saved)

    Returns:
        Tuple of (success, message)
    """
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False, "Error: Not in a git repository"

    git_root_path = Path(git_root)
    hooks_dir = git_root_path / ".git" / "hooks"

    if not hooks_dir.exists():
        return False, f"Error: Git hooks directory not found: {hooks_dir}"

    import ai_guardian

    package_dir = Path(ai_guardian.__file__).parent
    for parent_level in ["..", "../..", "../../.."]:
        potential_template_dir = (package_dir / parent_level / "templates").resolve()
        if potential_template_dir.exists():
            template_dir = potential_template_dir
            break
    else:
        template_dir = package_dir.parent / "templates"

    git_template = template_dir / "pre-commit.sh"
    yaml_template = template_dir / ".pre-commit-config.yaml"

    if not git_template.exists() or not yaml_template.exists():
        return False, f"Error: Templates not found in {template_dir}"

    hook_path = hooks_dir / "pre-commit"

    # Read existing hook content (if any real hook exists)
    existing_content = None
    if hook_path.exists() and not hook_path.is_symlink():
        try:
            with open(hook_path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip() and not _is_sample_hook(content):
                existing_content = content
        except Exception:
            existing_content = ""

    # --- No existing hook: install fresh ---
    if existing_content is None:
        if dry_run:
            return True, f"[DRY RUN] Would install pre-commit hook at {hook_path}"
        return _auto_install_hook(
            git_root_path,
            hooks_dir,
            git_template,
            yaml_template,
            log_violations=log_violations,
        )

    # --- Force: backup + replace ---
    if force:
        if dry_run:
            return True, (
                f"[DRY RUN] Would replace pre-commit hook at {hook_path}\n"
                f"  Backup would be saved as {hook_path}.bak"
            )
        import shutil

        backup_path = Path(f"{hook_path}.bak")
        shutil.copy2(hook_path, backup_path)
        content = git_template.read_text(encoding="utf-8")
        if log_violations:
            content = content.replace(
                "scan --diff --staged --exit-code",
                "scan --diff --staged --exit-code --log-violations",
            )
        Path(hook_path).write_text(content, encoding="utf-8")
        os.chmod(hook_path, 0o755)
        return True, (
            f"Pre-commit hook replaced at {hook_path}\n"
            f"  Backup saved: {backup_path}\n"
            f"\n"
            f"The hook will run automatically on 'git commit'.\n"
            f"To skip: git commit --no-verify"
        )

    # --- Existing hook already has ai-guardian: update in place ---
    if _has_ai_guardian_line(existing_content):
        updated = _update_ai_guardian_line(
            existing_content, log_violations=log_violations
        )
        if updated == existing_content:
            return True, f"Pre-commit hook at {hook_path} already up to date."

        if dry_run:
            return True, (f"[DRY RUN] Would update ai-guardian command in {hook_path}")
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write(updated)
        return True, f"Updated ai-guardian command in {hook_path}"

    # --- Existing hook without ai-guardian: append ---
    updated = _append_ai_guardian_line(existing_content, log_violations=log_violations)
    if dry_run:
        return True, (f"[DRY RUN] Would append ai-guardian scan to {hook_path}")
    with open(hook_path, "w", encoding="utf-8") as f:
        f.write(updated)
    os.chmod(hook_path, 0o755)
    return True, (
        f"Appended ai-guardian scan to existing hook at {hook_path}\n"
        f"\n"
        f"The hook will run automatically on 'git commit'.\n"
        f"To skip: git commit --no-verify"
    )


# --- IDE extension/plugin template constants ---

# AiderDesk extension file contents (Issue #639)
_AIDERDESK_PACKAGE_JSON = """\
{
  "name": "ai-guardian-aiderdesk",
  "version": "1.0.0",
  "description": "AI Guardian security extension for AiderDesk",
  "main": "index.ts",
  "dependencies": {
    "@aiderdesk/extensions": ">=0.55.0"
  }
}
"""

_AIDERDESK_EXTENSION_TS = """\
import type { Extension, ExtensionContext } from '@aiderdesk/extensions';
import { execSync } from 'child_process';

export default class AiGuardianExtension implements Extension {
  static metadata = {
    name: 'AI Guardian',
    version: '1.0.0',
    description: 'Security scanning for tool calls, prompts, and file access',
    author: 'ai-guardian',
  };

  private runGuardian(
    hookData: Record<string, unknown>,
  ): { blocked: boolean; error?: string; output?: string } {
    try {
      const input = JSON.stringify(hookData);
      const result = execSync('ai-guardian', {
        input,
        encoding: 'utf-8',
        timeout: 30000,
        env: { ...process.env, AI_GUARDIAN_IDE_TYPE: 'aiderdesk' },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      return { blocked: false, output: result?.trim() || undefined };
    } catch (err: any) {
      if (err.status === 1) {
        const errorMsg =
          err.stderr?.toString().trim() || 'Blocked by ai-guardian';
        return { blocked: true, error: errorMsg };
      }
      return { blocked: false };
    }
  }

  async onToolApproval(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'pre_tool_use',
      tool_name: event.toolName,
      tool_input: event.input || {},
    };
    const result = this.runGuardian(hookData);
    if (result.blocked) {
      context.log(`Blocked tool: ${event.toolName} - ${result.error}`, 'warn');
      return { blocked: true };
    }
  }

  async onToolCalled(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'pre_tool_use',
      tool_name: event.toolName,
      tool_input: event.input || {},
    };
    const result = this.runGuardian(hookData);
    if (result.blocked) {
      context.log(`Blocked tool: ${event.toolName} - ${result.error}`, 'warn');
      return { blocked: true, output: { error: result.error } };
    }
  }

  async onToolFinished(event: any, context: ExtensionContext) {
    const output =
      typeof event.output === 'string'
        ? event.output
        : JSON.stringify(event.output || '');
    const hookData = {
      hook_event_name: 'post_tool_use',
      tool_name: event.toolName,
      tool_response: { output },
    };
    const result = this.runGuardian(hookData);
    if (result.output) {
      return { output: result.output };
    }
  }

  async onPromptStarted(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'prompt_submit',
      prompt: event.prompt || '',
    };
    const result = this.runGuardian(hookData);
    if (result.blocked) {
      context.log(`Blocked prompt - ${result.error}`, 'warn');
      return { blocked: true };
    }
  }

  async onFilesAdded(event: any, context: ExtensionContext) {
    const files = event.files || [];
    for (const file of files) {
      const hookData = {
        hook_event_name: 'pre_tool_use',
        tool_name: 'Read',
        tool_input: { file_path: file.path || file },
      };
      const result = this.runGuardian(hookData);
      if (result.blocked) {
        context.log(`Blocked file: ${file.path || file} - ${result.error}`, 'warn');
        return { files: [] };
      }
    }
  }

  async onBeforeCommit(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'pre_tool_use',
      tool_name: 'Bash',
      tool_input: { command: 'git commit -m ' + JSON.stringify(event.message || '') },
    };
    const result = this.runGuardian(hookData);
    if (result.blocked) {
      context.log(`Blocked commit - ${result.error}`, 'warn');
      return { blocked: true };
    }
  }
}
"""


# OpenCode plugin file contents (Issue #640)
_OPENCODE_PLUGIN_TS = """\
import type { Plugin } from '@opencode-ai/plugin';
import { execSync } from 'child_process';

interface GuardianResult {
  blocked: boolean;
  error?: string;
  output?: string;
}

function runGuardian(hookData: Record<string, unknown>): GuardianResult {
  try {
    const input = JSON.stringify(hookData);
    const result = execSync('ai-guardian', {
      input,
      encoding: 'utf-8',
      timeout: 30000,
      env: { ...process.env, AI_GUARDIAN_IDE_TYPE: 'opencode' },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const stdout = result?.trim() || '';
    if (stdout) {
      try {
        const parsed = JSON.parse(stdout);
        if (parsed._blocked) {
          const msg = parsed.systemMessage
            || JSON.parse(parsed.output || '{}').systemMessage
            || 'Blocked by ai-guardian';
          return { blocked: true, error: msg, output: stdout };
        }
        const inner = parsed.output ? JSON.parse(parsed.output) : parsed;
        if (inner.decision === 'block') {
          return { blocked: true, error: inner.reason || 'Blocked by ai-guardian', output: stdout };
        }
        if (inner.hookSpecificOutput?.permissionDecision === 'deny') {
          return { blocked: true, error: inner.systemMessage || 'Blocked by ai-guardian', output: stdout };
        }
      } catch {}
    }
    return { blocked: false, output: stdout || undefined };
  } catch (err: any) {
    if (err.status === 1) {
      const errorMsg =
        err.stderr?.toString().trim() || 'Blocked by ai-guardian';
      return { blocked: true, error: errorMsg };
    }
    return { blocked: false };
  }
}

export const AiGuardian: Plugin = async (ctx) => {
  const cwd = ctx.directory || process.cwd();

  return {
    async 'tool.execute.before'(input, output) {
      if (input.tool?.startsWith('ai-guardian')) return;
      const hookData = {
        hook_event_name: 'tool.execute.before',
        opencode_version: '1.0.0',
        hook_source: 'opencode',
        tool_name: input.tool,
        tool_use: { name: input.tool, input: output.args || {} },
        session_id: input.sessionID,
        tool_use_id: input.callID,
        cwd,
      };
      const result = runGuardian(hookData);
      if (result.blocked) {
        throw new Error(result.error || 'Blocked by ai-guardian');
      }
    },

    async 'chat.message'(input, output) {
      const text = (output.parts || [])
        .filter((p) => p.type === 'text' && !p.synthetic)
        .map((p) => p.text || p.content || '')
        .join('\\\\n');
      if (!text) return;
      const hookData = {
        hook_event_name: 'message.submit',
        opencode_version: '1.0.0',
        hook_source: 'opencode',
        prompt: text,
        session_id: input.sessionID,
        cwd,
      };
      const result = runGuardian(hookData);
      if (result.blocked) {
        const firstPart = output.parts[0] || {};
        output.parts.length = 0;
        output.parts.push({
          ...firstPart,
          type: 'text',
          text: '🛡️ ai-guardian: Secret detected in user message. Original content removed for security. Tell the user their message was blocked because it contained a secret. Do NOT attempt to recover the original content.',
          synthetic: true,
        });
      }
    },

    async 'tool.execute.after'(input, output) {
      if (input.tool?.startsWith('ai-guardian')) return;
      const hookData = {
        hook_event_name: 'tool.execute.after',
        opencode_version: '1.0.0',
        hook_source: 'opencode',
        tool_name: input.tool,
        tool_response: { output: output.output || '' },
        tool_use: { name: input.tool, input: input.args || {} },
        session_id: input.sessionID,
        tool_use_id: input.callID,
        cwd,
      };
      const result = runGuardian(hookData);
      if (result.blocked) {
        throw new Error(result.error || 'Blocked by ai-guardian');
      }
      if (result.output) {
        try {
          const parsed = JSON.parse(result.output);
          const hookOutput = JSON.parse(parsed.output || '{}').hookSpecificOutput;
          if (hookOutput?.updatedToolOutput) {
            output.output = hookOutput.updatedToolOutput;
          }
        } catch {}
      }
    },

    async 'session.end'() {
      runGuardian({ hook_event_name: 'session.end', opencode_version: '1.0.0', hook_source: 'opencode', cwd });
    },
  };
};
"""

_OPENCLAW_PACKAGE_JSON = """\
{
  "name": "ai-guardian-openclaw",
  "version": "1.0.0",
  "description": "AI Guardian security plugin for OpenClaw",
  "main": "index.ts",
  "openclaw": {
    "hooks": ["ai-guardian"]
  },
  "dependencies": {
    "openclaw": ">=0.1.0"
  }
}
"""

_OPENCLAW_PLUGIN_TS = """\
import { definePluginEntry } from 'openclaw/plugin-sdk/plugin-entry';
import { execSync } from 'child_process';

function runGuardian(
  hookData: Record<string, unknown>,
): { blocked: boolean; error?: string; output?: string } {
  try {
    const input = JSON.stringify(hookData);
    const result = execSync('ai-guardian', {
      input,
      encoding: 'utf-8',
      timeout: 30000,
      env: { ...process.env, AI_GUARDIAN_IDE_TYPE: 'openclaw' },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return { blocked: false, output: result?.trim() || undefined };
  } catch (err: any) {
    if (err.status === 1) {
      const errorMsg =
        err.stderr?.toString().trim() || 'Blocked by ai-guardian';
      return { blocked: true, error: errorMsg };
    }
    return { blocked: false };
  }
}

export default definePluginEntry({
  id: 'ai-guardian',
  name: 'AI Guardian',
  register(api) {
    api.on('before_tool_call', async (event) => {
      const hookData = {
        hook_event_name: 'pre_tool_use',
        tool_name: event.toolName,
        tool_input: event.params || {},
      };
      const result = runGuardian(hookData);
      if (result.blocked) {
        return { block: true, blockReason: result.error };
      }
    });

    api.on('after_tool_call', async (event) => {
      const output =
        typeof event.result === 'string'
          ? event.result
          : JSON.stringify(event.result || '');
      const hookData = {
        hook_event_name: 'post_tool_use',
        tool_name: event.toolName,
        tool_response: { output },
      };
      runGuardian(hookData);
    });

    api.on('message_received', async (event) => {
      const hookData = {
        hook_event_name: 'prompt_submit',
        prompt: event.content || '',
      };
      const result = runGuardian(hookData);
      if (result.blocked) {
        return { cancel: true, cancelReason: result.error };
      }
    });

    api.on('session_start', async () => {
      runGuardian({ hook_event_name: 'prompt_submit', prompt: '' });
    });

    api.on('session_end', async () => {
      runGuardian({ hook_event_name: 'session.end', hook_source: 'openclaw' });
    });
  },
});
"""
