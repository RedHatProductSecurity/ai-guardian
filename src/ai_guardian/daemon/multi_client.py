"""
Multi-daemon client that routes tray actions to the correct daemon transport.

Supports local (Unix socket), container (REST + podman/docker exec),
Kubernetes (REST + kubectl exec), and manual (REST) targets.
"""

import json
import logging
import os
import platform
import shlex
import shutil
import subprocess
from typing import List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from ai_guardian.daemon.discovery import DaemonTarget

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 5.0

# macOS terminals that support Terminal.app-style "do script" AppleScript.
_MACOS_DO_SCRIPT_APPS = {"Terminal", "Warp"}

# macOS CLI terminals: app name → binary name.
# These are launched directly via their CLI binary, not AppleScript.
_MACOS_CLI_TERMINALS = {
    "alacritty": "alacritty",
    "kitty": "kitty",
    "wezterm": "wezterm",
}


def _get_configured_terminal():
    """Read daemon.tray.terminal_app from config. Returns None for auto-detect."""
    try:
        from ai_guardian.config.loaders import _load_config_file

        cfg, _ = _load_config_file()
        return (cfg or {}).get("daemon", {}).get("tray", {}).get("terminal_app")
    except Exception:
        return None


def _build_iterm_applescript(cmd_str, keep_open):
    """Build iTerm2-specific AppleScript."""
    cmd_escaped = cmd_str.replace("\\", "\\\\").replace('"', '\\"')
    if keep_open:
        auto_close = ""
    else:
        auto_close = (
            "        repeat while (is at shell prompt of current session "
            "of current window) is false\n"
            "            delay 1\n"
            "        end repeat\n"
            "        delay 0.5\n"
            "        close current window\n"
        )
    return (
        'tell application "iTerm"\n'
        "    activate\n"
        "    create window with default profile\n"
        "    tell current session of current window\n"
        f'        write text "{cmd_escaped}"\n'
        f"{auto_close}"
        "    end tell\n"
        "end tell"
    )


def _build_terminal_applescript(app_name, cmd_str, keep_open):
    """Build Terminal.app-style AppleScript (also works for Warp)."""
    cmd_escaped = cmd_str.replace("\\", "\\\\").replace('"', '\\"')
    if keep_open:
        auto_close = ""
    else:
        auto_close = (
            "    repeat\n"
            "        delay 1\n"
            "        if not busy of currentTab then\n"
            "            close (every window whose tabs contains "
            "currentTab)\n"
            "            exit repeat\n"
            "        end if\n"
            "    end repeat\n"
        )
    return (
        f'tell application "{app_name}"\n'
        '    set currentTab to do script ""\n'
        "    delay 2\n"
        f'    do script "{cmd_escaped}" in currentTab\n'
        "    activate\n"
        "    set zoomed of front window to true\n"
        f"{auto_close}"
        "end tell"
    )


def _launch_in_terminal(
    cmd_parts, keep_open=False, clear=False, cwd=None, terminal_app=None
):
    """Launch a command in a new terminal window.

    Args:
        cmd_parts: Command and arguments to run.
        keep_open: If True, keep the terminal open after the command
            finishes so the user can read the output.
        clear: If True, clear the terminal before running the command.
        cwd: If set, cd to this directory before running the command.
        terminal_app: Override terminal application. If None, reads from
            config (daemon.tray.terminal_app). If unset, uses platform default.

    Returns:
        True if a terminal was launched, False otherwise.
    """
    if terminal_app is None:
        terminal_app = _get_configured_terminal()

    cmd_str = " ".join(shlex.quote(p) for p in cmd_parts)
    if cwd:
        cmd_str = f"cd {shlex.quote(cwd)}; {cmd_str}"
    if clear:
        cmd_str = "clear; " + cmd_str
    try:
        system = platform.system()
        if system == "Darwin":
            return _launch_macos(cmd_parts, cmd_str, keep_open, terminal_app)
        elif system == "Windows":
            if terminal_app and shutil.which(terminal_app):
                subprocess.Popen([terminal_app] + list(cmd_parts))
                return True
            flag = "/k" if keep_open else "/c"
            win_parts = (["cls", "&&"] if clear else []) + cmd_parts
            if cwd:
                win_parts = ["cd", "/d", cwd, "&&"] + win_parts
            subprocess.Popen(["cmd", flag, "start", "/max"] + win_parts)
            return True
        else:
            if keep_open:
                shell_cmd = cmd_str + '; echo; read -rp "Press Enter to close..."'
                cmd_parts = ["bash", "-c", shell_cmd]
            if terminal_app and shutil.which(terminal_app):
                subprocess.Popen([terminal_app, "-e"] + list(cmd_parts))
                return True
            if terminal_app:
                logger.warning(
                    "Configured terminal '%s' not found, "
                    "falling back to auto-detection.",
                    terminal_app,
                )
            for term, args in [
                ("gnome-terminal", ["--maximize", "--"]),
                ("kgx", ["-e"]),
                ("konsole", ["--fullscreen", "-e"]),
                ("xfce4-terminal", ["--maximize", "-e"]),
                ("xterm", ["-maximized", "-e"]),
            ]:
                if shutil.which(term):
                    subprocess.Popen([term] + args + cmd_parts)
                    return True
            else:
                logger.warning(
                    "No supported terminal emulator found. "
                    "Tried: gnome-terminal, kgx, konsole, "
                    "xfce4-terminal, xterm. Install one of these to use "
                    "Console/Terminal/Doctor from the tray."
                )
                return False
    except OSError as e:
        logger.warning("Failed to launch terminal: %s", e)
        return False


