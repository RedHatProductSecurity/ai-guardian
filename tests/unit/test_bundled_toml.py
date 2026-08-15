"""Tests for bundled TOML pattern files.

Validates that all bundled TOML files parse correctly and contain
the expected number of compiled rules.
"""

import pytest

from ai_guardian.patterns import DATA_DIR
from ai_guardian.patterns.toml_parser import load_and_compile, load_toml_file

PATTERNS_DIR = DATA_DIR

EXPECTED_COUNTS = {
    "secrets.toml": 107,
    "pii.toml": 13,
    "prompt-injection.toml": 73,
    "unicode.toml": 107,
    "config-exfil.toml": 10,  # Updated for Issue #1100: added curl @file patterns
    "ssrf.toml": 24,
}


class TestBundledTomlFiles:

    @pytest.mark.parametrize("filename", list(EXPECTED_COUNTS.keys()))
    def test_file_exists(self, filename):
        path = PATTERNS_DIR / filename
        assert path.exists(), f"Missing bundled pattern file: {path}"

    @pytest.mark.parametrize("filename,expected", list(EXPECTED_COUNTS.items()))
    def test_rule_count_matches(self, filename, expected):
        path = PATTERNS_DIR / filename
        category = filename.replace(".toml", "").replace("-", "_")
        rules = load_and_compile(path, category)
        assert (
            len(rules) == expected
        ), f"{filename}: expected {expected} rules, got {len(rules)}"

    @pytest.mark.parametrize("filename", list(EXPECTED_COUNTS.keys()))
    def test_all_rules_have_ids(self, filename):
        path = PATTERNS_DIR / filename
        raw_rules = load_toml_file(path)
        for i, rule in enumerate(raw_rules):
            assert "id" in rule, f"{filename} rule {i}: missing 'id' field"
            assert rule["id"], f"{filename} rule {i}: empty 'id' field"

    @pytest.mark.parametrize("filename", list(EXPECTED_COUNTS.keys()))
    def test_all_rules_have_match_type(self, filename):
        path = PATTERNS_DIR / filename
        raw_rules = load_toml_file(path)
        for rule in raw_rules:
            assert (
                "match_type" in rule
            ), f"{filename} rule {rule.get('id', '?')}: missing 'match_type'"

    @pytest.mark.parametrize("filename", list(EXPECTED_COUNTS.keys()))
    def test_unique_ids(self, filename):
        path = PATTERNS_DIR / filename
        raw_rules = load_toml_file(path)
        ids = [r["id"] for r in raw_rules]
        dupes = [x for x in ids if ids.count(x) > 1]
        assert not dupes, f"{filename}: duplicate rule IDs: {set(dupes)}"

    def test_total_rule_count(self):
        total = 0
        for filename, expected in EXPECTED_COUNTS.items():
            path = PATTERNS_DIR / filename
            category = filename.replace(".toml", "").replace("-", "_")
            rules = load_and_compile(path, category)
            total += len(rules)
        assert total == sum(
            EXPECTED_COUNTS.values()
        ), f"Total rules mismatch: {total} != {sum(EXPECTED_COUNTS.values())}"

    def test_secrets_have_redaction_strategy(self):
        path = PATTERNS_DIR / "secrets.toml"
        rules = load_and_compile(path, "secrets")
        for rule in rules:
            assert (
                "redaction_strategy" in rule.metadata
            ), f"Secret rule {rule.id}: missing redaction_strategy"

    def test_pii_have_pii_type(self):
        path = PATTERNS_DIR / "pii.toml"
        rules = load_and_compile(path, "pii")
        for rule in rules:
            assert "pii_type" in rule.metadata, f"PII rule {rule.id}: missing pii_type"

    def test_prompt_injection_have_group(self):
        path = PATTERNS_DIR / "prompt-injection.toml"
        rules = load_and_compile(path, "prompt_injection")
        valid_groups = {"critical", "documentation", "jailbreak", "suspicious"}
        for rule in rules:
            assert "group" in rule.metadata, f"PI rule {rule.id}: missing group"
            assert (
                rule.metadata["group"] in valid_groups
            ), f"PI rule {rule.id}: invalid group '{rule.metadata['group']}'"

    def test_prompt_injection_group_counts(self):
        path = PATTERNS_DIR / "prompt-injection.toml"
        rules = load_and_compile(path, "prompt_injection")
        counts = {}
        for rule in rules:
            group = rule.metadata.get("group", "unknown")
            counts[group] = counts.get(group, 0) + 1
        assert counts.get("critical", 0) == 32
        assert counts.get("documentation", 0) == 20
        assert counts.get("jailbreak", 0) == 14
        assert counts.get("suspicious", 0) == 7


