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
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ai_guardian.daemon.discovery import DaemonTarget, get_openshell_forward_state_dir
from ai_guardian.ide_registry import SUPPORTED_CLI_IDE_TYPES

CONTAINER_RUNTIME = "container"
OPENSHELL_RUNTIME = "openshell"
SUPPORTED_RUNTIMES = (CONTAINER_RUNTIME, OPENSHELL_RUNTIME)

DEFAULT_CONTAINER_ENGINE = "podman"
DEFAULT_CONTAINER_IMAGE = "quay.io/redhatproductsecurity/ai-guardian:latest"
DEFAULT_OPENSHELL_IMAGE = "quay.io/redhatproductsecurity/ai-guardian-openshell:latest"
DEFAULT_CONTAINER_AGENT = "codex"
DEFAULT_OPENSHELL_AGENT = "claude"
DEFAULT_REST_PORT = "63152"
DEFAULT_OPENSHELL_MODEL = "claude-sonnet-4-6"
MANAGED_LABEL = "ai-guardian.managed=true"
MANAGED_LABEL_KEY = "ai-guardian.managed"
RUNTIME_LABEL_KEY = "ai-guardian.runtime"
DAEMON_LABEL_KEY = "ai-guardian.daemon"
OPENSHELL_ENTRYPOINT = "/usr/local/bin/entrypoint.sh"
# Host configuration is staged outside the active sandbox config directory so
# an existing sandbox-local config can win over it at container startup.
CONTAINER_HOST_CONFIG_PATH = "/sandbox/.config/ai-guardian.host.json"
SANDBOX_CONFIG_STATE_DIRNAME = "sandboxes"
SANDBOX_CONFIG_FILENAME = "ai-guardian.json"
SANDBOX_CONFIG_METADATA_FILENAME = "metadata.json"

_OPENSHELL_BASE_POLICY_ENV = "AI_GUARDIAN_OPEN_SHELL_BASE_POLICY"
_OPENSHELL_AGENT_POLICY_DIR_ENV = "AI_GUARDIAN_OPEN_SHELL_AGENT_POLICY_DIR"

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OPENSHELL_FORWARD_LINE_RE = re.compile(
    r"Forwarding\s+127\.0\.0\.1:(?P<port>[0-9]+)\s+->"
)

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
    """Resolve the selected runtime, defaulting creation to containers."""
    return _requested_runtime(args) or CONTAINER_RUNTIME


def _container_engine(args) -> str:
    return (
        getattr(args, "container_engine", None)
        or os.environ.get("CONTAINER_ENGINE")
        or DEFAULT_CONTAINER_ENGINE
    )


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
    executable = _runtime_executable(args, runtime)
    return executable if shutil.which(executable) is None else None


def _command_args(args) -> List[str]:
    """Return arguments after an optional argparse ``--`` separator."""
    command = list(getattr(args, "command_args", None) or [])
    if command and command[0] == "--":
        return command[1:]
    return command


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


def _is_ai_guardian_labels(labels) -> bool:
    """Return whether runtime metadata identifies an AI Guardian resource."""
    if not isinstance(labels, dict):
        return False
    return (
        labels.get(MANAGED_LABEL_KEY) == "true"
        or labels.get(DAEMON_LABEL_KEY) == "true"
        or labels.get(RUNTIME_LABEL_KEY) in SUPPORTED_RUNTIMES
    )


def _container_is_ai_guardian(args, name: str) -> bool:
    """Check an exact container name without printing a probe error."""
    result = _run_capture([_container_engine(args), "inspect", name])
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
    container_match = _container_is_ai_guardian(args, name)
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
    agent = getattr(args, "agent", None) or os.environ.get(
        "AI_GUARDIAN_AGENT", DEFAULT_CONTAINER_AGENT
    )
    values = [
        f"AI_GUARDIAN_AGENT={agent}",
        f"AI_GUARDIAN_IDE={agent}",
        f"AI_GUARDIAN_REST_PORT={DEFAULT_REST_PORT}",
        "AI_GUARDIAN_CONFIG_DIR=/sandbox/.config/ai-guardian",
        "AI_GUARDIAN_HOME=/sandbox/.config/ai-guardian",
        f"AI_GUARDIAN_SETUP_SCOPE={os.environ.get('AI_GUARDIAN_SETUP_SCOPE', 'selected')}",
    ]
    for value in values:
        command.extend(["--env", value])

    # Let the runtime read host credentials from the child environment instead
    # of putting their values in the engine command line.
    for name in _KNOWN_CREDENTIAL_ENVIRONMENT:
        if os.environ.get(name):
            command.extend(["--env", name])

    api_key = getattr(args, "api_key", None)
    if api_key:
        child_env["ANTHROPIC_API_KEY"] = api_key
        command.extend(["--env", "ANTHROPIC_API_KEY"])

    for value in getattr(args, "environment", None) or []:
        command.extend(["--env", value])


