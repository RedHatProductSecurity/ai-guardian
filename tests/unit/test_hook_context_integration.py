"""
Integration tests for cross-hook context passing (Issue #366).

Tests the full PreToolUse -> PostToolUse round-trip through process_hook_data(),
verifying context inheritance, double-scan skipping, and ignore_files consistency.
"""

from unittest.mock import patch


import ai_guardian
from ai_guardian.hook_context import HookContextManager


class TestPreToolUseContextSaving:
    """Verify PreToolUse saves context for PostToolUse to retrieve."""

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_pretooluse_saves_context_with_file_path(
        self, mock_redaction, mock_pattern, mock_secret, tmp_path
    ):
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": False}, None)

        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_use_id": "toolu_ctx_test_001",
            "session_id": "session-ctx-test",
            "tool_use": {
                "name": "Read",
                "parameters": {"file_path": str(test_file)},
            },
        }

        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        result = ai_guardian.process_hook_data(hook_data, daemon_state=state)

        assert result["exit_code"] == 0

        # Verify context was saved
        ctx = state.get_pretooluse_context("session-ctx-test", "toolu_ctx_test_001")
        assert ctx is not None
        assert ctx["file_path"] == str(test_file)
        assert ctx["tool_name"] == "Read"
        assert "scan_results" in ctx

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_pretooluse_non_file_tool_saves_context(
        self, mock_redaction, mock_pattern, mock_secret, tmp_path
    ):
        """Bash tool (non-file-reading) should still save context."""
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": False}, None)

        hook_data = {
            "hook_event_name": "PreToolUse",
            "tool_use_id": "toolu_bash_001",
            "session_id": "session-bash-test",
            "tool_use": {
                "name": "Bash",
                "parameters": {"command": "echo hello"},
            },
        }

        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        result = ai_guardian.process_hook_data(hook_data, daemon_state=state)

        assert result["exit_code"] == 0

        ctx = state.get_pretooluse_context("session-bash-test", "toolu_bash_001")
        assert ctx is not None
        assert ctx["file_path"] is None
        assert ctx["tool_name"] == "Bash"


class TestPostToolUseContextLoading:
    """Verify PostToolUse loads and uses PreToolUse context."""

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_posttooluse_skips_scan_when_pretool_clean(
        self, mock_redaction, mock_pattern, mock_secret, tmp_path
    ):
        """PostToolUse should skip secret scan when PreToolUse found no secrets."""
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": True}, None)

        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")

        # Pre-populate PreToolUse context as if PreToolUse ran first
        state.store_pretooluse_context(
            "session-skip",
            "toolu_skip_001",
            {
                "file_path": "/tmp/test.py",
                "tool_name": "Read",
                "scan_results": {
                    "secrets_scanned": True,
                    "secrets_found": False,
                    "pii_scanned": True,
                    "pii_skipped_reason": None,
                    "prompt_injection_scanned": True,
                },
                "ignore_files_matched": False,
            },
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "toolu_skip_001",
            "session_id": "session-skip",
            "tool_name": "Read",
            "tool_response": {"output": "print('hello world')"},
        }

        # Mock gitleaks to track if it's called
        with patch(
            "ai_guardian.scanners.secret_scanning.check_secrets"
        ) as mock_gitleaks:
            mock_gitleaks.return_value = (False, None)
            result = ai_guardian.process_hook_data(hook_data, daemon_state=state)

            assert result["exit_code"] == 0
            # Gitleaks should NOT be called because PreToolUse already scanned clean
            mock_gitleaks.assert_not_called()

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_posttooluse_scans_normally_without_pretool_context(
        self, mock_redaction, mock_pattern, mock_secret, tmp_path
    ):
        """PostToolUse should scan normally when no PreToolUse context available."""
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": True}, None)

        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "toolu_no_ctx_001",
            "session_id": "session-no-ctx",
            "tool_name": "Read",
            "tool_response": {"output": "clean output"},
        }

        with patch(
            "ai_guardian.scanners.secret_scanning.check_secrets"
        ) as mock_gitleaks:
            mock_gitleaks.return_value = (False, None)
            result = ai_guardian.process_hook_data(hook_data, daemon_state=state)

            assert result["exit_code"] == 0
            # Gitleaks SHOULD be called since no PreToolUse context
            mock_gitleaks.assert_called_once()


class TestIgnoreFilesConsistency:
    """Verify ignore_files is consistent between PreToolUse and PostToolUse."""

    @patch("ai_guardian.config.loaders._load_pii_config")
    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_posttooluse_skips_when_ignore_files_matched(
        self, mock_redaction, mock_pattern, mock_secret, mock_pii, tmp_path
    ):
        """PostToolUse should skip scans when PreToolUse matched ignore_files."""
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": True}, None)
        mock_pii.return_value = (None, None)

        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")

        state.store_pretooluse_context(
            "session-ignore",
            "toolu_ignore_001",
            {
                "file_path": "/data/sensitive.csv",
                "tool_name": "Read",
                "scan_results": {
                    "secrets_scanned": False,
                    "secrets_found": False,
                    "pii_scanned": False,
                    "pii_skipped_reason": "ignore_files match",
                    "prompt_injection_scanned": False,
                },
                "ignore_files_matched": True,
            },
        )

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "toolu_ignore_001",
            "session_id": "session-ignore",
            "tool_name": "Read",
            "tool_response": {"output": "sensitive data here"},
        }

        with patch(
            "ai_guardian.scanners.secret_scanning.check_secrets"
        ) as mock_gitleaks:
            mock_gitleaks.return_value = (False, None)
            result = ai_guardian.process_hook_data(hook_data, daemon_state=state)

            assert result["exit_code"] == 0
            mock_gitleaks.assert_not_called()


