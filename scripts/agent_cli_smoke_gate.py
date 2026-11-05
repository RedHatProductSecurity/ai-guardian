#!/usr/bin/env python3
"""Do not start smoke setup, daemon or agents until trusted firewall setup succeeds."""

import os
import stat
import sys
import time
from pathlib import Path

READY_FILE = Path("/tmp/ai-guardian-smoke-firewall-ready")


def agent_privileges_are_restricted(status: str) -> bool:
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if fields.get("NoNewPrivs", "").strip() != "1":
        return False
    try:
        return all(
            int(fields[key].strip(), 16) == 0
            for key in ("CapEff", "CapPrm", "CapBnd", "CapAmb")
        )
    except (KeyError, ValueError):
        return False


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
        restricted = agent_privileges_are_restricted(
            Path("/proc/self/status").read_text(encoding="ascii")
        )
    except OSError:
        restricted = False
    if os.geteuid() == 0 or not restricted:
        print("ERROR: smoke sandbox must be unprivileged with no-new-privileges.")
        return 1
    if not wait_for_firewall():
        print(
            "ERROR: smoke firewall readiness was not established; setup was not started."
        )
        return 1
    os.execv("/usr/local/bin/entrypoint.sh", ["entrypoint.sh", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
