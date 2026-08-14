"""Tests for scan_analyzer module."""

import pytest

from ai_guardian.scan_analyzer import (
    DirectoryAnalysis,
    FindingCluster,
    ScanAnalysisResult,
    build_recommendations,
    cluster_findings,
    analyze_directories,
    fingerprint_finding,
    NEVER_SUPPRESS,
)


def _make_finding(rule_id, file_path, **details_kwargs):
    return {
        "rule_id": rule_id,
        "level": "error",
        "message": f"Test finding: {rule_id}",
        "file_path": file_path,
        "line_number": 1,
        "snippet": "test",
        "details": details_kwargs,
    }


class TestFingerprintFinding:
    def test_offensive_language_finding(self):
        f = _make_finding("profanity-fword", "a.py", category="profanity")
        assert fingerprint_finding(f) == ("profanity-fword", "profanity")

    def test_offensive_language_slur(self):
        f = _make_finding("slur-racial-1", "a.py", category="slurs")
        assert fingerprint_finding(f) == ("slur-racial-1", "slurs")

    def test_offensive_language_inclusive(self):
        f = _make_finding("inclusive-ableist-1", "a.py", category="inclusive")
        assert fingerprint_finding(f) == ("inclusive-ableist-1", "inclusive")

    def test_secret_finding(self):
        f = _make_finding("SECRET-001", "a.py", secret_type="generic-api-key")
        assert fingerprint_finding(f) == ("SECRET-001", "generic-api-key")

    def test_pii_finding(self):
        f = _make_finding("PII-001", "a.py", pii_type="email")
        assert fingerprint_finding(f) == ("PII-001", "email")

    def test_prompt_injection_finding(self):
        f = _make_finding(
            "PROMPT-INJECTION-001",
            "a.py",
            description="System prompt override detected",
        )
        assert fingerprint_finding(f) == (
            "PROMPT-INJECTION-001",
            "System prompt override detected",
        )

    def test_prompt_injection_strips_line_info(self):
        f = _make_finding(
            "PROMPT-INJECTION-001",
            "a.py",
            description="Jailbreak detected at line 42 in foo.py",
        )
        rule_id, sub = fingerprint_finding(f)
        assert "line 42" not in sub
        assert "in foo.py" not in sub

    def test_supply_chain_finding(self):
        f = _make_finding("SUPPLY-CHAIN-001", "a.json", category="malicious_url")
        assert fingerprint_finding(f) == ("SUPPLY-CHAIN-001", "malicious_url")

    def test_config_finding(self):
        f = _make_finding("CONFIG-001", "a.sh", pattern="cat ~/.aws")
        assert fingerprint_finding(f) == ("CONFIG-001", "cat ~/.aws")

    def test_exfil_finding(self):
        f = _make_finding("EXFIL-DETECTION-001", "a.sh", category="base64_encoding")
        assert fingerprint_finding(f) == ("EXFIL-DETECTION-001", "base64_encoding")

    def test_bandit_finding(self):
        f = _make_finding("B101", "a.py")
        assert fingerprint_finding(f) == ("B101", "")

    def test_ssrf_finding(self):
        f = _make_finding(
            "SSRF-001", "a.py", url="http://169.254.169.254", reason="metadata endpoint"
        )
        assert fingerprint_finding(f) == ("SSRF-001", "metadata endpoint")

    def test_ssrf_localhost_finding(self):
        f = _make_finding(
            "SSRF-001",
            "a.py",
            url="https://localhost:5173",
            reason="blocked domain 'localhost'",
        )
        assert fingerprint_finding(f) == ("SSRF-001", "blocked domain 'localhost'")

    def test_missing_details(self):
        f = {"rule_id": "SECRET-001", "file_path": "x.py", "details": {}}
        assert fingerprint_finding(f) == ("SECRET-001", "unknown")


