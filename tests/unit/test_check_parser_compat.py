"""Tests for scripts/check_parser_compat.py."""

import importlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = str(Path(__file__).parent.parent.parent / "scripts")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import check_parser_compat as cpc  # noqa: E402

importlib.reload(cpc)

SAMPLE_GITLEAKS_TOML = """\
[[rules]]
id = "aws-access-key"
description = "AWS Access Key"
regex = '''AKIA[A-Z0-9]{16}'''
keywords = ["AKIA"]
secretGroup = 0

[[rules]]
id = "github-pat"
description = "GitHub PAT"
regex = '''ghp_[A-Za-z0-9]{36}'''
keywords = ["ghp_"]
"""

SAMPLE_AI_GUARDIAN_TOML = """\
[[rules]]
id = "fixture-api-key"
match_type = "regex"
regex = '''(FIXTURE_KEY_[A-Za-z0-9]{20,})'''
redaction_strategy = "preserve_prefix_suffix"
description = "Test API Key (fixture)"
keywords = ["FIXTURE_KEY_"]

[[rules]]
id = "fixture-token"
match_type = "regex"
regex = '''(FIXTURE_TOKEN_[A-Za-z0-9]{36,})'''
redaction_strategy = "preserve_prefix_suffix"
description = "Test Token (fixture)"
keywords = ["FIXTURE_TOKEN_"]
"""


class TestFetchPatternData:

    def test_fetch_from_fixture_file(self):
        fixture = (
            Path(__file__).parent.parent
            / "fixtures"
            / "ai_guardian_native_patterns.toml"
        )
        with patch.object(cpc, "FIXTURE_PATH", fixture):
            result = cpc.fetch_pattern_data("ai-guardian")

        assert result is not None
        assert "rules" in result
        assert len(result["rules"]) == 3

    @patch.object(cpc, "fetch_url")
    def test_fetch_from_url_success(self, mock_fetch_url):
        mock_fetch_url.return_value = SAMPLE_GITLEAKS_TOML

        result = cpc.fetch_pattern_data("gitleaks")

        assert result is not None
        assert "rules" in result
        assert len(result["rules"]) == 2
        assert result["rules"][0]["id"] == "aws-access-key"

    @patch.object(cpc, "fetch_url")
    def test_fetch_from_url_failure(self, mock_fetch_url):
        mock_fetch_url.return_value = None

        result = cpc.fetch_pattern_data("gitleaks")
        assert result is None

    @patch.object(cpc, "fetch_url")
    def test_fetch_from_url_invalid_toml(self, mock_fetch_url):
        mock_fetch_url.return_value = "{{invalid toml content}}"

        result = cpc.fetch_pattern_data("gitleaks")
        assert result is None

    def test_fetch_from_missing_fixture(self):
        with patch.object(cpc, "FIXTURE_PATH", Path("/nonexistent/fixture.toml")):
            result = cpc.fetch_pattern_data("ai-guardian")
        assert result is None

    def test_fetch_unknown_format(self):
        result = cpc.fetch_pattern_data("unknown-format")
        assert result is None


class TestExtractSchema:

    def test_extract_schema_basic(self):
        data = {
            "rules": [
                {"id": "r1", "regex": "test", "description": "test rule"},
            ]
        }
        schema = cpc.extract_schema(data)
        assert "rules" in schema["top_level_keys"]
        assert "id" in schema["rule_fields"]
        assert "regex" in schema["rule_fields"]
        assert "description" in schema["rule_fields"]

    def test_extract_schema_empty_rules(self):
        schema = cpc.extract_schema({"rules": []})
        assert schema["rule_fields"] == set()

    def test_extract_schema_union_of_fields(self):
        data = {
            "rules": [
                {"id": "r1", "regex": "test"},
                {"id": "r2", "regex": "test2", "entropy": 3.5},
            ]
        }
        schema = cpc.extract_schema(data)
        assert "entropy" in schema["rule_fields"]
        assert "id" in schema["rule_fields"]
        assert "regex" in schema["rule_fields"]

    def test_extract_schema_no_rules_key(self):
        schema = cpc.extract_schema({"metadata": {"version": "1.0"}})
        assert schema["rule_fields"] == set()
        assert "metadata" in schema["top_level_keys"]


