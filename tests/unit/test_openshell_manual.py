"""Tests for the developer-only OpenShell smoke-test runner."""

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "container" / "tests" / "test_openshell_agents.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "manual_openshell_runner", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides):
    values = {
        "prompt": "hello",
        "codex_model": None,
        "claude_vertex_model": "claude-model-contract",
        "opencode_vertex_model": "google-vertex/claude-model-contract",
        "vertex_project": "contract-project",
        "vertex_region": "us-east5",
        "accept_proprietary_tos": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _qualification_args(**overrides):
    values = {
        "prompt": "hello",
        "image": "quay.io/example/ai-guardian-openshell:1.19.0",
        "repo": None,
        "openshell_cli": "openshell",
        "podman": "podman",
        "executor": "openshell",
        "timeout": 10,
        "keep": False,
        "codex_model": None,
        "claude_vertex_model": "claude-model-contract",
        "opencode_vertex_model": "google-vertex/claude-model-contract",
        "vertex_project": "contract-project",
        "vertex_region": "us-east5",
        "accept_proprietary_tos": True,
        "provider": [],
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_manual_runner_has_expected_cases():
    runner = _load_runner()

    assert set(runner.CASES) == {
        "codex",
        "claude-vertex",
        "opencode-claude-vertex",
    }


def test_manual_runner_builds_requested_cli_commands():
    runner = _load_runner()
    args = _args()

    assert runner.build_cli_command(runner.CASES["codex"], args) == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "hello",
    ]
    assert runner.build_cli_command(runner.CASES["claude-vertex"], args) == [
        "claude",
        "--bare",
        "--print",
        "hello",
        "--model",
        "claude-model-contract",
    ]
    assert runner.build_cli_command(runner.CASES["opencode-claude-vertex"], args) == [
        "opencode",
        "run",
        "--agent",
        "claude",
        "--model",
        "google-vertex/claude-model-contract",
        "hello",
    ]


def test_manual_runner_builds_vertex_create_contract_without_credentials():
    runner = _load_runner()
    args = _qualification_args()
    command = runner.build_create_command(
        ["ai-guardian"],
        "openshell",
        runner.CASES["opencode-claude-vertex"],
        args,
        "ag-ocv-test",
        {"opencode-claude-vertex": "gcp-provider"},
    )

    assert "--opencode-agent-profile" in command
    assert command[command.index("--opencode-agent-profile") + 1] == "claude"
    assert "--provider" in command
    assert command[command.index("--provider") + 1] == "gcp-provider"
    assert "--env" in command
    assert "GOOGLE_CLOUD_PROJECT=contract-project" in command
    assert "VERTEX_LOCATION=us-east5" in command
    assert "--" in command


def test_manual_runner_discards_model_output_in_smoke_mode(capsys):
    runner = _load_runner()
    model_output = "private model response"

    with patch.object(
        runner,
        "_execute_case_quiet",
        return_value=SimpleNamespace(
            returncode=0, stdout=model_output, stderr="private provider detail"
        ),
    ) as execute:
        result = runner._execute_case(
            "openshell",
            "podman",
            "openshell",
            "ag-clv-test",
            ["claude", "--print", "hello"],
            10,
        )

    assert result == 0
    assert execute.called
    captured = capsys.readouterr()
    assert model_output not in captured.out
    assert "private provider detail" not in captured.err


def test_manual_runner_discards_partial_output_on_command_timeout():
    runner = _load_runner()
    timeout = runner.subprocess.TimeoutExpired(
        cmd=["claude"], timeout=1, output="private model response", stderr="token"
    )

    with patch.object(runner.subprocess, "run", side_effect=timeout):
        result = runner._run_quiet(["claude", "--print", "hello"], 1)

    assert result is not None
    assert result.returncode == 124
    assert result.stdout == ""
    assert result.stderr == ""
    assert runner._step_from_result(result, failure_code="command_failed") == {
        "status": "failed",
        "exit_code": 124,
        "failure_code": "timed_out",
    }


def test_manual_runner_parses_provider_overrides_without_values():
    runner = _load_runner()

    assert runner.parse_provider_overrides(["codex=codex-provider"]) == {
        "codex": "codex-provider",
    }
    assert runner.parse_provider_overrides(["claude-vertex=gcp-provider"]) == {
        "claude-vertex": "gcp-provider"
    }


def test_manual_runner_generates_names_within_openshell_limit():
    runner = _load_runner()

    name = runner.sandbox_name("codex")

    assert len(name) <= 19
    assert name.startswith("ag-cdx-")


def test_manual_runner_closes_stdin_for_noninteractive_commands():
    runner = _load_runner()

    with patch.object(runner.subprocess, "run") as run:
        run.return_value.returncode = 0
        assert runner._run(["true"], 10) == 0

    assert run.call_args.kwargs["stdin"] is runner.subprocess.DEVNULL


def test_manual_runner_checks_for_partial_sandbox_after_failed_create():
    runner = _load_runner()

    with patch.object(runner.subprocess, "run") as run:
        run.return_value.returncode = 1
        assert runner._sandbox_exists("openshell", "ag-test") is False

    assert run.call_args.kwargs["stdin"] is runner.subprocess.DEVNULL
    assert run.call_args.kwargs["capture_output"] is True


def test_qualification_matrix_includes_codex_and_native_vertex_rows():
    runner = _load_runner()

    assert tuple(case.id for case in runner.QUALIFICATION_CASES) == (
        "codex-openshell",
        "claude-vertex-openshell",
        "opencode-claude-vertex-openshell",
    )
    assert [case.provider_class for case in runner.QUALIFICATION_CASES] == [
        "openshell-codex",
        "openshell-google-cloud",
        "openshell-google-cloud",
    ]
    assert runner.QUALIFICATION_CASES[0].requires_provider is True
    assert [case.requires_metadata for case in runner.QUALIFICATION_CASES] == [
        False,
        True,
        True,
    ]


def test_compatibility_report_validation_rejects_raw_output():
    runner = _load_runner()
    args = _qualification_args()
    with patch.object(runner, "_run_quiet", return_value=None):
        report = runner._build_compatibility_report(args, None)
    report["cases"].append(
        runner._qualification_case_record(runner.QUALIFICATION_CASES[0])
    )
    runner._update_report_summary(report)

    runner.validate_compatibility_report(report)
    report["image"]["reference"] = "raw_output"
    with pytest.raises(ValueError, match="raw-output"):
        runner.validate_compatibility_report(report)


def test_gateway_version_parser_uses_explicit_field_not_server_ip():
    runner = _load_runner()

    assert (
        runner._gateway_version_from_text(
            "Server: https://127.0.0.1:17670\nVersion: 0.1.3\n"
        )
        == "0.1.3"
    )
    assert (
        runner._gateway_version_from_text("Server: https://127.0.0.1:17670\n")
        == "unknown"
    )


def test_compatibility_report_records_image_digest_and_managed_cli_versions():
    runner = _load_runner()

    assert runner._normalise_package_version("ai_guardian-1.19.0-py3-none-any.whl") == (
        "1.19.0"
    )
    assert runner._normalise_package_version(
        "ai_guardian-1.19.0.dev1-py3-none-any.whl"
    ) == ("1.19.0.dev1")

    metadata = runner._image_metadata("quay.io/example/ai-guardian-openshell:1.19.0")

    assert metadata["tag"] == "1.19.0"
    assert metadata["digest"] == "unknown"
    assert metadata["base_digest"].startswith("sha256:")
    assert metadata["bundled_cli_versions"] == {
        "codex": "0.160.0",
        "opencode": "1.18.34",
    }


def test_compatibility_report_accepts_sha256_image_reference():
    runner = _load_runner()

    metadata = runner._image_metadata(
        "quay.io/example/ai-guardian-openshell@sha256:" + "b" * 64
    )

    assert metadata["tag"] == "latest"
    assert metadata["digest"] == "sha256:" + "b" * 64


def test_service_health_does_not_retain_service_url():
    runner = _load_runner()
    response = MagicMock(status=200)
    with (
        patch.object(
            runner,
            "_run_quiet",
            return_value=SimpleNamespace(
                returncode=0,
                stdout="http://sandbox--ai-guardian.openshell.localhost:1234/",
                stderr="",
            ),
        ),
        patch.object(runner, "urlopen") as open_url,
    ):
        open_url.return_value.__enter__.return_value = response
        assert runner._service_health("openshell", "ag-test", 10) is True

    open_url.assert_called_once()
    assert "api/health" in open_url.call_args.args[0]


def test_qualification_case_checks_detection_restart_and_cleanup_without_output():
    runner = _load_runner()
    args = _qualification_args()
    execute_results = [
        SimpleNamespace(returncode=0),  # daemon
        SimpleNamespace(returncode=0),  # agent
        SimpleNamespace(returncode=1),  # deterministic detection
        SimpleNamespace(returncode=0),  # reconnect
        SimpleNamespace(returncode=0),  # post-restart daemon
    ]

    def quiet_result(command, _timeout):
        if "sandbox" in command and "create" in command:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "sandbox" in command and "restart" in command:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "sandbox" in command and "delete" in command:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch.object(runner, "_run_quiet", side_effect=quiet_result),
        patch.object(runner, "_execute_case_quiet", side_effect=execute_results),
        patch.object(runner, "_service_health", side_effect=[True, True]),
        patch.object(runner, "_sandbox_exists", return_value=False),
    ):
        result = runner._qualify_case(
            runner.QUALIFICATION_CASES[0],
            args,
            ["ai-guardian"],
            {"codex": "codex-provider"},
        )

    assert result["result"] == "passed"
    assert result["steps"]["detection"] == {
        "status": "passed",
        "exit_code": 1,
        "failure_code": None,
    }
    assert result["steps"]["cleanup"]["status"] == "passed"


