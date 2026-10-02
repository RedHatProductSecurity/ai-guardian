"""Tests for the NiceGUI-first interactive UI provider selection."""

import json
from unittest.mock import patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


def test_preferred_ui_accepts_supported_values(monkeypatch):
    from ai_guardian.ui.display import get_preferred_ui

    for value in ("auto", "tkinter", "nicegui", "headless"):
        monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", value)
        assert get_preferred_ui() == value


def test_removed_textual_config_is_migrated_to_nicegui(tmp_path, monkeypatch):
    from ai_guardian.ui.display import get_preferred_ui

    monkeypatch.delenv("AI_GUARDIAN_PREFERRED_UI", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "ai-guardian.json").write_text(
        json.dumps({"console": {"preferred_ui": "textual"}}),
        encoding="utf-8",
    )
    with patch("ai_guardian.config.utils.get_config_dir", return_value=config_dir):
        assert get_preferred_ui() == "nicegui"


def test_headless_provider_never_probes_other_ui(monkeypatch):
    from ai_guardian.ui.display import select_ui_provider

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "headless")
    with patch("ai_guardian.ui.display._tkinter_available") as tkinter:
        assert select_ui_provider("form") == "headless"
    tkinter.assert_not_called()


def test_auto_uses_nicegui_when_tkinter_is_unavailable(monkeypatch):
    from ai_guardian.ui.display import select_ui_provider

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    with patch("ai_guardian.ui.display._tkinter_available", return_value=False):
        assert select_ui_provider("form") == "nicegui"


def test_nicegui_preference_does_not_require_availability_probe(monkeypatch):
    from ai_guardian.ui.display import select_ui_provider

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "nicegui")
    with patch("ai_guardian.ui.display._tkinter_available") as tkinter:
        assert select_ui_provider("form") == "nicegui"
    tkinter.assert_not_called()


def test_action_dialog_uses_nicegui_without_tkinter(monkeypatch):
    from ai_guardian.ui.display import select_ui_provider

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    with patch("ai_guardian.ui.display._tkinter_available", return_value=False):
        assert select_ui_provider("action") == "nicegui"


def test_tray_prompt_never_requires_terminal(monkeypatch):
    from ai_guardian.ui.tray_prompt import TrayPromptApp

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    app = TrayPromptApp([], "echo test")
    assert app.needs_terminal is False


def test_tray_prompt_headless_rejects_interaction(monkeypatch):
    from ai_guardian.ui.tray_prompt import TrayPromptApp

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "headless")
    app = TrayPromptApp([], "echo test")
    with pytest.raises(RuntimeError, match="headless"):
        app.run()
