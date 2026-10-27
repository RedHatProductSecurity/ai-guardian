"""Collection-only wire format and protected desktop import of daemon diagnostics.

Never transport a bundle reference, destination, consent or connection object.
Only complete sanitized text files cross the boundary, not an extractable archive.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ai_guardian.reporting import support_bundle as bundles
from ai_guardian.reporting.cli_diagnostics import _read_config
from ai_guardian.reporting.github_support import public_text, support_context
from ai_guardian.ui.support_review import diagnostic_sort_key

MAX_WIRE_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MAX_FILES = 256
PROVENANCE_FILE = "daemon-source.json"
_NAME = re.compile(
    r"(?:[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}\.(?:json|jsonl|log)|"
    r"projects/project-[0-9]{3}\.json|\.ai-guardian/ai-guardian\.json)\Z"
)


class SupportCollectionError(ValueError):
    """A fixed, credential-free collection or validation failure."""


def source_label(name: str, runtime: str) -> str:
    """Only display-safe fields, never endpoint URLs or transport metadata."""
    clean, _ = public_text(str(name)[:200])
    clean = " ".join(clean.split())
    kind = (
        runtime
        if runtime in {"local", "container", "kubernetes", "manual", "ssh", "openshell"}
        else "daemon"
    )
    return f"{clean or 'Selected daemon'} ({kind})"


def _valid_name(name) -> bool:
    return (
        isinstance(name, str)
        and _NAME.fullmatch(name) is not None
        and name not in {"support-context.json", "support-message.json"}
        and name.split("/")[-1].split(".")[0].upper()
        not in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10)),
        }
    )


def _structured_text(value) -> str:
    """Bound pretty-print expansion of a compact, potentially hostile JSON file."""
    chunks = []
    size = 0
    for chunk in json.JSONEncoder(indent=2).iterencode(value):
        size += len(chunk.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise SupportCollectionError(
                "Complete diagnostic text exceeds the transfer limit."
            )
        chunks.append(chunk)
    return "".join(chunks)


def _sanitize_file(name: str, text: str) -> tuple[str, int]:
    count = 0
    if not name.endswith(".log"):
        value, count = bundles._sanitize_config(json.loads(text))
        text = _structured_text(value)
    text, redactions = public_text(text)
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise SupportCollectionError(
            "Sanitized diagnostic text exceeds the transfer limit."
        )
    return text, count + redactions


def collect_diagnostics(
    name: str, project_paths: list[Path], *, daemon_version: str | None = None
) -> dict:
    """Run entirely in the source daemon's environment, without delivery setup."""
    from ai_guardian import __version__
    from ai_guardian.config.utils import get_config_dir, get_state_dir

    prepared = bundles.prepare_bundle(
        _collection_only=True, _project_config_paths=project_paths
    )
    root = Path(prepared["temp_path"])
    try:
        files: list[dict] = []
        total = 0
        omissions = []
        for item in prepared["files"]:
            filename = item["name"]
            if not _valid_name(filename):
                raise SupportCollectionError("Unsupported diagnostic file.")
            text = _read_config(root / filename, MAX_FILE_BYTES).decode("utf-8")
            # Collector metadata is untrusted text too (project paths, notices).
            text, count = _sanitize_file(filename, text)
            raw = text.encode("utf-8")
            total += len(raw)
            if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES - 1:
                raise SupportCollectionError(
                    "Complete diagnostics exceed the transfer limit."
                )
            note, _ = public_text(item.get("note", ""))
            if item.get("collection_status") == "omitted":
                omissions.append(
                    f"{filename}: source configuration omitted; view its status file"
                )
            files.append(
                {
                    "name": filename,
                    "data": base64.b64encode(raw).decode("ascii"),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "redactions": item.get("redactions", 0) + count,
                    "truncated": bool(item.get("truncated")),
                    "note": note[:1000],
                }
            )
        available = {item["name"] for item in files}
        expected = {
            "ai-guardian.json",
            "doctor.json",
            "smoke-test.json",
            "metrics.json",
            "system-info.json",
            "violations.jsonl",
            "ai-guardian.log",
            "session_state.json",
        }
        omissions.extend(
            [
                f"{item}: unavailable or no applicable records in the source environment"
                for item in sorted(expected - available)
            ]
        )
        if not any(item.startswith("cli-") for item in available):
            omissions.append(
                "CLI configurations: none available in the source environment"
            )
        for index in range(len(project_paths)):
            filename = f"projects/project-{index + 1:03d}.json"
            if filename not in available:
                omissions.append(
                    f"{filename}: source project configuration unavailable"
                )
        if not project_paths:
            omissions.append(
                "Project configuration: no daemon-observed project configuration"
            )
        provenance, provenance_count = public_text(
            json.dumps(
                {
                    "daemon_name": name,
                    "version": daemon_version or __version__,
                    "collector_version": __version__,
                    "working_directory": str(Path.cwd()),
                    "config_root": str(get_config_dir()),
                    "state_root": str(get_state_dir()),
                    "project_configurations": [str(path) for path in project_paths],
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "omissions": omissions,
                    "window": "Logs and violations: last 12 hours; only logs may be excerpted",
                },
                indent=2,
            )
        )
        raw = provenance.encode("utf-8")
        files.append(
            {
                "name": PROVENANCE_FILE,
                "data": base64.b64encode(raw).decode("ascii"),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "redactions": provenance_count,
                "truncated": False,
                "note": "Source environment and explicit collection omissions",
            }
        )
        payload = {"schema": 1, "files": files}
        validate_diagnostics(payload)
        return payload
    finally:
        shutil.rmtree(root)  # Only the private directory created by this collection.


