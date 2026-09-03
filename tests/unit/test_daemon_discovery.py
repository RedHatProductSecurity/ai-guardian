"""Tests for multi-daemon discovery engine."""

import json
import os
import tempfile
import threading
import time
from unittest import mock


from ai_guardian.daemon.discovery import (
    DaemonDiscovery,
    DaemonTarget,
    HAS_K8S_SDK,
    _detect_engine,
    _engine_from_source,
    _get_podman_socket,
)


class TestDaemonTarget:
    def test_dataclass_defaults(self):
        t = DaemonTarget(name="test", runtime="local")
        assert t.name == "test"
        assert t.runtime == "local"
        assert t.status == "unknown"
        assert t.host == "127.0.0.1"
        assert t.port == 0
        assert t.container_id is None
        assert t.container_engine is None
        assert t.container_name is None
        assert t.pod_name is None
        assert t.namespace is None
        assert t.context is None
        assert t.socket_path is None
        assert t.stats is None
        assert t.last_seen == 0.0

    def test_container_name_field(self):
        t = DaemonTarget(
            name="my-project",
            runtime="container",
            container_id="abc123def456",
            container_engine="podman",
            container_name="sandbox-1",
        )
        assert t.container_name == "sandbox-1"
        assert t.name == "my-project"

    def test_container_name_defaults_none_for_local(self):
        t = DaemonTarget(name="local", runtime="local")
        assert t.container_name is None

    def test_local_target(self):
        t = DaemonTarget(
            name="local",
            runtime="local",
            socket_path="/tmp/daemon.sock",
            status="running",
        )
        assert t.runtime == "local"
        assert t.socket_path == "/tmp/daemon.sock"

    def test_container_target(self):
        t = DaemonTarget(
            name="my-container",
            runtime="container",
            container_id="abc123",
            container_engine="podman",
            host="127.0.0.1",
            port=49152,
        )
        assert t.runtime == "container"
        assert t.container_id == "abc123"
        assert t.container_engine == "podman"
        assert t.port == 49152

    def test_kubernetes_target(self):
        t = DaemonTarget(
            name="my-pod",
            runtime="kubernetes",
            pod_name="guardian-abc",
            namespace="ai-sdlc",
            port=63152,
        )
        assert t.runtime == "kubernetes"
        assert t.pod_name == "guardian-abc"
        assert t.namespace == "ai-sdlc"

    def test_manual_target(self):
        t = DaemonTarget(
            name="remote",
            runtime="manual",
            url="https://guardian.company.com:63152",
            auth_token="secret",
        )
        assert t.runtime == "manual"
        assert t.url == "https://guardian.company.com:63152"
        assert t.auth_token == "secret"


