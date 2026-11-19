"""Tests for PatternCache — pre-compiled pattern store."""

import pytest

from ai_guardian.patterns.cache import PatternCache


@pytest.fixture
def secrets_toml(tmp_path):
    content = b"""
[[rules]]
id = "test-api-key"
match_type = "regex"
regex = '''(sk-[A-Za-z0-9]{20,})'''
redaction_strategy = "preserve_prefix_suffix"
description = "Test API Key"
keywords = ["sk-"]

[[rules]]
id = "test-token"
match_type = "regex"
regex = '''(ghp_[A-Za-z0-9]{36,})'''
redaction_strategy = "preserve_prefix_suffix"
description = "GitHub Token"
"""
    path = tmp_path / "secrets.toml"
    path.write_bytes(content)
    return path


@pytest.fixture
def pii_toml(tmp_path):
    content = b"""
[[rules]]
id = "pii-credit-card"
match_type = "regex"
regex = '''\\b(?:\\d{4}[- ]?){3}\\d{4}\\b'''
redaction_strategy = "credit_card"
validation = "luhn"
description = "Credit Card Number"
pii_type = "credit_card"

[[rules]]
id = "pii-email"
match_type = "regex"
regex = '''\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b'''
redaction_strategy = "pii_email"
description = "Email Address"
pii_type = "email"
"""
    path = tmp_path / "pii.toml"
    path.write_bytes(content)
    return path


@pytest.fixture
def unicode_toml(tmp_path):
    content = (
        "[[rules]]\n"
        'id = "homoglyph-cyrillic-a"\n'
        'match_type = "literal"\n'
        'source = "а"\n'
        'target = "a"\n'
        'script = "Cyrillic"\n'
        "\n"
        "[[rules]]\n"
        'id = "tag-chars"\n'
        'match_type = "range"\n'
        "start = 917504\n"
        "end = 917631\n"
        'description = "Unicode tag characters"\n'
    ).encode("utf-8")
    path = tmp_path / "unicode.toml"
    path.write_bytes(content)
    return path


@pytest.fixture
def ssrf_toml(tmp_path):
    content = b"""
[[rules]]
id = "ssrf-private-a"
match_type = "cidr"
cidr = "10.0.0.0/8"
description = "Private network Class A"

[[rules]]
id = "ssrf-loopback"
match_type = "cidr"
cidr = "127.0.0.0/8"
description = "Loopback"
"""
    path = tmp_path / "ssrf.toml"
    path.write_bytes(content)
    return path


