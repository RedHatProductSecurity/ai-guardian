"""OpenCode PostToolUse filename attribution regressions."""

from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters.opencode import OpenCodeAdapter
from ai_guardian.hook_events.post_tool_use import handle_post_tool_use
from ai_guardian.scanners.scan_result import ScanResult


@pytest.mark.parametrize(
    ("opencode_version", "path_key"),
    [
        ("1.0.0", "filePath"),
        ("2.0.24", "path"),
        ("2.0.24", "file_path"),
    ],
)
@pytest.mark.parametrize("legacy_invocation", [False, True], ids=["context", "legacy"])
def test_posttool_prompt_injection_violation_keeps_native_filename(
    tmp_path, opencode_version, path_key, legacy_invocation
):
    """The normalized native filename reaches the scanner and violation log."""
    html_path = tmp_path / "fixture.html"
    html_path.write_text('<html><script>const greeting = "hello";</script></html>')
    expected_path = str(html_path)
    tool_input = {path_key: expected_path, "limit": 2000}
    hook_data = {
        "hook_event_name": "tool.execute.after",
        "opencode_version": opencode_version,
        "hook_source": "opencode",
        "tool_name": "read",
        "tool_use": {"name": "read", "input": tool_input},
        "tool_response": {"output": html_path.read_text()},
        "cwd": str(tmp_path),
    }
    violation_logger = Mock()
    from ai_guardian.hook_processing import _ensure_hook_events_imported

    _ensure_hook_events_imported()

    def detect_fixture(_content, *, file_path=None, **_kwargs):
        # Model a deterministic finding while deriving its path only from the
        # actual scanner argument supplied by the PostToolUse handler.
        result = ScanResult.from_prompt_injection(
            should_block=False,
            error_message="synthetic prompt-injection finding",
            detected=True,
            file_path=file_path,
        )
        result.extra["action"] = "warn"
        return result

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "ai_guardian.hook_processing._handle_bootstrap_scan",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.hook_processing.ViolationLogger",
                return_value=violation_logger,
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.config.loaders._load_secret_scanning_config",
                return_value=({"enabled": True}, None),
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.scanners.password_likelihood.run_password_likelihood_scan",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.hook_events.post_tool_use.run_secret_scan",
                return_value=ScanResult.clean("secret_detected"),
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.hook_events.post_tool_use.run_pii_scan",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.hook_events.post_tool_use._load_overlaid_config",
                return_value=None,
            )
        )
        prompt_scan = stack.enter_context(
            patch(
                "ai_guardian.hook_events.post_tool_use.run_prompt_injection_scan",
                side_effect=detect_fixture,
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.hook_events.post_tool_use.run_context_poisoning_scan",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "ai_guardian.hook_events.post_tool_use.run_offensive_language_scan",
                return_value=None,
            )
        )

        if legacy_invocation:
            adapter = OpenCodeAdapter()
            handle_post_tool_use(
                hook_data=hook_data,
                adapter=adapter,
                ide_type=adapter.ide_type,
                hook_event=HookEvent.POST_TOOL_USE,
                hook_tool_use_id=None,
                hook_session_id=None,
                context_mgr=None,
                violation_logger=violation_logger,
                _latency_timer=None,
                _invocation_allowed=set(),
                now=datetime.now(timezone.utc),
            )
        else:
            from ai_guardian.hook_processing import _process_hook_data

            _process_hook_data(hook_data)

    assert prompt_scan.call_args.kwargs["file_path"] == expected_path
    logged_violation = violation_logger.log_violation.call_args.kwargs
    assert logged_violation["blocked"]["file_path"] == expected_path