def validate_diagnostics(payload: dict) -> list[tuple[dict, str]]:
    """Validate the whole envelope before creating any local diagnostic files."""
    try:
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "files"}
            or type(payload["schema"]) is not int
            or payload["schema"] != 1
            or not isinstance(payload["files"], list)
            or not 1 <= len(payload["files"]) <= MAX_FILES
            or len(json.dumps(payload).encode("utf-8")) > MAX_WIRE_BYTES
        ):
            raise ValueError
        result = []
        names: set[str] = set()
        total = 0
        for item in payload["files"]:
            if not isinstance(item, dict) or set(item) != {
                "name",
                "data",
                "sha256",
                "redactions",
                "truncated",
                "note",
            }:
                raise ValueError
            name = item["name"]
            if (
                not _valid_name(name)
                or name.casefold() in names
                or not isinstance(item["data"], str)
                or len(item["data"]) > (MAX_FILE_BYTES + 2) // 3 * 4
                or not isinstance(item["sha256"], str)
                or type(item["redactions"]) is not int
                or not 0 <= item["redactions"] <= 10**9
                or type(item["truncated"]) is not bool
                or (item["truncated"] and not name.endswith(".log"))
                or not isinstance(item["note"], str)
                or len(item["note"]) > 1000
            ):
                raise ValueError
            names.add(name.casefold())
            raw = base64.b64decode(item["data"], validate=True)
            total += len(raw)
            if (
                len(raw) > MAX_FILE_BYTES
                or total > MAX_TOTAL_BYTES
                or hashlib.sha256(raw).hexdigest() != item["sha256"]
            ):
                raise ValueError
            text = raw.decode("utf-8")
            if not name.endswith(".log"):
                json.loads(text)  # Complete structured files, never cropped JSON.
            result.append((item, text))
        if PROVENANCE_FILE not in names:
            raise ValueError
        return result
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise SupportCollectionError(
            "The daemon diagnostics are malformed, unsafe or exceed the transfer limit. Nothing was sent."
        ) from None


def import_diagnostics(payload: dict, source: str) -> dict:
    """Register a new desktop-owned bundle; remote data cannot set its destination."""
    checked = validate_diagnostics(payload)
    config = bundles._get_support_config()
    destination = config.get("export_destination") or "github-discussions"
    root = Path(tempfile.mkdtemp(prefix="ai-guardian-support-"))
    try:
        (root / ".ai-read-deny").touch(mode=0o600)
        files: list[dict] = []
        for item, text in checked:
            name = item["name"]
            # Resanitize on receipt; metadata is never an instruction to the UI.
            text, count = _sanitize_file(name, text)
            if not name.endswith(".log"):
                json.loads(text)
            if name == PROVENANCE_FILE:
                provenance = json.loads(text)
                if not isinstance(provenance, dict):
                    raise ValueError("Invalid source provenance")
                provenance["selected_source"] = source
                text = _structured_text(provenance)
            path = root / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # A newly allocated directory plus exclusive files: no archive links,
            # absolute paths, traversal, hidden receipt replacement or overwrite.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
            note, _ = public_text(item["note"])
            files.append(
                {
                    "name": name,
                    "redactions": item["redactions"] + count,
                    "sanitized": item["redactions"] + count > 0,
                    "truncated": item["truncated"],
                    "note": note,
                    "size_bytes": path.stat().st_size,
                }
            )
        if destination == "github-discussions":
            context, _ = support_context(
                "", "", config.get("github_category", "bug-reports"), draft=True
            )
            bundles._write_text(
                root / "support-context.json", json.dumps(context, indent=2)
            )
            files.append(
                {
                    "name": "support-context.json",
                    "redactions": 0,
                    "sanitized": False,
                    "note": "Desktop support proposal",
                }
            )
        files.sort(key=lambda item: diagnostic_sort_key(item["name"]))
        bundle_id = f"support-{uuid.uuid4().hex}"
        info = {
            "temp_path": str(root),
            "destination": destination,
            "created": datetime.now(timezone.utc).isoformat(),
            "ttl_minutes": config.get("bundle_ttl_minutes", 30),
            "files": files,
            "source": source,
        }
        if not bundles._persist_bundle_ref(bundle_id, info):
            raise ValueError("Desktop review reference unavailable")
        bundles._active_bundles[bundle_id] = info
        return {"bundle_id": bundle_id, **info}
    except Exception:
        shutil.rmtree(root)  # Only this new import; never remove an existing bundle.
        raise SupportCollectionError(
            "The daemon diagnostics could not be safely prepared for desktop review. Nothing was sent."
        ) from None
