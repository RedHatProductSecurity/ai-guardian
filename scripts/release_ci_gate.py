#!/usr/bin/env python3
"""Dispatch, persist, validate, and resume the release CI gate."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

STATE_VERSION = 1
RELEASE_EVENT = "workflow_dispatch"


@dataclass(frozen=True)
class Workflow:
    filename: str
    label: str
    release_validation: bool = False

    def inputs(self, attempt_id: str) -> dict[str, str]:
        values = {"release_attempt_id": attempt_id}
        if self.release_validation:
            values["release_validation"] = "true"
        return values

    def run_name(self, attempt_id: str) -> str:
        suffix = f" [release-attempt:{attempt_id}"
        if self.release_validation:
            suffix += "; release_validation=true"
        return f"{self.label}{suffix}]"


WORKFLOWS = (
    Workflow("release-readiness.yml", "Release Readiness"),
    Workflow("test.yml", "Tests"),
    Workflow("lint.yml", "Lint"),
    Workflow("integration-tests.yml", "Integration Tests", True),
)


class GateError(Exception):
    """A release CI gate failure with a user-safe explanation."""


class GitHubError(GateError):
    """A GitHub CLI operation failed or returned invalid data."""


class StaleRunError(GateError):
    """A run's source or workflow-input metadata does not match the attempt."""


class AmbiguousRunError(GateError):
    """More than one run could belong to the saved attempt."""


