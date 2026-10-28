"""Authored synthetic qualification data; no real passwords, files or accounts.

The qualification seed is separate from the focused unit examples. This is not
a linguistic model/dictionary and is never included in runtime candidate scoring.
Do not tune thresholds against the held-out seed after reporting its results.
"""

import random
import string

HELD_OUT_SEED = 26122026
VALUE = "m7Q!t2R#v9L$x5N@"
TEXT = f'My password is "{VALUE}"'


def isolated_policy(action="warn", enabled=True):
    """Explicit test policy; never consult workstation settings or services."""
    return {
        **{
            key: {"enabled": False}
            for key in (
                "secret_scanning",
                "scan_pii",
                "prompt_injection",
                "context_poisoning",
                "supply_chain",
                "scan_offensive",
                "canary_detection",
                "config_file_scanning",
                "exfil_detection",
                "ssrf_protection",
                "image_scanning",
                "code_scanning",
                "transcript_scanning",
                "permissions",
                "annotations",
            )
        },
        "password_likelihood": {"enabled": enabled, "action": action},
        "violation_logging": {"enabled": False},
    }


WORDS = (
    "amber",
    "birch",
    "cedar",
    "delta",
    "ember",
    "fjord",
    "glade",
    "hazel",
    "ivory",
    "juniper",
    "kelp",
    "lilac",
    "marble",
    "nectar",
    "olive",
    "pebble",
)


def cases(samples=1000, seed=HELD_OUT_SEED):
    rng = random.Random(seed)
    for _ in range(samples):
        alnum = "".join(rng.choices(string.ascii_letters + string.digits, k=24))
        mixed = "".join(
            rng.choices(string.ascii_letters + string.digits + "!#$%&*+?-", k=24)
        )
        words = rng.sample(WORDS, 4)
        for label, value in (("alphanumeric", alnum), ("mixed_symbol", mixed)):
            yield "standalone_" + label, value, True, False
            yield "contextual_" + label, f'my password is "{value}"', True, True
        for label, value in (
            ("joined", "".join(words)),
            ("camelcase", "".join(w.title() for w in words)),
            ("separated", "-".join(words)),
            ("spaced", " ".join(words)),
        ):
            yield "contextual_" + label, f'my passphrase is "{value}"', True, True
        number = rng.randrange(100000)
        digest = "".join(rng.choices("0123456789abcdef", k=64))
        for label, text in (
            (
                "code",
                f"def process_chunk_{number}(record):\n    return record.get('status', False)\n",
            ),
            (
                "prose",
                "The worker stores the current result and then processes another message.",
            ),
            (
                "logs",
                f"2026-10-28 INFO worker={number} request_completed elapsed_ms=42",
            ),
            (
                "configuration",
                f'{{"package_version": "1.21.0-dev", "worker_count": {number}}}',
            ),
            ("digest", f"sha256={digest}"),
            ("url_encoded_ids", f"https://example.org/build/{alnum}?digest={digest}"),
        ):
            yield label, text, False, False
