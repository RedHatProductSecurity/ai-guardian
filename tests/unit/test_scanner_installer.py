"""
Tests for scanner_installer module.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian.scanners.installer import ScannerInstaller


class TestScannerConfigLoading:
    """Tests for scanner config loading from bundled and development paths."""

    def test_load_config_finds_pyproject(self):
        """Test that config loading finds pyproject.toml in at least one location."""
        installer = ScannerInstaller()
        config = installer.scanner_config

        assert config, "Scanner config should not be empty"
        assert "gitleaks" in config or "repos" in config

    def test_load_config_has_repos(self):
        """Test that loaded config contains repos section."""
        installer = ScannerInstaller()
        repos = installer.scanner_config.get("repos", {})

        assert "gitleaks" in repos
        assert "betterleaks" in repos
        assert "leaktk" in repos

    def test_load_config_has_pattern_servers(self):
        """Test that loaded config contains pattern_servers section."""
        installer = ScannerInstaller()
        servers = installer.scanner_config.get("pattern_servers", {})

        assert "leaktk" in servers
        assert "url" in servers["leaktk"]
        assert "patterns_endpoint" in servers["leaktk"]

    def test_get_pattern_servers(self):
        """Test get_pattern_servers returns pattern server config."""
        installer = ScannerInstaller()
        servers = installer.get_pattern_servers()

        assert isinstance(servers, dict)
        assert "leaktk" in servers
        assert servers["leaktk"]["url"] == "https://raw.githubusercontent.com"

    def test_get_pattern_servers_empty_config(self):
        """Test get_pattern_servers with empty scanner config."""
        installer = ScannerInstaller()
        installer.scanner_config = {}
        servers = installer.get_pattern_servers()

        assert servers == {}


class TestScannerInstaller:
    """Tests for ScannerInstaller class."""

    def test_detect_platform(self):
        """Test platform detection."""
        installer = ScannerInstaller()
        platform_arch = installer.detect_platform()

        # Should be in format "system_arch"
        assert "_" in platform_arch

        # Should match one of expected platforms
        expected_platforms = {
            "darwin_arm64",
            "darwin_x64",
            "linux_x64",
            "linux_arm64",
            "linux_armv7",
            "linux_armv6",
            "linux_x32",
            "windows_x64",
            "windows_arm64",
            "windows_x32",
        }
        assert platform_arch in expected_platforms

    def test_get_github_repo(self):
        """Test GitHub repository lookup."""
        installer = ScannerInstaller()

        assert installer.get_github_repo("gitleaks") == "gitleaks/gitleaks"
        assert installer.get_github_repo("betterleaks") == "betterleaks/betterleaks"
        assert installer.get_github_repo("leaktk") == "leaktk/leaktk"

    def test_get_pinned_version(self):
        """Test pinned version lookup."""
        installer = ScannerInstaller()

        # Should return version strings (without 'v' prefix)
        gitleaks_version = installer.get_pinned_version("gitleaks")
        assert gitleaks_version != "unknown"
        assert not gitleaks_version.startswith("v")
        assert "." in gitleaks_version  # Should be semantic version

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_get_latest_version_from_github(self, mock_requests):
        """Test fetching latest version from GitHub API."""
        # Mock successful GitHub API response
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {"tag_name": "v8.30.1"}
        mock_requests.get.return_value = mock_response

        installer = ScannerInstaller()
        version = installer.get_latest_version("gitleaks")

        assert version == "8.30.1"  # Should strip 'v' prefix
        mock_requests.get.assert_called_once()

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_get_latest_version_fallback_to_pinned(self, mock_requests):
        """Test fallback to pinned version when GitHub API fails."""
        # Mock failed GitHub API response
        mock_requests.get.side_effect = Exception("Network error")

        installer = ScannerInstaller()
        version = installer.get_latest_version("gitleaks")

        # Should fall back to pinned version
        assert version != "unknown"
        assert "." in version

    @mock.patch("shutil.which")
    @mock.patch("subprocess.run")
    def test_install_via_package_manager_brew(self, mock_run, mock_which):
        """Test installation via Homebrew (macOS)."""
        # Mock platform detection and brew availability
        with mock.patch("platform.system", return_value="Darwin"):
            mock_which.return_value = "/opt/homebrew/bin/brew"
            mock_run.return_value = mock.Mock(returncode=0)

            installer = ScannerInstaller()
            success = installer.install_via_package_manager("gitleaks")

            assert success
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "brew"
            assert "install" in args
            assert "gitleaks" in args

    @mock.patch("shutil.which")
    @mock.patch("subprocess.run")
    def test_install_via_package_manager_apt(self, mock_run, mock_which):
        """Test installation via apt-get (Linux) for a repo-available scanner."""
        with mock.patch("platform.system", return_value="Linux"):
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/apt-get" if cmd == "apt-get" else None
            )
            mock_run.return_value = mock.Mock(returncode=0)

            installer = ScannerInstaller()
            # Use a scanner name NOT in DOWNLOAD_ONLY_LINUX
            success = installer.install_via_package_manager("future-scanner")

            assert success
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "apt-get" in args
            assert "install" in args

    @mock.patch("shutil.which")
    @mock.patch("subprocess.run")
    def test_install_via_package_manager_dnf(self, mock_run, mock_which):
        """Test installation via dnf (Fedora/RHEL)."""
        with mock.patch("platform.system", return_value="Linux"):
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/dnf" if cmd == "dnf" else None
            )
            mock_run.return_value = mock.Mock(returncode=0)

            installer = ScannerInstaller()
            success = installer.install_via_package_manager("future-scanner")

            assert success
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "dnf" in args
            assert "install" in args

    @mock.patch("shutil.which")
    @mock.patch("subprocess.run")
    def test_install_via_package_manager_dnf_preferred_over_yum(
        self, mock_run, mock_which
    ):
        """Test that dnf is preferred over yum when both are available."""
        with mock.patch("platform.system", return_value="Linux"):
            mock_which.side_effect = lambda cmd: {
                "dnf": "/usr/bin/dnf",
                "yum": "/usr/bin/yum",
            }.get(cmd)
            mock_run.return_value = mock.Mock(returncode=0)

            installer = ScannerInstaller()
            success = installer.install_via_package_manager("future-scanner")

            assert success
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "dnf" in args
            assert "yum" not in args

    @mock.patch("shutil.which")
    def test_install_via_package_manager_skips_download_only_on_linux(self, mock_which):
        """Test that download-only scanners skip Linux package managers entirely."""
        with mock.patch("platform.system", return_value="Linux"):
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/dnf" if cmd == "dnf" else None
            )

            installer = ScannerInstaller()
            for scanner in ["gitleaks", "betterleaks", "leaktk", "trufflehog"]:
                result = installer.install_via_package_manager(scanner)
                assert not result, f"{scanner} should skip Linux package managers"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific path test")
    @mock.patch("ai_guardian.scanners.installer.os.access")
    def test_init_fallback_when_dir_exists_not_writable(self, mock_access):
        """Test fallback to ~/.local/bin when /usr/local/bin exists but is not writable."""
        mock_access.return_value = False

        original_mkdir = Path.mkdir

        def mkdir_side_effect(self, *args, **kwargs):
            if str(self) == "/usr/local/bin":
                return None
            return original_mkdir(self, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", mkdir_side_effect):
            with mock.patch.object(Path, "exists", return_value=True):
                installer = ScannerInstaller()
                assert installer.install_dir == Path.home() / ".local" / "bin"

    def test_install_unsupported_scanner(self):
        """Test that installing unsupported scanner raises ValueError."""
        installer = ScannerInstaller()

        with pytest.raises(ValueError, match="Unsupported scanner"):
            installer.install("invalid_scanner")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_latest_version")
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    def test_install_with_explicit_version(
        self, mock_pkg_mgr, mock_download, mock_get_latest, mock_get_installed
    ):
        """Test installation with explicit version flag."""
        mock_pkg_mgr.return_value = False  # Package manager fails
        mock_download.return_value = Path("/fake/path/gitleaks")
        mock_get_installed.return_value = None  # Not installed

        installer = ScannerInstaller()
        success = installer.install("gitleaks", version="8.30.1")

        # Should use explicit version, not call get_latest_version
        mock_get_latest.assert_not_called()
        mock_download.assert_called_once_with("gitleaks", "8.30.1")
        assert success

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_latest_version")
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_pinned_version")
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    def test_install_with_use_pinned(
        self,
        mock_pkg_mgr,
        mock_download,
        mock_get_pinned,
        mock_get_latest,
        mock_get_installed,
    ):
        """Test installation with use_pinned flag."""
        mock_pkg_mgr.return_value = False  # Package manager fails
        mock_download.return_value = Path("/fake/path/gitleaks")
        mock_get_pinned.return_value = "8.29.0"
        mock_get_installed.return_value = None  # Not installed

        installer = ScannerInstaller()
        success = installer.install("gitleaks", use_pinned=True)

        # Should use pinned version, not call get_latest_version
        mock_get_latest.assert_not_called()
        mock_get_pinned.assert_called_once()
        mock_download.assert_called_once_with("gitleaks", "8.29.0")
        assert success

    @mock.patch("shutil.which")
    @mock.patch("subprocess.run")
    def test_verify_installation_success(self, mock_run, mock_which):
        """Test successful installation verification."""
        mock_which.return_value = "/usr/local/bin/gitleaks"
        mock_run.return_value = mock.Mock(returncode=0)

        installer = ScannerInstaller()
        assert installer.verify_installation("gitleaks")

    @mock.patch("shutil.which")
    def test_verify_installation_not_found(self, mock_which):
        """Test verification when scanner not found."""
        mock_which.return_value = None

        # Create temp install_dir for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))
            assert not installer.verify_installation("gitleaks")

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_install_from_download_network_error(self, mock_requests):
        """Test download failure handling."""
        mock_requests.get.side_effect = Exception("Network error")

        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))

            with pytest.raises(RuntimeError, match="Failed to download"):
                installer.install_from_download("gitleaks", "8.30.1")

    def test_init_creates_install_dir(self):
        """Test that installer creates install directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir) / "new_dir" / "bin"
            assert not install_dir.exists()

            installer = ScannerInstaller(install_dir=install_dir)
            assert install_dir.exists()
            assert installer.install_dir == install_dir

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific path test")
    @mock.patch("ai_guardian.scanners.installer.os.access", return_value=False)
    def test_init_falls_back_to_local_bin(self, mock_access):
        """Test fallback to ~/.local/bin when /usr/local/bin is not writable."""
        original_mkdir = Path.mkdir

        def mkdir_side_effect(self, *args, **kwargs):
            if str(self) == "/usr/local/bin":
                raise PermissionError("Permission denied")
            return original_mkdir(self, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", mkdir_side_effect):
            installer = ScannerInstaller()
            assert installer.install_dir == Path.home() / ".local" / "bin"


class TestPlatformDetection:
    """Tests for platform-specific detection."""

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_darwin_arm64(self, mock_machine, mock_system):
        """Test detection of macOS ARM64 (Apple Silicon)."""
        mock_system.return_value = "Darwin"
        mock_machine.return_value = "arm64"

        installer = ScannerInstaller()
        assert installer.detect_platform() == "darwin_arm64"

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_darwin_x64(self, mock_machine, mock_system):
        """Test detection of macOS x64 (Intel)."""
        mock_system.return_value = "Darwin"
        mock_machine.return_value = "x86_64"

        installer = ScannerInstaller()
        assert installer.detect_platform() == "darwin_x64"

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_linux_x64(self, mock_machine, mock_system):
        """Test detection of Linux x64."""
        mock_system.return_value = "Linux"
        mock_machine.return_value = "x86_64"

        installer = ScannerInstaller()
        assert installer.detect_platform() == "linux_x64"

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_windows_x64(self, mock_machine, mock_system):
        """Test detection of Windows x64."""
        mock_system.return_value = "Windows"
        mock_machine.return_value = "AMD64"

        installer = ScannerInstaller()
        assert installer.detect_platform() == "windows_x64"

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_linux_arm64(self, mock_machine, mock_system):
        """Test detection of Linux ARM64."""
        mock_system.return_value = "Linux"
        mock_machine.return_value = "aarch64"

        installer = ScannerInstaller()
        assert installer.detect_platform() == "linux_arm64"


class TestVersionChecking:
    """Tests for version checking and smart installation."""

    @mock.patch("shutil.which")
    @mock.patch("subprocess.run")
    def test_get_installed_version(self, mock_run, mock_which):
        """Test getting installed version of a scanner."""
        mock_which.return_value = "/usr/local/bin/gitleaks"
        mock_run.return_value = mock.Mock(
            returncode=0, stdout="gitleaks version 8.30.1\n"
        )

        installer = ScannerInstaller()
        version = installer._get_installed_version("gitleaks")

        assert version == "8.30.1"

    @mock.patch("shutil.which")
    @mock.patch("subprocess.run")
    def test_get_installed_version_with_v_prefix(self, mock_run, mock_which):
        """Test parsing version with 'v' prefix."""
        mock_which.return_value = "/usr/local/bin/gitleaks"
        mock_run.return_value = mock.Mock(returncode=0, stdout="v8.30.1\n")

        installer = ScannerInstaller()
        version = installer._get_installed_version("gitleaks")

        assert version == "8.30.1"

    @mock.patch("shutil.which")
    def test_get_installed_version_not_installed(self, mock_which):
        """Test getting version when scanner not installed."""
        mock_which.return_value = None

        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))
            version = installer._get_installed_version("gitleaks")

            assert version is None

    def test_compare_versions_less_than(self):
        """Test version comparison: v1 < v2."""
        installer = ScannerInstaller()

        assert installer._compare_versions("8.30.1", "8.31.0") == -1
        assert installer._compare_versions("8.30.1", "9.0.0") == -1
        assert installer._compare_versions("8.30.0", "8.30.1") == -1

    def test_compare_versions_equal(self):
        """Test version comparison: v1 == v2."""
        installer = ScannerInstaller()

        assert installer._compare_versions("8.30.1", "8.30.1") == 0
        assert installer._compare_versions("v8.30.1", "8.30.1") == 0

    def test_compare_versions_greater_than(self):
        """Test version comparison: v1 > v2."""
        installer = ScannerInstaller()

        assert installer._compare_versions("8.31.0", "8.30.1") == 1
        assert installer._compare_versions("9.0.0", "8.30.1") == 1
        assert installer._compare_versions("8.30.1", "8.30.0") == 1

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_latest_version")
    @mock.patch("shutil.which")
    def test_install_skip_when_up_to_date(
        self, mock_which, mock_get_latest, mock_get_installed
    ):
        """Test that installation is skipped when already up-to-date."""
        mock_get_installed.return_value = "8.30.1"
        mock_get_latest.return_value = "8.30.1"
        mock_which.return_value = "/usr/local/bin/gitleaks"

        installer = ScannerInstaller()
        success = installer.install("gitleaks")

        # Should skip installation
        assert success
        mock_get_installed.assert_called_once_with("gitleaks")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_latest_version")
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    @mock.patch("shutil.which")
    def test_install_upgrade_when_newer_available(
        self,
        mock_which,
        mock_pkg_mgr,
        mock_download,
        mock_get_latest,
        mock_get_installed,
    ):
        """Test that installation proceeds when upgrade is available."""
        mock_get_installed.return_value = "8.30.1"
        mock_get_latest.return_value = "8.31.0"
        mock_which.return_value = "/usr/local/bin/gitleaks"
        mock_pkg_mgr.return_value = False
        mock_download.return_value = Path("/fake/path/gitleaks")

        installer = ScannerInstaller()
        success = installer.install("gitleaks")

        # Should proceed with upgrade
        assert success
        mock_download.assert_called_once_with("gitleaks", "8.31.0")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_latest_version")
    @mock.patch("shutil.which")
    def test_install_no_auto_downgrade(
        self, mock_which, mock_get_latest, mock_get_installed
    ):
        """Test that auto-downgrade is prevented without explicit version."""
        mock_get_installed.return_value = "8.31.0"
        mock_get_latest.return_value = "8.30.1"
        mock_which.return_value = "/usr/local/bin/gitleaks"

        installer = ScannerInstaller()
        success = installer.install("gitleaks")

        # Should skip downgrade and return True
        assert success

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    @mock.patch("shutil.which")
    def test_install_explicit_downgrade_allowed(
        self, mock_which, mock_pkg_mgr, mock_download, mock_get_installed
    ):
        """Test that explicit version allows downgrade."""
        mock_get_installed.return_value = "8.31.0"
        mock_which.return_value = "/usr/local/bin/gitleaks"
        mock_pkg_mgr.return_value = False
        mock_download.return_value = Path("/fake/path/gitleaks")

        installer = ScannerInstaller()
        success = installer.install("gitleaks", version="8.30.1")

        # Should proceed with downgrade
        assert success
        mock_download.assert_called_once_with("gitleaks", "8.30.1")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    @mock.patch("shutil.which")
    def test_install_explicit_reinstall_allowed(
        self, mock_which, mock_pkg_mgr, mock_download, mock_get_installed
    ):
        """Test that explicit version allows reinstalling same version."""
        mock_get_installed.return_value = "8.30.1"
        mock_which.return_value = "/usr/local/bin/gitleaks"
        mock_pkg_mgr.return_value = False
        mock_download.return_value = Path("/fake/path/gitleaks")

        installer = ScannerInstaller()
        success = installer.install("gitleaks", version="8.30.1")

        # Should proceed with reinstall
        assert success
        mock_download.assert_called_once_with("gitleaks", "8.30.1")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_latest_version")
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    def test_install_when_not_installed(
        self, mock_pkg_mgr, mock_download, mock_get_latest, mock_get_installed
    ):
        """Test normal installation when scanner not already installed."""
        mock_get_installed.return_value = None
        mock_get_latest.return_value = "8.30.1"
        mock_pkg_mgr.return_value = False
        mock_download.return_value = Path("/fake/path/gitleaks")

        installer = ScannerInstaller()
        success = installer.install("gitleaks")

        # Should proceed with installation
        assert success
        mock_download.assert_called_once_with("gitleaks", "8.30.1")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    def test_install_upgrade_skips_package_manager(
        self, mock_pkg_mgr, mock_download, mock_get_installed
    ):
        """
        Test that upgrades skip package manager to avoid unnecessary sudo prompts.

        When a scanner is already installed, upgrades should use direct download
        instead of package manager (which requires sudo on Linux).
        """
        mock_get_installed.return_value = "8.18.2"  # Already installed
        mock_download.return_value = Path("/fake/path/gitleaks")

        installer = ScannerInstaller()
        success = installer.install("gitleaks", version="8.30.1")

        assert success
        mock_pkg_mgr.assert_not_called()
        mock_download.assert_called_once_with("gitleaks", "8.30.1")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.get_pinned_version")
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    def test_install_upgrade_pinned_skips_package_manager(
        self, mock_pkg_mgr, mock_download, mock_get_pinned, mock_get_installed
    ):
        """
        Test that pinned-version upgrades skip package manager.

        When the scanner is already installed at an older version and --use-pinned
        requests a newer one, should use direct download (no sudo).
        """
        mock_get_installed.return_value = "8.18.2"  # Already installed
        mock_get_pinned.return_value = "8.30.1"
        mock_download.return_value = Path("/fake/path/gitleaks")

        installer = ScannerInstaller()
        success = installer.install("gitleaks", use_pinned=True)

        assert success
        mock_pkg_mgr.assert_not_called()
        mock_get_pinned.assert_called_once()
        mock_download.assert_called_once_with("gitleaks", "8.30.1")

    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller._get_installed_version"
    )
    @mock.patch("ai_guardian.scanners.installer.ScannerInstaller.install_from_download")
    @mock.patch(
        "ai_guardian.scanners.installer.ScannerInstaller.install_via_package_manager"
    )
    def test_install_reinstall_skips_package_manager(
        self, mock_pkg_mgr, mock_download, mock_get_installed
    ):
        """
        Test that reinstalling the same explicit version skips package manager.

        When the scanner is already at the requested version and an explicit
        version is passed, should reinstall via direct download (no sudo).
        """
        mock_get_installed.return_value = "8.30.1"  # Already at this version
        mock_download.return_value = Path("/fake/path/gitleaks")

        installer = ScannerInstaller()
        success = installer.install("gitleaks", version="8.30.1")

        assert success
        mock_pkg_mgr.assert_not_called()
        mock_download.assert_called_once_with("gitleaks", "8.30.1")


