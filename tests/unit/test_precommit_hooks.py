"""Tests for pre-commit hook install_precommit_hooks behavior matrix (#2067)."""

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian.setup.hooks import (
    _append_ai_guardian_line,
    _build_scan_line,
    _has_ai_guardian_line,
    _is_sample_hook,
    _update_ai_guardian_line,
    install_precommit_hooks,
)

# --- Helper unit tests ---


class TestIsSampleHook:
    def test_git_sample_hook(self):
        content = "#!/bin/sh\n# An example hook script. This sample shows...\nexit 0\n"
        assert _is_sample_hook(content) is True

    def test_real_hook(self):
        content = "#!/bin/bash\nset -e\nnpm test\n"
        assert _is_sample_hook(content) is False

    def test_long_sample_is_not_sample(self):
        content = "#!/bin/sh\n# sample\n" + "x\n" * 300
        assert _is_sample_hook(content) is False

    def test_non_sh_shebang(self):
        content = "#!/usr/bin/env python3\n# sample\nprint('hi')\n"
        assert _is_sample_hook(content) is False


class TestHasAiGuardianLine:
    def test_has_scan_line(self):
        content = "#!/bin/bash\nai-guardian scan --exit-code .\n"
        assert _has_ai_guardian_line(content) is True

    def test_has_full_path_scan(self):
        content = "#!/bin/bash\n/usr/local/bin/ai-guardian scan --exit-code .\n"
        assert _has_ai_guardian_line(content) is True

    def test_no_ai_guardian(self):
        content = "#!/bin/bash\nnpm test\n"
        assert _has_ai_guardian_line(content) is False

    def test_commented_out_not_counted(self):
        content = "#!/bin/bash\n# ai-guardian scan --exit-code .\nnpm test\n"
        assert _has_ai_guardian_line(content) is False

    def test_ai_guardian_without_scan(self):
        content = "#!/bin/bash\nai-guardian --version\n"
        assert _has_ai_guardian_line(content) is False


class TestAppendAiGuardianLine:
    def test_appends_with_comment(self):
        content = "#!/bin/bash\nnpm test\n"
        result = _append_ai_guardian_line(content)
        assert "# AI Guardian security scan" in result
        assert "ai-guardian scan --exit-code ." in result
        assert result.startswith("#!/bin/bash\nnpm test\n")

    def test_adds_newline_if_missing(self):
        content = "#!/bin/bash\nnpm test"
        result = _append_ai_guardian_line(content)
        assert "npm test\n\n# AI Guardian" in result


class TestUpdateAiGuardianLine:
    @mock.patch(
        "ai_guardian.setup.hooks._build_scan_line",
        return_value="/new/path/ai-guardian scan --exit-code .",
    )
    def test_replaces_old_path(self, _mock):
        content = "#!/bin/bash\n/old/path/ai-guardian scan --exit-code .\n"
        result = _update_ai_guardian_line(content)
        assert "/new/path/ai-guardian scan --exit-code ." in result
        assert "/old/path/" not in result

    @mock.patch(
        "ai_guardian.setup.hooks._build_scan_line",
        return_value="ai-guardian scan --exit-code .",
    )
    def test_preserves_other_lines(self, _mock):
        content = "#!/bin/bash\nnpm test\nai-guardian scan --exit-code .\nexit 0\n"
        result = _update_ai_guardian_line(content)
        assert "npm test\n" in result
        assert "exit 0\n" in result

    @mock.patch(
        "ai_guardian.setup.hooks._build_scan_line",
        return_value="ai-guardian scan --exit-code .",
    )
    def test_no_change_when_same(self, _mock):
        content = "#!/bin/bash\nai-guardian scan --exit-code .\n"
        result = _update_ai_guardian_line(content)
        assert result == content


# --- Integration tests ---


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with hooks dir and no pre-existing hooks."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "pre-commit"
    if hook.exists():
        hook.unlink()
    return tmp_path


@pytest.fixture
def mock_git_root(git_repo):
    """Mock git rev-parse to return our temp repo."""
    with mock.patch(
        "ai_guardian.setup.hooks.subprocess.check_output",
        return_value=str(git_repo),
    ):
        yield git_repo


class TestInstallPrecommitNoExisting:
    def test_fresh_install(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        assert not hook_path.exists()

        with mock.patch("ai_guardian.setup.hooks._auto_install_hook") as mock_auto:
            mock_auto.return_value = (True, "Installed!")
            success, msg = install_precommit_hooks()
            mock_auto.assert_called_once()
            assert success

    def test_sample_hook_treated_as_no_hook(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/sh\n# A sample hook\nexit 0\n")

        with mock.patch("ai_guardian.setup.hooks._auto_install_hook") as mock_auto:
            mock_auto.return_value = (True, "Installed!")
            success, _ = install_precommit_hooks()
            mock_auto.assert_called_once()

    def test_dry_run_no_existing(self, mock_git_root):
        success, msg = install_precommit_hooks(dry_run=True)
        assert success
        assert "DRY RUN" in msg


class TestInstallPrecommitForce:
    def test_force_replaces_with_backup(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/bash\nnpm test\n")

        success, msg = install_precommit_hooks(force=True)
        assert success
        assert "replaced" in msg.lower() or "Backup" in msg

        backup = Path(f"{hook_path}.bak")
        assert backup.exists()
        assert backup.read_text() == "#!/bin/bash\nnpm test\n"
        assert "ai-guardian" in hook_path.read_text().lower()

    def test_force_dry_run(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/bash\nnpm test\n")

        success, msg = install_precommit_hooks(force=True, dry_run=True)
        assert success
        assert "DRY RUN" in msg
        assert hook_path.read_text() == "#!/bin/bash\nnpm test\n"


class TestInstallPrecommitAppend:
    def test_appends_to_existing_hook(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/bash\nnpm test\n")

        success, msg = install_precommit_hooks()
        assert success
        assert "Appended" in msg

        content = hook_path.read_text()
        assert "npm test" in content
        assert "ai-guardian scan" in content

    def test_append_dry_run(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/bash\nnpm test\n")

        success, msg = install_precommit_hooks(dry_run=True)
        assert success
        assert "DRY RUN" in msg
        assert "npm test" in hook_path.read_text()
        assert "ai-guardian" not in hook_path.read_text()


class TestInstallPrecommitUpdate:
    def test_updates_existing_ai_guardian_line(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/bash\n/old/path/ai-guardian scan --exit-code .\n")

        with mock.patch(
            "ai_guardian.setup.hooks._build_scan_line",
            return_value="/new/ai-guardian scan --exit-code .",
        ):
            success, msg = install_precommit_hooks()
            assert success
            assert "Updated" in msg
            content = hook_path.read_text()
            assert "/new/ai-guardian" in content
            assert "/old/path/" not in content

    def test_already_up_to_date(self, mock_git_root):
        hook_path = mock_git_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/bash\nai-guardian scan --exit-code .\n")

        with mock.patch(
            "ai_guardian.setup.hooks._build_scan_line",
            return_value="ai-guardian scan --exit-code .",
        ):
            success, msg = install_precommit_hooks()
            assert success
            assert "up to date" in msg.lower()
