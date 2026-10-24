#!/usr/bin/env python3
"""Operator-invoked integration recovery, independent of the installed package.

Python 3.11+ standard library only. Do not import ai_guardian here: the package,
its interpreter, and every registered executable may already be gone. This is
not a hook fallback, CLI subcommand, or MCP tool.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    tomllib = None  # type: ignore[assignment]

GENERATED = "// ai-guardian-generated-version:"
MAX_FILE_BYTES = 8 * 1024 * 1024
DROP = object()


def basename(value: str) -> str:
    return value.strip("\"'").replace("\\", "/").rsplit("/", 1)[-1].lower()


def owned_command(command: Any, args: Any = None) -> bool:
    """Recognize setup's exact launch forms, never a name in an argument.

    No runtime lookup or execution. Compound/custom shell commands are left to
    the operator rather than deleting an embedded third-party security check.
    """
    if isinstance(command, list):
        tokens = command
    elif isinstance(command, str):
        if re.search(r"[;&|<>`\n\r]", command):
            return False
        try:
            tokens = shlex.split(
                command, posix=not bool(re.search(r"[A-Za-z]:\\", command))
            )
        except ValueError:
            return False
    else:
        return False
    if args is not None:
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            return False
        tokens = [*tokens, *args]
    if not tokens or not all(isinstance(token, str) for token in tokens):
        return False
    executable = basename(tokens[0])
    if executable in {"ai-guardian", "ai-guardian.exe", "ai-guardian.cmd"}:
        return True
    if not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable):
        return False
    index = 1
    while index < len(tokens) and tokens[index] in {"-I", "-S", "-s", "-E", "-u"}:
        index += 1
    return tokens[index : index + 1] == ["-m"] and tokens[index + 1 : index + 2] in (
        ["ai_guardian"],
        ["ai_guardian_hook_runtime"],
    )


def jsonc_text(text: str) -> tuple[str, str]:
    """Mask comments/trailing commas without changing character offsets."""
    chars = list(text)
    decoder = json.JSONDecoder()
    i = 0
    while i < len(text):
        if text[i] == '"':
            _, i = decoder.raw_decode(text, i)
        elif text.startswith("//", i) or text.startswith("/*", i):
            if text.startswith("//", i):
                end = text.find("\n", i)
                end = len(text) if end < 0 else end
            else:
                end = text.find("*/", i + 2)
                if end < 0:
                    raise ValueError("Unterminated JSONC comment")
                end += 2
            chars[i:end] = ["\n" if c == "\n" else " " for c in text[i:end]]
            i = end
        else:
            i += 1
    comments_masked = "".join(chars)
    i = 0
    while i < len(chars):
        if chars[i] == '"':
            _, i = decoder.raw_decode(comments_masked, i)
        elif chars[i] == ",":
            following = i + 1
            while following < len(chars) and chars[following].isspace():
                following += 1
            if following < len(chars) and chars[following] in "}]":
                chars[i] = " "
            i += 1
        else:
            i += 1
    return "".join(chars), comments_masked


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError("Non-JSON constant")


def load_json(text: str) -> Any:
    masked, _ = jsonc_text(text)
    return json.loads(
        masked, object_pairs_hook=unique_object, parse_constant=invalid_constant
    )


@dataclass
class JsonNode:
    start: int
    end: int
    members: list[tuple[str | int, int, JsonNode]] = field(default_factory=list)


def json_tree(masked: str, start: int = 0) -> JsonNode:
    """Locate validated JSON members so removals retain comments/formatting."""
    while masked[start].isspace():
        start += 1
    decoder = json.JSONDecoder()
    if masked[start] not in "[{":
        _, end = decoder.raw_decode(masked, start)
        return JsonNode(start, end)
    opening = masked[start]
    closing = "}" if opening == "{" else "]"
    node = JsonNode(start, start)
    i = start + 1
    while True:
        while masked[i].isspace() or masked[i] == ",":
            i += 1
        if masked[i] == closing:
            node.end = i + 1
            return node
        entry_start = i
        if opening == "{":
            key, i = decoder.raw_decode(masked, i)
            while masked[i].isspace() or masked[i] == ":":
                i += 1
        else:
            key = len(node.members)
        child = json_tree(masked, i)
        node.members.append((key, entry_start, child))
        i = child.end


def without_spans(text: str, spans: list[tuple[int, int]]) -> str:
    pieces = []
    cursor = 0
    for start, end in sorted(spans):
        if start > cursor:
            pieces.append(text[cursor:start])
        cursor = max(cursor, end)
    pieces.append(text[cursor:])
    return "".join(pieces)


def delete_json_members(text: str, removed: set[tuple]) -> str:
    masked, comments_masked = jsonc_text(text)
    spans: list[tuple[int, int]] = []

    def visit(node: JsonNode, path: tuple = ()) -> None:
        retained = [path + (key,) not in removed for key, _, _ in node.members]
        unchanged = all(retained)
        last_retained = max((i for i, keep in enumerate(retained) if keep), default=-1)
        for index, (key, entry_start, child) in enumerate(node.members):
            if not retained[index]:
                spans.append((entry_start, child.end))
            else:
                visit(child, path + (key,))
            following = (
                node.members[index + 1][1]
                if index + 1 < len(node.members)
                else node.end - 1
            )
            comma = comments_masked.find(",", child.end, following)
            if (
                comma >= 0
                and not unchanged
                and not (retained[index] and index < last_retained)
            ):
                spans.append((comma, comma + 1))

    visit(json_tree(masked))
    return without_spans(text, spans)


def clean_hooks(
    value: Any, path: tuple, removed: set[tuple], problems: list[str]
) -> Any:
    if isinstance(value, list):
        cleaned = []
        for index, item in enumerate(value):
            result = clean_hooks(item, path + (index,), removed, problems)
            if result is not DROP:
                cleaned.append(result)
        return cleaned
    if not isinstance(value, dict):
        return value
    commands = [value[key] for key in ("command", "bash", "powershell") if key in value]
    if commands and any(owned_command(command) for command in commands):
        if all(owned_command(command) for command in commands):
            removed.add(path)
            return DROP
        problems.append("mixed owned and third-party hook commands retained")
        return value
    if commands and any(
        isinstance(command, str)
        and owned_command(re.split(r"[;&|]", command, maxsplit=1)[0].strip())
        for command in commands
    ):
        problems.append("unrecognized hook command retained")
    result = {}
    for key, item in value.items():
        cleaned = clean_hooks(item, path + (key,), removed, problems)
        if cleaned is DROP or (isinstance(item, (dict, list)) and item and not cleaned):
            removed.add(path + (key,))
        else:
            result[key] = cleaned
    if (
        isinstance(value.get("hooks"), list)
        and value["hooks"]
        and "hooks" not in result
    ):
        removed.add(path)
        return DROP
    return result


def clean_json(text: str, host: str, plugin_paths: set[Path]) -> tuple[str, list[str]]:
    config = load_json(text)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be an object")
    expected = copy.deepcopy(config)
    removed: set[tuple] = set()
    problems: list[str] = []
    if host == "copilot":
        for event in (
            "userPromptSubmitted",
            "preToolUse",
            "postToolUse",
            "sessionStart",
            "sessionEnd",
        ):
            if event in expected:
                if not isinstance(expected[event], list):
                    raise ValueError("Invalid Copilot event container")
                expected[event] = clean_hooks(
                    expected[event], (event,), removed, problems
                )
    if "hooks" in expected:
        hooks = expected["hooks"]
        if not isinstance(hooks, dict) and not (
            host == "gemini" and isinstance(hooks, list)
        ):
            raise ValueError("Invalid hooks container")
        expected["hooks"] = clean_hooks(hooks, ("hooks",), removed, problems)
    if host == "antigravity" and "ai-guardian" in expected:
        original = expected["ai-guardian"]
        cleaned = clean_hooks(original, ("ai-guardian",), removed, problems)
        if cleaned is DROP or (original and not cleaned):
            removed.add(("ai-guardian",))
            del expected["ai-guardian"]
        else:
            expected["ai-guardian"] = cleaned
    for key in ("mcpServers", "mcp_servers", "mcp"):
        if key not in expected:
            continue
        container = expected[key]
        if not isinstance(container, dict):
            raise ValueError("Invalid MCP container")
        mappings: list[tuple[tuple[str, ...], dict[str, Any]]] = [((key,), container)]
        if key == "mcp" and "servers" in container:
            if not isinstance(container["servers"], dict):
                raise ValueError("Invalid MCP servers container")
            mappings.append(((key, "servers"), container["servers"]))
        for path, servers in mappings:
            if "ai-guardian" in servers:
                server = servers["ai-guardian"]
                if isinstance(server, dict) and owned_command(
                    server.get("command"), server.get("args")
                ):
                    del servers["ai-guardian"]
                    removed.add(path + ("ai-guardian",))
                else:
                    problems.append("unrecognized ai-guardian MCP entry retained")
    if host == "opencode":
        for key in ("plugin", "plugins"):
            if key not in expected:
                continue
            if not isinstance(expected[key], list):
                raise ValueError("Invalid plugin container")
            retained = []
            for index, entry in enumerate(expected[key]):
                # Setup registered absolute local files in V1. Never infer
                # ownership from a package name or delete a V2 options object.
                if isinstance(entry, str) and entry in {
                    spelling for p in plugin_paths for spelling in (str(p), p.as_uri())
                }:
                    removed.add((key, index))
                else:
                    retained.append(entry)
            expected[key] = retained
    if not removed:
        return text, problems
    output = delete_json_members(text, removed)
    if load_json(output) != expected:
        raise ValueError("Lossless JSON edit verification failed")
    return output, problems


def clean_toml(text: str) -> tuple[str, list[str]]:
    if tomllib is None:
        raise ValueError("Python 3.11+ is required")
    original = tomllib.loads(text)
    servers = original.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("Invalid TOML MCP container")
    if "ai-guardian" not in servers:
        return text, []
    server = servers["ai-guardian"]
    if not isinstance(server, dict) or not owned_command(
        server.get("command"), server.get("args")
    ):
        return text, ["unrecognized ai-guardian MCP entry retained"]
    expected = copy.deepcopy(original)
    del expected["mcp_servers"]["ai-guardian"]
    # Header candidates are validated twice: by TOML parsing and by comparing
    # the complete edited document. Header-looking text in multiline strings,
    # inline tables, or unusual dotted assignments can never lose other data.
    headers = list(
        re.finditer(r"(?m)^[ \t]*\[[^\r\n]+\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)", text)
    )
    spans = []
    for index, header in enumerate(headers):
        try:
            probe = tomllib.loads(header.group() + "\n__recovery_probe__ = true\n")
        except ValueError:
            continue
        if "ai-guardian" in probe.get("mcp_servers", {}):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            # Comments immediately before another table can belong to that
            # table. Retain trailing comment/blank lines rather than guessing.
            for line in reversed(text[header.end() : end].splitlines(keepends=True)):
                if line.strip() and not line.lstrip().startswith("#"):
                    break
                end -= len(line)
            spans.append((header.start(), end))
    output = without_spans(text, spans)
    parsed = tomllib.loads(output)
    # TOML implicitly creates the parent table when only a child was present.
    if expected.get("mcp_servers") == {} and "mcp_servers" not in parsed:
        expected.pop("mcp_servers")
    if not spans or parsed != expected:
        raise ValueError("Unsupported TOML layout; original retained")
    return output, []


@dataclass(frozen=True)
class ConfigTarget:
    path: Path
    host: str


@dataclass(frozen=True)
class Artifact:
    path: Path
    kind: str = "generated"
    package_name: str = ""


def expanded(value: str) -> Path:
    return Path(os.path.abspath(os.path.expandvars(os.path.expanduser(value))))


def inventory(
    scope: str, projects: list[Path]
) -> tuple[list[ConfigTarget], list[Artifact]]:
    """Finite setup inventory. No recursive discovery or parent-project walk."""
    configs: list[ConfigTarget] = []
    artifacts: list[Artifact] = []

    def config(host: str, *paths: Path) -> None:
        configs.extend(ConfigTarget(path, host) for path in paths)

    def opencode(base: Path, explicit: Path | None = None) -> None:
        config(
            "opencode",
            *(
                [explicit]
                if explicit
                else [base / "opencode.json", base / "opencode.jsonc"]
            ),
        )
        for path in (
            base / "plugins/ai-guardian.ts",
            base / "plugins/ai-guardian-bridge.ts",
            base / "ai-guardian/ai-guardian-bridge.ts",
        ):
            artifacts.append(Artifact(path))

    def package(base: Path, name: str) -> None:
        artifacts.extend(
            [
                Artifact(base / "index.ts"),
                Artifact(base / "package.json", "package", name),
                Artifact(base / "ai-guardian-bridge.ts"),
            ]
        )

    if scope in {"user", "both"}:
        home = Path.home()

        def root(default: str, *variables: str) -> Path:
            return next(
                (expanded(os.environ[v]) for v in variables if os.environ.get(v)),
                home / default,
            )

        claude = root(".claude", "CLAUDE_CONFIG_DIR")
        config(
            "claude",
            claude / "settings.json",
            (claude if os.environ.get("CLAUDE_CONFIG_DIR") else home) / ".claude.json",
        )
        cursor = root(".cursor", "CURSOR_CONFIG_DIR")
        config("cursor", cursor / "hooks.json", cursor / "mcp.json")
        copilot = root(".github", "COPILOT_HOME")
        config("copilot", copilot / "hooks/hooks.json")
        if os.environ.get("COPILOT_HOME"):
            config("copilot", copilot / "mcp-config.json")
        for host, default, variable in (
            ("codex", ".codex", "CODEX_HOME"),
            ("grok", ".grok", "GROK_HOME"),
        ):
            base = root(default, variable)
            config(
                host,
                base / ("hooks/ai-guardian.json" if host == "grok" else "hooks.json"),
                base / "config.toml",
            )
            if host == "codex":
                config(host, base / "codex.json", home / "codex.json")
        config(
            "windsurf",
            home / ".codeium/windsurf/hooks.json",
            home / ".windsurf/mcp.json",
        )
        gemini = (
            expanded(os.environ["GEMINI_CLI_HOME"]) / ".gemini"
            if os.environ.get("GEMINI_CLI_HOME")
            else home / ".gemini"
        )
        config("gemini", gemini / "settings.json")
        config(
            "antigravity",
            home / ".gemini/config/hooks.json",
            home / ".gemini/config/mcp_config.json",
        )
        config("augment", home / ".augment/settings.json")
        config("cline", root(".cline", "CLINE_DATA_DIR") / "mcp_settings.json")
        config(
            "kiro",
            root(".kiro", "KIRO_HOME")
            / ("settings/mcp.json" if os.environ.get("KIRO_HOME") else "settings.json"),
        )
        config("junie", root(".junie", "JUNIE_HOME") / "mcp.json")
        aider = root(".aider-desk", "AIDER_DESK_DIR", "AIDER_DESK_HOME_DIR")
        config("aiderdesk", aider / "settings.json")
        package(aider / "extensions/ai-guardian", "ai-guardian-aiderdesk")
        claw = root(".openclaw", "OPENCLAW_STATE_DIR")
        if not os.environ.get("OPENCLAW_STATE_DIR") and os.environ.get("OPENCLAW_HOME"):
            claw = expanded(os.environ["OPENCLAW_HOME"]) / ".openclaw"
        config(
            "openclaw",
            (
                expanded(os.environ["OPENCLAW_CONFIG_PATH"])
                if os.environ.get("OPENCLAW_CONFIG_PATH")
                else claw / "settings.json"
            ),
        )
        package(claw / "plugins/ai-guardian", "ai-guardian-openclaw")
        explicit = (
            expanded(os.environ["OPENCODE_CONFIG"])
            if os.environ.get("OPENCODE_CONFIG")
            else None
        )
        opencode(
            (
                explicit.parent
                if explicit
                else root(".config/opencode", "OPENCODE_CONFIG_DIR")
            ),
            explicit,
        )
        pi = root(".pi/agent", "PI_CODING_AGENT_DIR") / "extensions"
        package(pi / "ai-guardian", "ai-guardian-pi-extension")
        artifacts.append(Artifact(pi / "ai-guardian.ts"))
        if os.environ.get("CRUSH_GLOBAL_CONFIG"):
            config("crush", expanded(os.environ["CRUSH_GLOBAL_CONFIG"]))
    for project in projects:
        for host, paths in {
            "claude": (
                ".claude/settings.json",
                ".claude/settings.local.json",
                ".mcp.json",
            ),
            "cursor": (".cursor/hooks.json", ".cursor/mcp.json"),
            "codex": (".codex/hooks.json", ".codex/config.toml", ".codex/codex.json"),
            "copilot": (".github/hooks/hooks.json",),
            "grok": (".grok/hooks/ai-guardian.json", ".grok/config.toml"),
            "gemini": (".gemini/settings.json",),
            "antigravity": (".agents/hooks.json",),
            "crush": (".crush.json",),
        }.items():
            config(host, *(project / p for p in paths))
        for folder, events in (
            (".clinerules/hooks", ("PreToolUse", "PostToolUse", "UserPromptSubmit")),
            (".kiro/hooks", ("PreToolUse", "PostToolUse", "PromptSubmit")),
        ):
            for event in events:
                for suffix in ("", ".bat", ".ps1"):
                    artifacts.append(
                        Artifact(project / folder / (event + suffix), "script")
                    )
        package(project / ".pi/extensions/ai-guardian", "ai-guardian-pi-extension")
        artifacts.append(Artifact(project / ".pi/extensions/ai-guardian.ts"))
        opencode(project / ".opencode")
        config("opencode", project / "opencode.json", project / "opencode.jsonc")
    return list(dict.fromkeys(configs)), list(dict.fromkeys(artifacts))


def safe_read(path: Path) -> tuple[bytes, os.stat_result]:
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("linked/reparse-point path retained")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("non-regular or multiply-linked file retained")
    if info.st_size > MAX_FILE_BYTES:
        raise ValueError("oversized file retained")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("file changed while opening")
        data = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
        if (info.st_mtime_ns, info.st_ctime_ns, info.st_size) != (
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_size,
        ):
            raise ValueError("file changed while reading")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("oversized file retained")
    return data, info


@dataclass
class Change:
    path: Path
    original: bytes
    replacement: bytes | None
    mode: int

    def validate(self) -> None:
        current, info = safe_read(self.path)
        if current != self.original or info.st_mode != self.mode:
            raise ValueError("file changed since preview; retained")
        if not info.st_mode & 0o222 or not self.path.parent.stat().st_mode & 0o222:
            raise PermissionError("file or directory is unwritable")

    def apply(self) -> Path:
        self.validate()
        backup = self.path.with_name(
            self.path.name + ".ai-guardian-backup-" + uuid.uuid4().hex + ".bak"
        )
        # Exclusive creation never overwrites a user's earlier backup. Backups
        # use POSIX 0600; Windows inherits the selected directory's ACL.
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(self.original)
            stream.flush()
            os.fsync(stream.fileno())
        current, _ = safe_read(self.path)
        if current != self.original:
            raise ValueError("file changed before replacement; retained")
        if self.replacement is None:
            self.path.unlink()
        else:
            temporary: str | None = None
            try:
                fd, temporary = tempfile.mkstemp(
                    prefix=".guardian-recovery-", suffix=".tmp", dir=self.path.parent
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(self.replacement)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, stat.S_IMODE(self.mode))
                os.replace(temporary, self.path)
            finally:
                if temporary is not None and os.path.exists(temporary):
                    os.unlink(temporary)
        return backup


def artifact_owned(artifact: Artifact, data: bytes) -> bool:
    text = data.decode("utf-8-sig")
    if artifact.kind == "package":
        package = load_json(text)
        return (
            isinstance(package, dict)
            and package.get("name") == artifact.package_name
            and package.get("main") == "index.ts"
        )
    if artifact.kind == "script":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) != 2 or lines[0].lower() not in {
            "#!/bin/sh",
            "#!/usr/bin/env bash",
            "@echo off",
        }:
            return False
        return owned_command(lines[1])
    return text.startswith(GENERATED)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project", "both"), default="user")
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Exact project root; repeat to select more than one",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writes or backups"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Operator confirmation for this selected scope",
    )
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error(
            "Standalone recovery requires an independent Python 3.11+ interpreter"
        )
    if (args.scope == "user" and args.project) or (
        args.scope != "user" and not args.project
    ):
        parser.error(
            "Project cleanup requires --scope project/both and an explicit --project"
        )
    if any(not value for value in args.project):
        parser.error("Each selected project requires a non-empty path")
    projects = [expanded(value) for value in args.project]
    if any(not path.is_dir() or path.is_symlink() for path in projects):
        parser.error("Each selected project must be an existing, non-symlink directory")
    configs, artifacts = inventory(args.scope, projects)
    changes: dict[Path, Change] = {}
    failures: list[tuple[Path, str]] = []
    plugins: set[Path] = set()
    print(f"Integration cleanup scope: {args.scope}")
    for project in projects:
        print(f"Selected project: {project}")
    # Establish ownership before removing registrations for local plugin files.
    for artifact in artifacts:
        try:
            data, info = safe_read(artifact.path)
            if not artifact_owned(artifact, data):
                # Shared event names and unrelated scripts are expected.
                if artifact.kind != "script":
                    failures.append((artifact.path, "unrecognized artifact retained"))
                continue
            # A manifest alone cannot authorize removing a user-owned index.
            if artifact.kind == "package":
                index = artifact.path.parent / "index.ts"
                if index.exists():
                    index_data, _ = safe_read(index)
                    if not index_data.decode("utf-8-sig").startswith(GENERATED):
                        raise ValueError("unrecognized package source retained")
            changes[artifact.path] = Change(artifact.path, data, None, info.st_mode)
            if (
                artifact.path.name == "ai-guardian.ts"
                and artifact.path.parent.name == "plugins"
            ):
                plugins.add(artifact.path)
        except FileNotFoundError:
            if (
                artifact.path.name == "ai-guardian.ts"
                and artifact.path.parent.name == "plugins"
            ):
                plugins.add(artifact.path)
            continue
        except (OSError, ValueError, UnicodeError, RecursionError):
            failures.append(
                (artifact.path, "unsafe, unreadable or malformed artifact retained")
            )
    for target in configs:
        try:
            data, info = safe_read(target.path)
            text = data.decode("utf-8-sig")
            output, problems = (
                clean_toml(text)
                if target.path.suffix.lower() == ".toml"
                else clean_json(text, target.host, plugins)
            )
            failures.extend((target.path, problem) for problem in problems)
            if output != text:
                bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
                changes[target.path] = Change(
                    target.path, data, bom + output.encode("utf-8"), info.st_mode
                )
        except FileNotFoundError:
            continue
        except (OSError, ValueError, UnicodeError, RecursionError):
            # Never print parser/exception text: host configs can contain secrets.
            failures.append(
                (
                    target.path,
                    "unsafe, unreadable, malformed or unsupported configuration retained",
                )
            )
    for path, change in list(changes.items()):
        try:
            change.validate()
        except (OSError, ValueError):
            failures.append(
                (change.path, "unsafe, changed or unwritable file retained")
            )
            del changes[path]
            continue
        print(
            f"Would {'remove' if change.replacement is None else 'edit'}: {change.path}"
        )
    if changes and not args.dry_run and not args.yes:
        try:
            answer = input("Apply integration cleanup to only this scope? [y/N] ")
        except EOFError:
            answer = ""
        if answer.lower() not in {"y", "yes"}:
            print("Cancelled; no changes made.")
            return 1
    if not args.dry_run:
        for change in changes.values():
            try:
                backup = change.apply()
                print(f"Backed up: {backup}")
            except (OSError, ValueError):
                failures.append(
                    (
                        change.path,
                        "backup or mutation failed; inspect retained original/backup",
                    )
                )
    for path, message in failures:
        print(f"Retained/failed: {path}: {message}", file=sys.stderr)
    if args.dry_run:
        print("Preview complete; no files or backups written.")
    elif failures:
        print("Integration cleanup incomplete; review retained/failed paths.")
    else:
        print("Integration cleanup complete.")
    print(
        "Restart affected hosts. AI Guardian settings and violation history were not changed."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
