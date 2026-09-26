"""
Unit tests for ai-guardian self-protection feature (Issue #32)

Tests the IMMUTABLE_DENY_PATTERNS that protect:
- ai-guardian configuration files
- IDE hook configuration files (Claude, Cursor)
- ai-guardian package source code
"""

import json
from unittest.mock import patch

import pytest

from ai_guardian.tools.policy import ToolPolicyChecker


@pytest.fixture
def policy_checker():
    """Create policy checker with empty config (only immutable deny patterns)."""
    return ToolPolicyChecker(config={"permissions": []})


# ============================================================================
# Parametrized: Write-blocks protected paths
# ============================================================================

WRITE_BLOCKED_PATHS = [
    pytest.param(
        "/home/user/.config/ai-guardian/ai-guardian.json",
        None,
        id="user-config-file",
    ),
    pytest.param(
        "/home/user/my-project/.ai-guardian.json",
        None,
        id="project-config-file",
    ),
    pytest.param(
        "/tmp/test-ai-guardian.json",
        None,
        id="any-ai-guardian-json",
    ),
    pytest.param(
        "/home/user/.cursor/hooks.json",
        None,
        id="cursor-hooks",
    ),
    pytest.param(
        "/usr/lib/python3.12/site-packages/ai_guardian/tool_policy.py",
        None,
        id="package-source-site-packages",
    ),
]


@pytest.mark.parametrize("file_path,content", WRITE_BLOCKED_PATHS)
def test_write_blocks_protected_path(policy_checker, file_path, content):
    """AI cannot write to protected paths"""
    tool_input = {"file_path": file_path}
    if content is not None:
        tool_input["content"] = content

    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Write", "input": tool_input},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Write to {file_path} should be blocked"
    assert error_msg is not None, "Error message should be provided"


# ============================================================================
# Parametrized: Write-blocks with content-aware hook checks
# ============================================================================

WRITE_BLOCKED_WITH_HOOKS_CONTENT = [
    pytest.param(
        "/home/user/.claude/settings.json",
        json.dumps(
            {
                "hooks": {"PreToolUse": [{"matcher": "*", "hooks": []}]},
                "model": "claude-sonnet-4-5-20250514",
            }
        ),
        id="claude-settings-with-hooks",
    ),
    pytest.param(
        "C:/Users/user/AppData/Roaming/Claude/settings.json",
        json.dumps(
            {
                "hooks": {"PreToolUse": [{"matcher": "*"}]},
                "model": "claude-sonnet-4-5-20250514",
            }
        ),
        id="windows-claude-settings-with-hooks",
    ),
]


@pytest.mark.parametrize("file_path,content", WRITE_BLOCKED_WITH_HOOKS_CONTENT)
def test_write_blocks_settings_with_hooks(policy_checker, file_path, content):
    """AI cannot write hooks to IDE settings files (content-aware, Issue #807)"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Write",
            "input": {"file_path": file_path, "content": content},
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Write with hooks to {file_path} should be blocked"
    assert "Hook Protection" in error_msg


# ============================================================================
# Parametrized: Edit-blocks protected paths
# ============================================================================

EDIT_BLOCKED_PATHS = [
    pytest.param(
        "/home/user/.config/ai-guardian/ai-guardian.json",
        '"enabled": true',
        '"enabled": false',
        id="user-config-file",
    ),
    pytest.param(
        "/usr/lib/python3.12/site-packages/ai_guardian/tool_policy.py",
        "IMMUTABLE_DENY_PATTERNS",
        "DISABLED",
        id="package-source",
    ),
]


@pytest.mark.parametrize("file_path,old_string,new_string", EDIT_BLOCKED_PATHS)
def test_edit_blocks_protected_path(policy_checker, file_path, old_string, new_string):
    """AI cannot edit protected paths"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Edit of {file_path} should be blocked"
    assert "Protection:" in error_msg


