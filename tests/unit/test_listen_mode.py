"""Tests for listen mode (#1590)."""

import json
import sys
import threading
from unittest import mock

import pytest

from ai_guardian.scanners.listen_mode import (
    LeakTKListenProcess,
    ListenModeManager,
    parse_listen_results,
)
from ai_guardian.scanners.output_parsers import _normalize_leaktk_result

# --- _normalize_leaktk_result ---


class TestNormalizeLeaktkResult:
    def test_full_result(self):
        result = {
            "rule": {"id": "aws-key", "description": "AWS Access Key"},
            "location": {
                "path": "/tmp/test.py",
                "start": {"line": 10, "column": 5},
                "end": {"line": 10, "column": 45},
                "version": "abc123",
            },
            "match": "some-matched-text",
            "secret": "redacted-secret-value",
        }
        normalized = _normalize_leaktk_result(result)
        assert normalized["rule_id"] == "aws-key"
        assert normalized["description"] == "AWS Access Key"
        assert normalized["file"] == "/tmp/test.py"
        assert normalized["line_number"] == 10
        assert normalized["start_column"] == 5
        assert normalized["end_line"] == 10
        assert normalized["end_column"] == 45
        assert normalized["matched_text"] == "some-matched-text"
        assert normalized["commit"] == "abc123"

    def test_missing_optional_fields(self):
        result = {"rule": {}, "location": {}}
        normalized = _normalize_leaktk_result(result)
        assert normalized["rule_id"] == "unknown"
        assert normalized["file"] == "unknown"
        assert normalized["line_number"] == 0
        assert normalized["matched_text"] == ""

    def test_empty_result(self):
        normalized = _normalize_leaktk_result({})
        assert normalized["rule_id"] == "unknown"
        assert normalized["line_number"] == 0


# --- parse_listen_results ---


class TestParseListenResults:
    def test_with_findings(self):
        response = {
            "kind": "ScanResults",
            "request_id": "req1",
            "results": [
                {
                    "rule": {"id": "jwt", "description": "JSON Web Token"},
                    "location": {
                        "path": "/tmp/file.py",
                        "start": {"line": 5, "column": 1},
                        "end": {"line": 5, "column": 80},
                    },
                    "match": "eyJ...",
                }
            ],
        }
        parsed = parse_listen_results(response)
        assert parsed["has_secrets"] is True
        assert parsed["total_findings"] == 1
        assert parsed["findings"][0]["rule_id"] == "jwt"
        assert parsed["findings"][0]["line_number"] == 5

    def test_empty_results(self):
        response = {"kind": "ScanResults", "request_id": "req1", "results": []}
        parsed = parse_listen_results(response)
        assert parsed["has_secrets"] is False
        assert parsed["total_findings"] == 0

    def test_no_results_key(self):
        parsed = parse_listen_results({"kind": "ScanResults"})
        assert parsed["has_secrets"] is False

    def test_multiple_findings(self):
        response = {
            "results": [
                {
                    "rule": {"id": "r1"},
                    "location": {"start": {"line": 1}, "end": {}},
                },
                {
                    "rule": {"id": "r2"},
                    "location": {"start": {"line": 2}, "end": {}},
                },
            ]
        }
        parsed = parse_listen_results(response)
        assert parsed["total_findings"] == 2
        assert parsed["findings"][0]["rule_id"] == "r1"
        assert parsed["findings"][1]["rule_id"] == "r2"


# --- LeakTKListenProcess ---


def _make_started_proc(**stdout_kwargs):
    """Create a started LeakTKListenProcess with a mock subprocess."""
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = mock.MagicMock()
    for k, v in stdout_kwargs.items():
        setattr(mock_proc.stdout, k, v)
    mock_proc.stderr = iter([])

    proc = LeakTKListenProcess("leaktk")
    with mock.patch("ai_guardian.scanners.listen_mode.subprocess.Popen") as m:
        m.return_value = mock_proc
        proc.start()
    return proc, mock_proc