def _launch_macos(cmd_parts, cmd_str, keep_open, terminal_app):
    """Launch terminal on macOS. Handles iTerm2, CLI terminals, and Terminal.app."""
    app = (terminal_app or "").strip().removesuffix(".app")

    # CLI-based terminals (alacritty, kitty, wezterm) — launch binary directly
    cli_bin = _MACOS_CLI_TERMINALS.get(app.lower())
    if cli_bin and shutil.which(cli_bin):
        subprocess.Popen([cli_bin, "-e"] + list(cmd_parts))
        return True

    # iTerm2 — uses its own AppleScript API
    if app.lower() in ("iterm", "iterm2"):
        script = _build_iterm_applescript(cmd_str, keep_open)
        subprocess.Popen(["osascript", "-e", script])
        return True

    # Terminal.app, Warp, or unset (default) — "do script" AppleScript
    app_name = app or "Terminal"
    if app and app not in _MACOS_DO_SCRIPT_APPS:
        logger.warning(
            "Terminal '%s' not recognized; trying Terminal.app-style "
            "AppleScript. If it fails, use a CLI terminal name "
            "(alacritty, kitty, wezterm) or iTerm/iTerm2.",
            app,
        )
    script = _build_terminal_applescript(app_name, cmd_str, keep_open)
    subprocess.Popen(["osascript", "-e", script])
    return True


