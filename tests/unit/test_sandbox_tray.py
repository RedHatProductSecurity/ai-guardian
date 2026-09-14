"""Tests for sandbox actions exposed by the system tray."""

import os
from types import SimpleNamespace
from unittest import mock

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.ide_registry import SUPPORTED_CLI_IDE_TYPES
from ai_guardian.tray.app import DaemonTray
from ai_guardian.tray.menu import (
    launch_sandbox_command,
    launch_sandbox_create_command,
)
from ai_guardian.tray.menu_builder import TrayMenuBuilder


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
            mock.patch.object(tray._menu, "_start_sandbox_command") as start,
        ):
            item = tray._menu._build_sandbox_start_menu_items()[0]
            item.action.items[0].action(None, None)

        start.assert_called_once_with(
            target,
            "start",
            ["stopped-container"],
        )

    def test_create_form_maps_restore_and_runtime_options(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "name": "ag-test",
            "agent": "",
            "cli": "claude",
            "repo": "/tmp/repo",
            "config_dir": "",
            "image": "localhost/ai-guardian:openshell",
            "model": "claude-sonnet-4-6",
            "profile": "",
            "policies": "/tmp/read-only.yaml, /tmp/network.yaml",
            "providers": "ai-guardian-claude, ai-guardian-github",
            "environment": "DEBUG=1, TERM=xterm",
            "labels": "team=security, owner=ai",
            "config_source": "Latest saved snapshot",
            "port": "",
        }
        with (
            mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create,
            mock.patch(
                "ai_guardian.tray.menu_builder.tray_notifications.show_notification"
            ),
        ):
            tray._menu._complete_sandbox_create_form(values)

        create.assert_called_once()
        args = create.call_args.args[0]
        assert args.runtime == "openshell"
        assert args.name == "ag-test"
        assert args.cli == "claude"
        assert args.opencode_agent is None
        assert args.repo == "/tmp/repo"
        assert args.config_dir is None
        assert args.image == "localhost/ai-guardian:openshell"
        assert args.model == "claude-sonnet-4-6"
        assert args.policy == ["/tmp/read-only.yaml", "/tmp/network.yaml"]
        assert args.provider == ["ai-guardian-claude", "ai-guardian-github"]
        assert args.environment == ["DEBUG=1", "TERM=xterm"]
        assert args.label == ["team=security", "owner=ai"]
        assert args.restore_config == "latest"
        assert args.port is None
        assert create.call_args.kwargs["interactive"] is False
        assert isinstance(create.call_args.kwargs["output"], list)

    def test_create_form_shows_runtime_log_when_direct_create_fails(self):
        tray = _make_tray([])

        def fail_create(_args, *, interactive, output):
            assert interactive is False
            output.append("runtime failed\n")
            return 1

        with (
            mock.patch("ai_guardian.sandbox.create_sandbox", side_effect=fail_create),
            mock.patch("ai_guardian.tray.sandbox_dialog.show_sandbox_log") as show_log,
        ):
            tray._menu._complete_sandbox_create_form(
                {"runtime": "container", "name": "ag-test"}
            )

        show_log.assert_called_once_with(
            "Sandbox creation failed",
            "Unable to create sandbox 'ag-test'.",
            "runtime failed",
        )

    def test_create_form_maps_opencode_cli_and_agent(self):
        tray = _make_tray([])
        values = {
            "runtime": "openshell",
            "name": "ag-opencode",
            "cli": "opencode",
            "agent": "build",
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
        with mock.patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create:
            tray._menu._complete_sandbox_create_form(values)

        args = create.call_args.args[0]
        assert args.cli == "opencode"
        assert args.opencode_agent == "build"

    def test_create_form_exposes_policy_file_field(self):
        tray = _make_tray([])
        home = os.path.expanduser("~")

        with mock.patch.dict(
            os.environ,
            {"HOME": home, "USERPROFILE": home},
            clear=True,
        ):
            fields = tray._menu._sandbox_create_fields()

        cli_field = next(field for field in fields if field["name"] == "cli")
        assert cli_field["type"] == "choice"
        assert cli_field["choices"] == SUPPORTED_CLI_IDE_TYPES
        assert cli_field["default"] == "codex"
        assert cli_field["required"] is True

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

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CLI": "opencode",
                "AI_GUARDIAN_OPENCODE_AGENT": "build",
            },
            clear=True,
        ):
            fields = tray._menu._sandbox_create_fields()

        agent_field = next(field for field in fields if field["name"] == "agent")
        assert agent_field["default"] == "build"

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
        provider_field = next(field for field in fields if field["name"] == "providers")
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

        config_dir_field = next(
            field for field in fields if field["name"] == "config_dir"
        )
        assert config_dir_field["type"] == "directory"

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

    def test_path_browser_starts_at_current_directory_value(self, tmp_path):
        from ai_guardian.tray.sandbox_dialog import _browse_initialdir

        repo = tmp_path / "repo"
        repo.mkdir()

        assert _browse_initialdir(str(repo)) == str(repo)
        assert _browse_initialdir(str(repo / "new-file")) == str(repo)
        assert _browse_initialdir("") is None

    def test_local_image_choices_use_ai_guardian_image_label(self):
        from ai_guardian.tray.sandbox_dialog import _local_image_choices

        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "localhost/ai-guardian-openshell:dev\n"
                "<none>:<none>\n"
                "localhost/ai-guardian:dev\n"
                "localhost/ai-guardian-openshell:dev\n"
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
                "localhost/ai-guardian-openshell:dev",
                "localhost/ai-guardian:dev",
            ]

        run.assert_called_once_with(
            [
                "podman",
                "image",
                "ls",
                "--filter",
                "label=ai-guardian.support-image=true",
                "--format",
                "{{.Repository}}:{{.Tag}}",
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
    def test_log_copy_uses_system_clipboard(self):
        from ai_guardian.tray.sandbox_dialog import _copy_sandbox_log

        with mock.patch(
            "ai_guardian.tui.app.copy_to_system_clipboard",
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

    def test_form_returns_none_when_tkinter_is_unavailable(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=False
        ):
            assert show_sandbox_form("Title", "Message", []) is None

    def test_form_isolated_in_subprocess_when_tkinter_is_available(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_form

        with (
            mock.patch("ai_guardian.tui.display._tkinter_available", return_value=True),
            mock.patch(
                "ai_guardian.tray.sandbox_dialog._show_tkinter_form_subprocess",
                return_value={"runtime": "container"},
            ) as show_form,
        ):
            result = show_sandbox_form("Title", "Message", [])

        assert result == {"runtime": "container"}
        show_form.assert_called_once_with("Title", "Message", [])

    def test_confirmation_returns_false_when_tkinter_is_unavailable(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_confirmation

        with mock.patch(
            "ai_guardian.tui.display._tkinter_available", return_value=False
        ):
            assert show_sandbox_confirmation("ag-test", "container") is False

    def test_confirmation_isolated_in_subprocess_when_tkinter_is_available(self):
        from ai_guardian.tray.sandbox_dialog import show_sandbox_confirmation

        with (
            mock.patch("ai_guardian.tui.display._tkinter_available", return_value=True),
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
