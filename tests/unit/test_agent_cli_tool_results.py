"""Provider-boundary and hook-stage evidence; no containers or live providers."""

import importlib.util
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_tool_tests", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provider():
    return load_script("agent_cli_mock_provider")


def command_catalog(protocol, tools):
    """Wrap synthetic name/schema pairs in each supported provider catalog."""
    if protocol == "chat":
        return {
            "tools": [
                {"type": "function", "function": {"name": name, "parameters": schema}}
                for name, schema in tools
            ]
        }
    if protocol == "responses":
        return {
            "tools": [
                {"type": "function", "name": name, "parameters": schema}
                for name, schema in tools
            ]
        }
    if protocol == "anthropic":
        return {
            "tools": [{"name": name, "input_schema": schema} for name, schema in tools]
        }
    return {
        "tools": [
            {
                "functionDeclarations": [
                    {"name": name, "parameters": schema} for name, schema in tools
                ]
            }
        ]
    }


def offered_command(provider, protocol, payload, case, request_numbers):
    """Return the offered tool name/arguments, or None for a final text reply."""
    response = getattr(provider, f"{protocol}_response")(
        payload, case, *request_numbers
    )
    if protocol == "chat":
        calls = response["choices"][0]["message"].get("tool_calls", [])
        if calls:
            call = calls[0]["function"]
            return call["name"], json.loads(call["arguments"])
    elif protocol == "responses":
        call = response["output"][0]
        if call["type"] == "function_call":
            return call["name"], json.loads(call["arguments"])
    elif protocol == "anthropic":
        call = response["content"][0]
        if call["type"] == "tool_use":
            return call["name"], call["input"]
    else:
        call = response["candidates"][0]["content"]["parts"][0].get("functionCall")
        if call:
            return call["name"], call["args"]
    return None


@pytest.mark.parametrize(
    ("protocol", "native_name", "argument", "field_type"),
    (
        ("chat", "bash", "command", "string"),
        ("chat", "shell", "command", "string"),
        ("anthropic", "Bash", "command", "string"),
        ("responses", "shell", "command", "array"),
        ("responses", "exec_command", "cmd", "string"),
        ("responses", "shell_command", "command", "string"),
        ("gemini", "run_shell_command", "command", "string"),
    ),
)
@pytest.mark.parametrize(
    "case",
    (
        "ssrf",
        "config_exfil",
        "command_credential",
        "clean_tool",
        "tool_output_secret",
        "tool_output_pii",
    ),
)
def test_mock_selects_native_shell_instead_of_an_earlier_advisory_checker(
    provider, protocol, native_name, argument, field_type, case
):
    command_schema = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }
    native_schema = {
        "type": "object",
        "properties": {argument: {"type": field_type}},
        "required": [argument],
    }
    payload = command_catalog(
        protocol,
        [
            ("ai-guardian_check_command", command_schema),
            ("mcp__other__shell", command_schema),
            ("custom_command_helper", command_schema),
            (native_name, native_schema),
        ],
    )
    request_numbers = provider._record_request(case, payload)
    assert request_numbers == (1, 1)
    name, arguments = offered_command(
        provider, protocol, payload, case, request_numbers
    )
    assert name == native_name
    expected = provider.TOOL_COMMANDS[case]
    if field_type == "array":
        expected = ["bash", "-lc", expected]
    assert arguments[argument] == expected
    stats = provider._stats()
    assert stats["tool_offers"] == {case: 1}
    assert stats["command_tool_names"] == {case: {native_name.casefold(): 1}}
    assert all(
        tool_name not in json.dumps(stats)
        for tool_name in (
            "ai-guardian_check_command",
            "mcp__other__shell",
            "custom_command_helper",
        )
    )


