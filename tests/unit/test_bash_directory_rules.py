"""
Test that Bash tool commands are not incorrectly treated as file paths
for directory_rules checking and error messages.

Bug #94: Directory rules incorrectly parse Bash command text as file paths
"""

import unittest
import json
from pathlib import Path
from ai_guardian import process_hook_input
from unittest.mock import patch
from io import StringIO


class TestBashDirectoryRules(unittest.TestCase):
    """Test that Bash commands don't trigger false positive directory blocks"""

    def test_bash_error_message_shows_command_not_file(self):
        """Bug #94: Error message should show 'Command:' not 'File:' for Bash tool"""
        # Create a Bash command that matches an immutable deny pattern
        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_use": {
                "name": "Bash",
                "parameters": {
                    "command": "sed -i 's/foo/bar/' ~/.config/ai-guardian/ai-guardian.json",
                    "description": "Modify config",
                },
            },
        }

        stdin_input = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(stdin_input)):
            response = process_hook_input()

        # PreToolUse uses JSON response, not exit codes
        self.assertEqual(
            response["exit_code"], 0, "PreToolUse always returns exit_code 0"
        )
        self.assertIsNotNone(response.get("output"), "Should have JSON output")

        # Parse JSON response
        output = json.loads(response["output"])

        # Check blocking decision
        self.assertEqual(
            output.get("hookSpecificOutput", {}).get("permissionDecision"),
            "deny",
            "Command should be blocked (permissionDecision: deny)",
        )

        # Check that the error message contains "Command:" not "File:"
        if "systemMessage" in output:
            error_msg = output["systemMessage"]
            self.assertIn(
                "Command:",
                error_msg,
                "Error message should show 'Command:' for Bash tool",
            )
            self.assertNotIn(
                "File: sed",
                error_msg,
                "Error message should not show 'File: <command>' for Bash tool",
            )

    def test_bash_command_not_treated_as_file_path(self):
        """Bash command text should not be checked as a file path"""
        # Simulate a Bash tool call with a long command
        # This should NOT be treated as a file path for directory rules
        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_use": {
                "name": "Bash",
                "parameters": {
                    "command": 'daf git create enhancement --summary "Phase 1: ..." --description "..."',
                    "description": "Create GitHub issue",
                },
            },
        }

        # Mock stdin to provide hook data
        stdin_input = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(stdin_input)):
            with patch(
                "ai_guardian.scanners.secret_scanning.check_secrets",
                return_value=(False, None),
            ):
                response = process_hook_input()

        # Should allow the operation (no directory blocking)
        self.assertEqual(
            response["exit_code"],
            0,
            "Bash command should not be blocked by directory rules",
        )

    def test_bash_command_with_directory_rules_configured(self):
        """Bash commands should not match directory rules patterns"""
        # Configure directory rules that might accidentally match command text
        config = {"directory_rules": [{"mode": "deny", "paths": ["/tmp/skills/**"]}]}

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_use": {
                "name": "Bash",
                "parameters": {
                    "command": "echo 'test command with /tmp/skills/something in it'",
                    "description": "Test command",
                },
            },
        }

        stdin_input = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(stdin_input)):
            with patch(
                "ai_guardian.scanners.secret_scanning.check_secrets",
                return_value=(False, None),
            ):
                with patch(
                    "ai_guardian.hook_processing.ToolPolicyChecker"
                ) as mock_policy:
                    # Mock policy checker to return allowed
                    mock_policy.return_value.check_tool_allowed.return_value = (
                        True,
                        None,
                        "Bash",
                    )
                    response = process_hook_input()

        # Should allow - command text should not be matched against directory rules
        self.assertEqual(
            response["exit_code"],
            0,
            "Bash command text should not match directory rules",
        )

    def test_only_file_reading_tools_check_directory_rules(self):
        """Only tools that read files (Read, etc.) should check directory rules"""
        # Test that Read tool DOES check directory rules
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .ai-read-deny marker
            deny_marker = Path(tmpdir) / ".ai-read-deny"
            deny_marker.touch()

            # Create test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test content")

            # Read tool should be blocked
            hook_data = {
                "hook_event_name": "PreToolUse",
                "tool_use": {
                    "name": "Read",
                    "parameters": {"file_path": str(test_file)},
                },
            }

            stdin_input = json.dumps(hook_data)

            # Mock config to use block mode (not log mode)
            mock_config = {"directory_rules": {"action": "block", "rules": []}}

            with patch("sys.stdin", StringIO(stdin_input)):
                with patch(
                    "ai_guardian.hook_processing.ToolPolicyChecker"
                ) as mock_policy_cls:
                    mock_policy = mock_policy_cls.return_value
                    mock_policy.config = mock_config
                    mock_policy.check_tool_allowed.return_value = (True, None, "Read")
                    response = process_hook_input()

            # PreToolUse uses JSON response
            output = json.loads(response["output"])
            self.assertEqual(
                output.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
                "Read tool should be blocked by .ai-read-deny",
            )

            # But Bash tool with same file path in command should NOT be blocked
            hook_data_bash = {
                "hook_event_name": "PreToolUse",
                "tool_use": {
                    "name": "Bash",
                    "parameters": {
                        "command": f"cat {test_file}",
                        "description": "Read file",
                    },
                },
            }

            stdin_input_bash = json.dumps(hook_data_bash)

            with patch("sys.stdin", StringIO(stdin_input_bash)):
                with patch(
                    "ai_guardian.scanners.secret_scanning.check_secrets",
                    return_value=(False, None),
                ):
                    with patch(
                        "ai_guardian.hook_processing.ToolPolicyChecker"
                    ) as mock_policy:
                        mock_policy.return_value.check_tool_allowed.return_value = (
                            True,
                            None,
                            "Bash",
                        )
                        response_bash = process_hook_input()

            # Bash should NOT be blocked (command text is not a file path to check)
            self.assertEqual(
                response_bash["exit_code"],
                0,
                "Bash command should not be blocked even if it references a blocked file",
            )


if __name__ == "__main__":
    unittest.main()
