"""Privacy-safe URL locators for fetched response findings (#2779)."""

import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from ai_guardian.constants import HookEvent
from ai_guardian.violations import command_context
from ai_guardian.violations.logger import ViolationLogger

SOURCE_URL = "https://example.test/docs/page"
REPORTED_GIST_URL = "https://gist.github.com/itdove/6d8dcf794323deeb2a1c939933e7bc41"
PRIVATE_VALUE = "LOCATOR_FIXTURE_" + "A1B2C3D4E5F6G7H8"
RESPONSE = "# Converted page\n" + PRIVATE_VALUE + "\nEnd"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (SOURCE_URL, SOURCE_URL),
        (REPORTED_GIST_URL, REPORTED_GIST_URL),
        (SOURCE_URL + "?access_token=private-query#private-fragment", SOURCE_URL),
        ("https://user:private-userinfo@example.test/docs/page", SOURCE_URL),
        ("HTTP://EXAMPLE.TEST:8080/docs/page", "http://example.test:8080/docs/page"),
        ("https://[2001:db8::1]/docs", "https://[2001:db8::1]/docs"),
        ("https://example.test/docs/%70age", "https://example.test/docs/%70age"),
        (None, None),
        (123, None),
        ({"url": SOURCE_URL}, None),
        ("/docs/page", None),
        ("file:///docs/page", None),
        ("https:///docs/page", None),
        ("https://example.test:invalid/docs", None),
        ("https://example.test:65536/docs", None),
        ("https://example.test:/docs", None),
        ("https://[2001:db8::1]suffix/docs", None),
        ("https://-invalid.test/docs", None),
        ("https://example..test/docs", None),
        ("https://example.test../docs", None),
        ("https://[v1.example]/docs", None),
        ("https://example.test\\other/docs", None),
        ("https://example.test/line\nbreak", None),
        ("https://example.test/" + "a" * 4096, None),
        ("https://example.test/person%40example.test", None),
        ("https://example.test/person%2540example.test", None),
        ("https://example.test/%0aother", None),
        ("https://example.test/%invalid", None),
        ("https://example.test/password/private-value", None),
        ("https://example.test/access_token/private-value", None),
        ("https://example.test/client_secret/private-value", None),
        ("https://example.test/token=private-value", None),
    ],
    ids=lambda value: (
        "oversized" if isinstance(value, str) and len(value) > 100 else None
    ),
)
def test_source_url_validation(value, expected):
    assert command_context.sanitize_source_url(value) == expected


def test_source_url_rejects_sensitive_path_without_external_scanners():
    secret = "gh" + "p_" + "Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4"
    with patch(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        side_effect=AssertionError("metadata validation must stay in-process"),
    ):
        assert command_context.sanitize_source_url(SOURCE_URL) == SOURCE_URL
        encoded = "".join(f"%{ord(char):02x}" for char in secret)
        for path in (secret, encoded, encoded.replace("%", "%25")):
            assert command_context.sanitize_source_url(SOURCE_URL + "/" + path) is None


def test_source_url_validation_fails_closed(monkeypatch):
    redactor = Mock(compiled_pii_types=set(), secret_patterns_complete=True)
    monkeypatch.setattr(command_context, "_origin_command_redactor", lambda: redactor)
    assert command_context.sanitize_source_url(SOURCE_URL) is None
    redactor.redact.assert_not_called()


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"redactions": []},
        {"redactions": [PRIVATE_VALUE], "redacted_text": SOURCE_URL},
        {"redactions": [], "redacted_text": "different"},
    ],
)
def test_incomplete_or_sensitive_url_check_does_not_retain_a_locator(
    monkeypatch, result
):
    redactor = Mock(
        compiled_pii_types=set(command_context._ORIGIN_COMMAND_PII_TYPES),
        secret_patterns_complete=True,
    )
    redactor.redact.return_value = result
    monkeypatch.setattr(command_context, "_origin_command_redactor", lambda: redactor)
    assert command_context.sanitize_source_url(SOURCE_URL) is None


