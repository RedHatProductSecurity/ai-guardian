"""Connection generations, persistence, nonblocking discovery and backoff."""

from dataclasses import replace
from unittest import mock

import pytest

from ai_guardian.daemon.discovery import (
    DaemonDiscovery,
    DaemonTarget,
    should_update_target_name,
)
from ai_guardian.daemon.multi_client import MultiDaemonClient
from ai_guardian.daemon.ssh_connections import SSHConnectionManager, _Connection
from ai_guardian.daemon.ssh_storage import SSHConnectionError, SSHStore, STORAGE_ERROR
from ai_guardian.daemon.ssh_tunnel import IDENTITY_CHANGED, OFFLINE_ERROR, SSH_ERROR
from tests.fixtures.ssh_daemon import make_pairing


@pytest.fixture
def context(tmp_path):
    pairing = make_pairing(tmp_path)[0]
    manager = SSHConnectionManager(SSHStore(tmp_path / "connections"))
    yield manager, pairing
    manager.close()


def test_prepare_does_not_persist_or_start_tunnel(context):
    manager, pairing = context
    with (
        mock.patch(
            "ai_guardian.daemon.ssh_connections.probe_destination", return_value=pairing
        ) as probe,
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
    ):
        assert manager.prepare(pairing.profile.destination) == pairing
    probe.assert_called_once()
    assert probe.call_args.args == (pairing.profile.destination,)
    assert callable(probe.call_args.kwargs["on_process"])
    tunnel.assert_not_called()
    assert manager.store.load() == []


def test_enrollment_authenticates_before_publishing(context):
    manager, pairing = context
    with (
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
        mock.patch.object(manager, "refresh") as refresh,
    ):
        tunnel.return_value.request.side_effect = lambda *_args: {
            "old_daemon_fields": True
        }
        manager.enroll(pairing)
    tunnel.return_value.start.assert_called_once()
    tunnel.return_value.request.assert_called_once_with("GET", "/api/stats")
    tunnel.return_value.close.assert_called_once()
    assert manager.store.load() == [pairing.profile]
    refresh.assert_called_once()


def test_failed_authentication_does_not_save_trust(context):
    manager, pairing = context
    with mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel:
        tunnel.return_value.request.side_effect = SSHConnectionError(
            "Synthetic safe error"
        )
        with pytest.raises(SSHConnectionError):
            manager.enroll(pairing)
    assert manager.store.load() == []
    tunnel.return_value.close.assert_called_once()


def test_shutdown_during_pairing_never_authenticates_or_saves(context):
    manager, pairing = context
    with mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel:
        tunnel.return_value.start.side_effect = manager.close
        with pytest.raises(SSHConnectionError):
            manager.enroll(pairing)
    tunnel.return_value.request.assert_not_called()
    assert manager.store.load() == []
    assert not manager._enrolling