class TestClusterFindings:
    def test_single_cluster(self):
        findings = [
            _make_finding("SECRET-001", f"file{i}.py", secret_type="generic-api-key")
            for i in range(5)
        ]
        clusters = cluster_findings(findings)
        assert len(clusters) == 1
        assert clusters[0].rule_id == "SECRET-001"
        assert clusters[0].sub_type == "generic-api-key"
        assert clusters[0].file_count == 5
        assert clusters[0].total_count == 5

    def test_multiple_clusters(self):
        findings = [
            _make_finding("SECRET-001", "a.py", secret_type="generic-api-key"),
            _make_finding("PII-001", "b.py", pii_type="email"),
            _make_finding("SECRET-001", "c.py", secret_type="generic-api-key"),
        ]
        clusters = cluster_findings(findings)
        assert len(clusters) == 2
        secret_cluster = next(c for c in clusters if c.rule_id == "SECRET-001")
        assert secret_cluster.file_count == 2

    def test_same_file_counted_once(self):
        findings = [
            _make_finding("SECRET-001", "a.py", secret_type="generic-api-key"),
            _make_finding("SECRET-001", "a.py", secret_type="generic-api-key"),
        ]
        clusters = cluster_findings(findings)
        assert clusters[0].file_count == 1
        assert clusters[0].total_count == 2

    def test_sample_files_capped(self):
        findings = [
            _make_finding("SECRET-001", f"file{i}.py", secret_type="key")
            for i in range(20)
        ]
        clusters = cluster_findings(findings)
        assert len(clusters[0].sample_files) == 5

    def test_empty_findings(self):
        assert cluster_findings([]) == []


class TestAnalyzeDirectories:
    def test_all_high_frequency(self):
        findings = [
            _make_finding("SECRET-001", "tests/test_a.py", secret_type="key"),
            _make_finding("SECRET-001", "tests/test_b.py", secret_type="key"),
        ]
        high_fps = {("SECRET-001", "key")}
        dirs = analyze_directories(findings, high_fps)
        tests_dir = next(d for d in dirs if d.directory == "tests")
        assert tests_dir.all_high_frequency
        assert tests_dir.total_findings == 2

    def test_partial_high_frequency(self):
        findings = [
            _make_finding("SECRET-001", "src/main.py", secret_type="key"),
            _make_finding("SSRF-001", "src/util.py", url="http://evil.com"),
        ]
        high_fps = {("SECRET-001", "key")}
        dirs = analyze_directories(findings, high_fps)
        src_dir = next(d for d in dirs if d.directory == "src")
        assert not src_dir.all_high_frequency
        assert src_dir.total_findings == 2
        assert src_dir.high_frequency_findings == 1

    def test_root_files_ignored(self):
        findings = [
            _make_finding("SECRET-001", "config.py", secret_type="key"),
        ]
        dirs = analyze_directories(findings, set())
        assert len(dirs) == 0

    def test_empty_findings(self):
        assert analyze_directories([], set()) == []


