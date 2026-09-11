"""Tests for the support-image launchers and entrypoint contract."""

import json
import os
import stat
import subprocess
import sys
import base64
import time
from pathlib import Path

import pytest
import yaml

from ai_guardian.ide_registry import SUPPORTED_IDE_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_ROOT / "container" / "run.sh"
OPENSHELL_SCRIPT = REPO_ROOT / "container" / "openshell.sh"
ENTRYPOINT_SCRIPT = REPO_ROOT / "container" / "entrypoint.sh"
DOCKERFILE = REPO_ROOT / "container" / "Dockerfile"
OPENSHELL_DOCKERFILE = REPO_ROOT / "container" / "Dockerfile.openshell"
CLI_VERSION_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "cli-version-health.yml"
BUILD_CONTAINER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-container.yml"
POLICY_COMPOSER = REPO_ROOT / "container" / "compose_openshell_policy.py"
POLICY_BASE = REPO_ROOT / "container" / "policies" / "base.yaml"
AGENT_POLICY_DIR = REPO_ROOT / "container" / "policies" / "agents"
GITHUB_POLICY = REPO_ROOT / "container" / "openshell-github-readonly-policy.yaml"
GITHUB_READWRITE_POLICY = (
    REPO_ROOT / "container" / "openshell-github-readwrite-policy.yaml"
)


def _executable_script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _launcher_env(tmp_path: Path, executable: Path, capture: Path) -> dict:
    """Return a clean environment for a launcher argument-capture test."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "CONTAINER_ENGINE": str(executable),
        "OPENSHELL_CLI": str(executable),
        "CAPTURE": str(capture),
    }
    for name in (
        "AI_GUARDIAN_AGENT",
        "AI_GUARDIAN_IDE",
        "AI_GUARDIAN_CONFIG_DIR",
        "AI_GUARDIAN_HOME",
        "AI_GUARDIAN_SETUP_SCOPE",
        "AI_GUARDIAN_PROFILE",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_VERTEX_PROJECT_ID",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "CODEX_HOME",
        "CODEX_AUTH_ACCESS_TOKEN",
        "CODEX_AUTH_REFRESH_TOKEN",
        "CODEX_AUTH_ACCOUNT_ID",
        "CODEX_AUTH_ID_TOKEN",
        "AI_GUARDIAN_CODEX_NETWORK_ACCESS",
        "AI_GUARDIAN_CODEX_SANDBOX_MODE",
        "AI_GUARDIAN_IMAGE",
        "AI_GUARDIAN_OPEN_SHELL_IMAGE",
        "AI_GUARDIAN_OPEN_SHELL_FORWARD",
        "AI_GUARDIAN_OPEN_SHELL_DAEMON_PORT",
        "AI_GUARDIAN_OPEN_SHELL_FORWARD_STATE_DIR",
        "OPENAI_API_KEY",
    ):
        env.pop(name, None)
    return env


def _capture_script(path: Path) -> Path:
    return _executable_script(
        path,
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$CAPTURE"\n',
    )


def _staging_openshell_script(path: Path) -> Path:
    return _executable_script(
        path,
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "provider" ] && [ "$2" = "list-profiles" ]; then
    echo '[{"id": "codex"}, {"id": "claude-code"}, {"id": "google-vertex-ai"}]'
    exit 0
fi
if [ "$1" = "provider" ] && [ "$2" = "get" ]; then
    exit 1
fi
if [ "$1" = "settings" ] && [ "$2" = "get" ]; then
    if [ "${FAKE_PROVIDERS_V2:-true}" = "true" ]; then
        echo '{"settings": {"providers_v2_enabled": true}}'
    else
        echo '{"settings": {"providers_v2_enabled": "<unset>"}}'
    fi
    exit 0
fi
if [ "$1" = "provider" ] && [ "$2" = "create" ]; then
    if [ -n "${CODEX_AUTH_ACCESS_TOKEN:-}" ] &&
        [ -n "${CODEX_AUTH_REFRESH_TOKEN:-}" ] &&
        [ -n "${CODEX_AUTH_ACCOUNT_ID:-}" ]; then
        echo present > "$CAPTURE.provider.auth"
    else
        echo absent > "$CAPTURE.provider.auth"
    fi
fi
if [ "$1" = "sandbox" ] && [ "$2" = "create" ]; then
    previous_arg=""
    for arg in "$@"; do
        if [ "$previous_arg" = "--policy" ]; then
            cp "$arg" "$CAPTURE.policy.yaml"
        fi
        previous_arg="$arg"
    done
    if [ -n "${CODEX_AUTH_ACCESS_TOKEN:-}" ] ||
        [ -n "${CODEX_AUTH_REFRESH_TOKEN:-}" ] ||
        [ -n "${CODEX_AUTH_ACCOUNT_ID:-}" ] ||
        [ -n "${CODEX_AUTH_ID_TOKEN:-}" ]; then
        echo leaked > "$CAPTURE.sandbox.auth"
    else
        echo clean > "$CAPTURE.sandbox.auth"
    fi
fi
if [ "$1" = "forward" ] && [ "$2" = "service" ]; then
    capture_file="$CAPTURE.$1.$2"
    for arg in "$@"; do
        echo "$arg"
    done > "$capture_file"
    echo 'Forwarding 127.0.0.1:55745 -> 127.0.0.1:63152 in sandbox'
    sleep 0.2
    exit 0
fi
capture_file="$CAPTURE.$1.$2"
for arg in "$@"; do
    echo "$arg"
done > "$capture_file"
""",
    )


