"""Bounded source jobs and authenticated collection-only HTTP endpoints."""

import json
import subprocess
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ai_guardian.daemon.rest_api import DaemonRestAPI
from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.daemon.multi_client import MultiDaemonClient
from ai_guardian.daemon.rest_transport import DaemonConnectionError, DaemonHTTPError
from ai_guardian.reporting.remote_support import SupportCollectionError
from ai_guardian.daemon.support import COLLECTION_TIMEOUT, SupportJobs
from ai_guardian.daemon import support as source_support
from tests.fixtures.support_remote import diagnostics


def request(port, path, *, token=None, body=None):
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urlopen(req, timeout=5) as response:
        return json.load(response)


@pytest.mark.parametrize("configured", [None, "synthetic-auth"])
def test_support_endpoints_require_authentication_even_on_loopback(configured):
    api = DaemonRestAPI(Mock(), port=0, auth_token=configured)
    port = api.start()
    try:
        for path, body in [
            ("/api/support-bundles", {}),
            ("/api/support-bundles/" + "a" * 32, None),
        ]:
            with pytest.raises(HTTPError) as caught:
                request(port, path, body=body)
            assert caught.value.code == 401
            caught.value.close()
    finally:
        api.stop()


@pytest.mark.parametrize(
    "body",
    [
        {"path": "/private"},
        {"command": "anything"},
        {"destination": "elsewhere"},
        [],
        "value",
    ],
)
def test_collection_api_accepts_no_paths_commands_or_delivery_authority(body):
    api = DaemonRestAPI(Mock(), port=0, auth_token="synthetic-auth")
    port = api.start()
    try:
        with pytest.raises(HTTPError) as caught:
            request(port, "/api/support-bundles", token="synthetic-auth", body=body)
        assert caught.value.code == 400
        caught.value.close()
    finally:
        api.stop()


def test_authenticated_api_prepares_then_retrieves_exact_job(monkeypatch):
    api = DaemonRestAPI(Mock(), port=0, auth_token="synthetic-auth")
    port = api.start()
    try:
        jobs = api._server.support_jobs
        monkeypatch.setattr(jobs, "_collect", Mock())
        job = request(port, "/api/support-bundles", token="synthetic-auth", body={})
        assert job["status"] == "preparing"
        assert (
            request(
                port, "/api/support-bundles/" + job["job_id"], token="synthetic-auth"
            )
            == job
        )
        assert (
            request(port, "/api/support-bundles/unknown", token="synthetic-auth")[
                "error_code"
            ]
            == "expired"
        )
    finally:
        api.stop()


def test_source_job_uses_fixed_isolated_collector_and_observed_projects(monkeypatch):
    state = Mock()
    state.get_project_cache_status.return_value = {
        "projects": [{"config_path": "/source/project/.ai-guardian/ai-guardian.json"}]
    }
    jobs = SupportJobs(state, "Source VM")
    monkeypatch.setattr("ai_guardian.daemon.support.threading.Thread", Mock())
    job = jobs.start()

    def run(argv, **kwargs):
        assert argv[1:3] == ["-I", "-c"]
        assert "ai_guardian.daemon.support" in argv[3]
        assert kwargs["timeout"] == COLLECTION_TIMEOUT
        assert kwargs["stderr"] is subprocess.DEVNULL
        staging = kwargs["env"]["TMPDIR"]
        from pathlib import Path

        assert (Path(staging) / ".ai-read-deny").exists()
        from ai_guardian import __version__

        assert json.loads(kwargs["input"]) == {
            "name": "Source VM",
            "projects": ["/source/project/.ai-guardian/ai-guardian.json"],
            "daemon_version": __version__,
        }
        kwargs["stdout"].write(json.dumps(diagnostics()).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("ai_guardian.daemon.support.subprocess.run", run)
    jobs._collect(job["job_id"])
    result = jobs.get(job["job_id"])
    assert result["status"] == "ready"
    assert result["diagnostics"] == diagnostics()
    assert jobs.start()["status"] == "preparing"
    assert jobs.start()["error_code"] == "busy"
    jobs.close()
    assert jobs.get(job["job_id"])["error_code"] == "expired"


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired("collector", 90), ValueError("private source data")],
)
def test_source_failures_never_return_raw_errors(monkeypatch, failure):
    jobs = SupportJobs(
        Mock(get_project_cache_status=lambda: {"projects": []}), "Source VM"
    )
    monkeypatch.setattr("ai_guardian.daemon.support.threading.Thread", Mock())
    job = jobs.start()
    monkeypatch.setattr(
        "ai_guardian.daemon.support.subprocess.run", Mock(side_effect=failure)
    )
    jobs._collect(job["job_id"])
    result = jobs.get(job["job_id"])
    assert result["status"] == "error"
    assert "private source data" not in json.dumps(result)
    assert result["error_code"] == (
        "timeout" if isinstance(failure, subprocess.TimeoutExpired) else "collection"
    )


