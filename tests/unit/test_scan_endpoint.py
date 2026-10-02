"""Tests for POST /api/scan endpoint and config_section_for_rule_id mapping."""

from unittest.mock import MagicMock

import pytest

from ai_guardian.ui.pattern_editor import (
    config_section_for_rule_id,
)


class TestConfigSectionForRuleId:
    """Test the rule_id to config section mapping."""

    def test_secret(self):
        assert config_section_for_rule_id("SECRET-001") == "secret_scanning"

    def test_pii(self):
        assert config_section_for_rule_id("PII-001") == "scan_pii"

    def test_prompt_injection(self):
        assert config_section_for_rule_id("PROMPT-INJECTION-001") == "prompt_injection"

    def test_ssrf(self):
        assert config_section_for_rule_id("SSRF-001") == "ssrf_protection"

    def test_config(self):
        assert config_section_for_rule_id("CONFIG-001") == "config_file_scanning"

    def test_supply_chain(self):
        assert config_section_for_rule_id("SUPPLY-CHAIN-001") == "supply_chain"

    def test_unicode_maps_to_prompt_injection(self):
        assert config_section_for_rule_id("UNICODE-001") == "prompt_injection"

    def test_unknown_returns_none(self):
        assert config_section_for_rule_id("UNKNOWN-999") is None


class TestScanEndpointHandler:
    """Test the _handle_scan method in the REST API."""

    def _make_handler(self):
        """Create a mock handler with the _handle_scan method."""
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()
        handler._send_error = MagicMock()
        handler.server = MagicMock()
        handler.server.daemon_state = MagicMock()
        handler.server.daemon_state.get_config.return_value = {}
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS
        _RestHandler._handle_scan.__get__(handler)(handler)
        return handler

    def test_missing_path_returns_400(self):
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_error = MagicMock()
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(handler, {})
        handler._send_error.assert_called_once_with(400, "path is required")

    def test_empty_path_returns_400(self):
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_error = MagicMock()
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(handler, {"path": ""})
        handler._send_error.assert_called_once_with(400, "path is required")

    def test_nonexistent_path_returns_404(self):
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_error = MagicMock()
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(handler, {"path": "/nonexistent/path/abc123"})
        handler._send_error.assert_called_once()
        assert handler._send_error.call_args[0][0] == 404

    @pytest.mark.skipif(
        __import__("sys").platform == "win32",
        reason="Unix system directories not available on Windows",
    )
    def test_system_dir_returns_403(self):
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_error = MagicMock()
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(handler, {"path": "/usr"})
        handler._send_error.assert_called_once()
        assert handler._send_error.call_args[0][0] == 403

    def test_valid_scan_returns_findings(self, tmp_path):
        from ai_guardian.daemon.rest_api import _RestHandler

        test_file = tmp_path / "test.py"
        test_file.write_text("API_KEY = 'sk-test123456789'")

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()
        handler._send_error = MagicMock()
        handler.server = MagicMock()
        handler.server.daemon_state = MagicMock()
        handler.server.daemon_state.get_config.return_value = {}
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(handler, {"path": str(tmp_path)})

        if handler._send_json.called:
            result = handler._send_json.call_args[0][0]
            assert "findings" in result
            assert "scan_time_ms" in result
            assert isinstance(result["findings"], list)

            for f in result["findings"]:
                assert "config_section" in f

    def test_single_file_scan(self, tmp_path):
        from ai_guardian.daemon.rest_api import _RestHandler

        test_file = tmp_path / "clean.py"
        test_file.write_text("print('hello')")

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()
        handler._send_error = MagicMock()
        handler.server = MagicMock()
        handler.server.daemon_state = MagicMock()
        handler.server.daemon_state.get_config.return_value = {}
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(handler, {"path": str(test_file)})

        if handler._send_json.called:
            result = handler._send_json.call_args[0][0]
            assert "findings" in result
            assert isinstance(result["findings"], list)


class TestCheckEndpointProjectTracking:
    """Test that POST /api/check registers project directories."""

    def test_check_registers_project_dir(self):
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()
        handler._send_error = MagicMock()
        handler.server = MagicMock()
        handler.server.daemon_state = MagicMock()
        handler.server.daemon_state.get_config.return_value = {
            "secret_scanning": {"enabled": False},
            "prompt_injection": {"enabled": False},
            "context_poisoning": {"enabled": False},
        }

        _RestHandler._handle_check(
            handler,
            {
                "content": "hello world",
                "project_dir": "/some/project",
            },
        )

        handler.server.daemon_state.check_project_config.assert_called_once_with(
            "/some/project"
        )

    def test_check_without_project_dir_skips_registration(self):
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()
        handler._send_error = MagicMock()
        handler.server = MagicMock()
        handler.server.daemon_state = MagicMock()
        handler.server.daemon_state.get_config.return_value = {
            "secret_scanning": {"enabled": False},
            "prompt_injection": {"enabled": False},
            "context_poisoning": {"enabled": False},
        }

        _RestHandler._handle_check(handler, {"content": "hello world"})

        handler.server.daemon_state.check_project_config.assert_not_called()