class TestDiscoverLocal:
    """Tests for local discovery with config file check.

    discover_local() now requires ai-guardian.json to exist.
    All tests use a temp directory to isolate config state.
    """

    def _make_config_dir(self, tmp_path, config_content=None):
        """Create a temp config dir, optionally with ai-guardian.json."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        if config_content is not None:
            (config_dir / "ai-guardian.json").write_text(
                json.dumps(config_content), encoding="utf-8"
            )
        return config_dir

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    def test_no_config_returns_none(self, mock_pid, tmp_path):
        """No ai-guardian.json → discover_local() returns None."""
        config_dir = self._make_config_dir(tmp_path)
        mock_pid.return_value = mock.MagicMock(exists=lambda: False)
        d = DaemonDiscovery()
        with mock.patch(
            "ai_guardian.config.utils.get_config_dir", return_value=config_dir
        ):
            target = d.discover_local()
        assert target is None

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_config_exists_daemon_running(self, mock_running, mock_pid, tmp_path):
        """Config exists + daemon running → status='running', config_exists=True."""
        config_dir = self._make_config_dir(tmp_path, {})
        mock_pid.return_value = mock.MagicMock(exists=lambda: False)
        d = DaemonDiscovery()
        with mock.patch(
            "ai_guardian.config.utils.get_config_dir", return_value=config_dir
        ):
            target = d.discover_local()
        assert target is not None
        assert target.status == "running"
        assert target.config_exists is True

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=False)
    def test_config_exists_daemon_not_running(self, mock_running, mock_pid, tmp_path):
        """Config exists + daemon not running → status='stopped'."""
        config_dir = self._make_config_dir(tmp_path, {})
        mock_pid.return_value = mock.MagicMock(exists=lambda: False)
        d = DaemonDiscovery()
        with mock.patch(
            "ai_guardian.config.utils.get_config_dir", return_value=config_dir
        ):
            target = d.discover_local()
        assert target is not None
        assert target.status == "stopped"
        assert target.config_exists is True

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=False)
    def test_config_name_loaded(self, mock_running, mock_pid, tmp_path):
        """Name loaded from daemon.name in config file."""
        config_dir = self._make_config_dir(
            tmp_path, {"daemon": {"name": "my-workstation"}}
        )
        mock_pid.return_value = mock.MagicMock(exists=lambda: False)
        d = DaemonDiscovery()
        with mock.patch(
            "ai_guardian.config.utils.get_config_dir", return_value=config_dir
        ):
            target = d.discover_local()
        assert target.name == "my-workstation"

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_pid_file_name_overrides_config_name(
        self, mock_running, mock_pid, tmp_path
    ):
        """PID file name takes precedence over config name."""
        config_dir = self._make_config_dir(
            tmp_path, {"daemon": {"name": "config-name"}}
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            json.dump({"pid": 12345, "rest_port": 54321, "name": "pid-name"}, f)
            f.flush()
            from pathlib import Path

            mock_pid.return_value = Path(f.name)

        try:
            d = DaemonDiscovery()
            with mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=config_dir
            ):
                target = d.discover_local()
            assert target.name == "pid-name"
            assert target.port == 54321
        finally:
            os.unlink(f.name)

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_finds_running_daemon(self, mock_running, mock_pid, tmp_path):
        config_dir = self._make_config_dir(tmp_path, {})
        mock_pid.return_value = mock.MagicMock(exists=lambda: False)
        d = DaemonDiscovery()
        with mock.patch(
            "ai_guardian.config.utils.get_config_dir", return_value=config_dir
        ):
            target = d.discover_local()
        assert target is not None
        assert target.name == "local"
        assert target.runtime == "local"
        assert target.status == "running"

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_reads_rest_port_from_pid_file(self, mock_running, mock_pid, tmp_path):
        config_dir = self._make_config_dir(tmp_path, {})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            json.dump({"pid": 12345, "rest_port": 54321}, f)
            f.flush()
            from pathlib import Path

            mock_pid.return_value = Path(f.name)

        try:
            d = DaemonDiscovery()
            with mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=config_dir
            ):
                target = d.discover_local()
            assert target.port == 54321
        finally:
            os.unlink(f.name)


def _make_mock_container(
    container_id="abc123def456",
    name="my-guardian",
    labels=None,
    ports=None,
):
    """Create a mock docker SDK Container object."""
    c = mock.MagicMock()
    c.id = container_id
    c.name = name
    c.labels = labels or {"ai-guardian.daemon": "true"}
    c.ports = ports or {"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49200"}]}
    return c


class TestEngineFromSource:
    def test_docker_socket(self):
        assert _engine_from_source("/var/run/docker.sock") == "docker"

    def test_podman_rootless_socket(self):
        assert _engine_from_source("/run/user/1000/podman/podman.sock") == "podman"

    def test_podman_rootful_socket(self):
        assert _engine_from_source("/run/podman/podman.sock") == "podman"

    def test_docker_host_tcp(self):
        assert _engine_from_source("tcp://localhost:2375") == "docker"

    def test_docker_host_podman(self):
        assert _engine_from_source("unix:///run/podman/podman.sock") == "podman"


class TestDetectEngine:
    def test_podman_detected_via_api(self):
        client = mock.MagicMock()
        client.version.return_value = {
            "Components": [{"Name": "Podman Engine", "Version": "5.4.0"}],
        }
        assert _detect_engine(client, "/var/run/docker.sock") == "podman"

    def test_docker_detected_via_api(self):
        client = mock.MagicMock()
        client.version.return_value = {
            "Components": [{"Name": "Engine", "Version": "27.0.0"}],
        }
        assert _detect_engine(client, "/var/run/docker.sock") == "docker"

    def test_fallback_to_socket_path_on_api_error(self):
        client = mock.MagicMock()
        client.version.side_effect = Exception("connection lost")
        assert _detect_engine(client, "/run/user/1000/podman/podman.sock") == "podman"
        assert _detect_engine(client, "/var/run/docker.sock") == "docker"

    def test_fallback_when_components_empty(self):
        client = mock.MagicMock()
        client.version.return_value = {"Version": "27.0.0"}
        assert _detect_engine(client, "/run/podman/podman.sock") == "podman"
        assert _detect_engine(client, "/var/run/docker.sock") == "docker"

    def test_podman_via_docker_host_env(self):
        client = mock.MagicMock()
        client.version.return_value = {
            "Components": [{"Name": "Podman Engine", "Version": "5.4.0"}],
        }
        assert _detect_engine(client, "unix:///var/run/docker.sock") == "podman"


class TestGetPodmanSocket:
    def test_prefers_xdg_runtime_dir(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/5000"}):
            assert _get_podman_socket() == "/run/user/5000/podman/podman.sock"

    @mock.patch("os.getuid", create=True, return_value=1000)
    def test_falls_back_to_uid_path_when_no_xdg(self, mock_uid):
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            assert _get_podman_socket() == "/run/user/1000/podman/podman.sock"

    def test_returns_none_on_windows(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("os.getuid", create=True, side_effect=AttributeError):
                assert _get_podman_socket() is None


class TestDiscoverContainers:
    """Tests for SDK-based container discovery.

    All tests mock _probe_daemon and _sdk_exec_instance_name to avoid
    actual HTTP/exec calls during container discovery.
    """

    def _patch_probes(self, d, probe_return=None):
        """Patch _probe_daemon and _sdk_exec_instance_name on a discovery instance."""
        return (
            mock.patch.object(d, "_probe_daemon", return_value=probe_return),
            mock.patch.object(d, "_sdk_exec_instance_name", return_value=None),
        )

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", False)
    def test_no_sdk_returns_empty(self):
        d = DaemonDiscovery()
        assert d.discover_containers() == []

    def test_no_reachable_sockets_returns_empty(self):
        d = DaemonDiscovery()
        with mock.patch.object(d, "_get_docker_clients", return_value=[]):
            assert d.discover_containers() == []

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_label_discovery_via_sdk(self):
        container = _make_mock_container()
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 1
        assert targets[0].name == "my-guardian"
        assert targets[0].container_id == "abc123def456"
        assert targets[0].port == 49200
        assert targets[0].container_engine == "podman"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_label_discovery_multiple_containers(self):
        c1 = _make_mock_container(
            container_id="aaa111bbb222ccc333",
            name="daemon-1",
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "50001"}]},
        )
        c2 = _make_mock_container(
            container_id="bbb222ccc333ddd444",
            name="daemon-2",
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "50002"}]},
        )
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [c1, c2]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "docker")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 2

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_port_fallback_discovery(self):
        container = _make_mock_container(
            container_id="abc789def012abc789",
            name="some-container",
            labels={},
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49300"}]},
        )
        mock_client = mock.MagicMock()
        mock_client.containers.list.side_effect = [
            [],
            [container],
        ]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 1
        assert targets[0].name == "some-container"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_deduplicates_by_container_id(self):
        container = _make_mock_container(
            container_id="abc123def456abc123",
            name="guardian",
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49400"}]},
        )
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 1

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_empty_container_list(self):
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = []
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d)
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()
        assert targets == []

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_custom_name_from_label(self):
        container = _make_mock_container(
            container_id="abc123def456abc123",
            name="default-name",
            labels={"ai-guardian.daemon": "true", "ai-guardian.name": "my-sandbox"},
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49500"}]},
        )
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()
        assert targets[0].name == "my-sandbox"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_custom_rest_port_from_label(self):
        container = _make_mock_container(
            container_id="abc123def456abc123",
            name="guardian",
            labels={"ai-guardian.daemon": "true", "ai-guardian.rest-port": "8080"},
            ports={"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49600"}]},
        )
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()
        assert targets[0].port == 49600

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_multi_engine_discovery(self):
        podman_container = _make_mock_container(
            container_id="aaa111bbb222ccc333",
            name="carbonite",
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49700"}]},
        )
        docker_container = _make_mock_container(
            container_id="ddd444eee555fff666",
            name="dev-api",
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49800"}]},
        )
        podman_client = mock.MagicMock()
        podman_client.containers.list.return_value = [podman_container]
        podman_client.close = mock.MagicMock()

        docker_client = mock.MagicMock()
        docker_client.containers.list.return_value = [docker_container]
        docker_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d,
                "_get_docker_clients",
                return_value=[(podman_client, "podman"), (docker_client, "docker")],
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 2
        engines = {t.container_engine for t in targets}
        assert engines == {"podman", "docker"}
        names = {t.name for t in targets}
        assert names == {"carbonite", "dev-api"}

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_multi_engine_deduplication(self):
        container = _make_mock_container(
            container_id="abc123def456abc123",
            name="guardian",
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49900"}]},
        )
        podman_client = mock.MagicMock()
        podman_client.containers.list.return_value = [container]
        podman_client.close = mock.MagicMock()

        docker_client = mock.MagicMock()
        docker_client.containers.list.return_value = [container]
        docker_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d,
                "_get_docker_clients",
                return_value=[(podman_client, "podman"), (docker_client, "docker")],
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 1
        assert targets[0].container_engine == "podman"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_client_close_called(self):
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = []
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        with mock.patch.object(
            d, "_get_docker_clients", return_value=[(mock_client, "docker")]
        ):
            d.discover_containers()

        mock_client.close.assert_called_once()

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_client_close_called_on_error(self):
        mock_client = mock.MagicMock()
        mock_client.containers.list.side_effect = Exception("connection lost")
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        with mock.patch.object(
            d, "_get_docker_clients", return_value=[(mock_client, "docker")]
        ):
            targets = d.discover_containers()

        assert targets == []
        mock_client.close.assert_called_once()


class TestGetDockerClients:
    """Tests for _get_docker_clients socket discovery."""

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    @mock.patch("os.path.exists", return_value=False)
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_no_sockets_returns_empty(self, mock_exists):
        d = DaemonDiscovery()
        with mock.patch("ai_guardian.daemon.discovery.docker_sdk") as mock_docker:
            clients = d._get_docker_clients()
        assert clients == []

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    @mock.patch("os.path.exists")
    @mock.patch.dict(os.environ, {"DOCKER_HOST": "unix:///var/run/docker.sock"})
    def test_docker_host_env_used_first(self, mock_exists):
        mock_exists.return_value = False
        mock_client = mock.MagicMock()
        mock_client.ping.return_value = True
        mock_client.version.return_value = {
            "Components": [{"Name": "Engine", "Version": "27.0.0"}],
        }

        d = DaemonDiscovery()
        with mock.patch("ai_guardian.daemon.discovery.docker_sdk") as mock_docker:
            mock_docker.DockerClient.return_value = mock_client
            clients = d._get_docker_clients()

        assert len(clients) == 1
        assert clients[0][1] == "docker"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    @mock.patch("os.path.exists")
    @mock.patch.dict(os.environ, {"DOCKER_HOST": "unix:///var/run/docker.sock"})
    def test_podman_behind_docker_socket(self, mock_exists):
        """Podman providing Docker-compatible socket is detected as podman."""
        mock_exists.return_value = False
        mock_client = mock.MagicMock()
        mock_client.ping.return_value = True
        mock_client.version.return_value = {
            "Components": [{"Name": "Podman Engine", "Version": "5.4.0"}],
        }

        d = DaemonDiscovery()
        with mock.patch("ai_guardian.daemon.discovery.docker_sdk") as mock_docker:
            mock_docker.DockerClient.return_value = mock_client
            clients = d._get_docker_clients()

        assert len(clients) == 1
        assert clients[0][1] == "podman"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_podman_socket_detected(self):
        mock_client = mock.MagicMock()
        mock_client.ping.return_value = True

        d = DaemonDiscovery()
        podman_sock = _get_podman_socket()

        def mock_exists(path):
            return path == podman_sock

        with (
            mock.patch("ai_guardian.daemon.discovery.docker_sdk") as mock_docker,
            mock.patch("os.path.exists", side_effect=mock_exists),
        ):
            mock_docker.DockerClient.return_value = mock_client
            clients = d._get_docker_clients()

        if podman_sock:
            assert len(clients) == 1
            assert clients[0][1] == "podman"


class TestDiscoverPausedState:
    """Tests for paused state detection from API response (issue #696)."""

    def _patch_probes(self, d, probe_return=None):
        return (
            mock.patch.object(d, "_probe_daemon", return_value=probe_return),
            mock.patch.object(d, "_sdk_exec_instance_name", return_value=None),
        )

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_sdk_container_paused_status(self):
        """Container with paused API response gets status='paused'."""
        container = _make_mock_container()
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"paused": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 1
        assert targets[0].status == "paused"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_sdk_container_running_status(self):
        """Container with paused=False API response gets status='running'."""
        container = _make_mock_container()
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"paused": False})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 1
        assert targets[0].status == "running"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_sdk_container_no_paused_field(self):
        """Container with no paused field in API response gets status='running'."""
        container = _make_mock_container()
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        p1, p2 = self._patch_probes(d, probe_return={"running": True})
        with (
            mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ),
            p1,
            p2,
        ):
            targets = d.discover_containers()

        assert len(targets) == 1
        assert targets[0].status == "running"

    @mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", True)
    def test_sdk_paused_container_still_resolves_exec_name(self):
        """Paused container should NOT fall through to exec name resolution."""
        container = _make_mock_container(labels={})
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [container]
        mock_client.close = mock.MagicMock()

        d = DaemonDiscovery()
        with (
            mock.patch.object(d, "_probe_daemon", return_value={"paused": True}),
            mock.patch.object(
                d, "_sdk_exec_instance_name", return_value="exec-name"
            ) as mock_exec,
        ):
            with mock.patch.object(
                d, "_get_docker_clients", return_value=[(mock_client, "podman")]
            ):
                targets = d.discover_containers()

        mock_exec.assert_not_called()
        assert targets[0].status == "paused"

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_local_daemon_paused_via_api(self, mock_running, mock_pid, tmp_path):
        """Local daemon with paused API response gets status='paused'."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            json.dump({"pid": 12345, "rest_port": 54321}, f)
            f.flush()
            from pathlib import Path

            mock_pid.return_value = Path(f.name)

        try:
            d = DaemonDiscovery()
            with (
                mock.patch(
                    "ai_guardian.config.utils.get_config_dir", return_value=config_dir
                ),
                mock.patch.object(d, "_probe_daemon", return_value={"paused": True}),
            ):
                target = d.discover_local()
            assert target.status == "paused"
        finally:
            os.unlink(f.name)

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_local_daemon_running_via_api(self, mock_running, mock_pid, tmp_path):
        """Local daemon with paused=False API response gets status='running'."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            json.dump({"pid": 12345, "rest_port": 54321}, f)
            f.flush()
            from pathlib import Path

            mock_pid.return_value = Path(f.name)

        try:
            d = DaemonDiscovery()
            with (
                mock.patch(
                    "ai_guardian.config.utils.get_config_dir", return_value=config_dir
                ),
                mock.patch.object(d, "_probe_daemon", return_value={"paused": False}),
            ):
                target = d.discover_local()
            assert target.status == "running"
        finally:
            os.unlink(f.name)

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_local_daemon_no_port_stays_running(self, mock_running, mock_pid, tmp_path):
        """Local daemon without REST port falls back to socket check."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")
        mock_pid.return_value = mock.MagicMock(exists=lambda: False)

        d = DaemonDiscovery()
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=config_dir
            ),
            mock.patch.object(d, "_check_pause_via_socket", return_value=False),
        ):
            target = d.discover_local()
        assert target.status == "running"

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_local_probe_fail_socket_fallback_paused(
        self, mock_running, mock_pid, tmp_path
    ):
        """Probe failure falls back to socket check — paused detected."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            json.dump({"pid": 12345, "rest_port": 54321}, f)
            f.flush()
            from pathlib import Path

            mock_pid.return_value = Path(f.name)

        try:
            d = DaemonDiscovery()
            with (
                mock.patch(
                    "ai_guardian.config.utils.get_config_dir", return_value=config_dir
                ),
                mock.patch.object(d, "_probe_daemon", return_value=None),
                mock.patch.object(d, "_check_pause_via_socket", return_value=True),
            ):
                target = d.discover_local()
            assert target.status == "paused"
        finally:
            os.unlink(f.name)

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    @mock.patch("ai_guardian.daemon.client.is_daemon_running", return_value=True)
    def test_local_no_port_socket_fallback_paused(
        self, mock_running, mock_pid, tmp_path
    ):
        """No REST port falls back to socket check — paused detected."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")
        mock_pid.return_value = mock.MagicMock(exists=lambda: False)

        d = DaemonDiscovery()
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=config_dir
            ),
            mock.patch.object(d, "_check_pause_via_socket", return_value=True),
        ):
            target = d.discover_local()
        assert target.status == "paused"

    @mock.patch("ai_guardian.daemon.discovery.get_pid_path")
    def test_in_process_shortcut_checks_pause(self, mock_pid, tmp_path):
        """In-process shortcut (local_pid == os.getpid()) checks pause state."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text("{}", encoding="utf-8")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            json.dump({"pid": os.getpid(), "rest_port": 54321}, f)
            f.flush()
            from pathlib import Path

            mock_pid.return_value = Path(f.name)

        try:
            d = DaemonDiscovery()
            with (
                mock.patch(
                    "ai_guardian.config.utils.get_config_dir", return_value=config_dir
                ),
                mock.patch.object(d, "_check_pause_via_socket", return_value=True),
            ):
                target = d.discover_local()
            assert target.status == "paused"
        finally:
            os.unlink(f.name)

    def test_check_pause_via_socket_returns_true(self):
        """_check_pause_via_socket returns True when daemon reports paused."""
        with mock.patch(
            "ai_guardian.daemon.client.send_status_request",
            return_value={"paused": True},
        ):
            assert DaemonDiscovery._check_pause_via_socket() is True

    def test_check_pause_via_socket_returns_false(self):
        """_check_pause_via_socket returns False when daemon is running."""
        with mock.patch(
            "ai_guardian.daemon.client.send_status_request",
            return_value={"paused": False},
        ):
            assert DaemonDiscovery._check_pause_via_socket() is False

    def test_check_pause_via_socket_returns_false_on_failure(self):
        """_check_pause_via_socket returns False when socket fails."""
        with mock.patch(
            "ai_guardian.daemon.client.send_status_request", return_value=None
        ):
            assert DaemonDiscovery._check_pause_via_socket() is False


