"""Complete inline pause controls, rendered only in an isolated UI process."""

import json
import logging
import sys
from functools import partial

from ai_guardian.ui.modal import (
    create_tk_root,
    run_modal_channel,
    run_modal_child,
    run_nicegui_modal,
)
from ai_guardian.ui.monitor import (
    place_tk_window,
    screen_payload,
    tk_scrollable_content,
)

logger = logging.getLogger(__name__)

COMPACT_INSTRUCTIONS = "Select a duration beside a row to pause it; select Resume to clear only that row's pause."


def _set_initial_tk_size(window):
    """Apply size even when placement deliberately leaves position to the WM."""
    max_width, max_height = window.maxsize()
    window.geometry(f"{min(1200, max_width)}x{min(820, max_height)}")


def run_pause_provider(provider, payload, on_event, *, screen_bounds=None):
    if provider not in {"tkinter", "nicegui"}:
        raise ValueError("Unsupported pause UI provider")
    child = (
        "from ai_guardian.ui.pause_controls import run_pause_child; "
        f"run_pause_child({provider!r})"
    )
    run_modal_channel(
        [sys.executable, "-c", child],
        {**payload, "screen_bounds": screen_payload(screen_bounds)},
        on_event,
    )


def _read_snapshot():
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("Pause controls channel closed")
    payload = json.loads(line)
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("Invalid pause display snapshot")
    return payload


def run_pause_child(provider):
    def interaction():
        initial = _read_snapshot()

        def exchange(event):
            print(json.dumps(event), flush=True)
            return _read_snapshot()

        if provider == "tkinter":
            _show_tkinter(initial, exchange)
        elif provider == "nicegui":
            _show_nicegui(initial, exchange)
        else:
            raise ValueError("Unsupported pause UI provider")

    run_modal_child(interaction)


def _row_choices(payload, row):
    if not row["available"]:
        return {}
    return payload["durations"] if row["action"] == "Pause" else {"Resume": "resume"}


def _row_placeholder(row):
    if not row["available"]:
        return "Unavailable"
    return "Pause for…" if row["action"] == "Pause" else "Resume…"


def _row_event(row, selection):
    return {
        "row": row["id"],
        "action": row["action"],
        "minutes": selection if row["action"] == "Pause" else None,
    }


def _show_tkinter(initial, exchange):
    import tkinter as tk
    from tkinter import ttk

    root = create_tk_root()
    root.withdraw()
    root.title("Pause scanning")
    root.resizable(True, True)
    _set_initial_tk_size(root)
    body, footer = tk_scrollable_content(root, padding=12, fit_width=True)
    body.columnconfigure(0, weight=1)
    footer.columnconfigure(1, weight=1)
    toolbar = ttk.Frame(body)
    toolbar.grid(row=0, column=0, sticky="ew")
    toolbar.columnconfigure(0, weight=1)

    def wrapped_label(parent, **options):
        label = ttk.Label(parent, wraplength=280, **options)
        label.bind(
            "<Configure>",
            lambda event: label.configure(wraplength=max(1, event.width - 16)),
        )
        return label

    wrapped_label(toolbar, text=initial["legend"]).grid(row=0, column=0, sticky="ew")
    wrapped_label(toolbar, text=COMPACT_INSTRUCTIONS).grid(
        row=1, column=0, sticky="ew", pady=6
    )
    hierarchy = ttk.Frame(body)
    hierarchy.grid(row=1, column=0, sticky="nsew")
    hierarchy.columnconfigure(0, weight=1)
    details = ttk.Frame(body)
    details.grid(row=2, column=0, sticky="ew")
    details.columnconfigure(0, weight=1)
    wrapped_label(details, text=initial["message"]).grid(
        row=0, column=0, sticky="ew", pady=6
    )
    wrapped_label(details, text=initial["session_lifetime"]).grid(
        row=1, column=0, sticky="ew"
    )
    details.grid_remove()
    help_visible = False
    feedback = tk.StringVar(value=initial.get("feedback", ""))
    wrapped_label(footer, textvariable=feedback).grid(
        row=0, column=0, columnspan=3, sticky="ew"
    )
    controls = []
    failure = []
    busy = False

    def render(payload):
        for widget in hierarchy.winfo_children():
            widget.destroy()
        controls.clear()
        if not payload["rows"]:
            ttk.Label(hierarchy, text="○ No discovered daemons.").grid(row=0, column=0)
        for index, row in enumerate(payload["rows"]):
            line = ttk.Frame(hierarchy, padding=(4, 6))
            line.grid(row=index, column=0, sticky="ew", padx=(24 * row["level"], 0))
            line.columnconfigure(0, weight=1)
            wrapped_label(line, text=row["label"], justify="left").grid(
                row=0, column=0, sticky="ew", padx=(0, 12)
            )
            choices = _row_choices(payload, row)
            placeholder = _row_placeholder(row)
            variable = tk.StringVar(value=placeholder)
            control = ttk.Combobox(
                line,
                textvariable=variable,
                values=[placeholder, *choices],
                state="readonly" if row["available"] else "disabled",
                width=22,
            )
            control.grid(row=0, column=1, sticky="ne")
            control.bind(
                "<<ComboboxSelected>>", partial(choose, row, choices, variable)
            )
            controls.append(control)
        feedback.set(payload.get("feedback", ""))

    def choose(row, choices, variable, _event=None):
        selection = variable.get()
        if selection in choices:
            perform(_row_event(row, choices[selection]))

    def perform(event):
        nonlocal busy
        if busy:
            return
        busy = True
        for control in controls:
            control.state(["disabled"])
        refresh.state(["disabled"])
        feedback.set("Refreshing status…")
        root.update_idletasks()
        try:
            render(exchange(event))
        except (OSError, ValueError, RuntimeError):
            failure.append(True)
            root.destroy()
        finally:
            busy = False
            if not failure:
                refresh.state(["!disabled"])

    def toggle_help():
        nonlocal help_visible
        help_visible = not help_visible
        if help_visible:
            details.grid()
        else:
            details.grid_remove()
        help_toggle.configure(text="Hide help" if help_visible else "Show help")

    refresh = ttk.Button(
        footer,
        text="Refresh status",
        command=partial(perform, {"action": "Refresh status"}),
    )
    refresh.grid(row=1, column=0, sticky="w", pady=(8, 0))
    help_toggle = ttk.Button(footer, text="Show help", command=toggle_help)
    help_toggle.grid(row=1, column=1, sticky="e", padx=8, pady=(8, 0))
    ttk.Button(footer, text="Close", command=root.destroy).grid(
        row=1, column=2, sticky="e", pady=(8, 0)
    )
    render(initial)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.bind("<Escape>", lambda _event: root.destroy())
    place_tk_window(root, initial.get("screen_bounds"), 1200, 820)

    def foreground():
        try:
            root.lift()
            root.focus_force()
        except tk.TclError:
            logger.debug("Pause controls foreground hint unavailable")

    root.deiconify()
    root.after_idle(foreground)
    root.mainloop()
    if failure:
        raise RuntimeError("Pause controls channel ended after display")


