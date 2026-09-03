"""User experience contract for automatic IDE setup prompts (#2216)."""

from types import SimpleNamespace
from unittest.mock import patch

from ai_guardian.tray.health import TrayHealthMonitor


def test_local_daemon_prompts_for_detected_unconfigured_ide():
    """
    USER EXPERIENCE: Detected local IDE without hooks -> offer setup choices.

    Scenario:
    1. User runs a local AI Guardian daemon.
    2. AI Guardian detects an IDE without configured hooks.
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
            "Cursor IDE was detected but is not protected by AI Guardian.\n\n"
            "Set up its security hooks now?"
        ),
        action_label="Set Up Now",
        dismiss_label="Don't Ask Again",
        snooze_options=("1h", "6h", "1d", "1w"),
    )