class TestSdkFindHostPort:
    def test_finds_port_from_sdk_format(self):
        c = _make_mock_container(
            ports={"63152/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49200"}]}
        )
        assert DaemonDiscovery._sdk_find_host_port(c, 63152) == 49200

    def test_no_match_returns_zero(self):
        c = _make_mock_container(ports={"8080/tcp": [{"HostPort": "49200"}]})
        assert DaemonDiscovery._sdk_find_host_port(c, 63152) == 0

    def test_empty_ports_returns_zero(self):
        c = mock.MagicMock()
        c.ports = {}
        assert DaemonDiscovery._sdk_find_host_port(c, 63152) == 0

    def test_none_bindings_returns_zero(self):
        c = _make_mock_container(ports={"63152/tcp": None})
        assert DaemonDiscovery._sdk_find_host_port(c, 63152) == 0


class TestSdkExecInstanceName:
    def test_reads_name_from_config(self):
        c = mock.MagicMock()
        c.exec_run.return_value = (0, b"my-daemon\n")
        assert DaemonDiscovery._sdk_exec_instance_name(c) == "my-daemon"

    def test_fallback_to_config_show_summary(self):
        c = mock.MagicMock()
        c.exec_run.side_effect = [
            (1, b""),
            (0, json.dumps({"daemon": {"name": "fallback-name"}}).encode()),
        ]
        assert DaemonDiscovery._sdk_exec_instance_name(c) == "fallback-name"

    def test_returns_none_on_failure(self):
        c = mock.MagicMock()
        c.exec_run.side_effect = Exception("container stopped")
        assert DaemonDiscovery._sdk_exec_instance_name(c) is None

    def test_empty_name_tries_fallback(self):
        c = mock.MagicMock()
        c.exec_run.side_effect = [
            (0, b"\n"),
            (0, json.dumps({"daemon": {"name": "from-config-show"}}).encode()),
        ]
        assert DaemonDiscovery._sdk_exec_instance_name(c) == "from-config-show"


