#!/usr/bin/env python3
"""
Tests for the Engine Tester core logic.

Tests engine testing, formatting, and CLI command without requiring
real scanner binaries — all subprocess calls are mocked.
"""

import json
import types
from io import StringIO
from unittest.mock import MagicMock, patch


from ai_guardian.scanners.engine_tester import (
    EngineTestResult,
    _try_daemon_engine_test,
    apply_strategy,
    engine_test_command,
    format_comparison,
    format_result,
    get_available_engines,
    get_configured_strategy,
    test_all_engines as _test_all_engines,
    test_engine as _test_engine,
)
from ai_guardian.scanners.strategies import ScanResult, SecretMatch

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_secret(rule_id="generic-api-key", line=1, desc="API key detected"):
    return SecretMatch(
        rule_id=rule_id,
        description=desc,
        file="test_input.txt",
        line_number=line,
        engine="gitleaks",
    )


def _scan_result_found(engine="gitleaks", secrets=None, time_ms=42.0):
    return ScanResult(
        has_secrets=True,
        secrets=secrets or [_make_secret()],
        engine=engine,
        scan_time_ms=time_ms,
    )


def _scan_result_clean(engine="gitleaks", time_ms=35.0):
    return ScanResult(
        has_secrets=False,
        secrets=[],
        engine=engine,
        scan_time_ms=time_ms,
    )


def _scan_result_error(engine="trufflehog", msg="Binary not found: trufflehog"):
    return ScanResult(
        has_secrets=False,
        secrets=[],
        engine=engine,
        error=msg,
        scan_time_ms=0.0,
    )


# ---------------------------------------------------------------------------
# get_available_engines
# ---------------------------------------------------------------------------


class TestGetAvailableEngines:

    @patch("ai_guardian._load_secret_scanning_config")
    def test_returns_configured_engines(self, mock_cfg):
        mock_cfg.return_value = ({"engines": ["betterleaks", "gitleaks"]}, None)
        result = get_available_engines()
        assert result == ["betterleaks", "gitleaks"]

    @patch("ai_guardian._load_secret_scanning_config")
    def test_dict_entries(self, mock_cfg):
        mock_cfg.return_value = (
            {"engines": [{"type": "betterleaks"}, {"type": "gitleaks"}]},
            None,
        )
        result = get_available_engines()
        assert result == ["betterleaks", "gitleaks"]

    @patch("ai_guardian._load_secret_scanning_config")
    def test_default_gitleaks_when_no_config(self, mock_cfg):
        mock_cfg.return_value = (None, None)
        assert get_available_engines() == ["gitleaks"]

    @patch("ai_guardian._load_secret_scanning_config")
    def test_default_gitleaks_appended_if_missing(self, mock_cfg):
        mock_cfg.return_value = ({"engines": ["betterleaks"]}, None)
        result = get_available_engines()
        assert result == ["betterleaks", "gitleaks"]

    @patch("ai_guardian._load_secret_scanning_config")
    def test_no_duplicate_gitleaks(self, mock_cfg):
        mock_cfg.return_value = ({"engines": ["gitleaks", "betterleaks"]}, None)
        result = get_available_engines()
        assert result.count("gitleaks") == 1


# ---------------------------------------------------------------------------
# test_engine
# ---------------------------------------------------------------------------


class TestTestEngine:

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    def test_found_secret(self, mock_run):
        mock_run.return_value = _scan_result_found()
        result = _test_engine("gitleaks", "AKIAIOSFODNN7EXAMPLE")
        assert result.found is True
        assert len(result.secrets) == 1
        assert result.secrets[0].rule_id == "generic-api-key"
        assert result.engine == "gitleaks"
        assert result.error is None

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    def test_no_secret(self, mock_run):
        mock_run.return_value = _scan_result_clean()
        result = _test_engine("gitleaks", "safe text")
        assert result.found is False
        assert result.secrets == []

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    def test_engine_error(self, mock_run):
        mock_run.return_value = _scan_result_error()
        result = _test_engine("trufflehog", "test")
        assert result.found is False
        assert "Binary not found" in result.error

    def test_unknown_engine(self):
        result = _test_engine("nonexistent", "test")
        assert result.found is False
        assert "Unknown engine" in result.error

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    def test_pattern_server_off(self, mock_run):
        mock_run.return_value = _scan_result_clean()
        _test_engine("gitleaks", "test", use_pattern_server=False)
        _, kwargs = mock_run.call_args
        assert kwargs.get("config_path") is None

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    def test_scan_time_propagated(self, mock_run):
        mock_run.return_value = _scan_result_clean(time_ms=123.4)
        result = _test_engine("gitleaks", "test")
        assert result.scan_time_ms == 123.4

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    @patch("ai_guardian.scanners.engine_tester._build_engine_config")
    def test_toml_patterns_engine(self, mock_build, mock_run):
        from ai_guardian.scanners.engine_builder import EngineConfig

        mock_scanner = MagicMock()
        mock_scanner.name = "toml-patterns"
        mock_build.return_value = EngineConfig(
            type="python",
            binary="__python__",
            command_template=[],
            python_scanner=mock_scanner,
        )
        mock_run.return_value = _scan_result_found(engine="toml-patterns")
        result = _test_engine("toml-patterns", "export GITLAB_TOKEN=glpat-xxx")
        assert result.found is True
        assert result.engine == "toml-patterns"
        assert result.error is None


