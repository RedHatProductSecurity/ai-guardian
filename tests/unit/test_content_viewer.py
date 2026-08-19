"""Tests for the content viewer component (#2025)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.web.components.content_viewer import (
    _escape_html,
    detect_content_type,
    format_content,
    show_content_viewer,
)


class TestDetectContentType:
    def test_valid_json_object(self):
        assert detect_content_type('{"key": "value"}') == "json"

    def test_valid_json_array(self):
        assert detect_content_type("[1, 2, 3]") == "json"

    def test_json_with_whitespace(self):
        assert detect_content_type('  \n{"key": "value"}') == "json"

    def test_invalid_json_with_brace(self):
        assert detect_content_type("{not valid json}") != "json"

    def test_python_def(self):
        assert detect_content_type("def hello():\n    print('hi')") == "python"

    def test_python_class(self):
        assert detect_content_type("class MyClass:\n    pass") == "python"

    def test_python_import(self):
        assert detect_content_type("import os\nimport sys") == "python"

    def test_python_from_import(self):
        assert detect_content_type("from os.path import join") == "python"

    def test_python_decorator(self):
        assert detect_content_type("@pytest.fixture\ndef fix():\n    pass") == "python"

    def test_javascript_function(self):
        assert detect_content_type("function hello() {\n  return 1;\n}") == "javascript"

    def test_javascript_const(self):
        assert detect_content_type("const x = 42;\nconst y = 'hello';") == "javascript"

    def test_javascript_let(self):
        assert detect_content_type("let items = [];\nlet count = 0;") == "javascript"

    def test_javascript_arrow(self):
        assert detect_content_type("=> {\n  doStuff();\n}") == "javascript"

    def test_javascript_import_from(self):
        assert detect_content_type("import React from 'react';\n") == "javascript"

    def test_javascript_export(self):
        assert detect_content_type("export default App;\n") == "javascript"

    def test_yaml_detected(self):
        assert detect_content_type("name: test\nversion: 1.0\n") == "yaml"

    def test_plain_text(self):
        assert detect_content_type("Hello world, this is plain text.") == "plain"

    def test_empty_string(self):
        assert detect_content_type("") == "plain"

    def test_multiline_plain(self):
        assert detect_content_type("line 1\nline 2\nline 3") == "plain"


class TestFormatContent:
    def test_json_pretty_prints(self):
        raw = '{"b":2,"a":1}'
        formatted, lang = format_content(raw, "json")
        assert lang == "json"
        parsed = json.loads(formatted)
        assert parsed == {"b": 2, "a": 1}
        assert "\n" in formatted

    def test_json_invalid_passthrough(self):
        raw = "{broken json"
        formatted, lang = format_content(raw, "json")
        assert lang == "json"
        assert formatted == raw

    def test_python_passthrough(self):
        raw = "def hello():\n    pass"
        formatted, lang = format_content(raw, "python")
        assert lang == "python"
        assert formatted == raw

    def test_javascript_passthrough(self):
        raw = "const x = 42;"
        formatted, lang = format_content(raw, "javascript")
        assert lang == "javascript"
        assert formatted == raw

    def test_yaml_passthrough(self):
        raw = "key: value"
        formatted, lang = format_content(raw, "yaml")
        assert lang == "yaml"
        assert formatted == raw

    def test_plain_no_language(self):
        raw = "hello world"
        formatted, lang = format_content(raw, "plain")
        assert lang is None
        assert formatted == raw


class TestEscapeHtml:
    def test_escapes_angle_brackets(self):
        assert _escape_html("<div>") == "&lt;div&gt;"

    def test_escapes_ampersand(self):
        assert _escape_html("a & b") == "a &amp; b"

    def test_escapes_quotes(self):
        assert _escape_html("\"hello'") == "&quot;hello&#x27;"

    def test_plain_text_unchanged(self):
        assert _escape_html("hello world") == "hello world"


class TestShowContentViewer:
    def _make_chainable(self):
        mock = MagicMock()
        mock.classes.return_value = mock
        mock.style.return_value = mock
        mock.props.return_value = mock
        mock.tooltip.return_value = mock
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    def test_dialog_has_persistent_prop(self):
        mock_ui = MagicMock()
        mock_dialog = self._make_chainable()
        mock_ui.dialog.return_value = mock_dialog
        mock_ui.card.return_value = self._make_chainable()
        mock_ui.row.return_value = self._make_chainable()
        mock_ui.scroll_area.return_value = self._make_chainable()
        mock_ui.label.return_value = self._make_chainable()
        mock_ui.badge.return_value = self._make_chainable()
        mock_ui.button.return_value = self._make_chainable()
        mock_ui.code.return_value = self._make_chainable()

        nicegui_mod = MagicMock()
        nicegui_mod.ui = mock_ui
        with patch.dict("sys.modules", {"nicegui": nicegui_mod}):
            show_content_viewer("Test", '{"key": "value"}')

        mock_dialog.props.assert_called_once_with("persistent")
        mock_dialog.open.assert_called_once()
