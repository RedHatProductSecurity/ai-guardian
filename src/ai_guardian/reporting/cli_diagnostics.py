"""Bounded, sanitized host CLI configuration copies for user-reviewed support.

Use setup's path resolvers without invoking any CLI or importing its MCP server.
Never traverse configuration directories, credential stores, or conversations.
"""

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_CONFIG_BYTES = 256_000
MAX_CONFIG_TOTAL_BYTES = 1_000_000
_FORMATS = {".json", ".jsonc", ".toml", ".yaml", ".yml"}


def _write_text(path: Path, text: str) -> None:
    """Write reviewed diagnostic text with stable LF newlines."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(text)


def _config_sources() -> list[tuple[str, str, str, Path]]:
    """Enumerate known settings/hook/MCP files, including active-project layers."""
    from ai_guardian.config.utils import get_project_dir
    from ai_guardian.ide_paths import get_ide_home
    from ai_guardian.setup.hooks import IDESetup
    from ai_guardian.setup.mcp import get_mcp_config_path

    # The project directory is an intentional user-selected read root; only
    # allowlisted configuration paths under it are inspected, never executed.
    project = Path(get_project_dir()).expanduser().resolve()  # lgtm[py/path-injection]
    if not project.is_dir():
        logger.warning(
            "Project directory is unavailable; project CLI diagnostics omitted"
        )
        return []
    sources = []
    seen = set()

    def add(agent: str, scope: str, kind: str, path) -> None:
        if path is None:
            return
        path = Path(path).expanduser()
        if not path.is_absolute():
            path = project / path
            scope = "project"
        if path.name.lower() in {
            "auth.json",
            "auth-profiles.json",
            "credentials.json",
            "oauth_creds.json",
            "tokens.json",
        }:
            return
        if path.suffix.lower() not in _FORMATS or path in seen:
            return
        seen.add(path)
        sources.append((agent, scope, kind, path))

    setup = IDESetup()
    for agent, spec in setup.IDE_CONFIGS.items():
        # Directory-based plugins/skills are code, not configuration files.
        if spec.get("config_filename"):
            add(agent, "user", "hooks", setup.get_config_path(agent))
        add(agent, "user", "mcp", get_mcp_config_path(agent))

    for agent in ("cursor", "grok", "crush"):
        add(
            agent,
            "project",
            "hooks",
            setup.get_config_path(agent, scope="project", project_dir=str(project)),
        )
        add(
            agent,
            "project",
            "mcp",
            get_mcp_config_path(agent, scope="project", project_dir=str(project)),
        )

    # Optional native settings and project overlays are not all setup targets.
    pi_home = get_ide_home("pi") or Path("~/.pi/agent").expanduser()
    copilot_home = get_ide_home("copilot") or Path("~/.copilot").expanduser()
    add("pi", "user", "settings", pi_home / "settings.json")
    add("copilot", "user", "settings", copilot_home / "config.json")
    add("copilot", "user", "mcp", copilot_home / "mcp-config.json")
    for agent, overlays in {
        "claude": {
            "settings": ".claude/settings.json",
            "settings-local": ".claude/settings.local.json",
            "mcp": ".mcp.json",
        },
        "codex": {"config": ".codex/config.toml", "hooks": ".codex/hooks.json"},
        "gemini": {"settings": ".gemini/settings.json"},
        "opencode": {
            "config-json": "opencode.json",
            "config-jsonc": "opencode.jsonc",
            "dot-config-json": ".opencode/opencode.json",
            "dot-config-jsonc": ".opencode/opencode.jsonc",
        },
        "pi": {"settings": ".pi/settings.json"},
    }.items():
        for kind, name in overlays.items():
            add(agent, "project", kind, project / name)
    return sources


def _read_config(path: Path, limit: int | None) -> bytes:
    """Read an unlinked regular file, with an optional collection byte limit."""
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Linked configuration omitted")
    # The trailing separator excludes sibling directories sharing this prefix.
    root = os.path.join(str(path.parent.resolve(strict=True)), "")
    canonical = str(path.resolve(strict=True))
    if not canonical.startswith(root):
        raise ValueError("Configuration escapes its source directory")
    path = Path(canonical)
    attributes = path.stat()
    if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
        raise ValueError("Unsupported configuration file omitted")
    if limit is not None and attributes.st_size > limit:
        raise ValueError("Configuration exceeds the diagnostic size limit")
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "rb") as stream:
        attributes = os.fstat(stream.fileno())
        if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
            raise ValueError("Unsupported configuration file omitted")
        raw = stream.read() if limit is None else stream.read(limit + 1)
    if limit is not None and len(raw) > limit:
        raise ValueError("Configuration exceeds the diagnostic size limit")
    return raw


def _parse_config(path: Path, raw: bytes) -> dict:
    """Parse supported formats; never fall back to unsafe raw diagnostic text."""
    text = raw.decode("utf-8")
    suffix = path.suffix.lower()
    if suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        value = tomllib.loads(text)
    elif suffix in (".yaml", ".yml"):
        import yaml

        value = yaml.safe_load(text)
    else:
        if suffix == ".jsonc":
            from ai_guardian.setup.utils import _strip_jsonc_comments

            text = _strip_jsonc_comments(text)
        value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Configuration must be an object")
    return value


def _redact_credentials(value: Any) -> tuple[Any, int]:
    """Remove credential containers even when their values are not strings."""
    count = 0
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized.startswith("_comment"):
                continue
            if normalized in (
                "env",
                "environment",
                "env_vars",
                "envvars",
                "headers",
                "http_headers",
                "httpheaders",
            ):
                if isinstance(item, dict):
                    result[key] = {name: "[REDACTED]" for name in item}
                    count += len(item)
                else:
                    result[key] = "[REDACTED]"
                    count += 1
            elif normalized in ("auth", "key") or any(
                part in normalized
                for part in (
                    "token",
                    "password",
                    "passwd",
                    "secret",
                    "api_key",
                    "apikey",
                    "credential",
                    "private_key",
                    "privatekey",
                    "access_key",
                    "accesskey",
                    "authorization",
                    "cookie",
                    "url",
                    "endpoint",
                )
            ):
                result[key] = "[REDACTED]"
                count += 1
            else:
                result[key], redactions = _redact_credentials(item)
                count += redactions
        return result, count
    if isinstance(value, list):
        result_list = []
        for item in value:
            sanitized, redactions = _redact_credentials(item)
            result_list.append(sanitized)
            count += redactions
        return result_list, count
    return value, 0


def collect_cli_configs(output_dir: Path) -> list[dict[str, Any]]:
    """Write individual sanitized JSON copies; return names/counts, never contents."""
    from ai_guardian.config.utils import get_project_dir
    from ai_guardian.reporting.github_support import public_text

    files = []
    remaining = MAX_CONFIG_TOTAL_BYTES
    for agent, scope, kind, path in _config_sources():
        # Missing files are normal: CLI installation and authentication are not
        # prerequisites to preparing diagnostics for a broken integration.
        if not path.exists() and not path.is_symlink():
            continue
        count = 0
        artifact: dict[str, Any] = {
            "integration": agent,
            "scope": scope,
            "kind": kind,
            "format": path.suffix.lstrip("."),
        }
        try:
            raw = _read_config(path, min(MAX_CONFIG_BYTES, remaining))
            remaining -= len(raw)
            value = _parse_config(path, raw)
            if agent == "claude" and scope == "user" and kind == "mcp":
                # ~/.claude.json mixes MCP registration with account/history
                # state. Only the MCP mapping belongs in support diagnostics.
                value = {"mcpServers": value.get("mcpServers", {})}
            value, count = _redact_credentials(value)
            artifact["configuration"] = value
            text = json.dumps(artifact, indent=2, default=str)
            for prefix, replacement in (
                (str(Path(get_project_dir()).absolute()), "[PROJECT]"),
                (str(Path.home()), "[HOME]"),
            ):
                escaped = json.dumps(prefix)[1:-1]
                if len(prefix) > 1:
                    count += text.count(escaped)
                    text = text.replace(escaped, replacement)
            text, redactions = public_text(text)
            count += redactions
            note = "Sanitized CLI configuration copy; original file unchanged"
        except Exception:
            # Parse/sanitizer exceptions can contain credential values. Never
            # log them or fall back to publishing the unparsed source text.
            logger.warning(
                "CLI support configuration omitted (%s/%s/%s)", agent, scope, kind
            )
            artifact.pop("configuration", None)
            artifact.update(
                status="omitted",
                reason="Configuration could not be safely read, parsed, and sanitized; source content omitted.",
            )
            text = json.dumps(artifact, indent=2)
            count = 0
            note = "Configuration omitted; review the diagnostic status file"
        # The directory is private and protected; only sanitized JSON is
        # written here for the user's explicit review.
        output_dir.mkdir(
            mode=0o700, parents=True, exist_ok=True
        )  # lgtm[py/clear-text-storage-sensitive-data]
        (output_dir / ".ai-read-deny").touch()
        name = f"cli-{agent}-{scope}-{kind}.json"
        _write_text(
            output_dir / name, text
        )  # lgtm[py/clear-text-storage-sensitive-data]
        files.append(
            {
                "name": name,
                "sanitized": count > 0,
                "redactions": count,
                "note": note,
                "collection_status": artifact.get("status", "included"),
            }
        )
    return files
