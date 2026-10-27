"""Opt-in SSH discovery defaults agree across all persistent config surfaces."""

import json
from pathlib import Path

import jsonschema
import pytest

from ai_guardian.daemon.ssh_config import DEFAULT_SETTINGS
from ai_guardian.setup.config import _get_default_config_template, create_default_config

ROOT = Path(__file__).resolve().parents[2]


def test_schema_setup_example_profiles_and_create_config_agree():
    schema = json.loads(
        (ROOT / "src/ai_guardian/schemas/ai-guardian-config.schema.json").read_text()
    )
    definition = schema["definitions"]["daemon"]["properties"]["tray"]["properties"][
        "ssh_alias_discovery"
    ]
    configurations = [
        _get_default_config_template(),
        json.loads((ROOT / "ai-guardian-example.json").read_text()),
    ]
    success, rendered = create_default_config(json_output=True)
    assert success
    configurations.append(json.loads(rendered))
    for profile in ("minimal", "standard", "strict", "moderator"):
        configurations.append(
            json.loads(
                (
                    ROOT / f"src/ai_guardian/templates/profiles/{profile}.json"
                ).read_text()
            )
        )
    for config in configurations:
        settings = config["daemon"]["tray"]["ssh_alias_discovery"]
        assert settings == DEFAULT_SETTINGS
        jsonschema.validate(settings, definition)
    for key, value in DEFAULT_SETTINGS.items():
        assert definition["properties"][key]["default"] == value
    jsonschema.validate({"enabled": True, "alias_prefix": ""}, definition)
    for invalid in (
        {"enabled": "true"},
        {"alias_prefix": "*"},
        {"alias_prefix": "a" * 254},
        {"unknown": True},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, definition)
