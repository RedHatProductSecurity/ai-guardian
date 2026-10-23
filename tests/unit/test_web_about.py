"""Web About author attribution, without running the server or opening a browser."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages import about


def test_about_includes_named_author_profile_and_keeps_the_repository_link(monkeypatch):
    ui = MagicMock()
    monkeypatch.setattr(about, "ui", ui)
    monkeypatch.setattr(about, "create_sidebar", MagicMock())
    monkeypatch.setattr(about, "create_header", MagicMock())
    about.create_about_page(MagicMock(), "local")
    ui.label.assert_any_call("Author:")
    ui.label.assert_any_call("Dominique Vernier")
    ui.link.assert_any_call("(ITDoVe)", "https://github.com/itdove", new_tab=True)
    assert all(
        call.args[0] != "https://github.com/itdove" for call in ui.link.call_args_list
    )
    ui.link.assert_any_call(
        "GitHub Repository",
        "https://github.com/RedHatProductSecurity/ai-guardian",
        new_tab=True,
    )
