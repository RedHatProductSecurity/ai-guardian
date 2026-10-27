"""Verified daemon REST transport. Trust is explicit, never learned by discovery.

TLS verification (including an optional additional leaf pin) finishes on the
connection that carries the HTTP request, before any headers or body are sent.
Daemon requests never use environment proxies or follow redirects.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import ssl
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

logger = logging.getLogger(__name__)

TLS_CONFIG_ERROR = (
    "Daemon TLS configuration is invalid; check certificate, private key, and local file "
    "permissions. REST listener was not started."
)
TLS_VERIFY_ERROR = (
    "Daemon TLS certificate verification failed; check the trusted CA, certificate validity, "
    "and expected server identity. No daemon credentials were sent."
)
TLS_IDENTITY_ERROR = (
    "Daemon TLS server identity mismatch; check the expected server name against the certificate "
    "subject alternative names. No daemon credentials were sent."
)
TLS_EXPIRED_ERROR = (
    "Daemon TLS certificate has expired or is not yet valid; renew the certificate or check "
    "the system clock. No daemon credentials were sent."
)
TLS_PIN_ERROR = (
    "Daemon certificate pin mismatch; independently verify the renewed certificate before "
    "updating the saved SHA-256 pin. No daemon credentials were sent."
)
TLS_CLIENT_ERROR = (
    "Daemon TLS trust configuration is invalid; check the CA file, expected server name, "
    "SHA-256 pin, and local file permissions. No daemon credentials were sent."
)
REST_CONNECTION_ERROR = (
    "Daemon REST connection failed; check listener availability and transport settings."
)
REST_REDIRECT_ERROR = "Daemon REST redirects are not allowed; configure the verified daemon endpoint directly."


class DaemonConnectionError(ValueError):
    """An actionable error containing no raw URLs, credentials or crypto errors."""


class DaemonHTTPError(DaemonConnectionError):
    """A credential-free HTTP status, without the remote response body or URL."""

    def __init__(self, status: int):
        super().__init__("The daemon did not accept the request.")
        self.status = status


def _is_loopback_host(host: str) -> bool:
    """Local addresses and existing container gateway transports (compatibility)."""
    normalized = (host or "").lower().rstrip(".")
    if normalized == "openshell.localhost" or normalized.endswith(
        ".openshell.localhost"
    ):
        return True
    if normalized in {"host.docker.internal", "host.containers.internal"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return normalized in {"localhost", "localhost.localdomain"}


def _material_file(value: str, *, private: bool = False) -> Path:
    path = Path(value).expanduser()
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Not a regular file")
    if os.name != "nt":
        trusted_owners = {0, os.geteuid()}
        if (
            metadata.st_uid not in trusted_owners
            or path.lstat().st_uid not in trusted_owners
        ):
            raise ValueError("Untrusted file owner")
        if metadata.st_mode & (0o077 if private else 0o022):
            raise ValueError("Unsafe file permissions")
        # Protect the configured path as well as its resolved material. A
        # writable directory could substitute a CA/key despite safe file modes.
        for parent in set(path.absolute().parents) | set(path.resolve().parents):
            info = parent.stat()
            if (
                parent.lstat().st_uid not in trusted_owners
                or info.st_uid not in trusted_owners
                or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)
            ):
                raise ValueError("Unsafe parent directory permissions")
    return path


def _server_name(value: str) -> str:
    if not value:
        return value
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        encoded = value.encode("idna").decode("ascii")
        if len(encoded) > 253 or not all(
            re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
            for label in encoded.removesuffix(".").split(".")
        ):
            raise ValueError("Invalid server identity") from None
        return encoded


@dataclass(frozen=True)
class TLSOptions:
    """Client trust, independent of the URL's TCP address and port.

    An empty CA file uses system trust. A pin is an additional constraint, not
    an alternative to chain, validity, EKU or hostname verification.
    """

    ca_file: str = ""
    server_name: str = ""
    certificate_sha256: str = ""

    @classmethod
    def from_config(cls, config) -> "TLSOptions":
        try:
            if not isinstance(config, dict) or any(
                not isinstance(key, str)
                or (
                    key not in {"ca_file", "server_name", "certificate_sha256"}
                    and not key.startswith("_comment")
                )
                for key in config
            ):
                raise ValueError("Invalid trust fields")
            values = {key: config.get(key, "") for key in cls.__dataclass_fields__}
            if not all(isinstance(value, str) for value in values.values()):
                raise ValueError("Invalid trust types")
            values["server_name"] = _server_name(values["server_name"])
            pin = values["certificate_sha256"].replace(":", "").lower()
            if pin and not re.fullmatch(r"[0-9a-f]{64}", pin):
                raise ValueError("Invalid fingerprint")
            values["certificate_sha256"] = pin
            return cls(**values)
        except (ValueError, UnicodeError, TypeError):
            raise DaemonConnectionError(TLS_CLIENT_ERROR) from None

    def context(self) -> ssl.SSLContext:
        try:
            ca_file = str(_material_file(self.ca_file)) if self.ca_file else None
            context = ssl.create_default_context(cafile=ca_file)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.hostname_checks_common_name = False
            return context
        except (OSError, ValueError):
            raise DaemonConnectionError(TLS_CLIENT_ERROR) from None


def create_server_context(config) -> ssl.SSLContext | None:
    """Load a complete TLS identity before opening a listening socket.

    Restart is required for certificate/key or listener changes. A config
    reload never replaces a live context or creates a plaintext listener.
    """
    try:
        if not isinstance(config, dict) or any(
            not isinstance(key, str)
            or (
                key not in {"enabled", "cert_file", "key_file", "client"}
                and not key.startswith("_comment")
            )
            for key in config
        ):
            raise ValueError("Invalid TLS fields")
        enabled = config.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("Invalid enabled value")
        if not enabled:
            return None
        from cryptography import x509

        cert_file, key_file = config.get("cert_file"), config.get("key_file")
        if (
            not isinstance(cert_file, str)
            or not cert_file
            or not isinstance(key_file, str)
            or not key_file
        ):
            raise ValueError("Missing TLS identity")
        certificate_path = _material_file(cert_file)
        private_key_path = _material_file(key_file, private=True)
        certificates = x509.load_pem_x509_certificates(certificate_path.read_bytes())
        certificate = certificates[0]
        now = datetime.now(timezone.utc)
        if any(
            not item.not_valid_before_utc <= now < item.not_valid_after_utc
            for item in certificates
        ):
            raise DaemonConnectionError(
                "Daemon TLS certificate is expired or not yet valid; renew it or check the system clock. "
                "REST listener was not started."
            )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # No password callback: an encrypted unattended key fails without prompting.
        context.load_cert_chain(
            str(certificate_path), str(private_key_path), password=lambda: b""
        )
        if certificate.not_valid_after_utc - now <= timedelta(days=30):
            logger.warning(
                "Daemon TLS certificate expires within 30 days; renew it and restart the daemon"
            )
        return context
    except DaemonConnectionError:
        raise
    except (OSError, ValueError, TypeError, IndexError):
        raise DaemonConnectionError(TLS_CONFIG_ERROR) from None


class _VerifiedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, tls: TLSOptions, context: ssl.SSLContext, **kwargs):
        super().__init__(host, context=context, **kwargs)
        self._tls = tls
        self._verified_context = context

    def connect(self):
        # Connect to the URL's physical endpoint but authenticate the explicit
        # remote identity (SNI and hostname), including through a future tunnel.
        http.client.HTTPConnection.connect(self)
        try:
            self.sock = self._verified_context.wrap_socket(
                self.sock, server_hostname=self._tls.server_name or self.host
            )
            if self._tls.certificate_sha256:
                certificate = self.sock.getpeercert(binary_form=True)
                if not certificate:
                    raise DaemonConnectionError(TLS_VERIFY_ERROR)
                actual = hashlib.sha256(certificate).hexdigest()
                if not hmac.compare_digest(actual, self._tls.certificate_sha256):
                    raise DaemonConnectionError(TLS_PIN_ERROR)
        except (OSError, ValueError):
            self.close()
            raise


class _VerifiedHTTPSHandler(HTTPSHandler):
    def __init__(self, tls: TLSOptions):
        self._tls = tls
        self._verified_context = tls.context()
        super().__init__(context=self._verified_context)

    def https_open(self, req):
        def connection(host, **kwargs):
            return _VerifiedHTTPSConnection(
                host, tls=self._tls, context=self._verified_context, **kwargs
            )

        return self.do_open(connection, req)


class _NoDaemonRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise DaemonConnectionError(REST_REDIRECT_ERROR)


def open_daemon_request(
    request: Request, *, timeout=5.0, tls: TLSOptions | None = None
):
    """Open one daemon request without redirects, proxies, retries or downgrade."""
    options = TLSOptions.from_config(vars(tls)) if tls is not None else TLSOptions()
    try:
        parsed = urlsplit(request.full_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise DaemonConnectionError(
                "Invalid daemon REST URL; use an HTTP or HTTPS endpoint without embedded credentials."
            )
        if request.host != parsed.netloc or getattr(request, "_tunnel_host", None):
            raise DaemonConnectionError(
                "Daemon REST proxy connections are not allowed; configure the direct verified endpoint."
            )
        if parsed.scheme != "https" and options != TLSOptions():
            raise DaemonConnectionError(
                "Daemon TLS trust configuration requires HTTPS. No daemon credentials were sent."
            )
        if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
            raise DaemonConnectionError(
                "Refusing insecure HTTP request to a non-loopback daemon; configure HTTPS."
            )
        _ = parsed.port  # Validate the port before building a request/connection.
        handlers = [ProxyHandler({}), _NoDaemonRedirect()]
        if parsed.scheme == "https":
            handlers.append(_VerifiedHTTPSHandler(options))
        return build_opener(*handlers).open(request, timeout=timeout)
    except HTTPError:
        raise  # HTTP status is handled separately; never expose its body in diagnostics.
    except DaemonConnectionError:
        raise
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            code = exc.reason.verify_code
            message = (
                TLS_EXPIRED_ERROR
                if code in {9, 10}
                else TLS_IDENTITY_ERROR if code in {62, 64} else TLS_VERIFY_ERROR
            )
            raise DaemonConnectionError(message) from None
        raise DaemonConnectionError(REST_CONNECTION_ERROR) from None
    except (OSError, http.client.HTTPException):
        raise DaemonConnectionError(REST_CONNECTION_ERROR) from None
    except (ValueError, TypeError):
        raise DaemonConnectionError(
            "Invalid daemon REST URL or request; check the configured endpoint."
        ) from None


def local_daemon_request(path, *, data=None, timeout=5.0, pid_info=None):
    """Use the running local daemon's transport and explicitly configured trust.

    Only the scheme/port come from the PID file, never a discovered certificate
    or pin. Missing scheme means HTTP for compatibility with older daemons.
    """
    from ai_guardian.config.loaders import _load_config_file
    from ai_guardian.daemon import get_auth_token_path, get_pid_path

    if pid_info is None:
        pid_info = json.loads(get_pid_path().read_text(encoding="utf-8"))
    scheme = pid_info.get("rest_scheme", "http")
    if scheme not in {"http", "https"}:
        raise DaemonConnectionError(REST_CONNECTION_ERROR)
    options = TLSOptions()
    config, error = _load_config_file()
    daemon_config = (config or {}).get("daemon", {})
    if not isinstance(daemon_config, dict):
        raise DaemonConnectionError(TLS_CLIENT_ERROR)
    if scheme == "https":
        if error:
            raise DaemonConnectionError(TLS_CLIENT_ERROR)
        listener_config = daemon_config.get("rest_tls", {})
        if not isinstance(listener_config, dict):
            raise DaemonConnectionError(TLS_CLIENT_ERROR)
        options = TLSOptions.from_config(listener_config.get("client", {}))
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(
        f"{scheme}://127.0.0.1:{int(pid_info['rest_port'])}{path}", data=payload
    )
    request.add_header("Content-Type", "application/json")
    token_path = get_auth_token_path()
    token = daemon_config.get("auth_token")
    try:
        token = token or (
            _material_file(str(token_path), private=True)
            .read_text(encoding="utf-8")
            .strip()
            if token_path.exists()
            else pid_info.get("auth_token")
        )
    except (OSError, ValueError):
        raise DaemonConnectionError(
            "Local daemon authentication material is unavailable or has unsafe permissions."
        ) from None
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    return open_daemon_request(request, timeout=timeout, tls=options)
