"""Integration tests for multi-engine execution strategies.

Tests the full strategy execution flow with mocked scanner functions,
verifying that strategies correctly combine results from multiple engines.
"""

import unittest
from unittest.mock import patch

from ai_guardian.scanners.strategies import (
    FirstMatchStrategy,
    AnyMatchStrategy,
    ConsensusStrategy,
    SecretMatch,
    ScanResult,
    get_strategy,
)
from ai_guardian.scanners.engine_builder import ENGINE_PRESETS


def _make_engine(engine_type, file_patterns=None, ignore_files=None):
    """Create a test EngineConfig."""
    import copy

    config = copy.deepcopy(ENGINE_PRESETS.get(engine_type, ENGINE_PRESETS["gitleaks"]))
    config.type = engine_type
    config.file_patterns = file_patterns
    config.ignore_files = ignore_files
    return config


def _make_scanner_fn(results_by_engine):
    """Create a mock scanner function that returns predefined results."""

    def scanner_fn(engine_config, source_file, report_file, config_path=None, **kwargs):
        engine_type = engine_config.type
        if engine_type in results_by_engine:
            return results_by_engine[engine_type]
        return ScanResult(has_secrets=False, secrets=[], engine=engine_type)

    return scanner_fn


class TestFirstMatchStrategyExecute(unittest.TestCase):
    """Test FirstMatchStrategy.execute() with scanner function."""

    def test_returns_first_engine_result(self):
        engines = [_make_engine("gitleaks"), _make_engine("trufflehog")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
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
                    scan_time_ms=50.0,
                ),
            }
        )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.engine, "gitleaks")

    def test_falls_back_on_binary_not_found(self):
        engines = [_make_engine("gitleaks"), _make_engine("trufflehog")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="gitleaks",
                    error="Binary not found: gitleaks",
                ),
                "trufflehog": ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="trufflehog",
                    scan_time_ms=30.0,
                ),
            }
        )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertFalse(result.has_secrets)
        self.assertEqual(result.engine, "trufflehog")

    def test_reports_error_when_all_engines_are_unavailable(self):
        engines = [_make_engine("gitleaks")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="gitleaks",
                    error="Binary not found: gitleaks",
                ),
            }
        )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertFalse(result.has_secrets)
        self.assertEqual(result.engine, "first-match")
        self.assertIn("gitleaks: Binary not found: gitleaks", result.error)


class TestFirstMatchFallthroughBehavior(unittest.TestCase):
    """Test FirstMatchStrategy falls through to next engine when no secrets found (Issue #523)."""

    def test_first_engine_clean_second_finds_secrets(self):
        """Bug #523: betterleaks finds nothing, gitleaks finds AWS key."""
        engines = [_make_engine("betterleaks"), _make_engine("gitleaks")]
        scanner_fn = _make_scanner_fn(
            {
                "betterleaks": ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="betterleaks",
                    scan_time_ms=15.0,
                ),
                "gitleaks": ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-access-token",
                            description="AWS Access Key",
                            file="t.txt",
                            line_number=1,
                            engine="gitleaks",
                        )
                    ],
                    engine="gitleaks",
                    scan_time_ms=25.0,
                ),
            }
        )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.engine, "gitleaks")
        self.assertEqual(result.secrets[0].rule_id, "aws-access-token")

    def test_all_engines_clean_returns_clean(self):
        """All engines find nothing → returns clean result (not error)."""
        engines = [_make_engine("betterleaks"), _make_engine("gitleaks")]
        scanner_fn = _make_scanner_fn(
            {
                "betterleaks": ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="betterleaks",
                    scan_time_ms=10.0,
                ),
                "gitleaks": ScanResult(
                    has_secrets=False, secrets=[], engine="gitleaks", scan_time_ms=10.0
                ),
            }
        )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertFalse(result.has_secrets)
        self.assertEqual(len(result.secrets), 0)
        self.assertIsNone(result.error)

    def test_unavailable_then_clean_then_finds(self):
        """First unavailable, second clean, third finds secrets."""
        engines = [
            _make_engine("missing"),
            _make_engine("betterleaks"),
            _make_engine("gitleaks"),
        ]
        scanner_fn = _make_scanner_fn(
            {
                "missing": ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="missing",
                    error="Binary not found: missing",
                ),
                "betterleaks": ScanResult(
                    has_secrets=False,
                    secrets=[],
                    engine="betterleaks",
                    scan_time_ms=10.0,
                ),
                "gitleaks": ScanResult(
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
                ),
            }
        )

        strategy = FirstMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(result.engine, "gitleaks")

    def test_first_finds_secrets_does_not_run_second(self):
        """First engine finds secrets → stops immediately."""
        call_log = []

        def tracking_scanner_fn(
            engine_config, source_file, report_file, config_path=None, **kwargs
        ):
            call_log.append(engine_config.type)
            if engine_config.type == "betterleaks":
                return ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="secret",
                            description="Secret",
                            file="t.txt",
                            line_number=1,
                            engine="betterleaks",
                        )
                    ],
                    engine="betterleaks",
                )
            return ScanResult(has_secrets=False, secrets=[], engine=engine_config.type)

        engines = [_make_engine("betterleaks"), _make_engine("gitleaks")]
        strategy = FirstMatchStrategy()
        result = strategy.execute(
            engines, tracking_scanner_fn, "/tmp/src", "/tmp/report"
        )

        self.assertTrue(result.has_secrets)
        self.assertEqual(call_log, ["betterleaks"])