@pytest.mark.parametrize(
    "runtime,runtime_type",
    [
        ("local", None),
        ("container", None),
        ("kubernetes", None),
        ("manual", None),
        ("ssh", None),
        ("manual", "openshell"),
    ],
)
def test_all_transports_collect_selected_daemon_without_exec_or_local_fallback(
    monkeypatch, runtime, runtime_type
):
    client = MultiDaemonClient()
    selected = DaemonTarget("Source", runtime, runtime_type=runtime_type)
    send = Mock(
        side_effect=[
            {"status": "preparing", "job_id": "a" * 32},
            {"status": "ready", "job_id": "a" * 32, "diagnostics": diagnostics()},
        ]
    )
    monkeypatch.setattr(client, "_rest_request", send)
    for method in ("_local_exec", "_container_exec", "_kubectl_exec"):
        monkeypatch.setattr(
            client, method, Mock(side_effect=AssertionError("No CLI fallback"))
        )
    assert client.export_support(selected) == diagnostics()
    assert send.call_args_list[0].args == (selected, "POST", "/api/support-bundles", {})
    assert send.call_args.args == (selected, "GET", "/api/support-bundles/" + "a" * 32)
    assert all(call.kwargs == {"raise_errors": True} for call in send.call_args_list)


@pytest.mark.parametrize(
    "status,message",
    [
        (401, "Authentication failed"),
        (403, "Authentication failed"),
        (404, "does not support"),
        (405, "does not support"),
        (500, "could not provide"),
    ],
)
def test_http_feedback_is_specific_and_credential_free(monkeypatch, status, message):
    client = MultiDaemonClient()
    monkeypatch.setattr(
        client, "_rest_request", Mock(side_effect=DaemonHTTPError(status))
    )
    with pytest.raises(SupportCollectionError, match=message):
        client.export_support(DaemonTarget("Source", "manual"))


@pytest.mark.parametrize(
    "failure", [DaemonConnectionError("private transport data"), None]
)
def test_offline_and_malformed_initial_jobs_fail_closed(monkeypatch, failure):
    client = MultiDaemonClient()
    send = Mock(side_effect=failure) if failure else Mock(return_value=None)
    monkeypatch.setattr(client, "_rest_request", send)
    with pytest.raises(SupportCollectionError) as caught:
        client.export_support(DaemonTarget("Source", "ssh"))
    assert "private transport data" not in str(caught.value)
    assert "Nothing was sent" in str(caught.value)


def test_ssh_preserves_http_status_and_uses_enrolled_tunnel():
    tunnel = Mock()
    tunnel.request.side_effect = DaemonHTTPError(404)
    target = DaemonTarget("Source", "ssh", ssh_tunnel=tunnel)
    with pytest.raises(SupportCollectionError, match="does not support"):
        MultiDaemonClient().export_support(target)
    tunnel.request.assert_called_once_with(
        "POST", "/api/support-bundles", {}, timeout=5.0, raise_http_errors=True
    )