def test_url_check_error_is_omitted_without_logging_sensitive_details(
    monkeypatch, caplog
):
    redactor = Mock(
        compiled_pii_types=set(command_context._ORIGIN_COMMAND_PII_TYPES),
        secret_patterns_complete=True,
    )
    redactor.redact.side_effect = RuntimeError(PRIVATE_VALUE)
    monkeypatch.setattr(command_context, "_origin_command_redactor", lambda: redactor)
    assert command_context.sanitize_source_url(SOURCE_URL) is None
    assert PRIVATE_VALUE not in caplog.text


@pytest.mark.parametrize("patterns", [[], [{"regex": "[", "secret_type": "invalid"}]])
def test_source_url_omitted_when_secret_rules_are_missing_or_rejected(
    monkeypatch, patterns
):
    from ai_guardian.scanners.secret_redactor import SecretRedactor

    with patch.object(
        SecretRedactor, "_load_patterns_from_toml", return_value=patterns
    ):
        redactor = SecretRedactor(
            config={"enabled": True},
            pii_config={
                "enabled": True,
                "pii_types": list(command_context._ORIGIN_COMMAND_PII_TYPES),
            },
        )
    assert redactor.compiled_pii_types == set(command_context._ORIGIN_COMMAND_PII_TYPES)
    assert redactor.secret_patterns_complete is False
    monkeypatch.setattr(command_context, "_origin_command_redactor", lambda: redactor)
    assert command_context.sanitize_source_url(SOURCE_URL) is None


@pytest.fixture
def fetched_history(tmp_path, monkeypatch):
    """Run the real handler, normalization, logging and redactor without a network."""
    from ai_guardian.hook_events.post_tool_use import handle_post_tool_use
    from ai_guardian.hook_processing import _ensure_hook_events_imported
    from ai_guardian.reporting.latency import _CheckTimer
    from ai_guardian.scanners import secret_scanning

    _ensure_hook_events_imported()
    history = ViolationLogger(
        log_path=tmp_path / "history.jsonl", config={"enabled": True}
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_scanning_config",
        lambda: ({"enabled": True}, None),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_secret_redaction_config",
        lambda: (
            {
                "enabled": True,
                "action": "warn",
                "additional_patterns": [
                    {
                        "pattern": r"LOCATOR_FIXTURE_[A-Z0-9]{16}",
                        "type": "synthetic-locator-value",
                        "strategy": "full_redact",
                    }
                ],
            },
            None,
        ),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_pii_config", lambda: (None, None)
    )
    monkeypatch.setattr(
        "ai_guardian.scanners.password_likelihood.run_password_likelihood_scan",
        lambda _content: None,
    )

    def detect(content, filename, *, context, **_kwargs):
        assert content == RESPONSE
        # Match the scanner's side-channel metadata contract; PostToolUse defers
        # logging until the effective redaction outcome is known.
        monkeypatch.setattr(secret_scanning, "_last_secret_matched_text", PRIVATE_VALUE)
        monkeypatch.setattr(secret_scanning, "_last_secret_line_number", 2)
        monkeypatch.setattr(secret_scanning, "_last_secret_start_column", 0)
        monkeypatch.setattr(
            secret_scanning,
            "_last_secret_findings",
            [
                {
                    "line_number": 2,
                    "end_line": 2,
                    "start_column": 0,
                    "end_column": len(PRIVATE_VALUE),
                }
            ],
        )
        return True, "Synthetic sensitive finding"

    monkeypatch.setattr("ai_guardian.scanners.secret_scanning.check_secrets", detect)

    def run(
        tool_name="webfetch",
        tool_input=None,
        pretool=None,
        opencode=True,
        response=RESPONSE,
    ):
        from ai_guardian.hook_adapters.base_agent import BaseAgentAdapter
        from ai_guardian.hook_adapters.opencode import OpenCodeAdapter

        data = {
            "hook_event_name": "tool.execute.after" if opencode else "PostToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input or {},
            "tool_response": {"output": response},
        }
        if opencode:
            data["hook_source"] = "opencode"
            data["opencode_version"] = "2.0.24"
        adapter = OpenCodeAdapter() if opencode else BaseAgentAdapter()
        context_mgr = Mock()
        context_mgr.get_pretool_context.return_value = pretool
        result = handle_post_tool_use(
            hook_data=data,
            adapter=adapter,
            ide_type=adapter.ide_type,
            hook_event=HookEvent.POST_TOOL_USE,
            hook_tool_use_id="call_locator",
            hook_session_id="locator-session",
            context_mgr=context_mgr,
            violation_logger=history,
            _latency_timer=_CheckTimer(enabled=False),
            _invocation_allowed=set(),
            now=datetime.now(timezone.utc),
        )
        assert PRIVATE_VALUE not in result["output"]
        return history.get_recent_violations(limit=10)

    return run