# ---------------------------------------------------------------------------
# test_all_engines
# ---------------------------------------------------------------------------


class TestTestAllEngines:

    @patch("ai_guardian.scanners.engine_tester.test_engine")
    @patch("ai_guardian.scanners.engine_tester.get_available_engines")
    def test_runs_all(self, mock_avail, mock_test):
        mock_avail.return_value = ["gitleaks", "betterleaks"]
        mock_test.side_effect = [
            EngineTestResult("gitleaks", True, [_make_secret()], 40),
            EngineTestResult("betterleaks", False, [], 35),
        ]
        results = _test_all_engines("test text")
        assert len(results) == 2
        assert results[0].found is True
        assert results[1].found is False

    @patch("ai_guardian.scanners.engine_tester.get_available_engines")
    def test_empty_when_none_installed(self, mock_avail):
        mock_avail.return_value = []
        assert _test_all_engines("test") == []


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatResult:

    def test_found(self):
        r = EngineTestResult("gitleaks", True, [_make_secret()], 42)
        text = format_result(r)
        assert "gitleaks" in text
        assert "FOUND" in text
        assert "generic-api-key" in text

    def test_not_found(self):
        r = EngineTestResult("betterleaks", False, [], 35)
        text = format_result(r)
        assert "NOT FOUND" in text

    def test_error(self):
        r = EngineTestResult("trufflehog", False, [], 0, error="Binary not found")
        text = format_result(r)
        assert "ERROR" in text
        assert "Binary not found" in text


class TestFormatComparison:

    def test_table(self):
        results = [
            EngineTestResult("gitleaks", True, [_make_secret()], 42),
            EngineTestResult("betterleaks", False, [], 35),
        ]
        text = format_comparison(results)
        assert "Engine" in text
        assert "gitleaks" in text
        assert "betterleaks" in text
        assert "FOUND" in text
        assert "NOT FOUND" in text

    def test_empty(self):
        text = format_comparison([])
        assert "No engines" in text


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


class TestEngineTestCommand:

    def _make_args(self, **kwargs):
        defaults = {
            "engine": None,
            "all_engines": False,
            "compare": False,
            "pattern_server": False,
            "json": False,
        }
        defaults.update(kwargs)
        return types.SimpleNamespace(**defaults)

    @patch("ai_guardian.scanners.engine_tester.test_engine")
    @patch("sys.stdin", new=StringIO("AKIAEXAMPLE"))
    def test_single_engine(self, mock_test):
        mock_test.return_value = EngineTestResult("gitleaks", False, [], 40)
        rc = engine_test_command(self._make_args(engine="gitleaks"))
        assert rc == 0
        mock_test.assert_called_once()

    @patch("ai_guardian.scanners.engine_tester.test_all_engines")
    @patch("sys.stdin", new=StringIO("AKIAEXAMPLE"))
    def test_all_flag(self, mock_all):
        mock_all.return_value = [EngineTestResult("gitleaks", False, [], 40)]
        rc = engine_test_command(self._make_args(all_engines=True))
        assert rc == 0

    @patch("ai_guardian.scanners.engine_tester.test_all_engines")
    @patch("sys.stdin", new=StringIO("AKIAEXAMPLE"))
    def test_compare_flag(self, mock_all):
        mock_all.return_value = [
            EngineTestResult("gitleaks", True, [_make_secret()], 42),
        ]
        rc = engine_test_command(self._make_args(compare=True))
        assert rc == 1  # secrets found

    @patch("ai_guardian.scanners.engine_tester.test_engine")
    @patch("sys.stdin", new=StringIO("AKIAEXAMPLE"))
    def test_json_output(self, mock_test):
        mock_test.return_value = EngineTestResult("gitleaks", False, [], 40)
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            rc = engine_test_command(self._make_args(engine="gitleaks", json=True))
        output = mock_out.getvalue()
        parsed = json.loads(output)
        assert parsed["engine"] == "gitleaks"
        assert rc == 0

    def test_no_flags_returns_error(self):
        rc = engine_test_command(self._make_args())
        assert rc == 2

    @patch("sys.stdin.isatty", return_value=True)
    def test_tty_returns_error(self, _):
        rc = engine_test_command(self._make_args(engine="gitleaks"))
        assert rc == 2

    @patch("ai_guardian.scanners.engine_tester.test_engine")
    @patch("sys.stdin", new=StringIO("AKIAEXAMPLE"))
    def test_exit_code_1_when_found(self, mock_test):
        mock_test.return_value = EngineTestResult(
            "gitleaks", True, [_make_secret()], 42
        )
        rc = engine_test_command(self._make_args(engine="gitleaks"))
        assert rc == 1


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class TestGetConfiguredStrategy:

    @patch("ai_guardian._load_secret_scanning_config")
    def test_returns_configured(self, mock_cfg):
        mock_cfg.return_value = ({"execution_strategy": "any-match"}, None)
        assert get_configured_strategy() == "any-match"

    @patch("ai_guardian._load_secret_scanning_config")
    def test_defaults_to_first_match(self, mock_cfg):
        mock_cfg.return_value = ({}, None)
        assert get_configured_strategy() == "first-match"

    @patch("ai_guardian._load_secret_scanning_config")
    def test_no_config(self, mock_cfg):
        mock_cfg.return_value = (None, None)
        assert get_configured_strategy() == "first-match"


