"""Tests for desktop-notification command success reporting."""

import platform
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from ai_guardian.tray import notifications


def test_waiting_notification_reports_command_success(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "run", run)

    assert notifications.show_notification("AI Guardian", "Alert", wait=True) is True

    run.assert_called_once_with(
        ["notify-send", "AI Guardian", "Alert"],
        check=False,
        timeout=5,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_waiting_notification_reports_command_failure(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    assert notifications.show_notification("AI Guardian", "Alert", wait=True) is False


def test_async_notification_preserves_existing_nonblocking_behavior(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen", popen)

    assert notifications.show_notification("AI Guardian", "Alert") is True

    popen.assert_called_once_with(["notify-send", "AI Guardian", "Alert"])


def test_waiting_notification_reports_timeout_and_missing_command(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired("notify-send", 5)),
    )
    assert notifications.show_notification("AI Guardian", "Alert", wait=True) is False

    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=FileNotFoundError("notify-send"))
    )
    assert notifications.show_notification("AI Guardian", "Alert", wait=True) is False


def test_unsupported_platform_returns_false(monkeypatch):
    run = Mock()
    monkeypatch.setattr(platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", run)

    assert notifications.show_notification("AI Guardian", "Alert", wait=True) is False
    run.assert_not_called()