@pytest.mark.parametrize(
    "tool_name,opencode", [("webfetch", True), ("WebFetch", True), ("WebFetch", False)]
)
def test_fetched_response_records_share_source_and_coordinates(
    fetched_history, tool_name, opencode
):
    records = fetched_history(tool_name, {"url": SOURCE_URL}, opencode=opencode)
    assert {record["violation_type"] for record in records} == {
        "sensitive_finding",
        "secret_redaction",
    }
    for record in records:
        blocked = record["blocked"]
        assert blocked["source_url"] == SOURCE_URL
        assert not blocked.get("file_path")
        assert blocked["source_context"] == "tool_output"
        assert blocked["line_number"] == 2
        assert blocked["start_column"] == 0
        assert blocked["end_column"] == len(PRIVATE_VALUE)
        assert PRIVATE_VALUE not in json.dumps(record)
    sensitive = next(r for r in records if r["violation_type"] == "sensitive_finding")
    assert set(sensitive["blocked"]) <= {
        "source_url",
        "source_context",
        "line_number",
        "start_column",
        "end_column",
        "end_line",
    }


def test_missing_post_input_uses_correlated_safe_url_and_still_scans(fetched_history):
    records = fetched_history(
        pretool={
            "tool_name": "webfetch",
            "source_url": SOURCE_URL,
            "scan_results": {"secrets_scanned": True, "secrets_found": False},
        }
    )
    assert len(records) == 2
    assert all(r["blocked"]["source_url"] == SOURCE_URL for r in records)


@pytest.mark.parametrize(
    "tool_input",
    [
        {},
        {"url": None},
        {"url": "not-a-url"},
        {"url": SOURCE_URL + "/password/private-value"},
    ],
)
def test_missing_or_unsafe_url_uses_fixed_context(fetched_history, tool_input):
    for record in fetched_history(tool_input=tool_input):
        assert "source_url" not in record["blocked"]
        assert not record["blocked"].get("file_path")
        assert record["blocked"]["source_context"] == "tool_output"
        assert "webfetch_output" not in json.dumps(record)


def test_bad_post_url_does_not_reuse_cached_locator(fetched_history):
    records = fetched_history(
        tool_input={"url": "bad"},
        pretool={
            "tool_name": "webfetch",
            "source_url": SOURCE_URL,
        },
    )
    assert all("source_url" not in r["blocked"] for r in records)


def test_missing_tool_metadata_never_invents_a_file(fetched_history):
    records = fetched_history("unknown")
    sensitive = next(r for r in records if r["violation_type"] == "sensitive_finding")
    assert not sensitive["blocked"].get("file_path")
    assert "source_url" not in sensitive["blocked"]
    assert sensitive["blocked"]["source_context"] == "tool_output"


def test_cached_webfetch_identity_recovers_missing_post_tool_metadata(fetched_history):
    records = fetched_history(
        "unknown", pretool={"tool_name": "WebFetch", "source_url": SOURCE_URL}
    )
    assert all(r["blocked"]["source_url"] == SOURCE_URL for r in records)


def test_different_cached_tool_does_not_supply_url_metadata(fetched_history):
    records = fetched_history(pretool={"tool_name": "Read", "source_url": SOURCE_URL})
    assert all("source_url" not in r["blocked"] for r in records)


def test_file_exclusion_from_cached_input_cannot_suppress_url_response(fetched_history):
    records = fetched_history(
        tool_input={"url": SOURCE_URL},
        pretool={
            "tool_name": "webfetch",
            "source_url": SOURCE_URL,
            "ignore_files_matched": True,
        },
    )
    assert len(records) == 2


def test_url_response_does_not_inherit_cached_file_annotations(fetched_history):
    with patch(
        "ai_guardian.hook_events.post_tool_use.process_annotations"
    ) as annotations:
        records = fetched_history(
            tool_input={"url": SOURCE_URL},
            pretool={
                "tool_name": "Read",
                "file_path": "/repo/unrelated.txt",
            },
        )
    annotations.assert_not_called()
    assert len(records) == 2
    assert all(not record["blocked"].get("file_path") for record in records)


