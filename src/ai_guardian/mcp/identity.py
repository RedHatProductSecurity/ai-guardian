"""Local identity attestation for the built-in AI Guardian MCP server.

The MCP server name is supplied by the host and is not an identity proof.  Setup
records the installed package and launch identity, while each MCP process proves
that identity with a one-time nonce and a short-lived, process-bound session.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ai_guardian.config.utils import get_config_dir, get_state_dir

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "ai-guardian"
IDENTITY_SCHEMA_VERSION = 1
IDENTITY_MANIFEST_FILENAME = "mcp-identity.json"
IDENTITY_KEY_FILENAME = "mcp-identity.key"
IDENTITY_SESSION_DIRNAME = "mcp-identity-sessions"
IDENTITY_SESSION_PREFIX = "session-"
ENTRY_POINT = "ai_guardian.mcp.server:run_mcp_server"
CHALLENGE_TTL_SECONDS = 30
SESSION_TTL_SECONDS = 24 * 60 * 60

_pending_challenges: Dict[str, float] = {}


def is_ai_guardian_mcp_tool(tool_name: str) -> bool:
    """Return whether a tool claims the built-in AI Guardian MCP namespace."""
    return tool_name.startswith("mcp__ai-guardian__")


def get_identity_manifest_path() -> Path:
    """Return the protected setup-time identity manifest path."""
    return get_config_dir() / IDENTITY_MANIFEST_FILENAME


def get_identity_key_path() -> Path:
    """Return the protected signing-key path used for the identity manifest."""
    return get_config_dir() / IDENTITY_KEY_FILENAME


def get_identity_session_dir() -> Path:
    """Return the runtime directory containing process-bound attestations."""
    return get_state_dir() / IDENTITY_SESSION_DIRNAME


def _sha256_file(path: Optional[Path]) -> Optional[str]:
    """Return a file digest, or ``None`` when the path cannot be read."""
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _package_root() -> Path:
    """Return the installed ``ai_guardian`` package directory."""
    return Path(__file__).resolve().parents[1]


def _package_digest() -> Optional[str]:
    """Hash package Python sources and relative names deterministically."""
    root = _package_root()
    digest = hashlib.sha256()
    try:
        files = sorted(root.rglob("*.py"))
        for path in files:
            if "__pycache__" in path.parts or path.is_symlink() or not path.is_file():
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    except (OSError, ValueError):
        return None
    return digest.hexdigest()


def _resolve_path(value: Optional[str]) -> Optional[Path]:
    """Resolve an executable path without trusting a non-existent value."""
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_file():
        located = shutil.which(value)
        if located:
            candidate = Path(located)
    try:
        return candidate.resolve() if candidate.is_file() else None
    except OSError:
        return None


def _command_paths(command: str) -> Tuple[Optional[Path], Path]:
    """Resolve the configured entry point and Python runtime paths."""
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        tokens = command.split()

    entrypoint = None
    if tokens:
        module_invocation = any(
            token == "-m"
            and index + 1 < len(tokens)
            and tokens[index + 1] == "ai_guardian"
            for index, token in enumerate(tokens)
        )
        if not module_invocation:
            entrypoint = _resolve_path(tokens[0])

    try:
        runtime = Path(sys.executable).resolve()
    except OSError:
        runtime = Path(sys.executable)
    return entrypoint, runtime


def _runtime_entrypoint() -> Optional[Path]:
    """Resolve the console entry point used by the current process, if any."""
    return _resolve_path(sys.argv[0])


def _current_identity() -> Dict[str, Optional[str]]:
    """Collect identity facts from the current Python process."""
    from ai_guardian import __version__

    try:
        runtime = Path(sys.executable).resolve()
    except OSError:
        runtime = Path(sys.executable)
    entrypoint = _runtime_entrypoint()
    return {
        "package_version": __version__,
        "package_root": str(_package_root()),
        "package_sha256": _package_digest(),
        "runtime_executable": str(runtime),
        "runtime_executable_sha256": _sha256_file(runtime),
        "entrypoint": str(entrypoint) if entrypoint else None,
        "entrypoint_sha256": _sha256_file(entrypoint),
    }


def _build_manifest(command: str) -> Optional[Dict[str, Any]]:
    """Build the canonical identity facts recorded by setup."""
    from ai_guardian import __version__

    entrypoint, runtime = _command_paths(command)
    package_sha256 = _package_digest()
    runtime_sha256 = _sha256_file(runtime)
    if not package_sha256 or not runtime_sha256:
        return None

    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "server_name": MCP_SERVER_NAME,
        "package_name": "ai-guardian",
        "package_version": __version__,
        "package_root": str(_package_root()),
        "package_sha256": package_sha256,
        "entry_point": ENTRY_POINT,
        "launch_command": command,
        "entrypoint": str(entrypoint) if entrypoint else None,
        "entrypoint_sha256": _sha256_file(entrypoint),
        "runtime_executable": str(runtime),
        "runtime_executable_sha256": runtime_sha256,
        "created_at": time.time(),
    }


def _canonical_json(value: Dict[str, Any]) -> bytes:
    """Serialize identity data for signing without exposing secret material."""
    unsigned = {key: item for key, item in value.items() if key != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_or_create_key() -> bytes:
    """Load the setup key, creating it with restrictive permissions once."""
    path = get_identity_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(key)
        except FileExistsError:
            return path.read_bytes()
        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.debug("Unable to set identity key permissions", exc_info=True)
        return key


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    """Atomically write a private JSON identity record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            logger.debug("Unable to set identity record permissions", exc_info=True)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def register_mcp_identity(command: str) -> bool:
    """Register the installed package identity during MCP setup."""
    try:
        manifest = _build_manifest(command)
        if manifest is None:
            logger.error("Unable to collect the AI Guardian MCP installation identity")
            return False
        key = _load_or_create_key()
        if len(key) < 32:
            logger.error("AI Guardian MCP identity key is invalid")
            return False
        manifest["signature"] = hmac.new(
            key, _canonical_json(manifest), hashlib.sha256
        ).hexdigest()
        _write_json(get_identity_manifest_path(), manifest)
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.error("Unable to register AI Guardian MCP identity: %s", exc)
        return False


