"""Tests for the violations --clear --yes flag (Issue #360)."""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_guardian import _handle_violations_command
from ai_guardian.cli import main as cli_main


class TestViolationsClearYesFlag:
    """Test --yes/-y flag for non-interactive violations --clear."""

    def _make_args(
        self,
        clear=False,
        yes=False,
        export=None,
        limit=10,
        type=None,
        violation_id=None,
        json_output=False,
    ):
        return argparse.Namespace(
            clear=clear,
            yes=yes,
            export=export,
            limit=limit,
            type=type,
            violation_id=violation_id,
            json_output=json_output,
        )

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_clear_with_yes_skips_prompt(self, mock_logger_cls):
        mock_logger = MagicMock()
        mock_logger.clear_log.return_value = True
        mock_logger_cls.return_value = mock_logger

        args = self._make_args(clear=True, yes=True)

        with patch("builtins.input") as mock_input:
            result = _handle_violations_command(args)

        mock_input.assert_not_called()
        mock_logger.clear_log.assert_called_once()
        assert result == 0

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_clear_without_yes_prompts(self, mock_logger_cls):
        mock_logger = MagicMock()
        mock_logger.clear_log.return_value = True
        mock_logger_cls.return_value = mock_logger

        args = self._make_args(clear=True, yes=False)

        with patch("builtins.input", return_value="y") as mock_input:
            result = _handle_violations_command(args)

        mock_input.assert_called_once()
        mock_logger.clear_log.assert_called_once()
        assert result == 0

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_clear_without_yes_cancelled(self, mock_logger_cls):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger

        args = self._make_args(clear=True, yes=False)

        with patch("builtins.input", return_value="n"):
            result = _handle_violations_command(args)

        mock_logger.clear_log.assert_not_called()
        assert result == 0

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_clear_with_yes_handles_failure(self, mock_logger_cls):
        mock_logger = MagicMock()
        mock_logger.clear_log.return_value = False
        mock_logger_cls.return_value = mock_logger

        args = self._make_args(clear=True, yes=True)

        with patch("builtins.input") as mock_input:
            result = _handle_violations_command(args)

        mock_input.assert_not_called()
        assert result == 1


