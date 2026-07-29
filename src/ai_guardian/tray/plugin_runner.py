"""
Plugin menu building and execution for the system tray.

Split from tray.py (Issue #1542). TrayPluginMenuBuilder holds plugin state
(loaded plugins, hashes) and provides menu slot building and command execution.
It receives a back-reference to DaemonTray.
"""

import logging
import threading

from ai_guardian.tray import plugins as tray_plugins

logger = logging.getLogger(__name__)

try:
    import pystray
except Exception:
    pystray = None


class TrayPluginMenuBuilder:
    """Manages plugin loading, menu slot construction, and command execution."""

    from ai_guardian.tray.plugins import (
        MAX_PLUGIN_SLOTS as _MAX_PLUGIN_SLOTS,
        MAX_ITEMS_PER_PLUGIN as _MAX_ITEMS_PER_PLUGIN,
        MAX_SUBMENU_ITEMS as _MAX_SUBMENU_ITEMS,
        MAX_SUBMENU_DEPTH as _MAX_SUBMENU_DEPTH,
        MAX_GLOBAL_PLUGIN_SLOTS as _MAX_GLOBAL_PLUGIN_SLOTS,
        MAX_GLOBAL_ITEMS_PER_PLUGIN as _MAX_GLOBAL_ITEMS_PER_PLUGIN,
    )

    def __init__(self, tray):
        self._tray = tray
        self._daemon_plugins = {}
        self._last_plugins_hash = {}
        self._global_plugins = []
        self._daemon_global_plugins = {}

    def _poll_plugins(self):
        """Fetch plugin definitions from each discovered daemon.

        Global-scope plugins are collected from all reachable daemons
        and stored in ``_global_plugins`` for top-level rendering.
        They follow the daemon lifecycle: when a daemon stops, its
        global plugins disappear.
        """
        import json as json_mod

        collected_globals = []
        seen_global_names = set()
        reachable_slots = set()
        for i, target in enumerate(self._tray._targets):
            is_reachable = target.status in ("running", "paused")
            if not is_reachable and target.runtime != "local":
                continue
            reachable_slots.add(i)
            try:
                wd = getattr(target, "working_dir", None)
                if self._tray._multi_client:
                    if target.runtime == "local":
                        data = self._tray._multi_client._local_plugins(working_dir=wd)
                    elif is_reachable:
                        data = self._tray._multi_client.get_plugins(target)
                    else:
                        continue
                else:
                    from ai_guardian.tray.plugins import (
                        load_merged_plugins,
                        plugins_to_dict,
                    )

                    data = plugins_to_dict(load_merged_plugins(wd))
                if data:
                    data_hash = json_mod.dumps(data, sort_keys=True)
                    daemon_tags = self._get_daemon_menu_tags(target)
                    tag_hash = json_mod.dumps(daemon_tags, sort_keys=True)
                    combined_hash = data_hash + tag_hash
                    if self._last_plugins_hash.get(i) != combined_hash:
                        from ai_guardian.tray.plugins import (
                            dict_to_plugins,
                            filter_plugins_by_tags,
                        )

                        plugins = dict_to_plugins(data)
                        daemon_only = [p for p in plugins if p.scope != "global"]
                        self._daemon_plugins[i] = filter_plugins_by_tags(
                            daemon_only,
                            daemon_tags,
                        )
                        self._last_plugins_hash[i] = combined_hash
                        self._daemon_global_plugins[i] = [
                            p for p in plugins if p.scope == "global"
                        ]
            except Exception:
                pass  # intentionally silent — best-effort operation
        for i in reachable_slots:
            for p in self._daemon_global_plugins.get(i, []):
                if p.dedup_key not in seen_global_names:
                    collected_globals.append(p)
                    seen_global_names.add(p.dedup_key)
        stale = set(self._daemon_global_plugins) - reachable_slots
        for i in stale:
            del self._daemon_global_plugins[i]
        if collected_globals != self._global_plugins:
            self._global_plugins = collected_globals

    def _get_daemon_menu_tags(self, target):
        """Get menu_tags for a daemon target."""
        if target.runtime == "local":
            from ai_guardian.daemon import get_local_menu_tags

            return get_local_menu_tags()
        if self._tray._multi_client:
            status = self._tray._multi_client.get_status(target)
            if status:
                return status.get("menu_tags", [])
        return []

    def _get_daemon_plugins(self, slot):
        """Get plugin list for a daemon slot index."""
        return self._daemon_plugins.get(slot, [])

    def _execute_plugin_command_with_params(self, plugin_item_dict, target=None):
        """Collect parameters via direct call or subprocess, then execute.

        Uses direct in-process TrayPromptApp call when NiceGUI is available
        (no subprocess overhead). Tkinter cannot be used in-process because
        pystray already owns NSApplication on macOS — tk.Tk() crashes when
        called after NSApplication.sharedApplication(). Falls back to
        subprocess for tkinter and terminal for Textual.
        """
        import json as json_mod
        import os
        import subprocess
        import tempfile
        import threading
        from ai_guardian.tray.plugins import (
            resolve_command,
            substitute_target_vars,
        )

        resolved_cmd = resolve_command(plugin_item_dict["command"])
        if resolved_cmd is None:
            return

        resolved_cmd = substitute_target_vars(resolved_cmd, target)

        extra_vars = {}
        if target and getattr(target, "working_dir", None):
            extra_vars["working_dir"] = target.working_dir

        label = plugin_item_dict.get("label")
        item_type = plugin_item_dict.get("type", "terminal")
        run_on_target = plugin_item_dict.get("run_on_target", False)
        params = plugin_item_dict.get("params", [])

        from ai_guardian.tui.display import (
            _nicegui_available,
            _tkinter_available,
        )

        if _tkinter_available():
            logger.info("Plugin prompt: using tkinter subprocess")
            tmpdir = tempfile.mkdtemp(prefix="ai-guardian-prompt-")
            output_path = os.path.join(tmpdir, "command")

            params_json = json_mod.dumps(params)
            prompt_cmd = tray_plugins.resolve_cli_cmd(
                "prompt",
                "--mode",
                "params",
                "--params",
                params_json,
                "--template",
                resolved_cmd,
                "--type",
                item_type,
                "--output-file",
                output_path,
            )
            if extra_vars:
                prompt_cmd += ["--extra-vars", json_mod.dumps(extra_vars)]
            if label:
                prompt_cmd += ["--title", label]

            subprocess.Popen(prompt_cmd)

            def _watch_and_dispatch():
                command = tray_plugins.poll_output_file(output_path, tmpdir)
                if command:
                    tray_plugins.execute_plugin_command(
                        command,
                        item_type,
                        target=target,
                        run_on_target=run_on_target,
                        label=label,
                    )

            threading.Thread(
                target=_watch_and_dispatch,
                daemon=True,
                name="plugin-prompt-watch",
            ).start()
        elif _nicegui_available():

            def _run_prompt_and_dispatch():
                try:
                    from ai_guardian.tui.tray_prompt import TrayPromptApp

                    app = TrayPromptApp(
                        params=params,
                        command_template=resolved_cmd,
                        command_type=item_type,
                        extra_vars=extra_vars,
                        title=label,
                    )
                    command = app.run()
                except Exception as e:
                    logger.warning("Direct prompt call failed: %s", e)
                    command = None
                if command:
                    tray_plugins.execute_plugin_command(
                        command,
                        item_type,
                        target=target,
                        run_on_target=run_on_target,
                        label=label,
                    )

            threading.Thread(
                target=_run_prompt_and_dispatch,
                daemon=True,
                name="plugin-prompt",
            ).start()
        else:
            tmpdir = tempfile.mkdtemp(prefix="ai-guardian-prompt-")
            output_path = os.path.join(tmpdir, "command")

            params_json = json_mod.dumps(params)
            prompt_cmd = tray_plugins.resolve_cli_cmd(
                "prompt",
                "--mode",
                "params",
                "--params",
                params_json,
                "--template",
                resolved_cmd,
                "--type",
                item_type,
                "--output-file",
                output_path,
            )
            if extra_vars:
                prompt_cmd += ["--extra-vars", json_mod.dumps(extra_vars)]
            if label:
                prompt_cmd += ["--title", label]

            from ai_guardian.daemon.multi_client import _launch_in_terminal

            _launch_in_terminal(prompt_cmd, keep_open=False, clear=True)

            def _watch_and_dispatch():
                command = tray_plugins.poll_output_file(output_path, tmpdir)
                if command:
                    tray_plugins.execute_plugin_command(
                        command,
                        item_type,
                        target=target,
                        run_on_target=run_on_target,
                        label=label,
                    )

            threading.Thread(
                target=_watch_and_dispatch,
                daemon=True,
                name="plugin-prompt-watch",
            ).start()

    def _resolve_target_list(self, target_mode):
        """Resolve a target mode to a list of DaemonTarget instances."""
        if target_mode == "all":
            return list(self._tray._targets)
        if target_mode == "containers":
            return [t for t in self._tray._targets if t.runtime == "container"]
        return []

    def _execute_multi_target_command(
        self,
        targets,
        command_str,
        item_type,
        run_on_target=False,
        label=None,
    ):
        """Execute the same command on multiple targets sequentially."""
        for target in targets:
            tray_plugins.execute_plugin_command(
                command_str,
                item_type,
                target=target,
                run_on_target=run_on_target,
                label=label,
            )

    def _serialize_targets_for_selector(self):
        """Serialize discovered targets to JSON dicts for the selector TUI."""
        return [
            {
                "name": t.name,
                "runtime": t.runtime,
                "container_name": getattr(t, "container_name", None),
                "container_engine": t.container_engine,
                "container_id": t.container_id,
                "pod_name": t.pod_name,
                "namespace": t.namespace,
                "status": t.status,
            }
            for t in self._tray._targets
        ]

    def _execute_multi_target_with_params(self, plugin_item, targets):
        """Collect params once via direct call or subprocess, then execute on all targets.

        Uses direct in-process TrayPromptApp call when NiceGUI is available.
        Tkinter requires a subprocess (conflicts with pystray's NSApplication
        on macOS). Falls back to Textual TUI in a terminal window.
        """
        import json as json_mod
        import os
        import subprocess
        import tempfile
        import threading
        from ai_guardian.tray.plugins import (
            _item_to_dict,
            resolve_command,
        )

        item_dict = _item_to_dict(plugin_item)
        resolved_cmd = resolve_command(plugin_item.command)
        if resolved_cmd is None:
            return

        label = plugin_item.label
        item_type = plugin_item.type
        run_on_target = plugin_item.run_on_target
        params = item_dict.get("params", [])

        from ai_guardian.tui.display import (
            _nicegui_available,
            _tkinter_available,
        )

        if _tkinter_available():
            tmpdir = tempfile.mkdtemp(prefix="ai-guardian-prompt-")
            output_path = os.path.join(tmpdir, "command")

            params_json = json_mod.dumps(params)
            prompt_cmd = tray_plugins.resolve_cli_cmd(
                "prompt",
                "--mode",
                "params",
                "--params",
                params_json,
                "--template",
                resolved_cmd,
                "--type",
                item_type,
                "--output-file",
                output_path,
            )
            if label:
                prompt_cmd += ["--title", label]

            subprocess.Popen(prompt_cmd)

            def _watch_and_dispatch():
                command = tray_plugins.poll_output_file(output_path, tmpdir)
                if command:
                    self._execute_multi_target_command(
                        targets,
                        command,
                        item_type,
                        run_on_target=run_on_target,
                        label=label,
                    )

            threading.Thread(
                target=_watch_and_dispatch,
                daemon=True,
                name="multi-plugin-prompt-watch",
            ).start()
        elif _nicegui_available():

            def _run_prompt_and_dispatch():
                try:
                    from ai_guardian.tui.tray_prompt import TrayPromptApp

                    app = TrayPromptApp(
                        params=params,
                        command_template=resolved_cmd,
                        command_type=item_type,
                        title=label,
                    )
                    command = app.run()
                except Exception as e:
                    logger.warning("Direct prompt call failed: %s", e)
                    command = None
                if command:
                    self._execute_multi_target_command(
                        targets,
                        command,
                        item_type,
                        run_on_target=run_on_target,
                        label=label,
                    )

            threading.Thread(
                target=_run_prompt_and_dispatch,
                daemon=True,
                name="multi-plugin-prompt",
            ).start()
        else:
            tmpdir = tempfile.mkdtemp(prefix="ai-guardian-prompt-")
            output_path = os.path.join(tmpdir, "command")

            params_json = json_mod.dumps(params)
            prompt_cmd = tray_plugins.resolve_cli_cmd(
                "prompt",
                "--mode",
                "params",
                "--params",
                params_json,
                "--template",
                resolved_cmd,
                "--type",
                item_type,
                "--output-file",
                output_path,
            )
            if label:
                prompt_cmd += ["--title", label]

            from ai_guardian.daemon.multi_client import _launch_in_terminal

            _launch_in_terminal(prompt_cmd, keep_open=False, clear=True)

            def _watch_and_dispatch():
                command = tray_plugins.poll_output_file(output_path, tmpdir)
                if command:
                    self._execute_multi_target_command(
                        targets,
                        command,
                        item_type,
                        run_on_target=run_on_target,
                        label=label,
                    )

            threading.Thread(
                target=_watch_and_dispatch,
                daemon=True,
                name="multi-plugin-prompt-watch",
            ).start()

    def _execute_plugin_with_target_select(self, plugin_item):
        """Launch target selector, then execute on selected targets."""
        import json as json_mod
        import os
        import tempfile
        import threading
        from ai_guardian.tray.plugins import (
            resolve_command,
        )
        from ai_guardian.daemon.multi_client import _launch_in_terminal

        targets_json = json_mod.dumps(self._serialize_targets_for_selector())
        tmpdir = tempfile.mkdtemp(prefix="ai-guardian-target-")
        output_path = os.path.join(tmpdir, "selected")

        select_cmd = tray_plugins.resolve_cli_cmd(
            "tray-target-select",
            "--targets",
            targets_json,
            "--output-file",
            output_path,
        )
        _launch_in_terminal(select_cmd, keep_open=False, clear=True)

        def _watch_and_dispatch():
            raw = tray_plugins.poll_output_file(output_path, tmpdir)
            if not raw:
                return
            try:
                indices = json_mod.loads(raw)
            except (json_mod.JSONDecodeError, TypeError):
                return
            if not isinstance(indices, list):
                return
            selected = [
                self._tray._targets[i]
                for i in indices
                if isinstance(i, int) and 0 <= i < len(self._tray._targets)
            ]
            if not selected:
                return

            if plugin_item.params:
                self._execute_multi_target_with_params(
                    plugin_item,
                    selected,
                )
            else:
                cmd = resolve_command(plugin_item.command)
                if cmd:
                    self._execute_multi_target_command(
                        selected,
                        cmd,
                        plugin_item.type,
                        run_on_target=plugin_item.run_on_target,
                        label=plugin_item.label,
                    )

        watcher = threading.Thread(target=_watch_and_dispatch, daemon=True)
        watcher.start()

    def _build_plugin_slots_for_daemon(self, daemon_slot, visibility_guard=None):
        """Build pre-allocated plugin menu item slots for a daemon.

        Args:
            daemon_slot: Index into self._tray._targets for this daemon.
            visibility_guard: Optional callable(_item) -> bool wrapping
                each plugin's visibility. When None, plugins are always
                visible if they exist.
        """
        get_plugins = lambda: self._get_daemon_plugins(daemon_slot)
        get_target = lambda: (
            self._tray._targets[daemon_slot]
            if daemon_slot < len(self._tray._targets)
            else None
        )
        return self._build_plugin_slots(
            get_plugins,
            get_target,
            max_plugins=self._MAX_PLUGIN_SLOTS,
            max_items=self._MAX_ITEMS_PER_PLUGIN,
            visibility_guard=visibility_guard,
        )

    def _build_plugin_slots(
        self,
        get_plugins_fn,
        get_target_fn,
        max_plugins,
        max_items,
        visibility_guard=None,
    ):
        """Build pre-allocated plugin menu item slots.

        Args:
            get_plugins_fn: Callable returning the plugin list.
            get_target_fn: Callable returning the target for execution.
            max_plugins: Number of plugin slots to pre-allocate.
            max_items: Number of item slots per plugin.
            visibility_guard: Optional callable(_item) -> bool.
        """
        items = []

        for p_idx in range(max_plugins):
            p_slot = p_idx

            def _plugin_name(_item, ps=p_slot):
                plugins = get_plugins_fn()
                if ps < len(plugins):
                    return plugins[ps].name
                return ""

            def _plugin_visible(_item, ps=p_slot):
                if visibility_guard is not None and not visibility_guard(_item):
                    return False
                plugins = get_plugins_fn()
                return ps < len(plugins)

            def _get_item_list(ps=p_slot):
                plugins = get_plugins_fn()
                if ps < len(plugins):
                    return plugins[ps].items
                return []

            sub_items = self._build_nested_item_slots(
                _get_item_list,
                get_target_fn,
                max_items,
                depth=0,
            )

            items.append(
                pystray.MenuItem(
                    _plugin_name, pystray.Menu(*sub_items), visible=_plugin_visible
                )
            )

        return items

    def _build_nested_item_slots(
        self,
        get_items_fn,
        get_target_fn,
        max_items,
        depth,
    ):
        """Build pre-allocated slots for items that may contain submenus.

        For each slot position, two pystray MenuItems are created:
        one for command items (clickable) and one for submenu items
        (expandable). Only one is visible at a time.

        Args:
            get_items_fn: Callable returning the item list.
            get_target_fn: Callable returning the execution target.
            max_items: Number of item slots to pre-allocate.
            depth: Current nesting depth (0 = direct plugin children).
        """
        slots = []

        for i_idx in range(max_items):
            i_slot = i_idx

            def _cmd_label(_item, ix=i_slot):
                items_list = get_items_fn()
                if ix < len(items_list):
                    return items_list[ix].label
                return ""

            def _cmd_visible(_item, ix=i_slot):
                items_list = get_items_fn()
                if ix >= len(items_list):
                    return False
                item = items_list[ix]
                if item.items:
                    return False
                from ai_guardian.tray.plugins import resolve_command

                return resolve_command(item.command) is not None

            def _cmd_action(ix=i_slot):
                def action(_, __):
                    items_list = get_items_fn()
                    if ix >= len(items_list):
                        return
                    item = items_list[ix]
                    if item.items:
                        return
                    target = get_target_fn()

                    if item.target in ("all", "containers"):
                        from ai_guardian.tray.plugins import resolve_command

                        targets = self._resolve_target_list(item.target)
                        if not targets:
                            return
                        if item.params:
                            self._execute_multi_target_with_params(
                                item,
                                targets,
                            )
                        else:
                            cmd = resolve_command(item.command)
                            if cmd:
                                self._execute_multi_target_command(
                                    targets,
                                    cmd,
                                    item.type,
                                    run_on_target=item.run_on_target,
                                    label=item.label,
                                )
                    elif item.target == "select":
                        self._execute_plugin_with_target_select(item)
                    elif item.params:
                        from ai_guardian.tray.plugins import _item_to_dict

                        self._execute_plugin_command_with_params(
                            _item_to_dict(item),
                            target=target,
                        )
                    else:
                        from ai_guardian.tray.plugins import resolve_command

                        cmd = resolve_command(item.command)
                        if cmd:
                            tray_plugins.execute_plugin_command(
                                cmd,
                                item.type,
                                target=target,
                                run_on_target=item.run_on_target,
                                label=item.label,
                            )

                return action

            def _cmd_enabled(_item, ix=i_slot):
                items_list = get_items_fn()
                if ix >= len(items_list):
                    return True
                item = items_list[ix]
                if not item.run_on_target:
                    return True
                target = get_target_fn()
                if target is None:
                    return False
                return target.status in ("running", "paused")

            slots.append(
                pystray.MenuItem(
                    _cmd_label,
                    _cmd_action(),
                    visible=_cmd_visible,
                    enabled=_cmd_enabled,
                )
            )

            if depth < self._MAX_SUBMENU_DEPTH:

                def _sub_label(_item, ix=i_slot):
                    items_list = get_items_fn()
                    if ix < len(items_list):
                        return items_list[ix].label
                    return ""

                def _sub_visible(_item, ix=i_slot):
                    items_list = get_items_fn()
                    if ix >= len(items_list):
                        return False
                    return bool(items_list[ix].items)

                def _get_children(ix=i_slot):
                    items_list = get_items_fn()
                    if ix < len(items_list) and items_list[ix].items:
                        return items_list[ix].items
                    return []

                child_slots = self._build_nested_item_slots(
                    _get_children,
                    get_target_fn,
                    self._MAX_SUBMENU_ITEMS,
                    depth + 1,
                )

                slots.append(
                    pystray.MenuItem(
                        _sub_label,
                        pystray.Menu(*child_slots),
                        visible=_sub_visible,
                    )
                )

        return slots

    def _build_single_daemon_plugin_items(self):
        """Build plugin menu items for single-daemon mode.

        Each plugin becomes a top-level submenu. Pre-allocates slots
        for pystray macOS compatibility. Only visible when exactly one
        daemon is discovered and that daemon has plugins.
        """

        def _has_plugins(_item):
            return (
                self._tray._is_single_daemon() and len(self._get_daemon_plugins(0)) > 0
            )

        guard = lambda _item: self._tray._is_single_daemon()
        items = [
            pystray.MenuItem("", None, visible=lambda _: (_has_plugins(_) and False))
        ]
        items.extend(self._build_plugin_slots_for_daemon(0, visibility_guard=guard))
        return items

    def _build_multi_daemon_plugin_slots(self, daemon_slot):
        """Build pre-allocated plugin slots for a multi-daemon submenu."""
        return self._build_plugin_slots_for_daemon(daemon_slot)

    def _build_global_plugin_items(self):
        """Build top-level menu items for global-scope plugins.

        Global plugins appear at the tray top level, not inside any
        daemon submenu. Pre-allocates slots for pystray macOS
        compatibility.
        """
        items = self._build_plugin_slots(
            get_plugins_fn=lambda: self._global_plugins,
            get_target_fn=lambda: self._tray._active_target,
            max_plugins=self._MAX_GLOBAL_PLUGIN_SLOTS,
            max_items=self._MAX_GLOBAL_ITEMS_PER_PLUGIN,
        )
        items.append(pystray.Menu.SEPARATOR)
        return items
