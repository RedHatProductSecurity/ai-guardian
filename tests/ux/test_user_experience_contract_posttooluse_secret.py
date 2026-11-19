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

import pytest

import ai_guardian
from ai_guardian.hook_events.scanners import run_secret_scan as _run_secret_scan
from ai_guardian.scanners.secret_redactor import SecretRedactor
from tests.fixtures.nuget_sonar_tokens import CREDENTIAL_CASES
from tests.fixtures.research_secret_tokens import (
    CREDENTIAL_CASES as RESEARCH_CREDENTIAL_CASES,
)


@pytest.mark.parametrize("tool_name", ["webfetch", "WebFetch"])
@pytest.mark.parametrize("safe_location", [True, False])
@pytest.mark.parametrize("correlated", [True, False])
def test_fetched_response_history_has_private_safe_source(
    tmp_path, monkeypatch, tool_name, safe_location, correlated
):
    """USER EXPERIENCE: fetched sensitive content → redacted output and safe URL.

    Manual verification with an isolated project and synthetic custom rule:
    1. Ask an agent to fetch a page containing the synthetic rule's value.
    2. Verify the value is replaced in the agent-visible tool response.
    3. Open both history records: Source URL identifies the request, not a file.
    4. Response line/columns refer to the converted response, not the original page.
    5. Userinfo, query, and fragment values never appear in history or its copies.
       An unsafe path leaves only Tool output context; no URL is invented.
    """
    from ai_guardian.hook_processing import (
        _ensure_hook_events_imported,
        _process_hook_data,
    )
    from ai_guardian.violations.logger import ViolationLogger

    _ensure_hook_events_imported()
    private_value = "LOCATOR_FIXTURE_" + "A1B2C3D4E5F6G7H8"
    pattern = r"LOCATOR_FIXTURE_[A-Z0-9]{16}"
    history = ViolationLogger(
        log_path=tmp_path / "history.jsonl", config={"enabled": True}
    )
    monkeypatch.setattr(
        "ai_guardian.hook_processing._handle_bootstrap_scan", lambda *_a, **_k: None
    )
    for target in (
        "ai_guardian.hook_processing.ViolationLogger",
        "ai_guardian.violations.logger.ViolationLogger",
    ):
        monkeypatch.setattr(target, lambda **_kwargs: history)
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning._load_pattern_server_config", lambda: None
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: (
            {
                "enabled": True,
                "engines": ["toml-patterns"],
                "additional_patterns": [
                    {"id": "locator-fixture", "match_type": "regex", "regex": pattern}
                ],
            },
            None,
        ),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_redaction_config",
        lambda: (
            {
                "enabled": True,
                "action": "warn",
                "additional_patterns": [
                    {
                        "pattern": pattern,
                        "type": "synthetic-locator-value",
                        "strategy": "full_redact",
                    }
                ],
            },
            None,
        ),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_pii_config", lambda: (None, None)
    )
    monkeypatch.setattr(
        "ai_guardian.scanners.password_likelihood.run_password_likelihood_scan",
        lambda _content: None,
    )
    monkeypatch.setattr(
        "ai_guardian.tools.policy.ToolPolicyChecker.check_tool_allowed",
        lambda *_a, **_k: (True, None, tool_name),
    )
    source_url = "https://example.test/docs/page"
    request_url = (
        "https://user:private-userinfo@example.test/docs/page?key=private-query#private-fragment"
        if safe_location
        else source_url + "/password/private-path"
    )
    shared = {
        "hook_source": "opencode",
        "opencode_version": "2.0.24",
        "tool_name": tool_name,
        "tool_use_id": "call_locator",
        "session_id": "locator-session",
    }
    if correlated:
        before = _process_hook_data(
            {
                **shared,
                "hook_event_name": "tool.execute.before",
                "tool_input": {"url": request_url},
            }
        )
        assert before.get("_blocked") is not True
    result = _process_hook_data(
        {
            **shared,
            "hook_event_name": "tool.execute.after",
            "hook_source": "opencode",
            "opencode_version": "2.0.24",
            "tool_name": tool_name,
            "tool_input": {} if correlated else {"url": request_url},
            "tool_response": {"output": "# Converted response\n" + private_value},
        }
    )
    assert private_value not in result["output"]
    assert result.get("_blocked") is not True
    records = history.get_recent_violations()
    assert {r["violation_type"] for r in records} == {
        "sensitive_finding",
        "secret_redaction",
    }
    assert all(r["action_taken"] == "allow" for r in records)
    assert all(r["redaction_status"] == "redacted" for r in records)
    for record in records:
        blocked = record["blocked"]
        assert blocked.get("source_url") == (source_url if safe_location else None)
        assert blocked["source_context"] == "tool_output"
        assert not blocked.get("file_path")
        assert blocked["line_number"] == 2
        assert blocked["start_column"] == 0
        assert blocked["end_column"] == len(private_value)
    serialized = json.dumps(records)
    assert private_value not in serialized
    assert "private-" not in serialized
    assert "webfetch_output" not in serialized


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
            filename="Bash_output",
            config={"enabled": True, "engines": ["toml-patterns"]},
            secret_context={"hook_event": "PostToolUse"},
            tool_name="Bash",
        )
        assert result is not None, "run_secret_scan must return a result"
        assert result.detected, "env-variable pattern must detect JIRA_API_TOKEN"

    def test_run_secret_scan_detects_issue_2323_resend_api_key(self):
        """
        USER EXPERIENCE: Resend API key in tool output -> secret scan detects it.

        This contract verifies that the new bundled credential pattern reaches
        the PostToolUse scanning path, where the normal secret handling flow
        protects the tool output from reaching the AI agent.
        """
        fake_token = "re_" + "a1B2c3D4" * 3
        content = f"RESEND_API_KEY={fake_token}"

        result = _run_secret_scan(
            content,
            filename="Bash_output",
            config={"enabled": True, "engines": ["toml-patterns"]},
            secret_context={"hook_event": "PostToolUse"},
            tool_name="Bash",
        )
        assert result is not None, "run_secret_scan must return a result"
        assert result.detected, "resend-api-key pattern must detect the API key"
        assert result.should_block, "detected secret output must remain protected"

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
            filename="Bash_output",
            config={"enabled": True, "engines": ["toml-patterns"]},
            secret_context={"hook_event": "PostToolUse"},
            tool_name="Bash",
        )
        assert result is not None, "run_secret_scan must return a result"
        assert (
            result.detected
        ), "env-variable pattern must detect JIRA_API_TOKEN in env output"

    def test_run_secret_scan_allows_lifecycle_metadata_assignments(self):
        """USER EXPERIENCE: lifecycle paths and timestamps pass through cleanly."""
        content = (
            "++ _LIFECYCLE_DIR=/service-lifecycle\n"
            "++ _INIT_START_NS=1234567890123456789"
        )

        result = _run_secret_scan(
            content,
            filename="Bash_output",
            config={"enabled": True, "engines": ["toml-patterns"]},
            secret_context={"hook_event": "PostToolUse"},
            tool_name="Bash",
        )

        assert result is None or not result.detected


