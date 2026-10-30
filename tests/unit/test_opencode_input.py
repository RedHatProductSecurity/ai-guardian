"""OpenCode native file arguments and safe policy diagnostics (#2627)."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from ai_guardian import __version__
from ai_guardian.config.utils import (
    clear_project_dir_override,
    set_project_dir_override,
)
from ai_guardian.hook_adapters.opencode import OpenCodeAdapter
from ai_guardian.tools.policy import ToolPolicyChecker


def _hook(tool_input, *, tool="read", cwd=None, **extra):
    return {
        "hook_event_name": "tool.execute.before",
        "hook_source": "opencode",
        "opencode_version": "2.0.24",
        "tool_name": tool,
        "tool_use": {"name": tool, "input": tool_input},
        **({"cwd": str(cwd)} if cwd else {}),
        **extra,
    }


@pytest.fixture
def checker():
    return ToolPolicyChecker(
        config={
            "permissions": {"rules": []},
            "agent_config_protection": {"enabled": False},
            "ssrf_protection": {"enabled": False},
        }
    )


@pytest.mark.parametrize("tool", ["read", "write", "edit"])
@pytest.mark.parametrize("key", ["path", "filePath", "file_path"])
def test_native_file_targets_are_checked_without_mutating_input(
    checker, tmp_path, tool, key
):
    args = {key: "README.md", "limit": 180}
    before = dict(args)
    hook = _hook(args, tool=tool, cwd=tmp_path)

    normalized = OpenCodeAdapter().normalize_input(hook)
    target = str(tmp_path / "README.md")
    assert normalized.tool_input["file_path"] == target
    assert normalized.file_path == target
    assert checker._extract_tool_info(hook)[1]["file_path"] == target
    assert checker.check_tool_allowed(hook)[0] is True
    assert args == before


@pytest.mark.parametrize("key", ["path", "filePath", "file_path"])
def test_protected_native_target_is_not_misclassified_as_missing(
    checker, key, tmp_path
):
    target = str(tmp_path / ".ai-guardian.json")
    hook = _hook({key: target}, cwd=tmp_path)
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        allowed, message, name = checker.check_tool_allowed(hook)

    assert allowed is False
    assert name == "Read"
    assert "missing" not in message.lower()
    record = logger.return_value.log_violation.call_args.kwargs
    assert record["blocked"]["file_path"] == target
    assert record["blocked"]["input_diagnostics"]["subreason"] == "immutable_protection"
    assert record["blocked"]["is_immutable"] is True
    assert record["suggestion"] == {}


@pytest.mark.parametrize("tool", ["glob", "grep", "custom_tool", "bash"])
def test_unrelated_path_arguments_are_not_file_aliases(tool):
    normalized = OpenCodeAdapter().normalize_input(_hook({"path": "src"}, tool=tool))
    assert "file_path" not in normalized.tool_input
    assert normalized.file_path is None


@pytest.mark.parametrize(
    "args,subreason",
    [
        ({"limit": 180}, "missing_argument"),
        ({"path": ""}, "empty_argument"),
        ({"path": "   "}, "empty_argument"),
        ({"path": None}, "invalid_argument"),
        ({"path": 123}, "invalid_argument"),
        ({"path": True}, "invalid_argument"),
        ({"path": []}, "invalid_argument"),
        ({"path": {"private": "PRIVATE_PAYLOAD"}}, "invalid_argument"),
        ({"path": "bad\x00path"}, "invalid_argument"),
        ({"path": None, "file_path": "safe.md"}, "invalid_argument"),
        ({"path": "one.md", "filePath": "other.md"}, "conflicting_arguments"),
        ({"path": "one.md", "file_path": "other.md"}, "conflicting_arguments"),
        ([], "invalid_argument"),
        ("PRIVATE_PAYLOAD", "invalid_argument"),
        (None, "invalid_argument"),
    ],
)
def test_invalid_inputs_fail_closed_with_value_free_diagnostics(
    checker, args, subreason
):
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        allowed, message, name = checker.check_tool_allowed(_hook(args))

    assert allowed is False
    assert name == "Read"
    assert "file_path" in message
    record = logger.return_value.log_violation.call_args.kwargs
    blocked = record["blocked"]
    diagnostics = blocked["input_diagnostics"]
    assert diagnostics["subreason"] == subreason
    assert diagnostics["expected_field"] == "path"
    assert diagnostics["native_tool_name"] == "read"
    assert diagnostics["canonical_tool_name"] == "Read"
    assert blocked["file_path"] is None
    assert blocked["is_immutable"] is True
    assert record["suggestion"] == {}
    assert "PRIVATE_PAYLOAD" not in json.dumps(
        record, default=lambda value: value.to_dict()
    )


def test_aliases_for_same_effective_path_remain_compatible(checker, tmp_path):
    hook = _hook(
        {
            "path": "./README.md",
            "filePath": "README.md",
            "file_path": str(tmp_path / "README.md"),
        },
        cwd=tmp_path,
    )
    assert checker.check_tool_allowed(hook)[0] is True


def test_native_payload_wins_over_conflicting_canonical_wrapper(checker, tmp_path):
    hook = _hook({"path": str(tmp_path / ".ai-guardian.json")}, cwd=tmp_path)
    hook["tool_input"] = {"file_path": str(tmp_path / "safe.md")}
    with patch("ai_guardian.violations.logger.ViolationLogger"):
        assert checker.check_tool_allowed(hook)[0] is False


def test_normalization_failure_retains_recoverable_target(checker, tmp_path):
    target = str(tmp_path / "README.md")
    hook = _hook({"path": target, "limit": 180}, cwd=tmp_path)
    with (
        patch.object(
            checker, "_extract_tool_info", return_value=("Read", {"limit": 180})
        ),
        patch("ai_guardian.violations.logger.ViolationLogger") as logger,
    ):
        assert checker.check_tool_allowed(hook)[0] is False

    blocked = logger.return_value.log_violation.call_args.kwargs["blocked"]
    assert blocked["file_path"] == target
    assert blocked["input_diagnostics"]["subreason"] == "normalization_failure"


def test_argument_shape_is_schema_limited_and_preserves_correlation(checker, tmp_path):
    args = {"limit": 180, "offset": True, "content": "PRIVATE_CONTENT"}
    args.update({f"PRIVATE_KEY_{index}": "PRIVATE_VALUE" for index in range(1000)})
    hook = _hook(
        args,
        cwd=tmp_path,
        session_id="ses_2627test",
        tool_use_id="call_2627test",
        message_id="msg_2627test",
        session_title="PRIVATE_TITLE",
        integration_version="1.21.0-dev",
        workspace_source="session",
    )
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        assert checker.check_tool_allowed(hook)[0] is False

    record = logger.return_value.log_violation.call_args.kwargs
    context = record["context"]
    assert context["tool_name"] == "Read"
    assert context["project_path"] == str(tmp_path)
    assert context["session_id"] == "ses_2627test"
    assert context["tool_use_id"] == "call_2627test"
    assert context["message_id"] == "msg_2627test"
    assert context["host_version"] == "2.0.24"
    assert context["integration_version"] == __version__
    diagnostics = record["blocked"]["input_diagnostics"]
    assert diagnostics["argument_shape"] == {"limit": "integer", "offset": "boolean"}
    assert diagnostics["unrecognized_argument_count"] == 1001
    assert "PRIVATE_" not in json.dumps(record, default=lambda value: value.to_dict())


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "PRIVATE_PAYLOAD",
        {},
        {"schema_version": True},
        {"schema_version": 2},
        {"schema_version": 1, "subreason": "PRIVATE_SUBREASON"},
    ],
)
def test_stored_diagnostic_schema_rejects_unknown_shapes(value):
    from ai_guardian.violations.tool_diagnostics import safe_input_diagnostics

    assert safe_input_diagnostics(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "null"),
        (True, "boolean"),
        (1, "integer"),
        (1.5, "number"),
        ("PRIVATE_VALUE", "string"),
        ({}, "object"),
        ([], "array"),
        (object(), "unknown"),
    ],
)
def test_argument_type_labels_never_stringify_values(value, expected):
    from ai_guardian.tools.input import json_type

    assert json_type(value) == expected


def test_unknown_workspace_is_explicit_and_fail_closed(checker):
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        allowed, _, _ = checker.check_tool_allowed(
            _hook({"path": "README.md"}, workspace_source="unknown")
        )
    assert allowed is False
    record = logger.return_value.log_violation.call_args.kwargs
    assert record["context"]["project_path"] == ""
    assert record["blocked"]["file_path"] is None
    assert (
        record["blocked"]["input_diagnostics"]["subreason"] == "workspace_unavailable"
    )


def test_policy_log_uses_request_workspace_in_parallel_not_daemon_cwd(
    checker, tmp_path
):
    from threading import Barrier

    barrier = Barrier(2)
    records = []

    def capture(_result, context, **_kwargs):
        barrier.wait(timeout=5)
        records.append(context.to_dict()["project_path"])

    def worker(index):
        set_project_dir_override(str(tmp_path / f"project-{index}"))
        try:
            checker._log_violation(
                "Read", "/workspace/blocked.md", "denied", "Read", _hook({})
            )
        finally:
            clear_project_dir_override()

    with patch(
        "ai_guardian.violations.log_violation.log_violation", side_effect=capture
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(worker, [1, 2]))
    assert set(records) == {str(tmp_path / "project-1"), str(tmp_path / "project-2")}


def test_parallel_workspaces_load_their_own_project_policy(tmp_path):
    """Policy routing, not just attribution, follows the daemon request context."""
    from threading import Barrier

    barrier = Barrier(2)
    projects = [tmp_path / "allowed-project", tmp_path / "denied-project"]
    for index, project in enumerate(projects):
        config_dir = project / ".ai-guardian"
        config_dir.mkdir(parents=True)
        rules = (
            []
            if index == 0
            else [{"matcher": "Read", "mode": "deny", "patterns": ["*"]}]
        )
        (config_dir / "ai-guardian.json").write_text(
            json.dumps({"permissions": {"rules": rules}})
        )
    startup_cwd = os.getcwd()

    def worker(project):
        set_project_dir_override(str(project))
        try:
            policy = ToolPolicyChecker()
            barrier.wait(timeout=5)
            return policy.check_tool_allowed(_hook({"path": "README.md"}, cwd=project))[
                0
            ]
        finally:
            clear_project_dir_override()

    with (
        patch.object(ToolPolicyChecker, "_load_user_config", return_value=(None, None)),
        patch.object(ToolPolicyChecker, "_load_remote_configs", return_value=[]),
        patch(
            "ai_guardian.tools.policy.is_trusted_developer_session", return_value=False
        ),
        patch("ai_guardian.violations.logger.ViolationLogger") as logger,
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert list(executor.map(worker, projects)) == [True, False]
    assert os.getcwd() == startup_cwd
    record = logger.return_value.log_violation.call_args.kwargs
    assert record["context"]["project_path"] == str(projects[1])
    assert record["context"]["policy_project_path"] == str(projects[1])
    assert record["blocked"]["file_path"] == str(projects[1] / "README.md")
    assert record["blocked"]["input_diagnostics"]["subreason"] == "permission_denied"


def test_persisted_record_withholds_payload_and_keeps_generic_policy_reason(
    checker, tmp_path
):
    from ai_guardian.violations.logger import ViolationLogger

    log_path = tmp_path / "violations.jsonl"
    logger = ViolationLogger(log_path=log_path, config={"enabled": True})
    with patch("ai_guardian.violations.logger.ViolationLogger", return_value=logger):
        allowed, _, _ = checker.check_tool_allowed(
            _hook(
                {"path": {"PRIVATE_KEY": "PRIVATE_PAYLOAD"}, "limit": 180},
                cwd=tmp_path,
                message_id="msg_2627test",
                session_title="PRIVATE_TITLE",
            )
        )
    assert allowed is False
    text = log_path.read_text()
    assert "PRIVATE_" not in text
    record = json.loads(text)
    assert record["blocked"]["input_diagnostics"]["subreason"] == "invalid_argument"
    assert record["blocked"]["input_diagnostics"]["argument_shape"] == {
        "path": "object",
        "limit": "integer",
    }
    assert record["blocked"]["tool_value"] == ""
    assert record["policy_decision"]["reason"] == "tool permission denied"
    assert record["policy_decision"]["decision"] == "block"
    assert record["context"]["message_id"] == "msg_2627test"


@pytest.mark.parametrize(
    "cwd", ["relative", "", None, {"PRIVATE_KEY": "PRIVATE_PAYLOAD"}]
)
def test_invalid_workspace_metadata_is_not_replaced_by_startup_cwd(checker, cwd):
    hook = _hook({"path": "README.md"})
    hook["cwd"] = cwd
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        assert checker.check_tool_allowed(hook)[0] is False
    record = logger.return_value.log_violation.call_args.kwargs
    assert record["context"]["project_path"] == ""
    assert (
        record["blocked"]["input_diagnostics"]["subreason"] == "workspace_unavailable"
    )
    assert "PRIVATE_" not in json.dumps(record, default=lambda value: value.to_dict())


def test_host_home_resolution_happens_before_alias_comparison(
    checker, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    target = str(home / "README.md")
    hook = _hook({"path": "~/README.md", "file_path": target}, cwd=tmp_path)
    assert OpenCodeAdapter().normalize_input(hook).file_path == target
    assert checker.check_tool_allowed(hook)[0] is True

    protected = str(home / ".config" / "ai-guardian" / "ai-guardian.json")
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        allowed, _, _ = checker.check_tool_allowed(
            _hook({"path": "~/.config/ai-guardian/ai-guardian.json"}, cwd=tmp_path)
        )
    assert allowed is False
    record = logger.return_value.log_violation.call_args.kwargs
    assert record["blocked"]["file_path"] == protected
    assert record["blocked"]["input_diagnostics"]["subreason"] == "immutable_protection"


def test_named_user_home_syntax_is_not_invented(tmp_path):
    hook = _hook({"path": "~other/README.md"}, cwd=tmp_path)
    assert OpenCodeAdapter().normalize_input(hook).file_path == str(
        tmp_path / "~other" / "README.md"
    )


@pytest.mark.parametrize(
    "native,expected",
    [
        ("/q:/project/README.md", "Q:/project/README.md"),
        ("/q:\\project\\README.md", "Q:/project\\README.md"),
        ("/q/project/README.md", "Q:/project/README.md"),
        ("/cygdrive/q/project/README.md", "Q:/project/README.md"),
        ("/mnt/q/project/README.md", "Q:/project/README.md"),
        ("/mnt/q", "Q:/"),
        ("/workspace/project", "/workspace/project"),
        ("/mnt/queue/project", "/mnt/queue/project"),
        ("/q:relative", "/q:relative"),
    ],
)
def test_windows_shell_aliases_match_the_supported_host_forms(native, expected):
    from ai_guardian.tools.input import _windows_shell_path

    assert _windows_shell_path(native) == expected


@pytest.mark.parametrize(
    "ide,payload,native",
    [
        (
            "claude",
            {
                "tool_use": {
                    "name": "Read",
                    "input": {"limit": 180, "PRIVATE_KEY": "PRIVATE_PAYLOAD"},
                }
            },
            "Read",
        ),
        (
            "codex",
            {
                "tool_name": "Read",
                "tool_input": {"limit": 180, "PRIVATE_KEY": "PRIVATE_PAYLOAD"},
            },
            "Read",
        ),
        (
            "cursor",
            {
                "tool_name": "Read",
                "tool_input": {"limit": 180, "PRIVATE_KEY": "PRIVATE_PAYLOAD"},
            },
            "Read",
        ),
        (
            "copilot",
            {
                "toolName": "Read",
                "toolArgs": '{"limit":180,"PRIVATE_KEY":"PRIVATE_PAYLOAD"}',
            },
            "Read",
        ),
        (
            "augment",
            {
                "tool_use": {
                    "name": "view",
                    "input": {"limit": 180, "PRIVATE_KEY": "PRIVATE_PAYLOAD"},
                }
            },
            "view",
        ),
    ],
)
def test_shared_diagnostics_cover_other_agent_policy_callers(
    checker, monkeypatch, ide, payload, native
):
    """The diagnostic fix is shared; other agents' input normalization is unchanged."""
    monkeypatch.delenv("AI_GUARDIAN_IDE_TYPE", raising=False)
    hook = {"hook_event_name": "PreToolUse", "_ide_type": ide, **payload}
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        assert checker.check_tool_allowed(hook)[0] is False
    record = logger.return_value.log_violation.call_args.kwargs
    diagnostics = record["blocked"]["input_diagnostics"]
    assert diagnostics["subreason"] == "missing_argument"
    assert diagnostics["canonical_tool_name"] == "Read"
    assert diagnostics["native_tool_name"] == native
    assert diagnostics["argument_shape"] == {"limit": "integer"}
    assert diagnostics["unrecognized_argument_count"] == 1
    assert "PRIVATE_" not in json.dumps(record, default=lambda value: value.to_dict())


@pytest.mark.skipif(
    os.name != "nt", reason="Windows drive-relative resolution contract"
)
def test_windows_drive_relative_target_is_rejected_instead_of_guessing(
    checker, tmp_path
):
    with patch("ai_guardian.violations.logger.ViolationLogger") as logger:
        assert (
            checker.check_tool_allowed(_hook({"path": "Q:README.md"}, cwd=tmp_path))[0]
            is False
        )
    assert (
        logger.return_value.log_violation.call_args.kwargs["blocked"][
            "input_diagnostics"
        ]["subreason"]
        == "invalid_argument"
    )
