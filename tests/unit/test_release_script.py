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
README = REPO_ROOT / "README.md"
RELEASING_DOC = REPO_ROOT / "RELEASING.md"
RELEASE_READINESS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "release-readiness.yml"
)
REQUIRED_CI_WORKFLOWS = (
    "release-readiness.yml",
    "test.yml",
    "lint.yml",
    "integration-tests.yml",
)
WORKFLOW_RUN_IDS = {
    workflow: str(1001 + index) for index, workflow in enumerate(REQUIRED_CI_WORKFLOWS)
}

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
    assert "--write-out '%{http_code} %{url_effective}'" in script
    assert "DOCS_VERSION_URL_PREFIX" in script
    assert "DOCS_VERIFICATION_STATUS" in script
    assert "quay.io/redhatproductsecurity/ai-guardian:${NEW_VERSION}" not in script
    assert "verify_container_images.py" in script
    assert "${NORMAL_CONTAINER_IMAGE}" in script
    assert "${OPENSHELL_CONTAINER_IMAGE}" in script


def test_readme_links_to_stable_docs_and_labels_latest_as_development():
    """The default documentation link is stable, with main docs separate."""
    readme = README.read_text(encoding="utf-8")

    assert "Full documentation site (latest stable release)" in readme
    assert "https://ai-guardian.readthedocs.io/en/stable/" in readme
    assert "Latest documentation (tracks `main`)" in readme
    assert "https://ai-guardian.readthedocs.io/en/latest/" in readme


def test_release_docs_explain_dashboard_activation_and_recovery():
    """Maintainers can configure RTD once and recover a missed release version."""
    releasing = RELEASING_DOC.read_text(encoding="utf-8")

    assert "Neither `.readthedocs.yaml` nor the release script manages" in releasing
    assert "Match: **SemVer versions**" in releasing
    assert "Version type: **Tag**" in releasing
    assert "Action: **Activate version**" in releasing
    assert (
        "Activated versions appear in the Read the Docs version selector" in releasing
    )
    assert "Read the Docs → Versions" in releasing
    assert "Do not rerun the full release script" in releasing


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


def test_release_ci_workflows_have_safe_manual_dispatch_contracts():
    """Release validation dispatches CI without scanner issue automation."""

    def events(workflow_path):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        return workflow.get("on", workflow.get(True, {}))

    test_events = events(REPO_ROOT / ".github" / "workflows" / "test.yml")
    lint_events = events(REPO_ROOT / ".github" / "workflows" / "lint.yml")
    integration_events = events(
        REPO_ROOT / ".github" / "workflows" / "integration-tests.yml"
    )
    assert "workflow_dispatch" in test_events
    assert "workflow_dispatch" in lint_events

    release_validation = integration_events["workflow_dispatch"]["inputs"][
        "release_validation"
    ]
    assert release_validation["type"] == "boolean"
    assert release_validation["default"] is False

    integration = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "integration-tests.yml").read_text(
            encoding="utf-8"
        )
    )
    health_check = integration["jobs"]["version-health-check"]
    assert "github.event.inputs.release_validation != 'true'" in health_check["if"]

    readiness = yaml.safe_load(RELEASE_READINESS_WORKFLOW.read_text(encoding="utf-8"))
    jobs = readiness["jobs"]
    assert jobs["smoke-tests"]["uses"] == "./.github/workflows/smoke-tests.yml"
    assert jobs["scenario-tests"]["uses"] == "./.github/workflows/scenario-tests.yml"
    assert (
        jobs["container-build-validation"]["uses"]
        == "./.github/workflows/container-build-validation.yml"
    )


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
    if args[:2] == ["-c", "merge.conflictStyle=merge"]:
        args = args[2:]
    if args == ["branch", "--show-current"]:
        print(os.environ.get("RELEASE_CURRENT_BRANCH", "main"))
    elif args[0] == "rev-parse":
        if args[1] == "HEAD":
            print(os.environ.get("RELEASE_HEAD_SHA", "same-commit"))
        elif args[1] == "origin/main":
            print(os.environ.get("RELEASE_MAIN_SHA", "same-commit"))
        elif args[1] == "--verify" and args[2].startswith("origin/release-"):
            remote_sha = os.environ.get("RELEASE_REMOTE_BRANCH_SHA", "")
            if remote_sha:
                print(remote_sha)
            else:
                sys.exit(1)
        else:
            sys.exit(1)
    elif args[:2] == ["tag", "--list"]:
        print("v1.2.2")
    elif args[:3] == ["diff", "--name-only", "--diff-filter=U"]:
        conflicts = json.loads(os.environ["RELEASE_MERGE_CONFLICTS"])
        commands = [
            json.loads(line)
            for line in Path(os.environ["RELEASE_TEST_LOG"]).read_text().splitlines()
        ]
        resolver_ran = any(
            command[0] == "python3"
            and Path(command[1]).name == "resolve_release_merge.py"
            for command in commands
        )
        if conflicts and not resolver_ran:
            print("\n".join(conflicts))
    elif args[0] == "merge":
        if json.loads(os.environ["RELEASE_MERGE_CONFLICTS"]):
            sys.exit(1)
    elif args[0] in ("diff", "merge-base"):
        sys.exit(1)
    elif args[0] not in ("status", "fetch", "checkout", "merge", "add", "commit", "push", "tag", "pull"):
        raise AssertionError(args)
