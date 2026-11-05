#!/usr/bin/env python3
"""Trusted one-shot nftables setup, only in a smoke sandbox's network namespace."""

import subprocess

# An inet table covers IPv4 and IPv6. Only loopback and replies to connections
# initiated from outside the namespace may leave it; new outbound flows cannot.
# The transaction never flushes any existing rules or touches another namespace.
RULESET = """\
create table inet ai_guardian_smoke
add chain inet ai_guardian_smoke output { type filter hook output priority 0; policy drop; }
add rule inet ai_guardian_smoke output oifname "lo" accept
add rule inet ai_guardian_smoke output ct state established,related ct direction reply accept
"""


def main() -> int:
    try:
        result = subprocess.run(
            ["nft", "--file", "-"],
            input=RULESET,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("ERROR: smoke firewall tool is unavailable or timed out.")
        return 1
    if result.returncode:
        print(
            f"ERROR: smoke firewall installation failed (exit code {result.returncode})."
        )
        return 1
    print("Smoke firewall installed: new non-loopback IPv4/IPv6 egress is blocked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