def test_edit_blocks_claude_settings_hooks(policy_checker):
    """AI cannot edit hooks in ~/.claude/settings.json (content-aware, Issue #807)"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": "/home/user/.claude/settings.json",
                "old_string": '"hooks": {"PreToolUse": []}',
                "new_string": '"hooks": {}',
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, "Edit of Claude settings hooks should be blocked"
    assert "Hook Protection" in error_msg


# ============================================================================
# Parametrized: Bash command blocks
# ============================================================================

BASH_BLOCKED_COMMANDS = [
    # sed/awk on config
    pytest.param(
        "sed -i 's/enabled\":true/enabled\":false/' ~/.config/ai-guardian/ai-guardian.json",
        id="sed-on-config",
    ),
    pytest.param(
        'awk \'{gsub(/enabled":true/, "enabled":false")}1\' ai-guardian.json > tmp && mv tmp ai-guardian.json',
        id="awk-on-config",
    ),
    # sed on Claude settings and package source
    pytest.param(
        "sed -i 's/ai-guardian//' ~/.claude/settings.json",
        id="sed-on-claude-settings",
    ),
    pytest.param(
        "sed -i 's/IMMUTABLE/DISABLED/' /usr/lib/python3.12/site-packages/ai_guardian/tool_policy.py",
        id="sed-on-package-source",
    ),
    # vim/nano on settings/hooks
    pytest.param(
        "vim ~/.claude/settings.json",
        id="vim-on-claude-settings",
    ),
    pytest.param(
        "nano ~/.cursor/hooks.json",
        id="nano-on-cursor-hooks",
    ),
    # echo/cat redirect
    pytest.param(
        "echo '{}' > ~/.config/ai-guardian/ai-guardian.json",
        id="echo-redirect-to-config",
    ),
    pytest.param(
        "cat /dev/null > ~/.claude/settings.json",
        id="redirect-to-claude-settings",
    ),
    # rm/mv
    pytest.param(
        "rm ~/.config/ai-guardian/ai-guardian.json",
        id="rm-config",
    ),
    pytest.param(
        "rm -f ~/.claude/settings.json",
        id="rm-claude-settings",
    ),
    pytest.param(
        "mv ~/.config/ai-guardian/ai-guardian.json /tmp/backup.json",
        id="mv-config",
    ),
    pytest.param(
        "mv .ai-guardian.json /tmp/backup.json",
        id="mv-hidden-config",
    ),
    # chmod/chattr
    pytest.param(
        "chmod 777 ~/.config/ai-guardian/ai-guardian.json",
        id="chmod-on-config",
    ),
    pytest.param(
        "chattr -i ~/.claude/settings.json",
        id="chattr-on-claude-settings",
    ),
    # cat/grep/head/tail/less/more on config/state/cache (Issue #512)
    pytest.param(
        "cat ~/.config/ai-guardian/ai-guardian.json",
        id="cat-config",
    ),
    pytest.param(
        "cat ~/.local/state/ai-guardian/violations.jsonl",
        id="cat-state",
    ),
    pytest.param(
        "cat ~/.cache/ai-guardian/patterns.toml",
        id="cat-cache",
    ),
    pytest.param(
        "cat ai-guardian.json",
        id="cat-any-ai-guardian-json",
    ),
    pytest.param(
        "grep -i 'allow' ~/.config/ai-guardian/ai-guardian.json",
        id="grep-config",
    ),
    pytest.param(
        "grep 'secret' ~/.local/state/ai-guardian/violations.jsonl",
        id="grep-state",
    ),
    pytest.param(
        "head -50 ~/.local/state/ai-guardian/ai-guardian.log",
        id="head-log",
    ),
    pytest.param(
        "tail -f ~/.local/state/ai-guardian/ai-guardian.log",
        id="tail-log",
    ),
    pytest.param(
        "less ai-guardian.json",
        id="less-config",
    ),
    pytest.param(
        "more ai-guardian.json",
        id="more-config",
    ),
    # Issue #188 - still blocks actual config
    pytest.param(
        "echo 'malicious content' > ~/.config/ai-guardian/ai-guardian.json",
        id="redirect-to-actual-config-issue-188",
    ),
]


@pytest.mark.parametrize("command", BASH_BLOCKED_COMMANDS)
def test_bash_blocks_command(policy_checker, command):
    """AI cannot use Bash to modify/read protected files"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Bash", "input": {"command": command}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Bash command should be blocked: {command}"


# ============================================================================
# Parametrized: .ai-read-deny Write blocks
# ============================================================================

AI_READ_DENY_WRITE_PATHS = [
    pytest.param(
        "/home/user/secrets/.ai-read-deny",
        id="write-marker",
    ),
    pytest.param(
        "/var/lib/sensitive/.ai-read-deny",
        id="write-absolute-path",
    ),
    pytest.param(
        "/home/user/project/a/b/c/.ai-read-deny",
        id="write-nested-path",
    ),
]


