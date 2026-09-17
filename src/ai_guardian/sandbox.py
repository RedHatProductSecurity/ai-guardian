"""Lifecycle management for AI Guardian container sandboxes.

The ``ai-guardian sandbox`` command is a small, runtime-neutral wrapper around
the native Docker/Podman and OpenShell CLIs.  Keeping the lifecycle operations
here means a sandbox can be created once and then stopped, started, inspected,
or connected to without re-running interactive setup.
"""

from __future__ import annotations

import os
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ai_guardian.daemon.discovery import DaemonTarget
from ai_guardian.ide_registry import SUPPORTED_CLI_IDE_TYPES

CONTAINER_RUNTIME = "container"
OPENSHELL_RUNTIME = "openshell"
SUPPORTED_RUNTIMES = (CONTAINER_RUNTIME, OPENSHELL_RUNTIME)

DEFAULT_CONTAINER_ENGINE = "podman"
DEFAULT_CONTAINER_IMAGE = "quay.io/redhatproductsecurity/ai-guardian:latest"
DEFAULT_OPENSHELL_IMAGE = "quay.io/redhatproductsecurity/ai-guardian-openshell:latest"
DEFAULT_CONTAINER_CLI = "codex"
DEFAULT_OPENSHELL_CLI = "claude"
DEFAULT_REST_PORT = "63152"
DEFAULT_OPENSHELL_MODEL = "claude-sonnet-4-6"
MANAGED_LABEL = "ai-guardian.managed=true"
DAEMON_LABEL = "ai-guardian.daemon=true"
MANAGED_LABEL_KEY = "ai-guardian.managed"
RUNTIME_LABEL_KEY = "ai-guardian.runtime"
DAEMON_LABEL_KEY = "ai-guardian.daemon"
OPENSHELL_ENTRYPOINT = "/usr/local/bin/entrypoint.sh"
OPENSHELL_SERVICE_NAME = "ai-guardian"
CONTAINER_GOOGLE_CREDENTIALS_PATH = (
    "/sandbox/.config/gcloud/application_default_credentials.json"
)
# Host configuration is staged outside the active sandbox config directory so
# an existing sandbox-local config can win over it at container startup.
CONTAINER_HOST_CONFIG_PATH = "/sandbox/.config/ai-guardian.host.json"
SANDBOX_CONFIG_STATE_DIRNAME = "sandboxes"
SANDBOX_CONFIG_FILENAME = "ai-guardian.json"
SANDBOX_CONFIG_METADATA_FILENAME = "metadata.json"

_OPENSHELL_BASE_POLICY_ENV = "AI_GUARDIAN_OPEN_SHELL_BASE_POLICY"
_OPENSHELL_AGENT_POLICY_DIR_ENV = "AI_GUARDIAN_OPEN_SHELL_AGENT_POLICY_DIR"

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OPENSHELL_SERVICE_URL_RE = re.compile(r"https?://[^\s<>\[\]{}\"']+")

logger = logging.getLogger(__name__)

_KNOWN_CREDENTIAL_ENVIRONMENT = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "COPILOT_GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "GITLAB_HOST",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "ACCEPT_PROPRIETARY_TOS",
)


def _requested_runtime(args) -> Optional[str]:
    """Return an explicitly selected runtime, if one was provided."""
    selected = (
        getattr(args, "runtime", None)
        or os.environ.get("AI_GUARDIAN_SANDBOX_RUNTIME")
        or None
    )
    if selected is None:
        return None
    if selected not in SUPPORTED_RUNTIMES:
        raise ValueError(
            f"unsupported sandbox runtime '{selected}'; "
            f"choose one of: {', '.join(SUPPORTED_RUNTIMES)}"
        )
    return selected


def _runtime(args) -> str:
    """Resolve the selected runtime, defaulting creation to OpenShell."""
    return _requested_runtime(args) or OPENSHELL_RUNTIME


def _container_engine(args) -> str:
    return (
        getattr(args, "container_engine", None)
        or os.environ.get("CONTAINER_ENGINE")
        or DEFAULT_CONTAINER_ENGINE
    )


def _container_engine_candidates(args) -> Tuple[str, ...]:
    """Return engines to probe when lifecycle selection is automatic."""
    selected = getattr(args, "container_engine", None) or os.environ.get(
        "CONTAINER_ENGINE"
    )
    if selected:
        return (selected,)
    return tuple(dict.fromkeys((DEFAULT_CONTAINER_ENGINE, "docker")))


def _container_runtime_name(args, name: str) -> str:
    """Return the native container name for a logical sandbox target."""
    return getattr(args, "container_name", None) or name


def _openshell_cli(args) -> str:
    return getattr(args, "openshell_cli", None) or os.environ.get(
        "OPENSHELL_CLI", "openshell"
    )


def _runtime_executable(args, runtime: str) -> str:
    """Return the native executable used by a sandbox runtime."""
    if runtime == CONTAINER_RUNTIME:
        return _container_engine(args)
    if runtime == OPENSHELL_RUNTIME:
        return _openshell_cli(args)
    raise ValueError(f"unsupported sandbox runtime: {runtime}")


def _missing_runtime_executable(args, runtime: str) -> Optional[str]:
    """Return a missing runtime executable, if one is not on ``PATH``."""
    if runtime == CONTAINER_RUNTIME:
        executables = _container_engine_candidates(args)
    else:
        executables = (_runtime_executable(args, runtime),)
    missing = [
        executable for executable in executables if shutil.which(executable) is None
    ]
    if len(missing) == len(executables):
        return ", ".join(missing)
    return None


def _command_args(args) -> List[str]:
    """Return arguments after an optional argparse ``--`` separator."""
    command = list(getattr(args, "command_args", None) or [])
    if command and command[0] == "--":
        return command[1:]
    return command


def _selected_cli(args, default: str) -> str:
    """Resolve the CLI executable selected for a sandbox."""
    return str(
        getattr(args, "cli", None) or os.environ.get("AI_GUARDIAN_CLI") or default
    ).strip()


def _opencode_agent(args, cli: str) -> Optional[str]:
    """Return the OpenCode agent profile selected for the CLI."""
    if cli != "opencode":
        return None

    selected = getattr(args, "opencode_agent", None)
    return (
        str(selected or os.environ.get("AI_GUARDIAN_OPENCODE_AGENT") or "").strip()
        or None
    )


def _openshell_inference_cli(args, cli: str) -> str:
    """Return the model client whose OpenShell inference route is requested."""
    if cli == "claude":
        return "claude"
    if cli != "opencode":
        return cli

    opencode_agent = _opencode_agent(args, cli)
    requested_model = getattr(args, "model", None) or os.environ.get(
        "AI_GUARDIAN_OPEN_SHELL_MODEL", DEFAULT_OPENSHELL_MODEL
    )
    # OpenCode's ``--agent`` is normally a user-defined profile, not a
    # provider. Treat the conventional ``claude`` profile name, the default
    # Claude model, or an explicitly Claude-named inference model as a request
    # for the Anthropic-compatible OpenShell route. Generic OpenCode providers
    # remain untouched when a non-Claude model is selected.
    if opencode_agent == "claude" or "claude" in str(requested_model).lower():
        return "claude"
    return cli


def _openshell_explicit_command(args) -> List[str]:
    """Apply OpenShell-specific flags to an explicit CLI command.

    OpenShell's documented interactive flow keeps ``--bare`` explicit. The
    create command's trailing command is executed through ``sandbox exec``
    after bootstrap, so it does not pass through the image entrypoint. Preserve
    the non-interactive automation behavior here without installing a shell
    wrapper. When ``--cli opencode --agent NAME`` is used, pass the selected
    OpenCode profile to an explicit ``opencode`` command.
    """
    command = _command_args(args)
    cli = _selected_cli(args, DEFAULT_OPENSHELL_CLI)
    if not command:
        return command

    executable = Path(str(command[0])).name
    if cli == "opencode" and executable == "opencode":
        opencode_agent = _opencode_agent(args, cli)
        administrative_commands = {
            "agent",
            "auth",
            "debug",
            "export",
            "github",
            "import",
            "mcp",
            "models",
            "serve",
            "session",
            "stats",
            "upgrade",
            "web",
            "--help",
            "-h",
            "--version",
        }
        if (
            opencode_agent
            and (not command[1:2] or command[1] not in administrative_commands)
            and "--agent" not in command
        ):
            return [command[0], "--agent", opencode_agent, *command[1:]]
        return command

    if cli != "claude" or executable != "claude":
        return command

    administrative_commands = {
        "auth",
        "config",
        "doctor",
        "help",
        "install",
        "mcp",
        "plugin",
        "update",
        "version",
        "--help",
        "-h",
        "--version",
        "-V",
    }
    if command[1:2] and command[1] in administrative_commands:
        return command
    if "--bare" in command or "--print" not in command:
        return command
    return [command[0], "--bare", *command[1:]]


def _image_for_runtime(args, runtime: str) -> str:
    """Resolve the selected image while preserving an explicit form value."""
    explicit = str(getattr(args, "image", None) or "").strip()
    if explicit:
        return explicit
    if runtime == CONTAINER_RUNTIME:
        return os.environ.get("AI_GUARDIAN_IMAGE", DEFAULT_CONTAINER_IMAGE)
    return os.environ.get(
        "AI_GUARDIAN_IMAGE",
        os.environ.get("AI_GUARDIAN_OPEN_SHELL_IMAGE", DEFAULT_OPENSHELL_IMAGE),
    )


