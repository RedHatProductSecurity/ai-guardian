"""Tests for scanner execution strategies."""

import unittest
from ai_guardian.scanners.engine_builder import _build_engine_config
from ai_guardian.scanners.strategies import (
    FirstMatchStrategy,
    AnyMatchStrategy,
    ConsensusStrategy,
    SecretMatch,
    ScanResult,
    get_strategy,
    EXECUTION_STRATEGIES,
)


class TestSecretMatch(unittest.TestCase):
    """Test SecretMatch dataclass."""

    def test_create_basic_match(self):
        """Test creating a basic secret match."""
        match = SecretMatch(
            rule_id="aws-key",
            description="AWS Access Key",
            file="test.txt",
            line_number=5,
        )

        self.assertEqual(match.rule_id, "aws-key")
        self.assertEqual(match.description, "AWS Access Key")
        self.assertEqual(match.file, "test.txt")
        self.assertEqual(match.line_number, 5)
        self.assertIsNone(match.end_line)
        self.assertIsNone(match.commit)
        self.assertEqual(match.engine, "")
        self.assertEqual(match.confidence, 1.0)
        self.assertFalse(match.verified)

    def test_create_match_with_optional_fields(self):
        """Test creating a match with all optional fields."""
        match = SecretMatch(
            rule_id="github-token",
            description="GitHub Token",
            file="config.py",
            line_number=10,
            end_line=12,
            commit="abc123",
            secret="ghp_redacted",
            engine="trufflehog",
            confidence=0.9,
            verified=True,
        )

        self.assertEqual(match.end_line, 12)
        self.assertEqual(match.commit, "abc123")
        self.assertEqual(match.secret, "ghp_redacted")
        self.assertEqual(match.engine, "trufflehog")
        self.assertEqual(match.confidence, 0.9)
        self.assertTrue(match.verified)


class TestScanResult(unittest.TestCase):
    """Test ScanResult dataclass."""

    def test_create_clean_result(self):
        """Test creating a scan result with no secrets."""
        result = ScanResult(has_secrets=False, secrets=[], engine="gitleaks")

        self.assertFalse(result.has_secrets)
        self.assertEqual(len(result.secrets), 0)
        self.assertEqual(result.engine, "gitleaks")
        self.assertIsNone(result.error)
        self.assertEqual(result.scan_time_ms, 0.0)

    def test_create_result_with_secrets(self):
        """Test creating a scan result with secrets found."""
        match = SecretMatch(
            rule_id="aws-key", description="AWS Key", file="test.txt", line_number=5
        )

        result = ScanResult(
            has_secrets=True, secrets=[match], engine="trufflehog", scan_time_ms=125.5
        )

        self.assertTrue(result.has_secrets)
        self.assertEqual(len(result.secrets), 1)
        self.assertEqual(result.engine, "trufflehog")
        self.assertEqual(result.scan_time_ms, 125.5)


