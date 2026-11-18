#!/usr/bin/env python3
"""
Unit tests for configuration display functionality.

Tests Issue #144: 'config show' command with rule labeling
"""

from unittest.mock import patch, MagicMock

from ai_guardian.config.display import ConfigDisplay


class TestConfigDisplay:
    """Test configuration display with source attribution."""

    def test_basic_display(self):
        """Should display configuration sections."""
        config = {
            "permissions": {
                "enabled": True,
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}],
            }
        }

        display = ConfigDisplay(config)
        output = display.show()

        assert "AI GUARDIAN CONFIGURATION" in output
        assert "Tool Permissions" in output
        assert "enabled: True" in output

    def test_generated_rules_shown_by_default(self):
        """Should show generated rules by default with [GENERATED] label."""
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]},
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["test-*"],
                        "_generated": True,
                    },
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=False)

        # Both rules should appear
        assert "daf-*" in output
        assert "test-*" in output
        assert "[GENERATED]" in output

    def test_show_all_includes_generated(self):
        """Should show generated rules when show_all=True."""
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]},
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["test-*"],
                        "_generated": True,
                    },
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        # Both rules should appear
        assert "daf-*" in output
        assert "test-*" in output
        # Should include legend
        assert "LEGEND" in output
        assert "[GENERATED]" in output

    def test_rule_labeling_user(self):
        """Should label user rules as [USER]."""
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["my-skill"]}
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        assert "[USER" in output

    def test_rule_labeling_generated(self):
        """Should label generated rules as [GENERATED]."""
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["daf-*"],
                        "_generated": True,
                    }
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        assert "[GENERATED]" in output

    def test_rule_labeling_immutable(self):
        """Should label immutable rules as [IMMUTABLE]."""
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "deny",
                        "patterns": ["dangerous-*"],
                        "_immutable": True,
                        "_source": "enterprise-policy.json",
                    }
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        # CRITICAL: Immutable rules MUST be visible
        assert "[IMMUTABLE]" in output
        assert "dangerous-*" in output
        assert "enterprise-policy.json" in output

    def test_directory_rules_labeling(self):
        """Should label directory rules with source."""
        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    {
                        "mode": "allow",
                        "paths": ["~/.claude/skills/daf-git/**"],
                        "_generated": True,
                    },
                    {"mode": "deny", "paths": ["~/.ssh/**"]},
                    {
                        "mode": "deny",
                        "paths": ["~/.aws/**"],
                        "_immutable": True,
                        "_source": "enterprise.json",
                    },
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        # All three types should be visible
        assert "[GENERATED]" in output
        assert "[USER]" in output
        assert "[IMMUTABLE]" in output

    def test_section_filter(self):
        """Should filter to specific section when requested."""
        config = {
            "permissions": {"enabled": True},
            "secret_scanning": {"enabled": True},
            "prompt_injection": {"enabled": False},
        }

        display = ConfigDisplay(config)
        output = display.show(section="permissions")

        # Should only show permissions section
        assert "Tool Permissions" in output or "Permissions" in output
        assert "Secret Scanning" not in output
        assert "Prompt Injection" not in output

    @patch("ai_guardian.tools.directory_rules.DirectoryRuleGenerator")
    def test_preview_auto_rules(self, mock_generator_class):
        """Should preview auto-generated rules."""
        mock_generator = MagicMock()
        mock_generator.generate_directory_rules.return_value = [
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]
        mock_generator_class.return_value = mock_generator

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(preview_auto_rules=True)

        assert "AUTO-GENERATED DIRECTORY RULES PREVIEW" in output
        assert "Auto-generation: ENABLED" in output

    def test_preview_when_disabled(self):
        """Should show how to enable when previewing disabled auto-generation."""
        config = {"permissions": {"auto_directory_rules": {"enabled": False}}}

        display = ConfigDisplay(config)
        output = display.show(preview_auto_rules=True)

        assert "Auto-generation: DISABLED" in output
        assert "To enable" in output
        assert '"enabled": true' in output

    def test_format_permission_rule_details(self):
        """Should format permission rule with all details."""
        rule = {
            "matcher": "Skill",
            "mode": "allow",
            "patterns": ["daf-*", "gh-cli"],
            "action": "block",
        }

        display = ConfigDisplay({})
        label = display._get_rule_label(rule)

        assert label == "USER"

    def test_directory_rule_path_truncation(self):
        """Should truncate long path lists for readability."""
        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    {
                        "mode": "allow",
                        "paths": [f"~/.claude/skills/skill-{i}/**" for i in range(10)],
                    }
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show()

        # Should indicate truncation
        assert "..." in output or "more" in output

    def test_auto_directory_rules_config_shown(self):
        """Should display auto_directory_rules configuration."""
        config = {
            "permissions": {
                "enabled": True,
                "auto_directory_rules": {"enabled": True, "skill_directories": "auto"},
                "rules": [],
            }
        }

        display = ConfigDisplay(config)
        output = display.show()

        assert "auto_directory_rules" in output
        assert "enabled: True" in output

    def test_generic_section_formatting(self):
        """Should format generic sections correctly."""
        config = {"secret_scanning": {"enabled": True, "engines": ["gitleaks"]}}

        display = ConfigDisplay(config)
        output = display.show()

        assert "Secret Scanning" in output

    def test_legend_shows_all_types(self):
        """Legend should explain all rule types."""
        config = {
            "permissions": {
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["user-*"]},
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["gen-*"],
                        "_generated": True,
                    },
                    {
                        "matcher": "Skill",
                        "mode": "deny",
                        "patterns": ["bad-*"],
                        "_immutable": True,
                    },
                ]
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        # Legend should appear
        assert "LEGEND" in output
        assert "[USER]" in output
        assert "[GENERATED]" in output
        assert "[IMMUTABLE]" in output

    @patch("ai_guardian.config.display.Path.exists")
    def test_skill_directories_existence_in_preview(self, mock_exists):
        """Preview should show which directories exist."""
        mock_exists.return_value = True  # All exist

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["*"]}],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(preview_auto_rules=True)

        assert "Skill directories" in output
        # Should show checkmarks for existing directories
        assert "✓" in output or "✗" in output

    def test_json_output_includes_generated_rules(self):
        """JSON output should include generated rules with _generated marker."""
        import json

        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    {"mode": "deny", "paths": ["~/.ssh/**"]},
                    {
                        "mode": "allow",
                        "paths": ["~/.claude/skills/test/**"],
                        "_generated": True,
                    },
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(output_json=True)
        parsed = json.loads(output)

        rules = parsed["directory_rules"]["rules"]
        assert len(rules) == 2
        assert any(r.get("_generated") for r in rules)

    def test_legend_shown_when_generated_rules_exist(self):
        """Legend should appear when generated rules exist, even without --all."""
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["gen-*"],
                        "_generated": True,
                    }
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=False)

        assert "LEGEND" in output
        assert "[GENERATED]" in output


