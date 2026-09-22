"""
Dummy Agent — interactive fake IDE for hook testing without LLM.

Fires UserPromptSubmit, PreToolUse, and PostToolUse hook events against
ai-guardian, simulating a full AI coding session without any API key.

Usage:
    Interactive chatbot:  ai-guardian dummy-agent
    Automated scenarios:  ai-guardian dummy-agent --script scenarios/basic-secret.yaml
"""

import importlib
import json
import os
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ai_guardian.constants import HookEvent
from ai_guardian.hook_processing import process_hook_data

_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

# keyword → (tool_name, input_key, fake_output_template)
_TOOL_KEYWORD_MAP: Dict[str, Tuple[str, str, str]] = {
    "read": ("Read", "file_path", "# file contents\nline 1\nline 2\nline 3"),
    "write": ("Write", "file_path", "File written successfully."),
    "edit": ("Edit", "file_path", "File edited successfully."),
    "bash": ("Bash", "command", "$ command\noutput line 1\noutput line 2"),
    "run": ("Bash", "command", "$ command\nexecution complete"),
    "curl": ("Bash", "command", 'HTTP/1.1 200 OK\n{"status": "ok"}'),
    "ls": ("Bash", "command", "file1.py  file2.py  README.md"),
    "cat": ("Bash", "command", "file contents here"),
    "grep": ("Bash", "command", "match found at line 42"),
    "find": ("Bash", "command", "./src/main.py\n./src/util.py"),
    "git": ("Bash", "command", "On branch main\nnothing to commit"),
}


def _color(text: str, code: str, enabled: bool = True) -> str:
    if not enabled or not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


def _make_session_id() -> str:
    return str(uuid.uuid4())


def _make_hook_payload(
    event: str,
    session_id: str,
    cwd: str,
    *,
    prompt: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_input: Optional[Dict] = None,
    tool_response: Optional[Any] = None,
    tool_use_id: Optional[str] = None,
) -> Dict:
    payload: Dict[str, Any] = {
        "hook_event_name": event,
        "session_id": session_id,
        "cwd": cwd,
        "dummy_agent": True,
        "_ide_type": "dummy-agent",
    }
    if prompt is not None:
        # hook_processing reads hook_data["prompt"] for content_to_scan.
        # transcript mirrors Claude Code format for transcript-based scanners.
        payload["prompt"] = prompt
        payload["transcript"] = [
            {"role": "human", "content": [{"type": "text", "text": prompt}]}
        ]
    if tool_name is not None:
        payload["tool_name"] = tool_name
    if tool_input is not None:
        payload["tool_input"] = tool_input
    if tool_response is not None:
        payload["tool_response"] = tool_response
    if tool_use_id is not None:
        payload["tool_use_id"] = tool_use_id
    return payload


def _run_hook(payload: Dict, daemon_state=None) -> Dict:
    return process_hook_data(payload, daemon_state=daemon_state)


def _is_blocked(result: Dict) -> bool:
    return bool(result.get("_blocked", False))


def _block_reason(result: Dict) -> str:
    output_str = result.get("output") or "{}"
    try:
        output = json.loads(output_str) if isinstance(output_str, str) else output_str
    except (json.JSONDecodeError, TypeError):
        output = {}
    return (
        output.get("reason")
        or output.get("systemMessage")
        or output.get("hookSpecificOutput", {}).get("additionalContext", "blocked")
    )


def _warn_message(result: Dict) -> Optional[str]:
    output_str = result.get("output") or "{}"
    try:
        output = json.loads(output_str) if isinstance(output_str, str) else output_str
    except (json.JSONDecodeError, TypeError):
        output = {}
    return output.get("systemMessage") or output.get("hookSpecificOutput", {}).get(
        "additionalContext"
    )


