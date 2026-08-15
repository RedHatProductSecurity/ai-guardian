"""Tests for TomlPatternsScanner — Scanner SDK engine."""

from ai_guardian.patterns.cache import PatternCache
from ai_guardian.patterns.validators import shannon_entropy
from ai_guardian.scanners.sdk import Scanner, Finding
from ai_guardian.scanners.toml_patterns import TomlPatternsScanner


class TestTomlPatternsScanner:

    def test_is_scanner_subclass(self):
        scanner = TomlPatternsScanner()
        assert isinstance(scanner, Scanner)

    def test_name_and_version(self):
        scanner = TomlPatternsScanner()
        assert scanner.name == "toml-patterns"
        assert scanner.version == "1.0.0"

    def test_scan_finds_api_key(self):
        scanner = TomlPatternsScanner()
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert len(findings) >= 1
        assert any(f.rule_id == "openai-api-key" for f in findings)

    def test_scan_returns_finding_objects(self):
        scanner = TomlPatternsScanner()
        findings = scanner.scan(
            "Token: ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        )  # notsecret
        for f in findings:
            assert isinstance(f, Finding)
            assert f.rule_id
            assert f.line_number >= 1
            assert f.matched_text
            assert f.severity == "warning"

    def test_scan_no_match(self):
        scanner = TomlPatternsScanner()
        findings = scanner.scan("Nothing sensitive here at all.")
        secret_findings = [
            f
            for f in findings
            if f.rule_id.startswith("openai") or f.rule_id.startswith("github")
        ]
        assert len(secret_findings) == 0

    def test_scan_empty_content(self):
        scanner = TomlPatternsScanner()
        assert scanner.scan("") == []

    def test_has_rules_loaded(self):
        scanner = TomlPatternsScanner()
        assert scanner._cache.rule_count > 0

    def test_configure_additional_patterns(self):
        scanner = TomlPatternsScanner()
        initial_count = scanner._cache.rule_count
        scanner.configure(
            {
                "additional_patterns": [
                    {
                        "id": "custom-1",
                        "match_type": "regex",
                        "regex": "custom-secret-[0-9]+",
                    }
                ]
            }
        )
        assert scanner._cache.rule_count == initial_count + 1


class TestTomlPatternsPiiFiltering:
    """Secret scanner must NOT detect PII — PII is handled by the PII scanner (#1178)."""

    def test_scan_does_not_return_pii_findings(self):
        """Secret scanner must not return PII findings like email."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan("Contact: user@example.com")
        assert not any(f.rule_id.startswith("pii-") for f in findings)

    def test_scan_does_not_return_ssn(self):
        """Secret scanner must not detect SSN (PII scanner's job)."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan("SSN: 123-45-6789")
        assert not any(f.rule_id.startswith("pii-") for f in findings)

    def test_scan_does_not_return_credit_card(self):
        """Secret scanner must not detect credit cards (PII scanner's job)."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan("Card: 4111111111111111")
        assert not any(f.rule_id.startswith("pii-") for f in findings)

    def test_secrets_still_detected(self):
        """Secret detection must not regress after PII removal."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert any(f.rule_id == "openai-api-key" for f in findings)


class TestTomlPatternsFindingCategory:
    """Tests for category propagation through Finding objects (Issue #984)."""

    def test_secret_finding_has_secrets_category(self):
        scanner = TomlPatternsScanner()
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        secret_findings = [f for f in findings if f.rule_id == "openai-api-key"]
        assert len(secret_findings) >= 1
        assert secret_findings[0].category == "secrets"

    def test_no_pii_findings_from_secret_scanner(self):
        """Secret scanner must not produce PII-category findings (#1178)."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan("SSN: 123-45-6789")
        pii_findings = [f for f in findings if f.category == "pii"]
        assert len(pii_findings) == 0

    def test_finding_category_field_exists(self):
        """Finding dataclass has category attribute."""
        f = Finding(
            rule_id="test",
            line_number=1,
            matched_text="test",
            description="test",
            category="pii",
        )
        assert f.category == "pii"

    def test_finding_category_defaults_to_none(self):
        f = Finding(
            rule_id="test",
            line_number=1,
            matched_text="test",
            description="test",
        )
        assert f.category is None


class TestTomlPatternsGapFillingRules:
    """Tests for platform-specific gap-filling rules (Issue #972).

    These rules cover platforms NOT detected by gitleaks/leaktk engines.
    """

    def _find(self, text, rule_id):
        scanner = TomlPatternsScanner()
        findings = scanner.scan(text)
        return any(f.rule_id == rule_id for f in findings)

    # --- Payment / Financial ---

    def test_square_oauth_secret_detected(self):
        token = "sq0csp-" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCDEFG"
        assert self._find(f"SECRET={token}", "square-oauth-secret")

    def test_square_oauth_secret_placeholder_skipped(self):
        token = "sq0csp-" + "X" * 43
        assert not self._find(f"SECRET={token}", "square-oauth-secret")

    def test_square_access_token_not_matched_as_oauth_secret(self):
        # sq0atp- is an access token (covered by gitleaks), not our rule
        token = "sq0atp-" + "A" * 43
        assert not self._find(f"TOKEN={token}", "square-oauth-secret")

    def test_paypal_braintree_production_token(self):
        text = "token=access_token$production$abc123def456abcd"
        assert self._find(text, "paypal-braintree-token")

    def test_paypal_braintree_sandbox_token(self):
        text = "token=access_token$sandbox$abc123def456abcdef01"
        assert self._find(text, "paypal-braintree-token")

    def test_paypal_braintree_short_value_not_matched(self):
        # Value after $production$ must be >= 16 chars
        text = "token=access_token$production$short"
        assert not self._find(text, "paypal-braintree-token")

    def test_paypal_client_secret_env_var(self):
        text = "PAYPAL_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUvWx"
        assert self._find(text, "paypal-client-secret")

    def test_paypal_secret_case_insensitive(self):
        text = "paypal_secret = 'AbCdEfGhIjKlMnOpQrStUvWx'"
        assert self._find(text, "paypal-client-secret")

    def test_generic_secret_not_matched_as_paypal(self):
        text = "MY_SECRET=AbCdEfGhIjKlMnOpQrStUvWx"
        assert not self._find(text, "paypal-client-secret")

    # --- CI/CD ---

    def test_circleci_token_detected(self):
        text = "CIRCLE_TOKEN=" + "a1b2c3d4" * 5  # 40 hex chars
        assert self._find(text, "circleci-api-token")

    def test_circleci_ci_token_detected(self):
        text = "CIRCLECI_API_TOKEN=" + "abcdef01" * 5  # 40 hex chars
        assert self._find(text, "circleci-api-token")

    def test_circleci_non_hex_not_matched(self):
        text = "CIRCLE_TOKEN=not_a_real_hex_token_value_here"
        assert not self._find(text, "circleci-api-token")

    def test_jenkins_token_detected(self):
        text = "JENKINS_API_TOKEN=" + "a1b2c3d4" * 4 + "ab"  # 34 hex chars
        assert self._find(text, "jenkins-api-token")

    def test_jenkins_token_case_insensitive(self):
        text = "jenkins_token: " + "abcdef01" * 4  # 32 hex chars
        assert self._find(text, "jenkins-api-token")

    def test_jenkins_non_hex_not_matched(self):
        text = "JENKINS_TOKEN=not-hex-characters-here!"
        assert not self._find(text, "jenkins-api-token")

    # --- Database ---

    def test_mongodb_atlas_api_key_detected(self):
        text = "MONGODB_ATLAS_PRIVATE_KEY=abcd1234-ab12-cd34-ef56-abcdef123456"
        assert self._find(text, "mongodb-atlas-api-key")

    def test_mongo_atlas_key_variant(self):
        text = "MONGO_ATLAS_KEY: abcd1234-ab12-cd34-ef56-abcdef123456"
        assert self._find(text, "mongodb-atlas-api-key")

    def test_generic_uuid_without_atlas_context_not_matched(self):
        text = "REQUEST_ID=abcd1234-ab12-cd34-ef56-abcdef123456"
        assert not self._find(text, "mongodb-atlas-api-key")

    def test_supabase_service_role_key_detected(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.M2d_0djnGBiRw1rXznITPA"
        text = f"SUPABASE_SERVICE_ROLE_KEY={jwt}"
        assert self._find(text, "supabase-service-role-key")

    def test_supabase_anon_key_detected(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.ZopqoUt20nEV9cklpv9e3yw3PVyZLmKs5qLD6nGL1SI"
        text = f"SUPABASE_ANON_KEY={jwt}"
        assert self._find(text, "supabase-service-role-key")

    def test_generic_jwt_without_supabase_context_not_matched(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.ZopqoUt20nEV9cklpv9e3yw3PVyZLmKs5qLD6nGL1SI"
        text = f"AUTH_TOKEN={jwt}"
        assert not self._find(text, "supabase-service-role-key")

    # --- AI/ML ---

    def test_replicate_api_token_detected(self):
        token = "r8_" + "aBcDeFgHiJ" * 4  # 40 alphanumeric chars
        assert self._find(f"TOKEN={token}", "replicate-api-token")

    def test_replicate_placeholder_rejected(self):
        token = "r8_" + "X" * 40
        assert not self._find(f"TOKEN={token}", "replicate-api-token")

    def test_short_r8_prefix_not_matched(self):
        # r8_ followed by < 40 chars should not match
        text = "r8_shortvalue"
        assert not self._find(text, "replicate-api-token")

    # --- Issue #1777: AI/ML Provider Keys ---

    def test_groq_api_key_detected(self):
        token = "gsk_" + "a1B2c3D4" * 7
        assert self._find(f"TOKEN={token}", "groq-api-key")

    def test_groq_placeholder_rejected(self):
        token = "gsk_" + "X" * 52
        assert not self._find(f"TOKEN={token}", "groq-api-key")

    def test_groq_short_not_matched(self):
        assert not self._find("gsk_short", "groq-api-key")

    def test_xai_api_key_detected(self):
        token = "xai-" + "a1B2c3D4" * 10
        assert self._find(f"TOKEN={token}", "xai-api-key")

    def test_xai_short_not_matched(self):
        assert not self._find("xai-short", "xai-api-key")

    def test_nvidia_nim_api_key_detected(self):
        token = "nvapi-" + "a1B2c3D4" * 8
        assert self._find(f"TOKEN={token}", "nvidia-nim-api-key")

    def test_nvidia_nim_short_not_matched(self):
        assert not self._find("nvapi-short", "nvidia-nim-api-key")

    def test_new_relic_api_key_detected(self):
        token = "NRAK-" + "A1B2C3D4" * 3 + "A1B"
        assert self._find(f"TOKEN={token}", "new-relic-api-key")

    def test_new_relic_short_not_matched(self):
        assert not self._find("NRAK-SHORT", "new-relic-api-key")

    def test_langfuse_secret_key_detected(self):
        token = "sk-lf-" + "a1B2c3D4" * 5
        assert self._find(f"TOKEN={token}", "langfuse-secret-key")

    def test_langfuse_short_not_matched(self):
        assert not self._find("sk-lf-short", "langfuse-secret-key")

    def test_langsmith_pat_detected(self):
        token = "lsv2_pt_" + "a1b2c3d4" * 4 + "_" + "e5f6a7b8c9"
        assert self._find(f"TOKEN={token}", "langsmith-pat")

    def test_langsmith_service_key_detected(self):
        token = "lsv2_sk_" + "a1b2c3d4" * 4 + "_" + "e5f6a7b8c9"
        assert self._find(f"TOKEN={token}", "langsmith-service-key")

    def test_wandb_api_key_detected(self):
        token = "wandb_v1_" + "a1B2c3D4xYz" * 7
        assert self._find(f"TOKEN={token}", "wandb-api-key")

    def test_wandb_short_not_matched(self):
        assert not self._find("wandb_v1_short", "wandb-api-key")

    def test_cerebras_api_key_detected(self):
        token = "csk-" + "a1b2c3d4" * 6
        assert self._find(f"TOKEN={token}", "cerebras-api-key")

    def test_cerebras_short_not_matched(self):
        assert not self._find("csk-short", "cerebras-api-key")

    def test_together_ai_api_key_detected(self):
        token = "tgp_v1_" + "a1B2c3D4xYz" * 4
        assert self._find(f"TOKEN={token}", "together-ai-api-key")

    def test_together_ai_short_not_matched(self):
        assert not self._find("tgp_v1_short", "together-ai-api-key")

    def test_pinecone_api_key_detected(self):
        token = "pcsk_" + "AbCdEf" + "_" + "a1b2c3d4e5f6" * 5 + "a1b"
        assert self._find(f"TOKEN={token}", "pinecone-api-key")

    def test_pinecone_short_not_matched(self):
        assert not self._find("pcsk_short", "pinecone-api-key")

    def test_runpod_api_key_detected(self):
        token = "rpa_" + "A1B2C3D4" * 5 + "aBcDeF"
        assert self._find(f"TOKEN={token}", "runpod-api-key")

    def test_runpod_short_not_matched(self):
        assert not self._find("rpa_SHORT", "runpod-api-key")

    def test_minimax_api_key_detected(self):
        token = "sk-api-" + "a1B2c3D4" * 15
        assert self._find(f"TOKEN={token}", "minimax-api-key")

    def test_minimax_short_not_matched(self):
        assert not self._find("sk-api-short", "minimax-api-key")

    def test_devin_personal_api_key_detected(self):
        token = "apk_user_" + "a1B2c3D4" * 18
        assert self._find(f"TOKEN={token}", "devin-personal-api-key")

    def test_devin_service_api_key_detected(self):
        token = "apk_" + "a1B2c3D4" * 12
        assert self._find(f"TOKEN={token}", "devin-service-api-key")

    def test_azure_ad_client_secret_detected(self):
        token = "AbC1Q~" + "a1b2c3d4e5f6g7h8" * 2 + "x"
        assert self._find(f"SECRET={token}", "azure-ad-client-secret")

    def test_azure_ad_short_not_matched(self):
        assert not self._find("shortQ~val", "azure-ad-client-secret")

    # --- Issue #1986: Cloudflare, Figma, GitLab, Salesforce ---

    def test_cloudflare_user_api_token_detected(self):
        token = "cfut_" + "a1B2c3D4e5F6g7H8" * 3
        assert self._find(f"TOKEN={token}", "cloudflare-user-api-token")

    def test_cloudflare_user_api_token_placeholder_rejected(self):
        token = "cfut_" + "X" * 40
        assert not self._find(f"TOKEN={token}", "cloudflare-user-api-token")

    def test_cloudflare_user_api_token_short_not_matched(self):
        assert not self._find("cfut_short", "cloudflare-user-api-token")

    def test_cloudflare_account_api_token_detected(self):
        token = "cfat_" + "a1B2c3D4e5F6g7H8" * 3
        assert self._find(f"TOKEN={token}", "cloudflare-account-api-token")

    def test_cloudflare_account_api_token_placeholder_rejected(self):
        token = "cfat_" + "X" * 40
        assert not self._find(f"TOKEN={token}", "cloudflare-account-api-token")

    def test_cloudflare_user_api_key_detected(self):
        token = "cfk_" + "a1B2c3D4e5F6g7H8" * 2
        assert self._find(f"KEY={token}", "cloudflare-user-api-key")

    def test_cloudflare_user_api_key_placeholder_rejected(self):
        token = "cfk_" + "X" * 20
        assert not self._find(f"KEY={token}", "cloudflare-user-api-key")

    def test_figma_personal_access_token_detected(self):
        token = "figp_" + "a1B2c3D4e5F6g7H8" * 3
        assert self._find(f"TOKEN={token}", "figma-personal-access-token")

    def test_figma_personal_access_token_placeholder_rejected(self):
        token = "figp_" + "X" * 40
        assert not self._find(f"TOKEN={token}", "figma-personal-access-token")

    def test_figma_short_not_matched(self):
        assert not self._find("figp_short", "figma-personal-access-token")

    def test_gitlab_incoming_mail_token_detected(self):
        token = "glimt-" + "a1B2c3D4e5F6g7H8i9J0k1L2m"
        assert self._find(f"TOKEN={token}", "gitlab-incoming-mail-token")

    def test_gitlab_incoming_mail_token_placeholder_rejected(self):
        token = "glimt-" + "X" * 25
        assert not self._find(f"TOKEN={token}", "gitlab-incoming-mail-token")

    def test_gitlab_incoming_mail_token_short_not_matched(self):
        assert not self._find("glimt-short", "gitlab-incoming-mail-token")

    def test_salesforce_marketing_cloud_secret_detected(self):
        token = "SFMC_" + "a1B2c3D4" * 8
        assert self._find(f"SECRET={token}", "salesforce-marketing-cloud-secret")

    def test_salesforce_marketing_cloud_placeholder_rejected(self):
        token = "SFMC_" + "X" * 64
        assert not self._find(f"SECRET={token}", "salesforce-marketing-cloud-secret")

    def test_salesforce_marketing_cloud_short_not_matched(self):
        assert not self._find("SFMC_short", "salesforce-marketing-cloud-secret")


class TestTomlPatternsMultiLineColumns:
    """Tests for column calculation when match spans multiple lines (#1902)."""

    def test_single_line_match_no_end_line(self):
        scanner = TomlPatternsScanner()
        scanner._cache = PatternCache()
        scanner._cache.load_rules(
            [
                {
                    "id": "test-col",
                    "match_type": "regex",
                    "regex": r"sk-[a-z]{20,}",
                }
            ],
            category="secrets",
        )
        content = "prefix sk-abcdefghijklmnopqrstuvwxyz suffix"
        findings = scanner.scan(content)
        assert len(findings) >= 1
        f = findings[0]
        assert f.end_line is None
        assert f.start_column is not None
        assert f.end_column is not None
        assert f.start_column <= f.end_column

    def test_multi_line_match_sets_end_line(self):
        scanner = TomlPatternsScanner()
        scanner._cache = PatternCache()
        scanner._cache.load_rules(
            [
                {
                    "id": "test-multiline",
                    "match_type": "regex",
                    "regex": r"BEGIN[\s\S]{5,50}END",
                }
            ],
            category="secrets",
        )
        content = "line1 BEGIN\nsome content\nmore END here"
        findings = scanner.scan(content)
        assert len(findings) >= 1
        f = findings[0]
        assert f.end_line is not None
        assert f.end_line > f.line_number

    def test_multi_line_match_columns_are_line_relative(self):
        scanner = TomlPatternsScanner()
        scanner._cache = PatternCache()
        scanner._cache.load_rules(
            [
                {
                    "id": "test-multiline",
                    "match_type": "regex",
                    "regex": r"BEGIN[\s\S]{5,50}END",
                }
            ],
            category="secrets",
        )
        content = "aaaa BEGIN\nbbbb\ncc END rest"
        findings = scanner.scan(content)
        assert len(findings) >= 1
        f = findings[0]
        assert f.start_column == 5
        assert f.end_column is not None
        assert f.end_column <= len("cc END rest")


class TestTomlPatternsEngineBuilder:

    def test_select_toml_patterns_engine(self):
        from ai_guardian.scanners.engine_builder import _build_engine_config

        config = _build_engine_config("toml-patterns")
        assert config is not None
        assert config.type == "python"
        assert config.python_scanner is not None
        assert config.python_scanner.name == "toml-patterns"

    def test_select_toml_patterns_as_dict(self):
        from ai_guardian.scanners.engine_builder import _build_engine_config

        config = _build_engine_config({"type": "toml-patterns"})
        assert config is not None
        assert config.python_scanner.name == "toml-patterns"

    def test_select_engine_with_toml_patterns(self):
        from ai_guardian.scanners.engine_builder import select_engine

        config = select_engine(["toml-patterns"])
        assert config is not None
        assert config.python_scanner.name == "toml-patterns"


class TestTomlPatternsAllowlist:
    """Tests for scanner-level allowlist filtering (Issue #1093)."""

    def test_configure_allowlist_suppresses_matching_finding(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"allowlist_patterns": ["sk-abcdefghijklmnopqrstuvwxyz"]})
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert not any(f.rule_id == "openai-api-key" for f in findings)

    def test_allowlist_does_not_suppress_nonmatching(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"allowlist_patterns": ["some-other-pattern"]})
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert any(f.rule_id == "openai-api-key" for f in findings)

    def test_allowlist_empty_list_no_effect(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"allowlist_patterns": []})
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert any(f.rule_id == "openai-api-key" for f in findings)

    def test_allowlist_none_no_effect(self):
        scanner = TomlPatternsScanner()
        scanner.configure({})
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert any(f.rule_id == "openai-api-key" for f in findings)

    def test_allowlist_dangerous_pattern_blocked(self):
        """compile_allowlist strips catch-all patterns like '.*'."""
        scanner = TomlPatternsScanner()
        scanner.configure({"allowlist_patterns": [".*"]})
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert any(f.rule_id == "openai-api-key" for f in findings)


class TestTomlPatternsIgnoreFiles:
    """Tests for scanner-level ignore_files filtering (Issue #1093)."""

    def test_ignore_files_matching_path_returns_empty(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"ignore_files": ["**/tests/fixtures/**"]})
        findings = scanner.scan(
            "Config: sk-abcdefghijklmnopqrstuvwxyz",
            file_path="/project/tests/fixtures/creds.json",
        )
        assert findings == []

    def test_ignore_files_nonmatching_path_scans_normally(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"ignore_files": ["**/tests/fixtures/**"]})
        findings = scanner.scan(
            "Config: sk-abcdefghijklmnopqrstuvwxyz",
            file_path="/project/src/main.py",
        )
        assert any(f.rule_id == "openai-api-key" for f in findings)

    def test_ignore_files_none_file_path_scans_normally(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"ignore_files": ["**/tests/**"]})
        findings = scanner.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert any(f.rule_id == "openai-api-key" for f in findings)

    def test_ignore_files_empty_list_scans_normally(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"ignore_files": []})
        findings = scanner.scan(
            "Config: sk-abcdefghijklmnopqrstuvwxyz",
            file_path="/project/src/main.py",
        )
        assert any(f.rule_id == "openai-api-key" for f in findings)

    def test_ignore_files_basename_matching(self):
        scanner = TomlPatternsScanner()
        scanner.configure({"ignore_files": ["*.fixture"]})
        findings = scanner.scan(
            "Config: sk-abcdefghijklmnopqrstuvwxyz",
            file_path="/project/data/creds.fixture",
        )
        assert findings == []


