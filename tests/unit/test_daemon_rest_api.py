"""Tests for daemon REST API."""

import json
import os
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ai_guardian.daemon.rest_api import DaemonRestAPI


class MockDaemonState:
    """Minimal mock for DaemonState with pause/resume and stats."""

    def __init__(self):
        self._paused = False
        self._pause_minutes = 0
        self._config_reloaded = False

    def get_stats(self):
        return {
            "version": "1.9.0-dev",
            "request_count": 42,
            "blocked_count": 3,
            "paused": self._paused,
            "uptime_seconds": 300.0,
            "config_error": None,
            "mcp_installed": False,
        }

    def pause(self, minutes):
        self._paused = True
        self._pause_minutes = minutes

    def resume(self):
        self._paused = False
        self._pause_minutes = 0

    def force_reload_config(self):
        self._config_reloaded = True

    def get_config(self):
        return {
            "secret_scanning": {"enabled": True},
            "prompt_injection": {"enabled": True},
            "context_poisoning": {"enabled": True},
        }


@pytest.fixture
def rest_api():
    """Start a REST API server on a random port and yield (api, port)."""
    state = MockDaemonState()
    api = DaemonRestAPI(state=state, host="127.0.0.1", port=0)
    port = api.start()
    yield api, port, state
    api.stop()