@pytest.mark.parametrize("protocol", ("chat", "responses", "anthropic", "gemini"))
def test_advisory_or_unknown_command_tools_never_count_as_a_native_tool_offer(
    provider, protocol
):
    schema = {"type": "object", "properties": {"command": {"type": "string"}}}
    payload = command_catalog(
        protocol,
        [
            (name, schema)
            for name in (
                "ai-guardian_check_command",
                "mcp__other__bash",
                "custom_command_helper",
            )
        ],
    )
    assert provider._find_command_tool(payload) is None
    request_numbers = provider._record_request("clean_tool", payload)
    assert request_numbers == (1, 0)
    assert (
        offered_command(provider, protocol, payload, "clean_tool", request_numbers)
        is None
    )
    assert provider._stats()["tool_offers"] == {}
    assert provider._stats()["command_tool_requests"] == {}
    assert provider._stats()["command_tool_names"] == {}
    assert provider.TOOL_IDENTITIES == {}
    assert provider.GEMINI_TOOL_CASES == {}


def test_an_advisory_only_preflight_does_not_consume_the_native_tool_offer(provider):
    schema = {"type": "object", "properties": {"command": {"type": "string"}}}
    advisory = command_catalog("chat", [("ai-guardian_check_command", schema)])
    assert provider._record_request("clean_tool", advisory) == (1, 0)
    native = command_catalog(
        "chat", [("ai-guardian_check_command", schema), ("bash", schema)]
    )
    numbers = provider._record_request("clean_tool", native)
    assert numbers == (2, 1)
    name, _arguments = offered_command(provider, "chat", native, "clean_tool", numbers)
    assert name == "bash"


def result_payload(provider, protocol, case, output):
    tool = {
        "name": "bash",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
    }
    if protocol == "chat":
        response = provider.chat_response(
            {"tools": [{"type": "function", "function": tool}]}, case, 1
        )
        call = response["choices"][0]["message"]["tool_calls"][0]
        return {
            "messages": [
                {"role": "tool", "tool_call_id": call["id"], "content": output}
            ]
        }
    if protocol == "responses":
        response = provider.responses_response(
            {"tools": [{"type": "function", **tool}]}, case, 1
        )
        call = response["output"][0]
        return {
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": output,
                }
            ]
        }
    if protocol == "anthropic":
        response = provider.anthropic_response(
            {"tools": [{"name": "bash", "input_schema": tool["parameters"]}]}, case, 1
        )
        call = response["content"][0]
        return {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": output,
                        }
                    ],
                }
            ]
        }
    provider.gemini_response({"tools": [{"functionDeclarations": [tool]}]}, case, 1)
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "bash",
                            "response": {"output": output},
                        }
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize("protocol", ("chat", "responses", "anthropic", "gemini"))
def test_clean_tool_requires_a_correlated_result_not_a_tool_offer(provider, protocol):
    output = provider.tool_output("clean_tool")
    payload = result_payload(provider, protocol, "clean_tool", output)
    assert provider._stats()["clean_tool_results"].get("clean_tool", 0) == 0
    provider._observe_request(payload)
    assert provider._stats()["clean_tool_results"]["clean_tool"] == 1
    assert provider.request_case(payload) == "clean_tool"


def test_responses_function_output_diagnostics_retain_only_shape_counts(provider):
    identity = provider._issued_tool_id("clean_tool", "call_")
    payload = {
        "input": [
            {
                "type": "function_call_output",
                "call_id": identity,
                "output": {"success": True, "output": "private-output-sentinel"},
            }
        ]
    }

    provider._observe_request(payload)
    stats = provider._stats()

    assert stats["function_call_outputs"] == {"clean_tool": 1}
    assert stats["known_function_call_outputs"] == {"clean_tool": 1}
    assert stats["unknown_function_call_outputs"] == {"clean_tool": 0}
    assert stats["function_call_output_shapes"] == {"clean_tool": {"object_success": 1}}
    assert stats["function_call_output_categories"] == {"clean_tool": {"other_text": 1}}
    assert "private-output-sentinel" not in json.dumps(stats)


def test_responses_function_output_diagnostics_count_unknown_ids(provider):
    payload = {
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "AGENT_CLI_SMOKE_CASE: clean_tool"}
                ],
            },
            {
                "type": "function_call_output",
                "call_id": "unrecognized-call-id",
                "output": "No function found for this tool invocation",
            },
        ]
    }

    provider._observe_request(payload)
    stats = provider._stats()

    assert stats["function_call_outputs"] == {"clean_tool": 1}
    assert stats["known_function_call_outputs"] == {"clean_tool": 0}
    assert stats["unknown_function_call_outputs"] == {"clean_tool": 1}
    assert stats["function_call_output_shapes"] == {"clean_tool": {"string": 1}}
    assert stats["function_call_output_categories"] == {
        "clean_tool": {"unresolved_tool": 1}
    }
    assert "No function found" not in json.dumps(stats)


