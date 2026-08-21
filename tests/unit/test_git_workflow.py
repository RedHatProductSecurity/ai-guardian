"""Tests for git_workflow module — git operations for --annotate."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest


class TestCheckCleanWorkingTree:
    def test_clean_tree(self):
        from ai_guardian.git_workflow import check_clean_working_tree

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            is_clean, msg = check_clean_working_tree()
            assert is_clean is True
            assert msg == ""

    def test_dirty_tree(self):
        from ai_guardian.git_workflow import check_clean_working_tree

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=" M src/app.py\n", stderr=""
            )
            is_clean, msg = check_clean_working_tree()
            assert is_clean is False
            assert "not clean" in msg

    def test_git_not_installed(self):
        from ai_guardian.git_workflow import check_clean_working_tree

        with patch(
            "ai_guardian.git_workflow.subprocess.run", side_effect=FileNotFoundError
        ):
            is_clean, msg = check_clean_working_tree()
            assert is_clean is False
            assert "not installed" in msg

    def test_git_failure(self):
        from ai_guardian.git_workflow import check_clean_working_tree

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="not a git repo"
            )
            is_clean, msg = check_clean_working_tree()
            assert is_clean is False


class TestCreateAnnotationBranch:
    def test_creates_branch(self):
        from ai_guardian.git_workflow import create_annotation_branch

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            branch = create_annotation_branch()
            assert branch is not None
            assert branch.startswith("ai-guardian/annotate-")

    def test_failure_returns_none(self):
        from ai_guardian.git_workflow import create_annotation_branch

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            assert create_annotation_branch() is None


class TestStageAndCommit:
    def test_success(self):
        from ai_guardian.git_workflow import stage_and_commit

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            assert stage_and_commit(["file.py"], "test commit") is True
            assert mock_run.call_count == 2

    def test_empty_files_returns_false(self):
        from ai_guardian.git_workflow import stage_and_commit

        assert stage_and_commit([], "test") is False

    def test_add_failure(self):
        from ai_guardian.git_workflow import stage_and_commit

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            assert stage_and_commit(["file.py"], "test") is False


class TestPushAndCreatePr:
    def test_github_pr(self):
        from ai_guardian.git_workflow import push_and_create_pr

        with patch("ai_guardian.git_workflow._push_branch", return_value=True):
            with patch(
                "ai_guardian.tools.diff_provider.detect_platform",
                return_value="github",
            ):
                with patch(
                    "ai_guardian.git_workflow._create_github_pr",
                    return_value="https://github.com/org/repo/pull/1",
                ):
                    url = push_and_create_pr("branch", "title", "body")
                    assert url == "https://github.com/org/repo/pull/1"

    def test_gitlab_mr(self):
        from ai_guardian.git_workflow import push_and_create_pr

        with patch("ai_guardian.git_workflow._push_branch", return_value=True):
            with patch(
                "ai_guardian.tools.diff_provider.detect_platform",
                return_value="gitlab",
            ):
                with patch(
                    "ai_guardian.git_workflow._create_gitlab_mr",
                    return_value="https://gitlab.com/org/repo/-/merge_requests/1",
                ):
                    url = push_and_create_pr("branch", "title", "body")
                    assert "gitlab" in url

    def test_unknown_platform(self):
        from ai_guardian.git_workflow import push_and_create_pr

        with patch("ai_guardian.git_workflow._push_branch", return_value=True):
            with patch(
                "ai_guardian.tools.diff_provider.detect_platform",
                return_value="unknown",
            ):
                url = push_and_create_pr("branch", "title", "body")
                assert url is None

    def test_push_failure(self):
        from ai_guardian.git_workflow import push_and_create_pr

        with patch("ai_guardian.git_workflow._push_branch", return_value=False):
            url = push_and_create_pr("branch", "title", "body")
            assert url is None


class TestGhCliNotInstalled:
    def test_github_pr_no_gh(self):
        from ai_guardian.git_workflow import _create_github_pr

        with patch(
            "ai_guardian.git_workflow.subprocess.run", side_effect=FileNotFoundError
        ):
            assert _create_github_pr("title", "body") is None

    def test_gitlab_mr_no_glab(self):
        from ai_guardian.git_workflow import _create_gitlab_mr

        with patch(
            "ai_guardian.git_workflow.subprocess.run", side_effect=FileNotFoundError
        ):
            assert _create_gitlab_mr("title", "body") is None


class TestGetCurrentBranch:
    def test_returns_branch(self):
        from ai_guardian.git_workflow import get_current_branch

        with patch("ai_guardian.git_workflow.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n", stderr="")
            assert get_current_branch() == "main"

    def test_failure_returns_none(self):
        from ai_guardian.git_workflow import get_current_branch

        with patch(
            "ai_guardian.git_workflow.subprocess.run", side_effect=FileNotFoundError
        ):
            assert get_current_branch() is None
