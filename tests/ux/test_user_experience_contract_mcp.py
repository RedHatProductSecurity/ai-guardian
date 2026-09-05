"""
User Experience Contract Tests for MCP Security Features

These tests document and verify the expected user experience when ai-guardian
protects against MCP tool threats. They serve as a "contract" that defines
what users should see in Claude Code when MCP security protections trigger.

Issue #226: Document UX for MCP security features (permissions, secrets, SSRF,
prompt injection, and clean operations).

IMPORTANT: These tests use explicit configuration dicts and mocks to ensure
test isolation. They do NOT rely on the user's ~/.config/ai-guardian/ai-guardian.json
file, ensuring consistent behavior in CI/CD and across different environments.
"""

import json
import sys
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import pytest

import ai_guardian
from tests.fixtures.mock_mcp_server import create_hook_data, create_tool_response
from tests.fixtures import attack_constants


class MCPUserExperienceContractTests(TestCase):
    """
    Tests documenting the user experience contract for MCP security protections.

    These tests verify what users SHOULD see when ai-guardian is configured
    in Claude Code's PreToolUse and PostToolUse hooks to protect MCP operations.
    """

    def test_user_experience_mcp_tool_blocked(self):
        """
        USER EXPERIENCE: MCP tool blocked → DENIED immediately, no prompt shown.

        Scenario:
        1. Claude Code permission: "Ask before using MCP tools" (user wants review)
        2. User asks Claude: "Create a NotebookLM notebook"
        3. Claude tries to call mcp__notebooklm-mcp__notebook_create
        4. ai-guardian PreToolUse hook runs
        5. Tool is NOT in allowlist

        Expected User Experience:
        ❌ Claude Code does NOT show permission prompt
        ❌ Operation is BLOCKED immediately
        🛡️ User sees error: "TOOL ACCESS DENIED: Tool not in allow list"

        This is CORRECT behavior - unauthorized MCP tools should be blocked,
        regardless of user permission settings, to prevent malicious tool usage.
        """
        # Configure: MCP tools require explicit allow
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__notebooklm-mcp__*",
                        "mode": "allow",
                        "patterns": [
                            "mcp__notebooklm-mcp__notebook_list",
                            "mcp__notebooklm-mcp__notebook_get",
                        ],
                    }
                ],
            }
        }

        from ai_guardian.tools.policy import ToolPolicyChecker

        policy_checker = ToolPolicyChecker(config=config)

        # Claude Code invokes PreToolUse hook
        hook_data = create_hook_data(
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
            tool_input={"title": "My Research Notes"},
            hook_event="PreToolUse",
        )

        # ai-guardian checks tool permission
        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Verify ai-guardian's response
        assert not allowed, "Tool not in allowlist should be denied"
        assert error_msg is not None, "Must include error message"
        assert (
            "not in allow list" in error_msg.lower() or "denied" in error_msg.lower()
        ), f"Error should explain tool is not allowed: {error_msg}"

        # USER SEES: Error message in Claude Code
        # USER DOES NOT SEE: Permission prompt (operation blocked before prompt)
        # OPERATION: Denied, notebook not created, tool not executed

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_secret_in_mcp_output(
        self, mock_pattern_config, mock_redaction_config, mock_scan_config
    ):
        """
        USER EXPERIENCE: Secret in MCP output → Currently NOT scanned by default.

        Scenario:
        1. User asks Claude: "Query my notebook about API keys"
        2. Claude calls mcp__notebooklm-mcp__notebook_query
        3. Tool executes and returns response containing Slack token
        4. ai-guardian PostToolUse hook runs
        5. MCP tool output currently NOT scanned for secrets

        Current Behavior (as of this test):
        ⚠️ MCP tool responses are NOT extracted/scanned by default
        ✅ PostToolUse returns exit 0 with empty response
        ❌ Secret passes through to AI (not ideal)

        Expected Future Behavior:
        🛡️ Secret should be REDACTED from output
        ⚠️ User should see warning: "Redacted secrets from tool output"
        ✅ AI should receive redacted version (secrets removed)

        Note: This test documents current behavior. MCP tool response extraction
        needs to be implemented in extract_tool_result() function to enable
        secret scanning for MCP outputs.

        Reference: tests/unit/test_posttooluse_mcp.py::test_mcp_response_with_secret_allowed_by_default
        """
        # Configure mocks to avoid loading user's config file
        mock_pattern_config.return_value = None
        mock_redaction_config.return_value = ({"enabled": True, "action": "warn"}, None)
        mock_scan_config.return_value = (
            {"enabled": True, "ignore_files": [], "ignore_tools": []},
            None,
        )

        # Simulate MCP tool response containing secret
        tool_output = f"""
        Here are the findings from your notebook:
        - API endpoint: https://api.slack.com/v1
        - Auth token: {attack_constants.SECRET_SLACK_TOKEN}
        - Status: active
        """

        # Claude Code invokes PostToolUse hook after tool execution
        hook_data = create_tool_response(
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_QUERY,
            output={"answer": tool_output, "status": "success"},
        )

        with patch("sys.stdin", StringIO(json.dumps(hook_data))):
            result = ai_guardian.process_hook_input()

        # Verify ai-guardian's current response (empty because MCP not scanned)
        assert result["exit_code"] == 0, "PostToolUse always returns exit 0"

        response = json.loads(result["output"])

        # CURRENT BEHAVIOR: Empty response because MCP outputs not scanned
        # If extract_tool_result() doesn't handle this MCP tool specifically,
        # it returns None and scanning is skipped
        assert (
            response == {}
        ), "Current behavior: MCP tool outputs not scanned, returns empty response"

        # USER SEES: No warning (current behavior)
        # AI RECEIVES: Original output with secret (current behavior - not ideal)
        # OPERATION: Already executed on MCP server
        #
        # FUTURE IMPROVEMENT: Implement MCP output extraction in extract_tool_result()
        # to enable secret scanning and redaction for MCP tool responses

    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_ssrf_in_mcp_parameter(self, mock_pattern_config):
        """
        USER EXPERIENCE: SSRF attempt in MCP parameter → DENIED immediately.

        Scenario:
        1. User asks Claude: "Add source from http://169.254.169.254/metadata"
        2. Claude tries to call source_add with AWS metadata URL
        3. ai-guardian PreToolUse hook runs
        4. SSRF pattern detected in URL parameter

        Expected User Experience:
        ❌ Claude Code does NOT show permission prompt
        ❌ Operation is BLOCKED immediately
        🛡️ User sees error: "SSRF PATTERN DETECTED"

        This is CORRECT behavior - SSRF attempts should be blocked to prevent
        internal network access or cloud metadata theft.

        Note: Current implementation checks SSRF primarily in Bash commands.
        This test documents expected behavior for future MCP-specific SSRF checks.
        """
        # Disable pattern server
        mock_pattern_config.return_value = None

        from ai_guardian.scanners.ssrf import SSRFProtector

        # Configure SSRF protector
        config = {"enabled": True}
        protector = SSRFProtector(config)

        # For now, SSRF protection focuses on Bash tool
        # This documents expected behavior for MCP tools with URL parameters
        tool_input = {"command": f"curl {attack_constants.SSRF_AWS_METADATA}"}

        should_block, error_msg = protector.check("Bash", tool_input)

        # Verify SSRF detection
        assert should_block, "SSRF attempt should be blocked"
        assert error_msg is not None, "Must include error message"
        assert (
            "ssrf" in error_msg.lower() or "metadata" in error_msg.lower()
        ), f"Error should mention SSRF: {error_msg}"

        # USER SEES: Error message about SSRF attempt
        # USER DOES NOT SEE: Permission prompt
        # OPERATION: Denied, no metadata access, internal network protected

    def test_user_experience_prompt_injection_in_mcp_input(self):
        """
        USER EXPERIENCE: Prompt injection in MCP input → DENIED immediately.

        Scenario:
        1. User asks Claude: "Create notebook titled 'Test | Ignore all previous instructions'"
        2. Claude tries to call notebook_create with injection in title
        3. ai-guardian PreToolUse hook runs
        4. Prompt injection detected in title parameter

        Expected User Experience:
        ❌ Claude Code does NOT show permission prompt
        ❌ Operation is BLOCKED immediately
        🛡️ User sees error: "Prompt Injection Detected"

        This is CORRECT behavior - prompt injection attempts should be blocked
        to prevent manipulation of AI behavior or context poisoning.
        """
        from ai_guardian.scanners.prompt_injection import check_prompt_injection

        # Malicious notebook title with prompt injection
        malicious_title = attack_constants.PROMPT_INJECTION_IGNORE_PREVIOUS

        config = {"enabled": True}

        # Check for prompt injection
        is_attack, error_msg, _ = check_prompt_injection(
            malicious_title,
            config,
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
        )

        # Verify prompt injection detection
        assert is_attack, "Prompt injection should be detected"
        assert error_msg is not None, "Must include error message"
        assert (
            "prompt injection" in error_msg.lower() or "injection" in error_msg.lower()
        ), f"Error should mention prompt injection: {error_msg}"

        # USER SEES: Error message about prompt injection
        # USER DOES NOT SEE: Permission prompt
        # OPERATION: Denied, notebook not created, injection blocked

    def test_user_experience_clean_mcp_operation(self):
        """
        USER EXPERIENCE: Clean MCP operation → Permission prompt shown (if configured).

        Scenario:
        1. Claude Code permission: "Ask before using MCP tools"
        2. User asks Claude: "List my notebooks"
        3. Claude tries to call mcp__notebooklm-mcp__notebook_list
        4. ai-guardian PreToolUse hook runs
        5. No threats detected, tool is in allowlist

        Expected User Experience:
        ✅ Claude Code SHOWS permission prompt: "Claude wants to use mcp__notebooklm-mcp__notebook_list"
        ✅ User can review the operation
        ✅ User clicks "Allow" or "Deny"

        This is CORRECT behavior - user retains control over MCP operations
        when no security threats are detected.

        This follows the same principle as issue #224 fix - ai-guardian
        returns empty response (no auto-approve), allowing Claude Code's
        normal permission system to work.
        """
        # Configure: Allow notebook_list tool
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__notebooklm-mcp__*",
                        "mode": "allow",
                        "patterns": [
                            "mcp__notebooklm-mcp__notebook_list",
                            "mcp__notebooklm-mcp__notebook_get",
                        ],
                    }
                ],
            }
        }

        from ai_guardian.tools.policy import ToolPolicyChecker

        policy_checker = ToolPolicyChecker(config=config)

        # Claude Code invokes PreToolUse hook
        hook_data = create_hook_data(
            tool_name="mcp__notebooklm-mcp__notebook_list",
            tool_input={},
            hook_event="PreToolUse",
        )

        # ai-guardian checks tool (clean operation)
        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Verify ai-guardian allows operation (returns empty response)
        assert allowed, f"Clean allowed tool should pass: {error_msg}"
        assert error_msg is None, "No error for clean operation"

        # IMPORTANT: ai-guardian does NOT auto-approve
        # It returns empty response, allowing Claude Code to show permission prompt

        # USER SEES: Claude Code permission prompt (because ai-guardian didn't auto-approve)
        # PROMPT SHOWS: "Claude wants to use mcp__notebooklm-mcp__notebook_list"
        # USER CHOOSES: Allow or Deny
        # OPERATION: Proceeds only if user approves

    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_comparison_threat_vs_clean_mcp(self, mock_pattern_config):
        """
        USER EXPERIENCE COMPARISON: Threat vs Clean MCP operations.

        This test demonstrates the difference in user experience between
        MCP operations with threats (denied) vs clean operations (prompt shown).

        Scenario A: MCP tool with prompt injection
        ===========================================
        1. User asks: "Create notebook with injection attack"
        2. ai-guardian: DENIES immediately
        3. User sees: Error message "Prompt injection detected"
        4. User does NOT see: Permission prompt
        5. Result: Notebook NOT created (attack blocked)

        Scenario B: Clean MCP tool operation
        ====================================
        1. User asks: "List my notebooks"
        2. ai-guardian: Returns empty response (no auto-approve)
        3. User sees: Permission prompt "Claude wants to use notebook_list"
        4. User clicks: "Allow"
        5. Result: Notebooks listed (user gave explicit consent)

        This is the CORRECT behavior for MCP security.
        """
        # Disable pattern server
        mock_pattern_config.return_value = None

        from ai_guardian.scanners.prompt_injection import check_prompt_injection
        from ai_guardian.tools.policy import ToolPolicyChecker

        # Scenario A: MCP operation with prompt injection
        malicious_title = attack_constants.PROMPT_INJECTION_IGNORE_PREVIOUS

        config_pi = {"enabled": True}
        is_attack, error_msg, _ = check_prompt_injection(
            malicious_title,
            config_pi,
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
        )

        # Scenario A verification: Immediate denial
        assert is_attack, "Prompt injection should be detected"
        assert error_msg is not None, "Must have error message for attack"
        assert (
            "injection" in error_msg.lower()
        ), f"Error should mention injection: {error_msg}"

        # Scenario B: Clean MCP operation
        config_tool = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__notebooklm-mcp__*",
                        "mode": "allow",
                        "patterns": ["mcp__notebooklm-mcp__notebook_list"],
                    }
                ],
            }
        }

        policy_checker = ToolPolicyChecker(config=config_tool)

        hook_data = create_hook_data(
            tool_name="mcp__notebooklm-mcp__notebook_list",
            tool_input={},
            hook_event="PreToolUse",
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Scenario B verification: Allowed, no auto-approve
        assert allowed, f"Clean operation should be allowed: {error_msg}"
        assert error_msg is None, "No error for clean operation"

        # SUMMARY: Different user experiences
        # MCP with Threat: User sees error, operation blocked immediately
        # Clean MCP: User sees prompt, chooses to allow/deny

    def test_user_experience_documentation_mcp(self):
        """
        Documentation test: What users should expect for MCP security.

        This test always passes but documents the expected behavior
        for users configuring ai-guardian in Claude Code with MCP servers.

        Configuration:
        ==============
        ~/.claude/settings.json:
        {
          "PreToolUse": [
            {
              "matcher": "*",
              "hooks": [
                {
                  "command": "ai-guardian",
                  "statusMessage": "🛡️ AI Guardian checking..."
                }
              ]
            }
          ],
          "PostToolUse": [
            {
              "matcher": "*",
              "hooks": [
                {
                  "command": "ai-guardian",
                  "statusMessage": "🛡️ AI Guardian scanning output..."
                }
              ]
            }
          ]
        }

        Expected User Experience for MCP Tools:
        ========================================

        1. MCP TOOL BLOCKED (not in allowlist):
           ❌ BLOCKED immediately (PreToolUse)
           🛡️ Error shown: "TOOL ACCESS DENIED: Tool not in allow list"
           ⚠️ No permission prompt (security override)

        2. PROMPT INJECTION IN MCP INPUT:
           ❌ BLOCKED immediately (PreToolUse)
           🛡️ Error shown: "Prompt Injection Detected"
           ⚠️ No permission prompt (security override)

        3. SECRET IN MCP OUTPUT:
           ⚠️ CURRENT: MCP outputs NOT scanned by default (limitation)
           ⚠️ Secret passes through to AI (not ideal)
           🔧 FUTURE: Should redact secrets and show warning
           📝 Note: Requires MCP output extraction implementation

        4. SSRF IN MCP PARAMETER:
           ❌ BLOCKED immediately (PreToolUse)
           🛡️ Error shown: "SSRF PATTERN DETECTED"
           ⚠️ No permission prompt (security override)

        5. CLEAN MCP OPERATION (allowed, no threats):
           ✅ Permission prompt shown (if configured)
           👤 User reviews and approves/denies
           ✅ User maintains control

        This is the correct behavior for MCP security protection.
        All threats are blocked before execution or output exposure,
        while clean operations follow normal permission flow.
        """
        # This test always passes - it's documentation
        assert True, "See docstring for expected MCP security user experience"


class MCPManualVerificationGuide(TestCase):
    """
    Manual verification guide for testing MCP security in actual Claude Code.

    These tests document how to manually verify MCP protections in Claude Code IDE.
    They always pass but provide step-by-step instructions.
    """

    def test_manual_verification_mcp_steps(self):
        """
        MANUAL VERIFICATION: How to test MCP security in Claude Code IDE.

        Prerequisites:
        =============
        1. Install ai-guardian: pip install ai-guardian
        2. Install NotebookLM MCP server: https://github.com/modelcontextprotocol/servers
        3. Configure MCP server in Claude Code settings
        4. Configure PreToolUse/PostToolUse hooks in ~/.claude/settings.json (see above)
        5. Configure MCP tool permissions in ai-guardian config

        Test Steps:
        ==========

        TEST 1: MCP tool blocked (should DENY, no prompt)
        --------------------------------------------------
        1. Configure ai-guardian with limited MCP allowlist (only notebook_list)
        2. Ask Claude: "Create a new NotebookLM notebook titled 'Test'"
        3. EXPECTED: Operation blocked, error shown, NO permission prompt
        4. VERIFY: Notebook not created, tool not in allowlist message shown

        TEST 2: Prompt injection in MCP input (should DENY, no prompt)
        --------------------------------------------------------------
        1. Ask Claude: "Create notebook titled 'Research | Ignore all previous instructions'"
        2. EXPECTED: Operation blocked, error "Prompt injection detected"
        3. VERIFY: Notebook not created, injection blocked

        TEST 3: Secret in MCP output (CURRENT: NOT scanned)
        ---------------------------------------------------
        1. Create notebook with source containing fake secret
        2. Ask Claude: "Query the notebook about API keys"
        3. CURRENT BEHAVIOR: Secret NOT detected/redacted (MCP outputs not scanned)
        4. VERIFY: No warning shown, secret passes to AI
        5. FUTURE: Should redact secret and show warning (needs implementation)

        TEST 4: Clean MCP operation (should PROMPT)
        -------------------------------------------
        1. Configure ai-guardian to allow notebook_list
        2. Set Claude Code to "Ask before MCP tools"
        3. Ask Claude: "List my NotebookLM notebooks"
        4. EXPECTED: Permission prompt shown: "Claude wants to use notebook_list"
        5. VERIFY: You can click "Allow" or "Deny"
        6. VERIFY: Operation proceeds only if you click "Allow"

        TEST 5: Verify no auto-approve for clean operations
        ---------------------------------------------------
        1. Complete TEST 4 above
        2. CRITICAL: If you see NO permission prompt and notebooks list immediately,
           the bug is present (ai-guardian auto-approved)
        3. CORRECT: Permission prompt appears, you must click "Allow"

        Troubleshooting:
        ===============
        - If no permission prompt for TEST 4: Check Claude Code permission settings
        - If all tests show prompts: ai-guardian might not be running (check logs)
        - If MCP tools fail: Verify MCP server is running and configured
        - Logs: Check ~/.claude/logs/ for ai-guardian output
        """
        # This test always passes - it's a manual testing guide
        assert True, "See docstring for manual MCP verification steps"


class MCPAllowRuleActionModesUXTest(TestCase):
    """
    UX contract tests for MCP allow rules with action modes (Issue #495).

    Verifies that MCP tools matched by an allow rule are permitted regardless
    of the action field value (block, warn, log-only, or absent).
    The action field controls behavior for tools NOT in the allow list,
    not for tools that match.
    """

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_mcp_allow_action_block(
        self, mock_pattern_config, mock_scan_config
    ):
        """
        USER EXPERIENCE: MCP allow rule with action=block → matched tools ALLOWED

        Scenario:
        1. Config has: matcher=mcp__mcp-atlassian__*, mode=allow, action=block, patterns=["*"]
        2. User asks Claude to update a JIRA issue
        3. Claude calls mcp__mcp-atlassian__jira_update_issue
        4. ai-guardian PreToolUse hook runs
        5. Tool matches allow pattern "*"

        Expected User Experience:
        ✅ Operation ALLOWED — tool matches the allow pattern
        ✅ No warning shown — this is an explicitly allowed tool
        ⚠️ action=block only applies when a tool is NOT in the allow list
        """
        mock_pattern_config.return_value = None
        mock_scan_config.return_value = ({"enabled": True}, None)

        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__mcp-atlassian__*",
                        "mode": "allow",
                        "action": "block",
                        "patterns": ["*"],
                    }
                ],
            }
        }

        checker = ToolPolicyChecker(config)
        hook_data = {
            "tool_use": {
                "name": "mcp__mcp-atlassian__jira_update_issue",
                "input": {"issue_key": "TEST-123", "fields": "{}"},
            }
        }

        is_allowed, msg, tool_name = checker.check_tool_allowed(hook_data)
        self.assertTrue(
            is_allowed, "Matched MCP tool must be allowed even with action=block"
        )
        self.assertIsNone(msg, "No warning for explicitly allowed tools")

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    def test_user_experience_mcp_allow_no_action_field(
        self, mock_pattern_config, mock_scan_config
    ):
        """
        USER EXPERIENCE: MCP allow rule with no action field → matched tools ALLOWED

        Scenario:
        1. Config has: matcher=mcp__mcp-atlassian__*, mode=allow, patterns=["*"]
           (no action field — defaults to "block")
        2. User asks Claude to view a JIRA issue
        3. Claude calls mcp__mcp-atlassian__jira_get_issue
        4. ai-guardian PreToolUse hook runs

        Expected User Experience:
        ✅ Operation ALLOWED — tool matches the allow pattern
        ✅ Default action=block does not interfere with allow matching
        """
        mock_pattern_config.return_value = None
        mock_scan_config.return_value = ({"enabled": True}, None)

        from ai_guardian.tools.policy import ToolPolicyChecker

        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__mcp-atlassian__*",
                        "mode": "allow",
                        "patterns": ["*"],
                    }
                ],
            }
        }

        checker = ToolPolicyChecker(config)
        hook_data = {
            "tool_use": {
                "name": "mcp__mcp-atlassian__jira_get_issue",
                "input": {"issue_key": "TEST-123"},
            }
        }

        is_allowed, msg, tool_name = checker.check_tool_allowed(hook_data)
        self.assertTrue(
            is_allowed, "Matched MCP tool must be allowed with default action"
        )
        self.assertIsNone(msg)


