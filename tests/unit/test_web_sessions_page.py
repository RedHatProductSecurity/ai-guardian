"""Contracts for the unified web Sessions page."""

import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


def test_sessions_page_explains_cross_agent_correlation():
    """The page identifies the environment variable required by non-SDK agents."""
    from ai_guardian.web.pages.traces import create_traces_page

    source = inspect.getsource(create_traces_page)
    assert 'ui.label("Sessions")' in source
    assert "AI_GUARDIAN_RUN_ID" in source
    assert "SDK run_id" in source


def test_crashed_trace_is_displayed_as_interrupted():
    """The UI uses a neutral label while preserving the stored API value."""
    from ai_guardian.web.pages.traces import _display_stop_reason

    assert _display_stop_reason("crashed") == "interrupted"
    assert _display_stop_reason("error") == "error"


def test_session_timestamps_use_browser_local_time():
    """Session lists and details convert UTC timestamps in the browser."""
    from ai_guardian.web.pages.traces import (
        _render_run_group_card,
        _render_trace_card,
        _render_trace_list,
        create_trace_detail_page,
    )

    assert "local_time_label" in inspect.getsource(_render_run_group_card)
    assert "local_time_label" in inspect.getsource(_render_trace_card)
    assert "inject_local_time_js" in inspect.getsource(_render_trace_list)
    assert "local_time_label" in inspect.getsource(create_trace_detail_page)
    assert "inject_local_time_js" in inspect.getsource(create_trace_detail_page)


def test_tracing_settings_write_top_level_config():
    """The web UI must not write the deprecated SDK trace_viewer location."""
    from ai_guardian.web.pages.tracing_settings import create_tracing_settings_page

    source = inspect.getsource(create_tracing_settings_page)
    assert 'setdefault("tracing", {})' in source
    assert "trace_viewer" not in source
    assert "auto_refresh_interval_seconds" in source
    assert "trace_cache_retention_days" in source


def test_tracing_settings_reports_failed_config_writes():
    """Read-only or unavailable config targets must not report a false save."""
    from ai_guardian.web.pages.tracing_settings import create_tracing_settings_page

    source = inspect.getsource(create_tracing_settings_page)
    assert "saved = await run.io_bound(save_web_config, config)" in source
    assert "if not saved:" in source
    assert "read-only or unavailable" in source


def test_tracing_settings_number_labels_have_room_to_render():
    """Numeric settings stay wide enough to show their complete labels."""
    from ai_guardian.web.pages.tracing_settings import create_tracing_settings_page

    source = inspect.getsource(create_tracing_settings_page)
    assert source.count('.classes("w-full max-w-md")') == 2


def test_tracing_settings_hydration_does_not_save_and_enabled_edits_save_once(
    monkeypatch,
):
    """Initial control hydration is side-effect free, including enabled=True."""
    from ai_guardian.web.pages import tracing_settings

    class FakeElement:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def classes(self, *_args):
            return self

    class FakeControl(FakeElement):
        def __init__(self, value):
            self._value = value
            self.callbacks = []
            self.pending_changes = []

        @property
        def value(self):
            return self._value

        @value.setter
        def value(self, value):
            self._value = value
            self.pending_changes.extend(
                (callback, SimpleNamespace(value=value)) for callback in self.callbacks
            )

        def on_value_change(self, callback):
            self.callbacks.append(callback)

        async def flush_changes(self):
            pending_changes = self.pending_changes
            self.pending_changes = []
            for callback, event in pending_changes:
                result = callback(event)
                if inspect.isawaitable(result):
                    await result

        async def trigger_change(self, value):
            self.value = value
            await self.flush_changes()

    class FakeUI:
        def __init__(self):
            self.controls = {}
            self.timer_callback = None
            self.notifications = []

        def column(self):
            return FakeElement()

        def label(self, *_args):
            return FakeElement()

        def switch(self, label):
            control = FakeControl(False)
            self.controls[label] = control
            return control

        def number(self, label, value, **_kwargs):
            control = FakeControl(value)
            self.controls[label] = control
            return control

        def timer(self, _delay, callback, once=False):
            assert once is True
            self.timer_callback = callback

        def notify(self, message, **kwargs):
            self.notifications.append((message, kwargs))

    class FakeRun:
        @staticmethod
        async def io_bound(function, *args):
            return function(*args)

    fake_ui = FakeUI()
    saved_configs = []

    def load_config():
        return {
            "tracing": {
                "enabled": True,
                "auto_refresh_interval_seconds": 12,
                "trace_cache_retention_days": 45,
            }
        }

    def save_config(config):
        saved_configs.append(deepcopy(config))
        return True

    monkeypatch.setattr(tracing_settings, "ui", fake_ui)
    monkeypatch.setattr(tracing_settings, "run", FakeRun)
    monkeypatch.setattr(
        tracing_settings, "create_sidebar", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        tracing_settings, "create_header", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(tracing_settings, "load_web_config", load_config)
    monkeypatch.setattr(tracing_settings, "save_web_config", save_config)

    tracing_settings.create_tracing_settings_page(None, "local")
    asyncio.run(fake_ui.timer_callback())
    for control in fake_ui.controls.values():
        asyncio.run(control.flush_changes())

    enabled = fake_ui.controls["Record SDK and hook traces"]
    assert enabled.value is True
    assert fake_ui.controls["Auto-refresh interval (seconds)"].value == 12
    assert fake_ui.controls["Remote trace cache retention (days)"].value == 45
    assert saved_configs == []
    assert fake_ui.notifications == []

    asyncio.run(enabled.trigger_change(False))

    assert len(saved_configs) == 1
    assert saved_configs[0]["tracing"]["enabled"] is False


def test_sessions_page_has_day_navigation():
    """The unified Sessions page supports browsing one local day at a time."""
    from ai_guardian.web.pages.traces import create_traces_page

    source = inspect.getsource(create_traces_page)
    assert '"day": date.today()' in source
    assert "_previous_day" in source
    assert "_next_day" in source
    assert "_format_day_label" in source


def test_trace_local_day_converts_utc_timestamp_to_local_date():
    from datetime import datetime, timezone

    from ai_guardian.web.pages.traces import _trace_local_day

    timestamp = datetime(2025, 6, 15, 23, 45, tzinfo=timezone.utc).isoformat()
    assert (
        _trace_local_day(timestamp)
        == datetime.fromisoformat(timestamp).astimezone().date()
    )


def test_trace_local_day_handles_invalid_timestamp():
    from ai_guardian.web.pages.traces import _trace_local_day

    assert _trace_local_day(None) is None
    assert _trace_local_day("not-a-timestamp") is None
