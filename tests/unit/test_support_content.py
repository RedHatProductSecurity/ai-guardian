"""Support defaults, recent logs, and bounded diagnostic copies (synthetic only)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_guardian.reporting import support_bundle as bundles
from ai_guardian.reporting import github_support as gh
from ai_guardian.reporting import github_gist as gist
from ai_guardian.tray import support as tray_support
from ai_guardian.ui import support_review as review


def _write_text(path, text, *, encoding="utf-8"):
    """Keep synthetic diagnostic files byte-stable on Windows."""
    with path.open("w", encoding=encoding, newline="") as stream:
        stream.write(text)


@pytest.mark.parametrize(
    "saved", [{}, {"support": {}}, {"support": {"export_destination": ""}}]
)
def test_unset_saved_destination_defaults_to_public_categories(
    monkeypatch, tmp_path, saved
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ai_guardian.config.utils.get_config_dir", lambda: tmp_path)
    _write_text(tmp_path / "ai-guardian.json", json.dumps(saved))
    status = bundles._get_bundle_status()
    assert status["destination"] == gh.DESTINATION
    assert status["destination_type"] == "github-discussions"


def test_tray_honors_configured_destination_without_rewriting_it(monkeypatch, tmp_path):
    saved = {"export_destination": str(tmp_path / "legacy-exports")}
    monkeypatch.setattr(bundles, "_get_support_config", lambda: saved)
    root = tmp_path / "prepared"
    root.mkdir()
    info = {
        "destination": saved["export_destination"],
        "temp_path": str(root),
        "files": [],
    }

    def prepare(**kwargs):
        assert kwargs == {}
        return {"bundle_id": "support-default"}

    monkeypatch.setattr(bundles, "prepare_bundle", prepare)
    monkeypatch.setattr(bundles, "_active_bundles", {"support-default": info})
    monkeypatch.setattr(gh, "review_dialog", lambda request: None)
    monkeypatch.setattr(
        bundles,
        "send_bundle",
        lambda bid: {"status": "error", "error_code": "cancelled"},
    )
    assert tray_support.run_support_flow()["error_code"] == "cancelled"
    assert saved["export_destination"] == str(tmp_path / "legacy-exports")


@pytest.fixture
def log_source(monkeypatch, tmp_path):
    now = datetime(2026, 10, 22, 16, 0, 0, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(bundles, "datetime", Clock)
    monkeypatch.setattr("ai_guardian.config.utils.get_state_dir", lambda: tmp_path)
    sanitizer = Mock(
        side_effect=lambda text: {
            "sanitized_text": text.replace("private-fragment", "[REDACTED]"),
            "stats": {"total": int("private-fragment" in text)},
        }
    )
    monkeypatch.setattr("ai_guardian.scanners.sanitizer.sanitize_text", sanitizer)
    path = tmp_path / "ai-guardian.log"

    def record(hours_ago, text):
        timestamp = (
            (now - timedelta(hours=hours_ago))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        return f"{timestamp} - v1.21.0 - test - INFO - {text}\n"

    return path, record, sanitizer


def test_only_last_twelve_hours_and_their_multiline_records_are_collected(log_source):
    path, record, sanitizer = log_source
    _write_text(
        path,
        "undated preamble\n"
        + record(13, "old-record")
        + "old traceback\n"
        + record(12, "boundary-record")
        + record(1, "recent private-fragment")
        + "recent traceback\n"
        + record(-1, "future-record"),
    )
    text, count = bundles._get_sanitized_log()
    assert "old-record" not in text and "old traceback" not in text
    assert "undated preamble" not in text and "future-record" not in text
    assert "boundary-record" in text and "recent traceback" in text
    assert "[REDACTED]" in text and "private-fragment" not in text
    assert count == 1
    assert "old-record" not in sanitizer.call_args.args[0]


def test_log_window_accepts_explicit_timezones_and_fractional_timestamps(log_source):
    path, _, _ = log_source
    _write_text(
        path,
        "2026-10-22T05:00:00Z - recent UTC\n2026-10-22 07:30:00,123+02:00 - recent offset\n2026-10-22T02:00:00+00:00 - too old\n",
    )
    text, _ = bundles._get_sanitized_log()
    assert "recent UTC" in text and "recent offset" in text
    assert "too old" not in text


def test_old_or_undated_log_is_not_collected(log_source):
    path, record, sanitizer = log_source
    _write_text(path, "unattributed content\n" + record(13, "old-record"))
    assert bundles._get_sanitized_log() == ("", 0)
    sanitizer.assert_not_called()


def test_large_log_keeps_recent_tail_without_reading_entire_source(
    log_source, monkeypatch
):
    path, record, _ = log_source
    _write_text(
        path,
        record(1, "first-record") + "old padding\n" * 1000 + record(0, "latest-record"),
    )
    original = path.read_bytes()
    monkeypatch.setattr(bundles, "MAX_PREVIEW_BYTES", 256)
    text, _ = bundles._get_sanitized_log()
    assert len(text.encode()) <= 256
    assert "latest-record" in text and "first-record" not in text
    assert "Truncated" in text
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "name", ["ai-guardian.json", "violations.jsonl", "state.ndjson"]
)
def test_non_log_files_are_never_shortened_even_when_the_viewer_limit_is_exceeded(
    tmp_path, monkeypatch, name
):
    path = tmp_path / name
    original = json.dumps({"begin": "BEGIN", "details": "record" * 500, "end": "END"})
    _write_text(path, original)
    assert review.truncate_text(original, name, 256) == (original, False)
    monkeypatch.setattr(review, "MAX_PREVIEW_BYTES", 256)
    parts = []
    offset = 0
    while True:
        page = review.read_preview(str(tmp_path), name, [name], offset=offset)
        parts.append(page.text)
        if page.next_offset is None:
            break
        assert page.next_offset > offset
        offset = page.next_offset
    assert len(parts) > 1
    assert "".join(parts) == original
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("name", ["ai-guardian.log", "ai-guardian.log.1"])
def test_prepared_log_excerpt_preserves_utf8_and_view_never_clips_it_again(
    tmp_path, name
):
    text, truncated = review.truncate_text("日本語🙂" * 1000 + "LATEST\n", name, 257)
    assert truncated is True
    assert len(text.encode("utf-8")) <= 257
    assert "Truncated" in text and "LATEST" in text and "�" not in text
    _write_text(tmp_path / name, text)
    assert review.read_preview(str(tmp_path), name, [name]).text == text


def test_view_does_not_show_a_smaller_excerpt_than_send_for_an_imported_log(
    tmp_path, monkeypatch
):
    name = "imported.log"
    original = "record\n" * 100 + "LATEST\n"
    _write_text(tmp_path / name, original)
    monkeypatch.setattr(review, "MAX_PREVIEW_BYTES", 256)
    page = review.read_preview(str(tmp_path), name, [name])
    assert page.next_offset is not None
    assert page.text == original[: page.next_offset]
    assert "Truncated" not in page.text
    assert (tmp_path / name).read_text(encoding="utf-8") == original


@pytest.fixture
def collectors(monkeypatch, tmp_path):
    from ai_guardian import doctor, smoke_test

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("ai_guardian.config.utils.get_config_dir", lambda: config_dir)
    monkeypatch.setattr(
        "ai_guardian.config.utils.get_state_dir", lambda: tmp_path / "state"
    )
    monkeypatch.setattr(
        "ai_guardian.config.utils.get_project_config_path", lambda: None
    )
    monkeypatch.setattr(bundles, "collect_cli_configs", lambda directory: [])
    monkeypatch.setattr(bundles, "_get_system_info", lambda: {"platform": "synthetic"})
    monkeypatch.setattr(gh, "public_text", lambda text: (text, 0))
    state = tmp_path / "state"
    state.mkdir()
    now = datetime.now(timezone.utc)
    _write_text(
        state / "violations.jsonl",
        "\n".join(
            json.dumps(
                {
                    "timestamp": (now - timedelta(hours=hours)).isoformat(),
                    "details": "record" * 100,
                    "message": message,
                }
            )
            for hours, message in [(2, "OLDEST-VIOLATION"), (1, "LATEST-VIOLATION")]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        doctor,
        "Doctor",
        lambda: SimpleNamespace(run_all=lambda: SimpleNamespace(checks=[])),
    )
    monkeypatch.setattr(
        smoke_test,
        "SmokeTestRunner",
        lambda: SimpleNamespace(
            run=lambda: SimpleNamespace(phase1_passed=True, phase2_results=[])
        ),
    )
    return config_dir


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("preclipped", [False, True])
def test_only_prepared_logs_are_truncated_and_view_matches_sent_content(
    collectors, monkeypatch, tmp_path, public, preclipped
):
    destination = gh.DESTINATION if public else str(tmp_path / "exports")
    monkeypatch.setattr(
        bundles, "_get_support_config", lambda: {"export_destination": destination}
    )
    monkeypatch.setattr(bundles, "MAX_PREVIEW_BYTES", 256)
    original = {
        "begin": "BEGIN-CONFIG",
        "padding": "details" * 1000,
        "end": "END-CONFIG",
    }
    source = collectors / "ai-guardian.json"
    _write_text(source, json.dumps(original))
    source_bytes = source.read_bytes()
    monkeypatch.setattr(
        bundles,
        "_get_sanitized_log",
        lambda: (
            (
                "[Truncated: older content omitted; showing newest data.]\nLATEST-LOG\n"
                if preclipped
                else "LOG-START\n" + "record\n" * 100 + "LATEST-LOG\n"
            ),
            2,
        ),
    )
    result = bundles.prepare_bundle()
    try:
        root = Path(result["temp_path"])
        names = [item["name"] for item in result["files"]]
        viewed = {
            name: review.read_preview(str(root), name, names).text for name in names
        }
        assert json.loads(viewed["ai-guardian.json"]) == original
        assert source.read_bytes() == source_bytes
        assert all(
            not item.get("truncated")
            for item in result["files"]
            if item["name"] != "ai-guardian.log"
        )
        events = json.loads(viewed["violations.jsonl"])
        assert [entry["message"] for entry in events] == [
            "LATEST-VIOLATION",
            "OLDEST-VIOLATION",
        ]
        log = next(
            item for item in result["files"] if item["name"] == "ai-guardian.log"
        )
        assert log["truncated"] is True
        assert "Last 12 hours" in log["note"]
        assert len(viewed["ai-guardian.log"].encode("utf-8")) <= 256
        assert "LATEST-LOG" in viewed["ai-guardian.log"]
        assert "LOG-START" not in viewed["ai-guardian.log"]
        assert "truncated" in bundles._format_prepare_human(result).lower()
        if public:
            files = gh._read_files(bundles._active_bundles[result["bundle_id"]])
            client = Mock()
            client.scrub.side_effect = lambda text: text
            uploaded, summary = gist.prepare_files(files, client)
            names = {item["name"]: item["gist_name"] for item in summary}
            assert all(
                uploaded[names[name]]["content"] == text
                for name, text in viewed.items()
                if name != gh.CONTEXT_FILE
            )
        else:
            sent = bundles.send_bundle(result["bundle_id"])
            assert sent["delivery_status"] == "local_only"
            assert all(
                Path(sent["destination"], name).read_text(encoding="utf-8") == text
                for name, text in viewed.items()
            )
    finally:
        bundles._cleanup_bundle(result["bundle_id"])


@pytest.mark.parametrize("public", [False, True])
def test_violations_include_all_complete_records_in_last_twelve_hours(
    collectors, log_source, monkeypatch, tmp_path, public
):
    path, _, _ = log_source
    now = bundles.datetime.now(timezone.utc)
    records = [
        {"timestamp": (now - timedelta(hours=13)).isoformat(), "message": "old"},
        {"timestamp": (now - timedelta(hours=12)).isoformat(), "message": "boundary"},
        *[
            {
                "timestamp": (now - timedelta(minutes=index)).isoformat(),
                "message": f"recent-{index}",
                "details": "Full ordinary event details. " * 30,
                "last_field": "END",
                "context": {"file_path": "/home/example/project/file.py"},
            }
            for index in range(180, -1, -1)
        ],
        {"timestamp": (now + timedelta(seconds=1)).isoformat(), "message": "future"},
        {"message": "no-timestamp"},
        {"timestamp": "invalid", "message": "bad-timestamp"},
        {"timestamp": 123, "message": "wrong-type"},
    ]
    source = path.parent / "violations.jsonl"
    _write_text(
        source,
        "\n".join(json.dumps(record) for record in records) + "\nnot-json\n[]\n",
        encoding="utf-8",
    )
    original = source.read_bytes()
    destination = gh.DESTINATION if public else str(tmp_path / "exports")
    monkeypatch.setattr(
        bundles, "_get_support_config", lambda: {"export_destination": destination}
    )
    result = bundles.prepare_bundle(include_log=False)
    try:
        root = Path(result["temp_path"])
        data = json.loads((root / "violations.jsonl").read_text(encoding="utf-8"))
        assert len(data) == 182  # No arbitrary newest-100 cap.
        assert data[0]["message"] == "recent-0" and data[-1]["message"] == "boundary"
        assert all(record["last_field"] == "END" for record in data[:-1])
        assert all(
            record["context"]["file_path"] == str(Path("...") / "project/file.py")
            for record in data[:-1]
        )
        info = next(
            item for item in result["files"] if item["name"] == "violations.jsonl"
        )
        assert "Last 12 hours" in info["note"] and not info.get("truncated")
        assert source.read_bytes() == original
    finally:
        bundles._cleanup_bundle(result["bundle_id"])


def test_violation_window_accepts_offsets_fractions_and_empty_sources(log_source):
    path, _, _ = log_source
    assert bundles._get_recent_support_violations() == []
    source = path.parent / "violations.jsonl"
    _write_text(
        source,
        "\n".join(
            json.dumps(record)
            for record in [
                {"timestamp": "2026-10-22T06:00:00.123+02:00", "message": "inside"},
                {"timestamp": "2026-10-22T04:00:00Z", "message": "boundary"},
                {"timestamp": "2026-10-22T03:59:59.999+00:00", "message": "old"},
            ]
        ),
        encoding="utf-8",
    )
    assert [
        record["message"] for record in bundles._get_recent_support_violations()
    ] == ["boundary", "inside"]


@pytest.mark.parametrize("padding", [25_000, 80_000])
def test_public_size_budget_only_clips_logs_and_never_configs(
    collectors, monkeypatch, padding
):
    monkeypatch.setattr(bundles, "_get_support_config", lambda: {})
    original = {"details": "x" * padding, "end": "END-CONFIG"}
    source = collectors / "ai-guardian.json"
    _write_text(source, json.dumps(original))
    monkeypatch.setattr(
        bundles,
        "_get_sanitized_log",
        lambda: ("OLD\n" + "recent log record\n" * 5000 + "LATEST\n", 0),
    )
    result = bundles.prepare_bundle(include_violations=False)
    try:
        root = Path(result["temp_path"])
        files = gh._read_files(bundles._active_bundles[result["bundle_id"]])
        assert json.loads(files["ai-guardian.json"]) == original
        assert "LATEST" in files["ai-guardian.log"].decode("utf-8")
        assert "Truncated" in files["ai-guardian.log"].decode("utf-8")
        assert review.read_preview(
            str(root), "ai-guardian.json", list(files)
        ).text == files["ai-guardian.json"].decode("utf-8")
        client = Mock()
        client.scrub.side_effect = lambda text: text
        # Gist files no longer consume the Discussion Markdown body limit.
        uploaded, summary = gist.prepare_files(files, client)
        names = {item["name"]: item["gist_name"] for item in summary}
        assert uploaded[names["ai-guardian.json"]]["content"] == files[
            "ai-guardian.json"
        ].decode("utf-8")
        assert uploaded[names["ai-guardian.log"]]["content"] == files[
            "ai-guardian.log"
        ].decode("utf-8")
        _, body = gh._publication(
            result["bundle_id"],
            "https://gist.github.com/reporter/" + "a" * 32,
            gh._context(files),
            client,
        )
        assert len(body.encode("utf-8")) < gh.MAX_BODY_BYTES
        assert "END-CONFIG" not in body
    finally:
        bundles._cleanup_bundle(result["bundle_id"])