class TestAnyMatchStrategyExecute(unittest.TestCase):
    """Test AnyMatchStrategy.execute() with scanner function."""

    def test_blocks_if_any_engine_finds_secrets(self):
        engines = [_make_engine("gitleaks"), _make_engine("trufflehog")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-key",
                            description="AWS Key",
                            file="t.txt",
                            line_number=5,
                            engine="gitleaks",
                        )
                    ],
                    engine="gitleaks",
                ),
                "trufflehog": ScanResult(
                    has_secrets=False, secrets=[], engine="trufflehog"
                ),
            }
        )

        strategy = AnyMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(len(result.secrets), 1)
        self.assertIn("any-match", result.engine)

    def test_allows_if_no_engine_finds_secrets(self):
        engines = [_make_engine("gitleaks"), _make_engine("trufflehog")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
                    has_secrets=False, secrets=[], engine="gitleaks"
                ),
                "trufflehog": ScanResult(
                    has_secrets=False, secrets=[], engine="trufflehog"
                ),
            }
        )

        strategy = AnyMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertFalse(result.has_secrets)
        self.assertEqual(len(result.secrets), 0)

    def test_deduplicates_across_engines(self):
        engines = [_make_engine("gitleaks"), _make_engine("trufflehog")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-key",
                            description="AWS Key",
                            file="t.txt",
                            line_number=5,
                            engine="gitleaks",
                        )
                    ],
                    engine="gitleaks",
                ),
                "trufflehog": ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-key",
                            description="AWS Key Detected",
                            file="t.txt",
                            line_number=5,
                            engine="trufflehog",
                        )
                    ],
                    engine="trufflehog",
                ),
            }
        )

        strategy = AnyMatchStrategy()
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertEqual(len(result.secrets), 1)
        self.assertIn("gitleaks", result.secrets[0].engine)
        self.assertIn("trufflehog", result.secrets[0].engine)


class TestConsensusStrategyExecute(unittest.TestCase):
    """Test ConsensusStrategy.execute() with scanner function."""

    def test_blocks_when_threshold_met(self):
        engines = [_make_engine("gitleaks"), _make_engine("trufflehog")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-key",
                            description="AWS Key",
                            file="t.txt",
                            line_number=5,
                            engine="gitleaks",
                        )
                    ],
                    engine="gitleaks",
                ),
                "trufflehog": ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-key",
                            description="AWS Key",
                            file="t.txt",
                            line_number=5,
                            engine="trufflehog",
                        )
                    ],
                    engine="trufflehog",
                ),
            }
        )

        strategy = ConsensusStrategy(threshold=2)
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertTrue(result.has_secrets)
        self.assertIn("consensus", result.engine)
        self.assertIn("2 engines", result.secrets[0].engine)

    def test_allows_when_below_threshold(self):
        engines = [_make_engine("gitleaks"), _make_engine("trufflehog")]
        scanner_fn = _make_scanner_fn(
            {
                "gitleaks": ScanResult(
                    has_secrets=True,
                    secrets=[
                        SecretMatch(
                            rule_id="aws-key",
                            description="AWS Key",
                            file="t.txt",
                            line_number=5,
                            engine="gitleaks",
                        )
                    ],
                    engine="gitleaks",
                ),
                "trufflehog": ScanResult(
                    has_secrets=False, secrets=[], engine="trufflehog"
                ),
            }
        )

        strategy = ConsensusStrategy(threshold=2)
        result = strategy.execute(engines, scanner_fn, "/tmp/src", "/tmp/report")

        self.assertFalse(result.has_secrets)
        self.assertEqual(len(result.secrets), 0)


