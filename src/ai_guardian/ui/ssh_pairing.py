"""Display-only SSH identity text shared by desktop forms and the Web Console."""

PAIRING_MESSAGE = "Only pair a host you are authorized to manage. OpenSSH uses your existing configuration and agent. Unknown or changed host keys are not accepted automatically."
TRUST_LABEL = "I confirm this SSH destination and daemon certificate identity"
PAIRED_MESSAGE = (
    "SSH daemon paired. The connection is saved and reconnects automatically."
)


def pairing_summary(pairing):
    profile = pairing.profile
    return (
        f"SSH destination: {profile.destination}\nDaemon: {pairing.daemon_name}\n"
        f"Remote loopback port: {pairing.port}\nTLS server identity: {profile.server_name}\n"
        f"Certificate SHA-256: {profile.certificate_sha256}\n\n"
        "Certificate trust and the authorized daemon credential came through host-key-verified SSH. "
        "Only the daemon credential and certificate trust are saved; no SSH private key or password is stored. "
        "Changed identities require a new, explicit pairing."
    )
