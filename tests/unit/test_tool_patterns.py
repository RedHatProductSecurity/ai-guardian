"""
Tests for tool_patterns module — pattern data integrity and heredoc stripping.

Split from tool_policy tests (Issue #1494) to validate the extracted
pattern constants and _strip_bash_heredoc_content utility independently.
"""

from ai_guardian.tools.patterns import (
    IMMUTABLE_DENY_PATTERNS,
    MIXED_SETTINGS_PATTERNS,
    HOOK_INDICATOR_KEYS,
    _HOOK_KEY_PATTERN,
    _strip_bash_heredoc_content,
    is_ai_guardian_cli_command,
)


class TestImmutableDenyPatterns:
    def test_has_expected_tool_keys(self):
        expected = {"Write", "Edit", "Read", "Bash", "PowerShell"}
        assert set(IMMUTABLE_DENY_PATTERNS.keys()) == expected

    def test_all_values_are_lists(self):
        for tool, patterns in IMMUTABLE_DENY_PATTERNS.items():
            assert isinstance(patterns, list), f"{tool} patterns not a list"

    def test_all_patterns_are_strings(self):
        for tool, patterns in IMMUTABLE_DENY_PATTERNS.items():
            for p in patterns:
                assert isinstance(p, str), f"{tool} has non-string pattern: {p!r}"

    def test_write_protects_config(self):
        patterns = IMMUTABLE_DENY_PATTERNS["Write"]
        assert any("ai-guardian.json" in p for p in patterns)

    def test_edit_protects_config(self):
        patterns = IMMUTABLE_DENY_PATTERNS["Edit"]
        assert any("ai-guardian.json" in p for p in patterns)

    def test_read_protects_config(self):
        patterns = IMMUTABLE_DENY_PATTERNS["Read"]
        assert any("ai-guardian.json" in p for p in patterns)

    def test_bash_protects_self(self):
        assert is_ai_guardian_cli_command("ai-guardian pause")
        assert is_ai_guardian_cli_command("ai-guardian status")

    def test_cli_detection_is_command_position_aware(self):
        assert is_ai_guardian_cli_command("/usr/local/bin/ai-guardian --help")
        assert is_ai_guardian_cli_command("python -m ai_guardian")
        assert is_ai_guardian_cli_command("python -m ai_guardian.cli.main")
        assert is_ai_guardian_cli_command("uv run ai-guardian doctor")
        assert is_ai_guardian_cli_command("npx ai-guardian status")
        assert is_ai_guardian_cli_command("su -c 'ai-guardian status'")
        assert is_ai_guardian_cli_command("bash -lc 'ai-guardian status'")
        assert not is_ai_guardian_cli_command("printf '%s\\n' 'ai-guardian status'")
        assert not is_ai_guardian_cli_command("grep ai-guardian README.md")
        assert not is_ai_guardian_cli_command("git -C ai-guardian status")

    def test_cli_detection_ignores_heredoc_content(self):
        command = "cat <<'EOF'\nai-guardian status\nEOF"
        assert not is_ai_guardian_cli_command(command)

    def test_write_protects_hooks(self):
        patterns = IMMUTABLE_DENY_PATTERNS["Write"]
        assert any(".claude/hooks.json" in p for p in patterns)
        assert any(".cursor/hooks.json" in p for p in patterns)

    def test_write_and_edit_share_same_list(self):
        assert IMMUTABLE_DENY_PATTERNS["Write"] is IMMUTABLE_DENY_PATTERNS["Edit"]

    def test_bash_protects_cache(self):
        patterns = IMMUTABLE_DENY_PATTERNS["Bash"]
        assert any(".cache/ai-guardian" in p for p in patterns)

    def test_powershell_protects_config(self):
        patterns = IMMUTABLE_DENY_PATTERNS["PowerShell"]
        assert any("ai-guardian.json" in p for p in patterns)


class TestMixedSettingsPatterns:
    def test_is_list(self):
        assert isinstance(MIXED_SETTINGS_PATTERNS, list)

    def test_contains_claude_settings(self):
        assert any(".claude/settings.json" in p for p in MIXED_SETTINGS_PATTERNS)

    def test_contains_gemini_settings(self):
        assert any(".gemini/settings.json" in p for p in MIXED_SETTINGS_PATTERNS)

    def test_contains_augment_settings(self):
        assert any(".augment/settings.json" in p for p in MIXED_SETTINGS_PATTERNS)

    def test_contains_windows_claude(self):
        assert any("Claude/settings.json" in p for p in MIXED_SETTINGS_PATTERNS)


class TestHookIndicatorKeys:
    def test_is_set(self):
        assert isinstance(HOOK_INDICATOR_KEYS, set)

    def test_contains_hooks(self):
        assert "hooks" in HOOK_INDICATOR_KEYS

    def test_contains_hook_events(self):
        for event in ("PreToolUse", "PostToolUse", "UserPromptSubmit"):
            assert event in HOOK_INDICATOR_KEYS


class TestHookKeyPattern:
    def test_matches_double_quoted_hooks(self):
        assert _HOOK_KEY_PATTERN.search('"hooks": {}')

    def test_matches_single_quoted_pretooluse(self):
        assert _HOOK_KEY_PATTERN.search("'PreToolUse': []")

    def test_no_match_on_unrelated_key(self):
        assert not _HOOK_KEY_PATTERN.search('"permissions": {}')

    def test_matches_with_whitespace(self):
        assert _HOOK_KEY_PATTERN.search('"hooks"  :  {}')


class TestStripBashHeredocContent:
    def test_no_heredoc_passthrough(self):
        cmd = "echo hello world"
        assert _strip_bash_heredoc_content(cmd) == cmd

    def test_empty_string(self):
        assert _strip_bash_heredoc_content("") == ""

    def test_none_passthrough(self):
        assert _strip_bash_heredoc_content(None) is None

    def test_simple_heredoc(self):
        cmd = "cat <<EOF\nrm ai-guardian.json\nEOF"
        result = _strip_bash_heredoc_content(cmd)
        assert "rm ai-guardian.json" not in result
        assert "EOF" in result

    def test_quoted_heredoc(self):
        cmd = "cat <<'EOF'\nrm ai-guardian.json\nEOF"
        result = _strip_bash_heredoc_content(cmd)
        assert "rm ai-guardian.json" not in result

    def test_double_quoted_heredoc(self):
        cmd = 'cat <<"EOF"\nrm ai-guardian.json\nEOF'
        result = _strip_bash_heredoc_content(cmd)
        assert "rm ai-guardian.json" not in result

    def test_dash_heredoc(self):
        cmd = "cat <<-EOF\n\trm ai-guardian.json\n\tEOF"
        result = _strip_bash_heredoc_content(cmd)
        assert "rm ai-guardian.json" not in result

    def test_hyphenated_delimiter(self):
        cmd = "cat <<END-OF-FILE\nrm ai-guardian.json\nEND-OF-FILE"
        result = _strip_bash_heredoc_content(cmd)
        assert "rm ai-guardian.json" not in result

    def test_preserves_command_before_heredoc(self):
        cmd = "some-command | cat <<EOF\ndangerous content\nEOF"
        result = _strip_bash_heredoc_content(cmd)
        assert "some-command" in result
        assert "dangerous content" not in result

    def test_no_newline_after_delimiter(self):
        cmd = "cat <<EOF"
        assert _strip_bash_heredoc_content(cmd) == cmd