class TestLeakTKListenProcess:
    def test_start_spawns_process(self):
        with mock.patch("ai_guardian.scanners.listen_mode.subprocess.Popen") as m:
            m.return_value.poll.return_value = None
            m.return_value.stderr = iter([])
            proc = LeakTKListenProcess("leaktk")
            proc.start()
            assert proc.is_alive()
            m.assert_called_once()
            cmd = m.call_args[0][0]
            assert cmd == ["leaktk", "listen", "--format", "json"]

    def test_start_with_config(self):
        with mock.patch("ai_guardian.scanners.listen_mode.subprocess.Popen") as m:
            m.return_value.poll.return_value = None
            m.return_value.stderr = iter([])
            proc = LeakTKListenProcess("leaktk", config_path="/etc/leaktk.toml")
            proc.start()
            cmd = m.call_args[0][0]
            assert "--config" in cmd
            assert "/etc/leaktk.toml" in cmd

    def test_is_alive_false_when_not_started(self):
        proc = LeakTKListenProcess("leaktk")
        assert proc.is_alive() is False

    def test_is_alive_false_when_exited(self):
        with mock.patch("ai_guardian.scanners.listen_mode.subprocess.Popen") as m:
            m.return_value.poll.return_value = 0
            m.return_value.stderr = iter([])
            proc = LeakTKListenProcess("leaktk")
            proc.start()
            assert proc.is_alive() is False

    def test_scan_writes_request_reads_response(self):
        response_json = json.dumps(
            {"kind": "ScanResults", "request_id": "abc", "results": []}
        )
        proc, mock_proc = _make_started_proc(
            readline=mock.MagicMock(return_value=(response_json + "\n").encode())
        )

        with mock.patch(
            "ai_guardian.scanners.listen_mode.select.select",
            return_value=([mock_proc.stdout], [], []),
        ):
            result = proc.scan("/tmp/test.txt", "req123")
        assert result["has_secrets"] is False

        written = mock_proc.stdin.write.call_args[0][0].decode()
        request = json.loads(written)
        assert request["kind"] == "Files"
        assert request["id"] == "req123"
        assert request["resource"] == "/tmp/test.txt"

    def test_scan_raises_when_not_alive(self):
        proc = LeakTKListenProcess("leaktk")
        with pytest.raises(RuntimeError, match="not running"):
            proc.scan("/tmp/test.txt", "req1")

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="select on pipes not supported on Windows",
    )
    def test_scan_raises_on_timeout(self):
        proc, mock_proc = _make_started_proc()

        with mock.patch(
            "ai_guardian.scanners.listen_mode.select.select", return_value=([], [], [])
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                proc.scan("/tmp/test.txt", "req1")
        mock_proc.kill.assert_called_once()

    def test_scan_raises_on_empty_response(self):
        proc, mock_proc = _make_started_proc(readline=mock.MagicMock(return_value=b""))

        with mock.patch(
            "ai_guardian.scanners.listen_mode.select.select",
            return_value=([mock_proc.stdout], [], []),
        ):
            with pytest.raises(RuntimeError, match="empty response"):
                proc.scan("/tmp/test.txt", "req1")

    def test_stop_closes_stdin_and_waits(self):
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.stdin.closed = False
        mock_proc.stderr = iter([])

        proc = LeakTKListenProcess("leaktk")
        with mock.patch("ai_guardian.scanners.listen_mode.subprocess.Popen") as m:
            m.return_value = mock_proc
            proc.start()

        proc.stop()
        mock_proc.stdin.close.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=5)
        assert proc._process is None

    def test_stop_kills_on_timeout(self):
        from subprocess import TimeoutExpired

        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [TimeoutExpired("leaktk", 5), None]
        mock_proc.stderr = iter([])

        proc = LeakTKListenProcess("leaktk")
        with mock.patch("ai_guardian.scanners.listen_mode.subprocess.Popen") as m:
            m.return_value = mock_proc
            proc.start()

        proc.stop()
        mock_proc.kill.assert_called_once()


