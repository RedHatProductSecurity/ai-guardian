"""Tests for the Scan Configure web page."""

import json
import os
from unittest import mock
from pathlib import Path

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestScanConfigureImport:
    """Verify the page module imports and exposes its create function."""

    def test_scan_configure_page_exists(self):
        from ai_guardian.web.pages.scan_configure import (
            create_scan_configure_page,
        )

        assert callable(create_scan_configure_page)

    def test_scan_configure_in_web_nav(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        tools_items = None
        for name, items in NAV_GROUPS:
            if name == "Tools":
                tools_items = items
                break
        assert tools_items is not None
        slugs = [slug for _, slug in tools_items]
        assert "/scan-configure" in slugs

    def test_scan_configure_after_directory_scan(self):
        from ai_guardian.web.components.header import NAV_GROUPS

        for name, items in NAV_GROUPS:
            if name == "Tools":
                slugs = [slug for _, slug in items]
                idx = slugs.index("/scan-configure")
                assert slugs[idx - 1] == "/directory-scan"
                break


class TestRunScan:
    """Test the background scan function."""

    def test_run_scan_returns_result(self, tmp_path):
        from ai_guardian.web.pages.scan_configure import _run_scan
        from ai_guardian.scan_analyzer import ScanAnalysisResult

        import threading

        cancel = threading.Event()

        mock_analysis = ScanAnalysisResult(
            total_findings=5,
            suppressed_count=3,
            recommended_config={"prompt_injection": {"allowlist_patterns": []}},
            recommended_ignore_paths={},
        )

        progress = {"phase": "", "file": "", "index": 0, "total": 0}

        with (
            mock.patch(
                "ai_guardian.project_init.ProjectInitializer.detect_languages",
                return_value=[],
            ),
            mock.patch(
                "ai_guardian.project_init.ProjectInitializer.generate_allowlist",
                return_value=([], []),
            ),
            mock.patch(
                "ai_guardian.project_init.ProjectInitializer.generate_config",
                return_value={},
            ),
            mock.patch(
                "ai_guardian.scanners.file_scanner.FileScanner.scan_directory",
                return_value=[{"rule_id": "SECRET-001"}] * 5,
            ),
            mock.patch(
                "ai_guardian.project_init.ProjectInitializer.analyze_scan",
                return_value=mock_analysis,
            ),
            mock.patch(
                "ai_guardian.project_init.ProjectInitializer.merge_configs",
                return_value={"prompt_injection": {"allowlist_patterns": []}},
            ),
        ):
            result = _run_scan(str(tmp_path), 10, cancel, progress)

        assert result is not None
        assert result.findings_count == 5
        assert result.analysis.suppressed_count == 3
        assert result.merged_config == {"prompt_injection": {"allowlist_patterns": []}}

    def test_run_scan_cancelled(self, tmp_path):
        from ai_guardian.web.pages.scan_configure import _run_scan

        import threading

        cancel = threading.Event()
        cancel.set()
        progress = {"phase": "", "file": "", "index": 0, "total": 0}

        with mock.patch(
            "ai_guardian.project_init.ProjectInitializer.detect_languages",
            return_value=[],
        ):
            result = _run_scan(str(tmp_path), 10, cancel, progress)

        assert result is None


class TestApplyConfig:
    """Test the config application function."""

    def test_apply_config_rejects_host_managed_config(self, tmp_path):
        from ai_guardian.config.utils import CONFIG_READ_ONLY_MESSAGE
        from ai_guardian.web.pages.scan_configure import _apply_config

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_READ_ONLY": "true"}):
            with pytest.raises(RuntimeError) as exc_info:
                _apply_config(str(tmp_path), {"changed": True}, {})
        assert str(exc_info.value) == CONFIG_READ_ONLY_MESSAGE

    def test_apply_config_project_scope(self, tmp_path):
        from ai_guardian.web.pages.scan_configure import _apply_config

        config = {"prompt_injection": {"allowlist_patterns": ["test"]}}

        with mock.patch(
            "ai_guardian.project_init.ProjectInitializer.write_aiguardignore"
        ):
            _apply_config(str(tmp_path), config, {}, scope="project")

        config_path = tmp_path / ".ai-guardian" / "ai-guardian.json"
        assert config_path.exists()
        written = json.loads(config_path.read_text())
        assert written["prompt_injection"]["allowlist_patterns"] == ["test"]

    def test_apply_config_global_scope(self, tmp_path):
        from ai_guardian.web.pages.scan_configure import _apply_config

        config = {"prompt_injection": {"allowlist_patterns": ["test"]}}

        with mock.patch(
            "ai_guardian.config.utils.get_config_dir",
            return_value=tmp_path,
        ):
            _apply_config(str(tmp_path), config, {}, scope="global")

        config_path = tmp_path / "ai-guardian.json"
        assert config_path.exists()
        written = json.loads(config_path.read_text())
        assert written["prompt_injection"]["allowlist_patterns"] == ["test"]

    def test_apply_config_merges_existing(self, tmp_path):
        from ai_guardian.web.pages.scan_configure import _apply_config

        ai_dir = tmp_path / ".ai-guardian"
        ai_dir.mkdir()
        existing = {"prompt_injection": {"allowlist_patterns": ["old"]}}
        (ai_dir / "ai-guardian.json").write_text(json.dumps(existing))

        new_config = {"prompt_injection": {"allowlist_patterns": ["new"]}}
        with mock.patch(
            "ai_guardian.project_init.ProjectInitializer.write_aiguardignore"
        ):
            _apply_config(str(tmp_path), new_config, {}, scope="project")

        written = json.loads((ai_dir / "ai-guardian.json").read_text())
        assert "old" in written["prompt_injection"]["allowlist_patterns"]
        assert "new" in written["prompt_injection"]["allowlist_patterns"]

    def test_apply_config_skips_empty(self, tmp_path):
        from ai_guardian.web.pages.scan_configure import _apply_config

        _apply_config(str(tmp_path), {}, {})

        config_path = tmp_path / ".ai-guardian" / "ai-guardian.json"
        assert not config_path.exists()

    def test_apply_config_writes_aiguardignore(self, tmp_path):
        from ai_guardian.web.pages.scan_configure import _apply_config

        ignore = {"secret_scanning": ["vendor/**"]}

        with mock.patch(
            "ai_guardian.project_init.ProjectInitializer.write_aiguardignore"
        ) as mock_ignore:
            _apply_config(str(tmp_path), {}, ignore)

        mock_ignore.assert_called_once_with(ignore)
