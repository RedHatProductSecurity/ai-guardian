"""User experience contract for automatic IDE setup prompts (#2216)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai_guardian.setup.hooks import IDESetup
from ai_guardian.tray.health import TrayHealthMonitor


def test_local_daemon_prompts_for_installed_unconfigured_ide():
    """
    USER EXPERIENCE: Installed local IDE without hooks -> offer setup choices.

    Scenario:
    1. User runs a local AI Guardian daemon.
    2. AI Guardian finds an IDE configuration directory without configured hooks.
    3. Tray health monitoring checks setup status.

    Expected User Experience:
    - User sees "Set Up AI Guardian".
    - User can choose "Set Up Now", "Later", or "Don't Ask Again".
    - Remote-only daemon targets do not show this prompt.
    """
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)

    with (
        patch.object(monitor, "_get_unconfigured_ides", return_value=["cursor"]),
        patch("ai_guardian.tray.proactive_prompt.ProactivePromptDialog") as dialog,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    dialog.assert_called_once_with(
        title="Set Up AI Guardian",
        message=(
            "Cursor IDE is installed but is not protected by AI Guardian.\n\n"
            "Set up its security hooks now?"
        ),
        action_label="Set Up Now",
        dismiss_label="Don't Ask Again",
        snooze_options=("1h", "6h", "1d", "1w"),
    )


def test_setup_action_reports_doctor_style_hook_counts():
    """
    USER EXPERIENCE: Setup action -> show per-IDE hook setup results.

    Scenario:
    1. The tray offers to configure an installed IDE.
    2. The user selects "Set Up Now".
    3. AI Guardian configures the hooks and verifies the resulting adapter.

    Expected User Experience:
    - A result notification is shown after setup finishes.
    - Each IDE reports its configured hook count using doctor-style statuses.
    """
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": True,
        "events": {
            "UserPromptSubmit": "healthy",
            "PreToolUse": "healthy",
            "PostToolUse": "healthy",
        },
        "obsolete": [],
    }

    with (
        patch.object(monitor, "_get_unconfigured_ides", return_value=["claude"]),
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
        patch(
            "ai_guardian.tray.proactive_prompt.ProactivePromptDialog.show",
            return_value="action",
        ),
        patch("ai_guardian.setup.setup_hooks", return_value=True),
        patch("ai_guardian.tray.plugins.send_notification") as notify,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    notify.assert_called_once_with(
        "AI Guardian Setup",
        "IDE/CLI setup result\n\n"
        "[PASS] Claude Code: 3/3 hooks configured\n\n"
        "1 passed",
    )


def test_local_daemon_ignores_project_root_only_ide(tmp_path, monkeypatch):
    """
    USER EXPERIENCE: Project-root config path only -> do not show a false popup.

    A project-local path such as ``.crush.json`` has the current directory as
    its parent, so it must not be treated as proof that the IDE is installed.
    """
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    setup = IDESetup()
    setup.IDE_CONFIGS = {
        "cursor": {
            "config_path": str(cursor_dir / "hooks.json"),
            "config_filename": "hooks.json",
        },
        "crush": {
            "config_path": ".crush.json",
            "config_filename": "crush.json",
        },
    }
    setup.check_hooks_for_ide = MagicMock(return_value=(False, "IDE: not configured"))

    with patch("ai_guardian.setup.hooks.IDESetup", return_value=setup):
        assert monitor._get_unconfigured_ides() == ["cursor"]

    setup.check_hooks_for_ide.assert_called_once_with("cursor", integrity=True)


def test_local_daemon_accepts_cursor_config_directory(tmp_path, monkeypatch):
    """
    USER EXPERIENCE: Cursor config directory -> include Cursor in the check.

    Cursor may be a desktop installation without a ``cursor`` executable on
    PATH. Its canonical ``~/.cursor`` directory is the installation signal.
    """
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(
        '{"mcpServers": {"ai-guardian": {"command": "ai-guardian"}}}'
    )
    monkeypatch.chdir(tmp_path)

    setup = IDESetup()
    setup.IDE_CONFIGS = {
        "cursor": {
            "config_path": str(cursor_dir / "hooks.json"),
            "config_filename": "hooks.json",
        }
    }
    setup.check_hooks_for_ide = MagicMock(return_value=(False, "IDE: not configured"))

    with patch("ai_guardian.setup.hooks.IDESetup", return_value=setup):
        assert monitor._get_unconfigured_ides() == ["cursor"]

    setup.check_hooks_for_ide.assert_called_once_with("cursor", integrity=True)
