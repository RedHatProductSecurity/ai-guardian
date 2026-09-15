"""Interactive ask dialog for the 'ask' action mode.

When a violation is detected and the action is 'ask', this module shows
an interactive dialog letting the user choose: Allow Once, Allow Always
(with pattern editor), or Block.

Cascade: tkinter (native popup) -> NiceGUI (browser) -> Textual (terminal) -> headless fallback.

Shared types and dispatch live here. Tier-specific implementations:
  - tui/ask_dialog_tk.py       — tkinter (native popup)
  - web/ask_dialog_nicegui.py  — NiceGUI (browser)
  - tui/ask_dialog_textual.py  — Textual (terminal)
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from ai_guardian.constants import HookEvent

logger = logging.getLogger(__name__)


class AskDecision(str, Enum):
    """User's decision from the ask dialog."""

    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    SUPPRESS_IN_SOURCE = "suppress_in_source"
    IGNORE_FILE = "ignore_file"
    BLOCK = "block"
    BLOCK_ALL = "block_all"


@dataclass
class AskViolationInfo:
    """Violation details presented in the ask dialog."""

    violation_type: str
    summary: str
    matched_text: str
    config_section: str
    error_message: str = ""
    matched_pattern: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    start_column: Optional[int] = None
    project_path: Optional[str] = None
    session_id: Optional[str] = None
    tool_name: Optional[str] = None
    hook_event: Optional[str] = None
    finding_index: Optional[int] = None
    total_findings: Optional[int] = None


@dataclass
class AskResult:
    """Result from the ask dialog."""

    decision: AskDecision
    allowlist_pattern: Optional[str] = None
    config_saved: bool = False
    dialog_wait_ms: float = 0.0
    source_annotation_saved: bool = False
    ignore_path: Optional[str] = None
    ignore_scanner_types: Optional[List[str]] = None
    config_path: Optional[str] = None
    per_finding_results: Optional[List] = None


def build_dialog_title(violation_info: AskViolationInfo) -> str:
    """Build dialog title with project/tool/file context for multi-session identification."""
    from pathlib import Path

    parts = ["ai-guardian: Violation Detected"]
    if violation_info.project_path:
        parts.append(f"— {Path(violation_info.project_path).name}")
    tool_file_parts = []
    if violation_info.tool_name:
        tool_file_parts.append(violation_info.tool_name)
    if violation_info.file_path:
        tool_file_parts.append(Path(violation_info.file_path).name)
    if tool_file_parts:
        parts.append(f"— {' '.join(tool_file_parts)}")
    if violation_info.session_id:
        parts.append(f"[{violation_info.session_id[:4]}]")
    return " ".join(parts)


def build_sub_dialog_title(base_title: str, violation_info: AskViolationInfo) -> str:
    """Build sub-dialog title with project/tool/session context prefix."""
    from pathlib import Path

    prefix_parts = []
    if violation_info.project_path:
        prefix_parts.append(Path(violation_info.project_path).name)
    tool_file_parts = []
    if violation_info.tool_name:
        tool_file_parts.append(violation_info.tool_name)
    if violation_info.file_path:
        tool_file_parts.append(Path(violation_info.file_path).name)
    if tool_file_parts:
        prefix_parts.append(" ".join(tool_file_parts))
    if violation_info.session_id:
        prefix_parts.append(f"[{violation_info.session_id[:4]}]")
    if prefix_parts:
        return f"{' '.join(prefix_parts)} — {base_title}"
    return base_title


_TOOL_TO_LABEL = {
    "Read": "reading file",
    "Bash": "running command",
    "Write": "writing file",
    "Edit": "editing file",
}


def format_hook_label(
    hook_event: Optional[str], tool_name: Optional[str] = None
) -> Optional[str]:
    """Map hook event + optional tool name to a human-readable label."""
    if not hook_event:
        return None
    raw = hook_event.value if hasattr(hook_event, "value") else str(hook_event)
    ev = raw.lower().replace("_", "").replace("-", "")
    if ev in ("pretooluse", "beforereadfile"):
        ctx = _TOOL_TO_LABEL.get(tool_name or "", "before tool use")
        return f"{HookEvent.PRE_TOOL_USE.display_name} ({ctx})"
    if ev == "posttooluse":
        return f"{HookEvent.POST_TOOL_USE.display_name} (tool output)"
    if ev in ("prompt", "userpromptsubmit"):
        return f"{HookEvent.PROMPT.display_name} (your prompt)"
    return raw


def _map_fallback_to_decision(fallback_action: str) -> AskDecision:
    """Map a fallback action string to an AskDecision."""
    if fallback_action in ("warn", "log-only"):
        return AskDecision.ALLOW_ONCE
    return AskDecision.BLOCK