@pytest.mark.parametrize(
    ("output", "category"),
    (
        ("approval policy is never; reject command", "approval_policy_rejected"),
        ("approval request is unavailable", "approval_reference"),
        ("permission denied", "permission_denied"),
        ("bwrap: setting up uid map: Permission denied", "permission_denied_bwrap"),
        ("Permission denied creating a namespace", "permission_denied_namespace"),
        ("operation not permitted", "operation_not_permitted"),
        ("permission check failed", "permission_reference"),
        ("sandbox denied the operation", "sandbox_reference"),
        ("execution policy rejected the operation", "policy_reference"),
    ),
)
def test_function_call_output_categories_use_fixed_policy_labels(
    provider, output, category
):
    assert provider._function_call_output_category("clean_tool", output) == category
    assert output not in json.dumps({"category": category})


@pytest.mark.parametrize("protocol", ("chat", "responses", "anthropic", "gemini"))
def test_json_encoded_native_result_retains_exact_clean_evidence(provider, protocol):
    output = json.dumps(
        {"exit": 0, "output": provider.tool_output("clean_tool"), "truncated": False}
    )
    payload = result_payload(provider, protocol, "clean_tool", output)
    provider._observe_request(payload)
    assert provider._stats()["clean_tool_results"] == {"clean_tool": 1}
    assert output not in json.dumps(provider._stats())
    provider.TOOL_IDENTITIES.clear()
    provider.GEMINI_TOOL_CASES.clear()
    provider.CLEAN_TOOL_RESULT_COUNTS.clear()
    provider._observe_request(payload)
    assert provider._stats()["clean_tool_results"] == {}


def test_json_encoded_prompt_cannot_impersonate_a_native_result(provider):
    output = json.dumps({"output": provider.tool_output("clean_tool")})
    provider._observe_request({"messages": [{"role": "user", "content": output}]})
    assert provider._stats()["clean_tool_results"] == {}


def test_clean_output_flattened_into_a_summary_is_not_native_result_evidence(provider):
    payload = result_payload(
        provider, "chat", "clean_tool", provider.tool_output("clean_tool")
    )
    identity = payload["messages"][0]["tool_call_id"]
    payload["messages"][0]["role"] = "user"
    provider._observe_request(payload)
    assert provider._known_tool_case(identity) == "clean_tool"
    assert provider._stats()["clean_tool_results"] == {}


@pytest.mark.parametrize("protocol", ("chat", "responses", "anthropic", "gemini"))
@pytest.mark.parametrize("case", ("tool_output_secret", "tool_output_pii"))
def test_mock_detects_raw_sensitive_tool_results_without_retaining_them(
    provider, protocol, case, capsys
):
    output = provider.tool_output(case)
    payload = result_payload(provider, protocol, case, output)
    provider._observe_request(payload)
    stats = provider._stats()
    assert stats["raw_tool_output_requests"][case] == 1
    assert output not in json.dumps(stats)
    assert provider.sensitive_value(case) not in json.dumps(stats)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("protocol", ("chat", "responses", "anthropic", "gemini"))
def test_unrelated_result_does_not_prove_clean_tool_execution(provider, protocol):
    payload = result_payload(provider, protocol, "clean_tool", "an unrelated result")
    provider._observe_request(payload)
    assert provider._stats()["clean_tool_results"].get("clean_tool", 0) == 0


def test_sensitive_output_in_non_tool_messages_is_still_a_delivery_failure(provider):
    case = "tool_output_secret"
    provider._observe_request(
        {"messages": [{"role": "assistant", "content": provider.sensitive_value(case)}]}
    )
    assert provider._stats()["raw_tool_output_requests"][case] == 1


def test_structured_numeric_pii_is_also_detected_at_the_provider_boundary(provider):
    case = "tool_output_pii"
    provider._observe_request(
        {"output": {"value": int(provider.sensitive_value(case))}}
    )
    assert provider._stats()["raw_tool_output_requests"][case] == 1