def test_local_file_location_is_unchanged(fetched_history):
    records = fetched_history("Read", {"file_path": "/repo/source.txt"}, opencode=False)
    for record in records:
        assert record["blocked"]["file_path"] == "/repo/source.txt"
        assert "source_url" not in record["blocked"]


def test_url_credentials_never_enter_history(fetched_history):
    records = fetched_history(
        tool_input={
            "url": "https://user:private-userinfo@example.test/docs/page?key=private-query#private-fragment"
        }
    )
    assert len(records) == 2
    assert all(r["blocked"]["source_url"] == SOURCE_URL for r in records)
    assert "private-" not in json.dumps(records)


@pytest.mark.parametrize("action", ["block", "redact"])
def test_pii_finding_retains_url_not_warning_filename(
    fetched_history, monkeypatch, action
):
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *_a, **_k: (False, None),
    )
    monkeypatch.setattr(
        "ai_guardian.config.loaders._load_pii_config",
        lambda: (
            {"enabled": True, "pii_types": ["email"], "action": action},
            None,
        ),
    )
    records = fetched_history(
        tool_input={"url": SOURCE_URL}, response="# Response\nperson@example.test"
    )
    assert len(records) == 1
    assert records[0]["violation_type"] == "sensitive_finding"
    assert records[0]["blocked"] == {
        "source_url": SOURCE_URL,
        "source_context": "tool_output",
        "line_number": 2,
        "start_column": 0,
        "end_column": len("person@example.test"),
    }
    assert "person@example.test" not in json.dumps(records)


@pytest.mark.parametrize(
    "violation_type", ["secret_detected", "pii_detected", "secret_redaction"]
)
def test_logger_revalidates_urls_at_persistence_boundary(tmp_path, violation_type):
    history = ViolationLogger(
        log_path=tmp_path / "history.jsonl", config={"enabled": True}
    )
    history.log_violation(
        violation_type,
        blocked={
            "source_url": SOURCE_URL + "?key=private-query",
            "source_context": "tool_output",
            "line_number": 7,
            "start_column": 0,
        },
        context={
            "source_url": "invalid-private-value",
            "pretool_context": {"source_url": SOURCE_URL + "#private-fragment"},
        },
    )
    record = history.get_recent_violations()[0]
    assert record["blocked"]["source_url"] == SOURCE_URL
    assert record["blocked"]["start_column"] == 0
    assert "private-" not in json.dumps(record)
    assert "invalid-" not in json.dumps(record)


@pytest.mark.parametrize(
    "metadata,expected",
    [
        (
            {"line_number": 2, "position": 2, "original_length": 4},
            {"line_number": 2, "start_column": 0, "end_line": 3, "end_column": 1},
        ),
        (
            {"line_number": 2, "position": 2, "original_length": None},
            {"line_number": 2},
        ),
        (
            {"line_number": 2, "position": True, "original_length": 4},
            {"line_number": 2},
        ),
        ({"line_number": 2, "position": 2, "original_length": 100}, {"line_number": 2}),
    ],
)
def test_redaction_coordinates_describe_original_response(metadata, expected):
    from ai_guardian.hook_events.post_tool_use import _redaction_coordinates

    assert _redaction_coordinates(metadata, "x\nab\nc") == expected


@pytest.fixture(params=["sensitive_finding", "secret_redaction", "secret_detected"])
def url_record(request):
    record = {
        "id": "viol_12345678",
        "violation_type": request.param,
        "severity": "high",
        "blocked": {
            "source_url": SOURCE_URL + "?key=private-query#private-fragment",
            "source_context": "tool_output",
            "line_number": 2,
            "start_column": 0,
            "end_column": 8,
        },
    }
    if request.param != "secret_redaction":
        record["blocked"]["matched_text"] = PRIVATE_VALUE
    return record