def _save_pattern_to_config(
    pattern: str,
    config_section: str,
    config_path: Optional[str] = None,
) -> bool:
    """Save a pattern to the config file. Returns True on success."""
    try:
        from pathlib import Path
        from ai_guardian.config.writer import save_ask_pattern

        cp = Path(config_path) if config_path else None
        return save_ask_pattern(config_section, pattern, config_path=cp)
    except Exception as e:
        logger.warning("Failed to save pattern to config: %s", e)
        return False


def _write_config_text(json_text: str, config_path_str: Optional[str] = None) -> bool:
    """Write JSON text directly to ai-guardian.json with backup. Returns True on success."""
    from pathlib import Path

    try:
        new_config = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON, not writing config: %s", e)
        return False
    try:
        if config_path_str:
            config_path = Path(config_path_str)
        else:
            from ai_guardian.config.utils import get_config_dir

            config_path = get_config_dir() / "ai-guardian.json"

        from ai_guardian.config.writer import _atomic_config_update

        def _replace_config(config):
            config.clear()
            config.update(new_config)
            return False, "Manual config update from pattern editor"

        return _atomic_config_update(config_path, _replace_config)
    except Exception as e:
        logger.warning("Failed to write config: %s", e)
        return False


def _save_ignore_path(path: str, scanner_types: Optional[List[str]] = None) -> bool:
    """Save a path to .aiguardignore.toml. Returns True on success."""
    try:
        from ai_guardian.aiguardignore import add_ignore_path

        return add_ignore_path(path, scanner_types=scanner_types)
    except Exception as e:
        logger.warning("Failed to save ignore path: %s", e)
        return False


def _write_aiguardignore_text(
    toml_text: str,
    project_root=None,
) -> bool:
    """Write TOML text directly to .aiguardignore.toml. Returns True on success."""
    try:
        from ai_guardian.aiguardignore import write_aiguardignore_text

        return write_aiguardignore_text(toml_text, project_root=project_root)
    except Exception as e:
        logger.warning("Failed to write .aiguardignore.toml: %s", e)
        return False


def _serialize_violation(violation: AskViolationInfo) -> dict:
    """Serialize AskViolationInfo to a JSON-safe dict."""
    return {
        "violation_type": violation.violation_type,
        "summary": violation.summary,
        "matched_text": violation.matched_text,
        "config_section": violation.config_section,
        "error_message": violation.error_message,
        "matched_pattern": violation.matched_pattern,
        "file_path": violation.file_path,
        "line_number": violation.line_number,
        "start_column": violation.start_column,
        "project_path": violation.project_path,
        "session_id": violation.session_id,
        "tool_name": violation.tool_name,
        "hook_event": violation.hook_event,
        "finding_index": violation.finding_index,
        "total_findings": violation.total_findings,
    }


def _show_via_tray_forwarding(
    violation: AskViolationInfo,
    fallback_action: str = "block",
    timeout_seconds: int = 300,
) -> Optional[AskResult]:
    """Queue prompt for host tray pickup on headless remote daemon (#1342).

    Returns None if no tray registered or decision timed out (caller falls
    through to existing headless fallback with zero delay).
    """
    try:
        from ai_guardian.daemon import get_daemon_state

        daemon_state = get_daemon_state()
    except Exception:
        return None

    if daemon_state is None or not daemon_state.is_tray_registered():
        return None

    violation_dict = _serialize_violation(violation)
    pending = daemon_state.queue_prompt(
        violation_dict, fallback_action, timeout_seconds
    )

    resolved = pending.decision_event.wait(timeout=timeout_seconds)

    if not resolved or pending.result is None:
        logger.info(
            "Tray prompt %s timed out, falling back to %s",
            pending.prompt_id,
            fallback_action,
        )
        return None

    data = pending.result
    decision_str = data.get("decision", "block")
    try:
        decision = AskDecision(decision_str)
    except ValueError:
        decision = AskDecision.BLOCK

    return AskResult(
        decision=decision,
        allowlist_pattern=data.get("allowlist_pattern"),
        config_saved=data.get("config_saved", False),
        source_annotation_saved=data.get("source_annotation_saved", False),
        ignore_path=data.get("ignore_path"),
        ignore_scanner_types=data.get("ignore_scanner_types"),
        config_path=data.get("config_path"),
    )


