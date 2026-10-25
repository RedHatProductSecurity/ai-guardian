"""Synthetic SSH protocol fixtures; no live host or user credential access."""

from pathlib import Path

from ai_guardian.daemon.ssh_tunnel import SSHPairing
from tests.fixtures.daemon_tls import make_identity


def make_pairing(path):
    identity = make_identity(path / "identity")
    certificate = Path(identity["cert_file"]).read_text()
    metadata = {
        "status": "ok",
        "version": 1,
        "host": "127.0.0.1",
        "port": 45231,
        "name": "test-vm",
        "server_name": "daemon.test",
        "certificate": certificate,
        "ca_pem": certificate,
        "token": "synthetic-daemon-credential",
    }
    return SSHPairing.from_metadata("tester@vm-alias", metadata), metadata, identity
