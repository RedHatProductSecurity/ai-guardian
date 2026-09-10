"""Tests for reusable proactive tray prompts."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import pytest

from ai_guardian.constants import CODEX_COVERAGE_NOTE
from ai_guardian.setup.hooks import IDESetup
from ai_guardian.tray.proactive_prompt import (
    ProactivePromptDialog,
    ProactivePromptState,
    reset_ide_setup_state,
    sync_ide_setup_state,
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


def test_prompt_state_persists_per_ide_exclusions_and_manual_override(tmp_path: Path):
    state = ProactivePromptState(tmp_path / "proactive_prompts.json")

    state.update_ide_setup_exclusions(never=("cursor", "claude"))
    assert state.get_ide_setup_exclusions() == {"claude", "cursor"}

    state.update_ide_setup_exclusions(install=("cursor",))
    assert state.get_ide_setup_exclusions() == {"claude"}


def test_sync_ide_setup_state_records_current_reality_and_keeps_history(tmp_path):
    class FakeIDESetup:
        IDE_CONFIGS = {
            "claude": {"name": "Claude Code"},
            "cursor": {"name": "Cursor IDE"},
        }

        def list_installed_ides(self):
            return ["claude", "cursor"]

        def verify_hooks_for_ide(self, ide_type):
            return {
                "ide": ide_type,
                "config_path": f"/{ide_type}/settings.json",
                "healthy": ide_type == "claude",
                "events": {
                    "PreToolUse": "healthy" if ide_type == "claude" else "missing"
                },
                "obsolete": [],
            }

    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    state.record("ide_setup_claude_codex_cursor", "dismiss")
    state.update_ide_setup_exclusions(never=("cursor",))
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)

    snapshot = sync_ide_setup_state(state=state, setup=FakeIDESetup(), now=now)

    assert snapshot["checked_at"] == "2026-09-06T12:00:00Z"
    assert snapshot["installed"] == ["claude", "cursor"]
    assert snapshot["configured"] == ["claude"]
    assert snapshot["needs_setup"] == ["cursor"]
    assert snapshot["never_install"] == ["cursor"]
    assert snapshot["integrations"]["cursor"]["excluded"] is True
    saved = state.load()
    assert saved["ide_setup_claude_codex_cursor"]["status"] == "dismissed"
    assert saved["ide_setup_status"] == snapshot


def test_sync_ide_setup_state_skips_never_install_when_requested(tmp_path):
    class FakeIDESetup:
        IDE_CONFIGS = {
            "claude": {"name": "Claude Code"},
            "cursor": {"name": "Cursor IDE"},
        }

        def __init__(self):
            self.healthy = {"claude": True, "cursor": True}
            self.verify_calls = []

        def list_installed_ides(self):
            return ["claude", "cursor"]

        def verify_hooks_for_ide(self, ide_type):
            self.verify_calls.append(ide_type)
            status = "healthy" if self.healthy[ide_type] else "missing"
            return {
                "ide": ide_type,
                "healthy": self.healthy[ide_type],
                "events": {"PreToolUse": status},
                "obsolete": [],
            }

    setup = FakeIDESetup()
    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    sync_ide_setup_state(state=state, setup=setup)
    state.update_ide_setup_exclusions(never=("cursor",))
    setup.verify_calls.clear()
    setup.healthy["cursor"] = False

    snapshot = sync_ide_setup_state(
        state=state,
        setup=setup,
        skip_excluded=True,
    )

    assert setup.verify_calls == ["claude"]
    assert snapshot["integrations"]["cursor"]["healthy"] is True
    assert snapshot["integrations"]["cursor"]["excluded"] is True
    assert snapshot["integrations"]["cursor"]["verification_skipped"] is True


def test_reset_ide_setup_clears_one_ide_history_and_exclusion(tmp_path):
    path = tmp_path / "proactive_prompts.json"
    state = ProactivePromptState(path)
    state.save(
        {
            "ide_setup_claude_crush": {"status": "dismissed"},
            "ide_setup_codex_cursor": {"status": "snoozed"},
            "ide_setup_never_install": ["claude", "cursor"],
            "ide_setup_status": {
                "never_install": ["claude", "cursor"],
                "integrations": {
                    "claude": {"excluded": True},
                    "cursor": {"excluded": True},
                },
            },
        }
    )

    result = reset_ide_setup_state("claude", state=state)

    assert result["changed"] is True
    assert result["removed_prompt_keys"] == ["ide_setup_claude_crush"]
    assert result["removed_exclusion"] is True
    saved = state.load()
    assert "ide_setup_claude_crush" not in saved
    assert "ide_setup_codex_cursor" in saved
    assert saved["ide_setup_never_install"] == ["cursor"]
    assert saved["ide_setup_status"]["never_install"] == ["cursor"]
    assert saved["ide_setup_status"]["integrations"]["claude"]["excluded"] is False


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
        patch("platform.system", return_value="Darwin"),
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


def test_linux_tray_prompt_uses_in_process_tkinter():
    dialog = ProactivePromptDialog("Title", "Message", "Update", "Skip")
    with (
        patch("platform.system", return_value="Linux"),
        patch(
            "ai_guardian.tray.proactive_prompt.get_preferred_ui", return_value="auto"
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._tkinter_available", return_value=True
        ),
        patch.object(dialog, "_show_tkinter", return_value="action") as tkinter,
        patch.object(dialog, "_show_tkinter_subprocess") as subprocess_tkinter,
        patch.object(dialog, "_show_native_fallback", return_value=None) as native,
    ):
        assert dialog.show(tray_safe=True) == "action"

    native.assert_called_once_with()
    tkinter.assert_called_once_with()
    subprocess_tkinter.assert_not_called()


def test_tray_prompt_uses_native_fallback_on_macos_when_foreground_ui_unavailable():
    dialog = ProactivePromptDialog("Title", "Message", "Set Up", "Cancel")
    with (
        patch("platform.system", return_value="Darwin"),
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
        patch.object(
            dialog, "_show_native_fallback", return_value="action"
        ) as fallback,
        patch.object(dialog, "_show_tkinter_subprocess") as tkinter,
    ):
        assert dialog.show(tray_safe=True) == "action"

    tkinter.assert_not_called()
    fallback.assert_called_once_with()


def test_linux_tray_prompt_uses_native_fallback_when_ui_tiers_fail():
    dialog = ProactivePromptDialog("Title", "Message", "Set Up", "Cancel")
    with (
        patch("platform.system", return_value="Linux"),
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
        patch.object(
            dialog, "_show_native_fallback", return_value="action"
        ) as fallback,
    ):
        assert dialog.show(tray_safe=True) == "action"

    fallback.assert_called_once_with()


def test_tray_prompt_uses_tkinter_subprocess_before_nicegui_on_macos():
    dialog = ProactivePromptDialog("Title", "Message", "Set Up", "Cancel")
    with (
        patch("platform.system", return_value="Darwin"),
        patch(
            "ai_guardian.tray.proactive_prompt.get_preferred_ui", return_value="auto"
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._tkinter_available", return_value=True
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._nicegui_available", return_value=True
        ) as nicegui_available,
        patch.object(
            dialog, "_show_tkinter_subprocess", return_value="action"
        ) as tkinter,
        patch.object(dialog, "_show_nicegui") as nicegui,
    ):
        assert dialog.show(tray_safe=True) == "action"

    tkinter.assert_called_once_with()
    nicegui.assert_not_called()
    nicegui_available.assert_not_called()


def test_tkinter_subprocess_failure_returns_none_for_fallback():
    dialog = ProactivePromptDialog("Title", "Message", "Update", "Skip")
    failed = SimpleNamespace(returncode=1, stdout="", stderr="Tk failed")

    with patch("subprocess.run", return_value=failed):
        assert dialog._show_tkinter_subprocess() is None


def test_tkinter_subprocess_failure_falls_back_to_native_macos_prompt():
    dialog = ProactivePromptDialog("Title", "Message", "Update", "Skip")
    failed = SimpleNamespace(returncode=1, stdout="", stderr="Tk failed")
    with (
        patch("platform.system", return_value="Darwin"),
        patch(
            "ai_guardian.tray.proactive_prompt.get_preferred_ui", return_value="auto"
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._tkinter_available", return_value=True
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._nicegui_available"
        ) as nicegui_available,
        patch(
            "ai_guardian.tray.proactive_prompt._textual_available", return_value=False
        ),
        patch("subprocess.run", return_value=failed) as subprocess_run,
        patch.object(
            dialog, "_show_native_fallback", return_value="action"
        ) as fallback,
    ):
        assert dialog.show(tray_safe=True) == "action"

    subprocess_run.assert_called_once()
    fallback.assert_called_once_with()
    nicegui_available.assert_not_called()


def test_tkinter_subprocess_failure_logs_complete_diagnostic(caplog):
    dialog = ProactivePromptDialog("Title", "Message", "Update", "Skip")
    diagnostic = "Traceback (most recent call last):\n" + ("diagnostic detail\n" * 100)
    failed = SimpleNamespace(returncode=1, stdout="", stderr=diagnostic)

    with (
        caplog.at_level("WARNING", logger="ai_guardian.tray.proactive_prompt"),
        patch("subprocess.run", return_value=failed),
    ):
        assert dialog._show_tkinter_subprocess() is None

    assert diagnostic in caplog.text


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


def test_multi_ide_prompt_defaults_to_install_now():
    dialog = ProactivePromptDialog(
        "Title",
        "Message",
        "Continue",
        "Cancel",
        ide_choices=[
            {"ide": "claude", "name": "Claude Code"},
            {"ide": "cursor", "name": "Cursor IDE"},
        ],
    )

    assert dialog._default_ide_selection() == {
        "result": "action",
        "install": ["claude", "cursor"],
        "never": [],
    }


def test_multi_ide_prompt_never_excludes_all_displayed_integrations():
    dialog = ProactivePromptDialog(
        "Title",
        "Message",
        "Continue",
        "Never",
        ide_choices=[
            {"ide": "claude", "name": "Claude Code"},
            {"ide": "cursor", "name": "Cursor IDE/CLI"},
        ],
    )

    assert dialog._never_ide_selection() == {
        "result": "action",
        "install": [],
        "never": ["claude", "cursor"],
    }


def test_profile_prompt_defaults_to_standard_and_includes_skip_choice():
    dialog = ProactivePromptDialog(
        "Title",
        "Message",
        "Continue",
        "Cancel",
        profile_choices=TrayHealthMonitor._security_profile_choices(),
    )

    assert [choice["profile"] for choice in dialog._profile_options()] == [
        "@minimal",
        "@standard",
        "@strict",
        "@moderator",
        None,
    ]
    assert dialog._default_profile_selection() == "@standard"
    assert dialog._ide_selection_result("action", profile="@strict") == {
        "result": "action",
        "install": [],
        "never": [],
        "profile": "@strict",
    }


def test_user_config_detection_ignores_project_local_config(tmp_path, monkeypatch):
    global_config_dir = tmp_path / "global-config"
    global_config_dir.mkdir()
    project_dir = tmp_path / "project"
    project_config_dir = project_dir / ".ai-guardian"
    project_config_dir.mkdir(parents=True)
    (project_config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(global_config_dir))
    monkeypatch.chdir(project_dir)

    monitor = TrayHealthMonitor(SimpleNamespace(_standalone=True, _targets=[]))

    assert monitor._has_user_config() is False
    (global_config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")
    assert monitor._has_user_config() is True


def test_missing_user_config_creates_selected_profile_before_hook_setup(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    calls = []

    def create_config(**kwargs):
        calls.append(("config", kwargs))
        return True, "created"

    def setup_hooks(**kwargs):
        calls.append(("hooks", kwargs))
        return True

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_has_user_config", return_value=False),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["claude"]),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": True,
                "events": {"PreToolUse": "healthy"},
                "obsolete": [],
            },
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch("ai_guardian.tray.proactive_prompt.ProactivePromptDialog") as dialog,
        patch("ai_guardian.setup.create_default_config", side_effect=create_config),
        patch("ai_guardian.setup.setup_hooks", side_effect=setup_hooks),
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        dialog.return_value.show.return_value = {
            "result": "action",
            "profile": "@strict",
        }
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    assert calls == [
        ("config", {"profile": "@strict", "force": False}),
        ("hooks", {"ide_type": "claude", "interactive": False}),
    ]
    assert dialog.call_args.kwargs["profile_choices"] == (
        monitor._security_profile_choices()
    )


def test_missing_user_config_can_skip_profile_and_setup_hooks(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_has_user_config", return_value=False),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["claude"]),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": True,
                "events": {"PreToolUse": "healthy"},
                "obsolete": [],
            },
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value={"result": "action", "profile": None},
        ),
        patch("ai_guardian.setup.create_default_config") as create_config,
        patch("ai_guardian.setup.setup_hooks", return_value=True) as setup_hooks,
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    create_config.assert_not_called()
    setup_hooks.assert_called_once_with(ide_type="claude", interactive=False)


def test_first_run_profile_prompt_preserves_single_ide_dismissal_state(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    state_path = tmp_path / "proactive_prompts.json"

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_has_user_config", return_value=False),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["claude"]),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": False,
                "events": {"PreToolUse": "missing"},
                "obsolete": [],
            },
        ),
        patch("ai_guardian.tray.proactive_prompt._state_path", return_value=state_path),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value={"result": "dismiss", "profile": None},
        ),
        patch("ai_guardian.setup.create_default_config") as create_config,
        patch("ai_guardian.setup.setup_hooks") as setup_hooks,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    assert ProactivePromptState(state_path).load()["ide_setup_claude"]["status"] == (
        "dismissed"
    )
    create_config.assert_not_called()
    setup_hooks.assert_not_called()


def test_profile_creation_failure_stops_hook_setup_and_snoozes_prompt(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    state_path = tmp_path / "proactive_prompts.json"

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_has_user_config", return_value=False),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["claude"]),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": False,
                "events": {"PreToolUse": "missing"},
                "obsolete": [],
            },
        ),
        patch("ai_guardian.tray.proactive_prompt._state_path", return_value=state_path),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value={"result": "action", "profile": "@strict"},
        ),
        patch(
            "ai_guardian.setup.create_default_config",
            return_value=(False, "configuration could not be written"),
        ) as create_config,
        patch("ai_guardian.setup.setup_hooks") as setup_hooks,
        patch("ai_guardian.tray.plugins.send_notification") as notify,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    create_config.assert_called_once_with(profile="@strict", force=False)
    setup_hooks.assert_not_called()
    assert ProactivePromptState(state_path).load()["ide_setup_claude"]["status"] == (
        "snoozed"
    )
    notify.assert_called_once_with(
        "AI Guardian Setup",
        "Unable to create the AI Guardian security profile @strict.\n\n"
        "configuration could not be written",
    )


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


@pytest.mark.parametrize("runtime", ["container", "kubernetes", "manual"])
def test_ide_setup_prompt_skips_remote_only_tray(runtime):
    tray = SimpleNamespace(
        _standalone=False,
        _targets=[SimpleNamespace(name=runtime, runtime=runtime)],
    )
    monitor = TrayHealthMonitor(tray)

    with patch.object(monitor, "_get_unconfigured_ides") as detected:
        monitor._check_ide_setup_notification()

    detected.assert_not_called()


def test_manual_ide_check_reports_all_configured():
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_get_installed_ides", return_value=["claude"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=[]),
        patch("ai_guardian.tray.plugins.send_notification") as notify,
    ):
        monitor._check_ide_setup_notification(manual=True)

    notify.assert_called_once_with(
        "AI Guardian",
        "All installed IDE/CLI integrations are configured:\n• Claude Code",
    )


def test_ide_health_notification_explains_configured_and_pending_counts():
    with patch("ai_guardian.tray.plugins.send_notification") as notify:
        TrayHealthMonitor._notify_ide_check_result(
            ["claude", "cursor", "codex"],
            unconfigured=["cursor"],
        )

    notify.assert_called_once_with(
        "AI Guardian",
        "IDE/CLI health check: 2 configured, 1 need setup.\n\n"
        "Configured:\n"
        "• Claude Code\n"
        f"• OpenAI Codex (CLI + Desktop) ({CODEX_COVERAGE_NOTE})\n\n"
        "Needs setup:\n"
        "• Cursor IDE/CLI",
    )


def test_manual_ide_check_falls_back_to_dialog_when_notification_fails():
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_get_installed_ides", return_value=["claude"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=[]),
        patch(
            "ai_guardian.tray.plugins.send_notification", return_value=False
        ) as notify,
        patch("ai_guardian.tray.plugins.show_dialog", return_value=True) as dialog,
    ):
        monitor._check_ide_setup_notification(manual=True)

    notify.assert_called_once_with(
        "AI Guardian",
        "All installed IDE/CLI integrations are configured:\n• Claude Code",
    )
    dialog.assert_called_once_with(
        "AI Guardian",
        "All installed IDE/CLI integrations are configured:\n• Claude Code",
    )


def test_manual_ide_check_does_not_open_popup_when_notification_succeeds():
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)
    message = "All installed IDE/CLI integrations are configured:\n• Claude Code"

    with (
        patch("platform.system", return_value="Darwin"),
        patch.object(monitor, "_get_installed_ides", return_value=["claude"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=[]),
        patch(
            "ai_guardian.tray.plugins.send_notification", return_value=True
        ) as notify,
        patch("ai_guardian.tray.plugins.show_dialog", return_value=True) as dialog,
    ):
        monitor._check_ide_setup_notification(manual=True)

    notify.assert_called_once_with("AI Guardian", message)
    dialog.assert_not_called()


def test_manual_ide_check_action_runs_a_manual_check():
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_check_ide_setup_notification") as check,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ](**thread.call_args.kwargs["kwargs"])
        monitor._on_check_ide_setup(None, None)

    check.assert_called_once_with(manual=True)


def test_startup_ide_check_runs_an_automatic_check():
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_check_ide_setup_notification") as check,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ](**thread.call_args.kwargs["kwargs"])
        monitor._on_startup_ide_setup()

    check.assert_called_once_with(manual=False, report_result=True)


def test_overlapping_startup_and_manual_ide_checks_are_deduplicated():
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with patch("ai_guardian.tray.health.threading.Thread") as thread:
        monitor._start_ide_setup_check(
            manual=False,
            name="ide-setup-startup-check",
            report_result=True,
        )
        monitor._start_ide_setup_check(
            manual=True,
            name="ide-setup-check",
        )

    assert thread.call_count == 1


def test_startup_ide_check_reports_health_result_once():
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    message = "All installed IDE/CLI integrations are configured:\n• Claude Code"

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_get_installed_ides", return_value=["claude"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=[]),
        patch("ai_guardian.tray.plugins.send_notification") as notify,
    ):
        monitor._check_ide_setup_notification(report_result=True)

    notify.assert_called_once_with("AI Guardian", message)


def test_startup_ide_check_prompts_when_setup_is_missing(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_get_installed_ides", return_value=["cursor"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["cursor"]),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": False,
                "events": {"beforeTabFileRead": "missing"},
                "obsolete": [],
            },
        ),
        patch.object(monitor, "_has_user_config", return_value=True),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="dismiss",
        ) as show,
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification(report_result=True)

    show.assert_called_once()


def test_ide_setup_prompt_configures_installed_local_ides(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["claude"]),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="action",
        ),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": True,
                "events": {
                    "PreToolUse": "healthy",
                    "PostToolUse": "healthy",
                },
                "obsolete": [],
            },
        ),
        patch("ai_guardian.setup.setup_hooks") as setup_hooks,
        patch("ai_guardian.tray.plugins.send_notification") as notify,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    setup_hooks.assert_called_once_with(ide_type="claude", interactive=False)
    notify.assert_called_once_with(
        "AI Guardian Setup",
        "IDE/CLI setup result\n\n"
        "[PASS] Claude Code: 2/2 hooks configured\n\n"
        "1 passed",
    )


def test_codex_setup_result_reports_managed_hook_count():
    managed_events = IDESetup().expected_hook_manifest("codex")
    events = {event: "healthy" for event in managed_events}
    events.update(
        {
            event: "healthy"
            for event in (
                "SessionStart",
                "PermissionRequest",
                "PreCompact",
                "SubagentStart",
                "SubagentStop",
                "Stop",
                "Interrupt",
            )
        }
    )
    verification = {
        "healthy": True,
        "events": events,
        "obsolete": [],
    }

    with patch("ai_guardian.tray.plugins.send_notification") as notify:
        TrayHealthMonitor._notify_ide_setup_result(
            [
                {
                    "ide": "codex",
                    "success": True,
                    "verification": verification,
                }
            ]
        )

    assert (
        "[PASS] OpenAI Codex (CLI + Desktop): 5/5 hooks configured"
        in notify.call_args.args[1]
    )
    assert CODEX_COVERAGE_NOTE in notify.call_args.args[1]


def test_setup_result_uses_final_verification_health_over_setup_return():
    verification = {
        "healthy": True,
        "events": {"PreToolUse": "healthy"},
        "obsolete": [],
    }

    with patch("ai_guardian.tray.plugins.send_notification") as notify:
        TrayHealthMonitor._notify_ide_setup_result(
            [
                {
                    "ide": "claude",
                    "success": False,
                    "verification": verification,
                }
            ]
        )

    message = notify.call_args.args[1]
    assert "[PASS] Claude Code: 1/1 hooks configured" in message
    assert "setup failed" not in message


def test_setup_result_falls_back_to_dialog_when_notification_fails():
    verification = {
        "healthy": True,
        "events": {"PreToolUse": "healthy"},
        "obsolete": [],
    }
    message = (
        "IDE/CLI setup result\n\n[PASS] Claude Code: 1/1 hooks configured\n\n1 passed"
    )

    with (
        patch("ai_guardian.tray.plugins.send_notification", return_value=False),
        patch("ai_guardian.tray.plugins.show_dialog", return_value=True) as dialog,
    ):
        TrayHealthMonitor._notify_ide_setup_result(
            [
                {
                    "ide": "claude",
                    "success": True,
                    "verification": verification,
                }
            ]
        )

    dialog.assert_called_once_with("AI Guardian Setup", message)


def test_setup_result_names_integrations_not_configured_in_selected_batch():
    with patch("ai_guardian.tray.plugins.send_notification") as notify:
        TrayHealthMonitor._notify_ide_setup_result(
            [
                {
                    "ide": "claude",
                    "success": True,
                    "verification": {
                        "healthy": True,
                        "events": {"PreToolUse": "healthy"},
                        "obsolete": [],
                    },
                },
            ],
            remaining=["cursor"],
        )

    assert "1 passed" in notify.call_args.args[1]
    assert "Still needs setup (1):\n• Cursor IDE/CLI" in notify.call_args.args[1]


def test_ide_setup_prompt_snoozes_local_prompt(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
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


def test_multi_ide_setup_prompt_snoozes_structured_prompt(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": False,
        "events": {"PreToolUse": "missing"},
        "obsolete": [],
    }
    state_path = tmp_path / "proactive_prompts.json"

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_has_user_config", return_value=True),
        patch.object(
            monitor,
            "_get_unconfigured_ides",
            return_value=["claude", "cursor"],
        ),
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=state_path,
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value={
                "result": "snooze_1h",
                "install": [],
                "never": [],
            },
        ) as show,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()
        monitor._check_ide_setup_notification()

    state = ProactivePromptState(state_path)
    assert not state.available("ide_setup_claude_cursor")
    show.assert_called_once()


def test_ide_setup_prompt_snoozes_after_failed_setup(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": False,
        "events": {"PreToolUse": "missing"},
        "obsolete": [],
    }

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["codex"]),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="action",
        ) as show,
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
        patch("ai_guardian.setup.setup_hooks", return_value=False),
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()
        monitor._check_ide_setup_notification()

    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    assert state.load()["ide_setup_codex"]["status"] == "snoozed"
    assert not state.available("ide_setup_codex")
    show.assert_called_once()


def test_ide_setup_prompt_does_not_snooze_when_final_verification_is_healthy(
    tmp_path,
):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": True,
        "events": {"PreToolUse": "healthy"},
        "obsolete": [],
    }

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["codex"]),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="action",
        ),
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
        patch("ai_guardian.setup.setup_hooks", return_value=False),
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    assert "ide_setup_codex" not in state.load()


def test_multi_ide_prompt_only_configures_selected_integrations(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": False,
        "events": {"PreToolUse": "missing"},
        "obsolete": [],
    }

    with (
        patch.object(
            monitor,
            "_get_unconfigured_ides",
            return_value=["claude", "cursor"],
        ),
        patch.object(monitor, "_has_user_config", return_value=True),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value={
                "result": "action",
                "install": ["claude"],
                "never": ["cursor"],
            },
        ),
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
        patch("ai_guardian.setup.setup_hooks", return_value=True) as setup_hooks,
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    setup_hooks.assert_called_once_with(ide_type="claude", interactive=False)
    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    assert state.get_ide_setup_exclusions() == {"cursor"}


def test_never_install_exclusion_suppresses_automatic_prompt(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    state = ProactivePromptState(tmp_path / "proactive_prompts.json")
    state.update_ide_setup_exclusions(never=("cursor",))

    with (
        patch.object(monitor, "_get_unconfigured_ides", return_value=["cursor"]),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": False,
                "events": {"PreToolUse": "missing"},
                "obsolete": [],
            },
        ),
        patch("ai_guardian.tray.proactive_prompt.ProactivePromptDialog") as dialog,
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
    ):
        monitor._check_ide_setup_notification()

    dialog.assert_not_called()


def test_automatic_monitoring_does_not_recheck_never_install(tmp_path):
    class FakeIDESetup:
        IDE_CONFIGS = {"claude": {"name": "Claude Code"}}

        def __init__(self):
            self.healthy = True
            self.verify_calls = 0

        def list_installed_ides(self):
            return ["claude"]

        def verify_hooks_for_ide(self, _ide_type):
            self.verify_calls += 1
            return {
                "healthy": self.healthy,
                "events": {"PreToolUse": "healthy" if self.healthy else "missing"},
                "obsolete": [],
            }

    setup = FakeIDESetup()
    state_path = tmp_path / "proactive_prompts.json"
    state = ProactivePromptState(state_path)
    sync_ide_setup_state(state=state, setup=setup)
    state.update_ide_setup_exclusions(never=("claude",))
    setup.healthy = False

    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=state_path,
        ),
        patch("ai_guardian.setup.hooks.IDESetup", return_value=setup),
    ):
        monitor._check_ide_setup_notification()
        monitor._check_ide_setup_notification()

    assert setup.verify_calls == 1
    saved = ProactivePromptState(state_path).get_ide_setup_status()
    assert saved["integrations"]["claude"]["healthy"] is True
    assert saved["integrations"]["claude"]["excluded"] is True


def test_dismissed_prompt_reappears_after_live_health_change(tmp_path):
    class FakeIDESetup:
        IDE_CONFIGS = {"claude": {"name": "Claude Code"}}

        def __init__(self):
            self.healthy = False
            self.verify_calls = 0

        def list_installed_ides(self):
            return ["claude"]

        def verify_hooks_for_ide(self, _ide_type):
            self.verify_calls += 1
            return {
                "healthy": self.healthy,
                "events": {"PreToolUse": "healthy" if self.healthy else "missing"},
                "obsolete": [],
            }

    setup = FakeIDESetup()
    state_path = tmp_path / "proactive_prompts.json"
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=state_path,
        ),
        patch("ai_guardian.setup.hooks.IDESetup", return_value=setup),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            side_effect=["dismiss", "dismiss"],
        ) as show,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()
        setup.healthy = True
        monitor._check_ide_setup_notification()
        setup.healthy = False
        monitor._check_ide_setup_notification()

    assert setup.verify_calls == 3
    assert show.call_count == 2
    status = ProactivePromptState(state_path).get_ide_setup_status()
    assert status["needs_setup"] == ["claude"]


def test_dismissed_prompt_is_eligible_when_no_health_snapshot_exists(tmp_path):
    class FakeIDESetup:
        IDE_CONFIGS = {"claude": {"name": "Claude Code"}}

        def __init__(self):
            self.verify_calls = 0

        def list_installed_ides(self):
            return ["claude"]

        def verify_hooks_for_ide(self, _ide_type):
            self.verify_calls += 1
            return {
                "healthy": False,
                "events": {"PreToolUse": "missing"},
                "obsolete": [],
            }

    setup = FakeIDESetup()
    state_path = tmp_path / "proactive_prompts.json"
    state = ProactivePromptState(state_path)
    state.record("ide_setup_claude", "dismiss")
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=state_path,
        ),
        patch("ai_guardian.setup.hooks.IDESetup", return_value=setup),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="dismiss",
        ) as show,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    assert setup.verify_calls == 1
    show.assert_called_once()


def test_newly_detected_ide_remains_eligible_after_an_exclusion(tmp_path):
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    state_path = tmp_path / "proactive_prompts.json"
    ProactivePromptState(state_path).update_ide_setup_exclusions(never=("cursor",))

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch.object(
            monitor,
            "_get_unconfigured_ides",
            return_value=["cursor", "codex"],
        ),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": False,
                "events": {"PreToolUse": "missing"},
                "obsolete": [],
            },
        ),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=state_path,
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="action",
        ),
        patch("ai_guardian.setup.setup_hooks", return_value=True) as setup_hooks,
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    setup_hooks.assert_called_once_with(ide_type="codex", interactive=False)
    assert ProactivePromptState(state_path).get_ide_setup_exclusions() == {"cursor"}


def test_newly_detected_ide_is_prompted_even_when_existing_prompt_is_snoozed(
    tmp_path,
):
    class FakeIDESetup:
        IDE_CONFIGS = {
            "claude": {"name": "Claude Code"},
            "cursor": {"name": "Cursor IDE/CLI"},
        }

        def __init__(self):
            self.installed = ["claude"]

        def list_installed_ides(self):
            return list(self.installed)

        def verify_ide_setup(self, ide_type):
            return {
                "ide": ide_type,
                "healthy": False,
                "events": {"PreToolUse": "missing"},
                "obsolete": [],
            }

    setup = FakeIDESetup()
    state_path = tmp_path / "proactive_prompts.json"
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=state_path,
        ),
        patch("ai_guardian.setup.hooks.IDESetup", return_value=setup),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            side_effect=["snooze_1h", "dismiss"],
        ) as show,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()
        setup.installed.append("cursor")
        monitor._check_ide_setup_notification()

    assert show.call_count == 2
    assert ProactivePromptState(state_path).get_ide_setup_status()["needs_setup"] == [
        "claude",
        "cursor",
    ]


def test_manual_ide_check_can_override_never_install_exclusion(tmp_path):
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)
    state_path = tmp_path / "proactive_prompts.json"
    state = ProactivePromptState(state_path)
    state.update_ide_setup_exclusions(never=("cursor",))

    with (
        patch.object(monitor, "_has_user_config", return_value=True),
        patch.object(monitor, "_get_installed_ides", return_value=["cursor"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=["cursor"]),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=state_path,
        ),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="action",
        ),
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": False,
                "events": {"PreToolUse": "missing"},
                "obsolete": [],
            },
        ),
        patch("ai_guardian.setup.setup_hooks", return_value=True),
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification(manual=True)

    assert ProactivePromptState(state_path).get_ide_setup_exclusions() == set()
