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


@pytest.mark.parametrize(
    "mcp,expected",
    [
        ({}, {"mcp_proactive_level": "low", "mcp_enabled": True}),
        (
            {"proactive_level": "medium", "enabled": True},
            {"mcp_proactive_level": "medium", "mcp_enabled": True},
        ),
        ({"enabled": False}, {"mcp_proactive_level": "low", "mcp_enabled": False}),
    ],
)
def test_current_main_daemon_mcp_state_uses_its_global_config_api(
    context, mcp, expected
):
    manager, pairing = context
    connection = _Connection(pairing.profile)
    tunnel = mock.Mock()
    stats = {"request_count": 42, "mcp_installed": True}
    tunnel.request.side_effect = [dict(stats), {"mcp_server": mcp}]

    def stop(_timeout):
        connection.stop.set()
        return True

    with (
        mock.patch.object(manager, "prepare", return_value=pairing),
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel", return_value=tunnel),
        mock.patch.object(connection.stop, "wait", side_effect=stop),
    ):
        manager._run(connection)
    assert connection.target.status == "running"
    assert connection.target.stats == {**stats, **expected}
    assert tunnel.request.call_args_list == [
        mock.call("GET", "/api/stats"),
        mock.call("GET", "/api/config?scope=global"),
    ]
    assert stats == {"request_count": 42, "mcp_installed": True}


@pytest.mark.parametrize(
    "config",
    [
        None,
        {"error": "unsupported"},
        {"features": {"proactive_level": "high"}},
        {"mcp_server": None},
        {"mcp_server": {"proactive_level": []}},
        SSHConnectionError("Unsupported configuration endpoint"),
    ],
)
def test_optional_mcp_compatibility_failure_keeps_vm_online_without_inventing_state(
    context, config
):
    manager, pairing = context
    connection = _Connection(pairing.profile)
    stats = {"request_count": 42, "mcp_installed": True}
    tunnel = mock.Mock()
    tunnel.request.side_effect = [stats, config]

    def stop(_timeout):
        connection.stop.set()
        return True

    with (
        mock.patch.object(manager, "prepare", return_value=pairing),
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel", return_value=tunnel),
        mock.patch.object(connection.stop, "wait", side_effect=stop),
    ):
        manager._run(connection)
    assert connection.target.status == "running"
    assert connection.target.stats == stats
    assert connection.target.error_message is None


@pytest.mark.parametrize(
    "stats",
    [
        {"mcp_installed": True, "mcp_enabled": True, "mcp_proactive_level": "high"},
        {"mcp_installed": False},
        {},
    ],
)
def test_mcp_compatibility_only_fetches_missing_capabilities_for_installed_mcp(
    context, stats
):
    manager, _pairing = context
    tunnel = mock.Mock()
    assert manager._stats_with_mcp_state(tunnel, stats) == stats
    tunnel.request.assert_not_called()


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
        # Exercise the real authenticated scoped endpoint used by existing main
        # daemons, not just a fabricated new-stats response. Project overrides
        # must never be requested and unrelated config must not enter the cache.
        with mock.patch(
            "ai_guardian.config.writer.load_scoped_config",
            return_value={
                "mcp_server": {"proactive_level": "medium"},
                "daemon": {"auth_token": "synthetic-private-value"},
            },
        ) as config:
            stats = SSHConnectionManager._stats_with_mcp_state(
                tunnel, {"mcp_installed": True}
            )
        assert stats == {
            "mcp_installed": True,
            "mcp_enabled": True,
            "mcp_proactive_level": "medium",
        }
        config.assert_called_once_with("global", None)
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


@pytest.fixture
def alias_config(context, tmp_path, monkeypatch):
    from ai_guardian.daemon import ssh_config

    path = tmp_path / ".ssh" / "config"
    path.parent.mkdir()
    path.write_text("Host existing-vm ai-guardian-new\n")
    monkeypatch.setattr(ssh_config, "user_ssh_config", lambda: path)
    monkeypatch.setattr(
        "ai_guardian.daemon.ssh_connections.load_settings",
        lambda: {"enabled": True, "alias_prefix": ""},
    )
    return path


def test_alias_scan_is_local_and_candidates_are_not_daemon_targets(
    context, alias_config
):
    manager, _ = context
    discovery = DaemonDiscovery()
    discovery._ssh_manager = manager
    with (
        mock.patch("ai_guardian.daemon.ssh_connections.probe_destination") as probe,
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
        mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as worker,
    ):
        for _ in range(3):
            assert discovery.discover_ssh() == []
    assert discovery.ssh_alias_discovery["aliases"] == (
        "ai-guardian-new",
        "existing-vm",
    )
    assert manager.store.load() == []
    probe.assert_not_called()
    tunnel.assert_not_called()
    worker.assert_not_called()


