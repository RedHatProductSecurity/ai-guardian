"""Subprocess regressions for notification handoff from short-lived hooks."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from ai_guardian.violations.notifications import NotificationStore


def test_direct_hook_persists_notification_before_short_lived_process_exits(
    tmp_path,
):
    state_dir = tmp_path / "state"
    worker_marker = tmp_path / "worker-started"
    script = textwrap.dedent("""
        import os
        import sys
        from io import StringIO

        import ai_guardian.cli as cli
        import ai_guardian.daemon.client as daemon_client
        import ai_guardian.violations.notifications as notifications
        from ai_guardian.violations.logger import ViolationLogger
        from ai_guardian.violations.notifications import NotificationStore

        event_id = "viol_0123456789abcdef"

        def process_hook_data(_hook_data):
            ViolationLogger(config={"enabled": False}).log_violation(
                "tool_permission",
                blocked={},
                context={},
                severity="high",
                violation_id=event_id,
            )
            return {"output": "{}", "exit_code": 0}

        def start_worker(persisted_event_id):
            assert persisted_event_id == event_id
            pending = NotificationStore().pending_local_event(persisted_event_id)
            assert pending is not None
            with open(os.environ["WORKER_MARKER"], "w", encoding="utf-8") as marker:
                marker.write(persisted_event_id)
            return True

        cli._load_config_file = lambda: ({}, None)
        cli.process_hook_data = process_hook_data
        daemon_client.is_daemon_running = lambda: False
        daemon_client.start_daemon_background = lambda: False
        notifications._spawn_notification_worker = start_worker
        sys.argv = ["ai-guardian"]
        sys.stdin = StringIO("{}")
        cli.main()
        """)
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("AI_GUARDIAN_"):
            env.pop(key)
    env["AI_GUARDIAN_STATE_DIR"] = str(state_dir)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["WORKER_MARKER"] = str(worker_marker)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
    assert worker_marker.read_text(encoding="utf-8") == "viol_0123456789abcdef"
    events = NotificationStore(
        state_dir / "violation-notifications.sqlite3"
    ).recent_local_events()
    assert len(events) == 1
    assert events[0]["id"] == "viol_0123456789abcdef"
    assert events[0]["delivery"]["desktop"] == "pending"


def test_detached_worker_module_starts_from_package_root_without_python_env(
    tmp_path,
):
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("AI_GUARDIAN_"):
            env.pop(key)
    env["AI_GUARDIAN_STATE_DIR"] = str(tmp_path / "state")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")

    result = subprocess.run(
        [
            sys.executable,
            "-E",
            "-m",
            "ai_guardian.violations.notification_worker",
            "viol_0123456789abcdef",
        ],
        cwd=Path(__file__).resolve().parents[2] / "src",
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