def _validate_image_reference(image: Optional[str]) -> None:
    """Reject the common two-colon image typo before invoking a runtime.

    A single colon in an unqualified image is a tag (``image:tag``).  A colon
    before the repository path is a registry port and must be numeric
    (``localhost:5000/image:tag``).  This catches values such as
    ``localhost:ai-guardian:openshell`` instead of letting a runtime resolve
    or report them ambiguously.
    """
    value = str(image or "").strip()
    if not value:
        return

    first_component = value.split("/", 1)[0]
    if "/" not in value:
        if value.count(":") > 1:
            raise ValueError(
                f"invalid image reference '{value}'; use registry/name:tag, "
                "for example localhost/ai-guardian-openshell:dev"
            )
        return

    if ":" in first_component:
        port = first_component.rsplit(":", 1)[1]
        if not port.isdigit():
            raise ValueError(
                f"invalid image reference '{value}'; a registry port must be "
                "numeric, for example localhost:5000/image:tag"
            )


def _record_output(output: Optional[List[str]], text) -> None:
    """Append subprocess output to an optional programmatic log buffer."""
    if output is None or text is None:
        return
    if not isinstance(text, str):
        text = str(text)
    if text:
        output.append(text)


def _emit_output(
    message: str, *, output: Optional[List[str]] = None, error: bool = False
) -> None:
    """Write a command message to the CLI or an in-process log buffer."""
    if output is not None:
        output.append(f"{message}\n")
        return
    print(message, file=sys.stderr if error else sys.stdout)


def _run(
    command: Sequence[str],
    env: Optional[Dict[str, str]] = None,
    *,
    output: Optional[List[str]] = None,
) -> int:
    """Run a native runtime command, optionally capturing its output."""
    try:
        if output is None:
            result = subprocess.run(list(command), env=env, check=False)
        else:
            result = subprocess.run(
                list(command),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            _record_output(output, result.stdout)
            _record_output(output, result.stderr)
    except FileNotFoundError:
        _emit_output(
            f"Error: required executable was not found: {command[0]}",
            output=output,
            error=True,
        )
        return 127
    except OSError as exc:
        _emit_output(f"Error running {command[0]}: {exc}", output=output, error=True)
        return 1
    return result.returncode


def _run_capture(
    command: Sequence[str], *, timeout: float = 10
) -> Optional[subprocess.CompletedProcess]:
    """Run a runtime probe without forwarding its output to the user."""
    try:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _sandbox_name_exists(args, runtime: str, name: str) -> bool:
    """Return whether a native runtime resource already uses ``name``."""
    if runtime == CONTAINER_RUNTIME:
        command = [_container_engine(args), "inspect", name]
    elif runtime == OPENSHELL_RUNTIME:
        command = [_openshell_cli(args), "sandbox", "get", name, "--output", "json"]
    else:
        raise ValueError(f"unsupported sandbox runtime: {runtime}")

    result = _run_capture(command)
    return bool(result and result.returncode == 0)


def _is_ai_guardian_labels(labels) -> bool:
    """Return whether runtime metadata identifies an AI Guardian resource."""
    if not isinstance(labels, dict):
        return False
    return (
        labels.get(MANAGED_LABEL_KEY) == "true"
        or labels.get(DAEMON_LABEL_KEY) == "true"
        or labels.get(RUNTIME_LABEL_KEY) in SUPPORTED_RUNTIMES
    )


def _container_is_ai_guardian(args, name: str, *, engine: Optional[str] = None) -> bool:
    """Check an exact container name without printing a probe error."""
    result = _run_capture(
        [
            engine or _container_engine(args),
            "inspect",
            _container_runtime_name(args, name),
        ]
    )
    if not result or result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, json.JSONDecodeError):
        return False

    records = payload if isinstance(payload, list) else [payload]
    for record in records:
        if not isinstance(record, dict):
            continue
        config = record.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if labels is None:
            labels = record.get("Labels")
        if _is_ai_guardian_labels(labels):
            return True
    return False


def _openshell_is_ai_guardian(args, name: str) -> bool:
    """Check an exact OpenShell sandbox name without printing probe errors."""
    result = _run_capture(
        [_openshell_cli(args), "sandbox", "get", name, "--output", "json"]
    )
    if not result or result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return _is_ai_guardian_labels(payload.get("labels") or payload.get("Labels"))


def _resolve_lifecycle_runtime(args, operation: str) -> Optional[str]:
    """Resolve a lifecycle runtime from an option or resource metadata."""
    requested = _requested_runtime(args)
    if requested:
        return requested

    if operation == "list":
        return None

    name = getattr(args, "name", None)
    if not name:
        raise ValueError(
            f"sandbox name is required to auto-detect the runtime for {operation}"
        )

    matches = []
    container_matches = [
        engine
        for engine in _container_engine_candidates(args)
        if _container_is_ai_guardian(args, name, engine=engine)
    ]
    if len(container_matches) > 1:
        raise ValueError(
            f"multiple AI Guardian container sandboxes named '{name}' were found; "
            "specify --container-engine"
        )
    container_match = bool(container_matches)
    if container_match:
        args.container_engine = container_matches[0]
    openshell_match = _openshell_is_ai_guardian(args, name)
    missing_executables = []
    if container_match:
        matches.append(CONTAINER_RUNTIME)
    if openshell_match:
        matches.append(OPENSHELL_RUNTIME)
    for runtime, matched in (
        (CONTAINER_RUNTIME, container_match),
        (OPENSHELL_RUNTIME, openshell_match),
    ):
        if not matched:
            executable = _missing_runtime_executable(args, runtime)
            if executable:
                missing_executables.append(f"{runtime} ({executable})")

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"multiple AI Guardian sandboxes named '{name}' were found; "
            "specify --runtime"
        )
    if missing_executables:
        raise ValueError(
            f"could not auto-detect runtime for sandbox '{name}'; "
            "required executable(s) not found: " + ", ".join(missing_executables)
        )
    raise ValueError(
        f"AI Guardian sandbox '{name}' was not found; "
        "specify --runtime for an unmanaged resource"
    )


def _parse_json_lines(output: str):
    """Parse either one JSON document or newline-delimited JSON."""
    try:
        return json.loads(output)
    except (TypeError, json.JSONDecodeError):
        records = []
        for line in (output or "").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records


def _run_all_lifecycle_lists(args, *, output: Optional[List[str]] = None) -> int:
    """List managed sandboxes from both runtimes when no runtime is given."""
    successes = []
    failures = []
    for runtime in SUPPORTED_RUNTIMES:
        result = _run_capture(_lifecycle_command(args, "list", runtime=runtime))
        if result is None:
            executable = _missing_runtime_executable(args, runtime)
            if executable:
                detail = f"required executable was not found: {executable}"
            else:
                detail = "runtime command was unavailable or timed out"
            failures.append((runtime, detail))
        elif result.returncode == 0:
            successes.append((runtime, result))
        else:
            failures.append((runtime, (result.stderr or "").strip()))

    if not successes:
        _emit_output(
            "Error: unable to list AI Guardian sandboxes in any supported runtime.",
            output=output,
            error=True,
        )
        for runtime, detail in failures:
            if detail:
                _emit_output(f"{runtime}: {detail}", output=output, error=True)
        return 1

    for runtime, detail in failures:
        if detail:
            _emit_output(f"Warning: {runtime}: {detail}", output=output, error=True)

    if getattr(args, "json_output", False):
        payload = {
            runtime: _parse_json_lines(result.stdout or "")
            for runtime, result in successes
        }
        _emit_output(json.dumps(payload, indent=2), output=output)
        return 0

    for index, (runtime, result) in enumerate(successes):
        if index:
            _emit_output("", output=output)
        if len(successes) > 1:
            _emit_output(f"{runtime} sandboxes:", output=output)
        if result.stderr:
            if output is None:
                print(result.stderr, end="")
            else:
                _record_output(output, result.stderr)
        if result.stdout:
            if output is None:
                print(result.stdout, end="")
            else:
                _record_output(output, result.stdout)
    return 0


def _config_dir(args) -> Path:
    configured = getattr(args, "config_dir", None)
    if configured:
        return Path(configured).expanduser()

    for environment_name in ("AI_GUARDIAN_CONFIG_DIR", "AI_GUARDIAN_HOME"):
        value = os.environ.get(environment_name)
        if value:
            return Path(value).expanduser()

    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]).expanduser() / "ai-guardian"
    return Path.home() / ".config" / "ai-guardian"


def _sandbox_config_state_root() -> Path:
    """Return the host directory containing sandbox config snapshots."""
    from ai_guardian.config.utils import get_state_dir

    return get_state_dir() / SANDBOX_CONFIG_STATE_DIRNAME


def _safe_sandbox_name(name: str) -> str:
    """Convert a logical sandbox name into a safe state-directory component."""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name).strip(".")
    return safe_name or "sandbox"


def _sandbox_config_snapshot_root(name: str) -> Path:
    """Return the snapshot directory for a logical sandbox name."""
    return _sandbox_config_state_root() / _safe_sandbox_name(name)


