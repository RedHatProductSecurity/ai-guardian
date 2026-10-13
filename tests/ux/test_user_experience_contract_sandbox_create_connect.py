"""UX contracts for connecting directly from tray sandbox creation."""

from types import SimpleNamespace
from unittest import mock

import pytest


@pytest.mark.parametrize("runtime", ["container", "openshell"])
def test_user_experience_successful_tray_creation_offers_connect(runtime):
    """
    USER EXPERIENCE: Successful tray creation can connect to that sandbox.

    Scenario:
    1. The user creates a container or OpenShell sandbox from the tray.
    2. Creation succeeds and the completion dialog keeps its output visible.
    3. The user selects Connect in that dialog.

    Expected experience:
    - Connect appears only in the successful completion state.
    - Connect launches the existing interactive flow for the new name/runtime.
    - Creation is not repeated; Copy and Close remain available.
    """
    from ai_guardian.tray.app import DaemonTray

    tray = DaemonTray(
        get_stats_callback=lambda: {},
        stop_callback=lambda: None,
        pause_callback=lambda _minutes: None,
        multi_client=mock.MagicMock(),
    )
    progress = mock.MagicMock()

    with (
        mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create,
        mock.patch.object(
            tray._menu, "_show_sandbox_progress", return_value=progress
        ) as show_progress,
        mock.patch(
            "ai_guardian.tray.menu_builder.tray_menu.launch_sandbox_command"
        ) as launch,
        mock.patch(
            "ai_guardian.tray.menu_builder.tray_notifications.show_notification"
        ),
    ):
        tray._menu._run_sandbox_create(
            SimpleNamespace(runtime=runtime, name="ag-created")
        )
        connect = show_progress.call_args.kwargs["on_connect"]
        connect()

    create.assert_called_once()
    progress.finish.assert_called_once_with(
        True,
        "Sandbox 'ag-created' created.",
        "",
        show_connect=True,
    )
    target, operation, arguments = launch.call_args.args
    assert target.name == "ag-created"
    assert tray._menu._sandbox_runtime(target) == runtime
    assert operation == "connect"
    assert arguments == ["ag-created"]
    assert launch.call_args.kwargs == {"keep_open": True}


def test_user_experience_failed_tray_creation_keeps_log_without_connect():
    """
    USER EXPERIENCE: Failed creation remains reviewable without Connect.

    Expected experience:
    - The failure details stay in the completion dialog for review.
    - No Connect action is enabled or offered after a failed create.
    - The separate failure-log fallback is not opened when progress is available.
    """
    from ai_guardian.tray.app import DaemonTray

    tray = DaemonTray(
        get_stats_callback=lambda: {},
        stop_callback=lambda: None,
        pause_callback=lambda _minutes: None,
        multi_client=mock.MagicMock(),
    )
    progress = mock.MagicMock()

    def fail_create(_args, *, interactive, output):
        assert interactive is False
        output.append("runtime failed\n")
        return 1

    with (
        mock.patch("ai_guardian.sandbox.create_sandbox", side_effect=fail_create),
        mock.patch.object(tray._menu, "_show_sandbox_progress", return_value=progress),
        mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log") as show_log,
    ):
        tray._menu._run_sandbox_create(
            SimpleNamespace(runtime="openshell", name="ag-failed")
        )

    progress.finish.assert_called_once_with(
        False, "Unable to create sandbox 'ag-failed'.", "runtime failed"
    )
    show_log.assert_not_called()
