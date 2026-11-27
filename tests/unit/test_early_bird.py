from pathlib import Path

import pytest

from scripts.early_bird import (
    development_base,
    next_dev_version,
    prepare_tree,
    validate_ordering,
)


def test_next_dev_version_is_monotonic_and_does_not_reuse_numbers():
    assert (
        next_dev_version("1.24.0", ["1.24.0.dev1", "1.24.0.dev7"], 3) == "1.24.0.dev8"
    )


def test_next_dev_version_uses_planned_base_not_incremented_release():
    assert next_dev_version("2.0.0", ["1.99.0.dev99"]) == "2.0.0.dev1"


def test_development_base_rejects_stable_versions():
    with pytest.raises(ValueError):
        development_base("1.24.0")


def test_pep440_ordering_is_documented_policy():
    validate_ordering("1.24.0")


def test_prepare_tree_writes_version_and_full_sha_without_touching_source(
    tmp_path: Path,
):
    source = tmp_path / "source"
    (source / "src" / "ai_guardian").mkdir(parents=True)
    (source / "pyproject.toml").write_text('version = "1.24.0-dev"\n', encoding="utf-8")
    (source / "src" / "ai_guardian" / "__init__.py").write_text(
        '__version__ = "1.24.0-dev"\n', encoding="utf-8"
    )
    destination = tmp_path / "build"
    prepare_tree(source, destination, "1.24.0.dev1", "a" * 40)
    assert 'version = "1.24.0.dev1"' in (destination / "pyproject.toml").read_text()
    assert (
        '"1.24.0.dev1"'
        in (destination / "src" / "ai_guardian" / "__init__.py").read_text()
    )
    assert (
        "source_sha=" + "a" * 40 in (destination / "EARLY_BIRD_PROVENANCE").read_text()
    )
    assert 'version = "1.24.0-dev"' in (source / "pyproject.toml").read_text()
