"""USER EXPERIENCE: Organization-local secret rules augment bundled detection.

Manual verification:
1. Open the Web Console's Secrets → Secret Detection Settings page.
2. Confirm Custom Secret Detection Rules explains that rules augment bundled
   patterns, require the built-in TOML engine, and differ from output redaction.
3. Save a synthetic regex rule and verify it persists under
   ``secret_scanning.additional_patterns`` without changing unrelated settings.
4. Submit malformed JSON and an invalid rule; confirm each is rejected with an
   actionable message and the saved configuration remains unchanged.
5. With ``toml-patterns`` selected, verify a synthetic match is detected and a
   safe near-match is not. Select only an external engine and verify the docs'
   stated scope: custom rules are not applied by that engine.
"""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages import secrets


class FakeWidget:
    def __init__(self, **kwargs):
        self.value = kwargs.get("value")
        self.text = kwargs.get("text", "")
        self.on_change = None
        self.on_click = kwargs.get("on_click")
        self.event_handlers = {}

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

    def set_visibility(self, _visible):
        return None

    def clear(self):
        return None

    def disable(self):
        return None

    def on_value_change(self, callback):
        self.on_change = callback

    def on(self, name, callback):
        self.event_handlers[name] = callback


class FakeUI:
    def __init__(self):
        self.buttons = {}
        self.textareas = []
        self.labels = []
        self.timers = []
        self.notifications = []

    def __getattr__(self, name):
        if name in {
            "column",
            "card",
            "row",
            "expansion",
            "icon",
            "badge",
            "switch",
            "checkbox",
            "select",
            "input",
            "number",
            "textarea",
        }:
            return lambda *args, **kwargs: self._widget(name, *args, **kwargs)
        raise AttributeError(name)

    def _widget(self, name, *args, **kwargs):
        widget = FakeWidget(**kwargs)
        if name == "label":
            widget.text = args[0] if args else kwargs.get("text", "")
            self.labels.append(widget)
        elif name == "textarea":
            self.textareas.append(widget)
        return widget

    def label(self, text="", **kwargs):
        return self._widget("label", text, **kwargs)

    def button(self, label="", **kwargs):
        widget = FakeWidget(**kwargs)
        self.buttons[label] = widget
        return widget

    def timer(self, _delay, callback, **_kwargs):
        self.timers.append(callback)

    def notify(self, message, **kwargs):
        self.notifications.append((message, kwargs))


def _install_console_fakes(monkeypatch, config):
    saved_configs = []
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

    monkeypatch.setattr(secrets, "ui", ui)
    monkeypatch.setattr(secrets, "run", SimpleNamespace(io_bound=io_bound))
    monkeypatch.setattr(secrets, "create_sidebar", Mock())
    monkeypatch.setattr(secrets, "create_header", Mock())
    monkeypatch.setattr(secrets, "add_help_button", Mock())
    monkeypatch.setattr(secrets, "field_help_icon", Mock())
    monkeypatch.setattr(secrets, "load_web_config", load_config)
    monkeypatch.setattr(secrets, "load_web_config_global", lambda: {})
    monkeypatch.setattr(secrets, "save_web_config", save_config)
    monkeypatch.setattr(secrets, "is_web_config_read_only", lambda: False)
    monkeypatch.setattr(secrets, "_render_password_likelihood", Mock())
    monkeypatch.setattr(secrets, "_render_command_credential_scanning", Mock())
    monkeypatch.setattr(secrets, "_render_http_request_credential_scanning", Mock())
    return ui, saved_configs


@pytest.mark.asyncio
async def test_console_saves_valid_custom_detection_rules(monkeypatch):
    """USER EXPERIENCE: valid rule → saved in detection config, unrelated settings kept."""
    config = {
        "secret_scanning": {"enabled": True, "additional_patterns": []},
        "unrelated": {"preserve": True},
    }
    ui, saved_configs = _install_console_fakes(monkeypatch, config)

    secrets.create_secrets_page(None, "local")
    await ui.timers[0]()

    assert any(label.text == "Custom Secret Detection Rules" for label in ui.labels)
    assert any(
        "augment bundled detection patterns" in label.text
        and "external-only engines" in label.text.lower()
        and "secret_redaction.additional_patterns" in label.text
        for label in ui.labels
    )

    rule = {
        "id": "org-internal-token",
        "match_type": "regex",
        "regex": r"ORG_INTERNAL_TOKEN_[A-Z0-9]{16}",
        "description": "Synthetic organization token",
        "keywords": ["ORG_INTERNAL_TOKEN_"],
    }
    ui.textareas[0].value = json.dumps([rule])
    await ui.buttons["Save custom rules"].on_click()

    assert config["secret_scanning"]["additional_patterns"] == [rule]
    assert config["unrelated"] == {"preserve": True}
    assert saved_configs[-1]["secret_scanning"]["additional_patterns"] == [rule]
    assert any(
        message == "Custom secret detection rules saved"
        for message, _ in ui.notifications
    )


@pytest.mark.asyncio
async def test_console_rejects_invalid_custom_rule_without_saving(monkeypatch):
    """USER EXPERIENCE: malformed rule → actionable error and no config change."""
    config = {
        "secret_scanning": {
            "enabled": True,
            "additional_patterns": [
                {
                    "id": "existing-rule",
                    "match_type": "regex",
                    "regex": "EXISTING_[A-Z]+",
                }
            ],
        }
    }
    before = copy.deepcopy(config)
    ui, saved_configs = _install_console_fakes(monkeypatch, config)

    secrets.create_secrets_page(None, "local")
    await ui.timers[0]()
    ui.textareas[0].value = json.dumps(
        [{"id": "org-rule", "match_type": "literal", "regex": "ORG_[A-Z]+"}]
    )
    await ui.buttons["Save custom rules"].on_click()

    assert config == before
    assert saved_configs == []
    assert any(
        "match_type must be 'regex'" in message and "not saved" in message
        for message, _ in ui.notifications
    )


@pytest.mark.asyncio
async def test_console_rejects_malformed_json_without_saving(monkeypatch):
    """USER EXPERIENCE: invalid JSON → location-aware feedback, no config change."""
    config = {"secret_scanning": {"enabled": True, "additional_patterns": []}}
    ui, saved_configs = _install_console_fakes(monkeypatch, config)

    secrets.create_secrets_page(None, "local")
    await ui.timers[0]()
    ui.textareas[0].value = "[{"
    await ui.buttons["Save custom rules"].on_click()

    assert saved_configs == []
    assert any(
        "invalid JSON (line 1, column" in message for message, _ in ui.notifications
    )
