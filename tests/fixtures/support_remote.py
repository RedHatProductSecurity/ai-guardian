"""Synthetic source diagnostics; never prepare or read personal support data."""

import base64
import hashlib
import json


def diagnostic(name, value, **metadata):
    raw = (value if isinstance(value, str) else json.dumps(value)).encode("utf-8")
    return {
        "name": name,
        "data": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "redactions": 0,
        "truncated": False,
        "note": "Synthetic source diagnostic",
        **metadata,
    }


def diagnostics(marker="remote-only"):
    return {
        "schema": 1,
        "files": [
            diagnostic("ai-guardian.json", {"diagnostic_marker": marker}),
            diagnostic("doctor.json", {"checks": [], "marker": marker}),
            diagnostic(
                "daemon-source.json",
                {
                    "daemon_name": marker,
                    "version": "1.21.0",
                    "omissions": [],
                },
            ),
        ],
    }
