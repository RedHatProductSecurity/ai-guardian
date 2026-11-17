#!/usr/bin/env python3
"""Smoke-only stdio proxy that records aggregate MCP version evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_VERSION_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?(?![0-9A-Za-z])"
)


def _result_versions(value: Any, depth: int = 0) -> Iterable[str]:
    """Read version fields from structured MCP result data, never prose."""
    if depth > 12:
        return
    if isinstance(value, dict):
        version = value.get("version")
        if isinstance(version, str):
            yield version
        for child in value.values():
            yield from _result_versions(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _result_versions(child, depth + 1)
    elif isinstance(value, str) and len(value) <= 65536:
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return
        if isinstance(decoded, (dict, list)):
            yield from _result_versions(decoded, depth + 1)


def _installed_version(command: str) -> str:
    """Read the version from the exact installed MCP-server executable."""
    try:
        result = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("AI Guardian MCP executable version is unavailable") from exc
    if result.returncode != 0:
        raise ValueError("AI Guardian MCP executable version is unavailable")
    match = _VERSION_PATTERN.search("\n".join((result.stdout, result.stderr)))
    if match is None:
        raise ValueError("AI Guardian MCP executable version is unavailable")
    return match.group(0)


def _append_event(event: str) -> None:
    evidence_path = os.environ.get("AI_GUARDIAN_MCP_EVIDENCE_FILE")
    if not evidence_path:
        return
    path = Path(evidence_path)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        line = (
            json.dumps({"event": event}, separators=(",", ":")).encode("ascii") + b"\n"
        )
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)
    except OSError:
        # Evidence failure must never prevent the real MCP response reaching its client.
        print("MCP smoke evidence could not be recorded", file=sys.stderr)


def _identity_key(value: Any) -> Optional[str]:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return json.dumps(value, separators=(",", ":"))
    return None


def _proxy_server(command: List[str], expected_version: str) -> int:
    if not command:
        print("MCP evidence proxy requires a server command", file=sys.stderr)
        return 2
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            bufsize=0,
        )
    except OSError:
        print(
            "MCP evidence proxy could not start the configured server", file=sys.stderr
        )
        return 127

    pending: Dict[str, int] = {}
    pending_lock = threading.Lock()

    def forward_server_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                response = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                response = None
            try:
                if isinstance(response, dict):
                    key = _identity_key(response.get("id"))
                    if key is not None:
                        with pending_lock:
                            count = pending.get(key, 0)
                            if count:
                                if count == 1:
                                    del pending[key]
                                else:
                                    pending[key] = count - 1
                                result = response.get("result")
                                version_matches = (
                                    expected_version in set(_result_versions(result))
                                    and response.get("error") is None
                                    and not (
                                        isinstance(result, dict)
                                        and result.get("isError") is True
                                    )
                                )
                                _append_event(
                                    "mcp_result_match"
                                    if version_matches
                                    else "mcp_result_mismatch"
                                )
            except (OSError, TypeError, ValueError, RecursionError):
                # The proxy is observational; a failed counter must not alter MCP.
                print(
                    "MCP smoke result evidence could not be recorded", file=sys.stderr
                )
            try:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
            except OSError:
                break

    output_thread = threading.Thread(target=forward_server_output, daemon=True)
    output_thread.start()

    assert process.stdin is not None
    try:
        for line in sys.stdin.buffer:
            try:
                request = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                request = None
            if (
                isinstance(request, dict)
                and request.get("method") == "tools/call"
                and isinstance(request.get("params"), dict)
                and request["params"].get("name") == "get_version"
            ):
                key = _identity_key(request.get("id"))
                if key is not None:
                    with pending_lock:
                        pending[key] = pending.get(key, 0) + 1
                    _append_event("mcp_call")
            process.stdin.write(line)
            process.stdin.flush()
    except BrokenPipeError:
        pass
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass

    return_code = process.wait()
    output_thread.join(timeout=5)
    return return_code


def _wrap_entry(
    entry: Dict[str, Any],
    proxy_path: str,
    expected_version: str,
    *,
    command_array: bool = False,
) -> bool:
    command = entry.get("command")
    entry_args = entry.get("args", [])
    if not isinstance(entry_args, list) or not all(
        isinstance(item, str) for item in entry_args
    ):
        raise ValueError("AI Guardian MCP args are not a string list")

    if command_array:
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(item, str) for item in command)
        ):
            raise ValueError("AI Guardian MCP command is not a string list")
        server_command = [*command, *entry_args]
    elif isinstance(command, str):
        server_command = [command, *entry_args]
    else:
        raise ValueError("AI Guardian MCP command is not a string")

    if server_command[:3] == [sys.executable, proxy_path, "proxy"]:
        return False

    if command_array:
        entry["command"] = [
            sys.executable,
            proxy_path,
            "proxy",
            "--expected-version",
            expected_version,
            "--",
            *server_command,
        ]
        entry.pop("args", None)
    else:
        entry["command"] = sys.executable
        entry["args"] = [
            proxy_path,
            "proxy",
            "--expected-version",
            expected_version,
            "--",
            *server_command,
        ]
    return True


def _patch_json_config(path: Path, cli: str, proxy_path: str) -> bool:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("AI Guardian MCP config could not be read") from exc
    if not isinstance(config, dict):
        raise ValueError("AI Guardian MCP config has an invalid root")

    entry: Any = None
    if cli in {"claude", "gemini"}:
        servers = config.get("mcpServers")
        entry = servers.get("ai-guardian") if isinstance(servers, dict) else None
    elif cli == "opencode":
        mcp = config.get("mcp")
        opencode_v2_servers = mcp.get("servers") if isinstance(mcp, dict) else None
        if isinstance(mcp, dict):
            servers = opencode_v2_servers
            entry = (
                servers.get("ai-guardian")
                if isinstance(servers, dict)
                else mcp.get("ai-guardian")
            )
    if not isinstance(entry, dict):
        raise ValueError("AI Guardian MCP server is missing from the CLI config")

    server_command = entry.get("command")
    server_args = entry.get("args", [])
    if cli == "opencode":
        if not isinstance(server_command, list) or not server_command:
            raise ValueError("AI Guardian MCP command is not a string list")
        version_command = server_command[0]
    else:
        if not isinstance(server_command, str):
            raise ValueError("AI Guardian MCP command is not a string")
        version_command = server_command
    if (
        server_command == sys.executable
        and isinstance(server_args, list)
        and server_args[:2] == [proxy_path, "proxy"]
    ) or (
        isinstance(server_command, list)
        and server_command[:3] == [sys.executable, proxy_path, "proxy"]
    ):
        return False
    expected_version = _installed_version(version_command)
    config_changed = False
    if cli == "opencode" and isinstance(opencode_v2_servers, dict):
        # The V2 smoke qualifies the server's direct native MCP function. Keep
        # Code Mode's execute interpreter outside this result-transport check.
        if entry.get("codemode") is not False:
            entry["codemode"] = False
            config_changed = True
    wrapped_changed = _wrap_entry(
        entry,
        proxy_path,
        expected_version,
        command_array=(cli == "opencode"),
    )
    if wrapped_changed or config_changed:
        path.write_text(json.dumps(config), encoding="utf-8")
    return wrapped_changed or config_changed


def _load_toml(path: Path) -> Dict[str, Any]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("AI Guardian MCP config could not be read") from exc
    if not isinstance(value, dict):
        raise ValueError("AI Guardian MCP config has an invalid root")
    return value


def _patch_toml_config(path: Path, proxy_path: str) -> bool:
    raw = path.read_text(encoding="utf-8")
    config = _load_toml(path)
    servers = config.get("mcp_servers")
    entry = servers.get("ai-guardian") if isinstance(servers, dict) else None
    if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
        raise ValueError("AI Guardian MCP server is missing from the CLI config")
    args = entry.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError("AI Guardian MCP args are not a string list")
    if entry["command"] == sys.executable and args[:2] == [proxy_path, "proxy"]:
        return False
    expected_version = _installed_version(entry["command"])

    table = re.search(r"(?m)^[ \t]*\[mcp_servers\.ai-guardian\][ \t]*(?:#.*)?$", raw)
    if table is None:
        raise ValueError("AI Guardian MCP table could not be located")
    next_table = re.search(r"(?m)^[ \t]*\[", raw[table.end() :])
    end = table.end() + next_table.start() if next_table else len(raw)
    section = raw[table.end() : end]
    wrapped_args = [
        proxy_path,
        "proxy",
        "--expected-version",
        expected_version,
        "--",
        entry["command"],
        *args,
    ]

    def replace_field(text: str, key: str, value: str) -> str:
        pattern = re.compile(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$")
        line = f"{key} = {value}"
        if pattern.search(text):
            return pattern.sub(line, text, count=1)
        return text.rstrip() + "\n" + line + "\n"

    section = replace_field(section, "command", json.dumps(sys.executable))
    section = replace_field(section, "args", json.dumps(wrapped_args))
    raw = raw[: table.end()] + section + raw[end:]
    path.write_text(raw, encoding="utf-8")
    return True


def _patch_pi_extension(extension: Path, proxy_path: str) -> bool:
    try:
        source = extension.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("managed Pi MCP extension could not be read") from exc
    binary_pattern = re.compile(r'const GUARDIAN_BINARY = ("[^"]*");')
    args_pattern = re.compile(r"const GUARDIAN_BINARY_ARGS: string\[\] = (\[[^;]*\]);")
    binary_match = binary_pattern.search(source)
    args_match = args_pattern.search(source)
    if binary_match is None or args_match is None:
        raise ValueError("managed Pi MCP launch settings could not be located")
    try:
        binary = json.loads(binary_match.group(1))
        args = json.loads(args_match.group(1))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("managed Pi MCP launch settings are invalid") from exc
    if (
        not isinstance(binary, str)
        or not isinstance(args, list)
        or not all(isinstance(item, str) for item in args)
    ):
        raise ValueError("managed Pi MCP launch settings have invalid types")
    if binary == sys.executable and args[:2] == [proxy_path, "proxy"]:
        return False

    expected_version = _installed_version(binary)
    wrapped_args = [
        proxy_path,
        "proxy",
        "--expected-version",
        expected_version,
        "--",
        binary,
        *args,
    ]
    source = binary_pattern.sub(
        f"const GUARDIAN_BINARY = {json.dumps(sys.executable)};", source, count=1
    )
    source = args_pattern.sub(
        "const GUARDIAN_BINARY_ARGS: string[] = " + json.dumps(wrapped_args) + ";",
        source,
        count=1,
    )
    extension.write_text(source, encoding="utf-8")
    return True


def _install_proxy(cli: str, home: Path, pi_agent_dir: Optional[Path]) -> int:
    proxy_path = str(Path(__file__).resolve())
    try:
        if cli == "claude":
            changed = _patch_json_config(home / ".claude.json", cli, proxy_path)
        elif cli == "gemini":
            changed = _patch_json_config(
                home / ".gemini" / "settings.json", cli, proxy_path
            )
        elif cli == "opencode":
            changed = _patch_json_config(
                home / ".config" / "opencode" / "opencode.json", cli, proxy_path
            )
        elif cli in {"codex", "grok"}:
            config_path = (
                home / ".codex" / "config.toml"
                if cli == "codex"
                else home / ".grok" / "config.toml"
            )
            changed = _patch_toml_config(config_path, proxy_path)
        elif cli == "pi":
            agent_dir = pi_agent_dir or home / ".pi" / "agent"
            changed = _patch_pi_extension(
                agent_dir / "extensions" / "ai-guardian" / "index.ts", proxy_path
            )
        else:
            raise ValueError("CLI has no configured AI Guardian MCP smoke path")
    except (OSError, ValueError) as exc:
        print(f"MCP evidence proxy setup failed: {exc}", file=sys.stderr)
        return 1
    if not changed:
        print("MCP evidence proxy was already configured", file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "proxy":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--expected-version", required=True)
        options, command = parser.parse_known_args(args[1:])
        if command and command[0] == "--":
            command = command[1:]
        return _proxy_server(command, options.expected_version)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install", choices=("install",))
    parser.add_argument(
        "--cli",
        choices=("claude", "codex", "gemini", "opencode", "pi", "grok"),
        required=True,
    )
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--pi-agent-dir", type=Path)
    options = parser.parse_args(args)
    return _install_proxy(options.cli, options.home, options.pi_agent_dir)


if __name__ == "__main__":
    raise SystemExit(main())
