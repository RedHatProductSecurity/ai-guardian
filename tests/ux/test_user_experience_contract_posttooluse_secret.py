"""
User Experience Contract Tests for PostToolUse Secret Handling

These tests document and verify the expected user experience when ai-guardian
detects secrets in PostToolUse output with different secret_redaction settings.

Issue #414: PostToolUse must BLOCK secrets when secret_redaction is disabled,
not allow them through as an "emergency bypass".

All tests use isolated_config_dir fixture (#344) to avoid writing to real
violations.jsonl.
"""

import json
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import ai_guardian
from ai_guardian.hook_events.scanners import run_secret_scan as _run_secret_scan


class PostToolUseSecretBlockingTests(TestCase):
    """
    Tests verifying PostToolUse correctly blocks secrets when redaction is disabled.
    """

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_blocks_secret_when_redaction_disabled(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Bash output with secret + redaction disabled -> BLOCKED

        Scenario:
        1. User runs: cat credentials.txt
        2. Output contains: SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234
        3. ai-guardian PostToolUse hook runs
        4. Secret detected, redaction disabled

        Expected User Experience:
        x Tool output BLOCKED
        User sees: "Secret Detected - aws-access-token"
        Output does NOT reach AI model
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = ({"enabled": False}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "test_001",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") == "block"
        ), f"PostToolUse must BLOCK secrets when redaction is disabled, got: {output}"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_redacts_secret_when_redaction_enabled(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Bash output with secret + redaction enabled -> ALLOWED
        with redacted output via updatedToolOutput (#2042).

        Scenario:
        1. User runs: cat credentials.txt
        2. Output contains: SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234
        3. ai-guardian PostToolUse hook runs
        4. Secret detected, redaction enabled

        Expected User Experience:
        Tool output is replaced with redacted content via updatedToolOutput
        in object form (Bash: {stdout, stderr, interrupted}).
        Agent sees redacted text as the normal tool result.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = ({"enabled": True, "action": "warn"}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "test_002",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor"
            ) as MockRedactor:
                mock_instance = MockRedactor.return_value
                mock_instance.redact.return_value = {
                    "redacted_text": "AWS_ACCESS_KEY=***REDACTED***",
                    "redactions": [
                        {"type": "aws-access-token", "position": 16, "strategy": "mask"}
                    ],
                }
                result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert output.get("decision") != "block", (
            "PostToolUse must NOT block when redaction succeeds — "
            "use updatedToolOutput instead"
        )
        uto = output.get("hookSpecificOutput", {}).get("updatedToolOutput", {})
        assert isinstance(
            uto, dict
        ), f"Bash updatedToolOutput must be object form, got: {type(uto)}"
        assert "***REDACTED***" in uto.get(
            "stdout", ""
        ), f"updatedToolOutput.stdout must contain redacted text, got: {uto}"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_blocks_when_redaction_config_missing(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Secret detected + no redaction config -> ALLOWED
        with redacted output via updatedToolOutput (#2042).

        When secret_redaction config is None (not configured), enabled defaults
        to True. Redaction runs and output is replaced via updatedToolOutput.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = (None, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "test_003",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor"
            ) as MockRedactor:
                mock_instance = MockRedactor.return_value
                mock_instance.redact.return_value = {
                    "redacted_text": "AWS_ACCESS_KEY=***REDACTED***",
                    "redactions": [
                        {"type": "aws-access-token", "position": 16, "strategy": "mask"}
                    ],
                }
                result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        uto = output.get("hookSpecificOutput", {}).get("updatedToolOutput", {})
        assert isinstance(
            uto, dict
        ), f"Bash updatedToolOutput must be object form, got: {type(uto)}"
        assert "***REDACTED***" in uto.get(
            "stdout", ""
        ), "updatedToolOutput.stdout must contain redacted text"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_blocks_when_redaction_config_error(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Secret detected + redaction config error -> BLOCKED

        When loading secret_redaction config fails, the system falls back to
        blocking to prevent secrets from leaking.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = (None, "Failed to load config")
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "test_004",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") == "block"
        ), f"PostToolUse must BLOCK when redaction config has errors, got: {output}"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_blocks_when_redactor_finds_zero_redactions(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Secret detected + redaction enabled + 0 redactions -> BLOCKED

        When detection finds a secret but the redactor's patterns don't match
        it (0 redactions), PostToolUse must fall back to blocking to prevent
        the unredacted secret from reaching the AI agent (#1624).
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - env-variable")
        mock_redact.return_value = ({"enabled": True, "action": "warn"}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "zero_redact_001",
            "tool_input": {"command": "env | grep JIRA"},
            "tool_response": {
                "output": "JIRA_API_TOKEN=dGVzdHVzZXJAZXhhbXBsZS5jb206ZmFrZXRva2VuMTIz"
            },
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor"
            ) as MockRedactor:
                mock_instance = MockRedactor.return_value
                mock_instance.redact.return_value = {
                    "redacted_text": "JIRA_API_TOKEN=dGVzdHVzZXJAZXhhbXBsZS5jb206ZmFrZXRva2VuMTIz",
                    "redactions": [],
                }
                result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") == "block"
        ), f"PostToolUse must BLOCK when redactor finds 0 redactions, got: {output}"


class PostToolUseRedactedOutputInContextTests(TestCase):
    """
    Tests verifying that redacted output is sent via updatedToolOutput
    when PostToolUse detects secrets after successful redaction (#2042).

    Previously used additionalContext workaround (#1630) because
    updatedToolOutput bare string was silently ignored. Now uses
    object-form updatedToolOutput (confirmed in claude-code #68951).
    """

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_sends_redacted_output_in_updated_tool_output(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Redacted output appears in updatedToolOutput

        When secrets are detected and redaction succeeds, the agent
        receives the redacted output via updatedToolOutput so it can
        continue working with sanitized content. For Bash tool, the
        output is wrapped in object form {stdout, stderr, interrupted}.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = ({"enabled": True, "action": "warn"}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "ctx_test_001",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor"
            ) as MockRedactor:
                mock_instance = MockRedactor.return_value
                mock_instance.redact.return_value = {
                    "redacted_text": "SECRET_KEY=***REDACTED***",
                    "redactions": [
                        {"type": "aws-access-token", "position": 11, "strategy": "mask"}
                    ],
                }
                result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert (
            output.get("decision") != "block"
        ), "PostToolUse must NOT block when redaction succeeds"
        uto = output.get("hookSpecificOutput", {}).get("updatedToolOutput", {})
        assert isinstance(
            uto, dict
        ), f"Bash updatedToolOutput must be object form, got: {type(uto)}"
        assert "***REDACTED***" in uto.get(
            "stdout", ""
        ), f"updatedToolOutput.stdout must contain the redacted text, got: {uto}"
        assert "FAKE_TEST_SECRET_VALUE_1234" not in uto.get(
            "stdout", ""
        ), "updatedToolOutput.stdout must NOT contain the raw secret"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_no_redacted_output_when_zero_redactions(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Zero redactions -> NO redacted output in context

        When detection finds a secret but the redactor produces 0 redactions,
        additionalContext must NOT contain the original (unredacted) output.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - env-variable")
        mock_redact.return_value = ({"enabled": True, "action": "warn"}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "ctx_test_002",
            "tool_input": {"command": "env | grep TOKEN"},
            "tool_response": {"output": "MY_TOKEN=supersecretvalue"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor"
            ) as MockRedactor:
                mock_instance = MockRedactor.return_value
                mock_instance.redact.return_value = {
                    "redacted_text": "MY_TOKEN=supersecretvalue",
                    "redactions": [],
                }
                result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert output.get("decision") == "block"
        ctx = output.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert (
            "supersecretvalue" not in ctx
        ), "additionalContext must NOT leak the original output on zero redactions"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_no_redacted_output_when_redaction_disabled(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Redaction disabled -> NO redacted output in context

        When redaction is disabled, there is no redacted text to send.
        additionalContext must contain only the sanitized block reason.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = ({"enabled": False}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "ctx_test_003",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        assert output.get("decision") == "block"
        ctx = output.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert (
            "FAKE_TEST_SECRET_VALUE_1234" not in ctx
        ), "additionalContext must NOT leak the raw secret"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_posttooluse_system_message_indicates_redaction(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: systemMessage tells agent secrets were redacted

        When redacted output is sent via updatedToolOutput, the
        systemMessage warns the agent about redacted secrets.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = ({"enabled": True, "action": "warn"}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "ctx_test_004",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor"
            ) as MockRedactor:
                mock_instance = MockRedactor.return_value
                mock_instance.redact.return_value = {
                    "redacted_text": "SECRET_KEY=***REDACTED***",
                    "redactions": [
                        {"type": "aws-access-token", "position": 11, "strategy": "mask"}
                    ],
                }
                result = ai_guardian.process_hook_input()

        output = json.loads(result["output"])
        sys_msg = output.get("systemMessage", "")
        assert (
            "redacted" in sys_msg.lower()
        ), f"systemMessage must mention redaction, got: {sys_msg}"


class PostToolUseSecretBlockingUXContractTests(TestCase):
    """
    UX Contract tests documenting the full user experience flow for
    PostToolUse secret detection with redaction disabled.
    """

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_posttooluse_secret_blocked_no_redaction(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Bash output with secret + redaction disabled -> BLOCKED

        Scenario:
        1. User asks Claude: "Show me what's in credentials.txt"
        2. Claude runs: cat credentials.txt
        3. Output contains: SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234
        4. ai-guardian PostToolUse hook runs
        5. Gitleaks detects secret
        6. secret_redaction.enabled = false

        Expected User Experience:
        x Tool output BLOCKED
        User sees: "Secret Detected - aws-access-token"
        Output does NOT reach AI model
        Claude does NOT see the secret value

        MANUAL VERIFICATION:
        1. Configure ai-guardian.json with secret_redaction.enabled = false
        2. Ask Claude to "cat" a file with an AWS key
        3. Verify output is blocked, not shown to Claude
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = ({"enabled": False}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "ux_test_001",
            "tool_input": {"command": "cat credentials.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        assert result["exit_code"] == 0

        response = json.loads(result["output"])

        # CONTRACT: Response MUST block the output
        assert (
            response.get("decision") == "block"
        ), "PostToolUse MUST block output containing secrets when redaction is disabled"

        # CONTRACT: Response MUST include reason
        assert "reason" in response, "Block response must include a reason for the user"
        assert (
            "secret" in response["reason"].lower() or "Secret" in response["reason"]
        ), "Reason should mention secret detection"

        # CONTRACT: Response MUST include hookSpecificOutput
        assert (
            "hookSpecificOutput" in response
        ), "Response must include hookSpecificOutput for Claude Code"
        assert (
            response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        ), "Must identify hook event as PostToolUse"

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_posttooluse_secret_redacted_with_redaction(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Bash output with secret + redaction enabled -> ALLOWED
        with redacted output via updatedToolOutput (#2042).

        Scenario:
        1. User asks Claude: "Show me what's in credentials.txt"
        2. Claude runs: cat credentials.txt
        3. Output contains: SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234
        4. ai-guardian PostToolUse hook runs
        5. Gitleaks detects secret
        6. secret_redaction.enabled = true

        Expected User Experience:
        Tool output is replaced with redacted content via updatedToolOutput
        in object form (Bash: {stdout, stderr, interrupted}).
        Agent sees redacted text as the normal tool result.

        MANUAL VERIFICATION:
        1. Configure ai-guardian.json with secret_redaction.enabled = true
        2. Ask Claude to "cat" a file with an AWS key
        3. Verify output is replaced with redacted content (not blocked)
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        mock_gitleaks.return_value = (True, "Secret Detected - aws-access-token")
        mock_redact.return_value = ({"enabled": True, "action": "warn"}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "ux_test_002",
            "tool_input": {"command": "cat credentials.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            with patch(
                "ai_guardian.scanners.secret_redactor.SecretRedactor"
            ) as MockRedactor:
                mock_instance = MockRedactor.return_value
                mock_instance.redact.return_value = {
                    "redacted_text": "AWS_ACCESS_KEY=***REDACTED***",
                    "redactions": [
                        {"type": "aws-access-token", "position": 16, "strategy": "mask"}
                    ],
                }
                result = ai_guardian.process_hook_input()

        assert result["exit_code"] == 0

        response = json.loads(result["output"])

        # CONTRACT: Response must NOT block — use updatedToolOutput (#2042)
        assert response.get("decision") != "block", (
            "PostToolUse must NOT block when redaction succeeds — "
            f"use updatedToolOutput instead, got: {response}"
        )

        # CONTRACT: Redacted output MUST appear in updatedToolOutput (#2042)
        uto = response.get("hookSpecificOutput", {}).get("updatedToolOutput", {})
        assert isinstance(
            uto, dict
        ), f"Bash updatedToolOutput must be object form, got: {type(uto)}"
        assert "***REDACTED***" in uto.get(
            "stdout", ""
        ), f"updatedToolOutput.stdout must contain redacted output, got: {uto}"


class PostToolUseEnvVarDetectionTests(TestCase):
    """
    End-to-end tests for env var token detection (#1624).

    Verifies that toml-patterns catches env var tokens in PostToolUse
    output without relying on mocked scanners.
    """

    def test_run_secret_scan_detects_jira_api_token(self):
        """
        Toml-patterns env-variable rule catches JIRA_API_TOKEN=base64.
        """
        fake_token = "dGVzdHVzZXJAZXhhbXBsZS5jb206ZmFrZXRva2VuMTIz"
        content = f"JIRA_API_TOKEN={fake_token}"

        result = _run_secret_scan(
            content,
            "Bash_output",
            config={"enabled": True, "engines": ["toml-patterns"]},
            context={"hook_event": "PostToolUse"},
            tool_name="Bash",
        )
        assert result is not None, "run_secret_scan must return a result"
        assert result.detected, "env-variable pattern must detect JIRA_API_TOKEN"

    def test_run_secret_scan_detects_env_output_with_multiple_vars(self):
        """
        Toml-patterns catches JIRA token in multi-line env output.
        """
        content = (
            "JIRA_METHOD=curl\n"
            "JIRA_USERNAME=\n"
            "JIRA_API_TOKEN=dGVzdHVzZXJAZXhhbXBsZS5jb206ZmFrZXRva2VuMTIz\n"
            "JIRA_URL=https://issues.example.com"
        )

        result = _run_secret_scan(
            content,
            "Bash_output",
            config={"enabled": True, "engines": ["toml-patterns"]},
            context={"hook_event": "PostToolUse"},
            tool_name="Bash",
        )
        assert result is not None, "run_secret_scan must return a result"
        assert (
            result.detected
        ), "env-variable pattern must detect JIRA_API_TOKEN in env output"


class GitleaksAllowGuidanceTests(TestCase):
    """
    Tests verifying that gitleaks:allow guidance tells users to put the
    comment inline (at the end of the line), not before the line.

    Issue #416: gitleaks only recognizes # gitleaks:allow when it appears
    on the SAME line as the secret, not on a preceding line.
    """

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.scanners.secret_scanning.check_secrets")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_block_message_says_end_of_line(
        self, mock_pattern, mock_scan, mock_gitleaks, mock_redact, mock_pii
    ):
        """
        USER EXPERIENCE: Block message must NOT include bypass hints (Issue #897)

        Remediation tips (gitleaks:allow, config paths) belong in the
        violation log only, not in the hook response seen by the AI agent.
        """
        mock_pattern.return_value = (None, None)
        mock_scan.return_value = ({"enabled": True, "engines": ["gitleaks"]}, None)
        error_no_hints = (
            "Secret Detected\n"
            "Recommendation:\n"
            "  • Move secrets to environment variables\n"
            "  • Never commit secrets to git\n"
        )
        mock_gitleaks.return_value = (True, error_no_hints)
        mock_redact.return_value = ({"enabled": False}, None)
        mock_pii.return_value = (None, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "guidance_test_001",
            "tool_input": {"command": "cat /tmp/test.txt"},
            "tool_response": {"output": "SECRET_KEY=FAKE_TEST_SECRET_VALUE_1234"},
        }

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        response = json.loads(result["output"])
        reason = response.get("reason", "")

        assert (
            "gitleaks:allow" not in reason
        ), f"Block message must NOT include gitleaks:allow bypass hint, got: {reason}"
        assert (
            "secret_scanning.enabled" not in reason
        ), f"Block message must NOT expose config section paths, got: {reason}"

    def test_check_secrets_error_message_no_bypass_hints(self):
        """
        USER EXPERIENCE: _build_secret_detected_message must NOT include bypass tips (Issue #897)

        Bypass hints (gitleaks:allow, config paths) belong in the violation log,
        not in the hook response that the AI agent sees.
        """
        from ai_guardian.hook_processing import _build_secret_detected_message

        details = {"rule_id": "aws-key", "file": "test.py", "line_number": 1}
        msg = _build_secret_detected_message("gitleaks", details, "built-in")

        assert (
            "gitleaks:allow" not in msg
        ), "_build_secret_detected_message must NOT include gitleaks:allow bypass hint"
        assert (
            "secret_scanning.enabled" not in msg
        ), "_build_secret_detected_message must NOT expose config section paths"

    def test_tui_violations_gitleaks_allow_guidance(self):
        """
        USER EXPERIENCE: TUI violations secret allowlisting says "inline" / "at the end"

        Issue #416: The TUI said "Add comment before the line" which is wrong.
        Must say "Add inline comment at the end of the line" with an example
        showing the comment on the same line as the secret.

        The guidance text lives in the shared violation_guidance module
        which the TUI imports and delegates to.
        """
        import inspect
        from ai_guardian.violations import guidance as violation_guidance

        source = inspect.getsource(violation_guidance)

        assert (
            "before the line" not in source
        ), "violation guidance must NOT say 'before the line' for gitleaks:allow"
        assert (
            "inline comment at the end of the line" in source
        ), "violation guidance must say 'inline comment at the end of the line'"
        assert (
            "YOUR_SECRET_LINE # gitleaks:allow" in source
        ), "violation guidance must show inline example: YOUR_SECRET_LINE # gitleaks:allow"
