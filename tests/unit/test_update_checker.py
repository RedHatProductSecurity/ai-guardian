"""Tests for the update_checker module (Issue #2155)."""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.update_checker import (
    UpdateCheckCache,
    UpgradeResult,
    build_upgrade_command,
    detect_install_method,
    fetch_pypi_versions,
    get_latest_version,
    is_upgrade_available,
    perform_full_upgrade,
    run_self_upgrade,
)

# ---------------------------------------------------------------------------
# detect_install_method
# ---------------------------------------------------------------------------


class TestDetectInstallMethod:
    def test_detect_uv_install(self, tmp_path):
        fake_exe = tmp_path / "ai-guardian"
        fake_target = tmp_path / "uv" / "tools" / "ai-guardian" / "bin" / "ag"
        fake_target.parent.mkdir(parents=True)
        fake_target.write_text("")
        fake_exe.symlink_to(fake_target)

        with patch("shutil.which", return_value=str(fake_exe)):
            assert detect_install_method() == "uv"

    def test_detect_pipx_install(self, tmp_path):
        fake_exe = tmp_path / "ai-guardian"
        fake_target = tmp_path / "pipx" / "venvs" / "ai-guardian" / "bin" / "ag"
        fake_target.parent.mkdir(parents=True)
        fake_target.write_text("")
        fake_exe.symlink_to(fake_target)

        with patch("shutil.which", return_value=str(fake_exe)):
            assert detect_install_method() == "pipx"

    def test_detect_venv_pip(self):
        with (
            patch("shutil.which", return_value=None),
            patch.object(sys, "prefix", "/some/venv"),
            patch.object(sys, "base_prefix", "/usr"),
        ):
            assert detect_install_method() == "venv-pip"

    def test_detect_user_pip(self):
        mock_mod = MagicMock()
        mock_mod.__file__ = (
            "/home/user/.local/lib/python3.12/site-packages/ai_guardian/__init__.py"
        )

        with (
            patch("shutil.which", return_value=None),
            patch.object(sys, "prefix", "/usr"),
            patch.object(sys, "base_prefix", "/usr"),
            patch.dict("sys.modules", {"ai_guardian": mock_mod}),
        ):
            assert detect_install_method() == "user-pip"

    def test_detect_system_pip_fallback(self):
        mock_mod = MagicMock()
        mock_mod.__file__ = "/usr/lib/python3.12/site-packages/ai_guardian/__init__.py"

        with (
            patch("shutil.which", return_value=None),
            patch.object(sys, "prefix", "/usr"),
            patch.object(sys, "base_prefix", "/usr"),
            patch.dict("sys.modules", {"ai_guardian": mock_mod}),
        ):
            assert detect_install_method() == "system-pip"

    def test_no_executable_found(self):
        with (
            patch("shutil.which", return_value=None),
            patch.object(sys, "prefix", "/usr"),
            patch.object(sys, "base_prefix", "/usr"),
        ):
            result = detect_install_method()
            assert result in ("user-pip", "system-pip")


# ---------------------------------------------------------------------------
# fetch_pypi_versions / get_latest_version
# ---------------------------------------------------------------------------


SAMPLE_PYPI_RESPONSE = json.dumps(
    {
        "info": {"version": "1.18.0"},
        "releases": {
            "1.16.0": [{"filename": "ai_guardian-1.16.0.tar.gz"}],
            "1.17.0": [{"filename": "ai_guardian-1.17.0.tar.gz"}],
            "1.18.0": [{"filename": "ai_guardian-1.18.0.tar.gz"}],
            "1.19.0a1": [{"filename": "ai_guardian-1.19.0a1.tar.gz"}],
            "1.19.0rc1": [{"filename": "ai_guardian-1.19.0rc1.tar.gz"}],
            "2.0.0.dev1": [{"filename": "ai_guardian-2.0.0.dev1.tar.gz"}],
            "0.1.0": [],
        },
    }
).encode()