class TestViolationsYesFlagCLIParsing:
    """Test that --yes/-y is correctly parsed by argparse."""

    def test_yes_long_flag_parsed(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--yes", "-y", action="store_true")
        args = parser.parse_args(["--clear", "--yes"])
        assert args.yes is True

    def test_y_short_flag_parsed(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--yes", "-y", action="store_true")
        args = parser.parse_args(["--clear", "-y"])
        assert args.yes is True

    def test_no_flag_defaults_false(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--yes", "-y", action="store_true")
        args = parser.parse_args(["--clear"])
        assert args.yes is False


class TestViolationsLookupAndJson:
    """Test list/detail output and violation ID lookup."""

    @staticmethod
    def _make_args(
        *,
        clear=False,
        yes=False,
        export=None,
        limit=10,
        type=None,
        violation_id=None,
        json_output=False,
    ):
        return argparse.Namespace(
            clear=clear,
            yes=yes,
            export=export,
            limit=limit,
            type=type,
            violation_id=violation_id,
            json_output=json_output,
        )

    def _record(self):
        return {
            "id": "viol_test_123",
            "timestamp": "2026-11-18T12:00:00Z",
            "violation_type": "ssrf_blocked",
            "severity": "high",
            "blocked": {"reason": "synthetic test"},
            "resolved": False,
        }

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_list_text_includes_each_violation_id(self, mock_logger_cls, capsys):
        mock_logger = MagicMock()
        mock_logger.get_recent_violations.return_value = [self._record()]
        mock_logger_cls.return_value = mock_logger

        result = _handle_violations_command(self._make_args())

        output = capsys.readouterr()
        assert result == 0
        assert 'ID: "viol_test_123"' in output.out
        assert output.err == ""

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_list_json_is_clean_and_honors_filters(self, mock_logger_cls, capsys):
        record = self._record()
        mock_logger = MagicMock()
        mock_logger.get_recent_violations.return_value = [record]
        mock_logger_cls.return_value = mock_logger
        args = self._make_args(limit=2, type="ssrf_blocked", json_output=True)

        result = _handle_violations_command(args)

        output = capsys.readouterr()
        assert result == 0
        assert json.loads(output.out) == [record]
        assert output.err == ""
        mock_logger.get_recent_violations.assert_called_once_with(
            limit=2, violation_type="ssrf_blocked", resolved=False
        )

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_detail_text_displays_labeled_fields_and_nested_details(
        self, mock_logger_cls, capsys
    ):
        record = self._record()
        record["resolved"] = True
        mock_logger = MagicMock()
        mock_logger.get_recent_violations.return_value = [record]
        mock_logger_cls.return_value = mock_logger
        args = self._make_args(violation_id=record["id"])

        result = _handle_violations_command(args)

        output = capsys.readouterr()
        assert result == 0
        assert output.out.splitlines() == [
            "Violation Details",
            f'Violation ID: {record["id"]}',
            f'Timestamp: {record["timestamp"]}',
            "Type: SSRF Blocked",
            "Severity: High",
            "Status: Resolved",
            "Blocked:",
            "  Reason: synthetic test",
        ]
        assert output.err == ""
        mock_logger.get_recent_violations.assert_called_once_with(
            limit=10_000, resolved=None
        )

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_detail_text_handles_missing_fields_and_unfamiliar_types(
        self, mock_logger_cls, capsys
    ):
        record = {
            "id": "viol_future_123",
            "violation_type": "future_detector_type",
            "blocked": {"evidence": [{"source_name": "fixture", "line_number": 7}]},
        }
        mock_logger = MagicMock()
        mock_logger.get_recent_violations.return_value = [record]
        mock_logger_cls.return_value = mock_logger

        result = _handle_violations_command(self._make_args(violation_id=record["id"]))

        output = capsys.readouterr()
        assert result == 0
        assert "Violation ID: viol_future_123" in output.out
        assert "Type: Future Detector Type" in output.out
        assert (
            "Blocked:\n  Evidence:\n    -\n      Source Name: fixture\n      Line Number: 7"
            in output.out
        )
        assert "Timestamp:" not in output.out
        assert "Severity:" not in output.out
        assert "Status:" not in output.out
        assert output.err == ""

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_detail_json_emits_only_the_record(self, mock_logger_cls, capsys):
        record = self._record()
        mock_logger = MagicMock()
        mock_logger.get_recent_violations.return_value = [record]
        mock_logger_cls.return_value = mock_logger
        args = self._make_args(violation_id=record["id"], json_output=True)

        result = _handle_violations_command(args)

        output = capsys.readouterr()
        assert result == 0
        assert json.loads(output.out) == record
        assert output.err == ""

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_unknown_id_returns_nonzero_error(self, mock_logger_cls, capsys):
        mock_logger = MagicMock()
        mock_logger.get_recent_violations.return_value = []
        mock_logger_cls.return_value = mock_logger
        args = self._make_args(violation_id="missing-id")

        result = _handle_violations_command(args)

        output = capsys.readouterr()
        assert result == 1
        assert output.out == ""
        assert output.err.strip() == "Error: Violation ID not found"

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_empty_json_list_is_an_array(self, mock_logger_cls, capsys):
        mock_logger = MagicMock()
        mock_logger.get_recent_violations.return_value = []
        mock_logger_cls.return_value = mock_logger

        result = _handle_violations_command(self._make_args(json_output=True))

        output = capsys.readouterr()
        assert result == 0
        assert json.loads(output.out) == []
        assert output.err == ""

    @patch("ai_guardian.violations.logger.ViolationLogger")
    def test_export_behavior_is_unchanged(self, mock_logger_cls, capsys):
        mock_logger = MagicMock()
        mock_logger.export_violations.return_value = True
        mock_logger_cls.return_value = mock_logger

        result = _handle_violations_command(
            self._make_args(export="violations.json", type="ssrf_blocked")
        )

        output = capsys.readouterr()
        assert result == 0
        assert output.out == "Violations exported to violations.json\n"
        assert output.err == ""
        mock_logger.export_violations.assert_called_once_with(
            Path("violations.json"), violation_type="ssrf_blocked"
        )

    @patch("ai_guardian.cli._ensure_daemon_started")
    @patch("ai_guardian.cli._handle_violations_command", return_value=0)
    def test_cli_parses_violation_id_and_json(
        self, mock_handler, _mock_daemon, monkeypatch
    ):
        monkeypatch.setattr(
            sys,
            "argv",
            ["ai-guardian", "violations", "viol_test_123", "--json"],
        )

        result = cli_main()

        assert result == 0
        args = mock_handler.call_args.args[0]
        assert args.violation_id == "viol_test_123"
        assert args.json_output is True

    @patch("ai_guardian.cli._ensure_daemon_started")
    @patch("ai_guardian.cli._handle_violations_command", return_value=0)
    def test_cli_parses_list_filters_and_json(
        self, mock_handler, _mock_daemon, monkeypatch
    ):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ai-guardian",
                "violations",
                "--type",
                "ssrf_blocked",
                "--limit",
                "2",
                "--json",
            ],
        )

        result = cli_main()

        assert result == 0
        args = mock_handler.call_args.args[0]
        assert args.violation_id is None
        assert args.type == "ssrf_blocked"
        assert args.limit == 2
        assert args.json_output is True