class TestPatternCacheLoad:

    def test_load_single_file(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        assert cache.rule_count == 2
        assert cache.loaded_at is not None

    def test_load_multiple_files(self, secrets_toml, pii_toml):
        cache = PatternCache()
        cache.load(secrets_toml, pii_toml)
        assert cache.rule_count == 4

    def test_load_with_additional_rules(self, secrets_toml):
        cache = PatternCache()
        extra = [{"id": "extra-1", "match_type": "regex", "regex": "extra-pattern"}]
        cache.load(secrets_toml, additional_rules=extra)
        assert cache.rule_count == 3

    def test_load_clears_previous(self, secrets_toml, pii_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        assert cache.rule_count == 2
        cache.load(pii_toml)
        assert cache.rule_count == 2

    def test_load_rules_additive(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        assert cache.rule_count == 2
        cache.load_rules([{"id": "extra", "match_type": "regex", "regex": "test"}])
        assert cache.rule_count == 3

    def test_categories_from_filename(self, secrets_toml, pii_toml):
        cache = PatternCache()
        cache.load(secrets_toml, pii_toml)
        categories = cache.get_categories()
        assert "secrets" in categories
        assert "pii" in categories

    def test_category_override(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml, category_override="my_secrets")
        categories = cache.get_categories()
        assert "my_secrets" in categories
        assert "secrets" not in categories

    def test_get_rules_filtered(self, secrets_toml, pii_toml):
        cache = PatternCache()
        cache.load(secrets_toml, pii_toml)
        secret_rules = cache.get_rules(category="secrets")
        assert len(secret_rules) == 2
        pii_rules = cache.get_rules(category="pii")
        assert len(pii_rules) == 2

    def test_get_rules_unfiltered(self, secrets_toml, pii_toml):
        cache = PatternCache()
        cache.load(secrets_toml, pii_toml)
        all_rules = cache.get_rules()
        assert len(all_rules) == 4

    def test_missing_file_does_not_crash(self, tmp_path):
        cache = PatternCache()
        cache.load(tmp_path / "nonexistent.toml")
        assert cache.rule_count == 0


class TestPatternCacheScan:

    def test_scan_regex_finds_match(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        findings = cache.scan("Here is sk-abcdefghijklmnopqrstuvwxyz a key")
        assert len(findings) == 1
        assert findings[0].rule_id == "test-api-key"
        assert findings[0].line_number == 1

    def test_scan_regex_no_match(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        findings = cache.scan("Nothing secret here")
        assert len(findings) == 0

    def test_scan_category_filter(self, secrets_toml, pii_toml):
        cache = PatternCache()
        cache.load(secrets_toml, pii_toml)
        findings = cache.scan(
            "sk-abcdefghijklmnopqrstuvwxyz and user@example.com",
            categories=["pii"],
        )
        assert all(f.category == "pii" for f in findings)

    def test_scan_multiline_line_numbers(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        text = "line1\nline2\nsk-abcdefghijklmnopqrstuvwxyz\nline4"
        findings = cache.scan(text)
        assert len(findings) == 1
        assert findings[0].line_number == 3

    def test_scan_empty_content(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        assert cache.scan("") == []

    def test_scan_no_rules(self):
        cache = PatternCache()
        assert cache.scan("anything") == []

    def test_scan_with_validation_filters(self, pii_toml):
        cache = PatternCache()
        cache.load(pii_toml)
        valid_cc = "4532015112830366"
        findings = cache.scan(f"Card: {valid_cc}")
        cc_findings = [f for f in findings if f.rule_id == "pii-credit-card"]
        assert len(cc_findings) == 1

    def test_scan_validation_rejects_invalid(self, pii_toml):
        cache = PatternCache()
        cache.load(pii_toml)
        invalid_cc = "1234567890123456"
        findings = cache.scan(f"Card: {invalid_cc}")
        cc_findings = [f for f in findings if f.rule_id == "pii-credit-card"]
        assert len(cc_findings) == 0


class TestEnvVariablePathFiltering:
    """Integration tests for env-variable pattern skipping file paths (#881)."""

    @pytest.fixture
    def env_var_toml(self, tmp_path):
        content = b"""
[[rules]]
id = "env-variable"
match_type = "regex"
regex = '''(?:^|[^A-Za-z0-9_\\r\\n])([A-Z][A-Z0-9_]+)\\s*=\\s*(["']?)([A-Za-z0-9\\-_+/=]{16,})\\2'''
flags = "m"
redaction_strategy = "env_assignment"
description = "Environment Variable"
validation = "env_not_false_positive"

[[rules]]
id = "exported-env-variable"
match_type = "regex"
regex = '''(export\\s+[A-Z][A-Z0-9_]+)\\s*=\\s*(["']?)([A-Za-z0-9\\-_+/=]{16,})\\2'''
redaction_strategy = "env_assignment"
description = "Exported Environment Variable"
validation = "env_not_false_positive"
"""
        path = tmp_path / "secrets.toml"
        path.write_bytes(content)
        return path

    def test_unix_path_not_flagged(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("ENV PKGMGR=/usr/bin/microdnf")
        assert len(findings) == 0

    def test_deep_unix_path_not_flagged(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("ENV APP_DIR=/opt/app-root/src/config")
        assert len(findings) == 0

    def test_single_segment_absolute_path_not_flagged(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("LIFECYCLE_DIR=/service-lifecycle")
        assert len(findings) == 0

    def test_numeric_metadata_not_flagged(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("INIT_START_NS=1234567890123456789")
        assert len(findings) == 0

    def test_numeric_secret_assignment_still_detected(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("AWS_SECRET_KEY=1234567890123456789")
        assert any(f.rule_id == "env-variable" for f in findings)

    def test_exported_path_not_flagged(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("export APP_DIR=/opt/app-root/src/config")
        assert len(findings) == 0

    def test_real_secret_still_detected(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("AWS_SECRET_KEY=wJalrXUtnFEMIK7MDENGEXAMPLEKEY")
        env_findings = [f for f in findings if f.rule_id == "env-variable"]
        assert len(env_findings) == 1

    def test_aws_key_with_slash_still_detected(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("AWS_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
        env_findings = [f for f in findings if f.rule_id == "env-variable"]
        assert len(env_findings) == 1

    def test_dockerfile_env_path_not_flagged(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        dockerfile = (
            "FROM ubi9\nENV PKGMGR=/usr/bin/microdnf\nRUN $PKGMGR install -y python3"
        )
        findings = cache.scan(dockerfile)
        assert len(findings) == 0

    def test_python_underscore_assignment_not_flagged(self, env_var_toml):
        """Issue #912: _ = _load_config_file should not be detected."""
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("_ = _load_config_file")
        assert len(findings) == 0

    def test_placeholder_export_not_flagged(self, env_var_toml):
        """Issue #912: placeholder values in docs should not be detected."""
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan('export JIRA_API_TOKEN="your-personal-access-token"')
        assert len(findings) == 0

    def test_python_identifier_value_not_flagged(self, env_var_toml):
        """Values starting with _ (Python identifiers) should not be detected."""
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("CONFIG = _internal_function_name_here")
        assert len(findings) == 0

    def test_placeholder_unquoted_not_flagged(self, env_var_toml):
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("MY_TOKEN=your-personal-access-token")
        assert len(findings) == 0

    def test_all_caps_identifier_not_flagged(self, env_var_toml):
        """Issue #1627: ALL_CAPS_IDENTIFIER values are programming constants."""
        cache = PatternCache()
        cache.load(env_var_toml)
        findings = cache.scan("ALL_DETECTION_CASES = NEW_SECRET_DETECTION_CASES")
        assert len(findings) == 0


class TestConnectionStringPlaceholderFiltering:
    """Issue #919: connection strings with placeholder passwords should not be flagged."""

    @pytest.fixture
    def connection_toml(self, tmp_path):
        content = b"""
[[rules]]
id = "mongodb-connection"
match_type = "regex"
regex = '''(mongodb://[^:]+:)([^@]+)(@[^\\s]+)'''
redaction_strategy = "connection_string"
validation = "connection_not_placeholder"
description = "MongoDB Connection"
keywords = ["mongodb://"]

[[rules]]
id = "postgres-connection"
match_type = "regex"
regex = '''(postgres://[^:]+:)([^@]+)(@[^\\s]+)'''
redaction_strategy = "connection_string"
validation = "connection_not_placeholder"
description = "PostgreSQL Connection"
keywords = ["postgres://"]
"""
        path = tmp_path / "conn.toml"
        path.write_bytes(content)
        return path

    def test_real_password_flagged(self, connection_toml):
        cache = PatternCache()
        cache.load(connection_toml)
        findings = cache.scan(
            "mongodb://user:MySecretPass123@db.example.com:27017/mydb"
        )
        assert len(findings) == 1

    def test_hidden_placeholder_not_flagged(self, connection_toml):
        """Issue #919: [HIDDEN] placeholder in docs should not be detected."""
        cache = PatternCache()
        cache.load(connection_toml)
        findings = cache.scan("mongodb://user:[HIDDEN]@db.example.com:27017/mydb")
        assert len(findings) == 0

    def test_redacted_placeholder_not_flagged(self, connection_toml):
        cache = PatternCache()
        cache.load(connection_toml)
        findings = cache.scan("postgres://admin:[REDACTED]@db.host:5432/app")
        assert len(findings) == 0

    def test_angle_bracket_placeholder_not_flagged(self, connection_toml):
        cache = PatternCache()
        cache.load(connection_toml)
        findings = cache.scan("mongodb://user:<password>@localhost:27017/test")
        assert len(findings) == 0

    def test_repeated_x_not_flagged(self, connection_toml):
        cache = PatternCache()
        cache.load(connection_toml)
        findings = cache.scan("postgres://user:xxxxxxxx@db.host:5432/app")
        assert len(findings) == 0


class TestPatternCacheLiteral:

    def test_check_literal_homoglyph(self, unicode_toml):
        cache = PatternCache()
        cache.load(unicode_toml)
        results = cache.check_literal("hаllo")
        assert len(results) == 1
        assert results[0][0] == "а"
        assert results[0][1] == "a"

    def test_check_literal_no_match(self, unicode_toml):
        cache = PatternCache()
        cache.load(unicode_toml)
        results = cache.check_literal("hello")
        assert len(results) == 0

    def test_scan_literal_via_scan(self, unicode_toml):
        cache = PatternCache()
        cache.load(unicode_toml)
        findings = cache.scan("hаllo", categories=["unicode"])
        literal_findings = [f for f in findings if f.rule_id == "homoglyph-cyrillic-a"]
        assert len(literal_findings) == 1


class TestPatternCacheCIDR:

    def test_check_cidr_match(self, ssrf_toml):
        cache = PatternCache()
        cache.load(ssrf_toml)
        matches = cache.check_cidr("10.0.0.1")
        assert len(matches) == 1
        assert matches[0].id == "ssrf-private-a"

    def test_check_cidr_no_match(self, ssrf_toml):
        cache = PatternCache()
        cache.load(ssrf_toml)
        matches = cache.check_cidr("8.8.8.8")
        assert len(matches) == 0

    def test_check_cidr_invalid_ip(self, ssrf_toml):
        cache = PatternCache()
        cache.load(ssrf_toml)
        matches = cache.check_cidr("not-an-ip")
        assert len(matches) == 0

    def test_scan_cidr_in_text(self, ssrf_toml):
        cache = PatternCache()
        cache.load(ssrf_toml)
        findings = cache.scan("Connect to 10.0.0.1 for data")
        assert len(findings) == 1
        assert findings[0].rule_id == "ssrf-private-a"


class TestPatternCacheRange:

    def test_check_range_match(self, unicode_toml):
        cache = PatternCache()
        cache.load(unicode_toml)
        matches = cache.check_range(0xE0001)
        assert len(matches) == 1
        assert matches[0].id == "tag-chars"

    def test_check_range_no_match(self, unicode_toml):
        cache = PatternCache()
        cache.load(unicode_toml)
        matches = cache.check_range(0x0041)
        assert len(matches) == 0

    def test_scan_range_in_text(self, unicode_toml):
        cache = PatternCache()
        cache.load(unicode_toml)
        tag_char = chr(0xE0001)
        findings = cache.scan(f"text{tag_char}more")
        range_findings = [f for f in findings if f.rule_id == "tag-chars"]
        assert len(range_findings) == 1


class TestPatternCacheRedact:

    def test_redact_preserves_prefix_suffix(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        result = cache.redact("Key: sk-abcdefghijklmnopqrstuvwxyz done")
        assert "sk-a" in result["redacted_text"]
        assert "wxyz" in result["redacted_text"]
        assert "abcdefghijklmnopqrstu" not in result["redacted_text"]
        assert len(result["redactions"]) == 1

    def test_redact_full_redact(self, tmp_path):
        toml_content = b"""
[[rules]]
id = "test-full"
match_type = "regex"
regex = '''AKIA[A-Z0-9]{16}'''
redaction_strategy = "full_redact"
description = "AWS Key"
"""
        path = tmp_path / "test.toml"
        path.write_bytes(toml_content)
        cache = PatternCache()
        cache.load(path)
        result = cache.redact("Key: AKIAIOSFODNN7EXAMPLE done")
        assert "[REDACTED]" in result["redacted_text"]
        assert "AKIAIOSFODNN7EXAMPLE" not in result["redacted_text"]

    def test_redact_credit_card(self, pii_toml):
        cache = PatternCache()
        cache.load(pii_toml)
        result = cache.redact("Card: 4532015112830366")
        assert "0366" in result["redacted_text"]
        assert "4532015112830" not in result["redacted_text"]

    def test_redact_email(self, pii_toml):
        cache = PatternCache()
        cache.load(pii_toml)
        result = cache.redact("Email: user@example.com")
        assert "u***@example.com" in result["redacted_text"]
        assert "user@example.com" not in result["redacted_text"]

    def test_redact_no_match_returns_original(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        result = cache.redact("Nothing sensitive here")
        assert result["redacted_text"] == "Nothing sensitive here"
        assert result["redactions"] == []

    def test_redact_empty_returns_empty(self, secrets_toml):
        cache = PatternCache()
        cache.load(secrets_toml)
        result = cache.redact("")
        assert result["redacted_text"] == ""


class TestPatternCachePerformance:

    def test_scan_under_5ms(self, secrets_toml, pii_toml):
        """Verify scan completes in under 5ms for moderate content."""
        import time

        cache = PatternCache()
        cache.load(secrets_toml, pii_toml)
        content = "Some text without secrets. " * 100
        start = time.monotonic()
        for _ in range(10):
            cache.scan(content)
        elapsed = (time.monotonic() - start) / 10
        assert elapsed < 0.005, f"Scan took {elapsed*1000:.1f}ms, expected <5ms"
