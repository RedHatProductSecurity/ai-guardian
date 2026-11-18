#!/usr/bin/env python3
"""
Unit tests for auto-generation of directory rules from skill permissions.

Tests Issue #144: Auto-generate directory rules from skill permissions
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from ai_guardian.tools.directory_rules import (
    DirectoryRuleGenerator,
    insert_generated_rules,
)


class TestDirectoryRuleGenerator:
    """Test directory rule generation from skill permissions."""

    def test_generation_disabled_by_default(self):
        """Auto-generation should be disabled by default."""
        config = {
            "permissions": {
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}]
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert rules == []

    def test_generation_enabled_but_no_permissions(self):
        """Should return empty if enabled but no skill permissions."""
        config = {
            "permissions": {"auto_directory_rules": {"enabled": True}, "rules": []}
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert rules == []

    @patch("ai_guardian.tools.directory_rules.Path.exists")
    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.iterdir")
    def test_basic_generation(self, mock_iterdir, mock_is_dir, mock_exists):
        """Should generate rules for matching skills."""
        # Mock skill directory
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        # Mock skills in directory
        mock_skill1 = MagicMock()
        mock_skill1.name = "daf-git"
        mock_skill1.is_dir.return_value = True
        mock_skill1.is_symlink.return_value = False

        mock_skill2 = MagicMock()
        mock_skill2.name = "daf-jira"
        mock_skill2.is_dir.return_value = True
        mock_skill2.is_symlink.return_value = False

        mock_iterdir.return_value = [mock_skill1, mock_skill2]

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}],
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        # Should generate rules for both skills
        assert len(rules) > 0
        assert any("daf-git" in str(rule) for rule in rules)
        assert any("daf-jira" in str(rule) for rule in rules)

        # All rules should be marked as generated
        for rule in rules:
            assert rule.get("_generated") is True
            assert "_source" in rule

    def test_only_existing_directories_scanned(self):
        """Should only scan directories that exist."""
        # Test relies on actual filesystem - just verify it returns a list
        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["*"]}],
            }
        }

        generator = DirectoryRuleGenerator(config)
        skill_dirs = generator._get_skill_directories({"skill_directories": "auto"})

        # Should return a list (may be empty if no dirs exist)
        assert isinstance(skill_dirs, list)

    def test_extract_skill_patterns(self):
        """Should extract only allow patterns for Skill matcher."""
        config = {
            "permissions": {
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["daf-*", "gh-cli"],
                    },
                    {"matcher": "Skill", "mode": "deny", "patterns": ["dangerous-*"]},
                    {"matcher": "Bash", "mode": "allow", "patterns": ["*"]},
                ]
            }
        }

        generator = DirectoryRuleGenerator(config)
        patterns = generator._get_skill_patterns()

        # Should only include allow patterns for Skill matcher
        assert "daf-*" in patterns
        assert "gh-cli" in patterns
        assert "dangerous-*" not in patterns  # deny pattern
        assert "*" not in patterns  # different matcher

    def test_match_skills_against_patterns(self):
        """Should correctly match skills against fnmatch patterns."""
        discovered = {
            "daf-git": [Path("~/.claude/skills/daf-git")],
            "daf-jira": [Path("~/.claude/skills/daf-jira")],
            "gh-cli": [Path("~/.claude/skills/gh-cli")],
            "other-skill": [Path("~/.claude/skills/other-skill")],
        }

        patterns = ["daf-*", "gh-cli"]

        generator = DirectoryRuleGenerator({})
        matching = generator._match_skills(discovered, patterns)

        assert "daf-git" in matching
        assert "daf-jira" in matching
        assert "gh-cli" in matching
        assert "other-skill" not in matching

    @patch("ai_guardian.tools.directory_rules.Path.exists")
    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.iterdir")
    def test_created_rules_structure(self, mock_iterdir, mock_is_dir, mock_exists):
        """Generated rules should have correct structure."""
        # Mock skill directory exists
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        # Mock skills in ~/.claude/skills directory
        mock_skill1 = MagicMock()
        mock_skill1.name = "daf-git"
        mock_skill1.is_dir.return_value = True
        mock_skill1.is_symlink.return_value = False

        mock_skill2 = MagicMock()
        mock_skill2.name = "daf-jira"
        mock_skill2.is_dir.return_value = True
        mock_skill2.is_symlink.return_value = False

        mock_iterdir.return_value = [mock_skill1, mock_skill2]

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}],
            }
        }

        generator = DirectoryRuleGenerator(config)

        # Mock some matching skills
        matching_skills = {"daf-git", "daf-jira"}
        rules = generator._create_directory_rules(matching_skills)

        assert len(rules) > 0
        for rule in rules:
            assert rule.get("mode") == "allow"
            assert isinstance(rule.get("paths"), list)
            assert rule.get("_generated") is True
            assert rule.get("_source") == "permissions.rules[Skill]"

    def test_time_based_patterns_supported(self):
        """Should handle time-based pattern format."""
        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": [
                            {"pattern": "daf-*", "valid_until": "2099-12-31T23:59:59Z"}
                        ],
                    }
                ],
            }
        }

        generator = DirectoryRuleGenerator(config)
        patterns = generator._get_skill_patterns()

        # Should extract pattern from dict format
        assert "daf-*" in patterns


class TestRuleInsertion:
    """Test insertion of generated rules into config."""

    def test_insert_after_user_rules_new_format(self):
        """Generated rules should be inserted AFTER user rules (new object format)."""
        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    {"mode": "deny", "paths": ["~/.ssh/**"]},
                    {"mode": "allow", "paths": ["~/.claude/skills/user-skill/**"]},
                ],
            }
        }

        generated = [
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]

        result = insert_generated_rules(config, generated)

        rules = result["directory_rules"]["rules"]
        # User rules should come first (position 0, 1)
        assert rules[0]["paths"][0] == "~/.ssh/**"
        assert rules[1]["paths"][0] == "~/.claude/skills/user-skill/**"

        # Generated rule should be LAST (position 2)
        assert rules[2]["_generated"] is True
        assert rules[2]["paths"][0] == "~/.claude/skills/daf-git/**"

    def test_insert_after_user_rules_legacy_format(self):
        """Should convert legacy array format to object format."""
        config = {"directory_rules": [{"mode": "deny", "paths": ["~/.ssh/**"]}]}

        generated = [
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]

        result = insert_generated_rules(config, generated)

        # Should convert to new format
        assert isinstance(result["directory_rules"], dict)
        assert "action" in result["directory_rules"]
        assert "rules" in result["directory_rules"]

        rules = result["directory_rules"]["rules"]
        # User rule first, generated rule last
        assert rules[0]["paths"][0] == "~/.ssh/**"
        assert rules[1]["_generated"] is True

    def test_generated_rules_override_user_deny(self):
        """
        CRITICAL: Generated allow rules must override broad user deny rules.

        Rule order (last-match-wins):
          Position 0-N:     User rules (broadest scope)
          Position N+1-M:   Generated rules (specific exceptions)
          Final positions:  Immutable rules (strongest - override all)
        """
        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    # User broadly denies all skills
                    {"mode": "deny", "paths": ["~/.claude/skills/**"]}
                ],
            }
        }

        generated = [
            # Generated allows specific permitted skills
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]

        result = insert_generated_rules(config, generated)
        rules = result["directory_rules"]["rules"]

        # Order must be: User (pos 0), Generated (pos 1)
        assert rules[0]["paths"][0] == "~/.claude/skills/**"  # User first
        assert rules[1]["_generated"] is True  # Generated second

        # With last-match-wins, generated allow overrides user deny
        # for specific paths - this is the correct behavior

    def test_immutable_rules_still_win(self):
        """Immutable rules must remain in final position and override all."""
        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    {"mode": "deny", "paths": ["~/.claude/skills/**"]},
                    {"mode": "deny", "paths": ["~/.ssh/**"], "_immutable": True},
                ],
            }
        }

        generated = [
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]

        result = insert_generated_rules(config, generated)
        rules = result["directory_rules"]["rules"]

        # Order: User deny (pos 0), Generated allow (pos 1), Immutable deny (pos 2)
        assert rules[0]["paths"][0] == "~/.claude/skills/**"
        assert rules[1]["_generated"] is True
        assert rules[2].get("_immutable") is True

        # Immutable rule stays at end, overriding everything

    def test_immutable_rules_not_displaced_by_generated(self):
        """Generated rules must be inserted before immutable, not after."""
        config = {
            "directory_rules": {
                "action": "block",
                "rules": [
                    {"mode": "allow", "paths": ["~/projects/**"]},
                    {"mode": "deny", "paths": ["~/.env/**"], "_immutable": True},
                    {"mode": "deny", "paths": ["~/.ssh/**"], "_immutable": True},
                ],
            }
        }

        generated = [
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]

        result = insert_generated_rules(config, generated)
        rules = result["directory_rules"]["rules"]

        # Order: User (pos 0), Generated (pos 1), Immutable (pos 2, 3)
        assert len(rules) == 4
        assert rules[0]["paths"][0] == "~/projects/**"
        assert rules[1]["_generated"] is True
        assert rules[2].get("_immutable") is True
        assert rules[3].get("_immutable") is True

    def test_empty_generated_rules(self):
        """Should handle empty generated rules gracefully."""
        config = {"directory_rules": {"action": "block", "rules": []}}
        generated = []

        result = insert_generated_rules(config, generated)

        assert result["directory_rules"]["rules"] == []

    def test_create_directory_rules_if_missing(self):
        """Should create directory_rules section if missing."""
        config = {}
        generated = [
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]

        result = insert_generated_rules(config, generated)

        assert "directory_rules" in result
        assert isinstance(result["directory_rules"], dict)
        assert result["directory_rules"]["rules"][0]["_generated"] is True

    def test_legacy_format_with_immutable_rules(self):
        """Legacy array format with immutable rules should preserve ordering."""
        config = {
            "directory_rules": [
                {"mode": "deny", "paths": ["~/.claude/skills/**"]},
                {"mode": "deny", "paths": ["~/.ssh/**"], "_immutable": True},
            ]
        }

        generated = [
            {
                "mode": "allow",
                "paths": ["~/.claude/skills/daf-git/**"],
                "_generated": True,
            }
        ]

        result = insert_generated_rules(config, generated)
        rules = result["directory_rules"]["rules"]

        # User first, generated second, immutable last
        assert rules[0]["paths"][0] == "~/.claude/skills/**"
        assert rules[1]["_generated"] is True
        assert rules[2].get("_immutable") is True


class TestMultiIDESupport:
    """Test support for multiple IDE agents."""

    @pytest.mark.parametrize(
        "env_var, env_value, expected_substring",
        [
            pytest.param(
                "CLAUDE_CONFIG_DIR",
                "/custom/claude",
                "/custom/claude/skills",
                id="CLAUDE_CONFIG_DIR",
            ),
            pytest.param(
                "CURSOR_PROJECT_PATH",
                "/workspace/project",
                "/workspace/project/.cursor/skills",
                id="CURSOR_PROJECT_PATH",
            ),
            pytest.param(
                "VSCODE_CWD",
                "/workspace/vscode",
                "/workspace/vscode/.vscode/skills",
                id="VSCODE_CWD",
            ),
            pytest.param(
                "KILO_CONFIG_DIR",
                "/custom/kilo",
                "/custom/kilo/skills",
                id="KILO_CONFIG_DIR",
            ),
        ],
    )
    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.exists")
    def test_ide_env_var_skill_directory(
        self, mock_exists, mock_is_dir, env_var, env_value, expected_substring
    ):
        """Should respect IDE-specific environment variables for skill directories."""
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True, "skill_directories": "auto"}
            }
        }

        with patch.dict("os.environ", {env_var: env_value}):
            generator = DirectoryRuleGenerator(config)
            dirs = generator._get_skill_directories({"skill_directories": "auto"})

        assert any(expected_substring.replace("/", os.sep) in str(d) for d in dirs)

    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.exists")
    def test_all_ide_directories_included(self, mock_exists, mock_is_dir):
        """Should scan all IDE skill directories by default."""
        # Mock all paths as existing
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True, "skill_directories": "auto"}
            }
        }

        generator = DirectoryRuleGenerator(config)
        all_candidates = generator._get_skill_directories({"skill_directories": "auto"})

        # Convert to strings with normalized separators for cross-platform matching
        all_dirs = [str(d).replace("\\", "/") for d in all_candidates]

        # Should include all IDE variations
        assert any(".claude/skills" in d for d in all_dirs)
        assert any(".cursor/skills" in d for d in all_dirs)
        assert any(".vscode/skills" in d for d in all_dirs)
        assert any(".windsurf/skills" in d for d in all_dirs)
        assert any(".kilo/skills" in d for d in all_dirs)
        assert any(".kilocode/skills" in d for d in all_dirs)
        assert any(".agents/skills" in d for d in all_dirs)

    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.exists")
    def test_explicit_skill_directories_override(self, mock_exists, mock_is_dir):
        """Should use explicit directories when configured."""
        # Mock all paths as existing
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        config = {
            "permissions": {
                "auto_directory_rules": {
                    "enabled": True,
                    "skill_directories": [
                        "/custom/path/skills",
                        "/another/path/skills",
                    ],
                }
            }
        }

        generator = DirectoryRuleGenerator(config)
        dirs = generator._get_skill_directories(
            {"skill_directories": ["/custom/path/skills", "/another/path/skills"]}
        )

        # Should only include explicit paths
        assert len(dirs) == 2
        assert Path("/custom/path/skills") in dirs
        assert Path("/another/path/skills") in dirs


class TestPluginCacheDiscovery:
    """Test discovery of skills in plugin cache directories (Issue #324)."""

    def test_plugin_cache_skills_discovered(self, tmp_path):
        """Skills in plugin cache should be discovered automatically."""
        # Create plugin cache structure:
        # ~/.claude/plugins/cache/<marketplace>/<plugin>/<hash>/skills/<skill>/
        cache_dir = tmp_path / ".claude" / "plugins" / "cache"
        skills_dir = cache_dir / "marketplace" / "my-plugin" / "abc123" / "skills"
        (skills_dir / "bugfix-workflow").mkdir(parents=True)
        (skills_dir / "code-review").mkdir(parents=True)

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["bugfix-workflow", "code-review"],
                    }
                ],
            }
        }

        generator = DirectoryRuleGenerator(config)

        with patch(
            "ai_guardian.tools.directory_rules.Path.home", return_value=tmp_path
        ):
            rules = generator.generate_directory_rules()

        assert len(rules) > 0
        assert any("bugfix-workflow" in str(rule) for rule in rules)
        assert any("code-review" in str(rule) for rule in rules)

    def test_plugin_cache_empty(self, tmp_path):
        """Empty plugin cache should not cause errors."""
        cache_dir = tmp_path / ".claude" / "plugins" / "cache"
        cache_dir.mkdir(parents=True)

        config = {
            "permissions": {
                "auto_directory_rules": {
                    "enabled": True,
                    "skill_directories": [str(cache_dir)],
                },
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["*"]}],
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert rules == []

    def test_plugin_cache_missing(self, tmp_path):
        """Missing plugin cache directory should not cause errors."""
        missing_dir = tmp_path / "nonexistent" / "skills"

        config = {
            "permissions": {
                "auto_directory_rules": {
                    "enabled": True,
                    "skill_directories": [str(missing_dir)],
                },
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["*"]}],
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert rules == []


