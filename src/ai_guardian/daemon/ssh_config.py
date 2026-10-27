"""Bounded, declarative user OpenSSH alias enumeration. Never invokes SSH.

This is deliberately not an OpenSSH evaluator. Include is supported only in
unconditional scope, for config / *.conf files below the user's .ssh directory.
Match predicates and every connection setting remain the system client's job.
"""

from dataclasses import dataclass
import fnmatch
import glob
import json
import logging
import os
from pathlib import Path
import re
import shlex
import stat

logger = logging.getLogger(__name__)

MAX_FILES = 64
MAX_DEPTH = 8
MAX_FILE_BYTES = 262144
MAX_TOTAL_BYTES = 1048576
MAX_ALIASES = 256
MAX_DIRECTORY_ENTRIES = 4096
DEFAULT_SETTINGS = {"enabled": False, "alias_prefix": "ai-guardian-"}
CONFIG_NOTICE = "SSH alias configuration is missing, unreadable, or unsupported. Check the local user SSH config; saved pairings are unchanged."
LIMIT_NOTICE = "SSH alias discovery reached its local parsing limits; some aliases were not listed. Use a smaller dedicated SSH Include file."
INCLUDE_NOTICE = "Some SSH Include directives were skipped (conditional, cyclic, linked, or outside the supported local config subset)."
SETTINGS_NOTICE = (
    "SSH alias discovery settings are unavailable or invalid; discovery is off."
)


@dataclass(frozen=True)
class AliasScan:
    aliases: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()


def user_ssh_config() -> Path:
    # System OpenSSH on Windows also uses %USERPROFILE%/.ssh/config.
    return Path.home() / ".ssh" / "config"


