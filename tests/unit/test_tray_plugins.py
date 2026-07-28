"""Tests for tray menu plugin loader and command utilities."""

import json
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

from ai_guardian.tray.plugins import (
    Plugin,
    PluginItem,
    PluginParam,
    check_circular_imports,
    dict_to_plugins,
    filter_plugins_by_tags,
    find_project_plugins_dir,
    load_merged_plugins,
    load_plugins,
    plugins_to_dict,
    resolve_command,
    show_dialog,
    substitute_params,
    substitute_target_vars,
    validate_param_value,
    wrap_for_target,
)


class TestLoadPlugins:
    def test_loads_single_plugin_file(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "TestPlugin",
                    "items": [
                        {
                            "label": "Hello",
                            "command": "echo hello",
                            "type": "background",
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert plugins[0].name == "TestPlugin"
        assert len(plugins[0].items) == 1
        assert plugins[0].items[0].label == "Hello"
        assert plugins[0].items[0].command == "echo hello"
        assert plugins[0].items[0].type == "background"

    def test_loads_multiple_plugin_files(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        for i in range(3):
            (plugins_dir / f"plugin{i}.json").write_text(
                json.dumps(
                    {
                        "name": f"Plugin{i}",
                        "items": [{"label": "Action", "command": f"cmd{i}"}],
                    }
                )
            )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 3

    def test_skips_malformed_json(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "bad.json").write_text("not valid json {{{")
        (plugins_dir / "good.json").write_text(
            json.dumps({"name": "Good", "items": [{"label": "Ok", "command": "true"}]})
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert plugins[0].name == "Good"

    def test_skips_plugin_missing_name(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "noname.json").write_text(
            json.dumps({"items": [{"label": "X", "command": "y"}]})
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 0

    def test_skips_plugin_missing_items(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "noitems.json").write_text(json.dumps({"name": "NoItems"}))
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 0

    def test_returns_empty_when_dir_missing(self, tmp_path):
        plugins = load_plugins(tmp_path / "nonexistent")
        assert plugins == []

    def test_returns_empty_when_dir_empty(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        plugins = load_plugins(plugins_dir)
        assert plugins == []

    def test_validates_item_requires_label(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {"command": "echo missing label"},
                        {"label": "Good", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert len(plugins[0].items) == 1
        assert plugins[0].items[0].label == "Good"

    def test_validates_item_requires_command(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {"label": "No Command"},
                        {"label": "Good", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins[0].items) == 1
        assert plugins[0].items[0].label == "Good"

    def test_parses_params_correctly(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Deploy",
                            "command": "deploy {tray.branch}",
                            "type": "terminal",
                            "params": [
                                {
                                    "name": "branch",
                                    "hint": "Git branch",
                                    "default": "main",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        item = plugins[0].items[0]
        assert len(item.params) == 1
        assert item.params[0].name == "branch"
        assert item.params[0].hint == "Git branch"
        assert item.params[0].default == "main"
        assert item.params[0].options is None

    def test_parses_params_with_options(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Deploy",
                            "command": "deploy --env {env}",
                            "params": [
                                {"name": "env", "options": ["dev", "staging", "prod"]}
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        param = plugins[0].items[0].params[0]
        assert param.name == "env"
        assert param.options == ["dev", "staging", "prod"]

    def test_ignores_non_json_files(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "readme.txt").write_text("not a plugin")
        (plugins_dir / "good.json").write_text(
            json.dumps({"name": "Good", "items": [{"label": "Ok", "command": "true"}]})
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1

    def test_default_type_is_terminal(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps({"name": "Test", "items": [{"label": "Run", "command": "bash"}]})
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].type == "terminal"

    def test_modal_type_accepted(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Version",
                            "command": "ai-guardian --version",
                            "type": "modal",
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].type == "modal"

    def test_invalid_type_defaults_to_terminal(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [{"label": "Run", "command": "bash", "type": "bogus"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].type == "terminal"

    def test_command_as_platform_map(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Shell",
                            "command": {
                                "darwin": "open -a Terminal",
                                "default": "bash",
                            },
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert isinstance(plugins[0].items[0].command, dict)

    def test_uses_default_dir_when_none(self):
        with mock.patch("ai_guardian.daemon.get_tray_plugins_dir") as m:
            m.return_value = mock.MagicMock()
            m.return_value.is_dir.return_value = False
            plugins = load_plugins()
            m.assert_called_once()
            assert plugins == []

    def test_skips_param_missing_name(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Deploy",
                            "command": "deploy",
                            "params": [
                                {"hint": "no name field"},
                                {"name": "good", "hint": "valid"},
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins[0].items[0].params) == 1
        assert plugins[0].items[0].params[0].name == "good"

    def test_parses_run_on_target_true(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Doctor",
                            "command": "ai-guardian doctor",
                            "run_on_target": True,
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].run_on_target is True

    def test_parses_run_on_target_false(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Logs",
                            "command": "podman logs {container_id}",
                            "run_on_target": False,
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].run_on_target is False

    def test_default_run_on_target_is_false(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {"name": "Test", "items": [{"label": "Run", "command": "echo hi"}]}
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].run_on_target is False


class TestResolveCommand:
    def test_string_command_returned_as_is(self):
        assert resolve_command("echo hello") == "echo hello"

    @pytest.mark.parametrize(
        "platform_name, cmd_map, expected",
        [
            ("Darwin", {"darwin": "open .", "linux": "xdg-open ."}, "open ."),
            ("Linux", {"darwin": "open .", "linux": "xdg-open ."}, "xdg-open ."),
            ("Windows", {"windows": "start .", "linux": "xdg-open ."}, "start ."),
            ("Linux", {"darwin": "open .", "default": "xdg-open ."}, "xdg-open ."),
            ("Linux", {"darwin": "open .", "windows": "start ."}, None),
            ("Darwin", {"darwin": "open ."}, "open ."),
            ("Darwin", {"darwin": "", "default": "fallback"}, ""),
        ],
        ids=[
            "darwin_on_macos",
            "linux",
            "windows",
            "falls_back_to_default",
            "no_match_returns_none",
            "platform_key_is_lowercase",
            "empty_string_not_falsy_fallthrough",
        ],
    )
    def test_platform_map_resolution(self, platform_name, cmd_map, expected):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = platform_name
            result = resolve_command(cmd_map)
            assert result == expected

    def test_platform_map_returns_none_when_empty_dict(self):
        assert resolve_command({}) is None

    def test_non_dict_non_string_returns_none(self):
        assert resolve_command(42) is None


class TestSubstituteParams:
    @pytest.mark.parametrize(
        "template, params, expected",
        [
            ("echo {tray.msg}", {"msg": "hello"}, "echo hello"),
            (
                "deploy --branch {tray.branch} --env {tray.env}",
                {"branch": "main", "env": "prod"},
                "deploy --branch main --env prod",
            ),
            ("echo {tray.missing}", {}, "echo "),
            ("echo hello", {}, "echo hello"),
            ("echo {tray.a}", {"a": "1", "b": "2"}, "echo 1"),
            ("{tray.a} and {tray.b}", {"a": "yes"}, "yes and "),
            ("echo {json} and {tray.name}", {"name": "hi"}, "echo {json} and hi"),
            ("echo $HOME {tray.x}", {"x": "val"}, "echo $HOME val"),
            (
                "cd {tray.working_dir} && make",
                {"working_dir": "/home/user/project"},
                "cd /home/user/project && make",
            ),
        ],
        ids=[
            "single_param",
            "multiple_params",
            "missing_param_replaced_with_empty",
            "no_params_returns_original",
            "extra_values_ignored",
            "partial_params_fills_known_clears_unknown",
            "non_tray_braces_left_untouched",
            "shell_variables_left_untouched",
            "tray_working_dir_substituted",
        ],
    )
    def test_substitute_params(self, template, params, expected):
        assert substitute_params(template, params) == expected


class TestSubstituteTargetVars:
    """Tests for target variable substitution in plugin commands."""

    def _make_target(self, **kwargs):
        from ai_guardian.daemon.discovery import DaemonTarget

        defaults = dict(
            name="test-daemon",
            runtime="container",
            host="192.168.1.10",
            port=63152,
            container_id="a1b2c3d4e5f6a1b2",
            container_engine="podman",
            pod_name="guardian-pod-1",
            namespace="ai-guardian",
        )
        defaults.update(kwargs)
        return DaemonTarget(**defaults)

    @pytest.mark.parametrize(
        "template, target_overrides, expected",
        [
            ("podman logs {container_id}", {}, "podman logs a1b2c3d4e5f6a1b2"),
            (
                "curl http://{host}:{port}/api/health",
                {},
                "curl http://192.168.1.10:63152/api/health",
            ),
            ("echo {name}", {}, "echo test-daemon"),
            ("{container_engine} ps", {"container_engine": "docker"}, "docker ps"),
            (
                "kubectl logs {pod_name} -n {namespace}",
                {},
                "kubectl logs guardian-pod-1 -n ai-guardian",
            ),
            ("logs {container_id}", {"container_id": None}, "logs "),
            (
                "echo {json} {tray.x} {name}",
                {},
                "echo {json} {tray.x} test-daemon",
            ),
            (
                "{container_id} and {container_id}",
                {},
                "a1b2c3d4e5f6a1b2 and a1b2c3d4e5f6a1b2",
            ),
            (":{port}", {"port": 8080}, ":8080"),
            ("echo hello world", {}, "echo hello world"),
            (
                "cd {working_dir} && make build",
                {"working_dir": "/home/user/project"},
                "cd /home/user/project && make build",
            ),
            ("cd {working_dir}", {"working_dir": None}, "cd "),
        ],
        ids=[
            "container_id",
            "host_and_port",
            "name",
            "container_engine",
            "pod_name_and_namespace",
            "none_field_becomes_empty",
            "non_target_braces_left_untouched",
            "multiple_same_variable",
            "port_converted_to_string",
            "no_placeholders_returns_original",
            "working_dir",
            "working_dir_none_becomes_empty",
        ],
    )
    def test_substitute_target_vars(self, template, target_overrides, expected):
        target = self._make_target(**target_overrides)
        assert substitute_target_vars(template, target) == expected

    def test_no_target_returns_template_unchanged(self):
        result = substitute_target_vars("echo {container_id}", None)
        assert result == "echo {container_id}"


class TestNeedsShell:
    """Tests for _needs_shell shell-operator detection."""

    @pytest.mark.parametrize(
        "command, expected",
        [
            ("echo hello", False),
            ("uname -a && lsb_release -a", True),
            ("ps aux | grep python", True),
            ("echo hello; echo world", True),
            ("ai-guardian doctor > /tmp/report.txt", True),
            ("echo line >> /tmp/log.txt", True),
            ("cmd1 || cmd2", True),
            ("wc -l < input.txt", True),
            ("cat << EOF", True),
            ("ai-guardian --version", False),
        ],
        ids=[
            "simple_command",
            "double_ampersand",
            "pipe",
            "semicolon",
            "redirect_out",
            "redirect_append",
            "double_pipe",
            "redirect_in",
            "heredoc",
            "no_operators",
        ],
    )
    def test_needs_shell(self, command, expected):
        from ai_guardian.tray.plugins import _needs_shell

        assert _needs_shell(command) is expected


class TestWrapForTarget:
    """Tests for run_on_target command wrapping."""

    def _make_target(self, **kwargs):
        from ai_guardian.daemon.discovery import DaemonTarget

        defaults = dict(name="test", runtime="local")
        defaults.update(kwargs)
        return DaemonTarget(**defaults)

    def test_local_runtime_no_wrapping(self):
        target = self._make_target(runtime="local")
        result = wrap_for_target(["ai-guardian", "doctor"], target)
        assert result == ["ai-guardian", "doctor"]

    def test_container_runtime_wraps_with_engine_exec(self):
        target = self._make_target(
            runtime="container",
            container_id="a1b2c3d4e5f6a1b2",
            container_engine="podman",
        )
        result = wrap_for_target(["ai-guardian", "doctor"], target)
        assert result == [
            "podman",
            "exec",
            "-it",
            "a1b2c3d4e5f6a1b2",
            "ai-guardian",
            "doctor",
        ]

    def test_container_runtime_docker_engine(self):
        target = self._make_target(
            runtime="container",
            container_id="a1b2c3d4e5f6a1b2",
            container_engine="docker",
        )
        result = wrap_for_target(["ai-guardian", "doctor"], target)
        assert result[0] == "docker"

    def test_container_runtime_defaults_to_podman(self):
        target = self._make_target(
            runtime="container",
            container_id="a1b2c3d4e5f6a1b2",
            container_engine=None,
        )
        result = wrap_for_target(["ai-guardian", "doctor"], target)
        assert result[0] == "podman"

    def test_container_runtime_non_interactive(self):
        target = self._make_target(
            runtime="container",
            container_id="a1b2c3d4e5f6a1b2",
            container_engine="podman",
        )
        result = wrap_for_target(
            ["ai-guardian", "doctor"],
            target,
            interactive=False,
        )
        assert "-it" not in result
        assert result == [
            "podman",
            "exec",
            "a1b2c3d4e5f6a1b2",
            "ai-guardian",
            "doctor",
        ]

    def test_container_runtime_invalid_id_falls_back_to_local(self):
        target = self._make_target(
            runtime="container",
            container_id=".invalid",
        )
        cmd = ["ai-guardian", "doctor"]
        result = wrap_for_target(cmd, target)
        assert result == cmd

    def test_container_runtime_missing_id_falls_back_to_local(self):
        target = self._make_target(
            runtime="container",
            container_id=None,
        )
        cmd = ["ai-guardian", "doctor"]
        result = wrap_for_target(cmd, target)
        assert result == cmd

    def test_kubernetes_runtime_wraps_with_kube_cli(self):
        target = self._make_target(
            runtime="kubernetes",
            pod_name="guardian-pod-1",
            namespace="ai-guardian",
        )
        with mock.patch("shutil.which", return_value=None):
            result = wrap_for_target(["ai-guardian", "doctor"], target)
        assert result == [
            "kubectl",
            "exec",
            "-it",
            "guardian-pod-1",
            "-n",
            "ai-guardian",
            "--",
            "ai-guardian",
            "doctor",
        ]

    def test_kubernetes_runtime_prefers_oc(self):
        target = self._make_target(
            runtime="kubernetes",
            pod_name="guardian-pod-1",
            namespace="ai-guardian",
        )
        with mock.patch("shutil.which", return_value="/usr/bin/oc"):
            result = wrap_for_target(["ai-guardian", "doctor"], target)
        assert result[0] == "oc"

    def test_kubernetes_default_namespace(self):
        target = self._make_target(
            runtime="kubernetes",
            pod_name="guardian-pod-1",
            namespace=None,
        )
        with mock.patch("shutil.which", return_value=None):
            result = wrap_for_target(["ai-guardian", "doctor"], target)
        assert "-n" in result
        ns_idx = result.index("-n")
        assert result[ns_idx + 1] == "default"

    def test_kubernetes_missing_pod_falls_back_to_local(self):
        target = self._make_target(
            runtime="kubernetes",
            pod_name=None,
        )
        cmd = ["ai-guardian", "doctor"]
        result = wrap_for_target(cmd, target)
        assert result == cmd

    def test_kubernetes_non_interactive(self):
        target = self._make_target(
            runtime="kubernetes",
            pod_name="guardian-pod-1",
            namespace="default",
        )
        with mock.patch("shutil.which", return_value=None):
            result = wrap_for_target(
                ["ai-guardian", "doctor"],
                target,
                interactive=False,
            )
        assert "-it" not in result

    def test_manual_runtime_runs_locally(self):
        target = self._make_target(runtime="manual")
        cmd = ["ai-guardian", "doctor"]
        result = wrap_for_target(cmd, target)
        assert result == cmd

    def test_unknown_runtime_runs_locally(self):
        target = self._make_target(runtime="unknown")
        cmd = ["ai-guardian", "doctor"]
        result = wrap_for_target(cmd, target)
        assert result == cmd


class TestPluginsToDict:
    def test_serializes_simple_plugin(self):
        plugins = [
            Plugin(
                name="Test",
                items=[PluginItem(label="Hello", command="echo hi", type="background")],
            )
        ]
        result = plugins_to_dict(plugins)
        assert result == {
            "plugins": [
                {
                    "name": "Test",
                    "items": [
                        {"label": "Hello", "command": "echo hi", "type": "background"}
                    ],
                }
            ]
        }

    def test_serializes_plugin_with_params(self):
        plugins = [
            Plugin(
                name="Deploy",
                items=[
                    PluginItem(
                        label="Go",
                        command="deploy {tray.env}",
                        type="terminal",
                        params=[
                            PluginParam(
                                name="env",
                                hint="Environment",
                                default="dev",
                                options=["dev", "prod"],
                            )
                        ],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        item = result["plugins"][0]["items"][0]
        assert item["params"] == [
            {
                "name": "env",
                "hint": "Environment",
                "default": "dev",
                "options": ["dev", "prod"],
            }
        ]

    def test_serializes_empty_list(self):
        result = plugins_to_dict([])
        assert result == {"plugins": []}

    def test_items_without_params_have_no_params_key(self):
        plugins = [Plugin(name="Test", items=[PluginItem(label="Run", command="bash")])]
        result = plugins_to_dict(plugins)
        assert "params" not in result["plugins"][0]["items"][0]

    def test_serializes_platform_map_command(self):
        cmd_map = {"darwin": "open .", "default": "xdg-open ."}
        plugins = [
            Plugin(name="Test", items=[PluginItem(label="Open", command=cmd_map)])
        ]
        result = plugins_to_dict(plugins)
        assert result["plugins"][0]["items"][0]["command"] == cmd_map

    def test_serializes_run_on_target_true(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Doctor",
                        command="ai-guardian doctor",
                        run_on_target=True,
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        assert result["plugins"][0]["items"][0]["run_on_target"] is True

    def test_serializes_run_on_target_false_omitted(self):
        plugins = [
            Plugin(
                name="Test", items=[PluginItem(label="Logs", command="podman logs abc")]
            )
        ]
        result = plugins_to_dict(plugins)
        assert "run_on_target" not in result["plugins"][0]["items"][0]

    def test_roundtrip_through_dict(self):
        original = [
            Plugin(
                name="Roundtrip",
                items=[
                    PluginItem(label="Simple", command="echo 1", type="background"),
                    PluginItem(
                        label="Params",
                        command="deploy {tray.env}",
                        type="terminal",
                        params=[PluginParam(name="env", hint="Env", default="dev")],
                    ),
                ],
            )
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert len(restored) == 1
        assert restored[0].name == "Roundtrip"
        assert len(restored[0].items) == 2
        assert restored[0].items[0].label == "Simple"
        assert restored[0].items[1].params[0].name == "env"

    def test_roundtrip_preserves_run_on_target(self):
        original = [
            Plugin(
                name="Roundtrip",
                items=[
                    PluginItem(
                        label="Doctor",
                        command="ai-guardian doctor",
                        run_on_target=True,
                    ),
                    PluginItem(label="Logs", command="podman logs abc"),
                ],
            )
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert restored[0].items[0].run_on_target is True
        assert restored[0].items[1].run_on_target is False


class TestSendNotification:
    def test_macos_uses_osascript(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run") as mock_run:
                from ai_guardian.tray.plugins import send_notification

                result = send_notification("Title", "Hello world")
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args[0] == "osascript"

    def test_linux_uses_notify_send(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Linux"
            with mock.patch("subprocess.run") as mock_run:
                from ai_guardian.tray.plugins import send_notification

                result = send_notification("Title", "Hello")
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args[0] == "notify-send"

    def test_returns_false_on_unknown_platform(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "FreeBSD"
            from ai_guardian.tray.plugins import send_notification

            assert send_notification("T", "M") is False

    def test_returns_false_on_error(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run", side_effect=FileNotFoundError):
                from ai_guardian.tray.plugins import send_notification

                assert send_notification("T", "M") is False

    def test_escapes_quotes_in_message(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run") as mock_run:
                from ai_guardian.tray.plugins import send_notification

                send_notification("Title", 'He said "hello"')
                script = mock_run.call_args[0][0][2]
                assert '\\"' in script

    def test_linux_includes_icon_flag(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Linux"
            with mock.patch(
                "ai_guardian.tray.plugins._find_icon",
                return_value="/path/to/icon.png",
            ):
                with mock.patch("subprocess.run") as mock_run:
                    from ai_guardian.tray.plugins import send_notification

                    result = send_notification("Title", "Hello")
                    assert result is True
                    args = mock_run.call_args[0][0]
                    assert "--icon" in args
                    assert "/path/to/icon.png" in args

    def test_linux_no_icon_when_not_found(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Linux"
            with mock.patch("ai_guardian.tray.plugins._find_icon", return_value=""):
                with mock.patch("subprocess.run") as mock_run:
                    from ai_guardian.tray.plugins import send_notification

                    result = send_notification("Title", "Hello")
                    assert result is True
                    args = mock_run.call_args[0][0]
                    assert "--icon" not in args

    def test_windows_loads_custom_icon(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Windows"
            with mock.patch(
                "ai_guardian.tray.plugins._find_icon",
                return_value="C:\\icons\\shield.png",
            ):
                with mock.patch("subprocess.run") as mock_run:
                    from ai_guardian.tray.plugins import send_notification

                    result = send_notification("Title", "Hello")
                    assert result is True
                    ps_cmd = mock_run.call_args[0][0][2]
                    assert "Bitmap" in ps_cmd
                    assert "shield.png" in ps_cmd

    def test_windows_fallback_icon_when_not_found(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Windows"
            with mock.patch("ai_guardian.tray.plugins._find_icon", return_value=""):
                with mock.patch("subprocess.run") as mock_run:
                    from ai_guardian.tray.plugins import send_notification

                    result = send_notification("Title", "Hello")
                    assert result is True
                    ps_cmd = mock_run.call_args[0][0][2]
                    assert "SystemIcons" in ps_cmd
                    assert "Bitmap" not in ps_cmd


class TestCopyToClipboard:
    def test_macos_uses_pbcopy(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run") as mock_run:
                from ai_guardian.tray.plugins import copy_to_clipboard

                result = copy_to_clipboard("hello")
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args == ["pbcopy"]
                assert mock_run.call_args[1]["input"] == b"hello"

    def test_linux_uses_xclip(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Linux"
            with mock.patch("shutil.which", return_value="/usr/bin/xclip"):
                with mock.patch("subprocess.run") as mock_run:
                    from ai_guardian.tray.plugins import copy_to_clipboard

                    result = copy_to_clipboard("hello")
                    assert result is True
                    args = mock_run.call_args[0][0]
                    assert "xclip" in args[0]

    def test_linux_falls_back_to_xsel(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Linux"
            with mock.patch(
                "shutil.which",
                side_effect=lambda x: "/usr/bin/xsel" if x == "xsel" else None,
            ):
                with mock.patch("subprocess.run") as mock_run:
                    from ai_guardian.tray.plugins import copy_to_clipboard

                    result = copy_to_clipboard("hello")
                    assert result is True
                    args = mock_run.call_args[0][0]
                    assert "xsel" in args[0]

    def test_linux_returns_false_when_no_tool(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Linux"
            with mock.patch("shutil.which", return_value=None):
                from ai_guardian.tray.plugins import copy_to_clipboard

                assert copy_to_clipboard("hello") is False

    def test_returns_false_on_unknown_platform(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "FreeBSD"
            from ai_guardian.tray.plugins import copy_to_clipboard

            assert copy_to_clipboard("hello") is False

    def test_returns_false_on_error(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run", side_effect=OSError("broken")):
                from ai_guardian.tray.plugins import copy_to_clipboard

                assert copy_to_clipboard("hello") is False


class TestDictToPlugins:
    def test_deserializes_valid_data(self):
        data = {
            "plugins": [
                {"name": "Test", "items": [{"label": "Run", "command": "bash"}]}
            ]
        }
        plugins = dict_to_plugins(data)
        assert len(plugins) == 1
        assert plugins[0].name == "Test"

    def test_skips_invalid_entries(self):
        data = {
            "plugins": [
                {"name": "Good", "items": [{"label": "A", "command": "b"}]},
                {"invalid": "data"},
            ]
        }
        plugins = dict_to_plugins(data)
        assert len(plugins) == 1
        assert plugins[0].name == "Good"

    def test_returns_empty_for_missing_plugins_key(self):
        plugins = dict_to_plugins({})
        assert plugins == []

    def test_returns_empty_for_empty_plugins(self):
        plugins = dict_to_plugins({"plugins": []})
        assert plugins == []


class TestShowDialog:
    def test_macos_uses_osascript(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run") as mock_run:
                result = show_dialog("Test Title", "Hello world")
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args[0] == "osascript"
                assert "display dialog" in args[2]

    def test_linux_uses_zenity(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Linux"
            with mock.patch("subprocess.run") as mock_run:
                result = show_dialog("Test Title", "Hello")
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args[0] == "zenity"

    def test_windows_uses_powershell(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Windows"
            with mock.patch("subprocess.run") as mock_run:
                result = show_dialog("Test Title", "Hello")
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert args[0] == "powershell"
                assert "MessageBox" in args[2]

    def test_returns_false_on_unknown_platform(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "FreeBSD"
            assert show_dialog("T", "M") is False

    def test_returns_false_on_error(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run", side_effect=FileNotFoundError):
                assert show_dialog("T", "M") is False

    def test_escapes_quotes_in_message(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run") as mock_run:
                show_dialog("Title", 'He said "hello"')
                script = mock_run.call_args[0][0][2]
                assert '\\"' in script

    def test_macos_includes_icon_when_found(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch(
                "ai_guardian.tray.plugins._find_icon",
                return_value="/path/to/icon.icns",
            ):
                with mock.patch("subprocess.run") as mock_run:
                    result = show_dialog("Title", "Hello")
                    assert result is True
                    script = mock_run.call_args[0][0][2]
                    assert "icon" in script.lower()

    def test_multiline_message_on_macos(self):
        with mock.patch("ai_guardian.tray.plugins.platform") as m:
            m.system.return_value = "Darwin"
            with mock.patch("subprocess.run") as mock_run:
                show_dialog("Title", "line1\nline2\nline3")
                script = mock_run.call_args[0][0][2]
                assert "return" in script


class TestPluginTags:
    def test_tags_parsed_from_json(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "tagged.json").write_text(
            json.dumps(
                {
                    "name": "Carbonite",
                    "tags": ["carbonite", "container"],
                    "items": [{"label": "Status", "command": "echo ok"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert plugins[0].tags == ["carbonite", "container"]

    def test_tags_missing_defaults_to_empty(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "untagged.json").write_text(
            json.dumps(
                {"name": "Generic", "items": [{"label": "Run", "command": "bash"}]}
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].tags == []

    def test_tags_invalid_type_ignored(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "badtag.json").write_text(
            json.dumps(
                {
                    "name": "Bad",
                    "tags": "not-a-list",
                    "items": [{"label": "Go", "command": "go"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].tags == []

    def test_tags_filters_non_string_entries(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "mixed.json").write_text(
            json.dumps(
                {
                    "name": "Mixed",
                    "tags": ["valid", 42, "", None, "also-valid"],
                    "items": [{"label": "Do", "command": "do"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].tags == ["valid", "also-valid"]

    def test_tags_included_in_serialization(self):
        plugins = [
            Plugin(
                name="Tagged",
                tags=["carbonite"],
                items=[PluginItem(label="Run", command="echo")],
            )
        ]
        result = plugins_to_dict(plugins)
        assert result["plugins"][0]["tags"] == ["carbonite"]

    def test_tags_omitted_when_empty(self):
        plugins = [
            Plugin(name="Untagged", items=[PluginItem(label="Run", command="echo")])
        ]
        result = plugins_to_dict(plugins)
        assert "tags" not in result["plugins"][0]

    def test_tags_roundtrip(self):
        original = [
            Plugin(
                name="Roundtrip",
                tags=["carbonite", "staging"],
                items=[PluginItem(label="Go", command="echo 1")],
            )
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert restored[0].tags == ["carbonite", "staging"]

    def test_tags_roundtrip_empty(self):
        original = [
            Plugin(name="Roundtrip", items=[PluginItem(label="Go", command="echo 1")])
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert restored[0].tags == []


class TestFilterPluginsByTags:
    def _make_plugin(self, name, tags=None):
        return Plugin(
            name=name,
            tags=tags or [],
            items=[PluginItem(label="Action", command="echo")],
        )

    def test_untagged_plugin_no_daemon_tags(self):
        plugins = [self._make_plugin("Generic")]
        assert filter_plugins_by_tags(plugins, None) == plugins
        assert filter_plugins_by_tags(plugins, []) == plugins

    def test_untagged_plugin_with_daemon_tags(self):
        plugins = [self._make_plugin("Generic")]
        assert filter_plugins_by_tags(plugins, ["carbonite"]) == plugins

    def test_tagged_plugin_matching_daemon(self):
        plugins = [self._make_plugin("Carbonite", ["carbonite"])]
        result = filter_plugins_by_tags(plugins, ["carbonite", "container"])
        assert len(result) == 1
        assert result[0].name == "Carbonite"

    def test_tagged_plugin_no_match(self):
        plugins = [self._make_plugin("Carbonite", ["carbonite"])]
        result = filter_plugins_by_tags(plugins, ["staging"])
        assert len(result) == 0

    def test_tagged_plugin_no_daemon_tags(self):
        plugins = [self._make_plugin("Carbonite", ["carbonite"])]
        assert filter_plugins_by_tags(plugins, None) == []
        assert filter_plugins_by_tags(plugins, []) == []

    def test_mixed_tagged_and_untagged(self):
        plugins = [
            self._make_plugin("Generic"),
            self._make_plugin("Carbonite", ["carbonite"]),
            self._make_plugin("Staging", ["staging"]),
        ]
        result = filter_plugins_by_tags(plugins, ["carbonite"])
        assert len(result) == 2
        assert result[0].name == "Generic"
        assert result[1].name == "Carbonite"

    def test_plugin_multiple_tags_one_matches(self):
        plugins = [self._make_plugin("Multi", ["carbonite", "staging"])]
        result = filter_plugins_by_tags(plugins, ["staging"])
        assert len(result) == 1

    def test_plugin_multiple_tags_none_match(self):
        plugins = [self._make_plugin("Multi", ["carbonite", "staging"])]
        result = filter_plugins_by_tags(plugins, ["production"])
        assert len(result) == 0

    def test_exact_string_match(self):
        plugins = [self._make_plugin("Carbon", ["carbonite"])]
        result = filter_plugins_by_tags(plugins, ["carbon"])
        assert len(result) == 0


class TestPluginScope:
    def test_scope_parsed_from_json(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "global.json").write_text(
            json.dumps(
                {
                    "name": "Quick Links",
                    "scope": "global",
                    "items": [{"label": "Docs", "command": "echo docs"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert plugins[0].scope == "global"

    def test_scope_daemon_explicit(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "daemon.json").write_text(
            json.dumps(
                {
                    "name": "Daemon Plugin",
                    "scope": "daemon",
                    "items": [{"label": "Run", "command": "echo"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].scope == "daemon"

    def test_scope_missing_defaults_to_daemon(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "noscope.json").write_text(
            json.dumps(
                {"name": "No Scope", "items": [{"label": "Run", "command": "echo"}]}
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].scope == "daemon"

    def test_scope_invalid_defaults_to_daemon(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "invalid.json").write_text(
            json.dumps(
                {
                    "name": "Invalid Scope",
                    "scope": "invalid_value",
                    "items": [{"label": "Run", "command": "echo"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].scope == "daemon"

    def test_scope_included_in_serialization(self):
        plugins = [
            Plugin(
                name="Global",
                scope="global",
                items=[PluginItem(label="Run", command="echo")],
            )
        ]
        result = plugins_to_dict(plugins)
        assert result["plugins"][0]["scope"] == "global"

    def test_scope_daemon_omitted_in_serialization(self):
        plugins = [
            Plugin(name="Daemon", items=[PluginItem(label="Run", command="echo")])
        ]
        result = plugins_to_dict(plugins)
        assert "scope" not in result["plugins"][0]

    def test_scope_roundtrip_global(self):
        original = [
            Plugin(
                name="Roundtrip",
                scope="global",
                items=[PluginItem(label="Go", command="echo 1")],
            )
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert restored[0].scope == "global"

    def test_scope_roundtrip_daemon(self):
        original = [
            Plugin(name="Roundtrip", items=[PluginItem(label="Go", command="echo 1")])
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert restored[0].scope == "daemon"

    def test_mixed_scopes_loaded(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "01-global.json").write_text(
            json.dumps(
                {
                    "name": "Global",
                    "scope": "global",
                    "items": [{"label": "Docs", "command": "echo docs"}],
                }
            )
        )
        (plugins_dir / "02-daemon.json").write_text(
            json.dumps(
                {
                    "name": "Daemon",
                    "items": [{"label": "Status", "command": "echo status"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 2
        global_plugins = [p for p in plugins if p.scope == "global"]
        daemon_plugins = [p for p in plugins if p.scope == "daemon"]
        assert len(global_plugins) == 1
        assert len(daemon_plugins) == 1


class TestParseParamTyped:
    """Tests for typed parameter parsing."""

    def test_default_type_is_string(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [{"name": "x", "hint": "val"}],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].params[0].type == "string"

    def test_type_int_parsed(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [
                                {"name": "count", "type": "int", "min": 1, "max": 10}
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        p = plugins[0].items[0].params[0]
        assert p.type == "int"
        assert p.min == 1.0
        assert p.max == 10.0

    def test_type_boolean_parsed(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [
                                {"name": "flag", "type": "boolean", "default": "true"}
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        p = plugins[0].items[0].params[0]
        assert p.type == "boolean"
        assert p.default == "true"

    def test_options_without_type_infers_choice(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [{"name": "env", "options": ["dev", "prod"]}],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].params[0].type == "choice"

    def test_options_with_explicit_type_uses_type(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [
                                {
                                    "name": "tag",
                                    "type": "combobox",
                                    "options": ["latest", "stable"],
                                }
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].params[0].type == "combobox"

    def test_type_path_file_parsed(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [
                                {
                                    "name": "file",
                                    "type": "path-file",
                                    "hint": "Pick a file",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        p = plugins[0].items[0].params[0]
        assert p.type == "path-file"
        assert p.hint == "Pick a file"

    def test_type_path_dir_parsed(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [
                                {"name": "dir", "type": "path-dir", "default": "."}
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        p = plugins[0].items[0].params[0]
        assert p.type == "path-dir"
        assert p.default == "."

    def test_invalid_type_defaults_to_string(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [{"name": "x", "type": "bogus"}],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].params[0].type == "string"

    def test_required_false_parsed(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [{"name": "tag", "required": False}],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].params[0].required is False

    def test_required_default_is_true(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {"label": "Run", "command": "cmd", "params": [{"name": "x"}]}
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].params[0].required is True

    def test_pattern_parsed(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [{"name": "branch", "pattern": "^[a-z]+$"}],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].params[0].pattern == "^[a-z]+$"

    def test_invalid_min_max_ignored(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Test",
                    "items": [
                        {
                            "label": "Run",
                            "command": "cmd",
                            "params": [
                                {
                                    "name": "x",
                                    "type": "int",
                                    "min": "not-a-number",
                                    "max": None,
                                }
                            ],
                        }
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        p = plugins[0].items[0].params[0]
        assert p.min is None
        assert p.max is None


class TestValidateParamValue:
    """Tests for validate_param_value."""

    def test_required_empty_fails(self):
        p = PluginParam(name="x", required=True)
        ok, err = validate_param_value(p, "")
        assert not ok
        assert "required" in err

    def test_not_required_empty_passes(self):
        p = PluginParam(name="x", required=False)
        ok, err = validate_param_value(p, "")
        assert ok

    def test_string_no_validation(self):
        p = PluginParam(name="x", type="string")
        ok, _ = validate_param_value(p, "anything")
        assert ok

    def test_string_with_pattern_match(self):
        p = PluginParam(name="x", type="string", pattern="^[a-z]+$")
        ok, _ = validate_param_value(p, "abc")
        assert ok

    def test_string_with_pattern_no_match(self):
        p = PluginParam(name="x", type="string", pattern="^[a-z]+$")
        ok, err = validate_param_value(p, "ABC123")
        assert not ok
        assert "pattern" in err

    def test_int_valid(self):
        p = PluginParam(name="n", type="int")
        ok, _ = validate_param_value(p, "42")
        assert ok

    def test_int_invalid(self):
        p = PluginParam(name="n", type="int")
        ok, err = validate_param_value(p, "abc")
        assert not ok
        assert "integer" in err

    def test_int_below_min(self):
        p = PluginParam(name="n", type="int", min=5.0)
        ok, err = validate_param_value(p, "3")
        assert not ok
        assert ">=" in err

    def test_int_above_max(self):
        p = PluginParam(name="n", type="int", max=10.0)
        ok, err = validate_param_value(p, "15")
        assert not ok
        assert "<=" in err

    def test_int_within_bounds(self):
        p = PluginParam(name="n", type="int", min=1.0, max=10.0)
        ok, _ = validate_param_value(p, "5")
        assert ok

    def test_int_at_boundary(self):
        p = PluginParam(name="n", type="int", min=1.0, max=10.0)
        ok1, _ = validate_param_value(p, "1")
        ok2, _ = validate_param_value(p, "10")
        assert ok1 and ok2

    def test_number_valid_float(self):
        p = PluginParam(name="n", type="number")
        ok, _ = validate_param_value(p, "3.14")
        assert ok

    def test_number_invalid(self):
        p = PluginParam(name="n", type="number")
        ok, err = validate_param_value(p, "abc")
        assert not ok
        assert "number" in err

    def test_number_bounds(self):
        p = PluginParam(name="n", type="number", min=0.0, max=1.0)
        ok1, _ = validate_param_value(p, "0.5")
        ok2, err2 = validate_param_value(p, "1.5")
        assert ok1
        assert not ok2

    def test_boolean_true(self):
        p = PluginParam(name="f", type="boolean")
        ok, _ = validate_param_value(p, "true")
        assert ok

    def test_boolean_false(self):
        p = PluginParam(name="f", type="boolean")
        ok, _ = validate_param_value(p, "false")
        assert ok

    def test_boolean_case_insensitive(self):
        p = PluginParam(name="f", type="boolean")
        ok, _ = validate_param_value(p, "True")
        assert ok

    def test_boolean_invalid(self):
        p = PluginParam(name="f", type="boolean")
        ok, err = validate_param_value(p, "yes")
        assert not ok
        assert "true or false" in err

    def test_choice_valid(self):
        p = PluginParam(name="env", type="choice", options=["dev", "prod"])
        ok, _ = validate_param_value(p, "dev")
        assert ok

    def test_choice_invalid(self):
        p = PluginParam(name="env", type="choice", options=["dev", "prod"])
        ok, err = validate_param_value(p, "staging")
        assert not ok
        assert "one of" in err

    def test_combobox_accepts_any(self):
        p = PluginParam(name="tag", type="combobox", options=["latest", "stable"])
        ok, _ = validate_param_value(p, "custom-tag")
        assert ok

    def test_path_file_accepts_any_string(self):
        p = PluginParam(name="f", type="path-file")
        ok, _ = validate_param_value(p, "/some/file.txt")
        assert ok

    def test_path_dir_accepts_any_string(self):
        p = PluginParam(name="d", type="path-dir")
        ok, _ = validate_param_value(p, "/some/directory")
        assert ok

    def test_path_file_required_empty_fails(self):
        p = PluginParam(name="f", type="path-file", required=True)
        ok, err = validate_param_value(p, "")
        assert not ok
        assert "required" in err

    def test_path_dir_not_required_empty_passes(self):
        p = PluginParam(name="d", type="path-dir", required=False)
        ok, _ = validate_param_value(p, "")
        assert ok


class TestParamSerializationTyped:
    """Tests for serialization of typed PluginParam fields."""

    def test_serializes_type_when_not_string(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Run",
                        command="cmd",
                        params=[PluginParam(name="n", type="int", min=1.0, max=10.0)],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        p = result["plugins"][0]["items"][0]["params"][0]
        assert p["type"] == "int"
        assert p["min"] == 1.0
        assert p["max"] == 10.0

    def test_omits_type_when_string(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Run",
                        command="cmd",
                        params=[PluginParam(name="x")],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        p = result["plugins"][0]["items"][0]["params"][0]
        assert "type" not in p

    def test_serializes_required_false(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Run",
                        command="cmd",
                        params=[PluginParam(name="x", required=False)],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        p = result["plugins"][0]["items"][0]["params"][0]
        assert p["required"] is False

    def test_omits_required_when_true(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Run",
                        command="cmd",
                        params=[PluginParam(name="x", required=True)],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        p = result["plugins"][0]["items"][0]["params"][0]
        assert "required" not in p

    def test_serializes_pattern(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Run",
                        command="cmd",
                        params=[PluginParam(name="b", pattern="^[a-z]+$")],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        p = result["plugins"][0]["items"][0]["params"][0]
        assert p["pattern"] == "^[a-z]+$"

    def test_serializes_path_file_type(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Run",
                        command="cmd",
                        params=[
                            PluginParam(name="f", type="path-file", hint="Pick file")
                        ],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        p = result["plugins"][0]["items"][0]["params"][0]
        assert p["type"] == "path-file"

    def test_serializes_path_dir_type(self):
        plugins = [
            Plugin(
                name="Test",
                items=[
                    PluginItem(
                        label="Run",
                        command="cmd",
                        params=[PluginParam(name="d", type="path-dir", default=".")],
                    )
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        p = result["plugins"][0]["items"][0]["params"][0]
        assert p["type"] == "path-dir"
        assert p["default"] == "."

    def test_roundtrip_typed_params(self):
        original = [
            Plugin(
                name="RT",
                items=[
                    PluginItem(
                        label="Go",
                        command="cmd",
                        params=[
                            PluginParam(
                                name="n", type="int", min=1.0, max=10.0, required=True
                            ),
                            PluginParam(
                                name="tag",
                                type="combobox",
                                options=["a", "b"],
                                required=False,
                            ),
                            PluginParam(name="flag", type="boolean", default="true"),
                            PluginParam(name="branch", pattern="^[a-z]+$"),
                            PluginParam(name="f", type="path-file"),
                            PluginParam(name="d", type="path-dir", default="."),
                        ],
                    )
                ],
            )
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        params = restored[0].items[0].params
        assert params[0].type == "int"
        assert params[0].min == 1.0
        assert params[0].max == 10.0
        assert params[1].type == "combobox"
        assert params[1].required is False
        assert params[2].type == "boolean"
        assert params[3].pattern == "^[a-z]+$"
        assert params[4].type == "path-file"
        assert params[5].type == "path-dir"
        assert params[5].default == "."


class TestPluginTarget:
    """Tests for the PluginItem target field."""

    def test_target_omitted_defaults_to_none(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "t.json").write_text(
            json.dumps({"name": "P", "items": [{"label": "A", "command": "cmd"}]})
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].target is None

    def test_target_select_parsed(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "t.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [{"label": "A", "command": "cmd", "target": "select"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].target == "select"

    def test_target_all_parsed(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "t.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [{"label": "A", "command": "cmd", "target": "all"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].target == "all"

    def test_target_containers_parsed(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "t.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [{"label": "A", "command": "cmd", "target": "containers"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].target == "containers"

    def test_target_invalid_defaults_to_none(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "t.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [{"label": "A", "command": "cmd", "target": "bogus"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert plugins[0].items[0].target is None

    def test_target_serialized_when_set(self):
        from ai_guardian.tray.plugins import _item_to_dict

        item = PluginItem(label="A", command="cmd", target="select")
        d = _item_to_dict(item)
        assert d["target"] == "select"

    def test_target_omitted_when_none(self):
        from ai_guardian.tray.plugins import _item_to_dict

        item = PluginItem(label="A", command="cmd", target=None)
        d = _item_to_dict(item)
        assert "target" not in d

    def test_target_roundtrip(self):
        original = [
            Plugin(name="T", items=[PluginItem(label="A", command="cmd", target="all")])
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert restored[0].items[0].target == "all"

    def test_container_name_in_target_vars(self):
        from ai_guardian.daemon.discovery import DaemonTarget

        t = DaemonTarget(
            name="my-project",
            runtime="container",
            container_name="sandbox-1",
        )
        result = substitute_target_vars("check {container_name}", t)
        assert "sandbox-1" in result


class TestInlineSubmenu:
    """Tests for inline submenu items (items with nested children)."""

    def test_inline_submenu_parsed(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "MyPlugin",
                    "items": [
                        {"label": "Check", "command": "echo check"},
                        {
                            "label": "Deploy",
                            "items": [
                                {"label": "Dev", "command": "deploy dev"},
                                {"label": "Prod", "command": "deploy prod"},
                            ],
                        },
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert len(plugins[0].items) == 2
        assert plugins[0].items[0].label == "Check"
        assert plugins[0].items[0].command == "echo check"
        sub = plugins[0].items[1]
        assert sub.label == "Deploy"
        assert sub.items is not None
        assert len(sub.items) == 2
        assert sub.items[0].label == "Dev"
        assert sub.items[0].command == "deploy dev"

    def test_two_levels_of_nesting(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Deep",
                    "items": [
                        {
                            "label": "Level 1",
                            "items": [
                                {
                                    "label": "Level 2",
                                    "items": [
                                        {"label": "Leaf", "command": "echo leaf"},
                                    ],
                                },
                            ],
                        },
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        level1 = plugins[0].items[0]
        assert level1.label == "Level 1"
        level2 = level1.items[0]
        assert level2.label == "Level 2"
        assert level2.items[0].label == "Leaf"
        assert level2.items[0].command == "echo leaf"

    def test_submenu_item_has_no_command(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {
                            "label": "Sub",
                            "items": [{"label": "A", "command": "cmd"}],
                        },
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        sub = plugins[0].items[0]
        assert sub.command is None
        assert sub.items is not None

    def test_submenu_with_all_features(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "Features",
                    "items": [
                        {
                            "label": "Sub",
                            "items": [
                                {
                                    "label": "Terminal",
                                    "command": "echo hi",
                                    "type": "terminal",
                                    "run_on_target": True,
                                },
                                {
                                    "label": "Platform",
                                    "command": {
                                        "darwin": "open .",
                                        "default": "xdg-open .",
                                    },
                                    "type": "background",
                                },
                                {
                                    "label": "Params",
                                    "command": "deploy {tray.env}",
                                    "params": [{"name": "env", "default": "dev"}],
                                },
                            ],
                        },
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        children = plugins[0].items[0].items
        assert children[0].run_on_target is True
        assert isinstance(children[1].command, dict)
        assert children[1].type == "background"
        assert len(children[2].params) == 1

    def test_empty_inline_items_skipped(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {"label": "Sub", "items": []},
                        {"label": "Ok", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert len(plugins[0].items) == 1
        assert plugins[0].items[0].label == "Ok"

    def test_mutually_exclusive_command_and_items(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "test.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {
                            "label": "Bad",
                            "command": "echo hi",
                            "items": [{"label": "X", "command": "y"}],
                        },
                        {"label": "Ok", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert plugins[0].items[0].label == "Ok"


class TestFileImport:
    """Tests for import submenu items (items referencing external JSON files)."""

    def test_import_resolves_file(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "deploy.json").write_text(
            json.dumps(
                {
                    "items": [
                        {"label": "Dev", "command": "deploy dev"},
                        {"label": "Prod", "command": "deploy prod"},
                    ],
                }
            )
        )
        (plugins_dir / "main.json").write_text(
            json.dumps(
                {
                    "name": "MyPlugin",
                    "items": [
                        {"label": "Check", "command": "echo check"},
                        {"label": "Deploy", "import": "deploy.json"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        main = [p for p in plugins if p.name == "MyPlugin"][0]
        assert len(main.items) == 2
        deploy = main.items[1]
        assert deploy.label == "Deploy"
        assert deploy.items is not None
        assert len(deploy.items) == 2
        assert deploy.items[0].label == "Dev"
        assert deploy.import_file is None

    def test_missing_import_file_skipped(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "main.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {"label": "Missing", "import": "nonexistent.json"},
                        {"label": "Ok", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert len(plugins[0].items) == 1
        assert plugins[0].items[0].label == "Ok"

    def test_import_with_tag_filtering_included(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "commands.json").write_text(
            json.dumps(
                {
                    "tags": ["workstation"],
                    "items": [{"label": "A", "command": "cmd_a"}],
                }
            )
        )
        (plugins_dir / "main.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {"label": "Commands", "import": "commands.json"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir, daemon_tags=["workstation"])
        assert len(plugins) == 1
        assert plugins[0].items[0].items is not None

    def test_import_with_tag_filtering_excluded(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "commands.json").write_text(
            json.dumps(
                {
                    "tags": ["server"],
                    "items": [{"label": "A", "command": "cmd_a"}],
                }
            )
        )
        (plugins_dir / "main.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {"label": "Commands", "import": "commands.json"},
                        {"label": "Ok", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir, daemon_tags=["workstation"])
        assert len(plugins) == 1
        assert len(plugins[0].items) == 1
        assert plugins[0].items[0].label == "Ok"

    def test_import_untagged_always_included(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "commands.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "A", "command": "cmd_a"}],
                }
            )
        )
        (plugins_dir / "main.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {"label": "Commands", "import": "commands.json"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir, daemon_tags=["anything"])
        assert len(plugins) == 1
        assert plugins[0].items[0].items is not None

    def test_nested_import_in_imported_file(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "leaf.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "Leaf", "command": "echo leaf"}],
                }
            )
        )
        (plugins_dir / "middle.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "Middle", "import": "leaf.json"}],
                }
            )
        )
        (plugins_dir / "main.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {"label": "Top", "import": "middle.json"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        main = [p for p in plugins if p.name == "P"][0]
        top = main.items[0]
        assert top.label == "Top"
        middle = top.items[0]
        assert middle.label == "Middle"
        assert middle.items[0].label == "Leaf"

    def test_mutually_exclusive_command_and_import(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "sub.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "A", "command": "cmd"}],
                }
            )
        )
        (plugins_dir / "main.json").write_text(
            json.dumps(
                {
                    "name": "P",
                    "items": [
                        {"label": "Bad", "command": "echo", "import": "sub.json"},
                        {"label": "Ok", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert plugins[0].items[0].label == "Ok"


class TestCircularImportDetection:
    """Tests for circular import detection."""

    def test_self_import_detected(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "self.json").write_text(
            json.dumps(
                {
                    "name": "Self",
                    "items": [
                        {"label": "Loop", "import": "self.json"},
                        {"label": "Ok", "command": "echo ok"},
                    ],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        assert len(plugins) == 1
        assert len(plugins[0].items) == 1
        assert plugins[0].items[0].label == "Ok"

    def test_mutual_circular_import(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "a.json").write_text(
            json.dumps(
                {
                    "name": "A",
                    "items": [{"label": "To B", "import": "b.json"}],
                }
            )
        )
        (plugins_dir / "b.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "To A", "import": "a.json"}],
                }
            )
        )
        plugins = load_plugins(plugins_dir)
        a_plugin = [p for p in plugins if p.name == "A"]
        assert len(a_plugin) == 0 or (
            a_plugin[0].items[0].items is not None
            and not any(
                child.import_file == "a.json"
                for child in (a_plugin[0].items[0].items or [])
            )
        )

    def test_check_circular_imports_detects_self(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "loop.json").write_text(
            json.dumps(
                {
                    "name": "Loop",
                    "items": [{"label": "Self", "import": "loop.json"}],
                }
            )
        )
        warnings = check_circular_imports(plugins_dir)
        assert len(warnings) == 1
        assert "loop.json" in warnings[0]

    def test_check_circular_imports_detects_chain(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "a.json").write_text(
            json.dumps(
                {
                    "name": "A",
                    "items": [{"label": "To B", "import": "b.json"}],
                }
            )
        )
        (plugins_dir / "b.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "To A", "import": "a.json"}],
                }
            )
        )
        warnings = check_circular_imports(plugins_dir)
        assert len(warnings) >= 1

    def test_check_circular_imports_no_false_positive(self, tmp_path):
        plugins_dir = tmp_path / "tray-plugins"
        plugins_dir.mkdir()
        (plugins_dir / "shared.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "Common", "command": "echo common"}],
                }
            )
        )
        (plugins_dir / "a.json").write_text(
            json.dumps(
                {
                    "name": "A",
                    "items": [{"label": "Shared", "import": "shared.json"}],
                }
            )
        )
        (plugins_dir / "b.json").write_text(
            json.dumps(
                {
                    "name": "B",
                    "items": [{"label": "Shared", "import": "shared.json"}],
                }
            )
        )
        warnings = check_circular_imports(plugins_dir)
        assert len(warnings) == 0


class TestNestedSerialization:
    """Tests for serialization and deserialization of nested items."""

    def test_serialize_inline_submenu(self):
        plugins = [
            Plugin(
                name="P",
                items=[
                    PluginItem(
                        label="Sub",
                        items=[PluginItem(label="A", command="cmd_a")],
                    ),
                ],
            )
        ]
        result = plugins_to_dict(plugins)
        sub = result["plugins"][0]["items"][0]
        assert "items" in sub
        assert "command" not in sub
        assert sub["items"][0]["label"] == "A"

    def test_serialize_import_file(self):
        plugins = [
            Plugin(
                name="P",
                items=[PluginItem(label="Imported", import_file="other.json")],
            )
        ]
        result = plugins_to_dict(plugins)
        item = result["plugins"][0]["items"][0]
        assert item["import"] == "other.json"
        assert "command" not in item
        assert "items" not in item

    def test_roundtrip_nested_items(self):
        original = [
            Plugin(
                name="P",
                items=[
                    PluginItem(label="Cmd", command="echo 1", type="background"),
                    PluginItem(
                        label="Sub",
                        items=[
                            PluginItem(label="Child1", command="cmd1"),
                            PluginItem(
                                label="Child2", command="cmd2", type="notification"
                            ),
                        ],
                    ),
                ],
            )
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        assert len(restored) == 1
        assert len(restored[0].items) == 2
        assert restored[0].items[0].label == "Cmd"
        sub = restored[0].items[1]
        assert sub.label == "Sub"
        assert sub.items is not None
        assert len(sub.items) == 2
        assert sub.items[0].command == "cmd1"
        assert sub.items[1].type == "notification"

    def test_roundtrip_deeply_nested(self):
        original = [
            Plugin(
                name="Deep",
                items=[
                    PluginItem(
                        label="L1",
                        items=[
                            PluginItem(
                                label="L2",
                                items=[
                                    PluginItem(label="L3", command="echo deep"),
                                ],
                            ),
                        ],
                    ),
                ],
            )
        ]
        data = plugins_to_dict(original)
        restored = dict_to_plugins(data)
        l1 = restored[0].items[0]
        l2 = l1.items[0]
        assert l2.items[0].label == "L3"
        assert l2.items[0].command == "echo deep"


class TestFindProjectPluginsDir:
    """Tests for project root discovery via upward directory walk."""

    def test_found_at_exact_dir(self, tmp_path):
        project = tmp_path / "my-project"
        plugins = project / ".ai-guardian" / "tray-plugins"
        plugins.mkdir(parents=True)
        result = find_project_plugins_dir(str(project))
        assert result == plugins

    def test_walks_up_from_subdirectory(self, tmp_path):
        project = tmp_path / "my-project"
        plugins = project / ".ai-guardian" / "tray-plugins"
        plugins.mkdir(parents=True)
        deep = project / "src" / "components" / "ui"
        deep.mkdir(parents=True)
        result = find_project_plugins_dir(str(deep))
        assert result == plugins

    def test_not_found_returns_none(self, tmp_path):
        result = find_project_plugins_dir(str(tmp_path))
        assert result is None

    def test_none_working_dir_returns_none(self):
        result = find_project_plugins_dir(None)
        assert result is None

    def test_empty_working_dir_returns_none(self):
        result = find_project_plugins_dir("")
        assert result is None

    def test_stops_at_ai_guardian_without_tray_plugins(self, tmp_path):
        project = tmp_path / "my-project"
        (project / ".ai-guardian").mkdir(parents=True)
        result = find_project_plugins_dir(str(project))
        assert result is None

    def test_finds_nearest_ancestor(self, tmp_path):
        outer = tmp_path / "outer"
        outer_plugins = outer / ".ai-guardian" / "tray-plugins"
        outer_plugins.mkdir(parents=True)
        inner = outer / "inner"
        inner_plugins = inner / ".ai-guardian" / "tray-plugins"
        inner_plugins.mkdir(parents=True)
        result = find_project_plugins_dir(str(inner / "src"))
        assert result == inner_plugins


class TestLoadMergedPlugins:
    """Tests for merging user-level and project-level plugins."""

    @pytest.fixture(autouse=True)
    def _no_bundled(self):
        with mock.patch(
            "ai_guardian.tray.plugins._load_bundled_plugins", return_value=[]
        ):
            yield

    def _make_plugin_json(self, path, name, label="Action", command="echo ok"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "name": name,
                    "items": [{"label": label, "command": command}],
                }
            )
        )

    def test_user_only_when_no_project(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        self._make_plugin_json(user_dir / "p1.json", "UserPlugin")
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(str(tmp_path / "no-project"))
        assert len(result) == 1
        assert result[0].name == "UserPlugin"

    def test_project_only_when_no_user(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        project = tmp_path / "project"
        proj_plugins = project / ".ai-guardian" / "tray-plugins"
        self._make_plugin_json(proj_plugins / "p1.json", "ProjectPlugin")
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(str(project))
        assert len(result) == 1
        assert result[0].name == "ProjectPlugin"

    def test_project_overrides_user_same_name(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        self._make_plugin_json(
            user_dir / "p1.json",
            "SharedName",
            label="User",
        )
        project = tmp_path / "project"
        proj_plugins = project / ".ai-guardian" / "tray-plugins"
        self._make_plugin_json(
            proj_plugins / "p1.json",
            "SharedName",
            label="Project",
        )
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(str(project))
        assert len(result) == 1
        assert result[0].name == "SharedName"
        assert result[0].items[0].label == "Project"

    def test_both_with_unique_names(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        self._make_plugin_json(user_dir / "u.json", "UserOnly")
        project = tmp_path / "project"
        proj_plugins = project / ".ai-guardian" / "tray-plugins"
        self._make_plugin_json(proj_plugins / "p.json", "ProjectOnly")
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(str(project))
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"UserOnly", "ProjectOnly"}

    def test_project_plugins_come_first(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        self._make_plugin_json(user_dir / "u.json", "UserPlugin")
        project = tmp_path / "project"
        proj_plugins = project / ".ai-guardian" / "tray-plugins"
        self._make_plugin_json(proj_plugins / "p.json", "ProjectPlugin")
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(str(project))
        assert result[0].name == "ProjectPlugin"
        assert result[1].name == "UserPlugin"

    def test_none_working_dir_returns_user_only(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        self._make_plugin_json(user_dir / "p1.json", "UserPlugin")
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(None)
        assert len(result) == 1
        assert result[0].name == "UserPlugin"

    def test_project_imports_resolve_relative_to_project_dir(self, tmp_path):
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        project = tmp_path / "project"
        proj_plugins = project / ".ai-guardian" / "tray-plugins"
        proj_plugins.mkdir(parents=True)
        (proj_plugins / "sub.json").write_text(
            json.dumps(
                {
                    "items": [{"label": "Sub", "command": "echo sub"}],
                }
            )
        )
        (proj_plugins / "main.json").write_text(
            json.dumps(
                {
                    "name": "ProjPlugin",
                    "items": [{"label": "Imported", "import": "sub.json"}],
                }
            )
        )
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(str(project))
        proj = [p for p in result if p.name == "ProjPlugin"]
        assert len(proj) == 1
        assert proj[0].items[0].items is not None
        assert proj[0].items[0].items[0].label == "Sub"

    def test_merged_plugins_preserve_tags_for_later_filtering(self, tmp_path):
        """Tags are loaded but not filtered — callers use filter_plugins_by_tags()."""
        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        project = tmp_path / "project"
        proj_plugins = project / ".ai-guardian" / "tray-plugins"
        proj_plugins.mkdir(parents=True)
        (proj_plugins / "tagged.json").write_text(
            json.dumps(
                {
                    "name": "Tagged",
                    "tags": ["special"],
                    "items": [{"label": "A", "command": "echo a"}],
                }
            )
        )
        with mock.patch(
            "ai_guardian.daemon.get_tray_plugins_dir",
            return_value=user_dir,
        ):
            result = load_merged_plugins(str(project))
        assert len(result) == 1
        assert result[0].tags == ["special"]
        filtered = filter_plugins_by_tags(result, daemon_tags=["other"])
        assert len(filtered) == 0
        filtered = filter_plugins_by_tags(result, daemon_tags=["special"])
        assert len(filtered) == 1


# --- Merged from test_tray_plugin_schema.py ---

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "ai_guardian"
    / "schemas"
    / "tray-plugin.schema.json"
)


@pytest.fixture
def plugin_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_schema(instance, schema):
    jsonschema.validate(instance, schema)


class TestValidPluginSchemas:
    def test_minimal_plugin(self, plugin_schema):
        _validate_schema(
            {
                "name": "My Plugin",
                "items": [{"label": "Hello", "command": "echo hello"}],
            },
            plugin_schema,
        )

    def test_all_fields(self, plugin_schema):
        _validate_schema(
            {
                "name": "Full Plugin",
                "items": [
                    {
                        "label": "Action",
                        "command": "echo {tray.name}",
                        "type": "notification",
                        "run_on_target": True,
                        "params": [
                            {
                                "name": "name",
                                "hint": "Your name",
                                "default": "World",
                                "options": ["Alice", "Bob"],
                            }
                        ],
                    }
                ],
            },
            plugin_schema,
        )

    def test_platform_map_command(self, plugin_schema):
        _validate_schema(
            {
                "name": "Cross-Platform",
                "items": [
                    {
                        "label": "Open",
                        "command": {
                            "darwin": "open .",
                            "linux": "xdg-open .",
                            "windows": "explorer .",
                            "default": "echo unsupported",
                        },
                    }
                ],
            },
            plugin_schema,
        )

    def test_platform_map_single_key(self, plugin_schema):
        _validate_schema(
            {
                "name": "Mac Only",
                "items": [
                    {"label": "Say", "command": {"darwin": "say hello"}},
                ],
            },
            plugin_schema,
        )

    def test_multiple_items(self, plugin_schema):
        _validate_schema(
            {
                "name": "Multi",
                "items": [
                    {"label": "A", "command": "cmd-a"},
                    {"label": "B", "command": "cmd-b", "type": "background"},
                    {"label": "C", "command": "cmd-c", "type": "clipboard"},
                ],
            },
            plugin_schema,
        )

    def test_all_execution_types(self, plugin_schema):
        for exec_type in (
            "terminal",
            "background",
            "notification",
            "clipboard",
            "modal",
        ):
            _validate_schema(
                {
                    "name": "Types",
                    "items": [{"label": "X", "command": "cmd", "type": exec_type}],
                },
                plugin_schema,
            )

    def test_param_minimal(self, plugin_schema):
        _validate_schema(
            {
                "name": "P",
                "items": [
                    {
                        "label": "X",
                        "command": "echo {tray.val}",
                        "params": [{"name": "val"}],
                    }
                ],
            },
            plugin_schema,
        )

    def test_schema_ref_allowed(self, plugin_schema):
        _validate_schema(
            {
                "$schema": "https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/src/ai_guardian/schemas/tray-plugin.schema.json",
                "name": "With Schema Ref",
                "items": [{"label": "X", "command": "echo ok"}],
            },
            plugin_schema,
        )


class TestInvalidPluginSchemas:
    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(
                {"items": [{"label": "X", "command": "cmd"}]},
                id="missing_name",
            ),
            pytest.param(
                {"name": "", "items": [{"label": "X", "command": "cmd"}]},
                id="empty_name",
            ),
            pytest.param(
                {"name": "NoItems"},
                id="missing_items",
            ),
            pytest.param(
                {"name": "Empty", "items": []},
                id="empty_items",
            ),
            pytest.param(
                {
                    "name": "TooMany",
                    "items": [
                        {"label": f"Item{i}", "command": f"cmd{i}"} for i in range(13)
                    ],
                },
                id="too_many_items",
            ),
            pytest.param(
                {"name": "P", "items": [{"command": "cmd"}]},
                id="missing_label",
            ),
            pytest.param(
                {"name": "P", "items": [{"label": "X"}]},
                id="missing_command",
            ),
            pytest.param(
                {
                    "name": "P",
                    "items": [{"label": "X", "command": "cmd", "type": "invalid"}],
                },
                id="invalid_type",
            ),
            pytest.param(
                {"name": "P", "items": [{"label": "X", "command": {}}]},
                id="empty_platform_map",
            ),
            pytest.param(
                {"name": "P", "items": [{"label": "X", "command": {"freebsd": "cmd"}}]},
                id="unknown_platform_key",
            ),
            pytest.param(
                {
                    "name": "P",
                    "items": [{"label": "X", "command": "cmd"}],
                    "unknown_field": True,
                },
                id="extra_property_on_root",
            ),
            pytest.param(
                {
                    "name": "P",
                    "items": [{"label": "X", "command": "cmd", "typo": True}],
                },
                id="extra_property_on_item",
            ),
            pytest.param(
                {
                    "name": "P",
                    "items": [
                        {
                            "label": "X",
                            "command": "cmd",
                            "params": [{"hint": "no name"}],
                        }
                    ],
                },
                id="missing_param_name",
            ),
            pytest.param(
                {
                    "name": "P",
                    "items": [
                        {
                            "label": "X",
                            "command": "cmd",
                            "params": [{"name": "x", "extra": True}],
                        }
                    ],
                },
                id="extra_property_on_param",
            ),
            pytest.param(
                {"name": 123, "items": [{"label": "X", "command": "cmd"}]},
                id="name_not_string",
            ),
            pytest.param(
                {"name": "P", "items": [{"label": "X", "command": 42}]},
                id="command_not_string_or_object",
            ),
            pytest.param(
                {
                    "name": "P",
                    "items": [{"label": "X", "command": "cmd", "run_on_target": "yes"}],
                },
                id="run_on_target_not_boolean",
            ),
        ],
    )
    def test_invalid_schema(self, plugin_schema, data):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(data, plugin_schema)


class TestTagsPluginSchema:
    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(
                {
                    "name": "Carbonite",
                    "tags": ["carbonite", "container"],
                    "items": [{"label": "Status", "command": "echo ok"}],
                },
                id="multiple_tags",
            ),
            pytest.param(
                {
                    "name": "Carbonite",
                    "tags": ["carbonite"],
                    "items": [{"label": "Status", "command": "echo ok"}],
                },
                id="single_tag",
            ),
            pytest.param(
                {
                    "name": "Generic",
                    "tags": [],
                    "items": [{"label": "Run", "command": "echo"}],
                },
                id="empty_tags",
            ),
            pytest.param(
                {"name": "Generic", "items": [{"label": "Run", "command": "echo"}]},
                id="without_tags",
            ),
        ],
    )
    def test_valid_tags(self, plugin_schema, data):
        _validate_schema(data, plugin_schema)

    @pytest.mark.parametrize(
        "tags_value",
        [
            pytest.param([""], id="empty_string"),
            pytest.param([42], id="non_string"),
            pytest.param("not-an-array", id="non_array"),
        ],
    )
    def test_invalid_tags(self, plugin_schema, tags_value):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {
                    "name": "P",
                    "tags": tags_value,
                    "items": [{"label": "X", "command": "cmd"}],
                },
                plugin_schema,
            )


class TestScopePluginSchema:
    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(
                {
                    "name": "Quick Links",
                    "scope": "global",
                    "items": [{"label": "Docs", "command": "echo docs"}],
                },
                id="scope_global",
            ),
            pytest.param(
                {
                    "name": "Daemon Plugin",
                    "scope": "daemon",
                    "items": [{"label": "Status", "command": "echo ok"}],
                },
                id="scope_daemon",
            ),
            pytest.param(
                {"name": "No Scope", "items": [{"label": "Run", "command": "echo"}]},
                id="without_scope",
            ),
            pytest.param(
                {
                    "name": "Global With Tags",
                    "scope": "global",
                    "tags": ["ignored"],
                    "items": [{"label": "Docs", "command": "echo"}],
                },
                id="global_scope_with_tags",
            ),
        ],
    )
    def test_valid_scope(self, plugin_schema, data):
        _validate_schema(data, plugin_schema)

    @pytest.mark.parametrize(
        "scope_value",
        [
            pytest.param("invalid", id="invalid_value"),
            pytest.param(42, id="non_string"),
        ],
    )
    def test_invalid_scope(self, plugin_schema, scope_value):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {
                    "name": "P",
                    "scope": scope_value,
                    "items": [{"label": "X", "command": "cmd"}],
                },
                plugin_schema,
            )


class TestSubmenuPluginSchema:
    def test_inline_submenu_valid(self, plugin_schema):
        _validate_schema(
            {
                "name": "Plugin",
                "items": [
                    {
                        "label": "Deploy",
                        "items": [
                            {"label": "Dev", "command": "deploy dev"},
                            {"label": "Prod", "command": "deploy prod"},
                        ],
                    }
                ],
            },
            plugin_schema,
        )

    def test_nested_two_levels(self, plugin_schema):
        _validate_schema(
            {
                "name": "Plugin",
                "items": [
                    {
                        "label": "Level 1",
                        "items": [
                            {
                                "label": "Level 2",
                                "items": [{"label": "Leaf", "command": "echo leaf"}],
                            }
                        ],
                    }
                ],
            },
            plugin_schema,
        )

    def test_mixed_command_and_submenu(self, plugin_schema):
        _validate_schema(
            {
                "name": "Plugin",
                "items": [
                    {"label": "Simple", "command": "echo hi"},
                    {"label": "Sub", "items": [{"label": "A", "command": "cmd"}]},
                ],
            },
            plugin_schema,
        )

    def test_submenu_empty_items_rejected(self, plugin_schema):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {"name": "P", "items": [{"label": "Empty", "items": []}]}, plugin_schema
            )

    def test_submenu_missing_label_rejected(self, plugin_schema):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {"name": "P", "items": [{"items": [{"label": "A", "command": "cmd"}]}]},
                plugin_schema,
            )


class TestImportPluginSchema:
    def test_import_item_valid(self, plugin_schema):
        _validate_schema(
            {"name": "Plugin", "items": [{"label": "Deploy", "import": "deploy.json"}]},
            plugin_schema,
        )

    def test_import_missing_label_rejected(self, plugin_schema):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {"name": "P", "items": [{"import": "file.json"}]}, plugin_schema
            )

    def test_import_empty_string_rejected(self, plugin_schema):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {"name": "P", "items": [{"label": "X", "import": ""}]}, plugin_schema
            )

    def test_command_with_items_rejected(self, plugin_schema):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {
                    "name": "P",
                    "items": [
                        {
                            "label": "Bad",
                            "command": "echo",
                            "items": [{"label": "A", "command": "cmd"}],
                        }
                    ],
                },
                plugin_schema,
            )

    def test_command_with_import_rejected(self, plugin_schema):
        with pytest.raises(jsonschema.ValidationError):
            _validate_schema(
                {
                    "name": "P",
                    "items": [{"label": "Bad", "command": "echo", "import": "f.json"}],
                },
                plugin_schema,
            )


class TestPathTypePluginSchema:
    def test_path_file_type_valid(self, plugin_schema):
        _validate_schema(
            {
                "name": "P",
                "items": [
                    {
                        "label": "Sanitize",
                        "command": "sanitize {tray.file}",
                        "params": [
                            {"name": "file", "type": "path-file", "hint": "Pick a file"}
                        ],
                    }
                ],
            },
            plugin_schema,
        )

    def test_path_dir_type_valid(self, plugin_schema):
        _validate_schema(
            {
                "name": "P",
                "items": [
                    {
                        "label": "Scan",
                        "command": "scan {tray.dir}",
                        "params": [{"name": "dir", "type": "path-dir", "default": "."}],
                    }
                ],
            },
            plugin_schema,
        )

    def test_path_file_with_required_false(self, plugin_schema):
        _validate_schema(
            {
                "name": "P",
                "items": [
                    {
                        "label": "X",
                        "command": "cmd {tray.f}",
                        "params": [
                            {"name": "f", "type": "path-file", "required": False}
                        ],
                    }
                ],
            },
            plugin_schema,
        )