def test_metadata_readiness_probe_checks_emulator_without_retaining_response():
    runner = _load_runner()

    command = runner._metadata_readiness_command()

    assert command[:2] == ["/bin/bash", "-lc"]
    assert '"${GCE_METADATA_HOST:-}" = "127.0.0.1:8174"' in command[2]
    assert '"${GCE_METADATA_IP:-}" = "127.0.0.1:8174"' in command[2]
    assert "METADATA_SERVER_DETECTION" in command[2]
    assert "Metadata-Flavor: Google" in command[2]
    assert "/computeMetadata/v1/project/project-id" in command[2]
    assert "--output /dev/null" in command[2]


def test_metadata_failure_is_reported_without_running_or_logging_agent_output():
    runner = _load_runner()
    args = _qualification_args()
    executed = []

    def execute(_openshell, _podman, _executor, _name, command, _timeout):
        executed.append(list(command))
        if command[0] == "/bin/bash":
            return SimpleNamespace(returncode=7, stdout="", stderr="connection refused")
        if command[:2] == ["ai-guardian", "scan"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch.object(
            runner,
            "_run_quiet",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ),
        patch.object(runner, "_execute_case_quiet", side_effect=execute),
        patch.object(runner, "_service_health", return_value=True),
        patch.object(runner, "_sandbox_exists", return_value=False),
    ):
        result = runner._qualify_case(
            runner.QUALIFICATION_CASES[1], args, ["ai-guardian"], {}
        )

    assert result["result"] == "failed"
    assert result["steps"]["metadata"] == {
        "status": "failed",
        "exit_code": 7,
        "failure_code": "metadata_unavailable",
    }
    assert result["steps"]["agent"] == {
        "status": "not_run",
        "exit_code": None,
        "failure_code": "not_run_after_failure",
    }
    assert not any(command[0] == "claude" for command in executed)
    serialized = json.dumps(result).lower()
    assert "connection refused" not in serialized
    assert "contract-project" not in serialized
    assert "claude-model-contract" not in serialized