class TestApplyStrategy:

    def _results(self, found_engines):
        """Create results where named engines found secrets."""
        return [
            EngineTestResult(
                name,
                name in found_engines,
                [_make_secret()] if name in found_engines else [],
                40,
            )
            for name in ["gitleaks", "betterleaks", "leaktk"]
        ]

    def test_first_match_blocks_on_any(self):
        v = apply_strategy("first-match", self._results({"gitleaks"}))
        assert v.blocked is True
        assert v.strategy == "first-match"

    def test_first_match_allows_when_clean(self):
        v = apply_strategy("first-match", self._results(set()))
        assert v.blocked is False

    def test_any_match_blocks_on_any(self):
        v = apply_strategy("any-match", self._results({"betterleaks"}))
        assert v.blocked is True

    def test_any_match_allows_when_clean(self):
        v = apply_strategy("any-match", self._results(set()))
        assert v.blocked is False

    @patch("ai_guardian._load_secret_scanning_config")
    def test_consensus_blocks_at_threshold(self, mock_cfg):
        mock_cfg.return_value = ({"consensus_threshold": 2}, None)
        v = apply_strategy("consensus", self._results({"gitleaks", "betterleaks"}))
        assert v.blocked is True
        assert v.consensus_threshold == 2

    @patch("ai_guardian._load_secret_scanning_config")
    def test_consensus_allows_below_threshold(self, mock_cfg):
        mock_cfg.return_value = ({"consensus_threshold": 2}, None)
        v = apply_strategy("consensus", self._results({"gitleaks"}))
        assert v.blocked is False

    def test_verdict_counts(self):
        v = apply_strategy("any-match", self._results({"gitleaks", "leaktk"}))
        assert v.total_engines == 3
        assert v.engines_with_secrets == 2


# ---------------------------------------------------------------------------
# scan_mode field
# ---------------------------------------------------------------------------


