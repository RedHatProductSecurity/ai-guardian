"""Owner-only SSH pairing storage, separate from exported daemon configuration.

POSIX uses private files/directories; Windows protects the entire record with
current-user DPAPI (confidentiality AND integrity, independent of inherited ACLs).
SSH passwords and private keys are never requested or stored.
"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from ai_guardian.daemon.rest_transport import _material_file, TLSOptions

STORAGE_ERROR = "Saved SSH connections are unavailable or have unsafe permissions; check the owning account's protected storage."
DESTINATION_ERROR = "Enter a known SSH host or alias, optionally as user@host; SSH options, URLs, and shell commands are not accepted."
DUPLICATE_ERROR = "This SSH destination is already paired. Remove the saved connection before pairing it again."
_WINDOWS = os.name == "nt"


class SSHConnectionError(ValueError):
    """Only constant, credential-free messages cross the UI/log boundary."""


def destination(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}@)?[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", value
    ):
        raise SSHConnectionError(DESTINATION_ERROR)
    return value


@dataclass(frozen=True)
class SSHProfile:
    destination: str
    server_name: str
    certificate_sha256: str
    ca_pem: str = field(repr=False)
    token: str = field(repr=False)

    @property
    def id(self):
        return hashlib.sha256(self.destination.encode()).hexdigest()[:32]

    @property
    def name(self):
        return f"ssh-{self.destination}"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise SSHConnectionError(STORAGE_ERROR)
        if not all(isinstance(item, str) for item in value.values()):
            raise SSHConnectionError(STORAGE_ERROR)
        destination(value["destination"])
        options = TLSOptions.from_config(
            {key: value[key] for key in ("server_name", "certificate_sha256")}
        )
        if (
            not options.server_name
            or not options.certificate_sha256
            or not 1 <= len(value["ca_pem"]) <= 131072
            or not re.fullmatch(r"[\x21-\x7e]{1,4096}", value["token"])
        ):
            raise SSHConnectionError(STORAGE_ERROR)
        return cls(**value)


def _dpapi(data: bytes, *, decrypt=False) -> bytes:
    """DPAPI is user-bound, authenticated encryption; never permits a UI prompt."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.DWORD),
            ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    dll = getattr(ctypes, "windll")
    crypt = dll.crypt32.CryptUnprotectData if decrypt else dll.crypt32.CryptProtectData
    if not crypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise SSHConnectionError(STORAGE_ERROR)
    try:
        return ctypes.string_at(output.data, output.length)
    finally:
        free = dll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(ctypes.cast(output.data, ctypes.c_void_p))


class SSHStore:
    def __init__(self, path: Path | None = None):
        from ai_guardian.config.utils import get_state_dir

        self.path = path or get_state_dir() / "ssh-connections"

    def _directory(self, *, create=False):
        if create:
            self.path.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not self.path.exists():
            return False
        info = self.path.lstat()
        if not stat.S_ISDIR(info.st_mode) or (
            not _WINDOWS and (info.st_uid != os.geteuid() or info.st_mode & 0o077)
        ):
            raise SSHConnectionError(STORAGE_ERROR)
        return True

    def load(self) -> list[SSHProfile]:
        try:
            if not self._directory():
                return []
            return [self._read(path) for path in sorted(self.path.glob("*.json"))]
        except (OSError, ValueError):
            raise SSHConnectionError(STORAGE_ERROR) from None

    def _read(self, path):
        if path.is_symlink():
            raise SSHConnectionError(STORAGE_ERROR)
        _material_file(str(path), private=True)
        with path.open("rb") as stream:
            data = stream.read(262145)
        if len(data) > 262144:
            raise SSHConnectionError(STORAGE_ERROR)
        if _WINDOWS:
            data = _dpapi(data, decrypt=True)
        profile = SSHProfile.from_dict(json.loads(data))
        if path.name != f"{profile.id}.json":
            raise SSHConnectionError(STORAGE_ERROR)
        return profile

    def contains(self, profile):
        try:
            return (
                self._directory()
                and self._read(self.path / f"{profile.id}.json") == profile
            )
        except (OSError, ValueError):
            return False

    def create(self, profile):
        temporary = None
        try:
            SSHProfile.from_dict(asdict(profile))
            self._directory(create=True)
            data = json.dumps(asdict(profile)).encode()
            if _WINDOWS:
                data = _dpapi(data)
            with tempfile.NamedTemporaryFile(
                dir=self.path, prefix=".pair-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                _material_file(str(temporary), private=True)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic, exclusive publication: pairing can never replace trust.
            os.link(temporary, self.path / f"{profile.id}.json")
        except FileExistsError:
            raise SSHConnectionError(DUPLICATE_ERROR) from None
        except (OSError, ValueError):
            raise SSHConnectionError(STORAGE_ERROR) from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def remove(self, profile_id):
        if not isinstance(profile_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", profile_id
        ):
            raise SSHConnectionError(STORAGE_ERROR)
        try:
            self._directory()
            path = self.path / f"{profile_id}.json"
            self._read(path)
            path.unlink()
        except (OSError, ValueError):
            raise SSHConnectionError(STORAGE_ERROR) from None

    def _dismissal_path(self, host):
        # Case-insensitive OpenSSH hostname, ignoring an explicit user override.
        alias = destination(host).rsplit("@", 1)[-1].casefold()
        digest = hashlib.sha256(alias.encode()).hexdigest()
        return self.path / f".dismissed-{digest}"

    def is_dismissed(self, host):
        try:
            if not self._directory():
                return False
            path = self._dismissal_path(host)
            if not path.exists() and not path.is_symlink():
                return False
            if path.is_symlink():
                raise SSHConnectionError(STORAGE_ERROR)
            _material_file(str(path), private=True)
            if path.stat().st_size != 0:
                raise SSHConnectionError(STORAGE_ERROR)
            return True
        except (OSError, ValueError):
            raise SSHConnectionError(STORAGE_ERROR) from None

    def dismiss(self, host):
        """Persist only a hostname digest; never changes a saved trust record."""
        try:
            self._directory(create=True)
            path = self._dismissal_path(host)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if not self.is_dismissed(host):
                    raise SSHConnectionError(STORAGE_ERROR) from None
            else:
                os.close(fd)
        except (OSError, ValueError):
            raise SSHConnectionError(STORAGE_ERROR) from None
