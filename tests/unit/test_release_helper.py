#!/usr/bin/env python3
"""
Tests for release helper module.

This test suite verifies the release helper functionality for:
- Version reading and updating
- CHANGELOG.md management
- Version calculation
- Prerequisites validation

Announcement tests mock all GitHub/PyPI I/O and never publish real artifacts.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.error import URLError

import pytest

# Try to import release_helper from project skills directory
try:
    # Get project root (parent of tests directory)
    project_root = Path(__file__).parent.parent.parent
    skills_path = project_root / ".claude" / "skills" / "release"

    sys.path.insert(0, str(skills_path))
    import release_helper

    from release_helper import (
        CursorHookVerifier,
        ReleaseHelper,
        get_container_image_references,
    )

    RELEASE_HELPER_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    RELEASE_HELPER_AVAILABLE = False
    ReleaseHelper = None
    CursorHookVerifier = None
    get_container_image_references = None

# Skip all tests if release_helper is not available
pytestmark = pytest.mark.skipif(
    not RELEASE_HELPER_AVAILABLE,
    reason="release_helper module not available (.claude/skills/release/ not found)",
)


def create_test_repo(tmp_path):
    """Create a minimal test repository structure."""
    # Create directory structure
    src_dir = tmp_path / "src" / "ai_guardian"
    src_dir.mkdir(parents=True)

    # Create pyproject.toml
    pyproject_content = """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ai-guardian"
version = "1.1.0-dev"
description = "Test"
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content)

    # Create __init__.py
    init_content = '''"""AI Guardian package."""

__version__ = "1.1.0-dev"
'''
    (src_dir / "__init__.py").write_text(init_content)

    # Create CHANGELOG.md
    changelog_content = """# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- New feature X
- New feature Y

### Fixed
- Bug fix Z

## [1.0.0] - 2026-01-01

### Added
- Initial release

[Unreleased]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.0
"""
    (tmp_path / "CHANGELOG.md").write_text(changelog_content)

    return tmp_path


def test_get_current_version():
    """Test getting current version from both files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        version, all_match = helper.get_current_version()

        assert version == "1.1.0-dev"
        assert all_match is True


def test_version_mismatch_detection():
    """Test detection of version mismatch between files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Manually update only one file to create mismatch
        init_path = tmp_path / "src" / "ai_guardian" / "__init__.py"
        content = init_path.read_text()
        content = content.replace(
            '__version__ = "1.1.0-dev"', '__version__ = "1.2.0-dev"'
        )
        init_path.write_text(content)

        helper = ReleaseHelper(tmp_path)
        version, all_match = helper.get_current_version()

        assert version is None  # No single version when mismatch
        assert all_match is False


def test_update_version():
    """Test updating version in both files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        success = helper.update_version("1.2.0")

        assert success is True

        # Verify both files updated
        version, all_match = helper.get_current_version()
        assert version == "1.2.0"
        assert all_match is True

        config = (tmp_path / ".release-config.json").read_text()
        assert '"detected_version": "1.2.0"' in config


def test_calculate_next_version_minor():
    """Test calculating next minor version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.1.0-dev", "minor")
        assert next_ver == "1.2.0"


def test_calculate_next_version_major():
    """Test calculating next major version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.1.0-dev", "major")
        assert next_ver == "2.0.0"


def test_calculate_next_version_patch():
    """Test calculating next patch version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.1.0", "patch")
        assert next_ver == "1.1.1"


