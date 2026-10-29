"""Tests for shared about info module."""

from unittest import mock

from ai_guardian.daemon.about import get_about_info, format_about_text, PROJECT_URL


class TestGetAboutInfo:
    def test_returns_dict_with_required_keys(self):
        info = get_about_info()
        assert isinstance(info, dict)
        assert "version" in info
        assert "python" in info
        assert "platform" in info
        assert "config_path" in info
        assert "scanners" in info
        assert "installed_scanners" in info
        assert "url" in info

    def test_version_is_string(self):
        info = get_about_info()
        assert isinstance(info["version"], str)
        assert info["version"] != ""

    def test_python_version_format(self):
        import sys

        info = get_about_info()
        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        assert info["python"] == expected

    def test_platform_is_string(self):
        info = get_about_info()
        assert isinstance(info["platform"], str)
        assert len(info["platform"]) > 0

    def test_scanners_is_list(self):
        info = get_about_info()
        assert isinstance(info["scanners"], list)

    def test_url_is_project_url(self):
        info = get_about_info()
        assert info["url"] == PROJECT_URL

    def test_author_is_dominique_vernier_with_github_profile(self):
        info = get_about_info()
        assert info["author"] == "Dominique Vernier"
        assert info["author_url"] == "https://github.com/itdove"

    def test_scanner_entries_have_name_version_and_default(self):
        from ai_guardian.scanners.manager import InstalledScanner

        fake = [
            InstalledScanner(
                name="gitleaks",
                version="8.30.1",
                path="/usr/bin/gitleaks",
                is_default=True,
            )
        ]
        with mock.patch(
            "ai_guardian.scanners.manager.ScannerManager.list_configured",
            return_value=fake,
        ):
            info = get_about_info()
        assert len(info["scanners"]) >= 1
        assert info["scanners"][0]["name"] == "gitleaks"
        assert info["scanners"][0]["version"] == "8.30.1"
        assert info["scanners"][0]["is_default"] is True

    def test_reports_configured_and_installed_scanners_separately(self):
        """About separates active scanners from the installable inventory."""
        from ai_guardian.scanners.manager import InstalledScanner

        configured = [
            InstalledScanner(
                name="gitleaks",
                version="8.30.1",
                path="/usr/bin/gitleaks",
                is_default=True,
            )
        ]
        installed = configured + [
            InstalledScanner(
                name="leaktk",
                version="0.2.10",
                path="/usr/bin/leaktk",
                is_default=False,
            ),
        ]
        with (
            mock.patch(
                "ai_guardian.scanners.manager.ScannerManager.list_configured",
                return_value=configured,
            ) as mock_configured,
            mock.patch(
                "ai_guardian.scanners.manager.ScannerManager.list_installed_names",
                return_value=[scanner.name for scanner in installed],
            ) as mock_installed_names,
        ):
            info = get_about_info()
        mock_configured.assert_called_once()
        mock_installed_names.assert_called_once()
        assert len(info["scanners"]) == 1
        assert info["scanners"][0]["name"] == "gitleaks"
        assert info["installed_scanners"] == ["gitleaks", "leaktk"]


class TestFormatAboutText:
    def test_author_and_profile_are_shown_even_for_older_daemon_responses(self):
        text = format_about_text({"version": "1.20.0"})
        assert "Author: Dominique Vernier (ITDoVe)" in text.splitlines()
        assert PROJECT_URL in text
        assert "https://github.com/itdove" not in text

    def test_explicit_author_metadata_is_formatted(self):
        text = format_about_text(
            {"author": "Dominique Vernier", "author_url": "https://github.com/itdove"}
        )
        assert "Author: Dominique Vernier (ITDoVe)" in text
        assert "https://github.com/itdove" not in text

    def test_contains_version(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "macOS 26.5 arm64",
            "config_path": "/tmp/cfg",
            "scanners": [],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "AI Guardian v1.9.0" in text

    def test_contains_python(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "Linux 5.15 x86_64",
            "config_path": None,
            "scanners": [],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "Python: 3.12.11" in text

    def test_contains_platform(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "Linux 5.15 x86_64",
            "config_path": None,
            "scanners": [],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "Platform: Linux 5.15 x86_64" in text

    def test_contains_config_path(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "macOS",
            "config_path": "/home/user/.config/ai-guardian/ai-guardian.json",
            "scanners": [],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "Config: /home/user/.config/ai-guardian/ai-guardian.json" in text

    def test_no_config_when_none(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "macOS",
            "config_path": None,
            "scanners": [],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "Config:" not in text

    def test_contains_scanners(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "macOS",
            "config_path": None,
            "scanners": [
                {"name": "gitleaks", "version": "8.30.1", "is_default": False}
            ],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "gitleaks 8.30.1" in text

    def test_default_scanner_marked(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "macOS",
            "config_path": None,
            "scanners": [
                {"name": "gitleaks", "version": "8.30.1", "is_default": True},
                {"name": "betterleaks", "version": "1.1.2", "is_default": False},
            ],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "gitleaks 8.30.1 (default)" in text
        assert "betterleaks 1.1.2" in text
        assert "(default)" not in text.split("betterleaks")[1]

    def test_no_scanners(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "macOS",
            "config_path": None,
            "scanners": [],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert "Scanners: none installed" in text

    def test_contains_url(self):
        info = {
            "version": "1.9.0",
            "python": "3.12.11",
            "platform": "macOS",
            "config_path": None,
            "scanners": [],
            "url": PROJECT_URL,
        }
        text = format_about_text(info)
        assert PROJECT_URL in text