class TestChecksumVerification:
    """Tests for SHA-256 checksum verification."""

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_download_checksums_gitleaks(self, mock_requests):
        """Test downloading checksums file for gitleaks."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        # Use realistic SHA-256 hash (64 hex characters)
        mock_response.text = "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5  gitleaks_8.30.1_darwin_arm64.tar.gz\n"
        mock_requests.get.return_value = mock_response

        installer = ScannerInstaller()
        content = installer._download_checksums(
            "gitleaks", "8.30.1", "gitleaks/gitleaks"
        )

        assert (
            content
            == "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5  gitleaks_8.30.1_darwin_arm64.tar.gz"
        )
        # Verify URL format: scanner_version_checksums.txt
        call_args = mock_requests.get.call_args
        assert "gitleaks_8.30.1_checksums.txt" in call_args[0][0]

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_download_checksums_betterleaks(self, mock_requests):
        """Test downloading checksums file for betterleaks (special naming)."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        # Use realistic SHA-256 hash (64 hex characters)
        mock_response.text = "19cc2298463d7abf0aee9a03208a49834ab2e6f8411781c4cf1360827b3ded36  betterleaks_1.1.2_darwin_arm64.tar.gz\n"
        mock_requests.get.return_value = mock_response

        installer = ScannerInstaller()
        content = installer._download_checksums(
            "betterleaks", "1.1.2", "betterleaks/betterleaks"
        )

        assert (
            content
            == "19cc2298463d7abf0aee9a03208a49834ab2e6f8411781c4cf1360827b3ded36  betterleaks_1.1.2_darwin_arm64.tar.gz"
        )
        # betterleaks uses simple "checksums.txt" without version
        call_args = mock_requests.get.call_args
        assert "checksums.txt" in call_args[0][0]
        assert "betterleaks_1.1.2_checksums.txt" not in call_args[0][0]

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_download_checksums_leaktk(self, mock_requests):
        """Test downloading checksums file for leaktk."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        # Use realistic SHA-256 hash (64 hex characters)
        mock_response.text = "6e1922156209aa60a998b9b62b3e6f194614e8525f79e88098ac81482417f0ed  leaktk-0.2.10-darwin-arm64.tar.xz\n"
        mock_requests.get.return_value = mock_response

        installer = ScannerInstaller()
        content = installer._download_checksums("leaktk", "0.2.10", "leaktk/leaktk")

        assert (
            content
            == "6e1922156209aa60a998b9b62b3e6f194614e8525f79e88098ac81482417f0ed  leaktk-0.2.10-darwin-arm64.tar.xz"
        )
        # Verify URL format: scanner_version_checksums.txt
        call_args = mock_requests.get.call_args
        assert "leaktk_0.2.10_checksums.txt" in call_args[0][0]

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_download_checksums_network_failure(self, mock_requests):
        """Test graceful handling when checksums file download fails."""
        mock_requests.get.side_effect = Exception("Network error")

        installer = ScannerInstaller()
        content = installer._download_checksums(
            "gitleaks", "8.30.1", "gitleaks/gitleaks"
        )

        # Should return None on failure, not raise
        assert content is None

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_download_checksums_http_404(self, mock_requests):
        """Test handling of 404 response for checksums file."""
        mock_response = mock.Mock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        mock_requests.get.return_value = mock_response

        installer = ScannerInstaller()
        content = installer._download_checksums(
            "gitleaks", "8.30.1", "gitleaks/gitleaks"
        )

        # Should return None on HTTP error
        assert content is None

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_download_checksums_empty_content(self, mock_requests):
        """Test handling of empty checksums file."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.text = ""
        mock_requests.get.return_value = mock_response

        installer = ScannerInstaller()
        content = installer._download_checksums(
            "gitleaks", "8.30.1", "gitleaks/gitleaks"
        )

        # Should return None for empty content
        assert content is None

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_download_checksums_malformed_content(self, mock_requests):
        """Test handling of malformed checksums file (too short)."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.text = "abc123"  # Too short to be valid SHA-256
        mock_requests.get.return_value = mock_response

        installer = ScannerInstaller()
        content = installer._download_checksums(
            "gitleaks", "8.30.1", "gitleaks/gitleaks"
        )

        # Should return None for malformed content
        assert content is None

    def test_verify_checksum_success(self):
        """Test successful checksum verification."""
        # Create a temporary file with known content
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            temp_file = Path(f.name)

        try:
            # Compute actual hash
            import hashlib

            actual_hash = hashlib.sha256(b"test content").hexdigest()

            # Create checksums content with the hash
            checksums_content = f"{actual_hash}  test_file.tar.gz\n"

            installer = ScannerInstaller()
            # Should not raise
            installer._verify_checksum(temp_file, checksums_content, "test_file.tar.gz")
        finally:
            temp_file.unlink()

    def test_verify_checksum_mismatch(self):
        """Test checksum verification failure when hash doesn't match."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            temp_file = Path(f.name)

        try:
            # Use a different hash (wrong content)
            wrong_hash = "0" * 64
            checksums_content = f"{wrong_hash}  test_file.tar.gz\n"

            installer = ScannerInstaller()
            with pytest.raises(RuntimeError, match="Checksum verification failed"):
                installer._verify_checksum(
                    temp_file, checksums_content, "test_file.tar.gz"
                )
        finally:
            temp_file.unlink()

    def test_verify_checksum_file_not_in_checksums(self):
        """Test checksum verification failure when file not found in checksums."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            temp_file = Path(f.name)

        try:
            # Checksums for different file
            checksums_content = "abc123  different_file.tar.gz\n"

            installer = ScannerInstaller()
            with pytest.raises(RuntimeError, match="Checksum verification failed"):
                installer._verify_checksum(
                    temp_file, checksums_content, "test_file.tar.gz"
                )
        finally:
            temp_file.unlink()

    def test_verify_checksum_with_multiple_files(self):
        """Test checksum verification with multiple files in checksums."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            temp_file = Path(f.name)

        try:
            import hashlib

            actual_hash = hashlib.sha256(b"test content").hexdigest()

            # Checksums content with multiple files
            checksums_content = f"""
abc123  file1.tar.gz
{actual_hash}  test_file.tar.gz
def456  file2.tar.gz
            """.strip()

            installer = ScannerInstaller()
            # Should find the correct hash in the middle
            installer._verify_checksum(temp_file, checksums_content, "test_file.tar.gz")
        finally:
            temp_file.unlink()

    def test_verify_checksum_case_insensitive(self):
        """Test that checksum verification is case-insensitive for hash."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            temp_file = Path(f.name)

        try:
            import hashlib

            actual_hash = hashlib.sha256(b"test content").hexdigest()

            # Use uppercase hash in checksums
            checksums_content = f"{actual_hash.upper()}  test_file.tar.gz\n"

            installer = ScannerInstaller()
            # Should match regardless of case
            installer._verify_checksum(temp_file, checksums_content, "test_file.tar.gz")
        finally:
            temp_file.unlink()

    def test_verify_checksum_with_binary_mode_indicator(self):
        """Test checksum verification with binary mode indicator (*filename)."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            temp_file = Path(f.name)

        try:
            import hashlib

            actual_hash = hashlib.sha256(b"test content").hexdigest()

            # Binary mode indicator format: hash *filename
            checksums_content = f"{actual_hash} *test_file.tar.gz\n"

            installer = ScannerInstaller()
            # Should handle binary mode indicator correctly
            installer._verify_checksum(temp_file, checksums_content, "test_file.tar.gz")
        finally:
            temp_file.unlink()

    def test_verify_checksum_sanitizes_path_traversal(self):
        """Test that path traversal in checksum filename is sanitized."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            temp_file = Path(f.name)

        try:
            import hashlib

            actual_hash = hashlib.sha256(b"test content").hexdigest()

            # Checksums file contains path traversal attempt
            checksums_content = f"{actual_hash}  ../../tmp/test_file.tar.gz\n"

            installer = ScannerInstaller()
            # Should sanitize to just filename and match successfully
            installer._verify_checksum(temp_file, checksums_content, "test_file.tar.gz")
        finally:
            temp_file.unlink()


class TestVersionValidation:
    """Tests for version format validation."""

    def test_install_from_download_invalid_version_format(self):
        """Test that invalid version format raises ValueError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))

            # Test various invalid version formats
            invalid_versions = [
                "8.30.1; rm -rf /",  # Command injection attempt
                "8.30",  # Missing patch version
                "v8.30.1",  # Has 'v' prefix
                "../8.30.1",  # Path traversal
                "8.30.1-beta",  # Has suffix
            ]

            for invalid_version in invalid_versions:
                with pytest.raises(ValueError, match="Invalid version format"):
                    installer.install_from_download("gitleaks", invalid_version)

    def test_install_from_download_valid_version_format(self):
        """Test that valid version format is accepted."""
        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))

            # Mock requests to avoid actual download
            with mock.patch("ai_guardian.scanners.installer.requests"):
                try:
                    # This will fail on actual download but should pass version validation
                    installer.install_from_download("gitleaks", "8.30.1")
                except Exception as e:
                    # Should not be a ValueError about version format
                    assert "Invalid version format" not in str(e)