class TestBuildRecommendations:
    def test_threshold_filters(self):
        findings = [
            _make_finding("SECRET-001", f"f{i}.py", secret_type="generic-api-key")
            for i in range(15)
        ]
        result = build_recommendations(findings, threshold=10)
        assert len(result.high_frequency_clusters) == 1
        assert result.suppressed_count == 15

    def test_below_threshold_not_suppressed(self):
        findings = [
            _make_finding("SECRET-001", f"f{i}.py", secret_type="generic-api-key")
            for i in range(5)
        ]
        result = build_recommendations(findings, threshold=10)
        assert len(result.high_frequency_clusters) == 0
        assert result.suppressed_count == 0

    def test_never_suppress_rules(self):
        findings = [
            _make_finding("SSRF-001", f"f{i}.py", url="http://169.254.169.254")
            for i in range(20)
        ]
        result = build_recommendations(findings, threshold=5)
        assert len(result.high_frequency_clusters) == 0

    def test_never_suppress_canary(self):
        findings = [_make_finding("canary_detected", f"f{i}.py") for i in range(20)]
        result = build_recommendations(findings, threshold=5)
        assert len(result.high_frequency_clusters) == 0

    def test_config_generation_secrets(self):
        findings = [
            _make_finding("SECRET-001", f"f{i}.py", secret_type="generic-api-key")
            for i in range(12)
        ]
        result = build_recommendations(findings, threshold=10)
        config = result.recommended_config
        assert "secret_scanning" in config
        assert "generic\\-api\\-key" in config["secret_scanning"]["allowlist_patterns"]

    def test_config_generation_pi(self):
        findings = [
            _make_finding(
                "PROMPT-INJECTION-001",
                f"f{i}.py",
                description="System prompt pattern",
            )
            for i in range(10)
        ]
        result = build_recommendations(findings, threshold=10)
        config = result.recommended_config
        assert "prompt_injection" in config
        patterns = config["prompt_injection"]["allowlist_patterns"]
        assert len(patterns) == 1

    def test_directory_ignore_recommendation(self):
        findings = [
            _make_finding("SECRET-001", f"tests/t{i}.py", secret_type="key")
            for i in range(12)
        ]
        result = build_recommendations(findings, threshold=10)
        assert any(d.directory == "tests" for d in result.directories_to_ignore)
        assert "secret_scanning" in result.recommended_ignore_paths
        assert "tests/**" in result.recommended_ignore_paths["secret_scanning"]

    def test_mixed_dir_not_ignored(self):
        findings = [
            _make_finding("SECRET-001", f"src/f{i}.py", secret_type="key")
            for i in range(12)
        ] + [
            _make_finding("SSRF-001", "src/util.py", url="http://evil"),
        ]
        result = build_recommendations(findings, threshold=10)
        ignored_dirs = [d.directory for d in result.directories_to_ignore]
        assert "src" not in ignored_dirs

    def test_empty_findings(self):
        result = build_recommendations([], threshold=10)
        assert result.total_findings == 0
        assert result.suppressed_count == 0
        assert result.high_frequency_clusters == []

    def test_config_generation_supply_chain(self):
        findings = [
            _make_finding(
                "SUPPLY-CHAIN-001",
                f"tools/configs/agent{i}.json",
                category="agent_config",
            )
            for i in range(12)
        ]
        result = build_recommendations(findings, threshold=10)
        config = result.recommended_config
        assert "supply_chain" in config
        assert "allowlist_paths" in config["supply_chain"]
        assert "tools/configs/**" in config["supply_chain"]["allowlist_paths"]

    def test_config_generation_config_file(self):
        findings = [
            _make_finding("CONFIG-001", f"scripts/helper{i}.sh", pattern="cat ~/.ssh")
            for i in range(11)
        ]
        result = build_recommendations(findings, threshold=10)
        config = result.recommended_config
        assert "config_file_scanning" in config
        assert "ignore_files" in config["config_file_scanning"]
        assert "scripts/**" in config["config_file_scanning"]["ignore_files"]

    def test_root_level_files_skipped_in_path_generation(self):
        findings = [
            _make_finding(
                "SUPPLY-CHAIN-001", f"root_file{i}.json", category="agent_config"
            )
            for i in range(12)
        ]
        result = build_recommendations(findings, threshold=10)
        config = result.recommended_config
        if "supply_chain" in config:
            paths = config["supply_chain"].get("allowlist_paths", [])
            assert "**" not in paths

    def test_config_generation_exfil(self):
        findings = [
            _make_finding(
                "EXFIL-DETECTION-001", f"tests/t{i}.sh", category="base64_encoding"
            )
            for i in range(10)
        ]
        result = build_recommendations(findings, threshold=10)
        config = result.recommended_config
        assert "exfil_detection" in config
        assert "base64_encoding" in config["exfil_detection"]["allowlist_patterns"]

    def test_offensive_language_excluded_until_scanner_supports_allowlist(self):
        findings = [
            _make_finding("profanity-fword", f"docs/d{i}.md", category="profanity")
            for i in range(11)
        ]
        result = build_recommendations(findings, threshold=10)
        assert len(result.high_frequency_clusters) == 0
        assert "scan_offensive" not in result.recommended_config

    def test_config_generation_code_scanning(self):
        findings = [_make_finding("B108", f"src/mod{i}.py") for i in range(10)]
        result = build_recommendations(findings, threshold=10)
        config = result.recommended_config
        assert "code_scanning" in config
        assert {"test_id": "B108"} in config["code_scanning"]["allowlist"]

    def test_pii_still_excluded(self):
        findings = [
            _make_finding("PII-001", f"data/f{i}.csv", pii_type="email")
            for i in range(20)
        ]
        result = build_recommendations(findings, threshold=10)
        assert len(result.high_frequency_clusters) == 0
        assert "scan_pii" not in result.recommended_config

    def test_multiple_scanner_types(self):
        findings = [
            _make_finding("SECRET-001", f"f{i}.py", secret_type="key")
            for i in range(11)
        ] + [
            _make_finding(
                "PROMPT-INJECTION-001",
                f"g{i}.py",
                description="Override pattern",
            )
            for i in range(11)
        ]
        result = build_recommendations(findings, threshold=10)
        assert len(result.high_frequency_clusters) == 2
        assert "secret_scanning" in result.recommended_config
        assert "prompt_injection" in result.recommended_config