def test_mcp_projection_preserves_safe_url_and_response_columns(url_record):
    pytest.importorskip("mcp")
    from ai_guardian.mcp.server import create_server

    with patch("ai_guardian.violations.logger.ViolationLogger") as logger_class:
        logger_class.return_value.get_recent_violations.return_value = [url_record]
        result = create_server()._tool_manager._tools["get_violations"].fn()
    record = result["violations"][0]
    assert record["source_url"] == SOURCE_URL
    assert record["source_context"] == "Tool output"
    assert record["file"] == ""
    assert record["line"] == 2
    assert record["start_column"] == 1
    assert record["end_column"] == 9
    assert PRIVATE_VALUE not in json.dumps(record)
    assert "private-" not in json.dumps(record)


def test_rest_projection_preserves_safe_url_and_response_columns(url_record):
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    with patch("ai_guardian.violations.logger.ViolationLogger") as logger_class:
        logger_class.return_value.get_recent_violations.return_value = [url_record]
        result = MultiDaemonClient._local_violations(10, None)
    record = result["violations"][0]
    assert record["source_url"] == SOURCE_URL
    assert record["source_context"] == "Tool output"
    assert record["line"] == 2
    assert record["start_column"] == 1
    assert record["end_column"] == 9
    assert PRIVATE_VALUE not in json.dumps(record)
    assert "private-" not in json.dumps(record)


def test_sdk_projection_preserves_safe_url_with_internal_columns(url_record):
    from ai_guardian.sdk import GuardSession

    record = GuardSession._sanitize_violation(
        url_record, lambda text: {"sanitized_text": text}
    )
    assert record["source_url"] == SOURCE_URL
    assert record["source_context"] == "Tool output"
    assert record["line_number"] == 2
    assert record["start_column"] == 0
    assert PRIVATE_VALUE not in json.dumps(record)
    assert "private-" not in json.dumps(record)


def test_safe_copies_and_support_retain_only_validated_urls(url_record):
    from ai_guardian.reporting.support_bundle import _sanitize_violations
    from ai_guardian.violations.tool_diagnostics import diagnostic_safe_violation

    for record in [
        diagnostic_safe_violation(url_record),
        _sanitize_violations([url_record])[0][0],
    ]:
        assert record["blocked"]["source_url"] == SOURCE_URL
        assert record["blocked"]["start_column"] == 0
        assert PRIVATE_VALUE not in json.dumps(record)
        assert "private-" not in json.dumps(record)


def test_web_flat_and_nested_history_use_response_coordinates(url_record):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.daemon.multi_client import MultiDaemonClient
    from ai_guardian.web.pages.violations import _format_violation_markdown

    with patch("ai_guardian.violations.logger.ViolationLogger") as logger_class:
        logger_class.return_value.get_recent_violations.return_value = [url_record]
        flat = MultiDaemonClient._local_violations(10, None)["violations"][0]
    for record in (url_record, flat):
        markdown = _format_violation_markdown(record)
        assert "**Source URL:** " + SOURCE_URL in markdown
        assert "**Response Line:** 2" in markdown
        assert "**Response Column:** 1" in markdown
        assert "**Response End Column:** 9" in markdown
        assert "**File:**" not in markdown
        assert "private-" not in markdown
        assert PRIVATE_VALUE not in markdown


def test_cli_url_location_is_not_rendered_as_a_file():
    from ai_guardian.cli_handlers import _sensitive_finding_location_lines

    assert _sensitive_finding_location_lines(
        {
            "source_url": SOURCE_URL + "?key=private-query",
            "line_number": 2,
            "start_column": 0,
            "end_column": 8,
        }
    ) == [f"  URL: {SOURCE_URL} (response line 2, column 1-9)"]


def test_locationless_response_still_shows_context_and_coordinates(url_record):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.cli_handlers import _sensitive_finding_location_lines
    from ai_guardian.web.pages.violations import _format_violation_markdown

    url_record["blocked"]["source_url"] = "invalid-private-locator"
    markdown = _format_violation_markdown(url_record)
    assert "**Source:** Tool output" in markdown
    assert "**Response Line:** 2" in markdown
    assert "**Response Column:** 1" in markdown
    assert "**Response End Column:** 9" in markdown
    assert "**Source URL:**" not in markdown
    assert "private-" not in markdown
    assert _sensitive_finding_location_lines(url_record["blocked"]) == [
        "  Source: Tool output (response line 2, column 1-9); precise location was not retained"
    ]


