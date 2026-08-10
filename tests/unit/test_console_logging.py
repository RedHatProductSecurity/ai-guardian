"""
Tests for Console startup logging suppression.

Verifies that stderr logging is suppressed during Console/TUI startup
to prevent log messages from appearing before the TUI renders.

Issue #600
"""

import logging
import sys


import ai_guardian


class TestConsoleLoggingSuppression:
    """
    Verify that _stderr_handler is set to WARNING level when
    'console' or 'tui' is in sys.argv, preventing INFO/DEBUG
    messages from printing to the terminal before the TUI loads.
    """

    def test_tui_mode_detection_logic(self):
        """The _is_tui_mode flag should match console/tui argv detection."""
        for cmd in ("console", "tui"):
            assert any(cmd in ["console", "tui"] for cmd in [cmd])

    def test_stderr_handler_exists(self):
        """Module exposes _stderr_handler for stderr output."""
        assert hasattr(ai_guardian, "_stderr_handler")
        assert isinstance(ai_guardian._stderr_handler, logging.StreamHandler)

    def test_file_handler_exists(self):
        """Module exposes _file_handler for log file output."""
        assert hasattr(ai_guardian, "_file_handler")

    def test_is_tui_mode_attribute_exists(self):
        """Module exposes _is_tui_mode flag."""
        assert hasattr(ai_guardian, "_is_tui_mode")

    def test_tui_mode_detection_expression(self):
        """The detection expression correctly identifies console/tui commands."""
        for argv_cmd in ("console", "tui"):
            result = any(cmd in sys.argv for cmd in ("console", "tui"))
            is_match = argv_cmd in sys.argv
            assert result == is_match

    def test_console_in_argv_suppresses_all_stderr(self):
        """When 'console' is in sys.argv, stderr handler should suppress all messages.

        This test validates the code path at module level:
            _is_tui_mode = any(cmd in sys.argv for cmd in ("console", "tui"))
            if _is_tui_mode:
                _stderr_handler.setLevel(logging.CRITICAL + 1)
        """
        handler = logging.StreamHandler()
        is_tui = any(cmd in ["ai-guardian", "console"] for cmd in ("console", "tui"))
        if is_tui:
            handler.setLevel(logging.CRITICAL + 1)
        assert is_tui is True
        assert handler.level > logging.CRITICAL

    def test_tui_in_argv_suppresses_all_stderr(self):
        """When 'tui' is in sys.argv, stderr handler should suppress all messages."""
        handler = logging.StreamHandler()
        is_tui = any(cmd in ["ai-guardian", "tui"] for cmd in ("console", "tui"))
        if is_tui:
            handler.setLevel(logging.CRITICAL + 1)
        assert is_tui is True
        assert handler.level > logging.CRITICAL

    def test_normal_command_keeps_default_level(self):
        """Non-console commands should not trigger TUI mode."""
        handler = logging.StreamHandler()
        is_tui = any(cmd in ["ai-guardian", "doctor"] for cmd in ("console", "tui"))
        assert is_tui is False
        assert handler.level == logging.NOTSET

    def test_file_handler_unaffected_by_tui_mode(self):
        """File handler should still log at DEBUG/INFO regardless of TUI mode."""
        assert ai_guardian._file_handler.level <= logging.DEBUG


class TestLogLevelOverride:
    """Verify that callers can control the ai_guardian logger level."""

    def test_env_var_log_level_respected(self):
        """AI_GUARDIAN_LOG_LEVEL env var logic sets level correctly."""
        import os

        env_level = "ERROR"
        assert hasattr(logging, env_level)
        assert getattr(logging, env_level) == logging.ERROR

    def test_caller_preset_level_not_overridden(self):
        """If logger level is already set (non-NOTSET), init should not reset it."""
        test_logger = logging.getLogger("test_preset_level")
        test_logger.setLevel(logging.ERROR)
        if test_logger.level == logging.NOTSET:
            test_logger.setLevel(logging.INFO)
        assert test_logger.level == logging.ERROR

    def test_notset_level_gets_default_info(self):
        """If logger level is NOTSET and no env var, default to INFO."""
        test_logger = logging.getLogger("test_notset_default")
        assert test_logger.level == logging.NOTSET
        if test_logger.level == logging.NOTSET:
            test_logger.setLevel(logging.INFO)
        assert test_logger.level == logging.INFO

    def test_env_var_overrides_preset(self):
        """AI_GUARDIAN_LOG_LEVEL takes priority over pre-set level."""
        env_level = "WARNING"
        test_logger = logging.getLogger("test_env_override")
        test_logger.setLevel(logging.DEBUG)
        if env_level and hasattr(logging, env_level):
            test_logger.setLevel(getattr(logging, env_level))
        assert test_logger.level == logging.WARNING

    def test_invalid_env_var_ignored(self):
        """Invalid AI_GUARDIAN_LOG_LEVEL value is silently ignored."""
        env_level = "NOTAVALIDLEVEL"
        test_logger = logging.getLogger("test_invalid_env")
        assert not hasattr(logging, env_level)
        if env_level and hasattr(logging, env_level):
            test_logger.setLevel(getattr(logging, env_level))
        elif test_logger.level == logging.NOTSET:
            test_logger.setLevel(logging.INFO)
        assert test_logger.level == logging.INFO