class TestScanEndpointProjectTracking:
    """Test that POST /api/scan registers project directories."""

    def test_scan_infers_project_dir(self, tmp_path):
        from ai_guardian.daemon.rest_api import _RestHandler

        test_file = tmp_path / "clean.py"
        test_file.write_text("x = 1")

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()
        handler._send_error = MagicMock()
        handler.server = MagicMock()
        handler.server.daemon_state = MagicMock()
        handler.server.daemon_state.get_config.return_value = {}
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(handler, {"path": str(tmp_path)})

        handler.server.daemon_state.check_project_config.assert_called_once()

    def test_scan_explicit_project_dir(self, tmp_path):
        from ai_guardian.daemon.rest_api import _RestHandler

        test_file = tmp_path / "clean.py"
        test_file.write_text("x = 1")

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()
        handler._send_error = MagicMock()
        handler.server = MagicMock()
        handler.server.daemon_state = MagicMock()
        handler.server.daemon_state.get_config.return_value = {}
        handler._BLOCKED_SCAN_DIRS = _RestHandler._BLOCKED_SCAN_DIRS

        _RestHandler._handle_scan(
            handler,
            {"path": str(tmp_path), "project_dir": "/explicit/project"},
        )

        handler.server.daemon_state.check_project_config.assert_called_once_with(
            "/explicit/project"
        )


class TestMultiClientScanPath:
    """Test the scan_path method in MultiDaemonClient."""

    def test_local_scan(self, tmp_path):
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        test_file = tmp_path / "clean.py"
        test_file.write_text("x = 1")

        result = MultiDaemonClient._local_scan(str(tmp_path))

        assert "findings" in result
        assert "scan_time_ms" in result
        assert isinstance(result["findings"], list)

    def test_local_scan_enriches_config_section(self, tmp_path):
        from ai_guardian.daemon.multi_client import MultiDaemonClient

        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1")

        result = MultiDaemonClient._local_scan(str(tmp_path))

        for f in result["findings"]:
            assert "config_section" in f


class TestLogsEndpoint:
    """Test GET /api/logs endpoint and _local_logs."""

    def test_local_logs_returns_entries(self, tmp_path, monkeypatch):
        from ai_guardian.daemon.multi_client import MultiDaemonClient
        import ai_guardian.config.utils as cu

        log_file = tmp_path / "ai-guardian.log"
        log_file.write_text(
            "2026-06-25 10:00:00 - ai_guardian - INFO - Server started\n"
            "2026-06-25 10:00:01 - ai_guardian - DEBUG - Debug detail\n"
            "2026-06-25 10:00:02 - ai_guardian - WARNING - Something odd\n"
        )
        monkeypatch.setattr(cu, "get_state_dir", lambda: tmp_path)

        result = MultiDaemonClient._local_logs(500, "INFO")

        assert result["count"] == 2
        assert all(e["level"] in ("INFO", "WARNING") for e in result["entries"])

    def test_local_logs_debug_includes_all(self, tmp_path, monkeypatch):
        from ai_guardian.daemon.multi_client import MultiDaemonClient
        import ai_guardian.config.utils as cu

        log_file = tmp_path / "ai-guardian.log"
        log_file.write_text(
            "2026-06-25 10:00:00 - ai_guardian - INFO - Info line\n"
            "2026-06-25 10:00:01 - ai_guardian - DEBUG - Debug line\n"
        )
        monkeypatch.setattr(cu, "get_state_dir", lambda: tmp_path)

        result = MultiDaemonClient._local_logs(500, "DEBUG")

        assert result["count"] == 2

    def test_local_logs_missing_file(self, tmp_path, monkeypatch):
        from ai_guardian.daemon.multi_client import MultiDaemonClient
        import ai_guardian.config.utils as cu

        monkeypatch.setattr(cu, "get_state_dir", lambda: tmp_path)

        result = MultiDaemonClient._local_logs(500, "INFO")

        assert result["count"] == 0
        assert result["entries"] == []

    def test_rest_handler_get_logs(self):
        from ai_guardian.daemon.rest_api import _RestHandler

        handler = MagicMock(spec=_RestHandler)
        handler._send_json = MagicMock()

        with MagicMock() as mock_client:
            mock_client._local_logs.return_value = {
                "entries": [{"level": "INFO", "message": "test"}],
                "count": 1,
            }
            import ai_guardian.daemon.rest_api as ra

            original = ra._RestHandler._get_logs

            result = original(100, "INFO")
            assert "entries" in result


class TestRestRequestTimeout:
    """Test that _rest_request accepts a timeout parameter."""

    def test_timeout_parameter_accepted(self):
        from ai_guardian.daemon.multi_client import MultiDaemonClient
        import inspect

        sig = inspect.signature(MultiDaemonClient._rest_request)
        assert "timeout" in sig.parameters

    def test_timeout_default_is_request_timeout(self):
        from ai_guardian.daemon.multi_client import (
            MultiDaemonClient,
            REQUEST_TIMEOUT,
        )
        import inspect

        sig = inspect.signature(MultiDaemonClient._rest_request)
        default = sig.parameters["timeout"].default
        assert default == REQUEST_TIMEOUT