def _load_verified_manifest() -> Optional[Dict[str, Any]]:
    """Load and authenticate the setup-time identity manifest."""
    try:
        manifest = json.loads(get_identity_manifest_path().read_text(encoding="utf-8"))
        key = get_identity_key_path().read_bytes()
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict) or len(key) < 32:
        return None
    signature = manifest.get("signature")
    if not isinstance(signature, str):
        return None
    expected = hmac.new(key, _canonical_json(manifest), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    if (
        manifest.get("schema_version") != IDENTITY_SCHEMA_VERSION
        or manifest.get("server_name") != MCP_SERVER_NAME
        or manifest.get("entry_point") != ENTRY_POINT
    ):
        return None
    return manifest


def _identity_matches(
    manifest: Dict[str, Any], observed: Dict[str, Optional[str]]
) -> bool:
    """Compare observed package and executable facts with the signed manifest."""
    required_equal = (
        "package_version",
        "package_sha256",
        "runtime_executable",
        "runtime_executable_sha256",
    )
    if any(manifest.get(key) != observed.get(key) for key in required_equal):
        return False

    expected_entrypoint_hash = manifest.get("entrypoint_sha256")
    if expected_entrypoint_hash and expected_entrypoint_hash != observed.get(
        "entrypoint_sha256"
    ):
        return False
    return True


def _process_executable(pid: int) -> Optional[Path]:
    """Return a process executable path where the platform exposes one."""
    if os.name != "posix":
        return None
    proc_path = Path(f"/proc/{pid}/exe")
    try:
        return proc_path.resolve() if proc_path.exists() else None
    except OSError:
        return None


def _process_start_token(pid: int) -> Optional[str]:
    """Return a PID-reuse-resistant process start token on Linux."""
    if os.name != "posix":
        return None
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    closing_paren = raw.rfind(")")
    if closing_paren == -1:
        return None
    fields = raw[closing_paren + 2 :].split()
    return fields[19] if len(fields) > 19 else None


def _process_exists(pid: int) -> bool:
    """Return whether a process currently exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def begin_identity_handshake() -> Dict[str, str]:
    """Create a one-time challenge for an MCP process handshake."""
    nonce = secrets.token_urlsafe(32)
    _pending_challenges[nonce] = time.monotonic() + CHALLENGE_TTL_SECONDS
    return {"server_name": MCP_SERVER_NAME, "nonce": nonce}


def complete_identity_handshake(
    challenge: Dict[str, str], response: Optional[Dict[str, Any]] = None
) -> bool:
    """Validate a nonce response and cache the verified process session."""
    nonce = challenge.get("nonce") if isinstance(challenge, dict) else None
    if not isinstance(nonce, str):
        return False
    deadline = _pending_challenges.pop(nonce, None)
    if deadline is None or time.monotonic() > deadline:
        return False

    response = response or {
        "server_name": MCP_SERVER_NAME,
        "nonce": nonce,
        "pid": os.getpid(),
    }
    if (
        response.get("server_name") != MCP_SERVER_NAME
        or response.get("nonce") != nonce
        or response.get("pid") != os.getpid()
    ):
        return False

    manifest = _load_verified_manifest()
    observed = _current_identity()
    if manifest is None or not _identity_matches(manifest, observed):
        logger.warning("AI Guardian MCP identity attestation failed")
        return False

    pid = os.getpid()
    process_executable = _process_executable(pid)
    if process_executable is not None and str(process_executable) != observed.get(
        "runtime_executable"
    ):
        logger.warning("AI Guardian MCP process executable could not be verified")
        return False

    session = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "server_name": MCP_SERVER_NAME,
        "session_id": secrets.token_urlsafe(24),
        "pid": pid,
        "process_start": _process_start_token(pid),
        "process_executable": observed.get("runtime_executable"),
        "process_executable_sha256": observed.get("runtime_executable_sha256"),
        "entrypoint_sha256": observed.get("entrypoint_sha256"),
        "package_sha256": observed.get("package_sha256"),
        "manifest_signature": manifest.get("signature"),
        "nonce_sha256": hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }
    try:
        _write_json(
            get_identity_session_dir() / f"{IDENTITY_SESSION_PREFIX}{pid}.json",
            session,
        )
    except (OSError, TypeError, ValueError) as exc:
        logger.error("Unable to cache AI Guardian MCP identity: %s", exc)
        return False
    return True


def attest_mcp_server() -> bool:
    """Perform the built-in server's nonce-based identity handshake."""
    challenge = begin_identity_handshake()
    return complete_identity_handshake(challenge)


def _session_is_valid(session: Dict[str, Any], manifest: Dict[str, Any]) -> bool:
    """Validate one cached attestation without changing local state."""
    if (
        session.get("schema_version") != IDENTITY_SCHEMA_VERSION
        or session.get("server_name") != MCP_SERVER_NAME
        or session.get("manifest_signature") != manifest.get("signature")
    ):
        return False
    if not isinstance(session.get("session_id"), str):
        return False
    raw_pid = session.get("pid")
    raw_expires_at = session.get("expires_at")
    if raw_pid is None or raw_expires_at is None:
        return False
    try:
        pid = int(raw_pid)
        expires_at = float(raw_expires_at)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or expires_at <= time.time() or not _process_exists(pid):
        return False

    if session.get("process_start") != _process_start_token(pid):
        return False
    process_executable = _process_executable(pid)
    if process_executable is not None and str(process_executable) != session.get(
        "process_executable"
    ):
        return False
    if process_executable is not None and _sha256_file(
        process_executable
    ) != session.get("process_executable_sha256"):
        return False
    if session.get("package_sha256") != manifest.get("package_sha256"):
        return False
    expected_entrypoint_hash = manifest.get("entrypoint_sha256")
    if (
        expected_entrypoint_hash
        and session.get("entrypoint_sha256") != expected_entrypoint_hash
    ):
        return False
    return True


def verify_active_attestation(server_name: str = MCP_SERVER_NAME) -> bool:
    """Return whether a live, verified MCP process owns the built-in namespace."""
    if server_name != MCP_SERVER_NAME:
        return False
    manifest = _load_verified_manifest()
    if manifest is None:
        return False
    session_dir = get_identity_session_dir()
    try:
        session_paths = sorted(session_dir.glob(f"{IDENTITY_SESSION_PREFIX}*.json"))
    except OSError:
        return False
    for path in session_paths:
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(session, dict) and _session_is_valid(session, manifest):
            return True
    return False


def revoke_active_attestation(pid: Optional[int] = None) -> None:
    """Remove this process's cached attestation during orderly shutdown."""
    process_id = pid if pid is not None else os.getpid()
    path = get_identity_session_dir() / f"{IDENTITY_SESSION_PREFIX}{process_id}.json"
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.debug("Unable to revoke MCP identity session", exc_info=True)
