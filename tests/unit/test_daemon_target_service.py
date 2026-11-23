"""Tests for headless daemon inventory and action routing."""

import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.daemon.target_service import DaemonTargetService


class FakeDiscovery:
    def __init__(self, targets):
        self.targets = list(targets)
        self.discover_calls = 0
        self.stop_calls = 0

    def discover_all(self):
        self.discover_calls += 1
        return self.targets

    def stop(self):
        self.stop_calls += 1


def _service_for(target):
    discovery = FakeDiscovery([target])
    return DaemonTargetService(discovery=discovery), discovery


def test_inventory_contains_only_display_safe_target_fields():
    target = DaemonTarget(
        name="local",
        runtime="local",
        status="running",
        auth_token="synthetic-private-token",
        tls={"client": {"key_file": "/private/client.key"}},
    )
    service, _ = _service_for(target)

    entry = service.get_inventory()[0]
    values = asdict(entry)

    assert values == {
        "target_id": entry.target_id,
        "name": "local",
        "runtime": "local",
        "runtime_type": None,
        "status": "running",
        "availability": "available",
        "capabilities": (
            "pause",
            "reload",
            "restart",
            "resume",
            "status",
            "stop",
        ),
    }
    assert "auth_token" not in values
    assert "tls" not in values


def test_inventory_reports_offline_and_unsupported_targets_explicitly():
    offline = DaemonTarget(name="offline", runtime="manual", status="offline")
    unsupported = DaemonTarget(
        name="other", runtime="unknown-runtime", status="running"
    )
    discovery = FakeDiscovery([offline, unsupported])
    service = DaemonTargetService(discovery=discovery)

    entries = service.get_inventory()

    assert entries[0].availability == "offline"
    assert entries[0].capabilities == ("status",)
    assert entries[1].availability == "unsupported"
    assert entries[1].capabilities == ()


@pytest.mark.parametrize(
    "runtime", ["local", "container", "kubernetes", "manual", "ssh"]
)
def test_pause_routes_only_to_the_selected_supported_target(runtime):
    target = DaemonTarget(name="selected", runtime=runtime, status="running")
    service, _ = _service_for(target)
    service.get_status = mock.Mock(
        return_value={
            "paused": False,
            "paused_dirs": {},
            "active_project_dirs": [],
            "pause_control_sessions": [],
        }
    )
    service.send_pause = mock.Mock(return_value=True)
    entry = service.get_inventory()[0]

    result = service.route(entry.target_id, "pause", minutes=15)

    assert result.succeeded
    service.send_pause.assert_called_once_with(target, 15)


def test_scoped_action_uses_only_the_requested_directory():
    target = DaemonTarget(name="container", runtime="container", status="running")
    service, _ = _service_for(target)
    service.get_status = mock.Mock(
        return_value={"paused": False, "paused_dirs": {}, "active_project_dirs": []}
    )
    service.send_pause_dir = mock.Mock(return_value=True)
    entry = service.get_inventory()[0]

    result = service.route(
        entry.target_id, "pause_directory", directory="/work/project", minutes=5
    )

    assert result.succeeded
    service.send_pause_dir.assert_called_once_with(target, "/work/project", 5)


def test_missing_session_capability_does_not_route_action():
    target = DaemonTarget(name="local", runtime="local", status="running")
    service, _ = _service_for(target)
    service.get_status = mock.Mock(return_value={"paused": False})
    service.send_pause_session = mock.Mock(return_value=True)
    entry = service.get_inventory()[0]

    result = service.route(
        entry.target_id, "pause_session", session_key="Adapter:session-1", minutes=5
    )

    assert result.status == "unsupported"
    assert result.reason == "capability_unavailable"
    service.send_pause_session.assert_not_called()


def test_offline_target_is_not_routed():
    target = DaemonTarget(name="offline", runtime="container", status="running")
    service, _ = _service_for(target)
    service.get_status = mock.Mock(return_value=None)
    service.send_pause = mock.Mock(return_value=True)
    entry = service.get_inventory()[0]

    result = service.route(entry.target_id, "pause", minutes=5)

    assert result.status == "unavailable"
    assert result.reason == "target_offline"
    assert target.status == "offline"
    service.send_pause.assert_not_called()


def test_unknown_status_does_not_authorize_mutation():
    target = DaemonTarget(name="manual", runtime="manual", status="running")
    service, _ = _service_for(target)
    service.get_status = mock.Mock(return_value={})
    service.send_pause = mock.Mock(return_value=True)
    entry = service.get_inventory()[0]

    result = service.route(entry.target_id, "pause", minutes=5)

    assert result.status == "unavailable"
    assert result.reason == "target_status_unknown"
    service.send_pause.assert_not_called()


def test_unknown_operation_and_invalid_arguments_never_fall_back():
    target = DaemonTarget(name="local", runtime="local", status="running")
    service, _ = _service_for(target)
    service.get_status = mock.Mock()
    service.send_pause = mock.Mock(return_value=True)
    entry = service.get_inventory()[0]

    unsupported = service.route(entry.target_id, "open_console")
    invalid = service.route(entry.target_id, "pause", minutes=True)

    assert unsupported.status == "unsupported"
    assert invalid.status == "invalid_request"
    service.get_status.assert_not_called()
    service.send_pause.assert_not_called()


def test_target_id_is_invalidated_when_discovery_replaces_target():
    original = DaemonTarget(name="local", runtime="local", status="running")
    service, discovery = _service_for(original)
    service.get_status = mock.Mock(return_value={"paused": False})
    entry = service.get_inventory()[0]
    discovery.targets = [DaemonTarget(name="local", runtime="local", status="running")]

    result = service.route(entry.target_id, "status")

    assert result.status == "stale_target"
    service.get_status.assert_not_called()


def test_target_id_is_stale_if_endpoint_or_trust_changes_in_place():
    target = DaemonTarget(
        name="manual",
        runtime="manual",
        status="running",
        url="https://daemon.example.test:63152",
        auth_token="synthetic-private-token",
    )
    service, _ = _service_for(target)
    service.get_status = mock.Mock(return_value={"paused": False})
    entry = service.get_inventory()[0]
    target.auth_token = "replacement-synthetic-token"

    result = service.route(entry.target_id, "status")

    assert result.status == "stale_target"
    service.get_status.assert_not_called()


def test_refresh_inventory_uses_shared_discovery_and_close_stops_it():
    target = DaemonTarget(name="local", runtime="local", status="running")
    service, discovery = _service_for(target)

    entries = service.refresh_inventory()
    service.close()

    assert len(entries) == 1
    assert discovery.discover_calls == 1
    assert discovery.stop_calls == 1


def test_multi_client_methods_remain_available_through_service_facade():
    target = DaemonTarget(name="local", runtime="local", status="running")
    client = mock.Mock()
    client.send_pause.return_value = True
    service = DaemonTargetService(discovery=FakeDiscovery([target]), client=client)

    assert service.send_pause(target, 5) is True
    client.send_pause.assert_called_once_with(target, 5)


def test_importing_headless_service_does_not_import_tray_ui():
    project_root = Path(__file__).resolve().parents[2]
    command = (
        "import sys; "
        "from ai_guardian.daemon.target_service import DaemonTargetService; "
        "assert not any(name == 'ai_guardian.tray' or "
        "name.startswith('ai_guardian.tray.') for name in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
