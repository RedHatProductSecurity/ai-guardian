"""All advertised host CLIs must have a smoke lane or an actionable audit record."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_guardian.ide_registry import SUPPORTED_CLI_IDE_TYPES

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "scripts/agent_cli_coverage.json"
AUDIT = ROOT / "docs/REAL_AGENT_CLI_COVERAGE.md"
WORKFLOW = ROOT / ".github/workflows/release-readiness.yml"


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location(
        "cli_coverage_runner", ROOT / "scripts/agent_cli_test.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_canonical_cli_has_a_ledger_record_and_parser_choice(runner):
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    clients = ledger["clients"]
    assert ledger["schema_version"] == 1
    assert set(clients) == set(SUPPORTED_CLI_IDE_TYPES)
    choices = next(a.choices for a in runner._parser()._actions if a.dest == "cli_name")
    assert set(choices) == set(clients)
    assert set(clients) == set(runner.RUNNABLE_CLI_NAMES) | set(
        runner.BLOCKED_SMOKE_CLIS
    )
    for cli, entry in clients.items():
        assert entry["runner"] in {"full", "pre-tool-only", "blocked"}
        if cli in runner.BLOCKED_SMOKE_CLIS:
            assert entry["runner"] == "blocked"
            assert entry["blocker"] == runner.BLOCKED_SMOKE_CLIS[cli]
            assert entry["ci_steps"] == []
        else:
            assert entry["runner"] == (
                "pre-tool-only" if cli in runner.PARTIAL_SMOKE_CLIS else "full"
            )
            assert entry["blocker"] is None
            assert entry["ci_steps"]


def test_ledger_matches_actual_release_readiness_invocations_and_versions(runner):
    clients = json.loads(LEDGER.read_text(encoding="utf-8"))["clients"]
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    lanes = {}
    for job in workflow["jobs"].values():
        job_lanes = []
        for step in job.get("steps", []):
            for cli in re.findall(
                r"scripts/agent-cli-test --cli-name ([a-z]+)", step.get("run", "")
            ):
                assert cli in clients
                job_lanes.append(cli)
                lanes.setdefault(cli, []).append(step["id"])
                if cli != "codex":
                    assert not step.get("continue-on-error", False)
        if job_lanes:
            assert len(job_lanes) == 1, "Each CLI/version needs its own job"
            assert not job.get("needs"), "A different CLI must not gate this job"
            assert not job.get("continue-on-error", False)
    assert lanes == {
        cli: entry["ci_steps"] for cli, entry in clients.items() if entry["ci_steps"]
    }
    dockerfile = (ROOT / "container/Dockerfile").read_text(encoding="utf-8")
    assert f"ARG GROK_VERSION={runner.GROK_VERSION}" in dockerfile
    assert clients["grok"]["reviewed_versions"] == [runner.GROK_VERSION]
    assert clients["goose"]["reviewed_versions"] == [runner.GOOSE_VERSION]
    parity = workflow["jobs"]["multi-agent-setup"]["steps"]
    assert any(
        "tests/unit/test_agent_cli_coverage.py" in step.get("run", "")
        and "agent_cli_test.py --coverage" in step["run"]
        and "GITHUB_STEP_SUMMARY" in step["run"]
        for step in parity
    )


def test_seven_client_audit_has_versions_sources_priorities_and_no_runtime_claim():
    clients = json.loads(LEDGER.read_text(encoding="utf-8"))["clients"]
    text = AUDIT.read_text(encoding="utf-8")
    sources = dict(re.findall(r"^\[([^\]]+)\]: (https://\S+)$", text, re.MULTILINE))
    for cli in ("copilot", "grok", "antigravity", "kiro", "openclaw", "crush", "goose"):
        assert clients[cli]["reviewed_versions"]
        section = text.split(f"## {cli}\n", 1)[1].split("\n## ", 1)[0]
        for version in clients[cli]["reviewed_versions"]:
            assert version in section
        assert "**Next action / priority:**" in section
        assert "**Native execution in this change:** not run" in section
        citations = re.findall(r"\[[^\]]+\]\[([^\]]+)\]", section)
        assert citations
        assert all(citation in sources for citation in citations)
        if clients[cli]["blocker"]:
            assert clients[cli]["blocker"] in section
    for entry in clients.values():
        assert f"## {entry['audit']}\n" in text


@pytest.mark.parametrize("cli", ("grok", "goose"))
def test_partial_profiles_never_run_prompt_or_sensitive_output_enforcement(cli, runner):
    assert {case.name for case in runner.smoke_cases(cli)} == {
        "ssrf",
        "config_exfil",
        "command_credential",
        "clean_tool",
        "allowed",
    }
    assert not set(runner.OUTPUT_CASES - {"clean_tool"}).intersection(
        case.name for case in runner.smoke_cases(cli)
    )
    # Existing full-matrix clients retain every applicable assertion/case.
    for full in ("claude", "codex", "gemini", "opencode", "pi"):
        assert runner.smoke_cases(full) == tuple(
            case
            for case in runner.CASES
            if not case.cli_names or full in case.cli_names
        )


def test_coverage_mode_is_read_only_and_explicitly_not_qualification(
    runner, monkeypatch, capsys
):
    monkeypatch.setattr(runner, "_run", lambda *a, **kw: pytest.fail("runtime started"))
    assert runner.main(["--coverage"]) == 0
    text = capsys.readouterr().out
    assert "NOT security qualification" in text
    assert "no client was run" in text
    for cli in SUPPORTED_CLI_IDE_TYPES:
        assert f"{cli}: runner=" in text
    assert "PASS" not in text


@pytest.mark.parametrize(
    "content", ("private malformed data", "{}", '{"schema_version": 1, "clients": {}}')
)
def test_bad_ledger_fails_without_printing_its_contents(
    content, runner, monkeypatch, capsys
):
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: content)
    assert runner.main(["--coverage"]) == 1
    assert capsys.readouterr().out.strip() == (
        "ERROR: CLI coverage ledger is invalid; no client was run."
    )


def test_ledger_status_drift_fails_without_releasing_untrusted_labels(
    runner, monkeypatch, capsys
):
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["clients"]["grok"]["runner"] = "private-untrusted-status"
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: json.dumps(ledger))
    assert runner.main(["--coverage"]) == 1
    output = capsys.readouterr().out
    assert "CLI coverage ledger is invalid" in output
    assert "private" not in output


def test_unreadable_ledger_fails_without_leaking_a_filesystem_error(
    runner, monkeypatch, capsys
):
    def unavailable(*a, **kw):
        raise OSError("private filesystem error")

    monkeypatch.setattr(Path, "read_text", unavailable)
    assert runner.main(["--coverage"]) == 1
    assert "private" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "option",
    (
        ["--cli-name", "grok"],
        ["--image", "supplied"],
        ["--agent", "default"],
        ["--cli-version", "2.0.24"],
        ["--wheel", "unused.whl"],
        ["--keep"],
        ["--accept-proprietary-tos"],
        ["--diagnose-sandbox", "ag-cli-smoke-grok-1234abcd"],
    ),
)
def test_inventory_cannot_silently_ignore_smoke_options(
    option, runner, monkeypatch, capsys
):
    monkeypatch.setattr(
        runner, "_coverage_report", lambda: pytest.fail("ignored run options")
    )
    with pytest.raises(SystemExit) as error:
        runner.main(["--coverage", *option])
    assert error.value.code == 2
    assert (
        "--coverage cannot be combined with smoke-run options"
        in capsys.readouterr().err
    )


def test_audited_client_host_settings_and_credentials_do_not_enter_smoke(
    runner, tmp_path, monkeypatch
):
    names = (
        "AGY_AUTH",
        "ANTIGRAVITY_CONFIG",
        "COPILOT_TOKEN",
        "CRUSH_GLOBAL_CONFIG",
        "GROK_HOME",
        "KIRO_API_KEY",
        "OPENCLAW_CONFIG_PATH",
        "XAI_API_KEY",
        "GOOSE_PATH_ROOT",
    )
    for name in names:
        monkeypatch.setenv(name, "private-host-setting")
    environment = runner.sanitized_host_environment(tmp_path / "empty-home")
    assert all(name not in environment for name in names)
    assert "private-host-setting" not in json.dumps(environment)


def test_openclaw_exclusion_tracks_the_missing_required_native_manifest(
    tmp_path, monkeypatch
):
    """Do not fabricate a smoke-only plugin when product setup cannot register it.

    OpenClaw 2026.11.3 requires openclaw.plugin.json even for filesystem loads.
    When setup gains that native surface, revisit the explicit exclusion instead
    of silently keeping a permanently missing lane.
    """
    from ai_guardian.setup import hooks

    plugin = tmp_path / "openclaw-plugin"
    monkeypatch.setattr(hooks.IDESetup, "get_config_path", lambda *a, **kw: str(plugin))
    monkeypatch.setattr(
        hooks.IDESetup, "verify_gitleaks_installed", lambda *a: (True, "available")
    )
    monkeypatch.setattr(hooks, "_resolve_binary_path", lambda: "ai-guardian")
    success, _message = hooks.IDESetup().setup_ide_hooks("openclaw")
    assert success
    assert {file.name for file in plugin.iterdir()} == {
        "index.ts",
        "package.json",
        "ai-guardian-bridge.ts",
    }
    assert not (plugin / "openclaw.plugin.json").exists()


@pytest.mark.parametrize("cli", ("copilot", "antigravity", "kiro", "openclaw", "crush"))
def test_blocked_clients_exit_nonzero_before_any_runtime_or_installation(
    cli, runner, monkeypatch, capsys
):
    for method in ("_run", "_exec", "build_current_image", "_temp_parent"):
        monkeypatch.setattr(runner, method, lambda *a, **kw: pytest.fail("side effect"))
    with pytest.raises(SystemExit) as result:
        runner.main(["--cli-name", cli, "--agent", "default", "--image", "supplied"])
    assert result.value.code == 2
    text = capsys.readouterr().err
    assert runner.BLOCKED_SMOKE_CLIS[cli] in text
    assert f"docs/REAL_AGENT_CLI_COVERAGE.md#{cli}" in text
    assert "no client was run" in text


@pytest.mark.parametrize(
    "output,exit_code,expected",
    [
        ("grok 1.0.41\n", 0, True),
        ("1.0.41\n", 0, True),
        ("grok 1.0.42\nprivate diagnostic", 0, False),
        ("grok 1.0.41-beta.1\n", 0, False),
        ("grok 1.0.41+unreviewed\n", 0, False),
        ("grok 1.0.41\n", 1, False),
        ("unknown private diagnostic", 0, False),
    ],
)
def test_grok_exact_version_preflight_is_private_and_never_rebuilds(
    output, exit_code, expected, runner, monkeypatch, capsys
):
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda *a: subprocess.CompletedProcess(a, exit_code, output, "private stderr"),
    )
    assert runner._verify_grok_version("docker", "owned", 2) is expected
    text = capsys.readouterr().out
    assert "private" not in text
    if not expected:
        assert "no image was rebuilt" in text


def test_grok_invocation_uses_local_model_without_granting_native_hook_trust(runner):
    command = runner.build_agent_command("grok", "default", "synthetic prompt")
    assert command[:4] == ["grok", "--no-auto-update", "-p", "synthetic prompt"]
    assert command[command.index("--model") + 1] == runner.MOCK_MODEL
    assert command[command.index("--output-format") + 1] == "json"
    assert command[command.index("--allow") + 1] == (
        "Bash(python3 /tmp/ai_guardian_agent_cli_mock_provider.py --tool-case clean_tool)"
    )
    assert not {
        "--trust",
        "--always-approve",
        "--yolo",
        "--dangerously-skip-permissions",
    }.intersection(command)
    assert runner.build_agent_environment("grok") == [
        "GROK_HOME=/sandbox/.grok",
        f"XAI_API_KEY={runner.MOCK_KEY}",
    ]
    with pytest.raises(ValueError, match="Grok's default agent"):
        runner._validate_agent("grok", "unreviewed-agent")


def test_a_blocked_cli_has_no_fallback_case_profile(runner):
    with pytest.raises(ValueError, match="no credential-free smoke path"):
        runner.smoke_cases("copilot")


def test_grok_model_configuration_preserves_mcp_hooks_and_is_idempotent(
    runner, tmp_path, monkeypatch
):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = tmp_path / ".grok/config.toml"
    config.parent.mkdir()
    original = (
        '[mcp_servers.guardian]\ncommand = "ai-guardian"\n[hooks]\nenabled = true\n'
    )
    config.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure",
            json.dumps(
                {
                    "cli_name": "grok",
                    "agent": "default",
                    "workspace": "/sandbox/repo",
                    "base_url": runner.MOCK_URL,
                    "api_key": runner.MOCK_KEY,
                    "model": runner.MOCK_MODEL,
                }
            ),
        ],
    )
    for _ in range(2):
        exec(runner._CONFIGURE_AGENT, {})
    text = config.read_text(encoding="utf-8")
    assert text.startswith(original)
    assert text.count("[model.ag-smoke]") == 1
    model = tomllib.loads(text)["model"][runner.MOCK_MODEL]
    assert model["base_url"] == runner.MOCK_URL
    assert model["api_backend"] == "chat_completions"
    assert model["env_key"] == "XAI_API_KEY"
    assert runner.MOCK_KEY not in text
    assert not (tmp_path / ".grok/trusted_folders.toml").exists()
    conflicting = text.replace(runner.MOCK_URL, "http://127.0.0.1:1/v1")
    config.write_text(conflicting, encoding="utf-8")
    with pytest.raises(SystemExit, match="Conflicting smoke model configuration"):
        exec(runner._CONFIGURE_AGENT, {})
    assert config.read_text(encoding="utf-8") == conflicting


@pytest.mark.parametrize("version_ok", (True, False))
def test_grok_supplied_image_lifecycle_runs_only_partial_cases_and_cleans_up(
    version_ok, runner, tmp_path, monkeypatch, capsys
):
    cases, commands = [], []
    owned_parent = tmp_path / "owned-smoke-parent"
    owned_parent.mkdir()
    monkeypatch.setattr(runner.shutil, "which", lambda executable: "/available")
    monkeypatch.setattr(runner, "_temp_parent", lambda: str(owned_parent))
    monkeypatch.setattr(runner, "sanitized_host_environment", lambda home: {})
    monkeypatch.setattr(
        runner, "build_current_image", lambda *a, **kw: pytest.fail("hidden build")
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda command, *a, **kw: commands.append(command)
        or subprocess.CompletedProcess(command, 0, "", ""),
    )
    for method in (
        "_create_internal_network",
        "_wait_for_sandbox_ready",
        "_check_sandbox_rest",
        "_configure_agent",
        "_start_mock",
    ):
        monkeypatch.setattr(runner, method, lambda *a: True)
    monkeypatch.setattr(runner, "_verify_grok_version", lambda *a: version_ok)
    monkeypatch.setattr(
        runner, "_run_case", lambda *a, **kw: cases.append(a[4].name) or True
    )
    assert runner.main(
        [
            "--cli-name",
            "grok",
            "--agent",
            "default",
            "--image",
            "current-wheel",
            "--container-engine",
            "docker",
            "--ai-guardian-command",
            "ai-guardian",
        ]
    ) == (0 if version_ok else 1)
    assert cases == (
        ["ssrf", "config_exfil", "command_credential", "clean_tool", "allowed"]
        if version_ok
        else []
    )
    assert any(command[1:3] == ["sandbox", "delete"] for command in commands)
    assert not any(command[1:3] == ["image", "rm"] for command in commands)
    assert list(owned_parent.iterdir()) == []
    assert (
        "prompt denial and sensitive-output containment are NOT QUALIFIED"
        in capsys.readouterr().out
    )