class TestDiscoverKubernetesKubectl:
    """Tests for kubectl-based Kubernetes discovery (fallback)."""

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    def test_no_kubectl_returns_empty(self):
        d = DaemonDiscovery(config={"daemon": {"tray": {"discover_kubernetes": True}}})
        with mock.patch("shutil.which", return_value=None):
            assert d.discover_kubernetes() == []

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/kubectl")
    def test_discovers_running_pods(self, mock_which, mock_run):
        pods = {
            "items": [
                {
                    "metadata": {
                        "name": "guardian-abc12",
                        "labels": {
                            "ai-guardian.daemon": "true",
                            "user": "testuser",
                        },
                    },
                    "status": {"phase": "Running"},
                }
            ]
        }
        mock_run.return_value = mock.MagicMock(
            returncode=0, stdout=json.dumps(pods), stderr=""
        )
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "discover_kubernetes": True,
                        "kubernetes": {"namespaces": ["ai-sdlc"]},
                    }
                }
            }
        )
        targets = d.discover_kubernetes()
        assert len(targets) == 1
        assert targets[0].name == "guardian-abc12"
        assert targets[0].runtime == "kubernetes"
        assert targets[0].status == "running"

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/kubectl")
    def test_kubectl_failure_returns_empty(self, mock_which, mock_run):
        mock_run.return_value = mock.MagicMock(
            returncode=1, stdout="", stderr="connection refused"
        )
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["default"]},
                    }
                }
            }
        )
        assert d.discover_kubernetes() == []

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/kubectl")
    def test_kubectl_multi_namespace(self, mock_which, mock_run):
        pods_ns1 = {
            "items": [
                {
                    "metadata": {
                        "name": "pod-a",
                        "labels": {"ai-guardian.daemon": "true"},
                    },
                    "status": {"phase": "Running"},
                }
            ]
        }
        pods_ns2 = {
            "items": [
                {
                    "metadata": {
                        "name": "pod-b",
                        "labels": {"ai-guardian.daemon": "true"},
                    },
                    "status": {"phase": "Running"},
                }
            ]
        }
        mock_run.side_effect = [
            mock.MagicMock(returncode=0, stdout=json.dumps(pods_ns1), stderr=""),
            mock.MagicMock(returncode=0, stdout="", stderr=""),
            mock.MagicMock(returncode=0, stdout=json.dumps(pods_ns2), stderr=""),
            mock.MagicMock(returncode=0, stdout="", stderr=""),
        ]
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {
                            "namespaces": ["ns1", "ns2"],
                        },
                    }
                }
            }
        )
        targets = d.discover_kubernetes()
        assert len(targets) == 2
        names = {t.name for t in targets}
        assert names == {"pod-a", "pod-b"}

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    def test_backward_compat_namespace_singular(self):
        """namespace (singular) treated as namespaces list."""
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespace": "my-ns"},
                    }
                }
            }
        )
        with (
            mock.patch("shutil.which", return_value="/usr/bin/kubectl"),
            mock.patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout=json.dumps({"items": []}),
                stderr="",
            )
            d.discover_kubernetes()
            call_args = mock_run.call_args_list[0]
            assert "-n" in call_args[0][0]
            ns_idx = call_args[0][0].index("-n")
            assert call_args[0][0][ns_idx + 1] == "my-ns"

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/kubectl")
    def test_kubectl_uses_configured_context(self, mock_which, mock_run):
        mock_run.return_value = mock.MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "items": [
                        {"metadata": {"name": "pod-a"}, "status": {"phase": "Running"}}
                    ]
                }
            ),
            stderr="",
        )
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {
                            "contexts": ["cluster-a"],
                            "namespaces": ["ai-sdlc"],
                        }
                    }
                }
            }
        )
        targets = d.discover_kubernetes()
        command = mock_run.call_args_list[0][0][0]
        assert command[0:3] == ["kubectl", "--context", "cluster-a"]
        assert targets[0].context == "cluster-a"


