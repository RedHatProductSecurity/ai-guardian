"""Capability-aware modal policy and runtime lifecycle contracts."""

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


def test_windows_action_dialog_uses_nicegui_without_tkinter(monkeypatch):
    from ai_guardian.ui.display import select_ui_provider

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    with (
        patch("platform.system", return_value="Windows"),
        patch("ai_guardian.ui.display._tkinter_available", return_value=False),
    ):
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


@pytest.mark.parametrize("system", ["Darwin", "Linux", "Windows"])
@pytest.mark.parametrize(
    "kind", ["simple", "confirmation", "picker", "action", "setup", "form", "stream"]
)
def test_automatic_capability_matrix(system, kind, monkeypatch):
    from ai_guardian.ui.display import ui_provider_order

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    with (
        patch("platform.system", return_value=system),
        patch("ai_guardian.ui.display._tkinter_available", return_value=True),
    ):
        native = (
            kind in {"simple", "confirmation", "picker"}
            or (kind == "action" and system != "Windows")
            or (kind == "setup" and system == "Darwin")
        )
        assert ui_provider_order(kind) == (
            ("native", "tkinter", "nicegui") if native else ("tkinter", "nicegui")
        )


@pytest.mark.parametrize("preferred", ["tkinter", "nicegui", "headless"])
def test_explicit_preferences_are_exclusive(preferred, monkeypatch):
    from ai_guardian.ui.display import ui_provider_order

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", preferred)
    with patch("ai_guardian.ui.display._tkinter_available", return_value=True):
        assert ui_provider_order("simple") == (
            () if preferred == "headless" else (preferred,)
        )


@pytest.mark.parametrize("value", [None, False, "dismiss", "timeout", "action"])
def test_completed_interaction_never_advances(value, monkeypatch):
    from unittest.mock import Mock
    from ai_guardian.ui.modal import run_modal

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    first, second = Mock(return_value=value), Mock()
    with patch("ai_guardian.ui.display._tkinter_available", return_value=True):
        assert (
            run_modal("form", {"tkinter": first, "nicegui": second}, fallback=None)
            == value
        )
    second.assert_not_called()


@pytest.mark.parametrize("startup", [True, False])
def test_only_explicit_startup_failure_advances(startup, monkeypatch):
    from unittest.mock import Mock
    from ai_guardian.ui.modal import UIUnavailable, run_modal

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    first = Mock(side_effect=UIUnavailable() if startup else RuntimeError())
    second = Mock(return_value="complete")
    with patch("ai_guardian.ui.display._tkinter_available", return_value=True):
        assert run_modal(
            "form", {"tkinter": first, "nicegui": second}, fallback=None
        ) == ("complete" if startup else None)
    assert second.call_count == int(startup)


@pytest.mark.parametrize(
    "kind", ["simple", "confirmation", "picker", "action", "setup"]
)
def test_macos_placement_policy_preserves_cocoa_capability(kind, monkeypatch):
    from ai_guardian.ui.display import ui_provider_order

    monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")
    with (
        patch("platform.system", return_value="Darwin"),
        patch("ai_guardian.ui.display._tkinter_available", return_value=True),
    ):
        order = ui_provider_order(kind, screen_bounds=(1920, 0, 1920, 1080))
    assert order == (
        ("native", "tkinter", "nicegui")
        if kind in {"action", "setup"}
        else ("tkinter", "nicegui")
    )


def test_console_description_matches_the_modal_policy():
    from ai_guardian.web.pages.console_settings import UI_TOOLKIT_DESCRIPTIONS

    assert (
        UI_TOOLKIT_DESCRIPTIONS["auto"]
        == "Native → Tkinter → NiceGUI, among capable providers; startup failures only."
    )