class TestLeaktkNamingConventions:
    """Tests for leaktk's different naming conventions."""

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_leaktk_filename_format(self, mock_requests, mock_machine, mock_system):
        """Test that leaktk uses hyphens and x86_64 instead of underscores and x64."""
        mock_system.return_value = "Darwin"
        mock_machine.return_value = "x86_64"

        # Mock successful download and checksum
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.content = b"fake binary content"

        def requests_get_side_effect(url, *args, **kwargs):
            response = mock.Mock()
            response.raise_for_status = mock.Mock()
            if "checksums" in url:
                # Return checksums file
                import hashlib

                file_hash = hashlib.sha256(b"fake binary content").hexdigest()
                response.text = f"{file_hash}  leaktk-0.2.10-darwin-x86_64.tar.xz\n"
            else:
                # Return binary file
                response.content = b"fake binary content"
            return response

        mock_requests.get.side_effect = requests_get_side_effect

        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))

            # Mock tarfile extraction
            with mock.patch("tarfile.open"):
                with mock.patch.object(Path, "rglob") as mock_rglob:
                    # Mock finding the binary in extracted files
                    fake_binary = Path(temp_dir) / "extract" / "leaktk"
                    fake_binary.parent.mkdir(parents=True, exist_ok=True)
                    fake_binary.write_text("fake binary")
                    mock_rglob.return_value = [fake_binary]

                    try:
                        installer.install_from_download("leaktk", "0.2.10")
                    except Exception:
                        # May fail on extraction, but we just need to check the URL
                        pass

            # Check that the download URL used hyphens and x86_64
            calls = [
                call[0][0]
                for call in mock_requests.get.call_args_list
                if "checksums" not in call[0][0]
            ]
            if calls:
                download_url = calls[0]
                assert "leaktk-0.2.10-darwin-x86_64.tar.xz" in download_url
                assert "leaktk_0.2.10" not in download_url  # Should NOT use underscores


