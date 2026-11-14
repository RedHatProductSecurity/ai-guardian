"""Best-effort replacement of the public notebook's finalized release export.

Uses only the optional, audited external CLI; never imports its auth libraries.
Pending intent/receipts live in Git metadata, not in release configuration.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

NOTEBOOK_ID = "9b78ebca-d327-4df7-8f2e-64e518f2ddcb"
EXPORT_NAME = "notebooklm-export.md"
STATE_NAME = "ai-guardian-notebooklm-refresh.json"
SUPPORTED_VERSION = "0.16.2"
STABLE_VERSION = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
PROFILE_NAME = r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}"


class RefreshError(RuntimeError):
    """Refresh is failed/unconfirmed; do not replay publication or an upload."""


def _source_id(value: Any) -> bool:
    """Require full UUIDs, never CLI aliases, prefixes, or option-like IDs."""
    return isinstance(value, str) and bool(
        re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value)
    )


def _failure_reason(output: str) -> str:
    """Classify diagnostics without returning provider text, accounts, or content."""
    text = output.lower()
    for fragments, reason in (
        (
            ("source limit", "too many sources", "maximum number of sources"),
            "source limit reached",
        ),
        (("quota", "rate limit", "resource_exhausted"), "quota or rate limit reached"),
        (
            ("expired", "credentials", "authentication", "unauthenticated"),
            "authentication missing or expired",
        ),
        (
            ("permission", "forbidden", "not found", "inaccessible"),
            "notebook or source access unavailable",
        ),
        (("processing", "indexing"), "source processing failed"),
        (("network", "connection", "dns"), "network request failed"),
    ):
        if any(fragment in text for fragment in fragments):
            return reason
    return "CLI command failed"


@contextmanager
def _locked(state_file: Path) -> Iterator[None]:
    """Serialize worktrees with an OS lock that is released even after a crash."""
    with state_file.with_suffix(".lock").open("a+b") as lock:
        try:
            if sys.platform == "win32":
                import msvcrt

                lock.seek(0)
                if not lock.read(1):
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RefreshError(
                "Another NotebookLM refresh holds the state lock; retry serially."
            ) from error
        # Closing the handle releases the lock on both platforms.
        yield


class NotebookLMRefresher:
    """Replace one exact-title source, retaining the old one until verification."""

    def __init__(
        self, version: str, repo_path: str, verify_publication: Callable[[], None]
    ):
        if not re.fullmatch(STABLE_VERSION, version):
            raise ValueError(
                "Specify a stable release version X.Y.Z (no v prefix or suffix)"
            )
        self.version = version
        self.title = f"AI Guardian v{version}"
        self.repo_path = repo_path
        self.verify_publication = verify_publication
        self.nlm = ""
        self.profile = ""

    def _command(self, args: list[str], operation: str, timeout: int = 60) -> str:
        try:
            result = subprocess.run(
                [self.nlm, *args],
                cwd=self.repo_path,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                check=False,
                env={
                    **os.environ,
                    "NLM_NO_COLOR": "1",
                    "NO_COLOR": "1",
                    "COLUMNS": "160",
                    # Source commands may otherwise attempt browser-based auth
                    # recovery after a previously valid session expires.
                    "NOTEBOOKLM_DISABLE_HEADLESS_REFRESH": "1",
                },
            )
        except subprocess.TimeoutExpired as error:
            raise RefreshError(f"{operation} timed out") from error
        except (OSError, UnicodeError) as error:
            raise RefreshError(
                f"{operation} unavailable or returned invalid output"
            ) from error
        if result.returncode:
            reason = _failure_reason(result.stdout + "\n" + result.stderr)
            raise RefreshError(f"{operation}: {reason} (exit {result.returncode})")
        return result.stdout

    def _json(self, args: list[str], operation: str, timeout: int = 60) -> Any:
        output = self._command(args, operation, timeout)
        try:
            return json.loads(output)
        except ValueError as error:
            raise RefreshError(f"{operation} returned malformed JSON") from error

    def _git(self, args: list[str], *, binary: bool = False) -> Any:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repo_path,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=not binary,
                timeout=30,
                check=False,
            )
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
            raise RefreshError(
                "Release export or Git metadata could not be read"
            ) from error
        if result.returncode:
            raise RefreshError(
                "Tagged release export or Git metadata is missing/unavailable"
            )
        return result.stdout

    def _prerequisites(self) -> str | None:
        self.nlm = shutil.which("nlm") or ""
        if not self.nlm:
            return "skipped (nlm not installed; optional refresh only)"
        try:
            version = self._command(["--version"], "CLI version check")
            help_text = self._command(["--help"], "CLI identity check")
        except RefreshError:
            return "skipped (nlm unavailable/incompatible; requires notebooklm-mcp-cli 0.16.2)"
        if (
            re.findall(r"^nlm version ([^\r\n]+)$", version, re.MULTILINE)
            != [SUPPORTED_VERSION]
            or "NotebookLM Tools - Unified CLI for Google NotebookLM" not in help_text
        ):
            return "skipped (incompatible nlm; requires notebooklm-mcp-cli 0.16.2)"
        try:
            authentication = self._command(["login", "--check"], "authentication check")
        except RefreshError as error:
            return f"skipped ({error}; no login attempted)"
        profiles = re.findall(r"^\s*Profile: ([^\r\n]+)$", authentication, re.MULTILINE)
        if (
            "Authentication valid!" not in authentication
            or len(profiles) != 1
            or not re.fullmatch(PROFILE_NAME, profiles[0])
        ):
            return "skipped (authentication could not be verified; no login attempted)"
        # Pin the current checked profile for this invocation without switching
        # defaults. Explicit selection also prevents environment-cookie override.
        self.profile = profiles[0]
        return None

    def _sources(self) -> list[dict[str, Any]]:
        sources = self._json(
            ["source", "list", NOTEBOOK_ID, "--json", "--profile", self.profile],
            "source discovery",
        )
        if not isinstance(sources, list):
            raise RefreshError(
                "Source discovery returned an incomplete list; not treated as absence"
            )
        seen = set()
        for entry in sources:
            if (
                not isinstance(entry, dict)
                or not _source_id(entry.get("id"))
                or entry["id"] in seen
                or not isinstance(entry.get("title"), str)
                or not isinstance(entry.get("type"), str)
                or (
                    entry.get("status") is not None and type(entry["status"]) is not int
                )
            ):
                raise RefreshError(
                    "Source discovery returned malformed/duplicate source metadata"
                )
            seen.add(entry["id"])
        return sources

    @staticmethod
    def _exports(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        matches = {
            entry["id"]: entry for entry in sources if entry["title"] == EXPORT_NAME
        }
        if any(
            entry["type"] not in ("uploaded_file", "pasted_text")
            or entry.get("url") not in (None, "")
            for entry in matches.values()
        ):
            raise RefreshError(
                "Export identity is ambiguous: matching title is not a local-file export"
            )
        return matches

    @staticmethod
    def _load(state_file: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise RefreshError(
                "Refresh state is unreadable or malformed; preserve it for review"
            ) from error
        if (
            not isinstance(data, dict)
            or not {
                "schema",
                "notebook",
                "version",
                "digest",
                "profile",
                "baseline",
                "old_id",
                "new_id",
                "phase",
            }.issubset(data)
            or data.get("schema") != 1
            or data.get("notebook") != NOTEBOOK_ID
            or not isinstance(data.get("version"), str)
            or not re.fullmatch(STABLE_VERSION, data["version"])
            or not isinstance(data.get("digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", data["digest"])
            or not isinstance(data.get("profile"), str)
            or not re.fullmatch(PROFILE_NAME, data["profile"])
            or not isinstance(data.get("baseline"), list)
            or not all(_source_id(value) for value in data["baseline"])
            or len(set(data["baseline"])) != len(data["baseline"])
            or (
                data.get("old_id") is not None
                and data["old_id"] not in data["baseline"]
            )
            or (data.get("new_id") is not None and not _source_id(data["new_id"]))
            or data.get("phase")
            not in (
                "upload_intent",
                "uploaded",
                "delete_intent",
                "rename_pending",
                "complete",
            )
            or (data["phase"] != "upload_intent" and data.get("new_id") is None)
            or (data["phase"] == "upload_intent" and data.get("new_id") is not None)
            or data.get("new_id") in data["baseline"]
        ):
            raise RefreshError(
                "Refresh state has invalid identity metadata; preserve it for review"
            )
        return data

    @staticmethod
    def _save(state_file: Path, state: dict[str, Any]) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=state_file.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                json.dump(state, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, state_file)
        except OSError as error:
            raise RefreshError(
                "Refresh state could not be saved; no further mutations attempted"
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _finish(self, state_file: Path, state: dict[str, Any]) -> str:
        matches = self._exports(self._sources())
        old_id, new_id = state["old_id"], state["new_id"]
        new = matches.get(new_id)
        if not new or new.get("status") != 2:
            raise RefreshError(
                "Uploaded export processing is not confirmed ready; existing source preserved"
            )
        if set(matches) - {old_id, new_id}:
            raise RefreshError(
                "Export identity became ambiguous; no deletion attempted"
            )
        if old_id in matches:
            state["phase"] = "delete_intent"
            self._save(state_file, state)
            receipt = self._json(
                [
                    "source",
                    "delete",
                    old_id,
                    "--confirm",
                    "--json",
                    "--profile",
                    self.profile,
                ],
                "superseded-source deletion",
            )
            if (
                not isinstance(receipt, dict)
                or receipt.get("status") != "success"
                or receipt.get("deleted_source_ids") != [old_id]
                or receipt.get("deleted_count") != 1
            ):
                raise RefreshError(
                    "Deletion receipt is unconfirmed; retry refresh only to reconcile the saved IDs"
                )
            matches = self._exports(self._sources())
        if set(matches) != {new_id} or matches[new_id].get("status") != 2:
            raise RefreshError(
                "Replacement could not be verified; retry refresh only, not publication"
            )
        state["phase"] = "rename_pending"
        self._save(state_file, state)
        self._rename_notebook()
        state["phase"] = "complete"
        self._save(state_file, state)
        return f"updated ({self.title}; one processed export and notebook title verified; unrelated sources untouched)"

    def _notebook_title(self) -> str:
        details = self._json(
            ["notebook", "get", NOTEBOOK_ID, "--json", "--profile", self.profile],
            "notebook title verification",
        )
        if (
            not isinstance(details, dict)
            or details.get("notebook_id") != NOTEBOOK_ID
            or not isinstance(details.get("title"), str)
            or not details["title"]
        ):
            raise RefreshError(
                "Notebook title lookup returned incomplete or mismatched notebook identity"
            )
        return details["title"]

    def _rename_notebook(self) -> None:
        # Read before retrying an uncertain rename. Setting a title is idempotent,
        # but a lost reply may already have applied the exact requested value.
        if self._notebook_title() == self.title:
            return
        # This audited subcommand has no --json; discard its human-readable
        # output and independently verify the same notebook's JSON metadata.
        self._command(
            ["notebook", "rename", NOTEBOOK_ID, self.title, "--profile", self.profile],
            "notebook rename",
        )
        if self._notebook_title() != self.title:
            raise RefreshError(
                "Notebook title change is unconfirmed; retry refresh only, without re-uploading"
            )

    def refresh(self, dry_run: bool = False) -> str:
        if dry_run:
            return (
                f"skipped (dry-run; would refresh {EXPORT_NAME} from v{self.version} in notebook {NOTEBOOK_ID}; "
                f"upload, verify processing, delete only the superseded export, then rename to {self.title})"
            )
        skipped = self._prerequisites()
        if skipped:
            return skipped
        self.verify_publication()
        export = self._git(["show", f"v{self.version}:docs/{EXPORT_NAME}"], binary=True)
        if not export or not export.strip():
            raise RefreshError(
                "Tagged release export is empty; existing source preserved"
            )
        digest = hashlib.sha256(export).hexdigest()
        common = Path(self._git(["rev-parse", "--git-common-dir"]).strip())
        if not common.is_absolute():
            common = Path(self.repo_path) / common
        state_file = common / STATE_NAME
        with _locked(state_file):
            state = self._load(state_file)
            identity = {
                "version": self.version,
                "digest": digest,
                "profile": self.profile,
            }
            if state and state["phase"] != "complete":
                if any(state[key] != value for key, value in identity.items()):
                    raise RefreshError(
                        "A different pending refresh must be reconciled first; no new upload"
                    )
                if state["new_id"] is None:
                    raise RefreshError(
                        "Previous upload outcome is unconfirmed; inspect the notebook and saved state. "
                        "No automatic re-upload or deletion; do not rerun publication."
                    )
                return self._finish(state_file, state)

            if state:
                if tuple(map(int, self.version.split("."))) < tuple(
                    map(int, state["version"].split("."))
                ):
                    raise RefreshError(
                        "A newer release was already refreshed; notebook will not be downgraded"
                    )
                if state["version"] == self.version and state["digest"] != digest:
                    raise RefreshError(
                        "Tagged release export changed since the saved refresh; preserve state for review"
                    )

            sources = self._sources()
            matches = self._exports(sources)
            if len(matches) > 1:
                raise RefreshError(
                    "Export identity is ambiguous: multiple exact-title sources; no changes"
                )
            if (
                state
                and all(state[key] == value for key, value in identity.items())
                and state["new_id"] in matches
            ):
                return self._finish(state_file, state)

            state = {
                "schema": 1,
                "notebook": NOTEBOOK_ID,
                **identity,
                "baseline": [entry["id"] for entry in sources],
                "old_id": next(iter(matches), None),
                "new_id": None,
                "phase": "upload_intent",
            }
            # Persist intent BEFORE calling a mutating CLI. An interrupted or
            # malformed upload reply must not authorize a second blind upload.
            self._save(state_file, state)
            with tempfile.TemporaryDirectory(
                prefix="ai-guardian-notebooklm-"
            ) as temporary:
                upload = Path(temporary) / EXPORT_NAME
                upload.write_bytes(export)
                receipt = self._json(
                    [
                        "source",
                        "add",
                        NOTEBOOK_ID,
                        "--file",
                        str(upload),
                        "--wait",
                        "--wait-timeout",
                        "600",
                        "--json",
                        "--profile",
                        self.profile,
                    ],
                    "export upload/processing",
                    timeout=720,
                )
            if (
                not isinstance(receipt, dict)
                or receipt.get("source_type") != "file"
                or receipt.get("title") != EXPORT_NAME
                or not _source_id(receipt.get("source_id"))
                or receipt["source_id"] in state["baseline"]
            ):
                raise RefreshError(
                    "Upload receipt is unconfirmed; existing source preserved; no automatic re-upload"
                )
            state["new_id"] = receipt["source_id"]
            state["phase"] = "uploaded"
            self._save(state_file, state)
            return self._finish(state_file, state)
