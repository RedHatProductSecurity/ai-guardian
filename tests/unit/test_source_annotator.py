"""Tests for source_annotator module — annotation insertion logic."""

import textwrap


class TestGetCommentPrefix:
    def test_python(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("test.py") == "#"
        assert get_comment_prefix("test.pyi") == "#"

    def test_javascript(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("app.js") == "//"
        assert get_comment_prefix("app.ts") == "//"
        assert get_comment_prefix("app.tsx") == "//"

    def test_go_rust(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("main.go") == "//"
        assert get_comment_prefix("main.rs") == "//"

    def test_sql_lua(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("query.sql") == "--"
        assert get_comment_prefix("init.lua") == "--"

    def test_unsupported(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("data.json") is None
        assert get_comment_prefix("page.html") is None
        assert get_comment_prefix("style.css") is None
        assert get_comment_prefix("config.xml") is None

    def test_case_insensitive_extension(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("test.PY") == "#"
        assert get_comment_prefix("app.JS") == "//"

    def test_yaml_toml(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("config.yml") == "#"
        assert get_comment_prefix("config.yaml") == "#"
        assert get_comment_prefix("settings.toml") == "#"

    def test_shell(self):
        from ai_guardian.ui.source_annotator import get_comment_prefix

        assert get_comment_prefix("run.sh") == "#"
        assert get_comment_prefix("run.bash") == "#"


class TestFindEnclosingMultilineString:
    def test_single_line_not_multiline(self, tmp_path):
        from ai_guardian.ui.source_annotator import find_enclosing_multiline_string

        f = tmp_path / "test.py"
        f.write_text('x = "hello"\ny = 42\n')
        assert find_enclosing_multiline_string(str(f), 1) is None

    def test_multiline_string_detected(self, tmp_path):
        from ai_guardian.ui.source_annotator import find_enclosing_multiline_string

        source = textwrap.dedent('''\
            x = 1
            msg = """
            this is a
            multi-line string
            """
            y = 2
        ''')
        f = tmp_path / "test.py"
        f.write_text(source)
        result = find_enclosing_multiline_string(str(f), 3)
        assert result is not None
        start, end = result
        assert start == 2
        assert end == 5

    def test_line_outside_multiline(self, tmp_path):
        from ai_guardian.ui.source_annotator import find_enclosing_multiline_string

        source = textwrap.dedent('''\
            x = 1
            msg = """multi"""
            y = 2
        ''')
        f = tmp_path / "test.py"
        f.write_text(source)
        assert find_enclosing_multiline_string(str(f), 1) is None
        assert find_enclosing_multiline_string(str(f), 3) is None

    def test_non_python_returns_none(self, tmp_path):
        from ai_guardian.ui.source_annotator import find_enclosing_multiline_string

        f = tmp_path / "test.js"
        f.write_text("const x = `multi\nline`;\n")
        assert find_enclosing_multiline_string(str(f), 1) is None

    def test_syntax_error_returns_none(self, tmp_path):
        from ai_guardian.ui.source_annotator import find_enclosing_multiline_string

        f = tmp_path / "test.py"
        f.write_text("def broken(\n")
        assert find_enclosing_multiline_string(str(f), 1) is None


class TestPrepareAnnotation:
    def test_inline_annotation(self, tmp_path):
        from ai_guardian.ui.source_annotator import prepare_annotation

        f = tmp_path / "test.py"
        f.write_text("x = 1\napi_key = 'secret'\ny = 2\n")
        result = prepare_annotation(str(f), 2)
        assert result is not None
        content, hl, ann_type = result
        assert ann_type == "inline"
        assert hl == 2
        assert "ai-guardian:allow" in content
        lines = content.splitlines()
        assert lines[1].endswith("# ai-guardian:allow")

    def test_block_annotation_multiline(self, tmp_path):
        from ai_guardian.ui.source_annotator import prepare_annotation

        source = textwrap.dedent('''\
            x = 1
            msg = """
            SSN: 123-45-6789
            """
            y = 2
        ''')
        f = tmp_path / "test.py"
        f.write_text(source)
        result = prepare_annotation(str(f), 3)
        assert result is not None
        content, hl, ann_type = result
        assert ann_type == "block"
        assert "ai-guardian:begin-allow" in content
        assert "ai-guardian:end-allow" in content

    def test_unsupported_file_returns_none(self, tmp_path):
        from ai_guardian.ui.source_annotator import prepare_annotation

        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}\n')
        assert prepare_annotation(str(f), 1) is None

    def test_out_of_range_line_returns_none(self, tmp_path):
        from ai_guardian.ui.source_annotator import prepare_annotation

        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        assert prepare_annotation(str(f), 100) is None
        assert prepare_annotation(str(f), 0) is None

    def test_javascript_inline(self, tmp_path):
        from ai_guardian.ui.source_annotator import prepare_annotation

        f = tmp_path / "app.js"
        f.write_text("const key = 'secret';\nconst x = 1;\n")
        result = prepare_annotation(str(f), 1)
        assert result is not None
        content, hl, ann_type = result
        assert ann_type == "inline"
        assert "// ai-guardian:allow" in content

    def test_sql_inline(self, tmp_path):
        from ai_guardian.ui.source_annotator import prepare_annotation

        f = tmp_path / "query.sql"
        f.write_text("SELECT * FROM users;\n")
        result = prepare_annotation(str(f), 1)
        assert result is not None
        content, _, _ = result
        assert "-- ai-guardian:allow" in content


class TestWriteAnnotatedSource:
    def test_writes_file(self, tmp_path):
        from ai_guardian.ui.source_annotator import write_annotated_source

        f = tmp_path / "test.py"
        f.write_text("original\n")
        assert write_annotated_source(str(f), "modified\n")
        assert f.read_text() == "modified\n"

    def test_returns_false_on_bad_path(self):
        from ai_guardian.ui.source_annotator import write_annotated_source

        assert not write_annotated_source("/nonexistent/dir/test.py", "content")


class TestGenerateSourcePreview:
    def test_generates_preview(self, tmp_path):
        from ai_guardian.ui.source_annotator import generate_source_preview

        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\nline4\nline5\n")
        result = generate_source_preview(str(f), 3, context_lines=2)
        assert result is not None
        orig, annotated, start, hl, ann_type = result
        assert "line3" in orig
        assert "ai-guardian:allow" in annotated
        assert ann_type == "inline"

    def test_unsupported_returns_none(self, tmp_path):
        from ai_guardian.ui.source_annotator import generate_source_preview

        f = tmp_path / "data.json"
        f.write_text('{"a": 1}\n')
        assert generate_source_preview(str(f), 1) is None
