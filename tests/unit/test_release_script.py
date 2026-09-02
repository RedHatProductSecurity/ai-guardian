"""Contract tests for the automated release script."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.sh"


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
