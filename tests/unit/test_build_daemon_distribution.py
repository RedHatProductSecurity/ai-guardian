"""Tests for staging the separately versioned daemon-only distribution."""

from pathlib import Path
from unittest import mock

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from scripts import build_daemon_distribution as builder


def test_staging_uses_shared_sources_and_minimal_metadata(tmp_path):
    staged = builder.prepare_daemon_project(tmp_path / "stage")
    version = builder._project_version()
    pyproject = (staged / "pyproject.toml").read_text(encoding="utf-8")
    metadata = tomllib.loads(pyproject)
    staged_init = (staged / "src/ai_guardian/__init__.py").read_text(encoding="utf-8")

    assert f'version = "{version}"' in pyproject
    assert f'__version__ = "{version}"' in staged_init
    assert 'ai-guardian-daemon = "ai_guardian.daemon_cli:main"' in pyproject
    assert metadata["project"]["dependencies"] == ["cryptography>=43.0.0"]
    assert (staged / "src/ai_guardian/daemon/server.py").is_file()
    assert (staged / "src/ai_guardian/schemas/ai-guardian-config.schema.json").is_file()
    assert (staged / "LICENSE").is_file()
    assert (staged / "README.md").is_file()
    assert "ai_guardian.cli" not in staged_init


def test_staging_rejects_version_mismatch(monkeypatch):
    source_init = builder.ROOT / "src/ai_guardian/__init__.py"
    original = source_init.read_text(encoding="utf-8")
    changed = original.replace(
        f'__version__ = "{builder._project_version()}"',
        '__version__ = "0.0.0"',
        1,
    )
    monkeypatch.setattr(
        Path,
        "read_text",
        mock.Mock(
            side_effect=[
                (builder.ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                changed,
            ]
        ),
    )
    with pytest.raises(ValueError, match="do not match"):
        builder._project_version()


def test_build_invokes_build_module_in_temporary_project(tmp_path, monkeypatch):
    calls = []

    def capture(command, *, cwd, check):
        calls.append((command, cwd, check))

    monkeypatch.setattr(builder.subprocess, "run", capture)
    output = tmp_path / "dist"
    builder.build_daemon_distribution(output)

    assert output.is_dir()
    assert len(calls) == 1
    command, cwd, check = calls[0]
    assert command[:3] == [builder.sys.executable, "-m", "build"]
    assert command[3] == "--outdir"
    assert Path(command[4]) == output.resolve()
    assert Path(command[5]).name == "project"
    assert cwd == builder.ROOT
    assert check is True
