"""Contract tests for the automated release script."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.sh"
RELEASE_READINESS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "release-readiness.yml"
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="release.sh requires a native Bash environment",
)


def test_release_script_has_valid_bash_syntax():
    """The release script must remain valid Bash after workflow changes."""
    result = subprocess.run(
        ["bash", "-n", str(RELEASE_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_release_script_help_and_docs_verification_contract():
    """Releases advertise their CLI and verify versioned documentation."""
    help_result = subprocess.run(
        ["bash", str(RELEASE_SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert help_result.returncode == 0
    assert "<minor|patch|major>" in help_result.stdout
    assert "https://ai-guardian.readthedocs.io/en/${TAG_NAME}/" in script
    assert "curl --fail --silent --location" in script
    assert "quay.io/redhatproductsecurity/ai-guardian:${NEW_VERSION}" not in script
    assert "${NORMAL_CONTAINER_IMAGE}" in script
    assert "${OPENSHELL_CONTAINER_IMAGE}" in script


def test_release_script_synchronizes_stable_references_before_tagging():
    """The automated release must update and then verify non-package refs."""
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert "scripts/sync_release_versions.py" in script
    assert '--stable-version "${NEW_VERSION}"' in script
    assert "--check" in script
    assert (
        "container/Dockerfile container/Dockerfile.openshell container/README.md"
        in script
    )


def test_release_readiness_derives_previous_stable_version():
    """Upgrade coverage must not require a hand-edited version pin."""
    workflow = RELEASE_READINESS_WORKFLOW.read_text(encoding="utf-8")

    assert "Determine previous stable version" in workflow
    assert "steps.previous.outputs.version" in workflow
    assert "pip install ai-guardian==1.17.1" not in workflow
    assert "assert previous not in v" in workflow
