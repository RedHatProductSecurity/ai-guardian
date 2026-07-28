#!/usr/bin/env python3
"""
Tests for release helper module.

This test suite verifies the release helper functionality for:
- Version reading and updating
- CHANGELOG.md management
- Version calculation
- Prerequisites validation

NOTE: These tests are skipped in CI/CD as the release skill is installed
locally on developer machines, not in the repository.
"""

import sys
import tempfile
from pathlib import Path

import pytest

# Try to import release_helper from project skills directory
try:
    # Get project root (parent of tests directory)
    project_root = Path(__file__).parent.parent.parent
    skills_path = project_root / ".claude" / "skills" / "release"

    sys.path.insert(0, str(skills_path))
    from release_helper import ReleaseHelper, CursorHookVerifier

    RELEASE_HELPER_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    RELEASE_HELPER_AVAILABLE = False
    ReleaseHelper = None
    CursorHookVerifier = None

# Skip all tests if release_helper is not available
pytestmark = pytest.mark.skipif(
    not RELEASE_HELPER_AVAILABLE,
    reason="release_helper module not available (.claude/skills/release/ not found)",
)


def create_test_repo(tmp_path):
    """Create a minimal test repository structure."""
    # Create directory structure
    src_dir = tmp_path / "src" / "ai_guardian"
    src_dir.mkdir(parents=True)

    # Create pyproject.toml
    pyproject_content = """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ai-guardian"
version = "1.1.0-dev"
description = "Test"
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content)

    # Create __init__.py
    init_content = '''"""AI Guardian package."""

__version__ = "1.1.0-dev"
'''
    (src_dir / "__init__.py").write_text(init_content)

    # Create CHANGELOG.md
    changelog_content = """# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- New feature X
- New feature Y

### Fixed
- Bug fix Z

## [1.0.0] - 2026-01-01

### Added
- Initial release

[Unreleased]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.0
"""
    (tmp_path / "CHANGELOG.md").write_text(changelog_content)

    return tmp_path


def test_get_current_version():
    """Test getting current version from both files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        version, all_match = helper.get_current_version()

        assert version == "1.1.0-dev"
        assert all_match is True


def test_version_mismatch_detection():
    """Test detection of version mismatch between files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Manually update only one file to create mismatch
        init_path = tmp_path / "src" / "ai_guardian" / "__init__.py"
        content = init_path.read_text()
        content = content.replace(
            '__version__ = "1.1.0-dev"', '__version__ = "1.2.0-dev"'
        )
        init_path.write_text(content)

        helper = ReleaseHelper(tmp_path)
        version, all_match = helper.get_current_version()

        assert version is None  # No single version when mismatch
        assert all_match is False


def test_update_version():
    """Test updating version in both files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        success = helper.update_version("1.2.0")

        assert success is True

        # Verify both files updated
        version, all_match = helper.get_current_version()
        assert version == "1.2.0"
        assert all_match is True


def test_calculate_next_version_minor():
    """Test calculating next minor version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.1.0-dev", "minor")
        assert next_ver == "1.2.0"


def test_calculate_next_version_major():
    """Test calculating next major version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.1.0-dev", "major")
        assert next_ver == "2.0.0"


def test_calculate_next_version_patch():
    """Test calculating next patch version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.1.0", "patch")
        assert next_ver == "1.1.1"


def test_calculate_next_version_test():
    """Test calculating test version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.2.0-dev", "test")
        assert next_ver == "1.2.0-test1"


def test_update_changelog():
    """Test updating CHANGELOG.md."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        success = helper.update_changelog("1.1.0", "2026-04-08")

        assert success is True

        # Verify CHANGELOG updated
        changelog = (tmp_path / "CHANGELOG.md").read_text()
        assert "## [1.1.0] - 2026-04-08" in changelog
        assert "### Added" in changelog
        assert "- New feature X" in changelog
        assert (
            "[1.1.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.1.0"
            in changelog
        )
        assert (
            "[Unreleased]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.1.0...HEAD"
            in changelog
        )


def test_update_changelog_empty_unreleased():
    """Test updating CHANGELOG with empty Unreleased section fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Create CHANGELOG with empty Unreleased
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0] - 2026-01-01

### Added
- Initial release

[Unreleased]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.0
"""
        (tmp_path / "CHANGELOG.md").write_text(changelog_content)

        helper = ReleaseHelper(tmp_path)
        success = helper.update_changelog("1.1.0", "2026-04-08")

        assert success is False


def test_validate_prerequisites_success():
    """Test successful prerequisites validation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is True
        assert len(errors) == 0


def test_validate_prerequisites_version_mismatch():
    """Test prerequisites validation detects version mismatch."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Create version mismatch
        init_path = tmp_path / "src" / "ai_guardian" / "__init__.py"
        content = init_path.read_text()
        content = content.replace(
            '__version__ = "1.1.0-dev"', '__version__ = "1.2.0-dev"'
        )
        init_path.write_text(content)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is False
        assert len(errors) > 0
        assert any("mismatch" in err.lower() for err in errors)


def test_validate_prerequisites_missing_unreleased():
    """Test prerequisites validation detects missing Unreleased section."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Remove Unreleased section
        changelog_content = """# Changelog

## [1.0.0] - 2026-01-01

### Added
- Initial release
"""
        (tmp_path / "CHANGELOG.md").write_text(changelog_content)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is False
        assert len(errors) > 0
        assert any("unreleased" in err.lower() for err in errors)


