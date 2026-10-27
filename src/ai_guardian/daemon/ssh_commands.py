"""Explicit user actions over the saved, host-key-verified SSH destination.

REST still uses the independently verified managed HTTPS tunnel. CLI context is
learned only from a successfully authenticated pairing and is kept in memory,
including while that daemon is stopped. It never contains daemon credentials.
"""

import logging
import posixpath
import shlex
import subprocess

from ai_guardian.daemon.ssh_storage import SSHConnectionError
from ai_guardian.daemon.ssh_tunnel import OFFLINE_ERROR, ssh_command

logger = logging.getLogger(__name__)
CLI_UNAVAILABLE = (
    "Remote installation context is unavailable. Start the daemon as the SSH "
    "user, then reconnect. If its interpreter cannot be identified, manage the "
    "installation through Terminal. "
    "No workstation command was run."
)


def validate_cli_context(value):
    """Accept only the small, credential-free POSIX context from daemon metadata."""
    if not isinstance(value, dict):
        return None
    result = {}
    for key in ("python", "config_dir", "state_dir"):
        path = value.get(key)
        if (
            not isinstance(path, str)
            or not posixpath.isabs(path)
            or len(path) > 4096
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
        ):
            return None
        result[key] = path
    if isinstance(value.get("system"), str) and value["system"] in {"linux", "darwin"}:
        result["system"] = value["system"]
    return result


class SSHCommands:
    """Bound to one saved connection, not a discovery slot or a local process."""

    def __init__(self, profile, store, cancelled, cli=None):
        self.profile = profile
        self.store = store
        self.cancelled = cancelled
        self.cli = validate_cli_context(cli)

    def command(self, argv=None, *, interactive=False, cwd=None, python=False):
        if self.cancelled.is_set() or not self.store.contains(self.profile):
            raise SSHConnectionError(OFFLINE_ERROR)
        command, host = ssh_command(self.profile.destination)
        if interactive:
            command[command.index("-T")] = "-tt"
        environment = []
        if self.cli:
            environment = [
                "env",
                "AI_GUARDIAN_CONFIG_DIR=" + self.cli["config_dir"],
                "AI_GUARDIAN_STATE_DIR=" + self.cli["state_dir"],
            ]
        if argv is None:
            remote = shlex.join(environment) + (
                " sh -c 'exec \"${SHELL:-/bin/sh}\" -l'"
            )
        else:
            argv = list(argv)
            if python or (argv and argv[0] == "ai-guardian"):
                if not self.cli:
                    raise SSHConnectionError(CLI_UNAVAILABLE)
                argv = (
                    [self.cli["python"]] + argv
                    if python
                    else [self.cli["python"], "-m", "ai_guardian"] + argv[1:]
                )
            remote = shlex.join(environment + argv)
        if self.cli:
            remote = (
                "PATH="
                + shlex.quote(posixpath.dirname(self.cli["python"]))
                + ':"$PATH" '
                + remote
            )
        if cwd:
            if (
                not isinstance(cwd, str)
                or not posixpath.isabs(cwd)
                or any(ord(c) < 32 or ord(c) == 127 for c in cwd)
            ):
                raise SSHConnectionError("Choose an absolute directory on the VM.")
            remote = "cd " + shlex.quote(cwd) + " && " + remote
        return command + ["-o", "ClearAllForwardings=yes", "--", host, remote.strip()]

    def run(self, argv, *, timeout=60, python=False, cwd=None):
        command = self.command(argv, python=python, cwd=cwd)
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (result.stdout + result.stderr).strip()
            return result.returncode == 0, output[-1048576:]
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("SSH command did not complete; no local fallback was used")
            return (
                False,
                "SSH command failed or timed out. Check the VM in Terminal; no local fallback was used.",
            )
