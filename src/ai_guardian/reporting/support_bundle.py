#!/usr/bin/env python3
"""
Support Bundle — sanitized export for troubleshooting.

Two-step process:
1. prepare() — creates sanitized bundle in temp dir for user review
2. send() — sends approved bundle to preconfigured destination

Issue #477
"""

import json
import logging
import os
import platform
import re
import shutil
import smtplib
import stat
import subprocess
import tempfile
import uuid
import webbrowser
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ai_guardian.reporting.cli_diagnostics import collect_cli_configs
from ai_guardian.ui.support_review import (
    MAX_PREVIEW_BYTES,
    diagnostic_sort_key,
    is_log_file,
    truncate_text,
)

logger = logging.getLogger(__name__)

_active_bundles: Dict[str, Dict[str, Any]] = {}
CANCELLED_MESSAGE = "Support cancelled. Nothing was sent; prepared files remain local."


def _get_support_config() -> Dict:
    """Load support config from ai-guardian.json."""
    from ai_guardian.config.utils import get_config_dir

    config_path = get_config_dir() / "ai-guardian.json"
    if not config_path.exists():
        config_path = Path.cwd() / ".ai-guardian.json"
    if not config_path.exists():
        return {
            "export_destination": "github-discussions",
            "github_category": "bug-reports",
        }
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        support = dict(config.get("support") or {})
        support["export_destination"] = (
            support.get("export_destination") or "github-discussions"
        )
        return support
    except (OSError, ValueError, TypeError, AttributeError):
        logger.warning(
            "Support configuration could not be loaded; using the default support channel"
        )
        return {}


