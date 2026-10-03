"""Contract tests for the Ubuntu runner migration policy."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

MIGRATED_WORKFLOWS = (
    "build-container.yml",
    "build-wheel.yml",
    "cli-version-health.yml",
    "container-build-validation.yml",
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


def test_linux_workflows_use_the_ubuntu_26_runner():
    """All repository Linux workflow jobs use the Ubuntu 26.04 image."""
    for workflow_name in MIGRATED_WORKFLOWS:
        workflow = (WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")
        assert "ubuntu-latest" not in workflow, workflow_name
        assert "ubuntu-24.04" not in workflow, workflow_name
        assert "ubuntu-26.04" in workflow, workflow_name


def test_test_workflow_keeps_coverage_on_the_pinned_linux_matrix():
    """Coverage uploads must follow the pinned matrix label."""
    workflow = (WORKFLOW_DIR / "test.yml").read_text(encoding="utf-8")

    assert "os: [ubuntu-26.04]" in workflow
    assert "matrix.os == 'ubuntu-26.04'" in workflow
    assert "matrix.os == 'ubuntu-latest'" not in workflow
    assert "pytest tests/ -v" in workflow


def test_supported_python_matrix_starts_at_310():
    """CI matrices cover the supported floor without claiming Python 3.9."""
    for workflow_name in ("test.yml", "release-readiness.yml"):
        workflow = (WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")
        matrix_line = next(
            line
            for line in workflow.splitlines()
            if "python-version:" in line and "[" in line
        )
        assert "3.9" not in matrix_line, workflow_name
        for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
            assert version in workflow, (workflow_name, version)


def test_smoke_install_lifecycle_uses_the_checked_out_wheel():
    """The installer smoke test must validate this checkout, not stale PyPI metadata."""
    workflow = (WORKFLOW_DIR / "smoke-tests.yml").read_text(encoding="utf-8")
    lifecycle = workflow.split("  install-uninstall:", 1)[1]

    assert "python -m build --wheel --outdir" in lifecycle
    assert '--version "$RUNNER_TEMP"/ai-guardian-dist/*.whl' in lifecycle


def test_container_build_validation_covers_release_risks():
    """The release gate covers scanners, smoke, and multi-architecture builds."""
    workflow = (WORKFLOW_DIR / "container-build-validation.yml").read_text(
        encoding="utf-8"
    )

    assert "runs-on: ubuntu-26.04" in workflow
    assert "ubuntu-24.04" not in workflow
    assert "ai-guardian scanner install gitleaks --use-pinned" in workflow
    assert "ai-guardian scanner install betterleaks --use-pinned" in workflow
    assert "ai-guardian scanner install leaktk --use-pinned" in workflow
    assert "ai-guardian doctor --smoke-test" in workflow
    assert "run-scenarios.sh" in workflow
    assert "docker/setup-qemu-action@v4" in workflow
    assert "docker/setup-buildx-action@v4" in workflow
    assert "--platform linux/amd64,linux/arm64" in workflow


def test_release_readiness_calls_container_build_validation_gate():
    """Release readiness must include the container validation gate explicitly."""
    workflow = (WORKFLOW_DIR / "release-readiness.yml").read_text(encoding="utf-8")

    assert "container-build-validation:" in workflow
    assert "uses: ./.github/workflows/container-build-validation.yml" in workflow