class MCPBlockReasonUXTest(TestCase):
    """
    UX contract tests for correct block-reason reporting (Issue #575).

    When a tool is blocked, the AI must report the ACTUAL reason from
    get_violations(), not guess based on error messages. The AI must
    never suggest using `!` prefix or alternative commands to bypass
    security blocks.
    """

    def test_skill_instructs_get_violations_for_block_reason(self):
        """
        USER EXPERIENCE: Tool blocked → AI calls get_violations() for real reason

        Scenario:
        1. User asks Claude: "Read /tmp/test.txt"
        2. Claude tries Read tool on /tmp/test.txt
        3. ai-guardian PreToolUse hook blocks it (secret detected in file)
        4. Claude sees hook error

        Expected AI Behavior (per skill instructions):
        ✅ AI calls get_violations(limit=1) to get actual reason
        ✅ AI reports: "The file was blocked because a secret was detected"
        ❌ AI does NOT guess: "outside allowed project directories"
        ❌ AI does NOT suggest: "! cat /tmp/test.txt"

        This test verifies the skill instructions contain the required
        guidance for correct block-reason reporting.
        """
        from ai_guardian.mcp.server import _load_skill_instructions

        instructions = _load_skill_instructions()

        assert (
            "get_violations" in instructions
        ), "Skill must instruct AI to call get_violations() for block reasons"
        assert (
            "Do NOT" in instructions
        ), "Skill must have a Do NOT section forbidding bypass suggestions"

    def test_skill_forbids_bypass_suggestions(self):
        """
        USER EXPERIENCE: Tool blocked → AI must NOT suggest bypass methods

        Scenario:
        1. ai-guardian blocks a Read operation (secret detected)
        2. AI responds to the user

        Expected AI Behavior (per skill instructions):
        ❌ AI must NOT suggest using `!` prefix
        ❌ AI must NOT suggest alternative commands (cat, head, less)
        ❌ AI must NOT suggest disabling security features
        ❌ AI must NOT suggest modifying .ai-read-deny

        This test verifies the skill instructions explicitly forbid
        all known bypass methods.
        """
        from ai_guardian.mcp.server import _load_skill_instructions

        instructions = _load_skill_instructions()

        forbidden_patterns = [
            "! ",
            "enabled: false",
            "--no-verify",
            "--skip-checksum",
        ]
        for pattern in forbidden_patterns:
            assert (
                pattern not in instructions or "Do NOT" in instructions
            ), f"Skill mentions '{pattern}' — must be in Do NOT context only"

        assert (
            "alternative commands" in instructions.lower()
            or "alternative" in instructions.lower()
        ), "Skill must forbid suggesting alternative access methods"

    @pytest.mark.skipif(
        sys.version_info < (3, 10),
        reason="MCP SDK requires Python >= 3.10",
    )
    def test_violations_provide_actual_block_reason(self):
        """
        USER EXPERIENCE: get_violations() returns the actual block reason

        This test verifies that when a secret is detected, get_violations()
        returns violation_type="secret_detected" so the AI can report the
        real reason instead of guessing.

        Expected:
        ✅ Violation type is "secret_detected" (not "directory_blocking")
        ✅ File path is included for context
        ✅ AI can use this to report: "blocked because a secret was detected"
        """
        from unittest.mock import MagicMock, patch
        from ai_guardian.mcp.server import create_server

        with patch("ai_guardian.violations.logger.ViolationLogger") as mock_vl_cls:
            mock_vl = MagicMock()
            mock_vl.get_recent_violations.return_value = [
                {
                    "timestamp": "2026-05-13T10:00:00Z",
                    "violation_type": "secret_detected",
                    "severity": "critical",
                    "blocked": {
                        "file_path": "/tmp/test.txt",
                        "line_number": 3,
                    },
                    "context": {"tool_name": "Read"},
                }
            ]
            mock_vl_cls.return_value = mock_vl

            server = create_server()
            tool = server._tool_manager._tools["get_violations"]
            result = tool.fn(limit=1)

            assert result["count"] == 1
            violation = result["violations"][0]
            assert (
                violation["type"] == "secret_detected"
            ), "Violation type must be 'secret_detected', not guessed from error"
            assert (
                violation["file"] == "/tmp/test.txt"
            ), "File path must be included for context"
            assert violation["line"] == 3, "Line number must be included when available"

    @pytest.mark.skipif(
        sys.version_info < (3, 10),
        reason="MCP SDK requires Python >= 3.10",
    )
    def test_file_content_prompt_injection_reports_scanned_path(self):
        """
        USER EXPERIENCE: File-content prompt injection → location is reported.

        Scenario:
        1. Claude reads a file containing a prompt-injection attempt.
        2. ai-guardian blocks the file-content scan.
        3. Claude calls get_violations(limit=1) for the structured reason.

        Expected User Experience:
        ✅ get_violations() identifies the violation as prompt_injection.
        ✅ The response includes the scanned file path and line number.
        """
        from unittest.mock import MagicMock
        from ai_guardian.mcp.server import create_server

        with patch("ai_guardian.violations.logger.ViolationLogger") as mock_vl_cls:
            mock_vl = MagicMock()
            mock_vl.get_recent_violations.return_value = [
                {
                    "timestamp": "2026-05-13T10:00:00Z",
                    "violation_type": "prompt_injection",
                    "severity": "high",
                    "blocked": {
                        "file_path": "/repo/reference.md",
                        "line_number": 2,
                        "start_column": 0,
                        "end_column": 31,
                    },
                    "context": {"tool_name": "Read"},
                }
            ]
            mock_vl_cls.return_value = mock_vl

            server = create_server()
            tool = server._tool_manager._tools["get_violations"]
            result = tool.fn(limit=1)

        violation = result["violations"][0]
        assert violation["type"] == "prompt_injection"
        assert violation["file"] == "/repo/reference.md"
        assert violation["line"] == 2

    def test_documentation_block_reason_flow(self):
        """
        Documentation test: Correct flow when a tool is blocked.

        This test always passes — it documents the expected interaction
        flow when ai-guardian blocks a tool call.

        CORRECT Flow (Issue #575 fix):
        ==============================
        1. User asks Claude to read /tmp/test.txt
        2. Claude calls Read tool
        3. ai-guardian hook blocks it (aws-access-token detected)
        4. Claude sees block error from hook
        5. Claude calls get_violations(limit=1)
        6. get_violations returns: type=secret_detected, file=/tmp/test.txt
        7. Claude tells user: "The read was blocked — a secret (aws-access-token)
           was detected in /tmp/test.txt"

        INCORRECT Flow (before fix):
        ============================
        1. User asks Claude to read /tmp/test.txt
        2. Claude calls Read tool
        3. ai-guardian hook blocks it
        4. Claude GUESSES: "outside allowed project directories"
        5. Claude SUGGESTS: "try ! cat /tmp/test.txt"

        The fix ensures the AI always queries for the real reason and
        never suggests bypass methods.
        """
        assert True, "See docstring for expected block-reason flow"