class TestStandaloneNugetSonarCredentials:
    """USER EXPERIENCE: standalone publishing/analysis tokens remain protected (#2558).

    Manual verification in an isolated test project:
    1. Use the bundled engine and synthetic fixtures, never issued credentials.
    2. Ask the agent to write a fixture to a text file: the write is denied.
    3. Print a fixture from a tool: normal output redaction masks its value.
    4. Prefix-only documentation and environment-variable references remain usable.

    The scanner runner and redactor below are real; configuration is explicit
    and the pattern-server loader is mocked so no user config or network is used.
    """

    @pytest.mark.parametrize(
        "rule_id,description,token",
        CREDENTIAL_CASES,
        ids=[c[0] for c in CREDENTIAL_CASES],
    )
    @pytest.mark.parametrize(
        "event,tool", (("PreToolUse", "Write"), ("PostToolUse", "Bash"))
    )
    @patch(
        "ai_guardian.scanners.secret_scanning._load_pattern_server_config",
        return_value=None,
    )
    def test_standalone_value_is_detected_and_blocked(
        self, mock_pattern, rule_id, description, token, event, tool
    ):
        """A bare token, without assignment context, must trigger secret protection."""
        result = _run_secret_scan(
            token,
            filename="credential-output.txt",
            config={"enabled": True, "engines": ["toml-patterns"]},
            secret_context={"hook_event": event},
            tool_name=tool,
        )
        assert result is not None
        assert result.detected
        assert result.should_block
        assert "Secret Detected" in result.error_message
        assert "Scanner: toml-patterns" in result.error_message
        assert token not in result.error_message
        assert any(f["rule_id"] == rule_id for f in result.findings)

    @pytest.mark.parametrize(
        "rule_id,description,token",
        CREDENTIAL_CASES,
        ids=[c[0] for c in CREDENTIAL_CASES],
    )
    def test_posttooluse_redaction_preserves_surrounding_output(
        self, rule_id, description, token
    ):
        """The agent sees masked output with useful attribution, not the credential."""
        redactor = SecretRedactor(
            config={"enabled": True, "log_redactions": False},
            pii_config={"enabled": False},
        )
        output = f'Build output:\n  "{token}"\nFinished.'
        result = redactor.redact(output)
        assert (
            result["redacted_text"]
            == f'Build output:\n  "{token[:6]}...{token[-4:]}"\nFinished.'
        )
        assert token not in result["redacted_text"]
        assert result["redactions"][0]["type"] == description


