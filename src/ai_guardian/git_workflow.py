"""Git workflow helpers for init-project --annotate.

Creates branches, commits annotation changes, and opens PRs/MRs.
"""

import logging
import subprocess
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def check_clean_working_tree(repo_path: str = ".") -> Tuple[bool, str]:
    """Check that the working tree has no modified or untracked files.

    Returns (is_clean, message).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_path,
        )
        if result.returncode != 0:
            return False, f"git status failed: {result.stderr.strip()}"
        output = result.stdout.strip()
        if output:
            return False, f"Working tree is not clean:\n{output}"
        return True, ""
    except FileNotFoundError:
        return False, "git is not installed"
    except subprocess.TimeoutExpired:
        return False, "git status timed out"


def create_annotation_branch(repo_path: str = ".") -> Optional[str]:
    """Create and checkout a new branch for annotation changes.

    Returns the branch name on success, None on failure.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    branch_name = f"ai-guardian/annotate-{timestamp}"
    try:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_path,
        )
        if result.returncode != 0:
            logger.warning("Failed to create branch %s: %s", branch_name, result.stderr)
            return None
        return branch_name
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("Failed to create branch: %s", e)
        return None


def stage_and_commit(
    file_paths: List[str],
    message: str,
    repo_path: str = ".",
) -> bool:
    """Stage specific files and commit.

    Returns True on success.
    """
    if not file_paths:
        return False
    try:
        add_result = subprocess.run(
            ["git", "add", "--"] + file_paths,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )
        if add_result.returncode != 0:
            logger.warning("git add failed: %s", add_result.stderr)
            return False

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )
        if commit_result.returncode != 0:
            logger.warning("git commit failed: %s", commit_result.stderr)
            return False
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("git stage/commit failed: %s", e)
        return False


def _push_branch(branch_name: str, repo_path: str = ".") -> bool:
    """Push branch to origin."""
    try:
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_path,
        )
        if result.returncode != 0:
            logger.warning("git push failed: %s", result.stderr)
            return False
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("git push failed: %s", e)
        return False


def push_and_create_pr(
    branch_name: str,
    title: str,
    body: str,
    repo_path: str = ".",
) -> Optional[str]:
    """Push branch and create PR/MR. Returns URL or None."""
    from ai_guardian.tools.diff_provider import detect_platform

    if not _push_branch(branch_name, repo_path):
        return None

    platform = detect_platform(repo_path)

    if platform == "github":
        return _create_github_pr(title, body, repo_path)
    elif platform == "gitlab":
        return _create_gitlab_mr(title, body, repo_path)
    else:
        logger.info("Not a GitHub/GitLab repo — skipping PR/MR creation")
        return None


def _create_github_pr(
    title: str,
    body: str,
    repo_path: str = ".",
) -> Optional[str]:
    """Create GitHub PR via gh CLI. Returns PR URL or None."""
    try:
        result = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )
        if result.returncode != 0:
            logger.warning("gh pr create failed: %s", result.stderr)
            return None
        return result.stdout.strip()
    except FileNotFoundError:
        logger.warning("gh CLI not installed — cannot create PR")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("gh pr create timed out")
        return None


def _create_gitlab_mr(
    title: str,
    body: str,
    repo_path: str = ".",
) -> Optional[str]:
    """Create GitLab MR via glab CLI. Returns MR URL or None."""
    try:
        result = subprocess.run(
            ["glab", "mr", "create", "--title", title, "--description", body, "--yes"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )
        if result.returncode != 0:
            logger.warning("glab mr create failed: %s", result.stderr)
            return None
        for line in result.stdout.strip().splitlines():
            if "http" in line:
                return line.strip()
        return result.stdout.strip()
    except FileNotFoundError:
        logger.warning("glab CLI not installed — cannot create MR")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("glab mr create timed out")
        return None


def restore_branch(original_branch: str, repo_path: str = ".") -> None:
    """Checkout the original branch (cleanup on failure)."""
    try:
        subprocess.run(
            ["git", "checkout", original_branch],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_path,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # intentionally silent — best-effort cleanup


def get_current_branch(repo_path: str = ".") -> Optional[str]:
    """Get the current branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_path,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
