"""Tests for the developer-only Container smoke-test runner."""

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "container" / "tests" / "test_container_agents.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "manual_container_runner", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides):
    values = {
        "prompt": "hello",
        "codex_model": None,
        "opencode_agent": "build",
        "opencode_model": "openai/gpt-5.6-luna",
        "openai_model": "gpt-5.6-luna",
        "anthropic_model": "claude-sonnet-4-6",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_container_runner_has_broader_cli_matrix():
    runner = _load_runner()

    assert set(runner.CASES) == {
        "claude",
        "copilot",
        "codex",
        "gemini",
        "antigravity",
        "kiro",
        "openclaw",
        "opencode",
        "pi-anthropic",
        "pi-openai",
        "pi-openai-codex",
        "crush",
    }


def test_container_runner_builds_model_commands():
    runner = _load_runner()
    args = _args()

    assert runner.build_cli_command(runner.CASES["codex"], args) == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "hello",
    ]
    assert runner.build_cli_command(runner.CASES["opencode"], args) == [
        "opencode",
        "--agent",
        "build",
        "run",
        "hello",
        "--model",
        "openai/gpt-5.6-luna",
    ]
    assert runner.build_cli_command(runner.CASES["pi-openai"], args) == [
        "pi",
        "-p",
        "hello",
        "--model",
        "gpt-5.6-luna",
        "--provider",
        "openai",
    ]


def test_container_runner_uses_help_probe_for_noninteractive_cli_cases():
    runner = _load_runner()
    args = _args()

    assert runner.build_cli_command(runner.CASES["antigravity"], args) == [
        "agy",
        "--help",
    ]
    assert runner.build_cli_command(runner.CASES["kiro"], args) == [
        "kiro-cli",
        "--help",
    ]


def test_container_runner_builds_runtime_safe_create_command():
    runner = _load_runner()
    args = _args(image="localhost/ai-guardian:test", repo="/tmp/repo")
    command = runner.build_create_command(
        ["uv", "run", "ai-guardian"],
        "podman",
        runner.CASES["pi-openai"],
        args,
        "ag-ct-pio-test",
    )

    assert command[:12] == [
        "uv",
        "run",
        "ai-guardian",
        "sandbox",
        "create",
        "--runtime",
        "container",
        "--container-engine",
        "podman",
        "--name",
        "ag-ct-pio-test",
        "--image",
    ]
    assert "--agent-provider" in command
    assert command[command.index("--agent-provider") + 1] == "openai"
    assert command[command.index("--repo") + 1] == "/tmp/repo"
    assert "--provider" not in command


def test_container_runner_generates_unique_names():
    runner = _load_runner()

    name = runner.container_name("pi-openai-codex")

    assert name.startswith("ag-ct-pioc-")
    assert len(name) > len("ag-ct-pioc-")


def test_container_runner_closes_stdin_for_commands():
    runner = _load_runner()

    with patch.object(runner.subprocess, "run") as run:
        run.return_value.returncode = 0
        assert runner._run(["true"], 10) == 0

    assert run.call_args.kwargs["stdin"] is runner.subprocess.DEVNULL


def test_container_runner_checks_for_partial_container_after_failed_create():
    runner = _load_runner()

    with patch.object(runner.subprocess, "run") as run:
        run.return_value.returncode = 1
        assert runner._container_exists("podman", "ag-test") is False

    assert run.call_args.kwargs["stdin"] is runner.subprocess.DEVNULL
    assert run.call_args.kwargs["capture_output"] is True
