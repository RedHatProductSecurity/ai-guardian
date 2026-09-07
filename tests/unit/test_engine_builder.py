#!/usr/bin/env python3
"""
Tests for scanner engine builder module.

Tests engine selection, command building, and configuration handling.
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_guardian.scanners.engine_builder import (
    EngineConfig,
    ENGINE_PRESETS,
    PATTERN_SERVER_UNSET,
    select_engine,
    build_scanner_command,
    resolve_engine_config_path,
    _build_engine_config,
)


class TestEnginePresets(unittest.TestCase):
    """Tests for built-in engine presets."""

    def test_gitleaks_preset_exists(self):
        """Test that gitleaks preset is defined."""
        self.assertIn("gitleaks", ENGINE_PRESETS)
        config = ENGINE_PRESETS["gitleaks"]
        self.assertEqual(config.type, "gitleaks")
        self.assertEqual(config.binary, "gitleaks")
        self.assertEqual(config.output_parser, "gitleaks")
        self.assertEqual(config.secrets_found_exit_code, 42)

    def test_betterleaks_preset_exists(self):
        """Test that betterleaks preset is defined."""
        self.assertIn("betterleaks", ENGINE_PRESETS)
        config = ENGINE_PRESETS["betterleaks"]
        self.assertEqual(config.type, "betterleaks")
        self.assertEqual(config.binary, "betterleaks")
        self.assertEqual(config.output_parser, "gitleaks")  # Same as gitleaks
        self.assertEqual(config.secrets_found_exit_code, 42)

    def test_leaktk_preset_exists(self):
        """Test that leaktk preset is defined."""
        self.assertIn("leaktk", ENGINE_PRESETS)
        config = ENGINE_PRESETS["leaktk"]
        self.assertEqual(config.type, "leaktk")
        self.assertEqual(config.binary, "leaktk")
        self.assertEqual(config.output_parser, "leaktk")  # Different parser
        self.assertEqual(config.secrets_found_exit_code, 1)

    def test_all_presets_have_required_fields(self):
        """Test that all presets have required fields."""
        for name, config in ENGINE_PRESETS.items():
            self.assertIsInstance(config, EngineConfig)
            self.assertTrue(config.type, f"{name} missing type")
            self.assertTrue(config.binary, f"{name} missing binary")
            self.assertTrue(config.command_template, f"{name} missing command_template")
            self.assertTrue(config.output_parser, f"{name} missing output_parser")


class TestCapabilityFlags(unittest.TestCase):
    """Tests for supports_listen_mode and version_hint capability flags (#1644)."""

    def test_leaktk_supports_listen_mode(self):
        config = ENGINE_PRESETS["leaktk"]
        self.assertTrue(config.supports_listen_mode)

    def test_leaktk_has_version_hint(self):
        config = ENGINE_PRESETS["leaktk"]
        self.assertIsNotNone(config.version_hint)
        self.assertIn("leaktk", config.version_hint)

    def test_other_presets_no_listen_mode(self):
        for name, config in ENGINE_PRESETS.items():
            if name == "leaktk":
                continue
            self.assertFalse(
                config.supports_listen_mode,
                f"Preset '{name}' should not support listen mode",
            )

    def test_other_presets_no_version_hint(self):
        for name, config in ENGINE_PRESETS.items():
            if name == "leaktk":
                continue
            self.assertIsNone(
                config.version_hint,
                f"Preset '{name}' should not have version_hint",
            )

    def test_default_values(self):
        config = EngineConfig(
            type="test",
            binary="test",
            command_template=[],
            output_parser="gitleaks",
        )
        self.assertFalse(config.supports_listen_mode)
        self.assertIsNone(config.version_hint)

    def test_dict_override_preserves_flags(self):
        config = _build_engine_config({"type": "leaktk", "extra_flags": ["--verbose"]})
        self.assertTrue(config.supports_listen_mode)
        self.assertIsNotNone(config.version_hint)


class TestSelectEngine(unittest.TestCase):
    """Tests for engine selection logic."""

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_select_first_available_engine(self, mock_which):
        """Test that first available engine is selected."""

        # Mock: betterleaks not found, gitleaks found
        def which_side_effect(binary):
            return "/usr/bin/gitleaks" if binary == "gitleaks" else None

        mock_which.side_effect = which_side_effect

        config = select_engine(["betterleaks", "gitleaks"])
        self.assertEqual(config.type, "gitleaks")

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_select_betterleaks_when_available(self, mock_which):
        """Test that betterleaks is selected when available."""

        # Mock: betterleaks found
        def which_side_effect(binary):
            return f"/usr/bin/{binary}" if binary == "betterleaks" else None

        mock_which.side_effect = which_side_effect

        config = select_engine(["betterleaks", "gitleaks"])
        self.assertEqual(config.type, "betterleaks")

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_select_engine_no_scanner_found(self, mock_which):
        """Test that RuntimeError is raised when no scanner is found."""
        # Mock: no scanner found
        mock_which.return_value = None

        with self.assertRaises(RuntimeError) as cm:
            select_engine(["betterleaks", "gitleaks", "leaktk"])

        self.assertIn("No secret scanner found", str(cm.exception))
        self.assertIn("Gitleaks", str(cm.exception))
        self.assertIn("BetterLeaks", str(cm.exception))

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_select_engine_with_custom_binary_path(self, mock_which):
        """Test engine selection with custom binary path override."""

        # Mock: custom path exists
        def which_side_effect(binary):
            return binary if binary == "/custom/path/betterleaks" else None

        mock_which.side_effect = which_side_effect

        engine_spec = {"type": "betterleaks", "binary": "/custom/path/betterleaks"}
        config = select_engine([engine_spec])
        self.assertEqual(config.type, "betterleaks")
        self.assertEqual(config.binary, "/custom/path/betterleaks")

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_select_engine_with_extra_flags(self, mock_which):
        """Test engine selection with extra flags override."""
        mock_which.return_value = "/usr/bin/betterleaks"

        engine_spec = {
            "type": "betterleaks",
            "extra_flags": ["--regex-engine=re2", "--verbose"],
        }
        config = select_engine([engine_spec])
        self.assertEqual(config.extra_flags, ["--regex-engine=re2", "--verbose"])

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_select_custom_engine(self, mock_which):
        """Test selection of fully custom engine."""
        mock_which.return_value = "/usr/bin/my-scanner"

        engine_spec = {
            "type": "custom",
            "binary": "my-scanner",
            "command_template": ["{binary}", "scan", "{source_file}"],
            "success_exit_code": 0,
            "secrets_found_exit_code": 2,
            "output_format": "gitleaks-compatible",
        }
        config = select_engine([engine_spec])
        self.assertEqual(config.type, "custom")
        self.assertEqual(config.binary, "my-scanner")
        self.assertEqual(config.secrets_found_exit_code, 2)
        self.assertEqual(config.output_parser, "gitleaks-compatible")

    @patch("ai_guardian.scanners.engine_builder.shutil.which")
    def test_select_engine_unknown_preset(self, mock_which):
        """Test that unknown presets are skipped."""
        mock_which.return_value = "/usr/bin/gitleaks"

        config = select_engine(["nonexistent", "gitleaks"])
        self.assertEqual(config.type, "gitleaks")


class TestBuildScannerCommand(unittest.TestCase):
    """Tests for scanner command building."""

    def test_build_gitleaks_command_without_config(self):
        """Test building gitleaks command without config file."""
        config = ENGINE_PRESETS["gitleaks"]
        cmd = build_scanner_command(
            engine_config=config,
            source_file="/tmp/test.txt",
            report_file="/tmp/report.json",
        )

        self.assertIn("gitleaks", cmd)
        self.assertIn("detect", cmd)
        self.assertIn("/tmp/test.txt", cmd)
        self.assertIn("/tmp/report.json", cmd)
        # Config flag should not be present
        self.assertNotIn("--config", cmd)

    def test_build_gitleaks_command_with_config(self):
        """Test building gitleaks command with config file."""
        config = ENGINE_PRESETS["gitleaks"]
        cmd = build_scanner_command(
            engine_config=config,
            source_file="/tmp/test.txt",
            report_file="/tmp/report.json",
            config_path="/home/user/.gitleaks.toml",
        )

        self.assertIn("--config", cmd)
        self.assertIn("/home/user/.gitleaks.toml", cmd)

    def test_build_betterleaks_command(self):
        """Test building betterleaks command."""
        config = ENGINE_PRESETS["betterleaks"]
        cmd = build_scanner_command(
            engine_config=config,
            source_file="/tmp/test.txt",
            report_file="/tmp/report.json",
        )

        self.assertIn("betterleaks", cmd)
        self.assertIn("dir", cmd)
        self.assertIn("--validation=false", cmd)
        self.assertIn("/tmp/test.txt", cmd)

    def test_build_leaktk_command(self):
        """Test building leaktk command."""
        config = ENGINE_PRESETS["leaktk"]
        cmd = build_scanner_command(
            engine_config=config,
            source_file="/tmp/test.txt",
            report_file="/tmp/report.json",
        )

        self.assertIn("leaktk", cmd)
        self.assertIn("scan", cmd)
        self.assertIn("--kind", cmd)
        self.assertIn("Files", cmd)
        self.assertIn("/tmp/test.txt", cmd)

    def test_build_command_with_extra_flags(self):
        """Test building command with extra flags."""
        config = ENGINE_PRESETS["betterleaks"]
        config.extra_flags = ["--verbose", "--debug"]

        cmd = build_scanner_command(
            engine_config=config,
            source_file="/tmp/test.txt",
            report_file="/tmp/report.json",
        )

        self.assertIn("--verbose", cmd)
        self.assertIn("--debug", cmd)

    def test_build_custom_command(self):
        """Test building custom scanner command."""
        config = EngineConfig(
            type="custom",
            binary="my-scanner",
            command_template=[
                "{binary}",
                "analyze",
                "--input",
                "{source_file}",
                "--output",
                "{report_file}",
                "--format",
                "json",
            ],
            output_parser="gitleaks",
        )

        cmd = build_scanner_command(
            engine_config=config,
            source_file="/tmp/test.txt",
            report_file="/tmp/report.json",
        )

        self.assertEqual(cmd[0], "my-scanner")
        self.assertIn("analyze", cmd)
        self.assertIn("--input", cmd)
        self.assertIn("/tmp/test.txt", cmd)
        self.assertIn("--output", cmd)
        self.assertIn("/tmp/report.json", cmd)

    def test_placeholder_replacement(self):
        """Test that all placeholders are replaced correctly."""
        config = EngineConfig(
            type="test",
            binary="test-scanner",
            command_template=["{binary}", "scan", "{source_file}", "{report_file}"],
            config_flag=["--config", "{config_path}"],
            output_parser="gitleaks",
        )

        cmd = build_scanner_command(
            engine_config=config,
            source_file="/tmp/source.txt",
            report_file="/tmp/report.json",
            config_path="/home/user/config.toml",
        )

        # No placeholders should remain
        for arg in cmd:
            self.assertNotIn("{binary}", arg)
            self.assertNotIn("{source_file}", arg)
            self.assertNotIn("{report_file}", arg)
            self.assertNotIn("{config_path}", arg)


class TestPatternServerSentinel(unittest.TestCase):
    """Tests for PATTERN_SERVER_UNSET sentinel and per-engine pattern_server."""

    def test_preset_engines_have_unset_sentinel(self):
        """Built-in engine presets should have PATTERN_SERVER_UNSET as default."""
        for name, config in ENGINE_PRESETS.items():
            self.assertIs(
                config.pattern_server,
                PATTERN_SERVER_UNSET,
                f"Preset '{name}' should have PATTERN_SERVER_UNSET default",
            )

    def test_string_engine_spec_has_unset_sentinel(self):
        """Engine from string spec should have PATTERN_SERVER_UNSET."""
        config = _build_engine_config("gitleaks")
        self.assertIs(config.pattern_server, PATTERN_SERVER_UNSET)

    def test_dict_engine_with_null_pattern_server(self):
        """Dict engine with pattern_server: null should have None."""
        config = _build_engine_config({"type": "betterleaks", "pattern_server": None})
        self.assertIsNone(config.pattern_server)

    def test_dict_engine_with_pattern_server_url(self):
        """Dict engine with pattern_server URL should preserve the config."""
        ps_config = {"url": "https://patterns.example.com"}
        config = _build_engine_config({"type": "gitleaks", "pattern_server": ps_config})
        self.assertEqual(config.pattern_server, ps_config)

    def test_dict_engine_without_pattern_server_key(self):
        """Dict engine without pattern_server key should keep UNSET."""
        config = _build_engine_config(
            {"type": "betterleaks", "extra_flags": ["--verbose"]}
        )
        self.assertIs(config.pattern_server, PATTERN_SERVER_UNSET)


class TestResolveEngineConfigPath(unittest.TestCase):
    """Tests for resolve_engine_config_path()."""

    def test_unset_gitleaks_uses_global(self):
        """Gitleaks with UNSET pattern_server should use global config_path."""
        config = _build_engine_config("gitleaks")
        result = resolve_engine_config_path(config, "/tmp/patterns.toml")
        self.assertIsNotNone(result)
        self.assertIn("patterns.toml", result)

    def test_unset_leaktk_no_global(self):
        """LeakTK with UNSET pattern_server should NOT use global (no config_flag, #529)."""
        config = _build_engine_config("leaktk")
        result = resolve_engine_config_path(config, "/tmp/patterns.toml")
        self.assertIsNone(result)

    def test_unset_betterleaks_no_global(self):
        """Betterleaks with UNSET pattern_server should NOT use global (incompatible engine)."""
        config = _build_engine_config("betterleaks")
        result = resolve_engine_config_path(config, "/tmp/patterns.toml")
        self.assertIsNone(result)

    def test_unset_trufflehog_no_global(self):
        """TruffleHog with UNSET pattern_server should NOT use global."""
        config = _build_engine_config("trufflehog")
        result = resolve_engine_config_path(config, "/tmp/patterns.toml")
        self.assertIsNone(result)

    def test_null_pattern_server_disables_config(self):
        """Explicit null pattern_server should return None regardless of global."""
        config = _build_engine_config({"type": "gitleaks", "pattern_server": None})
        result = resolve_engine_config_path(config, "/tmp/patterns.toml")
        self.assertIsNone(result)

    def test_null_pattern_server_betterleaks(self):
        """Betterleaks with explicit null → None."""
        config = _build_engine_config({"type": "betterleaks", "pattern_server": None})
        result = resolve_engine_config_path(config, "/tmp/patterns.toml")
        self.assertIsNone(result)

    @patch("ai_guardian.patterns.server.PatternServerClient")
    def test_per_engine_pattern_server_url(self, mock_client_cls):
        """Per-engine pattern_server with URL should fetch engine-specific patterns."""
        mock_client = MagicMock()
        mock_client.get_patterns_path.return_value = "/tmp/engine_patterns.toml"
        mock_client_cls.return_value = mock_client

        config = _build_engine_config(
            {
                "type": "gitleaks",
                "pattern_server": {"url": "https://patterns.example.com"},
            }
        )
        result = resolve_engine_config_path(config, "/tmp/global_patterns.toml")
        self.assertIn("engine_patterns.toml", result)
        mock_client_cls.assert_called_once_with({"url": "https://patterns.example.com"})

    @patch("ai_guardian.patterns.server.PatternServerClient")
    def test_per_engine_pattern_server_fetch_fails(self, mock_client_cls):
        """Per-engine pattern_server fetch failure should return None."""
        mock_client_cls.side_effect = Exception("Connection refused")

        config = _build_engine_config(
            {
                "type": "gitleaks",
                "pattern_server": {"url": "https://unreachable.example.com"},
            }
        )
        result = resolve_engine_config_path(config, "/tmp/global.toml")
        self.assertIsNone(result)

    def test_no_global_config_path(self):
        """UNSET pattern_server with no global → None."""
        config = _build_engine_config("gitleaks")
        result = resolve_engine_config_path(config, None)
        self.assertIsNone(result)

    def test_empty_pattern_server_dict_no_url(self):
        """Per-engine pattern_server dict without url key → None."""
        config = _build_engine_config(
            {"type": "gitleaks", "pattern_server": {"cache_hours": 24}}
        )
        result = resolve_engine_config_path(config, "/tmp/global.toml")
        self.assertIsNone(result)


class TestParentConfigPassthrough(unittest.TestCase):
    """Tests for parent_config flowing to Python scanners (Issue #1093)."""

    def test_build_python_preset_with_parent_config(self):
        from ai_guardian.scanners.engine_builder import _build_python_preset

        parent = {
            "allowlist_patterns": ["test-pattern"],
            "ignore_files": ["**/fixtures/**"],
        }
        config = _build_python_preset("toml-patterns", parent_config=parent)
        self.assertIsNotNone(config)
        scanner = config.python_scanner
        self.assertEqual(scanner._ignore_files, ["**/fixtures/**"])
        self.assertEqual(len(scanner._compiled_allowlist), 1)

    def test_build_engine_config_passes_parent_config(self):
        parent = {
            "allowlist_patterns": ["test-pattern"],
            "ignore_files": ["*.test"],
        }
        config = _build_engine_config("toml-patterns", parent_config=parent)
        self.assertIsNotNone(config)
        self.assertEqual(config.python_scanner._ignore_files, ["*.test"])

    def test_select_engine_passes_parent_config(self):
        parent = {
            "allowlist_patterns": ["test-pattern"],
            "ignore_files": ["*.test"],
        }
        config = select_engine(["toml-patterns"], parent_config=parent)
        self.assertIsNotNone(config)
        self.assertEqual(config.python_scanner._ignore_files, ["*.test"])

    def test_parent_scanner_options_are_forwarded(self):
        marker = "E2E_GUARDIAN_MARKER_A1B2C3D4E5F6G7H8"
        parent = {
            "additional_patterns": [
                {
                    "id": "synthetic-hook-output-marker",
                    "match_type": "regex",
                    "regex": r"E2E_GUARDIAN_MARKER_[A-Z0-9]{16}",
                }
            ],
            "min_entropy": 0.0,
            "stopwords": ["custom-stopword"],
        }
        config = _build_engine_config("toml-patterns", parent_config=parent)

        self.assertIsNotNone(config)
        scanner = config.python_scanner
        self.assertEqual(scanner._min_entropy, 0.0)
        self.assertIn("custom-stopword", scanner._stopwords)
        self.assertTrue(
            any(
                finding.rule_id == "synthetic-hook-output-marker"
                for finding in scanner.scan(marker)
            )
        )

    def test_scanner_config_overrides_parent_config(self):
        from ai_guardian.scanners.engine_builder import _build_python_preset

        parent = {"ignore_files": ["parent-pattern"]}
        scanner_cfg = {"ignore_files": ["engine-pattern"]}
        config = _build_python_preset(
            "toml-patterns",
            scanner_config=scanner_cfg,
            parent_config=parent,
        )
        self.assertIsNotNone(config)
        self.assertEqual(config.python_scanner._ignore_files, ["engine-pattern"])

    def test_parent_config_none_works(self):
        config = _build_engine_config("toml-patterns", parent_config=None)
        self.assertIsNotNone(config)
        self.assertEqual(config.python_scanner._ignore_files, [])

    def test_subprocess_engine_ignores_parent_config(self):
        """Subprocess engines don't use parent_config (no Python scanner)."""
        parent = {"allowlist_patterns": ["test"]}
        with patch("shutil.which", return_value="/usr/bin/gitleaks"):
            config = select_engine(["gitleaks"], parent_config=parent)
        self.assertEqual(config.type, "gitleaks")
        self.assertIsNone(config.python_scanner)


if __name__ == "__main__":
    unittest.main()