def test_gemini_continuations_remain_correlated_when_the_tool_name_is_reused(provider):
    for case in ("clean_tool", "tool_output_secret", "tool_output_pii"):
        payload = result_payload(provider, "gemini", case, "Tool output withheld.")
        assert provider.request_case(payload) == case
    assert provider.TOOL_IDENTITIES == {}


def test_clean_output_in_a_prompt_cannot_impersonate_a_tool_result(provider):
    provider._observe_request(
        {"messages": [{"role": "user", "content": provider.tool_output("clean_tool")}]}
    )
    assert provider._stats()["clean_tool_results"] == {}


@pytest.mark.parametrize("protocol", ("chat", "responses", "anthropic", "gemini"))
def test_unissued_tool_identity_cannot_prove_a_clean_result(provider, protocol):
    payload = result_payload(
        provider, protocol, "clean_tool", provider.tool_output("clean_tool")
    )
    provider.TOOL_IDENTITIES.clear()
    provider.GEMINI_TOOL_CASES.clear()
    provider._observe_request(payload)
    assert provider._stats()["clean_tool_results"] == {}


@pytest.mark.parametrize(
    "path", ("/v1/messages/count_tokens", "/v1beta/models/gemini-2.5-flash:countTokens")
)
def test_token_count_endpoints_also_detect_sensitive_output_delivery(
    provider, path, capsys
):
    server = provider.ThreadingHTTPServer(
        ("127.0.0.1", 0), provider.MockProviderHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        case = "tool_output_secret"
        body = json.dumps(
            {"messages": [{"role": "user", "content": provider.sensitive_value(case)}]}
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read()
        assert provider._stats()["raw_tool_output_requests"][case] == 1
        assert provider._stats()["requests"] == {}
        assert capsys.readouterr().out == ""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "payload",
    (
        {"contents": None, "messages": None, "input": None},
        {
            "contents": [{"parts": None}],
            "messages": [{"role": "tool", "tool_call_id": []}],
        },
        {"input": [{"type": "function_call_output", "call_id": {}}]},
    ),
)
def test_malformed_result_shapes_do_not_create_evidence_or_dump_payloads(
    provider, payload, capsys
):
    provider._observe_request(payload)
    assert provider._stats()["clean_tool_results"] == {}
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "case", ("clean_tool", "tool_output_secret", "tool_output_pii")
)
def test_tool_fixture_records_execution_without_putting_values_in_the_witness(
    provider, case, tmp_path, capsys
):
    assert provider.run_tool_case(case, tmp_path) == 0
    output = capsys.readouterr().out
    assert output == provider.tool_output(case)
    assert (tmp_path / f"{case}.executed").read_text(encoding="ascii") == "executed\n"
    if case != "clean_tool":
        assert (
            provider.sensitive_value(case)
            not in (tmp_path / f"{case}.executed").read_text()
        )


def test_tool_fixture_rejects_reexecution_without_overwriting_its_witness(
    provider, tmp_path, capsys
):
    provider.run_tool_case("clean_tool", tmp_path)
    capsys.readouterr()
    with pytest.raises(FileExistsError):
        provider.run_tool_case("clean_tool", tmp_path)
    assert capsys.readouterr() == ("", "")
    assert (tmp_path / "clean_tool.executed").read_text(
        encoding="ascii"
    ) == "executed\n"