@pytest.mark.parametrize("file_path", AI_READ_DENY_WRITE_PATHS)
def test_write_blocks_ai_read_deny(policy_checker, file_path):
    """AI cannot write to .ai-read-deny marker files"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Write", "input": {"file_path": file_path}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Write to {file_path} should be blocked"
    assert error_msg is not None, "Error message should be provided"
    assert "Protection:" in error_msg
    assert "Directory Protection Marker" in error_msg


def test_edit_blocks_ai_read_deny_marker(policy_checker):
    """AI cannot edit .ai-read-deny marker file"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": "/home/user/secrets/.ai-read-deny",
                "old_string": "",
                "new_string": "test",
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, "Edit of .ai-read-deny should be blocked"
    assert "Protection:" in error_msg
    assert "Directory Protection Marker" in error_msg


# ============================================================================
# Parametrized: .ai-read-deny Bash blocks
# ============================================================================

AI_READ_DENY_BASH_COMMANDS = [
    pytest.param("rm /home/user/secrets/.ai-read-deny", id="rm-absolute"),
    pytest.param("rm secrets/.ai-read-deny", id="rm-relative"),
    pytest.param("rm -rf /home/user/project/.ai-read-deny", id="rm-rf"),
    pytest.param("mv /home/user/secrets/.ai-read-deny /tmp/backup", id="mv"),
    pytest.param("mv .ai-read-deny .ai-read-deny.bak", id="mv-rename"),
    pytest.param("sed -i 's/test/new/' /home/user/secrets/.ai-read-deny", id="sed"),
    pytest.param("awk '{print}' .ai-read-deny > /tmp/out", id="awk"),
    pytest.param("echo '' > /home/user/secrets/.ai-read-deny", id="echo-redirect"),
    pytest.param("cat /dev/null > .ai-read-deny", id="cat-redirect"),
    pytest.param("chmod 777 /home/user/secrets/.ai-read-deny", id="chmod"),
    pytest.param("chattr +i /home/user/secrets/.ai-read-deny", id="chattr"),
    pytest.param("vim /home/user/secrets/.ai-read-deny", id="vim"),
    pytest.param("nano .ai-read-deny", id="nano"),
]


@pytest.mark.parametrize("command", AI_READ_DENY_BASH_COMMANDS)
def test_bash_blocks_ai_read_deny(policy_checker, command):
    """AI cannot use Bash to modify/delete .ai-read-deny markers"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Bash", "input": {"command": command}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Bash on .ai-read-deny should be blocked: {command}"


# ============================================================================
# Parametrized: Allow tests - Write
# ============================================================================

WRITE_ALLOWED_PATHS = [
    pytest.param(
        "/home/user/my-project/src/main.py",
        None,
        id="normal-file",
    ),
    pytest.param(
        "/home/user/my_ai_guardian_project/src/main.py",
        None,
        id="user-project-ai-guardian-in-name",
    ),
    pytest.param(
        "/home/user/backup_ai_guardian_configs/settings.json",
        None,
        id="backup-dir-ai-guardian",
    ),
    pytest.param(
        "/home/user/projects/ai_guardian_tutorial/example.py",
        None,
        id="tutorial-dir-ai-guardian",
    ),
    pytest.param(
        "/home/user/my-project/docs/ai-guardian-setup.md",
        None,
        id="doc-file-mentioning-ai-guardian-issue-188",
    ),
    pytest.param(
        "/home/user/ai-guardian/src/ai_guardian/__main__.py",
        "# Modified source",
        id="dev-source-main",
    ),
    pytest.param(
        "/home/user/ai-guardian/src/ai_guardian/__init__.py",
        "# Modified source",
        id="dev-source-init",
    ),
]


@pytest.mark.parametrize("file_path,content", WRITE_ALLOWED_PATHS)
def test_write_allows_non_protected(policy_checker, file_path, content):
    """AI can write to non-protected files and development source"""
    tool_input = {"file_path": file_path}
    if content is not None:
        tool_input["content"] = content

    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Write", "input": tool_input},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert is_allowed, f"Write to {file_path} should be allowed"
    assert error_msg is None, "No error message for allowed operation"


EDIT_ALLOWED_CASES = [
    pytest.param(
        "/home/user/my-project/README.md",
        "old",
        "new",
        id="normal-file",
    ),
    pytest.param(
        "/home/user/my_ai_guardian_project/config.py",
        "DEBUG = False",
        "DEBUG = True",
        id="user-project-ai-guardian-in-name",
    ),
    pytest.param(
        "/home/user/my-project/docs/tools.md",
        "ai-guardian v1.0",
        "ai-guardian v1.1",
        id="user-file-ai-guardian-content-issue-188",
    ),
]


@pytest.mark.parametrize("file_path,old_string,new_string", EDIT_ALLOWED_CASES)
def test_edit_allows_non_protected(policy_checker, file_path, old_string, new_string):
    """AI can edit non-protected files"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert is_allowed, f"Edit of {file_path} should be allowed"