class TestWindowsSupport:
    """Tests for Windows-specific install path and binary name handling."""

    @mock.patch("ai_guardian.scanners.installer.sys")
    def test_init_windows_default_install_dir_with_localappdata(self, mock_sys):
        """Test Windows default uses %LOCALAPPDATA%\\ai-guardian\\bin."""
        mock_sys.platform = "win32"
        mock_sys.version_info = sys.version_info

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_localappdata = os.path.join(temp_dir, "AppData", "Local")
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": fake_localappdata}):
                installer = ScannerInstaller()
                expected = Path(fake_localappdata) / "ai-guardian" / "bin"
                assert installer.install_dir == expected
                assert expected.exists()

    @mock.patch("ai_guardian.scanners.installer.sys")
    def test_init_windows_fallback_without_localappdata(self, mock_sys):
        """Test Windows fallback to ~/AppData/Local/ai-guardian/bin when env var missing."""
        mock_sys.platform = "win32"
        mock_sys.version_info = sys.version_info

        with mock.patch.dict(os.environ, {}, clear=False):
            env = os.environ.copy()
            env.pop("LOCALAPPDATA", None)
            with mock.patch.dict(os.environ, env, clear=True):
                installer = ScannerInstaller()
                expected = Path.home() / "AppData" / "Local" / "ai-guardian" / "bin"
                assert installer.install_dir == expected

    @mock.patch("ai_guardian.scanners.installer.sys")
    def test_get_binary_name_windows(self, mock_sys):
        """Test _get_binary_name returns .exe on Windows."""
        mock_sys.platform = "win32"
        mock_sys.version_info = sys.version_info

        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))
            assert installer._get_binary_name("gitleaks") == "gitleaks.exe"
            assert installer._get_binary_name("betterleaks") == "betterleaks.exe"

    @mock.patch("ai_guardian.scanners.installer.sys")
    def test_get_binary_name_unix(self, mock_sys):
        """Test _get_binary_name returns bare name on Unix."""
        mock_sys.platform = "linux"
        mock_sys.version_info = sys.version_info

        installer = ScannerInstaller()
        assert installer._get_binary_name("gitleaks") == "gitleaks"

    @mock.patch("ai_guardian.scanners.installer.sys")
    @mock.patch("shutil.which", return_value=None)
    def test_verify_installation_checks_exe_on_windows(self, mock_which, mock_sys):
        """Test verify_installation checks for .exe in install_dir on Windows."""
        mock_sys.platform = "win32"
        mock_sys.version_info = sys.version_info

        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))

            # No binary present
            assert not installer.verify_installation("gitleaks")

            # Create .exe file
            exe_path = Path(temp_dir) / "gitleaks.exe"
            exe_path.write_text("fake")

            # Still fails (can't run fake binary), but should find the file
            # The verify method tries to run the binary, so mock subprocess
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0)
                assert installer.verify_installation("gitleaks")
                # Verify the binary path used includes .exe
                called_path = mock_run.call_args[0][0][0]
                assert called_path.endswith("gitleaks.exe")

    @mock.patch("ai_guardian.scanners.installer.sys")
    @mock.patch("shutil.which", return_value=None)
    def test_get_installed_version_checks_exe_on_windows(self, mock_which, mock_sys):
        """Test _get_installed_version checks for .exe in install_dir on Windows."""
        mock_sys.platform = "win32"
        mock_sys.version_info = sys.version_info

        with tempfile.TemporaryDirectory() as temp_dir:
            installer = ScannerInstaller(install_dir=Path(temp_dir))

            # No binary present
            assert installer._get_installed_version("gitleaks") is None

            # Create .exe file and mock its version output
            exe_path = Path(temp_dir) / "gitleaks.exe"
            exe_path.write_text("fake")

            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0, stdout="gitleaks version 8.30.1\n"
                )
                version = installer._get_installed_version("gitleaks")
                assert version == "8.30.1"
                called_path = mock_run.call_args[0][0][0]
                assert called_path.endswith("gitleaks.exe")


