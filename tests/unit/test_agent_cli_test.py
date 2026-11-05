"""Contracts for the credential-free real-agent CLI hook smoke check."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "agent_cli_test.py"
MOCK_PATH = ROOT / "scripts" / "agent_cli_mock_provider.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-readiness.yml"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_agent_cli_matrix_covers_core_violation_and_allow_paths():
    runner = _load(RUNNER_PATH, "agent_cli_smoke_runner")

    assert {case.name for case in runner.CASES} == {
        "prompt_injection",
        "secret",
        "pii",
        "ssrf",
        "config_exfil",
        "clean_tool",
        "tool_output_secret",
        "tool_output_pii",
        "allowed",
    }
    assert all(
        case.expected_violation
        for case in runner.CASES
        if case.name not in ("allowed", "clean_tool")
    )
    assert runner.CASES[-1].expected_violation is None
    assert [case.expects_provider for case in runner.CASES] == [
        False,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
    ]


def test_agent_cli_invocations_use_native_noninteractive_clients():
    runner = _load(RUNNER_PATH, "agent_cli_smoke_commands")

    assert runner.build_agent_command("codex", "smoke", "hello") == [
        "codex",
        "exec",
        "--profile",
        "smoke",
        "--json",
        "--skip-git-repo-check",
        "hello",
    ]
    assert runner.build_agent_command("opencode", "build", "hello") == [
        "opencode",
        "run",
        "--agent",
        "build",
        "--auto",
        "--format",
        "json",
        "--model",
        "ai_guardian_smoke/ag-smoke",
        "hello",
    ]
    assert runner.build_agent_command(
        "opencode",
        "build",
        "hello",
        opencode_attach_url="http://127.0.0.1:4096",
    ) == [
        "opencode",
        "run",
        "--attach",
        "http://127.0.0.1:4096",
        "--dir",
        "/sandbox/repo",
        "--agent",
        "build",
        "--auto",
        "--format",
        "json",
        "--model",
        "ai_guardian_smoke/ag-smoke",
        "hello",
    ]
    assert runner.build_agent_command(
        "opencode", "build", "hello", opencode_v2=True
    ) == [
        "opencode",
        "run",
        "--standalone",
        "--agent",
        "build",
        "--auto",
        "--format",
        "json",
        "--model",
        "ai_guardian_smoke/ag-smoke",
        "hello",
    ]
    assert runner.build_agent_command("pi", "openai", "hello") == [
        "pi",
        "-p",
        "hello",
        "--model",
        "ag-smoke",
        "--provider",
        "openai",
    ]
    assert runner.build_agent_command("claude", "default", "hello") == [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--model",
        runner.MOCK_ANTHROPIC_MODEL,
        "hello",
    ]
    gemini_command = runner.build_agent_command("gemini", "default", "hello")
    assert gemini_command == [
        "gemini",
        "--prompt",
        "hello",
        "--model",
        runner.MOCK_GEMINI_MODEL,
        "--output-format",
        "json",
        "--skip-trust",
        "--approval-mode",
        "yolo",
    ]
    claude_environment = runner.build_agent_environment("claude")
    assert f"ANTHROPIC_BASE_URL={runner.MOCK_ANTHROPIC_BASE_URL}" in claude_environment
    assert f"ANTHROPIC_API_KEY={runner.MOCK_KEY}" in claude_environment
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1" in claude_environment
    assert all("OPENAI_API_KEY=" not in item for item in claude_environment)
    opencode_environment = runner.build_agent_environment("opencode")
    assert "OPENCODE_DISABLE_AUTOUPDATE=true" in opencode_environment
    assert "OPENCODE_DISABLE_MODELS_FETCH=true" in opencode_environment
    assert "OPENCODE_CONFIG=/sandbox/.config/opencode/opencode.json" in (
        opencode_environment
    )
    gemini_environment = runner.build_agent_environment("gemini")
    assert "GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:18765" in gemini_environment
    assert f"GEMINI_API_KEY={runner.MOCK_KEY}" in gemini_environment
    assert all("GOOGLE_API_KEY=" not in item for item in gemini_environment)


def test_sandbox_create_uses_supplied_image_strict_profile_and_isolated_workspace(
    tmp_path,
):
    runner = _load(RUNNER_PATH, "agent_cli_smoke_create")
    profile = tmp_path / "strict.json"
    workspace = tmp_path / "workspace"
    command = runner.build_create_command(
        ["ai-guardian"],
        "docker",
        "opencode",
        "build",
        "ai-guardian-current-wheel",
        profile,
        workspace,
        "ag-cli-smoke-opencode-test",
        container_network="ag-cli-smoke-opencode-test-internal",
    )

    assert command[:4] == ["ai-guardian", "sandbox", "create", "--runtime"]
    assert "container" in command
    assert command[command.index("--image") + 1] == "ai-guardian-current-wheel"
    assert command[command.index("--profile") + 1] == str(profile)
    assert command[command.index("--repo") + 1] == str(workspace)
    assert command[command.index("--agent") + 1] == "build"
    assert (
        command[command.index("--container-network") + 1]
        == "ag-cli-smoke-opencode-test-internal"
    )
    assert "OPENAI_API_KEY" not in " ".join(command)


def test_internal_network_command_requests_runtime_egress_isolation():
    runner = _load(RUNNER_PATH, "agent_cli_smoke_internal_network")

    assert runner.internal_network_name("ag-cli-smoke-codex-1234abcd") == (
        "ag-cli-smoke-codex-1234abcd-internal"
    )
    assert runner.create_internal_network_command(
        "docker", "ag-cli-smoke-codex-1234abcd-internal"
    ) == [
        "docker",
        "network",
        "create",
        "--internal",
        "ag-cli-smoke-codex-1234abcd-internal",
    ]


def test_podman_smoke_uses_normal_bridge_without_agent_capabilities(tmp_path):
    runner = _load(RUNNER_PATH, "agent_cli_smoke_firewall_container")
    command = runner.build_podman_create_command(
        "podman",
        "opencode",
        "build",
        "localhost/smoke:test",
        tmp_path / "strict.json",
        tmp_path / "workspace",
        "ag-cli-smoke-opencode-1234abcd",
    )
    assert command[:2] == ["podman", "run"]
    assert command[command.index("--network") + 1] == "bridge"
    assert command[command.index("--userns") + 1] == "keep-id:uid=1000,gid=1000"
    assert command[command.index("--user") + 1] == "1000:1000"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "--cap-add" not in command
    assert "--privileged" not in command
    assert "no-new-privileges" in command
    assert (
        command[command.index("--entrypoint") + 1]
        == "/usr/local/bin/agent_cli_smoke_gate.py"
    )
    assert "127.0.0.1::63152" in command
    assert "AI_GUARDIAN_OPENCODE_AGENT=build" in command
    assert f"AI_GUARDIAN_STATE_DIR={runner.STATE_DIR}" in command
    assert "ai-guardian.daemon=true" in command
    assert "OPENAI_API_KEY" not in " ".join(command)
    assert runner._is_podman_engine("podman")
    assert runner._is_podman_engine("/usr/bin/podman")
    assert not runner._is_podman_engine("docker")


@pytest.mark.parametrize("keep", (False, True))
@pytest.mark.parametrize(
    ("engine", "uses_firewall"),
    (("podman", True), ("docker", False)),
)
def test_main_sets_up_smoke_isolation_and_cleans_up(
    engine, uses_firewall, keep, monkeypatch, tmp_path
):
    runner = _load(RUNNER_PATH, f"agent_cli_smoke_lifecycle_{engine}_{keep}")
    runner._temp_parent = lambda: tmp_path
    runner.sanitized_host_environment = lambda _home: {"HOME": str(tmp_path)}
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/available")
    runner._wait_for_sandbox_ready = lambda *_args, **_kwargs: True
    runner._check_sandbox_rest = lambda *_args, **_kwargs: True
    runner._configure_agent = lambda *_args, **_kwargs: True
    runner._start_mock = lambda *_args, **_kwargs: True
    runner._run_case = lambda *_args, **_kwargs: True
    runner._check_podman_smoke_image = lambda *_args, **_kwargs: True
    firewall_calls = []
    runner._setup_podman_firewall = lambda *args: firewall_calls.append(args) or True

    commands = []

    def fake_run(command, *_args, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runner._run = fake_run
    deleted = []
    runner._delete_sandbox = lambda *args: deleted.append(args[2])

    argv = [
        "--cli-name",
        "codex",
        "--agent",
        "smoke",
        "--image",
        "localhost/smoke:test",
        "--container-engine",
        engine,
        "--ai-guardian-command",
        "ai-guardian",
    ]
    if keep:
        argv.append("--keep")

    assert runner.main(argv) == 0

    if uses_firewall:
        assert not any(command[1:2] == ["network"] for command in commands)
        assert any(command[:2] == [engine, "run"] for command in commands)
        assert len(firewall_calls) == 1
    else:
        network_create = next(
            index
            for index, command in enumerate(commands)
            if command[:3] == [engine, "network", "create"]
        )
        sandbox_create = next(
            index
            for index, command in enumerate(commands)
            if command[:3] == ["ai-guardian", "sandbox", "create"]
        )
        assert network_create < sandbox_create
        create_command = commands[sandbox_create]
        sandbox_network = create_command[
            create_command.index("--container-network") + 1
        ]
        assert commands[network_create] == [
            engine,
            "network",
            "create",
            "--internal",
            sandbox_network,
        ]
        assert sandbox_network.endswith("-internal")
        assert firewall_calls == []
    network_remove = [
        command for command in commands if command[:3] == [engine, "network", "rm"]
    ]
    assert len(network_remove) == (0 if keep or uses_firewall else 1)
    assert bool(deleted) is not keep
    assert not any(command[1:3] == ["network", "connect"] for command in commands)


def test_main_starts_one_opencode_v1_server_for_all_cases(monkeypatch, tmp_path):
    runner = _load(RUNNER_PATH, "agent_cli_smoke_opencode_v1_server")
    runner._temp_parent = lambda: tmp_path
    runner.sanitized_host_environment = lambda _home: {"HOME": str(tmp_path)}
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/available")
    runner._wait_for_sandbox_ready = lambda *_args, **_kwargs: True
    runner._check_sandbox_rest = lambda *_args, **_kwargs: True
    runner._configure_agent = lambda *_args, **_kwargs: True
    runner._start_mock = lambda *_args, **_kwargs: True
    runner._opencode_uses_v2 = lambda *_args: False
    runner._check_podman_smoke_image = lambda *_args: True
    runner._setup_podman_firewall = lambda *_args: True
    server_starts = []
    runner._start_opencode_v1_server = lambda *args: server_starts.append(args) or True
    warmups = []
    runner._warm_opencode_v1_server = lambda *args: warmups.append(args) or True
    case_calls = []
    runner._run_case = lambda *args, **kwargs: case_calls.append(kwargs) or True

    def fake_run(command, *_args, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runner._run = fake_run
    runner._delete_sandbox = lambda *_args: None

    assert (
        runner.main(
            [
                "--cli-name",
                "opencode",
                "--agent",
                "build",
                "--image",
                "localhost/smoke:test",
                "--container-engine",
                "podman",
                "--ai-guardian-command",
                "ai-guardian",
            ]
        )
        == 0
    )

    assert len(server_starts) == 1
    assert server_starts[0][0] == "podman"
    assert len(warmups) == 1
    assert warmups[0][0] == "podman"
    assert len(case_calls) == len(runner.CASES)
    assert all(
        call["opencode_attach_url"] == runner.OPENCODE_SERVER_URL for call in case_calls
    )


def test_opencode_v1_server_starts_detached_and_waits_for_health(monkeypatch):
    runner = _load(RUNNER_PATH, "agent_cli_opencode_v1_server_start")
    commands = []
    probes = []

    def fake_run(command, *_args, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def fake_exec(engine, name, command, *_args, **_kwargs):
        probes.append((engine, name, list(command)))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner, "_exec", fake_exec)

    assert runner._start_opencode_v1_server("podman", "smoke", 30)

    command = commands[0]
    assert command[:3] == ["podman", "exec", "--detach"]
    assert "OPENCODE_DISABLE_AUTOUPDATE=true" in command
    assert "OPENCODE_DISABLE_MODELS_FETCH=true" in command
    assert command[-6:] == [
        "opencode",
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        str(runner.OPENCODE_SERVER_PORT),
    ]
    assert probes[0][0:2] == ("podman", "smoke")
    assert probes[0][2][-1] == f"{runner.OPENCODE_SERVER_URL}/global/health"


def test_opencode_v1_warmup_uses_clean_case_and_local_provider(monkeypatch):
    runner = _load(RUNNER_PATH, "agent_cli_opencode_v1_warmup")
    violations = iter(({}, {}))
    requests = iter(({"allowed": 0}, {"allowed": 1}))
    commands = []

    monkeypatch.setattr(
        runner, "_violation_counts", lambda *_args, **_kwargs: next(violations)
    )
    monkeypatch.setattr(
        runner, "_provider_stats", lambda *_args, **_kwargs: next(requests)
    )

    def fake_exec(_engine, _name, command, *_args, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_exec", fake_exec)

    assert runner._warm_opencode_v1_server("podman", "smoke", "build", 30)

    assert commands[0][0:4] == [
        "opencode",
        "run",
        "--attach",
        runner.OPENCODE_SERVER_URL,
    ]
    assert "AGENT_CLI_SMOKE_CASE: allowed" in commands[0][-1]


def test_opencode_v1_warmup_fails_if_clean_case_creates_a_violation(monkeypatch):
    runner = _load(RUNNER_PATH, "agent_cli_opencode_v1_warmup_violation")
    violations = iter(({}, {"prompt_injection": 1}))
    requests = iter(({"allowed": 0}, {"allowed": 1}))
    monkeypatch.setattr(
        runner, "_violation_counts", lambda *_args, **_kwargs: next(violations)
    )
    monkeypatch.setattr(
        runner, "_provider_stats", lambda *_args, **_kwargs: next(requests)
    )
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda _engine, _name, command, *_args, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        ),
    )

    assert not runner._warm_opencode_v1_server("podman", "smoke", "build", 30)


def test_main_removes_smoke_network_when_sandbox_creation_fails(monkeypatch, tmp_path):
    runner = _load(RUNNER_PATH, "agent_cli_smoke_network_cleanup_on_failure")
    runner._temp_parent = lambda: tmp_path
    runner.sanitized_host_environment = lambda _home: {"HOME": str(tmp_path)}
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/available")
    commands = []

    def fake_run(command, *_args, **_kwargs):
        commands.append(list(command))
        code = 1 if command[:3] == ["ai-guardian", "sandbox", "create"] else 0
        if command[:2] == ["docker", "inspect"]:
            code = 1
        return subprocess.CompletedProcess(command, code, stdout="", stderr="failed")

    runner._run = fake_run
    runner._delete_sandbox = lambda *_args: pytest.fail(
        "a nonexistent sandbox should not be deleted"
    )

    assert (
        runner.main(
            [
                "--cli-name",
                "codex",
                "--agent",
                "smoke",
                "--image",
                "localhost/smoke:test",
                "--container-engine",
                "docker",
                "--ai-guardian-command",
                "ai-guardian",
            ]
        )
        == 1
    )

    assert (
        len(
            [
                command
                for command in commands
                if command[:3] == ["docker", "network", "rm"]
            ]
        )
        == 1
    )


def test_container_engine_prefers_docker_then_falls_back_to_podman(
    monkeypatch,
):
    runner = _load(RUNNER_PATH, "agent_cli_container_engine")
    monkeypatch.delenv("CONTAINER_ENGINE", raising=False)
    available = {"podman": "/usr/bin/podman"}
    monkeypatch.setattr(runner.shutil, "which", lambda name: available.get(name))

    assert runner._default_container_engine() == "podman"

    available["docker"] = "/usr/bin/docker"
    assert runner._default_container_engine() == "docker"

    monkeypatch.setenv("CONTAINER_ENGINE", "podman-custom")
    assert runner._default_container_engine() == "podman-custom"


def test_temporary_podman_image_names_are_qualified_as_local():
    runner = _load(RUNNER_PATH, "agent_cli_local_image_reference")

    assert runner.temporary_image_reference("podman", "abc123") == (
        "localhost/ai-guardian-agent-cli-smoke:abc123"
    )
    assert runner.temporary_image_reference("/usr/bin/podman", "abc123") == (
        "localhost/ai-guardian-agent-cli-smoke:abc123"
    )
    assert runner.temporary_image_reference("docker", "abc123") == (
        "ai-guardian-agent-cli-smoke:abc123"
    )


def test_sandbox_profile_preserves_strict_policy_and_enables_hook_evidence(tmp_path):
    runner = _load(RUNNER_PATH, "agent_cli_smoke_profile")
    profile_path = tmp_path / "strict-smoke.json"
    runner.write_strict_smoke_profile(profile_path)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    strict = json.loads(runner.STRICT_PROFILE.read_text(encoding="utf-8"))

    assert profile["secret_scanning"] == strict["secret_scanning"]
    assert profile["prompt_injection"] == strict["prompt_injection"]
    assert profile["ssrf_protection"] == strict["ssrf_protection"]
    assert profile["secret_redaction"] == strict["secret_redaction"]
    assert profile["scan_pii"] == strict["scan_pii"]
    assert profile["latency_tracking"]["enabled"] is True
    assert profile["violation_notifications"]["enabled"] is False
    assert strict["violation_notifications"]["enabled"] is True
    strict["violation_notifications"]["enabled"] = False
    strict.setdefault("latency_tracking", {})["enabled"] = True
    assert profile == strict


def test_sandbox_create_environment_strips_provider_secrets_and_host_config(
    monkeypatch, tmp_path
):
    runner = _load(RUNNER_PATH, "agent_cli_smoke_environment")
    host_home = tmp_path / "host-home"
    host_config = tmp_path / "host-config"
    storage_config = host_config / "containers" / "storage.conf"
    storage_config.parent.mkdir(parents=True)
    storage_config.write_text("[storage]\n", encoding="utf-8")
    podman_connections = host_config / "containers" / "podman-connections.json"
    connection_config = {
        "connection": {
            "podman-machine-default-root": {
                "uri": "ssh://root@127.0.0.1:63919/run/podman/podman.sock",
                "identity": str(
                    host_home / ".local/share/containers/podman/machine/machine"
                ),
            }
        },
        "default": "podman-machine-default-root",
    }
    podman_connections.write_text(json.dumps(connection_config), encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-host-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-host-value")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-host-value")
    monkeypatch.setenv("AWS_PROFILE", "developer")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(host_config))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("ACCEPT_PROPRIETARY_TOS", "true")

    environment = runner.sanitized_host_environment(tmp_path / "clean-home")

    assert "OPENAI_API_KEY" not in environment
    assert "ANTHROPIC_API_KEY" not in environment
    assert "GITHUB_TOKEN" not in environment
    assert "AWS_PROFILE" not in environment
    assert "ACCEPT_PROPRIETARY_TOS" not in environment
    assert environment["HOME"] == str(tmp_path / "clean-home")
    assert environment["XDG_CONFIG_HOME"] == str(tmp_path / "clean-home" / ".config")
    assert environment["XDG_DATA_HOME"] == str(host_home / ".local" / "share")
    assert environment["CONTAINERS_STORAGE_CONF"] == str(storage_config)
    isolated_connections = (
        tmp_path / "clean-home" / ".config" / "containers" / "podman-connections.json"
    )
    assert (
        json.loads(isolated_connections.read_text(encoding="utf-8"))
        == connection_config
    )

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "custom-data"))
    customized = runner.sanitized_host_environment(tmp_path / "clean-home-2")
    assert customized["XDG_DATA_HOME"] == str(tmp_path / "custom-data")


def test_mock_provider_configuration_is_written_to_each_clients_native_config(
    tmp_path,
):
    runner = _load(RUNNER_PATH, "agent_cli_smoke_config")
    cases = (
        ("codex", "smoke", Path(".codex/smoke.config.toml")),
        ("opencode", "build", Path(".config/opencode/opencode.json")),
        ("pi", "openai", Path(".pi/agent/models.json")),
        ("gemini", "default", Path(".gemini/settings.json")),
        ("claude", "default", Path(".claude/settings.json")),
    )
    for cli_name, agent, expected_path in cases:
        home = tmp_path / cli_name
        home.mkdir()
        workspace = home / "workspace"
        workspace.mkdir()
        environment = {
            **os.environ,
            "HOME": str(home),
            # pathlib.Path.home() uses USERPROFILE on Windows rather than HOME.
            "USERPROFILE": str(home),
        }
        if cli_name == "codex":
            environment["CODEX_HOME"] = str(home / ".codex")
            codex_home = home / ".codex"
            codex_home.mkdir()
            base_config = (
                '[mcp_servers.ai-guardian]\ncommand = "ai-guardian"\n'
                'args = ["mcp-server"]\n'
            )
            (codex_home / "config.toml").write_text(base_config, encoding="utf-8")
            hooks_config = '{"hooks": {"UserPromptSubmit": []}}\n'
            (codex_home / "hooks.json").write_text(hooks_config, encoding="utf-8")
        if cli_name == "pi":
            environment["PI_CODING_AGENT_DIR"] = str(home / ".pi/agent")
        if cli_name == "gemini":
            config_path = home / expected_path
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "BeforeTool": [
                                {
                                    "matcher": ".*",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "ai-guardian --ide gemini",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                runner._CONFIGURE_AGENT,
                json.dumps(
                    {
                        "cli_name": cli_name,
                        "agent": agent,
                        "workspace": str(workspace),
                        "base_url": runner.MOCK_URL,
                        "api_key": runner.MOCK_KEY,
                        "model": (
                            runner.MOCK_GEMINI_MODEL
                            if cli_name == "gemini"
                            else runner.MOCK_MODEL
                        ),
                    }
                ),
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        path = home / expected_path
        assert path.is_file()
        if cli_name == "codex":
            config = path.read_text(encoding="utf-8")
            assert config.startswith(f'model = "{runner.MOCK_MODEL}"\n')
            assert 'model_provider = "ai_guardian_smoke"' in config
            assert f'base_url = "{runner.MOCK_URL}"' in config
            assert 'wire_api = "responses"' in config
            assert 'approval_policy = "never"' in config
            assert 'sandbox_mode = "workspace-write"' in config
            assert "[profiles." not in config
            assert runner.MOCK_KEY not in config
            # Native profile overlays must preserve the base MCP/hook setup.
            assert (codex_home / "config.toml").read_text(
                encoding="utf-8"
            ) == base_config
            assert (codex_home / "hooks.json").read_text(
                encoding="utf-8"
            ) == hooks_config
            repeated = subprocess.run(
                result.args,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert repeated.returncode == 0, repeated.stderr
            assert path.read_text(encoding="utf-8") == config
            assert (codex_home / "config.toml").read_text(
                encoding="utf-8"
            ) == base_config
        else:
            config = json.loads(path.read_text(encoding="utf-8"))
            if cli_name == "claude":
                assert config["permissions"]["allow"] == [
                    "Bash(printf *)",
                    *[
                        f"Bash(python3 /tmp/ai_guardian_agent_cli_mock_provider.py --tool-case {case})"
                        for case in (
                            "clean_tool",
                            "tool_output_secret",
                            "tool_output_pii",
                        )
                    ],
                ]
                assert not (workspace / ".claude").exists()
            elif cli_name == "gemini":
                assert config["model"]["name"] == runner.MOCK_GEMINI_MODEL
                assert config["hooks"]["BeforeTool"][0]["matcher"] == ".*"
                assert (
                    config["hooks"]["BeforeTool"][0]["hooks"][0]["command"]
                    == "ai-guardian --ide gemini"
                )
                assert config["privacy"]["usageStatisticsEnabled"] is False
                assert config["security"]["auth"]["selectedType"] == "gemini-api-key"
                assert runner.MOCK_KEY not in json.dumps(config)
            else:
                assert runner.MOCK_URL in json.dumps(config)
                assert runner.MOCK_KEY in json.dumps(config)


@pytest.mark.parametrize("install_claude_code", (False, True))
@pytest.mark.parametrize("engine", ("docker", "podman"))
def test_claude_tos_opt_in_preinstalls_only_in_temporary_smoke_image(
    install_claude_code, engine, tmp_path, monkeypatch
):
    runner = _load(
        RUNNER_PATH, f"agent_cli_claude_image_tos_{engine}_{install_claude_code}"
    )
    container_dir = tmp_path / "container"
    container_dir.mkdir()
    (container_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    runner.CONTAINER_DIR = container_dir
    root = tmp_path / "smoke"
    root.mkdir()
    wheel = tmp_path / "ai_guardian-1.21.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    dockerfiles = []
    build_calls = []

    def fake_run(command, *_args, **kwargs):
        dockerfiles.append(Path(command[-1], "Dockerfile").read_text(encoding="utf-8"))
        build_calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run", fake_run)
    image = runner.build_current_image(
        engine,
        root,
        wheel,
        timeout=5,
        install_claude_code=install_claude_code,
    )

    assert len(dockerfiles) == 1
    command, kwargs = build_calls[0]
    assert command == [
        engine,
        "build",
        "--build-arg",
        f"AI_GUARDIAN_VERSION={wheel.name}",
        "--tag",
        image,
        str(root / "image-context"),
    ]
    assert kwargs["stream_output"] is True
    assert ("microdnf install -y --nodocs nftables" in dockerfiles[0]) is (
        engine == "podman"
    )
    assert ("ai-guardian.smoke-firewall=nftables-v1" in dockerfiles[0]) is (
        engine == "podman"
    )
    assert (container_dir / "Dockerfile").read_text(
        encoding="utf-8"
    ) == "FROM scratch\n"
    assert not (container_dir / "agent_cli_smoke_gate.py").exists()
    if install_claude_code:
        assert "https://claude.ai/install.sh" in dockerfiles[0]
        assert "test -x /sandbox/.local/bin/claude" in dockerfiles[0]
        assert "USER sandbox" in dockerfiles[0]
    else:
        assert "claude.ai/install.sh" not in dockerfiles[0]


def test_sandbox_runtime_never_receives_claude_install_consent(tmp_path):
    runner = _load(RUNNER_PATH, "agent_cli_claude_runtime_tos")
    profile = tmp_path / "strict.json"
    workspace = tmp_path / "workspace"
    command = runner.build_create_command(
        ["ai-guardian"],
        "docker",
        "claude",
        "default",
        "image",
        profile,
        workspace,
        "ag-cli-smoke-claude-test",
    )

    assert "ACCEPT_PROPRIETARY_TOS=true" not in command
    assert "AI_GUARDIAN_STATE_DIR=" + runner.STATE_DIR in command


@pytest.mark.parametrize("accept_proprietary_tos", (False, True))
def test_main_builds_claude_image_only_after_explicit_tos_opt_in(
    accept_proprietary_tos, monkeypatch, tmp_path
):
    runner = _load(RUNNER_PATH, f"agent_cli_claude_main_tos_{accept_proprietary_tos}")
    runner._temp_parent = lambda: tmp_path
    runner.sanitized_host_environment = lambda _home: {"HOME": str(tmp_path)}
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/available")
    runner._wait_for_sandbox_ready = lambda *_args, **_kwargs: True
    runner._check_sandbox_rest = lambda *_args, **_kwargs: True
    runner._configure_agent = lambda *_args, **_kwargs: True
    runner._start_mock = lambda *_args, **_kwargs: True
    runner._check_podman_smoke_image = lambda *_args: True
    runner._setup_podman_firewall = lambda *_args: True
    runner._run_case = lambda *_args, **_kwargs: True
    image_options = []
    runner.build_current_image = (
        lambda *_args, **kwargs: image_options.append(kwargs["install_claude_code"])
        or "localhost/claude-smoke:test"
    )
    commands = []

    def fake_run(command, *_args, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runner._run = fake_run
    runner._exec = lambda _engine, _name, command, *_args, **_kwargs: (
        subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    )
    runner._delete_sandbox = lambda *_args: None
    argv = [
        "--cli-name",
        "claude",
        "--agent",
        "default",
        "--container-engine",
        "podman",
        "--ai-guardian-command",
        "ai-guardian",
    ]
    if accept_proprietary_tos:
        argv.append("--accept-proprietary-tos")

    assert runner.main(argv) == 0

    assert image_options == [accept_proprietary_tos]
    assert all("ACCEPT_PROPRIETARY_TOS=true" not in command for command in commands)


def test_local_mock_returns_native_tool_calls_for_only_fixed_probe_cases():
    mock = _load(MOCK_PATH, "agent_cli_local_mock")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }
    ]
    response = mock.chat_response({"tools": tools}, "ssrf", 1)
    call = response["choices"][0]["message"]["tool_calls"][0]
    command = json.loads(call["function"]["arguments"])["command"]

    assert call["function"]["name"] == "bash"
    assert command.startswith("printf ")
    assert "169.254.169.254" in command
    assert (
        mock.chat_response({"tools": tools}, "allowed", 1)["choices"][0][
            "finish_reason"
        ]
        == "stop"
    )


def test_local_mock_stats_report_tool_availability_without_payloads():
    mock = _load(MOCK_PATH, "agent_cli_mock_tool_stats")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }
    ]

    assert mock._record_request("ssrf", {}) == (1, 0)
    assert mock._record_request("ssrf", {"tools": tools}) == (2, 1)
    stats = mock._stats()

    assert stats == {
        "requests": {"ssrf": 2},
        "command_tool_requests": {"ssrf": 1},
        "tool_offers": {"ssrf": 1},
        "clean_tool_results": {},
        "raw_tool_output_requests": {},
    }
    assert "curl" not in json.dumps(stats)

    response = mock.chat_response(
        {"tools": tools}, "ssrf", call_number=2, tool_call_number=1
    )
    assert response["choices"][0]["finish_reason"] == "tool_calls"


def test_codex_mock_response_uses_responses_api_stream_events():
    mock = _load(MOCK_PATH, "agent_cli_responses_mock")
    tools = [
        {
            "type": "function",
            "name": "shell",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "array"}},
                "required": ["command"],
            },
        }
    ]
    response = mock.responses_response({"tools": tools}, "config_exfil", 1)
    events = list(mock.response_events(response))
    call = response["output"][0]
    arguments = json.loads(call["arguments"])

    assert call["type"] == "function_call"
    assert arguments["command"][:2] == ["bash", "-lc"]
    assert any(
        event["type"] == "response.function_call_arguments.delta" for event in events
    )
    assert events[-1]["type"] == "response.completed"


def test_gemini_mock_builds_native_function_call_response():
    mock = _load(MOCK_PATH, "agent_cli_gemini_protocol")
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "AGENT_CLI_SMOKE_CASE: ssrf"}]}
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "run_shell_command",
                        "parametersJsonSchema": {
                            "type": "OBJECT",
                            "properties": {"command": {"type": "STRING"}},
                            "required": ["command"],
                        },
                    }
                ]
            }
        ],
    }

    response = mock.gemini_response(payload, "ssrf", 1, 1)
    part = response["candidates"][0]["content"]["parts"][0]

    assert response["candidates"][0]["finishReason"] == "STOP"
    assert part["functionCall"]["name"] == "run_shell_command"
    assert part["functionCall"]["args"]["command"].startswith("printf ")
    assert "169.254.169.254" in part["functionCall"]["args"]["command"]


def test_gemini_mock_supports_count_tokens_and_streaming_endpoints():
    mock = _load(MOCK_PATH, "agent_cli_gemini_http_protocol")
    server = mock.ThreadingHTTPServer(("127.0.0.1", 0), mock.MockProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1beta/models/gemini-2.5-flash"
        count_request = urllib.request.Request(
            f"{base}:countTokens?key=local-only",
            data=json.dumps({"contents": [{"parts": [{"text": "count me"}]}]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(count_request, timeout=5) as response:
            count_body = json.loads(response.read())
        assert response.status == 200
        assert count_body["totalTokens"] > 0
        assert mock._stats()["requests"] == {}

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "AGENT_CLI_SMOKE_CASE: ssrf run local diagnostic"}
                    ],
                }
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "run_shell_command",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"command": {"type": "STRING"}},
                                "required": ["command"],
                            },
                        }
                    ]
                }
            ],
        }
        stream_request = urllib.request.Request(
            f"{base}:streamGenerateContent?alt=sse&key=local-only",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(stream_request, timeout=5) as response:
            stream_body = response.read().decode("utf-8")

        assert response.headers["Content-Type"] == "text/event-stream"
        event = json.loads(stream_body.split("data: ", 1)[1].split("\n", 1)[0])
        assert (
            event["candidates"][0]["content"]["parts"][0]["functionCall"]["name"]
            == "run_shell_command"
        )
        assert mock._stats()["requests"] == {"ssrf": 1}
        assert mock._stats()["tool_offers"] == {"ssrf": 1}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_claude_mock_returns_messages_api_tool_calls_and_sse_events():
    mock = _load(MOCK_PATH, "agent_cli_anthropic_mock")
    runner = _load(RUNNER_PATH, "agent_cli_anthropic_endpoint")
    tools = [
        {
            "name": "Bash",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        }
    ]
    response = mock.anthropic_response(
        {"model": "claude-sonnet-4-6", "tools": tools}, "ssrf", 1
    )
    events = list(mock.anthropic_events(response))
    block = response["content"][0]

    assert response["type"] == "message"
    assert runner.MOCK_ANTHROPIC_BASE_URL == "http://127.0.0.1:18765"
    assert runner.MOCK_URL.endswith("/v1")
    assert response["stop_reason"] == "tool_use"
    assert block["type"] == "tool_use"
    assert block["name"] == "Bash"
    assert block["input"]["command"].startswith("printf ")
    assert any(
        event.get("delta", {}).get("type") == "input_json_delta" for event in events
    )
    assert events[-2]["delta"]["stop_reason"] == "tool_use"
    assert events[-1]["type"] == "message_stop"


def test_claude_mock_supports_messages_count_tokens_preflight():
    mock = _load(MOCK_PATH, "agent_cli_anthropic_count_tokens_mock")
    server = mock.ThreadingHTTPServer(("127.0.0.1", 0), mock.MockProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/messages/count_tokens?beta=1"
        request = urllib.request.Request(
            url,
            data=json.dumps(
                {
                    "model": "claude-sonnet-4-6",
                    "messages": [{"role": "user", "content": "local mock probe"}],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read())

        assert response.status == 200
        assert body["input_tokens"] > 0
        assert mock._stats()["requests"] == {}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_release_readiness_runs_clients_against_the_current_wheel_image():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["container-images"]["steps"]
    install_index = next(
        i
        for i, step in enumerate(steps)
        if step.get("name") == "Install current wheel for sandbox lifecycle"
    )
    image_index = next(
        i
        for i, step in enumerate(steps)
        if step.get("name") == "Build normal support image"
    )
    smoke_index = next(
        i
        for i, step in enumerate(steps)
        if step.get("name") == "Verify real agent CLI hooks with local mock provider"
    )
    run = steps[smoke_index]["run"]

    assert install_index < image_index < smoke_index
    for cli, agent in (
        ("codex", "smoke"),
        ("gemini", "default"),
        ("opencode", "build"),
        ("pi", "openai"),
    ):
        assert f"--cli-name {cli} --agent {agent}" in run
    assert "--image ai-guardian-readiness" in run
    assert "GEMINI_API_KEY=" not in run
    assert "OPENAI_API_KEY=" not in run
    assert "ANTHROPIC_API_KEY=" not in run
    claude_steps = [
        step
        for step in steps
        if step.get("name") == "Verify Claude Code hooks with local mock provider"
    ]
    assert len(claude_steps) == 1
    claude_step = claude_steps[0]
    assert claude_step["if"] == "vars.AI_GUARDIAN_CLAUDE_CODE_TOS_ACCEPTED == 'true'"
    assert "--cli-name claude --agent default" in claude_step["run"]
    assert "--accept-proprietary-tos" in claude_step["run"]
    assert "--image ai-guardian-readiness" not in claude_step["run"]

    v2_build = next(
        step
        for step in steps
        if step.get("name") == "Build pinned OpenCode V2 smoke image"
    )
    assert "--build-arg OPENCODE_VERSION=2.0.24" in v2_build["run"]
    assert "ai-guardian-opencode-v2-readiness" in v2_build["run"]
    v2_version_check = next(
        step
        for step in steps
        if step.get("name") == "Verify pinned OpenCode V2 smoke image version"
    )
    assert 'opencode_v2_version="${opencode_v2_version#opencode v}"' in (
        v2_version_check["run"]
    )
    v2_smoke = next(
        step
        for step in steps
        if step.get("name") == "Verify OpenCode V2 hooks with local mock provider"
    )
    assert "--cli-name opencode --agent build" in v2_smoke["run"]
    assert "--image ai-guardian-opencode-v2-readiness" in v2_smoke["run"]

    dockerfile = (ROOT / "container/Dockerfile").read_text(encoding="utf-8")
    assert 'npm install -g --prefix /opt/npm "@opencode/cli@${OPENCODE_VERSION}"' in (
        dockerfile
    )
    assert (
        "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}"
        in dockerfile
    )


def test_cli_and_scanner_checklists_keep_real_agent_smoke_coverage_in_sync():
    runtime_checklist = (ROOT / "docs/CLI_RUNTIME_CHECKLIST.md").read_text(
        encoding="utf-8"
    )
    scanner_checklist = (ROOT / "docs/SCANNER_INTEGRATION_CHECKLIST.md").read_text(
        encoding="utf-8"
    )
    agent_instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for document in (runtime_checklist, scanner_checklist, agent_instructions):
        assert "scripts/agent_cli_test.py" in document
        assert "tests/unit/test_agent_cli_test.py" in document
        assert ".github/workflows/release-readiness.yml" in document or (
            "Release Readiness" in document
        )
    assert "clean" in runtime_checklist.lower()
    assert "synthetic" in scanner_checklist.lower()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="agent-cli-test is a POSIX shell wrapper; Windows uses PowerShell",
)
def test_agent_cli_shell_wrapper_has_valid_syntax():
    wrapper = ROOT / "scripts" / "agent-cli-test"
    syntax = subprocess.run(
        ["bash", "-n", str(wrapper)], capture_output=True, text=True, check=False
    )

    assert syntax.returncode == 0, syntax.stderr


def test_agent_cli_runner_help():
    help_result = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert help_result.returncode == 0
    normalized_help = " ".join(help_result.stdout.split())
    assert "No provider credentials or live model calls are used" in normalized_help


def test_long_runner_steps_print_flushed_progress(capsys):
    runner = _load(RUNNER_PATH, "agent_cli_progress")
    result = runner._run(
        [sys.executable, "-c", "print('child output')"],
        timeout=5,
        progress="Building the temporary smoke image",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "child output"
    output = capsys.readouterr().out
    assert "[agent-cli-test] Building the temporary smoke image" in output
    assert "child output" not in output


@pytest.mark.parametrize("exit_code", (0, 2))
def test_streamed_build_output_is_visible_without_retaining_it(capfd, exit_code):
    runner = _load(RUNNER_PATH, f"agent_cli_streamed_build_{exit_code}")
    result = runner._run(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys; print('native build stdout'); "
            "print('native build stderr', file=sys.stderr); "
            f"sys.exit({exit_code})",
        ],
        timeout=5,
        progress="Building the temporary smoke image",
        stream_output=True,
    )

    visible = capfd.readouterr()
    assert "Building the temporary smoke image" in visible.out
    assert "native build stdout" in visible.out
    assert "native build stderr" in visible.err
    assert result.returncode == exit_code
    assert result.stdout is None
    assert result.stderr is None


def test_streamed_build_keeps_timeout_and_process_environment(monkeypatch, tmp_path):
    runner = _load(RUNNER_PATH, "agent_cli_streamed_build_timeout")
    calls = []
    environment = {"SMOKE_BUILD_TEST": "present"}

    def timeout_run(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(runner.subprocess, "run", timeout_run)

    with pytest.raises(subprocess.TimeoutExpired):
        runner._run(
            ["podman", "build", "."],
            timeout=900,
            env=environment,
            cwd=tmp_path,
            progress="Building the temporary smoke image",
            stream_output=True,
        )

    command, kwargs = calls[0]
    assert command == ["podman", "build", "."]
    assert kwargs["timeout"] == 900
    assert kwargs["env"] is environment
    assert kwargs["cwd"] == tmp_path
    assert kwargs["capture_output"] is False
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["check"] is False


def test_failed_runner_stage_reports_bounded_command_diagnostics(capsys):
    runner = _load(RUNNER_PATH, "agent_cli_failure_diagnostics")
    result = subprocess.CompletedProcess(
        ["ai-guardian", "sandbox", "create"],
        2,
        stdout="container output",
        stderr="profile mount failed",
    )

    runner._report_failure_details("Sandbox creation", result)
    output = capsys.readouterr().out

    assert "Sandbox creation failed (exit code 2)" in output
    assert "profile mount failed" in output
    assert "container output" in output


def test_failed_mock_provider_configuration_reports_diagnostics(monkeypatch, capsys):
    runner = _load(RUNNER_PATH, "agent_cli_config_diagnostics")
    failure = subprocess.CompletedProcess(
        ["podman", "exec"], 1, stdout="", stderr="PermissionError: settings path"
    )
    monkeypatch.setattr(runner, "_exec", lambda *args, **kwargs: failure)

    assert not runner._configure_agent("podman", "sandbox", "claude", "default", 5)

    output = capsys.readouterr().out
    assert "Local mock-provider configuration failed (exit code 1)" in output
    assert "PermissionError: settings path" in output


def test_failed_wheel_build_reports_diagnostics(tmp_path, monkeypatch, capsys):
    runner = _load(RUNNER_PATH, "agent_cli_wheel_build_diagnostics")
    failure = subprocess.CompletedProcess(
        ["uv", "build"], 1, stdout="wheel summary", stderr="wheel failure"
    )
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(runner, "_run", lambda *args, **kwargs: failure)

    with pytest.raises(RuntimeError, match="current AI Guardian wheel"):
        runner._build_wheel(tmp_path / "wheel-output", timeout=5)

    output = capsys.readouterr().out
    assert "Wheel build failed (exit code 1)" in output
    assert "wheel failure" in output
    assert "wheel summary" in output


def test_failed_smoke_image_build_reports_diagnostics(tmp_path, monkeypatch, capsys):
    runner = _load(RUNNER_PATH, "agent_cli_image_build_diagnostics")
    container_dir = tmp_path / "container"
    container_dir.mkdir()
    (container_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    runner.CONTAINER_DIR = container_dir
    root = tmp_path / "smoke"
    root.mkdir()
    wheel = tmp_path / "ai_guardian-1.21.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    failure = subprocess.CompletedProcess(
        ["podman", "build"], 1, stdout="build summary", stderr="build failure"
    )
    monkeypatch.setattr(runner, "_run", lambda *args, **kwargs: failure)

    with pytest.raises(RuntimeError, match="current-wheel smoke image"):
        runner.build_current_image("podman", root, wheel, timeout=5)

    output = capsys.readouterr().out
    assert "Smoke image build failed (exit code 1)" in output
    assert "build failure" in output
    assert "build summary" in output


def test_counter_read_failures_report_bounded_stderr(monkeypatch):
    runner = _load(RUNNER_PATH, "agent_cli_counter_diagnostics")
    failure = subprocess.CompletedProcess(
        ["podman", "exec"], 1, stdout="", stderr="PermissionError: state path"
    )
    monkeypatch.setattr(runner, "_exec", lambda *args, **kwargs: failure)

    diagnostics = []
    assert runner._violation_counts("podman", "sandbox", 30, diagnostics) is None
    assert diagnostics == [
        "violation log reader exited with code 1: PermissionError: state path"
    ]

    diagnostics.clear()
    assert runner._provider_stats("podman", "sandbox", 30, diagnostics) is None
    assert diagnostics == [
        "mock provider stats reader exited with code 1: PermissionError: state path"
    ]


def test_counter_read_diagnostics_truncate_stderr():
    runner = _load(RUNNER_PATH, "agent_cli_counter_diagnostics_truncated")
    diagnostics = []
    result = subprocess.CompletedProcess(["podman", "exec"], 1, stderr="x" * 2000)

    runner._counter_read_diagnostic("violation log", result, diagnostics)

    assert len(diagnostics[0]) < 1300
    assert diagnostics[0].endswith("x" * 1200)


@pytest.mark.parametrize(
    "case_name,exit_code,expected_diagnostic",
    [
        (
            "config_exfil",
            0,
            "provider_request_delta=1; violation_deltas=none; "
            "expected_config_file_exfil_delta=+0",
        ),
        (
            "allowed",
            2,
            "provider_request_delta=1; violation_deltas=none",
        ),
    ],
)
def test_agent_case_failures_report_only_aggregate_diagnostics(
    monkeypatch, capsys, case_name, exit_code, expected_diagnostic
):
    runner = _load(RUNNER_PATH, f"agent_cli_case_diagnostics_{case_name}")
    case = next(case for case in runner.CASES if case.name == case_name)
    violation_reads = iter(({}, {}))
    provider_reads = iter(({case_name: 0}, {case_name: 1}))
    hook_reads = iter(
        ({}, {"pretooluse" if case_name == "config_exfil" else "prompt": 1})
    )
    tool_reads = iter(({}, {"tool_offers": 1}))
    invocation = subprocess.CompletedProcess(
        ["codex", "exec"],
        exit_code,
        stdout="agent output must not be printed",
        stderr="agent error must not be printed",
    )
    monkeypatch.setattr(
        runner, "_violation_counts", lambda *_args, **_kwargs: next(violation_reads)
    )
    monkeypatch.setattr(
        runner, "_provider_stats", lambda *_args, **_kwargs: next(provider_reads)
    )
    monkeypatch.setattr(runner, "_exec", lambda *_args, **_kwargs: invocation)
    monkeypatch.setattr(
        runner, "_hook_counts", lambda *_args, **_kwargs: next(hook_reads)
    )
    monkeypatch.setattr(
        runner, "_tool_evidence", lambda *_args, **_kwargs: next(tool_reads)
    )

    assert not runner._run_case("docker", "sandbox", "codex", "smoke", case, 30)

    output = capsys.readouterr().out
    assert expected_diagnostic in output
    assert "agent output must not be printed" not in output
    assert "agent error must not be printed" not in output


def test_sandbox_readiness_waits_for_loaded_daemon(monkeypatch, capsys):
    runner = _load(RUNNER_PATH, "agent_cli_sandbox_readiness")
    results = [
        subprocess.CompletedProcess(
            ["podman", "exec"], 1, stdout="", stderr="daemon still starting"
        ),
        subprocess.CompletedProcess(
            ["podman", "exec"],
            0,
            stdout="ai-guardian daemon: running (pid 42)\nConfig: loaded\n",
            stderr="",
        ),
    ]
    calls = []

    def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return results.pop(0)

    monkeypatch.setattr(runner, "_exec", fake_exec)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    assert runner._wait_for_sandbox_ready("podman", "sandbox", timeout=5)
    assert len(calls) == 2
    assert calls[0][0][2] == ["ai-guardian", "daemon", "status"]
    assert "Sandbox setup and daemon are ready" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("container_healthy", "published_health", "stats_health", "expected", "message"),
    (
        (True, "healthy", "healthy", True, "authenticated host access work"),
        (False, "not_checked", "not_checked", False, "health failed inside"),
        (
            True,
            "connection_failed",
            "not_checked",
            False,
            "published-port/VM forwarding",
        ),
        (
            True,
            "healthy",
            "http_401",
            False,
            "authentication rather than changing network",
        ),
    ),
)
def test_rest_diagnostics_distinguish_listener_forwarding_and_authentication(
    container_healthy,
    published_health,
    stats_health,
    expected,
    message,
    monkeypatch,
    capsys,
):
    runner = _load(RUNNER_PATH, "agent_cli_rest_diagnostics")
    private_token = "private-smoke-auth-value"
    state = {
        "ipc": True,
        "rest_port": 63152,
        "internal_health": container_healthy,
        "auth_token": private_token,
    }
    commands = []

    def fake_exec(engine, name, command, timeout):
        commands.append((engine, name, command, timeout))
        return subprocess.CompletedProcess(
            command, 0, json.dumps(state), "private stderr"
        )

    def fake_run(command, *_args, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, "0.0.0.0:45678\n[::]:45678\n", ""
        )

    requests = []

    def probe(port, path, token=None):
        requests.append((port, path, token))
        return published_health if path == "/api/health" else stats_health

    monkeypatch.setattr(runner, "_exec", fake_exec)
    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner, "_probe_rest", probe)

    assert (
        runner._check_sandbox_rest("podman", "ag-cli-smoke-codex-1234abcd", 30)
        is expected
    )
    output = capsys.readouterr().out
    assert message in output
    assert private_token not in output
    assert "private stderr" not in output
    assert f"published_health={published_health}" in output
    assert f"authenticated_stats={stats_health}" in output
    assert all(request[0] == 45678 for request in requests)
    if stats_health != "not_checked":
        assert requests == [
            (45678, "/api/health", None),
            (45678, "/api/stats", private_token),
        ]
    assert not any(private_token in str(command) for command in commands)


@pytest.mark.parametrize(
    "port_output", ("", "0.0.0.0:0\n", "0.0.0.0:70000\n", "invalid")
)
def test_rest_diagnostics_report_missing_publication_without_network_access(
    port_output, monkeypatch, capsys
):
    runner = _load(RUNNER_PATH, "agent_cli_rest_missing_port")
    state = {"ipc": True, "rest_port": 63152, "internal_health": True}
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda *args: subprocess.CompletedProcess(args, 0, json.dumps(state), ""),
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args: subprocess.CompletedProcess(args, 0, port_output, ""),
    )
    requests = []
    monkeypatch.setattr(runner, "_probe_rest", lambda *args: requests.append(args))
    assert not runner._check_sandbox_rest("podman", "ag-cli-smoke-codex-1234abcd", 30)
    assert requests == []
    assert "REST port is not published" in capsys.readouterr().out


def test_diagnose_existing_sandbox_never_builds_creates_or_removes(monkeypatch):
    runner = _load(RUNNER_PATH, "agent_cli_rest_read_only_mode")
    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []
    monkeypatch.setattr(
        runner, "_check_sandbox_rest", lambda *args: calls.append(args) or True
    )

    def unexpected(*args, **kwargs):
        pytest.fail(
            "Read-only diagnostics must not create files, build images, or mutate sandboxes"
        )

    monkeypatch.setattr(runner.tempfile, "mkdtemp", unexpected)
    monkeypatch.setattr(runner, "build_current_image", unexpected)
    monkeypatch.setattr(runner, "_run", unexpected)
    monkeypatch.setattr(runner, "_delete_sandbox", unexpected)
    assert (
        runner.main(
            [
                "--diagnose-sandbox",
                "ag-cli-smoke-codex-1234abcd",
                "--container-engine",
                "podman",
            ]
        )
        == 0
    )
    assert calls == [("podman", "ag-cli-smoke-codex-1234abcd", 180)]


@pytest.mark.parametrize("name", ("ordinary-sandbox", "--all", "ag-cli-smoke-../other"))
def test_read_only_diagnostics_reject_non_smoke_names(name, monkeypatch):
    runner = _load(RUNNER_PATH, "agent_cli_rest_invalid_sandbox")
    calls = []
    monkeypatch.setattr(runner, "_check_sandbox_rest", lambda *args: calls.append(args))
    with pytest.raises(SystemExit) as error:
        runner.main([f"--diagnose-sandbox={name}"])
    assert error.value.code == 2
    assert calls == []


def test_podman_firewall_helper_is_short_lived_and_namespace_scoped(tmp_path):
    runner = _load(RUNNER_PATH, "agent_cli_firewall_helper_command")
    command = runner.build_firewall_command(
        "podman",
        "ag-cli-smoke-codex-1234abcd",
        "localhost/smoke:test",
        tmp_path / "helper.cid",
    )
    assert command[:3] == ["podman", "run", "--rm"]
    assert (
        command[command.index("--network") + 1]
        == "container:ag-cli-smoke-codex-1234abcd"
    )
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--cap-add") + 1] == "NET_ADMIN"
    assert command.count("--cap-add") == 1
    assert "--privileged" not in command
    assert "--volume" not in command
    assert "--pid" not in command
    assert "--read-only" in command
    assert "--pull=never" in command
    assert "ai-guardian.daemon=false" in command


@pytest.mark.parametrize("helper_code", (0, 1))
def test_firewall_gate_opens_only_after_successful_helper(
    helper_code, tmp_path, monkeypatch
):
    runner = _load(RUNNER_PATH, "agent_cli_firewall_bootstrap_order")
    events = []

    def fake_run(command, *_args, **_kwargs):
        events.append("helper")
        return subprocess.CompletedProcess(command, helper_code, "", "")

    def fake_exec(engine, name, command, timeout):
        events.append("release_gate")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner, "_exec", fake_exec)
    assert runner._setup_podman_firewall(
        "podman",
        "ag-cli-smoke-codex-1234abcd",
        "localhost/smoke:test",
        tmp_path,
        30,
        {},
    ) is (helper_code == 0)
    assert events == (["helper", "release_gate"] if helper_code == 0 else ["helper"])


@pytest.mark.parametrize(
    "windows_newlines", (False, True), ids=("native", "windows-newlines")
)
def test_firewall_readiness_marker_is_published_after_complete_write(
    tmp_path, monkeypatch, windows_newlines
):
    runner = _load(RUNNER_PATH, "agent_cli_firewall_atomic_readiness")
    ready = tmp_path / "ready"
    write = os.write
    monkeypatch.setattr(
        runner,
        "_run",
        lambda command, *args, **kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
    )

    def checked_write(fd, data):
        assert not ready.exists(), "startup gate can observe an incomplete marker"
        if windows_newlines and sys.platform != "win32":
            # Windows already translates text-mode descriptors natively.
            data = data.replace(b"\n", b"\r\n")
        return write(fd, data)

    def release_gate(engine, name, command, timeout):
        code = command[2].replace(
            "/tmp/ai-guardian-smoke-firewall-ready", str(ready).replace("\\", "/")
        )
        exec(compile(code, "<smoke-readiness>", "exec"))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(os, "write", checked_write)
    monkeypatch.setattr(runner, "_exec", release_gate)
    assert runner._setup_podman_firewall(
        "podman",
        "ag-cli-smoke-codex-1234abcd",
        "localhost/smoke:test",
        tmp_path,
        30,
        {},
    )
    # Match the gate's universal-newline text read, not host-specific raw bytes.
    assert ready.read_text(encoding="ascii") == "installed\n"


def test_supplied_podman_images_without_bootstrap_are_not_rebuilt(monkeypatch, capsys):
    runner = _load(RUNNER_PATH, "agent_cli_firewall_supplied_image")
    commands = []

    def fake_run(command, *_args, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner, "_run", fake_run)
    assert not runner._check_podman_smoke_image("podman", "localhost/normal:test", 30)
    assert len(commands) == 1
    assert commands[0][:3] == ["podman", "image", "inspect"]
    assert "omit --image" in capsys.readouterr().out


@pytest.mark.parametrize("keep", (False, True))
def test_firewall_failure_stops_sandbox_without_starting_agents(
    keep, tmp_path, monkeypatch
):
    runner = _load(RUNNER_PATH, "agent_cli_firewall_fail_closed")
    runner._temp_parent = lambda: tmp_path
    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runner, "_check_podman_smoke_image", lambda *args: True)
    monkeypatch.setattr(runner, "_setup_podman_firewall", lambda *args: False)
    monkeypatch.setattr(
        runner,
        "_wait_for_sandbox_ready",
        lambda *args: pytest.fail("bootstrap was not protected"),
    )
    commands = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda command, *args, **kwargs: commands.append(command)
        or subprocess.CompletedProcess(command, 0, "", ""),
    )
    removed = []
    monkeypatch.setattr(runner, "_delete_sandbox", lambda *args: removed.append(args))
    argv = [
        "--cli-name",
        "opencode",
        "--agent",
        "build",
        "--image",
        "localhost/smoke:test",
        "--container-engine",
        "podman",
        "--ai-guardian-command",
        "ai-guardian",
    ]
    if keep:
        argv.append("--keep")
    assert runner.main(argv) == 1
    assert any(command[:4] == ["podman", "stop", "--time", "1"] for command in commands)
    assert bool(removed) is not keep
    assert not any(command[1:2] == ["network"] for command in commands)


def test_firewall_timeout_removes_only_recorded_helper_id(tmp_path, monkeypatch):
    runner = _load(RUNNER_PATH, "agent_cli_firewall_timeout_cleanup")
    container_id = "a" * 64
    commands = []

    def run(command, *args, **kwargs):
        commands.append(command)
        if command[1] == "run":
            Path(command[command.index("--cidfile") + 1]).write_text(container_id)
            raise subprocess.TimeoutExpired(command, 30)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(
        runner, "_exec", lambda *args: pytest.fail("gate released after timeout")
    )
    with pytest.raises(subprocess.TimeoutExpired):
        runner._setup_podman_firewall(
            "podman",
            "ag-cli-smoke-codex-1234abcd",
            "localhost/smoke:test",
            tmp_path,
            30,
            {},
        )
    assert commands[-1] == ["podman", "rm", "--force", container_id]


@pytest.mark.parametrize(
    ("body", "path", "expected"),
    (
        (b'{"status":"ok"}', "/api/health", "healthy"),
        (b'{"request_count":1}', "/api/stats", "healthy"),
        (
            json.dumps({"request_count": 1, "sessions": "x" * 8192}).encode(),
            "/api/stats",
            "healthy",
        ),
        (b"[]", "/api/health", "invalid_response"),
        (b'{"private":"do not emit"}', "/api/stats", "invalid_response"),
        (b"not json", "/api/health", "invalid_response"),
        (b"x" * 4097, "/api/health", "invalid_response"),
        (b"x" * (1024 * 1024 + 1), "/api/stats", "invalid_response"),
    ),
    ids=(
        "health",
        "stats",
        "larger-stats",
        "list",
        "missing-stats",
        "invalid-json",
        "oversized-health",
        "oversized-stats",
    ),
)
def test_rest_probe_uses_no_proxy_no_redirects_and_never_emits_bodies(
    body, path, expected, monkeypatch, capsys
):
    runner = _load(RUNNER_PATH, "agent_cli_rest_private_probe")
    handlers = []
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append((request, timeout))
            return io.BytesIO(body)

    monkeypatch.setattr(
        runner, "build_opener", lambda *args: handlers.extend(args) or Opener()
    )
    assert runner._probe_rest(45678, path, "private-auth-value") == expected
    request, timeout = requests[0]
    assert request.full_url == f"http://127.0.0.1:45678{path}"
    assert request.get_header("Authorization") == "Bearer private-auth-value"
    assert timeout == 3
    assert handlers[0].proxies == {}
    assert handlers[1].redirect_request(None, None, None, None, None, None) is None
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("payload", ("not-json private-auth-value", "[]", "{}"))
def test_private_rest_state_failures_never_leak_subprocess_output(
    payload, monkeypatch, capsys
):
    runner = _load(RUNNER_PATH, "agent_cli_rest_private_failure")
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda *args: subprocess.CompletedProcess(
            args, 1, payload, "private-auth-value"
        ),
    )
    assert not runner._check_sandbox_rest("podman", "ag-cli-smoke-codex-1234abcd", 30)
    output = capsys.readouterr().out
    assert "private sandbox diagnostics" in output
    assert "private-auth-value" not in output


def test_private_rest_reader_uses_the_installed_tool_environment(
    tmp_path, monkeypatch, capsys
):
    """System Python has no AI Guardian; only the image's tool venv can import it.

    Execute the real reader with isolated paths and fake IPC/HTTP responses. Do
    not read a real daemon token, start a daemon, or run a container/network probe.
    """
    runner = _load(RUNNER_PATH, "agent_cli_rest_tool_python")
    pid_path = tmp_path / "daemon.pid"
    token_path = tmp_path / "daemon.token"
    pid_path.write_text(json.dumps({"rest_port": 63152}), encoding="utf-8")
    token_path.write_text("private-reader-test-token\n", encoding="utf-8")
    bootstrap = """