# --- ListenModeManager ---


class TestListenModeManager:
    def test_lazy_start(self):
        mgr = ListenModeManager()
        assert mgr.is_alive() is False

        with mock.patch(
            "ai_guardian.scanners.listen_mode.LeakTKListenProcess"
        ) as MockProc:
            mock_instance = MockProc.return_value
            mock_instance.is_alive.return_value = True
            mock_instance.scan.return_value = {
                "has_secrets": False,
                "findings": [],
                "total_findings": 0,
            }

            result = mgr.scan("leaktk", "/tmp/test.txt")
            mock_instance.start.assert_called_once()
            assert result["has_secrets"] is False

    def test_reuses_existing_process(self):
        mgr = ListenModeManager()
        with mock.patch(
            "ai_guardian.scanners.listen_mode.LeakTKListenProcess"
        ) as MockProc:
            mock_instance = MockProc.return_value
            mock_instance.is_alive.return_value = True
            mock_instance.scan.return_value = {
                "has_secrets": False,
                "findings": [],
                "total_findings": 0,
            }

            mgr.scan("leaktk", "/tmp/a.txt")
            mgr.scan("leaktk", "/tmp/b.txt")
            assert MockProc.call_count == 1

    def test_restarts_dead_process(self):
        mgr = ListenModeManager()
        with mock.patch(
            "ai_guardian.scanners.listen_mode.LeakTKListenProcess"
        ) as MockProc:
            mock_instance = MockProc.return_value
            mock_instance.is_alive.side_effect = [False, True]
            mock_instance.scan.return_value = {
                "has_secrets": False,
                "findings": [],
                "total_findings": 0,
            }

            mgr._process = mock_instance
            mgr.scan("leaktk", "/tmp/test.txt")
            mock_instance.stop.assert_called_once()
            assert MockProc.call_count == 1

    def test_stop(self):
        mgr = ListenModeManager()
        mock_proc = mock.MagicMock()
        mgr._process = mock_proc
        mgr.stop()
        mock_proc.stop.assert_called_once()
        assert mgr._process is None

    def test_stop_when_no_process(self):
        mgr = ListenModeManager()
        mgr.stop()

    def test_restart(self):
        mgr = ListenModeManager()
        mock_proc = mock.MagicMock()
        mgr._process = mock_proc
        mgr.restart()
        mock_proc.stop.assert_called_once()
        assert mgr._process is None


# --- executor.py listen mode integration ---


