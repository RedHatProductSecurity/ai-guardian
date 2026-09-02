"""Navigation contracts for agent activity pages in the TUI."""


def test_ai_sessions_prioritizes_security_sessions():
    """Security sessions are primary and raw IDE conversations are secondary."""
    from ai_guardian.tui.app import NAV_GROUPS

    groups = dict(NAV_GROUPS)
    assert groups["AI Sessions"] == [
        ("Sessions", "panel-traces"),
        ("Tracing Settings", "panel-tracing-settings"),
        ("OTEL Export", "panel-otel-settings"),
        ("IDE Conversations", "panel-ide-sessions"),
    ]


def test_sessions_help_explains_cross_agent_correlation():
    """The Sessions help identifies the non-SDK correlation contract."""
    from ai_guardian.tui.app import HELP_DOCS

    help_text = HELP_DOCS["panel-traces"]
    assert "AI_GUARDIAN_RUN_ID" in help_text
    assert "RunContext run_id" in help_text


def test_crashed_trace_is_displayed_as_interrupted():
    """An unfinalized recording must not imply that the agent crashed."""
    from ai_guardian.tui.traces import _format_trace_label

    label = _format_trace_label({"agent_name": "agent", "stop_reason": "crashed"})
    assert "INTERRUPTED" in label
    assert "CRASHED" not in label


def test_tracing_settings_write_top_level_config():
    """The TUI writes top-level tracing and preserves the legacy section."""
    from ai_guardian.tui.tracing_settings import TracingSettingsContent

    content = TracingSettingsContent.__new__(TracingSettingsContent)
    config = {
        "sdk": {"trace_viewer": {"enabled": True}},
        "tracing": {"trace_cache_retention_days": 90},
    }
    written = []
    content._load_full_config = lambda: config
    content._write_full_config = lambda value: written.append(value) or True
    content._set_status = lambda *args, **kwargs: None

    content._save_value("enabled", False)

    assert written == [config]
    assert config["tracing"]["enabled"] is False
    assert config["sdk"]["trace_viewer"]["enabled"] is True
