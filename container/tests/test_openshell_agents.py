#!/usr/bin/env python3
"""Run opt-in live OpenShell CLI/provider smoke tests.

This script is intentionally for a developer workstation. It delegates local
credential discovery to ``ai-guardian sandbox create`` and never accepts a
credential value as an argument. CI should continue to use the deterministic
unit and image tests instead of this live-provider runner.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

DEFAULT_IMAGE = os.environ.get(
    "AI_GUARDIAN_OPEN_SHELL_IMAGE",
    "quay.io/redhatproductsecurity/ai-guardian-openshell:latest",
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
    """One CLI/provider combination that can be tested locally."""

    name: str
    cli: str
    description: str
    agent_provider: Optional[str] = None
    opencode_profile: Optional[str] = None
    requires_gateway_provider: bool = False
    requires_codex_api_key: bool = False
    known_failure: bool = False


CASES = {
    "claude": SmokeCase(
        name="claude",
        cli="claude",
        description="Claude Code through a Claude-compatible OpenShell provider",
    ),
    "codex": SmokeCase(
        name="codex",
        cli="codex",
        description="Native Codex through the OpenShell Codex provider",
    ),
    "copilot": SmokeCase(
        name="copilot",
        cli="copilot",
        description="GitHub Copilot CLI setup through an OpenShell provider",
        requires_gateway_provider=True,
    ),
    "opencode-claude": SmokeCase(
        name="opencode-claude",
        cli="opencode",
        description="OpenCode with the tested Claude/Vertex inference route",
        opencode_profile="claude",
        requires_gateway_provider=True,
    ),
    "opencode-openai": SmokeCase(
        name="opencode-openai",
        cli="opencode",
        description="OpenCode with a generic OpenAI-compatible model",
        requires_gateway_provider=True,
    ),
    "opencode-openai-api-key": SmokeCase(
        name="opencode-openai-api-key",
        cli="opencode",
        description="OpenCode with a Codex API-key provider discovered automatically",
        requires_codex_api_key=True,
    ),
    "pi-anthropic": SmokeCase(
        name="pi-anthropic",
        cli="pi",
        description="Pi through the Anthropic-compatible OpenShell route",
        agent_provider="anthropic",
    ),
    "pi-openai": SmokeCase(
        name="pi-openai",
        cli="pi",
        description="Pi through an OpenAI API-key provider",
        agent_provider="openai",
    ),
    "pi-openai-codex": SmokeCase(
        name="pi-openai-codex",
        cli="pi",
        description="Diagnostic for the unsupported OpenShell Pi Codex OAuth route",
        agent_provider="openai-codex",
        known_failure=True,
    ),
}

CASE_NAME_PARTS = {
    "claude": "cld",
    "codex": "cdx",
    "copilot": "cop",
    "opencode-claude": "occl",
    "opencode-openai": "oc",
    "opencode-openai-api-key": "ocak",
    "pi-anthropic": "pia",
    "pi-openai": "pio",
    "pi-openai-codex": "pioc",
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


def _host_codex_api_key_available() -> bool:
    """Return whether Codex is logged in with an API key, without printing it."""
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    try:
        auth = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(auth, dict) and bool(auth.get("OPENAI_API_KEY"))


def parse_provider_overrides(values: Iterable[str]) -> Dict[str, str]:
    """Parse ``case=provider-name`` values without handling credential data."""
    overrides: Dict[str, str] = {}
    for value in values:
        case_name, separator, provider = value.partition("=")
        if not separator or case_name not in CASES or not provider.strip():
            choices = ", ".join(CASES)
            raise ValueError(
                f"provider override must use CASE=NAME for one of {choices}"
            )
        overrides[case_name] = provider.strip()
    return overrides


def sandbox_name(case_name: str) -> str:
    """Return a unique name within OpenShell's 19-character limit."""
    try:
        case_part = CASE_NAME_PARTS[case_name]
    except KeyError as exc:
        raise ValueError(f"unsupported smoke case: {case_name}") from exc
    return f"ag-{case_part}-{uuid.uuid4().hex[:8]}"


