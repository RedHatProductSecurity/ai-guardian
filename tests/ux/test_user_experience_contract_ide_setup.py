"""User experience contract for tray IDE/CLI setup flows (#2257)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai_guardian.setup.hooks import IDESetup
from ai_guardian.tray.health import TrayHealthMonitor
from ai_guardian.tray.proactive_prompt import ProactivePromptState


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
        patch.object(
            monitor,
            "_verify_ide_setup",
            return_value={
                "healthy": False,
                "events": {
                    "beforeSubmitPrompt": "missing",
                    "beforeReadFile": "missing",
                    "beforeShellExecution": "missing",
                    "afterShellExecution": "missing",
                    "preToolUse": "missing",
                    "postToolUse": "missing",
                },
                "obsolete": [],
            },
        ),
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
            "Current hook status: beforeSubmitPrompt (missing), "
            "beforeReadFile (missing), beforeShellExecution (missing), "
            "afterShellExecution (missing), preToolUse (missing), "
            "postToolUse (missing)\n\n"
            "Set up its security hooks now?"
        ),
        action_label="Set Up Now",
        dismiss_label="Don't Ask Again",
        snooze_options=("1h", "6h", "1d", "1w"),
    )


def test_codex_hooks_healthy_but_global_mcp_missing_gets_targeted_prompt(tmp_path):
    """
    USER EXPERIENCE: Codex hooks healthy + MCP missing -> explain the gap.

    Scenario:
    1. The local tray finds OpenAI Codex with all AI Guardian hooks healthy.
    2. The global Codex MCP configuration does not contain AI Guardian.
    3. The tray asks whether to register the missing MCP server.

    Expected User Experience:
    - The prompt distinguishes missing MCP registration from missing hooks.
    - The user sees the effective Codex configuration path.
    - The action is labeled for MCP setup.
    """
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    mcp_path = tmp_path / "codex" / "config.toml"
    verification = {
        "healthy": False,
        "hooks_healthy": True,
        "mcp_installed": False,
        "mcp_status": "missing",
        "mcp_config_path": str(mcp_path),
        "events": {
            event: "healthy" for event in IDESetup().expected_hook_manifest("codex")
        },
        "obsolete": [],
    }

    with (
        patch.object(monitor, "_get_unconfigured_ides", return_value=["codex"]),
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
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
            "OpenAI Codex hooks are configured, but the AI Guardian MCP server is "
            "missing.\n\n"
            f"Codex MCP configuration: {mcp_path}\n\n"
            "Register the AI Guardian MCP server now?"
        ),
        action_label="Set Up MCP",
        dismiss_label="Don't Ask Again",
        snooze_options=("1h", "6h", "1d", "1w"),
    )


def test_manual_health_check_works_without_daemon_for_multiple_ides():
    """
    USER EXPERIENCE: Manual health check -> inspect and optionally set up
    multiple IDEs without a daemon.

    Scenario:
    1. The tray has no local daemon target (for example, it is a standalone
       tray waiting for discovery).
    2. The user opens IDE/CLI Setup and chooses Check hooks/MCP installation.
    3. Claude Code and Cursor are installed but both need hooks.

    Expected User Experience:
    - The on-demand check is still available without a daemon.
    - One dialog lists each incomplete integration separately.
    - The user can choose targeted setup actions for each IDE.
    """
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": False,
        "events": {"PreToolUse": "missing"},
        "obsolete": [],
    }

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_get_installed_ides", return_value=["claude", "cursor"]),
        patch.object(
            monitor,
            "_get_unconfigured_ides",
            return_value=["claude", "cursor"],
        ),
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
        patch("ai_guardian.tray.proactive_prompt.ProactivePromptDialog") as dialog,
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        dialog.return_value.show.return_value = "dismiss"
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification(manual=True)

    dialog.assert_called_once_with(
        title="Set Up AI Guardian",
        message=(
            "These installed IDEs have incomplete AI Guardian hooks:\n"
            "• Claude Code: PreToolUse (missing)\n"
            "• Cursor IDE: PreToolUse (missing)\n\n"
            "Set up their security hooks now?"
        ),
        action_label="Set Up Selected",
        dismiss_label="Cancel",
        snooze_options=("1h", "6h", "1d", "1w"),
        ide_choices=[
            {
                "ide": "claude",
                "name": "Claude Code",
                "detail": "PreToolUse (missing)",
            },
            {
                "ide": "cursor",
                "name": "Cursor IDE",
                "detail": "PreToolUse (missing)",
            },
        ],
    )


def test_manual_health_check_falls_back_to_visible_dialog_when_notification_fails():
    """
    USER EXPERIENCE: macOS notification failure -> visible health result.

    Scenario:
    1. User selects Check hooks/MCP installation from the tray.
    2. Every installed integration is healthy.
    3. macOS notification delivery reports a failure.

    Expected User Experience:
    - The result is not silently discarded.
    - The tray presents the same health result in a modal dialog fallback.
    """
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)
    message = "All installed IDE/CLI integrations are configured:\n• Claude Code"

    with (
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_get_installed_ides", return_value=["claude"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=[]),
        patch("ai_guardian.tray.plugins.send_notification", return_value=False),
        patch("ai_guardian.tray.plugins.show_dialog", return_value=True) as dialog,
    ):
        monitor._check_ide_setup_notification(manual=True)

    dialog.assert_called_once_with("AI Guardian", message)


def test_manual_health_check_confirms_result_when_macos_accepts_but_hides_notification():
    """
    USER EXPERIENCE: Silent macOS notification acceptance -> visible result.

    Scenario:
    1. User selects Check hooks/MCP installation from the tray.
    2. macOS accepts the osascript notification command.
    3. Notification Center suppresses the banner because sender permissions
       are not visible or trusted yet.

    Expected User Experience:
    - The tray still shows the health result in a modal confirmation.
    - The user is never required to infer the result from a missing banner.
    """
    tray = SimpleNamespace(_standalone=False, _targets=[])
    monitor = TrayHealthMonitor(tray)
    message = "All installed IDE/CLI integrations are configured:\n• Claude Code"

    with (
        patch("platform.system", return_value="Darwin"),
        patch.object(monitor, "_refresh_ide_setup_state", return_value=None),
        patch.object(monitor, "_get_installed_ides", return_value=["claude"]),
        patch.object(monitor, "_get_unconfigured_ides", return_value=[]),
        patch("ai_guardian.tray.plugins.send_notification", return_value=True),
        patch("ai_guardian.tray.plugins.show_dialog", return_value=True) as dialog,
    ):
        monitor._check_ide_setup_notification(manual=True)

    dialog.assert_called_once_with("AI Guardian", message)


def test_codex_setup_reports_conflicting_active_configuration(tmp_path, monkeypatch):
    """
    USER EXPERIENCE: Conflicting Codex hook representation -> clear diagnostic.

    Scenario:
    1. User runs Codex setup while the active user ``config.toml`` already
       defines inline hooks.
    2. AI Guardian detects that it targets ``hooks.json`` in the same layer.

    Expected User Experience:
    - Setup stops before writing a second hook representation.
    - User sees an actionable message naming the conflict and next step.
    """
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text("[hooks]\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    success, message = IDESetup().setup_ide_hooks("codex")

    assert success is False
    assert message == (
        "OpenAI Codex setup stopped: inline hooks are already defined in "
        f"{codex_home / 'config.toml'}. AI Guardian targets "
        f"{codex_home / 'hooks.json'}; choose one hook representation in "
        "the active user layer and rerun setup to avoid duplicate hook loading."
    )
    assert not (codex_home / "hooks.json").exists()


def test_multiple_integrations_show_per_ide_install_or_never_choices(tmp_path):
    """
    USER EXPERIENCE: Multiple incomplete integrations -> per-IDE choices.

    Scenario:
    1. A local tray detects Claude Code and Cursor without healthy hooks.
    2. The tray opens one setup dialog containing both integrations.
    3. The user keeps Claude Code selected for installation and marks Cursor
       as Never install.

    Expected User Experience:
    - Each integration appears in the same two-column choice list.
    - Install now is selected by default and Never install is clear by default.
    - Only the selected integration is configured.
    - The Never install choice is persisted for future automatic checks.
    """
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
        patch.object(monitor, "_verify_ide_setup", return_value=verification),
        patch(
            "ai_guardian.tray.proactive_prompt._state_path",
            return_value=tmp_path / "proactive_prompts.json",
        ),
        patch("ai_guardian.tray.proactive_prompt.ProactivePromptDialog") as dialog,
        patch("ai_guardian.setup.setup_hooks", return_value=True) as setup_hooks,
        patch("ai_guardian.tray.plugins.send_notification"),
        patch("ai_guardian.tray.health.threading.Thread") as thread,
    ):
        dialog.return_value.show.return_value = {
            "result": "action",
            "install": ["claude"],
            "never": ["cursor"],
        }
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs[
            "target"
        ]()
        monitor._check_ide_setup_notification()

    dialog.assert_called_once_with(
        title="Set Up AI Guardian",
        message=(
            "These installed IDEs have incomplete AI Guardian hooks:\n"
            "• Claude Code: PreToolUse (missing)\n"
            "• Cursor IDE: PreToolUse (missing)\n\n"
            "Set up their security hooks now?"
        ),
        action_label="Set Up Selected",
        dismiss_label="Cancel",
        snooze_options=("1h", "6h", "1d", "1w"),
        ide_choices=[
            {
                "ide": "claude",
                "name": "Claude Code",
                "detail": "PreToolUse (missing)",
            },
            {
                "ide": "cursor",
                "name": "Cursor IDE",
                "detail": "PreToolUse (missing)",
            },
        ],
    )
    setup_hooks.assert_called_once_with(ide_type="claude", interactive=False)


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


def test_setup_result_uses_final_verification_health():
    """
    USER EXPERIENCE: Healthy post-setup verification -> report success.

    Scenario:
    1. The setup adapter reports a false result because configuration changed
       during setup or was already complete.
    2. The tray performs its final hook verification.
    3. Verification reports every managed hook as healthy.

    Expected User Experience:
    - The user sees a PASS result based on the final health check.
    - The notification does not claim that setup failed.
    """
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": True,
        "events": {"PreToolUse": "healthy"},
        "obsolete": [],
    }

    with patch("ai_guardian.tray.plugins.send_notification") as notify:
        monitor._notify_ide_setup_result(
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


def test_codex_setup_reports_only_managed_hook_count():
    """
    USER EXPERIENCE: Codex setup -> report five managed hooks, not twelve.

    Scenario:
    1. Codex setup verifies the hooks installed by AI Guardian.
    2. Codex exposes additional lifecycle events that are not installed by
       AI Guardian setup.

    Expected User Experience:
    - The result notification reports ``5/5 hooks configured``.
    - The notification does not imply that all twelve documented lifecycle
      events are required.
    """
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

    message = notify.call_args.args[1]
    assert "[PASS] OpenAI Codex: 5/5 hooks configured" in message
    assert "12/12" not in message


def test_failed_codex_setup_is_snoozed_for_automatic_prompt(tmp_path):
    """
    USER EXPERIENCE: Failed Codex setup -> avoid an immediate prompt loop.

    Scenario:
    1. The tray detects Codex without healthy managed hooks.
    2. The user selects Set Up Now.
    3. Hook setup fails.

    Expected User Experience:
    - The setup result is still reported.
    - The same automatic prompt is snoozed for one hour instead of reopening
      on the next health poll.
    """
    tray = SimpleNamespace(_standalone=True, _targets=[])
    monitor = TrayHealthMonitor(tray)
    verification = {
        "healthy": False,
        "events": {"PreToolUse": "missing"},
        "obsolete": [],
    }

    with (
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
    assert state.load()["ide_setup_codex"]["status"] == "snoozed"
    assert not state.available("ide_setup_codex")


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
