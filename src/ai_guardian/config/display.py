#!/usr/bin/env python3
"""
Configuration Display Module

Displays merged AI Guardian configuration with clear labeling of rule sources.
Supports showing user-defined, auto-generated, and immutable rules.

Usage:
    ai-guardian config show              # User-defined only
    ai-guardian config show --all        # Include auto-generated rules
    ai-guardian config show --section permissions  # Specific section
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ConfigDisplay:
    """Display AI Guardian configuration with source attribution."""

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize config display.

        Args:
            config: Optional pre-loaded configuration. If None, loads from disk.
        """
        self.config = config
        if self.config is None:
            # Import here to avoid circular dependency
            from ai_guardian.tools.policy import ToolPolicyChecker

            checker = ToolPolicyChecker()
            self.config = checker.config

    def show(
        self,
        show_all: bool = False,
        section: Optional[str] = None,
        preview_auto_rules: bool = False,
        output_json: bool = False,
    ) -> str:
        """
        Generate formatted configuration display.

        Args:
            show_all: Include auto-generated rules marked with [GENERATED]
            section: Filter to specific section name
            preview_auto_rules: Show preview of what would be auto-generated
            output_json: Output configuration as JSON instead of formatted text

        Returns:
            Formatted configuration string or JSON string
        """
        if preview_auto_rules:
            return self._preview_auto_generated_rules()

        # JSON output mode
        if output_json:
            return self._output_json(show_all, section)

        output = []
        output.append("=" * 70)
        output.append("AI GUARDIAN CONFIGURATION")
        output.append("=" * 70)
        output.append("")

        # Show specific section or all
        if section:
            self._add_section(output, section, show_all)
        else:
            self._add_all_sections(output, show_all)

        # Add legend if generated or immutable rules exist
        if show_all or self._has_generated_rules():
            output.append("")
            output.append("=" * 70)
            output.append("LEGEND")
            output.append("=" * 70)
            output.append("  [USER]      - Defined in your config files")
            output.append("  [GENERATED] - Auto-generated from skill permissions")
            output.append("  [IMMUTABLE] - From remote config (cannot override)")
            output.append("")

        return "\n".join(output)

    def _output_json(self, show_all: bool, section: Optional[str]) -> str:
        """
        Output configuration as JSON.

        Args:
            show_all: Include auto-generated rules (kept for backward compat)
            section: Filter to specific section name

        Returns:
            JSON string
        """
        # Deep copy config to avoid modifying original
        import copy

        output_config = copy.deepcopy(self.config)

        # Filter to specific section if requested
        if section:
            if section in output_config:
                output_config = {section: output_config[section]}
            else:
                output_config = {}

        return json.dumps(output_config, indent=2)

    def _filter_generated_rules(self, config: Dict) -> Dict:
        """
        Remove auto-generated rules from configuration.

        Args:
            config: Configuration dictionary

        Returns:
            Configuration with generated rules filtered out
        """
        if "permissions" in config:
            perms = config["permissions"]
            if isinstance(perms, dict) and "rules" in perms:
                perms["rules"] = [
                    rule for rule in perms["rules"] if not rule.get("_generated", False)
                ]

        if "directory_rules" in config:
            dir_rules = config["directory_rules"]
            if isinstance(dir_rules, dict) and "rules" in dir_rules:
                dir_rules["rules"] = [
                    rule
                    for rule in dir_rules["rules"]
                    if not rule.get("_generated", False)
                ]
            elif isinstance(dir_rules, list):
                config["directory_rules"] = [
                    rule for rule in dir_rules if not rule.get("_generated", False)
                ]

        return config

    def _add_all_sections(self, output: List[str], show_all: bool):
        """Add all configuration sections to output."""
        sections = [
            ("permissions", "Tool Permissions"),
            ("directory_rules", "Directory Access Rules"),
            ("secret_scanning", "Secret Scanning"),
            ("prompt_injection", "Prompt Injection Detection"),
            ("ssrf_protection", "SSRF Protection"),
            ("config_file_scanning", "Config File Scanning"),
            ("supply_chain", "Supply Chain Scanning"),
            ("security_instructions", "Security Instructions"),
            ("image_scanning", "Image Scanning (OCR)"),
        ]

        for section_key, section_title in sections:
            if section_key in self.config:
                self._add_section(output, section_key, show_all, section_title)
                output.append("")

    def _add_section(
        self,
        output: List[str],
        section_key: str,
        show_all: bool,
        title: Optional[str] = None,
    ):
        """
        Add a configuration section to output.

        Args:
            output: Output list to append to
            section_key: Configuration section key
            show_all: Include auto-generated rules
            title: Optional custom title (defaults to section_key)
        """
        if section_key not in self.config:
            output.append(f"# {title or section_key.title()}")
            output.append("  (not configured)")
            return

        output.append(f"# {title or section_key.replace('_', ' ').title()}")
        output.append("")

        section = self.config[section_key]

        # Special handling for permissions section
        if section_key == "permissions":
            self._format_permissions(output, section, show_all)
        # Special handling for directory_rules
        elif section_key == "directory_rules":
            self._format_directory_rules(output, section, show_all)
        # Generic section formatting
        else:
            self._format_generic_section(output, section)

    def _format_permissions(self, output: List[str], section: Dict, show_all: bool):
        """Format permissions section with rule labeling."""
        # Show enabled status
        enabled = section.get("enabled", True)
        output.append(f"  enabled: {enabled}")

        # Show auto_directory_rules config
        if "auto_directory_rules" in section:
            auto_config = section["auto_directory_rules"]
            auto_enabled = auto_config.get("enabled", False)
            output.append("  auto_directory_rules:")
            output.append(f"    enabled: {auto_enabled}")
            if auto_enabled:
                skill_dirs = auto_config.get("skill_directories", "auto")
                output.append(f"    skill_directories: {skill_dirs}")

        # Show rules
        rules = section.get("rules", [])
        if rules:
            output.append(f"  rules: ({len(rules)} total)")
            for i, rule in enumerate(rules, 1):
                self._format_permission_rule(output, rule, i, show_all)
        else:
            output.append("  rules: []")

    def _format_permission_rule(
        self, output: List[str], rule: Dict, index: int, show_all: bool
    ):
        """Format a single permission rule with source label."""
        # Determine source label
        label = self._get_rule_label(rule)

        matcher = rule.get("matcher", "unknown")
        mode = rule.get("mode", "unknown")
        patterns = rule.get("patterns", [])
        action = rule.get("action", "block")

        # Format rule header
        output.append(f"    [{label:9s}] Rule {index}: {matcher}")
        output.append(f"                mode: {mode}")
        output.append(f"                action: {action}")

        # Format patterns
        if patterns:
            output.append("                patterns:")
            for pattern in patterns[:5]:  # Limit to first 5
                pattern_str = (
                    pattern
                    if isinstance(pattern, str)
                    else pattern.get("pattern", str(pattern))
                )
                output.append(f"                  - {pattern_str}")
            if len(patterns) > 5:
                output.append(f"                  ... and {len(patterns) - 5} more")

        # Show source for immutable rules
        if label == "IMMUTABLE" and "_source" in rule:
            output.append(f"                source: {rule['_source']}")

    def _format_directory_rules(self, output: List[str], section: Dict, show_all: bool):
        """Format directory_rules section with rule labeling."""
        # Handle both old array format and new object format
        if isinstance(section, dict):
            action = section.get("action", "block")
            rules = section.get("rules", [])
            output.append(f"  action: {action}")
        else:
            # Old array format
            rules = section
            output.append("  (using legacy array format)")

        if rules:
            output.append(f"  rules: ({len(rules)} total)")
            output.append("")
            for i, rule in enumerate(rules, 1):
                self._format_directory_rule(output, rule, i, show_all)
        else:
            output.append("  rules: []")

    def _format_directory_rule(
        self, output: List[str], rule: Dict, index: int, show_all: bool
    ):
        """Format a single directory rule with source label."""
        # Determine source label
        label = self._get_rule_label(rule)

        mode = rule.get("mode", "unknown")
        paths = rule.get("paths", [])

        # Format rule
        output.append(f"  {index}. [{label:9s}] {mode:5s} {len(paths)} path(s)")
        for path in paths[:3]:  # Show first 3 paths
            output.append(f"       - {path}")
        if len(paths) > 3:
            output.append(f"       ... and {len(paths) - 3} more")

        # Show source for generated/immutable rules
        if "_source" in rule:
            output.append(f"       source: {rule['_source']}")

        output.append("")

    def _format_generic_section(self, output: List[str], section):
        """Format a generic configuration section."""
        if isinstance(section, dict):
            immutable = section.get("immutable")
            if immutable == "tighten-only":
                output.append("  [TIGHTEN-ONLY] overrides can tighten but not loosen")
            for key, value in section.items():
                if key.startswith("_"):  # Skip metadata
                    continue
                if isinstance(value, (dict, list)):
                    output.append(f"  {key}: {type(value).__name__}")
                else:
                    output.append(f"  {key}: {value}")
        else:
            output.append(f"  {json.dumps(section, indent=2)}")

    def _has_generated_rules(self) -> bool:
        """Check if the config contains any auto-generated rules."""
        for section_key in ("permissions", "directory_rules"):
            section = self.config.get(section_key)
            if not section:
                continue
            rules = (
                section.get("rules", [])
                if isinstance(section, dict)
                else section if isinstance(section, list) else []
            )
            if any(isinstance(r, dict) and r.get("_generated") for r in rules):
                return True
        return False

    def _get_rule_label(self, rule: Dict) -> str:
        """
        Get the source label for a rule.

        Args:
            rule: Rule dictionary

        Returns:
            Label string: USER, GENERATED, or IMMUTABLE
        """
        if rule.get("_generated", False):
            return "GENERATED"
        elif rule.get("_immutable", False) or rule.get("immutable", False):
            return "IMMUTABLE"
        else:
            return "USER"

    def _preview_auto_generated_rules(self) -> str:
        """
        Generate preview of what auto-generation would create.

        Returns:
            Formatted preview string
        """
        output = []
        output.append("=" * 70)
        output.append("AUTO-GENERATED DIRECTORY RULES PREVIEW")
        output.append("=" * 70)
        output.append("")

        # Check if auto-generation is configured
        permissions = self.config.get("permissions", {})
        auto_config = permissions.get("auto_directory_rules", {})
        auto_enabled = auto_config.get("enabled", False)

        output.append(f"Auto-generation: {'ENABLED' if auto_enabled else 'DISABLED'}")
        output.append("")

        if not auto_enabled:
            from ai_guardian.config.utils import format_config_paths

            output.append("To enable, add to your config:")
            output.append(format_config_paths())
            output.append("")
            output.append('  "permissions": {')
            output.append('    "auto_directory_rules": {"enabled": true}')
            output.append("  }")
            return "\n".join(output)

        # Get skill directories to scan
        skill_dirs = self._get_skill_directories(auto_config)
        output.append("Skill directories that would be scanned:")
        for dir_path in skill_dirs:
            exists = Path(dir_path).exists()
            status = "✓" if exists else "✗"
            output.append(f"  {status} {dir_path}")
        output.append("")

        # Generate preview of rules
        from ai_guardian.tools.directory_rules import DirectoryRuleGenerator

        generator = DirectoryRuleGenerator(self.config)
        generated_rules = generator.generate_directory_rules()

        if generated_rules:
            output.append(f"Would generate {len(generated_rules)} directory rules:")
            output.append("")
            for i, rule in enumerate(generated_rules, 1):
                mode = rule.get("mode", "unknown")
                paths = rule.get("paths", [])
                output.append(f"  {i}. {mode:5s} {len(paths)} path(s)")
                for path in paths[:3]:
                    output.append(f"       {path}")
                if len(paths) > 3:
                    output.append(f"       ... and {len(paths) - 3} more")
                output.append("")
        else:
            output.append("  (no rules would be generated)")
            output.append("")
            output.append("This may be because:")
            output.append("  - No skill permissions are configured")
            output.append("  - No matching skills found in skill directories")
            output.append("  - All skills are denied by immutable rules")

        output.append("")
        output.append("=" * 70)
        output.append("To apply: Set 'auto_directory_rules.enabled: true' in config")
        output.append("To view all rules: ai-guardian config show --all")
        output.append("=" * 70)

        return "\n".join(output)

    def _get_skill_directories(self, auto_config: Dict) -> List[str]:
        """
        Get list of skill directories to scan.

        Supports multiple IDE agents:
        - Claude Code: ./.claude/skills, ~/.claude/skills, $CLAUDE_CONFIG_DIR/skills
        - Cursor: ./.cursor/skills, ~/.cursor/skills
        - VSCode/Copilot: ./.vscode/skills, ~/.vscode/skills
        - Windsurf: ./.windsurf/skills, ~/.windsurf/skills

        Args:
            auto_config: auto_directory_rules configuration

        Returns:
            List of directory paths
        """
        skill_dirs_config = auto_config.get("skill_directories", "auto")

        if skill_dirs_config == "auto":
            # Standard locations for all supported IDEs
            dirs = [
                # Project-local directories
                "./.claude/skills",
                "./.cursor/skills",
                "./.vscode/skills",
                "./.windsurf/skills",
                # User home directories
                str(Path.home() / ".claude" / "skills"),
                str(Path.home() / ".cursor" / "skills"),
                str(Path.home() / ".vscode" / "skills"),
                str(Path.home() / ".windsurf" / "skills"),
            ]

            # Add IDE-specific config directories from environment
            import os

            # Claude Code
            claude_config = os.environ.get("CLAUDE_CONFIG_DIR")
            if claude_config:
                dirs.append(str(Path(claude_config) / "skills"))

            # Cursor
            cursor_project = os.environ.get("CURSOR_PROJECT_PATH")
            if cursor_project:
                dirs.append(str(Path(cursor_project) / ".cursor" / "skills"))

            # VSCode/Copilot
            vscode_cwd = os.environ.get("VSCODE_CWD")
            if vscode_cwd:
                dirs.append(str(Path(vscode_cwd) / ".vscode" / "skills"))

            return dirs
        elif isinstance(skill_dirs_config, list):
            return skill_dirs_config
        else:
            return []
