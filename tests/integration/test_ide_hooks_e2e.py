"""Isolated end-to-end checks for every supported IDE integration.

The command-hook integrations are installed into a temporary home/project and
their generated commands are invoked with representative allow, block, and
post-tool-output payloads. Plugin and extension integrations are verified at
the generated-source boundary because their host runtimes are not available in
this repository's test environment. Junie is verified as MCP-only.

Set AI_GUARDIAN_TEST_IDE to run one IDE from the matrix. Without it, the test
runs the complete local matrix. The release-readiness workflow sets the
variable per matrix job so a failure identifies both the IDE and the hook
event under test.
"""

import contextlib
import io
import json
import os
import platform
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import pytest

from ai_guardian.setup import (
    _MCP_IDE_CONFIGS,
    _install_mcp_config,
    get_mcp_config_path,
)
from ai_guardian.setup.hooks import IDESetup
from ai_guardian.setup.utils import _resolve_opencode_config, _strip_jsonc_comments

EXTERNAL_IDES = (
    "claude",
    "cursor",
    "copilot",
    "codex",
    "windsurf",
    "gemini",
    "cline",
    "zoocode",
    "kiro",
    "aiderdesk",
    "openclaw",
    "opencode",
    "augment",
    "crush",
    "junie",
)

POST_OUTPUT_MARKER = "E2E_GUARDIAN_MARKER_A1B2C3D4E5F6G7H8"
POST_OUTPUT_PATTERN = r"E2E_GUARDIAN_MARKER_[A-Z0-9]{16}"


# The event selected for each representative path is the event that the
# generated configuration actually wires. Entries absent from an IDE's native
# contract are intentionally omitted (for example, Copilot's setup currently
# has no PostToolUse hook and Crush currently has PreToolUse only).
REPRESENTATIVE_EVENTS = {
    "claude": {
        "allow": "UserPromptSubmit",
        "block": "PreToolUse",
        "post": "PostToolUse",
    },
    "cursor": {
        "allow": "beforeSubmitPrompt",
        "block": "beforeReadFile",
        "post": "afterShellExecution",
    },
    "copilot": {"allow": "userPromptSubmitted", "block": "preToolUse"},
    "codex": {
        "allow": "UserPromptSubmit",
        "block": "PreToolUse",
        "post": "PostToolUse",
    },
    "windsurf": {
        "allow": "pre_user_prompt",
        "block": "pre_read_code",
        "post": "post_run_command",
    },
    "gemini": {
        "allow": "BeforeAgent",
        "block": "BeforeTool",
        "post": "AfterTool",
    },
    "cline": {
        "allow": "UserPromptSubmit",
        "block": "PreToolUse",
        "post": "PostToolUse",
    },
    "zoocode": {
        "allow": "UserPromptSubmit",
        "block": "PreToolUse",
        "post": "PostToolUse",
    },
    "kiro": {
        "allow": "prompt_submit",
        "block": "pre_tool_use",
        "post": "post_tool_use",
    },
    "augment": {"block": "PreToolUse", "post": "PostToolUse"},
    "crush": {"allow": "PreToolUse", "block": "PreToolUse"},
}


def _selected_ides() -> Tuple[str, ...]:
    requested = os.environ.get("AI_GUARDIAN_TEST_IDE")
    if requested:
        if requested not in EXTERNAL_IDES:
            raise AssertionError(
                f"AI_GUARDIAN_TEST_IDE={requested!r} is not in the E2E matrix"
            )
        return (requested,)
    return EXTERNAL_IDES