class TestTomlPatternsAllowlistAndIgnoreInteraction:
    """Test interaction between allowlist and ignore_files (Issue #1093)."""

    def test_ignore_files_takes_precedence(self):
        """Ignored file returns [] without even checking allowlist."""
        scanner = TomlPatternsScanner()
        scanner.configure(
            {
                "allowlist_patterns": ["some-pattern"],
                "ignore_files": ["**/fixtures/**"],
            }
        )
        findings = scanner.scan(
            "Config: sk-abcdefghijklmnopqrstuvwxyz",
            file_path="/project/fixtures/test.json",
        )
        assert findings == []

    def test_allowlist_filters_when_not_ignored(self):
        scanner = TomlPatternsScanner()
        scanner.configure(
            {
                "allowlist_patterns": ["sk-abcdefghijklmnopqrstuvwxyz"],
                "ignore_files": ["**/fixtures/**"],
            }
        )
        findings = scanner.scan(
            "Config: sk-abcdefghijklmnopqrstuvwxyz",
            file_path="/project/src/main.py",
        )
        assert not any(f.rule_id == "openai-api-key" for f in findings)


class TestShannonEntropy:
    """Tests for the shannon_entropy utility (Issue #1091)."""

    def test_empty_string_returns_zero(self):
        assert shannon_entropy("") == 0.0

    def test_single_char_returns_zero(self):
        assert shannon_entropy("a") == 0.0

    def test_repeated_chars_returns_zero(self):
        assert shannon_entropy("aaaaaaa") == 0.0

    def test_two_distinct_chars_equal_frequency(self):
        result = shannon_entropy("abababab")
        assert abs(result - 1.0) < 0.01

    def test_random_alphanum_high_entropy(self):
        result = shannon_entropy("aB3kQ9xLm7Zy2pR4wE6t")
        assert result > 3.5

    def test_low_entropy_placeholder(self):
        result = shannon_entropy("XXXXXXXXXXXXXXXXXXXX")
        assert result == 0.0

    def test_moderate_entropy_string(self):
        result = shannon_entropy("password123")
        assert 2.0 < result < 4.0