def _openshell_asset_roots() -> List[Path]:
    """Return source-tree and installed locations for OpenShell assets."""
    repository_root = Path(__file__).resolve().parents[2] / "container"
    installed_root = Path(__file__).resolve().parent / "sandbox_assets"
    return [repository_root, installed_root]


def _openshell_policy_assets(args, agent: str) -> Tuple[Path, Path]:
    """Resolve the baseline and selected-agent OpenShell policy fragments."""
    base_override = os.environ.get(_OPENSHELL_BASE_POLICY_ENV)
    agent_override = os.environ.get(_OPENSHELL_AGENT_POLICY_DIR_ENV)
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

    if agent_override:
        agent_path = Path(agent_override).expanduser() / f"{agent}.yaml"
    else:
        agent_path = next(
            (
                root / "policies" / "agents" / f"{agent}.yaml"
                for root in roots
                if (root / "policies" / "agents" / f"{agent}.yaml").is_file()
            ),
            roots[0] / "policies" / "agents" / f"{agent}.yaml",
        )

    if not base_path.is_file():
        raise ValueError(f"OpenShell base policy not found: {base_path}")
    if not agent_path.is_file():
        raise ValueError(
            f"OpenShell policy fragment not found for agent '{agent}': {agent_path}"
        )
    return base_path, agent_path


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


def _compose_openshell_policy(args, agent: str) -> Tuple[Path, Path]:
    """Compose the baseline, user overlays, and selected-agent policy."""
    import yaml

    base_path, agent_path = _openshell_policy_assets(args, agent)
    overlay_paths = [
        Path(value).expanduser() for value in getattr(args, "policy", None) or []
    ]
    for policy_path in overlay_paths:
        if not policy_path.is_file():
            raise ValueError(f"OpenShell policy file not found: {policy_path}")

    policy: Dict[str, Any] = {}
    for path in [base_path, *overlay_paths, agent_path]:
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


def _openshell_provider_environment(args, agent: str) -> Dict[str, str]:
    """Build a temporary provider-process environment without sandbox secrets."""
    environment = os.environ.copy()
    environment.update(_openshell_environment_values(args))

    api_key = getattr(args, "api_key", None)
    if api_key and agent == "claude" and not environment.get("ANTHROPIC_API_KEY"):
        environment["ANTHROPIC_API_KEY"] = api_key

    if agent == "codex":
        codex_home = Path(
            os.environ.get("CODEX_HOME", _openshell_host_home() / ".codex")
        )
        auth_path = codex_home / "auth.json"
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            auth = {}
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


