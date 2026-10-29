"""Inline hierarchy renderers and isolated, display-only child transport."""

import asyncio
import io
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
import sys

import pytest

from ai_guardian.ui import pause_controls


@pytest.fixture
def display():
    return {
        "legend": "● Active ◐ Partially paused ☾ Paused ○ Unavailable",
        "message": "Resume affects only this row.",
        "session_lifetime": "Sessions also end.",
        "durations": {"5 minutes": 5, "1 hour": 60, "Until resume": 0},
        "feedback": "",
        "rows": [
            {
                "id": f"0:{index}",
                "level": index,
                "scope": scope,
                "available": True,
                "action": "Pause",
                "label": f"● {scope}",
            }
            for index, scope in enumerate(("global", "dir", "session"))
        ],
        "screen_bounds": [1920, 0, 1920, 1080],
    }


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.mark.parametrize(
    "choice,minutes", [("5 minutes", 5), ("1 hour", 60), ("Until resume", 0)]
)
def test_tk_row_dropdowns_pause_or_resume_in_one_larger_width_fitting_window(
    display, monkeypatch, choice, minutes
):
    root, body, footer = MagicMock(), MagicMock(), MagicMock()
    root.maxsize.return_value = (1920, 1080)
    body.winfo_children.return_value = []
    controls, combos, labels, frames = [], [], [], []

    def button(parent, **kwargs):
        widget = MagicMock()
        controls.append((parent, kwargs, widget))
        return widget

    def frame(*args, **kwargs):
        widget = MagicMock()
        frames.append(widget)
        return widget

    def combo(parent, **kwargs):
        widget = MagicMock()
        combos.append((parent, kwargs, widget))
        return widget

    def label(parent, **kwargs):
        widget = MagicMock()
        labels.append((parent, kwargs, widget))
        return widget

    ttk = SimpleNamespace(
        Frame=Mock(side_effect=frame),
        Label=Mock(side_effect=label),
        Combobox=Mock(side_effect=combo),
        Button=Mock(side_effect=button),
    )
    tk = SimpleNamespace(
        ttk=ttk, StringVar=Variable, TclError=type("TclError", (Exception,), {})
    )
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    create = Mock(return_value=root)
    monkeypatch.setattr(pause_controls, "create_tk_root", create)
    viewport = Mock(return_value=(body, footer))
    monkeypatch.setattr(pause_controls, "tk_scrollable_content", viewport)
    place = Mock(
        return_value=False
    )  # No monitor context: placement applies no geometry.
    monkeypatch.setattr(pause_controls, "place_tk_window", place)
    events = []

    def exchange(event):
        events.append(event)
        updated = deepcopy(display)
        updated["feedback"] = "Updated in place"
        if event.get("row"):
            row = next(r for r in updated["rows"] if r["id"] == event["row"])
            row["action"] = "Resume" if event["action"] == "Pause" else "Pause"
            row["label"] = ("☾ " if event["action"] == "Pause" else "● ") + row["scope"]
        return updated

    def interact():
        root.geometry.assert_called_once_with("1200x820")
        assert len(combos) == 3  # One dropdown per row; no shared duration control.
        assert {kw["text"] for _, kw, _ in controls} == {
            "Refresh status",
            "Show help",
            "Close",
        }
        help_panel = next(widget for widget in frames if widget.grid_remove.call_count)
        help_panel.grid_remove.assert_called_once()
        toggle = next(
            kw["command"] for _, kw, _ in controls if kw["text"] == "Show help"
        )
        toggle()
        toggle()
        assert help_panel.grid_remove.call_count == 2
        assert not events
        _, options, widget = combos[1]
        choose = widget.bind.call_args.args[1]
        assert widget.bind.call_args.args[0] == "<<ComboboxSelected>>"
        choose(None)  # Rendering/opening a placeholder must not send an action.
        assert not events
        options["textvariable"].set(choice)
        root.update_idletasks.side_effect = lambda: choose(None)
        choose(None)
        root.destroy.assert_not_called()
        assert events == [{"row": "0:1", "action": "Pause", "minutes": minutes}]
        _, resumed, resume_widget = combos[4]
        assert "Resume" in resumed["values"] and choice not in resumed["values"]
        resumed["textvariable"].set("Resume")
        resume_widget.bind.call_args.args[1](None)
        assert events[-1] == {"row": "0:1", "action": "Resume", "minutes": None}
        assert len(events) == 2
        text = next(w for _, kw, w in labels if kw.get("text") == "● dir")
        text.bind.call_args.args[1](SimpleNamespace(width=250))
        text.configure.assert_called_with(wraplength=234)
        text.bind.call_args.args[1](SimpleNamespace(width=90))
        text.configure.assert_called_with(wraplength=74)
        assert options["width"] >= 20
        assert all(
            parent is footer
            for parent, kw, _ in controls
            if kw["text"] in {"Refresh status", "Close"}
        )
        escape = root.bind.call_args.args[1]
        escape(None)
        root.destroy.assert_called_once()

    root.mainloop.side_effect = interact
    pause_controls._show_tkinter(display, exchange)
    create.assert_called_once()
    root.geometry.assert_called_once_with("1200x820")
    place.assert_called_once_with(root, display["screen_bounds"], 1200, 820)
    viewport.assert_called_once_with(root, padding=12, fit_width=True)