class TestFileTypeRouting(unittest.TestCase):
    """Test file type routing in strategies."""

    def test_routes_env_files_to_specialized_engine(self):
        gitleaks = _make_engine("gitleaks", file_patterns=["*.py", "*.js"])
        trufflehog = _make_engine("trufflehog", file_patterns=["*.env*", "*.yaml"])

        call_log = []

        def scanner_fn(config, src, report, path=None, **kwargs):
            call_log.append(config.type)
            return ScanResult(has_secrets=False, secrets=[], engine=config.type)

        strategy = AnyMatchStrategy()
        result = strategy.execute(
            [gitleaks, trufflehog],
            scanner_fn,
            "/tmp/src",
            "/tmp/report",
            context={"filename": "config.env"},
        )

        self.assertIn("trufflehog", call_log)
        self.assertNotIn("gitleaks", call_log)

    def test_engines_without_patterns_handle_all_files(self):
        gitleaks = _make_engine("gitleaks")  # No file_patterns = handles all
        trufflehog = _make_engine("trufflehog", file_patterns=["*.env*"])

        call_log = []

        def scanner_fn(config, src, report, path=None, **kwargs):
            call_log.append(config.type)
            return ScanResult(has_secrets=False, secrets=[], engine=config.type)

        strategy = AnyMatchStrategy()
        result = strategy.execute(
            [gitleaks, trufflehog],
            scanner_fn,
            "/tmp/src",
            "/tmp/report",
            context={"filename": "app.py"},
        )

        self.assertIn("gitleaks", call_log)
        self.assertNotIn("trufflehog", call_log)

    def test_fallback_to_all_if_none_match(self):
        gitleaks = _make_engine("gitleaks", file_patterns=["*.py"])
        trufflehog = _make_engine("trufflehog", file_patterns=["*.env"])

        call_log = []

        def scanner_fn(config, src, report, path=None, **kwargs):
            call_log.append(config.type)
            return ScanResult(has_secrets=False, secrets=[], engine=config.type)

        strategy = AnyMatchStrategy()
        result = strategy.execute(
            [gitleaks, trufflehog],
            scanner_fn,
            "/tmp/src",
            "/tmp/report",
            context={"filename": "data.csv"},
        )

        self.assertIn("gitleaks", call_log)
        self.assertIn("trufflehog", call_log)


class TestStrategyFromConfig(unittest.TestCase):
    """Test creating strategies from configuration values."""

    def test_default_strategy_is_first_match(self):
        strategy = get_strategy("first-match")
        self.assertIsInstance(strategy, FirstMatchStrategy)

    def test_any_match_strategy(self):
        strategy = get_strategy("any-match")
        self.assertIsInstance(strategy, AnyMatchStrategy)

    def test_consensus_with_threshold(self):
        strategy = get_strategy("consensus", threshold=3)
        self.assertIsInstance(strategy, ConsensusStrategy)
        self.assertEqual(strategy.threshold, 3)


class TestSelectAllEngines(unittest.TestCase):
    """Test select_all_engines() function."""

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_returns_all_available(self, mock_which):
        from ai_guardian.scanners.engine_builder import select_all_engines

        mock_which.side_effect = lambda b: b in ("gitleaks", "trufflehog")

        engines = select_all_engines(["gitleaks", "trufflehog", "betterleaks"])
        types = [e.type for e in engines]

        self.assertEqual(len(engines), 2)
        self.assertIn("gitleaks", types)
        self.assertIn("trufflehog", types)
        self.assertNotIn("betterleaks", types)

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_raises_when_none_available(self, mock_which):
        from ai_guardian.scanners.engine_builder import select_all_engines

        mock_which.return_value = None

        with self.assertRaises(RuntimeError):
            select_all_engines(["gitleaks", "trufflehog"])

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_per_engine_config_preserved(self, mock_which):
        from ai_guardian.scanners.engine_builder import select_all_engines

        mock_which.return_value = "/usr/bin/trufflehog"

        engines = select_all_engines(
            [
                {
                    "type": "trufflehog",
                    "binary": "trufflehog",
                    "ignore_files": ["**/test/**"],
                    "file_patterns": ["*.env*"],
                    "pattern_server": {"url": "https://example.com"},
                }
            ]
        )

        self.assertEqual(len(engines), 1)
        self.assertEqual(engines[0].ignore_files, ["**/test/**"])
        self.assertEqual(engines[0].file_patterns, ["*.env*"])
        self.assertEqual(engines[0].pattern_server, {"url": "https://example.com"})


if __name__ == "__main__":
    unittest.main()