class TestTomlPatternsKeywordPreFilter:
    """Tests for keyword pre-filtering in PatternCache (Issue #1091)."""

    def test_keyword_present_allows_match(self):
        """Rule with keywords fires when keyword is in content."""
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-keyword-rule",
                    "match_type": "regex",
                    "regex": r"sk-[a-z]{20,}",
                    "keywords": ["sk-"],
                }
            ],
            category="secrets",
        )
        findings = cache.scan("Config: sk-abcdefghijklmnopqrstuvwxyz")
        assert len(findings) >= 1

    def test_keyword_absent_skips_rule(self):
        """Rule with keywords does NOT fire when keyword is missing."""
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-keyword-rule",
                    "match_type": "regex",
                    "regex": r"sk-[a-z]{20,}",
                    "keywords": ["sk-"],
                }
            ],
            category="secrets",
        )
        findings = cache.scan("This text has no relevant prefix")
        assert len(findings) == 0

    def test_keyword_case_insensitive(self):
        """Keyword matching is case-insensitive."""
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-keyword-rule",
                    "match_type": "regex",
                    "regex": r"(?i)token-[a-z0-9]{10,}",
                    "keywords": ["TOKEN-"],
                }
            ],
            category="secrets",
        )
        findings = cache.scan("value: token-abc1234567890")
        assert len(findings) >= 1

    def test_no_keywords_fires_on_all_content(self):
        """Rules without keywords field fire on any matching content."""
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-no-keyword-rule",
                    "match_type": "regex",
                    "regex": r"secret-[a-z]{10,}",
                }
            ],
            category="secrets",
        )
        findings = cache.scan("found: secret-abcdefghijklmnop")
        assert len(findings) >= 1


