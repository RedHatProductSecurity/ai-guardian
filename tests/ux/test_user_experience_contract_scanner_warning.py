"""
User Experience Contract Tests for Scanner Not Installed Warning (Issue #343)

These tests document and verify the expected user experience when ai-guardian's
default scanner is not installed. Instead of blocking the user entirely, a
warning is displayed at each hook invocation while allowing operations to continue.

Issue #343: Display warning instead of blocking when default scanner is not installed.
"""

import json
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import ai_guardian
from tests.fixtures.mock_mcp_server import create_hook_data


class ScannerNotInstalledWarningTests(TestCase):
    """
    Tests documenting the user experience when the default scanner is not installed.

    When no scanner engine is available, ai-guardian should:
    - Display a warning message at each hook invocation
    - Allow the operation to continue (not block)
    - Include the scanner name and install command in the warning
    """

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_pretooluse_warns_when_scanner_not_installed(
        self, mock_config, mock_select_engine
    ):
        """
        USER EXPERIENCE: Read file with no scanner installed → WARNING shown, operation ALLOWED.

        Scenario:
        1. User has not installed any scanner (e.g., gitleaks)
        2. User asks Claude: "Read the config file"
        3. Claude tries to Read file
        4. ai-guardian PreToolUse hook runs
        5. select_engine() raises RuntimeError (no scanner found)

        Expected User Experience:
        ⚠️ Warning message shown via systemMessage
        ✅ Operation is ALLOWED (no permissionDecision: deny)
        🛡️ User sees: "Please install the gitleaks..."
        """
        mock_config.return_value = ({"engines": ["gitleaks"]}, None)
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("some file content")
            temp_path = f.name

        try:
            hook_data = create_hook_data(
                tool_name="Read",
                tool_input={"file_path": temp_path},
                hook_event="PreToolUse",
            )

            with patch("sys.stdin", StringIO(json.dumps(hook_data))):
                result = ai_guardian.process_hook_input()

            assert result["exit_code"] == 0

            response = json.loads(result["output"])

            # CONTRACT: Operation is NOT blocked
            assert (
                "hookSpecificOutput" not in response
                or response.get("hookSpecificOutput", {}).get("permissionDecision")
                != "deny"
            ), "Must NOT deny when scanner is not installed (Issue #343)"

            # CONTRACT: Warning is shown via systemMessage
            assert "systemMessage" in response, "Must include warning via systemMessage"
            warning = response["systemMessage"]
            assert "WARNING" in warning, "Warning should contain WARNING indicator"
            assert (
                "ai-guardian scanner install gitleaks" in warning
            ), "Warning should contain install command with scanner name"
            assert (
                "you may leak secrets" in warning
            ), "Warning should mention risk of leaking secrets"

        finally:
            os.unlink(temp_path)

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_posttooluse_warns_when_scanner_not_installed(
        self, mock_config, mock_select_engine
    ):
        """
        USER EXPERIENCE: Tool output with no scanner installed → WARNING shown, output ALLOWED.

        Scenario:
        1. User has not installed any scanner
        2. Claude runs a Bash command that produces output
        3. ai-guardian PostToolUse hook runs to scan output
        4. select_engine() raises RuntimeError (no scanner found)

        Expected User Experience:
        ⚠️ Warning message shown via systemMessage
        ✅ Tool output is ALLOWED through (not blocked)
        """
        mock_config.return_value = ({"engines": ["gitleaks"]}, None)
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_response": {"stdout": "some command output", "stderr": ""},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        assert result["exit_code"] == 0

        response = json.loads(result["output"])

        # CONTRACT: Operation is NOT blocked
        assert (
            response.get("decision") != "block"
        ), "Must NOT block PostToolUse when scanner is not installed"

        # CONTRACT: Warning is shown via systemMessage
        assert (
            "systemMessage" in response
        ), "Must include warning via systemMessage for PostToolUse"
        warning = response["systemMessage"]
        assert (
            "ai-guardian scanner install gitleaks" in warning
        ), "Warning should contain install command"
        assert "you may leak secrets" in warning, "Warning should mention risk"

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_prompt_warns_when_scanner_not_installed(
        self, mock_config, mock_select_engine
    ):
        """
        USER EXPERIENCE: User prompt with no scanner installed → WARNING shown, prompt ALLOWED.

        Scenario:
        1. User has not installed any scanner
        2. User submits a prompt
        3. ai-guardian UserPromptSubmit hook runs
        4. select_engine() raises RuntimeError

        Expected User Experience:
        ⚠️ Warning message shown via systemMessage
        ✅ Prompt submission is ALLOWED
        """
        mock_config.return_value = ({"engines": ["gitleaks"]}, None)
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Please read the database config",
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        assert result["exit_code"] == 0

        response = json.loads(result["output"])

        # CONTRACT: Prompt is NOT blocked
        assert (
            response.get("decision") != "block"
        ), "Must NOT block prompt when scanner is not installed"

        # CONTRACT: Warning is shown via systemMessage
        assert (
            "systemMessage" in response
        ), "Must include warning via systemMessage for UserPromptSubmit"
        warning = response["systemMessage"]
        assert (
            "ai-guardian scanner install gitleaks" in warning
        ), "Warning should contain install command"
        assert "you may leak secrets" in warning, "Warning should mention risk"

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_warning_uses_configured_scanner_name(
        self, mock_config, mock_select_engine
    ):
        """
        USER EXPERIENCE: Warning dynamically uses the configured default scanner name.

        When config has engines: ["betterleaks", "gitleaks"], the warning should
        suggest installing "betterleaks" (the first/default engine), not "gitleaks".
        """
        mock_config.return_value = ({"engines": ["betterleaks", "gitleaks"]}, None)
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "test prompt",
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        response = json.loads(result["output"])
        warning = response.get("systemMessage", "")

        assert (
            "ai-guardian scanner install betterleaks" in warning
        ), "Warning should suggest the configured default scanner (betterleaks), not hardcoded gitleaks"

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    def test_warning_defaults_to_toml_patterns_when_no_config(
        self, mock_config, mock_select_engine
    ):
        """
        USER EXPERIENCE: Warning defaults to toml-patterns + gitleaks when no scanner config exists.

        Since toml-patterns is built-in, the default engine list is
        ["toml-patterns", "gitleaks"]. If both fail (shouldn't happen
        in practice since toml-patterns is always available), the warning
        mentions gitleaks as the install suggestion.
        """
        mock_config.return_value = (None, None)
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        hook_data = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "test prompt",
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        response = json.loads(result["output"])
        warning = response.get("systemMessage", "")

        assert (
            "scanner" in warning.lower()
        ), "Warning should mention scanner when no engine is available"
        mock_select_engine.assert_called_once_with(
            ["toml-patterns", "gitleaks"], parent_config=None
        )