def _ensure_openshell_agent_provider(
    args, agent: str, *, output: Optional[List[str]] = None
) -> str:
    """Create or reuse the default provider needed by staged agent setup."""
    if agent not in {"claude", "codex", "copilot", "opencode"}:
        raise ValueError(
            f"the active OpenShell gateway has no automatic provider mapping for '{agent}'; "
            "create a compatible provider and pass it with --provider NAME"
        )

    profiles = _openshell_provider_profiles(args)
    provider_type = (
        "claude-code" if agent == "claude" and "claude-code" in profiles else agent
    )
    if agent == "claude" and provider_type == "claude" and "claude" not in profiles:
        raise ValueError(
            "the active OpenShell gateway has no provider profile for 'claude'; "
            "create a compatible provider and pass it with --provider NAME"
        )
    if provider_type not in profiles:
        raise ValueError(
            f"the active OpenShell gateway has no provider profile for '{agent}'; "
            "create a compatible provider and pass it with --provider NAME"
        )

    provider_name = f"ai-guardian-{agent}"
    if _openshell_provider_exists(args, provider_name):
        _emit_output(
            f"Using existing OpenShell provider: {provider_name}", output=output
        )
        return provider_name

    if agent == "codex" and not os.environ.get("OPENAI_API_KEY"):
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
    result = _run(
        [
            _openshell_cli(args),
            "provider",
            "create",
            "--name",
            provider_name,
            "--type",
            provider_type,
            "--from-existing",
        ],
        env=_openshell_provider_environment(args, agent),
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


def _openshell_agent_has_credentials(args, agent: str) -> bool:
    """Return whether staged setup needs an explicit provider instance."""
    environment = dict(os.environ)
    environment.update(_openshell_environment_values(args))
    if agent == "codex":
        codex_home = Path(
            environment.get("CODEX_HOME", _openshell_host_home() / ".codex")
        )
        return (codex_home / "auth.json").is_file() or bool(
            environment.get("OPENAI_API_KEY")
        )
    if agent == "claude":
        return bool(
            getattr(args, "api_key", None)
            or environment.get("ANTHROPIC_API_KEY")
            or environment.get("CLAUDE_API_KEY")
        )
    if agent == "copilot":
        return bool(
            environment.get("COPILOT_GITHUB_TOKEN")
            or environment.get("GH_TOKEN")
            or environment.get("GITHUB_TOKEN")
        )
    if agent == "opencode":
        return bool(
            environment.get("OPENCODE_API_KEY")
            or environment.get("OPENROUTER_API_KEY")
            or environment.get("OPENAI_API_KEY")
        )
    return False


def _openshell_forward_enabled(args) -> bool:
    """Resolve the OpenShell forwarding switch from CLI or environment."""
    if getattr(args, "no_forward", False):
        return False
    configured = os.environ.get("AI_GUARDIAN_OPEN_SHELL_FORWARD")
    if configured is None:
        return True
    if configured.lower() in {"1", "true", "yes", "on"}:
        return True
    if configured.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError("AI_GUARDIAN_OPEN_SHELL_FORWARD must be true or false")


def _openshell_entrypoint_args(args) -> List[str]:
    """Return the entrypoint command for an OpenShell-created sandbox."""
    return _command_args(args) or ["bash", "-l"]


def _generated_openshell_name(agent: str) -> str:
    """Generate a short name for OpenShell's upload-then-exec flow."""
    agent_suffix = agent[:8]
    pid_suffix = str(os.getpid())[-6:]
    return f"ag-{agent_suffix}-{pid_suffix}"


def _openshell_forward_state_path(name: str) -> Path:
    """Return the shared discovery state path for an OpenShell forward."""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return get_openshell_forward_state_dir() / f"{safe_name}.json"


def _read_openshell_forward_state(name: str) -> Optional[dict]:
    """Read a previously recorded OpenShell service-forward state."""
    try:
        data = json.loads(
            _openshell_forward_state_path(name).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_openshell_forward_state(
    name: str, port: int, pid: int, *, enabled: bool = True
) -> bool:
    """Atomically record OpenShell service-forward state for discovery."""
    state_path = _openshell_forward_state_path(name)
    try:
        state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".openshell-forward.",
            suffix=".tmp",
            dir=state_path.parent,
        )
        state = {
            "sandbox_name": name,
            "host": "127.0.0.1",
            "port": int(port),
            "target_port": int(DEFAULT_REST_PORT),
            "pid": int(pid),
        }
        if not enabled:
            state["enabled"] = False
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, separators=(",", ":"))
                stream.write("\n")
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, state_path)
        except Exception:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass  # intentionally silent — cleanup of temporary state
            raise
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Unable to record OpenShell forward for %s: %s", name, exc)
        return False
    return True


def _terminate_openshell_forward(pid: int) -> None:
    """Stop a service-forward process recorded by this command."""
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # intentionally silent — forward already stopped
    except OSError as exc:
        logger.debug("Unable to stop OpenShell forward process %s: %s", pid, exc)


def _stop_openshell_forward(name: str, *, retain: bool) -> None:
    """Stop a recorded forward and optionally retain its port for ``start``."""
    state_path = _openshell_forward_state_path(name)
    state = _read_openshell_forward_state(name)
    if state:
        try:
            _terminate_openshell_forward(int(state.get("pid", 0)))
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid OpenShell forward PID for %s", name)

    if retain and state:
        state["pid"] = 0
        try:
            state_path.write_text(
                json.dumps(state, separators=(",", ":")) + "\n", encoding="utf-8"
            )
            os.chmod(state_path, 0o600)
        except OSError as exc:
            logger.debug(
                "Unable to retain OpenShell forward state for %s: %s", name, exc
            )
    elif not retain:
        try:
            state_path.unlink()
        except FileNotFoundError:
            pass  # intentionally silent — no forward was recorded
        except OSError as exc:
            logger.debug(
                "Unable to remove OpenShell forward state for %s: %s", name, exc
            )


