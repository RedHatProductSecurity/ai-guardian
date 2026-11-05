"""Smoke-only firewall bootstrap; no real containers or firewall changes."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def restricted_status(**changes):
    fields = {
        "NoNewPrivs": "1",
        "CapEff": "0",
        "CapPrm": "0",
        "CapBnd": "0",
        "CapAmb": "0",
    }
    fields.update(changes)
    return "\n".join(f"{key}:\t{value}" for key, value in fields.items())


@pytest.mark.parametrize("exit_code", (0, 1))
def test_firewall_install_is_atomic_and_never_flushes_other_tables(
    exit_code, monkeypatch, capsys
):
    firewall = load_script("agent_cli_smoke_firewall")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command, exit_code, "private output", "private error"
        )

    monkeypatch.setattr(firewall.subprocess, "run", run)
    assert firewall.main() == exit_code
    command, options = calls[0]
    assert command == ["nft", "--file", "-"]
    assert options["input"] == firewall.RULESET
    assert "table inet ai_guardian_smoke" in firewall.RULESET
    assert "policy drop" in firewall.RULESET
    assert 'oifname "lo" accept' in firewall.RULESET
    assert "ct state established,related ct direction reply accept" in firewall.RULESET
    assert "flush" not in firewall.RULESET
    assert "private" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure", (OSError("unavailable"), subprocess.TimeoutExpired("nft", 10))
)
def test_firewall_setup_fails_closed(failure, monkeypatch):
    firewall = load_script("agent_cli_smoke_firewall")

    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(firewall.subprocess, "run", run)
    assert firewall.main() == 1


def test_agent_requires_no_capabilities_and_no_new_privileges():
    gate = load_script("agent_cli_smoke_gate")
    assert gate.agent_privileges_are_restricted(restricted_status())
    for key in ("NoNewPrivs", "CapEff", "CapPrm", "CapBnd", "CapAmb"):
        value = "0" if key == "NoNewPrivs" else "1000"
        assert not gate.agent_privileges_are_restricted(
            restricted_status(**{key: value})
        )
    assert not gate.agent_privileges_are_restricted("")
    assert not gate.agent_privileges_are_restricted(restricted_status(CapBnd="invalid"))


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX container bootstrap file modes"
)
def test_gate_accepts_only_private_ready_file(tmp_path):
    gate = load_script("agent_cli_smoke_gate")
    ready = tmp_path / "ready"
    ready.write_text("installed\n", encoding="ascii")
    ready.chmod(0o600)
    assert gate.wait_for_firewall(ready, 1)
    ready.chmod(0o666)
    assert not gate.wait_for_firewall(ready, 1)
    ready.chmod(0o600)
    ready.write_text("not-installed\n", encoding="ascii")
    assert not gate.wait_for_firewall(ready, 1)


@pytest.mark.skipif(os.name == "nt", reason="POSIX bootstrap file checks")
def test_gate_rejects_symlink(tmp_path):
    gate = load_script("agent_cli_smoke_gate")
    ready = tmp_path / "ready"
    ready.write_text("installed\n", encoding="ascii")
    ready.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(ready)
    assert not gate.wait_for_firewall(link, 1)


def test_gate_timeout_never_treats_missing_policy_as_ready(tmp_path, monkeypatch):
    gate = load_script("agent_cli_smoke_gate")
    ticks = iter((0, 0, 1))
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(gate.time, "sleep", lambda seconds: None)
    assert not gate.wait_for_firewall(tmp_path / "missing", 1)


def test_gate_rejects_unreadable_marker(tmp_path, monkeypatch):
    gate = load_script("agent_cli_smoke_gate")

    def unreadable(*args):
        raise PermissionError("private marker")

    monkeypatch.setattr(gate.Path, "lstat", unreadable)
    assert not gate.wait_for_firewall(tmp_path / "ready", 1)


def test_missing_firewall_never_starts_setup(monkeypatch):
    gate = load_script("agent_cli_smoke_gate")
    monkeypatch.setattr(
        gate.Path, "read_text", lambda *args, **kwargs: restricted_status()
    )
    monkeypatch.setattr(gate.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(gate, "wait_for_firewall", lambda: False)
    monkeypatch.setattr(
        gate.os, "execv", lambda *args: pytest.fail("unprotected setup started")
    )
    assert gate.main() == 1


def test_gate_starts_original_entrypoint_only_after_readiness(monkeypatch):
    gate = load_script("agent_cli_smoke_gate")
    monkeypatch.setattr(
        gate.Path, "read_text", lambda *args, **kwargs: restricted_status()
    )
    monkeypatch.setattr(gate.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(gate, "wait_for_firewall", lambda: True)
    monkeypatch.setattr(gate.sys, "argv", ["gate", "bash", "-l"])
    calls = []

    def replace_process(*args):
        calls.append(args)
        raise SystemExit(0)

    monkeypatch.setattr(gate.os, "execv", replace_process)
    with pytest.raises(SystemExit) as result:
        gate.main()
    assert result.value.code == 0
    assert calls == [("/usr/local/bin/entrypoint.sh", ["entrypoint.sh", "bash", "-l"])]