def _make_mock_k8s_pod(
    name="guardian-pod",
    namespace="ai-guardian",
    labels=None,
    phase="Running",
    pod_ip="10.0.0.5",
):
    """Create a mock K8s V1Pod object."""
    pod = mock.MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.labels = labels or {"ai-guardian.daemon": "true"}
    pod.status.phase = phase
    pod.status.pod_ip = pod_ip
    return pod


def _make_mock_k8s_service(
    name="ai-guardian-svc",
    selector=None,
    svc_type="ClusterIP",
    cluster_ip="10.96.0.10",
    ports=None,
    node_port=None,
    lb_ip=None,
):
    """Create a mock K8s V1Service object."""
    svc = mock.MagicMock()
    svc.metadata.name = name
    svc.spec.selector = selector or {"ai-guardian.daemon": "true"}
    svc.spec.type = svc_type
    svc.spec.cluster_ip = cluster_ip

    if ports is None:
        port_obj = mock.MagicMock()
        port_obj.port = 63152
        port_obj.target_port = 63152
        port_obj.node_port = node_port
        svc.spec.ports = [port_obj]
    else:
        svc.spec.ports = ports

    if lb_ip:
        ingress = mock.MagicMock()
        ingress.ip = lb_ip
        ingress.hostname = None
        svc.status.load_balancer.ingress = [ingress]
    else:
        svc.status.load_balancer.ingress = []

    return svc


import contextlib

_SENTINEL = object()


@contextlib.contextmanager
def _k8s_sdk_mocks():
    """Replace k8s_config, k8s_client, K8sApiException, k8s_stream on the
    discovery module with mocks, restoring originals on exit. Works whether
    the kubernetes package is installed or not."""
    import ai_guardian.daemon.discovery as disc

    _mock_k8s_config = mock.MagicMock()
    _mock_k8s_client = mock.MagicMock()
    _mock_api_exc = type("ApiException", (Exception,), {"status": 0})
    _mock_stream = mock.MagicMock()

    originals = {}
    for attr, val in [
        ("k8s_config", _mock_k8s_config),
        ("k8s_client", _mock_k8s_client),
        ("K8sApiException", _mock_api_exc),
        ("k8s_stream", _mock_stream),
    ]:
        originals[attr] = getattr(disc, attr, _SENTINEL)
        setattr(disc, attr, val)

    try:
        yield _mock_k8s_config, _mock_k8s_client, _mock_api_exc, _mock_stream
    finally:
        for attr, orig in originals.items():
            if orig is _SENTINEL:
                delattr(disc, attr)
            else:
                setattr(disc, attr, orig)


