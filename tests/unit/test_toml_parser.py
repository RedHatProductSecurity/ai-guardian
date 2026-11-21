"""Tests for TOML pattern parser and rule compilation."""

import re

import pytest

from ai_guardian.patterns.toml_parser import (
    CompiledRule,
    compile_rule,
    load_and_compile,
    load_toml_file,
    validate_re2_compatible,
    validate_regex_safety,
)


class TestValidateRE2Compatible:

    def test_simple_regex_is_compatible(self):
        ok, reason = validate_re2_compatible(r"(sk-[A-Za-z0-9]{20,})")
        assert ok is True
        assert reason is None

    def test_unicode_property_rejected(self):
        ok, reason = validate_re2_compatible(r"\p{L}+")
        assert ok is False
        assert "Unicode property" in reason

    def test_negated_unicode_property_rejected(self):
        ok, reason = validate_re2_compatible(r"\P{N}+")
        assert ok is False
        assert "Unicode property" in reason

    def test_lookbehind_rejected(self):
        ok, reason = validate_re2_compatible(r"(?<=foo)bar")
        assert ok is False
        assert "Lookbehind" in reason

    def test_negative_lookbehind_rejected(self):
        ok, reason = validate_re2_compatible(r"(?<!foo)bar")
        assert ok is False
        assert "Lookbehind" in reason

    def test_atomic_group_rejected(self):
        ok, reason = validate_re2_compatible(r"(?>abc)")
        assert ok is False
        assert "Atomic group" in reason

    def test_lookahead_is_allowed(self):
        ok, reason = validate_re2_compatible(r"(?=foo)bar")
        assert ok is True

    def test_named_group_is_allowed(self):
        ok, reason = validate_re2_compatible(r"(?P<name>[a-z]+)")
        assert ok is True


class TestRegexSafety:
    @pytest.mark.parametrize("pattern", [r"^(a+)+$", r"^(a|aa)+$"])
    def test_rejects_backtracking_dos_shapes(self, pattern):
        safe, reason = validate_regex_safety(pattern)

        assert safe is False
        assert "repetition" in reason

    def test_compile_rule_rejects_backtracking_dos_shape(self):
        raw = {"id": "unsafe", "match_type": "regex", "regex": r"^(a+)+$"}

        with pytest.raises(ValueError, match="Unsafe regex"):
            compile_rule(raw, "secret")


class TestCompileRule:

    def test_compile_regex_rule(self):
        raw = {
            "id": "test-regex",
            "match_type": "regex",
            "regex": r"(sk-[A-Za-z0-9]{20,})",
            "description": "Test secret",
            "redaction_strategy": "preserve_prefix_suffix",
        }
        rule = compile_rule(raw, "secret")
        assert rule.id == "test-regex"
        assert rule.match_type == "regex"
        assert isinstance(rule.compiled, re.Pattern)
        assert rule.category == "secret"
        assert rule.metadata["description"] == "Test secret"
        assert rule.metadata["redaction_strategy"] == "preserve_prefix_suffix"

    def test_compile_regex_with_flags(self):
        raw = {
            "id": "test-flags",
            "match_type": "regex",
            "regex": r"hello world",
            "case_insensitive": True,
            "multiline": True,
        }
        rule = compile_rule(raw, "test")
        assert rule.compiled.flags & re.IGNORECASE
        assert rule.compiled.flags & re.MULTILINE

    def test_compile_literal_rule(self):
        raw = {
            "id": "homoglyph-a",
            "match_type": "literal",
            "source": "а",
            "target": "a",
            "script": "Cyrillic",
        }
        rule = compile_rule(raw, "unicode")
        assert rule.match_type == "literal"
        assert rule.compiled == ("а", "a")
        assert rule.metadata["script"] == "Cyrillic"

    def test_compile_cidr_rule(self):
        raw = {
            "id": "private-a",
            "match_type": "cidr",
            "cidr": "10.0.0.0/8",
            "description": "RFC 1918 Class A",
        }
        rule = compile_rule(raw, "ssrf")
        assert rule.match_type == "cidr"
        import ipaddress

        assert isinstance(rule.compiled, ipaddress.IPv4Network)

    def test_compile_range_rule(self):
        raw = {
            "id": "tag-chars",
            "match_type": "range",
            "start": 0xE0000,
            "end": 0xE007F,
            "description": "Unicode tag characters",
        }
        rule = compile_rule(raw, "unicode")
        assert rule.match_type == "range"
        assert rule.compiled == (0xE0000, 0xE007F)

    def test_compile_glob_rule(self):
        raw = {
            "id": "ignore-node-modules",
            "match_type": "glob",
            "glob": "**/node_modules/**",
        }
        rule = compile_rule(raw, "ignore")
        assert rule.match_type == "glob"
        assert rule.compiled == "**/node_modules/**"

    def test_invalid_match_type_raises(self):
        raw = {"id": "bad", "match_type": "unknown"}
        with pytest.raises(ValueError, match="unsupported match_type"):
            compile_rule(raw, "test")

    def test_empty_regex_raises(self):
        raw = {"id": "empty", "match_type": "regex", "regex": ""}
        with pytest.raises(ValueError, match="empty"):
            compile_rule(raw, "test")

    def test_invalid_regex_raises(self):
        raw = {"id": "bad-re", "match_type": "regex", "regex": "[invalid"}
        with pytest.raises(ValueError, match="invalid regex"):
            compile_rule(raw, "test")

    def test_re2_incompatible_regex_raises(self):
        raw = {"id": "re2-bad", "match_type": "regex", "regex": r"\p{L}+"}
        with pytest.raises(ValueError, match="RE2-incompatible"):
            compile_rule(raw, "test")

    def test_invalid_cidr_raises(self):
        raw = {"id": "bad-cidr", "match_type": "cidr", "cidr": "not-a-cidr"}
        with pytest.raises(ValueError, match="invalid CIDR"):
            compile_rule(raw, "test")

    def test_missing_literal_source_raises(self):
        raw = {"id": "bad-lit", "match_type": "literal", "target": "a"}
        with pytest.raises(ValueError, match="missing 'source'"):
            compile_rule(raw, "test")

    def test_missing_range_fields_raises(self):
        raw = {"id": "bad-range", "match_type": "range", "start": 0}
        with pytest.raises(ValueError, match="missing 'start' or 'end'"):
            compile_rule(raw, "test")

    def test_metadata_excludes_reserved_fields(self):
        raw = {
            "id": "meta-test",
            "match_type": "regex",
            "regex": r"test",
            "description": "A test",
            "custom_field": "custom_value",
        }
        rule = compile_rule(raw, "test")
        assert "regex" not in rule.metadata
        assert "id" not in rule.metadata
        assert "match_type" not in rule.metadata
        assert rule.metadata["description"] == "A test"
        assert rule.metadata["custom_field"] == "custom_value"


