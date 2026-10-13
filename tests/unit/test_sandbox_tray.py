"""Tests for sandbox actions exposed by the system tray."""

import io
import os
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.ide_registry import (
    SANDBOX_PI_PROVIDER_CHOICES_BY_RUNTIME,
    SUPPORTED_CLI_IDE_TYPES,
    SUPPORTED_OPENSHELL_CLI_IDE_TYPES,
)
from ai_guardian.tray.app import DaemonTray
from ai_guardian.tray.menu import (
    launch_sandbox_command,
    launch_sandbox_create_command,
)
from ai_guardian.tray.menu_builder import (
    TRAY_OPENSHELL_AUTH_CHOICES,
    TRAY_OPENSHELL_CLI_CHOICES,
    TRAY_OPENSHELL_MODE_CHOICES,
    TrayMenuBuilder,
)


class FakeMenu:
    """Small pystray.Menu replacement that keeps nested menu items inspectable."""

    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


class FakeMenuItem:
    """Small pystray.MenuItem replacement for callback and label assertions."""

    def __init__(self, label, action=None, **kwargs):
        self.label = label
        self.action = action
        self.kwargs = kwargs


FAKE_PYSTRAY = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem)


class ImmediateThread:
    """Thread test double that executes a callback synchronously."""

    def __init__(self, target, args=(), **_kwargs):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


def _walk_labels(menu):
    """Return string labels from a fake menu tree."""
    labels = []
    for item in getattr(menu, "items", ()):
        if isinstance(item, FakeMenuItem):
            if isinstance(item.label, str):
                labels.append(item.label)
            if isinstance(item.action, FakeMenu):
                labels.extend(_walk_labels(item.action))
    return labels


def _make_tray(targets):
    tray = DaemonTray(
        get_stats_callback=lambda: {},
        stop_callback=lambda: None,
        pause_callback=lambda _minutes: None,
        multi_client=mock.MagicMock(),
    )
    tray._targets = targets
    return tray


class TestSandboxTrayCommands:
    def test_container_command_uses_target_engine_and_runtime_name(self):
        target = DaemonTarget(
            name="logical-name",
            runtime="container",
            container_engine="docker",
            container_name="runtime-name",
            status="running",
        )
        with (
            mock.patch(
                "ai_guardian.tray.plugins.resolve_cli_cmd",
                side_effect=lambda *args: ["ai-guardian", *args],
            ),
            mock.patch("ai_guardian.daemon.multi_client._launch_in_terminal") as launch,
        ):
            launch_sandbox_command(
                target,
                "exec",
                [target.name, "--", "pwd"],
            )

        launch.assert_called_once_with(
            [
                "ai-guardian",
                "sandbox",
                "exec",
                "--runtime",
                "container",
                "--container-engine",
                "docker",
                "runtime-name",
                "--",
                "pwd",
            ],
            keep_open=True,
        )

    def test_lifecycle_command_uses_logical_openshell_runtime(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            runtime_type="openshell",
            status="running",
        )
        with (
            mock.patch(
                "ai_guardian.tray.plugins.resolve_cli_cmd",
                side_effect=lambda *args: ["ai-guardian", *args],
            ),
            mock.patch("ai_guardian.daemon.multi_client._launch_in_terminal") as launch,
        ):
            launch_sandbox_command(
                target,
                ("config", "save"),
                ["ag-test"],
            )

        launch.assert_called_once_with(
            [
                "ai-guardian",
                "sandbox",
                "config",
                "save",
                "--runtime",
                "openshell",
                "ag-test",
            ],
            keep_open=True,
        )

    def test_create_command_includes_runtime_and_arguments(self):
        with (
            mock.patch(
                "ai_guardian.tray.plugins.resolve_cli_cmd",
                side_effect=lambda *args: ["ai-guardian", *args],
            ),
            mock.patch("ai_guardian.daemon.multi_client._launch_in_terminal") as launch,
        ):
            launch_sandbox_create_command(
                "container", ["--name", "smoke"], keep_open=True
            )

        launch.assert_called_once_with(
            [
                "ai-guardian",
                "sandbox",
                "create",
                "--runtime",
                "container",
                "--name",
                "smoke",
            ],
            keep_open=True,
        )