def build_cli_command(case: SmokeCase, args: argparse.Namespace) -> List[str]:
    """Build the command executed inside a prepared sandbox."""
    prompt = args.prompt
    if case.name == "claude":
        return [
            "claude",
            "--bare",
            "-p",
            prompt,
            "--model",
            args.anthropic_model,
        ]
    if case.name == "codex":
        command = ["codex", "exec", "--skip-git-repo-check"]
        if args.codex_model:
            command.extend(["--model", args.codex_model])
        return [*command, prompt]
    if case.name == "copilot":
        return ["copilot", "--help"]
    if case.name == "opencode-claude":
        return [
            "opencode",
            "--agent",
            case.opencode_profile or args.opencode_agent,
            "run",
            prompt,
            "--model",
            args.anthropic_model,
        ]
    if case.name in {"opencode-openai", "opencode-openai-api-key"}:
        return [
            "opencode",
            "--agent",
            case.opencode_profile or args.opencode_agent,
            "run",
            prompt,
            "--model",
            args.opencode_model,
        ]
    if case.name == "pi-anthropic":
        return [
            "pi",
            "-p",
            prompt,
            "--model",
            args.anthropic_model,
            "--provider",
            "anthropic",
        ]
    if case.name == "pi-openai":
        return [
            "pi",
            "-p",
            prompt,
            "--model",
            args.openai_model,
            "--provider",
            "openai",
        ]
    if case.name == "pi-openai-codex":
        return [
            "pi",
            "-p",
            prompt,
            "--model",
            args.openai_model,
            "--provider",
            "openai-codex",
        ]
    raise ValueError(f"unsupported smoke case: {case.name}")


