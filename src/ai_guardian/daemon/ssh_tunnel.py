"""Bounded system-OpenSSH probing and owned loopback HTTPS tunnels."""

from dataclasses import dataclass, field
import http.client
import ipaddress
import json
import logging
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

from ai_guardian.daemon.rest_transport import (
    DaemonConnectionError,
    REST_CONNECTION_ERROR,
    TLSOptions,
    open_daemon_request,
)
from ai_guardian.daemon.ssh_probe import PROBE_SCRIPT
from ai_guardian.daemon.ssh_storage import (
    SSHConnectionError,
    SSHProfile,
    destination,
)

SSH_ERROR = "SSH connection failed. Check the host alias, agent authentication, and known host key using your SSH client. No identities were accepted automatically."
SSH_MISSING = (
    "System OpenSSH is unavailable; install an SSH client before adding this daemon."
)
METADATA_ERROR = "Remote daemon metadata is unavailable or invalid; check the installation and the SSH user's configuration and state directories."
MISSING_CONFIG_ERROR = "Remote AI Guardian configuration is missing. Complete setup as the SSH user before pairing."
UNSAFE_METADATA_ERROR = "Remote daemon storage has unsafe ownership, permissions, or symbolic links. Check the SSH user's configuration/state files and their ancestor directories; no credentials were returned."
REST_UNAVAILABLE_ERROR = "The remote daemon process is running, but its REST listener is unavailable. Run daemon status as the SSH user to see the startup precondition."
STOPPED_ERROR = (
    "The remote daemon is stopped. Start it as the SSH user, then reconnect."
)
HTTPS_REQUIRED = "SSH-managed connections require a running HTTPS daemon with certificate metadata. Upgrade or configure the remote daemon before pairing; HTTP was not selected."
OFFLINE_ERROR = "SSH daemon offline; reconnecting with backoff. No daemon credentials are sent without an active, verified tunnel."
IDENTITY_CHANGED = "The saved daemon identity or credential has changed. Independently verify the remote daemon, then remove and pair the connection again. Saved trust was not replaced."
POLLING_ERROR = "Remote daemon does not support polling-only tray registration; upgrade the daemon to use SSH permission prompts."
DAEMON_AUTH_ERROR = "Remote daemon authentication failed; verify the authorized daemon account before pairing again."
REQUEST_ERROR = (
    "Remote daemon request failed; check daemon availability and compatibility."
)
logger = logging.getLogger(__name__)


def stop_owned_process(process):
    """Stop/reap one Popen handle only; tolerate its concurrent natural exit."""
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
    except ProcessLookupError:
        pass  # intentionally silent — owned child already exited during cleanup
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("Owned SSH process cleanup did not complete within its deadline")


def ssh_command(host):
    executable = shutil.which("ssh")
    if not executable:
        raise SSHConnectionError(SSH_MISSING)
    return [
        executable,
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UpdateHostKeys=no",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ForkAfterAuthentication=no",
        "-o",
        "StdinNull=no",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ForwardX11=no",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "RemoteCommand=none",
        "-o",
        "GatewayPorts=no",
    ], destination(host)