def load_settings(path: Path | None = None) -> dict:
    if path is None:
        from ai_guardian.config.utils import get_config_dir

        path = get_config_dir() / "ai-guardian.json"
    try:
        with path.open(encoding="utf-8") as stream:
            config = json.load(stream)
        settings = (
            config.get("daemon", {}).get("tray", {}).get("ssh_alias_discovery", {})
        )
        enabled, prefix = settings.get("enabled", False), settings.get(
            "alias_prefix", "ai-guardian-"
        )
        if (
            type(enabled) is not bool
            or not isinstance(prefix, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{0,253}", prefix)
        ):
            raise ValueError
        return {"enabled": enabled, "alias_prefix": prefix}
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except (OSError, ValueError, AttributeError):
        logger.warning(SETTINGS_NOTICE)
        return dict(DEFAULT_SETTINGS)


def save_settings(enabled, alias_prefix):
    """Shared tray/Web writer: always workstation-global, never remote/project."""
    from ai_guardian.config.utils import get_config_dir
    from ai_guardian.config.writer import _atomic_config_update, _ensure_section
    from ai_guardian.daemon.ssh_storage import SSHConnectionError

    if (
        type(enabled) is not bool
        or not isinstance(alias_prefix, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{0,253}", alias_prefix)
    ):
        raise SSHConnectionError(
            "Use a literal SSH alias prefix (letters, numbers, dots, underscores or hyphens), or leave it empty for all concrete aliases."
        )

    path = get_config_dir() / "ai-guardian.json"

    def update(config):
        # The shared updater can recover malformed configs for other callers;
        # this narrow settings form must never discard unrelated configuration.
        try:
            if path.exists():
                with path.open(encoding="utf-8") as stream:
                    if not isinstance(json.load(stream), dict):
                        raise ValueError
            if not isinstance(config, dict):
                raise ValueError
        except (OSError, ValueError):
            raise SSHConnectionError(
                "Could not read local configuration; SSH discovery settings were not saved."
            ) from None
        tray = _ensure_section(_ensure_section(config, "daemon"), "tray")
        tray["ssh_alias_discovery"] = {
            "enabled": enabled,
            "alias_prefix": alias_prefix,
        }
        return False, "Updated local SSH alias discovery settings"

    if not _atomic_config_update(path, update):
        raise SSHConnectionError(
            "Could not save local SSH alias discovery settings. Check configuration access and read-only state."
        )


def scan_aliases(path: Path | None = None, *, prefix: str = "") -> AliasScan:
    """Return concrete declared Host names, not resolved/verified destinations.

    Includes are relative to .ssh (as in OpenSSH), not the including file.
    No env/token expansion, recursive globs, parent traversal, linked files,
    non-regular files, key paths or external/system config includes are followed.
    """
    path = path if path is not None else user_ssh_config()
    root = path.parent
    aliases: dict[str, str] = {}
    notices: set[str] = set()
    active: set[Path] = set()
    files = 0
    total = 0
    include_patterns = 0

    def unlinked(candidate):
        relative = candidate.relative_to(root)
        return ".." not in relative.parts and not any(
            part.is_symlink()
            for part in [root, *candidate.parents[: len(relative.parts) - 1], candidate]
        )

    def safe_file(candidate):
        try:
            return (
                candidate.name == "config" or candidate.suffix == ".conf"
            ) and unlinked(candidate)
        except (OSError, ValueError):
            return False

    def expand(included):
        if not unlinked(included):
            notices.add(INCLUDE_NOTICE)
            return []
        if not glob.has_magic(included.name):
            return [included] if included.exists() else []
        matches: list[Path] = []
        try:
            # glob.iglob internally lists the entire directory before yielding.
            # Bound even nonmatching directory entries instead.
            with os.scandir(included.parent) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_DIRECTORY_ENTRIES or len(matches) >= MAX_FILES:
                        notices.add(LIMIT_NOTICE)
                        break
                    if fnmatch.fnmatchcase(entry.name, included.name):
                        matches.append(Path(entry.path))
        except OSError:
            notices.add(CONFIG_NOTICE)
        return sorted(matches)

    def parse(candidate, scope="global", depth=0):
        nonlocal files, total, include_patterns
        if candidate in active or not safe_file(candidate):
            notices.add(INCLUDE_NOTICE)
            return scope
        if depth >= MAX_DEPTH or files >= MAX_FILES or total >= MAX_TOTAL_BYTES:
            notices.add(LIMIT_NOTICE)
            return scope
        files += 1
        try:
            data = _read_config(
                candidate, min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total) + 1
            )
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                notices.add(LIMIT_NOTICE)
                return scope
            text = data.decode("utf-8-sig")
        except (OSError, ValueError):
            notices.add(CONFIG_NOTICE)
            return scope
        active.add(candidate)
        try:
            for line in text.splitlines():
                # OpenSSH accepts Keyword=value and Keyword = value too.
                line = re.sub(r"^(\s*\w+)\s*=\s*", r"\1 ", line)
                try:
                    parts = shlex.split(line, comments=True, posix=True)
                except ValueError:
                    notices.add(CONFIG_NOTICE)
                    continue
                if not parts:
                    continue
                keyword, values = parts[0].lower(), parts[1:]
                if keyword == "host":
                    scope = "host"
                    for alias in values:
                        if not re.fullmatch(
                            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", alias
                        ) or not alias.casefold().startswith(prefix.casefold()):
                            continue
                        key = alias.casefold()
                        if key not in aliases and len(aliases) >= MAX_ALIASES:
                            notices.add(LIMIT_NOTICE)
                        else:
                            aliases.setdefault(key, alias)
                elif keyword == "match":
                    scope = "match"
                elif keyword == "include":
                    if scope != "global":
                        notices.add(INCLUDE_NOTICE)
                        continue
                    for pattern in values:
                        if include_patterns >= MAX_FILES:
                            notices.add(LIMIT_NOTICE)
                            break
                        include_patterns += 1
                        if pattern.startswith("~/"):
                            pattern = str(root.parent / pattern[2:])
                        included = Path(pattern)
                        if not included.is_absolute():
                            included = root / included
                        try:
                            relative = included.relative_to(root)
                        except ValueError:
                            notices.add(INCLUDE_NOTICE)
                            continue
                        if (
                            ".." in relative.parts
                            or "**" in pattern
                            or any(char in pattern for char in "$%\\")
                            or any(glob.has_magic(part) for part in relative.parts[:-1])
                        ):
                            notices.add(INCLUDE_NOTICE)
                            continue
                        try:
                            matches = expand(included)
                        except (OSError, ValueError):
                            notices.add(INCLUDE_NOTICE)
                            continue
                        for match in matches:
                            scope = parse(match, scope, depth + 1)
        finally:
            active.remove(candidate)
        return scope

    parse(path)
    return AliasScan(
        tuple(aliases[key] for key in sorted(aliases)), tuple(sorted(notices))
    )


def _read_config(path, limit):
    """Reject links/devices and a file swapped between inspection and opening."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        current = os.fstat(stream.fileno())
        if not stat.S_ISREG(current.st_mode) or (before.st_dev, before.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            raise ValueError
        return stream.read(limit)