BASH_ALLOWED_COMMANDS = [
    pytest.param(
        "ls -la /home/user/my-project",
        id="normal-command",
    ),
    pytest.param(
        "sed -i 's/old/new/' /home/user/my_ai_guardian_project/config.py",
        id="sed-on-user-project-ai-guardian",
    ),
    pytest.param(
        "mv generate-ai-guardian-config.sh includes/",
        id="mv-user-script-ai-guardian-name",
    ),
    pytest.param(
        "mv my-ai-guardian-helper.py scripts/",
        id="mv-user-python-script-ai-guardian-name",
    ),
    # Issue #188 - legitimate content mentioning ai-guardian
    pytest.param(
        "echo 'The ai-guardian hook prevented the secret from being committed' > /tmp/review.md",
        id="write-code-review-mentioning-ai-guardian",
    ),
    pytest.param(
        "echo 'Install ai-guardian using pip install ai-guardian' > /home/user/docs/README.md",
        id="write-docs-about-ai-guardian",
    ),
    pytest.param(
        "cat <<'EOF' > /tmp/bug-report.txt\nThe ai-guardian configuration needs to be updated\nEOF",
        id="write-bug-report-mentioning-ai-guardian",
    ),
    pytest.param(
        "sed -i 's/old/new/' /home/user/my-project/docs/using-ai-guardian.md",
        id="sed-on-user-doc-file",
    ),
]