def test_healthy_ssh_without_collection_api_stays_connected_and_reports_unsupported(
    monkeypatch,
):
    from ai_guardian.daemon.ssh_tunnel import SSHTunnel

    tunnel = SSHTunnel(
        SimpleNamespace(profile=SimpleNamespace(token="synthetic-auth")), Mock()
    )
    tunnel.process = Mock(poll=Mock(return_value=None))
    tunnel.port = 12345
    http_error = HTTPError(
        "https://127.0.0.1:12345/api/support-bundles",
        404,
        "Not found",
        {},
        io.BytesIO(b"Private source response must never become the error message"),
    )
    monkeypatch.setattr(
        "ai_guardian.daemon.ssh_tunnel.open_daemon_request",
        Mock(side_effect=http_error),
    )
    target = DaemonTarget("Chosen VM", "ssh", status="running", ssh_tunnel=tunnel)

    with pytest.raises(
        SupportCollectionError, match="does not support remote diagnostics"
    ) as error:
        MultiDaemonClient().export_support(target)

    assert target.status == "running"
    assert tunnel.active
    assert "offline" not in str(error.value)
    assert "Private source response" not in str(error.value)
    assert "synthetic-auth" not in str(error.value)


@pytest.mark.parametrize(
    "body,headers", [(b"{}", {"Content-Length": "99999999"}), (b"malformed JSON", {})]
)
def test_strict_rest_reads_reject_oversized_and_malformed_responses(
    monkeypatch, body, headers
):
    import io

    response = io.BytesIO(body)
    response.headers = headers
    monkeypatch.setattr(
        "ai_guardian.daemon.multi_client.open_daemon_request",
        Mock(return_value=response),
    )
    monkeypatch.setattr(MultiDaemonClient, "_tcp_reachable", Mock(return_value=True))
    with pytest.raises(DaemonConnectionError):
        MultiDaemonClient._rest_request(
            DaemonTarget("Source", "manual", url="https://source.invalid"),
            "POST",
            "/api/support-bundles",
            {},
            raise_errors=True,
        )


def test_http_support_uses_existing_authentication_gateway_header_and_tls(monkeypatch):
    import io

    response = io.BytesIO(
        json.dumps({"job_id": "a" * 32, "status": "preparing"}).encode()
    )
    response.headers = {}
    open_request = Mock(return_value=response)
    monkeypatch.setattr(
        "ai_guardian.daemon.multi_client.open_daemon_request", open_request
    )
    monkeypatch.setattr(MultiDaemonClient, "_tcp_reachable", Mock(return_value=True))
    target = DaemonTarget(
        "Source",
        "manual",
        url="https://source.invalid",
        auth_token="synthetic-auth",
        tls={"server_name": "verified.invalid"},
    )
    assert (
        MultiDaemonClient._rest_request(
            target, "POST", "/api/support-bundles", {}, raise_errors=True
        )["status"]
        == "preparing"
    )
    req = open_request.call_args.args[0]
    assert req.get_header("Authorization") == "Bearer synthetic-auth"
    assert req.get_header("X-ai-guardian-token") == "synthetic-auth"
    assert open_request.call_args.kwargs["tls"].server_name == "verified.invalid"


def test_worker_entry_adds_only_source_cwd_project_and_emits_collection(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        source_support.sys,
        "stdin",
        io.StringIO(
            json.dumps({"name": "Source VM", "projects": ["/source/observed.json"]})
        ),
    )
    monkeypatch.setattr(
        "ai_guardian.config.utils.get_project_config_path",
        lambda: Path("/source/cwd/.ai-guardian/ai-guardian.json"),
    )
    collect = Mock(return_value=diagnostics())
    monkeypatch.setattr(
        "ai_guardian.reporting.remote_support.collect_diagnostics", collect
    )
    source_support._main()
    assert json.loads(capsys.readouterr().out) == diagnostics()
    collect.assert_called_once_with(
        "Source VM",
        [
            Path("/source/observed.json"),
            Path("/source/cwd/.ai-guardian/ai-guardian.json"),
        ],
        daemon_version=None,
    )


def test_isolated_source_bootstrap_uses_installation_not_malicious_cwd(tmp_path):
    package = tmp_path / "ai_guardian"
    package.mkdir()
    (package / "__init__.py").write_text(
        "raise RuntimeError('must not import the current project')"
    )
    command = source_support._collector_command()
    command[3] = command[3].replace(
        "runpy.run_module('ai_guardian.daemon.support', run_name='__main__')",
        "import ai_guardian; print(ai_guardian.__file__)",
    )
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert str(package) not in result.stdout
    assert "ai_guardian" in result.stdout