@dataclass(frozen=True)
class SSHPairing:
    profile: SSHProfile = field(repr=False)
    host: str
    port: int
    daemon_name: str
    cli: dict | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_metadata(cls, host, value):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization

        try:
            if not isinstance(value, dict):
                raise ValueError()
            status = value.get("status")
            if status == "stopped":
                raise SSHConnectionError(STOPPED_ERROR)
            if status == "https_required":
                raise SSHConnectionError(HTTPS_REQUIRED)
            if status in {"missing_config", "unsafe_metadata", "rest_unavailable"}:
                raise SSHConnectionError(
                    {
                        "missing_config": MISSING_CONFIG_ERROR,
                        "unsafe_metadata": UNSAFE_METADATA_ERROR,
                        "rest_unavailable": REST_UNAVAILABLE_ERROR,
                    }[status]
                )
            if (
                status != "ok"
                or type(value.get("version")) is not int
                or value["version"] != 1
            ):
                raise ValueError()
            if value.get("host") not in {"127.0.0.1", "::1", "localhost"}:
                raise ValueError()
            port = value.get("port")
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError()
            name = value.get("name")
            if (
                not isinstance(name, str)
                or not 1 <= len(name) <= 120
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
            ):
                raise ValueError()
            for key in ("certificate", "ca_pem"):
                pem = value[key]
                if (
                    not isinstance(pem, str)
                    or not 1 <= len(pem) <= 131072
                    or "PRIVATE KEY" in pem
                ):
                    raise ValueError()
                x509.load_pem_x509_certificates(pem.encode())
            certificate = x509.load_pem_x509_certificates(
                value["certificate"].encode()
            )[0]
            server_name = value.get("server_name")
            if not server_name:
                san = certificate.extensions.get_extension_for_class(
                    x509.SubjectAlternativeName
                ).value
                identities = san.get_values_for_type(x509.DNSName) + [
                    str(ip) for ip in san.get_values_for_type(x509.IPAddress)
                ]
                server_name = next(name for name in identities if "*" not in name)
            options = TLSOptions.from_config({"server_name": server_name})
            profile = SSHProfile.from_dict(
                {
                    "destination": destination(host),
                    "server_name": options.server_name,
                    "certificate_sha256": certificate.fingerprint(
                        hashes.SHA256()
                    ).hex(),
                    "ca_pem": "".join(
                        item.public_bytes(serialization.Encoding.PEM).decode("ascii")
                        for item in x509.load_pem_x509_certificates(
                            value["ca_pem"].encode()
                        )
                    ),
                    "token": value["token"],
                }
            )
            remote_host = "127.0.0.1" if value["host"] == "localhost" else value["host"]
            from ai_guardian.daemon.ssh_commands import validate_cli_context

            return cls(
                profile, remote_host, port, name, validate_cli_context(value.get("cli"))
            )
        except SSHConnectionError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            StopIteration,
            x509.ExtensionNotFound,
        ):
            raise SSHConnectionError(METADATA_ERROR) from None


def probe_destination(host, *, on_process=None) -> SSHPairing:
    command, host = ssh_command(host)
    # Private temporary streams bound memory usage and avoid pipe hangs from
    # ProxyCommand descendants. Never include stdout/stderr in any diagnostic.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = None
        try:
            process = subprocess.Popen(
                command + ["-o", "ClearAllForwardings=yes", "--", host, "python3 -"],
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=errors,
            )
            if on_process is not None:
                on_process(process, True)
            process.communicate(PROBE_SCRIPT.encode(), timeout=10)
            if process.returncode == 127:
                raise SSHConnectionError(METADATA_ERROR)
            if process.returncode:
                raise SSHConnectionError(SSH_ERROR)
            output.seek(0)
            data = output.read(524289)
            if len(data) > 524288:
                raise SSHConnectionError(METADATA_ERROR)
            return SSHPairing.from_metadata(host, json.loads(data))
        except (subprocess.TimeoutExpired, OSError):
            raise SSHConnectionError(SSH_ERROR) from None
        except (ValueError, UnicodeError, RecursionError) as exc:
            if isinstance(exc, SSHConnectionError):
                raise
            raise SSHConnectionError(METADATA_ERROR) from None
        finally:
            if process is not None:
                stop_owned_process(process)
                if on_process is not None:
                    on_process(process, False)


