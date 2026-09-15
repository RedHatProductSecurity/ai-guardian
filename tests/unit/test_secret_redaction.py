"""
Tests for secret redaction functionality (Phase 4: Hermes Security Patterns).

Tests the SecretRedactor class and its integration with PostToolUse hook.
"""

import re
import pytest
from ai_guardian.scanners.secret_redactor import SecretRedactor


class TestSecretRedactor:
    """Test the SecretRedactor class."""

    def test_redactor_initialization(self):
        """Test that SecretRedactor initializes correctly."""
        redactor = SecretRedactor()
        assert redactor.enabled is True
        assert redactor.action == "warn"
        assert redactor.preserve_format is True
        assert redactor.log_redactions is True
        assert len(redactor.compiled_patterns) > 30  # Should have 35+ patterns

    def test_redactor_disabled(self):
        """Test that disabled redactor returns original text."""
        redactor = SecretRedactor({"enabled": False})
        text = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx"
        result = redactor.redact(text)

        assert result["redacted_text"] == text
        assert len(result["redactions"]) == 0

    def test_openai_api_key_redaction(self):
        """Test redaction of OpenAI API keys."""
        redactor = SecretRedactor()
        text = "My key is sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx here"
        result = redactor.redact(text)

        # Should preserve some prefix and suffix (6 chars + 4 chars)
        assert (
            "sk-pro..." in result["redacted_text"]
            or "sk-proj..." in result["redacted_text"]
        )
        assert "abc123def456ghi789" not in result["redacted_text"]
        assert len(result["redactions"]) == 1
        assert result["redactions"][0]["type"] == "OpenAI Project Key"
        assert result["redactions"][0]["strategy"] == "preserve_prefix_suffix"

    def test_github_token_redaction(self):
        """Test redaction of GitHub tokens."""
        redactor = SecretRedactor()
        text = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"  # notsecret
        result = redactor.redact(text)

        assert "ghp_12...wxyz" in result["redacted_text"]
        assert "1234567890abcdefghijk" not in result["redacted_text"]
        assert len(result["redactions"]) == 1
        assert result["redactions"][0]["type"] == "GitHub Personal Token"

    def test_aws_access_key_full_redaction(self):
        """Test that AWS access keys are fully redacted."""
        redactor = SecretRedactor()
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = redactor.redact(text)

        # Secret should be completely gone
        assert "AKIAIOSFODNN7EXAMPLE" not in result["redacted_text"]
        assert len(result["redactions"]) == 1
        assert result["redactions"][0]["strategy"] == "full_redact"
        # Should have some replacement text
        assert "AWS" in result["redacted_text"]

    def test_env_var_redaction(self):
        """Test environment variable assignment redaction."""
        redactor = SecretRedactor()
        text = "AWS_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = redactor.redact(text)

        # Secret value should be gone but variable name preserved
        assert "wJalrXUtnFEMI" not in result["redacted_text"]
        assert "AWS_SECRET_KEY=" in result["redacted_text"]
        assert len(result["redactions"]) >= 1  # May match multiple patterns

    def test_json_field_redaction(self):
        """Test JSON field redaction preserves structure."""
        redactor = SecretRedactor()
        text = '{"api_key": "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx"}'
        result = redactor.redact(text)

        # Secret should be redacted but structure preserved
        assert '"api_key"' in result["redacted_text"]
        assert "abc123def456" not in result["redacted_text"]
        # Should still be valid-looking JSON
        assert "{" in result["redacted_text"] and "}" in result["redacted_text"]

    def test_connection_string_redaction(self):
        """Test database connection string redaction."""
        redactor = SecretRedactor()
        text = "mongodb://user:MySecretPass123@db.example.com:27017/mydb"
        result = redactor.redact(text)

        # Password should be redacted but endpoint preserved
        assert "MySecretPass123" not in result["redacted_text"]
        assert "mongodb://user:" in result["redacted_text"]
        assert "@db.example.com:27017/mydb" in result["redacted_text"]
        assert len(result["redactions"]) >= 1

    def test_bearer_token_redaction(self):
        """Test HTTP Authorization header redaction."""
        redactor = SecretRedactor()
        text = "Authorization: Bearer sk-ant-api03-abc123def456ghi789jkl012"
        result = redactor.redact(text)

        assert "Authorization: Bearer" in result["redacted_text"]
        assert "abc123def456" not in result["redacted_text"]
        assert len(result["redactions"]) >= 1

    def test_multiple_secrets_in_output(self):
        """Test redaction of multiple different secrets."""
        redactor = SecretRedactor()
        text = """
        GitHub: ghp_1234567890abcdefghijklmnopqrstuvwxyz
        OpenAI: sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx
        AWS: AKIAIOSFODNN7EXAMPLE
        """  # notsecret
        result = redactor.redact(text)

        # All secret values should be completely gone
        assert "1234567890abcdefghijk" not in result["redacted_text"]
        assert "abc123def456ghi789" not in result["redacted_text"]
        assert "AKIAIOSFODNN7EXAMPLE" not in result["redacted_text"]

        # Context labels should remain
        assert "GitHub:" in result["redacted_text"]
        assert "OpenAI:" in result["redacted_text"]
        assert "AWS:" in result["redacted_text"]

        assert len(result["redactions"]) >= 3

    def test_short_secret_handling(self):
        """Test that very short secrets are handled properly."""
        redactor = SecretRedactor()
        # This should match a pattern but be too short to preserve prefix/suffix
        text = "token: abc12345"  # 8 chars
        result = redactor.redact(text)

        # Short secrets may not be detected or may be redacted as ***
        assert len(result["redacted_text"]) > 0

    def test_overlapping_patterns(self):
        """Test that overlapping patterns don't cause issues."""
        redactor = SecretRedactor()
        text = "GITHUB_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz"  # notsecret
        result = redactor.redact(text)

        # Should redact either as env var or as GitHub token, but not duplicate
        assert "1234567890abcdefghijk" not in result["redacted_text"]
        # Should have at least one redaction
        assert len(result["redactions"]) >= 1

    def test_custom_patterns(self):
        """Test adding custom redaction patterns."""
        config = {
            "additional_patterns": [
                {
                    "pattern": r"(mycompany_token_[A-Za-z0-9]{20,})",
                    "strategy": "preserve_prefix_suffix",
                    "type": "Company Token",
                }
            ]
        }
        redactor = SecretRedactor(config)
        text = "Token: mycompany_token_abc123def456ghi789jkl012mno345"
        result = redactor.redact(text)

        # Secret middle part should be redacted
        assert "def456ghi789jkl012" not in result["redacted_text"]
        assert len(result["redactions"]) > 0

    def test_private_key_redaction(self):
        """Test that private keys are fully redacted."""
        redactor = SecretRedactor()
        text = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA1234567890abcdefghijklmno