@pytest.mark.parametrize(
    "url,expected_count",
    [(SOURCE_URL, 0), (SOURCE_URL + "?key=private-query", 1), ("bad-private-url", 1)],
)
def test_support_counts_url_sanitization(url, expected_count):
    from ai_guardian.reporting.support_bundle import _sanitize_violations

    records, count = _sanitize_violations(
        [
            {
                "violation_type": "secret_redaction",
                "blocked": {"source_url": url},
            }
        ]
    )
    assert count == expected_count
    assert "private-" not in json.dumps(records)


def test_mirrored_url_and_coordinates_survive_local_history_projection(url_record):
    from types import SimpleNamespace

    from ai_guardian.daemon.multi_client import MultiDaemonClient
    from ai_guardian.daemon.violation_mirroring import _make_mirror_record

    flat = {
        "id": "viol_12345678",
        "violation_type": url_record["violation_type"],
        "source_url": SOURCE_URL + "?key=private-query",
        "source_context": "Tool output",
        "line": 2,
        "start_column": 1,
        "end_column": 9,
    }
    mirrored, _ = _make_mirror_record(
        flat, SimpleNamespace(name="remote", runtime="container"), "a" * 64
    )
    assert mirrored["blocked"]["source_url"] == SOURCE_URL
    assert mirrored["blocked"]["start_column"] == 0
    assert "private-" not in json.dumps(mirrored)
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger_class:
        logger_class.return_value.get_recent_violations.return_value = [mirrored]
        result = MultiDaemonClient._local_violations(10, None)
    record = result["violations"][0]
    assert record["source_url"] == SOURCE_URL
    assert record["source_context"] == "Tool output"
    assert record["line"] == 2
    assert record["start_column"] == 1
    assert record["end_column"] == 9


def test_sensitive_url_guidance_explains_response_coordinate_space(url_record):
    from ai_guardian.violations.guidance import get_resolution_instructions

    url_record["violation_type"] = "sensitive_finding"
    instructions, snippet = get_resolution_instructions(url_record)
    assert "sanitized request URL" in instructions
    assert "not the original remote document" in instructions
    assert "precise location was not retained" not in instructions
    assert snippet == ""
    assert "private-" not in instructions


def test_web_detail_displays_url_and_original_response_columns(url_record):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.web.pages.violation_detail import _render_violation_detail

    with (
        patch("ai_guardian.web.pages.violation_detail.ui") as ui,
        patch("ai_guardian.web.pages.violation_detail.local_time_label"),
        patch("ai_guardian.web.pages.violations.ui", ui),
    ):
        _render_violation_detail(url_record, None, "local")
    labels = [str(call.args[0]) for call in ui.label.call_args_list if call.args]
    assert "Source URL:" in labels
    assert SOURCE_URL in labels
    assert "Response Line:" in labels
    assert "Response Column:" in labels
    assert "1" in labels
    assert "9" in labels
    assert "private-" not in str(ui.mock_calls)
    assert PRIVATE_VALUE not in str(ui.mock_calls)


@pytest.mark.parametrize(
    "bad_url",
    [
        "invalid-private-locator",
        SOURCE_URL + "/password/private-path",
        {"url": "private-value"},
    ],
)
def test_unsafe_url_is_omitted_from_all_query_and_copy_projections(url_record, bad_url):
    pytest.importorskip("mcp")
    from ai_guardian.daemon.multi_client import MultiDaemonClient
    from ai_guardian.mcp.server import create_server
    from ai_guardian.reporting.support_bundle import _sanitize_violations
    from ai_guardian.sdk import GuardSession
    from ai_guardian.violations.tool_diagnostics import diagnostic_safe_violation

    url_record["blocked"]["source_url"] = bad_url
    projected = [
        diagnostic_safe_violation(url_record),
        _sanitize_violations([url_record])[0][0],
        GuardSession._sanitize_violation(
            url_record, lambda text: {"sanitized_text": text}
        ),
    ]
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger_class:
        logger_class.return_value.get_recent_violations.return_value = [url_record]
        projected.append(
            create_server()._tool_manager._tools["get_violations"].fn()["violations"][0]
        )
        projected.append(MultiDaemonClient._local_violations(10, None)["violations"][0])
    for record in projected:
        assert "source_url" not in record
        assert "source_url" not in record.get("blocked", {})
        assert "private-" not in json.dumps(record)
        assert PRIVATE_VALUE not in json.dumps(record)
