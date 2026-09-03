"""Tests for reusable proactive tray prompts."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from ai_guardian.tray.proactive_prompt import (
    ProactivePromptDialog,
    ProactivePromptState,
)
from ai_guardian.tray.health import TrayHealthMonitor


def test_prompt_state_records_and_expires_snooze(tmp_path: Path):
    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    now = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)

    assert state.available("upgrade_v1.18.0", now)
    state.record("upgrade_v1.18.0", "snooze_1h", now)
    assert not state.available("upgrade_v1.18.0", now)
    assert state.available("upgrade_v1.18.0", now + timedelta(hours=1, seconds=1))


def test_prompt_state_dismissal_is_version_specific(tmp_path: Path):
    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    state.record("upgrade_v1.18.0", "dismiss")

    assert not state.available("upgrade_v1.18.0")
    assert state.available("upgrade_v1.19.0")


def test_prompt_state_does_not_persist_completed_action(tmp_path: Path):
    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    state.record("upgrade_v1.18.0", "action")

    assert not (tmp_path / "proactive_prompts.json").exists()


def test_prompt_uses_tkinter_first():
    dialog = ProactivePromptDialog("Title", "Message", "Update", "Skip")
    with (
        patch(
            "ai_guardian.tray.proactive_prompt.get_preferred_ui", return_value="auto"
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._tkinter_available", return_value=True
        ),
        patch.object(dialog, "_show_tkinter", return_value="action") as show,
    ):
        assert dialog.show() == "action"
    show.assert_called_once_with()


def test_tray_prompt_uses_tkinter_subprocess():
    dialog = ProactivePromptDialog("Title", "Message", "Update", "Skip")
    with (
        patch(
            "ai_guardian.tray.proactive_prompt.get_preferred_ui", return_value="auto"
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._tkinter_available", return_value=True
        ),
        patch.object(dialog, "_show_tkinter_subprocess", return_value="action") as show,
    ):
        assert dialog.show(tray_safe=True) == "action"
    show.assert_called_once_with()


def test_prompt_falls_back_to_headless_when_ui_unavailable():
    dialog = ProactivePromptDialog("Title", "Message", "Update", "Skip")
    with (
        patch(
            "ai_guardian.tray.proactive_prompt.get_preferred_ui", return_value="auto"
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._tkinter_available", return_value=False
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._nicegui_available", return_value=False
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._textual_available", return_value=False
        ),
    ):
        assert dialog.show() == "dismiss"


def test_upgrade_prompt_skips_remote_only_trays():
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)
    monitor._pypi_latest = "9.9.9"

    with patch.object(monitor, "_is_self_upgrade_available", return_value=True):
        monitor._check_self_upgrade_notification()

    assert monitor._upgrade_prompt_in_progress is False


def test_upgrade_prompt_records_snooze_for_local_tray(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    monitor._pypi_latest = "9.9.9"

    with (
        patch.object(monitor, "_is_self_upgrade_available", return_value=True),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="snooze_1h",
        ),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_self_upgrade_notification()

    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    assert not state.available("upgrade_v9.9.9")


def test_ide_setup_prompt_skips_remote_only_tray():
    tray = SimpleNamespace(
        _standalone=False,
        _targets=[SimpleNamespace(name="container", runtime="container")],
    )
    monitor = TrayHealthMonitor(tray)

    with patch.object(monitor, "_get_unconfigured_ides") as detected:
        monitor._check_ide_setup_notification()

    detected.assert_not_called()


def test_ide_setup_prompt_configures_detected_local_ides(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_get_unconfigured_ides", return_value=["claude"]),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="action",
        ),
        patch("ai_guardian.setup.setup_hooks") as setup_hooks,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    setup_hooks.assert_called_once_with(ide_type="claude", interactive=False)


def test_ide_setup_prompt_snoozes_local_prompt(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_get_unconfigured_ides", return_value=["cursor"]),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="snooze_1h",
        ),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    assert not state.available("ide_setup_cursor")