class TestLoadTomlFile:

    def test_load_valid_toml(self, tmp_path):
        toml_content = b"""
[[rules]]
id = "test-1"
match_type = "regex"
regex = "hello"
description = "Test rule"

[[rules]]
id = "test-2"
match_type = "literal"
source = "x"
target = "y"
"""
        path = tmp_path / "test.toml"
        path.write_bytes(toml_content)
        rules = load_toml_file(path)
        assert len(rules) == 2
        assert rules[0]["id"] == "test-1"
        assert rules[1]["id"] == "test-2"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_toml_file(tmp_path / "missing.toml")

    def test_empty_rules_returns_empty(self, tmp_path):
        path = tmp_path / "empty.toml"
        path.write_bytes(b"[metadata]\nversion = 1\n")
        rules = load_toml_file(path)
        assert rules == []


class TestLoadAndCompile:

    def test_compiles_valid_rules(self, tmp_path):
        toml_content = b"""
[[rules]]
id = "r1"
match_type = "regex"
regex = "secret-[0-9]+"
description = "Test secret"

[[rules]]
id = "r2"
match_type = "regex"
regex = "token-[a-z]+"
"""
        path = tmp_path / "test.toml"
        path.write_bytes(toml_content)
        compiled = load_and_compile(path, "test")
        assert len(compiled) == 2
        assert all(isinstance(r, CompiledRule) for r in compiled)

    def test_skips_invalid_rules_with_warning(self, tmp_path):
        toml_content = b"""
[[rules]]
id = "good"
match_type = "regex"
regex = "valid"

[[rules]]
id = "bad"
match_type = "regex"
regex = "[invalid"
"""
        path = tmp_path / "mixed.toml"
        path.write_bytes(toml_content)
        compiled = load_and_compile(path, "test")
        assert len(compiled) == 1
        assert compiled[0].id == "good"

    def test_category_assigned(self, tmp_path):
        toml_content = b"""
[[rules]]
id = "r1"
match_type = "regex"
regex = "test"
"""
        path = tmp_path / "test.toml"
        path.write_bytes(toml_content)
        compiled = load_and_compile(path, "my_category")
        assert compiled[0].category == "my_category"

    def test_skip_file_types_in_metadata(self, tmp_path):
        toml_content = b"""
[[rules]]
id = "yaml-only"
match_type = "regex"
regex = "password:\\\\s*\\\\S+"
skip_file_types = [".py", ".js", ".go"]
"""
        path = tmp_path / "test.toml"
        path.write_bytes(toml_content)
        compiled = load_and_compile(path, "secrets")
        assert compiled[0].metadata["skip_file_types"] == frozenset(
            [".py", ".js", ".go"]
        )

    def test_no_skip_file_types_absent_from_metadata(self, tmp_path):
        toml_content = b"""
[[rules]]
id = "universal"
match_type = "regex"
regex = "sk-[a-z]+"
"""
        path = tmp_path / "test.toml"
        path.write_bytes(toml_content)
        compiled = load_and_compile(path, "secrets")
        assert "skip_file_types" not in compiled[0].metadata