def _start_openshell_forward(
    args,
    name: str,
    port: Optional[int] = None,
    *,
    output: Optional[List[str]] = None,
) -> int:
    """Start a persistent host REST forward and record its assigned port."""
    if not name:
        _emit_output(
            "Error: OpenShell forwarding requires a sandbox name; provide --name.",
            output=output,
            error=True,
        )
        return 1

    requested_port = port if port is not None else getattr(args, "port", None)
    local_port = str(requested_port if requested_port is not None else 0)
    command = [
        _openshell_cli(args),
        "forward",
        "service",
        "--target-port",
        DEFAULT_REST_PORT,
        "--local",
        f"127.0.0.1:{local_port}",
        name,
    ]
    popen_options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
    }
    if os.name == "nt":
        popen_options["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        popen_options["start_new_session"] = True

    try:
        process = subprocess.Popen(command, **popen_options)
    except FileNotFoundError:
        _emit_output(
            "Error: required executable was not found: " f"{_openshell_cli(args)}",
            output=output,
            error=True,
        )
        return 127
    except OSError as exc:
        _emit_output(
            f"Error starting OpenShell service forward: {exc}",
            output=output,
            error=True,
        )
        return 1

    ready = threading.Event()
    result = {}

    def _consume_output():
        stream = process.stdout
        if stream is None:
            result["error"] = "OpenShell forward produced no status output"
            ready.set()
            return
        try:
            for raw_line in stream:
                line = _ANSI_ESCAPE_RE.sub("", raw_line).strip()
                _record_output(output, f"{line}\n")
                match = _OPENSHELL_FORWARD_LINE_RE.search(line)
                if match and "port" not in result:
                    result["port"] = int(match.group("port"))
                    ready.set()
        except (OSError, ValueError) as exc:
            result["error"] = str(exc)
        finally:
            if not ready.is_set():
                result.setdefault(
                    "error", "OpenShell forward exited before becoming ready"
                )
                ready.set()

    threading.Thread(
        target=_consume_output,
        name=f"openshell-forward-{name}",
        daemon=True,
    ).start()

    if not ready.wait(timeout=10):
        _terminate_openshell_forward(process.pid)
        _emit_output(
            "Error: timed out waiting for OpenShell service forward.",
            output=output,
            error=True,
        )
        return 1

    assigned_port = result.get("port")
    if not isinstance(assigned_port, int) or not 1 <= assigned_port <= 65535:
        _terminate_openshell_forward(process.pid)
        detail = result.get("error", "OpenShell did not report a valid host port")
        _emit_output(f"Error: {detail}.", output=output, error=True)
        return 1

    if not _write_openshell_forward_state(name, assigned_port, process.pid):
        _terminate_openshell_forward(process.pid)
        return 1

    _emit_output(
        f"OpenShell REST forward: http://127.0.0.1:{assigned_port}/",
        output=output,
    )
    return 0


def _restart_recorded_openshell_forward(
    args, name: str, *, output: Optional[List[str]] = None
) -> int:
    """Restart or recreate the OpenShell forward for a sandbox."""
    state = _read_openshell_forward_state(name)
    if state and state.get("enabled") is False:
        _emit_output(
            f"OpenShell REST forwarding is disabled for sandbox '{name}'.",
            output=output,
        )
        return 0

    port = 0
    if state:
        try:
            port = int(state.get("port", 0))
        except (TypeError, ValueError):
            port = 0

    if 1 <= port <= 65535:
        if output is None:
            result = _start_openshell_forward(args, name, port=port)
        else:
            result = _start_openshell_forward(args, name, port=port, output=output)
        if result == 0:
            return 0
        _emit_output(
            f"Unable to reuse OpenShell forward port {port}; allocating a new port.",
            output=output,
            error=True,
        )
    else:
        _emit_output(
            f"No usable OpenShell forward record for sandbox '{name}'; "
            "creating a new forward.",
            output=output,
        )

    if output is None:
        return _start_openshell_forward(args, name)
    return _start_openshell_forward(args, name, output=output)


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
        native_command = [_container_engine(args), "exec", name, *command]
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
        [_container_engine(args), "port", name, f"{DEFAULT_REST_PORT}/tcp"]
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
    if runtime == CONTAINER_RUNTIME:
        port = _container_rest_port(args, name)
    elif runtime == OPENSHELL_RUNTIME:
        state = _read_openshell_forward_state(name)
        try:
            port = int(state.get("port", 0)) if state else 0
            forward_pid = int(state.get("pid", 0)) if state else 0
        except (TypeError, ValueError):
            port = 0
            forward_pid = 0
        if not 1 <= port <= 65535 or forward_pid <= 0:
            raise ValueError(
                f"sandbox '{name}' has no active OpenShell REST forward; "
                "recreate it without --no-forward"
            )
    else:
        raise ValueError(f"unsupported sandbox runtime: {runtime}")

    return DaemonTarget(
        name=name,
        runtime=runtime,
        host="127.0.0.1",
        port=port,
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
    image = getattr(args, "image", None) or os.environ.get(
        "AI_GUARDIAN_IMAGE", DEFAULT_CONTAINER_IMAGE
    )
    command = [
        engine,
        "run",
        "--detach",
        "--interactive",
        "--tty",
        "--label",
        MANAGED_LABEL,
        "--label",
        "ai-guardian.runtime=container",
    ]

    name = getattr(args, "name", None)
    if name:
        command.extend(["--name", name])

    for label in getattr(args, "label", None) or []:
        command.extend(["--label", label])
    if name:
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
    image = getattr(args, "image", None) or os.environ.get(
        "AI_GUARDIAN_IMAGE",
        os.environ.get("AI_GUARDIAN_OPEN_SHELL_IMAGE", DEFAULT_OPENSHELL_IMAGE),
    )
    command = [cli, "sandbox", "create", "--from", image, "--detach"]

    command.extend(
        ["--label", MANAGED_LABEL, "--label", "ai-guardian.runtime=openshell"]
    )

    agent = getattr(args, "agent", None) or os.environ.get(
        "AI_GUARDIAN_AGENT", DEFAULT_OPENSHELL_AGENT
    )
    if agent not in SUPPORTED_CLI_IDE_TYPES:
        raise ValueError(
            f"unsupported OpenShell agent '{agent}'; supported CLI agents: "
            + ", ".join(SUPPORTED_CLI_IDE_TYPES)
        )

    name = getattr(args, "name", None) or _generated_openshell_name(agent)
    command.extend(["--name", name, "--label", f"ai-guardian.name={name}"])
    for label in getattr(args, "label", None) or []:
        command.extend(["--label", label])

    environment = [
        f"AI_GUARDIAN_AGENT={agent}",
        f"AI_GUARDIAN_IDE={agent}",
        f"AI_GUARDIAN_REST_PORT={DEFAULT_REST_PORT}",
        "AI_GUARDIAN_CONFIG_DIR=/sandbox/.config/ai-guardian",
        "AI_GUARDIAN_HOME=/sandbox/.config/ai-guardian",
        f"AI_GUARDIAN_SETUP_SCOPE={os.environ.get('AI_GUARDIAN_SETUP_SCOPE', 'selected')}",
    ]
    if agent == "claude":
        environment.append("DISABLE_AUTOUPDATER=1")
    if agent == "codex":
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
    project, region, model = _vertex_settings(args)
    vertex_provider_required = agent == "claude" and bool(project)
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
                "ANTHROPIC_API_KEY=unused",
            ]
        )

    if not provider_names and (
        uploads_requested or _openshell_agent_has_credentials(args, agent)
    ):
        provider_names = [_ensure_openshell_agent_provider(args, agent, output=output)]
        provider_attached = True

    for value in environment:
        command.extend(["--env", value])
    for value in getattr(args, "environment", None) or []:
        command.extend(["--env", value])
    for provider in provider_names:
        command.extend(["--provider", provider])

    if agent == "codex" and provider_attached:
        environment_marker = "AI_GUARDIAN_OPEN_SHELL_PROVIDER=true"
        command.extend(["--env", environment_marker])

    if uploads_requested:
        command.extend(["--env", "AI_GUARDIAN_OPEN_SHELL_STAGING=true"])

    if provider_attached or uploads_requested:
        command.append("--no-auto-providers")
    else:
        command.append("--auto-providers")

    policy_path, policy_dir = _compose_openshell_policy(args, agent)
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
        if runtime == CONTAINER_RUNTIME:
            command, child_env = _container_create(args)
            return _run(command, env=child_env, output=output)
        command, name, uploads_requested, policy_dir = _openshell_create(
            args, output=output
        )
        result = _run(command, output=output)
        shutil.rmtree(policy_dir, ignore_errors=True)
        policy_dir = None
        forward_enabled = _openshell_forward_enabled(args)
        if result != 0:
            return result

        if uploads_requested:
            exec_command = _openshell_exec_command(
                args, name, (OPENSHELL_ENTRYPOINT, "/bin/true")
            )
            result = _run(exec_command, output=output)
            if result != 0:
                return result

            # The detached OpenShell process already owns the persistent
            # login shell.  Bootstrap setup must return so create can start
            # the REST forward; an explicitly supplied command is a separate
            # user-requested exec and may remain interactive.
            command_args = _command_args(args)
            if command_args:
                result = _run(
                    _openshell_exec_command(
                        args,
                        name,
                        command_args,
                        tty=interactive and output is None and sys.stdin.isatty(),
                    ),
                    output=output,
                )
                if result != 0:
                    return result
        elif _command_args(args):
            result = _run(
                _openshell_exec_command(
                    args,
                    name,
                    _command_args(args),
                    tty=interactive and output is None and sys.stdin.isatty(),
                ),
                output=output,
            )
            if result != 0:
                return result

        if forward_enabled:
            if output is None:
                result = _start_openshell_forward(args, name)
            else:
                result = _start_openshell_forward(args, name, output=output)
            if result != 0:
                return result
        else:
            # Retain an explicit no-forward choice so a later lifecycle
            # restart does not silently create a host listener. Older
            # sandboxes without this marker default to recovery on restart.
            _write_openshell_forward_state(name, 0, 0, enabled=False)

        # Match native OpenShell UX by opening a shell after setup, but use an
        # independent exec session rather than ``connect``.  In OpenShell
        # versions where ``connect`` attaches to the sandbox's main process,
        # exiting that shell terminates the sandbox.
        if interactive and runtime == OPENSHELL_RUNTIME and not _command_args(args):
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
    daemon and REST forward are ready instead of attaching a shell.  When an
    output list is supplied, runtime output is captured there for a GUI log
    dialog; the normal CLI path keeps streaming to the caller's terminal.
    """
    return _create(args, interactive=interactive, output=output)


def _validate_create_options(args) -> None:
    """Validate create-only options before touching a runtime."""
    runtime = _requested_runtime(args) or _runtime(args)
    policy = getattr(args, "policy", None) or []
    providers = getattr(args, "provider", None) or []
    model = getattr(args, "model", None)
    if runtime == CONTAINER_RUNTIME:
        if policy:
            raise ValueError("--policy is supported for OpenShell sandboxes only")
        if providers:
            raise ValueError("--provider is supported for OpenShell sandboxes only")
        if model:
            raise ValueError("--model is supported for OpenShell sandboxes only")
        if getattr(args, "no_forward", False):
            raise ValueError("--no-forward is supported for OpenShell sandboxes only")
    elif getattr(args, "api_key", None):
        agent = getattr(args, "agent", None) or os.environ.get(
            "AI_GUARDIAN_AGENT", DEFAULT_OPENSHELL_AGENT
        )
        if agent != "claude":
            raise ValueError(
                "--api-key can only be used with the Claude OpenShell agent"
            )
    if runtime == OPENSHELL_RUNTIME:
        _openshell_forward_enabled(args)

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
            if _requested_runtime(args) is None:
                raise ValueError(
                    "--runtime is required when creating a sandbox; "
                    "lifecycle commands can auto-detect it"
                )
            return create_sandbox(args, output=output)

        runtime = _resolve_lifecycle_runtime(args, operation)
        if runtime is None:
            return _run_all_lifecycle_lists(args, output=output)

        if runtime == OPENSHELL_RUNTIME:
            name = getattr(args, "name", "")
            if operation == "stop":
                _stop_openshell_forward(name, retain=True)
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
                return _restart_recorded_openshell_forward(args, name, output=output)
            if operation == "restart":
                _stop_openshell_forward(name, retain=True)
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
                return _restart_recorded_openshell_forward(args, name, output=output)
            if operation == "delete":
                _stop_openshell_forward(name, retain=False)
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
