"""Every local REST caller honors the running HTTPS transport and explicit trust."""

import json
from unittest import mock

import pytest

from ai_guardian.daemon.rest_transport import DaemonConnectionError, TLS_PIN_ERROR


@pytest.fixture
def local_https_metadata(monkeypatch):
    from ai_guardian.daemon import get_pid_path

    path = get_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": 1234, "rest_port": 63152, "rest_scheme": "https"})
    )
    monkeypatch.setattr("ai_guardian.daemon.is_pid_alive", lambda _pid: True)
    return {"pid": 1234, "rest_port": 63152, "rest_scheme": "https"}


def test_sdk_registration_uses_shared_local_https_transport(local_https_metadata):
    from ai_guardian.sdk import _DirectSession

    with mock.patch(
        "ai_guardian.daemon.rest_transport.local_daemon_request"
    ) as request:
        _DirectSession(config={}, cwd="/unit/project")
    request.assert_called_once_with(
        "/api/register-project",
        data={"project_dir": "/unit/project"},
        timeout=2,
        pid_info=local_https_metadata,
    )


def test_ask_prompt_uses_shared_transport_without_changing_decisions(
    local_https_metadata,
):
    from ai_guardian.ui.ask_dialog import (
        AskDecision,
        AskViolationInfo,
        _show_via_daemon,
    )

    with mock.patch(
        "ai_guardian.daemon.rest_transport.local_daemon_request"
    ) as request:
        request.return_value.__enter__.return_value.read.return_value = (
            b'{"decision":"block"}'
        )
        result = _show_via_daemon(AskViolationInfo("unit", "safe", "sample", "test"))
    assert result.decision == AskDecision.BLOCK
    assert request.call_args.args == ("/api/prompt",)
    assert request.call_args.kwargs["pid_info"] == local_https_metadata


def test_local_trace_uses_shared_transport(local_https_metadata):
    from ai_guardian.integrations.anthropic.agent import GuardedAgent

    with (
        mock.patch("ai_guardian.daemon.rest_transport.local_daemon_request") as request,
        mock.patch.object(GuardedAgent, "_push_trace_to_remote") as remote,
    ):
        GuardedAgent._push_trace_to_daemon("trace.json", {"sample": "safe"})
    request.assert_called_once_with(
        "/api/traces",
        data={"filename": "trace.json", "trace_doc": {"sample": "safe"}},
        timeout=3,
        pid_info=local_https_metadata,
    )
    remote.assert_not_called()


def test_local_trace_tls_failure_does_not_fall_back_to_http(
    local_https_metadata, caplog
):
    from ai_guardian.integrations.anthropic.agent import GuardedAgent

    with (
        mock.patch(
            "ai_guardian.daemon.rest_transport.local_daemon_request",
            side_effect=DaemonConnectionError(TLS_PIN_ERROR),
        ),
        mock.patch.object(GuardedAgent, "_push_trace_to_remote") as remote,
    ):
        GuardedAgent._push_trace_to_daemon("trace.json", {})
    remote.assert_not_called()
    assert TLS_PIN_ERROR in caplog.text


def test_unexpected_https_failure_does_not_select_remote_fallback(local_https_metadata):
    from ai_guardian.integrations.anthropic.agent import GuardedAgent

    with (
        mock.patch(
            "ai_guardian.daemon.rest_transport.local_daemon_request",
            side_effect=TypeError("unit-only-error"),
        ),
        mock.patch.object(GuardedAgent, "_push_trace_to_remote") as remote,
    ):
        GuardedAgent._push_trace_to_daemon("trace.json", {})
    remote.assert_not_called()
