"""Deterministic, unissued credentials for pattern tests (#2558).

NuGet layout: Apache-2.0 NuGetGallery ApiKeyV4.cs (revision
63b66c98287c61c7e00fe6aefaff86c0d73ba157). Encode the identifier and
GUID password separately, as the vendor generator does. These helpers
do not create accounts, issue credentials, or make verification requests.
"""

from base64 import b32encode
from hashlib import sha256
from uuid import UUID


def make_nuget_v4(seed=0):
    """Encode a synthetic v4 identifier and a deterministic version-4 GUID."""
    identifier = sha256(f"synthetic-nuget-id:{seed}".encode()).digest()[:10]
    identifier = bytes(value or 1 for value in identifier)
    password = UUID(
        bytes=sha256(f"synthetic-nuget-password:{seed}".encode()).digest()[:16],
        version=4,
    )
    return (
        b32encode(b"v4" + identifier).decode().rstrip("=")
        + b32encode(password.bytes_le).decode().rstrip("=")
    ).lower()


SONAR_TOKEN_TYPES = (
    ("sonar-user-token", "squ_", "Sonar User Token"),
    ("sonar-project-analysis-token", "sqp_", "Sonar Project Analysis Token"),
    ("sonar-global-analysis-token", "sqa_", "Sonar Global Analysis Token"),
)

CREDENTIAL_CASES = (
    ("nuget-api-key", "NuGet V4 API Key", make_nuget_v4()),
    *(
        (
            rule_id,
            description,
            prefix + sha256(f"synthetic-sonar:{prefix}".encode()).hexdigest()[:40],
        )
        for rule_id, prefix, description in SONAR_TOKEN_TYPES
    ),
)

CREDENTIAL_RULE_IDS = {rule_id for rule_id, _, _ in CREDENTIAL_CASES}