class TestRunEngineListenMode:
    def test_uses_listen_mode_when_daemon_active(self):
        from ai_guardian.scanners.executor import run_engine
        from ai_guardian.scanners.engine_builder import ENGINE_PRESETS

        engine_config = ENGINE_PRESETS["leaktk"]
        mock_mgr = mock.MagicMock()
        mock_mgr.scan.return_value = {
            "has_secrets": False,
            "findings": [],
            "total_findings": 0,
        }
        mock_state = mock.MagicMock()
        mock_state.get_listen_manager.return_value = mock_mgr

        with mock.patch(
            "ai_guardian.scanners.executor._get_daemon_state",
            return_value=mock_state,
        ):
            result = run_engine(engine_config, "/tmp/test.txt", "/tmp/report.json")

        assert result.has_secrets is False
        mock_mgr.scan.assert_called_once()

    def test_falls_back_when_no_daemon(self):
        from ai_guardian.scanners.executor import run_engine
        from ai_guardian.scanners.engine_builder import ENGINE_PRESETS

        engine_config = ENGINE_PRESETS["leaktk"]

        with (
            mock.patch(
                "ai_guardian.scanners.executor._get_daemon_state",
                return_value=None,
            ),
            mock.patch(
                "ai_guardian.scanners.executor.run_single_engine"
            ) as mock_single,
        ):
            mock_single.return_value = mock.MagicMock(has_secrets=False)
            run_engine(engine_config, "/tmp/test.txt", "/tmp/report.json")
            mock_single.assert_called_once()

    def test_falls_back_on_listen_exception(self):
        from ai_guardian.scanners.executor import run_engine
        from ai_guardian.scanners.engine_builder import ENGINE_PRESETS

        engine_config = ENGINE_PRESETS["leaktk"]
        mock_state = mock.MagicMock()
        mock_state.get_listen_manager.side_effect = RuntimeError("boom")

        with (
            mock.patch(
                "ai_guardian.scanners.executor._get_daemon_state",
                return_value=mock_state,
            ),
            mock.patch(
                "ai_guardian.scanners.executor.run_single_engine"
            ) as mock_single,
        ):
            mock_single.return_value = mock.MagicMock(has_secrets=False)
            run_engine(engine_config, "/tmp/test.txt", "/tmp/report.json")
            mock_single.assert_called_once()

    def test_version_hint_appended_on_unexpected_exit_code(self):
        from ai_guardian.scanners.executor import run_single_engine
        from ai_guardian.scanners.engine_builder import EngineConfig

        config = EngineConfig(
            type="test-engine",
            binary="test-bin",
            command_template=["{binary}", "{source_file}"],
            output_parser="gitleaks",
            version_hint="test-engine >= 2.0 required",
        )
        proc = mock.MagicMock()
        proc.returncode = 99
        proc.stderr = "something went wrong"
        proc.stdout = ""

        with (
            mock.patch(
                "ai_guardian.scanners.executor.subprocess.run",
                return_value=proc,
            ),
            mock.patch("ai_guardian.scanners.executor.logger") as mock_logger,
        ):
            result = run_single_engine(config, "/tmp/test.txt", "/tmp/report.json")

        assert result.has_secrets is False
        assert result.error is not None
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "test-engine >= 2.0 required" in warning_msg

    def test_engine_without_listen_support_skips_listen_mode(self):
        from ai_guardian.scanners.executor import run_engine
        from ai_guardian.scanners.engine_builder import ENGINE_PRESETS

        engine_config = ENGINE_PRESETS["gitleaks"]
        assert not engine_config.supports_listen_mode

        with mock.patch(
            "ai_guardian.scanners.executor.run_single_engine"
        ) as mock_single:
            mock_single.return_value = mock.MagicMock(has_secrets=False)
            run_engine(engine_config, "/tmp/test.txt", "/tmp/report.json")
            mock_single.assert_called_once()


# --- Listen mode cache integration (#1721) ---