class TestTomlPatternsEntropyFilter:
    """Tests for per-rule entropy filtering (Issue #1091)."""

    def test_high_entropy_match_passes(self):
        """Match with entropy above threshold is kept."""
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-entropy-rule",
                    "match_type": "regex",
                    "regex": r"key-[A-Za-z0-9]{20,}",
                    "entropy": 3.0,
                }
            ],
            category="secrets",
        )
        findings = cache.scan("value: key-aB3kQ9xLm7Zy2pR4wE6tX")
        assert len(findings) >= 1

    def test_low_entropy_match_rejected(self):
        """Match with entropy below threshold is filtered out."""
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-entropy-rule",
                    "match_type": "regex",
                    "regex": r"key-[A-Za-z]{20,}",
                    "entropy": 3.0,
                }
            ],
            category="secrets",
        )
        findings = cache.scan("value: key-aaaaaaaaaaaaaaaaaaaaaaa")
        assert len(findings) == 0

    def test_no_entropy_field_passes_all(self):
        """Rules without entropy field accept all matches."""
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-no-entropy",
                    "match_type": "regex",
                    "regex": r"key-[A-Za-z]{20,}",
                }
            ],
            category="secrets",
        )
        findings = cache.scan("value: key-aaaaaaaaaaaaaaaaaaaaaaa")
        assert len(findings) >= 1


