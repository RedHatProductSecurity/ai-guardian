"""Tests for the IDE setup state CLI command."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_ide_setup_sync_handler_outputs_json(capsys):
    from ai_guardian.cli_handlers import _handle_ide_setup_command

    result = {
        "checked_at": "2026-09-06T12:00:00Z",
        "installed": ["claude"],
        "configured": ["claude"],
        "needs_setup": [],
        "integrations": {
            "claude": {"name": "Claude Code", "healthy": True},
        },
    }
    args = SimpleNamespace(ide_setup_command="sync", json_output=True)

    with patch(
        "ai_guardian.tray.proactive_prompt.sync_ide_setup_state",
        return_value=result,
    ) as sync:
        assert _handle_ide_setup_command(args) == 0

    assert json.loads(capsys.readouterr().out) == result
    sync.assert_called_once_with()


def test_ide_setup_sync_is_registered_without_daemon_autostart():
    from ai_guardian.cli import main

    with (
        patch("sys.argv", ["ai-guardian", "ide-setup", "sync", "--json"]),
        patch("ai_guardian.cli._ensure_daemon_started") as start,
        patch("ai_guardian.cli._handle_ide_setup_command", return_value=0) as handler,
    ):
        assert main() == 0

    start.assert_not_called()
    args = handler.call_args.args[0]
    assert args.command == "ide-setup"
    assert args.ide_setup_command == "sync"
    assert args.json_output is True


def test_ide_setup_reset_handler_outputs_result(capsys):
    from ai_guardian.cli_handlers import _handle_ide_setup_command

    args = SimpleNamespace(
        ide_setup_command="reset", ide_type="claude", json_output=False
    )
    with patch(
        "ai_guardian.tray.proactive_prompt.reset_ide_setup_state",
        return_value={"ide": "claude", "changed": True},
    ) as reset:
        assert _handle_ide_setup_command(args) == 0

    assert "Reset IDE setup decisions for claude" in capsys.readouterr().out
    reset.assert_called_once_with("claude")


def test_ide_setup_reset_is_registered():
    from ai_guardian.cli import main

    with (
        patch(
            "sys.argv",
            ["ai-guardian", "ide-setup", "reset", "--ide", "claude", "--json"],
        ),
        patch("ai_guardian.cli._handle_ide_setup_command", return_value=0) as handler,
    ):
        assert main() == 0

    args = handler.call_args.args[0]
    assert args.ide_setup_command == "reset"
    assert args.ide_type == "claude"
    assert args.json_output is True


def test_setup_help_explains_codex_scope(capsys):
    from ai_guardian.cli import main

    with patch("sys.argv", ["ai-guardian", "setup", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Codex mode in the ChatGPT" in output
    assert "desktop app" in output
    assert "regular ChatGPT mode is not protected" in output
    assert "Shared MCP configuration does not imply hook enforcement" in output


def test_cursor_project_setup_option_reaches_setup_orchestrator():
    from ai_guardian.cli import main

    with (
        patch(
            "sys.argv",
            [
                "ai-guardian",
                "setup",
                "--ide",
                "cursor",
                "--project",
                "/tmp/cloud-project",
                "--yes",
            ],
        ),
        patch("ai_guardian.cli._ensure_daemon_started"),
        patch("ai_guardian.setup.setup_hooks", return_value=True) as setup_hooks,
    ):
        assert main() == 0

    setup_hooks.assert_called_once_with(
        ide_type="cursor",
        remote_config_url=None,
        dry_run=False,
        force=False,
        interactive=False,
        migrate_pattern_server=False,
        create_config=False,
        permissive=False,
        pre_commit=False,
        log_violations=False,
        auto_install_hooks=False,
        uninstall_hooks=False,
        install_scanner=None,
        use_pinned=False,
        json_output=False,
        profile=None,
        save_profile=None,
        list_profiles=False,
        no_mcp=None,
        rules=None,
        scope="project",
        project_dir="/tmp/cloud-project",
    )