def _guess_tools(prompt: str) -> List[Dict]:
    """Infer tool specs from prompt keywords."""
    lower = prompt.lower()
    tools = []
    seen = set()
    for kw, (tool_name, input_key, fake_out) in _TOOL_KEYWORD_MAP.items():
        if kw in lower and tool_name not in seen:
            parts = prompt.split()
            value = parts[-1] if len(parts) > 1 else kw
            tools.append(
                {
                    "name": tool_name,
                    "input": {input_key: value},
                    "fake_output": fake_out,
                }
            )
            seen.add(tool_name)
    return tools


def _fake_intro(prompt: str, tools: List[Dict]) -> str:
    if not tools:
        return "I can help with that."
    names = [t["name"] for t in tools]
    return f"I'll use {', '.join(names)} to help with that."


def _fake_outro(prompt: str, tools: List[Dict]) -> str:
    if not tools:
        return "Let me know if you need anything else."
    return "Done. Let me know if you need further changes."


# ---------------------------------------------------------------------------
# Shell command execution (!cmd)
# ---------------------------------------------------------------------------


def _run_shell_command(cmd: str, session_id: str, cwd: str, c) -> None:
    """Run a real shell command, firing PreToolUse + PostToolUse hooks around it."""
    import subprocess

    tool_use_id = str(uuid.uuid4())

    print(c(f"[hook] PreToolUse(Bash, {json.dumps({'command': cmd})})", _DIM))
    result = _run_hook(
        _make_hook_payload(
            HookEvent.PRE_TOOL_USE.display_name,
            session_id,
            cwd,
            tool_name="Bash",
            tool_input={"command": cmd},
            tool_use_id=tool_use_id,
        )
    )
    if _is_blocked(result):
        print(c(f"🚨 BLOCKED: {_block_reason(result)}", _RED))
        return
    warn = _warn_message(result)
    if warn:
        print(c(f"⚠️  {warn}", _YELLOW))

    # Execute the real command
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    if output:
        print(c("╔─ Bash ─────────────────────────────────────", _DIM))
        for line in output.splitlines():
            print(c("│ ", _DIM) + line)
        print(c("╚────────────────────────────────────────────", _DIM))

    print(c("[hook] PostToolUse(Bash)", _DIM))
    result = _run_hook(
        _make_hook_payload(
            HookEvent.POST_TOOL_USE.display_name,
            session_id,
            cwd,
            tool_name="Bash",
            tool_input={"command": cmd},
            tool_response=output,
            tool_use_id=tool_use_id,
        )
    )
    if _is_blocked(result):
        print(c(f"🚨 BLOCKED (output): {_block_reason(result)}", _RED))
        return
    warn = _warn_message(result)
    if warn:
        print(c(f"⚠️  {warn}", _YELLOW))
    else:
        print(c("✅ Done", _GREEN))


# ---------------------------------------------------------------------------
# SessionStart event (bootstrap scan testing)
# ---------------------------------------------------------------------------


