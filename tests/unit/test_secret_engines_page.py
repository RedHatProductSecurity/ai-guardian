"""Tests for the Web Console secret-engine configuration helpers."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages import secret_engines


def test_toggle_engine_preserves_advanced_entries():
    engines = [
        {"type": "gitleaks", "extra_flags": ["--custom"]},
        "toml-patterns",
        {"type": "custom-extension", "binary": "/opt/scanner"},
    ]

    updated = secret_engines._toggle_engine(engines, "leaktk", True)

    assert updated == [*engines, "leaktk"]


def test_toggle_engine_removes_only_the_requested_engine():
    engines = [
        {"type": "gitleaks", "extra_flags": ["--custom"]},
        "leaktk",
        "toml-patterns",
    ]

    updated = secret_engines._toggle_engine(engines, "gitleaks", False)

    assert updated == ["leaktk", "toml-patterns"]


def test_toggle_default_engines_can_opt_out_of_toml_patterns():
    updated = secret_engines._toggle_engine(None, "toml-patterns", False)

    assert updated == ["gitleaks"]


def test_engine_inventory_comes_from_selected_daemon():
    target = object()
    service = Mock()
    service.get_target_by_name.return_value = target
    service.get_daemon_about.return_value = {
        "installed_scanners": ["gitleaks", "leaktk", "unknown"]
    }

    assert secret_engines._get_installed_engine_names(service, "remote") == {
        "gitleaks",
        "leaktk",
    }
    service.get_target_by_name.assert_called_once_with("remote")
    service.get_daemon_about.assert_called_once_with(target)


def test_engine_inventory_unavailable_for_old_daemon():
    service = Mock()
    service.get_target_by_name.return_value = object()
    service.get_daemon_about.return_value = {"scanners": []}

    assert secret_engines._get_installed_engine_names(service, "old-daemon") is None


def test_engine_inventory_unavailable_for_missing_target():
    service = Mock()
    service.get_target_by_name.return_value = None

    assert secret_engines._get_installed_engine_names(service, "offline") is None
    service.get_daemon_about.assert_not_called()


def test_save_engine_selection_preserves_other_config_and_engine_options(monkeypatch):
    config = {
        "secret_scanning": {
            "enabled": True,
            "execution_strategy": "consensus",
            "engines": [{"type": "gitleaks", "extra_flags": ["--custom"]}],
        },
        "unrelated": {"keep": True},
    }
    saved = []

    async def io_bound(function, *args):
        return function(*args)

    def save_config(value):
        saved.append(copy.deepcopy(value))
        return True

    monkeypatch.setattr(secret_engines, "run", SimpleNamespace(io_bound=io_bound))
    monkeypatch.setattr(
        secret_engines, "load_web_config", lambda: copy.deepcopy(config)
    )
    monkeypatch.setattr(secret_engines, "save_web_config", save_config)

    result, engines = asyncio.run(secret_engines._save_engine_selection("leaktk", True))

    assert result is True
    assert engines == [
        {"type": "gitleaks", "extra_flags": ["--custom"]},
        "leaktk",
    ]
    assert saved[0]["secret_scanning"]["execution_strategy"] == "consensus"
    assert saved[0]["unrelated"] == {"keep": True}


def test_save_engine_selection_persists_toml_patterns_opt_out(monkeypatch):
    config = {"secret_scanning": {"enabled": True}}

    async def io_bound(function, *args):
        return function(*args)

    def load_config():
        return copy.deepcopy(config)

    def save_config(value):
        config.clear()
        config.update(copy.deepcopy(value))
        return True

    monkeypatch.setattr(secret_engines, "run", SimpleNamespace(io_bound=io_bound))
    monkeypatch.setattr(secret_engines, "load_web_config", load_config)
    monkeypatch.setattr(secret_engines, "save_web_config", save_config)

    saved, engines = asyncio.run(
        secret_engines._save_engine_selection("toml-patterns", False)
    )

    assert saved is True
    assert engines == ["gitleaks"]
    assert config["secret_scanning"]["engines"] == ["gitleaks"]