class TestSandboxTrayMenu:
    def test_openshell_top_level_connect_uses_sandbox_connect_action(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            runtime_type="openshell",
            status="running",
        )
        tray = _make_tray([target])

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch(
                "ai_guardian.tray.menu_builder.tray_menu.launch_sandbox_command"
            ) as launch,
        ):
            items = tray._menu._build_single_daemon_menu_items()

            connect_item = next(
                item
                for item in items
                if isinstance(item, FakeMenuItem) and item.label == "Connect"
            )
            connect_item.action(None, None)

        launch.assert_called_once_with(
            target,
            "connect",
            [target.name],
            keep_open=True,
        )

    def test_manage_menu_contains_every_safe_sandbox_operation(self):
        tray = _make_tray(
            [
                DaemonTarget(
                    name="ag-test",
                    runtime="container",
                    runtime_type="openshell",
                    status="running",
                )
            ]
        )
        with mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY):
            item = tray._menu._build_sandbox_manage_menu_item(0)

        labels = _walk_labels(item.action)
        for label in (
            "Status",
            "Start",
            "Stop",
            "Restart",
            "Connect",
            "Exec...",
            "Logs...",
            "Config",
            "Save",
            "List",
            "Restore...",
            "Delete...",
        ):
            assert label in labels
        assert "List sandboxes" not in labels
        assert item.kwargs["visible"](None) is True

        connect_item = next(
            child
            for child in item.action.items
            if isinstance(child, FakeMenuItem) and child.label == "Connect"
        )
        assert connect_item.kwargs["visible"](None) is False

    def test_delete_requires_confirmation_before_running_command(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            runtime_type="openshell",
            status="running",
        )
        tray = _make_tray([target])

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch(
                "ai_guardian.tray.menu_builder.threading.Thread",
                ImmediateThread,
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_confirmation",
                return_value=True,
            ) as confirm,
            mock.patch.object(
                tray._menu, "_capture_sandbox_screen_bounds", return_value=None
            ),
            mock.patch.object(tray._menu, "_start_sandbox_command") as run_command,
        ):
            item = tray._menu._build_sandbox_manage_menu_item(0)
            delete_item = next(
                child
                for child in item.action.items
                if isinstance(child, FakeMenuItem) and child.label == "Delete..."
            )
            delete_item.action(None, None)

        confirm.assert_called_once_with("ag-test", "openshell")
        run_command.assert_called_once_with(target, "delete", ["ag-test"])

    def test_openshell_delete_forwards_clicked_display_to_confirmation(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            runtime_type="openshell",
            status="running",
        )
        tray = _make_tray([target])
        bounds = (1920, 37, 2560, 1380)

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch(
                "ai_guardian.tray.menu_builder.threading.Thread",
                ImmediateThread,
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_confirmation",
                return_value=False,
            ) as confirm,
            mock.patch.object(
                tray._menu,
                "_capture_sandbox_screen_bounds",
                return_value=bounds,
            ) as capture,
        ):
            item = tray._menu._build_sandbox_manage_menu_item(0)
            delete_item = next(
                child
                for child in item.action.items
                if isinstance(child, FakeMenuItem) and child.label == "Delete..."
            )
            delete_item.action("clicked-icon", None)

        capture.assert_called_once_with("clicked-icon")
        confirm.assert_called_once_with(
            "ag-test",
            "openshell",
            screen_bounds=bounds,
        )

    def test_delete_does_nothing_when_confirmation_is_cancelled(self):
        target = DaemonTarget(name="ag-test", runtime="container", status="running")
        tray = _make_tray([target])

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch(
                "ai_guardian.tray.menu_builder.threading.Thread",
                ImmediateThread,
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_confirmation",
                return_value=False,
            ),
            mock.patch.object(
                tray._menu, "_capture_sandbox_screen_bounds", return_value=None
            ),
            mock.patch.object(tray._menu, "_start_sandbox_command") as run_command,
        ):
            item = tray._menu._build_sandbox_manage_menu_item(0)
            delete_item = next(
                child
                for child in item.action.items
                if isinstance(child, FakeMenuItem) and child.label == "Delete..."
            )
            delete_item.action(None, None)

        run_command.assert_not_called()

    def test_container_delete_streams_output_and_refreshes_discovery(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            container_engine="podman",
            status="running",
        )
        tray = _make_tray([target])
        progress = mock.MagicMock()
        discovery = mock.MagicMock()
        tray._discovery = discovery

        def run_command(args, *, output):
            assert args.runtime == "container"
            output.append("removed\n")
            return 0

        with (
            mock.patch.object(
                tray._menu, "_show_sandbox_progress", return_value=progress
            ) as show_progress,
            mock.patch(
                "ai_guardian.sandbox.run_sandbox_command", side_effect=run_command
            ),
            mock.patch(
                "ai_guardian.tray.menu_builder.tray_notifications.show_notification"
            ),
        ):
            tray._menu._run_sandbox_command(target, "delete", [target.name])

        show_progress.assert_called_once_with(
            "Deleting sandbox 'ag-test'",
            "Operation: delete\nRuntime: container\n"
            "Command is running; output appears below.",
            screen_bounds=None,
        )
        progress.append.assert_called_once_with("removed\n")
        progress.finish.assert_called_once_with(
            True, "Sandbox 'ag-test' deleted.", "removed"
        )
        discovery.request_refresh.assert_called_once_with(wait=False)

    def test_openshell_delete_keeps_failed_progress_open(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            runtime_type="openshell",
            status="running",
        )
        tray = _make_tray([target])
        progress = mock.MagicMock()

        def run_command(args, *, output):
            assert args.runtime == "openshell"
            output.append("service cleanup failed\n")
            return 1

        with (
            mock.patch.object(
                tray._menu, "_show_sandbox_progress", return_value=progress
            ),
            mock.patch(
                "ai_guardian.sandbox.run_sandbox_command", side_effect=run_command
            ),
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log") as show_log,
        ):
            tray._menu._run_sandbox_command(target, "delete", [target.name])

        progress.finish.assert_called_once_with(
            False,
            "Unable to run delete for sandbox 'ag-test'.",
            "service cleanup failed",
        )
        show_log.assert_not_called()

    def test_manage_connect_remains_visible_for_regular_container(self):
        tray = _make_tray(
            [DaemonTarget(name="container", runtime="container", status="running")]
        )
        with mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY):
            item = tray._menu._build_sandbox_manage_menu_item(0)

        connect_item = next(
            child
            for child in item.action.items
            if isinstance(child, FakeMenuItem) and child.label == "Connect"
        )
        assert connect_item.kwargs["visible"](None) is True

    def test_manage_menu_is_hidden_for_local_daemon(self):
        tray = _make_tray([DaemonTarget(name="local", runtime="local")])
        with mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY):
            item = tray._menu._build_sandbox_manage_menu_item(0)

        assert item.kwargs["visible"](None) is False

    def test_manage_menu_hides_start_for_stopped_container_targets(self):
        tray = _make_tray(
            [DaemonTarget(name="stopped", runtime="container", status="stopped")]
        )
        with mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY):
            item = tray._menu._build_sandbox_manage_menu_item(0)

        start_item = next(
            child
            for child in item.action.items
            if isinstance(child, FakeMenuItem) and child.label == "Start"
        )
        assert start_item.kwargs["visible"](None) is False

    def test_create_action_is_in_the_main_menu(self):
        tray = _make_tray([])
        with mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY):
            items = tray._menu._build_sandbox_create_menu_items()

        assert [item.label for item in items] == ["Create sandbox..."]
        assert items[0].kwargs["enabled"](None) is True

    def test_create_action_ignores_repeated_click_while_form_is_open(self):
        tray = _make_tray([])
        action = tray._menu._mk_sandbox_create_action()

        with mock.patch.object(tray._menu, "_start_sandbox_form") as start_form:
            action(None, None)
            action(None, None)

        start_form.assert_called_once()
        assert tray._menu._sandbox_create_is_in_progress() is True
        tray._menu._end_sandbox_create()

    def test_single_daemon_menu_explains_current_status_symbol(self):
        tray = _make_tray(
            [
                DaemonTarget(
                    name="ag-test",
                    runtime="container",
                    runtime_type="openshell",
                    status="error",
                    error_message="OpenShell service unavailable",
                )
            ]
        )

        with mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY):
            items = tray._menu._build_single_daemon_menu_items()

        status_item = next(item for item in items if item.label == "Status")
        status_lines = status_item.action.items
        assert status_item.kwargs["visible"](None) is True
        assert status_lines[1].label(None) == "✗ Error"
        assert status_lines[2].label(None) == "Runtime: openshell (container)"
        assert status_lines[3].label(None) == "OpenShell service unavailable"
        assert status_lines[6].label == "Symbol legend"

    def test_multi_daemon_menu_has_status_entry_for_each_daemon(self):
        tray = _make_tray(
            [
                DaemonTarget(name="one", runtime="local", status="running"),
                DaemonTarget(name="two", runtime="container", status="stopped"),
            ]
        )

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", FAKE_PYSTRAY),
        ):
            single_items = tray._menu._build_single_daemon_menu_items()
            items = tray._menu._build_multi_daemon_menu_items()

        single_status = next(item for item in single_items if item.label == "Status")
        assert single_status.kwargs["visible"](None) is False
        assert len(items) == 2
        for daemon_item in items:
            assert "Status" in _walk_labels(daemon_item.action)

    def test_multi_daemon_pause_controls_are_prominent_and_scoped(self):
        targets = [
            DaemonTarget(name="one", runtime="container", status="running"),
            DaemonTarget(name="two", runtime="container", status="running"),
        ]
        tray = _make_tray(targets)
        stats_by_name = {
            "one": {
                "paused": False,
                "active_project_dirs": ["/project-one"],
                "paused_dirs": {},
                "active_sessions": [],
            },
            "two": {
                "paused": False,
                "active_project_dirs": ["/project-two"],
                "paused_dirs": {"/project-two-paused": 0},
                "active_sessions": [
                    {
                        "session_key": "ClaudeCodeAdapter:session-two",
                        "session_id": "session-two",
                        "agent": "Claude Code",
                        "project_dir": "/project-two",
                        "paused": False,
                        "pause_remaining_seconds": 0,
                    }
                ],
            },
        }
        tray._multi_client.get_status.side_effect = lambda target: stats_by_name[
            target.name
        ]

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", FAKE_PYSTRAY),
        ):
            daemon_items = tray._menu._build_multi_daemon_menu_items()

        second_daemon_menu = daemon_items[1].action
        pause_item = next(
            item
            for item in second_daemon_menu.items
            if isinstance(item, FakeMenuItem) and item.label == "Pause..."
        )
        console_item = next(
            item
            for item in second_daemon_menu.items
            if isinstance(item, FakeMenuItem) and item.label == "Console"
        )
        assert second_daemon_menu.items.index(
            pause_item
        ) < second_daemon_menu.items.index(console_item)
        assert pause_item.kwargs["visible"](None) is True

        pause_menu = pause_item.action
        global_item = pause_menu.items[0]
        global_menu = global_item.action
        global_actions = {item.label: item for item in global_menu.items}
        assert {
            "5 minutes",
            "15 minutes",
            "30 minutes",
            "1 hour",
            "Until resume",
            "Resume",
        } <= set(global_actions)
        assert global_actions["15 minutes"].kwargs["visible"](None) is True
        assert global_actions["Resume"].kwargs["visible"](None) is False

        with mock.patch.object(tray, "_check_and_autostart_daemon"):
            global_actions["15 minutes"].action(None, None)
        tray._multi_client.send_pause.assert_called_once_with(targets[1], 15)

        stats_by_name["two"]["paused"] = True
        assert global_actions["Resume"].kwargs["visible"](None) is True
        with mock.patch.object(tray, "_check_and_autostart_daemon"):
            global_actions["Resume"].action(None, None)
        tray._multi_client.send_resume.assert_called_once_with(targets[1])

        sessions_item = pause_menu.items[2]
        assert sessions_item.label == "Sessions..."
        assert sessions_item.action.items[1].label == (
            "Directory-wide pause also covers callers without stable session IDs"
        )
        session_options = [
            item
            for item in sessions_item.action.items
            if isinstance(item, FakeMenuItem)
            and item.action is not None
            and item.kwargs.get("visible", lambda _item: True)(None)
        ]
        assert len(session_options) == 1
        session_actions = {
            item.label: item
            for item in session_options[0].action.items
            if isinstance(item, FakeMenuItem)
        }
        assert session_actions["15 minutes"].kwargs["visible"](None) is True
        with mock.patch.object(tray, "_check_and_autostart_daemon"):
            session_actions["15 minutes"].action(None, None)
        tray._multi_client.send_pause_session.assert_called_once_with(
            targets[1], "ClaudeCodeAdapter:session-two", 15
        )

        stats_by_name["two"]["active_sessions"][0]["paused"] = True
        assert session_actions["Resume"].kwargs["visible"](None) is True
        with mock.patch.object(tray, "_check_and_autostart_daemon"):
            session_actions["Resume"].action(None, None)
        tray._multi_client.send_resume_session.assert_called_once_with(
            targets[1], "ClaudeCodeAdapter:session-two"
        )

        directories_item = pause_menu.items[3]
        assert directories_item.label == "All sessions in directory..."
        assert directories_item.kwargs["visible"](None) is True
        directory_items = directories_item.action.items
        second_directory_items = [
            item
            for item in directory_items
            if isinstance(item, FakeMenuItem) and item.kwargs["visible"](None)
        ]
        assert len(second_directory_items) == 2
        assert all(
            "/project-one" not in item.label(None) for item in second_directory_items
        )

        active_directory = next(
            item
            for item in second_directory_items
            if item.label(None).endswith("/project-two")
        )
        active_directory_actions = {
            item.label: item
            for item in active_directory.action.items
            if isinstance(item, FakeMenuItem)
        }
        assert active_directory_actions["15 minutes"].kwargs["visible"](None) is True
        with mock.patch.object(tray, "_check_and_autostart_daemon"):
            active_directory_actions["15 minutes"].action(None, None)
        tray._multi_client.send_pause_dir.assert_called_once_with(
            targets[1], "/project-two", 15
        )

        paused_directory = next(
            item
            for item in second_directory_items
            if item.label(None).endswith("/project-two-paused")
        )
        paused_directory_actions = {
            item.label: item
            for item in paused_directory.action.items
            if isinstance(item, FakeMenuItem)
        }
        assert paused_directory_actions["Resume"].kwargs["visible"](None) is True
        with mock.patch.object(tray, "_check_and_autostart_daemon"):
            paused_directory_actions["Resume"].action(None, None)
        tray._multi_client.send_resume_dir.assert_called_once_with(
            targets[1], "/project-two-paused"
        )

    def test_single_daemon_pause_menu_follows_status_and_groups_directories(self):
        target = DaemonTarget(name="single", runtime="container", status="running")
        tray = _make_tray([target])
        stats = {
            "paused": False,
            "active_project_dirs": ["/single-project"],
            "paused_dirs": {"/single-project-paused": 0},
        }
        tray._multi_client.get_status.return_value = stats

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", FAKE_PYSTRAY),
        ):
            menu_items = tray._menu._build_single_daemon_menu_items()
            daemon_items = tray._menu._build_single_daemon_daemon_items()

        status_item = next(item for item in menu_items if item.label == "Status")
        pause_item = next(item for item in menu_items if item.label == "Pause...")
        assert menu_items.index(pause_item) == menu_items.index(status_item) + 1
        assert not any(
            isinstance(item, FakeMenuItem) and item.label == "Pause..."
            for item in daemon_items
        )

        pause_menu = pause_item.action
        global_menu = pause_menu.items[0].action
        global_actions = {
            item.label: item
            for item in global_menu.items
            if isinstance(item, FakeMenuItem)
        }
        assert global_actions["15 minutes"].kwargs["visible"](None) is True
        assert global_actions["Resume"].kwargs["visible"](None) is False
        stats["paused"] = True
        assert global_actions["Resume"].kwargs["visible"](None) is True

        directories_item = pause_menu.items[3]
        assert directories_item.label == "All sessions in directory..."
        assert directories_item.kwargs["visible"](None) is True
        visible_directories = [
            item
            for item in directories_item.action.items
            if isinstance(item, FakeMenuItem) and item.kwargs["visible"](None)
        ]
        assert len(visible_directories) == 2
        assert any(
            item.label(None).endswith("/single-project") for item in visible_directories
        )
        assert any(
            item.label(None).endswith("/single-project-paused")
            for item in visible_directories
        )

    def test_start_menu_lists_stopped_container_and_openshell_sandboxes(self):
        stopped_container = DaemonTarget(
            name="stopped-container",
            runtime="container",
            status="stopped",
            container_id="container-id",
        )
        stopped_openshell = DaemonTarget(
            name="stopped-openshell",
            runtime="container",
            runtime_type="openshell",
            status="stopped",
        )
        tray = _make_tray([])
        tray._stopped_container_targets = [stopped_openshell, stopped_container]

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch.object(
                tray._menu, "_capture_sandbox_screen_bounds", return_value=None
            ),
            mock.patch.object(tray._menu, "_start_sandbox_command") as start,
        ):
            items = tray._menu._build_sandbox_start_menu_items()
            start_menu = items[0]
            container_child = start_menu.action.items[0]
            openshell_child = start_menu.action.items[1]
            container_child.action(None, None)
            openshell_child.action(None, None)

        assert start_menu.label == "Start stopped sandbox..."
        assert start_menu.kwargs["visible"](None) is True
        assert container_child.label == "stopped-container (container)"
        assert openshell_child.label == "stopped-openshell (openshell)"
        assert start.call_args_list == [
            mock.call(stopped_container, "start", ["stopped-container"]),
            mock.call(stopped_openshell, "start", ["stopped-openshell"]),
        ]

    def test_noninteractive_sandbox_command_shows_captured_status(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            status="running",
            container_engine="podman",
        )
        tray = _make_tray([target])
        tray._discovery = None

        def run_command(args, *, output):
            assert args.sandbox_command == "status"
            assert args.runtime == "container"
            assert args.name == "ag-test"
            output.append("status output\n")
            return 0

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch(
                "ai_guardian.tray.menu_builder.threading.Thread", ImmediateThread
            ),
            mock.patch(
                "ai_guardian.sandbox.run_sandbox_command", side_effect=run_command
            ),
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log") as show_log,
        ):
            item = tray._menu._build_sandbox_manage_menu_item(0)
            status_item = item.action.items[0]
            status_item.action(None, None)

        show_log.assert_called_once_with(
            "Sandbox status",
            "Output from sandbox 'ag-test'.",
            "status output",
        )

    def test_noninteractive_sandbox_command_shows_captured_logs(self):
        target = DaemonTarget(
            name="ag-test",
            runtime="container",
            status="running",
            container_engine="podman",
        )
        tray = _make_tray([target])
        tray._discovery = None

        def run_command(args, *, output):
            assert args.sandbox_command == "logs"
            assert args.runtime == "container"
            assert args.name == "ag-test"
            output.append("log output\n")
            return 0

        with (
            mock.patch(
                "ai_guardian.sandbox.run_sandbox_command", side_effect=run_command
            ),
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log") as show_log,
        ):
            tray._menu._run_sandbox_command(target, "logs", [target.name])

        show_log.assert_called_once_with(
            "Sandbox logs",
            "Output from sandbox 'ag-test'.",
            "log output",
        )

    def test_start_menu_action_uses_direct_sandbox_command(self):
        target = DaemonTarget(
            name="stopped-container",
            runtime="container",
            status="stopped",
            container_id="container-id",
        )
        tray = _make_tray([])
        tray._stopped_container_targets = [target]

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch.object(
                tray._menu, "_capture_sandbox_screen_bounds", return_value=None
            ),
            mock.patch.object(tray._menu, "_start_sandbox_command") as start,
        ):
            item = tray._menu._build_sandbox_start_menu_items()[0]
            item.action.items[0].action(None, None)

        start.assert_called_once_with(
            target,
            "start",
            ["stopped-container"],
        )

    def test_create_form_maps_restore_and_runtime_options(self, tmp_path):
        tray = _make_tray([])
        first_policy = tmp_path / "read-only.yaml"
        second_policy = tmp_path / "network.yaml"
        first_policy.write_text("network_policies: {}\n", encoding="utf-8")
        second_policy.write_text("network_middlewares: {}\n", encoding="utf-8")
        values = {
            "runtime": "openshell",
            "name": "ag-test",
            "agent": "",
            "cli": "codex",
            "openshell_auth": "OAuth",
            "agent_provider": "",
            "repo": "/tmp/repo",
            "config_dir": "",
            "image": "localhost/ai-guardian:openshell",
            "model": "",
            "profile": "",
            "policies": f"{first_policy}, {second_policy}",
            "providers": "ai-guardian-codex, ai-guardian-github",
            "environment": "DEBUG=1, TERM=xterm",
            "labels": "team=security, owner=ai",
            "config_source": "Latest saved snapshot",
            "port": "",
        }
        with (
            mock.patch(
                "ai_guardian.sandbox._load_snapshot_config",
                return_value=(mock.sentinel.snapshot, {}),
            ) as load_snapshot,
            mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create,
            mock.patch(
                "ai_guardian.tray.menu_builder.tray_notifications.show_notification"
            ),
            mock.patch.object(tray._menu, "_show_sandbox_progress", return_value=None),
            mock.patch.object(
                tray._menu, "_confirm_sandbox_upload", return_value=True
            ) as confirm_upload,
        ):
            tray._menu._complete_sandbox_create_form(values)

        confirm_upload.assert_called_once()
        load_snapshot.assert_called_once_with("ag-test", "latest", runtime="openshell")
        create.assert_called_once()
        args = create.call_args.args[0]
        assert args.runtime == "openshell"
        assert args.name == "ag-test"
        assert args.cli == "codex"
        assert args.openshell_auth == "oauth"
        assert args.opencode_agent is None
        assert args.agent_provider is None
        assert args.repo == "/tmp/repo"
        assert args.config_dir is None
        assert args.image == "localhost/ai-guardian:openshell"
        assert args.model is None
        assert args.policy == [str(first_policy), str(second_policy)]
        assert args.provider == ["ai-guardian-codex", "ai-guardian-github"]
        assert args.environment == ["DEBUG=1", "TERM=xterm"]
        assert args.label == ["team=security", "owner=ai"]
        assert args.restore_config == "latest"
        assert args.fresh_config is False
        assert args.port is None
        assert create.call_args.kwargs["interactive"] is False
        assert isinstance(create.call_args.kwargs["output"], list)

    def test_create_form_rejects_missing_snapshot_before_runtime(self, tmp_path):
        tray = _make_tray([])
        values = {
            "runtime": "container",
            "name": "new-sandbox",
            "cli": "codex",
            "config_source": "Latest saved snapshot",
        }

        with (
            mock.patch.dict(
                os.environ,
                {"AI_GUARDIAN_STATE_DIR": str(tmp_path / "state")},
                clear=False,
            ),
            mock.patch.object(tray._menu, "_sandbox_error") as show_error,
            mock.patch.object(tray._menu, "_run_sandbox_create") as run_create,
        ):
            tray._menu._complete_sandbox_create_form(values)

        show_error.assert_called_once()
        assert "no configuration snapshot found" in show_error.call_args.args[1]
        run_create.assert_not_called()

    def test_create_form_maps_api_key_authentication_selection(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "name": "ag-test",
            "cli": "codex",
            "openshell_auth": "API key",
            "repo": "",
            "providers": "",
            "config_source": "Host/default",
        }

        with mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create:
            tray._menu._complete_sandbox_create_form(values)

        args = create.call_args.args[0]
        assert args.openshell_auth == "api_key"

    def test_create_form_does_not_apply_codex_authentication_to_claude(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "name": "ag-claude",
            "cli": "claude",
            "openshell_auth": "API key",
            "repo": "",
            "providers": "",
            "config_source": "Host/default",
        }

        with mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create:
            tray._menu._complete_sandbox_create_form(values)

        args = create.call_args.args[0]
        assert args.cli == "claude"
        assert args.openshell_auth is None

    def test_create_form_maps_native_mode_and_policy(self, tmp_path):
        tray = _make_tray([])
        policy = tmp_path / "native-policy.yaml"
        policy.write_text(
            "version: 1\nfilesystem_policy:\n  read_write: [/sandbox]\n",
            encoding="utf-8",
        )
        values = {
            "runtime": "openshell",
            "openshell_mode": "Native OpenShell",
            "name": "native-demo",
            "cli": "codex",
            "policy": str(policy),
            "config_source": "Host/default",
        }

        with mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create:
            tray._menu._complete_sandbox_create_form(values)

        args = create.call_args.args[0]
        assert args.openshell_mode == "Native OpenShell"
        assert args.openshell_auth is None
        assert args.policy == [str(policy)]

    def test_create_form_shows_runtime_log_when_direct_create_fails(self):
        tray = _make_tray([])

        def fail_create(_args, *, interactive, output):
            assert interactive is False
            output.append("runtime failed\n")
            return 1

        with (
            mock.patch("ai_guardian.sandbox.create_sandbox", side_effect=fail_create),
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log") as show_log,
            mock.patch.object(tray._menu, "_show_sandbox_progress", return_value=None),
        ):
            tray._menu._complete_sandbox_create_form(
                {"runtime": "container", "name": "ag-test"}
            )

        show_log.assert_called_once_with(
            "Sandbox creation failed",
            "Unable to create sandbox 'ag-test'.",
            "runtime failed",
        )

    def test_openshell_preflight_skips_transient_progress_before_confirmation(
        self, tmp_path
    ):
        tray = _make_tray([])
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('ok')\n", encoding="utf-8")
        values = {
            "runtime": "openshell",
            "name": "ag-test",
            "cli": "codex",
            "repo": str(repo),
        }
        with (
            mock.patch.object(tray._menu, "_show_sandbox_progress") as show_progress,
            mock.patch.object(
                tray._menu, "_sandbox_image_status", return_value="Found locally."
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_upload_confirmation",
                return_value=True,
            ) as show_confirmation,
            mock.patch.object(tray._menu, "_run_sandbox_create") as run_create,
        ):
            tray._menu._complete_sandbox_create_form(values)

        show_progress.assert_not_called()
        assert "(1 files)" in show_confirmation.call_args.args[0]
        run_create.assert_called_once()

    def test_upload_preflight_summarizes_size_and_git_remote(self, tmp_path):
        tray = _make_tray([])
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('ok')\n", encoding="utf-8")
        values = {
            "runtime": "openshell",
            "name": "ag-test",
            "cli": "codex",
            "repo": str(repo),
            "image": "localhost/ai-guardian-openshell:dev",
            "providers": "ai-guardian-codex",
            "environment": "TOKEN=hidden",
        }

        with (
            mock.patch(
                "ai_guardian.tray.menu_builder.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout="git@github.com:example/project.git\n",
                ),
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_upload_confirmation",
                return_value=True,
            ) as show_confirmation,
        ):
            assert tray._menu._confirm_sandbox_upload(values, str(repo)) is True

        message = show_confirmation.call_args.args[0]
        assert str(repo) in message
        assert "1 files" in message
        assert "GitHub repository" in message
        assert "TOKEN=hidden" not in message
        assert "ai-guardian sandbox create" in message

    def test_native_upload_preview_uses_native_openshell_command(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "openshell_mode": "Native OpenShell",
            "name": "native-demo",
            "repo": "/tmp/repo",
        }
        summary = {
            "path": "/tmp/repo",
            "size": 128,
            "files": 2,
            "source": "Local repository",
        }

        with mock.patch.object(tray._menu, "_sandbox_image_status") as image_status:
            message = tray._menu._sandbox_upload_confirmation_message(values, summary)

        image_status.assert_not_called()
        command_preview = message.split("Command preview:\n", 1)[1]
        assert "openshell sandbox create" in command_preview
        assert "--upload /tmp/repo:/sandbox/repo" in command_preview
        assert "ai-guardian sandbox create" not in command_preview

    def test_upload_preflight_reports_local_and_remote_image_status(self):
        tray = _make_tray([])
        with mock.patch(
            "ai_guardian.tray.menu_builder.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ):
            assert tray._menu._sandbox_image_status("localhost/image:dev") == (
                "Found locally."
            )

        with mock.patch(
            "ai_guardian.tray.menu_builder.subprocess.run",
            return_value=SimpleNamespace(returncode=1),
        ):
            assert tray._menu._sandbox_image_status("localhost/image:dev") == (
                "Missing locally; this local image reference will likely fail."
            )
            assert tray._menu._sandbox_image_status("quay.io/example/image:latest") == (
                "Not found locally; remote pull not probed."
            )

    def test_missing_local_image_marks_preflight_as_error(self, tmp_path):
        tray = _make_tray([])
        repo = tmp_path / "repo"
        repo.mkdir()
        values = {
            "runtime": "openshell",
            "name": "ag-test",
            "cli": "codex",
            "repo": str(repo),
            "image": "localhost/missing:dev",
        }

        with (
            mock.patch(
                "ai_guardian.tray.menu_builder.subprocess.run",
                side_effect=[
                    SimpleNamespace(returncode=1, stdout=""),
                    SimpleNamespace(returncode=1, stdout=""),
                ],
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_upload_confirmation",
                return_value=True,
            ) as show_confirmation,
        ):
            assert tray._menu._confirm_sandbox_upload(values, str(repo)) is True

        assert show_confirmation.call_args.kwargs["error_lines"] == (
            "Image status: Missing locally; this local image reference will likely fail.",
        )

    def test_cancelled_upload_preflight_reopens_creation_form(self, tmp_path):
        tray = _make_tray([])
        repo = tmp_path / "repo"
        repo.mkdir()
        values = {"runtime": "openshell", "name": "ag-test", "repo": str(repo)}

        with (
            mock.patch.object(
                tray._menu, "_confirm_sandbox_upload", return_value=False
            ),
            mock.patch.object(tray._menu, "_reopen_sandbox_create_form") as reopen,
            mock.patch.object(tray._menu, "_run_sandbox_create") as run_create,
        ):
            tray._menu._complete_sandbox_create_form(values, screen_bounds=(1, 2, 3, 4))

        reopen.assert_called_once_with(values, (1, 2, 3, 4))
        run_create.assert_not_called()

    def test_reopened_create_form_preserves_explicit_snapshot_choice(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "name": "ag-test",
            "config_source": "Latest saved snapshot",
        }

        with mock.patch.object(tray._menu, "_start_sandbox_form") as start_form:
            tray._menu._reopen_sandbox_create_form(values, None)

        fields = start_form.call_args.args[2]
        config_source = next(
            field for field in fields if field["name"] == "config_source"
        )
        assert config_source["default"] == "Latest saved snapshot"

    def test_create_form_config_source_defaults_are_isolated_and_valid(self):
        tray = _make_tray([])

        fresh_fields = tray._menu._sandbox_create_fields()
        snapshot_fields = tray._menu._sandbox_create_fields(
            {"config_source": "Latest saved snapshot"}
        )
        empty_fields = tray._menu._sandbox_create_fields({"config_source": ""})

        def config_source_default(fields):
            return next(
                field["default"] for field in fields if field["name"] == "config_source"
            )

        assert config_source_default(fresh_fields) == "Host/default"
        assert config_source_default(snapshot_fields) == "Latest saved snapshot"
        assert config_source_default(empty_fields) == "Host/default"

    def test_form_choice_default_falls_back_to_first_provider_choice(self):
        from ai_guardian.tray.sandbox_dialog import _choice_default

        field = {
            "name": "config_source",
            "type": "choice",
            "default": "",
        }
        choices = ("Host/default", "Latest saved snapshot")

        assert _choice_default(field, choices) == "Host/default"
        assert (
            _choice_default(
                {**field, "default": "Latest saved snapshot"},
                choices,
            )
            == "Latest saved snapshot"
        )

    def test_create_streams_output_and_finishes_progress_on_success(self):
        tray = _make_tray([])
        progress = mock.MagicMock()
        discovery = mock.MagicMock()
        tray._discovery = discovery

        def create_sandbox(_args, *, interactive, output):
            assert interactive is False
            output.append("creating sandbox\n")
            return 0

        with (
            mock.patch(
                "ai_guardian.sandbox.create_sandbox", side_effect=create_sandbox
            ),
            mock.patch.object(
                tray._menu, "_show_sandbox_progress", return_value=progress
            ) as show_progress,
            mock.patch(
                "ai_guardian.tray.menu_builder.tray_notifications.show_notification"
            ),
        ):
            tray._menu._run_sandbox_create(
                SimpleNamespace(runtime="container", name="ag-test")
            )

        show_progress.assert_called_once_with(
            "Creating sandbox 'ag-test'",
            "Operation: create\nRuntime: container\n"
            "Command is running; output appears below.",
            screen_bounds=None,
        )
        progress.append.assert_called_once_with("creating sandbox\n")
        progress.finish.assert_called_once_with(
            True, "Sandbox 'ag-test' created.", "creating sandbox"
        )
        discovery.request_refresh.assert_called_once_with(wait=False)

    def test_create_keeps_failed_progress_open(self):
        tray = _make_tray([])
        progress = mock.MagicMock()

        def fail_create(_args, *, interactive, output):
            output.append("runtime failed\n")
            return 1

        with (
            mock.patch("ai_guardian.sandbox.create_sandbox", side_effect=fail_create),
            mock.patch.object(
                tray._menu, "_show_sandbox_progress", return_value=progress
            ),
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log") as show_log,
        ):
            tray._menu._run_sandbox_create(
                SimpleNamespace(runtime="openshell", name="ag-test")
            )

        progress.finish.assert_called_once_with(
            False, "Unable to create sandbox 'ag-test'.", "runtime failed"
        )
        show_log.assert_not_called()

    def test_create_form_defaults_missing_config_source_to_host(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "name": "ag-codex",
            "cli": "codex",
            "repo": "",
            "providers": "",
            "model": "",
        }
        with mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create:
            tray._menu._complete_sandbox_create_form(values)

        args = create.call_args.args[0]
        assert args.restore_config is None
        assert args.fresh_config is True

    def test_create_form_rejects_unsupported_openshell_cli(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "name": "ag-pi",
            "cli": "pi",
            "agent_provider": "",
            "repo": "",
            "config_dir": "",
            "image": "",
            "model": "",
            "profile": "",
            "policies": "",
            "providers": "",
            "environment": "",
            "labels": "",
            "config_source": "Host/default",
            "port": "",
        }

        with (
            mock.patch.object(tray._menu, "_sandbox_error") as show_error,
            mock.patch("ai_guardian.sandbox.create_sandbox") as create,
        ):
            tray._menu._complete_sandbox_create_form(values)

        show_error.assert_called_once()
        assert "CLI 'pi' is not supported for openshell sandboxes" in (
            show_error.call_args.args[1]
        )
        create.assert_not_called()

    def test_create_form_exposes_policy_file_field(self):
        tray = _make_tray([])
        base_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AI_GUARDIAN_")
        }

        with mock.patch.dict(
            os.environ,
            base_env,
            clear=True,
        ):
            fields = tray._menu._sandbox_create_fields()

        field_names = [field["name"] for field in fields]
        assert field_names.index("cli") < field_names.index("name")

        runtime_field = next(field for field in fields if field["name"] == "runtime")
        assert runtime_field["default"] == "openshell"

        cli_field = next(field for field in fields if field["name"] == "cli")
        assert cli_field["type"] == "choice"
        assert cli_field["choices"] == TRAY_OPENSHELL_CLI_CHOICES
        assert cli_field["default"] == "codex"
        assert cli_field["required"] is True

        auth_field = next(
            field for field in fields if field["name"] == "openshell_auth"
        )
        assert auth_field["type"] == "choice"
        assert auth_field["choices"] == TRAY_OPENSHELL_AUTH_CHOICES
        assert auth_field["default"] == "OAuth"
        assert auth_field["required"] is True
        assert auth_field["enabled_when"] == (
            {"field": "runtime", "values": ("openshell",)},
            {"field": "openshell_mode", "values": ("AI Guardian hooks",)},
            {"field": "cli", "values": ("codex",)},
        )
        from ai_guardian.tray.sandbox_dialog import _field_enabled

        assert _field_enabled(
            auth_field,
            {
                "runtime": "openshell",
                "openshell_mode": "AI Guardian hooks",
                "cli": "codex",
            },
        )
        assert not _field_enabled(
            auth_field,
            {
                "runtime": "openshell",
                "openshell_mode": "AI Guardian hooks",
                "cli": "claude",
            },
        )
        assert not _field_enabled(
            auth_field,
            {
                "runtime": "container",
                "openshell_mode": "AI Guardian hooks",
                "cli": "codex",
            },
        )
        assert not _field_enabled(
            auth_field,
            {
                "runtime": "openshell",
                "openshell_mode": "Native OpenShell",
                "cli": "codex",
            },
        )
        assert "ai-guardian-codex" in auth_field["help"]
        assert "ai-guardian-openai" in auth_field["help"]

        name_field = next(field for field in fields if field["name"] == "name")
        assert name_field["default"] == "ag-codex"
        dynamic_default = name_field["dynamic_default"]
        assert dynamic_default["field"] == "cli"
        assert dynamic_default["separator"] == ""
        assert dynamic_default["suffix"] == ""
        assert name_field["help"]

        agent_field = next(field for field in fields if field["name"] == "agent")
        assert agent_field["type"] == "choice"
        assert agent_field["choices"] == ("", "build", "plan", "claude")
        assert agent_field["editable"] is True
        assert agent_field["default"] == ""
        assert agent_field["required"] is True
        assert agent_field["enabled_when"] == {
            "field": "cli",
            "values": ("opencode",),
        }

        provider_field = next(
            field for field in fields if field["name"] == "agent_provider"
        )
        assert provider_field["label"] == "Pi provider"
        assert (
            provider_field["choices"]
            == SANDBOX_PI_PROVIDER_CHOICES_BY_RUNTIME["openshell"]
        )
        assert provider_field["editable"] is False
        assert provider_field["choices_by"]["field"] == "runtime"
        assert provider_field["enabled_when"] == {
            "field": "cli",
            "values": ("pi",),
        }

        opencode_env = base_env.copy()
        opencode_env["AI_GUARDIAN_CLI"] = "opencode"
        with mock.patch.dict(os.environ, opencode_env, clear=True):
            fields = tray._menu._sandbox_create_fields()

        cli_field = next(field for field in fields if field["name"] == "cli")
        assert cli_field["default"] == "opencode"
        assert cli_field["choices"] == TRAY_OPENSHELL_CLI_CHOICES

        pi_env = base_env.copy()
        pi_env.update(
            {
                "AI_GUARDIAN_CLI": "pi",
                "AI_GUARDIAN_AGENT_PROVIDER": "openai",
            }
        )
        with mock.patch.dict(os.environ, pi_env, clear=True):
            fields = tray._menu._sandbox_create_fields()

        provider_field = next(
            field for field in fields if field["name"] == "agent_provider"
        )
        assert provider_field["default"] == ""
        assert next(field for field in fields if field["name"] == "name")[
            "default"
        ] == ("ag-codex")

        container_env = base_env.copy()
        container_env.update({"AI_GUARDIAN_SANDBOX_RUNTIME": "container"})
        with mock.patch.dict(os.environ, container_env, clear=True):
            fields = tray._menu._sandbox_create_fields()

        cli_field = next(field for field in fields if field["name"] == "cli")
        assert cli_field["choices"] == SUPPORTED_CLI_IDE_TYPES
        assert cli_field["choices_by"]["field"] == "runtime"
        provider_field = next(
            field for field in fields if field["name"] == "agent_provider"
        )
        assert (
            provider_field["choices"]
            == SANDBOX_PI_PROVIDER_CHOICES_BY_RUNTIME["container"]
        )
        assert provider_field["editable"] is True

        policy_field = next(field for field in fields if field["name"] == "policies")
        assert policy_field["type"] == "file"
        assert policy_field["multiple"] is True
        assert policy_field["default"] == ""
        assert "OpenShell" in policy_field["help"]
        assert policy_field["enabled_when"] == {
            "field": "runtime",
            "values": ("openshell",),
        }

        image_field = next(field for field in fields if field["name"] == "image")
        assert image_field["type"] == "image"
        assert "localhost/ai-guardian-openshell:dev" in image_field["help"]

        model_field = next(field for field in fields if field["name"] == "model")
        assert model_field["enabled_when"] == {
            "field": "runtime",
            "values": ("openshell",),
        }
        profile_field = next(field for field in fields if field["name"] == "profile")
        assert profile_field["type"] == "choice"
        assert profile_field["choices"] == (
            "",
            "@minimal",
            "@standard",
            "@strict",
            "@moderator",
        )
        assert profile_field["editable"] is True
        assert profile_field["enabled_when"] == {
            "field": "config_source",
            "values": ("Host/default",),
        }
        assert profile_field["clear_when_disabled"] is True
        provider_field = next(field for field in fields if field["name"] == "providers")
        assert provider_field["label"] == "OpenShell provider override"
        assert provider_field["type"] == "text"
        assert provider_field["default"] == ""
        assert "Codex authentication" in provider_field["help"]
        assert provider_field["enabled_when"] == {
            "field": "runtime",
            "values": ("openshell",),
        }
        environment_field = next(
            field for field in fields if field["name"] == "environment"
        )
        assert "KEY=VALUE" in environment_field["help"]

        repo_field = next(field for field in fields if field["name"] == "repo")
        assert repo_field["type"] == "directory"
        assert repo_field["default"] == os.path.expanduser("~")

    def test_create_form_exposes_native_openshell_mode_and_policy_profile(self):
        tray = _make_tray([])
        base_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AI_GUARDIAN_")
        }
        with mock.patch.dict(os.environ, base_env, clear=True):
            fields = tray._menu._sandbox_create_fields()

        mode_field = next(
            field for field in fields if field["name"] == "openshell_mode"
        )
        assert mode_field["choices"] == TRAY_OPENSHELL_MODE_CHOICES
        assert mode_field["default"] == "AI Guardian hooks"
        policy_field = next(field for field in fields if field["name"] == "policy")
        assert policy_field["type"] == "choice"
        assert policy_field["choices"][0] == "No additional policy"
        assert any("valid" in choice for choice in policy_field["choices"][1:])

    def test_openshell_readiness_is_a_standalone_menu_action(self):
        tray = _make_tray([])
        with mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY):
            items = tray._menu._build_openshell_middleware_menu_items()

        assert [item.label for item in items] == ["Check middleware readiness..."]
        assert callable(items[0].action)

    def test_multi_daemon_policy_action_is_scoped_to_the_selected_openshell_target(
        self,
    ):
        targets = [
            DaemonTarget(
                name="sandbox-one",
                runtime="container",
                runtime_type="openshell",
                status="running",
            ),
            DaemonTarget(
                name="sandbox-two",
                runtime="container",
                runtime_type="openshell",
                status="running",
            ),
            DaemonTarget(name="container-one", runtime="container", status="running"),
        ]
        tray = _make_tray(targets)

        with (
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch("ai_guardian.tray.plugin_runner.pystray", FAKE_PYSTRAY),
        ):
            daemon_items = tray._menu._build_multi_daemon_menu_items()

        second_manage_item = next(
            item
            for item in daemon_items[1].action.items
            if isinstance(item, FakeMenuItem) and item.label == "Manage sandbox"
        )
        apply_item = next(
            item
            for item in second_manage_item.action.items
            if isinstance(item, FakeMenuItem)
            and item.label == "Apply policy to sandbox..."
        )
        assert apply_item.kwargs["visible"](None) is True

        third_manage_item = next(
            item
            for item in daemon_items[2].action.items
            if isinstance(item, FakeMenuItem) and item.label == "Manage sandbox"
        )
        non_openshell_policy_item = next(
            item
            for item in third_manage_item.action.items
            if isinstance(item, FakeMenuItem)
            and item.label == "Apply policy to sandbox..."
        )
        assert non_openshell_policy_item.kwargs["visible"](None) is False

        records = [
            {"name": "sandbox-one", "phase": "running"},
            {"name": "sandbox-two", "phase": "running"},
        ]
        with (
            mock.patch.object(
                tray._menu, "_capture_sandbox_screen_bounds", return_value=None
            ),
            mock.patch.object(tray._menu, "_start_sandbox_form") as start_form,
            mock.patch(
                "ai_guardian.sandbox.list_openshell_sandboxes", return_value=records
            ) as list_sandboxes,
            mock.patch(
                "ai_guardian.tray.menu_builder.discover_openshell_policies",
                return_value=(),
            ),
            mock.patch(
                "ai_guardian.tray.menu_builder.threading.Thread", ImmediateThread
            ),
        ):
            apply_item.action(None, None)

        list_args = list_sandboxes.call_args.args[0]
        assert list_args.openshell_cli is None
        fields = start_form.call_args.args[2]
        sandbox_field = next(field for field in fields if field["name"] == "sandbox")
        assert sandbox_field["choices"] == ("sandbox-two (running)",)
        assert sandbox_field["default"] == "sandbox-two (running)"
        assert sandbox_field["editable"] is False

    def test_apply_openshell_policy_form_has_a_wider_profile_field(self):
        tray = _make_tray([])
        with mock.patch(
            "ai_guardian.tray.menu_builder.discover_openshell_policies",
            return_value=(),
        ):
            fields = tray._menu._openshell_policy_apply_fields([])

        profile = next(field for field in fields if field["name"] == "policy")
        assert profile["width"] == 68
        assert "enter a policy file path" in profile["help"]
        assert "complete policy before replacement" in profile["help"]

    def test_apply_openshell_policy_edits_and_applies_complete_merged_yaml(
        self, tmp_path
    ):
        tray = _make_tray([])
        overlay = tmp_path / "github-readwrite.yaml"
        overlay.write_text("network_policies: {}\n", encoding="utf-8")
        temporary_dir = tmp_path / "prepared"
        temporary_dir.mkdir()
        policy_path = temporary_dir / "policy.yaml"
        policy_path.write_text(
            "version: 1\nfilesystem_policy:\n  read_only: false\n"
            "network_policies:\n  github: readwrite\n",
            encoding="utf-8",
        )
        complete_yaml = policy_path.read_text(encoding="utf-8").rstrip()
        current = {"version": 1, "filesystem_policy": {"read_only": False}}
        updated = {
            "version": 1,
            "filesystem_policy": {"read_only": False},
            "network_policies": {"github": "readwrite"},
        }

        with (
            mock.patch.object(
                tray._menu, "_openshell_policy_paths", return_value=[overlay]
            ),
            mock.patch.object(tray._menu, "_show_sandbox_progress") as show_progress,
            mock.patch.object(tray._menu, "_sandbox_progress_close") as close_progress,
            mock.patch(
                "ai_guardian.sandbox.prepare_openshell_policy_update",
                return_value=(policy_path, temporary_dir, current, updated),
            ),
            mock.patch(
                "ai_guardian.sandbox.apply_openshell_policy", return_value=0
            ) as apply_policy,
            mock.patch(
                "ai_guardian.sandbox.get_openshell_base_policy", return_value=updated
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_form",
                return_value={"policy_yaml": complete_yaml},
            ) as confirm,
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log"),
            mock.patch(
                "ai_guardian.tray.menu_builder.tray_notifications.show_notification"
            ),
        ):
            tray._menu._complete_openshell_policy_form(
                {"sandbox": "github-demo", "policy": str(overlay)}, []
            )

        title, message, fields = confirm.call_args.args
        assert title == "Apply OpenShell policy"
        assert f"Selected policy profile: {overlay}" in message
        assert "complete merged YAML below" in message
        assert fields[0]["type"] == "textarea"
        assert fields[0]["label"] == "Complete merged policy (YAML)"
        assert fields[0]["default"] == complete_yaml
        assert confirm.call_args.kwargs["submit_label"] == "Replace policy"
        apply_policy.assert_called_once()
        show_progress.assert_not_called()
        close_progress.assert_not_called()

    def test_apply_openshell_policy_reopens_editor_after_validation_error(
        self, tmp_path
    ):
        tray = _make_tray([])
        overlay = tmp_path / "github-readwrite.yaml"
        overlay.write_text("network_policies: {}\n", encoding="utf-8")
        temporary_dir = tmp_path / "prepared"
        temporary_dir.mkdir()
        policy_path = temporary_dir / "policy.yaml"
        initial_yaml = (
            "version: 1\nfilesystem_policy:\n  read_only: false\n"
            "network_policies:\n  github: readwrite\n"
        )
        policy_path.write_text(initial_yaml, encoding="utf-8")
        current = {"version": 1, "filesystem_policy": {"read_only": False}}
        updated = {
            "version": 1,
            "filesystem_policy": {"read_only": False},
            "network_policies": {"github": "readwrite"},
        }

        with (
            mock.patch.object(
                tray._menu, "_openshell_policy_paths", return_value=[overlay]
            ),
            mock.patch(
                "ai_guardian.sandbox.prepare_openshell_policy_update",
                return_value=(policy_path, temporary_dir, current, updated),
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.show_sandbox_form",
                side_effect=[
                    {"policy_yaml": "version: ["},
                    {"policy_yaml": initial_yaml},
                ],
            ) as edit_form,
            mock.patch(
                "ai_guardian.sandbox.apply_openshell_policy", return_value=1
            ) as apply_policy,
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log"),
        ):
            tray._menu._complete_openshell_policy_form(
                {"sandbox": "github-demo", "policy": str(overlay)}, []
            )

        assert edit_form.call_count == 2
        assert "validation failed" in edit_form.call_args_list[1].args[1]
        assert edit_form.call_args_list[1].args[2][0]["default"] == "version: ["
        apply_policy.assert_called_once()

    def test_middleware_readiness_action_auto_discovers_without_a_setup_form(self):
        tray = _make_tray([])

        with (
            mock.patch.object(
                tray._menu, "_capture_sandbox_screen_bounds", return_value=None
            ),
            mock.patch.object(
                tray._menu, "_run_openshell_middleware_readiness"
            ) as run_readiness,
            mock.patch.object(tray._menu, "_start_sandbox_form") as start_form,
            mock.patch("ai_guardian.tray.menu_builder.threading.Thread") as thread,
        ):
            action = tray._menu._mk_openshell_middleware_readiness_action()
            action(None, None)

        thread.assert_called_once()
        assert thread.call_args.kwargs["target"] == run_readiness
        assert thread.call_args.kwargs["kwargs"] == {}
        thread.return_value.start.assert_called_once()
        start_form.assert_not_called()

    def test_create_form_defaults_repo_to_active_working_dir(self):
        tray = _make_tray(
            [
                DaemonTarget(
                    name="ag-test",
                    runtime="container",
                    working_dir="/tmp/current-project",
                )
            ]
        )
        tray._active_target = tray._targets[0]

        with mock.patch.dict(os.environ, {}, clear=True):
            fields = tray._menu._sandbox_create_fields()

        repo_field = next(field for field in fields if field["name"] == "repo")
        assert repo_field["default"] == "/tmp/current-project"

    def test_working_dir_change_updates_create_form_target(self):
        first = DaemonTarget(
            name="first",
            runtime="container",
            working_dir="/tmp/first",
        )
        second = DaemonTarget(
            name="second",
            runtime="container",
            working_dir="/tmp/old-second",
        )
        tray = _make_tray([first, second])
        tray._active_target = first

        with (
            mock.patch(
                "ai_guardian.daemon.working_dir.choose_directory",
                return_value="/tmp/new-second",
            ),
            mock.patch("ai_guardian.daemon.working_dir.set_working_dir"),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            tray._menu._pick_working_dir(second, second.working_dir)
            fields = tray._menu._sandbox_create_fields()

        assert tray._active_target is second
        repo_field = next(field for field in fields if field["name"] == "repo")
        assert repo_field["default"] == "/tmp/new-second"

        config_dir_field = next(
            field for field in fields if field["name"] == "config_dir"
        )
        assert config_dir_field["type"] == "directory"
        assert config_dir_field["enabled_when"] == {
            "field": "config_source",
            "values": ("Host/default",),
        }
        assert config_dir_field["clear_when_disabled"] is True

        labels_field = next(field for field in fields if field["name"] == "labels")
        assert "KEY=VALUE" in labels_field["help"]

        port_field = next(field for field in fields if field["name"] == "port")
        assert port_field["enabled_when"] == {
            "field": "runtime",
            "values": ("container",),
        }

    def test_browse_paths_merge_without_duplicates(self):
        from ai_guardian.tray.sandbox_dialog import _merge_browse_paths

        assert _merge_browse_paths(
            "/tmp/one.yaml", ("/tmp/one.yaml", "/tmp/two.yaml")
        ) == ("/tmp/one.yaml, /tmp/two.yaml")

    def test_directory_browser_replaces_current_value(self):
        from ai_guardian.tray.sandbox_dialog import _browse_selection

        assert _browse_selection("/tmp/repo", "/tmp/Downloads", "directory") == (
            "/tmp/Downloads"
        )
        assert _browse_selection("/tmp/repo", "", "directory") == "/tmp/repo"

    def test_dynamic_default_uses_selected_cli(self):
        from ai_guardian.tray.sandbox_dialog import _dynamic_default_value

        assert (
            _dynamic_default_value(
                {
                    "prefix": "ag-",
                    "value_max_length": 8,
                    "separator": "-",
                    "suffix": "abc123",
                },
                "claude",
            )
            == "ag-claude-abc123"
        )

        assert (
            _dynamic_default_value(
                {"value_by": {"opencode": "openai/gpt-5.6-luna"}},
                "opencode",
            )
            == "openai/gpt-5.6-luna"
        )

    def test_path_browser_starts_at_current_directory_value(self, tmp_path):
        from ai_guardian.tray.sandbox_dialog import _browse_initialdir

        repo = tmp_path / "repo"
        repo.mkdir()

        assert _browse_initialdir(str(repo)) == str(repo)
        assert _browse_initialdir(str(repo / "new-file")) == str(repo)
        assert _browse_initialdir("") is None

    def test_local_image_choices_use_ai_guardian_image_label(self):
        from ai_guardian.tray.sandbox_dialog import (
            _format_local_image_choice,
            _local_image_choices,
        )

        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "localhost/ai-guardian-openshell:dev\t2026-10-03 16:00:00 +0000 UTC\n"
                "<none>:<none>\t2026-10-03 15:00:00 +0000 UTC\n"
                "localhost/ai-guardian:dev\t2026-10-02 16:00:00 +0000 UTC\n"
                "localhost/ai-guardian-openshell:dev\t2026-10-01 16:00:00 +0000 UTC\n"
            ),
        )
        with (
            mock.patch.dict(os.environ, {"CONTAINER_ENGINE": "podman"}, clear=True),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.subprocess.run",
                return_value=result,
            ) as run,
        ):
            assert _local_image_choices() == [
                (
                    "localhost/ai-guardian-openshell:dev",
                    "2026-10-03 16:00:00 +0000 UTC",
                ),
                ("localhost/ai-guardian:dev", "2026-10-02 16:00:00 +0000 UTC"),
            ]
            local_time = datetime.strptime(
                "2026-10-03 16:00:00 +0000", "%Y-%m-%d %H:%M:%S %z"
            ).astimezone()
            timezone_name = local_time.tzname() or local_time.strftime("%z")
            assert _format_local_image_choice(
                "localhost/ai-guardian-openshell:dev",
                "2026-10-03 16:00:00 +0000 UTC",
            ) == (
                "localhost/ai-guardian-openshell:dev "
                f"(created {local_time:%Y-%m-%d %H:%M:%S} {timezone_name})"
            )

        run.assert_called_once_with(
            [
                "podman",
                "image",
                "ls",
                "--filter",
                "label=ai-guardian.support-image=true",
                "--format",
                "{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def test_create_form_rejects_policy_files_for_container(self):
        tray = _make_tray([])

        with (
            mock.patch.object(tray._menu, "_sandbox_error") as show_error,
            mock.patch(
                "ai_guardian.tray.menu_builder.tray_menu.launch_sandbox_create_command"
            ) as launch,
        ):
            tray._menu._complete_sandbox_create_form(
                {
                    "runtime": "container",
                    "name": "ag-test",
                    "policies": "/tmp/policy.yaml",
                }
            )

        show_error.assert_called_once_with(
            "Create AI Guardian sandbox",
            "Policy files are supported for OpenShell sandboxes only.",
        )
        launch.assert_not_called()

    def test_main_tray_menu_includes_create_item(self):
        tray = _make_tray([])
        sentinel = object()
        with (
            mock.patch("ai_guardian.tray.app.pystray", FAKE_PYSTRAY, create=True),
            mock.patch("ai_guardian.tray.menu_builder.pystray", FAKE_PYSTRAY),
            mock.patch.object(
                tray._menu, "_build_single_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_single_daemon_daemon_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_multi_daemon_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._plugins, "_build_single_daemon_plugin_items", return_value=[]
            ),
            mock.patch.object(
                tray._plugins, "_build_global_plugin_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu, "_build_ide_setup_menu_items", return_value=[]
            ),
            mock.patch.object(
                tray._menu,
                "_build_sandbox_create_menu_items",
                return_value=[sentinel],
            ),
        ):
            menu = tray._build_tray_menu()

        assert sentinel in menu.items


class TestSandboxDialogFallback:
    @pytest.fixture(autouse=True)
    def _enable_ui_provider(self, monkeypatch):
        monkeypatch.setenv("AI_GUARDIAN_PREFERRED_UI", "auto")

    @staticmethod
    def _rect(x, y, width, height):
        return SimpleNamespace(
            origin=SimpleNamespace(x=x, y=y),
            size=SimpleNamespace(width=width, height=height),
        )

    def test_window_geometry_centers_and_clamps_to_display(self):
        from ai_guardian.tray.sandbox_dialog import _center_window_geometry

        assert _center_window_geometry(560, 250, (1920, 0, 2560, 1440)) == (
            2920,
            595,
            560,
            250,
        )
        assert _center_window_geometry(1000, 800, (0, 0, 800, 600)) == (
            0,
            0,
            800,
            600,
        )

    def test_cocoa_screen_bounds_convert_to_tk_coordinates(self):
        from ai_guardian.tray.sandbox_dialog import _tk_screen_bounds

        main = self._rect(0, 0, 1920, 1440)
        secondary_visible = self._rect(1920, 23, 2560, 1380)

        assert _tk_screen_bounds(secondary_visible, main) == (1920, 37, 2560, 1380)

    def test_tray_screen_bounds_select_status_item_display_without_tk(self):
        from ai_guardian.tray.sandbox_dialog import _get_tray_screen_bounds

        main = mock.MagicMock()
        main.frame.return_value = self._rect(0, 0, 1920, 1440)
        main.visibleFrame.return_value = self._rect(0, 23, 1920, 1390)
        secondary = mock.MagicMock()
        secondary.frame.return_value = self._rect(1920, 0, 2560, 1440)
        secondary.visibleFrame.return_value = self._rect(1920, 23, 2560, 1380)
        appkit = mock.MagicMock()
        appkit.NSScreen.screens.return_value = [main, secondary]
        appkit.NSApplication.sharedApplication.return_value.currentEvent.return_value = (
            None
        )
        # Keyboard focus may be on a different display; it must not change
        # the virtual-screen origin used for Tk geometry.
        appkit.NSScreen.mainScreen.return_value = secondary
        icon = mock.MagicMock()
        icon._status_item.button.return_value.window.return_value.screen.return_value = (
            secondary
        )

        with (
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.platform.system",
                return_value="Darwin",
            ),
            mock.patch.dict("sys.modules", {"AppKit": appkit}),
        ):
            assert _get_tray_screen_bounds(icon) == (1920, 37, 2560, 1380)

    def test_tray_screen_bounds_falls_back_to_pointer_display_without_icon(self):
        from ai_guardian.tray.sandbox_dialog import _get_tray_screen_bounds

        main = mock.MagicMock()
        main.frame.return_value = self._rect(0, 0, 1920, 1440)
        main.visibleFrame.return_value = self._rect(0, 23, 1920, 1390)
        secondary = mock.MagicMock()
        secondary.frame.return_value = self._rect(1920, 0, 2560, 1440)
        secondary.visibleFrame.return_value = self._rect(1920, 23, 2560, 1380)
        appkit = mock.MagicMock()
        appkit.NSScreen.screens.return_value = [main, secondary]
        appkit.NSApplication.sharedApplication.return_value.currentEvent.return_value = (
            None
        )
        appkit.NSEvent.mouseLocation.return_value = SimpleNamespace(x=2200, y=400)

        with (
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.platform.system",
                return_value="Darwin",
            ),
            mock.patch.dict("sys.modules", {"AppKit": appkit}),
        ):
            assert _get_tray_screen_bounds() == (1920, 37, 2560, 1380)

    def test_tray_screen_bounds_prefer_current_menu_event_display(self):
        from ai_guardian.tray.sandbox_dialog import _get_tray_screen_bounds

        main = mock.MagicMock()
        main.frame.return_value = self._rect(0, 0, 1920, 1440)
        secondary = mock.MagicMock()
        secondary.frame.return_value = self._rect(1920, 0, 2560, 1440)
        secondary.visibleFrame.return_value = self._rect(1920, 23, 2560, 1380)
        appkit = mock.MagicMock()
        appkit.NSScreen.screens.return_value = [main, secondary]
        event = mock.MagicMock()
        event.window.return_value.screen.return_value = secondary
        appkit.NSApplication.sharedApplication.return_value.currentEvent.return_value = (
            event
        )
        icon = mock.MagicMock()
        icon._status_item.button.return_value.window.return_value.screen.return_value = (
            main
        )

        with (
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.platform.system",
                return_value="Darwin",
            ),
            mock.patch.dict("sys.modules", {"AppKit": appkit}),
        ):
            assert _get_tray_screen_bounds(icon) == (1920, 37, 2560, 1380)

    def test_tray_screen_bounds_use_pointer_display_for_mouse_menu_event(self):
        from ai_guardian.tray.sandbox_dialog import _get_tray_screen_bounds

        main = mock.MagicMock()
        main.frame.return_value = self._rect(0, 0, 1920, 1440)
        secondary = mock.MagicMock()
        secondary.frame.return_value = self._rect(1920, 0, 2560, 1440)
        secondary.visibleFrame.return_value = self._rect(1920, 23, 2560, 1380)
        appkit = mock.MagicMock()
        appkit.NSScreen.screens.return_value = [main, secondary]
        appkit.NSLeftMouseUp = 2
        event = mock.MagicMock()
        event.type.return_value = appkit.NSLeftMouseUp
        # Nested menu actions can report the stale parent menu window even
        # though the pointer is on the display where the item was clicked.
        event.window.return_value.screen.return_value = main
        appkit.NSApplication.sharedApplication.return_value.currentEvent.return_value = (
            event
        )
        appkit.NSEvent.mouseLocation.return_value = SimpleNamespace(x=2200, y=400)
        icon = mock.MagicMock()
        icon._status_item.button.return_value.window.return_value.screen.return_value = (
            main
        )

        with (
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.platform.system",
                return_value="Darwin",
            ),
            mock.patch.dict("sys.modules", {"AppKit": appkit}),
        ):
            assert _get_tray_screen_bounds(icon) == (1920, 37, 2560, 1380)

    def test_place_window_on_screen_uses_centered_geometry(self):
        from ai_guardian.tray.sandbox_dialog import _place_window_on_screen

        window = mock.MagicMock()

        assert _place_window_on_screen(window, (1920, 0, 2560, 1440), 560, 250)
        window.geometry.assert_called_once_with("560x250+2920+595")

    def test_place_window_on_screen_formats_negative_virtual_coordinates(self):
        from ai_guardian.tray.sandbox_dialog import _place_window_on_screen

        window = mock.MagicMock()

        assert _place_window_on_screen(window, (-1600, -200, 1600, 900), 560, 250)
        window.geometry.assert_called_once_with("560x250+-1080+125")

    def test_place_window_without_screen_bounds_keeps_window_manager_fallback(self):
        from ai_guardian.tray.sandbox_dialog import _place_window_on_screen

        window = mock.MagicMock()

        assert not _place_window_on_screen(window, None, 560, 250)
        window.geometry.assert_not_called()

    def test_log_copy_uses_system_clipboard(self):
        from ai_guardian.tray.sandbox_dialog import _copy_sandbox_log

        with mock.patch(
            "ai_guardian.ui.clipboard.copy_to_system_clipboard",
            return_value=(None, "xclip"),
        ) as copy_to_clipboard:
            message = _copy_sandbox_log("runtime output")

        assert message == "Copied to clipboard (xclip)."
        copy_to_clipboard.assert_called_once_with("runtime output")

    def test_form_mouse_wheel_scrolls_canvas_on_each_platform(self):
        from ai_guardian.tray.sandbox_dialog import _scroll_canvas

        canvas = mock.MagicMock()
        _scroll_canvas(SimpleNamespace(delta=120, num=None), canvas)
        _scroll_canvas(SimpleNamespace(delta=-120, num=None), canvas)
        _scroll_canvas(SimpleNamespace(delta=0, num=4), canvas)
        _scroll_canvas(SimpleNamespace(delta=0, num=5), canvas)

        assert canvas.yview_scroll.call_args_list == [
            mock.call(-1, "units"),
            mock.call(1, "units"),
            mock.call(-1, "units"),
            mock.call(1, "units"),
        ]

    def test_log_copy_uses_tkinter_clipboard_owner(self):
        from ai_guardian.tray.sandbox_dialog import _copy_sandbox_log

        clipboard_owner = mock.MagicMock()
        message = _copy_sandbox_log("runtime output", clipboard_owner=clipboard_owner)

        assert message == "Copied to clipboard (Tkinter)."
        clipboard_owner.clipboard_clear.assert_called_once_with()
        clipboard_owner.clipboard_append.assert_called_once_with("runtime output")
        clipboard_owner.update.assert_called_once_with()

    def test_progress_forwards_output_and_completion(self):
        import json

        from ai_guardian.tray.sandbox_dialog import SandboxProgress

        process = mock.MagicMock()
        progress = SandboxProgress(process)

        progress.append("runtime output\n")
        assert progress.finish(False, "Operation failed.", "runtime output")

        updates = [
            json.loads(call.args[0]) for call in process.stdin.write.call_args_list
        ]
        assert updates == [
            {"type": "output", "text": "runtime output\n"},
            {
                "type": "complete",
                "success": False,
                "message": "Operation failed.",
                "log": "runtime output",
            },
        ]
        process.stdin.close.assert_called_once_with()

    def test_progress_reports_readiness_and_closes_without_completion(self):
        import json

        from ai_guardian.tray.sandbox_dialog import SandboxProgress, _PROGRESS_READY

        process = SimpleNamespace(
            stdout=io.StringIO(f"{_PROGRESS_READY}\n"),
            stdin=mock.MagicMock(),
            wait=mock.MagicMock(),
        )
        progress = SandboxProgress(process)

        assert progress.wait_ready(timeout=1) is True
        progress.update_status("Scanning repository files...")
        assert progress.close() is True

        updates = [
            json.loads(call.args[0]) for call in process.stdin.write.call_args_list
        ]
        assert updates == [
            {"type": "status", "message": "Scanning repository files..."},
            {"type": "close"},
        ]
        process.stdin.close.assert_called_once_with()

    def test_progress_subprocess_falls_back_when_child_is_not_ready(self):
        from ai_guardian.tray.sandbox_dialog import _show_tkinter_progress_subprocess

        process = SimpleNamespace(
            stdout=io.StringIO(),
            stdin=mock.MagicMock(),
            wait=mock.MagicMock(),
            terminate=mock.MagicMock(),
        )
        with mock.patch(
            "ai_guardian.tray.sandbox_dialog.subprocess.Popen", return_value=process
        ):
            assert _show_tkinter_progress_subprocess("Title", "Message") is None

        process.stdin.close.assert_called_once_with()
        process.terminate.assert_called_once_with()

    def test_progress_subprocess_waits_for_child_readiness(self):
        from ai_guardian.tray.sandbox_dialog import (
            SandboxProgress,
            _PROGRESS_READY,
            _show_tkinter_progress_subprocess,
        )

        process = SimpleNamespace(
            stdout=io.StringIO(f"{_PROGRESS_READY}\n"),
            stdin=mock.MagicMock(),
            wait=mock.MagicMock(),
        )
        with mock.patch(
            "ai_guardian.tray.sandbox_dialog.subprocess.Popen", return_value=process
        ):
            progress = _show_tkinter_progress_subprocess("Title", "Message")

        assert isinstance(progress, SandboxProgress)
        progress.close()

    def test_successful_progress_dialog_stays_open_for_user_to_close(self):
        import queue
        from types import ModuleType

        from ai_guardian.tray.sandbox_dialog import _show_tkinter_progress

        class Updates:
            def __init__(self):
                self.values = [
                    {
                        "type": "complete",
                        "success": True,
                        "message": "Sandbox 'demo' created.",
                        "log": "Sandbox ready",
                    }
                ]

            def get_nowait(self):
                if self.values:
                    return self.values.pop(0)
                raise queue.Empty

        root = mock.MagicMock()
        root.winfo_exists.return_value = True
        scheduled = []

        def schedule(delay, callback):
            if delay == 50:
                scheduled.append(callback)
            else:
                callback()

        root.after.side_effect = schedule
        root.mainloop.side_effect = lambda: scheduled.pop(0)()
        variables = []

        def make_variable(*_args, **_kwargs):
            variable = mock.MagicMock()
            variables.append(variable)
            return variable

        tk_module = ModuleType("tkinter")
        tk_module.Tk = mock.Mock(return_value=root)
        tk_module.StringVar = make_variable
        tk_module.BooleanVar = make_variable
        tk_module.Text = mock.Mock(return_value=mock.MagicMock())
        tk_module.TclError = type("TclError", (Exception,), {})
        ttk_module = ModuleType("tkinter.ttk")
        ttk_module.Frame = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())
        ttk_module.Label = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())
        ttk_module.Scrollbar = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())
        ttk_module.Checkbutton = mock.Mock(
            side_effect=lambda *_a, **_k: mock.MagicMock()
        )
        ttk_module.Button = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())
        tk_module.ttk = ttk_module

        with (
            mock.patch.dict(
                "sys.modules",
                {"tkinter": tk_module, "tkinter.ttk": ttk_module},
            ),
            mock.patch("ai_guardian.ui.display._ensure_tcl_library"),
            mock.patch("ai_guardian.tray.sandbox_dialog._place_window_on_screen"),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.queue.Queue", return_value=Updates()
            ),
            mock.patch("ai_guardian.tray.sandbox_dialog.threading.Thread"),
        ):
            _show_tkinter_progress("Creating sandbox", "Running")

        root.destroy.assert_not_called()
        variables[0].set.assert_called_once_with("Sandbox 'demo' created.")

    def test_sandbox_text_wrap_switches_between_wrapped_and_unwrapped(self):
        from ai_guardian.tray.sandbox_dialog import _set_text_wrap

        text = mock.MagicMock()

        _set_text_wrap(text, True)
        _set_text_wrap(text, False)

        assert text.configure.call_args_list == [
            mock.call(wrap="word"),
            mock.call(wrap="none"),
        ]

    def test_progress_uses_captured_output_fallback_when_tkinter_is_unavailable(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_progress

        with mock.patch(
            "ai_guardian.ui.display._tkinter_available", return_value=False
        ):
            progress = show_sandbox_progress("Title", "Message")

        assert progress is not None
        assert progress.finish(False, "failed", "output") is False

    def test_progress_isolated_in_subprocess_when_tkinter_is_available(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_progress

        progress = object()
        with (
            mock.patch("ai_guardian.ui.display._tkinter_available", return_value=True),
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="tkinter"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_tkinter_progress_subprocess",
                return_value=progress,
            ) as show_progress,
        ):
            result = show_sandbox_progress("Title", "Message")

        assert result is progress
        show_progress.assert_called_once_with("Title", "Message")

    def test_form_returns_none_when_ui_is_headless(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with mock.patch(
            "ai_guardian.ui.display.select_ui_provider", return_value="headless"
        ):
            assert show_sandbox_form("Title", "Message", []) is None

    def test_form_isolated_in_subprocess_when_tkinter_is_available(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with (
            mock.patch("ai_guardian.ui.display._tkinter_available", return_value=True),
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="tkinter"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
                return_value={"runtime": "container"},
            ) as show_form,
        ):
            result = show_sandbox_form("Title", "Message", [])

        assert result == {"runtime": "container"}
        show_form.assert_called_once_with("Title", "Message", [])

    def test_form_forwards_custom_submit_label_to_tkinter_subprocess(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with (
            mock.patch("ai_guardian.ui.display._tkinter_available", return_value=True),
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="tkinter"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
                return_value={"policy_yaml": "version: 1"},
            ) as show_form,
        ):
            result = show_sandbox_form(
                "Apply OpenShell policy",
                "Review policy",
                [{"name": "policy_yaml", "type": "textarea"}],
                submit_label="Replace policy",
            )

        assert result == {"policy_yaml": "version: 1"}
        show_form.assert_called_once_with(
            "Apply OpenShell policy",
            "Review policy",
            [{"name": "policy_yaml", "type": "textarea"}],
            submit_label="Replace policy",
        )

    def test_tk_form_returns_edited_multiline_textarea(self):
        from types import ModuleType

        from ai_guardian.tray.sandbox_dialog import _show_tkinter_form

        root = mock.MagicMock()
        text_widget = mock.MagicMock()
        text_widget.get.return_value = "version: 1\nnetwork_policies: {}"
        ttk_module = ModuleType("tkinter.ttk")
        ttk_module.Frame = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())
        ttk_module.Label = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())
        ttk_module.Scrollbar = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())
        ttk_module.Checkbutton = mock.Mock(
            side_effect=lambda *_a, **_k: mock.MagicMock()
        )
        ttk_module.Button = mock.Mock(side_effect=lambda *_a, **_k: mock.MagicMock())

        def run_form():
            ttk_module.Button.call_args_list[-1].kwargs["command"]()

        root.mainloop.side_effect = run_form
        tk_module = ModuleType("tkinter")
        tk_module.Tk = mock.Mock(return_value=root)
        tk_module.Canvas = mock.Mock(return_value=mock.MagicMock())
        tk_module.StringVar = mock.Mock(return_value=mock.MagicMock())
        tk_module.BooleanVar = mock.Mock(return_value=mock.MagicMock())
        tk_module.Text = mock.Mock(return_value=text_widget)
        tk_module.TclError = type("TclError", (Exception,), {})
        tk_module.ttk = ttk_module
        tk_module.filedialog = ModuleType("tkinter.filedialog")

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "tkinter": tk_module,
                    "tkinter.ttk": ttk_module,
                    "tkinter.filedialog": tk_module.filedialog,
                },
            ),
            mock.patch("ai_guardian.ui.display._ensure_tcl_library"),
            mock.patch("ai_guardian.tray.sandbox_dialog._place_window_on_screen"),
        ):
            result = _show_tkinter_form(
                "Apply OpenShell policy",
                "Review policy",
                [
                    {
                        "name": "policy_yaml",
                        "label": "Complete policy",
                        "type": "textarea",
                        "default": "version: 1",
                    }
                ],
                submit_label="Replace policy",
            )

        assert result == {"policy_yaml": "version: 1\nnetwork_policies: {}"}
        assert root.bind.call_args_list[-1].args[0] == "<Control-Return>"
        assert ttk_module.Button.call_args_list[-1].kwargs["text"] == "Replace policy"

    def test_confirmation_returns_false_when_ui_is_headless(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_confirmation

        with mock.patch(
            "ai_guardian.ui.display.select_ui_provider", return_value="headless"
        ):
            assert show_sandbox_confirmation("ag-test", "container") is False

    def test_confirmation_isolated_in_subprocess_when_tkinter_is_available(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_confirmation

        with (
            mock.patch("ai_guardian.ui.display._tkinter_available", return_value=True),
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="tkinter"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_tkinter_confirmation_subprocess",
                return_value=True,
            ) as show_confirmation,
        ):
            result = show_sandbox_confirmation("ag-test", "openshell")

        assert result is True
        show_confirmation.assert_called_once_with(
            "Delete AI Guardian sandbox",
            "Permanently delete sandbox 'ag-test' (openshell)?\n\n"
            "The runtime sandbox will be removed. Saved host configuration snapshots are kept.",
            "ag-test",
        )

    def test_upload_confirmation_returns_false_when_ui_is_headless(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_upload_confirmation

        with mock.patch(
            "ai_guardian.ui.display.select_ui_provider", return_value="headless"
        ):
            assert show_sandbox_upload_confirmation("Upload summary") is False

    def test_upload_confirmation_isolated_in_subprocess_when_tkinter_is_available(
        self,
    ):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_upload_confirmation

        with (
            mock.patch("ai_guardian.ui.display._tkinter_available", return_value=True),
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="tkinter"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_tkinter_upload_confirmation_subprocess",
                return_value=True,
            ) as show_confirmation,
        ):
            assert show_sandbox_upload_confirmation("Upload summary") is True

        show_confirmation.assert_called_once_with(
            "Confirm OpenShell repository upload",
            "Upload summary",
            error_lines=(),
        )

    def test_policy_confirmation_returns_false_when_ui_is_headless(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_policy_confirmation

        with mock.patch(
            "ai_guardian.ui.display.select_ui_provider", return_value="headless"
        ):
            assert show_sandbox_policy_confirmation("Replace policy?") is False

    def test_policy_confirmation_uses_explicit_replace_label(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_policy_confirmation

        with (
            mock.patch("ai_guardian.ui.display._tkinter_available", return_value=True),
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="tkinter"
            ) as select_provider,
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_tkinter_upload_confirmation_subprocess",
                return_value=True,
            ) as show_confirmation,
        ):
            assert show_sandbox_policy_confirmation("Replace policy?") is True

        show_confirmation.assert_called_once_with(
            "Apply OpenShell policy",
            "Replace policy?",
            confirm_label="Replace policy",
        )
        select_provider.assert_called_once_with("form", screen_bounds=None)

    def test_form_uses_nicegui_when_selected_without_tkinter(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with (
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="nicegui"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_nicegui_form",
                return_value={"runtime": "openshell"},
            ) as show_form,
        ):
            result = show_sandbox_form("Title", "Message", [])

        assert result == {"runtime": "openshell"}
        show_form.assert_called_once_with("Title", "Message", [], screen_bounds=None)

    def test_nicegui_form_receives_custom_submit_label(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with (
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="nicegui"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_nicegui_form",
                return_value={"policy_yaml": "version: 1"},
            ) as show_form,
        ):
            result = show_sandbox_form(
                "Apply OpenShell policy",
                "Review policy",
                [{"name": "policy_yaml", "type": "textarea"}],
                submit_label="Replace policy",
            )

        assert result == {"policy_yaml": "version: 1"}
        show_form.assert_called_once_with(
            "Apply OpenShell policy",
            "Review policy",
            [{"name": "policy_yaml", "type": "textarea"}],
            screen_bounds=None,
            submit_label="Replace policy",
        )

    def test_macos_native_upload_confirmation_works_without_tkinter(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_upload_confirmation

        with (
            mock.patch(
                "ai_guardian.ui.display.select_ui_provider", return_value="native"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_native_confirmation",
                return_value=True,
            ) as confirm,
        ):
            result = show_sandbox_upload_confirmation("Upload summary")

        assert result is True
        confirm.assert_called_once_with(
            "Confirm OpenShell repository upload",
            "Upload summary",
            "Continue upload",
        )

    def test_headless_form_is_cancelled_without_provider_lookup(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with mock.patch(
            "ai_guardian.ui.display.select_ui_provider", return_value="headless"
        ):
            assert show_sandbox_form("Title", "Message", []) is None

    def test_native_macos_upload_confirmation_parses_button_result(self):
        from ai_guardian.tray.sandbox_dialog import _show_native_confirmation

        result = SimpleNamespace(
            returncode=0,
            stdout="button returned: Continue upload\n",
        )
        with (
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.platform.system", return_value="Darwin"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.subprocess.run", return_value=result
            ) as run,
        ):
            assert _show_native_confirmation("Title", "Message", "Continue upload")

        assert run.call_args.args[0][0] == "osascript"
        assert "display dialog" in run.call_args.args[0][2]

    def test_native_macos_delete_confirmation_requires_exact_name(self):
        from ai_guardian.tray.sandbox_dialog import _show_native_confirmation

        result = SimpleNamespace(
            returncode=0,
            stdout="button returned: Delete sandbox, text returned: ag-test\n",
        )
        with (
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.platform.system", return_value="Darwin"
            ),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog.subprocess.run", return_value=result
            ),
        ):
            assert _show_native_confirmation(
                "Title",
                "Message",
                "Delete sandbox",
                expected_text="ag-test",
            )
