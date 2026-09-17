"""Tests for the ``ai-guardian sandbox`` lifecycle command."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from ai_guardian.sandbox import (
    CONTAINER_GOOGLE_CREDENTIALS_PATH,
    OPENSHELL_ENTRYPOINT,
    _compose_openshell_policy,
    _ensure_openshell_cli_provider,
    _ensure_openshell_daemon,
    _fetch_sandbox_config,
    _load_snapshot_config,
    _openshell_create,
    _openshell_explicit_command,
    _openshell_provider_environment,
    _expose_openshell_service,
    _runtime,
    _validate_create_options,
    create_sandbox,
    handle_sandbox_command,
)


def _args(**overrides):
    values = {
        "sandbox_command": "status",
        "sandbox_config_command": None,
        "runtime": "container",
        "container_engine": "podman",
        "openshell_cli": "openshell",
        "name": "demo",
        "cli": None,
        "opencode_agent": None,
        "restore_config": None,
        "snapshot": "latest",
        "json_output": False,
        "command_args": [],
        "follow": False,
        "tail": None,
        "source": None,
        "level": None,
        "since": None,
        "model": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_container_start_uses_selected_engine():
    args = _args(sandbox_command="start", container_engine="docker")

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    assert run.call_args.args[0] == ["docker", "start", "demo"]


def test_container_lifecycle_uses_runtime_container_name():
    args = _args(
        sandbox_command="exec",
        name="logical-name",
        container_name="runtime-name",
        command_args=["--", "pwd"],
    )

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    assert run.call_args.args[0] == [
        "podman",
        "exec",
        "--interactive",
        "--tty",
        "runtime-name",
        "pwd",
    ]


def test_programmatic_lifecycle_command_captures_runtime_output():
    args = _args(sandbox_command="status")
    output = []

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess(
            [], 0, stdout="status output\n", stderr="status warning\n"
        ),
    ):
        assert handle_sandbox_command(args, output=output) == 0

    assert output == ["status output\n", "status warning\n"]


def test_openshell_start_recovers_container_stopped_out_of_band():
    args = _args(
        sandbox_command="start",
        runtime="openshell",
        container_id="container-id",
    )
    output = []

    with (
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(
                    [], 1, stdout="", stderr="sandbox must be stopped to start\n"
                ),
                subprocess.CompletedProcess([], 0, stdout="container-id\n", stderr=""),
            ],
        ) as run,
        patch(
            "ai_guardian.sandbox._ensure_openshell_service", return_value=0
        ) as forward,
        patch("ai_guardian.sandbox._ensure_openshell_daemon", return_value=0) as daemon,
    ):
        assert handle_sandbox_command(args, output=output) == 0

    assert run.call_args_list[0].args[0] == [
        "openshell",
        "sandbox",
        "start",
        "demo",
    ]
    assert run.call_args_list[1].args[0] == [
        "podman",
        "start",
        "container-id",
    ]
    assert "starting the underlying container instead" in "".join(output)
    forward.assert_called_once_with(args, "demo", output=output)
    daemon.assert_called_once_with(args, "demo", output=output)


def test_create_defaults_to_openshell():
    args = _args(sandbox_command="create", runtime=None)

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_SANDBOX_RUNTIME": ""}),
        patch("ai_guardian.sandbox.create_sandbox", return_value=0) as create,
    ):
        assert _runtime(args) == "openshell"
        assert handle_sandbox_command(args) == 0

    create.assert_called_once_with(args, output=None)


def test_sandbox_create_reserves_agent_for_opencode_profiles():
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        opencode_agent="codex",
    )

    with pytest.raises(
        ValueError, match="--agent is supported only with --cli opencode"
    ):
        _validate_create_options(args)


def test_sandbox_create_requires_agent_for_opencode():
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        cli="opencode",
    )

    with pytest.raises(ValueError, match="--agent is required with --cli opencode"):
        _validate_create_options(args)


def test_container_list_is_scoped_to_managed_sandboxes():
    args = _args(sandbox_command="list", container_engine="docker")
    del args.name

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    assert run.call_args.args[0] == [
        "docker",
        "ps",
        "--all",
        "--filter",
        "label=ai-guardian.managed=true",
    ]


def test_openshell_list_is_scoped_to_managed_sandboxes():
    args = _args(sandbox_command="list", runtime="openshell")
    del args.name

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    assert run.call_args.args[0] == [
        "openshell",
        "sandbox",
        "list",
        "--selector",
        "ai-guardian.managed=true",
    ]


def test_openshell_status_uses_gateway_get_command():
    args = _args(
        sandbox_command="status",
        runtime="openshell",
        json_output=True,
    )

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    assert run.call_args.args[0] == [
        "openshell",
        "sandbox",
        "get",
        "demo",
        "--output",
        "json",
    ]


def test_openshell_lifecycle_commands():
    cases = (
        ("start", ["openshell", "sandbox", "start", "demo"]),
        ("stop", ["openshell", "sandbox", "stop", "demo"]),
        (
            "connect",
            [
                "openshell",
                "sandbox",
                "exec",
                "--name",
                "demo",
                "--tty",
                "--",
                "/bin/bash",
                "-l",
            ],
        ),
        ("delete", ["openshell", "sandbox", "delete", "demo"]),
        (
            "exec",
            [
                "openshell",
                "sandbox",
                "exec",
                "--name",
                "demo",
                "--",
                "printf",
                "hello",
            ],
        ),
        ("logs", ["openshell", "logs", "demo"]),
    )

    for operation, expected in cases:
        args = _args(
            sandbox_command=operation,
            runtime="openshell",
            command_args=["--", "printf", "hello"] if operation == "exec" else [],
        )
        with (
            patch(
                "ai_guardian.sandbox.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as run,
            patch("ai_guardian.sandbox._ensure_openshell_service", return_value=0),
            patch("ai_guardian.sandbox._ensure_openshell_daemon", return_value=0),
        ):
            assert handle_sandbox_command(args) == 0

        assert run.call_args.args[0] == expected


def test_openshell_restart_stops_before_starting():
    args = _args(sandbox_command="restart", runtime="openshell")

    with (
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
        patch("ai_guardian.sandbox._ensure_openshell_service", return_value=0),
        patch("ai_guardian.sandbox._ensure_openshell_daemon", return_value=0) as daemon,
    ):
        assert handle_sandbox_command(args) == 0

    assert [call.args[0] for call in run.call_args_list] == [
        ["openshell", "sandbox", "stop", "demo"],
        ["openshell", "sandbox", "start", "demo"],
    ]
    daemon.assert_called_once_with(args, "demo", output=None)


def test_ensure_openshell_daemon_starts_unresponsive_daemon():
    args = _args(runtime="openshell")
    not_running = subprocess.CompletedProcess(
        [], 1, stdout="ai-guardian daemon: not running\n", stderr=""
    )

    with (
        patch("ai_guardian.sandbox._runtime_exec_capture", return_value=not_running),
        patch("ai_guardian.sandbox._run", return_value=0) as run,
    ):
        assert _ensure_openshell_daemon(args, "demo") == 0

    run.assert_called_once_with(
        [
            "openshell",
            "sandbox",
            "exec",
            "--name",
            "demo",
            "--no-tty",
            "--",
            "ai-guardian",
            "daemon",
            "start",
            "--background",
        ],
        output=None,
    )


def test_ensure_openshell_daemon_skips_running_daemon():
    args = _args(runtime="openshell")
    running = subprocess.CompletedProcess([], 0)

    with (
        patch("ai_guardian.sandbox._runtime_exec_capture", return_value=running),
        patch("ai_guardian.sandbox._run") as run,
    ):
        assert _ensure_openshell_daemon(args, "demo") == 0

    run.assert_not_called()


def test_lifecycle_command_auto_detects_openshell_by_label():
    args = _args(sandbox_command="delete", runtime=None)

    def fake_run(command, **kwargs):
        if command[:2] == ["podman", "inspect"]:
            return subprocess.CompletedProcess(command, 125, stderr="not found")
        if command[:4] == ["openshell", "sandbox", "get", "demo"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "name": "demo",
                        "labels": {
                            "ai-guardian.managed": "true",
                            "ai-guardian.runtime": "openshell",
                        },
                    }
                ),
            )
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_SANDBOX_RUNTIME": ""}),
        patch("ai_guardian.sandbox.subprocess.run", side_effect=fake_run) as run,
    ):
        assert handle_sandbox_command(args) == 0

    assert run.call_args_list[-1].args[0] == [
        "openshell",
        "sandbox",
        "delete",
        "demo",
    ]


def test_lifecycle_command_auto_detects_container_by_runtime_label():
    args = _args(sandbox_command="delete", runtime=None)

    def fake_run(command, **kwargs):
        if command[:2] == ["podman", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [{"Config": {"Labels": {"ai-guardian.runtime": "container"}}}]
                ),
            )
        if command[:4] == ["openshell", "sandbox", "get", "demo"]:
            return subprocess.CompletedProcess(command, 1, stderr="not found")
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_SANDBOX_RUNTIME": ""}),
        patch("ai_guardian.sandbox.subprocess.run", side_effect=fake_run) as run,
    ):
        assert handle_sandbox_command(args) == 0

    assert run.call_args_list[-1].args[0] == ["podman", "rm", "--force", "demo"]


def test_lifecycle_auto_detection_finds_docker_and_retains_engine():
    args = _args(sandbox_command="delete", runtime=None, container_engine=None)

    def fake_run(command, **kwargs):
        if command[:2] == ["podman", "inspect"]:
            return subprocess.CompletedProcess(command, 125, stderr="not found")
        if command[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [{"Config": {"Labels": {"ai-guardian.daemon": "true"}}}]
                ),
            )
        if command[:4] == ["openshell", "sandbox", "get", "demo"]:
            return subprocess.CompletedProcess(command, 1, stderr="not found")
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.dict(
            os.environ,
            {"AI_GUARDIAN_SANDBOX_RUNTIME": "", "CONTAINER_ENGINE": ""},
        ),
        patch("ai_guardian.sandbox.subprocess.run", side_effect=fake_run) as run,
    ):
        assert handle_sandbox_command(args) == 0

    assert run.call_args_list[-1].args[0] == ["docker", "rm", "--force", "demo"]


def test_list_without_runtime_includes_both_supported_runtimes(capsys):
    args = _args(sandbox_command="list", runtime=None)

    def fake_run(command, **kwargs):
        if command[0] == "podman":
            return subprocess.CompletedProcess(command, 0, stdout="container-list\n")
        return subprocess.CompletedProcess(command, 0, stdout="openshell-list\n")

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_SANDBOX_RUNTIME": ""}),
        patch("ai_guardian.sandbox.subprocess.run", side_effect=fake_run) as run,
    ):
        assert handle_sandbox_command(args) == 0

    assert [call.args[0] for call in run.call_args_list] == [
        [
            "podman",
            "ps",
            "--all",
            "--filter",
            "label=ai-guardian.managed=true",
        ],
        ["openshell", "sandbox", "list", "--selector", "ai-guardian.managed=true"],
    ]
    output = capsys.readouterr().out
    assert "container sandboxes:" in output
    assert "openshell sandboxes:" in output
    assert "container-list" in output
    assert "openshell-list" in output


def test_container_create_is_detached_and_keeps_config_read_only(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "ai-guardian.json"
    config_path.write_text("{}\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    args = _args(
        sandbox_command="create",
        name="demo",
        cli="codex",
        profile=None,
        config_dir=str(config_dir),
        repo=str(repo),
        port=8123,
        image="example/ai-guardian:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
    )

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    command = run.call_args.args[0]
    assert command[:5] == [
        "podman",
        "run",
        "--detach",
        "--interactive",
        "--tty",
    ]
    assert command[5:8] == ["--label", "ai-guardian.managed=true", "--label"]
    assert "ai-guardian.daemon=true" in command
    assert "--name" in command
    assert command[command.index("--name") + 1] == "demo"
    assert "ai-guardian.name=demo" in command
    assert "--publish" in command
    assert command[command.index("--publish") + 1] == "8123:63152"
    assert f"{config_path}:/sandbox/.config/ai-guardian.host.json:ro,z" in command
    assert (
        "AI_GUARDIAN_HOST_CONFIG_PATH=/sandbox/.config/ai-guardian.host.json" in command
    )
    assert f"{repo}:/sandbox/repo" in command
    assert command[-3:] == ["example/ai-guardian:test", "bash", "-l"]


def test_container_create_forwards_vertex_auth_and_mounts_adc(tmp_path):
    adc_path = tmp_path / ".config" / "gcloud" / "application_default_credentials.json"
    adc_path.parent.mkdir(parents=True)
    adc_path.write_text("{}\n", encoding="utf-8")
    args = _args(
        sandbox_command="create",
        name="claude-vertex",
        cli="claude",
        image="example/ai-guardian:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
    )

    with (
        patch.dict(
            os.environ,
            {
                "HOME": str(tmp_path),
                "USERPROFILE": str(tmp_path),
                "ANTHROPIC_API_KEY": "inherited-placeholder",
                "ANTHROPIC_VERTEX_PROJECT_ID": "test-project",
                "CLOUD_ML_REGION": "global",
            },
            clear=True,
        ),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    command = run.call_args.args[0]
    assert "CLAUDE_CODE_USE_VERTEX=1" in command
    assert "ANTHROPIC_API_KEY" not in command
    assert "ANTHROPIC_VERTEX_PROJECT_ID=test-project" in command
    assert "CLOUD_ML_REGION=global" in command
    assert (
        f"GOOGLE_APPLICATION_CREDENTIALS={CONTAINER_GOOGLE_CREDENTIALS_PATH}" in command
    )
    assert f"{adc_path}:{CONTAINER_GOOGLE_CREDENTIALS_PATH}:ro,z" in command


def test_container_create_uses_latest_saved_config_snapshot(tmp_path):
    state_dir = tmp_path / "state"
    snapshot_dir = state_dir / "sandboxes" / "demo" / "20260913T192805.123456Z"
    snapshot_dir.mkdir(parents=True)
    snapshot_path = snapshot_dir / "ai-guardian.json"
    snapshot_path.write_text('{"action": "ask"}\n', encoding="utf-8")
    (snapshot_dir / "metadata.json").write_text(
        json.dumps(
            {
                "sandbox_name": "demo",
                "runtime": "container",
                "saved_at": "2026-09-13T19:28:05.123456Z",
            }
        ),
        encoding="utf-8",
    )
    args = _args(
        sandbox_command="create",
        name="demo",
        restore_config="latest",
        config_dir=None,
        repo=None,
        profile=None,
        port=8123,
        image="example/ai-guardian:test",
        environment=[],
        label=[],
    )

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_STATE_DIR": str(state_dir)}, clear=False),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    command = run.call_args.args[0]
    assert f"{snapshot_path}:/sandbox/.config/ai-guardian.host.json:ro,z" in command
    assert "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true" in command
    assert "AI_GUARDIAN_RESTORE_CONFIG=true" in command


def test_restore_config_requires_name(capsys):
    args = _args(
        sandbox_command="create",
        name=None,
        restore_config="latest",
        config_dir=None,
    )

    with patch("ai_guardian.sandbox.subprocess.run") as run:
        assert handle_sandbox_command(args) == 2

    run.assert_not_called()
    assert "--name is required with --restore-config" in capsys.readouterr().err


def test_restore_config_cannot_be_combined_with_profile(capsys):
    args = _args(
        sandbox_command="create",
        restore_config="latest",
        config_dir=None,
        profile="@standard",
    )

    with patch("ai_guardian.sandbox.subprocess.run") as run:
        assert handle_sandbox_command(args) == 2

    run.assert_not_called()
    assert "cannot be combined with --profile" in capsys.readouterr().err


def test_sandbox_config_save_persists_daemon_config_snapshot(tmp_path, capsys):
    args = _args(
        sandbox_command="config",
        sandbox_config_command="save",
        runtime="container",
        name="demo",
        json_output=True,
    )
    config = {"action": "ask", "secret_scanning": {"enabled": True}}

    with (
        patch.dict(
            os.environ,
            {"AI_GUARDIAN_STATE_DIR": str(tmp_path / "state")},
            clear=False,
        ),
        patch(
            "ai_guardian.sandbox._fetch_sandbox_config", return_value=config
        ) as fetch,
    ):
        assert handle_sandbox_command(args) == 0

    fetch.assert_called_once_with(args, "container", "demo")
    result = json.loads(capsys.readouterr().out)
    snapshot_path = Path(result["snapshot"])
    assert result["sandbox_name"] == "demo"
    assert result["runtime"] == "container"
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == config
    metadata = json.loads(
        (snapshot_path.parent / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["sandbox_name"] == "demo"
    assert metadata["runtime"] == "container"


def test_fetch_sandbox_config_reads_global_config_from_daemon():
    args = _args(runtime="container", name="demo")
    target = object()
    config = {"action": "warn"}

    with (
        patch("ai_guardian.sandbox._sandbox_rest_target", return_value=target),
        patch(
            "ai_guardian.daemon.multi_client.MultiDaemonClient.get_config_scoped",
            return_value=config,
        ) as get_config,
    ):
        assert _fetch_sandbox_config(args, "container", "demo") == config

    get_config.assert_called_once_with(target, scope="global")


def test_sandbox_config_restore_sends_latest_snapshot_to_daemon(tmp_path):
    snapshot_dir = tmp_path / "state" / "sandboxes" / "demo" / "20260913T192805.123456Z"
    snapshot_dir.mkdir(parents=True)
    snapshot_path = snapshot_dir / "ai-guardian.json"
    config = {"action": "block", "ssrf_protection": {"enabled": True}}
    snapshot_path.write_text(json.dumps(config), encoding="utf-8")
    args = _args(
        sandbox_command="config",
        sandbox_config_command="restore",
        runtime="container",
        name="demo",
        snapshot="latest",
    )
    target = object()

    with (
        patch.dict(
            os.environ,
            {"AI_GUARDIAN_STATE_DIR": str(tmp_path / "state")},
            clear=False,
        ),
        patch("ai_guardian.sandbox._sandbox_rest_target", return_value=target),
        patch(
            "ai_guardian.daemon.multi_client.MultiDaemonClient.write_config_bulk",
            return_value={"status": "ok"},
        ) as write_config,
    ):
        assert handle_sandbox_command(args) == 0

    write_config.assert_called_once_with(target, "global", config)


def test_sandbox_config_list_filters_runtime(tmp_path, capsys):
    state_root = tmp_path / "state" / "sandboxes" / "demo"
    for timestamp, runtime in (
        ("20260913T192805.123456Z", "container"),
        ("20260913T192806.123456Z", "openshell"),
    ):
        snapshot_dir = state_root / timestamp
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")
        (snapshot_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "sandbox_name": "demo",
                    "runtime": runtime,
                    "saved_at": timestamp,
                }
            ),
            encoding="utf-8",
        )
    args = _args(
        sandbox_command="config",
        sandbox_config_command="list",
        runtime="container",
        name="demo",
        json_output=True,
    )

    with patch.dict(
        os.environ,
        {"AI_GUARDIAN_STATE_DIR": str(tmp_path / "state")},
        clear=False,
    ):
        assert handle_sandbox_command(args) == 0

    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1
    assert records[0]["runtime"] == "container"


def test_latest_snapshot_is_scoped_to_requested_runtime(tmp_path):
    state_root = tmp_path / "state" / "sandboxes" / "demo"
    for timestamp, runtime, action in (
        ("20260913T192805.123456Z", "container", "container-action"),
        ("20260913T192806.123456Z", "openshell", "openshell-action"),
    ):
        snapshot_dir = state_root / timestamp
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "ai-guardian.json").write_text(
            json.dumps({"action": action}), encoding="utf-8"
        )
        (snapshot_dir / "metadata.json").write_text(
            json.dumps({"sandbox_name": "demo", "runtime": runtime}),
            encoding="utf-8",
        )

    with patch.dict(
        os.environ,
        {"AI_GUARDIAN_STATE_DIR": str(tmp_path / "state")},
        clear=False,
    ):
        snapshot_path, config = _load_snapshot_config("demo", runtime="container")

    assert snapshot_path.parent.name == "20260913T192805.123456Z"
    assert config == {"action": "container-action"}


def test_container_create_preserves_explicit_command():
    args = _args(
        sandbox_command="create",
        image="example/ai-guardian:test",
        command_args=["--", "ai-guardian", "daemon", "status"],
        profile=None,
        environment=[],
        label=[],
    )

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    assert run.call_args.args[0][-4:] == [
        "example/ai-guardian:test",
        "ai-guardian",
        "daemon",
        "status",
    ]


def test_openshell_automated_claude_print_gets_bare_without_shell_wrapper():
    args = _args(
        runtime="openshell",
        cli="claude",
        command_args=["--", "claude", "--print", "hello"],
    )

    assert _openshell_explicit_command(args) == [
        "claude",
        "--bare",
        "--print",
        "hello",
    ]


def test_openshell_interactive_claude_command_is_not_rewritten():
    args = _args(
        runtime="openshell",
        cli="claude",
        command_args=["--", "claude"],
    )

    assert _openshell_explicit_command(args) == ["claude"]


def test_openshell_explicit_opencode_command_uses_selected_agent_profile():
    args = _args(
        runtime="openshell",
        cli="opencode",
        opencode_agent="build",
        command_args=["--", "opencode", "run", "hello"],
    )

    assert _openshell_explicit_command(args) == [
        "opencode",
        "--agent",
        "build",
        "run",
        "hello",
    ]


def test_openshell_create_exposes_gateway_managed_service(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "ai-guardian.json").write_text("{}\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    policy = tmp_path / "policy.yaml"
    policy.write_text("version: 1\n", encoding="utf-8")
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="demo",
        cli="claude",
        profile=None,
        config_dir=str(config_dir),
        repo=str(repo),
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=["DEBUG=1"],
        policy=[str(policy)],
        provider=["ai-guardian-claude"],
        label=["team=security"],
    )

    with (
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
        patch(
            "ai_guardian.sandbox._expose_openshell_service", return_value=0
        ) as service,
    ):
        assert handle_sandbox_command(args) == 0

    service.assert_called_once_with(args, "demo", output=None)

    create_command = run.call_args_list[0].args[0]
    exec_command = run.call_args_list[1].args[0]
    shell_command = run.call_args_list[2].args[0]
    assert create_command[:5] == [
        "openshell",
        "sandbox",
        "create",
        "--from",
        "example/ai-guardian-openshell:test",
    ]
    assert "--detach" in create_command
    assert "--name" in create_command
    assert create_command[create_command.index("--name") + 1] == "demo"
    assert "ai-guardian.name=demo" in create_command
    assert [
        create_command[index + 1]
        for index, value in enumerate(create_command[:-1])
        if value == "--provider"
    ] == ["ai-guardian-claude"]
    policy_argument = create_command[create_command.index("--policy") + 1]
    assert Path(policy_argument).name == "policy.yaml"
    assert policy_argument != str(policy)
    assert f"{repo}:/sandbox/repo" in create_command
    assert "DEBUG=1" in create_command
    assert "--" not in create_command
    assert "--forward" not in create_command
    assert exec_command == [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        "demo",
        "--no-tty",
        "--workdir",
        "/sandbox/repo",
        "--",
        OPENSHELL_ENTRYPOINT,
        "/bin/true",
    ]
    assert shell_command == [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        "demo",
        "--tty",
        "--workdir",
        "/sandbox/repo",
        "--",
        "/bin/bash",
        "-l",
    ]


def test_openshell_create_composes_baseline_overlay_and_agent_policy(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text(
        "version: 1\nfilesystem_policy:\n  read_write: [/sandbox]\n"
        "network_policies:\n  base:\n    endpoints: []\n",
        encoding="utf-8",
    )
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    (agent_dir / "claude.yaml").write_text(
        "version: 1\nnetwork_policies:\n  claude:\n    endpoints: []\n",
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        "network_policies:\n  overlay:\n    endpoints: []\n",
        encoding="utf-8",
    )
    args = _args(policy=[str(overlay)])

    with patch.dict(
        os.environ,
        {
            "AI_GUARDIAN_OPEN_SHELL_BASE_POLICY": str(base),
            "AI_GUARDIAN_OPEN_SHELL_AGENT_POLICY_DIR": str(agent_dir),
        },
        clear=False,
    ):
        policy_path, policy_dir = _compose_openshell_policy(args, "claude")
        try:
            policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(policy_dir)

    assert policy["version"] == 1
    assert policy["filesystem_policy"]["read_write"] == ["/sandbox"]
    assert set(policy["network_policies"]) == {"base", "overlay", "claude"}


def test_openshell_create_adds_managed_policy_and_provider_modes(tmp_path):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="demo",
        cli="codex",
        config_dir=str(tmp_path / "config"),
        repo=None,
        profile=None,
        image="example/ai-guardian-openshell:test",
        environment=[],
        policy=[],
        provider=["codex-provider"],
        label=[],
    )

    with patch(
        "ai_guardian.sandbox._openshell_cli_has_credentials", return_value=False
    ):
        command, name, uploads, policy_dir = _openshell_create(args)
    try:
        assert name == "demo"
        assert uploads is False
        assert "--no-auto-providers" in command
        assert "--auto-providers" not in command
        assert command[command.index("--provider") + 1] == "codex-provider"
        assert Path(command[command.index("--policy") + 1]).name == "policy.yaml"
    finally:
        shutil.rmtree(policy_dir)


def test_openshell_opencode_provider_does_not_force_anthropic_route(tmp_path):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="opencode-demo",
        cli="opencode",
        model="gpt-5",
        config_dir=str(tmp_path / "config"),
        repo=None,
        profile=None,
        image="example/ai-guardian-openshell:test",
        environment=[],
        policy=[],
        provider=["opencode-provider"],
        label=[],
    )

    command, name, uploads, policy_dir = _openshell_create(args)
    try:
        assert name == "opencode-demo"
        assert uploads is False
        assert "AI_GUARDIAN_OPEN_SHELL_INFERENCE=true" not in command
        assert "ANTHROPIC_BASE_URL=https://inference.local/v1" not in command
        assert "ANTHROPIC_API_KEY=unused" not in command
        assert command[command.index("--provider") + 1] == "opencode-provider"
        assert "--no-credential-warnings" not in command
    finally:
        shutil.rmtree(policy_dir)


def test_openshell_opencode_claude_agent_uses_anthropic_route(tmp_path):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="opencode-claude-demo",
        cli="opencode",
        opencode_agent="claude",
        config_dir=str(tmp_path / "config"),
        repo=None,
        profile=None,
        image="example/ai-guardian-openshell:test",
        environment=[],
        policy=[],
        provider=["vertex-provider"],
        label=[],
    )

    with patch("ai_guardian.sandbox._configure_openshell_inference") as configure:
        command, name, uploads, policy_dir = _openshell_create(args)
    try:
        assert name == "opencode-claude-demo"
        assert uploads is False
        assert "AI_GUARDIAN_OPENCODE_AGENT=claude" in command
        assert "AI_GUARDIAN_OPEN_SHELL_INFERENCE=true" in command
        assert "ANTHROPIC_BASE_URL=https://inference.local/v1" in command
        assert "ANTHROPIC_API_KEY=unused" in command
        assert command[command.index("--provider") + 1] == "vertex-provider"
        assert "--no-credential-warnings" in command
        configure.assert_called_once()
    finally:
        shutil.rmtree(policy_dir)


def test_openshell_opencode_claude_model_uses_anthropic_route(tmp_path):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="opencode-model-demo",
        cli="opencode",
        opencode_agent="build",
        model="claude-sonnet-4-6",
        config_dir=str(tmp_path / "config"),
        repo=None,
        profile=None,
        image="example/ai-guardian-openshell:test",
        environment=[],
        policy=[],
        provider=["vertex-provider"],
        label=[],
    )

    with patch("ai_guardian.sandbox._configure_openshell_inference") as configure:
        command, name, uploads, policy_dir = _openshell_create(args)
    try:
        assert name == "opencode-model-demo"
        assert uploads is False
        assert "AI_GUARDIAN_OPENCODE_AGENT=build" in command
        assert "ANTHROPIC_BASE_URL=https://inference.local/v1" in command
        assert "--no-credential-warnings" in command
        configure.assert_called_once()
    finally:
        shutil.rmtree(policy_dir)


def test_openshell_opencode_default_model_uses_anthropic_route(tmp_path):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="opencode-default-model-demo",
        cli="opencode",
        opencode_agent="build",
        config_dir=str(tmp_path / "config"),
        repo=None,
        profile=None,
        image="example/ai-guardian-openshell:test",
        environment=[],
        policy=[],
        provider=["vertex-provider"],
        label=[],
    )

    with patch("ai_guardian.sandbox._configure_openshell_inference") as configure:
        command, name, uploads, policy_dir = _openshell_create(args)
    try:
        assert name == "opencode-default-model-demo"
        assert uploads is False
        assert "AI_GUARDIAN_OPENCODE_AGENT=build" in command
        assert "AI_GUARDIAN_OPEN_SHELL_INFERENCE=true" in command
        assert "ANTHROPIC_BASE_URL=https://inference.local/v1" in command
        assert "ANTHROPIC_API_KEY=unused" in command
        assert "--no-credential-warnings" in command
        configure.assert_called_once()
    finally:
        shutil.rmtree(policy_dir)


def test_openshell_provider_environment_bridges_codex_oauth_without_command_leak(
    tmp_path,
):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "account_id": "account-secret",
                    "id_token": "id-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    args = _args(environment=[])

    with patch.dict(
        os.environ, {"HOME": str(tmp_path), "CODEX_HOME": str(codex_home)}, clear=False
    ):
        environment = _openshell_provider_environment(args, "codex")

    assert environment["CODEX_AUTH_ACCESS_TOKEN"] == "access-secret"
    assert environment["CODEX_AUTH_REFRESH_TOKEN"] == "refresh-secret"
    assert environment["CODEX_AUTH_ACCOUNT_ID"] == "account-secret"
    assert environment["CODEX_AUTH_ID_TOKEN"] == "id-secret"
    with (
        patch(
            "ai_guardian.sandbox._openshell_provider_profiles",
            return_value=["codex"],
        ),
        patch("ai_guardian.sandbox._openshell_provider_exists", return_value=False),
        patch("ai_guardian.sandbox._openshell_providers_v2_enabled", return_value=True),
        patch("ai_guardian.sandbox._run", return_value=0) as run,
        patch.dict(
            os.environ,
            {"HOME": str(tmp_path), "CODEX_HOME": str(codex_home)},
            clear=False,
        ),
    ):
        assert _ensure_openshell_cli_provider(args, "codex") == "ai-guardian-codex"

    command = run.call_args.args[0]
    assert "access-secret" not in command
    assert run.call_args.kwargs["env"]["CODEX_AUTH_ACCESS_TOKEN"] == "access-secret"


def test_openshell_provider_environment_bridges_codex_api_key_without_command_leak(
    tmp_path,
):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "apikey",
                "OPENAI_API_KEY": "api-secret",
            }
        ),
        encoding="utf-8",
    )
    args = _args(environment=[f"CODEX_HOME={codex_home}"])

    with (
        patch(
            "ai_guardian.sandbox._openshell_provider_profiles",
            return_value=["codex"],
        ),
        patch("ai_guardian.sandbox._openshell_provider_exists", return_value=False),
        patch("ai_guardian.sandbox._run", return_value=0) as run,
        patch.dict(
            os.environ,
            {"HOME": str(tmp_path)},
            clear=True,
        ),
    ):
        assert _ensure_openshell_cli_provider(args, "codex") == "ai-guardian-codex"

    command = run.call_args.args[0]
    assert "api-secret" not in command
    assert command[command.index("--credential") + 1] == "OPENAI_API_KEY"
    assert "--from-existing" not in command
    assert run.call_args.kwargs["env"]["OPENAI_API_KEY"] == "api-secret"


def test_openshell_vertex_provider_uses_adc_and_default_model(tmp_path):
    adc_path = tmp_path / ".config" / "gcloud" / "application_default_credentials.json"
    adc_path.parent.mkdir(parents=True)
    adc_path.write_text("{}\n", encoding="utf-8")
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="vertex-demo",
        cli="claude",
        profile=None,
        config_dir=str(tmp_path / "config"),
        repo=None,
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
    )

    with (
        patch.dict(
            os.environ,
            {
                "HOME": str(tmp_path),
                "USERPROFILE": str(tmp_path),
                "ANTHROPIC_VERTEX_PROJECT_ID": "test-project",
                "CLOUD_ML_REGION": "us-central1",
            },
            clear=True,
        ),
        patch(
            "ai_guardian.sandbox._openshell_provider_profiles",
            return_value=["google-vertex-ai"],
        ),
        patch("ai_guardian.sandbox._openshell_provider_exists", return_value=False),
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    provider_create = run.call_args_list[0]
    assert provider_create.args[0] == [
        "openshell",
        "provider",
        "create",
        "--name",
        "ai-guardian-google-vertex-ai",
        "--type",
        "google-vertex-ai",
        "--from-gcloud-adc",
        "--config",
        "VERTEX_AI_PROJECT_ID=test-project",
        "--config",
        "VERTEX_AI_REGION=us-central1",
    ]
    assert provider_create.kwargs["env"]["GOOGLE_APPLICATION_CREDENTIALS"] == str(
        adc_path
    )
    assert run.call_args_list[1].args[0] == [
        "openshell",
        "inference",
        "set",
        "--provider",
        "ai-guardian-google-vertex-ai",
        "--model",
        "claude-sonnet-4-6",
        "--no-verify",
    ]
    create_command = run.call_args_list[2].args[0]
    assert "AI_GUARDIAN_OPEN_SHELL_INFERENCE=true" in create_command
    assert "ANTHROPIC_BASE_URL=https://inference.local" in create_command
    assert "ANTHROPIC_API_KEY=unused" in create_command
    assert "--provider" in create_command
    assert "ai-guardian-google-vertex-ai" in create_command
    assert "--no-credential-warnings" in create_command
    assert str(adc_path) not in create_command


def test_openshell_vertex_provider_updates_explicit_provider_and_model(tmp_path):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="vertex-demo",
        cli="claude",
        model="claude-haiku-4-5",
        profile=None,
        config_dir=str(tmp_path / "config"),
        repo=None,
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=["vertex-provider"],
        label=[],
    )

    with (
        patch.dict(
            os.environ,
            {
                "HOME": str(tmp_path),
                "USERPROFILE": str(tmp_path),
                "ANTHROPIC_VERTEX_PROJECT_ID": "test-project",
                "CLOUD_ML_REGION": "global",
            },
            clear=True,
        ),
        patch(
            "ai_guardian.sandbox._configure_openshell_vertex_provider"
        ) as configure_provider,
        patch(
            "ai_guardian.sandbox._configure_openshell_inference"
        ) as configure_inference,
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ),
    ):
        assert handle_sandbox_command(args) == 0

    configure_provider.assert_called_once_with(
        args,
        "vertex-provider",
        "test-project",
        "global",
        output=None,
    )
    configure_inference.assert_called_once_with(
        args, "vertex-provider", "claude-haiku-4-5", output=None
    )


def test_openshell_create_uses_latest_saved_config_snapshot(tmp_path):
    state_dir = tmp_path / "state"
    snapshot_dir = state_dir / "sandboxes" / "demo" / "20260913T192805.123456Z"
    snapshot_dir.mkdir(parents=True)
    snapshot_path = snapshot_dir / "ai-guardian.json"
    snapshot_path.write_text('{"action": "ask"}\n', encoding="utf-8")
    (snapshot_dir / "metadata.json").write_text(
        json.dumps({"sandbox_name": "demo", "runtime": "openshell"}),
        encoding="utf-8",
    )
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="demo",
        cli="claude",
        restore_config="latest",
        config_dir=None,
        repo=None,
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
    )

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_STATE_DIR": str(state_dir)}, clear=False),
        patch(
            "ai_guardian.sandbox._ensure_openshell_cli_provider",
            return_value="ai-guardian-claude",
        ),
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    create_command = run.call_args_list[0].args[0]
    assert (
        f"{snapshot_path}:{'/sandbox/.config/ai-guardian.host.json'}" in create_command
    )
    assert "AI_GUARDIAN_RESTORE_CONFIG=true" in create_command


def test_openshell_create_invokes_entrypoint_without_uploads(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="demo",
        cli="codex",
        profile=None,
        config_dir=str(config_dir),
        repo=None,
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
    )

    with (
        patch("ai_guardian.sandbox._openshell_cli_has_credentials", return_value=False),
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    assert run.call_args_list[0].args[0][-4:] == [
        "--",
        OPENSHELL_ENTRYPOINT,
        "bash",
        "-l",
    ]
    assert run.call_args_list[1].args[0] == [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        "demo",
        "--tty",
        "--",
        "/bin/bash",
        "-l",
    ]


def test_programmatic_openshell_create_skips_interactive_shell_and_captures_output(
    tmp_path,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="demo",
        cli="claude",
        profile=None,
        config_dir=str(config_dir),
        repo=None,
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
    )
    output = []

    with (
        patch("ai_guardian.sandbox._openshell_cli_has_credentials", return_value=False),
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout="created\n", stderr=""
            ),
        ) as run,
    ):
        assert create_sandbox(args, interactive=False, output=output) == 0

    assert output == ["created\n"]
    assert run.call_count == 1
    command = run.call_args.args[0]
    assert command[:5] == [
        "openshell",
        "sandbox",
        "create",
        "--from",
        "example/ai-guardian-openshell:test",
    ]
    assert "DISABLE_AUTOUPDATER=1" in command
    assert "AI_GUARDIAN_HOST_CONFIG_MOUNTED=false" in command
    assert "--auto-providers" in command
    assert Path(command[command.index("--policy") + 1]).name == "policy.yaml"
    assert command[-4:] == ["--", OPENSHELL_ENTRYPOINT, "bash", "-l"]


def test_openshell_create_stages_uploads_before_entrypoint_exec(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "ai-guardian.json").write_text("{}\n", encoding="utf-8")
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name=None,
        cli="codex",
        profile=None,
        config_dir=str(config_dir),
        repo=None,
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
    )

    with (
        patch(
            "ai_guardian.sandbox._ensure_openshell_cli_provider",
            return_value="ai-guardian-codex",
        ),
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    create_command = run.call_args_list[0].args[0]
    exec_command = run.call_args_list[1].args[0]
    shell_command = run.call_args_list[2].args[0]
    generated_name = create_command[create_command.index("--name") + 1]
    assert generated_name.startswith("ag-codex-")
    assert len(generated_name) <= 19
    assert "--" not in create_command
    assert exec_command == [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        generated_name,
        "--no-tty",
        "--",
        OPENSHELL_ENTRYPOINT,
        "/bin/true",
    ]
    assert shell_command == [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        generated_name,
        "--tty",
        "--",
        "/bin/bash",
        "-l",
    ]


def test_openshell_create_runs_explicit_command_after_bootstrap(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "ai-guardian.json").write_text("{}\n", encoding="utf-8")
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        name="demo",
        cli="claude",
        profile=None,
        config_dir=str(config_dir),
        repo=None,
        port=None,
        image="example/ai-guardian-openshell:test",
        api_key=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
        command_args=["--", "ai-guardian", "daemon", "status"],
    )

    with (
        patch(
            "ai_guardian.sandbox._ensure_openshell_cli_provider",
            return_value="ai-guardian-claude",
        ),
        patch(
            "ai_guardian.sandbox._expose_openshell_service", return_value=0
        ) as service,
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    assert run.call_args_list[1].args[0] == [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        "demo",
        "--no-tty",
        "--",
        OPENSHELL_ENTRYPOINT,
        "/bin/true",
    ]
    assert run.call_args_list[2].args[0] == [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        "demo",
        "--no-tty",
        "--",
        "ai-guardian",
        "daemon",
        "status",
    ]
    service.assert_called_once_with(args, "demo", output=None)


def test_openshell_create_does_not_put_api_keys_in_runtime_arguments(capsys):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        api_key="sensitive-test-value",
        profile=None,
        environment=[],
        policy=[],
        provider=[],
        label=[],
        name="demo",
        image="example/ai-guardian-openshell:test",
        port=None,
        repo=None,
        config_dir=None,
        command_args=[],
    )

    with (
        patch(
            "ai_guardian.sandbox._ensure_openshell_cli_provider",
            return_value="ai-guardian-claude",
        ),
        patch("ai_guardian.sandbox._expose_openshell_service", return_value=0),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    for call in run.call_args_list:
        assert "sensitive-test-value" not in call.args[0]
    assert "sensitive-test-value" not in capsys.readouterr().out


def test_openshell_expose_uses_gateway_managed_service():
    args = _args(runtime="openshell", port=None)
    service_url = "http://demo--ai-guardian.openshell.localhost:43152/"

    with (
        patch("ai_guardian.sandbox._run", return_value=0) as run,
        patch(
            "ai_guardian.sandbox._get_openshell_service_url",
            return_value=service_url,
        ) as get_service,
    ):
        assert _expose_openshell_service(args, "demo") == 0

    run.assert_called_once_with(
        [
            "openshell",
            "service",
            "expose",
            "demo",
            "63152",
            "ai-guardian",
        ],
        output=[],
    )
    get_service.assert_called_once_with(args, "demo")


def test_openshell_expose_captures_service_url_from_cli_output():
    args = _args(runtime="openshell", port=None)
    service_url = "http://demo--ai-guardian.openshell.localhost:43152/"
    output = []

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=f"Service URL: {service_url}\n", stderr=""
        ),
    ) as run:
        assert _expose_openshell_service(args, "demo", output=output) == 0

    assert service_url in "".join(output)
    assert "OpenShell AI Guardian service:" in "".join(output)
    run.assert_called_once_with(
        [
            "openshell",
            "service",
            "expose",
            "demo",
            "63152",
            "ai-guardian",
        ],
        env=None,
        capture_output=True,
        text=True,
        check=False,
    )


def test_openshell_start_ensures_gateway_managed_service():
    args = _args(sandbox_command="start", runtime="openshell", name="demo")

    with (
        patch(
            "ai_guardian.sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run,
        patch("ai_guardian.sandbox._ensure_openshell_daemon", return_value=0),
        patch(
            "ai_guardian.sandbox._ensure_openshell_service", return_value=0
        ) as service,
    ):
        assert handle_sandbox_command(args) == 0

    assert run.call_args.args[0] == ["openshell", "sandbox", "start", "demo"]
    service.assert_called_once_with(args, "demo", output=None)


def test_openshell_stop_does_not_manage_a_host_forward():
    args = _args(sandbox_command="stop", runtime="openshell", name="demo")

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0),
    ) as run:
        assert handle_sandbox_command(args) == 0

    run.assert_called_once_with(
        ["openshell", "sandbox", "stop", "demo"],
        env=None,
        check=False,
    )


def test_openshell_delete_removes_gateway_service_before_sandbox():
    args = _args(sandbox_command="delete", runtime="openshell", name="demo")

    with (
        patch(
            "ai_guardian.sandbox._get_openshell_service_url",
            return_value="http://demo--ai-guardian.openshell.localhost:43152/",
        ),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run,
    ):
        assert handle_sandbox_command(args) == 0

    assert [call.args[0] for call in run.call_args_list] == [
        ["openshell", "service", "delete", "demo", "ai-guardian"],
        ["openshell", "sandbox", "delete", "demo"],
    ]


def test_sandbox_command_is_registered_without_daemon_autostart():
    from ai_guardian.cli import main

    with (
        patch(
            "sys.argv",
            ["ai-guardian", "sandbox", "status", "demo", "--runtime", "openshell"],
        ),
        patch("ai_guardian.cli._ensure_daemon_started") as start,
        patch("ai_guardian.cli.handle_sandbox_command", return_value=0) as handler,
    ):
        assert main() == 0

    start.assert_not_called()
    args = handler.call_args.args[0]
    assert args.command == "sandbox"
    assert args.sandbox_command == "status"
    assert args.runtime == "openshell"
    assert args.name == "demo"


def test_sandbox_create_accepts_latest_config_restore_option():
    from ai_guardian.cli import main

    with (
        patch(
            "sys.argv",
            [
                "ai-guardian",
                "sandbox",
                "create",
                "--runtime",
                "container",
                "--name",
                "demo",
                "--restore-config",
                "latest",
            ],
        ),
        patch("ai_guardian.cli._ensure_daemon_started") as start,
        patch("ai_guardian.cli.handle_sandbox_command", return_value=0) as handler,
    ):
        assert main() == 0

    start.assert_not_called()
    args = handler.call_args.args[0]
    assert args.restore_config == "latest"


def test_sandbox_port_must_be_between_one_and_65535():
    from ai_guardian.cli import main

    with patch(
        "sys.argv",
        ["ai-guardian", "sandbox", "create", "--runtime", "container", "--port", "0"],
    ):
        with pytest.raises(SystemExit) as error:
            main()

    assert error.value.code == 2


def test_create_rejects_malformed_explicit_image_reference(capsys):
    args = _args(
        sandbox_command="create",
        runtime="openshell",
        image="localhost:ai-guardian:openshell",
    )

    with patch("ai_guardian.sandbox.subprocess.run") as run:
        assert handle_sandbox_command(args) == 2

    run.assert_not_called()
    assert "invalid image reference" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("runtime", "container_engine", "openshell_cli", "missing"),
    (
        (
            "container",
            "definitely-missing-podman",
            "openshell",
            "definitely-missing-podman",
        ),
        (
            "container",
            "definitely-missing-docker",
            "openshell",
            "definitely-missing-docker",
        ),
        (
            "openshell",
            "podman",
            "definitely-missing-openshell",
            "definitely-missing-openshell",
        ),
    ),
)
def test_missing_runtime_executable_returns_shell_not_found(
    runtime, container_engine, openshell_cli, missing, capsys
):
    args = _args(
        sandbox_command="status",
        runtime=runtime,
        container_engine=container_engine,
        openshell_cli=openshell_cli,
    )

    with patch(
        "ai_guardian.sandbox.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert handle_sandbox_command(args) == 127

    assert f"required executable was not found: {missing}" in capsys.readouterr().err


def test_auto_detection_reports_missing_runtime_executables(capsys):
    args = _args(sandbox_command="status", runtime=None)

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_SANDBOX_RUNTIME": ""}),
        patch(
            "ai_guardian.sandbox.subprocess.run",
            side_effect=FileNotFoundError,
        ),
        patch("ai_guardian.sandbox.shutil.which", return_value=None),
    ):
        assert handle_sandbox_command(args) == 2

    error = capsys.readouterr().err
    assert "could not auto-detect runtime for sandbox 'demo'" in error
    assert "container (podman)" in error
    assert "openshell (openshell)" in error


def test_list_reports_missing_runtime_when_other_runtime_is_available(capsys):
    args = _args(sandbox_command="list", runtime=None)
    del args.name

    def fake_run(command, **kwargs):
        if command[0] == "podman":
            raise FileNotFoundError
        return subprocess.CompletedProcess(command, 0, stdout="openshell-list\n")

    def fake_which(executable):
        return None if executable == "podman" else f"/usr/bin/{executable}"

    with (
        patch.dict(os.environ, {"AI_GUARDIAN_SANDBOX_RUNTIME": ""}),
        patch("ai_guardian.sandbox.subprocess.run", side_effect=fake_run),
        patch("ai_guardian.sandbox.shutil.which", side_effect=fake_which),
    ):
        assert handle_sandbox_command(args) == 0

    assert (
        "Warning: container: required executable was not found: podman"
        in capsys.readouterr().err
    )
