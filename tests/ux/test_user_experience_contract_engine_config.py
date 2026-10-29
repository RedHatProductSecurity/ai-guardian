"""Engine Configuration Console interaction contract.

Manual verification:
1. Open Console → Engine Config for a daemon with Gitleaks and LeakTK installed.
2. With no configured engine list, confirm built-in TOML patterns and Gitleaks
   are selected by default; built-in TOML patterns are labeled separately.
3. Toggle LeakTK and confirm the configuration is saved without clicking Save,
   the JSON preview updates, and unrelated strategy/advanced engine settings stay.
4. Edit the advanced JSON without saving; confirm engine checkboxes do not discard
   the edit and ask the user to save or reload first.
5. Repeat against an older daemon and confirm the page explains that its installed
   engine inventory is unavailable rather than claiming local workstation binaries.
6. Clear Built-in TOML patterns, then click Reload; confirm the opt-out remains
   saved and the checkbox stays clear.
"""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages import secret_engines


class FakeWidget:
    def __init__(self, **kwargs):
        self.value = kwargs.get("value")
        self.text = kwargs.get("text", "")
        self.on_change = None
        self.event_handlers = {}
        self.visible = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def classes(self, *_args, **_kwargs):
        return self

    def props(self, *_args, **_kwargs):
        return self

    def style(self, *_args, **_kwargs):
        return self

    def bind_visibility_from(self, *_args, **_kwargs):
        return self

    def set_visibility(self, visible):
        self.visible = visible

    def clear(self):
        return None

    def on_value_change(self, callback):
        self.on_change = callback

    def on(self, name, callback):
        self.event_handlers[name] = callback

    async def trigger_change(self, value):
        self.value = value
        await self.on_change(SimpleNamespace(value=value))


class FakeUI:
    def __init__(self):
        self.buttons = {}
        self.checkboxes = {}
        self.textareas = []
        self.labels = []
        self.timers = []
        self.notifications = []

    def column(self, *_args, **kwargs):
        return FakeWidget(**kwargs)

    def card(self, *_args, **kwargs):
        return FakeWidget(**kwargs)

    def row(self, *_args, **kwargs):
        return FakeWidget(**kwargs)

    def expansion(self, *_args, **kwargs):
        return FakeWidget(**kwargs)

    def label(self, text="", **kwargs):
        widget = FakeWidget(text=text, **kwargs)
        self.labels.append(widget)
        return widget

    def select(self, **kwargs):
        return FakeWidget(**kwargs)

    def input(self, **kwargs):
        return FakeWidget(**kwargs)

    def checkbox(self, label, **kwargs):
        widget = FakeWidget(**kwargs)
        self.checkboxes[label] = widget
        return widget

    def textarea(self, **kwargs):
        widget = FakeWidget(**kwargs)
        self.textareas.append(widget)
        return widget

    def code(self, *_args, **kwargs):
        return FakeWidget(**kwargs)

    def button(self, label, **kwargs):
        widget = FakeWidget()
        widget.on_click = kwargs.get("on_click")
        self.buttons[label] = widget
        return widget

    def timer(self, _delay, callback, **_kwargs):
        self.timers.append(callback)

    def notify(self, message, **kwargs):
        self.notifications.append((message, kwargs))


@pytest.mark.asyncio
async def test_checkbox_auto_saves_and_updates_engine_json(monkeypatch):
    """USER EXPERIENCE: select installed engine → config and JSON update immediately."""
    config = {
        "secret_scanning": {
            "enabled": True,
            "execution_strategy": "consensus",
            "engines": [{"type": "gitleaks", "extra_flags": ["--custom"]}],
        },
        "unrelated": {"keep": True},
    }
    saved_configs = []
    service = Mock()
    service.get_target_by_name.return_value = object()
    service.get_daemon_about.return_value = {
        "installed_scanners": ["gitleaks", "leaktk"]
    }
    ui = FakeUI()

    async def io_bound(function, *args):
        return function(*args)

    def load_config():
        return copy.deepcopy(config)

    def save_config(value):
        config.clear()
        config.update(copy.deepcopy(value))
        saved_configs.append(copy.deepcopy(value))
        return True

    monkeypatch.setattr(secret_engines, "ui", ui)
    monkeypatch.setattr(secret_engines, "run", SimpleNamespace(io_bound=io_bound))
    monkeypatch.setattr(secret_engines, "create_sidebar", Mock())
    monkeypatch.setattr(secret_engines, "create_header", Mock())
    monkeypatch.setattr(secret_engines, "load_web_config", load_config)
    monkeypatch.setattr(secret_engines, "save_web_config", save_config)

    secret_engines.create_secret_engines_page(service, "remote")
    await ui.timers[0]()

    assert ui.checkboxes["Built-in TOML patterns (built-in)"].value is False
    gitleaks = ui.checkboxes["gitleaks (installed)"]
    leaktk = ui.checkboxes["leaktk (installed)"]
    assert gitleaks.value is True
    assert leaktk.value is False

    await leaktk.trigger_change(True)

    assert config["secret_scanning"]["engines"] == [
        {"type": "gitleaks", "extra_flags": ["--custom"]},
        "leaktk",
    ]
    assert config["secret_scanning"]["execution_strategy"] == "consensus"
    assert config["unrelated"] == {"keep": True}
    assert json.loads(ui.textareas[0].value) == config["secret_scanning"]["engines"]
    assert len(saved_configs) == 1
    assert any("leaktk added to" in message for message, _ in ui.notifications)