def test_creation_failure_classification_does_not_retain_provider_error_text():
    runner = _load_runner()
    provider_error = SimpleNamespace(
        stdout="Google Application Default Credentials were not found",
        stderr="provider details omitted",
    )

    assert runner._creation_failure_code(provider_error) == "provider_not_configured"


def test_qualification_mode_writes_the_codex_report(tmp_path):
    runner = _load_runner()
    args = _qualification_args(report=tmp_path / "compatibility.json")

    def passed_record(case, *_args):
        record = runner._qualification_case_record(case)
        record["result"] = "passed"
        for step in record["steps"].values():
            step.update(status="passed", exit_code=0, failure_code=None)
        return record

    with (
        patch.object(
            runner,
            "_run_quiet",
            side_effect=[
                SimpleNamespace(returncode=0, stdout="OpenShell 0.1.3", stderr=""),
                SimpleNamespace(returncode=0, stdout="OpenShell 0.1.3", stderr=""),
            ],
        ),
        patch.object(runner, "_command_available", return_value=True),
        patch.object(runner, "_qualify_case", side_effect=passed_record),
    ):
        assert runner._run_qualification(args, ["uv", "run", "ai-guardian"], {}) == 0

    report = json.loads(args.report.read_text(encoding="utf-8"))
    assert report["sanitized"] is True
    assert [case["id"] for case in report["cases"]] == [
        "codex-openshell",
        "claude-vertex-openshell",
        "opencode-claude-vertex-openshell",
    ]
    assert "api_key" not in json.dumps(report).lower()
