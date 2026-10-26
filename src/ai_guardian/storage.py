"""Private application storage creation and credential-free precondition errors.

Never chmod existing directories: XDG parents may be shared or operator-managed.
Windows permissions remain controlled by the account's administrator-managed ACLs.
"""

import os
from pathlib import Path
import stat
import tempfile


class StorageError(ValueError):
    """A storage path and fixed reason, never file contents or raw OS errors."""

    def __init__(self, path: Path, reason: str):
        super().__init__(f"Application storage {str(path)!r}: {reason}")


def make_private_directory(path: Path) -> None:
    """Create every missing component as 0700, leaving existing modes untouched.

    Unlike mkdir(parents=True), this also restricts newly created ancestors.
    Creation alone is not validation; credential writers must check storage too.
    """
    try:
        path.mkdir(mode=0o700)
    except FileNotFoundError:
        make_private_directory(path.parent)
        make_private_directory(path)
    except FileExistsError:
        if not path.is_dir():
            raise StorageError(path, "not a directory") from None


def check_storage_directory(path: Path, *, missing_ok: bool = False) -> None:
    """Check configured/resolved ancestors without accepting a linked app leaf."""
    path = path.expanduser().absolute()
    try:
        if path.is_symlink():
            raise StorageError(path, "symbolic link")
        parents = {path, *path.parents, *path.resolve().parents}
        for parent in sorted(parents, key=lambda item: (len(item.parts), str(item))):
            try:
                link = parent.lstat()
                info = parent.stat()
            except FileNotFoundError:
                if missing_ok and not parent.is_symlink():
                    continue
                raise StorageError(parent, "directory unavailable") from None
            if not stat.S_ISDIR(info.st_mode):
                raise StorageError(parent, "not a directory")
            if os.name != "nt":
                if info.st_uid not in {0, os.geteuid()} or link.st_uid not in {
                    0,
                    os.geteuid(),
                }:
                    raise StorageError(parent, "untrusted directory owner")
                if info.st_mode & 0o022 and (
                    parent == path or not info.st_mode & stat.S_ISVTX
                ):
                    raise StorageError(
                        parent,
                        f"group/other-writable directory (mode {stat.S_IMODE(info.st_mode):04o})",
                    )
    except OSError:
        raise StorageError(path, "directory unavailable") from None


def check_storage_file(path: Path, *, private: bool = False) -> None:
    """Reject linked, non-regular, untrusted or exposed application material."""
    check_storage_directory(path.parent)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise StorageError(
                path, "not a regular file (symbolic links are not accepted)"
            )
        if os.name != "nt":
            if info.st_uid not in {0, os.geteuid()}:
                raise StorageError(path, "untrusted file owner")
            if info.st_mode & (0o077 if private else 0o022):
                raise StorageError(
                    path,
                    f"unsafe file permissions (mode {stat.S_IMODE(info.st_mode):04o})",
                )
    except OSError:
        raise StorageError(path, "file unavailable") from None


def write_private_text(path: Path, content: str, *, overwrite: bool = False) -> bool:
    """Atomically publish an owner-only file; preserve existing content by default."""
    check_storage_directory(path.parent, missing_ok=True)
    make_private_directory(path.parent)
    check_storage_directory(path.parent)
    if path.exists() or path.is_symlink():
        check_storage_file(path)
        if not overwrite:
            return False
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            check_storage_file(temporary, private=True)
            handle.write(content)
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                # An intervening creator must not lose their configuration.
                os.link(temporary, path)
            except FileExistsError:
                check_storage_file(path)
                return False
        return True
    finally:
        temporary.unlink(missing_ok=True)
