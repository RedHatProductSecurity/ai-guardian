"""Smoke-only isolation and diagnostics UX; never run containers or alter a firewall.

Manual qualification on Linux/macOS Podman:
1. Run scripts/agent-cli-test with a supported CLI and --keep.
2. Confirm firewall setup precedes daemon/agent setup and host REST checks pass.
3. Open the retained daemon's tray menu and confirm it stays responsive/connected.
4. With a controlled external listener, confirm new IPv4/IPv6 egress is denied
   while local mock cases work; never send provider credentials or prompts.
5. Use --diagnose-sandbox NAME to repeat REST checks without rebuilding anything.
6. Require clean_tool, tool_output_secret and tool_output_pii to pass with real
   tool execution and normalized pre/post hook evidence. A tool offer alone fails.
7. Sensitive output must not reach even the mock's token-count endpoint. A client
   ignoring its post-tool response must FAIL, not become a skipped/qualified pass.
8. Confirm the runner announces strict-derived input blocking/output sanitization,
   not unmodified @strict. Its prepared config is copied before daemon startup;
   the source is read-only, the active copy is writable and no live policy edit
   is required. Normal @strict and other containers retain their own policies.
9. Command probes must target an advertised native shell, not an advisory MCP
   checker. Findings from a checker do not qualify native pre/post-tool delivery.
10. Use --cli-name opencode --cli-version 1.19.0 or --cli-version 2.0.24 to
    pin a temporary image. Confirm the installed version before cases; V1 warms
    one backend, V2 uses private servers. --image cannot be combined with the pin.
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


def test_cli_version_cannot_silently_replace_a_supplied_image(
    runner, monkeypatch, capsys
):
    """USER EXPERIENCE: version selection is build-time only; --image stays explicit.

    For a local V2 test, omit --image and pass --cli-version 2.0.24. Reusing a
    prepared image instead must not trigger another image build or runtime install.
    """

    def unexpected(*args, **kwargs):
        pytest.fail("a supplied image was accessed or rebuilt")

    monkeypatch.setattr(runner, "_run", unexpected)
    monkeypatch.setattr(runner, "build_current_image", unexpected)
    monkeypatch.setattr(runner, "_temp_parent", unexpected)
    with pytest.raises(SystemExit) as error:
        runner.main(
            [
                "--cli-name",
                "opencode",
                "--agent",
                "build",
                "--cli-version",
                "2.0.24",
                "--image",
                "localhost/prepared:test",
            ]
        )
    assert error.value.code == 2
    assert "--cli-version and --image cannot be combined" in capsys.readouterr().err


def test_requested_version_mismatch_is_a_failure_not_different_generation_coverage(
    runner, monkeypatch, capsys
):
    """USER EXPERIENCE: a V2 pin cannot silently run the V1 smoke path instead."""
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda *args: subprocess.CompletedProcess(
            args, 0, "1.19.0\n", "private diagnostic body"
        ),
    )
    with pytest.raises(
        RuntimeError,
        match="installed OpenCode version does not match --cli-version 2.0.24",
    ):
        runner._opencode_uses_v2("podman", "smoke", 30, expected_version="2.0.24")
    output = capsys.readouterr().out
    assert "private" not in output
    assert "PASS" not in output


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


def stub_tool_case(
    runner, monkeypatch, case_name, *, pre_hook=1, post_hook=1, executed=1, raw=0
):
    case = next(case for case in runner.CASES if case.name == case_name)
    readings = {
        "_hook_counts": {"prompt": 1, "pretooluse": pre_hook, "posttooluse": post_hook},
        "_violation_counts": (
            {case.expected_violation: 1} if case.expected_violation else {}
        ),
        "_provider_stats": {case_name: 2},
        "_tool_evidence": {
            "executed": executed,
            "tool_offers": 1,
            "clean_tool_results": int(case_name == "clean_tool"),
            "raw_tool_output_requests": raw,
        },
    }
    for method, after in readings.items():
        values = iter(({}, after))
        monkeypatch.setattr(
            runner, method, lambda *args, values=values, **kwargs: next(values)
        )
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, "private model output", "private stderr"
        ),
    )
    return case


@pytest.mark.parametrize("native_name", ("bash", "shell"))
def test_opencode_smoke_uses_native_execution_not_an_advisory_mcp_check(native_name):
    """USER EXPERIENCE: catalog order cannot replace the real tool-hook path.

    OpenCode may advertise the advisory command checker before its native shell.
    The mock must still offer native execution, on Linux and macOS alike, without
    disabling MCP, altering the plugin or loosening the smoke evidence checks.
    """
    path = (
        Path(__file__).resolve().parents[2] / "scripts" / "agent_cli_mock_provider.py"
    )
    spec = importlib.util.spec_from_file_location("smoke_native_tool_ux", path)
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    schema = {"type": "object", "properties": {"command": {"type": "string"}}}
    payload = {
        "tools": [
            {"type": "function", "function": {"name": name, "parameters": schema}}
            for name in ("ai-guardian_check_command", native_name)
        ]
    }
    numbers = provider._record_request("clean_tool", payload)
    response = provider.chat_response(payload, "clean_tool", *numbers)
    call = response["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == native_name
    assert provider._stats()["tool_offers"] == {"clean_tool": 1}


@pytest.mark.parametrize("case_name", ("ssrf", "config_exfil"))
def test_advisory_findings_without_native_pre_tool_events_remain_failures(
    runner, monkeypatch, capsys, case_name
):
    """USER EXPERIENCE: an advisory finding plus a tool offer is not hook coverage."""
    case = stub_tool_case(
        runner, monkeypatch, case_name, pre_hook=0, post_hook=0, executed=0
    )
    assert not runner._run_case("podman", "smoke", "opencode", "build", case, 30)
    output = capsys.readouterr().out
    assert (
        f"FAIL {case_name}: expected pretooluse hook event was not recorded" in output
    )
    assert f"expected_{case.expected_violation}_delta=+1" in output
    assert "hook_event_deltas=prompt=+1" in output
    assert "PASS" not in output
    assert "private" not in output


@pytest.mark.parametrize(
    "case_name", ("clean_tool", "tool_output_secret", "tool_output_pii")
)
def test_success_requires_real_tool_execution_and_post_tool_hook(
    runner, monkeypatch, capsys, case_name
):
    """USER EXPERIENCE: strict-derived smoke config sanitizes sensitive output.

    Manual verification: run the smoke runner with a supported CLI. Clean output
    must be delivered through a correlated native tool result; sensitive output
    must cause a finding without delivering its original synthetic value.
    """
    case = stub_tool_case(runner, monkeypatch, case_name)
    assert runner._run_case("docker", "smoke", "opencode", "build", case, 30)
    output = capsys.readouterr().out
    assert f"PASS {case_name}" in output
    assert "private" not in output
    assert case.prompt not in output


@pytest.mark.parametrize("engine", ("docker", "podman"))
def test_smoke_config_is_prepared_before_startup_without_a_read_only_active_file(
    runner, tmp_path, engine
):
    """USER EXPERIENCE: prepared snapshot input, not a live policy rewrite.

    Only the disposable smoke config opts into output sanitization. Prompts and
    pre-tool file reads remain blocked; a successful run does not qualify the
    unmodified strict profile's post-tool block behavior.
    """
    original = runner.STRICT_PROFILE.read_bytes()
    config_dir = tmp_path / "smoke-config"
    runner.write_smoke_config(config_dir)
    config = json.loads((config_dir / "ai-guardian.json").read_text(encoding="utf-8"))
    assert config["secret_scanning"]["enabled"] is True
    assert config["secret_redaction"]["enabled"] is True
    assert config["scan_pii"]["action"] == "redact"
    assert runner.STRICT_PROFILE.read_bytes() == original
    args = (
        "claude",
        "default",
        "smoke-image",
        config_dir,
        tmp_path / "workspace",
        "smoke",
    )
    if engine == "docker":
        command = runner.build_create_command(["ai-guardian"], engine, *args)
        assert command[command.index("--config-dir") + 1] == str(config_dir)
        assert "--profile" not in command
    else:
        command = runner.build_podman_create_command(engine, *args)
        assert (
            f"{config_dir / 'ai-guardian.json'}:"
            "/sandbox/.config/ai-guardian.host.json:ro,z"
        ) in command
        assert not any(
            ":/sandbox/.config/ai-guardian/ai-guardian.json:" in value
            for value in command
        )


@pytest.mark.parametrize(
    ("post_hook", "executed", "message"),
    (
        (0, 1, "expected posttooluse hook event was not recorded"),
        (1, 0, "the expected tool did not execute exactly once"),
    ),
)
def test_tool_offers_and_violation_logs_alone_never_qualify_output_protection(
    runner, monkeypatch, capsys, post_hook, executed, message
):
    """USER EXPERIENCE: an unexecuted/unfinished probe fails rather than passing."""
    case = stub_tool_case(
        runner,
        monkeypatch,
        "tool_output_secret",
        post_hook=post_hook,
        executed=executed,
    )
    assert not runner._run_case("docker", "smoke", "opencode", "build", case, 30)
    output = capsys.readouterr().out
    assert f"FAIL tool_output_secret: {message}" in output
    assert "Diagnostics (aggregate only):" in output
    assert "private" not in output


@pytest.mark.parametrize(
    ("cli", "agent"),
    (
        ("codex", "smoke"),
        ("opencode", "build"),
        ("pi", "openai"),
        ("gemini", "default"),
        ("claude", "default"),
    ),
)
def test_clients_ignoring_post_tool_protection_fail_without_dumping_output(
    runner, monkeypatch, capsys, cli, agent
):
    """USER EXPERIENCE: detection is not containment; upstream limits stay failures.

    Scenario: the post-tool hook ran and logged a finding, but the client forwarded
    the original synthetic output anyway. No client-specific skip may turn this
    into a pass, and diagnostics must never echo model/tool output or prompts.
    """
    case = stub_tool_case(runner, monkeypatch, "tool_output_secret", raw=1)
    assert not runner._run_case("docker", "smoke", cli, agent, case, 30)
    output = capsys.readouterr().out
    assert (
        "FAIL tool_output_secret: raw sensitive tool output reached the local mock"
        in output
    )
    assert "PASS" not in output
    assert "private" not in output
    assert case.prompt not in output
