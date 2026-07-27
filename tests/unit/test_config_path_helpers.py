"""Tests for config path helper functions (Issue #1726).

Covers: get_all_config_paths(), format_config_paths()
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from ai_guardian.config.utils import get_all_config_paths, format_config_paths


class TestGetAllConfigPaths:
    """Tests for get_all_config_paths()."""

    def test_global_only(self):
        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                paths = get_all_config_paths()
        assert "global" in paths
        assert paths["global"] == Path(
            "/home/user/.config/ai-guardian/ai-guardian.json"
        )
        assert "project" not in paths

    def test_with_existing_project_config(self):
        project_config = Path("/myproject/.ai-guardian/ai-guardian.json")
        with patch(
            "ai_guardian.config.utils.get_project_config_path",
            return_value=project_config,
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                paths = get_all_config_paths()
        assert "global" in paths
        assert "project" in paths
        assert paths["project"] == project_config

    def test_with_explicit_project_dir(self):
        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                paths = get_all_config_paths(project_dir="/projects/carbonite")
        assert "project" in paths
        assert paths["project"] == Path(
            "/projects/carbonite/.ai-guardian/ai-guardian.json"
        )

    def test_project_config_takes_precedence_over_explicit_dir(self):
        existing = Path("/myproject/.ai-guardian/ai-guardian.json")
        with patch(
            "ai_guardian.config.utils.get_project_config_path",
            return_value=existing,
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                paths = get_all_config_paths(project_dir="/other/dir")
        assert paths["project"] == existing

    def test_project_dir_same_as_global_excluded(self):
        global_dir = Path("/home/user/.config/ai-guardian")
        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=global_dir,
            ):
                paths = get_all_config_paths(project_dir=str(global_dir))
        assert "project" not in paths


class TestFormatConfigPaths:
    """Tests for format_config_paths()."""

    def test_global_only(self):
        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                result = format_config_paths()
        assert "Global:" in result
        assert "ai-guardian.json" in result
        assert "Project:" not in result

    def test_both_paths(self):
        project_config = Path("/myproject/.ai-guardian/ai-guardian.json")
        with patch(
            "ai_guardian.config.utils.get_project_config_path",
            return_value=project_config,
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                result = format_config_paths()
        assert "Project:" in result
        assert "Global:" in result
        assert "(recommended)" in result
        lines = result.strip().split("\n")
        assert lines[0].strip().startswith("Project:")

    def test_project_not_exists_annotation(self):
        with patch(
            "ai_guardian.config.utils.get_project_config_path", return_value=None
        ):
            with patch(
                "ai_guardian.config.utils.get_config_dir",
                return_value=Path("/home/user/.config/ai-guardian"),
            ):
                result = format_config_paths(project_dir="/nonexistent/dir")
        assert "(will be created)" in result
        assert "(recommended)" in result

    def test_project_exists_no_create_annotation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            config_dir = project_dir / ".ai-guardian"
            config_dir.mkdir()
            config_file = config_dir / "ai-guardian.json"
            config_file.write_text("{}")
            with patch(
                "ai_guardian.config.utils.get_project_config_path",
                return_value=config_file,
            ):
                with patch(
                    "ai_guardian.config.utils.get_config_dir",
                    return_value=Path("/home/user/.config/ai-guardian"),
                ):
                    result = format_config_paths()
        assert "(will be created)" not in result
        assert "(recommended)" in result