class TestDownloadWithRetry:
    """Tests for _download_with_retry retry logic."""

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_succeeds_first_attempt(self, mock_requests):
        """Download succeeds on first try — no retry."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_requests.get.return_value = mock_response

        result = ScannerInstaller._download_with_retry(
            "https://example.com/file.tar.gz"
        )
        assert result is mock_response
        assert mock_requests.get.call_count == 1

    @mock.patch("ai_guardian.scanners.installer.time")
    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_succeeds_after_transient_failure(self, mock_requests, mock_time):
        """Download fails once then succeeds — retries work."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_requests.get.side_effect = [
            Exception("Connection reset"),
            mock_response,
        ]

        result = ScannerInstaller._download_with_retry(
            "https://example.com/file.tar.gz"
        )
        assert result is mock_response
        assert mock_requests.get.call_count == 2
        mock_time.sleep.assert_called_once_with(2)

    @mock.patch("ai_guardian.scanners.installer.time")
    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_all_attempts_fail(self, mock_requests, mock_time):
        """All 3 attempts fail — raises RuntimeError."""
        mock_requests.get.side_effect = Exception("Network error")

        with pytest.raises(RuntimeError, match="after 3 attempts"):
            ScannerInstaller._download_with_retry("https://example.com/file.tar.gz")
        assert mock_requests.get.call_count == 3
        assert mock_time.sleep.call_count == 2

    @mock.patch("ai_guardian.scanners.installer.time")
    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_exponential_backoff(self, mock_requests, mock_time):
        """Backoff waits 2s then 4s between attempts."""
        mock_requests.get.side_effect = Exception("timeout")

        with pytest.raises(RuntimeError):
            ScannerInstaller._download_with_retry("https://example.com/file.tar.gz")
        mock_time.sleep.assert_any_call(2)
        mock_time.sleep.assert_any_call(4)

    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_passes_timeout_to_requests(self, mock_requests):
        """Custom timeout forwarded to requests.get."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_requests.get.return_value = mock_response

        ScannerInstaller._download_with_retry(
            "https://example.com/file.tar.gz", timeout=120
        )
        mock_requests.get.assert_called_once_with(
            "https://example.com/file.tar.gz", timeout=120
        )

    @mock.patch("ai_guardian.scanners.installer.time")
    @mock.patch("ai_guardian.scanners.installer.requests")
    def test_http_error_triggers_retry(self, mock_requests, mock_time):
        """HTTP 500 triggers retry via raise_for_status."""
        bad_response = mock.Mock()
        bad_response.raise_for_status.side_effect = Exception("500 Server Error")

        good_response = mock.Mock()
        good_response.raise_for_status = mock.Mock()

        mock_requests.get.side_effect = [bad_response, good_response]

        result = ScannerInstaller._download_with_retry(
            "https://example.com/file.tar.gz"
        )
        assert result is good_response
        assert mock_requests.get.call_count == 2