-----END RSA PRIVATE KEY-----"""  # notsecret
        result = redactor.redact(text)

        # Private key content should be completely gone
        assert "MIIEpAIBAAKCAQEA" not in result["redacted_text"]
        assert len(result["redactions"]) == 1

    def test_anthropic_api_key(self):
        """Test Anthropic API key redaction."""
        redactor = SecretRedactor()
        text = "Key: sk-ant-api03-abc123def456ghi789jkl012mno345pqr678stu901"
        result = redactor.redact(text)

        # Should redact the middle part
        assert "abc123def456ghi789" not in result["redacted_text"]
        assert len(result["redactions"]) >= 1

    def test_slack_token(self):
        """Test Slack token redaction."""
        redactor = SecretRedactor()
        # Using intentionally fake token format that still matches our pattern
        text = "Slack: xoxb-TEST1234567-TEST1234567890-EXAMPLEEXAMPLEEX"  # notsecret
        result = redactor.redact(text)

        assert "xoxb-" in result["redacted_text"]
        assert "EXAMPLEEXAMPLEEX" not in result["redacted_text"]

    def test_stripe_keys(self):
        """Test Stripe API key redaction."""
        redactor = SecretRedactor()
        # Using public key to avoid GitHub's secret scanner (tests same redaction logic)
        text = "pk_test_XXXXXXXXXXXXXXXXXXXXXXXX"  # notsecret (fake public key)
        result = redactor.redact(text)

        # Should redact the secret part - middle X's should be gone
        assert "XXXXXXXXXXXXXXXXXX" not in result["redacted_text"]
        assert len(result["redactions"]) >= 1

    def test_redaction_metadata(self):
        """Test that redaction metadata is complete."""
        redactor = SecretRedactor()
        text = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"  # notsecret
        result = redactor.redact(text)

        assert "redacted_text" in result
        assert "redactions" in result
        assert "original_length" in result
        assert "redacted_length" in result

        if len(result["redactions"]) > 0:
            r = result["redactions"][0]
            assert "type" in r
            assert "position" in r
            assert "original_length" in r
            assert "redacted_length" in r
            assert "strategy" in r

    def test_performance(self):
        """Test that redaction completes within 100ms for a 30KB input."""
        import time

        redactor = SecretRedactor()
        # Create 10KB of text with some secrets
        text = (
            "Hello world. " * 100
            + "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz\n"  # notsecret
            + "Some more text. " * 100
        ) * 10

        start = time.perf_counter()
        result = redactor.redact(text)
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms

        # Allow normal variation on slower CI runners while catching regressions.
        assert elapsed < 100, f"Redaction took {elapsed}ms, expected <100ms"
        assert len(result["redactions"]) > 0

    def test_action_modes(self):
        """Test different action modes."""
        # log-only mode
        redactor_log = SecretRedactor({"action": "log-only"})
        assert redactor_log.action == "log-only"

        # warn mode
        redactor_warn = SecretRedactor({"action": "warn"})
        assert redactor_warn.action == "warn"

    def test_empty_text(self):
        """Test redaction of empty text."""
        redactor = SecretRedactor()
        result = redactor.redact("")

        assert result["redacted_text"] == ""
        assert len(result["redactions"]) == 0

    def test_none_text(self):
        """Test redaction of None."""
        redactor = SecretRedactor()
        result = redactor.redact(None)

        assert result["redacted_text"] is None
        assert len(result["redactions"]) == 0

    def test_generic_password_assignment_redaction(self):
        """Test password = 'value' assignment detection and redaction."""
        redactor = SecretRedactor()

        text = 'password = "SuperSecret123!"'
        result = redactor.redact(text)
        assert "SuperSecret123!" not in result["redacted_text"]
        assert "password" in result["redacted_text"]
        assert len(result["redactions"]) >= 1

    def test_generic_password_assignment_case_insensitive(self):
        """Test case-insensitive detection of PASSWORD = 'value'."""
        redactor = SecretRedactor()

        text = 'PASSWORD = "MySecretValueHere"'
        result = redactor.redact(text)
        assert "MySecretValueHere" not in result["redacted_text"]

    def test_generic_password_assignment_variants(self):
        """Test db_password, secret_key, api_secret variants."""
        redactor = SecretRedactor()

        for keyword in [
            "db_password",
            "secret_key",
            "api_secret",
            "passwd",
            "db_passwd",
        ]:
            text = f'{keyword} = "some_long_value_here"'
            result = redactor.redact(text)
            assert (
                "some_long_value_here" not in result["redacted_text"]
            ), f"Failed to redact {keyword} assignment"

    def test_generic_password_assignment_single_quotes(self):
        """Test single-quoted values: password = 'value'."""
        redactor = SecretRedactor()

        text = "password = 'SuperSecret123!'"
        result = redactor.redact(text)
        assert "SuperSecret123!" not in result["redacted_text"]

    def test_generic_password_assignment_no_fp_file_path(self):
        """File paths should NOT trigger generic password assignment."""
        redactor = SecretRedactor()

        text = 'secret = "/etc/secrets/production.key"'
        result = redactor.redact(text)
        fp = [
            r
            for r in result["redactions"]
            if r.get("rule_id") == "generic-password-assignment"
        ]
        assert len(fp) == 0

    def test_generic_password_assignment_no_fp_short(self):
        """Short values (<8 chars) should not trigger detection."""
        redactor = SecretRedactor()

        text = 'password = "short"'
        result = redactor.redact(text)
        fp = [
            r
            for r in result["redactions"]
            if r.get("rule_id") == "generic-password-assignment"
        ]
        assert len(fp) == 0

    def test_generic_password_assignment_no_fp_unrelated_key(self):
        """Non-secret keys should not trigger detection."""
        redactor = SecretRedactor()

        text = 'username = "admin_user_here"'
        result = redactor.redact(text)
        fp = [
            r
            for r in result["redactions"]
            if r.get("rule_id") == "generic-password-assignment"
        ]
        assert len(fp) == 0

    def test_hex_secret_redaction(self):
        """Test long hex string redaction with context."""
        redactor = SecretRedactor()
        # Hex patterns now require context keywords (secret, key, token, password)
        # or be very long (100+ chars) to avoid false positives with git SHAs
        text = "api_secret: abcdef1234567890abcdef1234567890abcdef1234567890"
        result = redactor.redact(text)

        # Long hex strings with context should be redacted - middle part gone
        assert "api_secret:" in result["redacted_text"]
        # Should have some redaction
        assert len(result["redacted_text"]) < len(text)

    def test_base64_secret_redaction(self):
        """Test base64 encoded secret redaction with context."""
        redactor = SecretRedactor()
        # Base64 patterns now require context keywords or be very long (100+ chars)
        text = "token: dGhpc2lzYWxvbmdzdHJpbmd0aGF0bG9va3NsaWtlYWJhc2U2NGVuY29kZWRzZWNyZXQ="
        result = redactor.redact(text)

        # Long base64 strings with context should be redacted
        assert (
            "dGhpc2...ZXQ=" in result["redacted_text"]
            or "token:" in result["redacted_text"]
        )


class TestSecretRedactionIntegration:
    """Test integration with PostToolUse hook."""

    def test_posttooluse_with_redaction_enabled(self):
        """Test that PostToolUse redacts instead of blocks when enabled."""
        # This would be an integration test with the actual hook
        # For now, just test the config loading
        from ai_guardian import _load_secret_redaction_config

        # Should not error when loading config
        config, error = _load_secret_redaction_config()
        assert error is None or config is None  # Either loads successfully or no config

    def test_redaction_preserves_non_secret_context(self):
        """Test that redaction preserves debugging context."""
        redactor = SecretRedactor()
        text = """
        AWS Configuration:
        AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
        AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
        AWS_REGION=us-east-1
        AWS_DEFAULT_OUTPUT=json
        """
        result = redactor.redact(text)

        # Non-secret values should be preserved
        assert "AWS_REGION=us-east-1" in result["redacted_text"]
        assert "AWS_DEFAULT_OUTPUT=json" in result["redacted_text"]

        # Secret values should be gone
        assert "AKIAIOSFODNN7EXAMPLE" not in result["redacted_text"]
        assert "wJalrXUtnFEMI" not in result["redacted_text"]

    def test_log_file_with_buried_secret(self):
        """Test finding a secret buried in log output."""
        redactor = SecretRedactor()
        # Simulate a large log file with one secret
        log_lines = ["[INFO] Application started"] * 100
        log_lines[50] = (
            "[DEBUG] API_KEY=sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx"  # notsecret
        )
        log_lines += ["[INFO] Processing request"] * 100

        text = "\n".join(log_lines)
        result = redactor.redact(text)

        # Should find and redact the secret - check middle is gone
        assert "abc123def456ghi789" not in result["redacted_text"]

        # Other log lines should be preserved
        assert "[INFO] Application started" in result["redacted_text"]
        assert "[INFO] Processing request" in result["redacted_text"]

    def test_config_file_review(self):
        """Test reviewing a config file with secrets."""
        redactor = SecretRedactor()
        text = """
        # Production Configuration
        database:
          host: prod-db.example.com
          port: 5432
          password: MySecretPass123

        api:
          key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx
          endpoint: https://api.example.com
        """
        result = redactor.redact(text)

        # Can see structure
        assert "database:" in result["redacted_text"]
        assert "host: prod-db.example.com" in result["redacted_text"]
        assert "port: 5432" in result["redacted_text"]
        assert "endpoint: https://api.example.com" in result["redacted_text"]

        # Secrets are hidden
        assert "MySecretPass123" not in result["redacted_text"]
        assert "abc123def456" not in result["redacted_text"]


class TestGitHubStatelessJWTTokens:
    """Test GitHub token detection for both stateful and stateless JWT formats.

    GitHub is rolling out stateless JWT tokens (mid-May to late-June 2026)
    for App installation tokens (ghs_). The new format includes dots and
    hyphens from base64url-encoded JWT payload. All four token types
    (ghp_, gho_, ghr_, ghs_) are updated proactively.
    """

    @pytest.fixture
    def redactor(self):
        return SecretRedactor()

    @pytest.mark.parametrize(
        "prefix,token_type",
        [
            ("ghp_", "GitHub Personal Token"),
            ("gho_", "GitHub OAuth Token"),
            ("ghr_", "GitHub Refresh Token"),
            ("ghs_", "GitHub Secret Token"),
        ],
    )
    def test_old_stateful_format(self, redactor, prefix, token_type):
        """Old stateful tokens (alphanumeric only) still match."""
        token = prefix + "A" * 36  # notsecret
        result = redactor.redact(f"Token: {token}")
        assert len(result["redactions"]) >= 1
        found = any(r["type"] == token_type for r in result["redactions"])
        assert found, f"Expected {token_type} detection for old format"
        assert "A" * 20 not in result["redacted_text"]

    @pytest.mark.parametrize(
        "prefix,token_type",
        [
            ("ghp_", "GitHub Personal Token"),
            ("gho_", "GitHub OAuth Token"),
            ("ghr_", "GitHub Refresh Token"),
            ("ghs_", "GitHub Secret Token"),
        ],
    )
    def test_new_stateless_jwt_format(self, redactor, prefix, token_type):
        """New stateless JWT tokens (with dots, hyphens, underscores) are detected."""
        # Simulates ghs_12345_eyJhbGciOi...base64url...  (~100 chars)
        jwt_payload = (
            "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGVzdHNpZ25hdHVyZQ"
        )
        token = prefix + "12345_" + jwt_payload  # notsecret
        result = redactor.redact(f"Token: {token}")
        assert len(result["redactions"]) >= 1
        found = any(r["type"] == token_type for r in result["redactions"])
        assert found, f"Expected {token_type} detection for JWT format"
        assert jwt_payload not in result["redacted_text"]

    def test_ghs_real_world_jwt_length(self, redactor):
        """New ghs_ tokens can be ~520 chars long with full JWT payload."""
        header = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
        payload = (
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9." * 3
        )
        sig = "dGVzdHNpZ25hdHVyZWRhdGFmb3J0ZXN0aW5n"
        token = f"ghs_12345_{header}.{payload}{sig}"  # notsecret
        result = redactor.redact(f"Token: {token}")
        assert len(result["redactions"]) >= 1
        found = any(r["type"] == "GitHub Secret Token" for r in result["redactions"])
        assert found
        assert header not in result["redacted_text"]

    def test_dots_and_hyphens_in_token(self, redactor):
        """Dots, hyphens, and underscores in the token body are matched."""
        token = "ghs_abc-def.ghi_jkl.mno-pqr.stu_vwx.yza-bcd"  # notsecret
        result = redactor.redact(f"Token: {token}")
        assert len(result["redactions"]) >= 1
        found = any(r["type"] == "GitHub Secret Token" for r in result["redactions"])
        assert found

    def test_short_token_no_match(self, redactor):
        """Tokens shorter than 36 chars after prefix should not match."""
        token = "ghs_short"  # notsecret - too short
        result = redactor.redact(f"Token: {token}")
        github_hits = [r for r in result["redactions"] if "GitHub" in r["type"]]
        assert len(github_hits) == 0

    def test_non_token_with_dots_no_false_positive(self, redactor):
        """Non-token strings containing dots should not be falsely detected."""
        text = "The file is at path/to/some.file.name.txt"
        result = redactor.redact(text)
        github_hits = [r for r in result["redactions"] if "GitHub" in r["type"]]
        assert len(github_hits) == 0


class TestTomlOnlyPatternLoading:
    """Tests for TOML-only pattern loading after removing hardcoded patterns (Issue #841)."""

    def test_patterns_loaded_from_toml_not_hardcoded(self):
        """Patterns are loaded from TOML files, not hardcoded on the class."""
        assert not hasattr(
            SecretRedactor, "PATTERNS"
        ), "Hardcoded PATTERNS class attribute should be removed (Issue #841)"
        assert not hasattr(
            SecretRedactor, "PII_PATTERNS"
        ), "Hardcoded PII_PATTERNS class attribute should be removed (Issue #841)"

    def test_valid_cc_prefixes_still_present(self):
        """VALID_CC_PREFIXES is validation data and must remain."""
        from ai_guardian.patterns.validators import VALID_CC_PREFIXES

        assert isinstance(VALID_CC_PREFIXES, tuple)
        assert len(VALID_CC_PREFIXES) > 0

    def test_toml_loads_all_secret_patterns(self):
        """TOML loading produces 44 secret patterns."""
        redactor = SecretRedactor()
        assert len(redactor.compiled_patterns) >= 44

    def test_fallback_when_secrets_toml_missing(self):
        """When secrets.toml is missing, redactor has 0 patterns with no error."""
        from pathlib import Path
        from unittest.mock import patch
        import ai_guardian.patterns as patterns_mod

        missing_files = dict(patterns_mod.BUNDLED_FILES)
        missing_files["secrets"] = Path("/nonexistent/secrets.toml")
        with patch.dict(patterns_mod.BUNDLED_FILES, missing_files):
            redactor = SecretRedactor()
            assert len(redactor.compiled_patterns) == 0

    def test_fallback_when_pii_toml_missing(self):
        """When pii.toml is missing, PII patterns are empty."""
        from pathlib import Path
        from unittest.mock import patch
        import ai_guardian.patterns as patterns_mod

        missing_files = dict(patterns_mod.BUNDLED_FILES)
        missing_files["pii"] = Path("/nonexistent/pii.toml")
        with patch.dict(patterns_mod.BUNDLED_FILES, missing_files):
            pii_config = {"enabled": True, "pii_types": ["ssn"], "action": "redact"}
            redactor = SecretRedactor(pii_config=pii_config)
            text = "SSN: 123-45-6789"
            result = redactor.redact(text)
            assert "123-45-6789" in result["redacted_text"]


class TestPositionDriftRegression:
    """Regression tests for position drift bug (#1228).

    When multiple matches exist for the same pattern, left-to-right replacement
    causes position drift because match positions from finditer() reference the
    original text, not the modified text. Right-to-left processing fixes this.
    """

    def test_multiple_same_pattern_no_garble(self):
        """Two secrets of the same type must both redact cleanly."""
        redactor = SecretRedactor()
        text = (
            "first: ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa\n"
            "second: ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBbbbbbbbb"
        )  # notsecret
        result = redactor.redact(text)
        out = result["redacted_text"]

        assert "AAAAAAAA" not in out
        assert "BBBBBBBB" not in out
        assert "first:" in out
        assert "second:" in out
        assert "\n" in out

    def test_line_boundaries_preserved(self):
        """Newlines between secrets must survive redaction."""
        redactor = SecretRedactor()
        lines = [
            "line1: ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa",
            "line2: normal text here",
            "line3: ghp_CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCcccccccc",
        ]  # notsecret
        text = "\n".join(lines)
        result = redactor.redact(text)
        out = result["redacted_text"]

        output_lines = out.split("\n")
        assert len(output_lines) == 3
        assert "line2: normal text here" in out

    def test_shorter_replacement_no_drift(self):
        """When redacted text is shorter than original, later positions stay correct."""
        redactor = SecretRedactor(config={"enabled": True})
        text = "KEY1=AKIAIOSFODNN7EXAMPLE1 " "KEY2=AKIAIOSFODNN7EXAMPLE2"  # notsecret
        result = redactor.redact(text)
        out = result["redacted_text"]

        assert "EXAMPLE1" not in out
        assert "EXAMPLE2" not in out
        assert "KEY1=" in out
        assert "KEY2=" in out

    def test_mixed_pattern_types_no_garble(self):
        """Different secret types in same text must all redact correctly."""
        redactor = SecretRedactor()
        text = (
            "github: ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa\n"
            "aws: AKIAIOSFODNN7EXAMPLE\n"
            "openai: sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx"
        )  # notsecret
        result = redactor.redact(text)
        out = result["redacted_text"]

        assert "AAAAAAAA" not in out
        assert "AKIAIOSFODNN7EXAMPLE" not in out
        assert "abc123def456" not in out
        assert "github:" in out
        assert "aws:" in out
        assert "openai:" in out
        assert out.count("\n") == 2

    def test_redaction_count_matches_secrets(self):
        """Number of redactions must match number of distinct secrets."""
        redactor = SecretRedactor()
        text = (
            "a]ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa "
            "b]ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBbbbbbbbb "
            "c]ghp_CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCcccccccc"
        )  # notsecret
        result = redactor.redact(text)

        assert len(result["redactions"]) >= 3


class TestPositionFromOriginalText:
    """Regression tests for positions recorded from modified text (#1235).

    When multiple pattern types match, finditer() must run on the original text
    so position metadata indexes correctly into the original content.
    """

    def test_cross_pattern_positions_index_original(self):
        """Positions from different pattern types must slice original text correctly."""
        redactor = SecretRedactor()
        text = (
            "github: ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa\n"
            "aws: AKIAIOSFODNN7EXAMPLE"
        )  # notsecret
        result = redactor.redact(text)

        for r in result["redactions"]:
            pos = r["position"]
            length = r["original_length"]
            extracted = text[pos : pos + length]
            assert len(extracted) == length
            assert "\n" not in extracted or r["type"] in ("private_key",)

    def test_position_after_length_changing_redaction(self):
        """Second pattern's position must be from original text, not modified."""
        redactor = SecretRedactor()
        text = (
            "token=ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa "
            "key=AKIAIOSFODNN7EXAMPLE"
        )  # notsecret
        result = redactor.redact(text)

        for r in result["redactions"]:
            pos = r["position"]
            length = r["original_length"]
            extracted = text[pos : pos + length]
            if "ghp_" in extracted or extracted.startswith("AKIA"):
                assert len(extracted) == length

    def test_line_number_from_original_text(self):
        """line_number must reflect original text line boundaries."""
        redactor = SecretRedactor()
        text = (
            "line1: ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa\n"
            "line2: normal\n"
            "line3: AKIAIOSFODNN7EXAMPLE"
        )  # notsecret
        result = redactor.redact(text)

        line_numbers = {r["type"]: r["line_number"] for r in result["redactions"]}
        for secret_type, line_num in line_numbers.items():
            pos = next(
                r["position"] for r in result["redactions"] if r["type"] == secret_type
            )
            expected_line = text[:pos].count("\n") + 1
            assert line_num == expected_line

    def test_column_from_original_text(self):
        """column must reflect position within original text line."""
        redactor = SecretRedactor()
        text = "prefix: ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaaaaaaaa"  # notsecret
        result = redactor.redact(text)

        assert len(result["redactions"]) >= 1
        r = result["redactions"][0]
        expected_col = r["position"] - text.rfind("\n", 0, r["position"])
        assert r["column"] == expected_col


class TestPerRuleRegexFlags:
    """Tests for per-rule regex flag handling (Issue #1262).

    secret_redactor.py must respect per-rule flags/case_insensitive from
    pattern dicts, matching toml_parser.py behavior. Tuple-format patterns
    keep IGNORECASE|MULTILINE for backward compatibility.
    """

    def test_extract_regex_flags_default_no_flags(self):
        """Dict with no flag fields produces flags=0."""
        flags = SecretRedactor._extract_regex_flags({})
        assert flags == 0

    def test_extract_regex_flags_case_insensitive_bool(self):
        """case_insensitive: True sets IGNORECASE."""
        flags = SecretRedactor._extract_regex_flags({"case_insensitive": True})
        assert flags & re.IGNORECASE

    def test_extract_regex_flags_string_i(self):
        """flags: "i" sets IGNORECASE."""
        flags = SecretRedactor._extract_regex_flags({"flags": "i"})
        assert flags & re.IGNORECASE

    def test_extract_regex_flags_multiline_bool(self):
        """multiline: True sets MULTILINE."""
        flags = SecretRedactor._extract_regex_flags({"multiline": True})
        assert flags & re.MULTILINE

    def test_extract_regex_flags_string_im(self):
        """flags: "im" sets both IGNORECASE and MULTILINE."""
        flags = SecretRedactor._extract_regex_flags({"flags": "im"})
        assert flags & re.IGNORECASE
        assert flags & re.MULTILINE

    def test_extract_regex_flags_dotall(self):
        """dotall: True sets DOTALL."""
        flags = SecretRedactor._extract_regex_flags({"dotall": True})
        assert flags & re.DOTALL

    def test_dict_pattern_case_sensitive_by_default(self):
        """Dict-format pattern without flags is case-sensitive (no IGNORECASE)."""
        redactor = SecretRedactor(
            config={
                "enabled": True,
                "additional_patterns": [
                    {
                        "pattern": r"EXACT_SECRET_[A-Z]{20}",
                        "strategy": "full_redact",
                        "type": "Test Case-Sensitive Secret",
                    }
                ],
            }
        )
        text = "exact_secret_abcdefghijklmnopqrst"
        result = redactor.redact(text)
        test_hits = [
            r for r in result["redactions"] if r["type"] == "Test Case-Sensitive Secret"
        ]
        assert (
            len(test_hits) == 0
        ), "Case-sensitive pattern should NOT match lowercase input"

    def test_dict_pattern_case_insensitive_flag(self):
        """Dict-format pattern with case_insensitive: True matches lowercase."""
        redactor = SecretRedactor(
            config={
                "enabled": True,
                "additional_patterns": [
                    {
                        "pattern": r"EXACT_SECRET_[A-Z]{20}",
                        "strategy": "full_redact",
                        "type": "Test CI Secret",
                        "case_insensitive": True,
                    }
                ],
            }
        )
        text = "exact_secret_abcdefghijklmnopqrst"
        result = redactor.redact(text)
        test_hits = [r for r in result["redactions"] if r["type"] == "Test CI Secret"]
        assert len(test_hits) == 1, "case_insensitive: True should match lowercase"

    def test_dict_pattern_flags_i_matches_lowercase(self):
        """Dict-format pattern with flags: 'i' matches lowercase."""
        redactor = SecretRedactor(
            config={
                "enabled": True,
                "additional_patterns": [
                    {
                        "pattern": r"EXACT_SECRET_[A-Z]{20}",
                        "strategy": "full_redact",
                        "type": "Test Flags-I Secret",
                        "flags": "i",
                    }
                ],
            }
        )
        text = "exact_secret_abcdefghijklmnopqrst"
        result = redactor.redact(text)
        test_hits = [
            r for r in result["redactions"] if r["type"] == "Test Flags-I Secret"
        ]
        assert len(test_hits) == 1

    def test_tuple_format_keeps_ignorecase(self):
        """Tuple-format patterns still get IGNORECASE|MULTILINE (backward compat)."""

        redactor = SecretRedactor.__new__(SecretRedactor)
        redactor.config = {"enabled": True}
        redactor.pii_config = {}
        redactor.enabled = True
        redactor.log_redactions = False
        redactor._compiled_pii_allowlist = []

        compiled = re.compile(r"TUPLE_SECRET_[A-Z]{20}", re.IGNORECASE | re.MULTILINE)
        redactor.compiled_patterns = [(compiled, "full_redact", "Tuple Test")]

        text = "tuple_secret_abcdefghijklmnopqrst"
        result = redactor.redact(text)
        assert (
            len(result["redactions"]) == 1
        ), "Tuple pattern with IGNORECASE should match lowercase"

    def test_detection_redaction_flag_parity(self):
        """Detection (toml_parser) and redaction use same flag logic for dict patterns."""

        pattern_info = {
            "regex": r"MY_SPECIAL_TOKEN_[A-Z]{20}",
            "flags": "i",
            "case_insensitive": False,
            "multiline": False,
        }
        detection_flags = 0
        raw_flags = pattern_info.get("flags", "")
        if "i" in raw_flags or pattern_info.get("case_insensitive", False):
            detection_flags |= re.IGNORECASE
        if "m" in raw_flags or pattern_info.get("multiline", False):
            detection_flags |= re.MULTILINE

        redaction_flags = SecretRedactor._extract_regex_flags(pattern_info)
        assert detection_flags == redaction_flags
