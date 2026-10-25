"""Operator-terminal recovery UX; all host paths belong to disposable fixtures.

Manual QA: use a disposable account/project, preview, confirm the selected scope,
then repeat after removing that test installation's executable/interpreter. Check
retained third-party integrations and backups, restart the host, and record the
exact host version/event/platform. These tests do not claim live-host behavior.
"""

import json
import runpy
import sys

import pytest

from tests.unit.test_orphan_recovery import ENGINE, HOME_VARIABLES

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="Standalone recovery requires Python 3.11+"
)


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    for name in HOME_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    config = tmp_path / ".claude.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "ai-guardian": {"command": "/gone/ai-guardian"},
                    "other": {"command": "other"},
                }
            }
        ),
        encoding="utf-8",
    )
    return runpy.run_path(str(ENGINE))["main"], config


def test_preview_explicitly_says_no_files_or_backups_written(recovery, capsys):
    """USER EXPERIENCE: Preview reports exact scope and paths without mutation."""
    main, config = recovery
    original = config.read_bytes()
    assert main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "Integration cleanup scope: user" in output
    assert f"Would edit: {config}" in output
    assert "Preview complete; no files or backups written." in output
    assert config.read_bytes() == original
    assert not list(config.parent.glob("*.bak"))


def test_success_explains_backup_restart_and_preserved_history(recovery, capsys):
    """USER EXPERIENCE: Cleanup is explicit; no silent error suppression occurs."""
    main, config = recovery
    assert main(["--yes"]) == 0
    output = capsys.readouterr().out
    assert "Integration cleanup complete." in output
    assert "Backed up: " in output
    assert (
        "Restart affected hosts. AI Guardian settings and violation history were not changed."
        in output
    )
    assert json.loads(config.read_text())["mcpServers"] == {
        "other": {"command": "other"}
    }


@pytest.mark.parametrize(
    "command",
    [
        r"C:\removed\Python\pythonw.EXE -m ai_guardian",
        [r"C:\removed\Python\pythonw.EXE -m ai_guardian", "mcp-server"],
    ],
)
def test_windows_module_launch_recovery_needs_no_surviving_runtime(
    recovery, capsys, command
):
    """USER EXPERIENCE: Owned Windows module launches recover, not falsely retain."""
    main, config = recovery
    data = json.loads(config.read_text())
    data["mcpServers"]["ai-guardian"] = {"command": command}
    config.write_text(json.dumps(data), encoding="utf-8")
    original = config.read_bytes()

    assert main(["--dry-run"]) == 0
    assert config.read_bytes() == original
    capsys.readouterr()
    assert main(["--yes"]) == 0
    captured = capsys.readouterr()
    assert "Integration cleanup complete." in captured.out
    assert "Retained/failed:" not in captured.err
    assert json.loads(config.read_text())["mcpServers"] == {
        "other": {"command": "other"}
    }


@pytest.mark.parametrize(
    "command",
    [
        "pythonw.exe -m unrelated_module",
        ["pythonw.exe -m ai_guardian_other", "mcp-server"],
        ["pythonw.exe -m ai_guardian && other -m ai_guardian", "mcp-server"],
    ],
)
def test_ambiguous_windows_module_entry_is_retained_not_guessed(
    recovery, capsys, command
):
    """USER EXPERIENCE: A matching entry name alone never authorizes deletion."""
    main, config = recovery
    data = json.loads(config.read_text())
    data["mcpServers"]["ai-guardian"] = {"command": command}
    config.write_text(json.dumps(data), encoding="utf-8")
    original = config.read_bytes()

    assert main(["--yes"]) == 1
    captured = capsys.readouterr()
    assert "unrecognized ai-guardian MCP entry retained" in captured.err
    assert (
        "Integration cleanup incomplete; review retained/failed paths." in captured.out
    )
    assert config.read_bytes() == original
    assert not list(config.parent.glob("*.bak"))


def test_malformed_input_is_retained_and_incomplete_not_success(recovery, capsys):
    """USER EXPERIENCE: Partial failure identifies a path, never its private contents."""
    main, config = recovery
    config.write_text("PRIVATE_DIAGNOSTIC_SENTINEL malformed", encoding="utf-8")
    assert main(["--yes"]) == 1
    captured = capsys.readouterr()
    assert (
        "Integration cleanup incomplete; review retained/failed paths." in captured.out
    )
    assert str(config) in captured.err
    assert "PRIVATE_DIAGNOSTIC_SENTINEL" not in captured.out + captured.err
    assert config.read_text() == "PRIVATE_DIAGNOSTIC_SENTINEL malformed"


def test_declining_confirmation_is_a_real_cancellation(recovery, monkeypatch, capsys):
    """USER EXPERIENCE: Default-no confirmation leaves every integration intact."""
    main, config = recovery
    original = config.read_bytes()
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert main([]) == 1
    assert "Cancelled; no changes made." in capsys.readouterr().out
    assert config.read_bytes() == original


def test_repeated_cleanup_does_not_create_more_backups(recovery, capsys):
    main, config = recovery
    assert main(["--yes"]) == 0
    capsys.readouterr()
    backups = list(config.parent.glob("*.bak"))
    assert main(["--yes"]) == 0
    output = capsys.readouterr().out
    assert "Would edit:" not in output
    assert "Backed up:" not in output
    assert list(config.parent.glob("*.bak")) == backups
