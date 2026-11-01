"""Tests for human-readable secret type display names."""

from ai_guardian.scanners.secret_types import SECRET_TYPE_NAMES, get_secret_type_display


class TestSecretTypeNames:
    """Tests for the SECRET_TYPE_NAMES mapping."""

    def test_known_secret_types(self):
        assert get_secret_type_display("openai-api-key") == "OpenAI API Key"
        assert (
            get_secret_type_display("github-personal-token") == "GitHub Personal Token"
        )
        assert get_secret_type_display("anthropic-api-key") == "Anthropic API Key"
        assert get_secret_type_display("env-variable") == "Environment Variable"
        assert get_secret_type_display("private-key") == "Private Key"

    def test_issue_2632_credential_display_names(self):
        assert get_secret_type_display("baseten-api-key") == "Baseten API Key"
        assert get_secret_type_display("labelbox-api-key") == "Labelbox API Key"
        assert get_secret_type_display("recursion-api-key") == "Recursion API Key"
        assert (
            get_secret_type_display("supabase-project-api-key")
            == "Supabase Project API Key"
        )
        assert get_secret_type_display("tailscale-api-key") == "Tailscale API Key"
        assert get_secret_type_display("tailscale-auth-key") == "Tailscale Auth Key"
        assert (
            get_secret_type_display("tailscale-oauth-client-secret")
            == "Tailscale OAuth Client Secret"
        )
        assert (
            get_secret_type_display("tailscale-webhook-secret")
            == "Tailscale Webhook Secret"
        )

    def test_known_pii_types(self):
        assert get_secret_type_display("pii-ssn") == "Social Security Number (SSN)"
        assert get_secret_type_display("pii-credit-card") == "Credit Card Number"
        assert get_secret_type_display("pii-iban") == "IBAN Number"

    def test_known_gitleaks_types(self):
        assert get_secret_type_display("generic-api-key") == "Generic API Key"
        assert get_secret_type_display("github-pat") == "GitHub Personal Access Token"
        assert get_secret_type_display("slack-bot-token") == "Slack Bot Token"

    def test_unknown_rule_id_fallback(self):
        assert get_secret_type_display("custom-scanner-rule") == "Custom Scanner Rule"
        assert get_secret_type_display("my-new-detector") == "My New Detector"

    def test_single_word_fallback(self):
        assert get_secret_type_display("password") == "Password"

    def test_unknown_value(self):
        assert get_secret_type_display("Unknown") == "Unknown"

    def test_empty_string(self):
        assert get_secret_type_display("") == "Unknown"

    def test_none_value(self):
        assert get_secret_type_display(None) == "Unknown"

    def test_mapping_not_empty(self):
        assert len(SECRET_TYPE_NAMES) > 50

    def test_all_values_are_strings(self):
        for rule_id, display_name in SECRET_TYPE_NAMES.items():
            assert isinstance(rule_id, str), f"Key {rule_id!r} is not a string"
            assert isinstance(display_name, str), f"Value for {rule_id} is not a string"
            assert len(display_name) > 0, f"Empty display name for {rule_id}"


class TestBuildSecretDetectedMessage:
    """Test that _build_secret_detected_message uses display names."""

    def test_block_message_shows_display_name(self):
        from ai_guardian.scanners.secret_scanning import _build_secret_detected_message

        secret_details = {
            "rule_id": "openai-api-key",
            "file": "config.py",
            "line_number": 42,
        }
        msg = _build_secret_detected_message(
            "gitleaks", secret_details, "built-in rules"
        )
        assert "OpenAI API Key" in msg
        assert "openai-api-key" not in msg

    def test_block_message_unknown_rule_id(self):
        from ai_guardian.scanners.secret_scanning import _build_secret_detected_message

        secret_details = {
            "rule_id": "some-new-scanner-rule",
            "file": "test.py",
        }
        msg = _build_secret_detected_message(
            "gitleaks", secret_details, "built-in rules"
        )
        assert "Some New Scanner Rule" in msg

    def test_block_message_no_details(self):
        from ai_guardian.scanners.secret_scanning import _build_secret_detected_message

        msg = _build_secret_detected_message("gitleaks", None, "built-in rules")
        assert "(multiple or unknown)" in msg


class TestSarifFormatterDisplayName:
    """Test that SARIF formatter uses display names."""

    def test_sarif_finding_message(self):
        from ai_guardian.reporting.sarif import create_secret_finding

        finding = create_secret_finding("github-personal-token", "test.py", 10)
        assert finding["message"] == "Secret detected: GitHub Personal Token"
        assert finding["details"]["secret_type"] == "github-personal-token"