def test_validate_prerequisites_empty_unreleased():
    """Test prerequisites validation detects empty Unreleased section."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Empty Unreleased section
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0] - 2026-01-01

### Added
- Initial release
"""
        (tmp_path / "CHANGELOG.md").write_text(changelog_content)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is False
        assert len(errors) > 0
        assert any("empty" in err.lower() for err in errors)


import json


def _create_settings(settings_path, hooks=None):
    """Create a minimal hooks.json for testing."""
    if hooks is None:
        settings = {"version": 1}
        for event in CursorHookVerifier.EXPECTED_EVENTS:
            settings[event] = [{"command": "ai-guardian"}]
    else:
        settings = hooks
    settings_path.write_text(json.dumps(settings, indent=2))
    return settings


def _create_debug_log(debug_dir, event_name, cursor_version="0.47.1"):
    """Create a mock debug log file."""
    log_data = {
        "hook_event_name": event_name,
        "cursor_version": cursor_version,
        "_debug_timestamp": 1718640000.0,
        "_debug_event": event_name,
    }
    log_file = (
        debug_dir / f"cursor-hook-debug-{event_name}-{int(1718640000 * 1e9)}.json"
    )
    log_file.write_text(json.dumps(log_data, indent=2))
    return log_file


class TestCursorHookVerifier:
    """Tests for CursorHookVerifier class."""

    def test_setup_creates_debug_script(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        result = verifier.setup()

        assert result is True
        assert verifier.debug_script.exists()
        if sys.platform != "win32":
            assert verifier.debug_script.stat().st_mode & 0o111

    def test_setup_modifies_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        settings = json.loads(settings_path.read_text())
        for event in CursorHookVerifier.EXPECTED_EVENTS:
            entries = settings["hooks"][event]
            debug_entries = [
                e
                for e in entries
                if isinstance(e, dict)
                and "cursor-hook-debug.sh" in e.get("command", "")
            ]
            assert len(debug_entries) == 1, f"Expected 1 debug entry for {event}"

    def test_setup_creates_backup(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        assert verifier.backup_path.exists()

    def test_setup_cleans_old_logs(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        old_log = debug_dir / "cursor-hook-debug-old-12345.json"
        old_log.write_text("{}")

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        assert not old_log.exists()

    def test_setup_fails_if_backup_exists(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        backup = tmp_path / "settings.json.cursor-verify-backup"
        backup.write_text("{}")

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        result = verifier.setup()
        assert result is False

    def test_analyze_all_pass(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in CursorHookVerifier.EXPECTED_EVENTS:
            _create_debug_log(debug_dir, event)

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is True
        assert cursor_version == "0.47.1"

    def test_analyze_missing_event(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in ["beforeSubmitPrompt", "beforeReadFile", "beforeShellExecution"]:
            _create_debug_log(debug_dir, event)

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is False

    def test_analyze_extracts_cursor_version(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in CursorHookVerifier.EXPECTED_EVENTS:
            _create_debug_log(debug_dir, event, cursor_version="0.50.0")

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        _, cursor_version = verifier.analyze()

        assert cursor_version == "0.50.0"

    def test_analyze_hook_name_field(self, tmp_path):
        """Cursor sends hook_name instead of hook_event_name (#1532)."""
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in CursorHookVerifier.EXPECTED_EVENTS:
            log_data = {
                "hook_name": event,
                "cursor_version": "3.1.0",
                "_debug_timestamp": 1718640000.0,
                "_debug_event": event,
            }
            log_file = (
                debug_dir / f"cursor-hook-debug-{event}-{int(1718640000 * 1e9)}.json"
            )
            log_file.write_text(json.dumps(log_data, indent=2))

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is True
        assert cursor_version == "3.1.0"

    def test_analyze_no_files(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is False
        assert cursor_version is None

    def test_cleanup_removes_debug_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()
        verifier.cleanup()

        settings = json.loads(settings_path.read_text())
        for event in CursorHookVerifier.EXPECTED_EVENTS:
            entries = settings.get(event, [])
            for entry in entries:
                if isinstance(entry, dict):
                    assert "cursor-hook-debug.sh" not in entry.get("command", "")

    def test_cleanup_preserves_existing_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()
        verifier.cleanup()

        settings = json.loads(settings_path.read_text())
        assert len(settings["beforeSubmitPrompt"]) == 1
        assert settings["beforeSubmitPrompt"][0]["command"] == "ai-guardian"

    def test_cleanup_removes_files(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        _create_debug_log(debug_dir, "preToolUse")

        verifier.cleanup()

        assert not verifier.debug_script.exists()
        assert not verifier.backup_path.exists()
        assert len(list(debug_dir.glob("cursor-hook-debug-*.json"))) == 0


def run_tests():
    """Run all tests and report results."""
    tests = [
        test_get_current_version,
        test_version_mismatch_detection,
        test_update_version,
        test_calculate_next_version_minor,
        test_calculate_next_version_major,
        test_calculate_next_version_patch,
        test_calculate_next_version_test,
        test_update_changelog,
        test_update_changelog_empty_unreleased,
        test_validate_prerequisites_success,
        test_validate_prerequisites_version_mismatch,
        test_validate_prerequisites_missing_unreleased,
        test_validate_prerequisites_empty_unreleased,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
            print(f"✓ {test.__name__}")
        except AssertionError as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"✗ {test.__name__}: {e}")
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"✗ {test.__name__}: {e}")

    print(f"\n{'='*70}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*70}")

    if errors:
        print("\nFailed tests:")
        for name, error in errors:
            print(f"  {name}: {error}")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
