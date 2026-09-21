#!/usr/bin/env python3
"""Verify versioned container manifests with bounded retries."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import Callable, Optional, Sequence, TextIO

DEFAULT_MAX_ATTEMPTS = 18
DEFAULT_RETRY_DELAY_SECONDS = 10.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0
CONTAINER_WORKFLOW_URL = (
    "https://github.com/RedHatProductSecurity/ai-guardian/actions/workflows/"
    "build-container.yml"
)

ManifestCheck = Callable[[str, float], Optional[bool]]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


def _run_manifest_check(image: str, command_timeout_seconds: float) -> Optional[bool]:
    """Run one manifest check, returning None when Docker is unavailable."""
    try:
        result = subprocess.run(
            ["docker", "manifest", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=command_timeout_seconds,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return None
    return result.returncode == 0


def _format_seconds(seconds: float) -> str:
    """Format retry intervals without unnecessary decimal places."""
    if float(seconds).is_integer():
        return f"{int(seconds)}s"
    return f"{seconds:g}s"


def verify_container_image(
    image: str,
    label: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    manifest_check: Optional[ManifestCheck] = None,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
    output: Optional[TextIO] = None,
    error: Optional[TextIO] = None,
) -> bool:
    """Verify one image and report immediate, delayed, or timed-out results."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must not be negative")
    if command_timeout_seconds <= 0:
        raise ValueError("command_timeout_seconds must be positive")

    manifest_check = manifest_check or _run_manifest_check
    output = output or sys.stdout
    error = error or sys.stderr
    started_at = clock()

    for attempt in range(1, max_attempts + 1):
        available = manifest_check(image, command_timeout_seconds)

        if available is None:
            print(
                f"{label}: Docker is unavailable; cannot verify {image}.",
                file=error,
            )
            print(
                f"Check the Build Container Image workflow: {CONTAINER_WORKFLOW_URL}",
                file=error,
            )
            return False

        if available:
            elapsed = max(0.0, clock() - started_at)
            if attempt == 1:
                message = f"{label}: {image} available"
            else:
                message = f"{label}: {image} became available after {attempt} checks"
            print(f"{message} (elapsed {elapsed:.1f}s)", file=output)
            return True

        if attempt < max_attempts:
            print(
                f"{label}: {image} not available yet "
                f"(check {attempt}/{max_attempts}); "
                f"retrying in {_format_seconds(retry_delay_seconds)}",
                file=output,
            )
            sleep(retry_delay_seconds)

    elapsed = max(0.0, clock() - started_at)
    print(
        f"{label}: {image} verification timed out after {max_attempts} checks "
        f"(elapsed {elapsed:.1f}s).",
        file=error,
    )
    print(
        f"Check the Build Container Image workflow: {CONTAINER_WORKFLOW_URL}",
        file=error,
    )
    return False


def verify_container_images(
    normal_image: str,
    openshell_image: str,
    **kwargs: object,
) -> bool:
    """Verify both release images, continuing when either image is unavailable."""
    all_available = True
    for label, image in (
        ("Container", normal_image),
        ("OpenShell container", openshell_image),
    ):
        if not verify_container_image(image, label, **kwargs):
            all_available = False
    return all_available


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the versioned normal and OpenShell image checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normal_image", help="Versioned normal container image")
    parser.add_argument("openshell_image", help="Versioned OpenShell container image")
    args = parser.parse_args(argv)

    return int(not verify_container_images(args.normal_image, args.openshell_image))


if __name__ == "__main__":
    raise SystemExit(main())