def test_collector_explicitly_supports_user_site_dependencies(monkeypatch, tmp_path):
    user_site = tmp_path / "user-site"
    user_site.mkdir()
    (user_site / "support_test_dependency.py").write_text(
        "marker = 'user-site dependency'"
    )
    monkeypatch.setattr(source_support.site, "ENABLE_USER_SITE", True)
    monkeypatch.setattr(
        source_support.site, "getusersitepackages", lambda: str(user_site)
    )
    command = source_support._collector_command()
    assert command[1:3] == ["-I", "-c"]
    assert str(user_site) in command[4:]
    assert str(Path(source_support.__file__).resolve().parents[2]) in command[4:]
    command[3] = command[3].replace(
        "runpy.run_module('ai_guardian.daemon.support', run_name='__main__')",
        "import support_test_dependency; print(support_test_dependency.marker)",
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "user-site dependency"


@pytest.mark.parametrize("enabled", [False, None])
def test_collector_does_not_add_disabled_user_installations(monkeypatch, enabled):
    monkeypatch.setattr(source_support.site, "ENABLE_USER_SITE", enabled)
    monkeypatch.setattr(
        source_support.site,
        "getusersitepackages",
        Mock(
            side_effect=AssertionError("Disabled user site must not affect the worker")
        ),
    )
    assert source_support._collector_command()[4:] == [
        str(Path(source_support.__file__).resolve().parents[2])
    ]


def test_project_distribution_metadata_cannot_inject_dependency_imports(
    monkeypatch, tmp_path
):
    metadata = tmp_path / "ai_guardian-999.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: ai-guardian\nVersion: 999\n")
    (tmp_path / "jsonschema.py").write_text(
        "raise RuntimeError('must not import a project dependency')"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    command = source_support._collector_command()
    command[3] = command[3].replace(
        "runpy.run_module('ai_guardian.daemon.support', run_name='__main__')",
        "import jsonschema; print(jsonschema.__file__)",
    )
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert str(tmp_path) not in result.stdout


def test_jobs_expire_and_bound_completed_result_count(monkeypatch):
    jobs = SupportJobs(Mock(), "Source VM")
    monkeypatch.setattr(source_support.threading, "Thread", Mock())
    clock = SimpleNamespace(monotonic=Mock(return_value=100))
    monkeypatch.setattr(source_support, "time", clock)
    for _ in range(4):
        job = jobs.start()
        jobs._running = False
    assert jobs.start()["error_code"] == "busy"
    clock.monotonic.return_value = 401
    assert jobs.get(job["job_id"])["error_code"] == "expired"
    assert jobs.start()["status"] == "preparing"


def test_worker_start_failure_and_closed_jobs_fail_safely(monkeypatch):
    jobs = SupportJobs(Mock(), "Source VM")
    monkeypatch.setattr(
        source_support.threading,
        "Thread",
        Mock(side_effect=RuntimeError("private error")),
    )
    job = jobs.start()
    assert jobs.get(job["job_id"])["error_code"] == "collection"
    jobs.close()
    assert jobs.start()["error_code"] == "busy"


@pytest.mark.parametrize(
    "returned",
    [
        {"status": "preparing", "job_id": "b" * 32},
        {"status": "error", "job_id": "a" * 32},
    ],
)
def test_retrieval_never_accepts_replaced_or_failed_job(monkeypatch, returned):
    client = MultiDaemonClient()
    monkeypatch.setattr(
        client,
        "_rest_request",
        Mock(side_effect=[{"status": "preparing", "job_id": "a" * 32}, returned]),
    )
    with pytest.raises(SupportCollectionError, match="Nothing was sent"):
        client.export_support(DaemonTarget("Selected VM", "ssh"))


def test_desktop_polling_deadline_is_bounded_without_sleeping_in_test(monkeypatch):
    from ai_guardian.daemon import multi_client

    clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 1, 111]), sleep=Mock())
    monkeypatch.setattr(multi_client, "time", clock)
    client = MultiDaemonClient()
    monkeypatch.setattr(
        client,
        "_rest_request",
        Mock(return_value={"status": "preparing", "job_id": "a" * 32}),
    )
    with pytest.raises(SupportCollectionError, match="timed out"):
        client.export_support(DaemonTarget("Selected VM", "ssh"))
    clock.sleep.assert_called_once_with(0.25)
