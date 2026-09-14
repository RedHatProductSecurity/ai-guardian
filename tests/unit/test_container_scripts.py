"""Tests for the support-image launchers and entrypoint contract."""

import base64
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from ai_guardian.ide_registry import SUPPORTED_IDE_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_ROOT / "container" / "run.sh"
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


def _latest_stable_release_version() -> str:
    """Return the first stable release listed in the changelog."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(
        r"^## \[(?P<version>\d+\.\d+\.\d+)\]",
        changelog,
        flags=re.MULTILINE,
    )
    assert match, "CHANGELOG.md must list a stable release"
    return match.group("version")


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
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED",
        "AI_GUARDIAN_HOST_CONFIG_PATH",
        "AI_GUARDIAN_RESTORE_CONFIG",
        "AI_GUARDIAN_OPEN_SHELL_STAGING",
        "AI_GUARDIAN_CONFIG_SOURCE",
        "AI_GUARDIAN_CONFIG_READ_ONLY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_VERTEX_PROJECT_ID",
        "VERTEX_AI_PROJECT_ID",
        "VERTEX_AI_REGION",
        "CLOUD_ML_REGION",
        "AI_GUARDIAN_OPEN_SHELL_MODEL",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_VERTEX_AI_TOKEN",
        "VERTEX_AI_TOKEN",
        "GOOGLE_VERTEX_AI_SERVICE_ACCOUNT_TOKEN",
        "VERTEX_AI_SERVICE_ACCOUNT_TOKEN",
        "CODEX_HOME",
        "CODEX_AUTH_ACCESS_TOKEN",
        "CODEX_AUTH_REFRESH_TOKEN",
        "CODEX_AUTH_ACCOUNT_ID",
        "CODEX_AUTH_ID_TOKEN",
        "AI_GUARDIAN_CODEX_NETWORK_ACCESS",
        "AI_GUARDIAN_CODEX_SANDBOX_MODE",
        "AI_GUARDIAN_IMAGE",
        "AI_GUARDIAN_OPEN_SHELL_IMAGE",
        "OPENAI_API_KEY",
    ):
        env.pop(name, None)
    return env


def _capture_script(path: Path) -> Path:
    return _executable_script(
        path,
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$CAPTURE"\n',
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
        for script in (RUN_SCRIPT, ENTRYPOINT_SCRIPT):
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

    def test_container_defaults_match_latest_stable_ai_guardian_release(self):
        expected_version = _latest_stable_release_version()

        for dockerfile_path in (DOCKERFILE, OPENSHELL_DOCKERFILE):
            dockerfile = dockerfile_path.read_text(encoding="utf-8")
            match = re.search(
                r"^ARG AI_GUARDIAN_VERSION=(?P<version>[^\s#]+)$",
                dockerfile,
                flags=re.MULTILINE,
            )
            assert match, f"{dockerfile_path} must define AI_GUARDIAN_VERSION"
            assert match.group("version") == expected_version

        container_readme = (REPO_ROOT / "container" / "README.md").read_text(
            encoding="utf-8"
        )
        assert f"| `AI_GUARDIAN_VERSION` | `{expected_version}` |" in container_readme

    def test_container_build_requires_the_same_run_wheel(self):
        workflow = BUILD_CONTAINER_WORKFLOW.read_text(encoding="utf-8")
        resolve_section = workflow.split(
            "# --- Resolve wheel filename for AI_GUARDIAN_VERSION build-arg ---", 1
        )[1].split("# --- Multi-arch build setup ---", 1)[0]

        assert "shopt -s nullglob" in resolve_section
        assert "wheels=(container/vendor/ai_guardian-*.whl)" in resolve_section
        assert "Expected exactly one AI Guardian wheel" in resolve_section
        assert 'WHL="${wheels[0]##*/}"' in resolve_section
        assert 'echo "version=${WHL}"' in resolve_section
        assert "steps.params.outputs.image_tag" not in resolve_section

    def test_container_build_checks_release_references_before_building(self):
        workflow = BUILD_CONTAINER_WORKFLOW.read_text(encoding="utf-8")

        assert "scripts/sync_release_versions.py --repo . --check" in workflow

    def test_openshell_image_uses_community_base_layout(self):
        dockerfile = OPENSHELL_DOCKERFILE.read_text(encoding="utf-8")

        assert (
            "ARG BASE_IMAGE=ghcr.io/nvidia/openshell-community/sandboxes/base@sha256:"
            in dockerfile
        )
        assert "sandboxes/base:latest" not in dockerfile
        assert "FROM ${BASE_IMAGE}" in dockerfile
        assert "uv pip install --python /sandbox/.venv/bin/python" in dockerfile
        assert "ARG CLAUDE_VERSION" not in dockerfile
        assert "ARG CODEX_VERSION=0.154.0" in dockerfile
        assert "ARG OPENCODE_VERSION=1.18.30" in dockerfile
        assert "ARG COPILOT_VERSION" not in dockerfile
        assert "npm install --global --prefix /usr" in dockerfile
        assert '"@openai/codex@${CODEX_VERSION}"' in dockerfile
        assert '"opencode-ai@${OPENCODE_VERSION}"' in dockerfile
        assert "command -v claude" in dockerfile
        assert "command -v copilot" in dockerfile
        assert "https://claude.ai/install.sh" not in dockerfile
        assert '"@github/copilot@${COPILOT_VERSION}"' not in dockerfile
        assert "&& opencode --version" in dockerfile
        assert "copilot --version" in dockerfile
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
        params_section = workflow.split("      - name: Determine build parameters", 1)[
            1
        ].split("      - name: Checkout code", 1)[0]
        openshell_section = workflow.split("# --- OpenShell sandbox image ---", 1)[1]

        assert 'echo "openshell_tag=latest"' in params_section
        assert "file: container/Dockerfile.openshell" in openshell_section
        assert (
            "tags: quay.io/redhatproductsecurity/ai-guardian-openshell:${{ steps.params.outputs.openshell_tag }}"
            in openshell_section
        )
        assert (
            "tags: quay.io/redhatproductsecurity/ai-guardian:${{ steps.params.outputs.openshell_tag }}"
            not in openshell_section
        )
        assert "quay.io/itdove" not in workflow

    def test_container_build_uses_separate_openshell_registry_credentials(self):
        workflow = BUILD_CONTAINER_WORKFLOW.read_text(encoding="utf-8")
        normal_login = workflow.split(
            "# --- Skip rebuild if commit-tagged image already exists ---", 1
        )[0]
        openshell_section = workflow.split("# --- OpenShell sandbox image ---", 1)[1]
        openshell_login = openshell_section.split(
            "- name: Build and push OpenShell sandbox image", 1
        )[0]

        assert "username: ${{ secrets.QUAY_RPS_USERNAME }}" in normal_login
        assert "password: ${{ secrets.QUAY_RPS_PASSWORD }}" in normal_login
        assert "- name: Log in to quay.io for OpenShell" in openshell_login
        assert "username: ${{ secrets.QUAY_RPS_OPENSHELL_USERNAME }}" in openshell_login
        assert "password: ${{ secrets.QUAY_RPS_OPENSHELL_PASSWORD }}" in openshell_login
        assert "legacy-mirror:" not in workflow
        assert "Export image tag" not in workflow
        assert "steps.export" not in workflow
        assert "quay.io/itdove" not in workflow
        assert "QUAY_USERNAME" not in workflow
        assert "QUAY_PASSWORD" not in workflow

    def test_container_build_publishes_openshell_for_supported_trigger_paths(self):
        workflow = BUILD_CONTAINER_WORKFLOW.read_text(encoding="utf-8")
        params_section = workflow.split("      - name: Determine build parameters", 1)[
            1
        ].split("      - name: Checkout code", 1)[0]

        assert "  workflow_run:" in workflow
        assert '    workflows: ["Build Wheel"]' in workflow
        assert "    types: [completed]" in workflow
        assert "  push:" in workflow
        assert "    tags: ['v*']" in workflow
        assert "  workflow_dispatch:" in workflow
        assert '        description: "Image tag override (default: latest)"' in workflow
        assert (
            "tags: quay.io/redhatproductsecurity/ai-guardian:${{ steps.params.outputs.image_tag }}"
            in workflow
        )
        assert (
            "tags: quay.io/redhatproductsecurity/ai-guardian:${{ github.sha }}"
            in workflow
        )
        assert 'echo "image_tag=latest"' in params_section
        assert 'echo "image_tag=${TAG}"' in params_section
        assert 'echo "image_tag=${TAG:-latest}"' in params_section
        assert 'echo "openshell_tag=latest"' in params_section
        assert 'echo "openshell_tag=${TAG}"' in params_section
        assert 'echo "openshell_tag=${TAG#openshell-}"' in params_section

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
            value == f"{config_path}:/sandbox/.config/ai-guardian.host.json:ro,z"
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
        assert not any(value.endswith("/ai-guardian.json:ro,z") for value in volumes)
        assert any(value.endswith("/profiles/team.json:ro,z") for value in volumes)
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
            value == f"{config_path}:/sandbox/.config/ai-guardian.host.json:ro,z"
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
            value == f"{option_config_path}:/sandbox/.config/ai-guardian.host.json:ro,z"
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
            value == f"{config_path}:/sandbox/.config/ai-guardian.host.json:ro,z"
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
            value == f"{config_path}:/sandbox/.config/ai-guardian.host.json:ro,z"
            for value in _volume_values(_captured_args(capture))
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
def test_entrypoint_reports_openshell_inference_auth(tmp_path):
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
        "AI_GUARDIAN_CONFIG_DIR": str(tmp_path / "config"),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_SETUP_SCOPE": "selected",
        "AI_GUARDIAN_OPEN_SHELL_INFERENCE": "true",
        "ANTHROPIC_API_KEY": "unused",
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "/bin/true"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Auth:         OpenShell inference route" in result.stdout
    assert "Auth:         Anthropic API key" not in result.stdout


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_adds_bare_to_direct_openshell_claude_command(tmp_path):
    args_path = tmp_path / "claude.args"
    _executable_script(
        tmp_path / "claude",
        """#!/usr/bin/env bash
