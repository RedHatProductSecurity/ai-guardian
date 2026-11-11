#!/usr/bin/env python3
"""Build the separate minimal daemon wheel and source distribution."""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAEMON_PACKAGING = ROOT / "packaging" / "daemon"


def _project_version() -> str:
    """Read and cross-check the package version used for the daemon artifact."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_section = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", pyproject)
    if project_section is None:
        raise ValueError("The root pyproject.toml has no [project] section")
    version_match = re.search(
        r'(?m)^version\s*=\s*[\'"]([^\'"]+)[\'"]\s*$', project_section.group(1)
    )
    source_version_match = re.search(
        r'(?m)^__version__\s*=\s*[\'"]([^\'"]+)[\'"]\s*$',
        (ROOT / "src" / "ai_guardian" / "__init__.py").read_text(encoding="utf-8"),
    )
    if version_match is None or source_version_match is None:
        raise ValueError("Could not determine the project and package versions")
    if version_match.group(1) != source_version_match.group(1):
        raise ValueError("pyproject.toml and ai_guardian.__version__ do not match")
    return version_match.group(1)


def prepare_daemon_project(staging_dir: Path) -> Path:
    """Stage shared package sources with daemon-only metadata and initialization."""
    version = _project_version()
    staging_dir.mkdir(parents=True, exist_ok=True)
    source_dir = staging_dir / "src"
    source_dir.mkdir()
    shutil.copytree(ROOT / "src" / "ai_guardian", source_dir / "ai_guardian")

    init_template = (DAEMON_PACKAGING / "minimal_init.py").read_text(encoding="utf-8")
    init_contents = init_template.replace("__DAEMON_VERSION__", version)
    (source_dir / "ai_guardian" / "__init__.py").write_text(
        init_contents, encoding="utf-8"
    )

    project_template = (DAEMON_PACKAGING / "pyproject.toml").read_text(encoding="utf-8")
    if project_template.count('version = "0.0.0"') != 1:
        raise ValueError("Daemon pyproject version placeholder must occur once")
    (staging_dir / "pyproject.toml").write_text(
        project_template.replace('version = "0.0.0"', f'version = "{version}"'),
        encoding="utf-8",
    )
    shutil.copy2(DAEMON_PACKAGING / "README.md", staging_dir / "README.md")
    shutil.copy2(ROOT / "LICENSE", staging_dir / "LICENSE")
    return staging_dir


def build_daemon_distribution(outdir: Path) -> None:
    """Build the daemon wheel and sdist into ``outdir`` using Hatchling."""
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-guardian-daemon-build-") as temp:
        staging_dir = prepare_daemon_project(Path(temp) / "project")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--outdir",
                str(outdir),
                str(staging_dir),
            ],
            cwd=ROOT,
            check=True,
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "dist",
        help="Output directory for the wheel and source distribution",
    )
    args = parser.parse_args(argv)
    build_daemon_distribution(args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