@pytest.mark.parametrize("command", BASH_ALLOWED_COMMANDS)
def test_bash_allows_command(policy_checker, command):
    """AI can use Bash for normal/legitimate commands"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Bash", "input": {"command": command}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert is_allowed, f"Bash command should be allowed: {command}"
    assert error_msg is None, "No error for allowed operation"


# ============================================================================
# Parametrized: Read blocks (Issue #512)
# ============================================================================

READ_BLOCKED_PATHS = [
    pytest.param("/home/user/.config/ai-guardian/ai-guardian.json", id="user-config"),
    pytest.param("/home/user/my-project/.ai-guardian.json", id="project-config"),
    pytest.param(
        "/home/user/.config/ai-guardian/profiles/default.json", id="config-directory"
    ),
    pytest.param(
        "/home/user/.local/state/ai-guardian/violations.jsonl", id="state-directory"
    ),
    pytest.param("/home/user/.local/state/ai-guardian/ai-guardian.log", id="state-log"),
    pytest.param(
        "/home/user/.local/state/ai-guardian/transcript_positions.json",
        id="state-transcript-positions",
    ),
    pytest.param("/home/user/.cache/ai-guardian/patterns.toml", id="cache-directory"),
]


@pytest.mark.parametrize("file_path", READ_BLOCKED_PATHS)
def test_read_blocks_protected_path(policy_checker, file_path):
    """AI cannot read ai-guardian config/state/cache files (Issue #512)"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Read", "input": {"file_path": file_path}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Read of {file_path} should be blocked"


READ_ALLOWED_PATHS = [
    pytest.param("/home/user/my-project/src/main.py", id="normal-file"),
    pytest.param(
        "/home/user/ai-guardian/src/ai_guardian/__init__.py", id="development-source"
    ),
]


@pytest.mark.parametrize("file_path", READ_ALLOWED_PATHS)
def test_read_allows_non_protected(policy_checker, file_path):
    """AI can read normal/development files"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Read", "input": {"file_path": file_path}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert is_allowed, f"Read of {file_path} should be allowed"
    assert error_msg is None


# ============================================================================
# Test: Error messages are clear
# ============================================================================


def test_error_message_format(policy_checker):
    """Error messages should be clear and helpful"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": "/home/user/.config/ai-guardian/ai-guardian.json",
                "old_string": "test",
                "new_string": "test2",
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert "Protection:" in error_msg
    assert "ai-guardian.json" in error_msg
    assert "Edit" in error_msg
    assert "ai-guardian configuration" in error_msg
    assert "IDE hook configuration" in error_msg
    assert "package source code" in error_msg
    assert ".ai-read-deny marker files" in error_msg
    assert "cannot be disabled via configuration" in error_msg
    assert "Use your text editor to modify these files" in error_msg


def test_error_message_format_hook_protection(policy_checker):
    """Hook protection messages for mixed settings files (Issue #807)"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": "/home/user/.claude/settings.json",
                "old_string": '"hooks": {}',
                "new_string": '"hooks": {"PreToolUse": []}',
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "Hook Protection" in error_msg
    assert "/home/user/.claude/settings.json" in error_msg
    assert "Edit" in error_msg
    assert "Non-hook settings" in error_msg
    assert "cannot be disabled via configuration" in error_msg


def test_error_message_marker_file_format(policy_checker):
    """Error message for .ai-read-deny should mention directory protection"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Write",
            "input": {"file_path": "/home/user/secrets/.ai-read-deny"},
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert "Protection:" in error_msg
    assert "/home/user/secrets/.ai-read-deny" in error_msg
    assert "Write" in error_msg
    assert "Directory Protection Marker" in error_msg
    assert ".ai-read-deny markers enforce directory protection" in error_msg
    assert "bypass directory protection" in error_msg
    assert "delete .ai-read-deny manually" in error_msg


# ============================================================================
# Test: Workaround tip for documentation files (Issue #65)
# ============================================================================


def test_error_message_includes_workaround_tip_for_write_protected_md_file(
    policy_checker,
):
    """Error message includes tip when writing to protected .md file with ai-guardian in name"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Write",
            "input": {
                "file_path": "/home/user/project/.config/ai-guardian/docs/setup.md"
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "\U0001f4a1 TIP" in error_msg
    assert "ai - guardian" in error_msg
    assert "with spaces" in error_msg
    assert "Writing ABOUT the tool" in error_msg


def test_error_message_for_pip_installed_readme(policy_checker):
    """Error message for pip-installed README explains it's production code"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": "/usr/lib/python3.12/site-packages/ai_guardian/README.md",
                "old_string": "old",
                "new_string": "new",
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "Pip-installed" in error_msg
    assert "security controls in production" in error_msg
    assert "git clone" in error_msg
    assert "Development source files CAN be edited" in error_msg


def test_error_message_includes_workaround_tip_for_protected_txt_in_docs(
    policy_checker,
):
    """Error message includes tip for protected .txt file with ai-guardian in path"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Write",
            "input": {"file_path": "/home/user/.config/ai-guardian/README.txt"},
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "\U0001f4a1 TIP" in error_msg


NO_TIP_CASES = [
    pytest.param(
        "Write",
        {"file_path": "/home/user/.config/ai-guardian/ai-guardian.json"},
        id="protected-config-file",
    ),
    pytest.param(
        "Edit",
        {
            "file_path": "/usr/lib/python3.12/site-packages/ai_guardian/tool_policy.py",
            "old_string": "old",
            "new_string": "new",
        },
        id="protected-python-source",
    ),
    pytest.param(
        "Write",
        {"file_path": "/home/user/.claude/hooks.json"},
        id="ide-settings-no-ai-guardian",
    ),
]


@pytest.mark.parametrize("tool_name_param,tool_input", NO_TIP_CASES)
def test_error_message_no_tip_for_non_doc_protected(
    policy_checker, tool_name_param, tool_input
):
    """Error message should NOT include tip for actual protected config/source/IDE files"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": tool_name_param, "input": tool_input},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "\U0001f4a1 TIP" not in error_msg


# ============================================================================
# Parametrized: Issue #113 - Fail-closed when file_path missing
# ============================================================================

MISSING_FILE_PATH_CASES = [
    pytest.param("Edit", {"input": {}}, id="edit-empty-input"),
    pytest.param("Write", {}, id="write-missing-input"),
    pytest.param("Read", {"input": {"limit": 100}}, id="read-other-params"),
    pytest.param("NotebookEdit", {"input": {}}, id="notebookedit-empty-input"),
]


@pytest.mark.parametrize("tool_name_param,tool_use_extra", MISSING_FILE_PATH_CASES)
def test_blocks_when_file_path_missing_issue_113(
    policy_checker, tool_name_param, tool_use_extra
):
    """
    Issue #113: AI cannot bypass IMMUTABLE checks by sending malformed tool_input.
    For file-path tools, fail-closed (block) if file_path is missing.
    """
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": tool_name_param, **tool_use_extra},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"{tool_name_param} with missing file_path should be blocked"
    assert error_msg is not None, "Error message should be provided"
    assert "Missing required parameter" in error_msg
    assert "file_path" in error_msg


# ============================================================================
# Test: Read error message mentions MCP alternative (Issue #512)
# ============================================================================