def test_output_failure_cannot_publish_a_completed_execution_witness(
    provider, tmp_path, monkeypatch
):
    class BrokenOutput:
        def write(self, _text):
            raise OSError("output unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(provider.sys, "stdout", BrokenOutput())
        with pytest.raises(OSError, match="output unavailable"):
            provider.run_tool_case("clean_tool", tmp_path)
    assert (tmp_path / "clean_tool.executed").read_text(encoding="ascii") == ""


def test_unknown_tool_fixture_does_not_execute_or_create_files(
    provider, tmp_path, capsys
):
    directory = tmp_path / "tool-witnesses"
    assert provider.run_tool_case("unknown", directory) == 1
    assert not directory.exists()
    assert capsys.readouterr() == ("", "")


def test_output_fixtures_are_detectable_but_prompts_and_commands_are_clean(provider):
    from ai_guardian.scanners.secret_redactor import SecretRedactor
    from ai_guardian.scanners.toml_patterns import TomlPatternsScanner

    runner = load_script("agent_cli_test")
    strict = json.loads(runner.STRICT_PROFILE.read_text(encoding="utf-8"))
    secrets = TomlPatternsScanner()
    pii = SecretRedactor(
        config={"enabled": True}, pii_config=strict["scan_pii"], pii_only=True
    )

    assert bool(secrets.scan(provider.tool_output("tool_output_secret")))
    assert bool(pii.redact(provider.tool_output("tool_output_pii"))["redactions"])
    for case in runner.CASES:
        if case.name in provider.OUTPUT_CASES:
            for text in (case.prompt, provider.TOOL_COMMANDS[case.name]):
                assert not secrets.scan(text)
                assert not pii.redact(text)["redactions"]
    assert not secrets.scan(provider.tool_output("clean_tool"))
    assert not pii.redact(provider.tool_output("clean_tool"))["redactions"]


@pytest.fixture
def smoke_config(tmp_path, monkeypatch):
    from ai_guardian.config import loaders

    runner = load_script("agent_cli_test")
    config_dir = tmp_path / "smoke-config"
    runner.write_smoke_config(config_dir)
    config = json.loads((config_dir / "ai-guardian.json").read_text(encoding="utf-8"))
    # All config loaders consume only this disposable smoke config, not the host's
    # policy. No external scanners, pattern downloads or daemon are required.
    monkeypatch.setattr(loaders, "_load_config_file", lambda: (config, None))
    monkeypatch.setattr(loaders, "_load_pattern_server_config", lambda: (None, None))
    return config


@pytest.mark.parametrize("case", ("tool_output_secret", "tool_output_pii"))
def test_prepared_smoke_config_requests_sanitized_post_tool_output(
    provider, smoke_config, monkeypatch, tmp_path, case
):
    from ai_guardian import process_hook_data

    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *args, **kwargs: (
            case == "tool_output_secret",
            "Synthetic secret detected" if case == "tool_output_secret" else None,
        ),
    )
    result = process_hook_data(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "smoke-config-fixture",
            "session_id": "smoke-config-fixture",
            "cwd": str(tmp_path),
            "tool_input": {"command": provider.TOOL_COMMANDS[case]},
            "tool_response": {"stdout": provider.tool_output(case), "stderr": ""},
        }
    )
    payload = json.loads(result["output"])
    replacement = payload["hookSpecificOutput"]["updatedToolOutput"]
    assert replacement["stdout"]
    assert provider.sensitive_value(case) not in json.dumps(payload)
    assert payload.get("decision") != "block"
    assert result["exit_code"] == 0


@pytest.mark.parametrize(
    "case", ("clean_tool", "tool_output_secret", "tool_output_pii")
)
@pytest.mark.parametrize("structured", (False, True))
def test_gemini_native_smoke_output_is_clean_or_natively_denied(
    provider, smoke_config, monkeypatch, tmp_path, case, structured
):
    from ai_guardian import process_hook_data

    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *args, **kwargs: (
            case == "tool_output_secret",
            "Synthetic secret detected" if case == "tool_output_secret" else None,
        ),
    )
    text = provider.tool_output(case)
    result = process_hook_data(
        {
            "hook_event_name": "AfterTool",
            "tool_name": "run_shell_command",
            "transcript_path": str(tmp_path / "gemini-session.jsonl"),
            "cwd": str(tmp_path),
            "session_id": "gemini-native-output",
            "tool_input": {"command": provider.TOOL_COMMANDS[case]},
            "tool_response": {
                "llmContent": [{"text": text}] if structured else text,
                "returnDisplay": text,
            },
        }
    )
    response = json.loads(result["output"])
    if case == "clean_tool":
        assert response.get("decision") != "deny"
        assert not result.get("_blocked")
    else:
        assert response["decision"] == "deny"
        assert result["_blocked"] is True
        assert provider.sensitive_value(case) not in json.dumps(response)
        assert "updatedToolOutput" not in json.dumps(response)