class TestListenModeCaching:
    def test_cache_hit_skips_listen_scan(self):
        from ai_guardian.scanners.executor import run_engine
        from ai_guardian.scanners.engine_builder import ENGINE_PRESETS
        from ai_guardian.scanners.strategies import ScanResult

        engine_config = ENGINE_PRESETS["leaktk"]
        cached_result = ScanResult(has_secrets=False, secrets=[], engine="leaktk")

        mock_cache = mock.MagicMock()
        mock_cache.get.return_value = cached_result

        with mock.patch(
            "ai_guardian.scanners.executor._get_daemon_state"
        ) as mock_daemon:
            result = run_engine(
                engine_config,
                "/tmp/test.txt",
                "/tmp/report.json",
                cache=mock_cache,
                content_hash="abc123",
            )

        assert result is cached_result
        mock_daemon.assert_not_called()

    def test_cache_miss_calls_listen_and_stores(self):
        from ai_guardian.scanners.executor import run_engine
        from ai_guardian.scanners.engine_builder import ENGINE_PRESETS

        engine_config = ENGINE_PRESETS["leaktk"]

        mock_cache = mock.MagicMock()
        mock_cache.get.return_value = None

        mock_mgr = mock.MagicMock()
        mock_mgr.scan.return_value = {
            "has_secrets": False,
            "findings": [],
            "total_findings": 0,
        }
        mock_state = mock.MagicMock()
        mock_state.get_listen_manager.return_value = mock_mgr

        with mock.patch(
            "ai_guardian.scanners.executor._get_daemon_state",
            return_value=mock_state,
        ):
            result = run_engine(
                engine_config,
                "/tmp/test.txt",
                "/tmp/report.json",
                cache=mock_cache,
                content_hash="abc123",
            )

        assert result.has_secrets is False
        mock_mgr.scan.assert_called_once()
        mock_cache.put.assert_called_once()

    def test_no_cache_when_hash_missing(self):
        from ai_guardian.scanners.executor import run_engine
        from ai_guardian.scanners.engine_builder import ENGINE_PRESETS

        engine_config = ENGINE_PRESETS["leaktk"]

        mock_mgr = mock.MagicMock()
        mock_mgr.scan.return_value = {
            "has_secrets": False,
            "findings": [],
            "total_findings": 0,
        }
        mock_state = mock.MagicMock()
        mock_state.get_listen_manager.return_value = mock_mgr

        with mock.patch(
            "ai_guardian.scanners.executor._get_daemon_state",
            return_value=mock_state,
        ):
            result = run_engine(
                engine_config,
                "/tmp/test.txt",
                "/tmp/report.json",
            )

        assert result.has_secrets is False
        mock_mgr.scan.assert_called_once()


# --- DaemonState integration ---


class TestDaemonStateListenManager:
    def test_lazy_init(self, tmp_path):
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        assert state._listen_manager is None
        mgr = state.get_listen_manager()
        assert mgr is not None
        assert state._listen_manager is mgr

    def test_returns_same_instance(self, tmp_path):
        from ai_guardian.daemon.state import DaemonState

        state = DaemonState(config_path=tmp_path / "nonexistent.json")
        mgr1 = state.get_listen_manager()
        mgr2 = state.get_listen_manager()
        assert mgr1 is mgr2


# --- LeakTKOutputParser v0.3.x format ---


class TestLeakTKOutputParserV03:
    def test_parse_new_format(self, tmp_path):
        from ai_guardian.scanners.output_parsers import LeakTKOutputParser

        data = {
            "kind": "ScanResults",
            "results": [
                {
                    "rule": {"id": "priv-key", "description": "Private Key"},
                    "location": {
                        "path": "/tmp/f.py",
                        "start": {"line": 3, "column": 1},
                        "end": {"line": 5, "column": 30},
                    },
                    "match": "-----BEGIN RSA",
                }
            ],
        }
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data))

        parser = LeakTKOutputParser()
        result = parser.parse(str(report))
        assert result["has_secrets"] is True
        assert result["total_findings"] == 1
        assert result["findings"][0]["rule_id"] == "priv-key"
        assert result["findings"][0]["line_number"] == 3

    def test_parse_new_format_clean(self, tmp_path):
        from ai_guardian.scanners.output_parsers import LeakTKOutputParser

        data = {"kind": "ScanResults", "results": []}
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data))

        parser = LeakTKOutputParser()
        result = parser.parse(str(report))
        assert result["has_secrets"] is False

    def test_parse_legacy_format_still_works(self, tmp_path):
        from ai_guardian.scanners.output_parsers import LeakTKOutputParser

        data = {
            "findings": [
                {
                    "RuleID": "old-rule",
                    "File": "test.py",
                    "StartLine": 7,
                    "Description": "Old secret",
                }
            ],
            "errors": [],
        }
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data))

        parser = LeakTKOutputParser()
        result = parser.parse(str(report))
        assert result["has_secrets"] is True
        assert result["findings"][0]["rule_id"] == "old-rule"
        assert result["findings"][0]["line_number"] == 7