class MultiDaemonClient:
    """Routes tray actions to the appropriate daemon transport."""

    def get_status(self, target: DaemonTarget) -> Optional[dict]:
        """Get daemon status/stats."""
        if target.runtime == "local":
            return self._local_status(target)
        return self._rest_request(target, "GET", "/api/stats")

    def send_pause(self, target: DaemonTarget, minutes: int) -> bool:
        """Pause daemon scanning."""
        if target.runtime == "local":
            return self._local_pause(target, minutes)
        result = self._rest_request(target, "POST", "/api/pause", {"minutes": minutes})
        return result is not None

    def send_resume(self, target: DaemonTarget) -> bool:
        """Resume daemon scanning."""
        if target.runtime == "local":
            return self._local_resume(target)
        result = self._rest_request(target, "POST", "/api/resume")
        return result is not None

    def send_pause_dir(
        self,
        target: DaemonTarget,
        directory: str,
        minutes: int,
    ) -> bool:
        """Pause scanning for a specific directory."""
        if target.runtime == "local":
            return MultiDaemonClient._local_socket_send(
                {
                    "version": 1,
                    "type": "pause_dir",
                    "data": {"dir": directory, "minutes": minutes},
                }
            )
        result = self._rest_request(
            target,
            "POST",
            "/api/pause_dir",
            {"dir": directory, "minutes": minutes},
        )
        return result is not None

    def send_resume_dir(self, target: DaemonTarget, directory: str) -> bool:
        """Resume scanning for a specific directory."""
        if target.runtime == "local":
            return MultiDaemonClient._local_socket_send(
                {"version": 1, "type": "resume_dir", "data": {"dir": directory}}
            )
        result = self._rest_request(
            target,
            "POST",
            "/api/resume_dir",
            {"dir": directory},
        )
        return result is not None

    def send_stop(self, target: DaemonTarget) -> bool:
        """Stop daemon."""
        if target.runtime == "local":
            from ai_guardian.daemon.client import send_shutdown

            return send_shutdown()
        return self._send_daemon_command(target, "stop")

    def send_restart(self, target: DaemonTarget) -> bool:
        """Restart daemon."""
        if target.runtime == "local":
            return self._local_restart()
        return self._send_daemon_command(target, "restart")

    # --- Upgrade transport ---

    def check_pip_available(self, target: DaemonTarget) -> bool:
        """Check whether pip is available on the target."""
        try:
            if target.runtime == "local":
                result = subprocess.run(
                    ["python", "-m", "pip", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.returncode == 0
            cmd = ["pip", "--version"]
            if target.runtime == "container":
                return self._container_exec(target, cmd, timeout=10) is not None
            if target.runtime == "kubernetes":
                return self._kubectl_exec(target, cmd, timeout=10) is not None
        except (subprocess.TimeoutExpired, OSError):
            pass  # intentionally silent — subprocess may fail
        return False

    @staticmethod
    def check_pypi_version() -> Optional[str]:
        """Fetch the latest ai-guardian version from PyPI."""
        try:
            url = "https://pypi.org/pypi/ai-guardian/json"
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return data.get("info", {}).get("version")
        except Exception:
            return None

    def run_pip_upgrade(
        self, target: DaemonTarget, version: Optional[str] = None, timeout: int = 120
    ) -> tuple:
        """Sync daemon to a specific version or upgrade to latest.

        Args:
            target: The daemon target to upgrade
            version: Specific version to install (e.g., "1.12.0"), or None for latest
            timeout: Command timeout in seconds

        Returns:
            (success, output): Tuple of success boolean and command output
        """
        try:
            # Build pip install command
            if version:
                pkg_spec = f"ai-guardian=={version}"
            else:
                pkg_spec = "ai-guardian"

            if target.runtime == "local":
                python_exe = (
                    shutil.which("python") or shutil.which("python3") or "python"
                )
                cmd = [python_exe, "-m", "pip", "install"]
                if not version:
                    cmd.append("--upgrade")
                cmd.append(pkg_spec)
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = result.stdout + result.stderr
                return (result.returncode == 0, output)

            # Remote targets (container/kubernetes)
            cmd = ["pip", "install"]
            if not version:
                cmd.append("--upgrade")
            cmd.append(pkg_spec)
            if target.runtime == "container":
                out = self._container_exec(target, cmd, timeout=timeout)
                return (out is not None, out or "")
            if target.runtime == "kubernetes":
                out = self._kubectl_exec(target, cmd, timeout=timeout)
                return (out is not None, out or "")
        except subprocess.TimeoutExpired:
            return (False, "Version sync timed out")
        except OSError as e:
            return (False, str(e))
        return (False, "Unsupported runtime")

    def _send_daemon_command(self, target: DaemonTarget, command: str) -> bool:
        """Send a daemon subcommand via exec to a remote target."""
        cmd = ["ai-guardian", "daemon", command]
        if target.runtime == "container":
            return self._container_exec(target, cmd) is not None
        if target.runtime == "kubernetes":
            return self._kubectl_exec(target, cmd) is not None
        return False

    def open_console(self, target: DaemonTarget, panel: Optional[str] = None):
        """Open console for the target daemon."""
        cmd = ["ai-guardian", "console"]
        if panel:
            cmd.extend(["--panel", panel])

        if target.runtime == "local":
            self._local_console(cmd)
        elif target.runtime == "container":
            self._container_console(target, cmd)
        elif target.runtime == "kubernetes":
            self._kubectl_console(target, cmd)

    def open_shell(self, target: DaemonTarget):
        """Open an interactive shell for the target daemon."""
        if target.runtime == "local":
            self._local_shell(cwd=getattr(target, "working_dir", None))
        elif target.runtime == "container":
            self._container_shell(target)
        elif target.runtime == "kubernetes":
            self._kubectl_shell(target)

    def open_doctor(self, target: DaemonTarget):
        """Open doctor for the target daemon in a new terminal."""
        cmd = ["ai-guardian", "doctor"]
        if target.runtime == "local":
            from ai_guardian.daemon import get_executable_command

            cmd_parts = get_executable_command() + cmd[1:]
            _launch_in_terminal(cmd_parts, keep_open=True)
        elif target.runtime == "container":
            engine = target.container_engine or "podman"
            exec_cmd = [engine, "exec", "-it", target.container_id] + cmd
            _launch_in_terminal(exec_cmd, keep_open=True)
        elif target.runtime == "kubernetes":
            exec_cmd = [
                "kubectl",
                "exec",
                "-it",
                target.pod_name,
                "-n",
                target.namespace or "default",
                "--",
            ] + cmd
            _launch_in_terminal(exec_cmd, keep_open=True)

    def get_plugins(self, target: DaemonTarget) -> Optional[dict]:
        """Get tray plugin definitions from a daemon."""
        if target.runtime == "local":
            return self._local_plugins(
                working_dir=getattr(target, "working_dir", None),
            )
        return self._rest_request(target, "GET", "/api/tray-plugins")

    @staticmethod
    def _local_plugins(working_dir: Optional[str] = None) -> dict:
        from ai_guardian.tray.plugins import load_merged_plugins, plugins_to_dict

        return plugins_to_dict(load_merged_plugins(working_dir))

    def get_about(self, target: DaemonTarget) -> Optional[dict]:
        """Get about info from a daemon."""
        if target.runtime == "local":
            return self._local_about()
        return self._rest_request(target, "GET", "/api/about")

    @staticmethod
    def _local_about() -> dict:
        from ai_guardian.daemon.about import get_about_info

        return get_about_info()

    # --- Tray ask forwarding (#1342) ---

    def register_tray(self, target, tray_host, tray_port):
        """Register this tray with a remote daemon for ask dialog forwarding."""
        result = self._rest_request(
            target,
            "POST",
            "/api/register-tray",
            {"host": tray_host, "port": int(tray_port)},
        )
        return result is not None

    def get_pending_prompts(self, target):
        """Poll for pending ask prompts from a remote daemon."""
        result = self._rest_request(target, "GET", "/api/pending-prompts", timeout=3.0)
        if result:
            return result.get("prompts", [])
        return None

    def send_prompt_decision(self, target, prompt_id, decision_data):
        """Send ask dialog decision back to a remote daemon."""
        body = {"prompt_id": prompt_id, **decision_data}
        result = self._rest_request(target, "POST", "/api/prompt-decision", body)
        return result is not None and result.get("status") == "accepted"

    def get_config(self, target: DaemonTarget) -> Optional[dict]:
        """Get feature configuration flags from a daemon."""
        if target.runtime == "local":
            return self._local_config()
        return self._rest_request(target, "GET", "/api/config")

    @staticmethod
    def _local_config() -> dict:
        from ai_guardian.config.loaders import _load_config_file
        from ai_guardian.config.utils import get_feature_flags, is_feature_enabled

        cfg, _ = _load_config_file()
        if not cfg:
            cfg = {}
        features = get_feature_flags(cfg)
        si_section = cfg.get("security_instructions")
        features["security_instructions"] = is_feature_enabled(
            (
                si_section.get("inject_on_prompt")
                if isinstance(si_section, dict)
                else None
            ),
            default=True,
        )
        mcp_cfg = cfg.get("mcp_server", {})
        features["mcp_server"] = bool(mcp_cfg) if mcp_cfg is not None else True
        scanner_action_keys = [
            "secret_redaction",
            "scan_pii",
            "prompt_injection",
            "context_poisoning",
            "ssrf_protection",
            "supply_chain",
            "config_file_scanning",
        ]
        global_action = cfg.get("action", "block")
        if isinstance(global_action, dict):
            global_action = global_action.get("mode", "block")
        scanner_actions = {}
        for key in scanner_action_keys:
            section = cfg.get(key, {})
            if isinstance(section, dict):
                scanner_actions[key] = section.get("action", global_action)
            else:
                scanner_actions[key] = global_action
        features["scanner_actions"] = scanner_actions
        if isinstance(mcp_cfg, dict):
            features["proactive_level"] = mcp_cfg.get("proactive_level", "low")
        else:
            features["proactive_level"] = "low"
        return {"features": features}

    def get_config_scoped(
        self,
        target: DaemonTarget,
        scope: str = "merged",
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        """Get config for a specific scope."""
        if target.runtime == "local":
            from ai_guardian.config.writer import load_scoped_config

            return load_scoped_config(scope, project_dir)
        params = f"?scope={scope}"
        if project_dir:
            params += f"&project_dir={project_dir}"
        return self._rest_request(target, "GET", f"/api/config{params}")

    def get_config_provenance(
        self,
        target: DaemonTarget,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        """Get per-key provenance information."""
        if target.runtime == "local":
            from ai_guardian.config.writer import compute_provenance

            return compute_provenance(project_dir)
        params = f"?project_dir={project_dir}" if project_dir else ""
        return self._rest_request(target, "GET", f"/api/config/provenance{params}")

    def write_config(
        self,
        target: DaemonTarget,
        scope: str,
        section: str,
        key: Optional[str],
        value,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        """Write a config value to the specified scope."""
        if target.runtime == "local":
            from ai_guardian.config.writer import write_scoped_config

            success, msg = write_scoped_config(scope, section, key, value, project_dir)
            return {"status": "ok" if success else "error", "message": msg}
        body = {"scope": scope, "section": section, "value": value}
        if key is not None:
            body["key"] = key
        if project_dir:
            body["project_dir"] = project_dir
        return self._rest_request(target, "POST", "/api/config", body)

    def delete_config_override(
        self,
        target: DaemonTarget,
        section: str,
        key: Optional[str] = None,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        """Delete a project config override."""
        if target.runtime == "local":
            from ai_guardian.config.writer import delete_project_override

            success, msg = delete_project_override(section, key, project_dir)
            return {"status": "ok" if success else "error", "message": msg}
        body: dict = {"section": section}
        if key is not None:
            body["key"] = key
        if project_dir:
            body["project_dir"] = project_dir
        return self._rest_request(target, "DELETE", "/api/config", body)

    def write_config_bulk(
        self,
        target: DaemonTarget,
        scope: str,
        config: dict,
        project_dir: Optional[str] = None,
    ) -> Optional[dict]:
        """Write an entire config dict to the specified scope."""
        if target.runtime == "local":
            from ai_guardian.config.writer import (
                _resolve_config_path,
                _atomic_config_update,
            )

            config_path = _resolve_config_path(scope, project_dir)

            def updater(existing):
                existing.clear()
                existing.update(config)
                return False, f"Bulk write [{scope}]"

            _atomic_config_update(config_path, updater)
            return {"status": "ok"}
        body: dict = {"scope": scope, "config": config}
        if project_dir:
            body["project_dir"] = project_dir
        return self._rest_request(
            target, "POST", "/api/config/bulk", body, timeout=10.0
        )

    def get_cache_status(self, target: DaemonTarget) -> Optional[dict]:
        """Get per-project config cache status from a daemon."""
        return self._rest_request(target, "GET", "/api/cache-status")

    @staticmethod
    def _local_cache_status() -> dict:
        import time as _time
        from ai_guardian.config.loaders import _caches

        now = _time.monotonic()
        projects = []
        for cache_key, entry in sorted(_caches.items()):
            gp = entry.global_path
            pp = entry.project_path
            projects.append(
                {
                    "project_dir": cache_key if cache_key != "__global__" else None,
                    "config_path": str(pp) if pp else None,
                    "config_mtime": entry.project_mtime,
                    "last_seen_seconds_ago": round(now - entry.last_accessed, 1),
                    "has_project_override": pp is not None,
                    "global_config_path": str(gp) if gp else None,
                    "global_config_mtime": entry.global_mtime,
                    "cached_project_path": str(pp) if pp else None,
                    "cached_project_mtime": entry.project_mtime,
                    "cache_last_accessed_seconds_ago": round(
                        now - entry.last_accessed, 1
                    ),
                }
            )
        return {
            "projects": projects,
            "total_tracked": len(projects),
            "last_project_config_reload_at": None,
            "timestamp": _time.time(),
        }

    def get_violations(
        self,
        target: DaemonTarget,
        limit: int = 50,
        violation_type: Optional[str] = None,
    ) -> Optional[dict]:
        """Get recent violations from a daemon."""
        if target.runtime == "local":
            return self._local_violations(limit, violation_type)
        params = f"?limit={limit}"
        if violation_type:
            params += f"&type={violation_type}"
        return self._rest_request(target, "GET", f"/api/violations{params}")

    @staticmethod
    def _local_violations(limit: int, violation_type: Optional[str]) -> dict:
        from ai_guardian.violations.logger import ViolationLogger

        vl = ViolationLogger()
        entries = vl.get_recent_violations(limit=limit, violation_type=violation_type)
        violations = []
        for entry in entries:
            ctx = entry.get("context", {})
            v = {
                "timestamp": entry.get("timestamp", ""),
                "type": entry.get("violation_type", ""),
                "severity": entry.get("severity", ""),
                "tool": ctx.get("tool", ""),
                "file": ctx.get("file", ""),
                "action": "blocked" if entry.get("blocked") else "logged",
                "suggestion": "",
            }
            sug = entry.get("suggestion")
            if isinstance(sug, dict):
                v["suggestion"] = sug.get("text", "")
            elif isinstance(sug, str):
                v["suggestion"] = sug
            line = ctx.get("line")
            if line is not None:
                v["line"] = line
            violations.append(v)
        return {"violations": violations, "count": len(violations)}

    def get_violation_context(
        self,
        target: DaemonTarget,
        file_path: str,
        line_number: int,
        violation_type: str,
        secret_type: str = "",
    ) -> Optional[dict]:
        """Rescan a file on the daemon to get matched text for allowlisting."""
        if target.runtime == "local":
            from ai_guardian.daemon.violation_rescan import rescan_violation

            return rescan_violation(
                file_path=file_path,
                line_number=line_number,
                violation_type=violation_type,
                sub_type=secret_type,
            )
        body = {
            "file_path": file_path,
            "line_number": line_number,
            "violation_type": violation_type,
            "secret_type": secret_type,
        }
        return self._rest_request(target, "POST", "/api/violation-context", body)

    def scan_path(
        self,
        target: DaemonTarget,
        path: str,
    ) -> Optional[dict]:
        """Run a file/directory scan on the target daemon."""
        if target.runtime == "local":
            return self._local_scan(path)
        return self._rest_request(
            target,
            "POST",
            "/api/scan",
            body={"path": path},
            timeout=120.0,
        )

    @staticmethod
    def _local_scan(path: str) -> dict:
        """Run scan locally via FileScanner."""
        import time
        from pathlib import Path as _Path
        from ai_guardian.scanners.file_scanner import FileScanner
        from ai_guardian.tui.pattern_editor import config_section_for_rule_id
        from ai_guardian.web.config_helpers import load_web_config

        config = load_web_config()
        scanner = FileScanner(config=config)
        resolved = _Path(path).resolve()

        t0 = time.monotonic()
        findings = scanner.scan_directory(path=str(resolved))
        elapsed_ms = round((time.monotonic() - t0) * 1000)

        base = resolved if resolved.is_dir() else resolved.parent
        for f in findings:
            f["config_section"] = config_section_for_rule_id(f.get("rule_id", ""))
            fp = f.get("file_path", "")
            if fp and not _Path(fp).is_absolute():
                f["file_path"] = str(base / fp)

        return {
            "findings": findings,
            "scanned_files": len(findings),
            "scan_time_ms": elapsed_ms,
        }

    def get_metrics(
        self,
        target: DaemonTarget,
        since_days: Optional[int] = None,
    ) -> Optional[dict]:
        """Get violation metrics from a daemon."""
        if target.runtime == "local":
            return self._local_metrics(since_days)
        params = f"?since_days={since_days}" if since_days else ""
        return self._rest_request(target, "GET", f"/api/metrics{params}")

    @staticmethod
    def _local_metrics(since_days: Optional[int]) -> dict:
        from ai_guardian.reporting.metrics import MetricsComputer

        mc = MetricsComputer(since_days=since_days)
        report = mc.compute()
        return {
            "total_violations": report.total_violations,
            "by_type": report.by_type,
            "by_severity": report.by_severity,
            "resolved": report.resolved_count,
            "unresolved": report.unresolved_count,
            "cumulative_total": report.cumulative_total,
            "cumulative_by_type": report.cumulative_by_type,
            "cumulative_since": report.cumulative_since,
        }

    def get_audit(
        self,
        target: DaemonTarget,
        since: str = "30d",
        until: Optional[str] = None,
        violation_type: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> Optional[dict]:
        """Get audit report from a daemon."""
        if target.runtime == "local":
            return self._local_audit(since, until, violation_type, severity)
        params = f"?since={since}"
        if until:
            params += f"&until={until}"
        if violation_type:
            params += f"&type={violation_type}"
        if severity:
            params += f"&severity={severity}"
        return self._rest_request(target, "GET", f"/api/audit{params}")

    @staticmethod
    def _local_audit(
        since: str = "30d",
        until: Optional[str] = None,
        violation_type: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> dict:
        import json as _json
        from ai_guardian.reporting.audit import AuditComputer, format_audit_json

        computer = AuditComputer(
            since=since,
            until=until,
            violation_type=violation_type,
            severity=severity,
        )
        report = computer.compute()
        return _json.loads(format_audit_json(report))

    def get_logs(
        self,
        target: DaemonTarget,
        limit: int = 500,
        level: str = "INFO",
    ) -> Optional[dict]:
        """Get log entries from a daemon."""
        if target.runtime == "local":
            return self._local_logs(limit, level)
        params = f"?limit={limit}&level={level}"
        return self._rest_request(target, "GET", f"/api/logs{params}")

    @staticmethod
    def _local_logs(limit: int = 500, level: str = "INFO") -> dict:
        from pathlib import Path as _Path
        from ai_guardian.config.utils import get_state_dir

        log_path = get_state_dir() / "ai-guardian.log"
        if not log_path.exists():
            return {"entries": [], "count": 0, "log_path": str(log_path)}

        level_priority = {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
            "CRITICAL": 50,
        }
        min_priority = level_priority.get(level, 20)

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                tail = lines[-limit:] if len(lines) > limit else lines
        except OSError:
            return {"entries": [], "count": 0, "log_path": str(log_path)}

        entries = []
        for line in tail:
            line = line.rstrip()
            if not line:
                continue
            parts = line.split(" - ")
            if len(parts) >= 4:
                if len(parts) == 5:
                    ts, _, module, lvl, msg = (
                        parts[0].strip(),
                        parts[1].strip(),
                        parts[2].strip(),
                        parts[3].strip(),
                        parts[4].strip(),
                    )
                else:
                    ts, module, lvl, msg = (
                        parts[0].strip(),
                        parts[1].strip(),
                        parts[2].strip(),
                        parts[3].strip(),
                    )
                if lvl in level_priority:
                    if level_priority[lvl] >= min_priority:
                        entries.append(
                            {
                                "timestamp": ts,
                                "module": module,
                                "level": lvl,
                                "message": msg,
                            }
                        )
                elif min_priority <= 10:
                    entries.append(
                        {
                            "timestamp": "",
                            "module": "",
                            "level": "DEBUG",
                            "message": line,
                        }
                    )
            elif min_priority <= 10:
                entries.append(
                    {
                        "timestamp": "",
                        "module": "",
                        "level": "DEBUG",
                        "message": line,
                    }
                )

        return {
            "entries": entries,
            "count": len(entries),
            "log_path": str(log_path),
        }

    def get_performance(
        self,
        target: DaemonTarget,
        since_days: int = 30,
    ) -> Optional[dict]:
        """Get hook latency performance data from a daemon."""
        if target.runtime == "local":
            return self._local_performance(since_days)
        params = f"?since_days={since_days}"
        return self._rest_request(target, "GET", f"/api/performance{params}")

    @staticmethod
    def _local_performance(since_days: int = 30) -> dict:
        from ai_guardian.reporting.latency import LatencyComputer

        computer = LatencyComputer(since_days=since_days)
        report = computer.compute()
        return {
            "hook_stats": report.hook_stats,
            "check_stats": report.check_stats,
            "invocation_count": report.invocation_count,
        }

    def get_health_check(
        self,
        target: DaemonTarget,
        fix: bool = False,
    ) -> Optional[dict]:
        """Run health checks on a daemon."""
        if target.runtime == "local":
            return self._local_health_check(fix)
        params = "?fix=true" if fix else ""
        return self._rest_request(target, "GET", f"/api/health-check{params}")

    @staticmethod
    def _local_health_check(fix: bool = False) -> dict:
        from ai_guardian.doctor import Doctor

        doctor = Doctor(fix=fix)
        report = doctor.run_all()
        return {
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "detail": c.detail,
                    "fix_hint": c.fix_hint,
                    "fixable": c.fixable,
                    "fixed": c.fixed,
                }
                for c in report.checks
            ],
            "version": report.version,
        }

    def refresh_pattern_cache(self, target: DaemonTarget) -> Optional[dict]:
        """Trigger pattern server cache refresh on a daemon."""
        if target.runtime == "local":
            return self._local_refresh_pattern_cache()
        return self._rest_request(target, "POST", "/api/patterns/refresh")

    @staticmethod
    def _local_refresh_pattern_cache() -> dict:
        from ai_guardian.config.loaders import _load_pattern_server_config
        from ai_guardian.patterns.server import PatternServerClient

        config = _load_pattern_server_config()
        if not config:
            return {"result": "No pattern server configured"}

        results = []
        for ptype in PatternServerClient.DEFAULT_CACHE_FILES:
            try:
                client = PatternServerClient(config, pattern_type=ptype)
                if client._fetch_patterns():
                    results.append(f"{ptype}: refreshed")
                else:
                    results.append(f"{ptype}: failed")
            except Exception as exc:
                results.append(f"{ptype}: error ({exc})")
        return {"result": "; ".join(results)}

    def export_support(self, target: DaemonTarget) -> Optional[str]:
        """Export support bundle."""
        cmd = ["ai-guardian", "support", "prepare"]
        if target.runtime == "local":
            return self._local_exec(cmd)
        if target.runtime == "container":
            return self._container_exec(target, cmd)
        if target.runtime == "kubernetes":
            return self._kubectl_exec(target, cmd)
        return None

    # --- Local transport ---

    @staticmethod
    def _local_status(target: DaemonTarget) -> Optional[dict]:
        from ai_guardian.daemon.client import send_status_request

        return send_status_request()

    @staticmethod
    def _local_socket_send(msg: dict) -> bool:
        import socket as socket_mod
        from ai_guardian.daemon import get_socket_path
        from ai_guardian.daemon.protocol import encode_message, decode_message

        try:
            sock = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
            sock.settimeout(REQUEST_TIMEOUT)
            sock.connect(str(get_socket_path()))
            sock.sendall(encode_message(msg))
            decode_message(sock, timeout=REQUEST_TIMEOUT)
            sock.close()
            return True
        except Exception:
            return False

    @staticmethod
    def _local_pause(target: DaemonTarget, minutes: int) -> bool:
        return MultiDaemonClient._local_socket_send(
            {"version": 1, "type": "pause", "data": {"minutes": minutes}}
        )

    @staticmethod
    def _local_resume(target: DaemonTarget) -> bool:
        return MultiDaemonClient._local_socket_send({"version": 1, "type": "resume"})

    @staticmethod
    def _local_restart() -> bool:
        from ai_guardian.daemon import get_executable_command

        cmd = get_executable_command() + ["daemon", "restart"]
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            return False

    @staticmethod
    def _local_console(cmd: List[str]):
        """Launch console locally in a new terminal window."""
        from ai_guardian.daemon import get_executable_command

        cmd_parts = get_executable_command() + cmd[1:]
        _launch_in_terminal(cmd_parts)

    @staticmethod
    def _local_shell(cwd=None):
        """Open default shell in a new terminal window."""
        shell = os.environ.get("SHELL", "/bin/sh")
        _launch_in_terminal([shell], keep_open=True, cwd=cwd)

    @staticmethod
    def _local_exec(cmd: List[str]) -> Optional[str]:
        from ai_guardian.daemon import get_executable_command

        full_cmd = get_executable_command() + cmd[1:]
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=30
            )
            return result.stdout
        except (subprocess.TimeoutExpired, OSError):
            return None

    # --- REST transport ---

    @staticmethod
    def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
        """Fast TCP connect check. Returns True if host:port accepts connections."""
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.close()
            return True
        except (OSError, socket.timeout):
            return False

    @staticmethod
    def _rest_request(
        target: DaemonTarget,
        method: str,
        path: str,
        body: Optional[dict] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> Optional[dict]:
        """Send HTTP request to daemon REST API."""
        if target.url:
            base = target.url.rstrip("/")
        elif target.port:
            base = f"http://{target.host}:{target.port}"
        else:
            return None

        from urllib.parse import urlparse

        parsed = urlparse(base)
        check_host = parsed.hostname or target.host
        check_port = parsed.port or target.port
        if (
            check_host
            and check_port
            and not MultiDaemonClient._tcp_reachable(check_host, check_port)
        ):
            logger.debug(
                "TCP unreachable (%s:%s), skipping REST request",
                check_host,
                check_port,
            )
            return None

        url = f"{base}{path}"
        data = json.dumps(body).encode("utf-8") if body else None

        req = Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if target.auth_token:
            req.add_header("Authorization", f"Bearer {target.auth_token}")

        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
            logger.debug("REST request failed (%s %s): %s", method, url, e)
            return None

    # --- Container transport ---

    @staticmethod
    def _container_exec(
        target: DaemonTarget, cmd: List[str], timeout: int = 30
    ) -> Optional[str]:
        """Execute command inside container (non-interactive)."""
        import re

        if not target.container_id or not re.match(
            r"^[a-fA-F0-9]{12,64}$", target.container_id
        ):
            logger.warning("Refusing exec: invalid container ID format")
            return None
        engine = target.container_engine or "podman"
        full_cmd = [engine, "exec", target.container_id] + cmd
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0:
                logger.debug("Container exec failed: %s", result.stderr)
                return None
            return result.stdout
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("Container exec error: %s", e)
            return None

    @staticmethod
    def _container_console(target: DaemonTarget, cmd: List[str]):
        """Open interactive console inside container in a new terminal."""
        engine = target.container_engine or "podman"
        exec_cmd = [engine, "exec", "-it", target.container_id] + cmd
        _launch_in_terminal(exec_cmd)

    @staticmethod
    def _container_shell(target: DaemonTarget):
        """Open interactive shell inside container in a new terminal."""
        engine = target.container_engine or "podman"
        exec_cmd = [engine, "exec", "-it", target.container_id, "/bin/sh"]
        _launch_in_terminal(exec_cmd, keep_open=True)

    # --- Kubernetes transport ---

    @staticmethod
    def _kubectl_exec(
        target: DaemonTarget, cmd: List[str], timeout: int = 30
    ) -> Optional[str]:
        """Execute command inside K8s pod (non-interactive)."""
        full_cmd = [
            "kubectl",
            "exec",
            target.pod_name,
            "-n",
            target.namespace or "default",
            "--",
        ] + cmd
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0:
                logger.debug("kubectl exec failed: %s", result.stderr)
                return None
            return result.stdout
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("kubectl exec error: %s", e)
            return None

    @staticmethod
    def _kubectl_console(target: DaemonTarget, cmd: List[str]):
        """Open interactive console inside K8s pod in a new terminal."""
        exec_cmd = [
            "kubectl",
            "exec",
            "-it",
            target.pod_name,
            "-n",
            target.namespace or "default",
            "--",
        ] + cmd
        _launch_in_terminal(exec_cmd)

    @staticmethod
    def _kubectl_shell(target: DaemonTarget):
        """Open interactive shell inside K8s pod in a new terminal."""
        exec_cmd = [
            "kubectl",
            "exec",
            "-it",
            target.pod_name,
            "-n",
            target.namespace or "default",
            "--",
            "/bin/sh",
        ]
        _launch_in_terminal(exec_cmd, keep_open=True)