def test_calculate_next_version_test():
    """Test calculating test version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        helper = ReleaseHelper(tmp_path)

        next_ver = helper.calculate_next_version("1.2.0-dev", "test")
        assert next_ver == "1.2.0-test1"


def test_get_container_image_references_uses_dedicated_openshell_repository():
    """Versioned releases use separate normal and OpenShell repositories."""
    assert get_container_image_references("1.2.0") == {
        "normal": "quay.io/redhatproductsecurity/ai-guardian:1.2.0",
        "openshell": "quay.io/redhatproductsecurity/ai-guardian-openshell:1.2.0",
    }


def test_get_container_image_references_rejects_non_release_versions():
    """Container release tags must be stable semantic versions."""
    with pytest.raises(ValueError):
        get_container_image_references("1.2.0-dev")


def test_update_changelog():
    """Test updating CHANGELOG.md."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        success = helper.update_changelog("1.1.0", "2026-04-08")

        assert success is True

        # Verify CHANGELOG updated
        changelog = (tmp_path / "CHANGELOG.md").read_text()
        assert "## [1.1.0] - 2026-04-08" in changelog
        assert "### Added" in changelog
        assert "- New feature X" in changelog
        assert (
            "[1.1.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.1.0"
            in changelog
        )
        assert (
            "[Unreleased]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.1.0...HEAD"
            in changelog
        )


def test_update_changelog_empty_unreleased():
    """Test updating CHANGELOG with empty Unreleased section fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Create CHANGELOG with empty Unreleased
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0] - 2026-01-01

### Added
- Initial release

[Unreleased]: https://github.com/RedHatProductSecurity/ai-guardian/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.0
"""
        (tmp_path / "CHANGELOG.md").write_text(changelog_content)

        helper = ReleaseHelper(tmp_path)
        success = helper.update_changelog("1.1.0", "2026-04-08")

        assert success is False


def test_validate_prerequisites_success():
    """Test successful prerequisites validation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is True
        assert len(errors) == 0


def test_validate_prerequisites_version_mismatch():
    """Test prerequisites validation detects version mismatch."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Create version mismatch
        init_path = tmp_path / "src" / "ai_guardian" / "__init__.py"
        content = init_path.read_text()
        content = content.replace(
            '__version__ = "1.1.0-dev"', '__version__ = "1.2.0-dev"'
        )
        init_path.write_text(content)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is False
        assert len(errors) > 0
        assert any("mismatch" in err.lower() for err in errors)


def test_validate_prerequisites_missing_unreleased():
    """Test prerequisites validation detects missing Unreleased section."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Remove Unreleased section
        changelog_content = """# Changelog

## [1.0.0] - 2026-01-01

### Added
- Initial release
"""
        (tmp_path / "CHANGELOG.md").write_text(changelog_content)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is False
        assert len(errors) > 0
        assert any("unreleased" in err.lower() for err in errors)


def test_validate_prerequisites_empty_unreleased():
    """Test prerequisites validation detects empty Unreleased section."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_test_repo(tmp_path)

        # Empty Unreleased section
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0] - 2026-01-01