def _atomic_write_json(path: Path, value: dict) -> None:
    """Write a JSON object atomically with user-only permissions."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass  # intentionally silent — cleanup of temporary state
        raise


def _snapshot_candidates(name: str, runtime: Optional[str] = None) -> List[Path]:
    """Return valid snapshots, optionally limited to one runtime."""
    snapshot_root = _sandbox_config_snapshot_root(name)
    try:
        candidates = [
            path / SANDBOX_CONFIG_FILENAME
            for path in snapshot_root.iterdir()
            if path.is_dir() and (path / SANDBOX_CONFIG_FILENAME).is_file()
        ]
    except OSError:
        return []
    if runtime:
        candidates = [
            path
            for path in candidates
            if (
                not _snapshot_metadata(path).get("runtime")
                or _snapshot_metadata(path).get("runtime") == runtime
            )
        ]
    return sorted(candidates, key=lambda path: path.parent.name, reverse=True)


def _snapshot_metadata(snapshot_path: Path) -> dict:
    """Read optional metadata for a configuration snapshot."""
    metadata_path = snapshot_path.parent / SANDBOX_CONFIG_METADATA_FILENAME
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _load_snapshot_config(
    name: str, selector: str = "latest", runtime: Optional[str] = None
) -> Tuple[Path, dict]:
    """Load a saved snapshot selected by ``latest`` or timestamp."""
    if selector == "latest":
        candidates = _snapshot_candidates(name, runtime)
        snapshot_path = candidates[0] if candidates else None
    else:
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}\.[0-9]{6}Z(?:-[0-9]+)?", str(selector)):
            raise ValueError(
                "snapshot must be 'latest' or a timestamp returned by "
                "'ai-guardian sandbox config list'"
            )
        snapshot_path = (
            _sandbox_config_snapshot_root(name) / selector / SANDBOX_CONFIG_FILENAME
        )
        if snapshot_path.is_file() and runtime:
            stored_runtime = _snapshot_metadata(snapshot_path).get("runtime")
            if stored_runtime and stored_runtime != runtime:
                snapshot_path = None
        if snapshot_path is not None and not snapshot_path.is_file():
            snapshot_path = None

    if snapshot_path is None:
        raise ValueError(
            f"no configuration snapshot found for sandbox '{name}'; "
            "run 'ai-guardian sandbox config save' first"
        )

    try:
        config = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"unable to read sandbox config snapshot: {snapshot_path}"
        ) from exc
    if not isinstance(config, dict):
        raise ValueError(
            f"sandbox config snapshot is not a JSON object: {snapshot_path}"
        )
    return snapshot_path, config


def _write_sandbox_config_snapshot(name: str, runtime: str, config: dict) -> Path:
    """Persist a daemon configuration as a timestamped host snapshot."""
    saved_at = datetime.now(timezone.utc)
    timestamp = saved_at.strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot_root = _sandbox_config_snapshot_root(name)
    snapshot_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot_dir = snapshot_root / timestamp
    suffix = 1
    while snapshot_dir.exists():
        snapshot_dir = snapshot_root / f"{timestamp}-{suffix}"
        suffix += 1
    snapshot_dir.mkdir(mode=0o700)

    config_path = snapshot_dir / SANDBOX_CONFIG_FILENAME
    _atomic_write_json(config_path, config)
    _atomic_write_json(
        snapshot_dir / SANDBOX_CONFIG_METADATA_FILENAME,
        {
            "sandbox_name": name,
            "runtime": runtime,
            "saved_at": saved_at.isoformat().replace("+00:00", "Z"),
        },
    )
    return config_path


def _list_sandbox_config_snapshots(
    name: Optional[str] = None, runtime: Optional[str] = None
) -> List[dict]:
    """Return saved snapshot metadata, newest snapshots first."""
    if name:
        snapshot_roots = [_sandbox_config_snapshot_root(name)]
    else:
        try:
            snapshot_roots = [
                path for path in _sandbox_config_state_root().iterdir() if path.is_dir()
            ]
        except OSError:
            snapshot_roots = []

    records = []
    for snapshot_root in snapshot_roots:
        discovered_name = name or snapshot_root.name
        for snapshot_path in _snapshot_candidates(discovered_name, runtime):
            metadata = _snapshot_metadata(snapshot_path)
            records.append(
                {
                    "sandbox_name": metadata.get("sandbox_name", discovered_name),
                    "runtime": metadata.get("runtime", "unknown"),
                    "saved_at": metadata.get("saved_at", snapshot_path.parent.name),
                    "snapshot": str(snapshot_path),
                }
            )
    return sorted(records, key=lambda record: record["snapshot"], reverse=True)


def _initial_config_source(args) -> Optional[Path]:
    """Return the host-side file to seed a new sandbox configuration from."""
    restore_selector = getattr(args, "restore_config", None)
    if restore_selector:
        name = getattr(args, "name", None)
        if not name:
            raise ValueError("--name is required with --restore-config")
        snapshot_path, _config = _load_snapshot_config(
            name,
            restore_selector,
            runtime=_requested_runtime(args) or _runtime(args),
        )
        return snapshot_path

    config_path = _config_dir(args) / SANDBOX_CONFIG_FILENAME
    return config_path if config_path.is_file() else None


def _path_like_profile(profile: str) -> bool:
    return profile.startswith(("/", "./", "../")) or os.sep in profile


def _profile_source(
    profile: Optional[str], config_dir: Path
) -> Tuple[Optional[Path], str]:
    """Resolve a custom profile file and its sandbox-relative destination."""
    if not profile or profile.startswith("@"):
        return None, profile or ""

    if _path_like_profile(profile):
        source = Path(profile).expanduser()
    else:
        source = config_dir / "profiles" / profile
        if source.suffix != ".json":
            source = source.with_suffix(".json")

    if not source.is_file():
        raise ValueError(f"custom profile file not found: {source}")
    return source, f"/sandbox/.config/ai-guardian/profiles/{source.name}"


def _add_container_environment(
    command: List[str], args, *, child_env: Dict[str, str]
) -> None:
    """Add non-secret setup values and pass selected host credentials through."""
    cli = _selected_cli(args, DEFAULT_CONTAINER_CLI)
    values = [
        f"AI_GUARDIAN_AGENT={cli}",
        f"AI_GUARDIAN_IDE={cli}",
        f"AI_GUARDIAN_REST_PORT={DEFAULT_REST_PORT}",
        "AI_GUARDIAN_CONFIG_DIR=/sandbox/.config/ai-guardian",
        "AI_GUARDIAN_HOME=/sandbox/.config/ai-guardian",
        f"AI_GUARDIAN_SETUP_SCOPE={os.environ.get('AI_GUARDIAN_SETUP_SCOPE', 'selected')}",
    ]
    opencode_agent = _opencode_agent(args, cli)
    if opencode_agent:
        values.append(f"AI_GUARDIAN_OPENCODE_AGENT={opencode_agent}")
    explicit_api_key = getattr(args, "api_key", None)
    vertex_project = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or os.environ.get(
        "VERTEX_AI_PROJECT_ID"
    )
    use_vertex = cli == "claude" and bool(vertex_project) and not explicit_api_key
    for value in values:
        command.extend(["--env", value])

    # Let the runtime read host credentials from the child environment instead
    # of putting their values in the engine command line.
    for name in _KNOWN_CREDENTIAL_ENVIRONMENT:
        if name == "ANTHROPIC_API_KEY" and use_vertex:
            continue
        if os.environ.get(name):
            command.extend(["--env", name])

    api_key = explicit_api_key or (
        os.environ.get("ANTHROPIC_API_KEY") if not use_vertex else None
    )
    if api_key:
        child_env["ANTHROPIC_API_KEY"] = api_key
        command.extend(["--env", "ANTHROPIC_API_KEY"])

    if use_vertex:
        vertex_region = os.environ.get("CLOUD_ML_REGION") or os.environ.get(
            "VERTEX_AI_REGION", "global"
        )
        command.extend(
            [
                "--env",
                "CLAUDE_CODE_USE_VERTEX=1",
                "--env",
                f"ANTHROPIC_VERTEX_PROJECT_ID={vertex_project}",
                "--env",
                f"CLOUD_ML_REGION={vertex_region}",
            ]
        )
        adc_path = _container_google_adc_path()
        if adc_path and adc_path.is_file():
            command.extend(
                [
                    "--env",
                    f"GOOGLE_APPLICATION_CREDENTIALS={CONTAINER_GOOGLE_CREDENTIALS_PATH}",
                    "--volume",
                    f"{adc_path}:{CONTAINER_GOOGLE_CREDENTIALS_PATH}:ro,z",
                ]
            )
        else:
            logger.warning(
                "Vertex AI is configured for the container, but Google ADC "
                "credentials were not found; run 'gcloud auth "
                "application-default login' or set GOOGLE_APPLICATION_CREDENTIALS"
            )

    for value in getattr(args, "environment", None) or []:
        command.extend(["--env", value])


def _container_google_adc_path() -> Optional[Path]:
    """Return the host Google ADC path used by a container sandbox."""
    configured = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if configured:
        return Path(configured).expanduser()

    candidates = [
        Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.insert(
            0,
            Path(appdata) / "gcloud" / "application_default_credentials.json",
        )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _openshell_asset_roots() -> List[Path]:
    """Return source-tree and installed locations for OpenShell assets."""
    repository_root = Path(__file__).resolve().parents[2] / "container"
    installed_root = Path(__file__).resolve().parent / "sandbox_assets"
    return [repository_root, installed_root]


def _openshell_policy_assets(args, cli: str) -> Tuple[Path, Path]:
    """Resolve the baseline and selected-CLI OpenShell policy fragments."""
    base_override = os.environ.get(_OPENSHELL_BASE_POLICY_ENV)
    cli_policy_dir = os.environ.get(_OPENSHELL_AGENT_POLICY_DIR_ENV)
    roots = _openshell_asset_roots()

    if base_override:
        base_path = Path(base_override).expanduser()
    else:
        base_path = next(
            (
                root / "policies" / "base.yaml"
                for root in roots
                if (root / "policies" / "base.yaml").is_file()
            ),
            roots[0] / "policies" / "base.yaml",
        )

    if cli_policy_dir:
        cli_path = Path(cli_policy_dir).expanduser() / f"{cli}.yaml"
    else:
        cli_path = next(
            (
                root / "policies" / "agents" / f"{cli}.yaml"
                for root in roots
                if (root / "policies" / "agents" / f"{cli}.yaml").is_file()
            ),
            roots[0] / "policies" / "agents" / f"{cli}.yaml",
        )

    if not base_path.is_file():
        raise ValueError(f"OpenShell base policy not found: {base_path}")
    if not cli_path.is_file():
        raise ValueError(
            f"OpenShell policy fragment not found for CLI '{cli}': {cli_path}"
        )
    return base_path, cli_path


def _load_openshell_policy(path: Path) -> Dict[str, Any]:
    """Load one YAML OpenShell policy fragment as a mapping."""
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(
            f"cannot read OpenShell policy fragment {path}: {exc}"
        ) from exc
    except UnicodeError as exc:
        raise ValueError(
            f"cannot decode OpenShell policy fragment {path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"invalid YAML in OpenShell policy fragment {path}: {exc}"
        ) from exc

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(
            f"OpenShell policy fragment {path} must contain a YAML mapping"
        )
    return value


def _merge_openshell_policy_values(base: Any, overlay: Any) -> Any:
    """Deep-merge policy mappings while replacing scalar and list values."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = (
                _merge_openshell_policy_values(merged[key], value)
                if key in merged
                else value
            )
        return merged
    return overlay


