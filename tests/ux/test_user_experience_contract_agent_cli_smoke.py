"""Smoke-only isolation and diagnostics UX; never run containers or alter a firewall.

Manual qualification on Linux/macOS Podman:
1. Run scripts/agent-cli-test with a supported CLI and --keep.
2. Confirm firewall setup precedes daemon/agent setup and host REST checks pass.
3. Open the retained daemon's tray menu and confirm it stays responsive/connected.
4. With a controlled external listener, confirm new IPv4/IPv6 egress is denied
   while local mock cases work; never send provider credentials or prompts.
5. Use --diagnose-sandbox NAME to repeat REST checks without rebuilding anything.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "agent_cli_test.py"
    spec = importlib.util.spec_from_file_location("smoke_rest_ux", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("internal", "host", "authenticated", "expected", "message"),
    (
        (
            True,
            "healthy",
            "healthy",
            True,
            "PASS daemon REST: container health and authenticated host access work.",
        ),
        (
            False,
            "not_checked",
            "not_checked",
            False,
            "FAIL daemon REST: health failed inside the sandbox; check daemon startup before host routing.",
        ),
        (
            True,
            "timeout",
            "not_checked",
            False,
            "FAIL daemon REST: internal health passes, but published health fails; check the published-port/VM forwarding path.",
        ),
        (
            True,
            "healthy",
            "http_401",
            False,
            "FAIL daemon REST: published health works, but authenticated stats failed; check daemon authentication rather than changing network isolation.",
        ),
    ),
)
def test_rest_path_errors_are_actionable_without_exposing_credentials(
    runner, internal, host, authenticated, expected, message, monkeypatch, capsys
):
    """USER EXPERIENCE: failures identify a layer, not a falsely stopped process."""
    state = {
        "ipc": True,
        "rest_port": 63152,
        "internal_health": internal,
        "auth_token": "private-smoke-credential",
    }
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda *args: subprocess.CompletedProcess(
            args, 0, json.dumps(state), "private stderr"
        ),
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, "127.0.0.1:45678\n", ""
        ),
    )
    monkeypatch.setattr(
        runner,
        "_probe_rest",
        lambda port, path, token=None: host if path == "/api/health" else authenticated,
    )
    assert (
        runner._check_sandbox_rest("podman", "ag-cli-smoke-codex-1234abcd", 30)
        is expected
    )
    output = capsys.readouterr().out
    assert message in output
    assert "private" not in output
    assert "stopped" not in output


def test_unprepared_images_fail_closed_without_hidden_builds(
    runner, monkeypatch, capsys
):
    """USER EXPERIENCE: --image stays explicit; no silent overlay build/download."""
    calls = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda command, *args, **kwargs: calls.append(command)
        or subprocess.CompletedProcess(command, 0, "", ""),
    )
    assert not runner._check_podman_smoke_image("podman", "localhost/normal:test", 30)
    assert capsys.readouterr().out.strip() == (
        "ERROR: Podman smoke image lacks the firewall bootstrap; omit --image to build a compatible temporary image. No image was rebuilt."
    )
    assert calls[0][:3] == ["podman", "image", "inspect"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("uid", "ready", "message"),
    (
        (0, True, "ERROR: smoke sandbox must be unprivileged with no-new-privileges."),
        (
            1000,
            False,
            "ERROR: smoke firewall readiness was not established; setup was not started.",
        ),
    ),
)
def test_unprotected_bootstrap_never_starts_daemon_or_agent(
    uid, ready, message, monkeypatch, capsys
):
    """USER EXPERIENCE: missing firewall or retained agent privilege stops setup."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "agent_cli_smoke_gate.py"
    spec = importlib.util.spec_from_file_location("smoke_gate_ux", path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    status = "NoNewPrivs: 1\nCapEff: 0\nCapPrm: 0\nCapBnd: 0\nCapAmb: 0\n"
    monkeypatch.setattr(gate.Path, "read_text", lambda *args, **kwargs: status)
    monkeypatch.setattr(gate.os, "geteuid", lambda: uid, raising=False)
    monkeypatch.setattr(gate, "wait_for_firewall", lambda: ready)
    monkeypatch.setattr(gate.os, "execv", lambda *args: pytest.fail("setup started"))
    assert gate.main() == 1
    assert capsys.readouterr().out.strip() == message
