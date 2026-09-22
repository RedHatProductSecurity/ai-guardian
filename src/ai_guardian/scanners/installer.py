#!/usr/bin/env python3
"""
Scanner Installer for ai-guardian.

Handles automated installation and upgrade of scanner engines:
- Gitleaks
- BetterLeaks
- LeakTK
"""

import errno
import hashlib
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, cast
import sys

logger = logging.getLogger(__name__)

# Handle tomllib import for Python 3.11+ and fallback to tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        logger.error("tomli package required for Python < 3.11 but not available")
        tomllib = None

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


@contextmanager
def _interprocess_file_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive file lock across processes on Windows and Unix."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            # msvcrt locks a byte range, so make sure the first byte exists.
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()

            locking = cast(Callable[[int, int, int], None], getattr(msvcrt, "locking"))
            lock_nonblocking = cast(int, getattr(msvcrt, "LK_NBLCK"))
            lock_unlock = cast(int, getattr(msvcrt, "LK_UNLCK"))
            conflict_errnos = {errno.EACCES, getattr(errno, "EDEADLK", None)}
            while True:
                lock_file.seek(0)
                try:
                    locking(lock_file.fileno(), lock_nonblocking, 1)
                    break
                except OSError as exc:
                    if exc.errno not in conflict_errnos:
                        raise
                    time.sleep(0.1)

            try:
                yield
            finally:
                lock_file.seek(0)
                locking(lock_file.fileno(), lock_unlock, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class InstallMethod(Enum):
    """Installation method types."""

    PACKAGE_MANAGER = "package_manager"
    DIRECT_DOWNLOAD = "direct_download"
    FROM_FILE = "from_file"


class ScannerInstaller:
    """Handles installation of scanner engines."""

    # Supported scanners
    SUPPORTED_SCANNERS = [
        "gitleaks",
        "betterleaks",
        "leaktk",
        "trufflehog",
        "detect-secrets",
        "secretlint",
        "gitguardian",
    ]

    # The GitGuardian scanner is named "gitguardian" in AI Guardian config,
    # but the installed upstream executable is named "ggshield".
    BINARY_NAMES = {"gitguardian": "ggshield"}

    # License information for scanners
    SCANNER_LICENSES = {
        "gitleaks": "MIT",
        "betterleaks": "MIT",
        "leaktk": "Apache-2.0",
        "trufflehog": "AGPL-3.0",
        "detect-secrets": "Apache-2.0",
        "secretlint": "MIT",
        "gitguardian": "MIT (ggshield CLI; service terms apply)",
    }

    # Scanners NOT available via Linux distro package managers (apt/dnf/yum).
    # These are Go/Rust/Node binaries distributed via GitHub releases only.
    DOWNLOAD_ONLY_LINUX = {
        "gitleaks",
        "betterleaks",
        "leaktk",
        "trufflehog",
        "secretlint",
        "gitguardian",
    }

    # These tools are distributed as upstream release assets on every
    # supported platform; package managers may install unpinned versions.
    DIRECT_DOWNLOAD_ONLY = {"secretlint", "gitguardian"}

    # New scanners must not be installed if upstream integrity metadata is
    # unavailable. Existing scanner behavior is retained for compatibility.
    CHECKSUM_REQUIRED = {"secretlint", "gitguardian"}

    def __init__(self, install_dir: Optional[Path] = None):
        """
        Initialize scanner installer.

        Args:
            install_dir: Directory to install scanners. Platform defaults:
                - Windows: %LOCALAPPDATA%\\ai-guardian\\bin
                - Unix: /usr/local/bin (fallback: ~/.local/bin)
        """
        if install_dir:
            self.install_dir = install_dir
            self.install_dir.mkdir(parents=True, exist_ok=True)
        elif sys.platform == "win32":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                self.install_dir = Path(local_app_data) / "ai-guardian" / "bin"
            else:
                self.install_dir = (
                    Path.home() / "AppData" / "Local" / "ai-guardian" / "bin"
                )
            self.install_dir.mkdir(parents=True, exist_ok=True)
        else:
            default_dir = Path("/usr/local/bin")
            if default_dir.exists() and os.access(default_dir, os.W_OK):
                self.install_dir = default_dir
            else:
                try:
                    default_dir.mkdir(parents=True, exist_ok=True)
                    if os.access(default_dir, os.W_OK):
                        self.install_dir = default_dir
                except PermissionError:
                    pass  # intentionally silent — best-effort operation

            if not hasattr(self, "install_dir"):
                logger.warning(
                    "No permission to write to /usr/local/bin, using ~/.local/bin instead"
                )
                self.install_dir = Path.home() / ".local" / "bin"
                self.install_dir.mkdir(parents=True, exist_ok=True)

        self.scanner_config = self._load_scanner_config()

    def _get_binary_name(self, scanner_name: str) -> str:
        """Return the platform-specific command name used to launch a scanner."""
        binary_name = self.BINARY_NAMES.get(scanner_name, scanner_name)
        if sys.platform == "win32":
            if scanner_name == "gitguardian":
                return f"{binary_name}.cmd"
            return f"{binary_name}.exe"
        return binary_name

    def _find_installed_binary(self, scanner_name: str) -> Optional[str]:
        """Find a scanner executable on PATH or in the configured install dir."""
        binary_name = self._get_binary_name(scanner_name)
        binary_path = shutil.which(binary_name)
        if binary_path:
            return binary_path

        candidate = self.install_dir / binary_name
        return str(candidate) if candidate.exists() else None

    def _load_scanner_config(self) -> Dict[str, Any]:
        """
        Load scanner configuration from pyproject.toml.

        Returns:
            Scanner configuration dict with versions and repos
        """
        if tomllib is None:
            logger.warning("tomllib not available, using fallback configuration")
            return {
                "gitleaks": "8.30.1",
                "betterleaks": "1.3.1",
                "leaktk": "0.3.4",
                "trufflehog": "3.88.0",
                "detect-secrets": "1.5.0",
                "secretlint": "13.0.5",
                "gitguardian": "1.54.0",
                "repos": {
                    "gitleaks": "gitleaks/gitleaks",
                    "betterleaks": "betterleaks/betterleaks",
                    "leaktk": "leaktk/leaktk",
                    "trufflehog": "trufflesecurity/trufflehog",
                    "detect-secrets": "Yelp/detect-secrets",
                    "secretlint": "secretlint/secretlint",
                    "gitguardian": "GitGuardian/ggshield",
                },
            }

        # Try bundled pyproject.toml first (installed via wheel),
        # then fall back to development path (editable install)
        candidates = [
            Path(__file__).parent.parent / "pyproject.toml",
            Path(__file__).parent.parent.parent.parent / "pyproject.toml",
        ]

        for pyproject_path in candidates:
            if pyproject_path.exists():
                try:
                    with open(pyproject_path, "rb") as f:
                        data = tomllib.load(f)
                    config = (
                        data.get("tool", {}).get("ai-guardian", {}).get("scanners", {})
                    )
                    if config:
                        return config
                except Exception as e:
                    logger.warning(
                        f"Failed to load scanner config from {pyproject_path}: {e}"
                    )

        logger.warning("pyproject.toml not found in any expected location")
        return {}

    def get_github_repo(self, scanner_name: str) -> str:
        """
        Get GitHub repository from pyproject.toml.

        Args:
            scanner_name: Scanner name (gitleaks, betterleaks, leaktk)

        Returns:
            GitHub repository in format "owner/repo"
        """
        repos = self.scanner_config.get("repos", {})
        return repos.get(scanner_name, f"{scanner_name}/{scanner_name}")

    def get_pattern_servers(self) -> Dict[str, Any]:
        """
        Get pattern server configuration from pyproject.toml.

        Returns:
            Dict of pattern server configs keyed by name
        """
        return self.scanner_config.get("pattern_servers", {})

    def get_pinned_version(self, scanner_name: str) -> str:
        """
        Get pinned version from pyproject.toml.

        Args:
            scanner_name: Scanner name

        Returns:
            Version string (without 'v' prefix)
        """
        version = self.scanner_config.get(scanner_name, "unknown")
        # Remove 'v' prefix if present
        if version.startswith("v"):
            version = version[1:]
        return version

    def detect_platform(self) -> str:
        """
        Detect platform architecture (e.g., darwin_arm64).

        Returns:
            Platform string in format "system_arch"
        """
        system = platform.system().lower()
        machine = platform.machine().lower()

        # Architecture normalization
        arch_map = {
            "x86_64": "x64",
            "amd64": "x64",
            "aarch64": "arm64",
            "arm64": "arm64",
            "armv7l": "armv7",
            "armv6l": "armv6",
            "i686": "x32",
            "i386": "x32",
        }

        arch = arch_map.get(machine, machine)
        return f"{system}_{arch}"

    def get_latest_version(self, scanner_name: str) -> str:
        """
        Fetch latest version from GitHub releases API.

        Args:
            scanner_name: Scanner name

        Returns:
            Latest version string (without 'v' prefix)
        """
        if not HAS_REQUESTS:
            logger.warning(
                "requests library not available, using pinned version from pyproject.toml"
            )
            return self.get_pinned_version(scanner_name)

        repo = self.get_github_repo(scanner_name)
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"

        try:
            response = requests.get(api_url, timeout=5)
            response.raise_for_status()
            version = response.json()["tag_name"]
            # Remove 'v' prefix if present
            if version.startswith("v"):
                version = version[1:]
            logger.info(f"Latest version of {scanner_name} from GitHub: {version}")
            return version
        except Exception as e:
            logger.warning(f"Failed to fetch latest version from GitHub: {e}")
            logger.info("Falling back to pinned version from pyproject.toml")
            return self.get_pinned_version(scanner_name)

    def install_via_package_manager(self, scanner_name: str) -> bool:
        """
        Try to install via system package manager.

        Args:
            scanner_name: Scanner to install

        Returns:
            True if installation succeeded, False otherwise
        """
        system = platform.system().lower()

        if scanner_name in self.DIRECT_DOWNLOAD_ONLY:
            logger.debug(
                f"{scanner_name} uses pinned upstream release assets, skipping package managers"
            )
            return False

        try:
            # detect-secrets is a Python package - use pip
            if scanner_name == "detect-secrets":
                # Try pip3 first, then pip
                pip_cmd = None
                if shutil.which("pip3"):
                    pip_cmd = "pip3"
                elif shutil.which("pip"):
                    pip_cmd = "pip"

                if pip_cmd:
                    logger.info(f"Installing {scanner_name} via {pip_cmd}...")
                    result = subprocess.run(
                        [pip_cmd, "install", scanner_name],
                        capture_output=True,
                        timeout=300,
                    )
                    return result.returncode == 0
                else:
                    logger.warning("pip/pip3 not found, cannot install detect-secrets")
                    return False
            # TruffleHog on macOS - use Homebrew with tap
            elif (
                scanner_name == "trufflehog"
                and system == "darwin"
                and shutil.which("brew")
            ):
                logger.info(f"Installing {scanner_name} via Homebrew...")
                result = subprocess.run(
                    ["brew", "install", "trufflesecurity/trufflehog/trufflehog"],
                    capture_output=True,
                    timeout=300,
                )
                return result.returncode == 0
            elif system == "darwin" and shutil.which("brew"):
                logger.info(f"Installing {scanner_name} via Homebrew...")
                result = subprocess.run(
                    ["brew", "install", scanner_name],
                    capture_output=True,
                    timeout=300,
                )
                return result.returncode == 0
            elif system == "linux":
                if scanner_name in self.DOWNLOAD_ONLY_LINUX:
                    logger.debug(
                        f"{scanner_name} is not available via Linux package managers, skipping"
                    )
                    return False
                if shutil.which("dnf"):
                    logger.info(f"Installing {scanner_name} via dnf...")
                    result = subprocess.run(
                        ["sudo", "dnf", "install", "-y", scanner_name],
                        capture_output=True,
                        timeout=300,
                    )
                    return result.returncode == 0
                elif shutil.which("apt-get"):
                    logger.info(f"Installing {scanner_name} via apt-get...")
                    result = subprocess.run(
                        ["sudo", "apt-get", "install", "-y", scanner_name],
                        capture_output=True,
                        timeout=300,
                    )
                    return result.returncode == 0
                elif shutil.which("yum"):
                    logger.info(f"Installing {scanner_name} via yum...")
                    result = subprocess.run(
                        ["sudo", "yum", "install", "-y", scanner_name],
                        capture_output=True,
                        timeout=300,
                    )
                    return result.returncode == 0
            elif system == "windows" and shutil.which("choco"):
                logger.info(f"Installing {scanner_name} via Chocolatey...")
                result = subprocess.run(
                    ["choco", "install", "-y", scanner_name],
                    capture_output=True,
                    timeout=300,
                )
                return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("Package manager installation timed out")
            return False
        except Exception as e:
            logger.debug(f"Package manager installation failed: {e}")
            return False

        logger.debug(f"No package manager available for {system}")
        return False

    @staticmethod
    def _download_with_retry(
        url: str, timeout: int = 60, max_attempts: int = 3
    ) -> "requests.Response":
        """Download a URL with retry and exponential backoff.

        Args:
            url: URL to download
            timeout: Request timeout in seconds
            max_attempts: Maximum number of attempts

        Returns:
            requests.Response object

        Raises:
            RuntimeError: If all attempts fail
        """
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                return response
            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    wait = attempt * 2
                    logger.warning(
                        f"Download attempt {attempt}/{max_attempts} failed for "
                        f"{url}: {e}. Retrying in {wait}s..."
                    )
                    time.sleep(wait)
        raise RuntimeError(
            f"Failed to download {url} after {max_attempts} attempts: {last_error}"
        )

    def _download_checksums(
        self,
        scanner_name: str,
        version: str,
        repo: str,
        asset_filename: Optional[str] = None,
    ) -> Optional[str]:
        """
        Download checksums file from GitHub releases.

        Args:
            scanner_name: Scanner name
            version: Version to download checksums for
            repo: GitHub repository (owner/repo)
            asset_filename: Release asset to verify when GitHub provides a digest

        Returns:
            Contents of checksums file as string, or None if download fails
        """
        if not HAS_REQUESTS:
            logger.warning(
                "requests library not available, skipping checksum verification"
            )
            return None

        if scanner_name == "gitguardian":
            if not asset_filename:
                logger.warning("GitGuardian checksum lookup requires the asset name")
                return None

            release_url = (
                f"https://api.github.com/repos/{repo}/releases/tags/v{version}"
            )
            try:
                response = self._download_with_retry(release_url, timeout=30)
                assets = response.json().get("assets", [])
                asset = next(
                    (item for item in assets if item.get("name") == asset_filename),
                    None,
                )
                digest = asset.get("digest", "") if asset else ""
                if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
                    logger.warning(
                        "GitGuardian release does not provide a SHA-256 asset digest"
                    )
                    return None
                return f"{digest.split(':', 1)[1]}  {asset_filename}"
            except Exception as e:
                logger.warning(f"Failed to fetch GitGuardian asset digest: {e}")
                return None

        # Different scanners have different checksums file naming conventions
        # gitleaks: gitleaks_8.30.1_checksums.txt
        # betterleaks: checksums.txt (no version!)
        # leaktk: leaktk_0.2.10_checksums.txt
        if scanner_name == "secretlint":
            checksums_filename = f"secretlint-{version}-sha256sum.txt"
        elif scanner_name == "betterleaks":
            checksums_filename = "checksums.txt"
        else:
            checksums_filename = f"{scanner_name}_{version}_checksums.txt"

        checksums_url = f"https://github.com/{repo}/releases/download/v{version}/{checksums_filename}"

        try:
            logger.info(f"Downloading checksums from {checksums_url}")
            response = self._download_with_retry(checksums_url, timeout=30)

            # Validate content is not empty or malformed
            content = response.text.strip()
            if not content or len(content) < 64:  # SHA-256 is 64 chars minimum
                logger.warning("Invalid or empty checksums file received")
                return None

            return content
        except Exception as e:
            logger.warning(f"Failed to download checksums file: {e}")
            logger.warning("Checksum verification will be skipped")
            return None

    def _verify_checksum(
        self, file_path: Path, checksums_content: str, filename: str
    ) -> None:
        """
        Verify SHA-256 checksum of downloaded file.

        Args:
            file_path: Path to file to verify
            checksums_content: Contents of checksums file
            filename: Name of file being verified (for lookup in checksums)

        Raises:
            RuntimeError: If checksum verification fails
        """
        # Compute SHA-256 hash of downloaded file
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files efficiently
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        computed_hash = sha256_hash.hexdigest()
        logger.info(f"Computed SHA-256: {computed_hash}")

        # Parse checksums file and look for our hash
        # Format is typically: "<hash>  <filename>" or "<hash> <filename>"
        checksums_lines = checksums_content.strip().split("\n")
        found = False

        for line in checksums_lines:
            # Skip empty lines
            if not line.strip():
                continue

            # Split on whitespace (handles both single and double space)
            parts = line.split()
            if len(parts) < 2:
                continue

            file_hash = parts[0].lower()
            file_name_part = parts[-1]  # Take last part as filename
            # Handle binary mode indicator (*filename) from sha256sum
            if file_name_part.startswith("*"):
                file_name = file_name_part[1:]  # Strip asterisk
            else:
                file_name = file_name_part
            # Sanitize: ensure no path traversal
            file_name = os.path.basename(file_name)

            # Check if this line matches our file
            if file_name == filename and file_hash == computed_hash.lower():
                found = True
                logger.info(f"✓ Checksum verification passed for {filename}")
                break

        if not found:
            raise RuntimeError(
                f"Checksum verification failed for {filename}\n"
                f"Computed hash: {computed_hash}\n"
                f"Hash not found in checksums file. This may indicate:\n"
                f"  - A compromised download (MITM attack)\n"
                f"  - Corrupted download\n"
                f"  - Mismatch between binary and checksums file versions\n"
                f"For security reasons, installation has been aborted."
            )

    @staticmethod
    def _safe_extract_tar(tar_ref: tarfile.TarFile, extract_dir: Path) -> None:
        """Extract tar archive with path traversal protection."""
        resolved_dir = str(extract_dir.resolve())
        for member in tar_ref.getmembers():
            member_path = (extract_dir / member.name).resolve()
            if (
                not str(member_path).startswith(resolved_dir + os.sep)
                and str(member_path) != resolved_dir
            ):
                raise RuntimeError(f"Path traversal detected in archive: {member.name}")
        if sys.version_info >= (3, 12):
            tar_ref.extractall(extract_dir, filter="data")
        else:
            tar_ref.extractall(extract_dir)

    @staticmethod
    def _safe_extract_zip(zip_ref: zipfile.ZipFile, extract_dir: Path) -> None:
        """Extract zip archive with path traversal protection."""
        resolved_dir = str(extract_dir.resolve())
        for info in zip_ref.infolist():
            member_path = (extract_dir / info.filename).resolve()
            if (
                not str(member_path).startswith(resolved_dir + os.sep)
                and str(member_path) != resolved_dir
            ):
                raise RuntimeError(
                    f"Path traversal detected in archive: {info.filename}"
                )
        zip_ref.extractall(extract_dir)

    def install_from_download(
        self, scanner_name: str, version: Optional[str] = None
    ) -> Path:
        """
        Download and install scanner binary from GitHub releases.

        Args:
            scanner_name: Scanner to install
            version: Specific version to install (optional, uses latest if not provided)

        Returns:
            Path to installed binary

        Raises:
            RuntimeError: If installation fails
        """
        # detect-secrets is pip-only, no binary releases
        if scanner_name == "detect-secrets":
            raise RuntimeError(
                f"{scanner_name} is a Python package and must be installed via pip:\n"
                f"  pip install detect-secrets\n"
                f"Direct download is not available for this scanner."
            )

        if not HAS_REQUESTS:
            raise RuntimeError(
                "requests library required for downloading scanners but not available"
            )

        # Determine version to install
        version = version or self.get_latest_version(scanner_name)

        # Validate version format before using in URLs
        if not re.match(r"^\d+\.\d+\.\d+$", version):
            raise ValueError(f"Invalid version format: {version}")

        # Detect platform
        platform_arch = self.detect_platform()
        logger.info(f"Detected platform: {platform_arch}")

        # Build download URL
        repo = self.get_github_repo(scanner_name)
        system = platform_arch.split("_")[0]
        arch = platform_arch.split("_")[1]

        # Determine file extension and binary name.
        binary_name = self._get_binary_name(scanner_name)
        archive_binary_name = self.BINARY_NAMES.get(scanner_name, scanner_name)
        if system == "windows":
            archive_binary_name += ".exe"
        archive_format: Optional[str]

        # Build filename - different scanners have different naming conventions
        # gitleaks/betterleaks: scanner_version_platform_arch.ext (e.g., gitleaks_8.30.1_darwin_arm64.tar.gz)
        # leaktk: scanner-version-platform-arch.ext (e.g., leaktk-0.2.10-darwin-arm64.tar.xz) with x86_64 instead of x64
        # trufflehog: scanner_version_system_arch.ext (e.g., trufflehog_3.88.0_linux_amd64.tar.gz) with amd64 instead of x64
        if scanner_name == "secretlint":
            supported_arches = {
                "linux": {"x64", "arm64"},
                "darwin": {"x64", "arm64"},
                "windows": {"x64"},
            }
            if arch not in supported_arches.get(system, set()):
                raise RuntimeError(
                    f"Secretlint does not publish an asset for {platform_arch}"
                )
            ext = ".exe" if system == "windows" else ""
            filename = f"secretlint-{version}-{system}-{arch}{ext}"
            archive_format = None
        elif scanner_name == "gitguardian":
            if system == "linux":
                gg_arch = {"x64": "x86_64", "arm64": "aarch64"}.get(arch)
                if not gg_arch:
                    raise RuntimeError(
                        f"GitGuardian does not publish an asset for {platform_arch}"
                    )
                filename = f"ggshield-{version}-{gg_arch}-unknown-linux-gnu.tar.gz"
                archive_format = "tar.gz"
            elif system == "darwin":
                gg_arch = {"x64": "x86_64", "arm64": "arm64"}.get(arch)
                if not gg_arch:
                    raise RuntimeError(
                        f"GitGuardian does not publish an asset for {platform_arch}"
                    )
                filename = f"ggshield-{version}-{gg_arch}-apple-darwin.tar.gz"
                archive_format = "tar.gz"
            elif system == "windows" and arch == "x64":
                filename = f"ggshield-{version}-x86_64-pc-windows-msvc.zip"
                archive_format = "zip"
            else:
                raise RuntimeError(
                    f"GitGuardian does not publish an asset for {platform_arch}"
                )
        elif scanner_name == "leaktk":
            # leaktk uses hyphens and x86_64 instead of x64
            leaktk_arch = "x86_64" if arch == "x64" else arch
            ext = "tar.xz" if system != "windows" else "zip"
            filename = f"{scanner_name}-{version}-{system}-{leaktk_arch}.{ext}"
            archive_format = ext
        elif scanner_name == "trufflehog":
            # trufflehog uses amd64 instead of x64
            trufflehog_arch = "amd64" if arch == "x64" else arch
            ext = "zip" if system == "windows" else "tar.gz"
            filename = f"{scanner_name}_{version}_{system}_{trufflehog_arch}.{ext}"
            archive_format = ext
        else:
            # gitleaks and betterleaks use underscores
            ext = "zip" if system == "windows" else "tar.gz"
            filename = f"{scanner_name}_{version}_{platform_arch}.{ext}"
            archive_format = ext

        download_url = (
            f"https://github.com/{repo}/releases/download/v{version}/{filename}"
        )

        logger.info(f"Downloading {scanner_name} {version} from {download_url}")

        # Download to temporary file
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / filename

            try:
                response = self._download_with_retry(download_url, timeout=60)

                with open(archive_path, "wb") as f:
                    f.write(response.content)

                logger.info(f"Downloaded {archive_path.stat().st_size} bytes")

                # Download and verify checksums
                checksums_content = self._download_checksums(
                    scanner_name, version, repo, filename
                )
                if checksums_content:
                    self._verify_checksum(archive_path, checksums_content, filename)
                    print(
                        f"✓ Checksum verification passed for {scanner_name} {version}"
                    )
                else:
                    if scanner_name in self.CHECKSUM_REQUIRED:
                        raise RuntimeError(
                            f"Checksum verification is required for {scanner_name}, "
                            "but upstream integrity metadata is unavailable"
                        )
                    print(
                        "⚠ Checksum verification skipped - checksums file not available"
                    )
                    logger.warning(
                        "Checksum verification skipped - checksums file not available"
                    )

                if archive_format is None:
                    # Secretlint's release asset is the standalone executable.
                    binary_path = archive_path
                else:
                    # Extract archives with path traversal protection.
                    extract_dir = temp_path / "extract"
                    extract_dir.mkdir()

                    if archive_format == "zip":
                        with zipfile.ZipFile(archive_path, "r") as zip_ref:
                            self._safe_extract_zip(zip_ref, extract_dir)
                    elif archive_format == "tar.xz":
                        with tarfile.open(archive_path, "r:xz") as tar_ref:
                            self._safe_extract_tar(tar_ref, extract_dir)
                    elif archive_format == "tar.gz":
                        with tarfile.open(archive_path, "r:gz") as tar_ref:
                            self._safe_extract_tar(tar_ref, extract_dir)
                    else:
                        raise RuntimeError(
                            f"Unsupported archive format: {archive_format}"
                        )

                    # Find the binary in extracted files.
                    binary_path = None
                    for path in extract_dir.rglob(archive_binary_name):
                        if path.is_file():
                            binary_path = path
                            break

                if not binary_path:
                    archive_contents = (
                        list(extract_dir.rglob("*"))
                        if archive_format is not None
                        else []
                    )
                    raise RuntimeError(
                        f"Binary '{binary_name}' not found in archive. "
                        f"Archive contents: {archive_contents}"
                    )

                if scanner_name == "gitguardian":
                    # Recent ggshield release archives are complete application
                    # bundles, not standalone executables. Keep the companion
                    # Python runtime and its _internal directory beside ggshield.
                    target_path = self._install_gitguardian_bundle(
                        binary_path.parent, archive_binary_name, version, system
                    )
                else:
                    target_path = self.install_dir / binary_name
                    shutil.copy2(binary_path, target_path)

                    # Make executable (Unix)
                    if system != "windows":
                        target_path.chmod(0o755)

                logger.info(f"Installed {scanner_name} to {target_path}")
                print(f"✓ Installed {scanner_name} {version} to {target_path}")

                return target_path

            except (tarfile.TarError, zipfile.BadZipFile) as e:
                raise RuntimeError(f"Failed to extract archive: {e}") from e
            except Exception as e:
                # Catch all download/network errors
                raise RuntimeError(
                    f"Failed to download {scanner_name} from {download_url}: {e}"
                ) from e

    def _install_gitguardian_bundle(
        self, bundle_source: Path, binary_name: str, version: str, system: str
    ) -> Path:
        """Serialize bundle staging, publication, and cleanup across processes."""
        lock_path = self.install_dir / ".ai-guardian" / "gitguardian-install.lock"
        with _interprocess_file_lock(lock_path):
            return self._install_gitguardian_bundle_locked(
                bundle_source, binary_name, version, system
            )

    def _install_gitguardian_bundle_locked(
        self, bundle_source: Path, binary_name: str, version: str, system: str
    ) -> Path:
        """Install ggshield's bundle while the shared install lock is held."""
        if system == "windows":
            bundle_parent = self.install_dir / ".ai-guardian" / "gitguardian"
            bundle_parent.mkdir(parents=True, exist_ok=True)
            bundle_dir = Path(tempfile.mkdtemp(prefix=f"{version}-", dir=bundle_parent))
            launcher_path = self.install_dir / f"{Path(binary_name).stem}.cmd"
            wrapper_path: Optional[Path] = None

            try:
                # Stage into a new version-specific directory. The active
                # command wrapper is not replaced until every bundle file is
                # safely in place, so a failed copy leaves the old install
                # available and cannot overwrite shared-path entries such as
                # _internal.
                shutil.copytree(
                    bundle_source, bundle_dir, dirs_exist_ok=True, symlinks=True
                )
                bundle_binary = bundle_dir / binary_name
                if not bundle_binary.is_file():
                    raise RuntimeError(
                        f"GitGuardian bundle is missing its launcher: {bundle_binary}"
                    )

                relative_binary = os.path.relpath(bundle_binary, self.install_dir)
                relative_binary = relative_binary.replace("/", "\\")
                wrapper = (
                    "@echo off\r\n"
                    f'call "%~dp0{relative_binary}" %*\r\n'
                    "exit /b %ERRORLEVEL%\r\n"
                )
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    prefix=f".{launcher_path.name}.",
                    dir=self.install_dir,
                    delete=False,
                ) as wrapper_file:
                    wrapper_path = Path(wrapper_file.name)
                    wrapper_file.write(wrapper)
                os.replace(wrapper_path, launcher_path)
            except Exception:
                if wrapper_path and wrapper_path.exists():
                    try:
                        wrapper_path.unlink()
                    except OSError as cleanup_error:
                        logger.warning(
                            "Could not remove staged ggshield launcher %s: %s",
                            wrapper_path,
                            cleanup_error,
                        )
                try:
                    shutil.rmtree(bundle_dir)
                except OSError as cleanup_error:
                    logger.warning(
                        "Could not remove incomplete ggshield bundle %s: %s",
                        bundle_dir,
                        cleanup_error,
                    )
                raise

            # The new wrapper is active now. Remove older managed bundles only
            # after the complete replacement has succeeded.
            for old_bundle in bundle_parent.iterdir():
                if old_bundle == bundle_dir:
                    continue
                try:
                    if old_bundle.is_symlink() or old_bundle.is_file():
                        old_bundle.unlink()
                    elif old_bundle.is_dir():
                        shutil.rmtree(old_bundle)
                except OSError as cleanup_error:
                    logger.warning(
                        "Could not remove old ggshield bundle %s: %s",
                        old_bundle,
                        cleanup_error,
                    )
            return launcher_path

        bundle_parent = self.install_dir / ".ai-guardian" / "gitguardian"
        bundle_parent.mkdir(parents=True, exist_ok=True)
        bundle_dir = bundle_parent / version

        # Stage the complete bundle next to its destination so it stays on the
        # same filesystem when moved into place.
        with tempfile.TemporaryDirectory(
            prefix=f".{version}-", dir=bundle_parent
        ) as staging_name:
            staging_dir = Path(staging_name)
            shutil.copytree(
                bundle_source, staging_dir, dirs_exist_ok=True, symlinks=True
            )
            if bundle_dir.is_symlink():
                bundle_dir.unlink()
            elif bundle_dir.exists():
                shutil.rmtree(bundle_dir)
            os.replace(staging_dir, bundle_dir)

        bundle_binary = bundle_dir / binary_name
        if not bundle_binary.is_file():
            raise RuntimeError(
                f"GitGuardian bundle is missing its launcher: {bundle_binary}"
            )
        bundle_binary.chmod(bundle_binary.stat().st_mode | 0o111)

        # The lightweight upstream launcher resolves its bundled runtime next
        # to the real executable, so this shell shim must exec that path rather
        # than copy the launcher into the shared scanner bin directory.
        target_path = self.install_dir / binary_name
        wrapper = "#!/bin/sh\n" f'exec {shlex.quote(str(bundle_binary))} "$@"\n'
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{binary_name}.",
            dir=self.install_dir,
            delete=False,
        ) as wrapper_file:
            wrapper_file.write(wrapper)
        wrapper_path = Path(wrapper_file.name)
        wrapper_path.chmod(0o755)
        os.replace(wrapper_path, target_path)

        # Keep only the active version so repeated scanner upgrades do not
        # leave multi-megabyte ggshield runtimes behind.
        for old_bundle in bundle_parent.iterdir():
            if old_bundle == bundle_dir or not re.fullmatch(
                r"\d+\.\d+\.\d+", old_bundle.name
            ):
                continue
            try:
                if old_bundle.is_symlink() or old_bundle.is_file():
                    old_bundle.unlink()
                elif old_bundle.is_dir():
                    shutil.rmtree(old_bundle)
            except OSError as exc:
                logger.warning(
                    "Could not remove old ggshield bundle %s: %s", old_bundle, exc
                )

        return target_path

    def install(
        self,
        scanner_name: str,
        version: Optional[str] = None,
        use_pinned: bool = False,
        method: Optional[InstallMethod] = None,
        ensure_only: bool = False,
    ) -> bool:
        """
        Install scanner using best available method.

        Args:
            scanner_name: Scanner to install (gitleaks, betterleaks, leaktk)
            version: Specific version to install (optional)
            use_pinned: Use version from pyproject.toml (fallback)
            method: Installation method (optional)
            ensure_only: If True, accept any working installation without upgrading

        Returns:
            True if installation succeeded

        Version selection priority:
            1. --version flag (explicit)
            2. GitHub API latest (default)
            3. pyproject.toml pinned version (fallback)
        """
        if scanner_name not in self.SUPPORTED_SCANNERS:
            raise ValueError(
                f"Unsupported scanner: {scanner_name}. "
                f"Supported: {', '.join(self.SUPPORTED_SCANNERS)}"
            )

        # Show license notice for AGPL-3.0 scanners
        if scanner_name == "trufflehog":
            print()
            print("=" * 70)
            print("⚠️  LICENSE NOTICE: TruffleHog")
            print("=" * 70)
            print()
            print(
                "TruffleHog is licensed under AGPL-3.0 (GNU Affero General Public License)."
            )
            print()
            print(
                "AI Guardian uses TruffleHog as an EXTERNAL TOOL via subprocess execution,"
            )
            print(
                "which does NOT create a derivative work or require AGPL compliance for"
            )
            print("AI Guardian itself (similar to how Apache projects can invoke Git).")
            print()
            print("However, you should be aware of TruffleHog's license terms:")
            print("  - License: AGPL-3.0 (copyleft)")
            print("  - Repository: https://github.com/trufflesecurity/trufflehog")
            print(
                "  - License text: https://github.com/trufflesecurity/trufflehog/blob/main/LICENSE"
            )
            print()
            print("By proceeding with this installation, you acknowledge TruffleHog's")
            print("AGPL-3.0 license and agree to its terms.")
            print()
            print("=" * 70)
            print()

            # Prompt for confirmation
            try:
                response = (
                    input("Continue with TruffleHog installation? (y/N): ")
                    .strip()
                    .lower()
                )
                if response not in ["y", "yes"]:
                    print("Installation cancelled.")
                    return False
            except (EOFError, KeyboardInterrupt):
                print("\nInstallation cancelled.")
                return False
            print()

        # Determine target version
        if version:
            # Explicit version specified
            target_version = version
            logger.info(f"Installing {scanner_name} {version} (explicitly specified)")
        elif use_pinned:
            # Use pinned version from pyproject.toml
            target_version = self.get_pinned_version(scanner_name)
            logger.info(f"Installing {scanner_name} {target_version} (pinned version)")
        else:
            # Try to fetch latest from GitHub (with fallback to pinned)
            target_version = self.get_latest_version(scanner_name)
            logger.info(f"Installing {scanner_name} {target_version}")

        # Check if already installed
        installed_version = self._get_installed_version(scanner_name)

        if installed_version and ensure_only:
            binary_path = self._find_installed_binary(scanner_name) or (
                self.install_dir / self._get_binary_name(scanner_name)
            )
            print(f"✓ {scanner_name} {installed_version} is already installed")
            print(f"  Path: {binary_path}")
            return True

        if installed_version:
            comparison = self._compare_versions(installed_version, target_version)

            if comparison == 0 and not version:
                # Already up-to-date, skip installation
                binary_path = self._find_installed_binary(scanner_name) or (
                    self.install_dir / self._get_binary_name(scanner_name)
                )
                print(
                    f"✓ {scanner_name} {installed_version} is already installed (up-to-date)"
                )
                print(f"  Path: {binary_path}")
                print()
                print("No action needed.")
                return True
            elif comparison < 0:
                # Installed version is older, upgrade available
                print(f"Current version: {installed_version}")
                print(f"Latest version:  {target_version}")
                print()
                print(
                    f"Upgrading {scanner_name} from {installed_version} to {target_version}..."
                )
            elif comparison > 0 and not version:
                # Installed version is newer, don't auto-downgrade
                binary_path = self._find_installed_binary(scanner_name) or (
                    self.install_dir / self._get_binary_name(scanner_name)
                )
                print(f"✓ {scanner_name} {installed_version} is already installed")
                print(f"  Path: {binary_path}")
                print()
                print(f"Latest version available: {target_version}")
                print(
                    f"To downgrade, use: ai-guardian scanner install {scanner_name} --version {target_version}"
                )
                return True
            else:
                # Explicit version specified: allow downgrade/reinstall
                if comparison == 0:
                    action = "Reinstalling"
                elif comparison > 0:
                    action = "Downgrading"
                else:
                    action = "Upgrading"
                print(f"{action} {scanner_name} to {target_version}...")

        # Try package manager first, but only for fresh installs.
        # When the scanner is already installed, skip package manager
        # to avoid unnecessary sudo prompts on Linux.
        scanner_already_available = installed_version or self._find_installed_binary(
            scanner_name
        )
        if (
            method is None or method == InstallMethod.PACKAGE_MANAGER
        ) and not scanner_already_available:
            if self.install_via_package_manager(scanner_name):
                # Verify installed version matches request
                installed_version = self._get_installed_version(scanner_name)
                if (
                    installed_version
                    and self._compare_versions(installed_version, target_version) == 0
                ):
                    print(f"✓ Installed {scanner_name} via package manager")
                    return True
                else:
                    # Version mismatch - package manager installed wrong version
                    if installed_version:
                        print(
                            f"⚠️  Package manager installed {scanner_name} {installed_version}, but {target_version} was requested"
                        )
                    else:
                        print(
                            "⚠️  Package manager installation succeeded but version verification failed"
                        )
                    print(
                        f"Falling back to direct download for {scanner_name} {target_version}..."
                    )
                    # Fall through to direct download

        # Fallback to direct download with determined version
        if method is None or method == InstallMethod.DIRECT_DOWNLOAD:
            try:
                self.install_from_download(scanner_name, target_version)
                return True
            except Exception as e:
                logger.error(f"Failed to install {scanner_name}: {e}")
                return False

        return False

    def _get_installed_version(self, scanner_name: str) -> Optional[str]:
        """
        Get the currently installed version of a scanner.

        Args:
            scanner_name: Scanner to check

        Returns:
            Version string (without 'v' prefix) if installed, None otherwise
        """
        binary_path = self._find_installed_binary(scanner_name)
        if not binary_path:
            return None

        # Different scanners have different version commands
        # gitleaks, betterleaks, leaktk, trufflehog: <binary> version
        # detect-secrets: <binary> --version
        version_commands = [
            [binary_path, "version"],  # Try subcommand first
            [binary_path, "--version"],  # Fallback to flag
        ]

        # Try to get version
        for cmd in version_commands:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=5,
                    text=True,
                )
                if result.returncode == 0:
                    # Parse version from output
                    # Expected formats:
                    # - "gitleaks version 8.30.1"
                    # - "detect-secrets 1.5.0"
                    # - "8.30.1"
                    # - "v8.30.1"
                    output = result.stdout.strip()

                    # Extract version number
                    import re

                    # Match semantic version pattern
                    match = re.search(r"v?(\d+\.\d+\.\d+)", output)
                    if match:
                        return match.group(1)

                    logger.debug(f"Could not parse version from output: {output}")
                    # Try next command
                    continue
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
                logger.debug(f"Failed to run {cmd}: {e}")
                continue

        logger.debug(f"Failed to get version for {scanner_name}")
        return None

    def _compare_versions(self, version1: str, version2: str) -> int:
        """
        Compare two semantic versions.

        Args:
            version1: First version string (e.g., "8.30.1")
            version2: Second version string (e.g., "8.31.0")

        Returns:
            -1 if version1 < version2
             0 if version1 == version2
             1 if version1 > version2
        """

        # Parse version strings
        def parse_version(v: str) -> tuple:
            parts = v.strip().lstrip("v").split(".")
            return tuple(int(p) for p in parts)

        try:
            v1_parts = parse_version(version1)
            v2_parts = parse_version(version2)

            if v1_parts < v2_parts:
                return -1
            elif v1_parts > v2_parts:
                return 1
            else:
                return 0
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to compare versions {version1} and {version2}: {e}")
            # If parsing fails, treat as equal (no upgrade/downgrade)
            return 0

    def verify_installation(self, scanner_name: str) -> bool:
        """
        Verify scanner is installed and working.

        Args:
            scanner_name: Scanner to verify

        Returns:
            True if scanner is installed and working
        """
        binary_path = self._find_installed_binary(scanner_name)
        if not binary_path:
            return False

        # Try both version command formats
        version_commands = [
            [binary_path, "version"],  # Try subcommand first
            [binary_path, "--version"],  # Fallback to flag
        ]

        for cmd in version_commands:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

        return False
