"""Tests for scanner CLI command options."""

import sys

import pytest

from ai_guardian.cli import main


@pytest.mark.parametrize("subcommand", ["install", "info"])
def test_scanner_commands_offer_secretlint_and_gitguardian(
    monkeypatch, capsys, subcommand
):
    monkeypatch.setattr(sys, "argv", ["ai-guardian", "scanner", subcommand, "--help"])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "secretlint" in output
    assert "gitguardian" in output