@pytest.fixture(scope="module")
def secret_rules():
    path = PATTERNS_DIR / "secrets.toml"
    return {r.id: r for r in load_and_compile(path, "secrets")}


NEW_SECRET_DETECTION_CASES = [
    ("huggingface-access-token", 'token = "hf_' + "A" * 34 + '"'),
    ("huggingface-organization-api-token", 'key = "api_org_' + "B" * 34 + '"'),
    ("github-fine-grained-pat", 'GITHUB_TOKEN="github_pat_' + "A" * 82 + '"'),
    ("github-user-token", 'token = "ghu_' + "A" * 36 + '"'),
    ("aws-amazon-bedrock-api-key-long-lived", 'key = "ABSK' + "A" * 109 + '"'),
    ("perplexity-api-key", 'PERPLEXITY_API_KEY="pplx-' + "a" * 48 + '"'),
]

NEW_SECRET_FALSE_POSITIVE_CASES = [
    ("huggingface-access-token", "# hf_ refers to HuggingFace token format"),
    ("huggingface-access-token", "hf_short"),
    ("huggingface-organization-api-token", "# api_org_ is the HuggingFace org prefix"),
    ("github-fine-grained-pat", "github_pat_tooshort"),
    ("github-fine-grained-pat", "# github_pat_ is the new fine-grained PAT prefix"),
    ("github-user-token", "# ghu_ prefix for GitHub user tokens"),
    ("github-user-token", "ghu_abc123"),
    ("aws-amazon-bedrock-api-key-long-lived", "ABSK" + "A" * 10),
    (
        "aws-amazon-bedrock-api-key-long-lived",
        "# ABSK prefix for Bedrock long-lived keys",
    ),
    ("perplexity-api-key", "# pplx- is the Perplexity API key prefix"),
    ("perplexity-api-key", "pplx-tooshort"),
]


ISSUE_1617_DETECTION_CASES = [
    ("openrouter-api-key", 'OPENROUTER_API_KEY="sk-or-v1-' + "a" * 48 + '"'),
    ("openrouter-api-key", "sk-or-v1-" + "A" * 64),
    ("google-gemini-auth-key", 'GEMINI_KEY="AQ.Ab' + "x" * 35 + '"'),
    ("google-gemini-auth-key", "AQ." + "A" * 37),
    ("hashicorp-vault-token", 'VAULT_TOKEN="hvs.' + "A" * 30 + '"'),
    ("hashicorp-vault-token", "hvb." + "A" * 24),
    ("hashicorp-vault-token", "hvr." + "A" * 30),
    ("confluent-cloud-api-key", "cflt" + "A" * 56),
    ("confluent-cloud-api-key", "cflt" + "A" * 60),
    ("confluent-cloud-api-key", "cflt" + "A" * 64),
    ("confluent-cloud-api-key", 'key = "cflt' + "a" * 60 + '"'),
]

ISSUE_1617_FALSE_POSITIVE_CASES = [
    ("openrouter-api-key", "sk-or-v1-tooshort"),
    ("openrouter-api-key", "# sk-or-v1- is the OpenRouter prefix"),
    ("google-gemini-auth-key", "AQ.short"),
    ("google-gemini-auth-key", "# AQ. prefix is for Gemini auth keys"),
    ("hashicorp-vault-token", "hvs.short"),
    ("hashicorp-vault-token", "# hvs. prefix for Vault service tokens"),
    ("confluent-cloud-api-key", "cflt" + "A" * 10),
    ("confluent-cloud-api-key", "cflt" + "A" * 55),
    ("confluent-cloud-api-key", "# cflt prefix for Confluent keys"),
]

