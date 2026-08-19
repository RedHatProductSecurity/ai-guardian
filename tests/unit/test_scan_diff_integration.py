"""Integration tests for scan_command() with diff flags."""

import tempfile
from argparse import Namespace
from pathlib import Path
from unittest import mock


from ai_guardian.scanners.file_scanner import scan_command


def _make_args(**overrides):
    """Build a minimal args Namespace for scan_command()."""
    defaults = {
        "path": ".",
        "config": None,
        "include": None,
        "exclude": None,
        "config_only": False,
        "sarif_output": None,
        "json_output": None,
        "exit_code": False,
        "verbose": False,
        "diff": False,
        "base": None,
        "staged": False,
        "pr": None,
        "mr": None,
        "stdin_diff": False,
        "changed_lines_only": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


class TestScanCommandDiffValidation:

    def test_mutual_exclusivity_diff_and_pr(self, capsys):
        args = _make_args(diff=True, pr="42")
        rc = scan_command(args)
        assert rc == 1
        assert "mutually exclusive" in capsys.readouterr().err

    def test_mutual_exclusivity_pr_and_mr(self, capsys):
        args = _make_args(pr="1", mr="2")
        rc = scan_command(args)
        assert rc == 1
        assert "mutually exclusive" in capsys.readouterr().err

    def test_base_requires_diff(self, capsys):
        args = _make_args(base="main")
        rc = scan_command(args)
        assert rc == 1
        assert "--base requires --diff" in capsys.readouterr().err

    def test_changed_lines_only_requires_diff_mode(self, capsys):
        args = _make_args(changed_lines_only=True)
        rc = scan_command(args)
        assert rc == 1
        assert "--changed-lines-only requires" in capsys.readouterr().err


SAMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 line1
+ADDED_LINE
 line2
 line3
"""


class TestScanCommandDiffMode:

    @mock.patch("ai_guardian.tools.diff_provider.get_diff_unified")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_diff_flag_scans_changed_files(self, mock_scan, mock_diff):
        mock_diff.return_value = SAMPLE_DIFF
        mock_scan.return_value = []

        args = _make_args(diff=True)
        rc = scan_command(args)

        assert rc == 0
        mock_diff.assert_called_once()
        mock_scan.assert_called_once()
        file_paths = mock_scan.call_args[1]["file_paths"]
        names = [p.name for p in file_paths]
        assert "foo.py" in names

    @mock.patch("ai_guardian.tools.diff_provider.get_diff_unified")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_diff_with_base(self, mock_scan, mock_diff):
        mock_diff.return_value = SAMPLE_DIFF
        mock_scan.return_value = []

        args = _make_args(diff=True, base="develop")
        rc = scan_command(args)

        assert rc == 0
        mock_diff.assert_called_once_with(base_ref="develop", repo_path=".")

    @mock.patch("ai_guardian.tools.diff_provider.get_pr_diff")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_pr_flag(self, mock_scan, mock_pr):
        mock_pr.return_value = SAMPLE_DIFF
        mock_scan.return_value = []

        args = _make_args(pr="123")
        rc = scan_command(args)

        assert rc == 0
        mock_pr.assert_called_once_with("123", repo_path=".")
        call_kwargs = mock_scan.call_args[1]
        file_paths = call_kwargs["file_paths"]
        base_path = call_kwargs["base_path"]
        assert len(file_paths) == 1
        assert file_paths[0].name == "foo.py"
        assert str(base_path).startswith(str(Path(tempfile.gettempdir())))

    @mock.patch("ai_guardian.tools.diff_provider.get_mr_diff")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_mr_flag(self, mock_scan, mock_mr):
        mock_mr.return_value = SAMPLE_DIFF
        mock_scan.return_value = []

        args = _make_args(mr="42")
        rc = scan_command(args)

        assert rc == 0
        mock_mr.assert_called_once_with("42", repo_path=".")
        call_kwargs = mock_scan.call_args[1]
        file_paths = call_kwargs["file_paths"]
        base_path = call_kwargs["base_path"]
        assert len(file_paths) == 1
        assert file_paths[0].name == "foo.py"
        assert str(base_path).startswith(str(Path(tempfile.gettempdir())))

    @mock.patch("ai_guardian.scanners.file_scanner.sys.stdin")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_stdin_diff(self, mock_scan, mock_stdin):
        mock_stdin.read.return_value = SAMPLE_DIFF
        mock_scan.return_value = []

        args = _make_args(stdin_diff=True)
        rc = scan_command(args)

        assert rc == 0
        mock_stdin.read.assert_called_once()
        mock_scan.assert_called_once()

    @mock.patch("ai_guardian.tools.diff_provider.get_diff_unified")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_no_changed_files(self, mock_scan, mock_diff, capsys):
        mock_diff.return_value = ""

        args = _make_args(diff=True)
        rc = scan_command(args)

        assert rc == 0
        mock_scan.assert_not_called()
        assert "No changed files" in capsys.readouterr().out

    @mock.patch("ai_guardian.tools.diff_provider.get_diff_unified")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_changed_lines_only_filters(self, mock_scan, mock_diff):
        mock_diff.return_value = SAMPLE_DIFF
        mock_scan.return_value = [
            {
                "file_path": "src/foo.py",
                "line_number": 2,
                "rule_id": "X",
                "message": "hit",
            },
            {
                "file_path": "src/foo.py",
                "line_number": 99,
                "rule_id": "Y",
                "message": "miss",
            },
        ]

        args = _make_args(diff=True, changed_lines_only=True)
        rc = scan_command(args)

        assert rc == 0

    @mock.patch("ai_guardian.scanners.file_scanner.sys")
    @mock.patch("ai_guardian.tools.diff_provider.get_staged_diff")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_diff_staged_skips_stdin_in_git_hooks(
        self, mock_scan, mock_staged, mock_sys
    ):
        """Issue #2069: --diff --staged must not fall into stdin mode when
        stdin is not a tty (as happens inside git pre-commit hooks)."""
        mock_sys.stdin.isatty.return_value = False
        mock_sys.stderr = __import__("sys").stderr
        mock_sys.stdout = __import__("sys").stdout
        mock_staged.return_value = SAMPLE_DIFF
        mock_scan.return_value = []

        args = _make_args(diff=True, staged=True, path=None)
        rc = scan_command(args)

        assert rc == 0
        mock_staged.assert_called_once()
        mock_sys.stdin.read.assert_not_called()

    @mock.patch("ai_guardian.tools.diff_provider.get_pr_diff")
    def test_diff_provider_error(self, mock_pr, capsys):
        from ai_guardian.tools.diff_provider import DiffProviderError

        mock_pr.side_effect = DiffProviderError("gh CLI not found")

        args = _make_args(pr="123")
        rc = scan_command(args)

        assert rc == 1
        assert "gh CLI not found" in capsys.readouterr().err

    @mock.patch("ai_guardian.tools.diff_provider.get_diff_unified")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_exit_code_with_findings(self, mock_scan, mock_diff):
        mock_diff.return_value = SAMPLE_DIFF
        mock_scan.return_value = [
            {
                "file_path": "src/foo.py",
                "line_number": 2,
                "rule_id": "X",
                "level": "error",
                "message": "bad",
            },
        ]

        args = _make_args(diff=True, exit_code=True)
        rc = scan_command(args)

        assert rc == 1


class TestScanCommandLoggingSuppression:
    """Tests for --verbose logging control (issue #1044)."""

    import logging

    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_directory")
    def test_default_suppresses_stderr_logging(self, mock_scan):
        """Without --verbose, stderr handlers should be raised to CRITICAL+1."""
        mock_scan.return_value = []

        args = _make_args(verbose=False)
        scan_command(args)

        pkg_logger = self.logging.getLogger("ai_guardian")
        stream_handlers = [
            h
            for h in pkg_logger.handlers
            if isinstance(h, self.logging.StreamHandler)
            and not isinstance(h, self.logging.FileHandler)
        ]
        for h in stream_handlers:
            assert h.level > self.logging.ERROR

    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_directory")
    def test_verbose_preserves_stderr_logging(self, mock_scan):
        """With --verbose, stderr handler levels should not be raised."""
        mock_scan.return_value = []

        pkg_logger = self.logging.getLogger("ai_guardian")
        stream_handlers = [
            h
            for h in pkg_logger.handlers
            if isinstance(h, self.logging.StreamHandler)
            and not isinstance(h, self.logging.FileHandler)
        ]
        original_levels = [h.level for h in stream_handlers]

        args = _make_args(verbose=True)
        scan_command(args)

        for h, orig in zip(stream_handlers, original_levels):
            assert h.level == orig


class TestScanCommandStagedValidation:

    def test_staged_requires_diff(self, capsys):
        args = _make_args(staged=True)
        rc = scan_command(args)
        assert rc == 1
        assert "--staged requires --diff" in capsys.readouterr().err

    def test_staged_and_base_mutually_exclusive(self, capsys):
        args = _make_args(diff=True, staged=True, base="main")
        rc = scan_command(args)
        assert rc == 1
        assert "mutually exclusive" in capsys.readouterr().err


class TestScanCommandStagedMode:

    @mock.patch("ai_guardian.tools.diff_provider.get_staged_diff")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_staged_scan_calls_get_staged_diff(self, mock_scan, mock_staged):
        mock_staged.return_value = SAMPLE_DIFF
        mock_scan.return_value = []
        args = _make_args(diff=True, staged=True)
        rc = scan_command(args)
        assert rc == 0
        mock_staged.assert_called_once()
        mock_scan.assert_called_once()

    @mock.patch("ai_guardian.tools.diff_provider.get_staged_diff")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_staged_with_changed_lines_only(self, mock_scan, mock_staged):
        mock_staged.return_value = SAMPLE_DIFF
        mock_scan.return_value = []
        args = _make_args(diff=True, staged=True, changed_lines_only=True)
        rc = scan_command(args)
        assert rc == 0
        mock_staged.assert_called_once()

    @mock.patch("ai_guardian.tools.diff_provider.get_staged_diff")
    @mock.patch("ai_guardian.scanners.file_scanner.FileScanner.scan_files")
    def test_staged_no_changes(self, mock_scan, mock_staged):
        mock_staged.return_value = ""
        args = _make_args(diff=True, staged=True)
        rc = scan_command(args)
        assert rc == 0
        mock_scan.assert_not_called()
