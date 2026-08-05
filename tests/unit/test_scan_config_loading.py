"""Tests for load_scanner_config and scan endpoint config loading (#1797).

Verifies that scan CLI, TUI, MCP, and daemon scan endpoints all load
merged global + project config with .aiguardignore.toml paths merged
into scanner sections.
"""

from unittest.mock import patch, MagicMock
import json

from ai_guardian.config.loaders import load_scanner_config


def _mock_config_file(config_dict):
    return patch(
        "ai_guardian.config.loaders._load_config_file",
        return_value=(config_dict, None),
    )


def _mock_config_file_error(error_msg):
    return patch(
        "ai_guardian.config.loaders._load_config_file",
        return_value=(None, error_msg),
    )


def _mock_aiguardignore(ignore_map):
    """Mock .aiguardignore.toml to return ignore paths per scanner type."""

    def fake_get_ignore_paths(scanner_type, project_root=None):
        return ignore_map.get(scanner_type, [])

    return patch(
        "ai_guardian.config.loaders._aiguardignore_cfg.get_ignore_paths",
        side_effect=fake_get_ignore_paths,
    )


class TestLoadScannerConfig:
    """Tests for the load_scanner_config() function."""

    def test_returns_empty_dict_when_no_config(self):
        with _mock_config_file(None):
            config = load_scanner_config(project_root="/tmp/test")
            assert config == {}

    def test_returns_empty_dict_on_error(self):
        with _mock_config_file_error("File not found"):
            config = load_scanner_config(project_root="/tmp/test")
            assert config == {}

    def test_returns_merged_config(self):
        base = {
            "secret_scanning": {"enabled": True, "allowlist_patterns": ["test.*"]},
            "scan_pii": {"enabled": False},
        }
        with _mock_config_file(base):
            with patch("ai_guardian.config.loaders.HAS_AIGUARDIGNORE", False):
                config = load_scanner_config(project_root="/tmp/test")
                assert config["secret_scanning"]["enabled"] is True
                assert config["secret_scanning"]["allowlist_patterns"] == ["test.*"]
                assert config["scan_pii"]["enabled"] is False

    def test_aiguardignore_merged_into_sections(self):
        base = {
            "secret_scanning": {"enabled": True, "ignore_files": ["existing.txt"]},
        }
        ignore_map = {
            "secret_scanning": ["*.log", "vendor/**"],
            "scan_pii": ["data/**"],
        }
        with _mock_config_file(base):
            with _mock_aiguardignore(ignore_map):
                with patch("ai_guardian.config.loaders.HAS_AIGUARDIGNORE", True):
                    config = load_scanner_config(project_root="/tmp/test")

        assert config["secret_scanning"]["ignore_files"] == [
            "existing.txt",
            "*.log",
            "vendor/**",
        ]
        assert config["scan_pii"]["ignore_files"] == ["data/**"]

    def test_aiguardignore_creates_section_when_missing(self):
        base = {}
        ignore_map = {"prompt_injection": ["prompts/**"]}
        with _mock_config_file(base):
            with _mock_aiguardignore(ignore_map):
                with patch("ai_guardian.config.loaders.HAS_AIGUARDIGNORE", True):
                    config = load_scanner_config(project_root="/tmp/test")

        assert config["prompt_injection"]["ignore_files"] == ["prompts/**"]

    def test_no_aiguardignore_leaves_config_unchanged(self):
        base = {"secret_scanning": {"enabled": True}}
        with _mock_config_file(base):
            with patch("ai_guardian.config.loaders.HAS_AIGUARDIGNORE", False):
                config = load_scanner_config(project_root="/tmp/test")

        assert config == {"secret_scanning": {"enabled": True}}

    def test_project_root_passed_to_aiguardignore(self):
        base = {}
        with _mock_config_file(base):
            with patch("ai_guardian.config.loaders.HAS_AIGUARDIGNORE", True):
                with patch(
                    "ai_guardian.config.loaders._aiguardignore_cfg.get_ignore_paths",
                    return_value=[],
                ) as mock_get:
                    load_scanner_config(project_root="/my/project")
                    calls = mock_get.call_args_list
                    for call in calls:
                        from pathlib import Path

                        assert call.kwargs.get("project_root") == Path("/my/project")


class TestScanCommandConfigLoading:
    """Tests that scan_command uses load_scanner_config."""

    @staticmethod
    def _make_scan_args(tmp_path, **overrides):
        args = MagicMock()
        args.verbose = False
        args.config = None
        args.path = str(tmp_path)
        args.text = None
        args.output = None
        args.format = "text"
        args.diff = False
        args.diff_range = None
        args.pr = None
        args.mr = None
        args.stdin_diff = False
        args.changed_lines_only = False
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def test_scan_command_loads_merged_config(self, tmp_path):
        from ai_guardian.scanners.file_scanner import scan_command

        args = self._make_scan_args(tmp_path)

        test_config = {"secret_scanning": {"enabled": False}}
        with patch(
            "ai_guardian.config.loaders.load_scanner_config",
            return_value=test_config,
        ) as mock_load:
            with patch(
                "ai_guardian.scanners.file_scanner.FileScanner"
            ) as mock_scanner_cls:
                mock_scanner_cls.return_value.scan_directory.return_value = []
                scan_command(args)

        mock_load.assert_called_once()
        mock_scanner_cls.assert_called_once_with(config=test_config, verbose=False)

    def test_scan_command_config_flag_uses_user_file(self, tmp_path):
        from ai_guardian.scanners.file_scanner import scan_command

        user_config_file = tmp_path / "custom.json"
        user_config_file.write_text(json.dumps({"scan_pii": {"enabled": True}}))

        args = self._make_scan_args(tmp_path, config=str(user_config_file))

        with patch("ai_guardian.scanners.file_scanner.FileScanner") as mock_scanner_cls:
            mock_scanner_cls.return_value.scan_directory.return_value = []
            scan_command(args)

        actual_config = mock_scanner_cls.call_args.kwargs["config"]
        assert actual_config["scan_pii"]["enabled"] is True