GITLEAKS_DETECTION_CASES = [
    ("cohere-api-token", 'COHERE_API_KEY="' + "a" * 40 + '"'),
    ("cohere-api-token", "cohere_token = '" + "B" * 40 + "'"),
    ("doppler-api-token", 'TOKEN="dp.pt.' + "a" * 43 + '"'),
    ("hashicorp-tf-api-token", 'token = "' + "a" * 14 + ".atlasv1." + "b" * 65 + '"'),
    ("pulumi-api-token", 'PULUMI_ACCESS_TOKEN="pul-' + "a" * 40 + '"'),
    ("grafana-cloud-api-token", 'token = "glc_' + "A" * 40 + '"'),
    (
        "grafana-service-account-token",
        'token = "glsa_' + "A" * 32 + "_" + "a" * 8 + '"',
    ),
    ("sentry-org-token", 'token = "sntrys_eyJ' + "A" * 100 + '"'),
    ("sentry-user-token", 'token = "sntryu_' + "a" * 64 + '"'),
    ("sentry-access-token", 'SENTRY_AUTH_TOKEN="' + "a" * 64 + '"'),
    ("datadog-access-token", 'DATADOG_API_KEY="' + "a" * 40 + '"'),
    ("cloudflare-api-key", 'CLOUDFLARE_API_KEY="' + "a" * 40 + '"'),
    ("digitalocean-access-token", 'token = "doo_v1_' + "a" * 64 + '"'),
    ("digitalocean-pat", 'DO_TOKEN="dop_v1_' + "a" * 64 + '"'),
    ("digitalocean-refresh-token", 'refresh = "dor_v1_' + "a" * 64 + '"'),
    ("alibaba-access-key-id", 'key = "LTAI' + "A" * 20 + '"'),
    ("snyk-api-token", 'SNYK_TOKEN="a1b2c3d4-e5f6-7890-abcd-ef1234567890"'),
    ("sourcegraph-access-token", 'token = "sgp_' + "a" * 40 + '"'),
    ("sourcegraph-access-token", 'token = "sgp_' + "a" * 16 + "_" + "b" * 40 + '"'),
    ("linear-api-key", 'LINEAR_API_KEY="lin_api_' + "a" * 40 + '"'),
    ("notion-api-token", 'token = "ntn_' + "1" * 11 + "A" * 35 + '"'),
    ("postman-api-token", 'key = "PMAK-' + "a" * 24 + "-" + "b" * 34 + '"'),
    ("1password-service-account-token", 'token = "ops_eyJ' + "A" * 260 + '"'),
]

ISSUE_1678_DETECTION_CASES = [
    (
        "credentials-in-git-url",
        "https://x-access-token:eyJhbGciOiJSUzI1NiJ9.eyJzdWI@github.com/org/repo.git",
    ),
    (
        "credentials-in-git-url",
        "https://oauth2:some-long-pat-value@gitlab.com/org/repo.git",
    ),
    (
        "credentials-in-git-url",
        "https://user:" + "supersecret" + "password" + "@bitbucket.org/team/repo.git",
    ),
    (
        "credentials-in-git-url",
        "https://token:" + "A" * 40 + "@dev.azure.com/org/project/_git/repo",
    ),
    (
        "credentials-in-git-url",
        "http://deploy:ghp_" + "A" * 36 + "@github.com/org/repo.git",
    ),
]