class TestFetchPypiVersions:
    def test_success_filters_prerelease(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_PYPI_RESPONSE
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ai_guardian.update_checker.urlopen", return_value=mock_resp):
            versions = fetch_pypi_versions(include_prerelease=False)

        assert versions is not None
        assert "1.18.0" in versions
        assert "1.19.0a1" not in versions
        assert "1.19.0rc1" not in versions
        assert "2.0.0.dev1" not in versions
        assert versions[0] == "1.18.0"

    def test_success_includes_prerelease(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_PYPI_RESPONSE
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ai_guardian.update_checker.urlopen", return_value=mock_resp):
            versions = fetch_pypi_versions(include_prerelease=True)

        assert versions is not None
        assert "1.19.0a1" in versions
        assert "1.19.0rc1" in versions

    def test_skips_empty_releases(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_PYPI_RESPONSE
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ai_guardian.update_checker.urlopen", return_value=mock_resp):
            versions = fetch_pypi_versions(include_prerelease=False)

        assert "0.1.0" not in versions

    def test_network_error_returns_none(self):
        from urllib.error import URLError

        with patch(
            "ai_guardian.update_checker.urlopen",
            side_effect=URLError("timeout"),
        ):
            assert fetch_pypi_versions() is None

    def test_timeout_returns_none(self):
        with patch(
            "ai_guardian.update_checker.urlopen",
            side_effect=TimeoutError(),
        ):
            assert fetch_pypi_versions() is None


class TestGetLatestVersion:
    def test_returns_first_version(self):
        with patch(
            "ai_guardian.update_checker.fetch_pypi_versions",
            return_value=["1.18.0", "1.17.0"],
        ):
            assert get_latest_version() == "1.18.0"

    def test_returns_none_on_failure(self):
        with patch(
            "ai_guardian.update_checker.fetch_pypi_versions",
            return_value=None,
        ):
            assert get_latest_version() is None

    def test_returns_none_on_empty(self):
        with patch(
            "ai_guardian.update_checker.fetch_pypi_versions",
            return_value=[],
        ):
            assert get_latest_version() is None


# ---------------------------------------------------------------------------
# is_upgrade_available
# ---------------------------------------------------------------------------


class TestIsUpgradeAvailable:
    def test_newer_version_available(self):
        assert is_upgrade_available("1.17.0", "1.18.0") is True

    def test_same_version(self):
        assert is_upgrade_available("1.18.0", "1.18.0") is False

    def test_older_latest(self):
        assert is_upgrade_available("1.18.0", "1.17.0") is False

    def test_dev_suffix_treated_as_older(self):
        assert is_upgrade_available("1.18.0-dev", "1.18.0") is True

    def test_none_latest(self):
        assert is_upgrade_available("1.18.0", None) is False

    def test_empty_latest(self):
        assert is_upgrade_available("1.18.0", "") is False


# ---------------------------------------------------------------------------
# UpdateCheckCache
# ---------------------------------------------------------------------------


class TestUpdateCheckCache:
    def test_save_load_roundtrip(self, tmp_path):
        with patch(
            "ai_guardian.config.utils.get_state_dir",
            return_value=tmp_path,
        ):
            cache = UpdateCheckCache(
                latest_version="1.18.0",
                checked_at=time.time(),
                install_method="uv",
            )
            cache.save()

            loaded = UpdateCheckCache.load()
            assert loaded is not None
            assert loaded.latest_version == "1.18.0"
            assert loaded.install_method == "uv"

    def test_load_missing_file(self, tmp_path):
        with patch(
            "ai_guardian.config.utils.get_state_dir",
            return_value=tmp_path,
        ):
            assert UpdateCheckCache.load() is None

    def test_load_corrupt_file(self, tmp_path):
        cache_file = tmp_path / "update_check.json"
        cache_file.write_text("not json", encoding="utf-8")

        with patch(
            "ai_guardian.config.utils.get_state_dir",
            return_value=tmp_path,
        ):
            assert UpdateCheckCache.load() is None

    def test_is_stale_true(self):
        cache = UpdateCheckCache(checked_at=time.time() - 86400)
        assert cache.is_stale(3600) is True

    def test_is_stale_false(self):
        cache = UpdateCheckCache(checked_at=time.time())
        assert cache.is_stale(3600) is False


# ---------------------------------------------------------------------------
# build_upgrade_command
# ---------------------------------------------------------------------------


class TestBuildUpgradeCommand:
    def test_uv(self):
        cmd = build_upgrade_command("uv")
        assert cmd == ["uv", "tool", "install", "--force", "ai-guardian"]

    def test_uv_with_version(self):
        cmd = build_upgrade_command("uv", version="1.18.0")
        assert cmd == ["uv", "tool", "install", "--force", "ai-guardian==1.18.0"]

    def test_pipx(self):
        cmd = build_upgrade_command("pipx")
        assert cmd == ["pipx", "upgrade", "ai-guardian"]

    def test_pipx_with_version(self):
        cmd = build_upgrade_command("pipx", version="1.18.0")
        assert cmd == ["pipx", "install", "--force", "ai-guardian==1.18.0"]

    def test_venv_pip(self):
        cmd = build_upgrade_command("venv-pip")
        assert cmd[0] == sys.executable
        assert "--upgrade" in cmd
        assert "ai-guardian" in cmd

    def test_system_pip(self):
        cmd = build_upgrade_command("system-pip")
        assert cmd[0] == sys.executable
        assert "-m" in cmd
        assert "pip" in cmd

    def test_system_pip_with_version(self):
        cmd = build_upgrade_command("system-pip", version="1.18.0")
        assert "ai-guardian==1.18.0" in cmd

    def test_never_contains_sudo(self):
        for method in ("uv", "pipx", "venv-pip", "user-pip", "system-pip", "unknown"):
            cmd = build_upgrade_command(method)
            assert "sudo" not in cmd


# ---------------------------------------------------------------------------
# run_self_upgrade
# ---------------------------------------------------------------------------


class TestRunSelfUpgrade:
    def test_dry_run_returns_command(self):
        with patch(
            "ai_guardian.update_checker.detect_install_method",
            return_value="uv",
        ):
            result = run_self_upgrade(dry_run=True)

        assert result.success is True
        assert "uv" in result.output
        assert result.command[0] == "uv"

    def test_success(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Successfully installed"
        mock_proc.stderr = ""

        with (
            patch(
                "ai_guardian.update_checker.detect_install_method",
                return_value="venv-pip",
            ),
            patch("subprocess.run", return_value=mock_proc),
            patch(
                "importlib.metadata.version",
                return_value="1.18.0",
            ),
        ):
            result = run_self_upgrade()

        assert result.success is True
        assert result.new_version == "1.18.0"

    def test_permission_error(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "ERROR: Permission denied"

        with (
            patch(
                "ai_guardian.update_checker.detect_install_method",
                return_value="system-pip",
            ),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = run_self_upgrade()

        assert result.success is False
        assert result.permission_error is True
        assert "sudo" in result.output

    def test_timeout(self):
        import subprocess as _sp

        with (
            patch(
                "ai_guardian.update_checker.detect_install_method",
                return_value="uv",
            ),
            patch(
                "subprocess.run", side_effect=_sp.TimeoutExpired(cmd="uv", timeout=120)
            ),
        ):
            result = run_self_upgrade()

        assert result.success is False
        assert "timed out" in result.output

    def test_command_not_found(self):
        with (
            patch(
                "ai_guardian.update_checker.detect_install_method",
                return_value="uv",
            ),
            patch("subprocess.run", side_effect=FileNotFoundError()),
        ):
            result = run_self_upgrade()

        assert result.success is False
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# perform_full_upgrade
# ---------------------------------------------------------------------------


class TestPerformFullUpgrade:
    def test_upgrade_with_restart(self):
        mock_result = UpgradeResult(success=True, new_version="1.18.0")

        with (
            patch(
                "ai_guardian.update_checker.run_self_upgrade",
                return_value=mock_result,
            ),
            patch(
                "ai_guardian.update_checker._get_active_session_count",
                return_value=0,
            ),
            patch("ai_guardian.update_checker._restart_daemon") as mock_restart,
        ):
            result = perform_full_upgrade()

        assert result.success is True
        mock_restart.assert_called_once()

    def test_upgrade_no_restart(self):
        mock_result = UpgradeResult(success=True, new_version="1.18.0")

        with (
            patch(
                "ai_guardian.update_checker.run_self_upgrade",
                return_value=mock_result,
            ),
            patch(
                "ai_guardian.update_checker._get_active_session_count",
                return_value=0,
            ),
            patch("ai_guardian.update_checker._restart_daemon") as mock_restart,
        ):
            result = perform_full_upgrade(restart_daemon=False)

        assert result.success is True
        mock_restart.assert_not_called()

    def test_active_sessions_warns(self):
        mock_result = UpgradeResult(success=True)

        with (
            patch(
                "ai_guardian.update_checker.run_self_upgrade",
                return_value=mock_result,
            ),
            patch(
                "ai_guardian.update_checker._get_active_session_count",
                return_value=2,
            ),
            patch("ai_guardian.update_checker._restart_daemon"),
            patch("ai_guardian.update_checker.logger") as mock_logger,
        ):
            perform_full_upgrade()

        mock_logger.warning.assert_called_once()
        assert "%d active session" in mock_logger.warning.call_args[0][0]

    def test_no_restart_on_failure(self):
        mock_result = UpgradeResult(success=False, output="error")

        with (
            patch(
                "ai_guardian.update_checker.run_self_upgrade",
                return_value=mock_result,
            ),
            patch(
                "ai_guardian.update_checker._get_active_session_count",
                return_value=0,
            ),
            patch("ai_guardian.update_checker._restart_daemon") as mock_restart,
        ):
            result = perform_full_upgrade()

        assert result.success is False
        mock_restart.assert_not_called()