def _compose_openshell_policy(args, cli: str) -> Tuple[Path, Path]:
    """Compose the baseline, user overlays, and selected-CLI policy."""
    import yaml

    base_path, cli_path = _openshell_policy_assets(args, cli)
    overlay_paths = [
        Path(value).expanduser() for value in getattr(args, "policy", None) or []
    ]
    for policy_path in overlay_paths:
        if not policy_path.is_file():
            raise ValueError(f"OpenShell policy file not found: {policy_path}")

    policy: Dict[str, Any] = {}
    for path in [base_path, *overlay_paths, cli_path]:
        policy = _merge_openshell_policy_values(policy, _load_openshell_policy(path))
    policy.setdefault("version", 1)
    if policy["version"] != 1:
        raise ValueError("OpenShell policy version must be 1")
    network_policies = policy.get("network_policies")
    if network_policies is not None and not isinstance(network_policies, dict):
        raise ValueError("network_policies must be a YAML mapping")

    try:
        temporary_dir = Path(
            tempfile.mkdtemp(
                prefix="ai-guardian-openshell-policy.",
                dir=os.environ.get("TMPDIR") or None,
            )
        )
    except OSError as exc:
        raise ValueError(
            f"unable to create a temporary directory for the OpenShell policy: {exc}"
        ) from exc
    policy_path = temporary_dir / "policy.yaml"
    try:
        policy_path.write_text(
            yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
        )
        os.chmod(policy_path, 0o600)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise ValueError(f"unable to compose OpenShell policy: {exc}") from exc
    return policy_path, temporary_dir


def _openshell_host_home() -> Path:
    """Return the host home used for provider credential discovery."""
    configured = os.environ.get("HOME")
    return Path(configured).expanduser() if configured else Path.home()


def _openshell_environment_values(args) -> Dict[str, str]:
    """Parse explicit KEY=VALUE values for provider discovery as well."""
    values = {}
    for raw_value in getattr(args, "environment", None) or []:
        key, separator, value = str(raw_value).partition("=")
        if separator and key:
            values[key] = value
    return values


def _openshell_provider_environment(args, cli: str) -> Dict[str, str]:
    """Build a temporary provider-process environment without command leaks."""
    environment = os.environ.copy()
    environment.update(_openshell_environment_values(args))

    api_key = getattr(args, "api_key", None)
    if api_key and cli == "claude" and not environment.get("ANTHROPIC_API_KEY"):
        environment["ANTHROPIC_API_KEY"] = api_key

    if cli == "codex":
        codex_home = Path(
            environment.get("CODEX_HOME", _openshell_host_home() / ".codex")
        )
        auth_path = codex_home / "auth.json"
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            auth = {}
        auth_api_key = auth.get("OPENAI_API_KEY") if isinstance(auth, dict) else None
        if (
            isinstance(auth_api_key, str)
            and auth_api_key
            and not environment.get("OPENAI_API_KEY")
        ):
            environment["OPENAI_API_KEY"] = auth_api_key
        tokens = auth.get("tokens", {}) if isinstance(auth, dict) else {}
        if isinstance(tokens, dict):
            for token_key, environment_name in (
                ("access_token", "CODEX_AUTH_ACCESS_TOKEN"),
                ("refresh_token", "CODEX_AUTH_REFRESH_TOKEN"),
                ("account_id", "CODEX_AUTH_ACCOUNT_ID"),
                ("id_token", "CODEX_AUTH_ID_TOKEN"),
            ):
                if not environment.get(environment_name) and tokens.get(token_key):
                    environment[environment_name] = str(tokens[token_key])
    return environment


def _openshell_provider_profiles(args) -> List[str]:
    """Return provider profile IDs advertised by the active gateway."""
    result = _run_capture(
        [_openshell_cli(args), "provider", "list-profiles", "--output", "json"]
    )
    if not result or result.returncode != 0:
        return []
    payload = _parse_json_lines(result.stdout or "")
    records = payload
    if isinstance(payload, dict):
        records = payload.get("profiles") or payload.get("provider_profiles") or []
    if not isinstance(records, list):
        return []
    profile_ids = []
    for record in records:
        if isinstance(record, str):
            profile_ids.append(record)
        elif isinstance(record, dict):
            profile_id = record.get("id") or record.get("name")
            if profile_id:
                profile_ids.append(str(profile_id))
    return profile_ids


def _openshell_provider_exists(args, name: str) -> bool:
    """Return whether a provider instance exists on the active gateway."""
    result = _run_capture([_openshell_cli(args), "provider", "get", name])
    return bool(result and result.returncode == 0)


def _openshell_providers_v2_enabled(args) -> Optional[bool]:
    """Return the gateway Providers v2 setting, or ``None`` if unavailable."""
    result = _run_capture(
        [_openshell_cli(args), "settings", "get", "--global", "--json"]
    )
    if not result or result.returncode != 0:
        return None
    payload = _parse_json_lines(result.stdout or "")
    if not isinstance(payload, dict):
        return None
    settings = payload.get("settings", payload)
    if not isinstance(settings, dict):
        return None
    value = settings.get("providers_v2_enabled")
    if isinstance(value, str):
        return value.lower() == "true"
    return value if isinstance(value, bool) else None


def _ensure_openshell_cli_provider(
    args, cli: str, *, output: Optional[List[str]] = None
) -> str:
    """Create or reuse the default provider needed by staged CLI setup."""
    if cli not in {"claude", "codex", "copilot", "opencode"}:
        raise ValueError(
            f"the active OpenShell gateway has no automatic provider mapping for '{cli}'; "
            "create a compatible provider and pass it with --provider NAME"
        )

    profiles = _openshell_provider_profiles(args)
    provider_type = (
        "claude-code" if cli == "claude" and "claude-code" in profiles else cli
    )
    if cli == "claude" and provider_type == "claude" and "claude" not in profiles:
        raise ValueError(
            "the active OpenShell gateway has no provider profile for 'claude'; "
            "create a compatible provider and pass it with --provider NAME"
        )
    if provider_type not in profiles:
        raise ValueError(
            f"the active OpenShell gateway has no provider profile for '{cli}'; "
            "create a compatible provider and pass it with --provider NAME"
        )

    provider_name = f"ai-guardian-{cli}"
    if _openshell_provider_exists(args, provider_name):
        _emit_output(
            f"Using existing OpenShell provider: {provider_name}", output=output
        )
        return provider_name

    if cli == "codex" and not os.environ.get("OPENAI_API_KEY"):
        codex_home = Path(
            os.environ.get("CODEX_HOME", _openshell_host_home() / ".codex")
        )
        auth_path = codex_home / "auth.json"
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            auth = {}
        tokens = auth.get("tokens", {}) if isinstance(auth, dict) else {}
        if isinstance(tokens, dict) and tokens.get("access_token"):
            if _openshell_providers_v2_enabled(args) is False:
                raise ValueError(
                    "Codex OAuth credentials were found, but OpenShell Providers v2 is "
                    "disabled on the active gateway. Enable it with: openshell settings "
                    "set --global --key providers_v2_enabled --value true"
                )

    _emit_output(
        f"Creating OpenShell provider from existing local credentials: {provider_name}",
        output=output,
    )
    provider_environment = _openshell_provider_environment(args, cli)
    provider_command = [
        _openshell_cli(args),
        "provider",
        "create",
        "--name",
        provider_name,
        "--type",
        provider_type,
    ]
    if cli == "codex" and provider_environment.get("OPENAI_API_KEY"):
        # OpenShell's Codex --from-existing discovery only recognizes the
        # OAuth credential set. API-key auth must use the environment-key
        # credential form instead; the key value stays out of argv.
        provider_command.extend(["--credential", "OPENAI_API_KEY"])
    else:
        provider_command.append("--from-existing")
    result = _run(
        provider_command,
        env=provider_environment,
        output=output,
    )
    if result != 0:
        raise ValueError(
            f"unable to create OpenShell provider '{provider_name}'; "
            "create a compatible provider and pass it with --provider NAME"
        )
    return provider_name


def _vertex_settings(args) -> Tuple[str, str, str]:
    """Return Vertex project, region, and inference model settings."""
    project = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or os.environ.get(
        "VERTEX_AI_PROJECT_ID", ""
    )
    region = os.environ.get("CLOUD_ML_REGION") or os.environ.get(
        "VERTEX_AI_REGION", "global"
    )
    model = getattr(args, "model", None) or os.environ.get(
        "AI_GUARDIAN_OPEN_SHELL_MODEL", DEFAULT_OPENSHELL_MODEL
    )
    return project, region, model