class TestAnyMatchStrategyDeduplication(unittest.TestCase):
    """Test AnyMatchStrategy deduplication logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.strategy = AnyMatchStrategy()

    def test_deduplicate_empty_list(self):
        """Test deduplicating empty list."""
        result = self.strategy._deduplicate([])
        self.assertEqual(len(result), 0)

    def test_deduplicate_single_secret(self):
        """Test deduplicating single secret."""
        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
            )
        ]

        result = self.strategy._deduplicate(secrets)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].engine, "gitleaks")

    def test_deduplicate_same_secret_different_engines(self):
        """Test deduplicating same secret found by multiple engines."""
        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
                confidence=1.0,
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Access Key",
                file="test.txt",
                line_number=5,
                engine="trufflehog",
                confidence=0.9,
            ),
        ]

        result = self.strategy._deduplicate(secrets)

        # Should keep only one, with combined engine names
        self.assertEqual(len(result), 1)
        self.assertIn("gitleaks", result[0].engine)
        self.assertIn("trufflehog", result[0].engine)
        # Should keep the one with higher confidence
        self.assertEqual(result[0].confidence, 1.0)

    def test_deduplicate_prefers_verified(self):
        """Test that deduplication prefers verified secrets."""
        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
                confidence=1.0,
                verified=False,
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key (verified)",
                file="test.txt",
                line_number=5,
                engine="trufflehog",
                confidence=0.8,
                verified=True,
            ),
        ]

        result = self.strategy._deduplicate(secrets)

        # Should prefer verified even if confidence is lower
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].verified)
        self.assertEqual(result[0].confidence, 0.8)

    def test_deduplicate_different_locations(self):
        """Test that secrets at different locations are not deduplicated."""
        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=10,  # Different line
                engine="gitleaks",
            ),
        ]

        result = self.strategy._deduplicate(secrets)

        # Should keep both since they're at different lines
        self.assertEqual(len(result), 2)

    def test_deduplicate_different_files(self):
        """Test that secrets in different files are not deduplicated."""
        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test1.txt",
                line_number=5,
                engine="gitleaks",
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test2.txt",  # Different file
                line_number=5,
                engine="gitleaks",
            ),
        ]

        result = self.strategy._deduplicate(secrets)

        # Should keep both since they're in different files
        self.assertEqual(len(result), 2)


class TestConsensusStrategyFindConsensus(unittest.TestCase):
    """Test ConsensusStrategy consensus finding logic."""

    def test_find_consensus_empty_list(self):
        """Test finding consensus in empty list."""
        strategy = ConsensusStrategy(threshold=2)
        result = strategy._find_consensus([])
        self.assertEqual(len(result), 0)

    def test_find_consensus_below_threshold(self):
        """Test that secrets below threshold are filtered out."""
        strategy = ConsensusStrategy(threshold=2)

        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
            )
            # Only one engine, threshold is 2
        ]

        result = strategy._find_consensus(secrets)
        self.assertEqual(len(result), 0)

    def test_find_consensus_meets_threshold(self):
        """Test that secrets meeting threshold are included."""
        strategy = ConsensusStrategy(threshold=2)

        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
                confidence=1.0,
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Access Key",
                file="test.txt",
                line_number=5,
                engine="trufflehog",
                confidence=0.9,
            ),
        ]

        result = strategy._find_consensus(secrets)

        # Should include since 2 engines agree (meets threshold of 2)
        self.assertEqual(len(result), 1)
        self.assertIn("2 engines", result[0].engine)

    def test_find_consensus_exceeds_threshold(self):
        """Test that secrets exceeding threshold are included."""
        strategy = ConsensusStrategy(threshold=2)

        secrets = [
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="trufflehog",
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="detect-secrets",
            ),
        ]

        result = strategy._find_consensus(secrets)

        # Should include since 3 engines agree (exceeds threshold of 2)
        self.assertEqual(len(result), 1)
        self.assertIn("3 engines", result[0].engine)

    def test_find_consensus_mixed_results(self):
        """Test consensus with mixed results."""
        strategy = ConsensusStrategy(threshold=2)

        secrets = [
            # Secret 1: 2 engines agree (should include)
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="gitleaks",
            ),
            SecretMatch(
                rule_id="aws-key",
                description="AWS Key",
                file="test.txt",
                line_number=5,
                engine="trufflehog",
            ),
            # Secret 2: only 1 engine (should exclude)
            SecretMatch(
                rule_id="github-token",
                description="GitHub Token",
                file="test.txt",
                line_number=10,
                engine="gitleaks",
            ),
        ]

        result = strategy._find_consensus(secrets)

        # Should only include the first secret
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].line_number, 5)


class TestFirstMatchStrategyExecute(unittest.TestCase):
    """Test FirstMatchStrategy.execute() fallthrough behavior."""

    def _make_engine(self, engine_type):
        """Create a minimal engine config for testing."""
        from unittest.mock import MagicMock

        engine = MagicMock()
        engine.type = engine_type
        engine.file_patterns = None
        engine.ignore_files = None
        return engine

    def test_tries_next_engine_when_no_secrets_found(self):
        """Bug #523: first engine finds nothing, second finds secrets."""
        engines = [self._make_engine("betterleaks"), self._make_engine("gitleaks")]

        def scanner_fn(
            engine_config, source_file, report_file, config_path=None, **kwargs
        ):
            if engine_config.type == "betterleaks":
                return ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="betterleaks",
                    scan_time_ms=10.0,
                )
            return ScanResult(
                has_secrets=True,
                secrets=[
                    SecretMatch(
                        rule_id="aws-access-token",
                        description="AWS Key",
                        file="t.txt",
                        line_number=1,
                        engine="gitleaks",
                    )
                ],
                engine="gitleaks",
                scan_time_ms=20.0,
            )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.engine, "gitleaks")
        self.assertEqual(len(result.secrets), 1)

    def test_returns_clean_when_all_engines_clean(self):
        """All engines find nothing → returns clean result."""
        engines = [self._make_engine("betterleaks"), self._make_engine("gitleaks")]

        def scanner_fn(
            engine_config, source_file, report_file, config_path=None, **kwargs
        ):
            return ScanResult(
                has_secrets=False,
                secrets=[],
                engine=engine_config.type,
                scan_time_ms=10.0,
            )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertFalse(result.has_secrets)
        self.assertEqual(len(result.secrets), 0)
        self.assertNotEqual(result.engine, "none")

    def test_stops_at_first_engine_with_secrets(self):
        """First engine finds secrets → returns immediately without running second."""
        call_log = []
        engines = [self._make_engine("gitleaks"), self._make_engine("trufflehog")]

        def scanner_fn(
            engine_config, source_file, report_file, config_path=None, **kwargs
        ):
            call_log.append(engine_config.type)
            if engine_config.type == "gitleaks":
                return ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-key",
                            description="AWS Key",
                            file="t.txt",
                            line_number=1,
                            engine="gitleaks",
                        )
                    ],
                    engine="gitleaks",
                    scan_time_ms=10.0,
                )
            return ScanResult(has_secrets=False, secrets=[], engine=engine_config.type)

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.engine, "gitleaks")
        self.assertEqual(call_log, ["gitleaks"])

    def test_skips_unavailable_then_tries_remaining(self):
        """First engine unavailable, second clean, third finds secrets."""
        engines = [
            self._make_engine("missing"),
            self._make_engine("betterleaks"),
            self._make_engine("gitleaks"),
        ]

        def scanner_fn(
            engine_config, source_file, report_file, config_path=None, **kwargs
        ):
            if engine_config.type == "missing":
                return ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="missing",
                    error="Binary not found: missing",
                )
            if engine_config.type == "betterleaks":
                return ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="betterleaks",
                    scan_time_ms=10.0,
                )
            return ScanResult(
                has_secrets=True,
                secrets=[
                    SecretMatch(
                        rule_id="aws-key",
                        description="AWS Key",
                        file="t.txt",
                        line_number=1,
                        engine="gitleaks",
                    )
                ],
                engine="gitleaks",
                scan_time_ms=20.0,
            )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.engine, "gitleaks")