class TestMultiIDEDisplaySupport:
    """Test display of multi-IDE skill directories."""

    @patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": "/custom/claude"})
    def test_claude_config_dir_in_preview(self):
        """Preview should show CLAUDE_CONFIG_DIR if set."""
        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True, "skill_directories": "auto"},
                "rules": [],
            }
        }

        display = ConfigDisplay(config)
        dirs = display._get_skill_directories({"skill_directories": "auto"})

        assert any("/custom/claude/skills" in d.replace("\\", "/") for d in dirs)

    def test_all_ide_dirs_in_preview(self):
        """Preview should list all IDE skill directories."""
        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True, "skill_directories": "auto"},
                "rules": [],
            }
        }

        display = ConfigDisplay(config)
        dirs = display._get_skill_directories({"skill_directories": "auto"})

        # Should include multiple IDE directories
        assert any(".claude/skills" in d for d in dirs)
        assert any(".cursor/skills" in d for d in dirs)
        assert any(".vscode/skills" in d for d in dirs)
        assert any(".windsurf/skills" in d for d in dirs)
        assert any(".kilo/skills" in d for d in dirs)
        assert any(".kilocode/skills" in d for d in dirs)
        assert any(".agents/skills" in d for d in dirs)


class TestImmutableRuleVisibility:
    """
    CRITICAL TEST: Immutable rules MUST be visible.

    The investigation document (INVESTIGATION_ISSUE_144.md) identifies
    "invisible immutable rules" as a critical issue that breaks user trust
    and makes debugging impossible.

    These tests ensure immutable rules are ALWAYS visible with clear labels.
    """

    def test_immutable_rules_always_visible(self):
        """
        CRITICAL: Immutable rules must ALWAYS be visible.

        Original issue #144 said to hide them - investigation found this
        breaks user trust and debugging. Changed to always show with [IMMUTABLE] label.
        """
        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "deny",
                        "patterns": ["debug-helper"],
                        "_immutable": True,
                        "_source": "enterprise-policy.json",
                    }
                ]
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        # MUST show immutable rule
        assert "debug-helper" in output
        assert "[IMMUTABLE]" in output
        assert "enterprise-policy.json" in output

    def test_all_rule_types_shown_without_all_flag(self):
        """All rule types (user, generated, immutable) visible without --all."""
        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    {
                        "mode": "allow",
                        "paths": ["~/.claude/skills/safe/**"],
                        "_generated": True,
                    },
                    {"mode": "deny", "paths": ["~/.ssh/**"]},
                    {"mode": "deny", "paths": ["~/.aws/**"], "_immutable": True},
                ],
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=False)

        # All three types should be visible
        assert "~/.claude/skills/safe/**" in output
        assert "[GENERATED]" in output
        assert "~/.ssh/**" in output
        assert "~/.aws/**" in output

    def test_immutable_source_attribution(self):
        """Immutable rules should show their source."""
        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Bash",
                        "mode": "deny",
                        "patterns": ["*rm -rf /*"],
                        "_immutable": True,
                        "_source": "security-baseline.json",
                    }
                ]
            }
        }

        display = ConfigDisplay(config)
        output = display.show(show_all=True)

        # Should show source
        assert "security-baseline.json" in output