def _configure_openshell_vertex_provider(
    args, provider_name: str, project: str, region: str, *, output=None
) -> None:
    """Update the project and region used by a Vertex provider."""
    result = _run(
        [
            _openshell_cli(args),
            "provider",
            "update",
            provider_name,
            "--config",
            f"VERTEX_AI_PROJECT_ID={project}",
            "--config",
            f"VERTEX_AI_REGION={region}",
        ],
        output=output,
    )
    if result != 0:
        raise ValueError(
            f"unable to configure OpenShell Vertex AI provider '{provider_name}'; "
            "the provider requires VERTEX_AI_PROJECT_ID and VERTEX_AI_REGION"
        )


def _ensure_openshell_vertex_provider(
    args, project: str, region: str, *, output=None
) -> str:
    """Create or reuse the gateway provider used by Claude Vertex inference."""
    profiles = _openshell_provider_profiles(args)
    if "google-vertex-ai" not in profiles:
        raise ValueError(
            "the active OpenShell gateway has no provider profile for 'google-vertex-ai'; "
            "create a compatible provider and pass it with --provider NAME"
        )

    provider_name = "ai-guardian-google-vertex-ai"
    if _openshell_provider_exists(args, provider_name):
        _emit_output(
            f"Using existing OpenShell provider: {provider_name}", output=output
        )
        _configure_openshell_vertex_provider(
            args, provider_name, project, region, output=output
        )
        return provider_name

    provider_environment = _openshell_provider_environment(args, "claude")
    adc_path = Path(
        provider_environment.get(
            "GOOGLE_APPLICATION_CREDENTIALS",
            _openshell_host_home()
            / ".config"
            / "gcloud"
            / "application_default_credentials.json",
        )
    ).expanduser()
    vertex_token_present = any(
        provider_environment.get(name)
        for name in (
            "GOOGLE_VERTEX_AI_TOKEN",
            "VERTEX_AI_TOKEN",
            "GOOGLE_VERTEX_AI_SERVICE_ACCOUNT_TOKEN",
            "VERTEX_AI_SERVICE_ACCOUNT_TOKEN",
        )
    )
    if vertex_token_present:
        creation_mode = "--from-existing"
    elif adc_path.is_file():
        provider_environment["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_path)
        creation_mode = "--from-gcloud-adc"
    else:
        raise ValueError(
            "Vertex AI was selected, but no gateway-readable GCP credentials were "
            f"found at {adc_path}; authenticate with gcloud ADC or pass an existing "
            "OpenShell provider with --provider NAME"
        )

    _emit_output(
        f"Creating OpenShell Vertex AI provider: {provider_name}", output=output
    )
    result = _run(
        [
            _openshell_cli(args),
            "provider",
            "create",
            "--name",
            provider_name,
            "--type",
            "google-vertex-ai",
            creation_mode,
            "--config",
            f"VERTEX_AI_PROJECT_ID={project}",
            "--config",
            f"VERTEX_AI_REGION={region}",
        ],
        env=provider_environment,
        output=output,
    )
    if result != 0:
        raise ValueError(
            f"unable to create OpenShell Vertex AI provider '{provider_name}'; "
            "create a compatible provider and pass it with --provider NAME"
        )
    return provider_name


def _configure_openshell_inference(
    args, provider_name: str, model: str, *, output=None
) -> None:
    """Configure OpenShell's local inference route for a Vertex provider."""
    _emit_output(
        f"Configuring OpenShell inference route: {provider_name} / {model}",
        output=output,
    )
    result = _run(
        [
            _openshell_cli(args),
            "inference",
            "set",
            "--provider",
            provider_name,
            "--model",
            model,
            "--no-verify",
        ],
        output=output,
    )
    if result != 0:
        raise ValueError(
            "unable to configure OpenShell inference for Vertex AI; verify the "
            "provider project/region and selected Vertex model"
        )


def _openshell_cli_has_credentials(args, cli: str) -> bool:
    """Return whether staged setup needs an explicit provider instance."""
    environment = dict(os.environ)
    environment.update(_openshell_environment_values(args))
    if cli == "codex":
        codex_home = Path(
            environment.get("CODEX_HOME", _openshell_host_home() / ".codex")
        )
        return (codex_home / "auth.json").is_file() or bool(
            environment.get("OPENAI_API_KEY")
        )
    if cli == "claude":
        return bool(
            getattr(args, "api_key", None)
            or environment.get("ANTHROPIC_API_KEY")
            or environment.get("CLAUDE_API_KEY")
        )
    if cli == "copilot":
        return bool(
            environment.get("COPILOT_GITHUB_TOKEN")
            or environment.get("GH_TOKEN")
            or environment.get("GITHUB_TOKEN")
        )
    if cli == "opencode":
        return bool(
            environment.get("OPENCODE_API_KEY")
            or environment.get("OPENROUTER_API_KEY")
            or environment.get("OPENAI_API_KEY")
        )
    return False


def _openshell_entrypoint_args(args) -> List[str]:
    """Return the entrypoint command for an OpenShell-created sandbox."""
    return _command_args(args) or ["bash", "-l"]


def _generated_openshell_name(cli: str) -> str:
    """Generate the default logical name shared by both sandbox runtimes."""
    return f"ag-{cli[:8]}"


def _sandbox_base_name(args, runtime: str) -> str:
    """Return the requested name or the runtime's default logical name."""
    requested = getattr(args, "name", None)
    if requested:
        return str(requested)
    default_cli = (
        DEFAULT_OPENSHELL_CLI if runtime == OPENSHELL_RUNTIME else DEFAULT_CONTAINER_CLI
    )
    return _generated_openshell_name(_selected_cli(args, default_cli))


def _resolve_sandbox_name(args, runtime: str) -> str:
    """Choose an unused runtime name, adding a local timestamp on collision."""
    base_name = _sandbox_base_name(args, runtime)
    if not _sandbox_name_exists(args, runtime, base_name):
        return base_name

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{base_name}-{timestamp}"
    disambiguator = 1
    while _sandbox_name_exists(args, runtime, candidate):
        candidate = f"{base_name}-{timestamp}-{disambiguator}"
        disambiguator += 1
    return candidate


def _extract_openshell_service_url(value: str) -> Optional[str]:
    """Extract a gateway-managed service URL from OpenShell CLI output."""
    for match in _OPENSHELL_SERVICE_URL_RE.finditer(
        _ANSI_ESCAPE_RE.sub("", value or "")
    ):
        return match.group(0).rstrip(".,;)")
    return None


def _get_openshell_service_url(args, name: str) -> Optional[str]:
    """Return the gateway-managed AI Guardian service URL for a sandbox."""
    result = _run_capture(
        [
            _openshell_cli(args),
            "service",
            "get",
            name,
            OPENSHELL_SERVICE_NAME,
        ]
    )
    if not result or result.returncode != 0:
        return None
    return _extract_openshell_service_url(result.stdout or "")


def _expose_openshell_service(
    args,
    name: str,
    *,
    output: Optional[List[str]] = None,
) -> int:
    """Expose the daemon through an OpenShell gateway-managed HTTP service."""
    if not name:
        _emit_output(
            "Error: exposing the OpenShell service requires a sandbox name; "
            "provide --name.",
            output=output,
            error=True,
        )
        return 1

    command = [
        _openshell_cli(args),
        "service",
        "expose",
        name,
        DEFAULT_REST_PORT,
        OPENSHELL_SERVICE_NAME,
    ]
    captured: List[str] = []
    result = _run(command, output=captured)
    if output is None:
        for chunk in captured:
            print(chunk, end="")
    else:
        output.extend(captured)
    if result != 0:
        return result

    service_url = _extract_openshell_service_url("".join(captured))
    if service_url is None:
        service_url = _get_openshell_service_url(args, name)
    if not service_url:
        _emit_output(
            "Error: OpenShell did not return a service URL for the AI Guardian "
            "daemon.",
            output=output,
            error=True,
        )
        return 1

    _emit_output(
        f"OpenShell AI Guardian service: {service_url}",
        output=output,
    )
    return 0


def _ensure_openshell_service(
    args, name: str, *, output: Optional[List[str]] = None
) -> int:
    """Ensure the durable AI Guardian service endpoint exists for a sandbox."""
    if _get_openshell_service_url(args, name):
        return 0
    return _expose_openshell_service(args, name, output=output)


def _delete_openshell_service(
    args, name: str, *, output: Optional[List[str]] = None
) -> int:
    """Delete the AI Guardian service endpoint before deleting its sandbox."""
    if not _get_openshell_service_url(args, name):
        return 0
    return _run(
        [
            _openshell_cli(args),
            "service",
            "delete",
            name,
            OPENSHELL_SERVICE_NAME,
        ],
        output=output,
    )


def _recover_stopped_openshell_container(
    args, *, output: Optional[List[str]] = None
) -> Optional[int]:
    """Start a stopped OpenShell container when its control-plane state is stale.

    A user can stop the generated container directly with Podman or Docker.
    OpenShell then still reports the sandbox as ready and rejects its native
    ``start`` operation.  Tray callers provide the underlying container ID so
    this recovery can repair that split state without changing the normal CLI
    behavior, which has no reliable way to map the logical name to a container.
    """
    if output is None:
        return None
    failure_text = "".join(output).lower()
    if "must be stopped to start" not in failure_text:
        return None
    container_id = getattr(args, "container_id", None)
    if not container_id:
        return None

    _emit_output(
        "OpenShell rejected the start because its control-plane state is not "
        "stopped; starting the underlying container instead.",
        output=output,
    )
    return _run(
        [_container_engine(args), "start", str(container_id)],
        output=output,
    )


def _ensure_openshell_daemon(
    args, name: str, *, output: Optional[List[str]] = None
) -> int:
    """Ensure the AI Guardian daemon is running after an OpenShell start.

    Upload-based OpenShell sandboxes use a persistent shell as their main
    process while setup runs in a separate entrypoint exec.  Restarting that
    shell therefore does not rerun the entrypoint, so explicitly start the
    daemon when it is not already responsive.
    """
    status = _runtime_exec_capture(
        args, OPENSHELL_RUNTIME, name, ["ai-guardian", "daemon", "status"]
    )
    if status is not None and status.returncode == 0:
        return 0

    _emit_output(
        f"Starting ai-guardian daemon in OpenShell sandbox '{name}'...",
        output=output,
    )
    return _run(
        _openshell_exec_command(
            args,
            name,
            ("ai-guardian", "daemon", "start", "--background"),
        ),
        output=output,
    )


def _runtime_exec_capture(
    args, runtime: str, name: str, command: Sequence[str]
) -> Optional[subprocess.CompletedProcess]:
    """Run a non-interactive command inside a sandbox runtime."""
    if runtime == CONTAINER_RUNTIME:
        native_command = [
            _container_engine(args),
            "exec",
            _container_runtime_name(args, name),
            *command,
        ]
    elif runtime == OPENSHELL_RUNTIME:
        native_command = [
            _openshell_cli(args),
            "sandbox",
            "exec",
            "--name",
            name,
            "--no-tty",
            "--",
            *command,
        ]
    else:
        raise ValueError(f"unsupported sandbox runtime: {runtime}")
    return _run_capture(native_command)


def _sandbox_auth_token(args, runtime: str, name: str) -> Optional[str]:
    """Read the optional REST token from a sandbox runtime."""
    token_paths = (
        "/sandbox/.local/state/ai-guardian/daemon.token",
        "/root/.local/state/ai-guardian/daemon.token",
    )
    for token_path in token_paths:
        result = _runtime_exec_capture(args, runtime, name, ["cat", token_path])
        if result and result.returncode == 0:
            token = (result.stdout or "").strip()
            if token:
                return token
    return None


def _container_rest_port(args, name: str) -> int:
    """Find the host-side REST port published by a container."""
    result = _run_capture(
        [
            _container_engine(args),
            "port",
            _container_runtime_name(args, name),
            f"{DEFAULT_REST_PORT}/tcp",
        ]
    )
    if result and result.returncode == 0:
        for line in (result.stdout or "").splitlines():
            match = re.search(r":(?P<port>[0-9]+)\s*$", line.strip())
            if match:
                port = int(match.group("port"))
                if 1 <= port <= 65535:
                    return port
    raise ValueError(
        f"sandbox '{name}' has no reachable published REST port; "
        "ensure the sandbox is running"
    )


def _sandbox_rest_target(args, runtime: str, name: str) -> DaemonTarget:
    """Build a REST target for a running sandbox daemon."""
    service_url = None
    if runtime == CONTAINER_RUNTIME:
        port = _container_rest_port(args, name)
    elif runtime == OPENSHELL_RUNTIME:
        service_url = _get_openshell_service_url(args, name)
        if not service_url:
            raise ValueError(
                f"sandbox '{name}' has no OpenShell AI Guardian service endpoint; "
                f"run 'openshell service expose {name} {DEFAULT_REST_PORT} "
                f"{OPENSHELL_SERVICE_NAME}'"
            )
        port = 0
    else:
        raise ValueError(f"unsupported sandbox runtime: {runtime}")

    return DaemonTarget(
        name=name,
        runtime=runtime,
        host="127.0.0.1",
        port=port,
        url=service_url,
        auth_token=_sandbox_auth_token(args, runtime, name),
        container_engine=(
            _container_engine(args) if runtime == CONTAINER_RUNTIME else None
        ),
    )


def _fetch_sandbox_config(args, runtime: str, name: str) -> dict:
    """Retrieve the active global config from a running sandbox daemon."""
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    target = _sandbox_rest_target(args, runtime, name)
    config = MultiDaemonClient().get_config_scoped(target, scope="global")
    if config is None:
        raise ValueError(
            f"unable to retrieve configuration from sandbox '{name}'; "
            "ensure the daemon is running and reachable"
        )
    if not isinstance(config, dict):
        raise ValueError(f"sandbox '{name}' returned an invalid configuration")
    return config


def _restore_sandbox_config(args, runtime: str, name: str, selector: str) -> Path:
    """Restore a saved config snapshot into a running sandbox daemon."""
    from ai_guardian.daemon.multi_client import MultiDaemonClient

    snapshot_path, config = _load_snapshot_config(name, selector, runtime=runtime)
    target = _sandbox_rest_target(args, runtime, name)
    result = MultiDaemonClient().write_config_bulk(target, "global", config)
    if not isinstance(result, dict) or result.get("status") != "ok":
        detail = result.get("message") if isinstance(result, dict) else None
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"unable to restore configuration to sandbox '{name}'{suffix}")
    return snapshot_path