ISSUE_1678_FALSE_POSITIVE_CASES = [
    ("credentials-in-git-url", "https://user:short@github.com/org/repo.git"),
    ("credentials-in-git-url", "https://user:PASSWORD@github.com/example"),
    ("credentials-in-git-url", "https://user:TOKEN@gitlab.com/example"),
    ("credentials-in-git-url", "https://user:YOUR_TOKEN@bitbucket.org/example"),
    ("credentials-in-git-url", "https://user:xxxxxxxx@github.com/example"),
    ("credentials-in-git-url", "https://registry.npmjs.org/@scope/package"),
    ("credentials-in-git-url", "https://user:port@randomhost.com/path"),
    ("credentials-in-git-url", "https://user:$GITHUB_TOKEN@github.com/org/repo"),
    ("credentials-in-git-url", "https://user:${GIT_PASSWORD}@gitlab.com/org/repo"),
    ("credentials-in-git-url", "https://user:%GIT_TOKEN%@github.com/org/repo"),
]

GITLEAKS_FALSE_POSITIVE_CASES = [
    ("cohere-api-token", 'cohere_key = "abc123"'),
    ("doppler-api-token", "dp.pt.tooshort"),
    ("hashicorp-tf-api-token", "# atlasv1 is the Terraform token prefix"),
    ("pulumi-api-token", "pul-tooshort"),
    ("grafana-cloud-api-token", "glc_short"),
    ("grafana-service-account-token", "glsa_short_ab"),
    ("sentry-org-token", "sntrys_eyJ" + "A" * 10),
    ("sentry-user-token", "sntryu_tooshort"),
    ("sentry-access-token", "a" * 64),
    ("datadog-access-token", "a" * 40),
    ("cloudflare-api-key", "a" * 40),
    ("digitalocean-access-token", "doo_v1_short"),
    ("digitalocean-pat", "dop_v1_short"),
    ("digitalocean-refresh-token", "dor_v1_short"),
    ("alibaba-access-key-id", "LTAIshort"),
    ("snyk-api-token", "a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    ("sourcegraph-access-token", "sgp_tooshort"),
    ("linear-api-key", "lin_api_short"),
    ("notion-api-token", "ntn_123short"),
    ("postman-api-token", "PMAK-short-tooshort"),
    ("1password-service-account-token", "ops_eyJ" + "A" * 10),
]

ISSUE_1777_DETECTION_CASES = [
    ("groq-api-key", "GROQ_API_KEY=" + "gsk_" + "a1B2c3D4" * 7),
    ("groq-api-key", 'key = "gsk_' + "xYz9AbCd" * 7 + '"'),
    ("xai-api-key", "XAI_API_KEY=" + "xai-" + "a1B2c3D4" * 10),
    ("xai-api-key", 'key = "xai-' + "xYz9AbCd" * 13 + '"'),
    ("nvidia-nim-api-key", "NVIDIA_API_KEY=" + "nvapi-" + "a1B2c3D4" * 8),
    ("nvidia-nim-api-key", 'key = "nvapi-' + "xYz9AbCd" * 8 + '"'),
    ("new-relic-api-key", 'NEWRELIC_KEY="' + "NRAK-" + "A1B2C3D4" * 3 + "A1B" + '"'),
    ("langfuse-secret-key", 'LANGFUSE_SK="sk-lf-' + "a1B2c3D4" * 5 + '"'),
    ("langfuse-secret-key", "sk-lf-" + "xYz9AbCd" * 5),
    ("langsmith-pat", "lsv2_pt_" + "a1b2c3d4" * 4 + "_" + "e5f6a7b8c9"),
    ("langsmith-service-key", "lsv2_sk_" + "a1b2c3d4" * 4 + "_" + "e5f6a7b8c9"),
    ("wandb-api-key", "WANDB_API_KEY=" + "wandb_v1_" + "a1B2c3D4xYz" * 7),
    ("cerebras-api-key", "CEREBRAS_KEY=" + "csk-" + "a1b2c3d4" * 6),
    ("together-ai-api-key", "TOGETHER_KEY=" + "tgp_v1_" + "a1B2c3D4xYz" * 4),
    ("devin-personal-api-key", "DEVIN_KEY=" + "apk_user_" + "a1B2c3D4" * 18),
    ("devin-service-api-key", "DEVIN_KEY=" + "apk_" + "a1B2c3D4" * 12),
    ("pinecone-api-key", "pcsk_" + "AbCdEf" + "_" + "a1b2c3d4e5f6" * 5 + "a1b"),
    ("runpod-api-key", "rpa_" + "A1B2C3D4" * 5 + "aBcDeF"),
    ("minimax-api-key", "sk-api-" + "a1B2c3D4" * 15),
    ("azure-ad-client-secret", "AbC1Q~" + "a1b2c3d4e5f6g7h8" * 2 + "x"),
]

ISSUE_1777_FALSE_POSITIVE_CASES = [
    ("groq-api-key", "gsk_short"),
    ("groq-api-key", "# gsk_ is the Groq API key prefix"),
    ("xai-api-key", "xai-tooshort"),
    ("xai-api-key", "# xai- is the xAI API key prefix"),
    ("nvidia-nim-api-key", "nvapi-short"),
    ("nvidia-nim-api-key", "# nvapi- is the NVIDIA NIM prefix"),
    ("new-relic-api-key", "NRAK-SHORT"),
    ("new-relic-api-key", "# NRAK- is the New Relic API key prefix"),
    ("langfuse-secret-key", "sk-lf-short"),
    ("langfuse-secret-key", "# sk-lf- is LangFuse secret key prefix"),
    ("langsmith-pat", "lsv2_pt_tooshort"),
    ("langsmith-pat", "# lsv2_pt_ is LangSmith PAT prefix"),
    ("langsmith-service-key", "lsv2_sk_short"),
    ("wandb-api-key", "wandb_v1_short"),
    ("wandb-api-key", "# wandb_v1_ is the W&B API key prefix"),
    ("cerebras-api-key", "csk-short"),
    ("cerebras-api-key", "# csk- is the Cerebras prefix"),
    ("together-ai-api-key", "tgp_v1_short"),
    ("together-ai-api-key", "# tgp_v1_ is Together.ai prefix"),
    ("devin-personal-api-key", "apk_user_short"),
    ("devin-service-api-key", "apk_short"),
    ("pinecone-api-key", "pcsk_short"),
    ("pinecone-api-key", "# pcsk_ is the Pinecone prefix"),
    ("runpod-api-key", "rpa_SHORT"),
    ("runpod-api-key", "# rpa_ is the RunPod prefix"),
    ("minimax-api-key", "sk-api-short"),
    ("minimax-api-key", "# sk-api- is the MiniMax prefix"),
    ("azure-ad-client-secret", "# Q~ is the Azure AD marker"),
    ("azure-ad-client-secret", "shortQ~value"),
]

ALL_DETECTION_CASES = (
    NEW_SECRET_DETECTION_CASES
    + ISSUE_1617_DETECTION_CASES
    + GITLEAKS_DETECTION_CASES
    + ISSUE_1678_DETECTION_CASES
    + ISSUE_1777_DETECTION_CASES
)
ALL_FALSE_POSITIVE_CASES = (
    NEW_SECRET_FALSE_POSITIVE_CASES
    + ISSUE_1617_FALSE_POSITIVE_CASES
    + GITLEAKS_FALSE_POSITIVE_CASES
    + ISSUE_1678_FALSE_POSITIVE_CASES
    + ISSUE_1777_FALSE_POSITIVE_CASES
)


class TestSecretPatterns:
    """Detection and false-positive tests for secret patterns (#1482, #1618)."""

    @pytest.mark.parametrize("rule_id,text", ALL_DETECTION_CASES)
    def test_pattern_detected(self, secret_rules, rule_id, text):
        assert secret_rules[rule_id].compiled.search(text)

    @pytest.mark.parametrize("rule_id,text", ALL_FALSE_POSITIVE_CASES)
    def test_no_false_positive(self, secret_rules, rule_id, text):
        assert not secret_rules[rule_id].compiled.search(text)