class TestStrategyRegistry(unittest.TestCase):
    """Test strategy registry and factory."""

    def test_all_strategies_registered(self):
        """Test that all expected strategies are registered."""
        expected_strategies = {"first-match", "any-match", "consensus"}
        self.assertEqual(set(EXECUTION_STRATEGIES.keys()), expected_strategies)

    def test_get_first_match_strategy(self):
        """Test getting FirstMatchStrategy."""
        strategy = get_strategy("first-match")
        self.assertIsInstance(strategy, FirstMatchStrategy)

    def test_get_any_match_strategy(self):
        """Test getting AnyMatchStrategy."""
        strategy = get_strategy("any-match")
        self.assertIsInstance(strategy, AnyMatchStrategy)

    def test_get_consensus_strategy(self):
        """Test getting ConsensusStrategy with default threshold."""
        strategy = get_strategy("consensus")
        self.assertIsInstance(strategy, ConsensusStrategy)
        self.assertEqual(strategy.threshold, 2)

    def test_get_consensus_strategy_custom_threshold(self):
        """Test getting ConsensusStrategy with custom threshold."""
        strategy = get_strategy("consensus", threshold=3)
        self.assertIsInstance(strategy, ConsensusStrategy)
        self.assertEqual(strategy.threshold, 3)

    def test_get_unknown_strategy_raises_error(self):
        """Test that unknown strategy name raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            get_strategy("unknown-strategy")

        self.assertIn("Unknown strategy", str(cm.exception))
        self.assertIn("unknown-strategy", str(cm.exception))


class TestPerEngineConfigPathResolution(unittest.TestCase):
    """Test that strategies resolve config_path per-engine (Issue #519)."""

    def test_first_match_per_engine_config_path(self):
        """FirstMatch should pass per-engine resolved config_path."""
        received = []

        def tracking_fn(engine_config, source_file, report_file, config_path, **kwargs):
            received.append({"engine": engine_config.type, "config_path": config_path})
            return ScanResult(
                has_secrets=False,
                secrets=[],
                engine=engine_config.type,
            )

        gitleaks = _build_engine_config("gitleaks")
        betterleaks_null = _build_engine_config(
            {
                "type": "betterleaks",
                "pattern_server": None,
            }
        )

        strategy = FirstMatchStrategy()
        strategy.execute(
            engine_configs=[gitleaks, betterleaks_null],
            scanner_fn=tracking_fn,
            source_file="/tmp/src.txt",
            report_file_prefix="/tmp/report",
            config_path="/tmp/global.toml",
            context={"filename": "test.py"},
        )

        self.assertEqual(len(received), 2)
        self.assertIn("global.toml", received[0]["config_path"])
        self.assertIsNone(received[1]["config_path"])

    def test_any_match_per_engine_config_path(self):
        """AnyMatch should pass per-engine resolved config_path."""
        received = []

        def tracking_fn(engine_config, source_file, report_file, config_path, **kwargs):
            received.append({"engine": engine_config.type, "config_path": config_path})
            return ScanResult(
                has_secrets=False,
                secrets=[],
                engine=engine_config.type,
            )

        gitleaks = _build_engine_config("gitleaks")
        trufflehog = _build_engine_config("trufflehog")

        strategy = AnyMatchStrategy()
        strategy.execute(
            engine_configs=[gitleaks, trufflehog],
            scanner_fn=tracking_fn,
            source_file="/tmp/src.txt",
            report_file_prefix="/tmp/report",
            config_path="/tmp/global.toml",
            context={"filename": "test.py"},
        )

        self.assertEqual(len(received), 2)
        by_engine = {r["engine"]: r["config_path"] for r in received}
        self.assertIn("global.toml", by_engine["gitleaks"])
        self.assertIsNone(by_engine["trufflehog"])


class TestStrategyEngineFailures(unittest.TestCase):
    """Unsuccessful scanners remain visible in combined strategy results."""

    @staticmethod
    def _engine(engine_type):
        return _build_engine_config(engine_type)

    @staticmethod
    def _scan_result(engine_config, *, error=None, finding=False):
        secrets = (
            [
                SecretMatch(
                    rule_id="synthetic-rule",
                    description="Synthetic finding",
                    file="test.txt",
                    line_number=1,
                    engine=engine_config.type,
                )
            ]
            if finding
            else []
        )
        return ScanResult(
            has_secrets=bool(secrets),
            secrets=secrets,
            engine=engine_config.type,
            error=error,
        )

    def test_first_match_retains_cloud_error_after_local_clean_scan(self):
        engines = [self._engine("gitguardian"), self._engine("gitleaks")]

        def scanner(engine_config, *_args, **_kwargs):
            if engine_config.type == "gitguardian":
                return self._scan_result(
                    engine_config, error="GitGuardian cloud scan quota exhausted"
                )
            return self._scan_result(engine_config)

        result = FirstMatchStrategy().execute(engines, scanner, "input", "report")

        self.assertFalse(result.has_secrets)
        self.assertIn(
            "gitguardian: GitGuardian cloud scan quota exhausted", result.error
        )
        self.assertEqual(result.engine, "gitleaks")

    def test_first_match_retains_prior_error_with_local_finding(self):
        engines = [self._engine("gitguardian"), self._engine("gitleaks")]

        def scanner(engine_config, *_args, **_kwargs):
            if engine_config.type == "gitguardian":
                return self._scan_result(
                    engine_config, error="GitGuardian cloud service unavailable"
                )
            return self._scan_result(engine_config, finding=True)

        result = FirstMatchStrategy().execute(engines, scanner, "input", "report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(len(result.secrets), 1)
        self.assertIn(
            "gitguardian: GitGuardian cloud service unavailable", result.error
        )

    def test_any_match_retains_each_engine_failure(self):
        engines = [self._engine("gitguardian"), self._engine("gitleaks")]

        def scanner(engine_config, *_args, **_kwargs):
            if engine_config.type == "gitguardian":
                return self._scan_result(
                    engine_config, error="GitGuardian cloud scan authentication failed"
                )
            return self._scan_result(engine_config)

        result = AnyMatchStrategy().execute(engines, scanner, "input", "report")

        self.assertFalse(result.has_secrets)
        self.assertIn(
            "gitguardian: GitGuardian cloud scan authentication failed", result.error
        )

    def test_consensus_error_does_not_lower_threshold(self):
        engines = [self._engine("gitguardian"), self._engine("gitleaks")]

        def scanner(engine_config, *_args, **_kwargs):
            if engine_config.type == "gitguardian":
                return self._scan_result(
                    engine_config, error="GitGuardian cloud service unavailable"
                )
            return self._scan_result(engine_config, finding=True)

        result = ConsensusStrategy(threshold=2).execute(
            engines, scanner, "input", "report"
        )

        self.assertFalse(result.has_secrets)
        self.assertEqual(result.secrets, [])
        self.assertIn(
            "gitguardian: GitGuardian cloud service unavailable", result.error
        )


if __name__ == "__main__":
    unittest.main()