def _captured_args(capture: Path) -> list[str]:
    return capture.read_text(encoding="utf-8").splitlines()


def _env_values(args: list[str], flag: str) -> list[str]:
    return [args[index + 1] for index, value in enumerate(args[:-1]) if value == flag]


def _volume_values(args: list[str]) -> list[str]:
    return _env_values(args, "-v")


def _openshell_env_values(args: list[str]) -> list[str]:
    return _env_values(args, "--env")


@pytest.mark.skipif(
    os.name == "nt", reason="The container launchers are POSIX shell scripts"
)
class TestContainerLaunchers:
    """Verify launcher defaults, isolation, and argument forwarding."""

    def test_shell_scripts_are_valid_and_executable(self):
        for script in (RUN_SCRIPT, OPENSHELL_SCRIPT, ENTRYPOINT_SCRIPT):
            result = subprocess.run(
                ["bash", "-n", str(script)], capture_output=True, text=True
            )
            assert result.returncode == 0, result.stderr
            assert os.access(script, os.X_OK), f"{script} must be executable"

    def test_normal_image_keeps_normal_runtime_layout(self):
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        assert "COPY --from=builder /opt/uv-tools /opt/uv-tools" in dockerfile
        assert (
            "COPY --from=builder /opt/npm/lib/node_modules "
            "/opt/npm/lib/node_modules" in dockerfile
        )
        assert 'CMD ["bash", "-l"]' in dockerfile
        assert "COPY --from=builder /opt/uv-tools /usr/lib/uv-tools" not in dockerfile

    def test_openshell_image_uses_community_base_layout(self):
        dockerfile = OPENSHELL_DOCKERFILE.read_text(encoding="utf-8")

        assert (
            "ARG BASE_IMAGE=ghcr.io/nvidia/openshell-community/sandboxes/base@sha256:"
            in dockerfile
        )
        assert "sandboxes/base:latest" not in dockerfile
        assert "FROM ${BASE_IMAGE}" in dockerfile
        assert "uv pip install --python /sandbox/.venv/bin/python" in dockerfile
        assert "ARG CLAUDE_VERSION=2.1.269" in dockerfile
        assert "ARG CODEX_VERSION=0.154.0" in dockerfile
        assert "ARG OPENCODE_VERSION=1.18.30" in dockerfile
        assert "ARG COPILOT_VERSION=1.0.83" in dockerfile
        assert "npm install --global --prefix /usr" in dockerfile
        assert '"@openai/codex@${CODEX_VERSION}"' in dockerfile
        assert '"opencode-ai@${OPENCODE_VERSION}"' in dockerfile
        assert '"@github/copilot@${COPILOT_VERSION}"' in dockerfile
        assert "https://claude.ai/install.sh" in dockerfile
        assert 'bash "$claude_install_script" "${CLAUDE_VERSION}"' in dockerfile
        assert 'install -m 0755 "$claude_install_home/.local/bin/claude"' in dockerfile
        assert "/usr/local/bin/claude --version" in dockerfile
        assert "&& opencode --version" in dockerfile
        assert "&& copilot --version" in dockerfile
        assert "/usr/sbin:/usr/bin:/sbin:/bin" in dockerfile
        assert "ai-guardian.openshell-base=true" in dockerfile

    def test_openshell_cli_health_workflow_is_scheduled_and_quay_only(self):
        workflow = CLI_VERSION_WORKFLOW.read_text(encoding="utf-8")

        assert "cron: '0 9 1,15 * *'" in workflow
        assert "scripts/check_cli_versions.py" in workflow
        assert "openshell-cli-version-update" in workflow
        assert "issues: write" in workflow
        assert "quay.io/redhatproductsecurity/ai-guardian" not in workflow
        assert "quay.io/itdove" not in workflow

    def test_container_build_publishes_openshell_to_dedicated_primary_registry(self):
        workflow = BUILD_CONTAINER_WORKFLOW.read_text(encoding="utf-8")
        openshell_section = workflow.split(
            "# --- Legacy mirror outputs for downstream jobs ---", 1
        )[0]

        assert "openshell_tag=latest" in openshell_section
        assert "file: container/Dockerfile.openshell" in openshell_section
        assert (
            "tags: quay.io/redhatproductsecurity/ai-guardian-openshell:${{ steps.params.outputs.openshell_tag }}"
            in openshell_section
        )
        assert (
            "tags: quay.io/redhatproductsecurity/ai-guardian:${{ steps.params.outputs.openshell_tag }}"
            not in openshell_section
        )
        assert "quay.io/itdove" not in openshell_section

    def test_default_agent_uses_file_only_host_config_mount(self, tmp_path):
        home = tmp_path / "home"
        config_path = home / ".config" / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)
        env["HOME"] = str(home)

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        args = _captured_args(capture)
        values = _env_values(args, "-e")
        volumes = _volume_values(args)
        assert "AI_GUARDIAN_AGENT=codex" in values
        assert "AI_GUARDIAN_IDE=codex" in values
        assert "AI_GUARDIAN_SETUP_SCOPE=selected" in values
        assert "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true" in values
        assert any(
            value == f"{config_path}:/sandbox/.config/ai-guardian/ai-guardian.json:ro"
            for value in volumes
        )
        assert args[-2:] == [
            "quay.io/redhatproductsecurity/ai-guardian:latest",
            "codex",
        ]

    def test_profile_suppresses_host_config_and_mounts_custom_profile_read_only(
        self, tmp_path
    ):
        home = tmp_path / "home"
        config_dir = home / ".config" / "ai-guardian"
        profile_path = config_dir / "profiles" / "team.json"
        profile_path.parent.mkdir(parents=True)
        (config_dir / "ai-guardian.json").write_text("{}\n", encoding="utf-8")
        profile_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)
        env["HOME"] = str(home)

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--agent", "opencode", "--profile", "team"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        args = _captured_args(capture)
        values = _env_values(args, "-e")
        volumes = _volume_values(args)
        assert "AI_GUARDIAN_AGENT=opencode" in values
        assert "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true" not in values
        assert "AI_GUARDIAN_HOST_CONFIG_MOUNTED=false" in values
        assert (
            "AI_GUARDIAN_PROFILE=/sandbox/.config/ai-guardian/profiles/team.json"
            in values
        )
        assert not any(value.endswith("/ai-guardian.json:ro") for value in volumes)
        assert any(value.endswith("/profiles/team.json:ro") for value in volumes)
        assert args[-2:] == [
            "quay.io/redhatproductsecurity/ai-guardian:latest",
            "opencode",
        ]

    def test_ai_guardian_home_selects_host_config_directory(self, tmp_path):
        home = tmp_path / "home"
        configured_dir = tmp_path / "guardian-home"
        config_path = configured_dir / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)
        env["HOME"] = str(home)
        env["AI_GUARDIAN_HOME"] = str(configured_dir)

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--agent", "gemini"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert any(
            value == f"{config_path}:/sandbox/.config/ai-guardian/ai-guardian.json:ro"
            for value in _volume_values(_captured_args(capture))
        )

    def test_config_dir_option_takes_precedence_over_ai_guardian_home(self, tmp_path):
        configured_dir = tmp_path / "env-config"
        option_dir = tmp_path / "option-config"
        env_config_path = configured_dir / "ai-guardian.json"
        option_config_path = option_dir / "ai-guardian.json"
        configured_dir.mkdir(parents=True)
        option_dir.mkdir(parents=True)
        env_config_path.write_text("{}\n", encoding="utf-8")
        option_config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)
        env["AI_GUARDIAN_HOME"] = str(configured_dir)

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--config-dir", str(option_dir)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        volumes = _volume_values(_captured_args(capture))
        assert any(
            value
            == f"{option_config_path}:/sandbox/.config/ai-guardian/ai-guardian.json:ro"
            for value in volumes
        )
        assert not any(str(env_config_path) in value for value in volumes)

    def test_agent_home_is_used_when_home_is_not_exported(self, tmp_path):
        inferred_home = tmp_path / "user"
        config_path = inferred_home / ".config" / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)
        env.pop("HOME")
        env["CODEX_HOME"] = str(inferred_home / ".codex")

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--agent", "codex"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert any(
            value == f"{config_path}:/sandbox/.config/ai-guardian/ai-guardian.json:ro"
            for value in _volume_values(_captured_args(capture))
        )

    def test_xdg_config_home_selects_host_config_directory(self, tmp_path):
        home = tmp_path / "home"
        xdg_config_home = tmp_path / "xdg"
        config_path = xdg_config_home / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(xdg_config_home)

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--agent", "codex"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert any(
            value == f"{config_path}:/sandbox/.config/ai-guardian/ai-guardian.json:ro"
            for value in _volume_values(_captured_args(capture))
        )

    def test_openshell_launcher_uses_supported_options_and_metadata(self, tmp_path):
        home = tmp_path / "home"
        config_path = home / ".config" / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)

        result = subprocess.run(
            [
                "bash",
                str(OPENSHELL_SCRIPT),
                "--agent",
                "codex",
                "--repo",
                ".",
                "--policy",
                str(GITHUB_POLICY),
                "--provider",
                "ai-guardian-codex",
                "--provider",
                "ai-guardian-github",
                "--name",
                "github-test",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        exec_args = _captured_args(capture.with_name("openshell.args.sandbox.exec"))
        assert create_args[:3] == ["sandbox", "create", "--from"]
        assert (
            create_args[3]
            == "quay.io/redhatproductsecurity/ai-guardian-openshell:latest"
        )
        assert "--no-auto-providers" in create_args
        assert "--detach" in create_args
        assert "--forward" not in create_args
        forward_args = _captured_args(
            capture.with_name("openshell.args.forward.service")
        )
        assert forward_args[:5] == [
            "forward",
            "service",
            "--target-port",
            "63152",
            "--local",
        ]
        assert forward_args[5].startswith("127.0.0.1:")
        assert forward_args[6:] == ["github-test"]
        selected_port = forward_args[5].rsplit(":", 1)[1]
        composed_policy_path = capture.with_name("openshell.args.policy.yaml")
        assert composed_policy_path.exists()
        composed_policy_argument = create_args[create_args.index("--policy") + 1]
        assert composed_policy_argument != str(GITHUB_POLICY)
        assert not Path(composed_policy_argument).exists()
        composed_policy = yaml.safe_load(
            composed_policy_path.read_text(encoding="utf-8")
        )
        assert set(composed_policy["network_policies"]) == {
            "github_api_readonly",
            "github_git_readonly",
            "codex_openai",
        }
        provider_values = [
            create_args[index + 1]
            for index, value in enumerate(create_args[:-1])
            if value == "--provider"
        ]
        assert provider_values == ["ai-guardian-codex", "ai-guardian-github"]
        assert create_args[create_args.index("--name") + 1] == "github-test"
        values = _openshell_env_values(create_args)
        assert "AI_GUARDIAN_AGENT=codex" in values
        assert "CODEX_HOME=/sandbox/.codex" in values
        assert "AI_GUARDIAN_CODEX_SANDBOX_MODE=danger-full-access" in values
        assert "AI_GUARDIAN_CODEX_NETWORK_ACCESS=true" not in values
        assert "AI_GUARDIAN_OPEN_SHELL_PROVIDER=true" in values
        assert "AI_GUARDIAN_REST_PORT=63152" in values
        assert "AI_GUARDIAN_SETUP_SCOPE=selected" in values
        assert "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true" in values
        assert any(
            value == f"{config_path}:/sandbox/.config/ai-guardian/ai-guardian.json"
            for value in _env_values(create_args, "--upload")
        )
        assert "--" not in create_args
        assert exec_args[:8] == [
            "sandbox",
            "exec",
            "--name",
            "github-test",
            "--no-tty",
            "--workdir",
            "/sandbox/repo",
            "--",
        ]
        assert exec_args[8:] == ["/usr/local/bin/entrypoint.sh", "/bin/bash"]

    def test_openshell_launcher_defaults_to_shell_in_uploaded_repo(self, tmp_path):
        home = tmp_path / "home"
        config_path = home / ".config" / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)

        result = subprocess.run(
            [
                "bash",
                str(OPENSHELL_SCRIPT),
                "--agent",
                "codex",
                "--repo",
                ".",
                "--provider",
                "ai-guardian-codex",
                "--name",
                "shell-test",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "Command:  /bin/bash" in result.stdout
        exec_args = _captured_args(capture.with_name("openshell.args.sandbox.exec"))
        assert exec_args[:8] == [
            "sandbox",
            "exec",
            "--name",
            "shell-test",
            "--no-tty",
            "--workdir",
            "/sandbox/repo",
            "--",
        ]
        assert exec_args[8:] == ["/usr/local/bin/entrypoint.sh", "/bin/bash"]

    def test_openshell_launcher_forces_tty_for_interactive_exec(self, tmp_path):
        pty = pytest.importorskip("pty")
        import os as posix_os
        import select

        home = tmp_path / "home"
        config_path = home / ".config" / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)

        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            ["bash", str(OPENSHELL_SCRIPT), "--agent", "codex", "--repo", "."],
            cwd=REPO_ROOT,
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        posix_os.close(slave_fd)
        try:
            while process.poll() is None:
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        posix_os.read(master_fd, 4096)
                    except OSError:
                        break
            process.wait(timeout=5)
        finally:
            posix_os.close(master_fd)

        assert process.returncode == 0
        exec_args = _captured_args(capture.with_name("openshell.args.sandbox.exec"))
        assert "--tty" in exec_args

    def test_openshell_launcher_keeps_anthropic_api_key_out_of_sandbox(self, tmp_path):
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)

        result = subprocess.run(
            [
                "bash",
                str(OPENSHELL_SCRIPT),
                "--agent",
                "claude",
                "--api-key",
                "test-anthropic-api-key",
                "--provider",
                "anthropic-provider",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        assert "test-anthropic-api-key" not in create_args
        assert not any(
            value.startswith("ANTHROPIC_API_KEY=")
            for value in _openshell_env_values(create_args)
        )

    def test_openshell_launcher_uses_openshell_dynamic_port_for_zero(self, tmp_path):
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)

        result = subprocess.run(
            [
                "bash",
                str(OPENSHELL_SCRIPT),
                "--agent",
                "codex",
                "--port",
                "0",
                "--provider",
                "codex-provider",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        assert "--forward" not in create_args
        forward_args = _captured_args(
            capture.with_name("openshell.args.forward.service")
        )
        assert forward_args[forward_args.index("--local") + 1] == "127.0.0.1:0"
        assert "--target-port" in forward_args
        assert "63152" in forward_args
        assert "AI_GUARDIAN_REST_PORT=63152" in _openshell_env_values(create_args)
        assert "Port:     dynamic (host forward)" in result.stdout
        assert "Access at: http://127.0.0.1:55745/" in result.stdout

        sandbox_name = create_args[create_args.index("--name") + 1]
        state_path = (
            tmp_path
            / "home"
            / ".local"
            / "state"
            / "ai-guardian"
            / "openshell-forwards"
        )
        state = json.loads(
            (state_path / f"{sandbox_name}.json").read_text(encoding="utf-8")
        )
        assert state["sandbox_name"] == sandbox_name
        assert state["host"] == "127.0.0.1"
        assert state["port"] == 55745
        assert state["target_port"] == 63152
        assert state["pid"] > 0

    @pytest.mark.parametrize(
        ("args", "forward_setting"),
        [
            (["--no-forward"], None),
            ([], "false"),
        ],
    )
    def test_openshell_launcher_can_disable_daemon_forwarding(
        self, tmp_path, args, forward_setting
    ):
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        if forward_setting is not None:
            env["AI_GUARDIAN_OPEN_SHELL_FORWARD"] = forward_setting

        result = subprocess.run(
            [
                "bash",
                str(OPENSHELL_SCRIPT),
                "--agent",
                "codex",
                *args,
                "--provider",
                "codex-provider",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        assert "--forward" not in create_args
        assert "AI_GUARDIAN_REST_PORT=63152" in _openshell_env_values(create_args)
        assert "Port:     63152 (not forwarded)" in result.stdout

    def test_openshell_launcher_uses_gateway_vertex_provider_without_adc_upload(
        self, tmp_path
    ):
        home = tmp_path / "home"
        adc_path = home / ".config" / "gcloud" / "application_default_credentials.json"
        adc_path.parent.mkdir(parents=True)
        adc_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)
        env["ANTHROPIC_VERTEX_PROJECT_ID"] = "test-project"

        result = subprocess.run(
            [
                "bash",
                str(OPENSHELL_SCRIPT),
                "--agent",
                "claude",
                "--name",
                "vertex-test",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        provider_args = _captured_args(
            capture.with_name("openshell.args.provider.create")
        )
        assert provider_args == [
            "provider",
            "create",
            "--name",
            "ai-guardian-google-vertex-ai",
            "--type",
            "google-vertex-ai",
            "--from-gcloud-adc",
        ]
        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        assert "--no-auto-providers" in create_args
        assert not any(
            value.startswith("GOOGLE_APPLICATION_CREDENTIALS=")
            for value in _openshell_env_values(create_args)
        )
        assert not any(
            str(adc_path) in value
            or value.endswith("/application_default_credentials.json")
            for value in _env_values(create_args, "--upload")
        )

    def test_github_policy_allows_read_only_api_and_git_operations(self):
        policy = yaml.safe_load(GITHUB_POLICY.read_text(encoding="utf-8"))

        assert policy["version"] == 1
        assert policy["filesystem_policy"]["include_workdir"] is True
        assert policy["filesystem_policy"]["read_write"] == [
            "/sandbox",
            "/tmp",
            "/dev/null",
        ]

        api_endpoint = policy["network_policies"]["github_api_readonly"]["endpoints"][0]
        assert api_endpoint["host"] == "api.github.com"
        assert api_endpoint["access"] == "read-only"

        git_endpoint = policy["network_policies"]["github_git_readonly"]["endpoints"][0]
        rules = [rule["allow"] for rule in git_endpoint["rules"]]
        assert {rule["method"] for rule in rules} == {"GET", "POST"}
        assert "/**/info/refs*" in [rule["path"] for rule in rules]
        assert "/**/git-upload-pack" in [rule["path"] for rule in rules]
        assert not any("git-receive-pack" in rule["path"] for rule in rules)

        assert set(policy["network_policies"]) == {
            "github_api_readonly",
            "github_git_readonly",
        }

    def test_github_readwrite_policy_allows_api_and_git_writes(self):
        policy = yaml.safe_load(GITHUB_READWRITE_POLICY.read_text(encoding="utf-8"))

        api_endpoint = policy["network_policies"]["github_api"]["endpoints"][0]
        assert api_endpoint["host"] == "api.github.com"
        assert api_endpoint["access"] == "read-write"

        git_endpoint = policy["network_policies"]["github_git"]["endpoints"][0]
        rules = [rule["allow"] for rule in git_endpoint["rules"]]
        assert {rule["method"] for rule in rules} == {"GET", "POST"}
        assert "/**/git-upload-pack" in [rule["path"] for rule in rules]
        assert "/**/git-receive-pack" in [rule["path"] for rule in rules]

        assert policy["filesystem_policy"]["read_write"] == [
            "/sandbox",
            "/tmp",
            "/dev/null",
        ]

    def test_agent_policy_fragments_are_scoped_to_one_selected_agent(self):
        expected_network_policies = {
            "claude": {"claude_code"},
            "codex": {"codex_openai"},
            "copilot": {"github_copilot"},
            "gemini": {"gemini_api"},
            "kiro": set(),
            "openclaw": set(),
            "opencode": {"deepinfra", "nvidia", "opencode_zen"},
            "crush": {"deepinfra", "nvidia"},
        }

        for agent, expected in expected_network_policies.items():
            fragment = yaml.safe_load(
                (AGENT_POLICY_DIR / f"{agent}.yaml").read_text(encoding="utf-8")
            )
            assert set(fragment.get("network_policies", {})) == expected

    def test_node_based_agent_policies_allow_the_community_base_node_binary(self):
        for agent in ("claude", "codex", "copilot", "gemini", "opencode", "crush"):
            fragment = yaml.safe_load(
                (AGENT_POLICY_DIR / f"{agent}.yaml").read_text(encoding="utf-8")
            )
            binaries = [
                binary["path"]
                for policy in fragment.get("network_policies", {}).values()
                for binary in policy.get("binaries", [])
            ]
            assert "/usr/bin/node" in binaries

    def test_policy_composer_merges_only_the_selected_agent_fragment(self, tmp_path):
        output = tmp_path / "composed.yaml"
        result = subprocess.run(
            [
                sys.executable,
                str(POLICY_COMPOSER),
                "--output",
                str(output),
                str(POLICY_BASE),
                str(GITHUB_READWRITE_POLICY),
                str(AGENT_POLICY_DIR / "claude.yaml"),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        policy = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert set(policy["network_policies"]) == {
            "github_api",
            "github_git",
            "claude_code",
        }
        assert "codex_openai" not in policy["network_policies"]

    def test_openshell_launcher_accepts_repeatable_policy_overlays(self, tmp_path):
        extra_policy = tmp_path / "extra-policy.yaml"
        extra_policy.write_text(
            """version: 1

network_policies:
  extra_api:
    name: extra-api
    endpoints:
      - host: example.com
        port: 443
        protocol: rest
        enforcement: enforce
        access: read-only
    binaries:
      - {path: /usr/bin/curl}
""",
            encoding="utf-8",
        )
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)

        result = subprocess.run(
            [
                "bash",
                str(OPENSHELL_SCRIPT),
                "--agent",
                "codex",
                "--policy",
                str(GITHUB_READWRITE_POLICY),
                "--policy",
                str(extra_policy),
                "--provider",
                "codex-provider",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        composed_policy = yaml.safe_load(
            capture.with_name("openshell.args.policy.yaml").read_text(encoding="utf-8")
        )
        assert set(composed_policy["network_policies"]) == {
            "github_api",
            "github_git",
            "extra_api",
            "codex_openai",
        }

    def test_openshell_upload_fallback_prepares_default_agent_provider(self, tmp_path):
        home = tmp_path / "home"
        config_path = home / ".config" / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)

        result = subprocess.run(
            ["bash", str(OPENSHELL_SCRIPT), "--agent", "codex"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        provider_args = _captured_args(
            capture.with_name("openshell.args.provider.create")
        )
        assert provider_args == [
            "provider",
            "create",
            "--name",
            "ai-guardian-codex",
            "--type",
            "codex",
            "--from-existing",
        ]

        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        exec_args = _captured_args(capture.with_name("openshell.args.sandbox.exec"))
        sandbox_name = create_args[create_args.index("--name") + 1]
        assert sandbox_name.startswith("ag-codex-")
        assert len(sandbox_name) <= 19
        assert "--provider" in create_args
        assert create_args[create_args.index("--provider") + 1] == "ai-guardian-codex"
        assert exec_args[:6] == [
            "sandbox",
            "exec",
            "--name",
            sandbox_name,
            "--no-tty",
            "--",
        ]
        assert exec_args[6:] == ["/usr/local/bin/entrypoint.sh", "/bin/bash"]

    def test_openshell_launcher_bridges_codex_oauth_file_for_provider_setup(
        self, tmp_path
    ):
        home = tmp_path / "home"
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True)
        (codex_home / "auth.json").write_text(
            """{
  "auth_mode": "chatgpt",
  "tokens": {
    "access_token": "test-access-token",
    "refresh_token": "test-refresh-token",
    "account_id": "test-account-id",
    "id_token": "test-id-token"
  }
}
""",
            encoding="utf-8",
        )
        config_path = home / ".config" / "ai-guardian" / "ai-guardian.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)

        result = subprocess.run(
            ["bash", str(OPENSHELL_SCRIPT), "--agent", "codex"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert (
            capture.with_name("openshell.args.provider.auth")
            .read_text(encoding="utf-8")
            .strip()
            == "present"
        )
        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        assert not any(
            token in value
            for value in create_args
            for token in (
                "test-access-token",
                "test-refresh-token",
                "test-account-id",
                "test-id-token",
            )
        )
        assert not any(
            value.endswith("/auth.json") or ":/sandbox/.codex" in value
            for value in _env_values(create_args, "--upload")
        )
        assert (
            capture.with_name("openshell.args.sandbox.auth")
            .read_text(encoding="utf-8")
            .strip()
            == "clean"
        )

    def test_openshell_launcher_uses_codex_provider_without_uploads(self, tmp_path):
        home = tmp_path / "home"
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True)
        (codex_home / "auth.json").write_text(
            '{"tokens": {"access_token": "access", "refresh_token": "refresh", '
            '"account_id": "account"}}\n',
            encoding="utf-8",
        )
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)

        result = subprocess.run(
            ["bash", str(OPENSHELL_SCRIPT), "--agent", "codex"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        create_args = _captured_args(capture.with_name("openshell.args.sandbox.create"))
        assert "--no-auto-providers" in create_args
        assert "--auto-providers" not in create_args
        assert "--detach" in create_args
        assert "--upload" not in create_args
        assert create_args[create_args.index("--provider") + 1] == "ai-guardian-codex"
        assert "CODEX_HOME=/sandbox/.codex" in _openshell_env_values(create_args)
        assert "AI_GUARDIAN_CODEX_SANDBOX_MODE=danger-full-access" in (
            _openshell_env_values(create_args)
        )
        assert "AI_GUARDIAN_CODEX_NETWORK_ACCESS=true" not in _openshell_env_values(
            create_args
        )
        assert "AI_GUARDIAN_OPEN_SHELL_PROVIDER=true" in _openshell_env_values(
            create_args
        )
        assert "--" not in create_args
        forward_args = _captured_args(
            capture.with_name("openshell.args.forward.service")
        )
        assert forward_args[forward_args.index("--target-port") + 1] == "63152"

    def test_openshell_launcher_explains_disabled_providers_v2_for_codex_oauth(
        self, tmp_path
    ):
        home = tmp_path / "home"
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True)
        (codex_home / "auth.json").write_text(
            '{"tokens": {"access_token": "access", "refresh_token": "refresh", '
            '"account_id": "account"}}\n',
            encoding="utf-8",
        )
        capture = tmp_path / "openshell.args"
        cli = _staging_openshell_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)
        env["FAKE_PROVIDERS_V2"] = "false"

        result = subprocess.run(
            ["bash", str(OPENSHELL_SCRIPT), "--agent", "codex"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        assert "Providers v2 is disabled" in result.stderr
        assert "providers_v2_enabled --value true" in result.stderr
        assert not capture.with_name("openshell.args.provider.create").exists()

    def test_openshell_launcher_rejects_gui_only_integrations(self, tmp_path):
        capture = tmp_path / "openshell.args"
        cli = _capture_script(tmp_path / "fake-openshell")
        env = _launcher_env(tmp_path, cli, capture)

        result = subprocess.run(
            ["bash", str(OPENSHELL_SCRIPT), "--agent", "cursor"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        assert "Supported CLI agents:" in result.stderr
        assert not capture.exists()

    def test_launcher_rejects_unknown_agent(self, tmp_path):
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--agent", "not-an-agent"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        assert "unsupported agent" in result.stderr
        assert not capture.exists()

    def test_launcher_rejects_missing_custom_profile_file(self, tmp_path):
        capture = tmp_path / "run.args"
        engine = _capture_script(tmp_path / "fake-engine")
        env = _launcher_env(tmp_path, engine, capture)
        missing_profile = tmp_path / "missing-profile.json"

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--profile", str(missing_profile)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        assert "custom profile file not found" in result.stderr
        assert not capture.exists()

    @pytest.mark.parametrize("agent", [*SUPPORTED_IDE_TYPES, "dummy-agent"])
    def test_launcher_accepts_every_supported_agent(self, tmp_path, agent):
        capture = tmp_path / f"{agent}.args"
        engine = _capture_script(tmp_path / f"engine-{agent}")
        env = _launcher_env(tmp_path, engine, capture)

        result = subprocess.run(
            ["bash", str(RUN_SCRIPT), "--agent", agent, "--", "/bin/true"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert f"AI_GUARDIAN_AGENT={agent}" in _env_values(
            _captured_args(capture), "-e"
        )


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_configures_all_external_integrations(tmp_path):
    """The selected agent and every supported external integration are setup."""
    log_path = tmp_path / "ai-guardian.log"
    fake_ai_guardian = _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_LOG"
if [[ "${1:-}" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
if [[ "${1:-}" = "--version" ]]; then
    printf 'ai-guardian test\n'
fi
""",
    )
    config_dir = tmp_path / "config"
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "FAKE_LOG": str(log_path),
        "AI_GUARDIAN_SETUP_SCOPE": "all",
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    setup_calls = log_path.read_text(encoding="utf-8").splitlines()
    configured_agents = {
        line.split("--ide ", 1)[1].split()[0]
        for line in setup_calls
        if line.startswith("setup ") and "--ide " in line
    }
    assert configured_agents == set(SUPPORTED_IDE_TYPES)
    assert "Setup:        all supported agents" in result.stdout

    log_path.unlink()
    env["AI_GUARDIAN_SETUP_SCOPE"] = "cli"
    cli_result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert cli_result.returncode == 0, cli_result.stderr
    cli_setup_calls = log_path.read_text(encoding="utf-8").splitlines()
    cli_agents = {
        line.split("--ide ", 1)[1].split()[0]
        for line in cli_setup_calls
        if line.startswith("setup ") and "--ide " in line
    }
    assert cli_agents == {
        "claude",
        "copilot",
        "codex",
        "gemini",
        "kiro",
        "openclaw",
        "opencode",
        "crush",
    }
    assert "Setup:        supported CLI agents" in cli_result.stdout

    log_path.unlink()
    env["AI_GUARDIAN_SETUP_SCOPE"] = "selected"
    selected_result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert selected_result.returncode == 0, selected_result.stderr
    selected_setup_calls = log_path.read_text(encoding="utf-8").splitlines()
    selected_agents = {
        line.split("--ide ", 1)[1].split()[0]
        for line in selected_setup_calls
        if line.startswith("setup ") and "--ide " in line
    }
    assert selected_agents == {"codex"}
    assert "Setup:        selected agent" in selected_result.stdout


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_skips_integrations_missing_from_released_package(tmp_path):
    log_path = tmp_path / "ai-guardian.log"
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_LOG"
if [[ "$1" = "setup" && "$2" = "--help" ]]; then
    printf 'usage: ai-guardian setup [--ide {codex}]\n'
    exit 0
fi
if [[ "$1" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
if [[ "$1" = "--version" ]]; then
    printf 'ai-guardian 1.17.1\n'
fi
""",
    )
    config_dir = tmp_path / "config"
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_SETUP_SCOPE": "cli",
        "FAKE_LOG": str(log_path),
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    setup_calls = log_path.read_text(encoding="utf-8").splitlines()
    assert setup_calls.count("setup --ide codex --create-config --force --yes") == 1
    assert "Skipping: claude (not supported by installed ai-guardian)" in result.stdout
    assert "Skipping: crush (not supported by installed ai-guardian)" in result.stdout


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_bootstraps_codex_oauth_placeholders(tmp_path):
    codex_home = tmp_path / "codex-home"
    config_dir = tmp_path / "config"
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
if [ "$1" = "--version" ]; then
    printf 'ai-guardian test\n'
fi
""",
    )
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_SETUP_SCOPE": "cli",
        "AI_GUARDIAN_OPEN_SHELL_PROVIDER": "true",
        "CODEX_HOME": str(codex_home),
        "CODEX_AUTH_ACCESS_TOKEN": ("openshell:resolve:env:CODEX_AUTH_ACCESS_TOKEN"),
        "CODEX_AUTH_REFRESH_TOKEN": ("openshell:resolve:env:CODEX_AUTH_REFRESH_TOKEN"),
        "CODEX_AUTH_ACCOUNT_ID": "openshell:resolve:env:CODEX_AUTH_ACCOUNT_ID",
        "CODEX_AUTH_ID_TOKEN": "openshell:resolve:env:CODEX_AUTH_ID_TOKEN",
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    auth_path = codex_home / "auth.json"
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert auth["OPENAI_API_KEY"] is None
    assert auth["auth_mode"] == "chatgpt"
    assert auth["tokens"]["access_token"] == env["CODEX_AUTH_ACCESS_TOKEN"]
    assert auth["tokens"]["refresh_token"] == env["CODEX_AUTH_REFRESH_TOKEN"]
    assert auth["tokens"]["account_id"] == env["CODEX_AUTH_ACCOUNT_ID"]
    assert auth["tokens"]["id_token"].count(".") == 2
    assert all(auth["tokens"]["id_token"].split("."))
    assert auth["tokens"]["id_token"] != env["CODEX_AUTH_ID_TOKEN"]
    id_token_payload = json.loads(
        base64.urlsafe_b64decode(
            auth["tokens"]["id_token"].split(".")[1] + "=="
        ).decode("utf-8")
    )
    assert id_token_payload["email"] == "openshell@localhost"
    assert "https://api.openai.com/auth" not in id_token_payload
    assert auth["last_refresh"].endswith("Z")
    assert stat.S_IMODE(auth_path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_configures_codex_workspace_network_access(tmp_path):
    codex_home = tmp_path / "codex-home"
    config_dir = tmp_path / "config"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-test"\n\n'
        "[sandbox_workspace_write]\n"
        "network_access = false\n"
        "\n"
        "[profiles.default]\n"
        'approval_policy = "never"\n',
        encoding="utf-8",
    )
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
if [[ "$1" = "--version" ]]; then
    printf 'ai-guardian test\n'
fi
""",
    )
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_SETUP_SCOPE": "selected",
        "AI_GUARDIAN_CODEX_NETWORK_ACCESS": "true",
        "CODEX_HOME": str(codex_home),
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    config = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-test"' in config
    assert "[sandbox_workspace_write]" in config
    assert "network_access = true" in config
    assert "network_access = false" not in config
    assert '[profiles.default]\napproval_policy = "never"' in config


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_creates_codex_workspace_network_config_when_missing(tmp_path):
    codex_home = tmp_path / "codex-home"
    config_dir = tmp_path / "config"
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
""",
    )
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_CODEX_NETWORK_ACCESS": "true",
        "CODEX_HOME": str(codex_home),
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == (
        "[sandbox_workspace_write]\nnetwork_access = true\n"
    )


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_configures_codex_outer_sandbox_mode(tmp_path):
    codex_home = tmp_path / "codex-home"
    config_dir = tmp_path / "config"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-test"\n'
        'sandbox_mode = "workspace-write"\n\n'
        "[mcp_servers.ai_guardian]\n"
        'command = "ai-guardian"\n',
        encoding="utf-8",
    )
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
if [[ "$1" = "--version" ]]; then
    printf 'ai-guardian test\n'
fi
""",
    )
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_CODEX_SANDBOX_MODE": "danger-full-access",
        "CODEX_HOME": str(codex_home),
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    config = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert 'sandbox_mode = "danger-full-access"' in config
    assert 'sandbox_mode = "workspace-write"' not in config
    assert "[mcp_servers.ai_guardian]" in config
    assert "network_access" not in config


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_inserts_codex_outer_sandbox_mode_before_tables(tmp_path):
    codex_home = tmp_path / "codex-home"
    config_dir = tmp_path / "config"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-test"\n\n[ mcp_servers.ai_guardian ]\n',
        encoding="utf-8",
    )
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
""",
    )
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_CODEX_SANDBOX_MODE": "danger-full-access",
        "CODEX_HOME": str(codex_home),
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    config_lines = (codex_home / "config.toml").read_text(encoding="utf-8").splitlines()
    mode_index = config_lines.index('sandbox_mode = "danger-full-access"')
    table_index = config_lines.index("[ mcp_servers.ai_guardian ]")
    assert mode_index < table_index


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_reuses_agent_already_available_on_path(tmp_path):
    config_dir = tmp_path / "config"
    _executable_script(tmp_path / "claude", "#!/usr/bin/env bash\nexit 0\n")
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && " $* " = *" --create-config "* ]]; then
    mkdir -p "$AI_GUARDIAN_CONFIG_DIR"
    printf '{}\n' > "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"
fi
""",
    )
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "claude",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "requires accepting its Terms of Service" not in result.stdout


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_waits_for_staged_host_config(tmp_path):
    fake_ai_guardian = _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "--version" ]; then
    echo "ai-guardian test"
fi
""",
    )
    config_dir = tmp_path / "config"
    config_path = config_dir / "ai-guardian.json"
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "true",
        "AI_GUARDIAN_OPEN_SHELL_STAGING": "true",
        "AI_GUARDIAN_SETUP_SCOPE": "cli",
    }

    process = subprocess.Popen(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.25)
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{}\n", encoding="utf-8")
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, stderr
    assert "Waiting for OpenShell to upload host ai-guardian config" in stdout
    assert "Using read-only host ai-guardian config" in stdout


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_rejects_conflicting_profile_and_host_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "ai-guardian.json").write_text("{}\n", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_PROFILE": "@strict",
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "true",
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "mutually exclusive" in result.stderr + result.stdout