class TestRestAPIEndpoints:
    def test_get_health(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/health"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "ok"

    def test_get_status(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/status"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["running"] is True
        assert data["name"] == "ai-guardian"

    def test_status_includes_mcp_installed(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/status"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "mcp_installed" in data
        assert data["mcp_installed"] is False

    def test_status_includes_menu_tags(self, rest_api):
        api, port, state = rest_api
        cfg = {"menu_tags": ["carbonite", "container"]}
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(cfg, None),
        ):
            url = f"http://127.0.0.1:{port}/api/status"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data["menu_tags"] == ["carbonite", "container"]

    def test_status_omits_menu_tags_when_empty(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/status"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "menu_tags" not in data

    def test_get_stats(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/stats"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["request_count"] == 42
        assert data["blocked_count"] == 3

    def test_stats_includes_menu_tags(self, rest_api):
        api, port, state = rest_api
        cfg = {"menu_tags": ["carbonite", "container"]}
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(cfg, None),
        ):
            url = f"http://127.0.0.1:{port}/api/stats"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data["menu_tags"] == ["carbonite", "container"]

    def test_stats_includes_mcp_installed(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/stats"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "mcp_installed" in data
        assert data["mcp_installed"] is False

    def test_stats_includes_version(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/stats"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "version" in data
        assert isinstance(data["version"], str)

    def test_about_endpoint(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/about"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "version" in data
        assert "python" in data
        assert "platform" in data
        assert "scanners" in data
        assert "url" in data

    def test_post_pause(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/pause"
        body = json.dumps({"minutes": 15}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "paused"
        assert data["minutes"] == 15
        assert state._paused is True

    def test_post_resume(self, rest_api):
        api, port, state = rest_api
        state.pause(15)

        url = f"http://127.0.0.1:{port}/api/resume"
        req = Request(url, data=b"", method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Content-Length", "0")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "resumed"
        assert state._paused is False

    def test_post_reload(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/reload"
        req = Request(url, data=b"", method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Content-Length", "0")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "config_reloaded"
        assert state._config_reloaded is True

    def test_unknown_path_returns_404(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/nonexistent"
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as exc_info:
            urlopen(url, timeout=5)
        assert exc_info.value.code == 404


class TestConfigEndpoint:
    def test_get_config_returns_features(self, rest_api):
        api, port, state = rest_api
        cfg = {
            "secret_scanning": {"enabled": True},
            "scan_pii": {"enabled": False},
        }
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(cfg, None),
        ):
            url = f"http://127.0.0.1:{port}/api/config"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert "features" in data
        assert data["features"]["secret_scanning"] is True
        assert data["features"]["scan_pii"] is False

    def test_get_config_no_config_file(self, rest_api):
        api, port, state = rest_api
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(None, None),
        ):
            url = f"http://127.0.0.1:{port}/api/config"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert "features" in data

    def test_get_config_includes_scanner_actions(self, rest_api):
        api, port, state = rest_api
        cfg = {
            "action": {"mode": "log"},
            "prompt_injection": {"action": "warn"},
        }
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(cfg, None),
        ):
            url = f"http://127.0.0.1:{port}/api/config"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        scanner_actions = data["features"]["scanner_actions"]
        assert "secret_scanning" not in scanner_actions
        assert scanner_actions["prompt_injection"] == "warn"
        assert scanner_actions["scan_pii"] == "log"  # falls back to global

    def test_get_config_includes_proactive_level(self, rest_api):
        api, port, state = rest_api
        cfg = {"mcp_server": {"proactive_level": "high"}}
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(cfg, None),
        ):
            url = f"http://127.0.0.1:{port}/api/config"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data["features"]["proactive_level"] == "high"


class TestViolationsEndpoint:
    def test_get_violations_returns_list(self, rest_api):
        api, port, state = rest_api
        mock_entries = [
            {
                "timestamp": "2026-05-01T10:00:00Z",
                "violation_type": "secret_detected",
                "severity": "high",
                "blocked": True,
                "context": {"tool": "Write", "file": "config.py", "line": 42},
                "suggestion": {"text": "Remove the secret"},
            },
        ]
        with mock.patch(
            "ai_guardian.hook_processing.ViolationLogger.get_recent_violations",
            return_value=mock_entries,
        ):
            url = f"http://127.0.0.1:{port}/api/violations"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data["count"] == 1
        v = data["violations"][0]
        assert v["type"] == "secret_detected"
        assert v["severity"] == "high"
        assert v["tool"] == "Write"
        assert v["file"] == "config.py"
        assert v["line"] == 42
        assert v["action"] == "blocked"
        assert v["suggestion"] == "Remove the secret"

    def test_get_violations_with_type_filter(self, rest_api):
        api, port, state = rest_api
        with mock.patch(
            "ai_guardian.hook_processing.ViolationLogger.get_recent_violations",
            return_value=[],
        ) as mock_get:
            url = f"http://127.0.0.1:{port}/api/violations?type=pii_detected&limit=10"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        mock_get.assert_called_once_with(limit=10, violation_type="pii_detected")
        assert data["count"] == 0

    def test_get_violations_empty(self, rest_api):
        api, port, state = rest_api
        with mock.patch(
            "ai_guardian.hook_processing.ViolationLogger.get_recent_violations",
            return_value=[],
        ):
            url = f"http://127.0.0.1:{port}/api/violations"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data == {"violations": [], "count": 0}


class TestMetricsEndpoint:
    def test_get_metrics_returns_summary(self, rest_api):
        api, port, state = rest_api
        mock_report = mock.MagicMock()
        mock_report.total_violations = 10
        mock_report.by_type = {"secret_detected": 5, "pii_detected": 5}
        mock_report.by_severity = {"high": 3, "warning": 7}
        mock_report.resolved_count = 2
        mock_report.unresolved_count = 8
        mock_report.cumulative_total = 50
        mock_report.cumulative_by_type = {"secret_detected": 30, "pii_detected": 20}
        mock_report.cumulative_since = "2026-01-01T00:00:00Z"
        with mock.patch(
            "ai_guardian.reporting.metrics.MetricsComputer.compute",
            return_value=mock_report,
        ):
            url = f"http://127.0.0.1:{port}/api/metrics"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data["total_violations"] == 10
        assert data["by_type"]["secret_detected"] == 5
        assert data["resolved"] == 2
        assert data["unresolved"] == 8

    def test_get_metrics_with_since_days(self, rest_api):
        api, port, state = rest_api
        mock_report = mock.MagicMock()
        mock_report.total_violations = 0
        mock_report.by_type = {}
        mock_report.by_severity = {}
        mock_report.resolved_count = 0
        mock_report.unresolved_count = 0
        mock_report.cumulative_total = 0
        mock_report.cumulative_by_type = {}
        mock_report.cumulative_since = ""
        with (
            mock.patch(
                "ai_guardian.reporting.metrics.MetricsComputer.__init__",
                return_value=None,
            ) as mock_init,
            mock.patch(
                "ai_guardian.reporting.metrics.MetricsComputer.compute",
                return_value=mock_report,
            ),
        ):
            url = f"http://127.0.0.1:{port}/api/metrics?since_days=7"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        mock_init.assert_called_once_with(since_days=7)
        assert data["total_violations"] == 0


class TestTrayPluginsEndpoint:
    def test_get_tray_plugins_returns_plugins(self, rest_api, tmp_path):
        api, port, state = rest_api
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "TestPlugin",
                    "items": [
                        {"label": "Hello", "command": "echo hi", "type": "background"}
                    ],
                }
            )
        )
        with (
            mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir", return_value=plugins_dir
            ),
            mock.patch(
                "ai_guardian.tray.plugins._load_bundled_plugins", return_value=[]
            ),
        ):
            url = f"http://127.0.0.1:{port}/api/tray-plugins"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert "plugins" in data
        assert len(data["plugins"]) == 1
        assert data["plugins"][0]["name"] == "TestPlugin"

    def test_get_tray_plugins_returns_empty_when_no_dir(self, rest_api, tmp_path):
        api, port, state = rest_api
        with (
            mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir",
                return_value=tmp_path / "nonexistent",
            ),
            mock.patch(
                "ai_guardian.tray.plugins._load_bundled_plugins", return_value=[]
            ),
            mock.patch(
                "ai_guardian.tray.plugins._get_bundled_plugins_dir",
                return_value=None,
            ),
        ):
            url = f"http://127.0.0.1:{port}/api/tray-plugins"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data == {"plugins": [], "files": []}

    def test_get_tray_plugins_with_multiple_plugins(self, rest_api, tmp_path):
        api, port, state = rest_api
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        for i in range(2):
            (plugins_dir / f"p{i}.json").write_text(
                json.dumps(
                    {
                        "name": f"Plugin{i}",
                        "items": [{"label": f"Item{i}", "command": f"cmd{i}"}],
                    }
                )
            )
        with (
            mock.patch(
                "ai_guardian.daemon.get_tray_plugins_dir", return_value=plugins_dir
            ),
            mock.patch(
                "ai_guardian.tray.plugins._load_bundled_plugins", return_value=[]
            ),
        ):
            url = f"http://127.0.0.1:{port}/api/tray-plugins"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        assert len(data["plugins"]) == 2


class TestRestAPILifecycle:
    def test_start_binds_port(self):
        state = MockDaemonState()
        api = DaemonRestAPI(state=state, host="127.0.0.1", port=0)
        port = api.start()
        assert port > 0
        assert api.port == port
        api.stop()

    def test_stop_shuts_down(self):
        state = MockDaemonState()
        api = DaemonRestAPI(state=state, host="127.0.0.1", port=0)
        port = api.start()
        api.stop()
        assert api._server is None

    def test_port_zero_before_start(self):
        state = MockDaemonState()
        api = DaemonRestAPI(state=state)
        assert api.port == 0


class TestCheckEndpoint:
    """Tests for POST /api/check."""

    def test_post_check_clean_content(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/check"
        body = json.dumps({"content": "Hello world"}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["clean"] is True
        assert data["findings"] == []
        assert data["redacted"] is None
        assert isinstance(data["elapsed_ms"], (int, float))

    def test_post_check_missing_content(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/check"
        body = json.dumps({}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 400

    def test_post_check_invalid_checks(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/check"
        body = json.dumps(
            {
                "content": "test",
                "checks": ["invalid_check"],
            }
        ).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 400

    def test_post_check_invalid_action(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/check"
        body = json.dumps(
            {
                "content": "test",
                "action": "invalid",
            }
        ).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 400

    def test_post_check_elapsed_ms(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/check"
        body = json.dumps({"content": "safe text"}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "elapsed_ms" in data
        assert data["elapsed_ms"] >= 0

    def test_post_check_specific_checks(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/check"
        body = json.dumps(
            {
                "content": "test",
                "checks": ["secrets"],
            }
        ).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["clean"] is True

    def test_post_check_with_findings(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/check"
        mock_result = mock.MagicMock()
        mock_result.detected = True
        mock_result.blocked = True
        mock_result.violation_type = "secret_detected"
        mock_result.message = "GitHub token detected"
        mock_result.details = None
        with mock.patch(
            "ai_guardian.sdk._DirectSession.check_content",
            return_value=mock_result,
        ):
            body = json.dumps({"content": "ghp_abc123"}).encode("utf-8")
            req = Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data["clean"] is False
        assert len(data["findings"]) >= 1
        assert data["findings"][0]["type"] == "secret_detected"
        assert data["redacted"] is not None


class TestRedactEndpoint:
    """Tests for POST /api/redact."""

    def test_post_redact_basic(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/redact"
        with mock.patch(
            "ai_guardian.scanners.sanitizer.sanitize_text",
            return_value={
                "sanitized_text": "my token is [REDACTED]",
                "redactions": [{"type": "secret"}],
                "stats": {"total": 1},
            },
        ):
            body = json.dumps(
                {
                    "content": "my token is ghp_abc123",
                }
            ).encode("utf-8")
            req = Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
        assert data["redacted"] == "my token is [REDACTED]"
        assert data["redaction_count"] == 1

    def test_post_redact_no_findings(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/redact"
        body = json.dumps({"content": "clean text"}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "redacted" in data
        assert data["redaction_count"] == 0

    def test_post_redact_missing_content(self, rest_api):
        api, port, state = rest_api
        url = f"http://127.0.0.1:{port}/api/redact"
        body = json.dumps({}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")

        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 400


class TestAuthEnforcement:
    """Tests for REST API authentication (#2143)."""

    @pytest.fixture
    def authed_api(self):
        """REST API with auth token enabled."""
        state = MockDaemonState()
        api = DaemonRestAPI(
            state=state, host="127.0.0.1", port=0, auth_token="test-secret-42"
        )
        port = api.start()
        yield api, port, state
        api.stop()

    def test_health_bypasses_auth(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/health"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "ok"

    def test_health_includes_paused_and_name(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/health"
        with urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "paused" in data
        assert "name" in data

    def test_get_status_rejected_without_token(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/status"
        with pytest.raises(HTTPError) as exc_info:
            urlopen(url, timeout=5)
        assert exc_info.value.code == 401

    def test_post_pause_rejected_without_token(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/pause"
        body = json.dumps({"minutes": 5}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 401

    def test_get_status_with_valid_token(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/status"
        req = Request(url, method="GET")
        req.add_header("Authorization", "Bearer test-secret-42")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["running"] is True

    def test_post_pause_with_valid_token(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/pause"
        body = json.dumps({"minutes": 5}).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer test-secret-42")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "paused"

    def test_wrong_token_rejected(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/status"
        req = Request(url, method="GET")
        req.add_header("Authorization", "Bearer wrong-token")
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 401

    def test_delete_rejected_without_token(self, authed_api):
        api, port, state = authed_api
        url = f"http://127.0.0.1:{port}/api/config"
        body = json.dumps({"section": "secret_scanning"}).encode("utf-8")
        req = Request(url, data=body, method="DELETE")
        req.add_header("Content-Type", "application/json")
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 401


class TestAuthTokenGeneration:
    """Tests for auto-generated auth token (#2143)."""

    def test_ensure_auth_token_generates_file(self, tmp_path):
        import sys

        from ai_guardian.daemon.server import DaemonServer

        token_path = tmp_path / "daemon.token"
        with mock.patch(
            "ai_guardian.daemon.get_auth_token_path",
            return_value=token_path,
        ):
            token = DaemonServer._ensure_auth_token()

        assert token_path.exists()
        assert len(token) > 20
        assert token_path.read_text().strip() == token
        if sys.platform != "win32":
            mode = oct(token_path.stat().st_mode & 0o777)
            assert mode == "0o600"

    def test_ensure_auth_token_reuses_existing(self, tmp_path):
        from ai_guardian.daemon.server import DaemonServer

        token_path = tmp_path / "daemon.token"
        token_path.write_text("existing-token-xyz")

        with mock.patch(
            "ai_guardian.daemon.get_auth_token_path",
            return_value=token_path,
        ):
            token = DaemonServer._ensure_auth_token()

        assert token == "existing-token-xyz"

    def test_ensure_auth_token_regenerates_empty_file(self, tmp_path):
        from ai_guardian.daemon.server import DaemonServer

        token_path = tmp_path / "daemon.token"
        token_path.write_text("")

        with mock.patch(
            "ai_guardian.daemon.get_auth_token_path",
            return_value=token_path,
        ):
            token = DaemonServer._ensure_auth_token()

        assert len(token) > 20
        assert token_path.read_text().strip() == token


class _HookMockDaemonState(MockDaemonState):
    """Extended mock with methods needed by _handle_hook."""

    def __init__(self):
        super().__init__()
        self._blocked_count = 0
        self._warning_count = 0
        self._log_only_count = 0
        self._activity_recorded = False
        self._dir_paused = set()

    @property
    def paused(self):
        return self._paused

    def check_project_config(self, cwd):
        pass

    def record_activity(self):
        self._activity_recorded = True

    def is_dir_paused(self, directory):
        return directory in self._dir_paused

    def record_blocked(self, violation_type=None):
        self._blocked_count += 1

    def record_warning(self):
        self._warning_count += 1

    def record_log_only(self):
        self._log_only_count += 1

    def mark_security_reinject(self, session_key):
        pass


class TestHookEndpoint:
    """Tests for POST /api/hook endpoint (#2146)."""

    @pytest.fixture
    def hook_api(self):
        state = _HookMockDaemonState()
        api = DaemonRestAPI(state=state, host="127.0.0.1", port=0)
        port = api.start()
        yield api, port, state
        api.stop()

    @pytest.fixture
    def authed_hook_api(self):
        state = _HookMockDaemonState()
        api = DaemonRestAPI(
            state=state, host="127.0.0.1", port=0, auth_token="hook-secret"
        )
        port = api.start()
        yield api, port, state
        api.stop()

    def test_hook_returns_result(self, hook_api):
        api, port, state = hook_api
        url = f"http://127.0.0.1:{port}/api/hook"
        hook_data = {"hook_event_name": "PreToolUse", "tool_name": "Bash"}
        payload = json.dumps(hook_data).encode()
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        with mock.patch(
            "ai_guardian.process_hook_data",
            return_value={"output": "{}", "exit_code": 0},
        ):
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

        assert "exit_code" in data
        assert data["exit_code"] == 0

    def test_hook_extracts_cwd(self, hook_api):
        api, port, state = hook_api
        url = f"http://127.0.0.1:{port}/api/hook"
        hook_data = {
            "hook_event_name": "PreToolUse",
            "_daemon_cwd": "/tmp/project",
        }
        payload = json.dumps(hook_data).encode()
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        captured_data = {}

        def mock_process(data, daemon_state=None):
            captured_data.update(data)
            return {"output": "{}", "exit_code": 0}

        with mock.patch("ai_guardian.process_hook_data", side_effect=mock_process):
            with urlopen(req, timeout=5) as resp:
                json.loads(resp.read())

        assert "_daemon_cwd" not in captured_data

    def test_hook_paused_returns_passthrough(self, hook_api):
        api, port, state = hook_api
        state._paused = True
        url = f"http://127.0.0.1:{port}/api/hook"
        hook_data = {"hook_event_name": "PreToolUse"}
        payload = json.dumps(hook_data).encode()
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        with mock.patch(
            "ai_guardian.inject_security_only",
            return_value=None,
        ):
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

        assert data["exit_code"] == 0

    def test_hook_requires_auth(self, authed_hook_api):
        api, port, state = authed_hook_api
        url = f"http://127.0.0.1:{port}/api/hook"
        payload = json.dumps({"hook_event_name": "PreToolUse"}).encode()
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 401

    def test_hook_with_valid_auth(self, authed_hook_api):
        api, port, state = authed_hook_api
        url = f"http://127.0.0.1:{port}/api/hook"
        payload = json.dumps({"hook_event_name": "PreToolUse"}).encode()
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer hook-secret")

        with mock.patch(
            "ai_guardian.process_hook_data",
            return_value={"output": "{}", "exit_code": 0},
        ):
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

        assert data["exit_code"] == 0