def _walk_commands(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            yield command
        for child in value.values():
            yield from _walk_commands(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_commands(child)


def _write_guardian_config(config_dir: Path, blocked_dir: Path) -> None:
    """Write a scanner-only config with deterministic synthetic fixtures."""
    custom_pattern = {
        "id": "synthetic-hook-output-marker",
        "match_type": "regex",
        "regex": POST_OUTPUT_PATTERN,
        "pattern": POST_OUTPUT_PATTERN,
        "description": "synthetic hook-output marker",
        "redaction_strategy": "full_redact",
        "strategy": "full_redact",
        "type": "synthetic hook-output marker",
    }
    config = {
        "secret_scanning": {
            "enabled": True,
            "engines": [{"type": "toml-patterns"}],
            "execution_strategy": "first-match",
            "min_entropy": 0.0,
            "stopwords": [],
            "additional_patterns": [custom_pattern],
        },
        "secret_redaction": {
            "enabled": True,
            "action": "warn",
            "preserve_format": False,
            "log_redactions": False,
            "additional_patterns": [custom_pattern],
        },
        "directory_rules": {
            "action": "block",
            "rules": [{"mode": "deny", "paths": [str(blocked_dir)]}],
        },
        "permissions": {"enabled": False, "rules": []},
        "prompt_injection": {"enabled": False},
        "context_poisoning": {"enabled": False},
        "scan_pii": {"enabled": False},
        "scan_offensive": {"enabled": False},
        "canary_detection": {"enabled": False},
        "exfil_detection": {"enabled": False},
        "config_file_scanning": {"enabled": False},
        "supply_chain": {"enabled": False},
        "code_scanning": {"enabled": False},
        "image_scanning": {"enabled": False},
        "transcript_scanning": {"enabled": False},
        "annotations": {"enabled": False},
    }
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "ai-guardian.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


@pytest.fixture
def isolated_ide_environment(tmp_path, monkeypatch):
    """Provide a disposable HOME, project, and AI Guardian configuration."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    xdg_home = tmp_path / "xdg"
    blocked_dir = project / "blocked-fixture"
    blocked_file = blocked_dir / "synthetic.txt"
    config_dir = Path(os.environ["AI_GUARDIAN_CONFIG_DIR"])

    home.mkdir()
    project.mkdir()
    blocked_dir.mkdir(parents=True)
    blocked_file.write_text("safe synthetic fixture\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(home / "codex"))
    monkeypatch.delenv("AI_GUARDIAN_IDE_TYPE", raising=False)
    monkeypatch.delenv("AI_GUARDIAN_DAEMON_URL", raising=False)
    monkeypatch.chdir(project)

    _write_guardian_config(config_dir, blocked_dir)

    return {
        "home": home,
        "project": project,
        "blocked_file": blocked_file,
        "config_dir": config_dir,
    }


def _install_and_verify(ide_type: str) -> Tuple[IDESetup, Dict[str, Any]]:
    setup = IDESetup()
    # Setup and MCP helpers print human-facing status text. Keep the matrix
    # output focused on assertion failures, which include IDE/event names.
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        success, message = setup.setup_ide_hooks(ide_type, force=True)
        assert success, f"{ide_type}/setup: {message}"
        _install_mcp_config(setup, ide_type)

    verification = setup.verify_hooks_for_ide(ide_type)
    assert verification["healthy"], (
        f"{ide_type}/verification: " f"{json.dumps(verification, sort_keys=True)}"
    )
    configured, detail = setup.check_hooks_for_ide(ide_type, integrity=True)
    assert configured, f"{ide_type}/integrity: {detail}"
    return setup, verification


def _read_json_config(path: Path) -> Dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonc":
        raw = _strip_jsonc_comments(raw)
    return json.loads(raw) if raw.strip() else {}


def _mcp_config_path(ide_type: str) -> Optional[Path]:
    return get_mcp_config_path(ide_type)


def _assert_mcp_registration(ide_type: str) -> None:
    """Verify MCP registration, including the intentional Copilot limitation."""
    spec = _MCP_IDE_CONFIGS[ide_type]
    path = _mcp_config_path(ide_type)
    if path is None:
        # Copilot has no local MCP config target in the current setup
        # contract; its hook integration is still verified below.
        assert ide_type == "copilot"
        return

    assert path.is_file(), f"{ide_type}/mcp-config: {path} was not created"
    if path.suffix.lower() == ".toml":
        from ai_guardian.setup.mcp import _load_toml_text

        config = _load_toml_text(path.read_text(encoding="utf-8"))
    else:
        config = _read_json_config(path)
    entry = config.get(spec["config_key"], {}).get("ai-guardian")
    assert isinstance(entry, dict), f"{ide_type}/mcp-config: entry missing"
    if ide_type == "opencode":
        assert entry.get("command", [None, None])[1:] == ["mcp-server"]
    else:
        assert entry.get("args") == ["mcp-server"]
        assert entry.get("command"), f"{ide_type}/mcp-config: command missing"


def _json_event_value(config: Dict[str, Any], ide_type: str, event_name: str) -> Any:
    if ide_type == "copilot":
        return config.get(event_name)
    if ide_type == "gemini":
        return [
            entry
            for entry in config.get("hooks", [])
            if isinstance(entry, dict) and entry.get("event") == event_name
        ]
    if ide_type == "windsurf":
        return config.get("hooks", {}).get(event_name)
    return config.get("hooks", {}).get(event_name)


def _command_for_event(setup: IDESetup, ide_type: str, event_name: str) -> str:
    path = Path(setup.get_config_path(ide_type)).expanduser()
    config = _read_json_config(path)
    commands = [
        command
        for command in _walk_commands(_json_event_value(config, ide_type, event_name))
        if f"--ide {ide_type}" in command
    ]
    assert commands, f"{ide_type}/{event_name}: generated command missing"
    return commands[0]


def _script_for_event(setup: IDESetup, ide_type: str, case_name: str) -> Path:
    config = setup.IDE_CONFIGS[ide_type]
    script_names = {
        "allow": "PromptSubmit" if ide_type == "kiro" else "UserPromptSubmit",
        "block": "PreToolUse",
        "post": "PostToolUse",
    }
    script_name = script_names[case_name]
    hooks_dir = Path(setup.get_config_path(ide_type)).expanduser()
    candidates = [hooks_dir / script_name]
    if platform.system() == "Windows":
        candidates.extend(
            [
                hooks_dir / f"{script_name}.bat",
                hooks_dir / f"{script_name}.ps1",
            ]
        )
    existing = [candidate for candidate in candidates if candidate.is_file()]
    assert existing, f"{ide_type}/{script_name}: generated script missing"
    assert script_name in config["hook_scripts"]
    content = existing[0].read_text(encoding="utf-8")
    assert f"--ide {ide_type}" in content, f"{ide_type}/{script_name}: IDE flag missing"
    return existing[0]


def _payload(
    ide_type: str,
    case_name: str,
    event_name: str,
    environment: Dict[str, Path],
) -> Dict[str, Any]:
    project = environment["project"]
    blocked_file = environment["blocked_file"]
    payload: Dict[str, Any] = {
        "cwd": str(project),
        "session_id": "isolated-ide-e2e",
    }

    if ide_type == "cursor":
        payload["cursor_version"] = "synthetic"
    elif ide_type in ("cline", "zoocode"):
        payload["clineVersion"] = "synthetic"
    elif ide_type == "kiro":
        payload["kiro_version"] = "synthetic"
    elif ide_type == "gemini":
        transcript = project / "gemini-transcript.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")
        payload["transcript_path"] = str(transcript)
    elif ide_type == "codex":
        payload.update({"codex_version": "synthetic", "model": "synthetic-model"})
    elif ide_type == "augment":
        payload["is_mcp_tool"] = False

    if ide_type == "crush":
        payload["event"] = event_name
    elif ide_type == "windsurf":
        payload["agent_action_name"] = event_name
    else:
        payload["hook_event_name"] = event_name

    if case_name == "allow":
        if ide_type == "crush":
            payload.update(
                {
                    "tool_name": "Read",
                    "tool_input": {"file_path": str(project / "README.md")},
                }
            )
        else:
            payload["prompt"] = "List the files in this synthetic project."
        return payload

    if case_name == "block":
        if ide_type == "cursor":
            payload.update(
                {
                    "file_path": str(blocked_file),
                    "content": "safe synthetic fixture",
                }
            )
        elif ide_type == "copilot":
            payload.update(
                {
                    "toolName": "Read",
                    "toolArgs": json.dumps({"file_path": str(blocked_file)}),
                }
            )
        elif ide_type == "windsurf":
            payload.update(
                {
                    "tool_name": "Read",
                    "tool_input": {"file_path": str(blocked_file)},
                    "tool_info": {
                        "name": "Read",
                        "file_path": str(blocked_file),
                    },
                }
            )
        else:
            tool_name = "view" if ide_type == "augment" else "Read"
            payload.update(
                {
                    "tool_name": tool_name,
                    "tool_input": {"file_path": str(blocked_file)},
                }
            )
        return payload

    if case_name == "post":
        tool_name = "launch-process" if ide_type == "augment" else "Bash"
        payload.update(
            {
                "tool_name": tool_name,
                "tool_response": {"output": POST_OUTPUT_MARKER},
            }
        )
        if ide_type == "windsurf":
            payload["tool_info"] = {"name": "Bash"}
        return payload

    raise AssertionError(f"Unknown E2E case: {case_name}")


def _run_command(
    command: Union[str, List[str]],
    payload: Dict[str, Any],
    environment: Dict[str, Path],
) -> subprocess.CompletedProcess:
    if isinstance(command, str):
        command_args = shlex.split(command, posix=platform.system() != "Windows")
    else:
        command_args = command
    return subprocess.run(
        command_args,
        cwd=environment["project"],
        env=os.environ.copy(),
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
    )


def _json_output(result: subprocess.CompletedProcess) -> Any:
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _response_is_blocked(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("permission") == "deny":
            return True
        if value.get("permissionDecision") == "deny":
            return True
        if value.get("decision") in ("block", "deny"):
            return True
        if value.get("cancel") is True:
            return True
        if value.get("continue") is False:
            return True
        return any(_response_is_blocked(child) for child in value.values())
    if isinstance(value, list):
        return any(_response_is_blocked(child) for child in value)
    return False


def _contains_transform(value: Any) -> bool:
    if isinstance(value, dict):
        if any(
            key in value
            for key in (
                "updatedToolOutput",
                "updatedMCPToolOutput",
                "modifiedToolOutput",
                "modifiedResult",
            )
        ):
            return True
        return any(_contains_transform(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_transform(child) for child in value)
    return False


def _assert_runtime_case(
    ide_type: str,
    case_name: str,
    event_name: str,
    command: Union[str, List[str]],
    environment: Dict[str, Path],
) -> None:
    result = _run_command(
        command,
        _payload(ide_type, case_name, event_name, environment),
        environment,
    )
    response = _json_output(result)
    label = f"{ide_type}/{event_name}/{case_name}"

    if case_name == "allow":
        assert result.returncode == 0, f"{label}: allow returned {result.returncode}"
        assert not _response_is_blocked(response), f"{label}: allow response denied"
    elif case_name == "block":
        assert result.returncode != 0 or _response_is_blocked(
            response
        ), f"{label}: block path was allowed"
    elif case_name == "post":
        combined_output = f"{result.stdout}\n{result.stderr}"
        assert result.returncode == 0, f"{label}: post returned {result.returncode}"
        assert (
            POST_OUTPUT_MARKER not in combined_output
        ), f"{label}: output was not redacted"
        assert _contains_transform(response) or any(
            marker in combined_output.upper() for marker in ("HIDDEN", "REDACTED")
        ), f"{label}: redaction response was not returned"


def _assert_plugin_or_extension_bridge(setup: IDESetup, ide_type: str) -> None:
    config = setup.IDE_CONFIGS[ide_type]
    root = Path(setup.get_config_path(ide_type)).expanduser()
    source_path = root / ("ai-guardian.ts" if config.get("plugin_file") else "index.ts")
    package_path = root / "package.json"
    assert source_path.is_file(), f"{ide_type}/setup: bridge source missing"
    if config.get("extension_based"):
        assert package_path.is_file(), f"{ide_type}/setup: package manifest missing"
    source = source_path.read_text(encoding="utf-8")
    assert f"--ide {ide_type}" in source, f"{ide_type}/setup: IDE flag missing"
    assert "execSync" in source and "AI_GUARDIAN_IDE_TYPE" in source

    if ide_type == "opencode":
        required_events = (
            "tool.execute.before",
            "chat.message",
            "tool.execute.after",
        )
        registration = _read_json_config(_resolve_opencode_config())
        assert str(source_path) in registration.get("plugins", [])
    else:
        required_events = ("prompt_submit", "pre_tool_use", "post_tool_use")
    for event_name in required_events:
        assert event_name in source, f"{ide_type}/{event_name}: bridge missing"


@pytest.mark.parametrize("ide_type", _selected_ides(), ids=_selected_ides())
def test_install_verify_and_exercise_ide_integration(
    ide_type, isolated_ide_environment
):
    """Install, verify, and exercise the generated integration for one IDE."""
    setup, verification = _install_and_verify(ide_type)
    _assert_mcp_registration(ide_type)

    if setup.IDE_CONFIGS[ide_type].get("mcp_only"):
        assert verification["events"] == {}
        return

    if setup.IDE_CONFIGS[ide_type].get("plugin_file") or setup.IDE_CONFIGS[
        ide_type
    ].get("extension_based"):
        _assert_plugin_or_extension_bridge(setup, ide_type)
        return

    # Windows setup is structurally verified above. The CI runtime matrix is
    # Linux because .bat execution depends on the host command interpreter.
    if platform.system() == "Windows":
        return

    for case_name, event_name in REPRESENTATIVE_EVENTS[ide_type].items():
        if setup.IDE_CONFIGS[ide_type].get("script_based"):
            command: Union[str, List[str]] = [
                str(_script_for_event(setup, ide_type, case_name))
            ]
        else:
            command = _command_for_event(setup, ide_type, event_name)
        _assert_runtime_case(
            ide_type,
            case_name,
            event_name,
            command,
            isolated_ide_environment,
        )