class TestDaemonModeRoundTrip:
    """Test full round-trip through DaemonState."""

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_daemon_state_correlates_pre_and_post(
        self, mock_redaction, mock_pattern, mock_secret, tmp_path
    ):
        """Same DaemonState used for both PreToolUse and PostToolUse."""
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": False}, None)

        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")

        test_file = tmp_path / "example.py"
        test_file.write_text("x = 1")

        # Step 1: PreToolUse
        pre_hook = {
            "hook_event_name": "PreToolUse",
            "tool_use_id": "toolu_roundtrip_001",
            "session_id": "session-roundtrip",
            "tool_use": {
                "name": "Read",
                "parameters": {"file_path": str(test_file)},
            },
        }
        result1 = ai_guardian.process_hook_data(pre_hook, daemon_state=state)
        assert result1["exit_code"] == 0

        # Verify context was stored
        ctx = state.get_pretooluse_context("session-roundtrip", "toolu_roundtrip_001")
        assert ctx is not None
        assert ctx["file_path"] == str(test_file)

        # Step 2: PostToolUse (same tool_use_id)
        post_hook = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "toolu_roundtrip_001",
            "session_id": "session-roundtrip",
            "tool_name": "Read",
            "tool_response": {"output": "x = 1"},
        }

        with patch(
            "ai_guardian.config.loaders._load_secret_scanning_config"
        ) as mock_secret2:
            mock_secret2.return_value = ({"enabled": True}, None)
            with patch(
                "ai_guardian.scanners.secret_scanning.check_secrets"
            ) as mock_gitleaks:
                mock_gitleaks.return_value = (False, None)
                result2 = ai_guardian.process_hook_data(post_hook, daemon_state=state)

                assert result2["exit_code"] == 0
                # Secret scan should be skipped due to PreToolUse context
                mock_gitleaks.assert_not_called()


class TestGracefulFallback:
    """Verify PostToolUse works normally when context is unavailable."""

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_no_daemon_state_no_session_id(
        self, mock_redaction, mock_pattern, mock_secret
    ):
        """PostToolUse processes normally without daemon_state or session_id."""
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": True}, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_response": {"output": "hello world"},
        }

        with patch(
            "ai_guardian.scanners.secret_scanning.check_secrets"
        ) as mock_gitleaks:
            mock_gitleaks.return_value = (False, None)
            result = ai_guardian.process_hook_data(hook_data)

            assert result["exit_code"] == 0
            mock_gitleaks.assert_called_once()

    @patch("ai_guardian.config.loaders._load_secret_scanning_config")
    @patch("ai_guardian.hook_processing._load_pattern_server_config")
    @patch("ai_guardian.config.loaders._load_secret_redaction_config")
    def test_context_manager_init_failure_handled(
        self, mock_redaction, mock_pattern, mock_secret
    ):
        """If HookContextManager init fails, processing continues normally."""
        mock_pattern.return_value = None
        mock_redaction.return_value = (None, None)
        mock_secret.return_value = ({"enabled": True}, None)

        hook_data = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "toolu_fallback_001",
            "session_id": "session-fallback",
            "tool_name": "Read",
            "tool_response": {"output": "clean output"},
        }

        with patch(
            "ai_guardian.hook_context.HookContextManager.__init__",
            side_effect=Exception("init failed"),
        ):
            with patch(
                "ai_guardian.scanners.secret_scanning.check_secrets"
            ) as mock_gitleaks:
                mock_gitleaks.return_value = (False, None)
                result = ai_guardian.process_hook_data(hook_data)

                assert result["exit_code"] == 0
                mock_gitleaks.assert_called_once()


class TestHookContextManagerModes:
    """Test HookContextManager local vs daemon mode selection."""

    def test_temp_file_mode_round_trip(self, tmp_path):
        mgr = HookContextManager(session_id="local-test-session")
        mgr._context_file = tmp_path / "local-test.json"

        ctx = {
            "file_path": "/tmp/test.py",
            "tool_name": "Read",
            "scan_results": {"secrets_scanned": True, "secrets_found": False},
        }
        mgr.save_pretool_context("toolu_local_001", ctx)

        result = mgr.get_pretool_context("toolu_local_001")
        assert result == ctx

    def test_daemon_mode_round_trip(self, tmp_path):
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        mgr = HookContextManager(session_id="daemon-test", daemon_state=state)

        ctx = {"file_path": "/test.py", "tool_name": "Read"}
        mgr.save_pretool_context("toolu_daemon_001", ctx)

        result = mgr.get_pretool_context("toolu_daemon_001")
        assert result == ctx