@pytest.mark.asyncio
async def test_default_toml_opt_out_saves_and_survives_reload(monkeypatch):
    """USER EXPERIENCE: default TOML selection can be intentionally saved off."""
    config = {"secret_scanning": {"enabled": True}}
    saved_configs = []
    service = Mock()
    service.get_target_by_name.return_value = object()
    service.get_daemon_about.return_value = {"installed_scanners": ["gitleaks"]}
    ui = FakeUI()

    async def io_bound(function, *args):
        return function(*args)

    def load_config():
        return copy.deepcopy(config)

    def save_config(value):
        config.clear()
        config.update(copy.deepcopy(value))
        saved_configs.append(copy.deepcopy(value))
        return True

    monkeypatch.setattr(secret_engines, "ui", ui)
    monkeypatch.setattr(secret_engines, "run", SimpleNamespace(io_bound=io_bound))
    monkeypatch.setattr(secret_engines, "create_sidebar", Mock())
    monkeypatch.setattr(secret_engines, "create_header", Mock())
    monkeypatch.setattr(secret_engines, "load_web_config", load_config)
    monkeypatch.setattr(secret_engines, "save_web_config", save_config)

    secret_engines.create_secret_engines_page(service, "remote")
    await ui.timers[0]()

    toml_checkbox = ui.checkboxes["Built-in TOML patterns (built-in)"]
    assert toml_checkbox.value is True
    assert ui.checkboxes["gitleaks (installed)"].value is True
    assert any("Clear its checkbox to opt out" in label.text for label in ui.labels)

    await toml_checkbox.trigger_change(False)

    assert config["secret_scanning"]["engines"] == ["gitleaks"]
    assert saved_configs[-1]["secret_scanning"]["engines"] == ["gitleaks"]

    await ui.buttons["Reload"].on_click()

    assert ui.checkboxes["Built-in TOML patterns (built-in)"].value is False
    assert ui.checkboxes["gitleaks (installed)"].value is True
    assert config["secret_scanning"]["engines"] == ["gitleaks"]


@pytest.mark.asyncio
async def test_unsaved_advanced_json_is_not_discarded_by_checkbox(monkeypatch):
    """USER EXPERIENCE: unsaved expert JSON → checkbox waits for save/reload."""
    config = {"secret_scanning": {"engines": ["gitleaks"]}}
    service = Mock()
    service.get_target_by_name.return_value = object()
    service.get_daemon_about.return_value = {"installed_scanners": ["gitleaks"]}
    ui = FakeUI()

    async def io_bound(function, *args):
        return function(*args)

    monkeypatch.setattr(secret_engines, "ui", ui)
    monkeypatch.setattr(secret_engines, "run", SimpleNamespace(io_bound=io_bound))
    monkeypatch.setattr(secret_engines, "create_sidebar", Mock())
    monkeypatch.setattr(secret_engines, "create_header", Mock())
    monkeypatch.setattr(
        secret_engines, "load_web_config", lambda: copy.deepcopy(config)
    )
    save_config = Mock(return_value=True)
    monkeypatch.setattr(secret_engines, "save_web_config", save_config)

    secret_engines.create_secret_engines_page(service, "remote")
    await ui.timers[0]()
    editor = ui.textareas[0]
    editor.value = '["gitleaks", "leaktk"]'
    editor.event_handlers["update:model-value"](SimpleNamespace(args=editor.value))

    await ui.checkboxes["gitleaks (installed)"].trigger_change(False)

    save_config.assert_not_called()
    assert editor.value == '["gitleaks", "leaktk"]'
    assert ui.checkboxes["gitleaks (installed)"].value is True
    assert any("Save or reload" in message for message, _ in ui.notifications)