def _handle_sandbox_config_command(args, *, output: Optional[List[str]] = None) -> int:
    """Handle sandbox config snapshot commands."""
    config_operation = getattr(args, "sandbox_config_command", None)
    if config_operation is None:
        _emit_output(
            "Usage: ai-guardian sandbox config {save|list|restore}",
            output=output,
            error=True,
        )
        return 1

    name = getattr(args, "name", None)
    if config_operation == "list":
        requested_runtime = _requested_runtime(args)
        records = _list_sandbox_config_snapshots(name, requested_runtime)
        if getattr(args, "json_output", False):
            _emit_output(json.dumps(records, indent=2), output=output)
            return 0
        if not records:
            target = f" for sandbox '{name}'" if name else ""
            _emit_output(f"No configuration snapshots found{target}.", output=output)
            return 0
        if name:
            _emit_output(
                f"Configuration snapshots for sandbox '{name}':", output=output
            )
        for record in records:
            _emit_output(
                f"  {record['saved_at']} ({record['runtime']}): "
                f"{record['snapshot']}",
                output=output,
            )
        return 0

    if not name:
        raise ValueError(f"sandbox name is required for config {config_operation}")
    runtime = _resolve_lifecycle_runtime(args, f"config {config_operation}")
    if runtime is None:
        raise ValueError(f"unable to determine runtime for sandbox '{name}'")

    if config_operation == "save":
        config = _fetch_sandbox_config(args, runtime, name)
        snapshot_path = _write_sandbox_config_snapshot(name, runtime, config)
        if getattr(args, "json_output", False):
            _emit_output(
                json.dumps(
                    {
                        "sandbox_name": name,
                        "runtime": runtime,
                        "snapshot": str(snapshot_path),
                    },
                    indent=2,
                ),
                output=output,
            )
        else:
            _emit_output(
                f"Saved sandbox configuration snapshot: {snapshot_path}",
                output=output,
            )
        return 0

    if config_operation == "restore":
        selector = getattr(args, "snapshot", None) or "latest"
        snapshot_path = _restore_sandbox_config(args, runtime, name, selector)
        if getattr(args, "json_output", False):
            _emit_output(
                json.dumps(
                    {
                        "sandbox_name": name,
                        "runtime": runtime,
                        "snapshot": str(snapshot_path),
                        "status": "restored",
                    },
                    indent=2,
                ),
                output=output,
            )
        else:
            _emit_output(
                f"Restored sandbox configuration from: {snapshot_path}",
                output=output,
            )
        return 0

    raise ValueError(f"unsupported sandbox config operation: {config_operation}")


def _config_mount_args(command: List[str], args) -> None:
    """Stage a host config/profile as input for a writable sandbox copy.

    The host config is placed beside, rather than over, the active sandbox
    config.  The image entrypoint then applies the shared precedence rule:
    profile, existing sandbox-local config, selected host/snapshot config,
    generated default.
    """
    config_dir = _config_dir(args)
    profile = getattr(args, "profile", None)
    if profile:
        source, destination = _profile_source(profile, config_dir)
        if source:
            command.extend(["--volume", f"{source}:{destination}:ro,z"])
            profile_value = destination
        else:
            profile_value = profile
        command.extend(["--env", f"AI_GUARDIAN_PROFILE={profile_value}"])
        return

    config_path = _initial_config_source(args)
    if config_path:
        command.extend(
            [
                "--volume",
                f"{config_path}:{CONTAINER_HOST_CONFIG_PATH}:ro,z",
                "--env",
                "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true",
                "--env",
                f"AI_GUARDIAN_HOST_CONFIG_PATH={CONTAINER_HOST_CONFIG_PATH}",
            ]
        )
        if getattr(args, "restore_config", None):
            command.extend(["--env", "AI_GUARDIAN_RESTORE_CONFIG=true"])
    else:
        command.extend(["--env", "AI_GUARDIAN_HOST_CONFIG_MOUNTED=false"])


def _container_create(args) -> Tuple[List[str], Optional[Dict[str, str]]]:
    engine = _container_engine(args)
    image = _image_for_runtime(args, CONTAINER_RUNTIME)
    command = [
        engine,
        "run",
        "--detach",
        "--interactive",
        "--tty",
        "--label",
        MANAGED_LABEL,
        "--label",
        DAEMON_LABEL,
        "--label",
        "ai-guardian.runtime=container",
    ]

    name = _sandbox_base_name(args, CONTAINER_RUNTIME)
    command.extend(["--name", name])

    for label in getattr(args, "label", None) or []:
        command.extend(["--label", label])
    # Discovery uses this stable label before probing the daemon, whose
    # hostname may otherwise be the runtime-generated container ID.
    command.extend(["--label", f"ai-guardian.name={name}"])

    port = getattr(args, "port", None)
    if port is None:
        # Match the sandbox create behavior: publish the internal daemon port on a
        # runtime-selected host port so multiple managed sandboxes can coexist.
        command.extend(["--publish", DEFAULT_REST_PORT])
    else:
        command.extend(["--publish", f"{port}:{DEFAULT_REST_PORT}"])

    child_env = os.environ.copy()
    _add_container_environment(command, args, child_env=child_env)
    _config_mount_args(command, args)

    repo = getattr(args, "repo", None)
    if repo:
        command.extend(["--volume", f"{Path(repo).expanduser()}:/sandbox/repo"])

    command.append(image)
    # The detached TTY keeps the default login shell alive until the sandbox
    # is explicitly stopped, while connect/exec can open additional sessions.
    command.extend(_command_args(args) or ["bash", "-l"])
    return command, child_env