printf '%s\n' "$@" > "$CLAUDE_ARGS"
""",
    )
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && "$2" = "--help" ]]; then
    printf 'usage: ai-guardian setup --ide {claude}\n'
    exit 0
fi
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
        "AI_GUARDIAN_CONFIG_DIR": str(tmp_path / "config"),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_SETUP_SCOPE": "selected",
        "AI_GUARDIAN_OPEN_SHELL_INFERENCE": "true",
        "CLAUDE_ARGS": str(args_path),
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT), "claude", "--print", "hello"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert args_path.read_text(encoding="utf-8").splitlines() == [
        "--bare",
        "--print",
        "hello",
    ]


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_wraps_plain_claude_in_openshell_interactive_shell(tmp_path):
    args_path = tmp_path / "claude.args"
    _executable_script(
        tmp_path / "claude",
        """#!/usr/bin/env bash
printf '%s\n' "$@" > "$CLAUDE_ARGS"
""",
    )
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "setup" && "$2" = "--help" ]]; then
    printf 'usage: ai-guardian setup --ide {claude}\n'
    exit 0
fi
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
        "AI_GUARDIAN_CONFIG_DIR": str(tmp_path / "config"),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "false",
        "AI_GUARDIAN_SETUP_SCOPE": "selected",
        "AI_GUARDIAN_OPEN_SHELL_INFERENCE": "true",
        "CLAUDE_ARGS": str(args_path),
    }

    result = subprocess.run(
        [
            "bash",
            str(ENTRYPOINT_SCRIPT),
            "/bin/bash",
            "-lc",
            "claude --print hello",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert args_path.read_text(encoding="utf-8").splitlines() == [
        "--bare",
        "--print",
        "hello",
    ]
    assert (Path(env["HOME"]) / ".bashrc").exists()
    assert (Path(env["HOME"]) / ".bash_profile").exists()


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
    host_config_path = config_dir / "ai-guardian.host.json"
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "true",
        "AI_GUARDIAN_HOST_CONFIG_PATH": str(host_config_path),
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
    host_config_path.parent.mkdir(parents=True)
    host_config_path.write_text("{}\n", encoding="utf-8")
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, stderr
    assert "Waiting for OpenShell to upload host ai-guardian config" in stdout
    assert "Using host ai-guardian config snapshot" in stdout


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_prefers_existing_sandbox_local_config(tmp_path):
    fake_ai_guardian = _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" = "--version" ]]; then
    echo "ai-guardian test"
fi
""",
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    local_config = config_dir / "ai-guardian.json"
    local_config.write_text('{"source": "sandbox-local"}\n', encoding="utf-8")
    host_config = tmp_path / "host-ai-guardian.json"
    host_config.write_text('{"source": "host"}\n', encoding="utf-8")
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "true",
        "AI_GUARDIAN_HOST_CONFIG_PATH": str(host_config),
        "AI_GUARDIAN_SETUP_SCOPE": "selected",
    }

    result = subprocess.run(
        [
            "bash",
            str(ENTRYPOINT_SCRIPT),
            "bash",
            "-c",
            "printf '%s|%s|' \"$AI_GUARDIAN_CONFIG_SOURCE\" "
            '"$AI_GUARDIAN_CONFIG_READ_ONLY"; cat "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"',
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Using sandbox-local ai-guardian config" in result.stdout
    assert 'sandbox-local|false|{"source": "sandbox-local"}' in result.stdout
    assert local_config.read_text(encoding="utf-8") == '{"source": "sandbox-local"}\n'
    assert json.loads(
        (config_dir / ".ai-guardian-config-metadata.json").read_text(encoding="utf-8")
    ) == {"source": "sandbox-local", "read_only": False}


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_uses_host_config_as_writable_snapshot(tmp_path):
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" = "--version" ]]; then
    echo "ai-guardian test"
fi
""",
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    host_config = tmp_path / "host-ai-guardian.json"
    host_config.write_text('{"source": "host"}\n', encoding="utf-8")
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "true",
        "AI_GUARDIAN_HOST_CONFIG_PATH": str(host_config),
        "AI_GUARDIAN_SETUP_SCOPE": "selected",
    }

    result = subprocess.run(
        [
            "bash",
            str(ENTRYPOINT_SCRIPT),
            "bash",
            "-c",
            "printf '%s|%s|' \"$AI_GUARDIAN_CONFIG_SOURCE\" "
            '"$AI_GUARDIAN_CONFIG_READ_ONLY"; '
            "printf '{\"changed\": true}\\n' > "
            '"$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"; '
            'cat "$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"',
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Using host ai-guardian config snapshot" in result.stdout
    assert 'host|false|{"changed": true}' in result.stdout
    assert host_config.read_text(encoding="utf-8") == '{"source": "host"}\n'
    assert json.loads(
        (config_dir / ".ai-guardian-config-metadata.json").read_text(encoding="utf-8")
    ) == {"source": "host", "read_only": False}


@pytest.mark.skipif(
    os.name == "nt", reason="The container entrypoint is a POSIX shell script"
)
def test_entrypoint_restores_snapshot_over_existing_sandbox_config(tmp_path):
    _executable_script(
        tmp_path / "ai-guardian",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" = "--version" ]]; then
    echo "ai-guardian test"
fi
""",
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    local_config = config_dir / "ai-guardian.json"
    local_config.write_text('{"source": "image"}\n', encoding="utf-8")
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text('{"source": "snapshot"}\n', encoding="utf-8")
    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "AI_GUARDIAN_AGENT": "codex",
        "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
        "AI_GUARDIAN_HOST_CONFIG_MOUNTED": "true",
        "AI_GUARDIAN_HOST_CONFIG_PATH": str(snapshot_path),
        "AI_GUARDIAN_RESTORE_CONFIG": "true",
        "AI_GUARDIAN_SETUP_SCOPE": "selected",
    }

    result = subprocess.run(
        [
            "bash",
            str(ENTRYPOINT_SCRIPT),
            "bash",
            "-c",
            "printf '%s|%s|' \"$AI_GUARDIAN_CONFIG_SOURCE\" "
            '"$AI_GUARDIAN_CONFIG_READ_ONLY"; cat '
            '"$AI_GUARDIAN_CONFIG_DIR/ai-guardian.json"',
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Restoring ai-guardian config snapshot" in result.stdout
    assert 'snapshot|false|{"source": "snapshot"}' in result.stdout
    assert json.loads(local_config.read_text(encoding="utf-8")) == {
        "source": "snapshot"
    }
    assert json.loads(
        (config_dir / ".ai-guardian-config-metadata.json").read_text(encoding="utf-8")
    ) == {"source": "snapshot", "read_only": False}


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