def test_restart_loads_saved_profile_without_blocking_or_repairing_trust(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    with (
        mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as thread,
        mock.patch.object(manager, "prepare") as prepare,
    ):
        first = manager.refresh()
        second = manager.refresh()
    assert first == second
    assert first[0].runtime == "ssh"
    assert first[0].status == "starting"
    thread.return_value.start.assert_called_once()
    prepare.assert_not_called()


def test_removal_invalidates_old_target_and_only_owned_tunnel(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    with mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread"):
        target = manager.refresh()[0]
    tunnel = mock.Mock()
    target.ssh_tunnel = tunnel
    manager.remove(target.ssh_id)
    assert target.ssh_tunnel is None
    assert manager.refresh() == []
    assert manager.store.load() == []
    tunnel.close.assert_called_once()


def test_external_removal_closes_own_generation_on_refresh(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    with mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread"):
        target = manager.refresh()[0]
    tunnel = mock.Mock()
    target.ssh_tunnel = tunnel
    manager.store.remove(pairing.profile.id)
    assert manager.refresh() == []
    tunnel.close.assert_called_once()


def test_invalid_storage_closes_existing_connections_and_shows_safe_error(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    with mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread"):
        target = manager.refresh()[0]
    target.ssh_tunnel = mock.Mock()
    with mock.patch.object(
        manager.store, "load", side_effect=SSHConnectionError(STORAGE_ERROR)
    ):
        result = manager.refresh()
    assert result[0].status == "error"
    assert result[0].error_message == STORAGE_ERROR
    assert target.ssh_tunnel is None


def test_offline_reconnect_uses_bounded_exponential_backoff(context):
    manager, pairing = context
    connection = _Connection(pairing.profile)
    connection.stop = mock.Mock()
    connection.stop.is_set.return_value = False
    connection.stop.wait.side_effect = [False, False, True]
    with mock.patch.object(
        manager, "prepare", side_effect=SSHConnectionError(SSH_ERROR)
    ):
        manager._run(connection)
    assert connection.stop.wait.call_args_list == [
        mock.call(2.0),
        mock.call(4.0),
        mock.call(8.0),
    ]
    assert connection.target.status == "offline"
    assert connection.target.error_message == SSH_ERROR


def test_offline_backoff_is_capped(context):
    manager, pairing = context
    connection = _Connection(pairing.profile)
    connection.stop = mock.Mock()
    connection.stop.is_set.return_value = False
    connection.stop.wait.side_effect = [False] * 7 + [True]
    with mock.patch.object(
        manager, "prepare", side_effect=SSHConnectionError(SSH_ERROR)
    ):
        manager._run(connection)
    assert [call.args[0] for call in connection.stop.wait.call_args_list] == [
        2,
        4,
        8,
        16,
        32,
        60,
        60,
        60,
    ]


def test_changed_identity_never_starts_a_tunnel_or_replaces_storage(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    connection = _Connection(pairing.profile)
    changed = replace(
        pairing, profile=replace(pairing.profile, certificate_sha256="00" * 32)
    )
    with (
        mock.patch.object(manager, "prepare", return_value=changed),
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
    ):
        manager._run(connection)
    tunnel.assert_not_called()
    assert connection.target.status == "error"
    assert connection.target.error_message == IDENTITY_CHANGED
    assert manager.store.load() == [pairing.profile]


def test_old_stats_fields_and_dynamic_port_reconnect(context):
    manager, pairing = context
    connection = _Connection(pairing.profile)
    connection.stop = mock.Mock()
    connection.stop.is_set.return_value = False

    def stopped(_timeout):
        connection.stop.is_set.return_value = True
        return True

    connection.stop.wait.side_effect = stopped
    pairing = replace(pairing, port=54321)
    with (
        mock.patch.object(manager, "prepare", return_value=pairing),
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
    ):
        tunnel.return_value.request.return_value = {"request_count": 1}
        manager._run(connection)
    assert connection.target.status == "running"
    assert connection.target.stats == {"request_count": 1}
    assert tunnel.call_args.args[0].port == 54321
    assert connection.target.ssh_tunnel is None
    tunnel.return_value.close.assert_called_once()


def test_shutdown_during_probe_never_starts_forwarding(context):
    manager, pairing = context
    connection = _Connection(pairing.profile)

    def probe(_host, **_kwargs):
        connection.stop.set()
        return pairing

    with (
        mock.patch.object(manager, "prepare", side_effect=probe),
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
    ):
        manager._run(connection)
    tunnel.assert_not_called()


def test_shutdown_cancels_an_owned_probe_and_refuses_new_enrollment(context):
    manager, pairing = context
    process = mock.Mock()
    process.poll.return_value = None

    def probe(_host, *, on_process):
        on_process(process, True)
        manager.close()
        on_process(process, False)
        return pairing

    with (
        mock.patch(
            "ai_guardian.daemon.ssh_connections.probe_destination", side_effect=probe
        ),
        pytest.raises(SSHConnectionError),
    ):
        manager.prepare(pairing.profile.destination)
    process.terminate.assert_called_once()
    assert not manager._probes
    with (
        mock.patch("ai_guardian.daemon.ssh_connections.probe_destination") as probe,
        pytest.raises(SSHConnectionError),
    ):
        manager.prepare(pairing.profile.destination)
    probe.assert_not_called()
    with (
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
        pytest.raises(SSHConnectionError),
    ):
        manager.enroll(pairing)
    tunnel.return_value.start.assert_not_called()


def test_removal_cancels_only_its_own_pending_probe(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    with mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread"):
        manager.refresh()
    connection = manager._connections[pairing.profile.id]
    owned, unrelated = mock.Mock(), mock.Mock()
    owned.poll.return_value = None
    unrelated.poll.return_value = None
    manager._probes = {owned: connection.stop, unrelated: None}
    manager.remove(pairing.profile.id)
    owned.terminate.assert_called_once()
    unrelated.terminate.assert_not_called()


def test_discovery_shutdown_prevents_late_manager_restart(context):
    manager, _ = context
    discovery = DaemonDiscovery()
    discovery.stop()
    with mock.patch(
        "ai_guardian.daemon.ssh_connections.SSHConnectionManager", return_value=manager
    ):
        assert discovery.discover_ssh() == []
    assert manager._closed


def test_ssh_never_falls_back_to_an_arbitrary_target_url():
    target = DaemonTarget(
        name="ssh",
        runtime="ssh",
        url="http://127.0.0.1:1",
        auth_token="synthetic-credential",
    )
    with mock.patch("ai_guardian.daemon.multi_client.open_daemon_request") as request:
        assert MultiDaemonClient().get_status(target) is None
    request.assert_not_called()
    assert target.error_message == OFFLINE_ERROR


def test_rest_controls_and_prompt_decision_route_through_owned_generation():
    tunnel = mock.Mock()
    target = DaemonTarget(name="ssh-alias", runtime="ssh", ssh_tunnel=tunnel)
    client = MultiDaemonClient()
    tunnel.request.return_value = {"status": "resumed"}
    assert client.send_resume(target)
    tunnel.request.assert_called_with("POST", "/api/resume", None, timeout=5.0)
    tunnel.request.return_value = {"status": "accepted"}
    assert client.send_prompt_decision(target, "prompt-1", {"decision": "block"})
    tunnel.request.assert_called_with(
        "POST",
        "/api/prompt-decision",
        {"prompt_id": "prompt-1", "decision": "block"},
        timeout=5.0,
    )
    assert not should_update_target_name(target, "remote-generated-name")


def test_daemon_restart_cannot_reuse_an_open_permission_prompt_id(tmp_path):
    from ai_guardian.daemon.state import DaemonState

    def state():
        return DaemonState(
            config_path=tmp_path / "config.json",
            sessions_file=tmp_path / "sessions.json",
            pause_file=tmp_path / "paused",
        )

    previous = state().queue_prompt({"summary": "Old invocation"}, "block", 300)
    restarted = state()
    current = restarted.queue_prompt({"summary": "New invocation"}, "block", 300)
    assert previous.prompt_id != current.prompt_id
    assert not restarted.resolve_prompt(previous.prompt_id, {"decision": "allow_once"})
    assert current.result is None


def test_poll_only_rest_flow_retains_https_authentication(tmp_path):
    from urllib.error import HTTPError
    from urllib.request import Request

    from ai_guardian.daemon.rest_api import DaemonRestAPI
    from ai_guardian.daemon.rest_transport import TLSOptions, open_daemon_request
    from ai_guardian.daemon.ssh_tunnel import SSHTunnel
    from ai_guardian.daemon.state import DaemonState
    from tests.fixtures.daemon_tls import client_config, listener_config

    pairing, _, identity = make_pairing(tmp_path)
    state = DaemonState(
        config_path=tmp_path / "config.json",
        sessions_file=tmp_path / "sessions.json",
        pause_file=tmp_path / "paused",
    )
    api = DaemonRestAPI(
        state, auth_token=pairing.profile.token, tls=listener_config(identity)
    )
    api.start()
    tunnel = SSHTunnel(pairing, SSHStore(tmp_path / "connections"))
    tunnel.process = mock.Mock()
    tunnel.process.poll.return_value = None
    tunnel.port = api.port
    tunnel.tls = TLSOptions.from_config(client_config(identity))
    target = DaemonTarget(name="ssh-alias", runtime="ssh", ssh_tunnel=tunnel)
    try:
        request = Request(
            f"https://127.0.0.1:{api.port}/api/register-tray", data=b"", method="POST"
        )
        with pytest.raises(HTTPError) as error:
            open_daemon_request(request, tls=tunnel.tls)
        assert error.value.code == 401
        error.value.close()
        assert not state.is_tray_registered()
        client = MultiDaemonClient()
        assert client.register_tray(target, None, 0)
        assert state._registered_tray["poll_only"] is True
        pending = state.queue_prompt({"summary": "Synthetic remote ask"}, "block", 10)
        assert client.get_pending_prompts(target)[0]["prompt_id"] == pending.prompt_id
        assert client.send_prompt_decision(
            target, pending.prompt_id, {"decision": "block"}
        )
        assert pending.decision_event.is_set()
    finally:
        tunnel.close()
        api.stop()


@pytest.mark.parametrize(
    "reply,accepted",
    [
        ({"status": "registered", "poll_only": True}, True),
        ({"status": "registered"}, False),
        (None, False),
    ],
)
def test_poll_only_registration_requires_explicit_capability_ack(reply, accepted):
    target = DaemonTarget(name="ssh", runtime="ssh")
    client = MultiDaemonClient()
    with mock.patch.object(client, "_rest_request", return_value=reply) as request:
        assert (
            client.register_tray(target, "not-used", 123, "must-not-be-forwarded")
            is accepted
        )
    request.assert_called_once_with(
        target, "POST", "/api/register-tray", {"poll_only": True}
    )