class GitHub:
    """Small, JSON-only adapter around the GitHub CLI."""

    def _run(self, arguments: list[str], *, watch: bool = False) -> str:
        try:
            result = subprocess.run(
                ["gh", *arguments],
                check=False,
                capture_output=not watch,
                text=True,
            )
        except OSError as exc:
            raise GitHubError(
                "Could not start the GitHub CLI for required CI."
            ) from exc
        if result.returncode != 0:
            raise GitHubError("GitHub CLI operation for required CI failed.")
        return result.stdout or ""

    def run_ids(self, workflow: Workflow, branch: str, source_sha: str) -> list[str]:
        output = self._run(
            [
                "run",
                "list",
                "--workflow",
                workflow.filename,
                "--branch",
                branch,
                "--commit",
                source_sha,
                "--event",
                RELEASE_EVENT,
                "--limit",
                "100",
                "--json",
                "databaseId",
                "--jq",
                ".[].databaseId",
            ]
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

    def dispatch(self, workflow: Workflow, branch: str, attempt_id: str) -> None:
        arguments = ["workflow", "run", workflow.filename, "--ref", branch]
        for name, value in workflow.inputs(attempt_id).items():
            arguments.extend(("-f", f"{name}={value}"))
        self._run(arguments)

    def inspect(self, run_id: str) -> dict[str, object]:
        output = self._run(
            [
                "run",
                "view",
                run_id,
                "--json",
                "workflowName,headSha,headBranch,event,status,conclusion,url,displayTitle",
            ]
        )
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise GitHubError(
                "GitHub returned invalid run metadata for required CI."
            ) from exc
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned invalid run metadata for required CI.")
        return data

    def watch(self, run_id: str) -> None:
        self._run(["run", "watch", run_id, "--exit-status"], watch=True)


def _identity(
    release_type: str,
    release_version: str,
    release_mode: str,
    source_ref: str,
    source_sha: str,
) -> dict[str, str]:
    return {
        "release_type": release_type,
        "release_version": release_version,
        "release_mode": release_mode,
        "source_ref": source_ref,
        "source_sha": source_sha,
        "event": RELEASE_EVENT,
    }


def _save_state(path: Path, state: dict[str, object]) -> None:
    """Atomically persist release state outside the worktree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            # intentionally silent — preserve the original state-write exception
            pass
        raise


def _load_state(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as stream:
            state = json.load(stream)
    except FileNotFoundError as exc:
        raise GateError(
            "No saved CI attempt exists for --resume. Start a normal release invocation."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(
            "The saved release CI attempt is unreadable; refusing to dispatch workflows."
        ) from exc
    if not isinstance(state, dict) or state.get("schema_version") != STATE_VERSION:
        raise GateError(
            "The saved release CI attempt has an unsupported format; refusing to resume."
        )
    return state


def _validate_identity(
    state: dict[str, object], expected: dict[str, str], *, resume: bool
) -> None:
    same_identity = state.get("identity") == expected
    if resume and not same_identity:
        raise GateError(
            "Saved CI attempt identity does not match this release type, version, "
            "mode, branch, or source commit. Start a normal release invocation "
            "for a new attempt."
        )
    status = state.get("status")
    if not resume and status == "release_in_progress":
        raise GateError(
            "A release attempt is already in progress; refusing to replace its CI state."
        )
    if resume and status != "active":
        explanations = {
            "failed": "the saved attempt has a failed workflow",
            "ambiguous": "the saved attempt has ambiguous workflow runs",
            "stale": "a saved workflow run no longer matches its source or inputs",
            "ci_succeeded": "all required workflows already succeeded",
            "release_in_progress": "release actions already started",
            "release_completed": "the release attempt already completed",
        }
        reason = explanations.get(str(status), f"its state is {status!r}")
        raise GateError(f"Cannot resume this CI attempt because {reason}.")
    replay_blocked = status in {"active", "release_completed"} or (
        status == "ci_succeeded" and expected["release_mode"] == "execute"
    )
    if not resume and same_identity and replay_blocked:
        guidance = (
            "Use --resume for an active attempt."
            if status == "active"
            else "Use a new source commit or release version for a new attempt."
        )
        raise GateError(
            f"A saved attempt for this exact release identity is already {status}; "
            f"refusing to dispatch a replacement. {guidance}"
        )


def _new_state(
    identity: dict[str, str],
    attempt_id: str,
    prior_run_ids: dict[str, list[str]],
) -> dict[str, object]:
    workflows: dict[str, object] = {}
    for workflow in WORKFLOWS:
        workflows[workflow.filename] = {
            "label": workflow.label,
            "inputs": workflow.inputs(attempt_id),
            "prior_run_ids": prior_run_ids[workflow.filename],
            "dispatch_state": "not_dispatched",
            "run_id": None,
            "status": None,
            "conclusion": None,
            "url": None,
        }
    return {
        "schema_version": STATE_VERSION,
        "status": "active",
        "identity": identity,
        "attempt_id": attempt_id,
        "workflows": workflows,
    }


def _workflow_state(state: dict[str, object], workflow: Workflow) -> dict[str, object]:
    workflows = state.get("workflows")
    if not isinstance(workflows, dict):
        raise GateError(
            "Saved release CI workflow state is invalid; refusing to resume."
        )
    workflow_state = workflows.get(workflow.filename)
    if not isinstance(workflow_state, dict):
        raise GateError(
            f"Saved release CI state is missing {workflow.label}; refusing to resume."
        )
    attempt_id = state.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise GateError(
            "Saved release CI attempt has no identifier; refusing to resume."
        )
    if workflow_state.get("inputs") != workflow.inputs(attempt_id):
        raise GateError(
            f"Saved {workflow.label} inputs do not match the expected release inputs."
        )
    return workflow_state


def _validate_run(
    metadata: dict[str, object],
    workflow: Workflow,
    identity: dict[str, str],
    attempt_id: str,
) -> None:
    expected = {
        "workflowName": workflow.label,
        "headSha": identity["source_sha"],
        "headBranch": identity["source_ref"],
        "event": RELEASE_EVENT,
        "displayTitle": workflow.run_name(attempt_id),
    }
    mismatches = [
        field for field, value in expected.items() if metadata.get(field) != value
    ]
    if mismatches:
        raise StaleRunError(
            f"{workflow.label} run failed source or workflow-input verification "
            f"({', '.join(mismatches)})."
        )


def _inspect_validated_run(
    github: GitHub,
    run_id: str,
    workflow: Workflow,
    identity: dict[str, str],
    attempt_id: str,
) -> dict[str, object]:
    metadata = github.inspect(run_id)
    _validate_run(metadata, workflow, identity, attempt_id)
    return metadata


def _candidate_runs(
    github: GitHub,
    state: dict[str, object],
    workflow: Workflow,
    identity: dict[str, str],
) -> list[tuple[str, dict[str, object]]]:
    workflow_state = _workflow_state(state, workflow)
    prior_ids = workflow_state.get("prior_run_ids")
    if not isinstance(prior_ids, list) or not all(
        isinstance(run_id, str) for run_id in prior_ids
    ):
        raise GateError(f"Saved {workflow.label} run baseline is invalid.")
    attempt_id = str(state["attempt_id"])
    marker = f"[release-attempt:{attempt_id}"
    candidates: list[tuple[str, dict[str, object]]] = []
    for run_id in github.run_ids(
        workflow, identity["source_ref"], identity["source_sha"]
    ):
        if run_id in prior_ids:
            continue
        metadata = github.inspect(run_id)
        title = metadata.get("displayTitle")
        if not isinstance(title, str) or marker not in title:
            continue
        _validate_run(metadata, workflow, identity, attempt_id)
        candidates.append((run_id, metadata))
    return candidates


def _resolve_run_id(
    path: Path,
    state: dict[str, object],
    workflow: Workflow,
    identity: dict[str, str],
    github: GitHub,
    *,
    poll_attempts: int,
    poll_interval: float,
    sleep: Callable[[float], None],
) -> dict[str, object]:
    workflow_state = _workflow_state(state, workflow)
    saved_id = workflow_state.get("run_id")
    if isinstance(saved_id, str) and saved_id:
        metadata = _inspect_validated_run(
            github, saved_id, workflow, identity, str(state["attempt_id"])
        )
        candidates = _candidate_runs(github, state, workflow, identity)
        if len(candidates) > 1:
            raise AmbiguousRunError(
                f"Found multiple runs for this {workflow.label} attempt; refusing to choose."
            )
        if not candidates or candidates[0][0] != saved_id:
            raise AmbiguousRunError(
                f"Saved {workflow.label} run {saved_id} is not the unique run for this attempt."
            )
        return metadata

    dispatch_state = workflow_state.get("dispatch_state")
    for attempt in range(poll_attempts):
        candidates = _candidate_runs(github, state, workflow, identity)
        if len(candidates) > 1:
            state["status"] = "ambiguous"
            _save_state(path, state)
            raise AmbiguousRunError(
                f"Found multiple runs for this {workflow.label} attempt; refusing to choose."
            )
        if candidates:
            run_id, metadata = candidates[0]
            workflow_state["run_id"] = run_id
            workflow_state["status"] = metadata.get("status")
            workflow_state["conclusion"] = metadata.get("conclusion")
            workflow_state["url"] = metadata.get("url")
            workflow_state["dispatch_state"] = "dispatched"
            _save_state(path, state)
            return metadata
        if dispatch_state == "not_dispatched":
            break
        if attempt + 1 < poll_attempts:
            sleep(poll_interval)

    if dispatch_state == "dispatching":
        raise GateError(
            f"The dispatch outcome for {workflow.label} is uncertain and no matching "
            "run is visible. Refusing to dispatch a duplicate; retry --resume after "
            "the run appears, or start a fresh release invocation."
        )
    raise GateError(
        f"No uniquely matching {workflow.label} run appeared for the saved attempt. "
        "Required CI remains incomplete; retry with --resume to check again."
    )


def _dispatch_missing(
    path: Path,
    state: dict[str, object],
    workflow: Workflow,
    identity: dict[str, str],
    github: GitHub,
) -> None:
    workflow_state = _workflow_state(state, workflow)
    # A state marked not_dispatched is safe to launch only if no run carrying
    # this attempt's unique ID already exists.
    candidates = _candidate_runs(github, state, workflow, identity)
    if candidates:
        state["status"] = "ambiguous"
        _save_state(path, state)
        raise AmbiguousRunError(
            f"A {workflow.label} run exists although the saved attempt says it was "
            "not dispatched; refusing to associate or duplicate it."
        )

    workflow_state["dispatch_state"] = "dispatching"
    _save_state(path, state)
    try:
        github.dispatch(workflow, identity["source_ref"], str(state["attempt_id"]))
    except GitHubError:
        # A failed CLI response may still follow a server-side dispatch. Keep the
        # dispatching marker so resume searches by attempt ID instead of retrying.
        print(f"⚠ Could not confirm dispatch for {workflow.label}")
        return
    workflow_state["dispatch_state"] = "dispatched"
    _save_state(path, state)
    print(f"✓ Started {workflow.label}")


def run_gate(
    *,
    state_path: Path,
    release_type: str,
    release_version: str,
    release_mode: str,
    source_ref: str,
    source_sha: str,
    resume: bool,
    github: GitHub | None = None,
    poll_attempts: int = 30,
    poll_interval: float = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run the blocking required-CI gate, raising GateError on unsafe state."""
    api = github or GitHub()
    identity = _identity(
        release_type, release_version, release_mode, source_ref, source_sha
    )
    if resume:
        state = _load_state(state_path)
        _validate_identity(state, identity, resume=True)
        print(f"Resuming saved release CI attempt {state['attempt_id']}")
    else:
        if state_path.exists():
            old_state = _load_state(state_path)
            _validate_identity(old_state, identity, resume=False)
        prior_ids: dict[str, list[str]] = {}
        for workflow in WORKFLOWS:
            prior_ids[workflow.filename] = api.run_ids(workflow, source_ref, source_sha)
        attempt_id = uuid.uuid4().hex
        state = _new_state(identity, attempt_id, prior_ids)
        _save_state(state_path, state)

    try:
        for workflow in WORKFLOWS:
            workflow_state = _workflow_state(state, workflow)
            if workflow_state.get("dispatch_state") == "not_dispatched":
                _dispatch_missing(state_path, state, workflow, identity, api)
            elif workflow_state.get("dispatch_state") not in {
                "dispatching",
                "dispatched",
            }:
                state["status"] = "stale"
                _save_state(state_path, state)
                raise GateError(
                    f"Saved {workflow.label} dispatch state is invalid; refusing to resume."
                )
    except StaleRunError:
        state["status"] = "stale"
        _save_state(state_path, state)
        raise

    # Resolve and persist every run ID before waiting on any workflow.
    try:
        for workflow in WORKFLOWS:
            metadata = _resolve_run_id(
                state_path,
                state,
                workflow,
                identity,
                api,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                sleep=sleep,
            )
            workflow_state = _workflow_state(state, workflow)
            run_id = workflow_state.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise GateError(f"No saved run ID for {workflow.label}.")
            _validate_run(metadata, workflow, identity, str(state["attempt_id"]))
            print(f"✓ Matched {workflow.label} run {run_id}")
    except StaleRunError:
        state["status"] = "stale"
        _save_state(state_path, state)
        raise
    except AmbiguousRunError:
        state["status"] = "ambiguous"
        _save_state(state_path, state)
        raise

    failures: list[str] = []
    incomplete: list[str] = []
    for workflow in WORKFLOWS:
        workflow_state = _workflow_state(state, workflow)
        run_id = str(workflow_state["run_id"])
        try:
            metadata = _inspect_validated_run(
                api, run_id, workflow, identity, str(state["attempt_id"])
            )
        except StaleRunError as exc:
            state["status"] = "stale"
            _save_state(state_path, state)
            raise GateError(
                f"{workflow.label} run {run_id} failed revalidation: {exc}"
            ) from exc

        status = metadata.get("status")
        conclusion = metadata.get("conclusion")
        url = metadata.get("url")
        workflow_state["status"] = status
        workflow_state["conclusion"] = conclusion
        workflow_state["url"] = url
        _save_state(state_path, state)

        if status != "completed":
            print(f"Waiting for {workflow.label} (run {run_id})...")
            try:
                api.watch(run_id)
            except GitHubError:
                # Re-inspect below: a watcher can fail while the run itself finishes.
                pass
            try:
                metadata = _inspect_validated_run(
                    api, run_id, workflow, identity, str(state["attempt_id"])
                )
            except StaleRunError as exc:
                state["status"] = "stale"
                _save_state(state_path, state)
                raise GateError(
                    f"{workflow.label} run {run_id} failed final revalidation: {exc}"
                ) from exc
            status = metadata.get("status")
            conclusion = metadata.get("conclusion")
            url = metadata.get("url")
            workflow_state["status"] = status
            workflow_state["conclusion"] = conclusion
            workflow_state["url"] = url
            _save_state(state_path, state)

        if status != "completed":
            incomplete.append(f"{workflow.label} (still {status or 'unknown'})")
        elif conclusion != "success":
            failures.append(
                f"{workflow.label} (status completed, conclusion {conclusion or 'none'})"
            )
            print(
                f"⚠ {workflow.label} did not succeed (status: completed, "
                f"conclusion: {conclusion or 'none'})"
            )
        else:
            print(f"✓ {workflow.label} passed" + (f": {url}" if url else ""))

    if failures:
        state["status"] = "failed"
        _save_state(state_path, state)
        print("Required CI validation failed or was incomplete:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        raise GateError(
            "Release changes were not made. Resolve the required CI results and "
            "start a normal fresh release invocation."
        )
    if incomplete:
        _save_state(state_path, state)
        print("Required CI validation failed or was incomplete:", file=sys.stderr)
        for item in incomplete:
            print(f"  - {item}", file=sys.stderr)
        raise GateError(
            "Release changes were not made. Retry this exact attempt with --resume."
        )

    state["status"] = "ci_succeeded"
    _save_state(state_path, state)
    print(f"✓ All required CI workflows passed for {source_ref} ({source_sha})")


def update_release_lifecycle(
    state_path: Path,
    identity: dict[str, str],
    target_status: str,
) -> None:
    state = _load_state(state_path)
    if state.get("identity") != identity:
        raise GateError(
            "Saved release CI identity changed; refusing to update its lifecycle."
        )
    expected_previous = {
        "release_in_progress": "ci_succeeded",
        "release_completed": "release_in_progress",
    }[target_status]
    if state.get("status") != expected_previous:
        raise GateError(
            f"Cannot mark release state {target_status}; expected {expected_previous}."
        )
    state["status"] = target_status
    _save_state(state_path, state)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument(
        "--release-type", choices=("minor", "patch", "major"), required=True
    )
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--release-mode", choices=("preview", "execute"), required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--poll-attempts", type=int, default=30, help=argparse.SUPPRESS)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--resume", action="store_true")
    actions.add_argument("--mark-release-started", action="store_true")
    actions.add_argument("--mark-release-completed", action="store_true")
    return parser


@contextlib.contextmanager
def _state_lock(state_path: Path):
    """Serialize CI gate and lifecycle operations for this repository."""
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - release.sh is POSIX-only
            pass
        else:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise GateError(
                    "Another release CI operation is active for this repository."
                ) from exc
        yield


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    identity = _identity(
        arguments.release_type,
        arguments.release_version,
        arguments.release_mode,
        arguments.source_ref,
        arguments.source_sha,
    )
    try:
        with _state_lock(arguments.state_file):
            if arguments.mark_release_started:
                update_release_lifecycle(
                    arguments.state_file, identity, "release_in_progress"
                )
            elif arguments.mark_release_completed:
                update_release_lifecycle(
                    arguments.state_file, identity, "release_completed"
                )
            else:
                run_gate(
                    state_path=arguments.state_file,
                    release_type=arguments.release_type,
                    release_version=arguments.release_version,
                    release_mode=arguments.release_mode,
                    source_ref=arguments.source_ref,
                    source_sha=arguments.source_sha,
                    resume=arguments.resume,
                    poll_attempts=max(1, arguments.poll_attempts),
                )
    except GateError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "✗ Interrupted while awaiting required CI. The saved attempt can be "
            "checked with --resume.",
            file=sys.stderr,
        )
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
