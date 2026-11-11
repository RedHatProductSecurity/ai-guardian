"""Tests for the restricted daemon-only command-line entry point."""

import argparse
import sys
from unittest import mock

import pytest

from ai_guardian import daemon_cli


def test_background_start_uses_daemon_module_entrypoint(monkeypatch):
    monkeypatch.setattr(daemon_cli, "_clear_stop_request", lambda: None)
    with mock.patch(
        "ai_guardian.daemon.client.start_daemon_background", return_value=True
    ) as start_background:
        assert daemon_cli.main(["start", "--background", "--idle-timeout", "5"]) == 0

    start_background.assert_called_once_with(
        daemon_command=[
            sys.executable,
            "-m",
            "ai_guardian.daemon_cli",
            "start",
            "--idle-timeout",
            "5.0",
        ]
    )


def test_foreground_start_uses_daemon_server(monkeypatch):
    monkeypatch.setattr(daemon_cli, "_clear_stop_request", lambda: None)
    server = mock.Mock()
    with mock.patch(
        "ai_guardian.daemon.server.DaemonServer", return_value=server
    ) as ctor:
        assert daemon_cli.main(["start", "--idle-timeout", "2"]) == 0

    ctor.assert_called_once_with(idle_timeout=120)
    server.start.assert_called_once_with()


@pytest.mark.parametrize("command", ["status", "stop"])
def test_status_and_stop_delegate_to_existing_handler(command):
    with mock.patch(
        "ai_guardian.cli_handlers._handle_daemon_command", return_value=0
    ) as handler:
        assert daemon_cli.main([command]) == 0

    handler.assert_called_once_with(argparse.Namespace(daemon_command=command))


def test_init_config_uses_safe_default_writer(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "ai-guardian.json"
    monkeypatch.setattr("ai_guardian.config.utils.get_config_dir", lambda: tmp_path)
    with mock.patch(
        "ai_guardian.setup.config.create_default_config",
        return_value=(True, "unused generic setup text"),
    ) as create_config:
        assert daemon_cli.main(["init-config"]) == 0

    create_config.assert_called_once_with()
    output = capsys.readouterr().out
    assert "Created default configuration" in output
    assert str(config_path) in output


def test_init_config_preserves_existing_config(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "ai-guardian.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("ai_guardian.config.utils.get_config_dir", lambda: tmp_path)
    with mock.patch(
        "ai_guardian.setup.config.create_default_config",
        return_value=(True, "existing configuration preserved"),
    ):
        assert daemon_cli.main(["init-config"]) == 0

    output = capsys.readouterr().out
    assert "Existing configuration preserved" in output
    assert str(config_path) in output


def test_restart_stops_then_starts_with_daemon_entrypoint(monkeypatch):
    monkeypatch.setattr(daemon_cli, "_clear_stop_request", lambda: None)
    with mock.patch(
        "ai_guardian.cli_handlers._handle_daemon_command", return_value=0
    ) as handler:
        with mock.patch.object(
            daemon_cli, "_start_background", return_value=0
        ) as start:
            assert daemon_cli.main(["restart"]) == 0

    handler.assert_called_once_with(argparse.Namespace(daemon_command="stop"))
    start.assert_called_once_with(0)
