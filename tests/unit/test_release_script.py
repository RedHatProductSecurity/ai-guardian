"""Contract tests for the automated release script."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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
    assert "verify_container_images.py" in script
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


def test_release_script_synchronizes_rust_middleware_version():
    """Release and post-release commits include the Rust binary version."""
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert "scripts/sync_rust_middleware_version.py" in script
    assert '--version "${NEW_VERSION}"' in script
    assert '--version "${NEXT_DEV_VERSION}"' in script
    assert "rust/openshell-middleware/Cargo.toml" in script
    assert "rust/openshell-middleware/Cargo.lock" in script


def test_release_readiness_derives_previous_stable_version():
    """Upgrade coverage must not require a hand-edited version pin."""
    workflow = RELEASE_READINESS_WORKFLOW.read_text(encoding="utf-8")

    assert "Determine previous stable version" in workflow
    assert "steps.previous.outputs.version" in workflow
    assert "pip install ai-guardian==1.17.1" not in workflow
    assert "assert previous not in v" in workflow


def test_release_readiness_covers_announcement_cli_without_publication():
    """Release gates exercise help and mocked tests, never a real announcement."""
    workflow = yaml.safe_load(RELEASE_READINESS_WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["daemon-lifecycle"]["steps"]
        if step["name"]
        == "Verify release announcement CLI and mocked publication contracts"
    )
    assert "announce-release --help" in step["run"]
    assert (
        "tests/unit/test_release_helper.py tests/unit/test_release_script.py"
        in step["run"]
    )
    assert "gh api" not in step["run"]


@pytest.fixture
def release_sandbox(tmp_path):
    """Run the full shell orchestrator in a disposable tree with fake executables."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "release.sh"
    script.write_bytes(RELEASE_SCRIPT.read_bytes())
    (tmp_path / "README.md").write_text(
        "https://github.com/ai-guardian/main/install.sh\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [Unreleased]\n\n### Added\n- A feature\n"
    )
    (tmp_path / "ai-guardian-example.json").write_text("{}")
    (tmp_path / "docs").mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands.jsonl"
    fake = f"#!{sys.executable}\n" + r"""
import json
import os
import sys
from pathlib import Path

program, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["RELEASE_TEST_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([program, *args]) + "\n")
if program == "git":
    if args == ["branch", "--show-current"]:
        print("main")
    elif args[0] == "rev-parse":
        if args[1] in ("HEAD", "origin/main"):
            print("same-commit")
        else:
            sys.exit(1)
    elif args[:2] == ["tag", "--list"]:
        print("v1.2.2")
    elif args[0] in ("diff", "merge-base"):
        sys.exit(1)
    elif args[0] not in ("status", "fetch", "checkout", "merge", "add", "commit", "push", "tag", "pull"):
        raise AssertionError(args)
elif program == "gh":
    if args[:2] == ["run", "list"]:
        print("123")
    elif args[:2] not in (["auth", "status"], ["workflow", "run"], ["run", "watch"]):
        raise AssertionError(args)
elif program == "python3":
    if Path(args[0]).name == "release_helper.py":
        command = args[3]
        if command == "get-version":
            print("Current version: 1.3.0-dev")
        elif command == "calc-version":
            print("1.2.3")
        elif command == "container-images":
            print("normal: quay.io/redhatproductsecurity/ai-guardian:1.2.3")
            print("openshell: quay.io/redhatproductsecurity/ai-guardian-openshell:1.2.3")
        elif command == "announce-release":
            assert args[4] == "1.2.3"
            if "--dry-run" in args:
                print("[dry-run] Announcements (announcements); AI Guardian v1.2.3 is now available")
                print("https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.2.3")
                print("https://pypi.org/project/ai-guardian/1.2.3/#files; not posted")
            else:
                outcome = os.environ.get("ANNOUNCEMENT_TEST_OUTCOME", "success")
                if outcome in ("unavailable", "uncertain"):
                    print("Announcement not confirmed: " + outcome, file=sys.stderr)
                    sys.exit(1)
                if outcome != "empty":
                    print("invalid receipt" if outcome == "invalid" else "https://github.com/RedHatProductSecurity/ai-guardian/discussions/123")
        elif command not in ("validate", "update-version", "update-changelog"):
            raise AssertionError(args)
    elif Path(args[0]).name not in ("sync_release_versions.py", "sync_rust_middleware_version.py", "verify_container_images.py"):
        raise AssertionError(args)
elif program == "pip":
    sys.exit(int(os.environ.get("PIP_TEST_EXIT", "0")))
elif program not in ("curl", "git-cliff", "sleep"):
    raise AssertionError(program)
"""
    for name in ("git", "gh", "python3", "pip", "curl", "git-cliff", "sleep"):
        path = binaries / name
        path.write_text(fake, encoding="utf-8")
        path.chmod(0o755)

    def run(*flags, outcome="success", pip_exit=0):
        result = subprocess.run(
            ["bash", str(script), "--skip-cursor", *flags, "patch"],
            input="y\ny\n",
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
                "RELEASE_TEST_LOG": str(log),
                "ANNOUNCEMENT_TEST_OUTCOME": outcome,
                "PIP_TEST_EXIT": str(pip_exit),
            },
        )
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        return result, commands

    return run