import io, sys, urllib.request
from pathlib import Path
import ai_guardian.daemon as daemon
from ai_guardian.daemon import client
daemon.get_pid_path = lambda: Path(sys.argv[2])
daemon.get_auth_token_path = lambda: Path(sys.argv[3])
client.send_status_request = lambda timeout: {'rest_port': 63152}
class LocalOpener:
    def open(self, url, timeout):
        assert url == 'http://127.0.0.1:63152/api/health'
        return io.BytesIO(b'{"status":"ok"}')
urllib.request.build_opener = lambda *handlers: LocalOpener()
exec(sys.argv[1])
"""
    commands = []

    def fake_exec(_engine, _name, command, timeout):
        commands.append(list(command))
        # Emulate the image's bare system interpreter versus its installed uv
        # tool environment. -I prevents accidental imports from this checkout.
        options = ["-I", "-S"] if command[0] == "python3" else ["-I"]
        assert command[1] == "-c"
        environment = dict(os.environ)
        for variable in (
            "HOME",
            "USERPROFILE",
            "AI_GUARDIAN_HOME",
            "AI_GUARDIAN_CONFIG_DIR",
            "AI_GUARDIAN_STATE_DIR",
        ):
            environment[variable] = str(tmp_path)
        return subprocess.run(
            [
                sys.executable,
                *options,
                "-c",
                bootstrap,
                command[2],
                str(pid_path),
                str(token_path),
            ],
            env=environment,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    monkeypatch.setattr(runner, "_exec", fake_exec)
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args: subprocess.CompletedProcess(args, 0, "127.0.0.1:45678\n", ""),
    )
    monkeypatch.setattr(runner, "_probe_rest", lambda *args, **kwargs: "healthy")

    assert runner._check_sandbox_rest("podman", "smoke", 30)
    assert commands[0][0] == "/opt/uv-tools/ai-guardian/bin/python3"
    output = capsys.readouterr()
    assert "authenticated host access work" in output.out
    assert "private-reader-test-token" not in output.out + output.err
    assert "Traceback" not in output.out + output.err
