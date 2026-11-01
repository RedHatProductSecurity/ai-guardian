"""Synthetic, unissued credential-shaped values for issue #2632 coverage."""

import base64
from hashlib import sha256, sha512
from string import ascii_letters, digits

_ALPHANUMERIC = ascii_letters + digits


def _alphanumeric(seed, length):
    """Build deterministic high-entropy-looking test text, never an issued key."""
    stream = sha512(seed.encode("ascii")).digest()
    return "".join(
        _ALPHANUMERIC[value % len(_ALPHANUMERIC)] for value in stream[:length]
    )


def _tailscale_token(kind):
    key_id = _alphanumeric(f"synthetic-tailscale-id:{kind}", 12)
    secret = _alphanumeric(f"synthetic-tailscale-secret:{kind}", 32)
    return f"tskey-{kind}-k{key_id}CNTRL-{secret}"


_labelbox_body = base64.urlsafe_b64encode(sha256(b"synthetic-labelbox-key").digest())
_recursion_body = base64.urlsafe_b64encode(sha256(b"synthetic-recursion-key").digest())

CREDENTIAL_CASES = (
    (
        "baseten-api-key",
        "Baseten API Key",
        f"b10_{_alphanumeric('synthetic-baseten-id', 8)}."
        f"{_alphanumeric('synthetic-baseten-secret', 32)}",
    ),
    (
        "labelbox-api-key",
        "Labelbox API Key",
        "lbx_" + _labelbox_body.decode("ascii").rstrip("="),
    ),
    (
        "recursion-api-key",
        "Recursion API Key",
        "rma_" + _recursion_body.decode("ascii").rstrip("="),
    ),
    (
        "supabase-project-api-key",
        "Supabase Project API Key",
        "sb_secret_" + _alphanumeric("synthetic-supabase-secret", 31),
    ),
    ("tailscale-api-key", "Tailscale API Key", _tailscale_token("api")),
    ("tailscale-auth-key", "Tailscale Auth Key", _tailscale_token("auth")),
    (
        "tailscale-oauth-client-secret",
        "Tailscale OAuth Client Secret",
        _tailscale_token("client"),
    ),
    (
        "tailscale-webhook-secret",
        "Tailscale Webhook Secret",
        _tailscale_token("webhook"),
    ),
)

LOW_ENTROPY_CASES = (
    ("baseten-api-key", "b10_" + "A" * 8 + "." + "A" * 32),
    ("labelbox-api-key", "lbx_" + "A" * 43),
    ("recursion-api-key", "rma_" + "A" * 43),
    ("supabase-project-api-key", "sb_secret_" + "A" * 31),
    ("tailscale-api-key", "tskey-api-k" + "A" * 12 + "CNTRL-" + "A" * 32),
    ("tailscale-auth-key", "tskey-auth-k" + "A" * 12 + "CNTRL-" + "A" * 32),
    (
        "tailscale-oauth-client-secret",
        "tskey-client-k" + "A" * 12 + "CNTRL-" + "A" * 32,
    ),
    (
        "tailscale-webhook-secret",
        "tskey-webhook-k" + "A" * 12 + "CNTRL-" + "A" * 32,
    ),
)