def test_discovery_off_never_reads_ssh_config_or_changes_saved_workers(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    with (
        mock.patch(
            "ai_guardian.daemon.ssh_connections.load_settings",
            return_value={"enabled": False, "alias_prefix": ""},
        ),
        mock.patch("ai_guardian.daemon.ssh_connections.scan_aliases") as scan,
        mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as worker,
    ):
        manager.refresh()
        assert not manager.refresh_aliases()["aliases"]
        manager.refresh()
    scan.assert_not_called()
    worker.return_value.start.assert_called_once()
    assert manager.store.load() == [pairing.profile]


def test_config_edits_hide_paired_aliases_without_replacing_trust(
    context, alias_config
):
    manager, pairing = context
    alias = pairing.profile.destination.rsplit("@", 1)[-1]
    manager.store.create(pairing.profile)
    record = manager.store.path / f"{pairing.profile.id}.json"
    before = record.read_bytes()
    alias_config.write_text(
        f"Host {alias.upper()} first\n HostName changed.example\n User different\n"
    )
    assert manager.refresh_aliases()["aliases"] == ("first",)
    alias_config.write_text("Host second\n")
    assert manager.refresh_aliases()["aliases"] == ("second",)
    alias_config.unlink()
    assert manager.refresh_aliases()["aliases"] == ()
    assert manager.alias_discovery["notices"]
    assert record.read_bytes() == before
    assert manager.store.load() == [pairing.profile]


def test_only_explicit_review_probes_and_stale_actions_fail_closed(
    context, alias_config
):
    from ai_guardian.daemon.ssh_connections import CANDIDATE_ERROR

    manager, pairing = context
    manager.refresh_aliases()
    with mock.patch.object(manager, "prepare", return_value=pairing) as probe:
        assert manager.prepare_discovered("existing-vm") is pairing
        probe.assert_called_once_with("existing-vm")
        alias_config.write_text("Host replacement\n")
        with pytest.raises(SSHConnectionError, match=CANDIDATE_ERROR):
            manager.prepare_discovered("existing-vm")
        assert probe.call_count == 1
    assert manager.store.load() == []


def test_dismissal_persists_restart_without_enrollment_or_remote_cleanup(
    context, alias_config
):
    manager, _ = context
    manager.refresh_aliases()
    with mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel:
        manager.dismiss_alias("existing-vm")
        manager.refresh_aliases()
        restarted = SSHConnectionManager(SSHStore(manager.store.path))
        try:
            assert restarted.refresh_aliases()["aliases"] == ("ai-guardian-new",)
            assert restarted.store.load() == []
        finally:
            restarted.close()
    tunnel.assert_not_called()


def test_removal_dismisses_alias_before_deleting_trust_and_cannot_recreate_it(
    context, alias_config
):
    manager, pairing = context
    alias_config.write_text(f"Host {pairing.profile.destination.rsplit('@', 1)[-1]}\n")
    manager.store.create(pairing.profile)
    manager.remove(pairing.profile.id)
    with mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as worker:
        assert manager.refresh() == []
        assert manager.refresh_aliases()["aliases"] == ()
    worker.assert_not_called()
    assert manager.store.is_dismissed(pairing.profile.destination)


def test_candidate_state_does_not_turn_storage_failures_into_trust(
    context, alias_config
):
    manager, _ = context
    with mock.patch.object(
        manager.store, "load", side_effect=SSHConnectionError(STORAGE_ERROR)
    ):
        state = manager.refresh_aliases()
    assert not state["aliases"]
    assert STORAGE_ERROR in state["notices"]


def test_overlapping_background_alias_refresh_uses_cached_snapshot_not_another_scan(
    context, alias_config
):
    manager, _ = context
    snapshot = manager.refresh_aliases()
    with (
        manager._alias_lock,
        mock.patch("ai_guardian.daemon.ssh_connections.scan_aliases") as scan,
    ):
        assert manager.refresh_aliases() == snapshot
    scan.assert_not_called()
    manager.close()
    assert manager.refresh_aliases()["aliases"] == ()


def test_discovered_confirmation_reuses_authentication_persistence_and_single_worker(
    context, alias_config
):
    manager, original = context
    pairing = replace(
        original, profile=replace(original.profile, destination="existing-vm")
    )
    with (
        mock.patch(
            "ai_guardian.daemon.ssh_connections.probe_destination", return_value=pairing
        ),
        mock.patch("ai_guardian.daemon.ssh_connections.SSHTunnel") as tunnel,
        mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as worker,
    ):
        draft = manager.prepare_discovered("existing-vm")
        assert manager.store.load() == []
        manager.enroll(draft)  # Called only by the explicit confirmation action.
        tunnel.return_value.request.assert_called_once_with("GET", "/api/stats")
        assert manager.store.load() == [pairing.profile]
        for _ in range(3):
            assert len(manager.refresh()) == 1
            assert manager.refresh_aliases()["aliases"] == ("ai-guardian-new",)
        worker.return_value.start.assert_called_once()
    manager.close()
    restarted = SSHConnectionManager(manager.store)
    with mock.patch("ai_guardian.daemon.ssh_connections.threading.Thread") as worker:
        try:
            assert len(restarted.refresh()) == 1
            assert len(restarted.refresh()) == 1
            worker.return_value.start.assert_called_once()
        finally:
            restarted.close()


def test_failed_dismissal_does_not_delete_trust_or_stop_saved_worker(context):
    manager, pairing = context
    manager.store.create(pairing.profile)
    with mock.patch.object(
        manager.store, "dismiss", side_effect=SSHConnectionError(STORAGE_ERROR)
    ):
        with pytest.raises(SSHConnectionError):
            manager.remove(pairing.profile.id)
    assert manager.store.load() == [pairing.profile]


def test_shutdown_during_alias_scan_never_publishes_candidates(context, alias_config):
    from ai_guardian.daemon.ssh_config import AliasScan

    manager, _ = context

    def scan(**kwargs):
        manager.close()
        return AliasScan(("existing-vm",))

    with mock.patch(
        "ai_guardian.daemon.ssh_connections.scan_aliases", side_effect=scan
    ):
        assert manager.refresh_aliases()["aliases"] == ()