class TestStandaloneResearchCredentials:
    """USER EXPERIENCE: #2632 credential-shaped values remain protected.

    A standalone synthetic candidate in a tool request is denied, while the same
    candidate in tool output is redacted before the AI agent receives it. Manual
    verification uses only generated values and the bundled TOML engine; no live
    credentials, scanner binaries, user configuration, or network are involved.
    """

    @pytest.mark.parametrize(
        "rule_id,description,token",
        RESEARCH_CREDENTIAL_CASES,
        ids=[case[0] for case in RESEARCH_CREDENTIAL_CASES],
    )
    @pytest.mark.parametrize(
        "event,tool", (("PreToolUse", "Write"), ("PostToolUse", "Bash"))
    )
    @patch(
        "ai_guardian.scanners.secret_scanning._load_pattern_server_config",
        return_value=None,
    )
    def test_standalone_value_is_detected_and_blocked(
        self, mock_pattern, rule_id, description, token, event, tool
    ):
        result = _run_secret_scan(
            token,
            filename="credential-output.txt",
            config={"enabled": True, "engines": ["toml-patterns"]},
            secret_context={"hook_event": event},
            tool_name=tool,
        )

        assert result is not None
        assert result.detected
        assert result.should_block
        assert "Secret Detected" in result.error_message
        assert "Scanner: toml-patterns" in result.error_message
        assert token not in result.error_message
        assert any(finding["rule_id"] == rule_id for finding in result.findings)

    @pytest.mark.parametrize(
        "rule_id,description,token",
        RESEARCH_CREDENTIAL_CASES,
        ids=[case[0] for case in RESEARCH_CREDENTIAL_CASES],
    )
    def test_posttooluse_redaction_masks_value_and_preserves_context(
        self, rule_id, description, token
    ):
        redactor = SecretRedactor(
            config={"enabled": True, "log_redactions": False},
            pii_config={"enabled": False},
        )
        output = f"Build output:\n  {token}\nFinished."

        result = redactor.redact(output)

        assert result["redacted_text"] == (
            f"Build output:\n  {token[:6]}...{token[-4:]}\nFinished."
        )
        assert token not in result["redacted_text"]
        assert result["redactions"][0]["type"] == description


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

    def test_web_violations_gitleaks_allow_guidance(self):
        """
        USER EXPERIENCE: Web Console violations secret allowlisting says "inline" / "at the end"

        Issue #416: The old console said "Add comment before the line" which is wrong.
        Must say "Add inline comment at the end of the line" with an example
        showing the comment on the same line as the secret.

        The guidance text lives in the shared violation_guidance module
        which the Web Console imports and delegates to.
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
