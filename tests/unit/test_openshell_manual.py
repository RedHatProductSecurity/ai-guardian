"""Tests for the developer-only OpenShell smoke-test runner."""

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "container" / "tests" / "test_openshell_agents.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "manual_openshell_runner", SCRIPT_PATH
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


def test_manual_runner_has_expected_cases():
    runner = _load_runner()

    assert set(runner.CASES) == {
        "claude",
        "codex",
        "copilot",
        "opencode-claude",
        "opencode-openai",
        "opencode-openai-api-key",
        "pi-anthropic",
        "pi-openai",
        "pi-openai-codex",
    }
    assert runner.CASES["pi-openai-codex"].known_failure is True
    assert runner.CASES["opencode-openai-api-key"].requires_codex_api_key is True
    assert runner.CASES["copilot"].requires_gateway_provider is True
    assert runner.CASES["opencode-claude"].opencode_profile == "claude"


def test_manual_runner_builds_requested_cli_commands():
    runner = _load_runner()
    args = _args()

    assert runner.build_cli_command(runner.CASES["codex"], args) == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "hello",
    ]
    assert runner.build_cli_command(runner.CASES["opencode-openai"], args) == [
        "opencode",
        "--agent",
        "build",
        "run",
        "hello",
        "--model",
        "openai/gpt-5.6-luna",
    ]
    assert runner.build_cli_command(runner.CASES["opencode-claude"], args) == [
        "opencode",
        "--agent",
        "claude",
        "run",
        "hello",
        "--model",
        "claude-sonnet-4-6",
    ]
    assert runner.build_cli_command(runner.CASES["opencode-openai-api-key"], args) == [
        "opencode",
        "--agent",
        "build",
        "run",
        "hello",
        "--model",
        "openai/gpt-5.6-luna",
    ]
    assert runner.build_cli_command(runner.CASES["pi-openai-codex"], args) == [
        "pi",
        "-p",
        "hello",
        "--model",
        "gpt-5.6-luna",
        "--provider",
        "openai-codex",
    ]


def test_manual_runner_parses_provider_overrides_without_values():
    runner = _load_runner()

    assert runner.parse_provider_overrides(
        ["opencode-openai=my-openai", "pi-anthropic=my-anthropic"]
    ) == {
        "opencode-openai": "my-openai",
        "pi-anthropic": "my-anthropic",
    }


def test_manual_runner_generates_names_within_openshell_limit():
    runner = _load_runner()

    name = runner.sandbox_name("pi-openai-codex")

    assert len(name) <= 19
    assert name.startswith("ag-pioc-")


def test_manual_runner_closes_stdin_for_noninteractive_commands():
    runner = _load_runner()

    with patch.object(runner.subprocess, "run") as run:
        run.return_value.returncode = 0
        assert runner._run(["true"], 10) == 0

    assert run.call_args.kwargs["stdin"] is runner.subprocess.DEVNULL


def test_manual_runner_checks_for_partial_sandbox_after_failed_create():
    runner = _load_runner()

    with patch.object(runner.subprocess, "run") as run:
        run.return_value.returncode = 1
        assert runner._sandbox_exists("openshell", "ag-test") is False

    assert run.call_args.kwargs["stdin"] is runner.subprocess.DEVNULL
    assert run.call_args.kwargs["capture_output"] is True