def _sanitize_config(config: Dict) -> tuple:
    """Sanitize config by redacting sensitive values. Returns (sanitized, redaction_count)."""
    import copy

    sanitized = copy.deepcopy(config)
    redactions = 0

    sensitive_keys = {
        "token",
        "api_key",
        "password",
        "secret",
        "auth_token",
        "token_env",
        "url",
        "remote_config_url",
    }

    def _redact(obj, path=""):
        nonlocal redactions
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if key.startswith("_comment"):
                    del obj[key]
                    continue
                if any(s in key.lower() for s in sensitive_keys):
                    if isinstance(obj[key], str) and obj[key]:
                        obj[key] = "[REDACTED]"
                        redactions += 1
                else:
                    _redact(obj[key], f"{path}.{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _redact(item, f"{path}[{i}]")

    _redact(sanitized)
    return sanitized, redactions


def _sanitize_violations(violations: List[Dict]) -> tuple:
    """Sanitize violation entries. Returns (sanitized_list, redaction_count)."""
    import copy

    sanitized = []
    redactions = 0

    for v in violations:
        entry = copy.deepcopy(v)
        ctx = entry.get("context", {})

        if "file_path" in ctx and ctx["file_path"]:
            parts = Path(ctx["file_path"]).parts
            if len(parts) > 2:
                ctx["file_path"] = str(Path("...") / Path(*parts[-2:]))
                redactions += 1

        if "content_preview" in ctx:
            del ctx["content_preview"]
            redactions += 1
        if "matched_pattern" in ctx:
            del ctx["matched_pattern"]
            redactions += 1

        entry["context"] = ctx
        sanitized.append(entry)

    return sanitized, redactions


def _get_system_info() -> Dict:
    """Collect non-sensitive system information."""
    import platform
    from ai_guardian import __version__

    return {
        "ai_guardian_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "os": platform.system(),
        "architecture": platform.machine(),
    }


def _get_sanitized_log() -> tuple:
    """Collect bounded, sanitized records from the last twelve hours only."""
    from ai_guardian.config.utils import get_state_dir

    log_path = get_state_dir() / "ai-guardian.log"
    if not log_path.exists():
        return "", 0

    try:
        fd = os.open(
            log_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            attributes = os.fstat(stream.fileno())
            if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
                return "", 0
            truncated = attributes.st_size > MAX_PREVIEW_BYTES
            if truncated:
                stream.seek(-MAX_PREVIEW_BYTES, os.SEEK_END)
            raw = stream.read(MAX_PREVIEW_BYTES)
        if truncated:
            # A tail starts inside a record: discard its partial first line,
            # including partial credentials, then wait for a timestamped record.
            raw = raw.partition(b"\n")[2]
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=12)
        recent = []
        include = False
        for line in raw.decode("utf-8", errors="replace").splitlines(keepends=True):
            match = re.match(
                r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?",
                line,
            )
            if match:
                try:
                    timestamp = datetime.fromisoformat(
                        match.group().replace(",", ".").replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                    include = cutoff <= timestamp <= now
                except ValueError:
                    include = False
            if include:
                recent.append(line)
        text = "".join(recent)
        if not text:
            return "", 0

        from ai_guardian.scanners.sanitizer import sanitize_text

        result = sanitize_text(text)
        redactions = result.get("stats", {}).get("total", 0)
        text = result["sanitized_text"]
        return (
            truncate_text(
                text, "ai-guardian.log", MAX_PREVIEW_BYTES, truncated=truncated
            )[0],
            redactions,
        )
    except Exception:
        logger.warning("Recent support log could not be safely collected")
        return "", 0


def _get_recent_support_violations() -> List[Dict]:
    """Read every complete violation in the last twelve hours, with no count cap."""
    from ai_guardian.config.utils import get_state_dir

    path = get_state_dir() / "violations.jsonl"
    if not path.exists():
        return []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=12)
    records = []
    invalid = False
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        attributes = os.fstat(stream.fileno())
        if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
            raise ValueError("Unsupported violation source")
        for line in stream:
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    raise ValueError("Invalid violation record")
                timestamp = datetime.fromisoformat(
                    entry["timestamp"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                if cutoff <= timestamp <= now:
                    records.append(entry)
            except (ValueError, KeyError, TypeError, AttributeError):
                invalid = True
    if invalid:
        logger.warning("Invalid support violation records or timestamps were omitted")
    return records[::-1]  # Match the logger's newest-first review order.


def prepare_bundle(
    *,
    include_log: bool = True,
    include_violations: bool = True,
    output_path: Optional[str] = None,
    title: str = "",
    description: str = "",
    category: Optional[str] = None,
    export_destination: Optional[str] = None,
) -> Dict[str, Any]:
    """Prepare a sanitized support bundle for user review.

    Args:
        include_log: Include sanitized ai-guardian.log records from the last 12 hours.
        include_violations: Include complete sanitized violation records from the last 12 hours.
        output_path: If provided, copy bundle files to this directory.
        export_destination: Internal tray override for a new report; saved settings
            and previously prepared bundles are not modified.

    Returns dict with bundle_id, temp_path, destination, and file list.
    """
    support_config = _get_support_config()
    destination = (
        export_destination
        or support_config.get("export_destination")
        or "github-discussions"
    )
    ttl = support_config.get("bundle_ttl_minutes", 30)

    context = None
    context_redactions = 0
    if destination == "github-discussions":
        from ai_guardian.reporting.github_support import support_context

        context, context_redactions = support_context(
            title,
            description,
            (
                category
                if category is not None
                else support_config.get("github_category", "bug-reports")
            ),
            draft=True,
        )

    bundle_id = f"support-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    temp_dir = Path(tempfile.mkdtemp(prefix="ai-guardian-support-"))

    # Protect bundle from direct AI agent access
    (temp_dir / ".ai-read-deny").touch()

    files_info = []

    # 1. Config (sanitized)
    try:
        from ai_guardian.config.utils import get_config_dir

        config_path = get_config_dir() / "ai-guardian.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                raw_config = json.load(f)
            sanitized, count = _sanitize_config(raw_config)
            (temp_dir / "ai-guardian.json").write_text(json.dumps(sanitized, indent=2))
            files_info.append(
                {
                    "name": "ai-guardian.json",
                    "sanitized": count > 0,
                    "redactions": count,
                    "note": (
                        f"{count} sensitive values redacted"
                        if count
                        else "No sensitive data found"
                    ),
                }
            )
    except Exception as e:
        logger.debug("Bundle config error: %s", e)

    # 1b. Project config (sanitized) — Issue #594
    try:
        from ai_guardian.config.utils import get_project_config_path

        project_path = get_project_config_path()
        if project_path and project_path.exists():
            with open(project_path, "r") as f:
                raw_project = json.load(f)
            sanitized, count = _sanitize_config(raw_project)
            bundle_subdir = temp_dir / ".ai-guardian"
            bundle_subdir.mkdir(exist_ok=True)
            (bundle_subdir / "ai-guardian.json").write_text(
                json.dumps(sanitized, indent=2)
            )
            files_info.append(
                {
                    "name": ".ai-guardian/ai-guardian.json",
                    "sanitized": count > 0,
                    "redactions": count,
                    "note": (
                        f"Project config from {project_path} — "
                        + (
                            f"{count} sensitive values redacted"
                            if count
                            else "No sensitive data found"
                        )
                    ),
                }
            )
    except Exception as e:
        logger.debug("Bundle project config error: %s", e)

    # Individual host CLI settings/hook/MCP copies, never auth stores or chats.
    files_info.extend(collect_cli_configs(temp_dir))

    # 2. Violations (sanitized)
    if include_violations:
        try:
            violations = _get_recent_support_violations()
            sanitized, count = _sanitize_violations(violations)
            (temp_dir / "violations.jsonl").write_text(json.dumps(sanitized, indent=2))
            files_info.append(
                {
                    "name": "violations.jsonl",
                    "sanitized": count > 0,
                    "redactions": count,
                    "note": (
                        f"Last 12 hours; {count} file paths and content redacted"
                        if count
                        else "Last 12 hours; no sensitive data found"
                    ),
                }
            )
        except Exception:
            logger.warning("Recent support violations could not be safely collected")

    # 3. Metrics (aggregate only)
    try:
        from ai_guardian.reporting.metrics import MetricsComputer

        mc = MetricsComputer(since_days=30)
        metrics_report = mc.compute()
        metrics = {
            "total_violations": metrics_report.total_violations,
            "by_type": dict(metrics_report.by_type),
            "by_severity": dict(metrics_report.by_severity),
            "resolved": metrics_report.resolved_count,
            "unresolved": metrics_report.unresolved_count,
        }
        (temp_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
        files_info.append(
            {
                "name": "metrics.json",
                "sanitized": False,
                "redactions": 0,
                "note": "Aggregate stats only, no sensitive data",
            }
        )
    except Exception as e:
        logger.debug("Bundle metrics error: %s", e)

    # 4. Doctor (health check)
    try:
        from ai_guardian.doctor import Doctor

        doc = Doctor()
        doctor_report = doc.run_all()
        checks = [
            {"name": c.name, "status": c.status.value, "message": c.message}
            for c in doctor_report.checks
        ]
        (temp_dir / "doctor.json").write_text(json.dumps({"checks": checks}, indent=2))
        files_info.append(
            {
                "name": "doctor.json",
                "sanitized": False,
                "redactions": 0,
                "note": "Health check results",
            }
        )
    except Exception as e:
        logger.debug("Bundle doctor error: %s", e)

    # 4b. Smoke test (scanner canary verification)
    try:
        from ai_guardian.smoke_test import SmokeTestRunner

        runner = SmokeTestRunner()
        smoke_report = runner.run()
        smoke_data = {
            "phase1_passed": smoke_report.phase1_passed,
            "phase2_results": [
                {
                    "scanner": r.scanner_name,
                    "outcome": r.outcome.value,
                    "expected_action": r.expected_action,
                    "detected": r.actual_detected,
                    "message": r.message,
                }
                for r in smoke_report.phase2_results
            ],
        }
        (temp_dir / "smoke-test.json").write_text(json.dumps(smoke_data, indent=2))
        files_info.append(
            {
                "name": "smoke-test.json",
                "sanitized": False,
                "redactions": 0,
                "note": "Scanner canary payload verification",
            }
        )
    except Exception as e:
        logger.debug("Bundle smoke test error: %s", e)

    # 5. System info
    try:
        info = _get_system_info()
        (temp_dir / "system-info.json").write_text(json.dumps(info, indent=2))
        files_info.append(
            {
                "name": "system-info.json",
                "sanitized": False,
                "redactions": 0,
                "note": "Python version, platform, ai-guardian version",
            }
        )
    except Exception as e:
        logger.debug("Bundle system info error: %s", e)

    # 6. Recent log (sanitized, last twelve hours, bounded newest records)
    if include_log:
        try:
            log_text, count = _get_sanitized_log()
            if log_text:
                # This is sanitized content in the private, user-reviewed bundle.
                (temp_dir / "ai-guardian.log").write_text(
                    log_text, encoding="utf-8"
                )  # lgtm[py/clear-text-storage-sensitive-data]
                files_info.append(
                    {
                        "name": "ai-guardian.log",
                        "sanitized": count > 0,
                        "redactions": count,
                        "truncated": log_text.startswith("[Truncated:"),
                        "note": (
                            f"Last 12 hours, {count} items redacted"
                            if count
                            else "Last 12 hours"
                        ),
                    }
                )
        except Exception as e:
            logger.debug("Bundle log error: %s", e)

    # 7. Session state (injection tracking)
    try:
        from ai_guardian.config.utils import get_state_dir
        from ai_guardian.session_state import STATE_FILENAME

        state_path = get_state_dir() / STATE_FILENAME
        if state_path.exists():
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            (temp_dir / STATE_FILENAME).write_text(json.dumps(raw, indent=2))
            session_count = len(raw.get("sessions", {}))
            files_info.append(
                {
                    "name": STATE_FILENAME,
                    "sanitized": False,
                    "redactions": 0,
                    "note": f"Session injection state ({session_count} sessions)",
                }
            )
    except Exception as e:
        logger.debug("Bundle session state error: %s", e)

    # Public diagnostics get full text sanitization, including doctor/session
    # messages and nested config values, before the user sees the artifact.
    if context is not None:
        from ai_guardian.reporting.github_support import CONTEXT_FILE, public_text

        for file_info in files_info:
            file_path = temp_dir / file_info["name"]
            text, count = public_text(file_path.read_text(encoding="utf-8"))
            file_path.write_text(
                text, encoding="utf-8"
            )  # lgtm[py/clear-text-storage-sensitive-data]
            file_info["redactions"] += count
            file_info["sanitized"] = file_info["redactions"] > 0
        (
            temp_dir / CONTEXT_FILE
        ).write_text(  # lgtm[py/clear-text-storage-sensitive-data]
            json.dumps(context, indent=2), encoding="utf-8"
        )
        files_info.append(
            {
                "name": CONTEXT_FILE,
                "redactions": context_redactions,
                "sanitized": context_redactions > 0,
                "note": "Proposed public title, context, and category",
            }
        )

    # Only the log may be shortened. Complete configuration/structured files take
    # priority; reserve public body space by bounding the prepared log, not them.
    # Keep a small newest log excerpt even when complete files already exceed the
    # target. Sending will then fail clearly rather than silently cutting files.
    log_limit = MAX_PREVIEW_BYTES
    if context is not None:
        non_log_bytes = sum(
            (temp_dir / item["name"]).stat().st_size
            for item in files_info
            if item["name"] != CONTEXT_FILE and not is_log_file(item["name"])
        )
        log_limit = min(log_limit, max(1024, 40_000 - non_log_bytes))
    for file_info in files_info:
        path = temp_dir / file_info["name"]
        if is_log_file(file_info["name"]):
            text = path.read_text(encoding="utf-8")
            clipped, truncated = truncate_text(text, file_info["name"], log_limit)
            if truncated:
                path.write_text(clipped, encoding="utf-8")
                file_info["truncated"] = True
                file_info["original_bytes"] = len(text.encode("utf-8"))
        if file_info.get("truncated"):
            file_info["note"] = (
                file_info.get("note", "") + "; truncated to review/delivery limit"
            )
        file_info["size_bytes"] = path.stat().st_size

    files_info.sort(key=lambda item: diagnostic_sort_key(item["name"]))

    # Copy to output_path if requested. The send operation must use the SAME
    # files the user reviews, not an unrevised original copy.
    actual_output = str(temp_dir)
    if output_path:
        out = Path(output_path).expanduser().resolve()
        out.mkdir(mode=0o700, parents=True, exist_ok=True)
        (out / ".ai-read-deny").touch()
        for item in temp_dir.iterdir():
            if item.name == ".ai-read-deny":
                continue
            if item.is_dir():
                shutil.copytree(item, out / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, out / item.name)
        actual_output = str(out)

    _active_bundles[bundle_id] = {
        "temp_path": actual_output,
        "destination": destination,
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": ttl,
        "files": files_info,
        "preserve_directory": bool(output_path),
    }

    _persist_bundle_ref(bundle_id, _active_bundles[bundle_id])

    result = {
        "bundle_id": bundle_id,
        "temp_path": actual_output,
        "destination": destination,
        "files": files_info,
    }
    if output_path:
        result["output_path"] = actual_output
        shutil.rmtree(temp_dir)  # only the temporary directory created above
    if context is not None:
        from ai_guardian.reporting.github_support import (
            CATEGORIES,
            PUBLIC_WARNING,
            REPOSITORY,
        )

        result.update(
            {
                "repository": REPOSITORY,
                "category": context["category"],
                "categories": dict(CATEGORIES),
                "public_warning": PUBLIC_WARNING,
                "publication_requires_user_review": True,
            }
        )
    return result


def _persist_bundle_ref(bundle_id: str, bundle_info: Dict) -> bool:
    """Write last-prepared bundle reference to state dir for cross-process use."""
    try:
        from ai_guardian.config.utils import get_state_dir

        state_dir = get_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        ref_path = state_dir / "last-support-bundle.json"
        ref_path.write_text(
            json.dumps(
                {
                    "bundle_id": bundle_id,
                    "temp_path": bundle_info["temp_path"],
                    "destination": bundle_info["destination"],
                    "created": bundle_info["created"],
                    "ttl_minutes": bundle_info.get("ttl_minutes", 30),
                    "files": bundle_info.get("files", []),
                    "preserve_directory": bundle_info.get("preserve_directory", False),
                    "include_files": bundle_info.get("include_files"),
                },
                indent=2,
            )
        )
        return True
    except Exception:
        logger.warning("Support review reference could not be saved")
        return False


def _is_local_destination(destination: str) -> bool:
    # Match legacy transport precedence so the displayed confirmation can
    # never promise local-only behavior for a destination routed to email.
    return "@" not in destination and (
        destination.startswith("~") or Path(destination).is_absolute()
    )


def _review_file_paths(bundle: Dict) -> Dict[str, Path]:
    """List registered prepared files without reading their contents."""
    root = Path(bundle["temp_path"])
    if root.is_symlink() or not root.is_dir():
        raise ValueError("The reviewed directory is unavailable")
    known = {item["name"] for item in bundle.get("files", [])}
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Linked files cannot be sent")
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if path.name == ".ai-read-deny" or name in {
            ".github-submission.json",
            ".github-gist.json",
        }:
            continue
        if name not in known or not path.is_file() or path.stat().st_nlink > 1:
            raise ValueError("Unreviewed or unsupported files cannot be sent")
        files[name] = path
    return files


def _set_file_selection(bundle_id: str, bundle: Dict, include_files) -> None:
    """Persist inclusion choices; never delete or modify the original files."""
    known = {item["name"] for item in bundle.get("files", [])}
    if (
        not isinstance(include_files, list)
        or any(not isinstance(name, str) for name in include_files)
        or len(include_files) != len(set(include_files))
        or not set(include_files) <= known
    ):
        raise ValueError("The file selection could not be validated")
    _review_file_paths(bundle)
    selection = list(include_files)
    if not _persist_bundle_ref(bundle_id, {**bundle, "include_files": selection}):
        raise ValueError("The file selection could not be saved; nothing was sent")
    bundle["include_files"] = selection


def _review_bundle_selection(
    bundle_id: str, bundle: Dict, *, zip_path: Optional[Path] = None
) -> bool:
    """Review local-only ZIP or legacy delivery without any GitHub authentication."""
    from ai_guardian.reporting import github_support as github

    available = _review_file_paths(bundle)
    included = bundle.get("include_files")
    if included is None:
        included = [name for name in available if name == "doctor.json"]
    request = {
        "mode": "bundle",
        "request_id": uuid.uuid4().hex,
        "temp_path": bundle["temp_path"],
        "destination": (
            str(zip_path) if zip_path else _final_destination(bundle_id, bundle)
        ),
        "local_only": zip_path is not None
        or _is_local_destination(bundle["destination"]),
        "zip_export": zip_path is not None,
        "files": sorted(
            (item for item in bundle.get("files", []) if item["name"] in available),
            key=lambda item: diagnostic_sort_key(item["name"]),
        ),
        "include_files": included,
    }
    reply = github.review_dialog(request)
    if reply is None:
        return False
    if (
        reply.get("request_id") != request["request_id"]
        or reply.get("send") is not True
    ):
        raise ValueError("Unverified support review")
    selection = reply.get("include_files")
    description = reply.get("description", "")
    if not isinstance(selection, list) or not selection:
        raise ValueError("No selected files")
    if (
        not isinstance(description, str)
        or len(description.encode("utf-8")) > github.MAX_BODY_BYTES
    ):
        raise ValueError("Unsupported support message")
    message, redactions = github.public_text(description)
    if not message.strip():
        raise github.GitHubError("A support message is required.", code="context")
    _set_file_selection(bundle_id, bundle, selection)
    if not set(selection).intersection(_review_file_paths(bundle)):
        raise ValueError("No selected diagnostic files remain")
    name = "support-message.txt"
    path = Path(bundle["temp_path"]) / name
    if path.exists():
        name = f"support-message-{uuid.uuid4().hex[:8]}.txt"
        path = path.with_name(name)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(message)  # lgtm[py/clear-text-storage-sensitive-data]
    bundle["files"].append(
        {
            "name": name,
            "redactions": redactions,
            "sanitized": redactions > 0,
            "note": "User support message",
        }
    )
    _set_file_selection(bundle_id, bundle, [*selection, name])
    return True


def _send_github_or_zip(bundle_id: str, bundle: Dict) -> Dict[str, Any]:
    """Offer a local ZIP before attempting authentication or public publication."""
    from ai_guardian.config.utils import get_state_dir
    from ai_guardian.reporting import github_support as github
    from ai_guardian.reporting import github_gist

    public_started = False
    existing_gist_url = github_gist.recovery_url(bundle)
    try:
        request = {
            "mode": "delivery",
            "request_id": uuid.uuid4().hex,
            "destination": f"{github.REPOSITORY_URL}/discussions (public), or a local ZIP with no upload",
            "github_available": github.credentials_available(),
            **({"gist_url": existing_gist_url} if existing_gist_url else {}),
        }
        reply = github.review_dialog(request)
        if reply is None:
            return {
                "status": "error",
                "error_code": "cancelled",
                "message": (
                    "Support cancelled. No new files were sent; the existing Gist was not deleted."
                    if existing_gist_url
                    else CANCELLED_MESSAGE
                )
                + github_gist.uploaded_notice(existing_gist_url),
                **(
                    {"gist_url": existing_gist_url, "delivery_status": "gist_only"}
                    if existing_gist_url
                    else {}
                ),
            }
        if reply.get("request_id") != request["request_id"]:
            raise ValueError("Unverified delivery choice")
        if reply.get("delivery") == "discussion":
            if not request["github_available"]:
                raise github.GitHubError(
                    "Gist + Discussion requires authenticated GitHub credentials. Authenticate your own GitHub CLI account and reopen support, or choose Create ZIP only.",
                    code="authentication",
                )
            # Never synthesize the separate identity/content-bound public approval.
            public_started = True
            return github.send_discussion(bundle_id, bundle)
        if reply.get("delivery") != "zip":
            raise ValueError("Unsupported delivery choice")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", bundle_id):
            raise ValueError("Unsupported bundle reference")
        export_dir = (
            get_state_dir() / "support-exports" / f"{bundle_id}-{uuid.uuid4().hex[:8]}"
        )
        zip_path = export_dir / f"{bundle_id}.zip"
        if not _review_bundle_selection(bundle_id, bundle, zip_path=zip_path):
            return {
                "status": "error",
                "error_code": "cancelled",
                "message": (
                    "Support cancelled. No new files were sent; the existing Gist was not deleted."
                    if existing_gist_url
                    else CANCELLED_MESSAGE
                )
                + github_gist.uploaded_notice(existing_gist_url),
                **(
                    {"gist_url": existing_gist_url, "delivery_status": "gist_only"}
                    if existing_gist_url
                    else {}
                ),
            }
        with _outgoing_files(bundle) as outgoing:
            export_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            export_dir.mkdir(mode=0o700)
            try:
                (export_dir / ".ai-read-deny").touch()
                _zip_bundle(outgoing, bundle_id, output_path=zip_path)
            except (OSError, ValueError):
                shutil.rmtree(export_dir)  # Only this newly created, private export.
                raise
        return {
            "status": "sent",
            "delivery_status": "zip_only",
            "destination": str(zip_path),
            "zip_path": str(zip_path),
            "temp_path": bundle["temp_path"],
            **({"gist_url": existing_gist_url} if existing_gist_url else {}),
            "message": (
                f"ZIP created locally: {zip_path}\n"
                + (
                    "This ZIP export did not upload files or create a Discussion. Your earlier Gist was not deleted.\n"
                    if existing_gist_url
                    else "No files were uploaded or sent to support. No Discussion was created.\n"
                )
                + "The ZIP is not encrypted. Review it before forwarding through a support channel you choose.\n"
                "The prepared bundle remains available to 'ai-guardian support send' until it expires; its configured destination is unchanged."
            )
            + github_gist.uploaded_notice(existing_gist_url),
        }
    except github.GitHubError as exc:
        gist_url = exc.gist_url or (
            github_gist.recovery_url(bundle) if public_started else existing_gist_url
        )
        return {
            "status": "error",
            "error_code": exc.code,
            "delivery_status": (
                "uncertain"
                if exc.uncertain
                else "gist_only" if gist_url else "not_published"
            ),
            "message": str(exc) + github_gist.uploaded_notice(gist_url),
            "temp_path": bundle["temp_path"],
            **({"gist_url": gist_url} if gist_url else {}),
        }
    except (OSError, ValueError, TypeError):
        logger.warning("Support delivery choice or ZIP export could not complete")
        gist_url = (
            github_gist.recovery_url(bundle) if public_started else existing_gist_url
        )
        return {
            "status": "error",
            "error_code": "uncertain" if public_started else "files",
            "delivery_status": "uncertain" if public_started else "not_sent",
            "message": (
                "Support publication outcome is uncertain. Check the repository Discussions before retrying, and check your GitHub Gists; retain the prepared files locally."
                if public_started
                else "The support choice or ZIP export could not be completed. No new files were uploaded by this attempt; retain the prepared files locally."
            )
            + github_gist.uploaded_notice(gist_url),
            "temp_path": bundle["temp_path"],
            **({"gist_url": gist_url} if gist_url else {}),
        }


@contextmanager
def _outgoing_files(bundle: Dict):
    """Stage only selected files for legacy transports, preserving originals."""
    selection = bundle.get("include_files")
    if selection is None:
        yield Path(bundle["temp_path"])
        return
    known = {item["name"] for item in bundle.get("files", [])}
    if not isinstance(selection, list) or any(
        not isinstance(name, str) or name not in known for name in selection
    ):
        raise ValueError("The file selection could not be validated")
    files = _review_file_paths(bundle)
    selected = {name: path for name, path in files.items() if name in selection}
    if not selected:
        raise ValueError("No selected diagnostic files remain")
    with tempfile.TemporaryDirectory(prefix="ai-guardian-support-selected-") as temp:
        outgoing = Path(temp)
        (outgoing / ".ai-read-deny").touch()
        for name, source in selected.items():
            target = outgoing / name
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(
                source,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
            with os.fdopen(fd, "rb") as stream:
                attributes = os.fstat(stream.fileno())
                if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
                    raise ValueError("Only regular reviewed files can be sent")
                with target.open("xb") as output:
                    shutil.copyfileobj(stream, output)
        yield outgoing


def _final_destination(bundle_id: str, bundle: Dict) -> str:
    """Display the actual final path/recipient without allowing it to be edited."""
    destination = bundle["destination"]
    if _is_local_destination(destination):
        return str(Path(destination).expanduser() / bundle_id)
    if destination.startswith("s3://"):
        parts = destination[5:].split("/", 1)
        prefix = parts[1] if len(parts) > 1 else ""
        key = f"{prefix}/{bundle_id}".strip("/")
        return f"s3://{parts[0]}/{key}/"
    if destination.startswith("gs://"):
        parts = destination[5:].split("/", 1)
        prefix = parts[1].strip("/") if len(parts) > 1 else ""
        key = f"{prefix}/{bundle_id}".strip("/")
        return f"gs://{parts[0]}/{key}/"
    return destination


def _load_last_bundle() -> Optional[str]:
    """Load the last prepared bundle from the persisted reference.

    Returns bundle_id if found and still valid, None otherwise.
    """
    try:
        from ai_guardian.config.utils import get_state_dir

        ref_path = get_state_dir() / "last-support-bundle.json"
        if not ref_path.exists():
            return None

        with open(ref_path, "r") as f:
            ref = json.load(f)

        bundle_id = ref.get("bundle_id", "")
        temp_path = Path(ref.get("temp_path", ""))

        created = datetime.fromisoformat(ref["created"])
        age_minutes = (datetime.now(timezone.utc) - created).total_seconds() / 60
        ttl = ref.get("ttl_minutes", 30)
        if age_minutes > ttl:
            return None

        if not temp_path.is_dir():
            # Older local exports consumed the temp directory but left this
            # reference pointing at it. Recover only that exact local copy;
            # never change destinations or reset the original review lifetime.
            destination = ref.get("destination", "")
            if (
                not _is_local_destination(destination)
                or not bundle_id.startswith("support-")
                or Path(bundle_id).name != bundle_id
            ):
                return None
            temp_path = Path(destination).expanduser() / bundle_id
            if not temp_path.is_dir() or temp_path.is_symlink():
                return None
            (temp_path / ".ai-read-deny").touch()
            ref.update(temp_path=str(temp_path), preserve_directory=True)
            _persist_bundle_ref(bundle_id, ref)

        if bundle_id not in _active_bundles:
            _active_bundles[bundle_id] = ref

        return bundle_id
    except Exception as e:
        logger.debug("Failed to load last bundle: %s", e)
        return None


def _load_bundle_from_path(bundle_path: str) -> Optional[str]:
    """Register an existing bundle directory in _active_bundles.

    Returns the bundle_id, or None if the path is invalid or empty.
    """
    path = Path(bundle_path).expanduser()
    if not path.is_dir():
        return None

    files = [f for f in path.iterdir() if f.name != ".ai-read-deny"]
    if not files:
        return None

    dir_name = path.name
    if dir_name.startswith("support-") and len(dir_name) > 8:
        bundle_id = dir_name
    else:
        bundle_id = f"support-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"

    support_config = _get_support_config()
    destination = support_config.get("export_destination") or "github-discussions"

    if destination == "github-discussions":
        if path.is_symlink():
            return None
        (path / ".ai-read-deny").touch()
        files = [
            f for f in path.rglob("*") if f.is_file() and f.name != ".ai-read-deny"
        ]
    files_info = [
        {
            "name": f.relative_to(path).as_posix(),
            "sanitized": False,
            "redactions": 0,
            "note": "pre-existing",
        }
        for f in files
    ]

    _active_bundles[bundle_id] = {
        "temp_path": str(path),
        "destination": destination,
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": (
            support_config.get("bundle_ttl_minutes", 30)
            if destination == "github-discussions"
            else 1440
        ),
        "files": files_info,
        "preserve_directory": True,
    }
    return bundle_id


def _get_bundle_status() -> Dict[str, Any]:
    """Get support bundle configuration and status information."""
    _load_last_bundle()
    support_config = _get_support_config()
    destination = support_config.get("export_destination") or "github-discussions"

    if destination == "github-discussions":
        dest_type = "github-discussions"
    elif destination.startswith("s3://"):
        dest_type = "s3"
    elif destination.startswith("gs://"):
        dest_type = "gcs"
    elif destination.startswith("mailto:") or "@" in destination:
        dest_type = "email"
    elif destination:
        dest_type = "local"
    else:
        dest_type = "none"

    auth = support_config.get("auth", {})
    email_config = support_config.get("email", {})
    email_auth = email_config.get("auth", {})
    email_auth_method = email_auth.get("method", "none")

    if dest_type == "github-discussions":
        auth_method = "github-cli (verified during review)"
        auth_configured = False
    elif dest_type == "email":
        auth_method = email_auth_method
        if email_auth_method == "env":
            username_env = email_auth.get("username_env", "")
            password_env = email_auth.get("password_env", "")
            auth_configured = bool(
                username_env
                and password_env
                and os.environ.get(username_env)
                and os.environ.get(password_env)
            )
        elif email_auth_method == "inline":
            auth_configured = bool(
                email_auth.get("username") and email_auth.get("password")
            )
        else:
            auth_configured = True  # "none" means no auth needed
    else:
        auth_method = auth.get("method", "none")
        token_env = auth.get("token_env", "")
        auth_configured = bool(
            auth_method == "env" and token_env and os.environ.get(token_env)
        )

    pending = []
    for bid, info in _active_bundles.items():
        pending.append(
            {
                "bundle_id": bid,
                "created": info.get("created", ""),
                "file_count": len(info.get("files", [])),
                "temp_path": info.get("temp_path", ""),
            }
        )

    return {
        "destination": destination,
        "destination_type": dest_type,
        "auth_method": auth_method,
        "auth_configured": auth_configured,
        "bundle_ttl_minutes": support_config.get("bundle_ttl_minutes", 30),
        "pending_bundles": pending,
    }


def send_bundle(bundle_id: str) -> Dict[str, Any]:
    """Send a previously prepared support bundle to the configured destination.

    Only works with a valid bundle_id from prepare_bundle().
    """
    if bundle_id not in _active_bundles:
        return {
            "status": "error",
            "message": f"Bundle '{bundle_id}' not found or expired. Prepare a new bundle first.",
        }

    bundle = _active_bundles[bundle_id]
    temp_path = Path(bundle["temp_path"])
    destination = bundle["destination"]

    if not temp_path.exists():
        del _active_bundles[bundle_id]
        return {
            "status": "error",
            "message": "Bundle temp directory no longer exists. Prepare a new bundle.",
        }

    # Check TTL
    created = datetime.fromisoformat(bundle["created"])
    age_minutes = (datetime.now(timezone.utc) - created).total_seconds() / 60
    ttl = bundle.get("ttl_minutes", 30)
    if age_minutes > ttl:
        _cleanup_bundle(bundle_id)
        return {
            "status": "error",
            "message": f"Bundle expired ({ttl} min TTL). Prepare a new bundle.",
        }

    if destination == "github-discussions":
        # Keep artifacts and the publication receipt for the normal lifetime,
        # including on success, so retries cannot create duplicate Discussions.
        return _send_github_or_zip(bundle_id, bundle)
    try:
        with _outgoing_files(bundle) as outgoing:
            if destination.startswith("s3://"):
                result = _send_to_s3(bundle_id, outgoing, destination)
            elif destination.startswith("gs://"):
                result = _send_to_gcs(bundle_id, outgoing, destination)
            elif destination.startswith("mailto:") or "@" in destination:
                result = _send_to_email(bundle_id, outgoing, destination)
            elif _is_local_destination(destination):
                # Reuse a retained export only if it is still the selected copy.
                # A narrower selection must not falsely claim to have excluded
                # files while reusing that same, unchanged destination directory.
                source = outgoing
                if Path(
                    _final_destination(bundle_id, bundle)
                ).resolve() == temp_path.resolve() and (
                    bundle.get("include_files") is None
                    or set(_review_file_paths(bundle)) <= set(bundle["include_files"])
                ):
                    source = temp_path
                result = _send_to_local(bundle_id, source, destination)
            elif not destination:
                return {
                    "status": "error",
                    "message": "No export destination configured. Add 'support.export_destination' to ai-guardian.json.",
                }
            else:
                return {
                    "status": "error",
                    "message": "Unsupported support destination. Files remain local.",
                }
            if outgoing != temp_path and result.get("status") != "sent":
                # Selection staging is short-lived; failure guidance must point
                # to the retained review directory, not the removed staging copy.
                result = {
                    **result,
                    "temp_path": str(temp_path),
                    "message": result.get("message", "Send failed").replace(
                        str(outgoing), str(temp_path)
                    ),
                }
    except (OSError, ValueError, TypeError):
        logger.warning("Selected support files could not be prepared")
        return {
            "status": "error",
            "message": "The selected files could not be prepared. Files remain local.",
        }

    if _is_local_destination(destination):
        if result.get("status") == "sent":
            # Export is not a support submission. Retain a cross-process
            # reference to the reviewed copy instead of consuming the bundle.
            if Path(result["destination"]).resolve() != temp_path.resolve():
                _cleanup_bundle(bundle_id)
            bundle.update(temp_path=result["destination"], preserve_directory=True)
            _active_bundles[bundle_id] = bundle
            _persist_bundle_ref(bundle_id, bundle)
        return result
    if (
        result.get("status") == "sent"
        and result.get("delivery_status") != "manual_required"
    ):
        _cleanup_bundle(bundle_id)
    return result


def _send_to_local(bundle_id: str, temp_path: Path, destination: str) -> Dict:
    """Export locally without claiming support delivery or consuming review state."""
    dest = Path(destination).expanduser()
    bundle_dest = dest / bundle_id
    staging = None
    try:
        source = temp_path.resolve()
        target = bundle_dest.resolve()
        if target != source:
            if target.is_relative_to(source) or bundle_dest.exists():
                return {
                    "status": "error",
                    "message": "Local export needs a new directory outside the reviewed bundle. Existing files were not overwritten.",
                }
            dest.mkdir(mode=0o700, parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{bundle_id}-", dir=dest))
            (staging / ".ai-read-deny").touch()
            for item in temp_path.iterdir():
                if item.name == ".ai-read-deny":
                    continue
                if item.is_dir():
                    shutil.copytree(item, staging / item.name)
                else:
                    shutil.copy2(item, staging / item.name)
            staging.rename(bundle_dest)
        else:
            # A second command uses the retained copy itself. In particular,
            # do not recollect or restore files that the user deleted there.
            (bundle_dest / ".ai-read-deny").touch()
    except OSError:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        logger.warning("Local support export failed; reviewed files retained")
        return {
            "status": "error",
            "message": f"Local export failed. Reviewed files remain at: {temp_path}",
        }

    return {
        "status": "sent",
        "delivery_status": "local_only",
        "destination": str(bundle_dest),
        "message": f"Bundle exported locally to {bundle_dest}. No files were sent to support. No Discussion was created.",
    }


def _send_to_s3(bundle_id: str, temp_path: Path, destination: str) -> Dict:
    """Upload bundle to S3."""
    try:
        import boto3
    except ImportError:
        return {
            "status": "error",
            "message": f"S3 upload requires boto3 but it is not available. "
            f"Bundle files are available at: {temp_path}",
        }

    support_config = _get_support_config()
    auth = support_config.get("auth", {})

    parts = destination.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    key_prefix = f"{prefix}/{bundle_id}".strip("/")

    try:
        token_env = auth.get("token_env", "")
        session_kwargs = {}
        if token_env and os.environ.get(token_env):
            session_kwargs["aws_session_token"] = os.environ[token_env]

        s3 = boto3.client("s3", **session_kwargs)
        uploaded = 0
        for item in sorted(temp_path.rglob("*")):
            if item.name == ".ai-read-deny" or not item.is_file():
                continue
            s3.upload_file(
                str(item),
                bucket,
                f"{key_prefix}/{item.relative_to(temp_path).as_posix()}",
            )
            uploaded += 1

        return {
            "status": "sent",
            "destination": f"s3://{bucket}/{key_prefix}/",
            "message": f"{uploaded} files uploaded to S3",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"S3 upload failed: {e}. Bundle files at: {temp_path}",
        }


def _get_gcs_token_from_adc() -> Optional[str]:
    """Get GCS access token from Application Default Credentials.

    Checks GOOGLE_APPLICATION_CREDENTIALS env var first, then the default
    gcloud ADC path. Only supports authorized_user credential type
    (no external JWT library needed).
    """
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        default_path = (
            Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        )
        if default_path.exists():
            creds_path = str(default_path)

    if not creds_path or not Path(creds_path).exists():
        return None

    try:
        with open(creds_path) as f:
            creds = json.load(f)

        if creds.get("type") != "authorized_user":
            return None

        from urllib.parse import urlencode

        token_uri = "https://oauth2.googleapis.com/token"
        data = urlencode(
            {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")

        req = Request(token_uri, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urlopen(req, timeout=10) as response:
            token_response = json.loads(response.read())
            return token_response.get("access_token")
    except Exception:
        return None


def _get_gcs_token_from_gcloud() -> Optional[str]:
    """Get GCS access token via gcloud CLI fallback."""
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        token = result.stdout.strip()
        return token if token else None
    except Exception:
        return None


def _send_to_gcs(bundle_id: str, temp_path: Path, destination: str) -> Dict:
    """Upload bundle to GCS using the JSON API."""
    support_config = _get_support_config()
    auth = support_config.get("auth", {})

    parts = destination.replace("gs://", "").split("/", 1)
    bucket = parts[0]
    prefix = parts[1].strip("/") if len(parts) > 1 else ""
    object_prefix = f"{prefix}/{bundle_id}".strip("/")

    # Resolve access token: ADC → gcloud CLI → config token_env
    access_token = _get_gcs_token_from_adc()

    if not access_token:
        access_token = _get_gcs_token_from_gcloud()

    if not access_token:
        token_env = auth.get("token_env", "")
        if token_env and os.environ.get(token_env):
            access_token = os.environ[token_env]

    if not access_token:
        return {
            "status": "error",
            "message": (
                "GCS upload requires Google Cloud credentials. Either:\n"
                "  1. Run: gcloud auth application-default login\n"
                "  2. Set GOOGLE_APPLICATION_CREDENTIALS env var\n"
                "  3. Configure auth.token_env in ai-guardian.json\n"
                f"Bundle files are available at: {temp_path}"
            ),
        }

    try:
        uploaded = 0
        for item in sorted(temp_path.rglob("*")):
            if item.name == ".ai-read-deny" or not item.is_file():
                continue

            object_name = f"{object_prefix}/{item.relative_to(temp_path).as_posix()}"
            url = (
                f"https://storage.googleapis.com/upload/storage/v1/b/"
                f"{quote(bucket, safe='')}/o"
                f"?uploadType=media&name={quote(object_name, safe='')}"
            )

            file_data = item.read_bytes()
            req = Request(url, data=file_data, method="POST")
            req.add_header("Authorization", f"Bearer {access_token}")
            req.add_header("Content-Type", "application/octet-stream")
            req.add_header("Content-Length", str(len(file_data)))

            with urlopen(req, timeout=30) as response:
                response.read()
            uploaded += 1

        return {
            "status": "sent",
            "destination": f"gs://{bucket}/{object_prefix}/",
            "message": f"{uploaded} files uploaded to GCS",
        }
    except HTTPError as e:
        return {
            "status": "error",
            "message": f"GCS upload failed (HTTP {e.code}). Bundle files at: {temp_path}",
        }
    except (URLError, OSError) as e:
        return {
            "status": "error",
            "message": f"GCS upload failed: {e}. Bundle files at: {temp_path}",
        }


_SIZE_WARNING_BYTES = 10 * 1024 * 1024  # 10 MB


def _zip_bundle(
    temp_path: Path, bundle_id: str, *, output_path: Optional[Path] = None
) -> Path:
    """Zip all bundle files into a single archive.

    Returns the path to the created zip file.
    Excludes .ai-read-deny markers.
    """
    zip_path = (
        output_path
        if output_path is not None
        else temp_path.parent / f"{bundle_id}.zip"
    )
    fd = os.open(
        zip_path,
        os.O_WRONLY
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | (os.O_EXCL if output_path is not None else 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as stream:
        attributes = os.fstat(stream.fileno())
        if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
            raise ValueError("Unsupported archive target")
        stream.truncate()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(temp_path.rglob("*")):
                if item.name == ".ai-read-deny" or not item.is_file():
                    continue
                zf.write(item, item.relative_to(temp_path).as_posix())
    return zip_path


def _send_to_email(bundle_id: str, temp_path: Path, destination: str) -> Dict:
    """Send bundle via SMTP email as a zip attachment.

    Falls back to opening the system mailto: handler when no SMTP
    host is configured. Issue #932.
    """
    support_config = _get_support_config()
    email_config = support_config.get("email", {})
    smtp_host = email_config.get("smtp_host", "")

    # Determine recipient address
    to_addr = destination
    if to_addr.startswith("mailto:"):
        to_addr = to_addr[len("mailto:") :]

    # --- Fallback: no SMTP configured → system mailto: ---
    if not smtp_host:
        zip_path = _zip_bundle(temp_path, bundle_id)
        subject_prefix = email_config.get("subject_prefix", "[AI Guardian Support]")
        subject = f"{subject_prefix} Bundle {bundle_id}"

        mailto_url = (
            f"mailto:{quote(to_addr, safe='@')}"
            f"?subject={quote(subject, safe='')}"
            f"&body={quote('Please attach the zip file referenced below.', safe='')}"
        )
        try:
            webbrowser.open(mailto_url)
        except Exception:
            logger.warning("Support mail client could not be opened")

        return {
            "status": "sent",
            "delivery_status": "manual_required",
            "destination": f"mailto:{to_addr}",
            "zip_path": str(zip_path),
            "message": (
                f"No SMTP configured. Bundle zipped to {zip_path}\n"
                "Complete the email in your mail client: attach the zip and send. "
                "AI Guardian has not sent an email."
            ),
        }

    # --- SMTP send path ---
    zip_path = _zip_bundle(temp_path, bundle_id)
    zip_size = zip_path.stat().st_size
    size_warning = ""
    if zip_size > _SIZE_WARNING_BYTES:
        size_mb = zip_size / (1024 * 1024)
        size_warning = (
            f" Warning: attachment is {size_mb:.1f} MB — "
            "some SMTP servers reject messages >10 MB. "
            "Consider S3 or GCS for large bundles."
        )

    from_addr = email_config.get("from", f"ai-guardian@{platform.node()}")
    subject_prefix = email_config.get("subject_prefix", "[AI Guardian Support]")
    subject = f"{subject_prefix} Bundle {bundle_id}"

    smtp_port = email_config.get("smtp_port", 587)
    smtp_tls = email_config.get("smtp_tls", True)

    # Build MIME message
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject

    body = (
        f"AI Guardian support bundle: {bundle_id}\n\n"
        f"Attached: {zip_path.name} ({zip_size} bytes)\n"
    )
    msg.attach(MIMEText(body, "plain"))

    zip_data = zip_path.read_bytes()
    attachment = MIMEApplication(zip_data, Name=zip_path.name)
    attachment["Content-Disposition"] = f'attachment; filename="{zip_path.name}"'
    msg.attach(attachment)

    # Resolve SMTP credentials
    auth_config = email_config.get("auth", {})
    auth_method = auth_config.get("method", "none")
    username = None
    password = None

    if auth_method == "env":
        username_env = auth_config.get("username_env", "")
        password_env = auth_config.get("password_env", "")
        if username_env:
            username = os.environ.get(username_env)
        if password_env:
            password = os.environ.get(password_env)
    elif auth_method == "inline":
        username = auth_config.get("username")
        password = auth_config.get("password")
    # method == "none" → no credentials

    try:
        server: smtplib.SMTP
        if smtp_port == 465:
            # Implicit SSL (SMTPS)
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            if smtp_tls:
                server.starttls()

        try:
            if username and password:
                server.login(username, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        finally:
            server.quit()
    except smtplib.SMTPAuthenticationError as e:
        return {
            "status": "error",
            "message": (
                f"SMTP authentication failed: {e}. "
                "Check credentials in support.email.auth."
            ),
        }
    except (smtplib.SMTPException, OSError) as e:
        return {
            "status": "error",
            "message": (
                f"SMTP send failed: {e}. " f"Bundle zip available at: {zip_path}"
            ),
        }

    if zip_path.exists():
        zip_path.unlink()
    return {
        "status": "sent",
        "destination": f"mailto:{to_addr}",
        "message": f"Bundle emailed to {to_addr}.{size_warning}",
    }


def _cleanup_bundle(bundle_id: str) -> None:
    """Remove temp directory and tracking entry for a bundle."""
    if bundle_id in _active_bundles:
        temp_path = Path(_active_bundles[bundle_id]["temp_path"])
        if temp_path.exists() and not _active_bundles[bundle_id].get(
            "preserve_directory", False
        ):
            shutil.rmtree(temp_path, ignore_errors=True)
        del _active_bundles[bundle_id]


# --- CLI formatters ---


def _format_prepare_human(result: Dict[str, Any], *, sending: bool = False) -> str:
    """Format prepare_bundle result for terminal output."""
    lines = []
    path = result.get("output_path", result["temp_path"])
    lines.append(f"Support bundle prepared at: {path}")
    lines.append("")
    lines.append("Files:")
    for f in result["files"]:
        marker = (
            "omitted — source content not included"
            if f.get("collection_status") == "omitted"
            else (
                f"⚠️  {f['redactions']} items redacted"
                if f["redactions"]
                else "no automatic redactions"
            )
        )
        if f.get("truncated"):
            marker += "; truncated log excerpt"
        lines.append(f"  {f['name']:25s} — {marker}")
    lines.append("")
    lines.append("Preparation is local; nothing has been sent.")
    lines.append(
        "Delete any files you do not want to send from this directory before continuing."
    )
    lines.append(
        "Deleted files will not be collected again. Review the remaining files yourself."
    )
    lines.append("Sanitization is not a guarantee of confidentiality.")
    destination = result.get("destination", "")
    if destination and _is_local_destination(destination):
        lines.append(f"Destination: local export only — {destination}")
        lines.append("No files will be sent to support. No Discussion will be created.")
    lines.append("")
    if result.get("public_warning"):
        lines.append(result["public_warning"])
        lines.append(
            "Publication requires native user review; --yes cannot approve it."
        )
        lines.append(
            "Categories: Bug Reports (default), Q&A. Preparation has not published anything."
        )
        lines.append("")
    if not sending:
        lines.append("After reviewing the files, run:")
        lines.append("  ai-guardian support send")
    return "\n".join(lines)


def _format_send_human(result: Dict[str, Any]) -> str:
    """Format send_bundle result for terminal output."""
    if result.get("delivery_status") == "zip_only":
        return result["message"]
    if result.get("delivery_status") == "manual_required":
        return f"Manual email delivery required:\n{result['message']}"
    if result.get("delivery_status") == "local_only":
        return (
            f"✓ Exported locally: {result['destination']}\n"
            "No files were sent to support. No Discussion was created.\n"
            "This reviewed copy remains available to 'ai-guardian support send' "
            "until the bundle expires; its destination is still local export.\n"
            "For public support, select GitHub Discussions (public) in "
            "Console → MCP Settings → Support Bundle Export."
        )
    if result["status"] == "sent":
        message = result.get("message", result.get("destination", ""))
        url = result.get("discussion_url")
        if url and url not in message:
            message += f"\n{url}"
        return f"✓ Sent: {message}"
    return f"✗ {result.get('message', 'Send failed')}"


def _format_status_human(status: Dict[str, Any]) -> str:
    """Format bundle status for terminal output."""
    lines = [
        "ai-guardian support status",
        "",
        f"  Destination:     {status['destination']} ({status['destination_type']})",
        f"  Auth:            {status['auth_method']}"
        + (" ✓" if status["auth_configured"] else ""),
        f"  Bundle TTL:      {status['bundle_ttl_minutes']} minutes",
        f"  Pending bundles: {len(status['pending_bundles'])}",
    ]
    for b in status["pending_bundles"]:
        lines.append(
            f"    {b['bundle_id']} ({b['file_count']} files) at {b['temp_path']}"
        )
    return "\n".join(lines)


# --- CLI entry point ---


def support_command(args) -> int:
    """Handle the 'ai-guardian support' CLI command."""
    import sys

    cmd = getattr(args, "support_command", None)

    if cmd == "prepare":
        result = prepare_bundle(
            include_log=not getattr(args, "no_log", False),
            include_violations=not getattr(args, "no_violations", False),
            output_path=getattr(args, "output", None),
            title=getattr(args, "title", ""),
            description=getattr(args, "description", ""),
            category=getattr(args, "category", None),
        )
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
        else:
            print(_format_prepare_human(result))
        return 0

    if cmd == "send":
        bundle_id = None

        if getattr(args, "prepare", False):
            result = prepare_bundle()
            bundle_id = result["bundle_id"]
        elif getattr(args, "bundle", None):
            bundle_id = _load_bundle_from_path(args.bundle)
            if not bundle_id:
                print(
                    f"Error: '{args.bundle}' is not a valid bundle directory.",
                    file=sys.stderr,
                )
                return 1
        else:
            bundle_id = _load_last_bundle()
            if not bundle_id:
                print(
                    "Error: No unexpired prepared bundle found; it may have expired or been removed.\n"
                    "Run 'ai-guardian support prepare' first, or use "
                    "'ai-guardian support send --prepare'.\n"
                    "To reuse a retained local export, use "
                    "'ai-guardian support send --bundle <exported-directory>'.",
                    file=sys.stderr,
                )
                return 1

        is_public = (
            _active_bundles.get(bundle_id, {}).get("destination")
            == "github-discussions"
        )
        if not getattr(args, "json", False):
            summary = dict(_active_bundles[bundle_id])
            review_path = Path(summary["temp_path"])
            summary["files"] = [
                item
                for item in summary.get("files", [])
                if (review_path / item["name"]).exists()
                and (
                    summary.get("include_files") is None
                    or item["name"] in summary["include_files"]
                )
            ]
            if is_public:
                from ai_guardian.reporting.github_support import PUBLIC_WARNING

                summary["public_warning"] = PUBLIC_WARNING
            print(_format_prepare_human(summary, sending=True))
            print()

        if not is_public and not getattr(args, "yes", False):
            if not sys.stdin.isatty():
                print(
                    "Error: Cannot prompt for confirmation in non-interactive mode. "
                    "Use --yes to skip.",
                    file=sys.stderr,
                )
                return 1
            dest = _active_bundles.get(bundle_id, {}).get("destination", "")
            prompt = (
                f"Export bundle locally to {dest}? [y/N] "
                if _is_local_destination(dest)
                else f"Send bundle to {dest}? [y/N] "
            )
            answer = input(prompt).strip().lower()
            if answer not in ("y", "yes"):
                print("Cancelled.")
                return 1

        send_result = send_bundle(bundle_id)
        if getattr(args, "json", False):
            print(json.dumps(send_result, indent=2))
        else:
            print(_format_send_human(send_result))
        return 0 if send_result.get("status") == "sent" else 1

    if cmd == "status":
        status = _get_bundle_status()
        if getattr(args, "json", False):
            print(json.dumps(status, indent=2))
        else:
            print(_format_status_human(status))
        return 0

    print("Usage: ai-guardian support {prepare|send|status}", file=sys.stderr)
    return 1