def _show_nicegui(initial, exchange):
    from nicegui import app, run, ui

    @ui.page("/")
    def page():
        busy = False
        controls = []
        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-3"):
            ui.label("Pause scanning").classes("text-xl font-bold")
            ui.label(initial["legend"]).classes("whitespace-pre-wrap")
            ui.label(COMPACT_INSTRUCTIONS).classes("whitespace-pre-wrap")
            rows = ui.column().classes(
                "w-full max-h-[65vh] overflow-y-auto overflow-x-hidden"
            )
            feedback = ui.label(initial.get("feedback", "")).classes(
                "whitespace-pre-wrap"
            )

            def render(payload):
                rows.clear()
                controls.clear()
                with rows:
                    if not payload["rows"]:
                        ui.label("○ No discovered daemons.")
                    for row in payload["rows"]:
                        with (
                            ui.row()
                            .classes("w-full flex-nowrap items-start")
                            .style(f"padding-left: {row['level'] * 1.5}rem")
                        ):
                            ui.label(row["label"]).classes(
                                "grow min-w-0 whitespace-pre-wrap break-words"
                            ).style("overflow-wrap:anywhere")
                            choices = _row_choices(payload, row)
                            control = ui.select(
                                options={
                                    value: label for label, value in choices.items()
                                },
                                value=None,
                                label=_row_placeholder(row),
                            ).classes("w-48 shrink-0")
                            control.on_value_change(partial(choose, row, choices))
                            if not row["available"]:
                                control.disable()
                            controls.append(control)
                feedback.set_text(payload.get("feedback", ""))

            async def choose(row, choices, event):
                if event.value is not None and event.value in choices.values():
                    await perform(_row_event(row, event.value))

            async def perform(event):
                nonlocal busy
                if busy:
                    return
                busy = True
                for control in controls:
                    control.disable()
                refresh.disable()
                feedback.set_text("Refreshing status…")
                try:
                    render(await run.io_bound(exchange, event))
                except (OSError, ValueError, RuntimeError):
                    app.shutdown()
                finally:
                    busy = False
                    refresh.enable()

            def close():
                ui.run_javascript("window.close()")
                ui.timer(0.1, app.shutdown, once=True)

            async def refresh_status():
                await perform({"action": "Refresh status"})

            with ui.expansion("Help", value=False).classes("w-full"):
                ui.label(initial["message"]).classes("whitespace-pre-wrap")
                ui.label(initial["session_lifetime"]).classes("text-sm")

            with ui.row().classes("w-full justify-between"):
                refresh = ui.button("Refresh status", on_click=refresh_status)
                ui.button("Close", on_click=close)
            render(initial)

    run_nicegui_modal("Pause scanning", screen_bounds=initial.get("screen_bounds"))