class TestDiscoverKubernetesSDK:
    """Tests for kubernetes SDK-based discovery."""

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/kubectl")
    def test_no_sdk_falls_back_to_kubectl(self, mock_which, mock_run):
        mock_run.return_value = mock.MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "items": [
                        {
                            "metadata": {
                                "name": "kubectl-pod",
                                "labels": {"ai-guardian.daemon": "true"},
                            },
                            "status": {"phase": "Running"},
                        }
                    ]
                }
            ),
            stderr="",
        )
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["default"]},
                    }
                }
            }
        )
        targets = d.discover_kubernetes()
        assert len(targets) == 1
        assert targets[0].name == "kubectl-pod"

    def test_sdk_discovers_pods_single_namespace(self):
        pod = _make_mock_k8s_pod()
        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = []

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ai-guardian"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 1
        assert targets[0].name == "guardian-pod"
        assert targets[0].runtime == "kubernetes"
        assert targets[0].namespace == "ai-guardian"
        assert targets[0].context == "default"
        assert targets[0].host == "10.0.0.5"

    def test_sdk_discovers_pods_multi_namespace(self):
        pod1 = _make_mock_k8s_pod(name="pod-ns1", namespace="ns1")
        pod2 = _make_mock_k8s_pod(name="pod-ns2", namespace="ns2", pod_ip="10.0.0.6")

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.side_effect = [
            mock.MagicMock(items=[pod1]),
            mock.MagicMock(items=[pod2]),
        ]
        mock_api.list_namespaced_service.return_value.items = []

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ns1", "ns2"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 2
        names = {t.name for t in targets}
        assert names == {"pod-ns1", "pod-ns2"}
        namespaces = {t.namespace for t in targets}
        assert namespaces == {"ns1", "ns2"}

    def test_sdk_discovers_pods_multi_context(self):
        pod1 = _make_mock_k8s_pod(name="pod-dev", namespace="ai-guardian")
        pod2 = _make_mock_k8s_pod(
            name="pod-staging", namespace="ai-guardian", pod_ip="10.0.1.5"
        )

        call_count = {"n": 0}

        def mock_core_v1_api(api_client):
            api = mock.MagicMock()
            call_count["n"] += 1
            if call_count["n"] == 1:
                api.list_namespaced_pod.return_value.items = [pod1]
            else:
                api.list_namespaced_pod.return_value.items = [pod2]
            api.list_namespaced_service.return_value.items = []
            return api

        all_contexts = [{"name": "dev"}, {"name": "staging"}]
        active_ctx = {"name": "dev"}

        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {
                            "contexts": ["dev", "staging"],
                            "namespaces": ["ai-guardian"],
                        },
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                all_contexts,
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.side_effect = mock_core_v1_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 2
        contexts = {t.context for t in targets}
        assert contexts == {"dev", "staging"}

    def test_sdk_service_nodeport_connectivity(self):
        pod = _make_mock_k8s_pod()
        svc = _make_mock_k8s_service(svc_type="NodePort", node_port=30152)

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = [svc]

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ai-guardian"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 1
        assert targets[0].host == "127.0.0.1"
        assert targets[0].port == 30152

    def test_sdk_service_clusterip_connectivity(self):
        pod = _make_mock_k8s_pod()
        svc = _make_mock_k8s_service(svc_type="ClusterIP", cluster_ip="10.96.0.10")

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = [svc]

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ai-guardian"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 1
        assert targets[0].host == "10.96.0.10"
        assert targets[0].port == 63152

    def test_sdk_no_service_uses_pod_ip(self):
        pod = _make_mock_k8s_pod(pod_ip="10.0.0.99")

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = []

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ai-guardian"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 1
        assert targets[0].host == "10.0.0.99"
        assert targets[0].port == 63152

    def test_sdk_graceful_on_api_error(self):
        mock_exc = type("ApiException", (Exception,), {"status": 403})

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.side_effect = mock_exc()

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ai-guardian"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch(
                    "ai_guardian.daemon.discovery.K8sApiException",
                    mock_exc,
                ),
            ):
                targets = d.discover_kubernetes()

        assert targets == []

    def test_sdk_auth_token_from_pod(self):
        pod = _make_mock_k8s_pod()

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = []

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ai-guardian"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, m_stream):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            m_stream.return_value = "test-token-abc123\n"
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 1
        assert targets[0].auth_token == "test-token-abc123"

    def test_sdk_custom_label_selector(self):
        pod = _make_mock_k8s_pod(labels={"app": "custom-guardian", "env": "prod"})

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = []

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {
                            "namespaces": ["prod"],
                            "label_selector": "app=custom-guardian",
                            "ownership": {"value": "testuser"},
                        },
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        mock_api.list_namespaced_pod.assert_called_once_with(
            namespace="prod",
            label_selector="app=custom-guardian,ai-guardian.owner=testuser",
        )
        assert len(targets) == 1

    def test_sdk_ownership_scope_is_added_to_custom_selector(self):
        pod = _make_mock_k8s_pod(
            labels={"app": "guardian", "ai-guardian.owner": "alice"}
        )
        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = []
        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {
                            "namespaces": ["shared"],
                            "label_selector": "app=guardian",
                            "ownership": {"value": "alice"},
                        }
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = ([active_ctx], active_ctx)
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                assert len(d.discover_kubernetes()) == 1

        mock_api.list_namespaced_pod.assert_called_once_with(
            namespace="shared",
            label_selector="app=guardian,ai-guardian.owner=alice",
        )

    @mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False)
    @mock.patch.dict(os.environ, {"USER": "alice"}, clear=True)
    def test_kubectl_scope_prevents_cross_user_pod_queries(self):
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespace": "shared"},
                    }
                }
            }
        )
        with (
            mock.patch("shutil.which", return_value="/usr/bin/kubectl"),
            mock.patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.MagicMock(
                returncode=0, stdout=json.dumps({"items": []}), stderr=""
            )
            d.discover_kubernetes()

        assert mock_run.call_args_list[0].args[0][4] == (
            "app=ai-guardian,ai-guardian.owner=alice"
        )

    def test_sdk_uses_default_namespace_when_none_configured(self):
        pod = _make_mock_k8s_pod()

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = []

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(config={"daemon": {"tray": {"kubernetes": {}}}})
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        mock_api.list_namespaced_pod.assert_called_once_with(
            namespace="ai-sdlc",
            label_selector="app=ai-guardian,ai-guardian.owner=dvernier",
        )
        assert len(targets) == 1

    @mock.patch.dict(os.environ, {"USERNAME": "windows-user"}, clear=True)
    def test_windows_username_is_used_for_default_ownership_scope(self):
        with mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", False):
            d = DaemonDiscovery(
                config={"daemon": {"tray": {"kubernetes": {"namespace": "shared"}}}}
            )
            with (
                mock.patch("shutil.which", return_value=None),
                mock.patch.object(d, "_discover_kubernetes_kubectl") as discover,
            ):
                d.discover_kubernetes()

        discover.assert_called_once_with(
            ["shared"],
            "app=ai-guardian,ai-guardian.owner=windows-user",
            63152,
            None,
        )

    def test_sdk_loadbalancer_connectivity(self):
        pod = _make_mock_k8s_pod()
        svc = _make_mock_k8s_service(svc_type="LoadBalancer", lb_ip="203.0.113.10")

        mock_api = mock.MagicMock()
        mock_api.list_namespaced_pod.return_value.items = [pod]
        mock_api.list_namespaced_service.return_value.items = [svc]

        active_ctx = {"name": "default"}
        d = DaemonDiscovery(
            config={
                "daemon": {
                    "tray": {
                        "kubernetes": {"namespaces": ["ai-guardian"]},
                    }
                }
            }
        )
        with _k8s_sdk_mocks() as (m_cfg, m_cli, _, _):
            m_cfg.list_kube_config_contexts.return_value = (
                [active_ctx],
                active_ctx,
            )
            m_cfg.new_client_from_config.return_value = mock.MagicMock()
            m_cli.CoreV1Api.return_value = mock_api
            with (
                mock.patch("ai_guardian.daemon.discovery.HAS_K8S_SDK", True),
                mock.patch.object(d, "_sdk_k8s_auth_token", return_value=None),
                mock.patch.object(d, "_probe_daemon", return_value=None),
            ):
                targets = d.discover_kubernetes()

        assert len(targets) == 1
        assert targets[0].host == "203.0.113.10"
        assert targets[0].port == 63152


class TestDiscoverManual:
    def test_missing_file_returns_empty(self):
        d = DaemonDiscovery()
        with mock.patch("ai_guardian.daemon.discovery.get_tray_targets_path") as m:
            m.return_value = mock.MagicMock(exists=lambda: False)
            assert d.discover_manual() == []

    def test_loads_targets(self):
        data = {
            "daemons": [
                {
                    "name": "central",
                    "url": "https://guardian.company.com:63152",
                    "token": "secret123",
                }
            ]
        }
        d = DaemonDiscovery()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            from pathlib import Path

            with mock.patch(
                "ai_guardian.daemon.discovery.get_tray_targets_path",
                return_value=Path(f.name),
            ):
                targets = d.discover_manual()

        os.unlink(f.name)
        assert len(targets) == 1
        assert targets[0].name == "central"
        assert targets[0].runtime == "manual"
        assert targets[0].host == "guardian.company.com"
        assert targets[0].port == 63152
        assert targets[0].auth_token == "secret123"

    def test_invalid_json_returns_empty(self):
        d = DaemonDiscovery()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            f.flush()
            from pathlib import Path

            with mock.patch(
                "ai_guardian.daemon.discovery.get_tray_targets_path",
                return_value=Path(f.name),
            ):
                targets = d.discover_manual()

        os.unlink(f.name)
        assert targets == []


class TestBackgroundDiscovery:
    @mock.patch.object(DaemonDiscovery, "discover_all")
    def test_callback_receives_targets(self, mock_discover):
        targets = [DaemonTarget(name="local", runtime="local", status="running")]
        mock_discover.return_value = targets

        received = []
        d = DaemonDiscovery()
        d.start_background_discovery(lambda t: received.append(t))

        import time

        time.sleep(0.3)
        d.stop()

        assert len(received) >= 1
        assert received[0][0].name == "local"

    def test_stop_terminates_thread(self):
        d = DaemonDiscovery()
        with mock.patch.object(d, "discover_all", return_value=[]):
            d.start_background_discovery(lambda t: None)
            assert d._thread is not None
            d.stop()
            assert not d._running

    @mock.patch.object(DaemonDiscovery, "discover_all")
    def test_callback_called_with_empty_list_on_exception(self, mock_discover):
        mock_discover.side_effect = RuntimeError("discovery failed")

        received = []
        d = DaemonDiscovery()
        d.start_background_discovery(lambda t: received.append(t))

        import time

        time.sleep(0.3)
        d.stop()

        assert len(received) >= 1
        assert received[0] == []


class TestProbeDaemonSocketPreCheck:
    """Tests for socket-level connect check in _probe_daemon (issue #711)."""

    def test_returns_none_on_socket_timeout(self):
        with mock.patch("socket.socket") as mock_socket_cls:
            import socket

            mock_sock = mock.MagicMock()
            mock_sock.connect.side_effect = socket.timeout("timed out")
            mock_socket_cls.return_value = mock_sock
            assert DaemonDiscovery._probe_daemon(63152) is None
            mock_sock.connect.assert_called_once_with(("127.0.0.1", 63152))

    def test_returns_none_on_connection_refused(self):
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_sock.connect.side_effect = ConnectionRefusedError
            mock_socket_cls.return_value = mock_sock
            assert DaemonDiscovery._probe_daemon(63152) is None

    @mock.patch("urllib.request.urlopen")
    def test_succeeds_after_socket_connect(self, mock_urlopen):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = b'{"status": "running"}'
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_socket_cls.return_value = mock_sock
            result = DaemonDiscovery._probe_daemon(63152)
            assert result == {"status": "running"}
            mock_sock.connect.assert_called_once()
            mock_sock.close.assert_called_once()

    def test_accepts_host_parameter(self):
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_sock.connect.side_effect = ConnectionRefusedError
            mock_socket_cls.return_value = mock_sock
            DaemonDiscovery._probe_daemon(63152, host="10.0.0.5")
            mock_sock.connect.assert_called_once_with(("10.0.0.5", 63152))


class TestDiscoverAllParallel:
    """Tests for parallel discovery with ThreadPoolExecutor (issue #711)."""

    def test_all_methods_run(self):
        d = DaemonDiscovery()
        local_target = DaemonTarget(name="local", runtime="local")
        manual_targets = [DaemonTarget(name="m1", runtime="manual")]

        with (
            mock.patch.object(d, "discover_local", return_value=local_target) as ml,
            mock.patch.object(d, "discover_containers", return_value=[]) as mc,
            mock.patch.object(d, "discover_manual", return_value=manual_targets) as mm,
        ):
            results = d.discover_all()
            ml.assert_called_once()
            mc.assert_called_once()
            mm.assert_called_once()
            assert len(results) == 2

    def test_results_merged_correctly(self):
        d = DaemonDiscovery()
        local = DaemonTarget(name="local", runtime="local")
        containers = [
            DaemonTarget(name="c1", runtime="container"),
            DaemonTarget(name="c2", runtime="container"),
        ]
        manual = [DaemonTarget(name="m1", runtime="manual")]

        with (
            mock.patch.object(d, "discover_local", return_value=local),
            mock.patch.object(d, "discover_containers", return_value=containers),
            mock.patch.object(d, "discover_manual", return_value=manual),
        ):
            results = d.discover_all()
            names = [t.name for t in results]
            assert "local" in names
            assert "c1" in names
            assert "c2" in names
            assert "m1" in names

    def test_slow_method_does_not_block_others(self):
        import time

        d = DaemonDiscovery()
        local = DaemonTarget(name="local", runtime="local")

        def slow_containers():
            time.sleep(30)
            return []

        with (
            mock.patch.object(d, "discover_local", return_value=local),
            mock.patch.object(d, "discover_containers", side_effect=slow_containers),
            mock.patch.object(d, "discover_manual", return_value=[]),
        ):
            start = time.monotonic()
            results = d.discover_all()
            elapsed = time.monotonic() - start
            assert elapsed < 7
            assert any(t.name == "local" for t in results)

    def test_failing_method_does_not_affect_others(self):
        d = DaemonDiscovery()
        local = DaemonTarget(name="local", runtime="local")

        with (
            mock.patch.object(d, "discover_local", return_value=local),
            mock.patch.object(
                d, "discover_containers", side_effect=RuntimeError("boom")
            ),
            mock.patch.object(d, "discover_manual", return_value=[]),
        ):
            results = d.discover_all()
            assert any(t.name == "local" for t in results)

    def test_config_disables_containers(self):
        d = DaemonDiscovery(config={"daemon": {"tray": {"discover_containers": False}}})
        local = DaemonTarget(name="local", runtime="local")

        with (
            mock.patch.object(d, "discover_local", return_value=local),
            mock.patch.object(d, "discover_containers") as mc,
            mock.patch.object(d, "discover_manual", return_value=[]),
        ):
            d.discover_all()
            mc.assert_not_called()

    def test_local_none_not_appended(self):
        d = DaemonDiscovery()
        with (
            mock.patch.object(d, "discover_local", return_value=None),
            mock.patch.object(d, "discover_containers", return_value=[]),
            mock.patch.object(d, "discover_manual", return_value=[]),
        ):
            results = d.discover_all()
            assert len(results) == 0

    def test_targets_stored_under_lock(self):
        d = DaemonDiscovery()
        local = DaemonTarget(name="local", runtime="local")

        with (
            mock.patch.object(d, "discover_local", return_value=local),
            mock.patch.object(d, "discover_containers", return_value=[]),
            mock.patch.object(d, "discover_manual", return_value=[]),
        ):
            d.discover_all()
            assert len(d.targets) == 1
            assert d.targets[0].name == "local"


class TestContainerEventStream:
    """Tests for container event streaming (#650)."""

    def test_start_noop_without_docker_sdk(self):
        d = DaemonDiscovery()
        with mock.patch("ai_guardian.daemon.discovery.HAS_DOCKER_SDK", False):
            d.start_container_event_stream(callback=lambda: None)
        assert not hasattr(d, "_event_threads") or not d._event_threads

    def test_stop_sets_flag(self):
        d = DaemonDiscovery()
        d._event_stream_running = True
        d.stop_container_event_stream()
        assert d._event_stream_running is False

    def test_stream_calls_callback_on_matching_event(self):
        d = DaemonDiscovery()
        d._event_stream_running = True
        called = threading.Event()

        def fake_callback():
            called.set()
            d._event_stream_running = False

        fake_event = {
            "Action": "start",
            "Actor": {
                "Attributes": {
                    "ai-guardian.daemon": "true",
                    "name": "ag-test",
                }
            },
        }

        mock_client = mock.MagicMock()
        mock_client.events.return_value = iter([fake_event])

        d._stream_container_events(mock_client, "podman", fake_callback)
        assert called.is_set()

    def test_stream_ignores_non_matching_event(self):
        d = DaemonDiscovery()
        d._event_stream_running = True
        called = {"n": 0}

        def fake_callback():
            called["n"] += 1

        non_matching = {
            "Action": "start",
            "Actor": {"Attributes": {"name": "some-other-container"}},
        }

        call_count = {"n": 0}

        def events_side_effect(**kw):
            call_count["n"] += 1
            if call_count["n"] > 1:
                d._event_stream_running = False
                return iter([])
            return iter([non_matching])

        mock_client = mock.MagicMock()
        mock_client.events.side_effect = events_side_effect

        d._stream_container_events(mock_client, "docker", fake_callback)
        assert called["n"] == 0

    def test_stream_reconnects_on_error(self):
        d = DaemonDiscovery()
        d._event_stream_running = True
        attempt = {"n": 0}

        def side_effect(*a, **kw):
            attempt["n"] += 1
            if attempt["n"] >= 2:
                d._event_stream_running = False
            raise ConnectionError("lost")

        mock_client = mock.MagicMock()
        mock_client.events.side_effect = side_effect

        with mock.patch("time.sleep"):
            d._stream_container_events(mock_client, "podman", lambda: None)

        assert attempt["n"] >= 2