def _run_session_start_event(
    *,
    session_files: List[Dict],
    colors: bool,
    daemon_state=None,
) -> bool:
    """Write session_files to a temp dir, fire SessionStart hook, return blocked bool."""
    import tempfile
    from pathlib import Path as _Path

    from ai_guardian.config.utils import (
        clear_project_dir_override,
        set_project_dir_override,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_resolved = _Path(tmpdir).resolve()
        for sf in session_files:
            dest = (tmpdir_resolved / sf["path"]).resolve()
            if not dest.is_relative_to(tmpdir_resolved):
                raise ValueError(f"session_files path escapes temp dir: {sf['path']}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(sf["content"], encoding="utf-8")

        fresh_session_id = _make_session_id()
        set_project_dir_override(tmpdir)
        try:
            payload = _make_hook_payload(
                HookEvent.SESSION_START.display_name, fresh_session_id, tmpdir
            )
            result = _run_hook(payload, daemon_state=daemon_state)
        finally:
            clear_project_dir_override()

    print(
        f"→ {_color('SessionStart', _CYAN, colors)} fired"
        f" (session_files={[sf['path'] for sf in session_files]})"
    )
    blocked = _is_blocked(result)
    if blocked:
        print(f"  {_color('🚨 BLOCKED', _RED, colors)}: {_block_reason(result)}")
    else:
        warn = _warn_message(result)
        if warn:
            print(f"  {_color('⚠️  WARNING', _YELLOW, colors)}: {warn}")
        else:
            print(f"  {_color('✅ Allowed', _GREEN, colors)}")
    return blocked


# ---------------------------------------------------------------------------
# Interactive chatbot REPL
# ---------------------------------------------------------------------------


def run_interactive(session_id: Optional[str] = None, colors: bool = True) -> None:
    if session_id is None:
        session_id = _make_session_id()
    cwd = os.getcwd()

    c = lambda text, code: _color(text, code, colors)  # noqa: E731

    print(c("╔══════════════════════════════════════╗", _CYAN))
    print(c("║   ai-guardian dummy-agent  🤖         ║", _CYAN))
    print(c("║   Simulated IDE — no LLM required    ║", _CYAN))
    print(c("╚══════════════════════════════════════╝", _CYAN))
    print(c(f"Session: {session_id[:8]}  |  cwd: {cwd}", _DIM))
    print(c("Type a prompt. !<cmd> runs a shell command. exit/quit to stop.\n", _DIM))

    while True:
        try:
            prompt = input(c("You: ", _BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit", "q"):
            break

        print()

        # Shell command mode: "! cmd" fires PreToolUse(Bash) + runs + PostToolUse(Bash)
        if prompt.startswith("!"):
            cmd = prompt[1:].strip()
            _run_shell_command(cmd, session_id, cwd, c)
            print()
            continue

        # 1. UserPromptSubmit
        print(c("[hook] UserPromptSubmit", _DIM))
        result = _run_hook(
            _make_hook_payload(
                HookEvent.PROMPT.display_name, session_id, cwd, prompt=prompt
            )
        )
        if _is_blocked(result):
            reason = _block_reason(result)
            print(c(f"🚨 BLOCKED: {str(reason)}", _RED))
            print()
            continue
        warn = _warn_message(result)
        if warn:
            print(c(f"⚠️  {warn}", _YELLOW))

        # 2. Generate assistant response
        tools = _guess_tools(prompt)
        print()
        print(c("Assistant: ", _GREEN) + _fake_intro(prompt, tools))

        blocked = False
        for tool_spec in tools:
            tool_name = tool_spec["name"]
            tool_input = tool_spec["input"]
            fake_output = tool_spec["fake_output"]
            tool_use_id = str(uuid.uuid4())

            # PreToolUse
            print()
            input_repr = json.dumps(tool_input)
            print(
                c(
                    f"[hook] {HookEvent.PRE_TOOL_USE.display_name}({tool_name}, {input_repr})",
                    _DIM,
                )
            )
            result = _run_hook(
                _make_hook_payload(
                    HookEvent.PRE_TOOL_USE.display_name,
                    session_id,
                    cwd,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_use_id=tool_use_id,
                )
            )
            if _is_blocked(result):
                reason = _block_reason(result)
                print(c(f"🚨 BLOCKED ({tool_name}): {str(reason)}", _RED))
                blocked = True
                break
            warn = _warn_message(result)
            if warn:
                print(c(f"⚠️  {warn}", _YELLOW))

            # Display fake tool output
            print()
            print(c(f"╔─ {tool_name} ─────────────────────────────────", _DIM))
            for line in str(fake_output).splitlines():
                print(c("│ ", _DIM) + line)
            print(c("╚──────────────────────────────────────────────", _DIM))

            # PostToolUse
            print(
                c(f"[hook] {HookEvent.POST_TOOL_USE.display_name}({tool_name})", _DIM)
            )
            result = _run_hook(
                _make_hook_payload(
                    HookEvent.POST_TOOL_USE.display_name,
                    session_id,
                    cwd,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_response=fake_output,
                    tool_use_id=tool_use_id,
                )
            )
            if _is_blocked(result):
                reason = _block_reason(result)
                print(
                    c(
                        f"🚨 BLOCKED (PostToolUse/{tool_name}): {str(reason)}",
                        _RED,
                    )
                )
                blocked = True
                break
            warn = _warn_message(result)
            if warn:
                print(c(f"⚠️  {warn}", _YELLOW))

        if not blocked:
            print()
            print(c("Assistant: ", _GREEN) + _fake_outro(prompt, tools))

        print()


# ---------------------------------------------------------------------------
# Script mode (automated scenarios)
# ---------------------------------------------------------------------------


def _run_scenario_event(
    *,
    prompt: str,
    tools: Optional[List[Dict]],
    session_id: str,
    cwd: str,
    colors: bool,
    fake_output: str = "<simulated output>",
    daemon_state=None,
    workspace_files: Optional[List[Dict]] = None,
) -> bool:
    """Fire UserPromptSubmit + PreToolUse/PostToolUse per tool. Returns True if blocked.

    When *workspace_files* is provided, a temp directory is created with those
    files and ``project_dir_override`` is set so that language detection sees
    the simulated project structure (e.g. ``pyproject.toml`` → Python overlay).
    """
    _workspace_ctx = None
    if workspace_files:
        import tempfile
        from pathlib import Path as _Path

        from ai_guardian.config.utils import (
            clear_project_dir_override,
            set_project_dir_override,
        )
        from ai_guardian.project_init import _language_fp_cache

        _workspace_ctx = tempfile.TemporaryDirectory()
        cwd = _workspace_ctx.name
        tmpdir_resolved = _Path(cwd).resolve()
        for wf in workspace_files:
            dest = (tmpdir_resolved / wf["path"]).resolve()
            if not dest.is_relative_to(tmpdir_resolved):
                _workspace_ctx.cleanup()
                raise ValueError(f"workspace_files path escapes temp dir: {wf['path']}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(wf.get("content", ""), encoding="utf-8")
        set_project_dir_override(cwd)

    try:
        print(
            f"→ {_color('UserPromptSubmit', _CYAN, colors)} fired"
            f" (transcript: {repr(prompt[:60])})"
        )
        result = _run_hook(
            _make_hook_payload(
                HookEvent.PROMPT.display_name, session_id, cwd, prompt=prompt
            ),
            daemon_state=daemon_state,
        )
        blocked = _is_blocked(result)
        if blocked:
            print(f"  {_color('🚨 BLOCKED', _RED, colors)}: {_block_reason(result)}")
            return True
        warn = _warn_message(result)
        if warn:
            print(f"  {_color('⚠️  WARNING', _YELLOW, colors)}: {warn}")
        else:
            print(f"  {_color('✅ Allowed', _GREEN, colors)}")

        if tools is None:
            tools = [
                {
                    "name": t["name"],
                    "input": t["input"],
                    "fake_output": t["fake_output"],
                }
                for t in _guess_tools(prompt)
            ]

        for tool_spec in tools:
            tool_name = tool_spec.get("name", "Bash")
            tool_input = tool_spec.get("input", {})
            tool_use_id = str(uuid.uuid4())
            tool_fake_out = tool_spec.get("fake_output", fake_output)

            print(
                f"→ {_color('PreToolUse', _CYAN, colors)} fired"
                f" ({tool_name}, input={json.dumps(tool_input)[:80]})"
            )
            result = _run_hook(
                _make_hook_payload(
                    HookEvent.PRE_TOOL_USE.display_name,
                    session_id,
                    cwd,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_use_id=tool_use_id,
                ),
                daemon_state=daemon_state,
            )
            blocked = _is_blocked(result)
            if blocked:
                print(
                    f"  {_color('🚨 BLOCKED', _RED, colors)}:"
                    f" {_block_reason(result)}"
                )
                return True
            warn = _warn_message(result)
            if warn:
                print(f"  {_color('⚠️  WARNING', _YELLOW, colors)}: {warn}")
            else:
                print(f"  {_color('✅ Allowed', _GREEN, colors)}")

            print(
                f"→ {_color('PostToolUse', _CYAN, colors)} fired"
                f" ({tool_name}, response={repr(str(tool_fake_out)[:60])})"
            )
            result = _run_hook(
                _make_hook_payload(
                    HookEvent.POST_TOOL_USE.display_name,
                    session_id,
                    cwd,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_response=tool_fake_out,
                    tool_use_id=tool_use_id,
                ),
                daemon_state=daemon_state,
            )
            blocked = _is_blocked(result)
            if blocked:
                print(
                    f"  {_color('🚨 BLOCKED', _RED, colors)}:"
                    f" {_block_reason(result)}"
                )
                return True
            warn = _warn_message(result)
            if warn:
                print(f"  {_color('⚠️  WARNING', _YELLOW, colors)}: {warn}")
            else:
                print(f"  {_color('✅ Allowed', _GREEN, colors)}")

        return False
    finally:
        if _workspace_ctx is not None:
            from ai_guardian.config.utils import clear_project_dir_override
            from ai_guardian.project_init import _language_fp_cache

            _language_fp_cache.pop(cwd, None)
            clear_project_dir_override()
            _workspace_ctx.cleanup()


def run_script(script_path: str, colors: bool = True) -> int:
    """Run scenarios from a YAML file. Returns exit code (0=all pass, 1=failure)."""
    try:
        yaml: Any = importlib.import_module("yaml")
    except ImportError:
        print(
            "PyYAML required for script mode. Install with: pip install pyyaml",
            file=sys.stderr,
        )
        return 1

    try:
        with open(script_path) as f:
            scenario = yaml.safe_load(f)
    except (OSError, Exception) as e:
        print(f"Failed to load scenario: {e}", file=sys.stderr)
        return 1

    events = scenario.get("events", [])
    session_id = _make_session_id()
    cwd = os.getcwd()
    passed = 0
    failed = 0

    daemon_state = None
    try:
        from ai_guardian.daemon.state import DaemonState

        daemon_state = DaemonState()
    except Exception:
        pass

    print(
        f"{_color('[dummy-agent]', _CYAN, colors)} Running script: {script_path}"
        f" ({len(events)} event(s))\n"
    )

    for idx, event in enumerate(events):
        event_type = event.get("event", HookEvent.PROMPT.display_name)
        prompt = event.get("prompt", "")
        tools = event.get("tools")
        expect = event.get("expect", "allow").lower()
        label = event.get("label") or f"event[{idx}]"

        print(f"{_color(f'--- {label} ---', _BOLD, colors)}")

        if event_type == HookEvent.SESSION_START.display_name:
            blocked = _run_session_start_event(
                session_files=event.get("session_files", []),
                colors=colors,
                daemon_state=daemon_state,
            )
        else:
            blocked = _run_scenario_event(
                prompt=prompt,
                tools=tools,
                session_id=session_id,
                cwd=cwd,
                colors=colors,
                daemon_state=daemon_state,
                workspace_files=event.get("workspace_files"),
            )

        expected_block = expect == "block"
        ok = blocked == expected_block

        if ok:
            passed += 1
            print(f"  {_color('PASS', _GREEN, colors)} (expected={expect})\n")
        else:
            failed += 1
            actual = "block" if blocked else "allow"
            print(
                f"  {_color('FAIL', _RED, colors)}"
                f" (expected={expect}, got={actual})\n"
            )

    total = passed + failed
    status = (
        _color("PASSED", _GREEN, colors)
        if failed == 0
        else _color("FAILED", _RED, colors)
    )
    print(f"\n{status} {passed}/{total} scenarios")
    return 0 if failed == 0 else 1