class TestTomlPatternsStopwords:
    """Tests for stopword filtering (Issue #1091)."""

    def test_bundled_stopwords_loaded(self):
        scanner = TomlPatternsScanner()
        assert len(scanner._stopwords) > 0

    def test_stopword_suppresses_matching_finding(self):
        """A match containing a stopword is filtered out."""
        scanner = TomlPatternsScanner()
        assert "example" in scanner._stopwords
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-stop",
                    "match_type": "regex",
                    "regex": r"key-[a-z_]+",
                }
            ],
            category="secrets",
        )
        scanner._cache = cache
        findings = scanner.scan("value: key-example_value")
        assert not any(f.rule_id == "test-stop" for f in findings)

    def test_stopword_does_not_suppress_non_matching(self):
        """A match NOT containing a stopword is kept."""
        scanner = TomlPatternsScanner()
        from ai_guardian.patterns.cache import PatternCache

        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "test-stop",
                    "match_type": "regex",
                    "regex": r"key-[a-z]{20,}",
                }
            ],
            category="secrets",
        )
        scanner._cache = cache
        findings = scanner.scan("value: key-abcdefghijklmnopqrstuvwxyz")
        assert any(f.rule_id == "test-stop" for f in findings)

    def test_user_stopwords_extend_bundled(self):
        scanner = TomlPatternsScanner()
        initial_count = len(scanner._stopwords)
        scanner.configure({"stopwords": ["mycompanystopword"]})
        assert len(scanner._stopwords) == initial_count + 1
        assert "mycompanystopword" in scanner._stopwords

    def test_short_stopwords_rejected(self):
        scanner = TomlPatternsScanner()
        initial_count = len(scanner._stopwords)
        scanner.configure({"stopwords": ["ab"]})
        assert len(scanner._stopwords) == initial_count

    def test_duplicate_stopwords_not_added(self):
        scanner = TomlPatternsScanner()
        initial_count = len(scanner._stopwords)
        scanner.configure({"stopwords": ["example"]})
        assert len(scanner._stopwords) == initial_count

    def test_secret_scanner_does_not_produce_pii(self):
        """Secret scanner does not produce PII findings (#1178)."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan("Contact: test@example.com")
        assert not any(f.rule_id.startswith("pii-") for f in findings)


class TestTomlPatternsSkipFileTypes:
    """Tests for per-rule skip_file_types filtering (Issue #1586)."""

    def test_skip_file_types_skips_matching_extension(self):
        """Rule with skip_file_types is skipped when file extension matches."""
        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "yaml-only-rule",
                    "match_type": "regex",
                    "regex": r"password:\s*\S+",
                    "skip_file_types": [".py", ".js"],
                }
            ],
            category="secrets",
        )
        findings = cache.scan("password: mysecretvalue", file_ext=".py")
        assert len(findings) == 0

    def test_skip_file_types_allows_non_matching_extension(self):
        """Rule fires when file extension is not in skip_file_types."""
        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "yaml-only-rule",
                    "match_type": "regex",
                    "regex": r"password:\s*\S+",
                    "skip_file_types": [".py", ".js"],
                }
            ],
            category="secrets",
        )
        findings = cache.scan("password: mysecretvalue", file_ext=".yaml")
        assert len(findings) >= 1

    def test_skip_file_types_no_file_ext_runs_all(self):
        """All rules run when file_ext is None (safe default)."""
        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "yaml-only-rule",
                    "match_type": "regex",
                    "regex": r"password:\s*\S+",
                    "skip_file_types": [".py", ".js"],
                }
            ],
            category="secrets",
        )
        findings = cache.scan("password: mysecretvalue")
        assert len(findings) >= 1

    def test_skip_file_types_empty_list_runs_all(self):
        """Rule without skip_file_types runs on all file types."""
        cache = PatternCache()
        cache.load_rules(
            [
                {
                    "id": "universal-rule",
                    "match_type": "regex",
                    "regex": r"sk-[a-z]{20,}",
                }
            ],
            category="secrets",
        )
        findings = cache.scan("sk-abcdefghijklmnopqrstuvwxyz", file_ext=".py")
        assert len(findings) >= 1

    def test_scanner_extracts_extension_from_file_path(self):
        """TomlPatternsScanner passes file extension to cache."""
        scanner = TomlPatternsScanner()
        scanner._cache = PatternCache()
        scanner._cache.load_rules(
            [
                {
                    "id": "yaml-only-rule",
                    "match_type": "regex",
                    "regex": r"password:\s*\S{8,}",
                    "skip_file_types": [".py"],
                }
            ],
            category="secrets",
        )
        findings_py = scanner.scan(
            "password: MySecret123", file_path="/tmp/aiguardian_config.py"
        )
        findings_yaml = scanner.scan(
            "password: MySecret123", file_path="/tmp/aiguardian_config.yaml"
        )
        assert len(findings_py) == 0
        assert len(findings_yaml) >= 1

    def test_scanner_no_file_path_runs_all_rules(self):
        """Scanner runs all rules when no file_path is provided."""
        scanner = TomlPatternsScanner()
        scanner._cache = PatternCache()
        scanner._cache.load_rules(
            [
                {
                    "id": "yaml-only-rule",
                    "match_type": "regex",
                    "regex": r"password:\s*\S{8,}",
                    "skip_file_types": [".py"],
                }
            ],
            category="secrets",
        )
        findings = scanner.scan("password: MySecret123")
        assert len(findings) >= 1

    def test_yaml_password_rule_skipped_on_python_file(self):
        """Bundled yaml-password rule has skip_file_types including .py."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan(
            "password: SuperSecretPassword123",
            file_path="/tmp/aiguardian_app.py",
        )
        yaml_pw = [f for f in findings if f.rule_id == "yaml-password"]
        assert len(yaml_pw) == 0

    def test_yaml_password_rule_fires_on_yaml_file(self):
        """Bundled yaml-password rule fires on .yaml files."""
        scanner = TomlPatternsScanner()
        findings = scanner.scan(
            "password: SuperSecretPassword123",
            file_path="/tmp/aiguardian_config.yaml",
        )
        yaml_pw = [f for f in findings if f.rule_id == "yaml-password"]
        assert len(yaml_pw) >= 1