def _openshell_exec_workdir(args) -> List[str]:
    """Return the OpenShell exec workdir option for an uploaded repository."""
    if getattr(args, "repo", None):
        return ["--workdir", "/sandbox/repo"]
    return []


def _openshell_exec_command(
    args,
    name: str,
    command: Sequence[str],
    *,
    tty: bool = False,
) -> List[str]:
    """Build an OpenShell exec command with an explicit terminal contract."""
    return [
        _openshell_cli(args),
        "sandbox",
        "exec",
        "--name",
        name,
        "--tty" if tty else "--no-tty",
        *_openshell_exec_workdir(args),
        "--",
        *command,
    ]


def _openshell_create(
    args, *, output: Optional[List[str]] = None
) -> Tuple[List[str], str, bool, Path]:
    """Build a managed OpenShell create command and its temporary policy."""
    cli = _openshell_cli(args)
    image = _image_for_runtime(args, OPENSHELL_RUNTIME)
    command = [cli, "sandbox", "create", "--from", image, "--detach"]

    command.extend(
        ["--label", MANAGED_LABEL, "--label", "ai-guardian.runtime=openshell"]
    )

    cli = _selected_cli(args, DEFAULT_OPENSHELL_CLI)
    if cli not in SUPPORTED_CLI_IDE_TYPES:
        raise ValueError(
            f"unsupported OpenShell CLI '{cli}'; supported CLIs: "
            + ", ".join(SUPPORTED_CLI_IDE_TYPES)
        )

    name = _sandbox_base_name(args, OPENSHELL_RUNTIME)
    opencode_agent = _opencode_agent(args, cli)
    if opencode_agent:
        command.extend(["--label", f"ai-guardian.opencode-agent={opencode_agent}"])
    for label in getattr(args, "label", None) or []:
        command.extend(["--label", label])
    command.extend(["--name", name, "--label", f"ai-guardian.name={name}"])

    environment = [
        f"AI_GUARDIAN_AGENT={cli}",
        f"AI_GUARDIAN_IDE={cli}",
        f"AI_GUARDIAN_REST_PORT={DEFAULT_REST_PORT}",
        "AI_GUARDIAN_CONFIG_DIR=/sandbox/.config/ai-guardian",
        "AI_GUARDIAN_HOME=/sandbox/.config/ai-guardian",
        f"AI_GUARDIAN_SETUP_SCOPE={os.environ.get('AI_GUARDIAN_SETUP_SCOPE', 'selected')}",
    ]
    if opencode_agent:
        environment.append(f"AI_GUARDIAN_OPENCODE_AGENT={opencode_agent}")
    if cli == "claude":
        environment.append("DISABLE_AUTOUPDATER=1")
    if cli == "codex":
        environment.extend(
            [
                "CODEX_HOME=/sandbox/.codex",
                "AI_GUARDIAN_CODEX_SANDBOX_MODE=danger-full-access",
            ]
        )

    profile = getattr(args, "profile", None)
    uploads_requested = False
    if profile:
        config_dir = _config_dir(args)
        source, destination = _profile_source(profile, config_dir)
        profile_value = destination if source else profile
        environment.append(f"AI_GUARDIAN_PROFILE={profile_value}")
        if source:
            command.extend(["--upload", f"{source}:{destination}"])
            uploads_requested = True
    else:
        config_path = _initial_config_source(args)
        if config_path:
            command.extend(
                [
                    "--upload",
                    f"{config_path}:{CONTAINER_HOST_CONFIG_PATH}",
                ]
            )
            environment.extend(
                [
                    "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true",
                    f"AI_GUARDIAN_HOST_CONFIG_PATH={CONTAINER_HOST_CONFIG_PATH}",
                ]
            )
            if getattr(args, "restore_config", None):
                environment.append("AI_GUARDIAN_RESTORE_CONFIG=true")
            uploads_requested = True
        else:
            environment.append("AI_GUARDIAN_HOST_CONFIG_MOUNTED=false")

    repo = getattr(args, "repo", None)
    if repo:
        command.extend(["--upload", f"{Path(repo).expanduser()}:/sandbox/repo"])
        uploads_requested = True

    explicit_providers = list(getattr(args, "provider", None) or [])
    provider_names = explicit_providers[:]
    provider_attached = bool(provider_names)
    suppress_credential_warnings = False
    project, region, model = _vertex_settings(args)
    inference_cli = _openshell_inference_cli(args, cli)
    vertex_provider_required = inference_cli == "claude" and bool(project)
    if vertex_provider_required:
        provider_name = (
            provider_names[0]
            if provider_names
            else _ensure_openshell_vertex_provider(args, project, region, output=output)
        )
        if provider_names:
            _configure_openshell_vertex_provider(
                args, provider_name, project, region, output=output
            )
        _configure_openshell_inference(args, provider_name, model, output=output)
        provider_names = [provider_name, *provider_names[1:]]
        provider_attached = True
        environment.extend(
            [
                "AI_GUARDIAN_OPEN_SHELL_INFERENCE=true",
                "ANTHROPIC_BASE_URL=https://inference.local",
                # Claude Code requires a non-empty key even though the
                # inference router strips it and authenticates with the
                # attached Vertex provider.
                "ANTHROPIC_API_KEY=unused",
            ]
        )
        suppress_credential_warnings = True

    if not provider_names and (
        uploads_requested or _openshell_cli_has_credentials(args, inference_cli)
    ):
        provider_names = [
            _ensure_openshell_cli_provider(args, inference_cli, output=output)
        ]
        provider_attached = True

    if cli == "opencode" and inference_cli == "claude" and provider_attached:
        # OpenShell documents OpenCode's Anthropic-compatible client through
        # inference.local/v1. Only an explicitly Claude-selected OpenCode
        # profile/model uses this route; generic OpenCode providers keep their
        # own endpoint and credential environment.
        if not vertex_provider_required:
            _configure_openshell_inference(
                args, provider_names[0], model, output=output
            )
        environment.extend(
            [
                "AI_GUARDIAN_OPEN_SHELL_INFERENCE=true",
                "ANTHROPIC_BASE_URL=https://inference.local/v1",
                "ANTHROPIC_API_KEY=unused",
            ]
        )
        suppress_credential_warnings = True

    for value in environment:
        command.extend(["--env", value])
    for value in getattr(args, "environment", None) or []:
        command.extend(["--env", value])
    for provider in provider_names:
        command.extend(["--provider", provider])

    if suppress_credential_warnings:
        # OpenShell identifies the required non-secret client placeholder by
        # its environment-variable name. Do not present it as a credential
        # warning when the actual authentication is provider-backed.
        command.append("--no-credential-warnings")

    if cli == "codex" and provider_attached:
        environment_marker = "AI_GUARDIAN_OPEN_SHELL_PROVIDER=true"
        command.extend(["--env", environment_marker])

    if uploads_requested:
        command.extend(["--env", "AI_GUARDIAN_OPEN_SHELL_STAGING=true"])

    if provider_attached or uploads_requested:
        command.append("--no-auto-providers")
    else:
        command.append("--auto-providers")

    policy_path, policy_dir = _compose_openshell_policy(args, cli)
    command.extend(["--policy", str(policy_path)])

    # A detached OpenShell sandbox with no upload still needs its entrypoint to
    # start the daemon and keep the main shell alive. Uploaded sandboxes are
    # bootstrapped through a separate exec after OpenShell transfers files.
    if not uploads_requested:
        command.extend(["--", OPENSHELL_ENTRYPOINT, "bash", "-l"])

    return command, name, uploads_requested, policy_dir


def _create(
    args,
    *,
    interactive: bool = True,
    output: Optional[List[str]] = None,
) -> int:
    """Create a sandbox using the selected runtime."""
    policy_dir = None
    try:
        _validate_create_options(args)
        runtime = _runtime(args)
        base_name = _sandbox_base_name(args, runtime)
        args.name = _resolve_sandbox_name(args, runtime)
        if args.name != base_name:
            _emit_output(
                f"Sandbox name '{base_name}' is already in use; using '{args.name}'.",
                output=output,
            )
        if runtime == CONTAINER_RUNTIME:
            command, child_env = _container_create(args)
            return _run(command, env=child_env, output=output)
        command, name, uploads_requested, policy_dir = _openshell_create(
            args, output=output
        )
        result = _run(command, output=output)
        shutil.rmtree(policy_dir, ignore_errors=True)
        policy_dir = None
        if result != 0:
            return result

        if uploads_requested:
            exec_command = _openshell_exec_command(
                args, name, (OPENSHELL_ENTRYPOINT, "/bin/true")
            )
            result = _run(exec_command, output=output)
            if result != 0:
                return result

        result = _expose_openshell_service(args, name, output=output)
        if result != 0:
            return result

        explicit_command = _openshell_explicit_command(args)
        if uploads_requested:
            # The detached OpenShell process already owns the persistent
            # login shell.  Bootstrap setup must return so create can start
            # the gateway-managed service; an explicitly supplied command is a separate
            # user-requested exec and may remain interactive.
            if explicit_command:
                result = _run(
                    _openshell_exec_command(
                        args,
                        name,
                        explicit_command,
                        tty=interactive and output is None and sys.stdin.isatty(),
                    ),
                    output=output,
                )
                if result != 0:
                    return result
        elif explicit_command:
            result = _run(
                _openshell_exec_command(
                    args,
                    name,
                    explicit_command,
                    tty=interactive and output is None and sys.stdin.isatty(),
                ),
                output=output,
            )
            if result != 0:
                return result

        # Match native OpenShell UX by opening a shell after setup, but use an
        # independent exec session rather than ``connect``.  In OpenShell
        # versions where ``connect`` attaches to the sandbox's main process,
        # exiting that shell terminates the sandbox.
        if interactive and runtime == OPENSHELL_RUNTIME and not explicit_command:
            return _run(_openshell_interactive_shell_command(args, name), output=output)
        return result
    except ValueError as exc:
        _emit_output(f"Error: {exc}", output=output, error=True)
        return 2
    finally:
        if policy_dir is not None:
            shutil.rmtree(policy_dir, ignore_errors=True)


