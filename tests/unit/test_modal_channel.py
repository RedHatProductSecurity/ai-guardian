"""Persistent modal channels retain startup-only fallback and safe cancellation."""

import io
import json
import sys
from unittest.mock import Mock, patch

import pytest

from ai_guardian.ui.modal import run_modal, run_modal_channel


class Input(io.StringIO):
    def close(self):
        self.sent = self.getvalue()
        super().close()


def process(output):
    return Mock(stdin=Input(), stdout=io.StringIO(output), poll=Mock(return_value=0))


def test_channel_processes_only_explicit_events_and_close_is_terminal():
    child = process('startup information\n{"action":"Refresh status"}\nnull\n')
    event = Mock(return_value={"rows": [], "feedback": "Refreshed"})
    with patch("subprocess.Popen", return_value=child) as popen:
        run_modal_channel(["child"], {"rows": []}, event)
    event.assert_called_once_with({"action": "Refresh status"})
    assert [json.loads(line) for line in child.stdin.sent.splitlines()] == [
        {"rows": []},
        {"rows": [], "feedback": "Refreshed"},
    ]
    assert popen.call_args.kwargs["encoding"] == "utf-8"
    child.terminate.assert_not_called()


@pytest.mark.parametrize(
    "output,attempts",
    [
        ("__AI_GUARDIAN_MODAL_UNAVAILABLE__\n", 1),
        ('{"action":"Refresh status"}\n__AI_GUARDIAN_MODAL_UNAVAILABLE__\n', 0),
        ("", 0),
        ("[]\n", 0),
        ("x" * 65537, 0),
    ],
)
def test_only_proven_first_startup_failure_advances(output, attempts):
    child = process(output)
    browser = Mock()
    with (
        patch("subprocess.Popen", return_value=child),
        patch(
            "ai_guardian.ui.modal.ui_provider_order",
            return_value=("tkinter", "nicegui"),
        ),
    ):
        run_modal(
            "form",
            {
                "tkinter": lambda: run_modal_channel(
                    ["child"], {"rows": []}, lambda e: {"rows": []}
                ),
                "nicegui": browser,
            },
            fallback=None,
        )
    assert browser.call_count == attempts


def test_missing_channel_executable_allows_startup_fallback():
    browser = Mock()
    with (
        patch("subprocess.Popen", side_effect=FileNotFoundError),
        patch(
            "ai_guardian.ui.modal.ui_provider_order",
            return_value=("tkinter", "nicegui"),
        ),
    ):
        run_modal(
            "form",
            {
                "tkinter": lambda: run_modal_channel(["child"], {}, Mock()),
                "nicegui": browser,
            },
            fallback=None,
        )
    browser.assert_called_once()


def test_real_child_roundtrip_keeps_large_unicode_payload_off_argv():
    script = (
        "import json,sys; p=json.loads(sys.stdin.readline()); "
        "print(json.dumps({'action':'Refresh status'}),flush=True); "
        "r=json.loads(sys.stdin.readline()); assert r==p; print('null',flush=True)"
    )
    display = {"rows": [], "message": "Complete review 日本語. " * 10000}
    event = Mock(return_value=display)
    run_modal_channel([sys.executable, "-c", script], display, event)
    event.assert_called_once_with({"action": "Refresh status"})


def test_callback_failure_is_terminal_and_releases_owned_child():
    child = process('{"action":"Refresh status"}\n')
    child.poll.return_value = None
    browser = Mock()
    with (
        patch("subprocess.Popen", return_value=child),
        patch(
            "ai_guardian.ui.modal.ui_provider_order",
            return_value=("tkinter", "nicegui"),
        ),
    ):
        run_modal(
            "form",
            {
                "tkinter": lambda: run_modal_channel(
                    ["child"], {}, Mock(side_effect=RuntimeError("private"))
                ),
                "nicegui": browser,
            },
            fallback=None,
        )
    browser.assert_not_called()
    child.terminate.assert_called_once()
    assert child.stdin.closed and child.stdout.closed