def test_read_error_message_mentions_mcp_alternative(policy_checker):
    """Read error message should suggest MCP tools as safe alternative"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Read",
            "input": {"file_path": "/home/user/.config/ai-guardian/ai-guardian.json"},
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "MCP tools" in error_msg
    assert "get_config()" in error_msg
    assert "get_violations()" in error_msg
    assert "doctor()" in error_msg


def test_read_error_message_for_state_file(policy_checker):
    """Read error message for state files should mention violations/logs"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Read",
            "input": {
                "file_path": "/home/user/.local/state/ai-guardian/violations.jsonl"
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "security state" in error_msg
    assert "detection results" in error_msg


def test_read_error_message_for_cache_file(policy_checker):
    """Read error message for cache files should mention patterns"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Read",
            "input": {"file_path": "/home/user/.cache/ai-guardian/patterns.toml"},
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed
    assert "cached security patterns" in error_msg
    assert "detection logic" in error_msg


# ============================================================================
# Issue #1065: Additional agent config file protection
# ============================================================================

AGENT_HOOK_WRITE_BLOCKED_PATHS = [
    pytest.param(
        "/home/user/.github/hooks/hooks.json",
        id="copilot-hooks",
    ),
    pytest.param(
        "/home/user/.codex/hooks.json",
        id="codex-hooks",
    ),
    pytest.param(
        "/home/user/.codeium/windsurf/hooks.json",
        id="windsurf-hooks",
    ),
    pytest.param(
        "/home/user/project/.clinerules/hooks/PreToolUse",
        id="cline-hooks-pretooluse",
    ),
    pytest.param(
        "/home/user/project/.clinerules/hooks/PostToolUse",
        id="cline-hooks-posttooluse",
    ),
    pytest.param(
        "/home/user/project/.kiro/hooks/PreToolUse",
        id="kiro-hooks-pretooluse",
    ),
    pytest.param(
        "/home/user/.aider-desk/extensions/ai-guardian/config.json",
        id="aiderdesk-extension",
    ),
    pytest.param(
        "/home/user/.openclaw/plugins/ai-guardian/plugin.json",
        id="openclaw-plugin",
    ),
]


@pytest.mark.parametrize("file_path", AGENT_HOOK_WRITE_BLOCKED_PATHS)
def test_write_blocks_agent_hook_files(policy_checker, file_path):
    """AI cannot write to additional agent hook/config files (Issue #1065)"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Write", "input": {"file_path": file_path}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Write to {file_path} should be blocked"
    assert error_msg is not None


@pytest.mark.parametrize("file_path", AGENT_HOOK_WRITE_BLOCKED_PATHS)
def test_edit_blocks_agent_hook_files(policy_checker, file_path):
    """AI cannot edit additional agent hook/config files (Issue #1065)"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {
            "name": "Edit",
            "input": {
                "file_path": file_path,
                "old_string": "ai-guardian",
                "new_string": "disabled",
            },
        },
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Edit of {file_path} should be blocked"


AGENT_HOOK_BASH_BLOCKED_COMMANDS = [
    # Copilot
    pytest.param(
        "sed -i 's/ai-guardian//' ~/.github/hooks/hooks.json",
        id="sed-copilot-hooks",
    ),
    pytest.param(
        "rm ~/.github/hooks/hooks.json",
        id="rm-copilot-hooks",
    ),
    pytest.param(
        "vim ~/.github/hooks/hooks.json",
        id="vim-copilot-hooks",
    ),
    pytest.param(
        "echo '{}' > ~/.github/hooks/hooks.json",
        id="redirect-copilot-hooks",
    ),
    # Codex
    pytest.param(
        "sed -i 's/ai-guardian//' ~/.codex/hooks.json",
        id="sed-codex-hooks",
    ),
    pytest.param(
        "rm ~/.codex/hooks.json",
        id="rm-codex-hooks",
    ),
    pytest.param(
        "chmod 000 ~/.codex/hooks.json",
        id="chmod-codex-hooks",
    ),
    # Windsurf
    pytest.param(
        "sed -i 's/ai-guardian//' ~/.codeium/windsurf/hooks.json",
        id="sed-windsurf-hooks",
    ),
    pytest.param(
        "mv ~/.codeium/windsurf/hooks.json /tmp/",
        id="mv-windsurf-hooks",
    ),
    pytest.param(
        "nano ~/.codeium/windsurf/hooks.json",
        id="nano-windsurf-hooks",
    ),
    # Cline / ZooCode
    pytest.param(
        "rm -rf .clinerules/hooks/PreToolUse",
        id="rm-cline-hooks",
    ),
    pytest.param(
        "sed -i 's/ai-guardian//' .clinerules/hooks/PostToolUse",
        id="sed-cline-hooks",
    ),
    pytest.param(
        "echo '#!/bin/sh' > .clinerules/hooks/PreToolUse",
        id="redirect-cline-hooks",
    ),
    # Kiro
    pytest.param(
        "rm .kiro/hooks/PreToolUse",
        id="rm-kiro-hooks",
    ),
    pytest.param(
        "chmod 000 .kiro/hooks/PromptSubmit",
        id="chmod-kiro-hooks",
    ),
    # AiderDesk
    pytest.param(
        "rm -rf ~/.aider-desk/extensions/ai-guardian",
        id="rm-aiderdesk-extension",
    ),
    pytest.param(
        "sed -i 's/enabled/disabled/' ~/.aider-desk/extensions/ai-guardian/config.json",
        id="sed-aiderdesk-extension",
    ),
    # OpenClaw
    pytest.param(
        "rm -rf ~/.openclaw/plugins/ai-guardian",
        id="rm-openclaw-plugin",
    ),
    pytest.param(
        "mv ~/.openclaw/plugins/ai-guardian /tmp/",
        id="mv-openclaw-plugin",
    ),
]


@pytest.mark.parametrize("command", AGENT_HOOK_BASH_BLOCKED_COMMANDS)
def test_bash_blocks_agent_hook_commands(policy_checker, command):
    """AI cannot use Bash to modify agent hook/config files (Issue #1065)"""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Bash", "input": {"command": command}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Bash command should be blocked: {command}"


# ============================================================================
# Issue #1072: Self-protection — block agent from running ai-guardian CLI
# ============================================================================

CLI_SELF_PROTECTION_BLOCKED_COMMANDS = [
    # pause
    pytest.param("ai-guardian pause 5", id="pause-with-minutes"),
    pytest.param("ai-guardian pause", id="pause-no-args"),
    # resume
    pytest.param("ai-guardian resume", id="resume"),
    # stop
    pytest.param("ai-guardian stop", id="stop"),
    # disable
    pytest.param("ai-guardian disable", id="disable"),
    # uninstall
    pytest.param("ai-guardian uninstall", id="uninstall"),
    # daemon stop
    pytest.param("ai-guardian daemon stop", id="daemon-stop"),
    # tray stop
    pytest.param("ai-guardian tray stop", id="tray-stop"),
    # Read-only and direct executable forms are protected as well.
    pytest.param("ai-guardian status", id="status"),
    pytest.param("ai-guardian --version", id="version"),
    pytest.param("/usr/local/bin/ai-guardian doctor", id="path-qualified"),
    pytest.param(
        r"C:\Users\user\.venv\Scripts\ai-guardian.exe scan",
        id="windows-path-qualified",
    ),
    pytest.param("python -m ai_guardian", id="python-module"),
    pytest.param("python3 -m ai_guardian.cli doctor", id="python-cli-module"),
    pytest.param("uv run ai-guardian check-update", id="uv-launcher"),
    pytest.param("env AI_GUARDIAN_TEST=1 ai-guardian doctor", id="env-wrapper"),
    pytest.param("sudo ai-guardian status", id="sudo-wrapper"),
    pytest.param("bash -lc 'ai-guardian status'", id="shell-wrapper"),
    pytest.param("powershell -Command 'ai-guardian status'", id="powershell-wrapper"),
]


CLI_SELF_PROTECTION_ALLOWED_MENTIONS = [
    "printf '%s\\n' 'ai-guardian status'",
    "grep -n ai-guardian README.md",
    "git -C ai-guardian status",
    "touch /tmp/ai-guardian-notes.txt",
    "cat docs/ai-guardian-status.md",
]


CLI_ADAPTER_PAYLOADS = [
    pytest.param(
        {
            "hook_event_name": "PreToolUse",
            "tool_use": {"name": "Bash", "input": {"command": "ai-guardian status"}},
        },
        id="claude-compatible",
    ),
    pytest.param(
        {
            "cursor_version": "1",
            "hook_name": "beforeShellExecution",
            "command": "ai-guardian status",
        },
        id="cursor",
    ),
    pytest.param(
        {
            "toolName": "Bash",
            "toolArgs": json.dumps({"command": "ai-guardian status"}),
        },
        id="copilot",
    ),
    pytest.param(
        {
            "conversationId": "conversation",
            "workspacePaths": ["/tmp/project"],
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "ai-guardian status"},
            },
        },
        id="antigravity",
    ),
    pytest.param(
        {
            "agent_action_name": "pre_run_command",
            "tool_info": {"name": "Bash", "command": "ai-guardian status"},
        },
        id="windsurf",
    ),
    pytest.param(
        {
            "kiro_hook_type": "pre_tool_use",
            "tool_name": "Bash",
            "tool_input": {"command": "ai-guardian status"},
        },
        id="kiro",
    ),
    pytest.param(
        {
            "clineVersion": "1",
            "tool_name": "Bash",
            "tool_input": {"command": "ai-guardian status"},
        },
        id="cline",
    ),
    pytest.param(
        {
            "is_mcp_tool": False,
            "tool_name": "launch-process",
            "tool_input": {"command": "ai-guardian status"},
        },
        id="augment",
    ),
    pytest.param(
        {
            "opencode_version": "1",
            "tool_use": {"name": "Bash", "input": {"command": "ai-guardian status"}},
        },
        id="opencode",
    ),
    pytest.param(
        {
            "pi_version": "1",
            "tool_use": {"name": "Bash", "input": {"command": "ai-guardian status"}},
        },
        id="pi",
    ),
    pytest.param(
        {
            "event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ai-guardian status"},
        },
        id="crush",
    ),
    pytest.param(
        {
            "model": "codex",
            "hook_event_name": "PreToolUse",
            "tool_use": {"name": "Bash", "input": {"command": "ai-guardian status"}},
        },
        id="codex",
    ),
    pytest.param(
        {
            "transcript_path": "/tmp/transcript.jsonl",
            "hook_event_name": "BeforeTool",
            "tool_use": {"name": "Bash", "input": {"command": "ai-guardian status"}},
        },
        id="gemini",
    ),
    pytest.param(
        {
            "dummy_agent": True,
            "hook_event_name": "PreToolUse",
            "tool_use": {"name": "Bash", "input": {"command": "ai-guardian status"}},
        },
        id="dummy-agent",
    ),
]


