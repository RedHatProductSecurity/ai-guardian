"""Unit tests for versioned container image release verification."""

import io
import sys
from pathlib import Path

SCRIPTS_PATH = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_PATH))

from verify_container_images import (  # noqa: E402
    CONTAINER_WORKFLOW_URL,
    _format_seconds,
    verify_container_image,
    verify_container_images,
)


def _clock(values):
    values = iter(values)
    return lambda: next(values)


def test_format_seconds_supports_python39_numeric_types():
    assert _format_seconds(2) == "2s"
    assert _format_seconds(2.5) == "2.5s"


def test_immediate_success_does_not_retry():
    output = io.StringIO()
    error = io.StringIO()
    calls = []

    def manifest_check(image, timeout):
        calls.append((image, timeout))
        return True

    result = verify_container_image(
        "quay.io/example/ai-guardian:1.19.0",
        "Container",
        max_attempts=3,
        retry_delay_seconds=2,
        command_timeout_seconds=7,
        manifest_check=manifest_check,
        clock=_clock([10.0, 10.25]),
        output=output,
        error=error,
    )

    assert result is True
    assert len(calls) == 1
    assert "available" in output.getvalue()
    assert "retrying" not in output.getvalue()
    assert error.getvalue() == ""


def test_delayed_success_reports_retries_without_warning():
    output = io.StringIO()
    error = io.StringIO()
    sleeps = []
    responses = iter([False, False, True])

    result = verify_container_image(
        "quay.io/example/ai-guardian:1.19.0",
        "Container",
        max_attempts=3,
        retry_delay_seconds=2,
        manifest_check=lambda image, timeout: next(responses),
        sleep=sleeps.append,
        clock=_clock([10.0, 12.5]),
        output=output,
        error=error,
    )

    assert result is True
    assert sleeps == [2, 2]
    assert "check 1/3" in output.getvalue()
    assert "check 2/3" in output.getvalue()
    assert "became available after 3 checks" in output.getvalue()
    assert "warning" not in output.getvalue().lower()
    assert error.getvalue() == ""


def test_timeout_identifies_image_and_workflow():
    output = io.StringIO()
    error = io.StringIO()
    sleeps = []

    result = verify_container_image(
        "quay.io/example/ai-guardian-openshell:1.19.0",
        "OpenShell container",
        max_attempts=3,
        retry_delay_seconds=1,
        manifest_check=lambda image, timeout: False,
        sleep=sleeps.append,
        clock=_clock([10.0, 13.0]),
        output=output,
        error=error,
    )

    assert result is False
    assert sleeps == [1, 1]
    assert "ai-guardian-openshell:1.19.0" in error.getvalue()
    assert "timed out after 3 checks" in error.getvalue()
    assert CONTAINER_WORKFLOW_URL in error.getvalue()


def test_both_images_are_checked_when_the_first_times_out():
    checked = []
    normal_responses = iter([False, False])

    def manifest_check(image, timeout):
        checked.append(image)
        if "openshell" in image:
            return True
        return next(normal_responses)

    result = verify_container_images(
        "quay.io/example/ai-guardian:1.19.0",
        "quay.io/example/ai-guardian-openshell:1.19.0",
        max_attempts=2,
        retry_delay_seconds=0,
        manifest_check=manifest_check,
        sleep=lambda seconds: None,
        clock=_clock([10.0, 10.0, 10.1, 10.2]),
        output=io.StringIO(),
        error=io.StringIO(),
    )

    assert result is False
    assert checked == [
        "quay.io/example/ai-guardian:1.19.0",
        "quay.io/example/ai-guardian:1.19.0",
        "quay.io/example/ai-guardian-openshell:1.19.0",
    ]