class TestScanMode:

    def test_default_scan_mode(self):
        r = EngineTestResult("gitleaks", False)
        assert r.scan_mode == "subprocess"

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    @patch("ai_guardian.daemon.get_daemon_state", return_value=None)
    def test_scan_mode_subprocess_when_no_daemon(self, _mock_ds, mock_run):
        mock_run.return_value = _scan_result_clean()
        result = _test_engine("gitleaks", "test")
        assert result.scan_mode == "subprocess"

    @patch("ai_guardian.scanners.engine_tester.run_engine")
    @patch("ai_guardian.daemon.get_daemon_state")
    def test_scan_mode_listen_when_daemon_and_listen_engine(self, mock_ds, mock_run):
        mock_ds.return_value = MagicMock()
        mock_run.return_value = _scan_result_clean(engine="leaktk")
        with patch(
            "ai_guardian.scanners.engine_tester._build_engine_config"
        ) as mock_build:
            from ai_guardian.scanners.engine_builder import EngineConfig

            mock_build.return_value = EngineConfig(
                type="leaktk",
                binary="leaktk",
                command_template=[],
                supports_listen_mode=True,
            )
            result = _test_engine("leaktk", "test")
        assert result.scan_mode == "listen"

    def test_scan_mode_in_format_result_subprocess(self):
        r = EngineTestResult("gitleaks", False, [], 40, scan_mode="subprocess")
        text = format_result(r)
        assert "[listen]" not in text
        assert "[daemon]" not in text

    def test_scan_mode_in_format_result_listen(self):
        r = EngineTestResult("gitleaks", False, [], 40, scan_mode="listen")
        text = format_result(r)
        assert "[listen]" in text

    def test_scan_mode_in_comparison_table(self):
        results = [
            EngineTestResult("gitleaks", False, [], 40, scan_mode="listen"),
            EngineTestResult("leaktk", False, [], 30, scan_mode="daemon"),
        ]
        text = format_comparison(results)
        assert "Mode" in text
        assert "listen" in text
        assert "daemon" in text

    def test_result_to_dict_includes_scan_mode(self):
        from ai_guardian.scanners.engine_tester import _result_to_dict

        r = EngineTestResult("gitleaks", False, [], 40, scan_mode="listen")
        d = _result_to_dict(r)
        assert d["scan_mode"] == "listen"

    def test_json_output_includes_scan_mode(self):
        from ai_guardian.scanners.engine_tester import _result_to_dict

        r = EngineTestResult("gitleaks", False, [], 40, scan_mode="daemon")
        d = _result_to_dict(r)
        output = json.dumps(d)
        assert '"scan_mode": "daemon"' in output


# ---------------------------------------------------------------------------
# Daemon routing
# ---------------------------------------------------------------------------


class TestDaemonRouting:

    @patch("ai_guardian.daemon.get_daemon_state", return_value=MagicMock())
    def test_skip_when_in_daemon_process(self, _mock_ds):
        result = _try_daemon_engine_test("gitleaks", "test", False)
        assert result is None

    @patch("ai_guardian.daemon.get_daemon_state", return_value=None)
    @patch("ai_guardian.daemon.client.is_daemon_running", return_value=False)
    def test_skip_when_daemon_not_running(self, _mock_running, _mock_ds):
        result = _try_daemon_engine_test("gitleaks", "test", False)
        assert result is None

    @patch("ai_guardian.daemon.get_daemon_state", return_value=None)
    @patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    @patch("ai_guardian.daemon.client.send_engine_test")
    def test_routes_through_daemon(self, mock_send, _mock_running, _mock_ds):
        mock_send.return_value = {
            "engine": "leaktk",
            "found": True,
            "secrets": [
                {
                    "rule_id": "generic-api-key",
                    "description": "API key",
                    "file": "test_input.txt",
                    "line_number": 1,
                    "engine": "leaktk",
                }
            ],
            "scan_time_ms": 28.5,
            "scan_mode": "listen",
        }
        result = _try_daemon_engine_test("leaktk", "AKIAEXAMPLE", False)
        assert result is not None
        assert result.found is True
        assert result.scan_mode == "listen"
        assert result.scan_time_ms == 28.5
        assert len(result.secrets) == 1

    @patch("ai_guardian.daemon.get_daemon_state", return_value=None)
    @patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    @patch("ai_guardian.daemon.client.send_engine_test", return_value=None)
    def test_fallback_on_send_failure(self, _mock_send, _mock_running, _mock_ds):
        result = _try_daemon_engine_test("gitleaks", "test", False)
        assert result is None

    @patch("ai_guardian.daemon.get_daemon_state", return_value=None)
    @patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    @patch(
        "ai_guardian.daemon.client.send_engine_test",
        return_value={"error": "something broke"},
    )
    def test_fallback_on_error_response(self, _mock_send, _mock_running, _mock_ds):
        result = _try_daemon_engine_test("gitleaks", "test", False)
        assert result is None

    @patch("ai_guardian.daemon.get_daemon_state", return_value=None)
    @patch(
        "ai_guardian.daemon.client.is_daemon_running",
        side_effect=Exception("socket error"),
    )
    def test_fallback_on_exception(self, _mock_running, _mock_ds):
        result = _try_daemon_engine_test("gitleaks", "test", False)
        assert result is None

    @patch("ai_guardian.daemon.get_daemon_state", return_value=None)
    @patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    @patch("ai_guardian.daemon.client.send_engine_test")
    def test_daemon_mode_set_on_result(self, mock_send, _mock_running, _mock_ds):
        mock_send.return_value = {
            "engine": "gitleaks",
            "found": False,
            "secrets": [],
            "scan_time_ms": 25.0,
        }
        result = _try_daemon_engine_test("gitleaks", "test", False)
        assert result is not None
        assert result.scan_mode == "daemon"
