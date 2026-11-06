#!/usr/bin/env python3
"""Do not start smoke setup, daemon or agents until trusted firewall setup succeeds."""

import os
import stat
import sys
import time
from pathlib import Path

READY_FILE = Path("/tmp/ai-guardian-smoke-firewall-ready")
CAPABILITY_FIELDS = ("CapEff", "CapPrm", "CapBnd", "CapAmb")
ADMIN_CAPABILITIES = (1 << 12) | (1 << 21)  # CAP_NET_ADMIN | CAP_SYS_ADMIN


def agent_has_no_container_admin_capabilities(status: str) -> bool:
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    try:
        capability_sets = [int(fields[key].strip(), 16) for key in CAPABILITY_FIELDS]
    except (KeyError, ValueError):
        return False
    return all(
        not capability_set & ADMIN_CAPABILITIES for capability_set in capability_sets
    )


def wait_for_firewall(path: Path = READY_FILE, timeout: float = 90) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            info = path.lstat()
            return (
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.geteuid()
                and info.st_nlink == 1
                and not info.st_mode & 0o022
                and path.read_text(encoding="ascii") == "installed\n"
            )
        except FileNotFoundError:
            time.sleep(0.1)
        except (OSError, UnicodeError):
            return False
    return False


def main() -> int:
    try:
        has_no_admin_capabilities = agent_has_no_container_admin_capabilities(
            Path("/proc/self/status").read_text(encoding="ascii")
        )
    except OSError:
        has_no_admin_capabilities = False
    if os.geteuid() == 0 or not has_no_admin_capabilities:
        print(
            "ERROR: smoke sandbox requires a non-root user without SYS_ADMIN or NET_ADMIN."
        )
        return 1
    if not wait_for_firewall():
        print(
            "ERROR: smoke firewall readiness was not established; setup was not started."
        )
        return 1
    os.execv("/usr/local/bin/entrypoint.sh", ["entrypoint.sh", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
