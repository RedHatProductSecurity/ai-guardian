"""
Integration tests for MCP tool protections.

Tests AI Guardian protections with actual MCP tool calls using a mock MCP server.
Covers all protection layers: permissions, secret scanning, prompt injection,
SSRF, and config exfiltration.
"""

from unittest import TestCase
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.tools.policy import ToolPolicyChecker
import ai_guardian
from tests.fixtures.mock_mcp_server import create_hook_data
from tests.fixtures import attack_constants


class MCPToolPermissionTests(TestCase):
    """Test MCP tool permission enforcement (Scenario 1)"""

    def test_blocked_mcp_tool_by_default(self):
        """
        Verify unlisted MCP tools are blocked by default.

        Scenario: MCP tools blocked by default
        Action: Attempt to use mcp__notebooklm-mcp__notebook_create
        Expected: BLOCKED with "TOOL ACCESS DENIED"
        """
        # Configure: MCP tools blocked by default (deny-all policy)
        config = {
            "permissions": {
                "enabled": True,
                "rules": [{"matcher": "mcp__*", "mode": "deny", "patterns": ["*"]}],
            }
        }

        policy_checker = ToolPolicyChecker(config=config)

        # Action: Attempt to use mcp__notebooklm-mcp__notebook_create
        hook_data = create_hook_data(
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
            tool_input={"title": "Test Notebook"},
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Expected: BLOCKED with "TOOL ACCESS DENIED"
        assert not allowed, "Unlisted MCP tool should be blocked"
        assert error_msg is not None, "Should have error message"
        assert (
            "TOOL ACCESS DENIED" in error_msg or "denied" in error_msg.lower()
        ), f"Error should mention denial: {error_msg}"

    def test_allowed_mcp_tool_in_allowlist(self):
        """
        Verify allow-listed MCP tools are permitted.

        Scenario: Specific MCP tool allowed via allowlist
        Action: Use mcp__notebooklm-mcp__notebook_list (in allowlist)
        Expected: ALLOWED
        """
        # Configure: Allow only notebook_list
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

        policy_checker = ToolPolicyChecker(config=config)

        # Action: Use allowed tool
        hook_data = create_hook_data(
            tool_name="mcp__notebooklm-mcp__notebook_list", tool_input={}
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Expected: ALLOWED
        assert allowed, f"Allow-listed MCP tool should be permitted: {error_msg}"
        assert error_msg is None, "No error message for allowed tool"

    def test_blocked_mcp_tool_not_in_allowlist(self):
        """
        Verify MCP tools not in allowlist are blocked.

        Scenario: MCP tool not in allowlist
        Action: Use mcp__notebooklm-mcp__notebook_create (not in allowlist)
        Expected: BLOCKED
        """
        # Configure: Allow only specific tools
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

        policy_checker = ToolPolicyChecker(config=config)

        # Action: Try to use tool NOT in allowlist
        hook_data = create_hook_data(
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
            tool_input={"title": "Test"},
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Expected: BLOCKED
        assert not allowed, "Tool not in allowlist should be blocked"
        assert error_msg is not None, "Should have error message"
        assert (
            "not in allow list" in error_msg.lower() or "denied" in error_msg.lower()
        ), f"Error should mention allowlist: {error_msg}"

    def test_wildcard_pattern_allows_all_notebooklm_tools(self):
        """
        Verify wildcard patterns work correctly.

        Scenario: Wildcard allowlist for all NotebookLM tools
        Action: Use various mcp__notebooklm-mcp__* tools
        Expected: ALL ALLOWED
        """
        # Configure: Allow all NotebookLM tools with wildcard
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__notebooklm-mcp__*",
                        "mode": "allow",
                        "patterns": ["mcp__notebooklm-mcp__*"],
                    }
                ],
            }
        }

        policy_checker = ToolPolicyChecker(config=config)

        # Test multiple tools
        tools = [
            attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
            attack_constants.MCP_TOOL_NOTEBOOKLM_SOURCE,
            attack_constants.MCP_TOOL_NOTEBOOKLM_QUERY,
            "mcp__notebooklm-mcp__notebook_list",
            "mcp__notebooklm-mcp__notebook_delete",
        ]

        for tool_name in tools:
            hook_data = create_hook_data(tool_name=tool_name, tool_input={})

            allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

            assert allowed, f"Wildcard should allow {tool_name}: {error_msg}"

    def test_custom_mcp_server_blocked_by_default(self):
        """
        Verify custom MCP servers are blocked when not allowlisted.

        Scenario: Custom MCP server not in configuration
        Action: Use mcp__custom-server__dangerous_action
        Expected: BLOCKED
        """
        # Configure: Allow only NotebookLM tools
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__notebooklm-mcp__*",
                        "mode": "allow",
                        "patterns": ["mcp__notebooklm-mcp__*"],
                    }
                ],
            }
        }

        policy_checker = ToolPolicyChecker(config=config)

        # Action: Try to use custom MCP server
        hook_data = create_hook_data(
            tool_name=attack_constants.MCP_TOOL_BLOCKED_CUSTOM,
            tool_input={"action": "delete_all"},
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Expected: BLOCKED
        assert not allowed, "Custom MCP server should be blocked"
        assert error_msg is not None, "Should have error message"

    def test_no_permission_rules_allows_non_restricted_tools(self):
        """
        Verify tools without permission rules are allowed by default.

        Scenario: No permission rules configured
        Action: Use MCP tool that doesn't require explicit allow
        Expected: ALLOWED (no rules = allowed by default for some tools)

        Note: MCP tools starting with mcp__ require explicit allow, so this
        tests a regular tool instead.
        """
        # Configure: No permission rules
        config = {"permissions": {"enabled": True, "rules": []}}

        policy_checker = ToolPolicyChecker(config=config)

        # Action: Try to use a tool that doesn't require explicit allow (e.g., Read)
        hook_data = create_hook_data(
            tool_name="Read", tool_input={"file_path": "/tmp/test.txt"}
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)

        # Expected: ALLOWED (Read tool allowed by default when no rules)
        assert allowed, f"Read tool should be allowed with no rules: {error_msg}"
        assert (
            error_msg is None
        ), "No error when no rules and tool doesn't require explicit allow"


class MCPSecretScanningTests(TestCase):
    """Test secret scanning in MCP tool inputs (Scenario 2)"""

    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_secret_in_notebook_title(self, mock_pattern_config):
        """
        Verify secrets in MCP tool parameters are blocked.

        Scenario: Secret in notebook title
        Action: Create notebook with title containing Slack token
        Expected: BLOCKED with "Secret Detected"
        """
        # Disable pattern server to use default gitleaks rules
        mock_pattern_config.return_value = None

        # Action: Attempt to create notebook with secret in title
        title_with_secret = f"Project Notes {attack_constants.SECRET_SLACK_TOKEN}"

        has_secrets, error_msg = ai_guardian.check_secrets(
            title_with_secret, "notebook_title"
        )

        # Expected: BLOCKED with "Secret Detected"
        assert has_secrets, "Secret in notebook title should be detected"
        assert error_msg is not None, "Should have error message"
        assert (
            "Secret Detected" in error_msg
        ), f"Error should mention secret detection: {error_msg}"

    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_secret_in_source_text(self, mock_pattern_config):
        """
        Verify secrets in MCP source content are blocked.

        Scenario: Secret in source text content
        Action: Add source with text containing Slack token
        Expected: BLOCKED with "Secret Detected"
        """
        # Disable pattern server
        mock_pattern_config.return_value = None

        # Action: Source text with Slack token
        source_text = f"""
        Research findings:
        - API endpoint: https://api.example.com
        - Auth token: {attack_constants.SECRET_SLACK_TOKEN}
        - Results: positive
        """

        has_secrets, error_msg = ai_guardian.check_secrets(
            source_text, "source_content"
        )

        # Expected: BLOCKED
        assert has_secrets, "Secret in source text should be detected"
        assert (
            "Secret Detected" in error_msg
        ), f"Error should mention secret: {error_msg}"

    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_multiple_secret_types_detected(self, mock_pattern_config):
        """
        Verify multiple secret types are detected in a single input.

        Scenario: Multiple secrets in one source
        Action: Add source with multiple Slack tokens
        Expected: BLOCKED with secrets detected
        """
        # Disable pattern server
        mock_pattern_config.return_value = None

        # Action: Content with multiple secrets
        # Note: Using Slack tokens as they are reliably detected by gitleaks
        content = f"""
        Credentials backup:
        Token 1: {attack_constants.SECRET_SLACK_TOKEN}
        Token 2: xoxb-987654321098-987654321098-YYYYYYYYYYYYYYYYYYYY  # notsecret - FAKE TEST CREDENTIAL
        """

        has_secrets, error_msg = ai_guardian.check_secrets(content, "multi_secret_test")

        # Expected: BLOCKED (at least one secret detected)
        assert has_secrets, "Multiple secrets should be detected"
        assert "Secret Detected" in error_msg, "Error should mention secrets"

    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_legitimate_content_not_blocked(self, mock_pattern_config):
        """
        Verify legitimate content without secrets is allowed.

        Scenario: Normal notebook content
        Action: Create notebook with legitimate title and sources
        Expected: ALLOWED
        """
        # Disable pattern server
        mock_pattern_config.return_value = None

        # Action: Legitimate content
        has_secrets, error_msg = ai_guardian.check_secrets(
            attack_constants.LEGITIMATE_NOTEBOOK_TITLE, "title"
        )

        # Expected: ALLOWED
        assert not has_secrets, "Legitimate content should not trigger secret detection"
        assert error_msg is None, "No error for clean content"

        # Test legitimate source text
        has_secrets, error_msg = ai_guardian.check_secrets(
            attack_constants.LEGITIMATE_TEXT_SOURCE, "source"
        )

        assert not has_secrets, "Legitimate source should not be blocked"
        assert error_msg is None, "No error for legitimate source"


class MCPPromptInjectionTests(TestCase):
    """Test prompt injection detection in MCP tool inputs (Scenario 3)"""

    def test_prompt_injection_in_notebook_title(self):
        """
        Verify prompt injection in MCP parameters is blocked.

        Scenario: Prompt injection in notebook title
        Action: Create notebook with title containing injection attempt
        Expected: BLOCKED with "Prompt Injection Detected"
        """
        from ai_guardian.scanners.prompt_injection import check_prompt_injection

        # Action: Notebook title with prompt injection
        malicious_title = attack_constants.PROMPT_INJECTION_IGNORE_PREVIOUS

        config = {"enabled": True}
        # Returns: (is_attack, error_msg, log_mode)
        is_attack, error_msg, _ = check_prompt_injection(
            malicious_title,
            config,
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
        )

        # Expected: BLOCKED
        assert is_attack, "Prompt injection should be detected"
        assert error_msg is not None, "Should have error message"
        assert (
            "PROMPT INJECTION" in error_msg.upper() or "injection" in error_msg.lower()
        ), f"Error should mention prompt injection: {error_msg}"

    def test_prompt_injection_role_switch_in_source(self):
        """
        Verify role-switching prompt injection is blocked.

        Scenario: Role-switch injection in source text
        Action: Add source with role-switching attack
        Expected: BLOCKED
        """
        from ai_guardian.scanners.prompt_injection import check_prompt_injection

        # Action: Source with role-switching injection
        malicious_source = attack_constants.PROMPT_INJECTION_ROLE_SWITCH

        config = {"enabled": True}
        # Returns: (is_attack, error_msg, log_mode)
        is_attack, error_msg, _ = check_prompt_injection(
            malicious_source,
            config,
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_SOURCE,
        )

        # Expected: BLOCKED
        assert is_attack, "Role-switching injection should be detected"
        assert error_msg is not None, "Should have error message"

    def test_delimiter_escape_injection(self):
        """
        Verify delimiter escape prompt injection is blocked.

        Scenario: Delimiter escape to break out of context
        Action: Use content with delimiter escape attempt
        Expected: BLOCKED
        """
        from ai_guardian.scanners.prompt_injection import check_prompt_injection

        # Action: Delimiter escape injection
        malicious_content = attack_constants.PROMPT_INJECTION_DELIMITER_ESCAPE

        config = {"enabled": True}
        # Returns: (is_attack, error_msg, log_mode)
        is_attack, error_msg, _ = check_prompt_injection(
            malicious_content,
            config,
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
        )

        # Expected: BLOCKED
        assert is_attack, f"Delimiter escape injection should be detected: {error_msg}"
        assert error_msg is not None, "Should have error message"

    def test_legitimate_notebook_query_allowed(self):
        """
        Verify legitimate queries are not flagged as injection.

        Scenario: Normal notebook query
        Action: Query notebook with legitimate question
        Expected: ALLOWED
        """
        from ai_guardian.scanners.prompt_injection import check_prompt_injection

        # Action: Legitimate query
        legitimate_query = "What are the main findings from the research?"

        config = {"enabled": True}
        # Returns: (is_attack, error_msg, log_mode)
        is_attack, error_msg, _ = check_prompt_injection(
            legitimate_query,
            config,
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_QUERY,
        )

        # Expected: ALLOWED
        assert not is_attack, "Legitimate query should not be flagged"
        assert error_msg is None, "No error for legitimate content"


class MCPSSRFProtectionTests(TestCase):
    """Test SSRF protection in Bash commands (Scenario 4)

    Note: SSRF protection currently only applies to Bash tool, not directly to MCP tools.
    MCP tools that generate Bash commands would be checked via those commands.
    """

    def test_ssrf_aws_metadata_in_bash_blocked(self):
        """
        Verify AWS metadata endpoint is blocked in Bash commands.

        Scenario: SSRF attack via Bash curl command
        Action: Bash command with curl to AWS metadata endpoint
        Expected: BLOCKED with "SSRF ATTACK DETECTED"
        """
        from ai_guardian.scanners.ssrf import SSRFProtector

        # Configure SSRF protector
        config = {"enabled": True}
        protector = SSRFProtector(config)

        # Action: Bash command with AWS metadata URL
        tool_input = {"command": f"curl {attack_constants.SSRF_AWS_METADATA}"}

        should_block, error_msg = protector.check("Bash", tool_input)

        # Expected: BLOCKED
        assert should_block, "AWS metadata endpoint should be blocked"
        assert error_msg is not None, "Should have error message"
        assert (
            "SSRF" in error_msg.upper() or "metadata" in error_msg.lower()
        ), f"Error should mention SSRF: {error_msg}"

    def test_ssrf_gcp_metadata_in_bash_blocked(self):
        """
        Verify GCP metadata endpoint is blocked in Bash.

        Scenario: SSRF attack targeting GCP metadata via wget
        Action: Bash wget command to GCP metadata
        Expected: BLOCKED
        """
        from ai_guardian.scanners.ssrf import SSRFProtector

        config = {"enabled": True}
        protector = SSRFProtector(config)

        # Action: Bash with GCP metadata URL
        tool_input = {"command": f"wget {attack_constants.SSRF_GCP_METADATA}"}

        should_block, error_msg = protector.check("Bash", tool_input)

        # Expected: BLOCKED
        assert should_block, "GCP metadata endpoint should be blocked"
        assert error_msg is not None, "Should have error message"

    def test_ssrf_private_ip_in_bash_blocked(self):
        """
        Verify private IP addresses are blocked in Bash.

        Scenario: SSRF targeting private network via Bash
        Action: Bash commands with RFC1918 private IPs
        Expected: BLOCKED
        """
        from ai_guardian.scanners.ssrf import SSRFProtector

        config = {"enabled": True}
        protector = SSRFProtector(config)

        # Test multiple private IPs in Bash commands
        for private_url in attack_constants.SSRF_PRIVATE_IPS:
            tool_input = {"command": f"curl {private_url}"}

            should_block, error_msg = protector.check("Bash", tool_input)

            assert should_block, f"Private IP should be blocked: {private_url}"
            assert error_msg is not None, f"Should have error for: {private_url}"

    def test_legitimate_public_url_in_bash_allowed(self):
        """
        Verify legitimate public URLs are allowed in Bash.

        Scenario: Normal public URL in Bash command
        Action: curl command with legitimate public URL
        Expected: ALLOWED
        """
        from ai_guardian.scanners.ssrf import SSRFProtector

        config = {"enabled": True}
        protector = SSRFProtector(config)

        # Action: Legitimate public URL in Bash
        tool_input = {"command": f"curl {attack_constants.LEGITIMATE_PUBLIC_URL}"}

        should_block, error_msg = protector.check("Bash", tool_input)

        # Expected: ALLOWED
        assert not should_block, f"Legitimate public URL should be allowed: {error_msg}"
        # error_msg might be None or might be a warning (both are OK for legitimate URLs)

    def test_ssrf_protection_skips_non_bash_tools(self):
        """
        Verify SSRF protection only applies to Bash tool.

        Scenario: MCP tool with URL (SSRF check skipped)
        Action: MCP source_add with URL
        Expected: SSRF check returns (False, None) - not applicable

        Note: This documents current behavior. Future enhancement could add
        MCP-specific URL checking.
        """
        from ai_guardian.scanners.ssrf import SSRFProtector

        config = {"enabled": True}
        protector = SSRFProtector(config)

        # Action: MCP tool (not Bash) with URL
        tool_input = {"url": attack_constants.SSRF_AWS_METADATA}

        should_block, error_msg = protector.check(
            attack_constants.MCP_TOOL_NOTEBOOKLM_SOURCE, tool_input
        )

        # Expected: Not checked (returns False, None)
        assert not should_block, "SSRF check should skip non-Bash tools"
        assert error_msg is None, "No error when tool is not Bash"


class MCPConfigExfiltrationTests(TestCase):
    """Test config file exfiltration pattern detection (Scenario 5)"""

    def test_config_exfiltration_pattern_in_claude_md(self):
        """
        Verify config exfiltration patterns are blocked in config files.

        Scenario: Config file exfiltration attempt in CLAUDE.md
        Action: CLAUDE.md file with curl exfiltration command
        Expected: BLOCKED (config exfiltration pattern)

        Note: Config scanner only scans known config files (CLAUDE.md, AGENTS.md, etc.)
        """
        from ai_guardian.scanners.config_scanner import check_config_file_threats

        # Action: CLAUDE.md with curl env exfiltration
        malicious_text = attack_constants.EXFILTRATION_CURL_ENV

        # Returns: (is_threat, error_msg, details_dict)
        # Must use a recognized config file name for scanner to activate
        is_threat, error_msg, details = check_config_file_threats(
            "CLAUDE.md", malicious_text, None
        )

        # Expected: BLOCKED
        assert is_threat, "Config exfiltration should be detected in CLAUDE.md"
        assert error_msg is not None, "Should have error message"
        assert (
            "exfiltration" in error_msg.lower() or "curl" in error_msg.lower()
        ), f"Should detect config exfiltration: {error_msg}"

    def test_credential_exfiltration_in_agents_md_blocked(self):
        """
        Verify credential exfiltration patterns are blocked in AGENTS.md.

        Scenario: Attempt to exfiltrate credentials via AGENTS.md
        Action: AGENTS.md with printenv piped to curl
        Expected: BLOCKED
        """
        from ai_guardian.scanners.config_scanner import check_config_file_threats

        # Action: AGENTS.md with credential exfiltration
        malicious_text = attack_constants.EXFILTRATION_CREDENTIALS

        # Returns: (is_threat, error_msg, details_dict)
        is_threat, error_msg, details = check_config_file_threats(
            "AGENTS.md", malicious_text, None
        )

        # Expected: BLOCKED
        assert is_threat, "Credential exfiltration should be detected in AGENTS.md"
        assert error_msg is not None, "Should have error message"

    def test_legitimate_research_content_allowed(self):
        """
        Verify legitimate content mentioning configs is allowed.

        Scenario: Research about configuration files
        Action: Add source discussing config files academically
        Expected: ALLOWED
        """
        from ai_guardian.scanners.config_scanner import check_config_file_threats

        # Action: Legitimate content that mentions config files
        legitimate_text = """
        Research on configuration management:
        - Best practices for storing configuration files
        - Version control strategies for config files
        - Security considerations for sensitive configurations
        """

        # Returns: (is_threat, error_msg, details_dict)
        is_threat, error_msg, details = check_config_file_threats(
            "research_text.txt", legitimate_text, None
        )

        # Expected: ALLOWED
        assert not is_threat, f"Legitimate research should not be blocked: {error_msg}"
        assert error_msg is None, "No error for legitimate content"


class MCPCombinedProtectionTests(TestCase):
    """Test multiple protections working together (Scenario 6)"""

    def test_combined_protections_mcp_workflow(self):
        """
        Verify multiple protections work together correctly.

        Scenario: Complete protection stack via tool_policy checker
        Test sequence:
        1. Check MCP tool permission (should pass if allowed)
        2. Check for SSRF in Bash commands (SSRF only applies to Bash)
        3. Check for secrets (should block if found)
        4. Check for prompt injection (should block if detected)
        """
        from ai_guardian.tools.policy import ToolPolicyChecker

        # Configure all protections
        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {
                        "matcher": "mcp__notebooklm-mcp__*",
                        "mode": "allow",
                        "patterns": ["mcp__notebooklm-mcp__*"],
                    }
                ],
            },
            "ssrf_protection": {"enabled": True},
        }

        policy_checker = ToolPolicyChecker(config=config)

        # Test 1: Permission check (should PASS for allowed tool)
        hook_data = create_hook_data(
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_SOURCE,
            tool_input={"url": "https://example.com"},
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(hook_data)
        assert allowed, f"Allowed MCP tool should pass permission check: {error_msg}"

        # Test 2: SSRF check via Bash tool (should BLOCK)
        bash_hook_data = create_hook_data(
            tool_name="Bash",
            tool_input={"command": f"curl {attack_constants.SSRF_AWS_METADATA}"},
        )

        allowed, error_msg, _ = policy_checker.check_tool_allowed(bash_hook_data)
        assert not allowed, "SSRF attempt in Bash should be blocked"
        assert error_msg is not None, "SSRF block should have error message"
        assert (
            "SSRF" in error_msg.upper() or "metadata" in error_msg.lower()
        ), f"Error should mention SSRF: {error_msg}"

    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_defense_in_depth_multiple_triggers(self, mock_pattern_config):
        """
        Verify defense in depth - multiple violations trigger appropriate blocks.

        Scenario: Input with both secrets AND prompt injection
        Action: Content with multiple attack vectors
        Expected: BLOCKED by first matching protection
        """
        # Disable pattern server
        mock_pattern_config.return_value = None

        from ai_guardian.scanners.prompt_injection import check_prompt_injection

        # Content with BOTH secret AND prompt injection
        malicious_content = f"""
        {attack_constants.PROMPT_INJECTION_IGNORE_PREVIOUS}
        Token: {attack_constants.SECRET_SLACK_TOKEN}
        """

        # Test secret scanning (should BLOCK)
        has_secrets, secret_error = ai_guardian.check_secrets(
            malicious_content, "test_content"
        )

        assert has_secrets, "Secret should be detected"

        # Test prompt injection (should ALSO BLOCK)
        config = {"enabled": True}
        # Returns: (is_attack, error_msg, log_mode)
        is_injection, injection_error, _ = check_prompt_injection(
            malicious_content,
            config,
            tool_name=attack_constants.MCP_TOOL_NOTEBOOKLM_CREATE,
        )

        assert is_injection, "Prompt injection should be detected"

        # Both protections should trigger - defense in depth
        assert has_secrets and is_injection, "Multiple protections should trigger"


class MCPServerToolInputFormatTests(TestCase):
    """Test that MCP server tools pass correct hook_data format to ToolPolicyChecker.

    Regression tests for issue #1264: MCP check_path/check_command passed
    'parameters' key but _extract_tool_info expected 'tool_input'.
    """

    def test_check_path_allowed_for_non_protected_path(self):
        """check_path returns allowed for paths not matched by directory rules."""
        import sys
        import tempfile

        if sys.version_info < (3, 10):
            pytest.skip("MCP SDK requires Python >= 3.10")

        from ai_guardian.mcp.server import create_server

        with tempfile.NamedTemporaryFile(suffix=".py") as f:
            f.write(b"x = 1")
            f.flush()
            server = create_server()
            tool = server._tool_manager._tools["check_path"]
            result = tool.fn(path=f.name)
            assert (
                result["status"] == "allowed"
            ), f"Non-protected path should be allowed, got: {result}"

    def test_check_path_denied_for_protected_path(self):
        """check_path returns denied for paths matching directory deny rules."""
        import sys
        import tempfile
        import os

        if sys.version_info < (3, 10):
            pytest.skip("MCP SDK requires Python >= 3.10")

        from ai_guardian.mcp.server import create_server

        with tempfile.TemporaryDirectory() as tmpdir:
            protected_dir = os.path.join(tmpdir, "secrets")
            os.makedirs(protected_dir)
            deny_marker = os.path.join(protected_dir, ".ai-read-deny")
            open(deny_marker, "w").close()
            target = os.path.join(protected_dir, "creds.txt")
            with open(target, "w") as f:
                f.write("secret data")

            config = {
                "directory_rules": {
                    "enabled": True,
                    "rules": [{"path": protected_dir + "/**", "action": "deny"}],
                }
            }
            with patch("ai_guardian.tools.policy.ToolPolicyChecker") as mock_cls:
                mock_checker = MagicMock()
                mock_checker.check_tool_allowed.return_value = (
                    False,
                    "Denied",
                    "Write",
                )
                mock_cls.return_value = mock_checker

                server = create_server()
                tool = server._tool_manager._tools["check_path"]
                result = tool.fn(path=target)
                assert result["status"] == "denied"

                hook_data = mock_checker.check_tool_allowed.call_args[0][0]
                assert "tool_input" in hook_data
                assert "file_path" in hook_data["tool_input"]

    def test_check_command_blocked_for_secret_pattern(self):
        """check_command returns blocked when command contains secret patterns."""
        import sys

        if sys.version_info < (3, 10):
            pytest.skip("MCP SDK requires Python >= 3.10")

        from ai_guardian.mcp.server import create_server

        config = {
            "secret_scanning": {"enabled": True},
        }

        with patch("ai_guardian.tools.policy.ToolPolicyChecker") as mock_cls:
            mock_checker = MagicMock()
            mock_checker.check_tool_allowed.return_value = (
                False,
                "Secret detected in command",
                "Bash",
            )
            mock_cls.return_value = mock_checker

            server = create_server()
            tool = server._tool_manager._tools["check_command"]
            result = tool.fn(
                command="curl -H 'Authorization: Bearer sk_live_abc123def456'"
            )
            assert result["status"] == "blocked"
            assert result["reason"] == "secret_detected"

            hook_data = mock_checker.check_tool_allowed.call_args[0][0]
            assert "tool_input" in hook_data
            assert (
                hook_data["tool_input"]["command"]
                == "curl -H 'Authorization: Bearer sk_live_abc123def456'"
            )

    def test_check_command_allowed_for_safe_command(self):
        """check_command returns allowed for safe commands."""
        import sys

        if sys.version_info < (3, 10):
            pytest.skip("MCP SDK requires Python >= 3.10")

        from ai_guardian.mcp.server import create_server

        server = create_server()
        tool = server._tool_manager._tools["check_command"]
        result = tool.fn(command="ls -la")
        assert (
            result["status"] == "allowed"
        ), f"Safe command should be allowed, got: {result}"