def build_create_command(
    ai_guardian: Sequence[str],
    openshell_cli: str,
    case: SmokeCase,
    args: argparse.Namespace,
    name: str,
    provider_overrides: Dict[str, str],
) -> List[str]:
    """Build the credential-safe sandbox creation command."""
    command = [
        *ai_guardian,
        "sandbox",
        "create",
        "--runtime",
        "openshell",
        "--openshell-cli",
        openshell_cli,
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
        command.extend(
            [
                "--opencode-agent-profile",
                case.opencode_profile or args.opencode_agent,
            ]
        )
    if case.agent_provider:
        command.extend(["--agent-provider", case.agent_provider])
    if case.name == "claude" or case.name == "pi-anthropic":
        command.extend(["--model", args.anthropic_model])
    elif case.name == "opencode-claude":
        command.extend(["--model", args.anthropic_model])
    elif case.name in {"opencode-openai", "opencode-openai-api-key"}:
        command.extend(["--model", args.opencode_model])
    elif case.name in {"pi-openai", "pi-openai-codex"}:
        command.extend(["--model", args.openai_model])
    if case.name in provider_overrides:
        command.extend(["--provider", provider_overrides[case.name]])

    # Create the sandbox and run a no-op bootstrap command first. The actual
    # agent command is launched separately through the supported OpenShell API.
    command.extend(["--", "/bin/true"])
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


def _find_podman_container(podman: str, name: str) -> Optional[str]:
    """Find a local OpenShell container when the gateway exposes one."""
    filters = (
        f"label=ai-guardian.name={name}",
        f"name={name}",
    )
    for filter_value in filters:
        result = subprocess.run(
            [podman, "ps", "--all", "--filter", filter_value, "--format", "{{.ID}}"],
            check=False,
            capture_output=True,
            text=True,
        )
        container_id = next(
            (line.strip() for line in result.stdout.splitlines() if line.strip()),
            None,
        )
        if container_id:
            return container_id
    return None


def _sandbox_exists(openshell_cli: str, name: str) -> bool:
    """Check whether a failed create left a sandbox behind."""
    result = subprocess.run(
        [openshell_cli, "sandbox", "get", name],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _execute_case(
    openshell_cli: str,
    podman: str,
    executor: str,
    name: str,
    command: Sequence[str],
    timeout: int,
) -> int:
    """Execute one agent command using OpenShell or local Podman."""
    if executor == "openshell":
        return _run(
            [openshell_cli, "sandbox", "exec", "--name", name, "--", *command],
            timeout,
        )

    container_id = _find_podman_container(podman, name)
    if not container_id:
        print(
            "ERROR: no local Podman container was found for this OpenShell sandbox; "
            "use --executor openshell or a gateway with a local Podman driver",
            file=sys.stderr,
        )
        return 127
    return _run([podman, "exec", container_id, *command], timeout)


def _delete_sandbox(ai_guardian: Sequence[str], openshell_cli: str, name: str) -> None:
    """Best-effort cleanup for a temporary sandbox."""
    result = subprocess.run(
        [
            *ai_guardian,
            "sandbox",
            "delete",
            "--runtime",
            "openshell",
            "--openshell-cli",
            openshell_cli,
            name,
        ],
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        print(f"WARNING: unable to delete temporary sandbox {name}")


def _parser() -> argparse.ArgumentParser:
    choices = ", ".join(CASES)
    parser = argparse.ArgumentParser(
        description=(
            "Run live OpenShell CLI/provider smoke tests with local credentials. "
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
        help=(
            "Run every supported case and diagnostic case, skipping cases missing "
            "required provider names or local credentials"
        ),
    )
    parser.add_argument(
        "--prompt", default="hello", help="Prompt sent to each CLI (default: hello)"
    )
    parser.add_argument(
        "--image", default=DEFAULT_IMAGE, help="OpenShell image reference"
    )
    parser.add_argument(
        "--repo", help="Optional repository snapshot to upload; omitted by default"
    )
    parser.add_argument(
        "--provider",
        action="append",
        default=[],
        metavar="CASE=NAME",
        help="Existing gateway provider for a case",
    )
    parser.add_argument(
        "--executor",
        choices=("openshell", "podman"),
        default="openshell",
        help="How to launch the CLI (default: openshell)",
    )
    parser.add_argument(
        "--openshell-cli",
        default=os.environ.get("OPENSHELL_CLI", "openshell"),
        help="OpenShell executable",
    )
    parser.add_argument(
        "--podman",
        default=os.environ.get("CONTAINER_ENGINE", "podman"),
        help="Podman executable for --executor podman",
    )
    parser.add_argument(
        "--ai-guardian-command",
        dest="ai_guardian",
        default=os.environ.get("AI_GUARDIAN_COMMAND", DEFAULT_AI_GUARDIAN_COMMAND),
        help="Host AI Guardian command; defaults to 'uv run ai-guardian' in the checkout",
    )
    parser.add_argument(
        "--opencode-agent",
        default="build",
        help="OpenCode agent profile (default: build)",
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
        "--keep", action="store_true", help="Keep created sandboxes for inspection"
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
    """Run selected local OpenShell smoke tests."""
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.case and not args.all:
        parser.error("select at least one --case or use --all")
    if args.case and args.all:
        parser.error("--all cannot be combined with --case")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    try:
        provider_overrides = parse_provider_overrides(args.provider)
        ai_guardian = _split_command(args.ai_guardian)
    except ValueError as exc:
        parser.error(str(exc))

    if not _command_available(ai_guardian):
        parser.error(f"AI Guardian command is not available: {args.ai_guardian}")
    if not _command_available([args.openshell_cli]):
        parser.error(f"OpenShell command is not available: {args.openshell_cli}")
    if args.executor == "podman" and not _command_available([args.podman]):
        parser.error(f"Podman command is not available: {args.podman}")

    selected = list(CASES) if args.all else list(dict.fromkeys(args.case))
    created: List[str] = []
    results: List[str] = []
    unexpected_failure = False

    print("Checking OpenShell gateway...")
    if _run([args.openshell_cli, "status"], args.timeout) != 0:
        return 1

    try:
        for case_name in selected:
            case = CASES[case_name]
            if case.requires_gateway_provider and case_name not in provider_overrides:
                print(
                    f"\nSKIP {case_name}: pass --provider {case_name}=NAME "
                    "for an existing OpenAI-compatible OpenShell gateway provider"
                )
                results.append(f"SKIP {case_name}")
                continue
            if case.requires_codex_api_key and not _host_codex_api_key_available():
                print(
                    f"\nSKIP {case_name}: the host Codex auth file has no API-key login"
                )
                results.append(f"SKIP {case_name}")
                continue

            name = sandbox_name(case_name)
            created.append(name)
            print(f"\n=== {case_name}: {case.description} ===")
            create_command = build_create_command(
                ai_guardian,
                args.openshell_cli,
                case,
                args,
                name,
                provider_overrides,
            )
            create_result = _run(create_command, args.timeout)
            if create_result != 0 and not _sandbox_exists(args.openshell_cli, name):
                created.pop()
            if create_result == 0:
                command_result = _execute_case(
                    args.openshell_cli,
                    args.podman,
                    args.executor,
                    name,
                    build_cli_command(case, args),
                    args.timeout,
                )
            else:
                command_result = create_result

            if command_result == 0:
                print(f"PASS {case_name}")
                results.append(f"PASS {case_name}")
            elif case.known_failure:
                print(
                    f"EXPECTED FAILURE {case_name}: this OpenShell scenario is "
                    "unsupported because Pi cannot consume resolver-backed OAuth "
                    "credentials"
                )
                results.append(f"EXPECTED FAILURE {case_name}")
            else:
                print(f"FAIL {case_name} (exit {command_result})")
                results.append(f"FAIL {case_name}")
                unexpected_failure = True
                if args.stop_on_failure:
                    break
    finally:
        if args.keep:
            print("\nKeeping sandboxes:")
            for name in created:
                print(f"  {name}")
        else:
            print("\nCleaning up temporary sandboxes...")
            for name in reversed(created):
                _delete_sandbox(ai_guardian, args.openshell_cli, name)

    print("\nSummary:")
    for result in results:
        print(f"  {result}")
    return 1 if unexpected_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