elif program == "gh":
    workflow_ids = json.loads(os.environ["RELEASE_WORKFLOW_RUN_IDS"])
    outcomes = json.loads(os.environ["RELEASE_WORKFLOW_OUTCOMES"])
    previous_runs = json.loads(os.environ["RELEASE_PREEXISTING_RUNS"])
    metadata_overrides = json.loads(os.environ["RELEASE_RUN_METADATA"])
    missing_workflow = os.environ.get("RELEASE_MISSING_WORKFLOW", "")
    dispatch_failure = os.environ.get("RELEASE_DISPATCH_FAILURE", "")

    def option_value(name):
        for index, argument in enumerate(args):
            if argument == name and index + 1 < len(args):
                return args[index + 1]
            if argument.startswith(name + "="):
                return argument.split("=", 1)[1]
        return ""

    def workflow_for_run(run_id):
        return next(
            (workflow for workflow, value in workflow_ids.items() if value == run_id),
            "",
        )

    if args[:2] == ["auth", "status"]:
        pass
    elif args[:2] == ["workflow", "run"]:
        workflow = args[2]
        if workflow == dispatch_failure:
            sys.exit(1)
    elif args[:2] == ["run", "list"]:
        workflow = option_value("--workflow")
        run_ids = [str(run_id) for run_id in previous_runs.get(workflow, [])]
        logged = [
            json.loads(line)
            for line in Path(os.environ["RELEASE_TEST_LOG"]).read_text().splitlines()
        ]
        was_dispatched = any(
            command[:3] == ["gh", "workflow", "run"] and command[3] == workflow
            for command in logged
        )
        if was_dispatched and workflow != missing_workflow:
            run_ids.append(workflow_ids.get(workflow, ""))
        print("\n".join(run_id for run_id in run_ids if run_id))
    elif args[:2] == ["run", "view"]:
        run_id = args[2]
        workflow = workflow_for_run(run_id)
        details = {
            "headSha": "same-commit",
            "headBranch": os.environ.get("RELEASE_CURRENT_BRANCH", "main"),
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": outcomes.get(workflow, "success"),
            "url": "https://github.com/RedHatProductSecurity/ai-guardian/actions/runs/" + run_id,
        }
        details.update(metadata_overrides.get(workflow, {}))
        if "--jq" in args and "@tsv" in args[args.index("--jq") + 1]:
            print("\t".join(str(details[key]) for key in (
                "headSha", "headBranch", "event", "status", "conclusion", "url"
            )))
        else:
            raise AssertionError(args)
    elif args[:2] == ["run", "watch"]:
        workflow = workflow_for_run(args[2])
        if outcomes.get(workflow, "success") != "success":
            sys.exit(1)
    else:
        raise AssertionError(args)