### Added
- Initial release
"""
        (tmp_path / "CHANGELOG.md").write_text(changelog_content)

        helper = ReleaseHelper(tmp_path)
        valid, errors = helper.validate_prerequisites("regular")

        assert valid is False
        assert len(errors) > 0
        assert any("empty" in err.lower() for err in errors)


@pytest.fixture
def announcement_io(monkeypatch):
    """All announcement I/O is mocked; no tests can publish or contact registries."""
    announcer = release_helper.ReleaseAnnouncer("1.2.3")
    url = f"https://github.com/{announcer.REPOSITORY}/discussions/123"

    def page(nodes, cursor=None):
        return {
            "nodes": nodes,
            "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
        }

    state = SimpleNamespace(
        announcer=announcer,
        url=url,
        page=page,
        release={
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-10-28T00:00:00Z",
            "html_url": announcer.release_url,
        },
        metadata={
            "info": {"name": "ai-guardian", "version": "1.2.3"},
            "urls": [
                {
                    "packagetype": kind,
                    "filename": filename,
                    "url": f"https://files.pythonhosted.org/packages/test/{filename}",
                    "yanked": False,
                }
                for kind, filename in (
                    ("bdist_wheel", "ai_guardian-1.2.3-py3-none-any.whl"),
                    ("sdist", "ai_guardian-1.2.3.tar.gz"),
                )
            ],
        },
        categories={None: page([{"id": "category-from-api", "slug": "announcements"}])},
        discussions={None: page([])},
        failures={},
        download_status=200,
        pypi_body=None,
        reconcile=None,
        events=[],
        mutations=[],
    )

    def github(command, **kwargs):
        assert command[:4] == ["gh", "api", "--hostname", "github.com"]
        if command[4] != "graphql":
            assert (
                command[4]
                == "repos/RedHatProductSecurity/ai-guardian/releases/tags/v1.2.3"
            )
            stage, result = "release", state.release
        else:
            payload = json.loads(kwargs["input"])
            query, variables = payload["query"], payload["variables"]
            if "mutation CreateReleaseAnnouncement" in query:
                stage = "create"
                state.mutations.append(variables)
                if state.reconcile is not None:
                    state.discussions = state.reconcile
                result = {
                    "data": {"createDiscussion": {"discussion": {"url": state.url}}}
                }
            else:
                assert variables["owner"] == "RedHatProductSecurity"
                assert variables["name"] == "ai-guardian"
                if "query ReleaseCategories" in query:
                    stage, field, pages = (
                        "categories",
                        "discussionCategories",
                        state.categories,
                    )
                else:
                    assert "query ReleaseDiscussions" in query
                    assert variables["categoryId"] == "category-from-api"
                    stage, field, pages = (
                        "discussions",
                        "discussions",
                        state.discussions,
                    )
                result = {
                    "data": {
                        "repository": {
                            "id": "repository-from-api",
                            field: pages[variables["after"]],
                        }
                    }
                }
        state.events.append(stage)
        failure = state.failures.get(stage)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")

    def http(request, **kwargs):
        stage = "pypi" if request.get_method() == "GET" else "download"
        if stage == "pypi":
            assert request.full_url == "https://pypi.org/pypi/ai-guardian/1.2.3/json"
        else:
            assert request.full_url.startswith(
                "https://files.pythonhosted.org/packages/"
            )
        state.events.append(stage)
        if stage in state.failures:
            raise state.failures[stage]
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = state.download_status if stage == "download" else 200
        response.read.return_value = (
            state.pypi_body
            if state.pypi_body is not None
            else json.dumps(state.metadata).encode()
        )
        return response

    state.gh = Mock(side_effect=github)
    state.http = Mock(side_effect=http)
    monkeypatch.setattr(release_helper.subprocess, "run", state.gh)
    monkeypatch.setattr(release_helper, "urlopen", state.http)
    return state


def test_announcement_dry_run_is_offline_and_does_not_detect_config(
    tmp_path, monkeypatch, capsys, announcement_io
):
    """Preview must work without gh, publication, or local version/config writes."""
    tmp_path = tmp_path / "release-checkout"
    tmp_path.mkdir()
    helper = Mock(side_effect=AssertionError("must not initialize version management"))
    monkeypatch.setattr(release_helper, "ReleaseHelper", helper)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_helper.py",
            "--repo",
            str(tmp_path),
            "announce-release",
            "1.2.3",
            "--dry-run",
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        release_helper.main()

    assert exit_info.value.code == 0
    assert list(tmp_path.iterdir()) == []
    helper.assert_not_called()
    output = capsys.readouterr().out
    assert "Announcements (announcements)" in output
    assert "AI Guardian v1.2.3 is now available" in output
    assert (
        "https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.2.3"
        in output
    )
    assert "https://pypi.org/project/ai-guardian/1.2.3/#files" in output
    assert "not posted" in output.lower()
    announcement_io.gh.assert_not_called()
    announcement_io.http.assert_not_called()


def test_announcement_rejects_development_version_before_any_io():
    """An explicit released version is required, never the later dev cycle."""
    with pytest.raises(ValueError, match="stable release version"):
        release_helper.ReleaseAnnouncer("1.2.3-dev")


@pytest.mark.parametrize(
    "version",
    ["v1.2.3", "1.2.3-test1", "1.2.3rc1", "1.2.3+build", "01.2.3", "1.2", "1.2.3\n"],
)
def test_announcement_excludes_non_production_versions(version, announcement_io):
    with pytest.raises(ValueError, match="stable release version"):
        release_helper.ReleaseAnnouncer(version)
    assert announcement_io.events == []


def test_announcement_creates_exact_version_in_resolved_category(
    announcement_io, capsys
):
    state = announcement_io
    assert state.announcer.announce() == state.url
    assert state.events == [
        "release",
        "pypi",
        "download",
        "download",
        "categories",
        "discussions",
        "create",
    ]
    assert state.mutations == [
        {
            "repositoryId": "repository-from-api",
            "categoryId": "category-from-api",
            "title": "AI Guardian v1.2.3 is now available",
            "body": state.announcer.body,
        }
    ]
    assert state.announcer.release_url in state.mutations[0]["body"]
    assert (
        "https://pypi.org/project/ai-guardian/1.2.3/#files"
        in state.mutations[0]["body"]
    )
    assert "latest" not in state.mutations[0]["body"]
    assert "posted" in capsys.readouterr().err


def test_announcement_retry_cli_does_not_initialize_version_management(
    tmp_path, monkeypatch, announcement_io, capsys
):
    tmp_path = tmp_path / "release-checkout"
    tmp_path.mkdir()
    helper = Mock(
        side_effect=AssertionError("no version, config, git, or publication mutations")
    )
    monkeypatch.setattr(release_helper, "ReleaseHelper", helper)
    monkeypatch.setattr(
        sys, "argv", ["helper", "--repo", str(tmp_path), "announce-release", "1.2.3"]
    )
    for _ in range(2):
        with pytest.raises(SystemExit) as exit_info:
            release_helper.main()
        assert exit_info.value.code == 0
        announcement_io.discussions = {
            None: announcement_io.page(
                [
                    {
                        "title": "Edited title",
                        "body": announcement_io.announcer.body,
                        "url": announcement_io.url,
                    }
                ]
            )
        }
    assert len(announcement_io.mutations) == 1
    helper.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr().out.splitlines() == [announcement_io.url] * 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", True),
        ("prerelease", True),
        ("tag_name", "v1.2.3-test1"),
        ("tag_name", "v1.2.4"),
        ("published_at", None),
        ("draft", None),
        ("html_url", "https://github.com/other/repo/releases/tag/v1.2.3"),
    ],
)
def test_announcement_requires_exact_public_production_release(
    field, value, announcement_io
):
    announcement_io.release[field] = value
    with pytest.raises(
        release_helper.AnnouncementError, match="production GitHub Release"
    ):
        announcement_io.announcer.announce()
    assert announcement_io.events == ["release"]


@pytest.mark.parametrize(
    "change",
    [
        "wrong_version",
        "wrong_package",
        "no_files",
        "wheel_only",
        "source_only",
        "yanked",
        "testpypi",
        "wrong_filename",
        "missing_yanked",
        "incomplete_distribution",
    ],
)
def test_announcement_requires_exact_downloadable_production_distributions(
    change, announcement_io
):
    metadata = announcement_io.metadata
    if change in ("wrong_version", "wrong_package"):
        metadata["info"]["version" if change == "wrong_version" else "name"] = "other"
    elif change == "no_files":
        metadata["urls"] = []
    elif change == "wheel_only":
        metadata["urls"] = metadata["urls"][:1]
    elif change == "source_only":
        metadata["urls"] = metadata["urls"][1:]
    elif change == "yanked":
        metadata["urls"][0]["yanked"] = True
    elif change == "testpypi":
        metadata["urls"][0][
            "url"
        ] = "https://test-files.pythonhosted.org/packages/test/file.whl"
    elif change == "wrong_filename":
        metadata["urls"][0]["filename"] = "ai_guardian-1.2.30-py3-none-any.whl"
    elif change == "missing_yanked":
        del metadata["urls"][0]["yanked"]
    else:
        metadata["urls"][0] = None
    with pytest.raises(release_helper.AnnouncementError, match="PyPI"):
        announcement_io.announcer.announce()
    assert announcement_io.mutations == []
    assert "categories" not in announcement_io.events


@pytest.mark.parametrize("stage", ["pypi", "download"])
def test_announcement_registry_or_distribution_unavailable(stage, announcement_io):
    announcement_io.failures[stage] = URLError("not yet available")
    with pytest.raises(release_helper.AnnouncementError, match="PyPI"):
        announcement_io.announcer.announce()
    assert announcement_io.mutations == []


@pytest.mark.parametrize(
    "body", [b"not JSON", b"null", b"[]", b'{"info":null,"urls":[]}']
)
def test_announcement_registry_incomplete_response_never_authorizes_posting(
    body, announcement_io
):
    announcement_io.pypi_body = body
    with pytest.raises(release_helper.AnnouncementError, match="PyPI"):
        announcement_io.announcer.announce()
    assert announcement_io.mutations == []


def test_announcement_distribution_unsuccessful_head_is_not_available(announcement_io):
    announcement_io.download_status = 503
    with pytest.raises(release_helper.AnnouncementError, match="not downloadable"):
        announcement_io.announcer.announce()
    assert announcement_io.mutations == []


def test_announcement_paginates_categories_and_existing_discussions(announcement_io):
    state = announcement_io
    state.categories = {
        None: state.page([{"id": "other", "slug": "general"}], "next-category"),
        "next-category": state.categories[None],
    }
    state.discussions = {
        None: state.page(
            [{"title": "Other", "body": "Other", "url": state.url}], "next-discussion"
        ),
        "next-discussion": state.page(
            [{"title": "Edited", "body": state.announcer.marker, "url": state.url}]
        ),
    }
    assert state.announcer.announce() == state.url
    assert state.events.count("categories") == state.events.count("discussions") == 2
    assert state.mutations == []


def test_announcement_creates_only_after_all_discussion_pages_are_exhausted(
    announcement_io,
):
    state = announcement_io
    state.discussions = {None: state.page([], "last-page"), "last-page": state.page([])}
    assert state.announcer.announce() == state.url
    assert state.events[-3:] == ["discussions", "discussions", "create"]


def test_announcement_second_page_api_failure_is_not_absence(announcement_io):
    state = announcement_io
    state.discussions[None] = state.page([], "last-page")
    original = state.gh.side_effect

    def fail_last_page(command, **kwargs):
        if kwargs.get("input"):
            payload = json.loads(kwargs["input"])
            if payload["variables"].get("after") == "last-page":
                return subprocess.CompletedProcess(command, 1, "", "failed page")
        return original(command, **kwargs)

    state.gh.side_effect = fail_last_page
    with pytest.raises(release_helper.AnnouncementError, match="GitHub request failed"):
        state.announcer.announce()
    assert state.mutations == []


def test_announcement_recognizes_manual_exact_title_and_release_link(announcement_io):
    state = announcement_io
    state.discussions[None] = state.page(
        [
            {
                "title": state.announcer.title,
                "body": f"[Release]({state.announcer.release_url})",
                "url": state.url,
            }
        ]
    )
    assert state.announcer.announce() == state.url
    assert state.mutations == []


def test_announcement_does_not_confuse_version_prefix_or_unrelated_discussion(
    announcement_io,
):
    state = announcement_io
    state.discussions[None] = state.page(
        [
            {
                "title": state.announcer.title,
                "body": state.announcer.release_url + "0",
                "url": state.url,
            },
            {
                "title": "Unrelated",
                "body": state.announcer.release_url,
                "url": state.url,
            },
        ]
    )
    state.announcer.announce()
    assert len(state.mutations) == 1


def test_announcement_missing_category_is_not_created(announcement_io):
    announcement_io.categories[None] = announcement_io.page([])
    with pytest.raises(
        release_helper.AnnouncementError, match="Announcements.*not found"
    ):
        announcement_io.announcer.announce()
    assert announcement_io.mutations == []


@pytest.mark.parametrize("field", ["categories", "discussions"])
@pytest.mark.parametrize(
    "problem",
    ["missing_nodes", "missing_page_info", "no_cursor", "repeated_cursor", "bad_node"],
)
def test_announcement_incomplete_pagination_never_authorizes_creation(
    field, problem, announcement_io
):
    state = announcement_io
    pages = getattr(state, field)
    pages[None] = state.page([])
    if problem == "missing_nodes":
        del pages[None]["nodes"]
    elif problem == "missing_page_info":
        del pages[None]["pageInfo"]
    elif problem == "no_cursor":
        pages[None]["pageInfo"]["hasNextPage"] = True
    elif problem == "repeated_cursor":
        pages[None] = state.page([], "loop")
        pages["loop"] = state.page([], "loop")
    else:
        pages[None]["nodes"] = [{}]
    with pytest.raises(release_helper.AnnouncementError, match="GitHub"):
        state.announcer.announce()
    assert state.mutations == []


@pytest.mark.parametrize("stage", ["release", "categories", "discussions"])
@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CompletedProcess([], 1, "", "permission denied"),
        subprocess.CompletedProcess(
            [], 0, '{"errors":[{"message":"forbidden"}],"data":null}', ""
        ),
        subprocess.CompletedProcess([], 0, "not JSON", ""),
        subprocess.CompletedProcess([], 0, '{"data":{"repository":null}}', ""),
        subprocess.TimeoutExpired("gh", 60),
        FileNotFoundError("gh"),
    ],
)
def test_announcement_lookup_errors_are_not_absence(stage, failure, announcement_io):
    announcement_io.failures[stage] = failure
    with pytest.raises(release_helper.AnnouncementError):
        announcement_io.announcer.announce()
    assert announcement_io.mutations == []


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("gh", 60),
        subprocess.CompletedProcess([], 1, "", "permission denied"),
        subprocess.CompletedProcess([], 0, '{"errors":[{"message":"forbidden"}]}', ""),
        subprocess.CompletedProcess([], 0, "not JSON", ""),
        subprocess.CompletedProcess([], 0, '{"data":{"createDiscussion":null}}', ""),
        subprocess.CompletedProcess(
            [],
            0,
            '{"data":{"createDiscussion":{"discussion":{"url":"https://github.com/other/repo/discussions/1"}}}}',
            "",
        ),
    ],
)
def test_announcement_uncertain_create_never_reposts(failure, announcement_io):
    announcement_io.failures["create"] = failure
    with pytest.raises(
        release_helper.AnnouncementError,
        match="Creation outcome uncertain; no automatic repost",
    ):
        announcement_io.announcer.announce()
    assert len(announcement_io.mutations) == 1
    assert announcement_io.events[-1] == "discussions"


def test_announcement_uncertain_create_can_be_confirmed_by_read_only_lookup(
    announcement_io, capsys
):
    state = announcement_io
    state.failures["create"] = subprocess.TimeoutExpired("gh", 60)
    state.reconcile = {
        None: state.page([], "after-create"),
        "after-create": state.page(
            [
                {
                    "title": state.announcer.title,
                    "body": state.announcer.body,
                    "url": state.url,
                }
            ]
        ),
    }
    assert state.announcer.announce() == state.url
    assert len(state.mutations) == 1
    assert "confirmed by lookup" in capsys.readouterr().err


def test_announcement_uncertain_create_and_failed_reconciliation_stays_uncertain(
    announcement_io,
):
    state = announcement_io
    original = state.gh.side_effect

    def failing_reconciliation(command, **kwargs):
        if state.mutations:
            raise subprocess.TimeoutExpired("gh", 60)
        return original(command, **kwargs)

    state.failures["create"] = subprocess.TimeoutExpired("gh", 60)
    state.gh.side_effect = failing_reconciliation
    with pytest.raises(
        release_helper.AnnouncementError, match="Creation outcome uncertain"
    ):
        state.announcer.announce()
    assert len(state.mutations) == 1


def test_announcement_cli_errors_do_not_report_success(
    monkeypatch, announcement_io, capsys
):
    announcement_io.failures["release"] = subprocess.CompletedProcess(
        [], 1, "", "forbidden"
    )
    monkeypatch.setattr(sys, "argv", ["helper", "announce-release", "1.2.3"])
    with pytest.raises(SystemExit) as exit_info:
        release_helper.main()
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Announcement not confirmed" in captured.err
    assert "permissions" in captured.err
    assert "posted" not in captured.err


def test_announcement_cli_rejects_non_production_version(
    monkeypatch, announcement_io, capsys
):
    monkeypatch.setattr(sys, "argv", ["helper", "announce-release", "1.2.3-test1"])
    with pytest.raises(SystemExit) as exit_info:
        release_helper.main()
    assert exit_info.value.code == 1
    assert "stable release version" in capsys.readouterr().err
    assert announcement_io.events == []


@pytest.mark.parametrize("errors", [[], ["Version mismatch", "Missing CHANGELOG"]])
def test_existing_validation_cli_messages_are_unchanged(errors, monkeypatch, capsys):
    """The new command must not alter existing prerequisite failure messages."""
    helper = Mock()
    helper.validate_prerequisites.return_value = (not errors, errors)
    monkeypatch.setattr(release_helper, "ReleaseHelper", Mock(return_value=helper))
    monkeypatch.setattr(sys, "argv", ["helper", "validate"])
    with pytest.raises(SystemExit) as exit_info:
        release_helper.main()
    assert exit_info.value.code == (1 if errors else 0)
    captured = capsys.readouterr()
    if errors:
        assert captured.err == "✗ Validation failed:\n" + "".join(
            f"  - {error}\n" for error in errors
        )
    else:
        assert captured.out == "✓ All prerequisites validated\n"


def _create_settings(settings_path, hooks=None):
    """Create a minimal hooks.json for testing."""
    if hooks is None:
        settings = {"version": 1}
        for event in CursorHookVerifier.EXPECTED_EVENTS:
            settings[event] = [{"command": "ai-guardian"}]
    else:
        settings = hooks
    settings_path.write_text(json.dumps(settings, indent=2))
    return settings


def _create_debug_log(debug_dir, event_name, cursor_version="0.47.1"):
    """Create a mock debug log file."""
    log_data = {
        "hook_event_name": event_name,
        "cursor_version": cursor_version,
        "_debug_timestamp": 1718640000.0,
        "_debug_event": event_name,
    }
    log_file = (
        debug_dir / f"cursor-hook-debug-{event_name}-{int(1718640000 * 1e9)}.json"
    )
    log_file.write_text(json.dumps(log_data, indent=2))
    return log_file


class TestCursorHookVerifier:
    """Tests for CursorHookVerifier class."""

    def test_setup_creates_debug_script(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        result = verifier.setup()

        assert result is True
        assert verifier.debug_script.exists()
        if sys.platform != "win32":
            assert verifier.debug_script.stat().st_mode & 0o111

    def test_setup_modifies_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        settings = json.loads(settings_path.read_text())
        for event in CursorHookVerifier.EXPECTED_EVENTS:
            entries = settings["hooks"][event]
            debug_entries = [
                e
                for e in entries
                if isinstance(e, dict)
                and "cursor-hook-debug.sh" in e.get("command", "")
            ]
            assert len(debug_entries) == 1, f"Expected 1 debug entry for {event}"

    def test_setup_creates_backup(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        assert verifier.backup_path.exists()

    def test_setup_cleans_old_logs(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        old_log = debug_dir / "cursor-hook-debug-old-12345.json"
        old_log.write_text("{}")

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        assert not old_log.exists()

    def test_setup_fails_if_backup_exists(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        backup = tmp_path / "settings.json.cursor-verify-backup"
        backup.write_text("{}")

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        result = verifier.setup()
        assert result is False

    def test_analyze_all_pass(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in CursorHookVerifier.EXPECTED_EVENTS:
            _create_debug_log(debug_dir, event)

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is True
        assert cursor_version == "0.47.1"

    def test_analyze_missing_event(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in ["beforeSubmitPrompt", "beforeReadFile", "beforeShellExecution"]:
            _create_debug_log(debug_dir, event)

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is False

    def test_analyze_extracts_cursor_version(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in CursorHookVerifier.EXPECTED_EVENTS:
            _create_debug_log(debug_dir, event, cursor_version="0.50.0")

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        _, cursor_version = verifier.analyze()

        assert cursor_version == "0.50.0"

    def test_analyze_hook_name_field(self, tmp_path):
        """Cursor sends hook_name instead of hook_event_name (#1532)."""
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        for event in CursorHookVerifier.EXPECTED_EVENTS:
            log_data = {
                "hook_name": event,
                "cursor_version": "3.1.0",
                "_debug_timestamp": 1718640000.0,
                "_debug_event": event,
            }
            log_file = (
                debug_dir / f"cursor-hook-debug-{event}-{int(1718640000 * 1e9)}.json"
            )
            log_file.write_text(json.dumps(log_data, indent=2))

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is True
        assert cursor_version == "3.1.0"

    def test_analyze_no_files(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        passed, cursor_version = verifier.analyze()

        assert passed is False
        assert cursor_version is None

    def test_cleanup_removes_debug_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()
        verifier.cleanup()

        settings = json.loads(settings_path.read_text())
        for event in CursorHookVerifier.EXPECTED_EVENTS:
            entries = settings.get(event, [])
            for entry in entries:
                if isinstance(entry, dict):
                    assert "cursor-hook-debug.sh" not in entry.get("command", "")

    def test_cleanup_preserves_existing_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()
        verifier.cleanup()

        settings = json.loads(settings_path.read_text())
        assert len(settings["beforeSubmitPrompt"]) == 1
        assert settings["beforeSubmitPrompt"][0]["command"] == "ai-guardian"

    def test_cleanup_removes_files(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        _create_settings(settings_path)
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        verifier = CursorHookVerifier(
            settings_path=str(settings_path), debug_dir=str(debug_dir)
        )
        verifier.setup()

        _create_debug_log(debug_dir, "preToolUse")

        verifier.cleanup()

        assert not verifier.debug_script.exists()
        assert not verifier.backup_path.exists()
        assert len(list(debug_dir.glob("cursor-hook-debug-*.json"))) == 0


def run_tests():
    """Run all tests and report results."""
    tests = [
        test_get_current_version,
        test_version_mismatch_detection,
        test_update_version,
        test_calculate_next_version_minor,
        test_calculate_next_version_major,
        test_calculate_next_version_patch,
        test_calculate_next_version_test,
        test_update_changelog,
        test_update_changelog_empty_unreleased,
        test_validate_prerequisites_success,
        test_validate_prerequisites_version_mismatch,
        test_validate_prerequisites_missing_unreleased,
        test_validate_prerequisites_empty_unreleased,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
            print(f"✓ {test.__name__}")
        except AssertionError as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"✗ {test.__name__}: {e}")
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"✗ {test.__name__}: {e}")

    print(f"\n{'='*70}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*70}")

    if errors:
        print("\nFailed tests:")
        for name, error in errors:
            print(f"  {name}: {error}")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