@pytest.mark.parametrize("event", ("UserPromptSubmit", "PreToolUse"))
@pytest.mark.parametrize("case_name", ("secret", "pii"))
def test_prepared_smoke_config_keeps_sensitive_input_blocked(
    smoke_config, monkeypatch, tmp_path, event, case_name
):
    from ai_guardian import process_hook_data

    runner = load_script("agent_cli_test")
    case = next(case for case in runner.CASES if case.name == case_name)
    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *args, **kwargs: (
            case_name == "secret",
            "Synthetic secret detected" if case_name == "secret" else None,
        ),
    )
    hook_data = {"hook_event_name": event, "cwd": str(tmp_path)}
    if event == "UserPromptSubmit":
        hook_data["prompt"] = case.prompt
    else:
        fixture = tmp_path / "synthetic-input.txt"
        fixture.write_text(case.prompt, encoding="utf-8")
        hook_data.update(tool_name="Read", tool_input={"file_path": str(fixture)})
    payload = json.loads(process_hook_data(hook_data)["output"])
    if event == "UserPromptSubmit":
        assert payload["decision"] == "block"
    else:
        assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("case_name", ("ssrf", "config_exfil"))
def test_pi_native_shell_runs_the_real_smoke_command_scanners(
    provider, smoke_config, monkeypatch, tmp_path, case_name
):
    from ai_guardian import process_hook_data

    runner = load_script("agent_cli_test")
    case = next(case for case in runner.CASES if case.name == case_name)
    log = Mock(return_value="pi-native-finding")
    monkeypatch.setattr(
        "ai_guardian.violations.logger.ViolationLogger.log_violation", log
    )
    result = process_hook_data(
        {
            "hook_event_name": "PreToolUse",
            "pi_version": "0.86.0",
            "hook_source": "pi",
            "tool_name": "bash",
            "tool_use": {
                "name": "bash",
                "input": {"command": provider.TOOL_COMMANDS[case_name]},
            },
            "tool_use_id": "pi-native-pre-tool",
            "session_id": "pi-command-scanner",
            "cwd": str(tmp_path),
        }
    )
    response = json.loads(result["output"])
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert result["_blocked"] is True
    assert result["_violation_type"] == "tool_permission"
    assert any(
        call.kwargs.get("violation_type") == case.expected_violation
        for call in log.call_args_list
    )


@pytest.mark.parametrize(
    "case", ("clean_tool", "tool_output_secret", "tool_output_pii")
)
def test_pi_native_shell_preserves_clean_output_and_safe_replacement(
    provider, smoke_config, monkeypatch, tmp_path, case
):
    from ai_guardian import process_hook_data

    monkeypatch.setattr(
        "ai_guardian.scanners.secret_scanning.check_secrets",
        lambda *args, **kwargs: (
            case == "tool_output_secret",
            "Synthetic secret detected" if case == "tool_output_secret" else None,
        ),
    )
    result = process_hook_data(
        {
            "hook_event_name": "PostToolUse",
            "hook_source": "pi",
            "pi_version": "0.86.0",
            "tool_name": "bash",
            "tool_use": {
                "name": "bash",
                "input": {"command": provider.TOOL_COMMANDS[case]},
            },
            "tool_use_id": "pi-native-output",
            "session_id": "pi-native-output",
            "cwd": str(tmp_path),
            "tool_response": {"output": provider.tool_output(case)},
        }
    )
    response = json.loads(result["output"])
    assert not result.get("_blocked")
    assert result["exit_code"] == 0
    if case == "clean_tool":
        assert "updatedToolOutput" not in response.get("hookSpecificOutput", {})
    else:
        replacement = response["hookSpecificOutput"]["updatedToolOutput"]
        # Post-tool extraction retains Pi's native name; its extension accepts
        # this text replacement without requiring Claude's Bash result wrapper.
        assert isinstance(replacement, str) and replacement
        assert provider.sensitive_value(case) not in json.dumps(response)