elif program == "python3":
    if Path(args[0]).name == "resolve_release_merge.py":
        conflicts = json.loads(os.environ["RELEASE_MERGE_CONFLICTS"])
        known = {
            "CHANGELOG.md",
            ".wolf/STATUS.md",
            "pyproject.toml",
            "src/ai_guardian/__init__.py",
            "rust/openshell-middleware/Cargo.toml",
            "rust/openshell-middleware/Cargo.lock",
        }
        unexpected = sorted(set(conflicts) - known)
        if unexpected:
            print(
                "Release merge conflict resolution stopped: Unexpected merge "
                "conflicts require manual resolution: " + ", ".join(unexpected),
                file=sys.stderr,
            )
            sys.exit(1)
    elif Path(args[0]).name == "release_helper.py":
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
elif program == "curl":
    print(os.environ["RTD_TEST_CURL_RESPONSE"])
elif program == "pip":
    sys.exit(int(os.environ.get("PIP_TEST_EXIT", "0")))
elif program == "git-cliff":
    print("### Added\n- Generated changelog entry")
elif program not in ("curl", "git-cliff", "sleep"):
    raise AssertionError(program)
"""
    for name in ("git", "gh", "python3", "pip", "curl", "git-cliff", "sleep"):
        path = binaries / name
        path.write_text(fake, encoding="utf-8")
        path.chmod(0o755)

    def run(
        *flags,
        outcome="success",
        pip_exit=0,
        workflow_outcomes=None,
        missing_workflow="",
        dispatch_failure="",
        run_metadata=None,
        empty_changelog=False,
        release_type="minor",
        docs_response="200 https://ai-guardian.readthedocs.io/en/v1.2.3/",
        current_branch="main",
        head_sha="same-commit",
        main_sha="same-commit",
        remote_branch_sha="same-commit",
        merge_conflicts=(),
    ):
        if empty_changelog:
            (tmp_path / "CHANGELOG.md").write_text("## [Unreleased]\n")
        result = subprocess.run(
            ["bash", str(script), "--skip-cursor", *flags, release_type],
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
                "RELEASE_CURRENT_BRANCH": current_branch,
                "RELEASE_HEAD_SHA": head_sha,
                "RELEASE_MAIN_SHA": main_sha,
                "RELEASE_REMOTE_BRANCH_SHA": remote_branch_sha,
                "RELEASE_WORKFLOW_RUN_IDS": json.dumps(WORKFLOW_RUN_IDS),
                "RELEASE_WORKFLOW_OUTCOMES": json.dumps(workflow_outcomes or {}),
                "RELEASE_PREEXISTING_RUNS": json.dumps(
                    {workflow: ["90"] for workflow in REQUIRED_CI_WORKFLOWS}
                ),
                "RELEASE_MISSING_WORKFLOW": missing_workflow,
                "RELEASE_DISPATCH_FAILURE": dispatch_failure,
                "RELEASE_RUN_METADATA": json.dumps(run_metadata or {}),
                "RELEASE_MERGE_CONFLICTS": json.dumps(list(merge_conflicts)),
                "RTD_TEST_CURL_RESPONSE": docs_response,
            },
        )
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        return result, commands

    return run


def _workflow_dispatches(commands):
    return [command for command in commands if command[:2] == ["gh", "workflow"]]


def _option_value(command, name):
    for index, argument in enumerate(command):
        if argument == name and index + 1 < len(command):
            return command[index + 1]
        if argument.startswith(name + "="):
            return argument.split("=", 1)[1]
    return ""


def _release_mutations(commands):
    mutations = []
    for command in commands:
        git_args = command[1:] if command[0] == "git" else []
        while git_args[:1] == ["-c"]:
            git_args = git_args[2:]
        if git_args and git_args[0] in (
            "add",
            "checkout",
            "commit",
            "merge",
            "pull",
            "push",
            "tag",
        ):
            if git_args[:2] != ["tag", "--list"]:
                mutations.append(command)
        if command[0] == "python3" and any(
            operation in command for operation in ("update-version", "update-changelog")
        ):
            mutations.append(command)
    return mutations


def test_release_script_defaults_to_non_mutating_preview(release_sandbox):
    result, commands = release_sandbox()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Release mode: preview only" in result.stdout
    assert "GitHub CI will run" in result.stdout
    assert [command[3] for command in _workflow_dispatches(commands)] == list(
        REQUIRED_CI_WORKFLOWS
    )
    assert not _release_mutations(commands)
    assert not any(command[:2] == ["pip", "install"] for command in commands)


def test_preview_does_not_generate_an_empty_changelog(release_sandbox):
    result, commands = release_sandbox("--dry-run", empty_changelog=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(command[0] == "git-cliff" for command in commands)
    assert not _release_mutations(commands)


def test_ci_failure_does_not_generate_changelog_before_gate(release_sandbox):
    result, commands = release_sandbox(
        "--execute",
        workflow_outcomes={"release-readiness.yml": "failure"},
        empty_changelog=True,
    )

    assert result.returncode == 1
    assert not any(command[0] == "git-cliff" for command in commands)
    assert not _release_mutations(commands)


def test_patch_release_from_main_is_rejected_before_ci_or_mutation(release_sandbox):
    result, commands = release_sandbox("--execute", release_type="patch")

    assert result.returncode == 1
    assert "Patch releases must run from the matching stable branch release-1.2" in (
        result.stderr
    )
    assert not _workflow_dispatches(commands)
    assert not _release_mutations(commands)


def test_patch_release_rejects_a_different_release_branch(release_sandbox):
    result, commands = release_sandbox(
        "--execute", release_type="patch", current_branch="release-1.1"
    )

    assert result.returncode == 1
    assert "does not match the release target release-1.2" in result.stderr
    assert not _workflow_dispatches(commands)
    assert not _release_mutations(commands)


def test_patch_release_rejects_a_diverged_local_stable_branch(release_sandbox):
    result, commands = release_sandbox(
        "--execute",
        release_type="patch",
        current_branch="release-1.2",
        remote_branch_sha="remote-commit",
    )

    assert result.returncode == 1
    assert "not synchronized with origin/release-1.2" in result.stderr
    assert not _workflow_dispatches(commands)
    assert not _release_mutations(commands)


def test_patch_release_uses_matching_synchronized_stable_branch(release_sandbox):
    result, commands = release_sandbox(
        "--execute", release_type="patch", current_branch="release-1.2"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert [
        _option_value(command, "--ref") for command in _workflow_dispatches(commands)
    ] == ["release-1.2"] * len(REQUIRED_CI_WORKFLOWS)
    assert not any(command[:3] == ["git", "merge", "main"] for command in commands)


def test_dispatch_failure_still_starts_and_awaits_other_required_workflows(
    release_sandbox,
):
    result, commands = release_sandbox("--execute", dispatch_failure="lint.yml")

    assert result.returncode == 1
    assert "Lint (dispatch failed)" in result.stderr
    assert [command[3] for command in _workflow_dispatches(commands)] == list(
        REQUIRED_CI_WORKFLOWS
    )
    assert (
        len([command for command in commands if command[:3] == ["gh", "run", "watch"]])
        == len(REQUIRED_CI_WORKFLOWS) - 1
    )
    assert not _release_mutations(commands)


@pytest.mark.parametrize(
    "flags",
    [(), ("--dry-run",), ("--execute",)],
    ids=["default-preview", "explicit-preview", "execute"],
)
def test_release_script_dispatches_and_awaits_required_ci_in_every_mode(
    flags, release_sandbox
):
    result, commands = release_sandbox(*flags)

    assert result.returncode == 0, result.stdout + result.stderr
    dispatches = _workflow_dispatches(commands)
    assert dispatches == [
        ["gh", "workflow", "run", workflow, "--ref", "main"]
        for workflow in REQUIRED_CI_WORKFLOWS[:3]
    ] + [
        [
            "gh",
            "workflow",
            "run",
            "integration-tests.yml",
            "--ref",
            "main",
            "-f",
            "release_validation=true",
        ]
    ]

    watched_runs = [
        command[3] for command in commands if command[:3] == ["gh", "run", "watch"]
    ]
    assert watched_runs == [
        WORKFLOW_RUN_IDS[workflow] for workflow in REQUIRED_CI_WORKFLOWS
    ]
    assert all(
        command[4] == "--exit-status"
        for command in commands
        if command[:3] == ["gh", "run", "watch"]
    )
    assert all(
        "--commit" in command
        and command[command.index("--commit") + 1] == "same-commit"
        and "--branch" in command
        and command[command.index("--branch") + 1] == "main"
        and "--event" in command
        and command[command.index("--event") + 1] == "workflow_dispatch"
        for command in commands
        if command[:3] == ["gh", "run", "list"]
        and _option_value(command, "--workflow") in REQUIRED_CI_WORKFLOWS
    )

    final_watch = max(
        i for i, command in enumerate(commands) if command[:3] == ["gh", "run", "watch"]
    )
    mutations = [
        i
        for i, command in enumerate(commands)
        if command in _release_mutations(commands)
    ]
    if flags == ("--execute",):
        assert mutations and min(mutations) > final_watch
    else:
        assert not mutations


@pytest.mark.parametrize("failed_workflow", REQUIRED_CI_WORKFLOWS)
@pytest.mark.parametrize(
    "flags",
    [("--dry-run",), ("--execute",)],
    ids=["preview", "execute"],
)
def test_failed_required_ci_blocks_release_mutations(
    failed_workflow, flags, release_sandbox
):
    result, commands = release_sandbox(
        *flags, workflow_outcomes={failed_workflow: "failure"}
    )

    assert result.returncode == 1
    assert "Required CI validation failed or was incomplete" in result.stderr
    failed_label = {
        "release-readiness.yml": "Release Readiness",
        "test.yml": "Tests",
        "lint.yml": "Lint",
        "integration-tests.yml": "Integration Tests",
    }[failed_workflow]
    assert f"{failed_label} did not succeed" in result.stdout
    assert [command[3] for command in _workflow_dispatches(commands)] == list(
        REQUIRED_CI_WORKFLOWS
    )
    assert len(
        [command for command in commands if command[:3] == ["gh", "run", "watch"]]
    ) == len(REQUIRED_CI_WORKFLOWS)
    assert not _release_mutations(commands)


def test_missing_required_ci_run_blocks_release_mutations(release_sandbox):
    result, commands = release_sandbox(
        "--execute", missing_workflow="integration-tests.yml"
    )

    assert result.returncode == 1
    assert "missing or ambiguous run" in result.stderr
    assert [command[3] for command in _workflow_dispatches(commands)] == list(
        REQUIRED_CI_WORKFLOWS
    )
    assert (
        len([command for command in commands if command[:3] == ["gh", "run", "watch"]])
        == len(REQUIRED_CI_WORKFLOWS) - 1
    )
    assert not _release_mutations(commands)


def test_mismatched_ci_source_commit_blocks_release_mutations(release_sandbox):
    result, commands = release_sandbox(
        "--execute", run_metadata={"lint.yml": {"headSha": "different-commit"}}
    )

    assert result.returncode == 1
    assert "does not match the requested source ref, commit, and event" in result.stdout
    assert "source verification failed" in result.stderr
    assert not _release_mutations(commands)


def test_release_script_rejects_conflicting_execution_modes():
    result = subprocess.run(
        ["bash", str(RELEASE_SCRIPT), "--execute", "--dry-run", "patch"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--dry-run and --execute cannot be combined" in result.stderr


def test_release_script_announces_after_verification_before_dev_bump(release_sandbox):
    result, commands = release_sandbox("--execute")
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


def test_release_script_verifies_the_exact_versioned_docs_url(release_sandbox):
    result, _commands = release_sandbox("--execute")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "Read the Docs: https://ai-guardian.readthedocs.io/en/v1.2.3/ available (HTTP 200)"
        in result.stdout
    )
    assert "Docs verification: verified (HTTP 200; release version served)" in (
        result.stdout
    )


@pytest.mark.parametrize(
    ("docs_response", "expected_message"),
    [
        (
            "404 https://ai-guardian.readthedocs.io/en/v1.2.3/",
            "did not serve v1.2.3 as an active release version (HTTP 404)",
        ),
        (
            "200 https://ai-guardian.readthedocs.io/en/latest/",
            "a redirect to another version does not verify v1.2.3",
        ),
        (
            "503 https://ai-guardian.readthedocs.io/en/v1.2.3/",
            "did not make v1.2.3 available after retries (HTTP 503)",
        ),
    ],
    ids=["inactive-version", "redirected-to-latest", "service-unavailable"],
)
def test_failed_docs_verification_is_actionable_and_fails_after_mergeback(
    docs_response, expected_message, release_sandbox
):
    result, commands = release_sandbox("--execute", docs_response=docs_response)

    assert result.returncode == 1
    assert expected_message in result.stdout
    assert "Do not rerun scripts/release.sh" in result.stdout
    assert "Docs verification: failed" in result.stdout
    assert "Main branch updated" in result.stdout
    assert "Release publication and main-branch merge-back completed" in result.stdout
    assert ["git", "push", "origin", "main"] in commands


def test_post_release_merge_waits_for_resolution_before_committing(release_sandbox):
    result, commands = release_sandbox("--execute")

    assert result.returncode == 0, result.stdout + result.stderr
    merge = next(
        command for command in commands if command[0] == "git" and "merge" in command
    )
    merge_commit = next(
        index
        for index, command in enumerate(commands)
        if command[:2] == ["git", "commit"]
        and command[-1] == "Merge release-1.2 into main"
    )
    assert merge[:3] == ["git", "-c", "merge.conflictStyle=merge"]
    assert "--no-commit" in merge
    assert "--no-ff" in merge
    assert merge_commit > commands.index(merge)


def test_post_release_merge_resolves_known_metadata_conflicts(release_sandbox):
    conflicts = ("CHANGELOG.md", "pyproject.toml", ".wolf/STATUS.md")
    result, commands = release_sandbox("--execute", merge_conflicts=conflicts)

    assert result.returncode == 0, result.stdout + result.stderr
    resolver = next(
        command
        for command in commands
        if command[0] == "python3"
        and Path(command[1]).name == "resolve_release_merge.py"
    )
    assert _option_value(resolver, "--release-version") == "1.2.3"
    assert _option_value(resolver, "--next-dev-version") == "1.3.0-dev"
    assert any(
        command[:2] == ["git", "commit"]
        and command[-1] == "Merge release-1.2 into main"
        for command in commands
    )


def test_unexpected_post_release_conflict_stops_before_merge_commit(release_sandbox):
    result, commands = release_sandbox(
        "--execute", merge_conflicts=("src/ai_guardian/unexpected.py",)
    )

    assert result.returncode == 1
    assert "Unexpected merge conflicts require manual resolution" in result.stderr
    assert not any(
        command[:2] == ["git", "commit"]
        and command[-1] == "Merge release-1.2 into main"
        for command in commands
    )
    assert not any(
        command[:2] == ["git", "push"] and command[-1] == "main" for command in commands
    )


@pytest.mark.parametrize("outcome", ["unavailable", "uncertain", "empty", "invalid"])
def test_release_script_failed_announcement_is_not_success_or_republication(
    outcome, release_sandbox
):
    result, commands = release_sandbox("--execute", outcome=outcome, pip_exit=1)
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
    assert [command[3] for command in _workflow_dispatches(commands)] == list(
        REQUIRED_CI_WORKFLOWS
    )
    assert not any(command[0] in ("pip", "curl") for command in commands)
    assert not _release_mutations(commands)
