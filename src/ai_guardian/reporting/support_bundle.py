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
import shutil
import smtplib
import subprocess
import tempfile
import uuid
import webbrowser
import zipfile
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_active_bundles: Dict[str, Dict[str, Any]] = {}


def _get_support_config() -> Dict:
    """Load support config from ai-guardian.json."""
    from ai_guardian.config.utils import get_config_dir

    config_path = get_config_dir() / "ai-guardian.json"
    if not config_path.exists():
        config_path = Path.cwd() / ".ai-guardian.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        return config.get("support", {})
    except Exception:
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
    """Get sanitized full ai-guardian log. Returns (text, redaction_count)."""
    from ai_guardian.config.utils import get_state_dir

    log_path = get_state_dir() / "ai-guardian.log"
    if not log_path.exists():
        return "", 0

    try:
        text = log_path.read_text(errors="replace")

        from ai_guardian.scanners.sanitizer import sanitize_text

        result = sanitize_text(text)
        redactions = result.get("stats", {}).get("total", 0)
        return result.get("sanitized_text", text), redactions
    except Exception as e:
        logger.debug("Log error: %s", e)
        return "", 0


def prepare_bundle(
    *,
    include_log: bool = True,
    include_violations: bool = True,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Prepare a sanitized support bundle for user review.

    Args:
        include_log: Include the sanitized ai-guardian.log file.
        include_violations: Include the sanitized violations.json file.
        output_path: If provided, copy bundle files to this directory.

    Returns dict with bundle_id, temp_path, destination, and file list.
    """
    support_config = _get_support_config()
    destination = support_config.get("export_destination", "")
    if not destination:
        from ai_guardian.config.utils import get_state_dir

        destination = str(get_state_dir() / "support-bundles")
    ttl = support_config.get("bundle_ttl_minutes", 30)

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

    # 2. Violations (sanitized)
    if include_violations:
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            violations = vl.get_recent_violations(limit=100)
            sanitized, count = _sanitize_violations(violations)
            (temp_dir / "violations.jsonl").write_text(json.dumps(sanitized, indent=2))
            files_info.append(
                {
                    "name": "violations.jsonl",
                    "sanitized": count > 0,
                    "redactions": count,
                    "note": (
                        f"{count} file paths and content redacted"
                        if count
                        else "No sensitive data found"
                    ),
                }
            )
        except Exception as e:
            logger.debug("Bundle violations error: %s", e)

    # 3. Metrics (aggregate only)
    try:
        from ai_guardian.reporting.metrics import MetricsComputer

        mc = MetricsComputer(since_days=30)
        report = mc.compute()
        metrics = {
            "total_violations": report.total_violations,
            "by_type": dict(report.by_type),
            "by_severity": dict(report.by_severity),
            "resolved": report.resolved_count,
            "unresolved": report.unresolved_count,
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
        report = doc.run_all()
        checks = [
            {"name": c.name, "status": c.status.value, "message": c.message}
            for c in report.checks
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

    # 6. Full log (sanitized)
    if include_log:
        try:
            log_text, count = _get_sanitized_log()
            if log_text:
                (temp_dir / "ai-guardian.log").write_text(log_text)
                files_info.append(
                    {
                        "name": "ai-guardian.log",
                        "sanitized": count > 0,
                        "redactions": count,
                        "note": (
                            f"Full log, {count} items redacted" if count else "Full log"
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

    # Copy to output_path if requested
    actual_output = str(temp_dir)
    if output_path:
        out = Path(output_path).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        for item in temp_dir.iterdir():
            if item.name == ".ai-read-deny":
                continue
            shutil.copy2(item, out / item.name)
        actual_output = str(out)

    _active_bundles[bundle_id] = {
        "temp_path": str(temp_dir),
        "destination": destination,
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": ttl,
        "files": files_info,
    }

    _persist_bundle_ref(bundle_id, _active_bundles[bundle_id])

    result = {
        "bundle_id": bundle_id,
        "temp_path": str(temp_dir),
        "destination": destination,
        "files": files_info,
    }
    if output_path:
        result["output_path"] = actual_output
    return result


def _persist_bundle_ref(bundle_id: str, bundle_info: Dict) -> None:
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
                },
                indent=2,
            )
        )
    except Exception as e:
        logger.debug("Failed to persist bundle ref: %s", e)


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

        if not temp_path.exists():
            return None

        created = datetime.fromisoformat(ref["created"])
        age_minutes = (datetime.now(timezone.utc) - created).total_seconds() / 60
        ttl = ref.get("ttl_minutes", 30)
        if age_minutes > ttl:
            return None

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
    destination = support_config.get("export_destination", "")
    if not destination:
        from ai_guardian.config.utils import get_state_dir

        destination = str(get_state_dir() / "support-bundles")

    files_info = [
        {"name": f.name, "sanitized": False, "redactions": 0, "note": "pre-existing"}
        for f in files
    ]

    _active_bundles[bundle_id] = {
        "temp_path": str(path),
        "destination": destination,
        "created": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": 1440,
        "files": files_info,
    }
    return bundle_id


def _get_bundle_status() -> Dict[str, Any]:
    """Get support bundle configuration and status information."""
    support_config = _get_support_config()
    destination = support_config.get("export_destination", "")

    if not destination:
        from ai_guardian.config.utils import get_state_dir

        destination = str(get_state_dir() / "support-bundles")

    if destination.startswith("s3://"):
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

    if dest_type == "email":
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

    try:
        if destination.startswith("s3://"):
            return _send_to_s3(bundle_id, temp_path, destination)
        elif destination.startswith("gs://"):
            return _send_to_gcs(bundle_id, temp_path, destination)
        elif destination.startswith("mailto:") or "@" in destination:
            return _send_to_email(bundle_id, temp_path, destination)
        elif destination.startswith("/") or destination.startswith("~"):
            return _send_to_local(bundle_id, temp_path, destination)
        elif not destination:
            return {
                "status": "error",
                "message": "No export destination configured. Add 'support.export_destination' to ai-guardian.json.",
            }
        else:
            return {
                "status": "error",
                "message": f"Unsupported destination: {destination}",
            }
    finally:
        _cleanup_bundle(bundle_id)


def _send_to_local(bundle_id: str, temp_path: Path, destination: str) -> Dict:
    """Copy bundle to a local directory."""
    dest = Path(destination).expanduser()
    bundle_dest = dest / bundle_id
    bundle_dest.mkdir(parents=True, exist_ok=True)

    for item in temp_path.iterdir():
        if item.name == ".ai-read-deny":
            continue
        shutil.copy2(item, bundle_dest / item.name)

    return {
        "status": "sent",
        "destination": str(bundle_dest),
        "message": f"Bundle copied to {bundle_dest}",
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
        for item in temp_path.iterdir():
            if item.name == ".ai-read-deny":
                continue
            s3.upload_file(str(item), bucket, f"{key_prefix}/{item.name}")
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
        for item in temp_path.iterdir():
            if item.name == ".ai-read-deny":
                continue

            object_name = f"{object_prefix}/{item.name}"
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


def _zip_bundle(temp_path: Path, bundle_id: str) -> Path:
    """Zip all bundle files into a single archive.

    Returns the path to the created zip file.
    Excludes .ai-read-deny markers.
    """
    zip_path = temp_path.parent / f"{bundle_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(temp_path.iterdir()):
            if item.name == ".ai-read-deny":
                continue
            zf.write(item, item.name)
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
            pass  # best-effort

        return {
            "status": "sent",
            "destination": f"mailto:{to_addr}",
            "zip_path": str(zip_path),
            "message": (
                f"No SMTP configured. Bundle zipped to {zip_path}\n"
                "Your default mail client has been opened. "
                "Please attach the zip and send."
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
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)
        del _active_bundles[bundle_id]


# --- CLI formatters ---


def _format_prepare_human(result: Dict[str, Any]) -> str:
    """Format prepare_bundle result for terminal output."""
    lines = []
    path = result.get("output_path", result["temp_path"])
    lines.append(f"Support bundle prepared at: {path}")
    lines.append("")
    lines.append("Files:")
    for f in result["files"]:
        marker = f"⚠️  {f['redactions']} items redacted" if f["redactions"] else "clean"
        lines.append(f"  {f['name']:25s} — {marker}")
    lines.append("")
    lines.append("Review the files, then run:")
    lines.append("  ai-guardian support send")
    return "\n".join(lines)


def _format_send_human(result: Dict[str, Any]) -> str:
    """Format send_bundle result for terminal output."""
    if result["status"] == "sent":
        return f"✓ Sent: {result.get('message', result.get('destination', ''))}"
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
            if not getattr(args, "json", False):
                print(_format_prepare_human(result))
                print()
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
                    "Error: No pending bundle found.\n"
                    "Run 'ai-guardian support prepare' first, or use "
                    "'ai-guardian support send --prepare'.",
                    file=sys.stderr,
                )
                return 1

        if not getattr(args, "yes", False):
            if not sys.stdin.isatty():
                print(
                    "Error: Cannot prompt for confirmation in non-interactive mode. "
                    "Use --yes to skip.",
                    file=sys.stderr,
                )
                return 1
            dest = _active_bundles.get(bundle_id, {}).get("destination", "")
            answer = input(f"Send bundle to {dest}? [y/N] ").strip().lower()
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
