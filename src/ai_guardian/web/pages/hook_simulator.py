"""Hook Simulator page — simulate hook events and see responses."""

import json
import os
import tempfile
from io import StringIO
from unittest import mock as mock_patch

from nicegui import run, ui

from ai_guardian.constants import CODEX_DISPLAY_NAME, HookEvent
from ai_guardian.logging_utils import quiet_logging
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.tui.hook_simulator import (
    build_hook_data,
    parse_simulation_result,
    HOOK_EVENTS,
    TOOL_OPTIONS,
)

IDE_OPTIONS = [
    ("Augment", "augment"),
    ("Claude Code", "claude"),
    ("Cline / ZooCode", "cline"),
    ("Crush", "crush"),
    (CODEX_DISPLAY_NAME, "codex"),
    ("Cursor", "cursor"),
    ("Gemini CLI", "gemini"),
    ("GitHub Copilot", "copilot"),
    ("Junie", "junie"),
    ("Kiro", "kiro"),
    ("OpenCode", "opencode"),
    ("Windsurf", "windsurf"),
]


def _execute_simulation(hook_data, ide_type="claude"):
    """Execute a hook simulation in an isolated environment.

    Returns result dict from process_hook_input() or None on error.
    """
    import ai_guardian

    ide_env_map = {"copilot": "github_copilot"}

    with tempfile.TemporaryDirectory() as tmp_state:
        env_overrides = {
            "AI_GUARDIAN_STATE_DIR": tmp_state,
            "AI_GUARDIAN_IDE_TYPE": ide_env_map.get(ide_type, ide_type),
        }

        stdin_data = json.dumps(hook_data)
        devnull = StringIO()

        with mock_patch.patch.dict(os.environ, env_overrides):
            with (
                mock_patch.patch("sys.stdin", StringIO(stdin_data)),
                mock_patch.patch("sys.stderr", devnull),
                mock_patch.patch("sys.stdout", devnull),
            ):
                try:
                    with quiet_logging():
                        result = ai_guardian.process_hook_input()
                except Exception as exc:
                    return {"error": str(exc)}

    return result


def create_hook_simulator_page(service, daemon_name: str):
    """Create the Hook Simulator page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/hook-simulator")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Hook Simulator").classes("text-2xl font-bold")
        ui.label("Simulate hook events to test detection rules.").classes(
            "text-xs text-grey-6"
        )

        hook_options = {v: label for label, v in HOOK_EVENTS}
        tool_options = {v: label for label, v in TOOL_OPTIONS}
        ide_options = {v: label for label, v in IDE_OPTIONS}

        with ui.card().classes("w-full"):
            ui.label("Input").classes("text-lg font-bold")

            with ui.row().classes("items-center gap-4 flex-wrap"):
                hook_sel = ui.select(
                    label="Hook Event",
                    options=hook_options,
                    value=HookEvent.PROMPT.display_name,
                ).classes("w-48")

                tool_sel = ui.select(
                    label="Tool",
                    options=tool_options,
                    value="Read",
                ).classes("w-40")

                ide_sel = ui.select(
                    label="IDE Format",
                    options=ide_options,
                    value="claude",
                ).classes("w-40")

            file_input = (
                ui.input(
                    label="File Path (optional)",
                    placeholder="/path/to/file",
                )
                .props("dense outlined")
                .classes("w-full")
            )

            content_input = (
                ui.textarea(
                    label="Content / Prompt",
                    placeholder="Enter text to scan...",
                )
                .props("outlined")
                .classes("w-full")
                .style("min-height: 150px")
            )

            def update_visibility(e=None):
                is_tool_hook = hook_sel.value != HookEvent.PROMPT.display_name
                tool_sel.set_visibility(is_tool_hook)
                file_input.set_visibility(is_tool_hook)

            hook_sel.on_value_change(update_visibility)
            update_visibility()

        results_container = ui.column().classes("w-full gap-4")

        async def do_simulate():
            hook_data = build_hook_data(
                hook_event=hook_sel.value,
                tool_name=(
                    tool_sel.value
                    if hook_sel.value != HookEvent.PROMPT.display_name
                    else None
                ),
                file_path=(
                    file_input.value
                    if hook_sel.value != HookEvent.PROMPT.display_name
                    else None
                ),
                content=content_input.value or "",
            )

            result = await run.io_bound(_execute_simulation, hook_data, ide_sel.value)

            results_container.clear()
            with results_container:
                with ui.card().classes("w-full"):
                    if result is None or "error" in result:
                        err = (
                            result.get("error", "Unknown error")
                            if result
                            else "No result"
                        )
                        ui.label("Error").classes("text-lg font-bold text-red")
                        ui.label(err).classes("text-sm text-red")
                        return

                    parsed = parse_simulation_result(result)

                    ui.label("Result").classes("text-lg font-bold")

                    decision = parsed["decision"]
                    if decision == "BLOCKED":
                        ui.badge("BLOCKED", color="red").classes("text-lg")
                    elif decision == "ALLOWED WITH WARNING":
                        ui.badge("ALLOWED WITH WARNING", color="amber").classes(
                            "text-lg"
                        )
                    else:
                        ui.badge("ALLOWED", color="green").classes("text-lg")

                    if parsed["reason"]:
                        ui.label("Reason:").classes("font-bold text-sm mt-2")
                        ui.label(parsed["reason"]).classes("text-sm text-grey-4")

                    if parsed["redacted_output"]:
                        ui.label("Redacted Output:").classes("font-bold text-sm mt-2")
                        ui.code(parsed["redacted_output"]).classes("w-full")

                    ui.label("Raw JSON:").classes("font-bold text-sm mt-2")
                    with ui.scroll_area().classes("w-full").style("max-height: 300px"):
                        ui.code(parsed["raw_json"], language="json").classes("w-full")

        ui.button(
            "Run Simulation",
            icon="play_arrow",
            on_click=do_simulate,
        ).props("dense")