@pytest.mark.parametrize("command", CLI_SELF_PROTECTION_BLOCKED_COMMANDS)
def test_bash_blocks_ai_guardian_cli_self_protection(policy_checker, command):
    """AI cannot launch any ai-guardian CLI command from Bash (Issue #2428)."""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Bash", "input": {"command": command}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"Bash command should be blocked: {command}"


@pytest.mark.parametrize("command", CLI_SELF_PROTECTION_ALLOWED_MENTIONS)
def test_bash_allows_non_invocation_mentions(policy_checker, command):
    """Text, filenames, and repository paths mentioning the CLI remain usable."""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Bash", "input": {"command": command}},
    }

    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert is_allowed, f"Non-invocation should be allowed: {command}"
    assert error_msg is None


@pytest.mark.parametrize(
    "tool_name",
    ["Shell", "PowerShell"],
)
def test_shell_tools_share_immutable_cli_protection(policy_checker, tool_name):
    """All supported shell tool names use the same immutable guard."""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": tool_name, "input": {"command": "ai-guardian status"}},
    }

    is_allowed, error_msg, checked_tool_name = policy_checker.check_tool_allowed(
        hook_data
    )

    assert not is_allowed
    assert checked_tool_name == tool_name
    assert "Pattern:" not in error_msg
    assert "allow" not in error_msg.lower()
    assert "immutable" in error_msg.lower()


@patch("ai_guardian.violations.log_violation.log_violation")
def test_cli_protection_logs_no_permission_allowlist_guidance(
    mock_log_violation, policy_checker
):
    """The persisted CLI violation must not expose an agent bypass suggestion."""
    hook_data = {
        "hook_event_name": "PreToolUse",
        "tool_use": {"name": "Bash", "input": {"command": "ai-guardian status"}},
    }

    policy_checker.check_tool_allowed(hook_data)

    assert mock_log_violation.call_args.kwargs["suggestion"] == {}


@pytest.mark.parametrize("hook_data", CLI_ADAPTER_PAYLOADS)
def test_supported_adapter_payloads_use_cli_protection(policy_checker, hook_data):
    """Adapter-specific shell payloads cannot bypass the immutable guard."""
    is_allowed, error_msg, tool_name = policy_checker.check_tool_allowed(hook_data)

    assert not is_allowed, f"CLI invocation should be blocked: {hook_data}"
    assert error_msg is not None
    assert "agent-originated" in error_msg.lower()


if __name__ == "__main__":
    pytest.main([__file__])
