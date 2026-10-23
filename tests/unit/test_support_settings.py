"""Support configuration, Web Console selectors, and readiness contracts."""

import ast
import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_schema_defaults_profiles_and_example_are_consistent():
    import jsonschema
    from ai_guardian.setup.config import _get_default_config_template

    schema = json.loads(
        (ROOT / "src/ai_guardian/schemas/ai-guardian-config.schema.json").read_text()
    )
    support_schema = schema["definitions"]["support"]
    assert (
        support_schema["properties"]["export_destination"]["default"]
        == "github-discussions"
    )
    assert support_schema["properties"]["github_category"]["enum"] == [
        "bug-reports",
        "q-a",
    ]
    configs = [
        _get_default_config_template(permissive=False),
        json.loads((ROOT / "ai-guardian-example.json").read_text()),
    ]
    for path in (ROOT / "src/ai_guardian/templates/profiles").glob("*.json"):
        profile = json.loads(path.read_text())
        if "support" in profile:
            configs.append(profile)
    for config in configs:
        assert config["support"]["export_destination"] == "github-discussions"
        assert config["support"]["github_category"] == "bug-reports"
        jsonschema.validate(config["support"], support_schema)
    for category in ("polls", "announcements", "general", "D_arbitrary"):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"github_category": category}, support_schema)


def test_readiness_checks_new_defaults_without_publication():
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release-readiness.yml").read_text()
    )
    steps = workflow["jobs"]["fresh-install"]["steps"]
    step = next(
        s
        for s in steps
        if s.get("name") == "Verify support defaults and explicit legacy destinations"
    )
    assert "ai-guardian support prepare --help" in step["run"]
    python = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    ast.parse(python)
    assert '"bug-reports", "q-a"' in python
    assert '== "local"' in python
    assert "send_bundle(" not in python
    assert "prepare_bundle(" not in python


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "saved",
    [
        {},
        {"support": {"export_destination": ""}},
        {
            "support": {
                "export_destination": "github-discussions",
                "github_category": "q-a",
            }
        },
    ],
)
async def test_web_support_settings_round_trip_preserves_selection(monkeypatch, saved):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.web.pages import mcp_servers as page

    controls = {}
    buttons = {}
    timers = []
    ui = MagicMock()

    def control(**kwargs):
        widget = MagicMock()
        widget.value = kwargs.get("value")
        widget.classes.return_value = widget
        widget.props.return_value = widget
        controls[kwargs.get("label", "Proactive level")] = widget
        if "options" in kwargs:
            widget.options = kwargs["options"]
        return widget

    ui.select.side_effect = control
    ui.input.side_effect = control

    def button(label, **kwargs):
        buttons[label] = kwargs["on_click"]
        return MagicMock()

    ui.button.side_effect = button
    ui.timer.side_effect = lambda delay, callback, **kwargs: timers.append(callback)
    save = Mock()

    async def io_bound(function, *args):
        return function(*args)

    monkeypatch.setattr(page, "ui", ui)
    monkeypatch.setattr(page, "run", MagicMock(io_bound=io_bound))
    monkeypatch.setattr(page, "create_header", Mock())
    monkeypatch.setattr(page, "create_sidebar", Mock())
    monkeypatch.setattr(page, "load_web_config", lambda: copy.deepcopy(saved))
    monkeypatch.setattr(page, "save_web_config", save)
    page.create_mcp_servers_page(None, "local")
    await timers[0]()
    category = controls["Discussion category"]
    assert category.options == {"bug-reports": "Bug Reports", "q-a": "Q&A"}
    await buttons["Save"]()
    original_dest = (
        saved.get("support", {}).get("export_destination") or "github-discussions"
    )
    assert save.call_args.args[0]["support"]["export_destination"] == original_dest
    controls["Support channel"].value = "github-discussions"
    category.value = "q-a"
    await buttons["Save"]()
    assert (
        save.call_args.args[0]["support"]["export_destination"] == "github-discussions"
    )
    assert save.call_args.args[0]["support"]["github_category"] == "q-a"
    save.reset_mock()
    category.value = "polls"
    await buttons["Save"]()
    save.assert_not_called()
