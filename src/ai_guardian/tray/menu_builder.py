"""
Menu construction for the system tray — single-daemon, multi-daemon,
directory pause, IDE setup, and about menus.

Split from tray.py (Issue #1542). TrayMenuBuilder constructs pystray
MenuItem trees by reading state from DaemonTray and its sub-managers.
"""

import logging
import os
import secrets
import shlex
import threading
import time
from types import SimpleNamespace

from ai_guardian.daemon.discovery import should_update_target_name
from ai_guardian.ide_registry import SUPPORTED_CLI_IDE_TYPES
from ai_guardian.tray import icons as tray_icons
from ai_guardian.tray import menu as tray_menu
from ai_guardian.tray import notifications as tray_notifications
from ai_guardian.tray import plugins as tray_plugins

logger = logging.getLogger(__name__)

try:
    import pystray
except Exception:
    pystray = None


class TrayMenuBuilder:
    """Constructs pystray menu item trees for the system tray."""

    from ai_guardian.tray.menu import (
        MAX_DIR_PAUSE_SLOTS as _MAX_DIR_PAUSE_SLOTS,
    )

    def __init__(self, tray):
        self._tray = tray
        self._single_daemon_closures = {}

    def _on_about(self, icon, item):
        """Show About info via OS dialog."""

        screen_bounds = self._capture_tray_screen_bounds(icon)
        target = None
        if len(self._tray._targets) == 1:
            target = self._tray._targets[0]

        def _show():
            try:
                from ai_guardian.tray.plugins import show_dialog

                title = "About AI Guardian"
                if target and target.runtime != "local":
                    info = None
                    if self._tray._multi_client:
                        info = self._tray._multi_client.get_about(target)
                    if info:
                        from ai_guardian.daemon.about import format_about_text

                        title = f"About {target.name}"
                        text = format_about_text(info)
                    else:
                        title, text = self._format_unavailable_remote_about(target)
                else:
                    text = tray_menu.build_about_text()
                    if self._tray._is_multi_daemon():
                        text = self._format_local_about_text(text)
                        text += self._format_daemon_list()
                show_dialog(
                    title,
                    text,
                    **self._screen_bounds_kwargs(screen_bounds),
                )
            except Exception:
                pass  # intentionally silent — optional dependency

        threading.Thread(target=_show, daemon=True, name="about-dialog").start()

    def _daemon_about_label(self, slot):
        """Build About menu label with daemon version for a specific slot."""

        def _label(_item=None):
            if slot >= len(self._tray._targets):
                return "About"
            target = self._tray._targets[slot]
            key = (target.name, target.runtime)
            version = self._tray._health._daemon_versions.get(key, "")
            if version:
                return f"About — v{version}"
            return "About"

        return _label

    def _on_daemon_about(self, slot):
        """Show About info for a specific daemon via OS dialog."""

        def action(icon, __):
            if slot >= len(self._tray._targets):
                return
            target = self._tray._targets[slot]
            screen_bounds = self._capture_tray_screen_bounds(icon)

            def _show():
                try:
                    from ai_guardian.tray.plugins import show_dialog

                    info = self._tray._daemon_about_cache.get(slot)
                    if info is None and self._tray._multi_client:
                        info = self._tray._multi_client.get_about(target)
                        if info:
                            self._tray._daemon_about_cache[slot] = info
                    if info:
                        from ai_guardian.daemon.about import format_about_text

                        text = format_about_text(info)
                    elif target.runtime != "local":
                        _, text = self._format_unavailable_remote_about(target)
                    else:
                        text = tray_menu.build_about_text()
                    show_dialog(
                        f"About {target.name}",
                        text,
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
                except Exception:
                    pass  # intentionally silent — optional dependency

            threading.Thread(
                target=_show, daemon=True, name="daemon-about-dialog"
            ).start()

        return action

    @staticmethod
    def _format_local_about_text(text):
        """Identify About fields that describe the local tray process."""
        return f"Local tray (this process):\n{text}"

    def _format_unavailable_remote_about(self, target):
        """Format a clear fallback when a remote daemon has no About data."""
        return (
            f"About {target.name}",
            "Remote daemon information is unavailable.\n\n"
            + self._format_local_about_text(tray_menu.build_about_text()),
        )

    def _format_daemon_list(self):
        """Format connected daemons list for multi-daemon About."""
        if not self._tray._targets:
            return ""
        lines = [f"\nDaemons: {len(self._tray._targets)} connected"]
        for target in self._tray._targets:
            key = (target.name, target.runtime)
            ver = self._tray._health._daemon_versions.get(key, "?")
            if target.status == "running" and self._tray._target_has_paused_dirs(
                target
            ):
                icon = "◐"
            else:
                icon = {"running": "●", "paused": "☾", "stopped": "⚠"}.get(
                    target.status, "○"
                )
            suffix = ""
            if key in self._tray._health._version_mismatch_notified:
                suffix = " ⟳"
            lines.append(f"  {icon} {target.name} v{ver}{suffix}")
        return "\n".join(lines)

    def _pause_menu_label(self):
        return "Pause..."

    def _resume_menu_label(self):
        stats = self._tray._get_stats()
        remaining = stats.get("pause_remaining_seconds", 0)
        if remaining > 0 and self._tray._supports_live_pause_countdown():
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            return f"Resume ({mins}m {secs}s left)"
        return "Resume (paused)"

    def _get_merged_dir_list(self, stats):
        """Merge active project dirs and paused dirs into a sorted list."""
        active = set(stats.get("active_project_dirs") or [])
        paused = set(stats.get("paused_dirs") or {})
        return sorted(active | paused)

    def _multi_global_pause_label(self, stats_fns, _item):
        """Format global pause label with status circle for multi-daemon."""
        is_paused = stats_fns[11](_item)
        if is_paused:
            stats = stats_fns[13](_item)
            remaining = stats.get("pause_remaining_seconds", 0)
            if remaining > 0 and self._tray._supports_live_pause_countdown():
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                return f"☾ Daemon (global) ({mins}m {secs}s)"
            return "☾ Daemon (global)"
        return "● Daemon (global)"

    def _mk_multi_pause_dir(self, slot):
        """Create a pause_dir callback for a multi-daemon slot."""

        def pause_dir_fn(directory, minutes):
            if slot < len(self._tray._targets) and self._tray._multi_client:
                self._tray._multi_client.send_pause_dir(
                    self._tray._targets[slot],
                    directory,
                    minutes,
                )

        return pause_dir_fn

    def _mk_multi_resume_dir(self, slot):
        """Create a resume_dir callback for a multi-daemon slot."""

        def resume_dir_fn(directory):
            if slot < len(self._tray._targets) and self._tray._multi_client:
                self._tray._multi_client.send_resume_dir(
                    self._tray._targets[slot],
                    directory,
                )

        return resume_dir_fn

    def _build_dir_pause_items(self, get_stats_fn, pause_dir_fn, resume_dir_fn):
        """Build pre-allocated per-directory pause/resume menu items.

        Returns a list of pystray.MenuItem, one per slot, each with a
        submenu for duration options or resume. Uses visibility lambdas
        to show only slots with actual directories.
        """
        from ai_guardian.daemon.working_dir import shorten_path

        items = []
        for i in range(self._MAX_DIR_PAUSE_SLOTS):
            slot = i

            def _dir_at(s, stats, slot=slot):
                dirs = self._get_merged_dir_list(stats)
                if slot < len(dirs):
                    return dirs[slot]
                return None

            def _is_visible(_item, slot=slot):
                stats = get_stats_fn(_item)
                return _dir_at(None, stats, slot) is not None

            def _label(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                if d is None:
                    return ""
                paused_dirs = stats.get("paused_dirs") or {}
                short = shorten_path(d)
                if len(short) > 40:
                    short = "..." + short[-37:]
                if d in paused_dirs:
                    remaining = paused_dirs[d]
                    if remaining > 0 and self._tray._supports_live_pause_countdown():
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        return f"☾ {short} ({mins}m {secs}s)"
                    return f"☾ {short}"
                return f"● {short}"

            def _is_paused(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                if d is None:
                    return False
                return d in (stats.get("paused_dirs") or {})

            def _is_active(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                if d is None:
                    return False
                return d not in (stats.get("paused_dirs") or {})

            def _mk_dir_pause(minutes, slot=slot):
                def action(_, __):
                    stats = get_stats_fn(None)
                    d = _dir_at(None, stats, slot)
                    if d:
                        pause_dir_fn(d, minutes)

                return action

            def _mk_dir_resume(slot=slot):
                def action(_, __):
                    stats = get_stats_fn(None)
                    d = _dir_at(None, stats, slot)
                    if d:
                        resume_dir_fn(d)

                return action

            def _full_path_label(_item, slot=slot):
                stats = get_stats_fn(_item)
                d = _dir_at(None, stats, slot)
                return shorten_path(d) if d else ""

            items.append(
                pystray.MenuItem(
                    _label,
                    pystray.Menu(
                        pystray.MenuItem(
                            _full_path_label,
                            None,
                            enabled=False,
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            "5 minutes",
                            _mk_dir_pause(5),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "15 minutes",
                            _mk_dir_pause(15),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "30 minutes",
                            _mk_dir_pause(30),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "1 hour",
                            _mk_dir_pause(60),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "Until resume",
                            _mk_dir_pause(0),
                            visible=_is_active,
                        ),
                        pystray.MenuItem(
                            "Resume",
                            _mk_dir_resume(),
                            visible=_is_paused,
                        ),
                    ),
                    visible=_is_visible,
                )
            )
        return items

    def _version_annotated_label(self, target):
        """Format daemon label with version mismatch indicator if needed."""
        stats = self._tray._get_target_stats(target)
        active_dirs = stats.get("active_project_dirs") or []
        label = tray_menu.daemon_status_label(
            target,
            has_paused_dirs=bool(stats.get("paused_dirs")),
            active_project_dir=active_dirs[0] if active_dirs else None,
            project_count=len(active_dirs),
            forwarding_failed=target.name in self._tray._ask_forwarding_failed,
        )
        key = (target.name, target.runtime)
        if key in self._tray._health._version_mismatch_notified:
            daemon_ver = self._tray._health._daemon_versions.get(key, "")
            if daemon_ver:
                label += f" — v{daemon_ver} ⟳"
        return label

    def _working_dir_menu_label(self, slot):
        """Format the Working Dir menu item label for a daemon slot."""
        from ai_guardian.daemon.working_dir import shorten_path

        if slot < len(self._tray._targets):
            wd = getattr(self._tray._targets[slot], "working_dir", None)
            if wd:
                short = shorten_path(wd)
                if len(short) > 50:
                    short = short[:47] + "..."
                return f"Working Dir: {short}"
        return "Working Dir: ~"

    def _mk_change_working_dir(self, slot):
        """Create a click handler that opens a directory picker for a slot."""

        def action(icon, __):
            if slot >= len(self._tray._targets):
                return
            t = self._tray._targets[slot]
            current = getattr(t, "working_dir", None)
            threading.Thread(
                target=self._pick_working_dir,
                args=(t, current, self._capture_tray_screen_bounds(icon)),
                daemon=True,
                name="working-dir-picker",
            ).start()

        return action

    def _pick_working_dir(self, target, current, screen_bounds=None):
        """Run directory picker in background thread and persist result."""
        from ai_guardian.daemon.working_dir import choose_directory, set_working_dir

        chosen = choose_directory(
            current,
            **self._screen_bounds_kwargs(screen_bounds),
        )
        if chosen:
            target.working_dir = chosen
            set_working_dir(target.name, chosen)
            self._tray._refresh_event.set()

    def _mk_cursor_cloud_setup_action(self):
        """Create a handler that selects a workspace for Cursor Cloud setup."""

        def action(icon, __):
            current = None
            if self._tray._targets:
                current = getattr(self._tray._targets[0], "working_dir", None)
            threading.Thread(
                target=self._pick_cursor_cloud_project,
                args=(current, self._capture_tray_screen_bounds(icon)),
                daemon=True,
                name="cursor-cloud-project-picker",
            ).start()

        return action

    def _pick_cursor_cloud_project(self, current=None, screen_bounds=None):
        """Select a workspace, then launch explicit Cursor project setup."""
        from ai_guardian.daemon.working_dir import choose_directory

        chosen = choose_directory(
            current,
            title="Choose Cursor Cloud project directory",
            **self._screen_bounds_kwargs(screen_bounds),
        )
        if chosen:
            tray_menu.launch_ide_setup("cursor", scope="project", project_dir=chosen)

    def _apply_working_dirs(self):
        """Populate target.working_dir from persisted state after discovery."""
        from ai_guardian.daemon.working_dir import get_working_dir

        for t in self._tray._targets:
            if not getattr(t, "working_dir", None):
                t.working_dir = get_working_dir(t.name)

    @staticmethod
    def _sandbox_runtime(target):
        """Return the logical sandbox runtime for a discovered target."""
        return getattr(target, "runtime_type", None) or getattr(target, "runtime", None)

    def _sandbox_target_at(self, slot):
        """Return a target slot when it represents a supported sandbox."""
        if slot >= len(self._tray._targets):
            return None
        target = self._tray._targets[slot]
        if self._sandbox_runtime(target) not in {"container", "openshell"}:
            return None
        return target

    def _sandbox_is_openshell(self, slot):
        """Return whether a target slot represents an OpenShell sandbox."""
        target = self._sandbox_target_at(slot)
        return bool(target and self._sandbox_runtime(target) == "openshell")

    def _sandbox_is_running(self, slot):
        """Return whether a sandbox target can accept an interactive session."""
        target = self._sandbox_target_at(slot)
        return bool(target and target.status in ("running", "paused"))

    def _mk_sandbox_connect_action(self, slot):
        """Create the canonical sandbox connect action for a target slot."""
        return self._mk_sandbox_command_action(
            slot,
            "connect",
            lambda target: [target.name],
        )

    def _start_sandbox_form(
        self, title, message, fields, callback, *, name="sandbox-form", icon=None
    ):
        """Show a sandbox form away from the tray callback thread."""
        screen_bounds = self._capture_sandbox_screen_bounds(icon)

        def run_form():
            try:
                from ai_guardian.tray.sandbox_dialog import show_sandbox_form

                if screen_bounds is None:
                    values = show_sandbox_form(title, message, fields)
                else:
                    values = show_sandbox_form(
                        title,
                        message,
                        fields,
                        screen_bounds=screen_bounds,
                    )
                if values is not None:
                    callback(values, screen_bounds=screen_bounds)
            except Exception:
                logger.exception("Sandbox form action failed")

        threading.Thread(target=run_form, daemon=True, name=name).start()

    @staticmethod
    def _capture_tray_screen_bounds(icon=None):
        """Capture the display containing the tray menu before worker dispatch."""
        from ai_guardian.tray.dialog_placement import _get_tray_screen_bounds

        return _get_tray_screen_bounds(icon)

    @staticmethod
    def _capture_sandbox_screen_bounds(icon=None):
        """Backward-compatible alias for sandbox display capture tests."""
        return TrayMenuBuilder._capture_tray_screen_bounds(icon)

    @staticmethod
    def _screen_bounds_kwargs(screen_bounds):
        """Build optional dialog placement kwargs without changing fallbacks."""
        return {"screen_bounds": screen_bounds} if screen_bounds is not None else {}

    @staticmethod
    def _sandbox_error(title, message, *, screen_bounds=None):
        """Show a best-effort error for invalid tray form input."""
        from ai_guardian.tray.plugins import show_dialog

        show_dialog(
            title, message, **TrayMenuBuilder._screen_bounds_kwargs(screen_bounds)
        )

    def _mk_sandbox_create_action(self):
        """Create the main-menu callback for sandbox creation."""

        def action(icon, __):
            self._start_sandbox_form(
                "Create AI Guardian sandbox",
                "Choose the sandbox runtime and initial configuration. Creation "
                "runs in the background; failures show the captured runtime log.",
                # The complete form is built in one place so its defaults stay
                # aligned with the current environment at click time.
                self._sandbox_create_fields(),
                self._complete_sandbox_create_form,
                name="sandbox-create-form",
                icon=icon,
            )

        return action

    def _sandbox_create_fields(self):
        """Return the create form fields used by the main tray menu."""
        runtime = os.environ.get("AI_GUARDIAN_SANDBOX_RUNTIME", "openshell")
        if runtime not in {"container", "openshell"}:
            runtime = "openshell"
        cli_choices = SUPPORTED_CLI_IDE_TYPES
        default_cli = "claude" if runtime == "openshell" else "codex"
        cli = os.environ.get("AI_GUARDIAN_CLI", default_cli)
        if cli not in cli_choices:
            cli = default_cli
        opencode_agent = os.environ.get("AI_GUARDIAN_OPENCODE_AGENT", "")
        repo_default = os.environ.get("AI_GUARDIAN_SANDBOX_REPO")
        if not repo_default:
            target = getattr(self._tray, "_active_target", None)
            if target is None and len(self._tray._targets) == 1:
                target = self._tray._targets[0]
            repo_default = getattr(target, "working_dir", None)
        if not repo_default:
            repo_default = os.path.expanduser("~")
        profile_choices = ("", "@minimal", "@standard", "@strict", "@moderator")
        opencode_agent_choices = ("", "build", "plan", "claude")
        name_suffix = secrets.token_hex(3)
        return [
            {
                "name": "runtime",
                "label": "Runtime",
                "type": "choice",
                "choices": ("container", "openshell"),
                "default": runtime,
                "required": True,
                "help": "Use Docker/Podman or NVIDIA OpenShell.",
            },
            {
                "name": "cli",
                "label": "CLI",
                "type": "choice",
                "choices": cli_choices,
                "default": cli,
                "required": True,
                "help": "Select the CLI to configure in the sandbox.",
            },
            {
                "name": "name",
                "label": "Sandbox name",
                "default": f"ag-{cli[:8]}-{name_suffix}",
                "dynamic_default": {
                    "field": "cli",
                    "prefix": "ag-",
                    "value_max_length": 8,
                    "suffix": name_suffix,
                },
                "required": True,
            },
            {
                "name": "agent",
                "label": "OpenCode agent",
                "type": "choice",
                "choices": opencode_agent_choices,
                "editable": True,
                "default": opencode_agent,
                "required": True,
                "help": (
                    "Required when CLI is opencode; choose a common profile or "
                    "type a custom name. Passed as opencode --agent NAME."
                ),
                "enabled_when": {"field": "cli", "values": ("opencode",)},
            },
            {
                "name": "repo",
                "label": "Repository",
                "type": "directory",
                "default": repo_default,
            },
            {
                "name": "config_dir",
                "label": "Host config directory",
                "type": "directory",
                "default": "",
                "help": "Optional directory containing the initial ai-guardian.json.",
            },
            {
                "name": "image",
                "label": "Image / base",
                "type": "image",
                "default": "",
                "help": (
                    "Leave empty to use the runtime default. Browse lists local "
                    "AI Guardian images; local tags use registry/name:tag, "
                    "for example localhost/ai-guardian-openshell:dev."
                ),
            },
            {
                "name": "model",
                "label": "Inference model",
                "default": os.environ.get("AI_GUARDIAN_OPEN_SHELL_MODEL", ""),
                "help": "OpenShell Vertex AI model; empty uses the default.",
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
            },
            {
                "name": "profile",
                "label": "Profile",
                "type": "choice",
                "choices": profile_choices,
                "editable": True,
                "default": "",
                "help": (
                    "Optional profile; choose a built-in or type a custom "
                    "profile name/path."
                ),
            },
            {
                "name": "policies",
                "label": "Policy files",
                "type": "file",
                "multiple": True,
                "default": "",
                "help": (
                    "OpenShell policy files or fragments; separate paths with "
                    "commas or newlines."
                ),
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
            },
            {
                "name": "providers",
                "label": "OpenShell providers",
                "default": "",
                "help": "OpenShell provider names; separate names with commas or newlines.",
                "enabled_when": {"field": "runtime", "values": ("openshell",)},
            },
            {
                "name": "environment",
                "label": "Environment",
                "default": "",
                "help": "KEY=VALUE entries; separate values with commas or newlines.",
            },
            {
                "name": "labels",
                "label": "Runtime labels",
                "default": "",
                "help": "Runtime KEY=VALUE labels; separate values with commas or newlines.",
            },
            {
                "name": "config_source",
                "label": "Initial config",
                "type": "choice",
                "choices": ("Host/default", "Latest saved snapshot"),
                "default": "Host/default",
            },
            {
                "name": "port",
                "label": "Host port",
                "default": "",
                "help": (
                    "Container host port 1-65535; empty means runtime-selected. "
                    "OpenShell uses the gateway-selected service port."
                ),
                "enabled_when": {"field": "runtime", "values": ("container",)},
            },
        ]

    def _complete_sandbox_create_form(self, values, *, screen_bounds=None):
        """Validate create form values and launch the selected command."""
        runtime = values.get("runtime")
        name = str(values.get("name") or "").strip()
        profile = str(values.get("profile") or "").strip()
        restore = values.get("config_source") == "Latest saved snapshot"
        if restore and profile:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "A saved configuration snapshot cannot be combined with a profile.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return
        if runtime not in {"container", "openshell"} or not name:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "A valid runtime and sandbox name are required.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return

        opencode_agent = str(values.get("agent") or "").strip() or None
        cli_value = str(values.get("cli") or "").strip() or None
        cli = cli_value or ("claude" if runtime == "openshell" else "codex")
        agent_profile = opencode_agent if cli == "opencode" else None
        if cli == "opencode" and not agent_profile:
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "An OpenCode agent profile is required when CLI is opencode.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return
        repo = str(values.get("repo") or "").strip() or None
        config_dir = str(values.get("config_dir") or "").strip() or None
        image = str(values.get("image") or "").strip() or None
        model = str(values.get("model") or "").strip() or None
        profile_value = profile or None
        if config_dir and (restore or profile):
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "The host config directory cannot be combined with a profile or saved snapshot.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return
        policies = str(values.get("policies") or "").strip()
        if policies and runtime != "openshell":
            self._sandbox_error(
                "Create AI Guardian sandbox",
                "Policy files are supported for OpenShell sandboxes only.",
                **self._screen_bounds_kwargs(screen_bounds),
            )
            return
        policy_paths = []
        for policy in policies.replace("\n", ",").split(","):
            policy = policy.strip()
            if policy:
                policy_paths.append(policy)
        providers = str(values.get("providers") or "").strip()
        provider_names = []
        for provider in providers.replace("\n", ",").split(","):
            provider = provider.strip()
            if provider:
                provider_names.append(provider)
        environment_values = []
        environment = str(values.get("environment") or "").strip()
        for entry in environment.replace("\n", ",").split(","):
            entry = entry.strip()
            if entry:
                environment_values.append(entry)
        labels = str(values.get("labels") or "").strip()
        label_values = []
        for label in labels.replace("\n", ",").split(","):
            label = label.strip()
            if label:
                if "=" not in label or not label.split("=", 1)[0].strip():
                    self._sandbox_error(
                        "Create AI Guardian sandbox",
                        "Labels must use KEY=VALUE entries separated by commas.",
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
                    return
                label_values.append(label)
        port = str(values.get("port") or "").strip()
        port_value = None
        if port:
            if runtime != "container":
                self._sandbox_error(
                    "Create AI Guardian sandbox",
                    "Host port is supported for container sandboxes only.",
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                return
            try:
                if not 1 <= int(port) <= 65535:
                    raise ValueError
            except ValueError:
                self._sandbox_error(
                    "Create AI Guardian sandbox",
                    "Host port must be an integer between 1 and 65535.",
                    **self._screen_bounds_kwargs(screen_bounds),
                )
                return
            port_value = int(port)

        self._run_sandbox_create(
            SimpleNamespace(
                sandbox_command="create",
                runtime=runtime,
                container_engine=None,
                openshell_cli=None,
                name=name,
                cli=cli,
                opencode_agent=agent_profile,
                profile=profile_value,
                restore_config="latest" if restore else None,
                config_dir=config_dir,
                repo=repo,
                port=port_value,
                image=image,
                model=model,
                api_key=None,
                environment=environment_values,
                policy=policy_paths,
                provider=provider_names,
                label=label_values,
                command_args=[],
            ),
            **self._screen_bounds_kwargs(screen_bounds),
        )

    def _run_sandbox_create(self, args, *, screen_bounds=None):
        """Create a sandbox in-process and report failures in a log dialog."""
        output = []
        try:
            from ai_guardian.sandbox import create_sandbox

            result = create_sandbox(args, interactive=False, output=output)
        except Exception as exc:
            logger.exception("Tray sandbox creation failed")
            output.append(f"Error: {exc}\n")
            result = 1

        if result != 0:
            try:
                from ai_guardian.tray.sandbox_dialog import show_sandbox_log

                log_text = "".join(output).strip()
                if not log_text:
                    log_text = f"Sandbox creation failed with exit code {result}."
                show_sandbox_log(
                    "Sandbox creation failed",
                    f"Unable to create sandbox '{args.name}'.",
                    log_text,
                    **self._screen_bounds_kwargs(screen_bounds),
                )
            except Exception:
                logger.exception("Unable to show sandbox creation log")
            return

        tray_notifications.show_notification(
            "AI Guardian",
            f"Sandbox created: {args.name}",
        )
        if self._tray._discovery:
            self._tray._discovery.request_refresh(wait=False)

    @staticmethod
    def _sandbox_operation_parts(operation):
        """Normalize a lifecycle operation and an optional config verb."""
        if isinstance(operation, (tuple, list)):
            return [str(part) for part in operation]
        return [str(operation)]

    def _sandbox_command_args(self, target, operation, command_args):
        """Build the argparse-compatible namespace used by sandbox helpers."""
        parts = self._sandbox_operation_parts(operation)
        runtime = self._sandbox_runtime(target)
        if runtime not in {"container", "openshell"} or not target.name:
            return None

        values = [str(value) for value in (command_args or ())]
        snapshot = "latest"
        if "--snapshot" in values:
            snapshot_index = values.index("--snapshot") + 1
            if snapshot_index < len(values):
                snapshot = values[snapshot_index]

        option_values = {}
        for option in ("tail", "source", "level", "since"):
            option_name = f"--{option}"
            if option_name in values:
                option_index = values.index(option_name) + 1
                if option_index < len(values):
                    option_values[option] = values[option_index]

        return SimpleNamespace(
            sandbox_command=parts[0],
            sandbox_config_command=parts[1] if len(parts) > 1 else None,
            runtime=runtime,
            container_engine=getattr(target, "container_engine", None),
            container_name=getattr(target, "container_name", None),
            openshell_cli=None,
            name=target.name,
            container_id=getattr(target, "container_id", None),
            snapshot=snapshot,
            json_output=False,
            command_args=[],
            follow="--follow" in values,
            tail=option_values.get("tail"),
            source=option_values.get("source"),
            level=option_values.get("level"),
            since=option_values.get("since"),
        )

    def _run_sandbox_command(
        self, target, operation, command_args=None, *, screen_bounds=None
    ):
        """Run a non-interactive sandbox action and show useful output."""
        output = []
        parts = self._sandbox_operation_parts(operation)
        args = self._sandbox_command_args(target, operation, command_args)
        if args is None:
            return

        try:
            from ai_guardian.sandbox import run_sandbox_command

            result = run_sandbox_command(args, output=output)
        except Exception as exc:
            logger.exception("Tray sandbox command failed")
            output.append(f"Error: {exc}\n")
            result = 1

        log_text = "".join(output).strip()
        show_log = result != 0 or parts[0] in {"status", "logs", "config"}
        if show_log:
            try:
                from ai_guardian.tray.sandbox_dialog import show_sandbox_log

                if not log_text:
                    log_text = f"Sandbox command exited with code {result}."
                if result == 0:
                    title = f"Sandbox {parts[0]}"
                    message = f"Output from sandbox '{target.name}'."
                else:
                    title = "Sandbox command failed"
                    message = (
                        f"Unable to run {' '.join(parts)} for sandbox "
                        f"'{target.name}'."
                    )
                show_sandbox_log(
                    title,
                    message,
                    log_text,
                    **self._screen_bounds_kwargs(screen_bounds),
                )
            except Exception:
                logger.exception("Unable to show sandbox command log")
        else:
            tray_notifications.show_notification(
                "AI Guardian",
                f"Sandbox {parts[0]}: {target.name}",
            )

        if result == 0 and self._tray._discovery:
            self._tray._discovery.request_refresh(wait=False)

    def _start_sandbox_command(
        self, target, operation, command_args=None, *, screen_bounds=None
    ):
        """Run a non-interactive sandbox action away from the tray callback."""
        thread_options = {}
        if screen_bounds is not None:
            thread_options["kwargs"] = {"screen_bounds": screen_bounds}
        thread = threading.Thread(
            target=self._run_sandbox_command,
            args=(target, operation, command_args),
            daemon=True,
            name="sandbox-command",
            **thread_options,
        )
        thread.start()
        return thread

    def _mk_sandbox_command_action(
        self, slot, operation, arguments=None, *, keep_open=True
    ):
        """Create a menu callback for a command using the selected target."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            command_args = arguments(target) if callable(arguments) else arguments
            parts = self._sandbox_operation_parts(operation)
            if parts[0] in {"connect", "exec"}:
                tray_menu.launch_sandbox_command(
                    target,
                    operation,
                    command_args or (),
                    keep_open=keep_open,
                )
            else:
                self._start_sandbox_command(
                    target,
                    operation,
                    command_args,
                    **self._screen_bounds_kwargs(screen_bounds),
                )

        return action

    def _mk_sandbox_exec_action(self, slot):
        """Create a callback that prompts for an exec command."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def complete(values, *, screen_bounds=None):
                command = str(values.get("command") or "").strip()
                try:
                    command_args = shlex.split(command) if command else []
                except ValueError as exc:
                    self._sandbox_error(
                        "Sandbox exec",
                        f"Invalid command: {exc}",
                        **self._screen_bounds_kwargs(screen_bounds),
                    )
                    return
                args = [target.name]
                if command_args:
                    args.extend(["--", *command_args])
                tray_menu.launch_sandbox_command(target, "exec", args, keep_open=True)

            self._start_sandbox_form(
                "Execute in sandbox",
                "Enter a command to run inside the sandbox.",
                [
                    {
                        "name": "command",
                        "label": "Command",
                        "default": "/bin/bash -l",
                        "help": "Leave empty to use the sandbox login shell.",
                    }
                ],
                complete,
                name="sandbox-exec-form",
                icon=icon,
            )

        return action

    def _mk_sandbox_logs_action(self, slot):
        """Create a callback that prompts for optional log filters."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def complete(values, *, screen_bounds=None):
                args = [target.name]
                if values.get("follow"):
                    args.append("--follow")
                for option in ("tail", "source", "level", "since"):
                    value = str(values.get(option) or "").strip()
                    if value:
                        args.extend([f"--{option}", value])
                if values.get("follow"):
                    tray_menu.launch_sandbox_command(
                        target, "logs", args, keep_open=True
                    )
                else:
                    self._start_sandbox_command(
                        target,
                        "logs",
                        args,
                        **self._screen_bounds_kwargs(screen_bounds),
                    )

            self._start_sandbox_form(
                "Sandbox logs",
                "Choose optional filters. Followed output opens in a terminal; "
                "one-shot output opens in a log window.",
                [
                    {
                        "name": "follow",
                        "label": "Follow output",
                        "type": "bool",
                        "default": False,
                    },
                    {"name": "tail", "label": "Tail lines", "default": ""},
                    {"name": "source", "label": "OpenShell source", "default": ""},
                    {"name": "level", "label": "OpenShell level", "default": ""},
                    {"name": "since", "label": "OpenShell since", "default": ""},
                ],
                complete,
                name="sandbox-logs-form",
                icon=icon,
            )

        return action

    def _mk_sandbox_restore_action(self, slot):
        """Create a callback that prompts for a snapshot selector."""

        def action(icon, __):
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def complete(values, *, screen_bounds=None):
                snapshot = str(values.get("snapshot") or "latest").strip()
                self._start_sandbox_command(
                    target,
                    ("config", "restore"),
                    [target.name, "--snapshot", snapshot],
                    **self._screen_bounds_kwargs(screen_bounds),
                )

            self._start_sandbox_form(
                "Restore sandbox configuration",
                "Enter latest or a timestamp from the saved snapshot list.",
                [
                    {
                        "name": "snapshot",
                        "label": "Snapshot",
                        "default": "latest",
                        "required": True,
                    }
                ],
                complete,
                name="sandbox-config-restore-form",
                icon=icon,
            )

        return action

    def _mk_sandbox_delete_action(self, slot):
        """Create a delete action protected by an isolated confirmation."""

        def action(icon, __):
            # Capture the click display before any worker dispatch. This is
            # especially important for the nested OpenShell management menu,
            # whose AppKit menu window may no longer be current by the time
            # the confirmation subprocess is started.
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            target = self._sandbox_target_at(slot)
            if target is None:
                return

            def confirm_and_delete():
                try:
                    from ai_guardian.tray.sandbox_dialog import (
                        show_sandbox_confirmation,
                    )

                    runtime = self._sandbox_runtime(target) or "unknown"
                    if show_sandbox_confirmation(
                        target.name,
                        runtime,
                        **self._screen_bounds_kwargs(screen_bounds),
                    ):
                        self._start_sandbox_command(
                            target,
                            "delete",
                            [target.name],
                            **self._screen_bounds_kwargs(screen_bounds),
                        )
                except Exception:
                    logger.exception("Sandbox delete confirmation failed")

            threading.Thread(
                target=confirm_and_delete,
                daemon=True,
                name="sandbox-delete-confirmation",
            ).start()

        return action

    def _build_sandbox_manage_menu_item(self, slot):
        """Build the per-target sandbox management submenu."""

        def visible(_item, slot=slot):
            return self._sandbox_target_at(slot) is not None

        def target_running(_item, slot=slot):
            target = self._sandbox_target_at(slot)
            return bool(target and target.status in ("running", "paused"))

        def target_not_running(_item, slot=slot):
            target = self._sandbox_target_at(slot)
            return bool(target and target.status not in ("running", "paused"))

        target_name = lambda target: [target.name]
        config_menu = pystray.Menu(
            pystray.MenuItem(
                "Save",
                self._mk_sandbox_command_action(slot, ("config", "save"), target_name),
                enabled=target_running,
            ),
            pystray.MenuItem(
                "List",
                self._mk_sandbox_command_action(slot, ("config", "list"), target_name),
            ),
            pystray.MenuItem(
                "Restore...",
                self._mk_sandbox_restore_action(slot),
                enabled=target_running,
            ),
        )
        return pystray.MenuItem(
            "Manage sandbox",
            pystray.Menu(
                pystray.MenuItem(
                    "Status",
                    self._mk_sandbox_command_action(slot, "status", target_name),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Start",
                    self._mk_sandbox_command_action(slot, "start", target_name),
                    enabled=target_not_running,
                    visible=lambda _item, slot=slot: (
                        self._sandbox_runtime(self._sandbox_target_at(slot))
                        == "openshell"
                    ),
                ),
                pystray.MenuItem(
                    "Stop",
                    self._mk_sandbox_command_action(slot, "stop", target_name),
                    enabled=target_running,
                ),
                pystray.MenuItem(
                    "Restart",
                    self._mk_sandbox_command_action(slot, "restart", target_name),
                ),
                pystray.MenuItem(
                    "Connect",
                    self._mk_sandbox_connect_action(slot),
                    enabled=target_running,
                    visible=lambda _item, slot=slot: not self._sandbox_is_openshell(
                        slot
                    ),
                ),
                pystray.MenuItem(
                    "Exec...",
                    self._mk_sandbox_exec_action(slot),
                    enabled=target_running,
                ),
                pystray.MenuItem(
                    "Logs...",
                    self._mk_sandbox_logs_action(slot),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Config", config_menu),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Delete...",
                    self._mk_sandbox_delete_action(slot),
                ),
            ),
            visible=visible,
        )

    def _build_sandbox_create_menu_items(self):
        """Build the always-available main-menu sandbox create action."""
        return [
            pystray.MenuItem(
                "Create sandbox...",
                self._mk_sandbox_create_action(),
            )
        ]

    def _stopped_container_targets(self):
        """Return stopped container-engine sandboxes for the start menu."""
        return tuple(
            sorted(
                (
                    target
                    for target in getattr(self._tray, "_stopped_container_targets", ())
                    if self._sandbox_runtime(target) in {"container", "openshell"}
                ),
                key=lambda target: target.name.casefold(),
            )
        )

    def _mk_sandbox_start_container_action(self, target):
        """Create the main-menu action for one stopped container."""

        def action(icon, __):
            screen_bounds = self._capture_sandbox_screen_bounds(icon)
            self._start_sandbox_command(
                target,
                "start",
                [target.name],
                **self._screen_bounds_kwargs(screen_bounds),
            )

        return action

    def _build_sandbox_start_menu_items(self):
        """Build the main-menu submenu for stopped container-engine sandboxes."""
        targets = self._stopped_container_targets()
        items = [
            pystray.MenuItem(
                f"{target.name} ({self._sandbox_runtime(target)})",
                self._mk_sandbox_start_container_action(target),
            )
            for target in targets
        ]
        if not items:
            items = [
                pystray.MenuItem(
                    "No stopped containers",
                    None,
                    enabled=False,
                )
            ]

        return [
            pystray.MenuItem(
                "Start stopped sandbox...",
                pystray.Menu(*items),
                visible=lambda _item: bool(self._stopped_container_targets()),
            )
        ]

    def _build_single_daemon_menu_items(self):
        """Build flat menu items for single-daemon mode.

        When exactly one daemon is discovered, all submenu items are
        promoted to the top level. Visible only when len(targets) == 1.
        """

        def _single_vis(_item):
            return self._tray._is_single_daemon()

        def _single_vis_refresh(_item):
            return self._tray._is_single_daemon()

        def _single_running(_item):
            if not self._tray._is_single_daemon():
                return False
            if self._tray._targets[0].status in ("running", "paused"):
                return True
            return self._tray._can_autostart_daemon()

        def _single_not_running(_item):
            return self._tray._is_single_daemon() and self._tray._targets[
                0
            ].status not in (
                "running",
                "paused",
            )

        def _header_label(_item):
            if not self._tray._targets:
                return ""
            return self._version_annotated_label(self._tray._targets[0])

        def _open_panel(panel=None):
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if (
                    self._tray._has_web_console
                    and self._tray._ensure_web_console_ready()
                ):
                    web_page = (
                        tray_menu.PANEL_TO_WEB_PATH.get(panel, "") if panel else ""
                    )
                    daemon_name = (
                        self._tray._targets[0].name if self._tray._targets else ""
                    )
                    tray_menu.open_web_console(daemon_name, web_page)
                    return
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.open_console(t, panel)
                    else:
                        tray_menu.launch_console(panel)

            return action

        def _open_shell():
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.open_shell(t)
                    else:
                        tray_menu.launch_shell(
                            cwd=getattr(t, "working_dir", None),
                        )

            return action

        if self._sandbox_is_openshell(0):
            shell_item = pystray.MenuItem(
                "Connect",
                self._mk_sandbox_connect_action(0),
                visible=_single_vis,
                enabled=lambda _item: self._sandbox_is_running(0),
            )
        else:
            shell_item = pystray.MenuItem(
                "Terminal",
                _open_shell(),
                visible=_single_vis,
            )

        def _open_doctor():
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.open_doctor(t)
                    else:
                        tray_menu.launch_doctor()

            return action

        def _pause_action(minutes):
            def action(_, __):
                self._tray._check_and_autostart_daemon()
                if self._tray._targets:
                    t = self._tray._targets[0]
                    if self._tray._multi_client:
                        self._tray._multi_client.send_pause(t, minutes)
                    else:
                        self._tray._pause(minutes)
                    self._tray.update_status("paused")

            return action

        def _resume_action(_, __):
            self._tray._check_and_autostart_daemon()
            if self._tray._targets:
                t = self._tray._targets[0]
                if self._tray._multi_client:
                    self._tray._multi_client.send_resume(t)
                else:
                    self._tray._pause(0)
                self._tray.update_status("running")

        def _stop_action(_, __):
            if self._tray._targets and self._tray._multi_client:
                self._tray._multi_client.send_stop(self._tray._targets[0])

        def _restart_action(_, __):
            if self._tray._health._restart_in_progress:
                return
            if not (self._tray._targets and self._tray._multi_client):
                return
            self._tray._health._restart_in_progress = True
            self._tray._dispatch_to_main(self._tray._refresh_menu)
            self._tray._multi_client.send_restart(self._tray._targets[0])

            def _poll():
                import json as _json

                from ai_guardian.daemon import get_pid_path

                pid_path = get_pid_path()
                old_pid = None
                try:
                    if pid_path.exists():
                        old_pid = _json.loads(pid_path.read_text()).get("pid")
                except Exception:
                    pass
                for _ in range(100):
                    time.sleep(0.1)
                    try:
                        if pid_path.exists():
                            new_pid = _json.loads(pid_path.read_text()).get("pid")
                            if new_pid and new_pid != old_pid:
                                break
                    except Exception:
                        pass
                self._tray._health._restart_in_progress = False
                self._tray._refresh_event.set()

            threading.Thread(target=_poll, daemon=True, name="restart-poll").start()

        _cache = {"stats": {}, "time": 0}

        def _get_stats(_item):
            import time as time_mod

            now = time_mod.monotonic()
            if now - _cache["time"] < 2.0:
                return _cache["stats"]
            if not self._tray._targets:
                return {}
            target = self._tray._targets[0]
            if self._tray._multi_client and target.runtime != "local":
                result = self._tray._multi_client.get_status(target)
                if result and should_update_target_name(target, result.get("name")):
                    target.name = result["name"]
                _cache["stats"] = result or {}
            else:
                _cache["stats"] = self._tray._get_stats()
            stats = _cache["stats"]
            if stats:
                key = (target.name, target.runtime)
                if "mcp_installed" in stats:
                    self._tray._mcp_installed_per_daemon[key] = stats["mcp_installed"]
                if "version" in stats:
                    self._tray._health._daemon_versions[key] = stats["version"]
            _cache["time"] = now
            return stats

        def _s_requests(_item):
            s = _get_stats(_item)
            return f"Requests: {s.get('request_count', 0):,}"

        def _s_blocked(_item):
            s = _get_stats(_item)
            b = s.get("blocked_count", 0)
            t = s.get("request_count", 0)
            if t > 0:
                return f"Blocked: {b:,} ({b/t*100:.1f}%)"
            return f"Blocked: {b:,}"

        def _s_warned(_item):
            s = _get_stats(_item)
            return f"Warned: {s.get('warning_count', 0):,}"

        def _s_logged(_item):
            s = _get_stats(_item)
            return f"Logged: {s.get('log_only_count', 0):,}"

        def _s_violations(_item):
            s = _get_stats(_item)
            return f"Violations: {s.get('violation_count', 0):,}"

        def _s_critical(_item):
            s = _get_stats(_item)
            return f"  Critical: {s.get('critical_count', 0):,}"

        def _s_warning_sev(_item):
            s = _get_stats(_item)
            return f"  Warning: {s.get('warning_severity_count', 0):,}"

        def _s_last_block(_item):
            s = _get_stats(_item)
            bt = s.get("last_block_type")
            ba = s.get("last_block_seconds_ago")
            if bt is None:
                return "Last block: none"
            return f"Last block: {bt} {tray_notifications.format_time_ago(ba)}"

        def _s_ask_dialogs(_item):
            s = _get_stats(_item)
            count = s.get("ask_dialog_count", 0)
            total_ms = s.get("ask_dialog_total_ms", 0)
            if total_ms >= 1000:
                return f"Ask dialogs: {count:,} (wait: {total_ms / 1000:.1f}s)"
            return f"Ask dialogs: {count:,} (wait: {total_ms:.0f}ms)"

        def _s_ask_dialogs_visible(_item):
            s = _get_stats(_item)
            return s.get("ask_dialog_count", 0) > 0

        def _s_config_reload(_item):
            s = _get_stats(_item)
            ago = s.get("last_config_reload_seconds_ago")
            if ago is not None:
                return f"Config reloaded: {tray_notifications.format_time_ago(ago)}"
            return "Config: loaded"

        self._single_daemon_closures = {
            "pause_action": _pause_action,
            "resume_action": _resume_action,
            "stop_action": _stop_action,
            "restart_action": _restart_action,
            "single_running": _single_running,
            "single_not_running": _single_not_running,
            "get_stats": _get_stats,
        }

        def _stale_vis(_item):
            if not self._tray._is_single_daemon() or not self._tray._targets:
                return False
            return (
                self._tray._targets[0].runtime == "local"
                and self._tray._health._stale_code_warned
                and not self._tray._health._restart_in_progress
            )

        def _stale_vis_remote(_item):
            if not self._tray._is_single_daemon() or not self._tray._targets:
                return False
            t = self._tray._targets[0]
            return t.runtime in (
                "container",
                "kubernetes",
            ) and self._tray._health._is_target_stale(t)

        def _stale_remote_label(_item):
            from ai_guardian import __version__ as _hv

            if self._tray._targets:
                t = self._tray._targets[0]
                daemon_ver = self._tray._health._daemon_versions.get(
                    (t.name, t.runtime), ""
                )
                if daemon_ver:
                    return f"⚠️ Host v{_hv} newer than container v{daemon_ver} — rebuild image"
            return "⚠️ Container daemon outdated — rebuild image to update"

        def _on_restart_daemon(_icon, _item):
            if self._tray._health._restart_in_progress:
                return
            self._tray._health._restart_in_progress = True
            self._tray._dispatch_to_main(self._tray._refresh_menu)

            import json as _json

            from ai_guardian.daemon import get_pid_path

            pid_path = get_pid_path()
            old_pid = None
            try:
                if pid_path.exists():
                    old_pid = _json.loads(pid_path.read_text()).get("pid")
            except Exception:
                pass

            cmd = tray_plugins.resolve_cli_cmd("daemon", "restart")
            import subprocess as _sp

            try:
                _sp.Popen(
                    cmd,
                    stdin=_sp.DEVNULL,
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    start_new_session=True,
                )
            except OSError as e:
                logger.error("Failed to restart daemon: %s", e)
                self._tray._health._restart_in_progress = False
                self._tray._dispatch_to_main(self._tray._refresh_menu)
                return

            def _poll_for_new_daemon():
                for _ in range(100):
                    time.sleep(0.1)
                    try:
                        if pid_path.exists():
                            new_pid = _json.loads(pid_path.read_text()).get("pid")
                            if new_pid and new_pid != old_pid:
                                break
                    except Exception:
                        pass

                self._tray._health._restart_in_progress = False
                self._tray._refresh_event.set()

            threading.Thread(
                target=_poll_for_new_daemon, daemon=True, name="restart-poll"
            ).start()

        return [
            pystray.MenuItem(
                "⚠️ Daemon running old code — click to restart",
                _on_restart_daemon,
                visible=_stale_vis,
            ),
            pystray.MenuItem(
                _stale_remote_label,
                None,
                visible=_stale_vis_remote,
                enabled=False,
            ),
            pystray.MenuItem(_header_label, None, visible=_single_vis_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Console",
                _open_panel(None),  # None means main console page
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.MenuItem(
                "Violations",
                _open_panel("panel-violations"),
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.MenuItem(
                "Metrics & Audit",
                _open_panel("panel-metrics"),
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.MenuItem(
                "Statistics",
                pystray.Menu(
                    pystray.MenuItem(_s_requests, None),
                    pystray.MenuItem(_s_blocked, None),
                    pystray.MenuItem(_s_warned, None),
                    pystray.MenuItem(_s_logged, None),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(_s_violations, None),
                    pystray.MenuItem(_s_critical, None),
                    pystray.MenuItem(_s_warning_sev, None),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(_s_last_block, None),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        _s_ask_dialogs, None, visible=_s_ask_dialogs_visible
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(_s_config_reload, None),
                ),
                visible=_single_vis,
                enabled=_single_running,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: f"MCP Proactive: {self._tray._proactive_level}",
                pystray.Menu(
                    pystray.MenuItem(
                        "low",
                        lambda _, __: self._tray._on_change_proactive("low"),
                        checked=lambda _: self._tray._proactive_level == "low",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "medium",
                        lambda _, __: self._tray._on_change_proactive("medium"),
                        checked=lambda _: self._tray._proactive_level == "medium",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "high",
                        lambda _, __: self._tray._on_change_proactive("high"),
                        checked=lambda _: self._tray._proactive_level == "high",
                        radio=True,
                    ),
                ),
                visible=lambda _: _single_vis(_)
                and self._tray._is_mcp_for_current_target(),
                enabled=_single_running,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: self._working_dir_menu_label(0),
                self._mk_change_working_dir(0),
                visible=_single_vis,
            ),
            shell_item,
            self._build_sandbox_manage_menu_item(0),
        ]

    def _build_single_daemon_daemon_items(self):
        """Build daemon operation items for single-daemon mode.

        Pause/Resume and Start/Stop/Restart grouped together without
        internal separators. Separated from preceding items by a
        separator. Must be called after _build_single_daemon_menu_items().
        """
        c = self._single_daemon_closures
        _pause_action = c["pause_action"]
        _resume_action = c["resume_action"]
        _stop_action = c["stop_action"]
        _restart_action = c["restart_action"]
        _single_running = c["single_running"]
        _single_not_running = c["single_not_running"]
        _get_stats = c["get_stats"]

        def _global_pause_label(_item):
            stats = _get_stats(_item)
            if stats.get("paused"):
                remaining = stats.get("pause_remaining_seconds", 0)
                if remaining > 0 and self._tray._supports_live_pause_countdown():
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    return f"☾ Daemon (global) ({mins}m {secs}s)"
                return "☾ Daemon (global)"
            return "● Daemon (global)"

        def _global_is_paused(_item):
            return _get_stats(_item).get("paused", False)

        def _global_is_active(_item):
            return not _get_stats(_item).get("paused", False)

        def _pause_dir_action(directory, minutes):
            if self._tray._targets and self._tray._multi_client:
                self._tray._multi_client.send_pause_dir(
                    self._tray._targets[0],
                    directory,
                    minutes,
                )

        def _resume_dir_action(directory):
            if self._tray._targets and self._tray._multi_client:
                self._tray._multi_client.send_resume_dir(
                    self._tray._targets[0],
                    directory,
                )

        dir_pause_items = self._build_dir_pause_items(
            _get_stats,
            _pause_dir_action,
            _resume_dir_action,
        )

        def _has_dirs(_item):
            stats = _get_stats(_item)
            return bool(self._get_merged_dir_list(stats))

        return [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause...",
                pystray.Menu(
                    pystray.MenuItem(
                        _global_pause_label,
                        pystray.Menu(
                            pystray.MenuItem(
                                "5 minutes",
                                _pause_action(5),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "15 minutes",
                                _pause_action(15),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "30 minutes",
                                _pause_action(30),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "1 hour",
                                _pause_action(60),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "Until resume",
                                _pause_action(0),
                                visible=_global_is_active,
                            ),
                            pystray.MenuItem(
                                "Resume",
                                _resume_action,
                                visible=_global_is_paused,
                            ),
                        ),
                    ),
                    pystray.Menu.SEPARATOR,
                    *dir_pause_items,
                ),
                visible=_single_running,
            ),
            pystray.MenuItem(
                "Start daemon", _restart_action, visible=_single_not_running
            ),
            pystray.MenuItem(
                lambda _: self._tray._health._upgrade_label(
                    self._tray._targets[0] if self._tray._targets else None,
                ),
                self._tray._health._on_upgrade_single,
                visible=lambda _: (
                    self._tray._is_single_daemon()
                    and self._tray._targets
                    and self._tray._health._is_upgrade_available(self._tray._targets[0])
                ),
            ),
            pystray.MenuItem(
                lambda _: self._tray._health._self_upgrade_label(),
                self._tray._health._on_self_upgrade,
                visible=lambda _: self._tray._health._is_self_upgrade_available(),
            ),
        ]

    def _build_multi_daemon_menu_items(self):
        """Build per-daemon action submenus for every discovered daemon.

        Each daemon gets its own submenu with Console, Pause, Restart, etc.
        The tray rebuilds this part of the menu when discovery changes the
        number of targets, so there is no fixed daemon-count limit.

        Only visible when 2+ daemons are discovered.
        """
        items = []
        for i in range(len(self._tray._targets)):
            idx = i

            def make_label(_item, slot=idx):
                if slot >= len(self._tray._targets):
                    return ""
                return self._version_annotated_label(self._tray._targets[slot])

            def make_visible(_item, slot=idx):
                return self._tray._is_multi_daemon() and slot < len(self._tray._targets)

            def _mk_open_panel(panel=None, slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if (
                        panel
                        and self._tray._has_web_console
                        and self._tray._ensure_web_console_ready()
                    ):
                        web_page = tray_menu.PANEL_TO_WEB_PATH.get(panel, "")
                        daemon_name = (
                            self._tray._targets[slot].name
                            if slot < len(self._tray._targets)
                            else ""
                        )
                        tray_menu.open_web_console(daemon_name, web_page)
                        return
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_console(t, panel)
                        else:
                            tray_menu.launch_console(panel)

                return action

            def _mk_web_console_action(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if (
                        self._tray._has_web_console
                        and self._tray._ensure_web_console_ready()
                    ):
                        if slot < len(self._tray._targets):
                            tray_menu.open_web_console(self._tray._targets[slot].name)
                        return
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_console(t)
                        else:
                            tray_menu.launch_console()

                return action

            def _mk_web_console_visible(slot=idx):
                def check(_):
                    return self._tray._has_web_console and slot < len(
                        self._tray._targets
                    )

                return check

            def _mk_open_shell(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_shell(t)
                        else:
                            tray_menu.launch_shell(
                                cwd=getattr(t, "working_dir", None),
                            )

                return action

            if self._sandbox_is_openshell(idx):
                shell_item = pystray.MenuItem(
                    "Connect",
                    self._mk_sandbox_connect_action(idx),
                    enabled=lambda _item, slot=idx: self._sandbox_is_running(slot),
                )
            else:
                shell_item = pystray.MenuItem("Terminal", _mk_open_shell())

            def _mk_doctor(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.open_doctor(t)
                        else:
                            tray_menu.launch_doctor()

                return action

            def _mk_pause(minutes, slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.send_pause(t, minutes)
                        else:
                            self._tray._pause(minutes)
                        self._tray._update_global_pause_status()

                return action

            def _mk_resume(slot=idx):
                def action(_, __):
                    self._tray._check_and_autostart_daemon()
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.send_resume(t)
                        else:
                            self._tray._pause(0)
                        self._tray._update_global_pause_status()

                return action

            def _mk_stop(slot=idx):
                def action(_, __):
                    if slot < len(self._tray._targets):
                        t = self._tray._targets[slot]
                        if self._tray._multi_client:
                            self._tray._multi_client.send_stop(t)

                return action

            def _mk_restart(slot=idx):
                def action(_, __):
                    if self._tray._health._restart_in_progress:
                        return
                    if slot >= len(self._tray._targets):
                        return
                    t = self._tray._targets[slot]
                    if not self._tray._multi_client:
                        return
                    self._tray._health._restart_in_progress = True
                    self._tray._dispatch_to_main(self._tray._refresh_menu)
                    self._tray._multi_client.send_restart(t)

                    def _poll(target=t):
                        if target.runtime == "local":
                            import json as _json

                            from ai_guardian.daemon import get_pid_path

                            pid_path = get_pid_path()
                            old_pid = None
                            try:
                                if pid_path.exists():
                                    old_pid = _json.loads(pid_path.read_text()).get(
                                        "pid"
                                    )
                            except Exception:
                                pass
                            for _ in range(100):
                                time.sleep(0.1)
                                try:
                                    if pid_path.exists():
                                        new_pid = _json.loads(pid_path.read_text()).get(
                                            "pid"
                                        )
                                        if new_pid and new_pid != old_pid:
                                            break
                                except Exception:
                                    pass
                        else:
                            time.sleep(3.0)
                        self._tray._health._restart_in_progress = False
                        self._tray._refresh_event.set()

                    threading.Thread(
                        target=_poll, daemon=True, name="restart-poll"
                    ).start()

                return action

            def _mk_daemon_stale_vis(slot=idx):
                def check(_item):
                    if slot >= len(self._tray._targets):
                        return False
                    t = self._tray._targets[slot]
                    return (
                        t.runtime == "local"
                        and self._tray._health._is_target_stale(t)
                        and not self._tray._health._restart_in_progress
                    )

                return check

            def _mk_daemon_stale_vis_remote(slot=idx):
                def check(_item):
                    if slot >= len(self._tray._targets):
                        return False
                    t = self._tray._targets[slot]
                    return t.runtime in (
                        "container",
                        "kubernetes",
                    ) and self._tray._health._is_target_stale(t)

                return check

            def _mk_stale_remote_label(slot=idx):
                def label(_item):
                    from ai_guardian import __version__ as _hv

                    if slot >= len(self._tray._targets):
                        return "⚠️ Container daemon outdated — rebuild image"
                    t = self._tray._targets[slot]
                    daemon_ver = self._tray._health._daemon_versions.get(
                        (t.name, t.runtime), ""
                    )
                    if daemon_ver:
                        return f"⚠️ Host v{_hv} newer than container v{daemon_ver} — rebuild image"
                    return "⚠️ Container daemon outdated — rebuild image"

                return label

            def _mk_stats(slot=idx):
                _cache = {"stats": {}, "time": 0}

                def _get(_item):
                    import time as time_mod

                    now = time_mod.monotonic()
                    if now - _cache["time"] < 2.0:
                        return _cache["stats"]
                    if slot >= len(self._tray._targets):
                        return {}
                    target = self._tray._targets[slot]
                    if self._tray._multi_client and target.runtime != "local":
                        result = self._tray._multi_client.get_status(target)
                        if result and should_update_target_name(
                            target, result.get("name")
                        ):
                            target.name = result["name"]
                        _cache["stats"] = result or {}
                    else:
                        _cache["stats"] = self._tray._get_stats()
                    stats = _cache["stats"]
                    if stats:
                        key = (target.name, target.runtime)
                        if "mcp_installed" in stats:
                            self._tray._mcp_installed_per_daemon[key] = stats[
                                "mcp_installed"
                            ]
                        if "version" in stats:
                            self._tray._health._daemon_versions[key] = stats["version"]
                    _cache["time"] = now
                    return stats

                def requests(_item):
                    s = _get(_item)
                    return f"Requests: {s.get('request_count', 0):,}"

                def blocked(_item):
                    s = _get(_item)
                    b = s.get("blocked_count", 0)
                    t = s.get("request_count", 0)
                    if t > 0:
                        return f"Blocked: {b:,} ({b/t*100:.1f}%)"
                    return f"Blocked: {b:,}"

                def warned(_item):
                    s = _get(_item)
                    return f"Warned: {s.get('warning_count', 0):,}"

                def logged(_item):
                    s = _get(_item)
                    return f"Logged: {s.get('log_only_count', 0):,}"

                def violations(_item):
                    s = _get(_item)
                    return f"Violations: {s.get('violation_count', 0):,}"

                def critical(_item):
                    s = _get(_item)
                    return f"  Critical: {s.get('critical_count', 0):,}"

                def warning_sev(_item):
                    s = _get(_item)
                    return f"  Warning: {s.get('warning_severity_count', 0):,}"

                def last_block(_item):
                    s = _get(_item)
                    bt = s.get("last_block_type")
                    ba = s.get("last_block_seconds_ago")
                    if bt is None:
                        return "Last block: none"
                    return f"Last block: {bt} {tray_notifications.format_time_ago(ba)}"

                def ask_dialogs(_item):
                    s = _get(_item)
                    count = s.get("ask_dialog_count", 0)
                    total_ms = s.get("ask_dialog_total_ms", 0)
                    if total_ms >= 1000:
                        return f"Ask dialogs: {count:,} (wait: {total_ms / 1000:.1f}s)"
                    return f"Ask dialogs: {count:,} (wait: {total_ms:.0f}ms)"

                def ask_dialogs_visible(_item):
                    try:
                        return int(_get(_item).get("ask_dialog_count", 0)) > 0
                    except (TypeError, ValueError):
                        return False

                def config_reload(_item):
                    s = _get(_item)
                    ago = s.get("last_config_reload_seconds_ago")
                    if ago is not None:
                        return f"Config reloaded: {tray_notifications.format_time_ago(ago)}"
                    return "Config: loaded"

                def is_paused(_item):
                    return _get(_item).get("paused", False)

                def resume_label(_item):
                    s = _get(_item)
                    remaining = s.get("pause_remaining_seconds", 0)
                    if remaining > 0:
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        return f"Resume ({mins}m {secs}s left)"
                    return "Resume (paused)"

                return (
                    requests,
                    blocked,
                    warned,
                    logged,
                    violations,
                    critical,
                    warning_sev,
                    last_block,
                    ask_dialogs,
                    ask_dialogs_visible,
                    config_reload,
                    is_paused,
                    resume_label,
                    _get,
                )

            stats_fns = _mk_stats()

            def _is_slot_running(_item, slot=idx):
                if slot >= len(self._tray._targets):
                    return False
                if self._tray._targets[slot].status in ("running", "paused"):
                    return True
                return self._tray._can_autostart_daemon()

            multi_plugin_items = self._tray._plugins._build_multi_daemon_plugin_slots(
                idx
            )

            items.append(
                pystray.MenuItem(
                    make_label,
                    pystray.Menu(
                        pystray.MenuItem(
                            "⚠️ Running old code — click to restart",
                            _mk_restart(),
                            visible=_mk_daemon_stale_vis(),
                        ),
                        pystray.MenuItem(
                            _mk_stale_remote_label(),
                            None,
                            visible=_mk_daemon_stale_vis_remote(),
                            enabled=False,
                        ),
                        pystray.MenuItem(
                            "Console",
                            _mk_web_console_action(idx),
                            visible=_mk_web_console_visible(idx),
                            enabled=_is_slot_running,
                        ),
                        pystray.MenuItem(
                            "Violations",
                            _mk_open_panel("panel-violations"),
                            enabled=_is_slot_running,
                        ),
                        pystray.MenuItem(
                            "Metrics & Audit",
                            _mk_open_panel("panel-metrics"),
                            enabled=_is_slot_running,
                        ),
                        pystray.MenuItem(
                            "Statistics",
                            pystray.Menu(
                                pystray.MenuItem(stats_fns[0], None),
                                pystray.MenuItem(stats_fns[1], None),
                                pystray.MenuItem(stats_fns[2], None),
                                pystray.MenuItem(stats_fns[3], None),
                                pystray.Menu.SEPARATOR,
                                pystray.MenuItem(stats_fns[4], None),
                                pystray.MenuItem(stats_fns[5], None),
                                pystray.MenuItem(stats_fns[6], None),
                                pystray.Menu.SEPARATOR,
                                pystray.MenuItem(stats_fns[7], None),
                                pystray.Menu.SEPARATOR,
                                pystray.MenuItem(
                                    stats_fns[8], None, visible=stats_fns[9]
                                ),
                                pystray.Menu.SEPARATOR,
                                pystray.MenuItem(stats_fns[10], None),
                            ),
                            enabled=_is_slot_running,
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            lambda _: f"MCP Proactive: {self._tray._proactive_level}",
                            pystray.Menu(
                                pystray.MenuItem(
                                    "low",
                                    lambda _, __: self._tray._on_change_proactive(
                                        "low"
                                    ),
                                    checked=lambda _: self._tray._proactive_level
                                    == "low",
                                    radio=True,
                                ),
                                pystray.MenuItem(
                                    "medium",
                                    lambda _, __: self._tray._on_change_proactive(
                                        "medium"
                                    ),
                                    checked=lambda _: self._tray._proactive_level
                                    == "medium",
                                    radio=True,
                                ),
                                pystray.MenuItem(
                                    "high",
                                    lambda _, __: self._tray._on_change_proactive(
                                        "high"
                                    ),
                                    checked=lambda _: self._tray._proactive_level
                                    == "high",
                                    radio=True,
                                ),
                            ),
                            visible=lambda _i, s=idx: self._tray._is_mcp_for_slot(s),
                            enabled=_is_slot_running,
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            lambda _i, s=idx: self._working_dir_menu_label(s),
                            self._mk_change_working_dir(idx),
                        ),
                        shell_item,
                        self._build_sandbox_manage_menu_item(idx),
                        pystray.Menu.SEPARATOR,
                        *multi_plugin_items,
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            "Pause...",
                            pystray.Menu(
                                pystray.MenuItem(
                                    lambda _i, _sf=stats_fns: (
                                        self._multi_global_pause_label(_sf, _i)
                                    ),
                                    pystray.Menu(
                                        pystray.MenuItem(
                                            "5 minutes",
                                            _mk_pause(5),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "15 minutes",
                                            _mk_pause(15),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "30 minutes",
                                            _mk_pause(30),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "1 hour",
                                            _mk_pause(60),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "Until resume",
                                            _mk_pause(0),
                                            visible=lambda _i, _sf=stats_fns: (
                                                not _sf[11](_i)
                                            ),
                                        ),
                                        pystray.MenuItem(
                                            "Resume",
                                            _mk_resume(),
                                            visible=lambda _i, _sf=stats_fns: (
                                                _sf[11](_i)
                                            ),
                                        ),
                                    ),
                                ),
                                pystray.Menu.SEPARATOR,
                                *self._build_dir_pause_items(
                                    stats_fns[13],
                                    self._mk_multi_pause_dir(idx),
                                    self._mk_multi_resume_dir(idx),
                                ),
                            ),
                            visible=_is_slot_running,
                        ),
                        pystray.MenuItem(
                            "Start daemon",
                            _mk_restart(),
                            visible=lambda _i, s=idx: (
                                s < len(self._tray._targets)
                                and self._tray._targets[s].status
                                not in ("running", "paused")
                            ),
                        ),
                        pystray.MenuItem(
                            lambda _i, s=idx: self._tray._health._upgrade_label(
                                (
                                    self._tray._targets[s]
                                    if s < len(self._tray._targets)
                                    else None
                                ),
                            ),
                            self._tray._health._mk_upgrade(idx),
                            visible=lambda _i, s=idx: (
                                s < len(self._tray._targets)
                                and self._tray._health._is_upgrade_available(
                                    self._tray._targets[s]
                                )
                            ),
                        ),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem(
                            self._daemon_about_label(idx),
                            self._on_daemon_about(idx),
                            enabled=_is_slot_running,
                        ),
                    ),
                    visible=make_visible,
                )
            )
        return items

    def _build_ide_setup_menu_items(self):
        """Build the top-level IDE/CLI setup submenu.

        Always visible regardless of daemon count. Groups the on-demand hook
        health check with targeted per-IDE setup and config creation so the
        three user flows are discoverable in one place.
        """
        from ai_guardian.setup import IDESetup

        def _mk_ide_action(k):
            def action(_, __):
                tray_menu.launch_ide_setup(k)

            return action

        ide_items = [
            pystray.MenuItem(
                "Check hooks/MCP installation...",
                self._tray._health._on_check_ide_setup,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Manual setup (specific IDE)", None),
        ]

        def _ide_display_name(ide_key, ide_cfg):
            return "Cursor IDE/CLI" if ide_key == "cursor" else ide_cfg["name"]

        # Dummy Agent is an internal hook-testing harness, not a user-facing
        # IDE/CLI integration with a manual setup flow.
        manual_setup_configs = [
            item for item in IDESetup.IDE_CONFIGS.items() if item[0] != "dummy-agent"
        ]
        for ide_key, ide_cfg in sorted(
            manual_setup_configs,
            key=lambda item: _ide_display_name(*item).casefold(),
        ):
            ide_label = _ide_display_name(ide_key, ide_cfg)
            ide_items.append(
                pystray.MenuItem(f"  {ide_label}", _mk_ide_action(ide_key))
            )
            if ide_key == "cursor":
                ide_items.append(
                    pystray.MenuItem(
                        "  Cursor Cloud (project setup)...",
                        self._mk_cursor_cloud_setup_action(),
                    )
                )
        ide_items.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Configuration", None),
                pystray.MenuItem(
                    "  Create Config...",
                    lambda _, __: tray_menu.launch_create_config(),
                ),
            ]
        )

        return [
            pystray.MenuItem(
                "IDE/CLI Setup...",
                pystray.Menu(*ide_items),
            ),
        ]
