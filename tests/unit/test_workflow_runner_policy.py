"""Contract tests for the Ubuntu runner migration policy."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

PINNED_WORKFLOWS = (
    "build-container.yml",
    "build-wheel.yml",
    "cli-version-health.yml",
    "integration-tests.yml",
    "lint.yml",
    "parser-compat.yml",
    "pattern-research-reminder.yml",
    "publish.yml",
    "release-readiness.yml",
    "scenario-tests.yml",
    "smoke-tests.yml",
    "tag-monitor.yml",
    "test.yml",
)


def test_linux_workflows_do_not_use_the_moving_ubuntu_label():
    """Existing Linux jobs stay on the deterministic Ubuntu 24.04 image."""
    for workflow_name in PINNED_WORKFLOWS:
        workflow = (WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")
        assert "ubuntu-latest" not in workflow, workflow_name
        assert "ubuntu-24.04" in workflow, workflow_name


def test_test_workflow_keeps_coverage_on_the_pinned_linux_matrix():
    """Coverage uploads must follow the pinned matrix label."""
    workflow = (WORKFLOW_DIR / "test.yml").read_text(encoding="utf-8")

    assert "os: [ubuntu-24.04]" in workflow
    assert "matrix.os == 'ubuntu-24.04'" in workflow
    assert "matrix.os == 'ubuntu-latest'" not in workflow


def test_ubuntu_26_compatibility_workflow_covers_release_risks():
    """The migration gate covers Python, scanners, smoke, and image builds."""
    workflow = (WORKFLOW_DIR / "ubuntu-26-compatibility.yml").read_text(
        encoding="utf-8"
    )

    assert "runs-on: ubuntu-26.04" in workflow
    assert "'3.9', '3.10', '3.11', '3.12', '3.13', '3.14'" in workflow
    assert "ai-guardian scanner install gitleaks --use-pinned" in workflow
    assert "ai-guardian scanner install betterleaks --use-pinned" in workflow
    assert "ai-guardian scanner install leaktk --use-pinned" in workflow
    assert "pytest tests/ -v" in workflow
    assert "ai-guardian doctor --smoke-test" in workflow
    assert "run-scenarios.sh" in workflow
    assert "docker/setup-qemu-action@v4" in workflow
    assert "docker/setup-buildx-action@v4" in workflow
    assert "--platform linux/amd64,linux/arm64" in workflow


def test_release_readiness_calls_ubuntu_26_compatibility_gate():
    """Release readiness must include the migration gate explicitly."""
    workflow = (WORKFLOW_DIR / "release-readiness.yml").read_text(encoding="utf-8")

    assert "ubuntu-26-compatibility:" in workflow
    assert "uses: ./.github/workflows/ubuntu-26-compatibility.yml" in workflow
