"""Fresh-environment package and daemon REST smoke tests used by CI."""

import importlib.metadata
import importlib.util
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

INSTALL_KIND = os.environ.get("AI_GUARDIAN_INSTALL_SMOKE")
pytestmark = pytest.mark.skipif(
    INSTALL_KIND not in {"full", "daemon"},
    reason="runs only against freshly installed distribution artifacts",
)


def _requirement_names(distribution_name):
    return {
        match.group(1).lower().replace("_", "-").replace(".", "-")
        for requirement in importlib.metadata.requires(distribution_name) or []
        if (match := re.match(r"\s*([A-Za-z0-9_.-]+)", requirement))
    }


def _free_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _run(command, env):
    return subprocess.run(
        command,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write_test_identity(home):
    """Create a disposable localhost TLS identity for REST readiness checks."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = Path(home) / "server-cert.pem"
    key_path = Path(home) / "server-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return cert_path, key_path


def test_installed_distribution_starts_headless_daemon_and_rest_api():
    if INSTALL_KIND == "full":
        distribution_name = "ai-guardian"
        executable = Path(sys.executable).parent / "ai-guardian"
        expected_requirements = {
            "nicegui",
            "rapidocr",
            "onnxruntime",
            "pystray",
            "pillow",
            "docker",
            "boto3",
            "bandit",
            "tree-sitter",
        }
        assert expected_requirements <= _requirement_names(distribution_name)
        commands = {
            "version": ["--version"],
            "init": ["setup", "--create-config"],
            "start": ["daemon", "start", "-b"],
            "restart": ["daemon", "restart"],
            "status": ["daemon", "status"],
            "stop": ["daemon", "stop"],
        }
    else:
        distribution_name = "ai-guardian-daemon"
        executable = Path(sys.executable).parent / "ai-guardian-daemon"
        assert _requirement_names(distribution_name) == {"cryptography"}
        omitted_modules = (
            "nicegui",
            "rapidocr",
            "onnxruntime",
            "pystray",
            "PIL",
            "docker",
            "boto3",
            "bandit",
            "tree_sitter",
            "mcp",
            "grpc",
        )
        assert all(
            importlib.util.find_spec(module) is None for module in omitted_modules
        )
        commands = {
            "version": ["--version"],
            "init": ["init-config"],
            "start": ["start", "-b"],
            "restart": ["restart"],
            "status": ["status"],
            "stop": ["stop"],
        }

    assert executable.is_file(), f"{distribution_name} console script was not installed"
    if INSTALL_KIND == "daemon":
        assert not executable.with_name("ai-guardian").exists()

    with tempfile.TemporaryDirectory(prefix="ai-guardian-install-smoke-") as home:
        env = os.environ.copy()
        env.update(
            {
                "HOME": home,
                "XDG_CONFIG_HOME": str(Path(home) / "config"),
                "XDG_STATE_HOME": str(Path(home) / "state"),
                "XDG_DATA_HOME": str(Path(home) / "data"),
                "AI_GUARDIAN_REST_HOST": "127.0.0.1",
                "AI_GUARDIAN_REST_PORT": str(_free_loopback_port()),
            }
        )
        _run([executable, *commands["version"]], env)
        _run([executable, *commands["init"]], env)

        started = False
        try:
            # A failed parent-side readiness check may still leave a child alive.
            started = True
            _run([executable, *commands["start"]], env)
            port = env["AI_GUARDIAN_REST_PORT"]
            url = f"http://127.0.0.1:{port}/api/health"
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        health = json.loads(response.read().decode("utf-8"))
                    break
                except (OSError, urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)

            assert health["status"] == "ok"
            status = _run([executable, *commands["status"]], env)
            assert "REST API: available" in status.stdout

            cert_path, key_path = _write_test_identity(home)
            config_path = (
                Path(env["XDG_CONFIG_HOME"]) / "ai-guardian" / "ai-guardian.json"
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config.setdefault("daemon", {})["rest_tls"] = {
                "enabled": True,
                "cert_file": str(cert_path),
                "key_file": str(key_path),
            }
            config_path.write_text(
                json.dumps(config, indent=2) + "\n", encoding="utf-8"
            )
            _run([executable, *commands["restart"]], env)

            tls_context = ssl.create_default_context(cafile=str(cert_path))
            tls_url = f"https://127.0.0.1:{port}/api/health"
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urllib.request.urlopen(
                        tls_url, timeout=1, context=tls_context
                    ) as response:
                        tls_health = json.loads(response.read().decode("utf-8"))
                    break
                except (OSError, urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)

            assert tls_health["status"] == "ok"
            tls_status = _run([executable, *commands["status"]], env)
            assert "REST API: available (HTTPS," in tls_status.stdout
        finally:
            if started:
                _run([executable, *commands["stop"]], env)