def _show_via_daemon(
    violation: AskViolationInfo,
    fallback_action: str = "block",
    timeout_seconds: int = 300,
) -> Optional[AskResult]:
    """Send prompt request to daemon REST API (direct call, no subprocess).

    The daemon process has display access (via the tray), so the ask
    dialog runs in-process there — avoiding Python interpreter startup
    overhead from subprocess spawning.

    Returns None if the daemon is not running or the request fails.
    """
    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    try:
        from ai_guardian.daemon import get_pid_path, is_pid_alive
    except ImportError:
        return None

    pid_path = get_pid_path()
    if not pid_path.exists():
        return None

    try:
        pid_info = json.loads(pid_path.read_text())
        rest_port = pid_info.get("rest_port")
        if not rest_port:
            return None
        pid = pid_info.get("pid", 0)
        if not pid or not is_pid_alive(pid):
            return None
    except (json.JSONDecodeError, OSError, ValueError):
        return None

    body = json.dumps(
        {
            "mode": "ask",
            "violation": {
                "violation_type": violation.violation_type,
                "summary": violation.summary,
                "matched_text": violation.matched_text,
                "config_section": violation.config_section,
                "error_message": violation.error_message,
                "matched_pattern": violation.matched_pattern,
                "file_path": violation.file_path,
                "line_number": violation.line_number,
                "start_column": violation.start_column,
                "project_path": violation.project_path,
                "session_id": violation.session_id,
                "tool_name": violation.tool_name,
                "hook_event": violation.hook_event,
                "finding_index": violation.finding_index,
                "total_findings": violation.total_findings,
            },
            "fallback": fallback_action,
            "timeout": timeout_seconds,
        }
    ).encode("utf-8")

    url = f"http://127.0.0.1:{rest_port}/api/prompt"
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    auth_token = pid_info.get("auth_token")
    if auth_token:
        req.add_header("Authorization", f"Bearer {auth_token}")

    try:
        with urlopen(req, timeout=timeout_seconds + 10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        decision_str = data.get("decision", "block")
        try:
            decision = AskDecision(decision_str)
        except ValueError:
            decision = AskDecision.BLOCK
        logger.debug("Ask dialog via daemon: %s", decision_str)
        return AskResult(
            decision=decision,
            allowlist_pattern=data.get("allowlist_pattern"),
            config_saved=data.get("config_saved", False),
            source_annotation_saved=data.get("source_annotation_saved", False),
            ignore_path=data.get("ignore_path"),
            ignore_scanner_types=data.get("ignore_scanner_types"),
            config_path=data.get("config_path"),
        )
    except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.debug("Daemon prompt request failed: %s", e)
        return None


def _show_via_subprocess(
    violation: AskViolationInfo,
    fallback_action: str = "block",
    timeout_seconds: int = 300,
    extra_env: Optional[dict] = None,
) -> Optional[AskResult]:
    """Launch prompt --mode ask as a separate subprocess with display access.

    extra_env: optional env overrides (e.g. AI_GUARDIAN_PREFERRED_UI=nicegui
    when called from the tray, where pystray's NSAccessory activation policy
    prevents tkinter subprocesses from appearing in front on macOS 14+).
    """
    import json
    import subprocess
    import tempfile

    violation_json = json.dumps(
        {
            "violation_type": violation.violation_type,
            "summary": violation.summary,
            "matched_text": violation.matched_text,
            "config_section": violation.config_section,
            "error_message": violation.error_message,
            "matched_pattern": violation.matched_pattern,
            "file_path": violation.file_path,
            "line_number": violation.line_number,
            "start_column": violation.start_column,
            "project_path": violation.project_path,
            "session_id": violation.session_id,
            "tool_name": violation.tool_name,
            "hook_event": violation.hook_event,
            "finding_index": violation.finding_index,
            "total_findings": violation.total_findings,
        }
    )

    tmpdir = tempfile.mkdtemp(prefix="ai-guardian-ask-")
    output_path = os.path.join(tmpdir, "result.json")

    from ai_guardian.daemon import get_executable_command

    cmd = get_executable_command() + ["prompt", "--mode", "ask"]
    logger.debug(f"prompt --mode ask cmd: {cmd[0]}")
    cmd += [
        "--violation",
        violation_json,
        "--output-file",
        output_path,
        "--fallback",
        fallback_action,
        "--timeout",
        str(timeout_seconds),
    ]

    env = None
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
        _, stderr_out = proc.communicate(timeout=timeout_seconds + 10)
        if proc.returncode != 0 and stderr_out:
            logger.warning(
                f"prompt ask stderr: {stderr_out.decode('utf-8', errors='replace')[:500]}"
            )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        logger.warning("prompt ask subprocess timed out")
        return None
    except Exception as e:
        logger.warning(f"prompt ask subprocess failed: {e}")
        return None

    try:
        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            decision_str = data.get("decision", "block")
            try:
                decision = AskDecision(decision_str)
            except ValueError:
                decision = AskDecision.BLOCK
            return AskResult(
                decision=decision,
                allowlist_pattern=data.get("allowlist_pattern"),
                config_saved=data.get("config_saved", False),
                source_annotation_saved=data.get("source_annotation_saved", False),
                ignore_path=data.get("ignore_path"),
                ignore_scanner_types=data.get("ignore_scanner_types"),
                config_path=data.get("config_path"),
            )
    except Exception as e:
        logger.warning(f"Failed to read prompt ask result: {e}")
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    return None


def _is_headless_env() -> bool:
    """Return True when running in a display-less environment.

    Covers explicit configuration and auto-detection: on Linux without a
    DISPLAY or WAYLAND_DISPLAY, no GUI tier can show windows, so the caller
    should fall back to tray-forwarding or the configured fallback action.
    """
    from ai_guardian.tui.display import get_preferred_ui

    preferred = get_preferred_ui()
    if preferred == "headless":
        return True
    if preferred != "auto":
        return False
    # Auto-detect: Linux container / SSH session without graphical display
    import sys

    if sys.platform != "linux":
        return False
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return False
    # Containers with -it have a TTY but no user watching the container
    # terminal — tray forwarding (step 1) handles them. If that fails, use
    # fallback. Textual inside a container would block with nobody to respond.
    in_container = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")
    if in_container:
        return True
    # Non-container with TTY (SSH session, local terminal without DISPLAY):
    # Textual can show an interactive dialog.
    if sys.stdin.isatty() and sys.stdout.isatty():
        return False
    return True


def show_ask_dialog(
    violation: AskViolationInfo,
    fallback_action: str = "block",
    timeout_seconds: int = 270,
) -> AskResult:
    """Show interactive dialog for a violation, falling back if headless.

    Two execution paths depending on whether a host tray is registered:

    LOCAL (daemon + display on same host)
    ─────────────────────────────────────
    Hook (runs inside daemon process)
      └─ show_ask_dialog()
           ├─ _show_via_tray_forwarding()  → None  (local tray not registered
           │                                         with local daemon)
           ├─ _is_headless_env()           → False (display available)
           └─ _show_via_daemon()
                └─ POST /api/prompt  (daemon calls its own REST endpoint)
                     └─ _handle_prompt()
                          └─ _show_via_subprocess()
                               └─ ai-guardian prompt --mode ask
                                    └─ tkinter / NiceGUI / Textual dialog
                                    └─ user responds
                               └─ AskResult → HTTP response
                └─ AskResult returned to hook

    REMOTE (container/K8s daemon, host tray)
    ─────────────────────────────────────────
    Host tray                              Container daemon
    ─────────                              ────────────────
    POST /api/register-tray (every ~30s)→  is_tray_registered() = True
                                           Hook fires
                                             └─ show_ask_dialog()
                                                  └─ _show_via_tray_forwarding()
                                                       └─ queue_prompt()
    GET /api/pending-prompts (every 2.5s) ←──────────── decision_event.wait()
      └─ _handle_remote_prompt()
           └─ _show_via_subprocess()        (AI_GUARDIAN_NO_TKINTER=1 on macOS)
                └─ NiceGUI / auto dialog
                └─ user responds
      └─ POST /api/prompt-decision ────────→ resolve_prompt()
                                             decision_event.set()
                                             AskResult returned to hook

    No tray registered + headless env → immediate fallback (no block).

    Args:
        violation: Violation details to display.
        fallback_action: Action to use when no interactive tier available.
        timeout_seconds: Auto-dismiss timeout (Block by default).

    Returns:
        AskResult with the user's decision and optional allowlist pattern.
    """
    # Tray forwarding: try early so containers/headless daemons get a visible
    # dialog on the host without needing explicit preferred_ui=headless.
    result = _show_via_tray_forwarding(violation, fallback_action, timeout_seconds)
    if result is not None:
        return result

    if _is_headless_env():
        decision = _map_fallback_to_decision(fallback_action)
        logger.info("headless env, using fallback: %s -> %s", fallback_action, decision)
        return AskResult(decision=decision)

    result = _show_via_daemon(violation, fallback_action, timeout_seconds)
    if result is not None:
        return result

    result = _show_via_subprocess(violation, fallback_action, timeout_seconds)
    if result is not None:
        return result

    decision = _map_fallback_to_decision(fallback_action)
    logger.info(f"Ask dialog headless fallback: {fallback_action} -> {decision}")
    return AskResult(decision=decision)


# ---------------------------------------------------------------------------
# Tier-specific implementations — re-exported for backward compatibility
# ---------------------------------------------------------------------------

try:
    from ai_guardian.tui.ask_dialog_tk import _TkinterAskDialog
except ImportError:
    pass  # intentionally silent — optional dependency

try:
    from ai_guardian.web.ask_dialog_nicegui import _NiceGuiAskDialog
except ImportError:
    pass  # intentionally silent — optional dependency

try:
    from ai_guardian.tui.ask_dialog_textual import _TextualAskDialog
except ImportError:
    pass  # intentionally silent — optional dependency