class TestCompareSchemas:

    def test_no_changes(self):
        actual = {"rule_fields": {"id", "regex", "description"}}
        expected = {
            "rule_fields": {"id", "regex", "description"},
            "required_rule_fields": {"id", "regex"},
        }
        result = cpc.compare_schemas(actual, expected)
        assert result["status"] == "ok"
        assert result["new_fields"] == []
        assert result["removed_fields"] == []

    def test_new_fields_detected(self):
        actual = {"rule_fields": {"id", "regex", "description", "new_field"}}
        expected = {
            "rule_fields": {"id", "regex", "description"},
            "required_rule_fields": {"id", "regex"},
        }
        result = cpc.compare_schemas(actual, expected)
        assert result["status"] == "warning"
        assert "new_field" in result["new_fields"]

    def test_removed_required_fields(self):
        actual = {"rule_fields": {"id", "description"}}
        expected = {
            "rule_fields": {"id", "regex", "description"},
            "required_rule_fields": {"id", "regex"},
        }
        result = cpc.compare_schemas(actual, expected)
        assert result["status"] == "changed"
        assert "regex" in result["missing_required"]

    def test_both_new_and_removed(self):
        actual = {"rule_fields": {"id", "description", "new_field"}}
        expected = {
            "rule_fields": {"id", "regex", "description"},
            "required_rule_fields": {"id", "regex"},
        }
        result = cpc.compare_schemas(actual, expected)
        assert result["status"] == "changed"
        assert "new_field" in result["new_fields"]
        assert "regex" in result["missing_required"]

    def test_removed_optional_fields_ok(self):
        actual = {"rule_fields": {"id", "regex"}}
        expected = {
            "rule_fields": {"id", "regex", "description"},
            "required_rule_fields": {"id", "regex"},
        }
        result = cpc.compare_schemas(actual, expected)
        assert result["status"] == "ok"


class TestRunCompatCheck:

    @patch.object(cpc, "fetch_pattern_data")
    def test_all_pass(self, mock_fetch):
        mock_fetch.side_effect = lambda fmt: {
            "gitleaks": {
                "rules": [
                    {
                        "id": "r1",
                        "description": "Test",
                        "regex": r"test_[A-Z]{10}",
                        "keywords": ["test_"],
                    },
                ]
            },
            "ai-guardian": {
                "rules": [
                    {"id": "r1", "match_type": "regex", "regex": r"test_[A-Z]{10}"},
                ]
            },
        }.get(fmt)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        exit_code = cpc.run_compat_check(output_path)
        assert exit_code == 0

        with open(output_path) as f:
            results = json.load(f)
        assert results["gitleaks"]["status"] == "OK"
        assert results["ai-guardian"]["status"] == "OK"

    @patch.object(cpc, "fetch_pattern_data")
    def test_parse_failure_empty_rules(self, mock_fetch):
        mock_fetch.side_effect = lambda fmt: {
            "gitleaks": {"rules": []},
            "ai-guardian": {
                "rules": [
                    {"id": "r1", "match_type": "regex", "regex": r"test_[A-Z]{10}"},
                ]
            },
        }.get(fmt)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        exit_code = cpc.run_compat_check(output_path)
        assert exit_code == 1

        with open(output_path) as f:
            results = json.load(f)
        assert results["gitleaks"]["status"] == "FAIL"
        assert results["ai-guardian"]["status"] == "OK"

    @patch.object(cpc, "fetch_pattern_data")
    def test_fetch_failure(self, mock_fetch):
        mock_fetch.return_value = None

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        exit_code = cpc.run_compat_check(output_path)
        assert exit_code == 1

    @patch.object(cpc, "fetch_pattern_data")
    def test_compile_with_some_invalid_rules(self, mock_fetch):
        mock_fetch.side_effect = lambda fmt: {
            "gitleaks": {
                "rules": [
                    {
                        "id": "r1",
                        "description": "Test",
                        "regex": r"valid_[A-Z]+",
                        "keywords": [],
                    },
                    {
                        "id": "r2",
                        "description": "Bad",
                        "regex": r"[invalid(",
                        "keywords": [],
                    },
                ]
            },
            "ai-guardian": {
                "rules": [
                    {"id": "r1", "match_type": "regex", "regex": r"test_[A-Z]{10}"},
                ]
            },
        }.get(fmt)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        exit_code = cpc.run_compat_check(output_path)
        assert exit_code == 0

        with open(output_path) as f:
            results = json.load(f)
        assert results["gitleaks"]["compiled_count"] >= 1


