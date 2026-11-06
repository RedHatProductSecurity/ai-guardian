"""User-visible contract for safe default text output from ``ai-guardian scan``.

The default terminal view reports finding counts and relative file paths without
echoing source-derived messages, positions, or snippets. Users may request a JSON
or SARIF report explicitly; those reports can contain source-derived details and
should be handled as sensitive files.

Manual verification:
1. Scan a file containing a synthetic sensitive marker.
2. Confirm the default terminal output reports the finding count and relative path,
   but not its message, line/column, or source snippet.
3. Use an explicit JSON/SARIF output path only when detailed results are needed.
"""

from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from ai_guardian.scanners.file_scanner import scan_command


def test_default_scan_output_omits_finding_details_and_source_content():
    """A finding must not echo scanned content to terminal logs by default."""
    private_marker = "synthetic-private-scan-marker"
    findings = [
        {
            "rule_id": "SECRET-001",
            "message": f"Sensitive finding detail: {private_marker}",
            "file_path": "src/settings.py",
            "line_number": 7,
            "start_column": 4,
            "snippet": f"API_TOKEN = {private_marker}",
        }
    ]
    args = SimpleNamespace(
        verbose=False,
        config=None,
        text=None,
        diff=False,
        staged=False,
        pr=None,
        mr=None,
        stdin_diff=False,
        path=".",
        changed_lines_only=False,
        agent_configs=False,
        sarif_output=None,
        json_output=None,
        exit_code=False,
    )
    output = StringIO()

    with (
        patch("ai_guardian.config.loaders.load_scanner_config", return_value={}),
        patch("ai_guardian.scanners.file_scanner.FileScanner") as scanner_class,
    ):
        scanner = scanner_class.return_value
        scanner._code_scanner_unavailable = None
        scanner._code_scan_skipped_count = 0
        scanner._finding_paths = ["src/settings.py"]
        scanner.scan_directory.return_value = findings
        with redirect_stdout(output):
            result = scan_command(args)

    text = output.getvalue()
    assert result == 0
    assert "Found 1 security issue(s)" in text
    assert "File: src/settings.py" in text
    assert "details are withheld" in text.lower()
    assert "--json-output" in text
    assert private_marker not in text
    assert "Sensitive finding detail" not in text
    assert "SECRET-001" not in text
    assert "line_number" not in text
    assert ":7" not in text