def test_release_script_announces_after_verification_before_dev_bump(release_sandbox):
    result, commands = release_sandbox()
    assert result.returncode == 0, result.stdout + result.stderr
    announcement = next(
        i for i, command in enumerate(commands) if "announce-release" in command
    )
    pypi = next(
        i
        for i, command in enumerate(commands)
        if command[:3] == ["pip", "install", "--dry-run"]
    )
    containers = next(
        i
        for i, command in enumerate(commands)
        if any(arg.endswith("verify_container_images.py") for arg in command)
    )
    dev_bump = next(
        i
        for i, command in enumerate(commands)
        if "update-version" in command and "1.3.0-dev" in command
    )
    assert pypi < containers < announcement < dev_bump
    assert commands[announcement][-2:] == ["announce-release", "1.2.3"]
    assert "Release Summary" in result.stdout
    assert (
        "Announcement: https://github.com/RedHatProductSecurity/ai-guardian/discussions/123"
        in result.stdout
    )
    assert (
        "Announcement: https://github.com/RedHatProductSecurity/ai-guardian/discussions/123"
        in result.stdout.split("Release Summary")[1]
    )


@pytest.mark.parametrize("outcome", ["unavailable", "uncertain", "empty", "invalid"])
def test_release_script_failed_announcement_is_not_success_or_republication(
    outcome, release_sandbox
):
    result, commands = release_sandbox(outcome=outcome, pip_exit=1)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PyPI verification failed" in result.stdout
    assert "Announcement: not confirmed" in result.stdout
    assert "retry the announcement only, not publication" in result.stdout
    assert "announce-release 1.2.3" in result.stdout
    assert "Main branch updated" in result.stdout
    assert sum("announce-release" in command for command in commands) == 1
    # The only tag/push operations are the normal release, not rollback or retry.
    assert [
        command[3] for command in commands if command[:3] == ["git", "tag", "-a"]
    ] == ["v1.2.3-test1", "v1.2.3"]
    assert [command for command in commands if command[:3] == ["git", "tag", "-d"]] == [
        ["git", "tag", "-d", "v1.2.3-test1"]
    ]
    assert "Announcement: https://" not in result.stdout


def test_release_script_dry_run_previews_announcement_without_mutations(
    release_sandbox,
):
    result, commands = release_sandbox("--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Announcements (announcements)" in result.stdout
    assert "https://pypi.org/project/ai-guardian/1.2.3/#files" in result.stdout
    assert "Announcement: not posted (dry-run)" in result.stdout
    announcement = next(
        command for command in commands if "announce-release" in command
    )
    assert announcement[-3:] == ["announce-release", "1.2.3", "--dry-run"]
    assert not any(command[0] in ("gh", "pip", "curl") for command in commands)
    assert not any(
        command[0] == "git"
        and command[1] in ("checkout", "push", "commit", "add", "tag", "pull", "merge")
        and command[1:3] != ["tag", "--list"]
        for command in commands
    )
