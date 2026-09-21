#!/usr/bin/env python3
"""Run opt-in live Docker/Podman CLI smoke tests.

This script is intentionally for a developer workstation. It creates one
temporary AI Guardian container per case, runs the selected CLI, and removes
the container afterward. It never accepts credential values as arguments;
container credential discovery remains controlled by the host environment and
the normal sandbox command.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_IMAGE = os.environ.get(
    "AI_GUARDIAN_CONTAINER_IMAGE",
    "quay.io/redhatproductsecurity/ai-guardian:latest",
)
DEFAULT_OPENCODE_MODEL = os.environ.get(
    "AI_GUARDIAN_OPENCODE_TEST_MODEL", "openai/gpt-5.6-luna"
)
DEFAULT_OPENAI_MODEL = os.environ.get("AI_GUARDIAN_OPENAI_TEST_MODEL", "gpt-5.6-luna")
DEFAULT_ANTHROPIC_MODEL = os.environ.get(
    "AI_GUARDIAN_ANTHROPIC_TEST_MODEL", "claude-sonnet-4-6"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AI_GUARDIAN_COMMAND = (
    "uv run ai-guardian"
    if (REPOSITORY_ROOT / "pyproject.toml").is_file()
    else "ai-guardian"
)


@dataclass(frozen=True)
class SmokeCase:
    """One Container CLI/provider combination that can be tested locally."""

    name: str
    cli: str
    description: str
    command_kind: str = "help"
    executable: Optional[str] = None
    agent_provider: Optional[str] = None


CASES = {
    "claude": SmokeCase(
        name="claude",
        cli="claude",
        description="Claude Code through container API-key or Vertex credentials",
        command_kind="claude",
    ),
    "copilot": SmokeCase(
        name="copilot",
        cli="copilot",
        description="GitHub Copilot CLI installation and hook setup",
    ),
    "codex": SmokeCase(
        name="codex",
        cli="codex",
        description="Native Codex through container credentials",
        command_kind="codex",
    ),
    "gemini": SmokeCase(
        name="gemini",
        cli="gemini",
        description="Gemini CLI installation and hook setup",
    ),
    "antigravity": SmokeCase(
        name="antigravity",
        cli="antigravity",
        description="Antigravity CLI installation and hook setup",
        executable="agy",
    ),
    "kiro": SmokeCase(
        name="kiro",
        cli="kiro",
        description="Kiro CLI after runtime ToS consent",
        executable="kiro-cli",
    ),
    "openclaw": SmokeCase(
        name="openclaw",
        cli="openclaw",
        description="OpenClaw CLI installation and hook setup",
    ),
    "opencode": SmokeCase(
        name="opencode",
        cli="opencode",
        description="OpenCode with a generic OpenAI-compatible model",
        command_kind="opencode",
    ),
    "pi-anthropic": SmokeCase(
        name="pi-anthropic",
        cli="pi",
        description="Pi with its Anthropic provider",
        command_kind="pi",
        agent_provider="anthropic",
    ),
    "pi-openai": SmokeCase(
        name="pi-openai",
        cli="pi",
        description="Pi with its OpenAI API-key provider",
        command_kind="pi",
        agent_provider="openai",
    ),
    "pi-openai-codex": SmokeCase(
        name="pi-openai-codex",
        cli="pi",
        description="Pi with its local OpenAI Codex OAuth provider",
        command_kind="pi",
        agent_provider="openai-codex",
    ),
    "crush": SmokeCase(
        name="crush",
        cli="crush",
        description="Crush CLI installation and hook setup",
    ),
}

CASE_NAME_PARTS = {
    "claude": "cld",
    "copilot": "cop",
    "codex": "cdx",
    "gemini": "gem",
    "antigravity": "agy",
    "kiro": "kir",
    "openclaw": "oclaw",
    "opencode": "oc",
    "pi-anthropic": "pia",
    "pi-openai": "pio",
    "pi-openai-codex": "pioc",
    "crush": "cru",
}


def _split_command(value: str) -> List[str]:
    """Split a configurable executable command without invoking a shell."""
    command = shlex.split(value)
    if not command:
        raise ValueError("command must not be empty")
    return command


def _command_available(command: Sequence[str]) -> bool:
    """Return whether the first executable in a command is available."""
    executable = command[0]
    return bool(shutil.which(executable) or os.path.isabs(executable))


def container_name(case_name: str) -> str:
    """Return a unique managed container name."""
    try:
        case_part = CASE_NAME_PARTS[case_name]
    except KeyError as exc:
        raise ValueError(f"unsupported smoke case: {case_name}") from exc
    return f"ag-ct-{case_part}-{uuid.uuid4().hex[:8]}"


def build_cli_command(case: SmokeCase, args: argparse.Namespace) -> List[str]:
    """Build the command executed inside a prepared container."""
    prompt = args.prompt
    executable = case.executable or case.cli
    if case.command_kind == "help":
        return [executable, "--help"]
    if case.command_kind == "claude":
        return [
            executable,
            "--bare",
            "-p",
            prompt,
            "--model",
            args.anthropic_model,
        ]
    if case.command_kind == "codex":
        command = [executable, "exec", "--skip-git-repo-check"]
        if args.codex_model:
            command.extend(["--model", args.codex_model])
        return [*command, prompt]
    if case.command_kind == "opencode":
        return [
            executable,
            "--agent",
            args.opencode_agent,
            "run",
            prompt,
            "--model",
            args.opencode_model,
        ]
    if case.command_kind == "pi":
        return [
            executable,
            "-p",
            prompt,
            "--model",
            (
                args.anthropic_model
                if case.agent_provider == "anthropic"
                else args.openai_model
            ),
            "--provider",
            case.agent_provider,
        ]
    raise ValueError(f"unsupported command kind: {case.command_kind}")


def build_create_command(
    ai_guardian: Sequence[str],
    container_engine: str,
    case: SmokeCase,
    args: argparse.Namespace,
    name: str,
) -> List[str]:
    """Build the credential-safe Container creation command."""
    command = [
        *ai_guardian,
        "sandbox",
        "create",
        "--runtime",
        "container",
        "--container-engine",
        container_engine,
        "--name",
        name,
        "--image",
        args.image,
        "--cli",
        case.cli,
    ]
    if args.repo:
        command.extend(["--repo", args.repo])
    if case.cli == "opencode":
        command.extend(["--opencode-agent-profile", args.opencode_agent])
    if case.agent_provider:
        command.extend(["--agent-provider", case.agent_provider])
    if case.command_kind in {"claude", "pi"} and case.agent_provider != "openai":
        command.extend(["--model", args.anthropic_model])
    elif case.command_kind in {"opencode", "pi"}:
        command.extend(
            [
                "--model",
                (
                    args.opencode_model
                    if case.command_kind == "opencode"
                    else args.openai_model
                ),
            ]
        )
    return command


def _run(command: Sequence[str], timeout: int) -> int:
    """Run a command while preserving its live output."""
    try:
        return subprocess.run(
            list(command),
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        ).returncode
    except FileNotFoundError:
        print(f"ERROR: executable not found: {command[0]}", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(f"ERROR: command timed out after {timeout}s: {command[0]}")
        return 124


def _container_exists(container_engine: str, name: str) -> bool:
    """Check whether a failed create left a managed container behind."""
    result = subprocess.run(
        [container_engine, "inspect", name],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _execute_case(
    container_engine: str,
    name: str,
    command: Sequence[str],
    timeout: int,
) -> int:
    """Execute one CLI command in the managed container."""
    return _run(
        [container_engine, "exec", "--interactive", name, *command],
        timeout,
    )


def _delete_container(
    ai_guardian: Sequence[str], container_engine: str, name: str
) -> None:
    """Best-effort cleanup for a temporary Container sandbox."""
    result = subprocess.run(
        [
            *ai_guardian,
            "sandbox",
            "delete",
            "--runtime",
            "container",
            "--container-engine",
            container_engine,
            name,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    if result.returncode != 0:
        print(f"WARNING: unable to delete temporary container {name}")


def _parser() -> argparse.ArgumentParser:
    choices = ", ".join(CASES)
    parser = argparse.ArgumentParser(
        description=(
            "Run live Docker/Podman CLI smoke tests with local credentials. "
            "Select --case or --all; no credential values are accepted."
        )
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(CASES),
        help=f"Case to run; available: {choices}",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every Container CLI/provider case one by one",
    )
    parser.add_argument(
        "--prompt", default="hello", help="Prompt sent to model cases (default: hello)"
    )
    parser.add_argument(
        "--image", default=DEFAULT_IMAGE, help="Container image reference"
    )
    parser.add_argument("--repo", help="Optional repository to mount")
    parser.add_argument(
        "--container-engine",
        default=os.environ.get("CONTAINER_ENGINE", "podman"),
        help="Docker/Podman executable",
    )
    parser.add_argument(
        "--ai-guardian-command",
        dest="ai_guardian",
        default=os.environ.get("AI_GUARDIAN_COMMAND", DEFAULT_AI_GUARDIAN_COMMAND),
        help="Host AI Guardian command; defaults to 'uv run ai-guardian' in the checkout",
    )
    parser.add_argument(
        "--opencode-agent", default="build", help="OpenCode agent profile"
    )
    parser.add_argument(
        "--opencode-model", default=DEFAULT_OPENCODE_MODEL, help="OpenCode model"
    )
    parser.add_argument(
        "--openai-model", default=DEFAULT_OPENAI_MODEL, help="Pi OpenAI/Codex model"
    )
    parser.add_argument(
        "--anthropic-model",
        default=DEFAULT_ANTHROPIC_MODEL,
        help="Claude/Pi Anthropic model",
    )
    parser.add_argument("--codex-model", help="Optional native Codex model")
    parser.add_argument(
        "--keep", action="store_true", help="Keep created containers for inspection"
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop after the first unexpected failure",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout per create/exec operation in seconds",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run selected local Container smoke tests."""
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.case and not args.all:
        parser.error("select at least one --case or use --all")
    if args.case and args.all:
        parser.error("--all cannot be combined with --case")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    try:
        ai_guardian = _split_command(args.ai_guardian)
    except ValueError as exc:
        parser.error(str(exc))

    if not _command_available(ai_guardian):
        parser.error(f"AI Guardian command is not available: {args.ai_guardian}")
    if not _command_available([args.container_engine]):
        parser.error(f"Container engine is not available: {args.container_engine}")

    selected = list(CASES) if args.all else list(dict.fromkeys(args.case))
    created: List[str] = []
    results: List[str] = []
    unexpected_failure = False

    print("Checking Container engine...")
    if _run([args.container_engine, "info"], args.timeout) != 0:
        return 1

    try:
        for case_name in selected:
            case = CASES[case_name]
            name = container_name(case_name)
            print(f"\n=== {case_name}: {case.description} ===")
            create_command = build_create_command(
                ai_guardian,
                args.container_engine,
                case,
                args,
                name,
            )
            create_result = _run(create_command, args.timeout)
            if create_result == 0 or _container_exists(args.container_engine, name):
                created.append(name)
            if create_result == 0:
                command_result = _execute_case(
                    args.container_engine,
                    name,
                    build_cli_command(case, args),
                    args.timeout,
                )
            else:
                command_result = create_result

            if command_result == 0:
                print(f"PASS {case_name}")
                results.append(f"PASS {case_name}")
            else:
                print(f"FAIL {case_name} (exit {command_result})")
                results.append(f"FAIL {case_name}")
                unexpected_failure = True
                if args.stop_on_failure:
                    break
    finally:
        if args.keep:
            print("\nKeeping containers:")
            for name in created:
                print(f"  {name}")
        else:
            print("\nCleaning up temporary containers...")
            for name in reversed(created):
                _delete_container(ai_guardian, args.container_engine, name)

    print("\nSummary:")
    for result in results:
        print(f"  {result}")
    return 1 if unexpected_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
