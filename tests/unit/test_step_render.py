"""Tests for inline session step content rendering (#2214)."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.components.step_render import (
    MAX_INLINE_CONTENT_CHARS,
    render_content_block,
    render_text_block,
)


def _chainable_element():
    element = MagicMock()
    element.classes.return_value = element
    element.style.return_value = element
    return element


def test_json_content_uses_syntax_highlighting():
    code_element = _chainable_element()

    with patch("ai_guardian.web.components.step_render.ui") as mock_ui:
        mock_ui.code.return_value = code_element
        render_text_block('{"status": "ok"}')

    mock_ui.code.assert_called_once_with('{"status": "ok"}', language="json")
    mock_ui.html.assert_not_called()


def test_python_and_yaml_content_use_syntax_highlighting():
    with patch("ai_guardian.web.components.step_render.ui") as mock_ui:
        mock_ui.code.return_value = _chainable_element()
        render_text_block("def greet():\n    return 'hello'")
        render_text_block("status: ok\ncount: 2")

    assert mock_ui.code.call_args_list[0].kwargs["language"] == "python"
    assert mock_ui.code.call_args_list[1].kwargs["language"] == "yaml"


def test_plain_text_keeps_existing_preformatted_rendering():
    html_element = _chainable_element()

    with patch("ai_guardian.web.components.step_render.ui") as mock_ui:
        mock_ui.html.return_value = html_element
        render_text_block("plain <text>")

    mock_ui.code.assert_not_called()
    rendered_html = mock_ui.html.call_args.args[0]
    assert "<pre" in rendered_html
    assert "plain &lt;text&gt;" in rendered_html


def test_highlighted_content_preserves_scroll_limit():
    code_element = _chainable_element()

    with patch("ai_guardian.web.components.step_render.ui") as mock_ui:
        mock_ui.code.return_value = code_element
        render_text_block('{"status": "ok"}', max_height=400)

    style = code_element.style.call_args.args[0]
    assert "max-height: 400px" in style
    assert "overflow-y: auto" in style


def test_oversized_content_uses_bounded_inline_preview():
    html_element = _chainable_element()
    content = "x" * (MAX_INLINE_CONTENT_CHARS + 100)

    with (
        patch("ai_guardian.web.components.step_render.ui") as mock_ui,
        patch("ai_guardian.web.components.content_viewer.render_view_button") as view,
    ):
        mock_ui.html.return_value = html_element
        render_content_block(content, step_label="Tool Result")

    rendered_html = mock_ui.html.call_args.args[0]
    assert "x" * MAX_INLINE_CONTENT_CHARS in rendered_html
    assert "Content truncated in the conversation view" in rendered_html
    view.assert_called_once()