class SSHTunnel:
    """A single generation. Closing it permanently invalidates stale targets.

    Process checks gate requests; TLS on the actual request socket is the
    decisive protection against local port reuse, including a death/check race.
    No token is sent by the readiness request.
    """

    def __init__(self, pairing, store, *, saved=False):
        self.profile = pairing.profile
        self.pairing = pairing
        self.store = store
        self.saved = saved
        self.process = None
        self.port = 0
        self._lock = threading.RLock()
        self._closed = False
        self._temporary = None
        self.tls = None

    @property
    def active(self):
        return (
            not self._closed
            and self.process is not None
            and self.process.poll() is None
        )

    def start(self):
        with self._lock:
            if self._closed:
                raise SSHConnectionError(OFFLINE_ERROR)
            self._start()

    def _start(self):
        command, host = ssh_command(self.profile.destination)
        try:
            self.store._directory(create=True)
            self._temporary = tempfile.TemporaryDirectory(
                prefix=".tunnel-", dir=self.store.path
            )
            ca = Path(self._temporary.name) / "ca.pem"
            with ca.open("x", encoding="utf-8") as stream:
                stream.write(self.profile.ca_pem)
            ca.chmod(0o600)
            self.tls = TLSOptions(
                str(ca), self.profile.server_name, self.profile.certificate_sha256
            )
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                self.port = reservation.getsockname()[1]
            remote = self.pairing.host
            if (
                ipaddress.ip_address(
                    remote if remote != "localhost" else "127.0.0.1"
                ).version
                == 6
            ):
                remote = f"[{remote}]"
            self.process = subprocess.Popen(
                command
                + [
                    "-N",
                    "-o",
                    "ExitOnForwardFailure=yes",
                    "-L",
                    f"127.0.0.1:{self.port}:{remote}:{self.pairing.port}",
                    "--",
                    host,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not self.active:
                    raise SSHConnectionError(SSH_ERROR)
                try:
                    if (
                        self.request(
                            "GET", "/api/health", authenticated=False, timeout=0.5
                        ).get("status")
                        == "ok"
                    ):
                        if not self.active:
                            raise SSHConnectionError(SSH_ERROR)
                        return
                    raise SSHConnectionError(REQUEST_ERROR)
                except DaemonConnectionError as exc:
                    if str(exc) != REST_CONNECTION_ERROR:
                        raise
                time.sleep(0.1)
            raise SSHConnectionError(OFFLINE_ERROR)
        except (SSHConnectionError, DaemonConnectionError):
            self.close()
            raise
        except (OSError, ValueError):
            self.close()
            raise SSHConnectionError(SSH_ERROR) from None

    def request(self, method, path, body=None, *, timeout=5.0, authenticated=True):
        with self._lock:
            if not self.active or (
                self.saved and not self.store.contains(self.profile)
            ):
                self.close()
                raise SSHConnectionError(OFFLINE_ERROR)
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or any(ord(c) < 32 for c in path)
            ):
                raise SSHConnectionError(REQUEST_ERROR)
            request = Request(
                f"https://127.0.0.1:{self.port}{path}",
                method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type": "application/json"},
            )
            if authenticated:
                request.add_header("Authorization", f"Bearer {self.profile.token}")
            try:
                deadline = time.monotonic() + min(timeout, 5.0)
                with open_daemon_request(
                    request, timeout=min(timeout, 5.0), tls=self.tls
                ) as response:
                    raw = bytearray()
                    while True:
                        if time.monotonic() >= deadline:
                            raise SSHConnectionError(REQUEST_ERROR)
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise SSHConnectionError(REQUEST_ERROR)
                    result = json.loads(raw)
                    if not isinstance(result, dict):
                        raise SSHConnectionError(REQUEST_ERROR)
                    return result
            except HTTPError as exc:
                exc.close()
                raise SSHConnectionError(
                    DAEMON_AUTH_ERROR if exc.code in {401, 403} else REQUEST_ERROR
                ) from None
            except DaemonConnectionError:
                raise
            except (OSError, ValueError, RecursionError, http.client.HTTPException):
                raise SSHConnectionError(REQUEST_ERROR) from None

    def close(self):
        # Invalidate first: an in-progress readiness/request owns this lock but
        # must not let shutdown race into another authenticated request.
        self._closed = True
        process = self.process
        if process is not None:
            # Closing the actual SSH transport also interrupts a stalled REST
            # read; never wait on the request lock before terminating it.
            stop_owned_process(process)
        with self._lock:
            if self.process is not None:
                if self.process is not process:
                    stop_owned_process(self.process)
                self.process = None
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