class TestSymlinkHandling:
    """Test allow_symlinks flag for container environments (Issue #324)."""

    @patch("ai_guardian.tools.directory_rules.Path.exists")
    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.iterdir")
    def test_symlinks_allowed_by_default(self, mock_iterdir, mock_is_dir, mock_exists):
        """Symlinked skills should be discovered when allow_symlinks is not set (default: true)."""
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        mock_symlink_skill = MagicMock()
        mock_symlink_skill.name = "daf-git"
        mock_symlink_skill.is_symlink.return_value = True
        mock_symlink_skill.is_dir.return_value = True
        mock_symlink_skill.resolve.return_value = MagicMock(
            is_dir=MagicMock(return_value=True)
        )

        mock_real_skill = MagicMock()
        mock_real_skill.name = "gh-cli"
        mock_real_skill.is_symlink.return_value = False
        mock_real_skill.is_dir.return_value = True

        mock_iterdir.return_value = [mock_symlink_skill, mock_real_skill]

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["daf-*", "gh-cli"],
                    }
                ],
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert len(rules) > 0
        assert any("daf-git" in str(rule) for rule in rules)
        assert any("gh-cli" in str(rule) for rule in rules)

    @patch("ai_guardian.tools.directory_rules.Path.exists")
    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.iterdir")
    def test_symlinks_allowed_explicitly(self, mock_iterdir, mock_is_dir, mock_exists):
        """Symlinked skills should be discovered when allow_symlinks is explicitly true."""
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        mock_symlink_skill = MagicMock()
        mock_symlink_skill.name = "daf-jira"
        mock_symlink_skill.is_symlink.return_value = True
        mock_symlink_skill.is_dir.return_value = True
        mock_symlink_skill.resolve.return_value = MagicMock(
            is_dir=MagicMock(return_value=True)
        )

        mock_iterdir.return_value = [mock_symlink_skill]

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True, "allow_symlinks": True},
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]}],
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert len(rules) > 0
        assert any("daf-jira" in str(rule) for rule in rules)

    @patch("ai_guardian.tools.directory_rules.Path.exists")
    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.iterdir")
    def test_symlinks_rejected_when_disabled(
        self, mock_iterdir, mock_is_dir, mock_exists
    ):
        """Symlinked skills should be skipped when allow_symlinks is false."""
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        mock_symlink_skill = MagicMock()
        mock_symlink_skill.name = "daf-git"
        mock_symlink_skill.is_symlink.return_value = True
        mock_symlink_skill.is_dir.return_value = True

        mock_real_skill = MagicMock()
        mock_real_skill.name = "gh-cli"
        mock_real_skill.is_symlink.return_value = False
        mock_real_skill.is_dir.return_value = True

        mock_iterdir.return_value = [mock_symlink_skill, mock_real_skill]

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True, "allow_symlinks": False},
                "rules": [
                    {
                        "matcher": "Skill",
                        "mode": "allow",
                        "patterns": ["daf-*", "gh-cli"],
                    }
                ],
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert len(rules) > 0
        assert not any("daf-git" in str(rule) for rule in rules)
        assert any("gh-cli" in str(rule) for rule in rules)

    @patch("ai_guardian.tools.directory_rules.Path.exists")
    @patch("ai_guardian.tools.directory_rules.Path.is_dir")
    @patch("ai_guardian.tools.directory_rules.Path.iterdir")
    def test_broken_symlinks_always_skipped(
        self, mock_iterdir, mock_is_dir, mock_exists
    ):
        """Broken symlinks should always be skipped regardless of allow_symlinks."""
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        mock_broken_symlink = MagicMock()
        mock_broken_symlink.name = "broken-skill"
        mock_broken_symlink.is_symlink.return_value = True
        mock_broken_symlink.is_dir.return_value = False
        mock_broken_symlink.resolve.return_value = MagicMock(
            is_dir=MagicMock(return_value=False)
        )

        mock_real_skill = MagicMock()
        mock_real_skill.name = "daf-git"
        mock_real_skill.is_symlink.return_value = False
        mock_real_skill.is_dir.return_value = True

        mock_iterdir.return_value = [mock_broken_symlink, mock_real_skill]

        config = {
            "permissions": {
                "auto_directory_rules": {"enabled": True, "allow_symlinks": True},
                "rules": [{"matcher": "Skill", "mode": "allow", "patterns": ["*"]}],
            }
        }

        generator = DirectoryRuleGenerator(config)
        rules = generator.generate_directory_rules()

        assert not any("broken-skill" in str(rule) for rule in rules)
        assert any("daf-git" in str(rule) for rule in rules)

    @pytest.mark.parametrize(
        "config, expected",
        [
            pytest.param(
                {"permissions": {"auto_directory_rules": {}}},
                True,
                id="default-not-configured",
            ),
            pytest.param(
                {"permissions": {"auto_directory_rules": {"allow_symlinks": True}}},
                True,
                id="explicit-true",
            ),
            pytest.param(
                {"permissions": {"auto_directory_rules": {"allow_symlinks": False}}},
                False,
                id="explicit-false",
            ),
            pytest.param(
                {},
                True,
                id="missing-config-sections",
            ),
        ],
    )
    def test_get_allow_symlinks(self, config, expected):
        """_get_allow_symlinks should return correct value based on config."""
        generator = DirectoryRuleGenerator(config)
        assert generator._get_allow_symlinks() is expected