def configure_case(
    monkeypatch, case_name, *, event_counts=None, observation=None, violations=None
):
    runner = load_script("agent_cli_test")
    case = next(case for case in runner.CASES if case.name == case_name)
    hook_reads = iter(
        (
            {},
            (
                event_counts
                if event_counts is not None
                else {"pretooluse": 1, "posttooluse": 1}
            ),
        )
    )
    violation_reads = iter(
        (
            {},
            (
                violations
                if violations is not None
                else ({case.expected_violation: 1} if case.expected_violation else {})
            ),
        )
    )
    request_reads = iter(({}, {case_name: 2}))
    observation_reads = iter(
        (
            {},
            (
                observation
                if observation is not None
                else {
                    "executed": 1,
                    "tool_offers": 1,
                    "clean_tool_results": int(case_name == "clean_tool"),
                    "raw_tool_output_requests": 0,
                }
            ),
        )
    )
    monkeypatch.setattr(
        runner, "_hook_counts", lambda *args, **kwargs: next(hook_reads)
    )
    monkeypatch.setattr(
        runner, "_violation_counts", lambda *args, **kwargs: next(violation_reads)
    )
    monkeypatch.setattr(
        runner, "_provider_stats", lambda *args, **kwargs: next(request_reads)
    )
    monkeypatch.setattr(
        runner, "_tool_evidence", lambda *args, **kwargs: next(observation_reads)
    )
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda command, *args, **kwargs: subprocess.CompletedProcess(
            command, 0, "private tool output", "private stderr"
        ),
    )
    return runner, case


@pytest.mark.parametrize(
    "case_name", ("clean_tool", "tool_output_secret", "tool_output_pii")
)
def test_tool_cases_require_execution_hook_and_provider_boundary_evidence(
    monkeypatch, case_name, capsys
):
    runner, case = configure_case(monkeypatch, case_name)
    assert runner._run_case("docker", "smoke", "opencode", "build", case, 30)
    assert "private" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "overrides",
    (
        {"event_counts": {"pretooluse": 1}},
        {"event_counts": {"posttooluse": 1}},
        {"observation": {"executed": 0, "tool_offers": 1, "clean_tool_results": 1}},
        {"observation": {"executed": 1, "tool_offers": 1, "clean_tool_results": 0}},
    ),
    ids=("no-post-hook", "no-pre-hook", "not-executed", "no-clean-result"),
)
def test_clean_tool_cannot_pass_with_missing_evidence(monkeypatch, overrides, capsys):
    runner, case = configure_case(monkeypatch, "clean_tool", **overrides)
    assert not runner._run_case("docker", "smoke", "opencode", "build", case, 30)
    assert "private" not in capsys.readouterr().out


@pytest.mark.parametrize("case_name", ("tool_output_secret", "tool_output_pii"))
def test_sensitive_case_fails_if_post_hook_logs_a_violation_but_raw_output_reaches_provider(
    monkeypatch, case_name, capsys
):
    runner, case = configure_case(
        monkeypatch,
        case_name,
        observation={"executed": 1, "tool_offers": 1, "raw_tool_output_requests": 1},
    )
    assert not runner._run_case("docker", "smoke", "opencode", "build", case, 30)
    assert "raw sensitive tool output reached the local mock" in capsys.readouterr().out


def test_prior_raw_output_delivery_is_not_baselined_away(monkeypatch):
    runner, case = configure_case(monkeypatch, "clean_tool")
    readings = iter(
        (
            {"raw_tool_output_requests": 1},
            {
                "executed": 1,
                "tool_offers": 1,
                "clean_tool_results": 1,
                "raw_tool_output_requests": 1,
            },
        )
    )
    monkeypatch.setattr(
        runner, "_tool_evidence", lambda *args, **kwargs: next(readings)
    )
    assert not runner._run_case("docker", "smoke", "opencode", "build", case, 30)