class Widget:
    def __init__(self, value=None, options=None, label=""):
        self.value = value
        self.options = options
        self.label = label
        self.enabled = True
        self.text = ""
        self.class_names = []
        self.styles = []
        self.callback = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def classes(self, *args):
        self.class_names.extend(args)
        return self

    def style(self, text):
        self.styles.append(text)
        return self

    def on_value_change(self, callback):
        self.callback = callback
        return self

    def disable(self):
        self.enabled = False

    def enable(self):
        self.enabled = True

    def set_text(self, text):
        self.text = text

    def clear(self):
        return None


@pytest.mark.parametrize(
    "maximum,geometry",
    [((1920, 1080), "1200x820"), ((1024, 720), "1024x720"), ((640, 480), "640x480")],
)
def test_initial_geometry_is_applied_within_window_manager_limits(maximum, geometry):
    root = Mock()
    root.maxsize.return_value = maximum
    pause_controls._set_initial_tk_size(root)
    root.geometry.assert_called_once_with(geometry)


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [0, 5, 60])
async def test_browser_per_row_dropdown_has_no_default_action_and_wraps_labels(
    display, monkeypatch, minutes
):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    pages, buttons, selects, labels, expansions = [], [], [], [], []

    def page(_route):
        def register(callback):
            pages.append(callback)
            return callback

        return register

    def button(label, *, on_click):
        widget = Widget()
        buttons.append((label, on_click, widget))
        return widget

    def select(*args, **kwargs):
        widget = Widget(kwargs["value"], kwargs["options"], kwargs.get("label", ""))
        selects.append(widget)
        return widget

    def label(text):
        widget = Widget()
        widget.text = text
        labels.append(widget)
        return widget

    def expansion(text, *, value):
        widget = Widget(value=value, label=text)
        expansions.append(widget)
        return widget

    ui = SimpleNamespace(
        page=page,
        column=Widget,
        row=Widget,
        label=label,
        button=button,
        select=select,
        expansion=expansion,
        run_javascript=Mock(),
        timer=Mock(),
    )

    async def io_bound(callback, event):
        assert all(
            not widget.enabled
            for label, callback, widget in buttons
            if label != "Close"
        )
        assert all(not widget.enabled for widget in selects)
        await asyncio.sleep(0)
        return callback(event)

    monkeypatch.setitem(
        sys.modules,
        "nicegui",
        SimpleNamespace(ui=ui, run=SimpleNamespace(io_bound=io_bound), app=Mock()),
    )
    server = Mock(side_effect=lambda *a, **k: pages[0]())
    monkeypatch.setattr(pause_controls, "run_nicegui_modal", server)

    def update(event):
        changed = deepcopy(display)
        changed["feedback"] = "Updated"
        changed["rows"][2]["action"] = (
            "Resume" if event["action"] == "Pause" else "Pause"
        )
        return changed

    exchange = Mock(side_effect=update)
    pause_controls._show_nicegui(display, exchange)
    assert [label for label, _, _ in buttons] == ["Refresh status", "Close"]
    assert len(expansions) == 1 and expansions[0].value is False
    assert expansions[0].label == "Help"
    assert any(widget.text == pause_controls.COMPACT_INSTRUCTIONS for widget in labels)
    assert len(selects) == 3 and all(widget.value is None for widget in selects)
    await selects[2].callback(SimpleNamespace(value=None))
    exchange.assert_not_called()
    await selects[2].callback(SimpleNamespace(value=minutes))
    exchange.assert_called_once_with(
        {"row": "0:2", "action": "Pause", "minutes": minutes}
    )
    assert all(widget.value is None for widget in selects[-3:])
    resume = selects[-1]
    assert resume.options == {"resume": "Resume"}
    await resume.callback(SimpleNamespace(value="resume"))
    assert exchange.call_args.args[0] == {
        "row": "0:2",
        "action": "Resume",
        "minutes": None,
    }
    server.assert_called_once()
    assert all("w-48 shrink-0" in widget.class_names for widget in selects)
    assert any(
        "grow min-w-0 whitespace-pre-wrap break-words" in widget.class_names
        for widget in labels
    )


@pytest.mark.parametrize("provider", ["tkinter", "nicegui"])
def test_provider_only_sends_display_data_over_stdin(display, provider):
    respond = Mock()
    with patch.object(pause_controls, "run_modal_channel") as channel:
        pause_controls.run_pause_provider(
            provider, display, respond, screen_bounds=(1920, 0, 1920, 1080)
        )
    command, payload, callback = channel.call_args.args
    assert display["message"] not in str(command)
    assert payload["rows"] == display["rows"] and callback is respond
    assert tuple(payload["screen_bounds"]) == (1920, 0, 1920, 1080)


@pytest.mark.parametrize(
    "provider,renderer", [("tkinter", "_show_tkinter"), ("nicegui", "_show_nicegui")]
)
def test_child_roundtrip_contains_only_narrow_event_and_terminal_close(
    display, provider, renderer, monkeypatch, capsys
):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps(display) + "\n" + json.dumps(display) + "\n"),
    )
    event = {"row": "0:1", "action": "Pause", "minutes": 5}

    def show(initial, exchange):
        assert initial == display and exchange(event) == display

    monkeypatch.setattr(pause_controls, renderer, show)
    pause_controls.run_pause_child(provider)
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        event,
        None,
    ]


@pytest.mark.parametrize("text", ["", "[]\n", "not-json\n"])
def test_invalid_initial_snapshot_fails_before_display_without_mutation(
    text, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    with pytest.raises(SystemExit):
        pause_controls.run_pause_child("tkinter")
    assert capsys.readouterr().out.strip() == "__AI_GUARDIAN_MODAL_UNAVAILABLE__"