def create_sandbox(
    args,
    *,
    interactive: bool = True,
    output: Optional[List[str]] = None,
) -> int:
    """Create a sandbox for CLI or in-process tray callers.

    ``args`` uses the same attributes as the ``sandbox create`` parser.  The
    tray passes ``interactive=False`` so OpenShell setup returns after the
    daemon and gateway-managed service are ready instead of attaching a shell.
    When an output list is supplied, runtime output is captured there for a GUI
    log dialog; the normal CLI path keeps streaming to the caller's terminal.
    """
    return _create(args, interactive=interactive, output=output)


def _validate_create_options(args) -> None:
    """Validate create-only options before touching a runtime."""
    runtime = _requested_runtime(args) or _runtime(args)
    _validate_image_reference(getattr(args, "image", None))
    policy = getattr(args, "policy", None) or []
    providers = getattr(args, "provider", None) or []
    model = getattr(args, "model", None)
    default_cli = (
        DEFAULT_OPENSHELL_CLI if runtime == OPENSHELL_RUNTIME else DEFAULT_CONTAINER_CLI
    )
    cli = _selected_cli(args, default_cli)
    opencode_agent = _opencode_agent(args, cli)
    if getattr(args, "opencode_agent", None) and cli != "opencode":
        raise ValueError("--agent is supported only with --cli opencode")
    if cli == "opencode" and not opencode_agent:
        raise ValueError("--agent is required with --cli opencode")
    if runtime == CONTAINER_RUNTIME:
        if policy:
            raise ValueError("--policy is supported for OpenShell sandboxes only")
        if providers:
            raise ValueError("--provider is supported for OpenShell sandboxes only")
        if model:
            raise ValueError("--model is supported for OpenShell sandboxes only")
    elif runtime == OPENSHELL_RUNTIME:
        if getattr(args, "api_key", None):
            if _openshell_inference_cli(args, cli) != "claude":
                raise ValueError(
                    "--api-key can only be used with Claude-compatible OpenShell "
                    "inference"
                )
        if getattr(args, "port", None) is not None:
            raise ValueError("--port is supported for container sandboxes only")
    restore_selector = getattr(args, "restore_config", None)
    if not restore_selector:
        return
    if getattr(args, "profile", None):
        raise ValueError("--restore-config cannot be combined with --profile")
    if getattr(args, "config_dir", None):
        raise ValueError("--restore-config cannot be combined with --config-dir")
    if not getattr(args, "name", None):
        raise ValueError("--name is required with --restore-config")
    _load_snapshot_config(
        args.name,
        restore_selector,
        runtime=_requested_runtime(args) or _runtime(args),
    )


def _lifecycle_command(
    args, operation: str, *, runtime: Optional[str] = None, name: Optional[str] = None
) -> List[str]:
    runtime = runtime or _runtime(args)
    name = getattr(args, "name", None) if name is None else name
    if runtime == CONTAINER_RUNTIME:
        engine = _container_engine(args)
        name = _container_runtime_name(args, name)
        if operation == "list":
            command = [
                engine,
                "ps",
                "--all",
                "--filter",
                f"label={MANAGED_LABEL}",
            ]
            if getattr(args, "json_output", False):
                command.extend(["--format", "{{json .}}"])
            return command
        if operation == "status":
            return [engine, "inspect", name]
        if operation == "start":
            return [engine, "start", name]
        if operation == "stop":
            return [engine, "stop", name]
        if operation == "restart":
            return [engine, "restart", name]
        if operation == "connect":
            return [engine, "exec", "--interactive", "--tty", name, "/bin/bash", "-l"]
        if operation == "exec":
            command_args = _command_args(args) or ["/bin/bash", "-l"]
            return [engine, "exec", "--interactive", "--tty", name, *command_args]
        if operation == "logs":
            command = [engine, "logs"]
            if getattr(args, "follow", False):
                command.append("--follow")
            if getattr(args, "tail", None) is not None:
                command.extend(["--tail", str(args.tail)])
            return [*command, name]
        if operation == "delete":
            return [engine, "rm", "--force", name]
    else:
        cli = _openshell_cli(args)
        if operation == "list":
            command = [cli, "sandbox", "list", "--selector", MANAGED_LABEL]
            if getattr(args, "json_output", False):
                command.extend(["--output", "json"])
            return command
        if operation == "status":
            command = [cli, "sandbox", "get", name]
            if getattr(args, "json_output", False):
                command.extend(["--output", "json"])
            return command
        if operation == "start":
            return [cli, "sandbox", "start", name]
        if operation == "stop":
            return [cli, "sandbox", "stop", name]
        if operation == "connect":
            return _openshell_interactive_shell_command(args, name)
        if operation == "exec":
            command_args = _command_args(args) or ["/bin/bash", "-l"]
            return [cli, "sandbox", "exec", "--name", name, "--", *command_args]
        if operation == "logs":
            command = [cli, "logs", name]
            if getattr(args, "follow", False):
                command.append("--tail")
            if getattr(args, "source", None):
                command.extend(["--source", args.source])
            if getattr(args, "level", None):
                command.extend(["--level", args.level])
            if getattr(args, "since", None):
                command.extend(["--since", args.since])
            return command
        if operation == "delete":
            return [cli, "sandbox", "delete", name]

    raise ValueError(f"unsupported sandbox operation: {operation}")


def _openshell_interactive_shell_command(args, name: str) -> List[str]:
    """Build an independent interactive shell session for an OpenShell sandbox."""
    return _openshell_exec_command(args, name, ("/bin/bash", "-l"), tty=True)


def handle_sandbox_command(args, *, output: Optional[List[str]] = None) -> int:
    """Handle ``ai-guardian sandbox`` lifecycle subcommands.

    The optional ``output`` buffer is used by in-process callers such as the
    system tray.  The regular CLI leaves it unset so native runtime output
    continues to stream directly to the terminal.
    """
    operation = getattr(args, "sandbox_command", None)
    if operation is None:
        _emit_output(
            "Usage: ai-guardian sandbox {create|list|status|start|stop|restart|connect|exec|logs|config|delete}",
            output=output,
            error=True,
        )
        return 1

    try:
        if operation == "config":
            return _handle_sandbox_config_command(args, output=output)

        if operation == "create":
            return create_sandbox(args, output=output)

        runtime = _resolve_lifecycle_runtime(args, operation)
        if runtime is None:
            return _run_all_lifecycle_lists(args, output=output)

        if runtime == OPENSHELL_RUNTIME:
            name = getattr(args, "name", "")
            if operation == "stop":
                return _run(
                    _lifecycle_command(args, operation, runtime=runtime),
                    output=output,
                )
            if operation == "start":
                started = _run(
                    _lifecycle_command(args, operation, runtime=runtime),
                    output=output,
                )
                if started != 0:
                    recovered = _recover_stopped_openshell_container(
                        args, output=output
                    )
                    if recovered is None:
                        return started
                    if recovered != 0:
                        return recovered
                daemon_started = _ensure_openshell_daemon(args, name, output=output)
                if daemon_started != 0:
                    return daemon_started
                return _ensure_openshell_service(args, name, output=output)
            if operation == "restart":
                stopped = _run(
                    _lifecycle_command(args, "stop", runtime=runtime),
                    output=output,
                )
                if stopped != 0:
                    return stopped
                started = _run(
                    _lifecycle_command(args, "start", runtime=runtime),
                    output=output,
                )
                if started != 0:
                    return started
                daemon_started = _ensure_openshell_daemon(args, name, output=output)
                if daemon_started != 0:
                    return daemon_started
                return _ensure_openshell_service(args, name, output=output)
            if operation == "delete":
                service_deleted = _delete_openshell_service(args, name, output=output)
                if service_deleted != 0:
                    return service_deleted
                return _run(
                    _lifecycle_command(args, operation, runtime=runtime),
                    output=output,
                )

        return _run(
            _lifecycle_command(args, operation, runtime=runtime),
            output=output,
        )
    except ValueError as exc:
        _emit_output(f"Error: {exc}", output=output, error=True)
        return 2


def run_sandbox_command(args, *, output: Optional[List[str]] = None) -> int:
    """Run a sandbox lifecycle operation for a programmatic caller."""
    return handle_sandbox_command(args, output=output)


__all__ = [
    "CONTAINER_RUNTIME",
    "OPENSHELL_RUNTIME",
    "SUPPORTED_RUNTIMES",
    "create_sandbox",
    "handle_sandbox_command",
    "run_sandbox_command",
]
