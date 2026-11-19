"""User-visible contract for safe default text output from ``ai-guardian scan``.

The default terminal view reports finding counts and relative file paths without
echoing source-derived messages, positions, or snippets. Users may request a JSON
or SARIF report explicitly; those reports can contain source-derived details and
should be handled as sensitive files. Violations history records hook findings
when logging is enabled; standalone scan findings are added only when the user
explicitly passes ``--log-violations``.

OCR log contract: default scans hide RapidOCR INFO diagnostics while warnings and
errors remain visible; ``--verbose`` shows OCR INFO diagnostics.

Manual verification:
1. Scan a file containing a synthetic sensitive marker.
2. Confirm the default terminal output reports the finding count and relative path,
   explains the distinction between hook history and standalone scan results, and
   does not show its message, line/column, or source snippet.
3. Use an explicit JSON/SARIF output path only when detailed results are needed.
4. Pass ``--log-violations`` when scan findings should be added to Violations history.
"""

import logging
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
        log_violations=False,
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
    assert (
        "violations history records hook findings when logging is enabled; "
        "standalone scan findings are included only with --log-violations"
    ) in text.lower()
    assert private_marker not in text
    assert "Sensitive finding detail" not in text
    assert "SECRET-001" not in text
    assert "line_number" not in text
    assert ":7" not in text


def test_image_scan_hides_rapidocr_info_by_default_but_shows_it_when_verbose(tmp_path):
    """Quiet scans hide OCR initialization INFO while preserving warnings."""
    image_path = tmp_path / "screenshot.png"
    image_path.write_bytes(b"synthetic image")

    rapidocr_logger = logging.getLogger("RapidOCR")
    original_handlers = rapidocr_logger.handlers[:]
    original_level = rapidocr_logger.level
    original_propagate = rapidocr_logger.propagate
    log_output = StringIO()
    rapidocr_handler = logging.StreamHandler(log_output)

    def fake_rapidocr(*, params):
        rapidocr_logger.setLevel(getattr(logging, params["Global.log_level"]))
        rapidocr_logger.info("synthetic OCR initialization INFO")
        rapidocr_logger.warning("synthetic OCR warning remains visible")
        return lambda _image: SimpleNamespace(boxes=None, txts=None, scores=None)

    try:
        # Capture RapidOCR's own non-propagating stream handler.
        rapidocr_logger.handlers[:] = [rapidocr_handler]
        rapidocr_logger.propagate = False

        for verbose, expect_info in ((False, False), (True, True)):
            log_output.seek(0)
            log_output.truncate(0)
            args = SimpleNamespace(
                verbose=verbose,
                config=None,
                text=None,
                diff=False,
                staged=False,
                pr=None,
                mr=None,
                stdin_diff=False,
                path=str(tmp_path),
                changed_lines_only=False,
                agent_configs=False,
                sarif_output=None,
                json_output=None,
                exit_code=False,
                log_violations=False,
                include=None,
                exclude=None,
                config_only=False,
            )
            with (
                patch(
                    "ai_guardian.config.loaders.load_scanner_config",
                    return_value={"image_scanning": {"enabled": True}},
                ),
                patch("ai_guardian.scanners.image_scanner.HAS_RAPIDOCR", True),
                patch(
                    "ai_guardian.scanners.image_scanner.RapidOCR",
                    side_effect=fake_rapidocr,
                ),
            ):
                result = scan_command(args)

            assert result == 0
            output = log_output.getvalue()
            assert ("synthetic OCR initialization INFO" in output) is expect_info
            assert "synthetic OCR warning remains visible" in output
    finally:
        rapidocr_logger.handlers[:] = original_handlers
        rapidocr_logger.setLevel(original_level)
        rapidocr_logger.propagate = original_propagate
