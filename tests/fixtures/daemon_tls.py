"""Ephemeral, independently generated TLS identities; never use real credentials."""

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import threading
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def make_identity(
    directory: Path, *, name="daemon.test", days=30, issuer=None, starts=-2, san=True
):
    directory.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer[0].subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + timedelta(days=starts))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.BasicConstraints(ca=issuer is None, path_length=None), critical=True
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                (issuer[1] if issuer else key).public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=issuer is None,
                crl_sign=issuer is None,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    )
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False
        )
    cert = builder.sign(issuer[1] if issuer else key, hashes.SHA256())
    cert_path, key_path = directory / "certificate.pem", directory / "private.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.chmod(0o600)
    key_path.chmod(0o600)
    return {
        "cert_file": str(cert_path),
        "key_file": str(key_path),
        "ca_file": str(cert_path),
        "server_name": name,
        "certificate_sha256": cert.fingerprint(hashes.SHA256()).hex(),
        "issuer": (cert, key),
    }


def listener_config(identity):
    return {"enabled": True, **{k: identity[k] for k in ("cert_file", "key_file")}}


def client_config(identity):
    return {k: identity[k] for k in ("ca_file", "server_name", "certificate_sha256")}


@contextmanager
def serve_endpoint(identity=None, *, redirect=None):
    """Observe actual HTTP delivery, including deliberately invalid external certs."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            requests.append(dict(self.headers))
            self.send_response(302 if redirect else 200)
            if redirect:
                self.send_header("Location", redirect)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = do_GET

    class Server(ThreadingHTTPServer):
        def handle_error(self, *_args):
            return  # Expected handshake/early-close errors from adversarial peers.

    server = Server(("127.0.0.1", 0), Handler)
    if identity:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(identity["cert_file"], identity["key_file"])
        server.socket = context.wrap_socket(
            server.socket, server_side=True, do_handshake_on_connect=False
        )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(port=server.server_port, requests=requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
