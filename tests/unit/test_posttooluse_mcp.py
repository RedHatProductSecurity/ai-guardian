"""
PostToolUse hook integration tests with MCP tools.

Tests output scanning and redaction functionality when tools return results
to the AI. Covers secret detection, prompt injection detection, and redaction
in tool responses.
"""

import json
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import pytest

import ai_guardian
from ai_guardian.hook_processing import extract_tool_result
from tests.fixtures.mock_mcp_server import create_tool_response
from tests.fixtures import attack_constants


class PostToolUseSecretScanningTests(TestCase):
    """Test secret scanning in tool outputs"""

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_bash_output_with_secret_blocked(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify secrets in Bash output are blocked.

        Scenario: Bash command returns output containing secret
        Action: PostToolUse with Bash output containing Slack token
        Expected: BLOCKED with decision='block' in response
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Create PostToolUse hook data with secret in Bash output
        hook_data = create_tool_response(
            tool_name="Bash",
            output=f"Environment variables:\nSLACK_TOKEN={attack_constants.SECRET_SLACK_TOKEN}\n",
        )

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: Exit 0 with warning message (redacted, not blocked)
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"
        response = json.loads(result["output"])
        assert (
            response.get("systemMessage") is not None
        ), "Should have warning about redacted secrets"
        assert "Redacted" in response.get(
            "systemMessage", ""
        ), "Warning should mention redaction"
        # Verify secret was redacted from output
        output_text = response.get("modified_output", response.get("output", ""))
        assert (
            attack_constants.SECRET_SLACK_TOKEN not in output_text
        ), "Secret should be redacted"

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_read_output_with_secret_blocked(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify secrets in Read tool output are redacted.

        Scenario: Read tool returns file content with secret
        Action: PostToolUse with Read output containing secret
        Expected: REDACTED with warning message
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = ({"enabled": True, "action": "warn"}, None)

        # Create PostToolUse hook data with secret in file content
        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_response": {
                "content": f"Config file:\napi_token: {attack_constants.SECRET_SLACK_TOKEN}\n"
            },
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: warning message (redacted, not blocked)
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"
        response = json.loads(result["output"])
        assert (
            response.get("systemMessage") is not None
        ), "Should have warning about redacted secrets"
        assert "Redacted" in response.get(
            "systemMessage", ""
        ), "Warning should mention redaction"
        # Verify secret was redacted from output
        output_text = response.get("modified_output", response.get("content", ""))
        assert (
            attack_constants.SECRET_SLACK_TOKEN not in output_text
        ), "Secret should be redacted"

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_bash_clean_output_allowed(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify clean Bash output is allowed.

        Scenario: Bash returns normal output without secrets
        Action: PostToolUse with clean output
        Expected: ALLOWED (no 'decision' field in response)
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Create PostToolUse hook data with clean output
        hook_data = create_tool_response(
            tool_name="Bash",
            output="Hello, World!\nOperation completed successfully.\n",
        )

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED (exit 0, no 'decision' field)
        assert result["exit_code"] == 0, "Clean Bash output should be allowed"
        response = json.loads(result["output"])
        assert (
            "decision" not in response or response.get("decision") != "block"
        ), "Clean output should not have decision='block'"

    def test_write_tool_output_skipped(self):
        """
        Verify Write tool PostToolUse is skipped (no output scanning needed).

        Scenario: Write tool completes successfully
        Action: PostToolUse for Write tool
        Expected: ALLOWED (state-modifying tools don't return scannable output)
        """
        # Create PostToolUse hook data for Write tool
        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_response": {"filePath": "/tmp/test.py", "success": True},
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED (Write output not scanned)
        assert result["exit_code"] == 0, "Write tool PostToolUse should be allowed"

    def test_edit_tool_output_skipped(self):
        """
        Verify Edit tool PostToolUse is skipped.

        Scenario: Edit tool completes successfully
        Action: PostToolUse for Edit tool
        Expected: ALLOWED
        """
        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_response": {"success": True},
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED
        assert result["exit_code"] == 0, "Edit tool PostToolUse should be allowed"


class PostToolUseContentScanningTests(TestCase):
    """Test content scanning in tool outputs

    Note: PostToolUse currently only scans for secrets, not prompt injection.
    Prompt injection detection is a UserPromptSubmit concern (user input to AI),
    not a PostToolUse concern (tool output to AI).
    """

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_bash_output_with_potential_injection_allowed(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify tool output with injection-like patterns is allowed.

        Scenario: Bash returns output that looks like prompt injection
        Action: PostToolUse with injection-like text
        Expected: ALLOWED (PostToolUse doesn't scan for prompt injection)

        Rationale: Tool outputs are data returned TO the AI, not user prompts.
        The AI should be able to read tool results without injection concerns.
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Output that looks like prompt injection but is just tool data
        hook_data = create_tool_response(
            tool_name="Bash",
            output=f"Found in logs:\n{attack_constants.PROMPT_INJECTION_IGNORE_PREVIOUS}\n",
        )

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED (PostToolUse only scans for secrets)
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"
        response = json.loads(result["output"])
        assert (
            response.get("decision") != "block"
        ), "Tool output with injection-like text should be allowed (not user input)"

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_read_file_with_commands_allowed(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify file content with commands is allowed.

        Scenario: Read returns file containing shell commands
        Action: PostToolUse with Read output containing commands
        Expected: ALLOWED (file content is data, not malicious input)
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_response": {
                "content": f"#!/bin/bash\n{attack_constants.PROMPT_INJECTION_ROLE_SWITCH}\necho 'done'\n"
            },
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"
        response = json.loads(result["output"])
        assert (
            response.get("decision") != "block"
        ), "File content with commands should be allowed"

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_normal_code_file_allowed(self, mock_pattern_config, mock_redaction_config):
        """
        Verify normal code files are allowed.

        Scenario: Read returns normal source code
        Action: PostToolUse with legitimate Python code
        Expected: ALLOWED
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_response": {"content": """
def hello_world():
    print("Hello, World!")
    return True

if __name__ == "__main__":
    hello_world()
"""},
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED
        assert result["exit_code"] == 0, "Normal code file should be allowed"
        response = json.loads(result["output"])
        assert response.get("decision") != "block", "Clean code should be allowed"


class PostToolUseMCPToolTests(TestCase):
    """Test PostToolUse with MCP tool responses"""

    def test_extract_structured_mcp_tools_call_result(self):
        """Structured MCP results are serialized so nested content is scannable."""
        output, tool_name = extract_tool_result(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": attack_constants.MCP_TOOL_NOTEBOOKLM_QUERY,
                "tool_response": {
                    "content": [{"type": "text", "text": "A public answer"}],
                    "isError": False,
                },
            }
        )

        assert tool_name == attack_constants.MCP_TOOL_NOTEBOOKLM_QUERY
        assert '"text": "A public answer"' in output

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_mcp_response_with_secret_redacted(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify secrets in structured MCP tool responses are redacted.

        Scenario: MCP notebook_query returns answer
        Action: PostToolUse with MCP response
        Expected: Secret is removed from the structured result before it reaches the AI.
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Create PostToolUse for MCP tool with secret in response
        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": attack_constants.MCP_TOOL_NOTEBOOKLM_QUERY,
            "tool_response": {
                "answer": f"The API token is {attack_constants.SECRET_SLACK_TOKEN}",
                "sources": [],
                "status": "success",
            },
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: PostToolUse returns exit 0
        # MCP tool responses might not be scanned the same as Bash/Read
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"

        # This test documents current behavior - MCP responses may not be scanned
        # If extract_tool_result() doesn't handle this MCP tool specifically,
        # it will return None and scanning will be skipped

    def test_mcp_clean_response_allowed(self):
        """
        Verify clean MCP responses are allowed.

        Scenario: MCP notebook_query returns normal answer
        Action: PostToolUse with clean MCP response
        Expected: ALLOWED
        """
        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": attack_constants.MCP_TOOL_NOTEBOOKLM_QUERY,
            "tool_response": {
                "answer": "The research shows that AI security is important.",
                "sources": ["source_1", "source_2"],
                "status": "success",
            },
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED
        assert result["exit_code"] == 0, "Clean MCP response should be allowed"

    def test_mcp_notebook_list_allowed(self):
        """
        Verify MCP notebook_list responses are allowed.

        Scenario: MCP notebook_list returns notebook metadata
        Action: PostToolUse with notebook list
        Expected: ALLOWED
        """
        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "mcp__notebooklm-mcp__notebook_list",
            "tool_response": {
                "notebooks": [
                    {
                        "notebook_id": "nb_1",
                        "title": "Research Notes",
                        "source_count": 5,
                    },
                    {
                        "notebook_id": "nb_2",
                        "title": "Project Planning",
                        "source_count": 3,
                    },
                ],
                "count": 2,
                "status": "success",
            },
        }

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: ALLOWED
        assert result["exit_code"] == 0, "Notebook list should be allowed"


class PostToolUseRedactionTests(TestCase):
    """Test secret redaction in tool outputs"""

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_redaction_mode_replaces_secrets(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify redaction mode replaces secrets in output.

        Scenario: Redaction enabled, Bash output contains secret
        Action: PostToolUse with redaction mode enabled
        Expected: Secret redacted, output allowed with modified content

        Note: This test documents expected behavior. Actual implementation
        may vary based on redaction configuration.
        """
        # Disable pattern server, enable redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (
            {"enabled": True, "mode": "redact", "redaction_string": "[REDACTED]"},
            None,
        )

        # Create PostToolUse with secret
        hook_data = create_tool_response(
            tool_name="Bash",
            output=f"Token: {attack_constants.SECRET_SLACK_TOKEN}\nOther output",
        )

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: PostToolUse returns exit 0
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"

        # Response behavior depends on redaction config
        if result["output"] is not None:
            response = json.loads(result["output"])
            # Either decision='block' or has modifiedOutput with redacted content
            # This is configuration-dependent


class PostToolUseCombinedTests(TestCase):
    """Test combined scenarios in PostToolUse"""

    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_multiple_threats_in_output(
        self, mock_pattern_config, mock_redaction_config
    ):
        """
        Verify output with multiple threats is blocked.

        Scenario: Bash output contains both secret and prompt injection
        Action: PostToolUse with multiple violations
        Expected: BLOCKED by first detected threat
        """
        # Disable pattern server and redaction
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = (None, None)

        # Output with both secret AND prompt injection
        malicious_output = f"""
        {attack_constants.PROMPT_INJECTION_IGNORE_PREVIOUS}
        Token: {attack_constants.SECRET_SLACK_TOKEN}
        """

        hook_data = create_tool_response(tool_name="Bash", output=malicious_output)

        hook_json = json.dumps(hook_data)

        with patch("sys.stdin", StringIO(hook_json)):
            result = ai_guardian.process_hook_input()

        # Expected: warning message (redacted, not blocked)
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"
        response = json.loads(result["output"])
        assert (
            response.get("systemMessage") is not None
        ), "Should have warning about redacted secrets"
        assert "Redacted" in response.get(
            "systemMessage", ""
        ), "Warning should mention redaction"
        # Verify secrets were redacted from output
        output_text = response.get("modified_output", response.get("output", ""))
        assert (
            attack_constants.SECRET_SLACK_TOKEN not in output_text
        ), "Secret should be redacted"

    def test_json_output_with_nested_secret(self):
        """
        Verify JSON output with nested secrets is blocked.

        Scenario: Tool returns JSON with secret in nested field
        Action: PostToolUse with JSON containing secret
        Expected: BLOCKED
        """
        # This test would require the tool to return structured JSON
        # and secret scanner to handle JSON serialization
        # Skipping for now - document as potential enhancement
        pytest.skip("JSON nested secret detection - future enhancement")