class TestRunFormatVersionCheck:

    @patch.object(cpc, "fetch_pattern_data")
    def test_no_changes(self, mock_fetch):
        mock_fetch.side_effect = lambda fmt: {
            "gitleaks": {
                "rules": [
                    {
                        "id": "r1",
                        "description": "Test",
                        "regex": r"test",
                        "keywords": [],
                        "secretGroup": 0,
                        "entropy": 3.0,
                        "allowlists": [],
                    },
                ]
            },
            "ai-guardian": {
                "rules": [
                    {
                        "id": "r1",
                        "match_type": "regex",
                        "regex": r"test",
                        "description": "Test",
                        "redaction_strategy": "full_redact",
                        "keywords": [],
                    },
                ]
            },
        }.get(fmt)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        exit_code = cpc.run_format_version_check(output_path)
        assert exit_code == 0

    @patch.object(cpc, "fetch_pattern_data")
    def test_with_new_field(self, mock_fetch):
        mock_fetch.side_effect = lambda fmt: {
            "gitleaks": {
                "rules": [
                    {
                        "id": "r1",
                        "description": "Test",
                        "regex": r"test",
                        "keywords": [],
                        "secretGroup": 0,
                        "entropy": 3.0,
                        "brand_new_field": "surprise",
                    },
                ]
            },
            "ai-guardian": {
                "rules": [
                    {
                        "id": "r1",
                        "match_type": "regex",
                        "regex": r"test",
                        "description": "Test",
                        "redaction_strategy": "full_redact",
                        "keywords": [],
                    },
                ]
            },
        }.get(fmt)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        exit_code = cpc.run_format_version_check(output_path)
        assert exit_code == 2

        with open(output_path) as f:
            results = json.load(f)
        assert results["gitleaks"]["status"] == "warning"
        assert "brand_new_field" in results["gitleaks"]["new_fields"]

    @patch.object(cpc, "fetch_pattern_data")
    def test_network_failure_graceful(self, mock_fetch):
        mock_fetch.return_value = None

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        exit_code = cpc.run_format_version_check(output_path)
        assert exit_code == 0


class TestPatternSourceResolution:

    def test_leaktk_url_from_pyproject(self):
        url = cpc.get_leaktk_url()
        assert "raw.githubusercontent.com" in url
        assert "leaktk/patterns" in url
        assert "gitleaks" in url

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_leaktk_url_fallback(self, mock_open):
        url = cpc.get_leaktk_url()
        assert url == f"{cpc.FALLBACK_LEAKTK_URL}{cpc.FALLBACK_LEAKTK_ENDPOINT}"


class TestJsonDefault:

    def test_set_serialization(self):
        result = json.dumps({"fields": {"b", "a", "c"}}, default=cpc._json_default)
        parsed = json.loads(result)
        assert parsed["fields"] == ["a", "b", "c"]

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            json.dumps({"obj": object()}, default=cpc._json_default)
