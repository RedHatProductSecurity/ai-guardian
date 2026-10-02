"""Tests for .aiguardignore.toml write API and JSON schema."""

import json
import os
import sys
from pathlib import Path

import pytest

HAS_TOML_W = True
try:
    import tomli_w
except ImportError:
    HAS_TOML_W = False

needs_toml_w = pytest.mark.skipif(not HAS_TOML_W, reason="tomli_w not installed")

HAS_JSONSCHEMA = True
try:
    import jsonschema
except ImportError:
    HAS_JSONSCHEMA = False

needs_jsonschema = pytest.mark.skipif(
    not HAS_JSONSCHEMA, reason="jsonschema not installed"
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ai_guardian"
    / "schemas"
    / "aiguardignore.schema.json"
)


@needs_toml_w
class TestAddIgnorePath:
    def test_creates_file_global(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        assert add_ignore_path("src/test.py", scanner_types=None, project_root=tmp_path)

        toml_path = tmp_path / ".aiguardignore.toml"
        assert toml_path.exists()
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "src/test.py" in data["allowlist"]["paths"]

    def test_creates_file_scanner_scope(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        assert add_ignore_path(
            "src/test.py", scanner_types=["secret_scanning"], project_root=tmp_path
        )

        toml_path = tmp_path / ".aiguardignore.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "src/test.py" in data["secret_scanning"]["allowlist"]["paths"]

    def test_deduplication(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        add_ignore_path("src/test.py", scanner_types=None, project_root=tmp_path)
        add_ignore_path("src/test.py", scanner_types=None, project_root=tmp_path)

        toml_path = tmp_path / ".aiguardignore.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        assert data["allowlist"]["paths"].count("src/test.py") == 1

    def test_preserves_existing(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        toml_path = tmp_path / ".aiguardignore.toml"
        toml_path.write_text('[allowlist]\npaths = ["existing/**"]\n')

        add_ignore_path("src/new.py", scanner_types=None, project_root=tmp_path)

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "existing/**" in data["allowlist"]["paths"]
        assert "src/new.py" in data["allowlist"]["paths"]

    def test_rejects_traversal(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        assert not add_ignore_path("../etc/passwd", project_root=tmp_path)

    def test_rejects_too_broad(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        assert not add_ignore_path("**", project_root=tmp_path)
        assert not add_ignore_path("*", project_root=tmp_path)

    def test_multiple_scanner_types(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        assert add_ignore_path(
            "src/test.py",
            scanner_types=["secret_scanning", "scan_pii"],
            project_root=tmp_path,
        )

        toml_path = tmp_path / ".aiguardignore.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "src/test.py" in data["secret_scanning"]["allowlist"]["paths"]
        assert "src/test.py" in data["scan_pii"]["allowlist"]["paths"]

    def test_unknown_scanner_type_skipped(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        assert add_ignore_path(
            "src/test.py",
            scanner_types=["nonexistent_scanner", "secret_scanning"],
            project_root=tmp_path,
        )

        toml_path = tmp_path / ".aiguardignore.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "nonexistent_scanner" not in data
        assert "src/test.py" in data["secret_scanning"]["allowlist"]["paths"]

    def test_cache_reset_after_write(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import (
            add_ignore_path,
            reset_cache,
        )

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda **kw: tmp_path
        )

        add_ignore_path("src/test.py", scanner_types=None, project_root=tmp_path)

        from ai_guardian import aiguardignore

        assert len(aiguardignore._cached_configs) == 0


@needs_toml_w
class TestGenerateAiguardignorePreview:
    def test_preview_global(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import (
            generate_aiguardignore_preview,
            reset_cache,
        )

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        text, line = generate_aiguardignore_preview(
            "src/test.py", scanner_types=None, project_root=tmp_path
        )
        assert "src/test.py" in text
        assert line >= 1

    def test_preview_scanner(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import (
            generate_aiguardignore_preview,
            reset_cache,
        )

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        text, line = generate_aiguardignore_preview(
            "src/test.py",
            scanner_types=["secret_scanning"],
            project_root=tmp_path,
        )
        assert "secret_scanning" in text
        assert "src/test.py" in text

    def test_preview_image_scanning(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import (
            generate_aiguardignore_preview,
            reset_cache,
        )

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        text, line = generate_aiguardignore_preview(
            "images/screenshot.png",
            scanner_types=["image_scanning"],
            project_root=tmp_path,
        )
        assert "image_scanning" in text
        assert "images/screenshot.png" in text


class TestMakeRelativePath:
    def test_relative_within_project(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import make_relative_path

        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        abs_path = str(tmp_path / "src" / "test.py")
        result = make_relative_path(abs_path, tmp_path)
        assert result == os.path.join("src", "test.py")

    def test_outside_project_returns_basename(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import make_relative_path

        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        result = make_relative_path("/totally/different/path/test.py", tmp_path)
        assert result == "test.py"


@needs_toml_w
class TestWriteAiguardignoreText:
    def test_writes_valid_toml(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import write_aiguardignore_text, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        toml_text = '[allowlist]\npaths = ["src/test.py"]\n'
        assert write_aiguardignore_text(toml_text, tmp_path)

        toml_path = tmp_path / ".aiguardignore.toml"
        assert toml_path.exists()
        content = toml_path.read_text()
        assert "src/test.py" in content

    def test_rejects_invalid_toml(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import write_aiguardignore_text, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        assert not write_aiguardignore_text("invalid [[ toml", tmp_path)


class TestValidateIgnorePath:
    def test_valid_path(self):
        from ai_guardian.ui.ignore_file_editor import validate_ignore_path

        valid, msg = validate_ignore_path("src/test.py")
        assert valid

    def test_empty_path(self):
        from ai_guardian.ui.ignore_file_editor import validate_ignore_path

        valid, msg = validate_ignore_path("")
        assert not valid

    def test_traversal_path(self):
        from ai_guardian.ui.ignore_file_editor import validate_ignore_path

        valid, msg = validate_ignore_path("../etc/passwd")
        assert not valid

    def test_too_broad(self):
        from ai_guardian.ui.ignore_file_editor import validate_ignore_path

        valid, _ = validate_ignore_path("**")
        assert not valid
        valid, _ = validate_ignore_path("*")
        assert not valid

    def test_glob_pattern_valid(self):
        from ai_guardian.ui.ignore_file_editor import validate_ignore_path

        valid, _ = validate_ignore_path("src/**/*.py")
        assert valid


class TestResolveScannertypes:
    def test_this_scanner(self):
        from ai_guardian.ui.ignore_file_editor import (
            resolve_scanner_types,
            SCOPE_THIS_SCANNER,
        )

        result = resolve_scanner_types(SCOPE_THIS_SCANNER, "secret_scanning", None)
        assert result == ["secret_scanning"]

    def test_all_scanners(self):
        from ai_guardian.ui.ignore_file_editor import (
            resolve_scanner_types,
            SCOPE_ALL_SCANNERS,
        )

        result = resolve_scanner_types(SCOPE_ALL_SCANNERS, "secret_scanning", None)
        assert result is None

    def test_select_scanners(self):
        from ai_guardian.ui.ignore_file_editor import (
            resolve_scanner_types,
            SCOPE_SELECT_SCANNERS,
        )

        result = resolve_scanner_types(
            SCOPE_SELECT_SCANNERS,
            "secret_scanning",
            ["secret_scanning", "scan_pii"],
        )
        assert result == ["secret_scanning", "scan_pii"]


class TestAskDecisionNewValues:
    def test_suppress_in_source_value(self):
        from ai_guardian.ui.ask_dialog import AskDecision

        assert AskDecision.SUPPRESS_IN_SOURCE.value == "suppress_in_source"

    def test_ignore_file_value(self):
        from ai_guardian.ui.ask_dialog import AskDecision

        assert AskDecision.IGNORE_FILE.value == "ignore_file"

    def test_ask_result_new_fields(self):
        from ai_guardian.ui.ask_dialog import AskResult, AskDecision

        result = AskResult(
            decision=AskDecision.IGNORE_FILE,
            ignore_path="src/test.py",
            ignore_scanner_types=["secret_scanning"],
        )
        assert result.ignore_path == "src/test.py"
        assert result.ignore_scanner_types == ["secret_scanning"]

    def test_ask_result_source_annotation(self):
        from ai_guardian.ui.ask_dialog import AskResult, AskDecision

        result = AskResult(
            decision=AskDecision.SUPPRESS_IN_SOURCE,
            source_annotation_saved=True,
        )
        assert result.source_annotation_saved


# ---------------------------------------------------------------------------
# JSON Schema validation
# ---------------------------------------------------------------------------


@needs_jsonschema
class TestAiguardignoreSchema:
    @pytest.fixture
    def schema(self):
        with open(SCHEMA_PATH) as f:
            return json.load(f)

    def test_schema_file_exists(self):
        assert SCHEMA_PATH.is_file()

    def test_schema_is_valid_json(self):
        with open(SCHEMA_PATH) as f:
            data = json.load(f)
        assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert data["type"] == "object"

    def test_valid_global_allowlist(self, schema):
        doc = {"allowlist": {"paths": ["tests/fixtures/**"]}}
        jsonschema.validate(doc, schema)

    def test_valid_scanner_section(self, schema):
        doc = {"secret_scanning": {"allowlist": {"paths": ["tests/**"]}}}
        jsonschema.validate(doc, schema)

    def test_valid_all_scanners(self, schema):
        doc = {
            "allowlist": {"paths": ["global/**"]},
            "secret_scanning": {"allowlist": {"paths": ["a.py"]}},
            "scan_pii": {"allowlist": {"paths": ["b.py"]}},
            "prompt_injection": {"allowlist": {"paths": ["c.md"]}},
            "config_file_scanning": {"allowlist": {"paths": ["d.json"]}},
            "context_poisoning": {"allowlist": {"paths": ["e.md"]}},
            "supply_chain": {"allowlist": {"paths": ["f.sh"]}},
            "image_scanning": {"allowlist": {"paths": ["g.png"]}},
        }
        jsonschema.validate(doc, schema)

    def test_empty_document_valid(self, schema):
        jsonschema.validate({}, schema)

    def test_unknown_top_level_key_rejected(self, schema):
        doc = {"unknown_scanner": {"allowlist": {"paths": ["x"]}}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, schema)

    def test_unknown_scanner_subkey_rejected(self, schema):
        doc = {"secret_scanning": {"unknown_key": True}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, schema)

    def test_paths_must_be_array(self, schema):
        doc = {"allowlist": {"paths": "not-an-array"}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, schema)

    def test_paths_items_must_be_strings(self, schema):
        doc = {"allowlist": {"paths": [123]}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, schema)

    def test_scanner_types_match_code(self, schema):
        from ai_guardian.aiguardignore import SCANNER_TYPES

        schema_scanners = {k for k in schema["properties"] if k != "allowlist"}
        assert schema_scanners == SCANNER_TYPES


# ---------------------------------------------------------------------------
# Schema header in generated files
# ---------------------------------------------------------------------------


@needs_toml_w
class TestSchemaHeader:
    def test_new_file_has_schema_header(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        add_ignore_path("src/test.py", scanner_types=None, project_root=tmp_path)

        content = (tmp_path / ".aiguardignore.toml").read_text()
        assert content.startswith("#:schema ")

    def test_existing_file_no_duplicate_header(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import add_ignore_path, reset_cache

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        toml_path = tmp_path / ".aiguardignore.toml"
        toml_path.write_text('[allowlist]\npaths = ["existing/**"]\n')

        add_ignore_path("src/new.py", scanner_types=None, project_root=tmp_path)

        content = toml_path.read_text()
        assert not content.startswith("#:schema ")

    def test_preview_new_file_has_schema_header(self, tmp_path, monkeypatch):
        from ai_guardian.aiguardignore import (
            generate_aiguardignore_preview,
            reset_cache,
        )

        reset_cache()
        monkeypatch.setattr(
            "ai_guardian.aiguardignore.find_project_root", lambda: tmp_path
        )

        text, _ = generate_aiguardignore_preview("src/test.py", project_root=tmp_path)
        assert text.startswith("#:schema ")
