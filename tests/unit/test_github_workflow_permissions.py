"""Security contracts for GitHub Actions token permissions."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_test_workflow_limits_github_token_to_read_only_contents():
    """The test workflow needs repository checkout, but no write permissions."""
    workflow_path = REPO_ROOT / ".github" / "workflows" / "test.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert workflow["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in workflow["jobs"].values())
