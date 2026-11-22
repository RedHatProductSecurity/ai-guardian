"""Shared version detection and stability advisories for agent CLIs."""

import logging
import re
import shutil
import subprocess
from typing import Any, Dict, Optional

from ai_guardian.ide_registry import IDEIntegration

logger = logging.getLogger(__name__)

_CLI_VERSION_PATTERN = re.compile(r"(?<!\d)v?(\d+\.\d+\.\d+)(?!\d)")
_CLI_VERSION_TIMEOUT_SECONDS = 5


def parse_cli_version(output: str) -> Optional[str]:
    """Extract the first semantic version from CLI output."""
    match = _CLI_VERSION_PATTERN.search(output or "")
    return match.group(1) if match else None


def detect_cli_runtime(integration: IDEIntegration) -> Optional[Dict[str, Any]]:
    """Best-effort version probe for an installed CLI integration."""
    if not integration.cli_capable:
        return None

    if integration.key == "opencode":
        from ai_guardian.opencode_support import detect_opencode_runtime

        runtime = detect_opencode_runtime()
        if not runtime.get("executable") and not runtime.get("version"):
            return None
        result: Dict[str, Any] = {
            "executable": integration.cli_executables[0],
            "version": runtime.get("version"),
        }
        generation = runtime.get("generation")
        if generation and generation != "unknown":
            result["generation"] = generation
        return result

    for executable in integration.cli_executables:
        binary = shutil.which(executable)
        if not binary:
            continue
        try:
            completed = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=_CLI_VERSION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("Could not read %s version: %s", executable, exc)
            return {"executable": executable, "version": None}

        output = "\n".join(
            value for value in (completed.stdout, completed.stderr) if value
        )
        return {
            "executable": executable,
            "version": parse_cli_version(output),
        }

    return None


def runtime_activation_info(
    integration: IDEIntegration,
    verification: Optional[Dict[str, Any]] = None,
    *,
    detected: Optional[bool],
) -> Dict[str, str]:
    """Describe runtime activation evidence separately from setup health.

    CLI version and saved-configuration checks do not prove that a host loaded
    or invoked AI Guardian. Only an explicit runtime result may report verified
    or failed activation; otherwise detected CLI integrations remain unverified.
    """
    if not integration.cli_capable:
        return {
            "status": "not_applicable",
            "reason": "This integration does not expose a local CLI runtime.",
        }
    if detected is False:
        return {
            "status": "not_detected",
            "reason": "No installed CLI or integration was detected.",
        }
    if detected is None:
        return {
            "status": "unknown",
            "reason": "CLI or integration detection did not complete.",
        }

    if not isinstance(verification, dict):
        verification = {}
    nested_status = verification.get("runtime_activation")
    if isinstance(nested_status, dict):
        status = nested_status.get("status")
    else:
        status = None
    if not isinstance(status, str) or status not in {
        "verified",
        "unverified",
        "failed",
    }:
        status = verification.get("runtime_activation_status")
    if not isinstance(status, str) or status not in {
        "verified",
        "unverified",
        "failed",
    }:
        status = verification.get("plugin_runtime_status")
    if not isinstance(status, str) or status not in {
        "verified",
        "unverified",
        "failed",
    }:
        status = "unverified"

    reason = (
        nested_status.get("reason")
        if isinstance(nested_status, dict)
        else verification.get("runtime_activation_reason")
    )
    if not isinstance(reason, str) or not reason.strip():
        if status == "verified":
            reason = "The host reported evidence that AI Guardian is active."
        elif status == "failed":
            reason = "The host reported that AI Guardian did not activate."
        else:
            reason = (
                integration.runtime_verification_note
                or "AI Guardian has no runtime signal confirming a live hook "
                "invocation or plugin load. Unverified is not a configuration "
                "fault, and CLI version checks are not proof."
            )
    return {"status": status, "reason": reason}


def runtime_activation_label(status: object) -> str:
    """Return a user-facing label for a runtime activation state."""
    if not isinstance(status, str):
        return "Unknown"
    labels = {
        "verified": "Verified",
        "unverified": "Unverified",
        "failed": "Failed",
        "not_detected": "Not detected",
        "unknown": "Check unavailable",
        "not_applicable": "Not applicable",
    }
    return labels.get(status, "Unknown")


def pre_1_0_cli_advisory(
    integration: IDEIntegration, runtime: Dict[str, Any]
) -> Optional[Dict[str, str]]:
    """Build an advisory only when a parseable detected version is below 1.0.0."""
    detected_version = runtime.get("version")
    if not isinstance(detected_version, str):
        return None

    version = parse_cli_version(detected_version)
    if version is None or int(version.split(".", 1)[0]) >= 1:
        return None

    return {
        "code": "pre_1_0_cli",
        "ide": integration.key,
        "executable": str(runtime.get("executable", "")),
        "version": version,
        "message": (
            f"{integration.display_name} version {version} is pre-1.0.0. "
            "Its upstream interface may change; AI Guardian's support status "
            "describes integration coverage, not upstream CLI stability."
        ),
    }