@pytest.mark.parametrize("field", ("violation_type", "hook_event"))
def test_log_reader_emits_counts_without_echoing_log_contents(tmp_path, field):
    runner = load_script("agent_cli_test")
    path = tmp_path / "events.jsonl"
    label = "sensitive_finding" if field == "violation_type" else "posttooluse"
    entry = json.dumps({field: label, "private": "private model output"})
    path.write_text(entry + "\nnot valid JSON\n" + entry + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", runner._READ_LOG_COUNTS, str(path), field],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {label: 2}
    assert "private" not in result.stdout + result.stderr


@pytest.mark.parametrize("post_events", (0, 1))
def test_pre_tool_denials_require_pre_event_and_cannot_be_passed_by_post_detection(
    monkeypatch, post_events
):
    runner, case = configure_case(
        monkeypatch, "ssrf", event_counts={"pretooluse": 1, "posttooluse": post_events}
    )
    assert runner._run_case("docker", "smoke", "opencode", "build", case, 30) is (
        post_events == 0
    )


@pytest.mark.parametrize("case_name", ("tool_output_secret", "tool_output_pii"))
def test_sensitive_case_requires_a_finding_even_when_output_is_withheld(
    monkeypatch, case_name
):
    runner, case = configure_case(monkeypatch, case_name, violations={})
    assert not runner._run_case("docker", "smoke", "opencode", "build", case, 30)


def test_hook_reader_releases_only_fixed_stage_counts(monkeypatch):
    runner = load_script("agent_cli_test")
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda command, *args, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"pretooluse": 1, "posttooluse": 2, "private-field": 9}),
        ),
    )
    assert runner._hook_counts("docker", "smoke", 30) == {
        "pretooluse": 1,
        "posttooluse": 2,
    }


def test_tool_evidence_reader_accepts_only_aggregate_counts(monkeypatch):
    runner = load_script("agent_cli_test")
    expected = {
        "executed": 1,
        "tool_offers": 1,
        "clean_tool_results": 1,
        "raw_tool_output_requests": 0,
        "function_call_outputs": 0,
        "known_function_call_outputs": 0,
        "unknown_function_call_outputs": 0,
        "function_call_output_string": 0,
        "function_call_output_object_success": 0,
        "function_call_output_object_other": 0,
        "function_call_output_array": 0,
        "function_call_output_null": 0,
        "function_call_output_scalar": 0,
        "function_call_output_category_expected_probe_output": 0,
        "function_call_output_category_unresolved_tool": 0,
        "function_call_output_category_unsupported_tool": 0,
        "function_call_output_category_invalid_arguments": 0,
        "function_call_output_category_hook_blocked": 0,
        "function_call_output_category_approval_policy_rejected": 0,
        "function_call_output_category_approval_reference": 0,
        "function_call_output_category_permission_denied": 0,
        "function_call_output_category_permission_denied_bwrap": 0,
        "function_call_output_category_permission_denied_namespace": 0,
        "function_call_output_category_operation_not_permitted": 0,
        "function_call_output_category_permission_reference": 0,
        "function_call_output_category_sandbox_reference": 0,
        "function_call_output_category_policy_reference": 0,
        "function_call_output_category_timeout": 0,
        "function_call_output_category_error_text": 0,
        "function_call_output_category_other_text": 0,
        "function_call_output_category_empty": 0,
        "native_tool_name_bash": 0,
        "native_tool_name_shell": 0,
        "native_tool_name_exec_command": 0,
        "native_tool_name_shell_command": 0,
        "native_tool_name_run_shell_command": 0,
    }
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, json.dumps(expected)
        ),
    )
    assert runner._tool_evidence("docker", "smoke", "clean_tool", 30) == expected


@pytest.mark.parametrize("stage", ("before", "after"))
def test_unavailable_hook_counters_cannot_pass_a_tool_case(monkeypatch, stage, capsys):
    runner, case = configure_case(monkeypatch, "clean_tool")
    readings = iter((None, {}) if stage == "before" else ({}, None))
    monkeypatch.setattr(runner, "_hook_counts", lambda *args, **kwargs: next(readings))
    assert not runner._run_case("docker", "smoke", "opencode", "build", case, 30)
    output = capsys.readouterr().out
    assert "FAIL clean_tool: could not read smoke counters" in output
    assert "private" not in output


@pytest.mark.parametrize("stdout", ("{}", '{"executed":true}', "private invalid data"))
def test_tool_evidence_reader_fails_closed_without_dumping_invalid_payload(
    monkeypatch, stdout, capsys
):
    runner = load_script("agent_cli_test")
    monkeypatch.setattr(
        runner,
        "_exec",
        lambda command, *args, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout, "private error"
        ),
    )
    diagnostics = []
    assert (
        runner._tool_evidence("docker", "smoke", "clean_tool", 30, diagnostics) is None
    )
    assert diagnostics == ["tool-evidence counter reader failed"]
    assert capsys.readouterr().out == ""
