"""Tests for .aiguardignore.toml support (Issue #497)."""

import os
import textwrap
from unittest.mock import patch

import pytest

from ai_guardian.aiguardignore import (
    load_aiguardignore,
    get_ignore_paths,
    reset_cache,
    _validate_paths,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Reset module caches between tests."""
    reset_cache()
    yield
    reset_cache()


SAMPLE_TOML = textwrap.dedent("""\
    [allowlist]
        paths = [
            "tests/fixtures/**",
            "tests/unit/test_ai_guardian.py",
        ]

    [secret_scanning]
        [secret_scanning.allowlist]
            paths = [
                "tests/integration/test_scanner.py",
            ]

    [scan_pii]
        [scan_pii.allowlist]
            paths = [
                "tests/unit/test_pii_detection.py",
            ]

    [prompt_injection]
        [prompt_injection.allowlist]
            paths = [
                "docs/security-patterns.md",
            ]

    [config_file_scanning]
        [config_file_scanning.allowlist]
            paths = [
                "examples/*.json",
            ]

    [code_scanning]
        [code_scanning.allowlist]
            paths = [
                "tests/code/**",
            ]

    [ssrf_protection]
        [ssrf_protection.allowlist]
            paths = [
                "tests/urls/**",
            ]

    [context_poisoning]
        [context_poisoning.allowlist]
            paths = [
                "docs/instructions.md",
            ]

    [supply_chain]
        [supply_chain.allowlist]
            paths = [
                "scripts/hooks/**",
            ]

    [image_scanning]
        [image_scanning.allowlist]
            paths = [
                "tests/fixtures/images/**",
            ]

    [offensive_language]
        [offensive_language.allowlist]
            paths = [
                "docs/language/**",
            ]
""")

GLOBAL_ONLY_TOML = textwrap.dedent("""\
    [allowlist]
        paths = [
            "tests/fixtures/**",
        ]
""")


# ---------------------------------------------------------------------------
# _validate_paths
# ---------------------------------------------------------------------------


class TestValidatePaths:
    def test_safe_paths_accepted(self):
        assert _validate_paths(["tests/**", "docs/*.md"]) == ["tests/**", "docs/*.md"]

    def test_traversal_blocked(self):
        assert _validate_paths(["../secrets.txt"]) == []
        assert _validate_paths(["tests/../../etc/passwd"]) == []

    def test_mixed(self):
        result = _validate_paths(["good/path.py", "../bad", "also/good/**"])
        assert result == ["good/path.py", "also/good/**"]

    def test_empty_list(self):
        assert _validate_paths([]) == []


# ---------------------------------------------------------------------------
# load_aiguardignore
# ---------------------------------------------------------------------------


class TestLoadAiguardignore:
    def test_loads_valid_toml(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(SAMPLE_TOML)

        config = load_aiguardignore(project_root=tmp_path)

        assert config is not None
        assert "tests/fixtures/**" in config.global_paths
        assert "tests/unit/test_ai_guardian.py" in config.global_paths
        assert config.scanner_paths["secret_scanning"] == [
            "tests/integration/test_scanner.py"
        ]
        assert config.scanner_paths["scan_pii"] == ["tests/unit/test_pii_detection.py"]
        assert config.scanner_paths["prompt_injection"] == ["docs/security-patterns.md"]
        assert config.scanner_paths["config_file_scanning"] == ["examples/*.json"]
        assert config.scanner_paths["code_scanning"] == ["tests/code/**"]
        assert config.scanner_paths["ssrf_protection"] == ["tests/urls/**"]
        assert config.scanner_paths["context_poisoning"] == ["docs/instructions.md"]
        assert config.scanner_paths["supply_chain"] == ["scripts/hooks/**"]
        assert config.scanner_paths["image_scanning"] == ["tests/fixtures/images/**"]
        assert config.scanner_paths["offensive_language"] == ["docs/language/**"]

    def test_global_only(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(GLOBAL_ONLY_TOML)

        config = load_aiguardignore(project_root=tmp_path)

        assert config is not None
        assert config.global_paths == ["tests/fixtures/**"]
        assert config.scanner_paths == {}

    def test_missing_file_returns_none(self, tmp_path):
        config = load_aiguardignore(project_root=tmp_path)
        assert config is None

    def test_invalid_toml_returns_none(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text("this is [[ not valid toml")

        config = load_aiguardignore(project_root=tmp_path)
        assert config is None

    def test_empty_file(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text("")

        config = load_aiguardignore(project_root=tmp_path)
        assert config is not None
        assert config.global_paths == []
        assert config.scanner_paths == {}

    def test_traversal_paths_blocked(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(textwrap.dedent("""\
            [allowlist]
                paths = ["../secrets.txt", "safe/path.py"]
        """))

        config = load_aiguardignore(project_root=tmp_path)
        assert config is not None
        assert config.global_paths == ["safe/path.py"]

    def test_caching_by_mtime(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(GLOBAL_ONLY_TOML)

        first = load_aiguardignore(project_root=tmp_path)
        second = load_aiguardignore(project_root=tmp_path)
        assert first is second  # same object from cache

    def test_cache_invalidation_on_mtime_change(self, tmp_path):
        import time

        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(GLOBAL_ONLY_TOML)

        first = load_aiguardignore(project_root=tmp_path)

        # Write new content and ensure mtime advances (Windows mtime granularity)
        time.sleep(0.05)
        toml_file.write_text(SAMPLE_TOML)
        os.utime(toml_file, (time.time() + 1, time.time() + 1))
        second = load_aiguardignore(project_root=tmp_path)

        assert first is not second
        assert len(second.scanner_paths) > 0

    def test_non_dict_allowlist_section_handled(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(textwrap.dedent("""\
            allowlist = "not a dict"
        """))

        config = load_aiguardignore(project_root=tmp_path)
        assert config is not None
        assert config.global_paths == []

    def test_non_dict_scanner_section_skipped(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(textwrap.dedent("""\
            secret_scanning = "not a dict"
        """))

        config = load_aiguardignore(project_root=tmp_path)
        assert config is not None
        assert "secret_scanning" not in config.scanner_paths

    def test_unknown_scanner_section_ignored(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(textwrap.dedent("""\
            [unknown_scanner]
                [unknown_scanner.allowlist]
                    paths = ["some/path.py"]
        """))

        config = load_aiguardignore(project_root=tmp_path)
        assert config is not None
        assert "unknown_scanner" not in config.scanner_paths

    def test_project_root_none(self):
        with patch("ai_guardian.aiguardignore.find_project_root", return_value=None):
            config = load_aiguardignore()
            assert config is None


# ---------------------------------------------------------------------------
# get_ignore_paths
# ---------------------------------------------------------------------------


class TestGetIgnorePaths:
    def test_global_plus_scanner_specific(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(SAMPLE_TOML)

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            paths = get_ignore_paths("secret_scanning")

        assert "tests/fixtures/**" in paths
        assert "tests/unit/test_ai_guardian.py" in paths
        assert "tests/integration/test_scanner.py" in paths

    def test_global_only_when_no_scanner_section(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(GLOBAL_ONLY_TOML)

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            paths = get_ignore_paths("secret_scanning")

        assert paths == ["tests/fixtures/**"]

    def test_empty_when_no_file(self, tmp_path):
        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            paths = get_ignore_paths("secret_scanning")
        assert paths == []

    def test_each_scanner_type(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(SAMPLE_TOML)

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            secret = get_ignore_paths("secret_scanning")
            pii = get_ignore_paths("scan_pii")
            pi = get_ignore_paths("prompt_injection")
            config = get_ignore_paths("config_file_scanning")
            code = get_ignore_paths("code_scanning")
            ssrf = get_ignore_paths("ssrf_protection")
            cp = get_ignore_paths("context_poisoning")
            sc = get_ignore_paths("supply_chain")
            img = get_ignore_paths("image_scanning")
            offensive = get_ignore_paths("offensive_language")

        # All should include global paths
        for paths in [secret, pii, pi, config, code, ssrf, cp, sc, img, offensive]:
            assert "tests/fixtures/**" in paths
            assert "tests/unit/test_ai_guardian.py" in paths

        # Each should include its own scanner-specific path
        assert "tests/integration/test_scanner.py" in secret
        assert "tests/unit/test_pii_detection.py" in pii
        assert "docs/security-patterns.md" in pi
        assert "examples/*.json" in config
        assert "tests/code/**" in code
        assert "tests/urls/**" in ssrf
        assert "docs/instructions.md" in cp
        assert "scripts/hooks/**" in sc
        assert "tests/fixtures/images/**" in img
        assert "docs/language/**" in offensive

        # No cross-contamination
        assert "tests/unit/test_pii_detection.py" not in secret
        assert "tests/integration/test_scanner.py" not in pii
        assert "docs/instructions.md" not in secret
        assert "scripts/hooks/**" not in pii


# ---------------------------------------------------------------------------
# TOML unavailability
# ---------------------------------------------------------------------------


class TestTomlUnavailable:
    def test_graceful_degradation(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(SAMPLE_TOML)

        with patch("ai_guardian.aiguardignore.HAS_TOML", False):
            config = load_aiguardignore(project_root=tmp_path)
            assert config is None

            paths = get_ignore_paths("secret_scanning")
            assert paths == []


# ---------------------------------------------------------------------------
# Integration: _merge_aiguardignore
# ---------------------------------------------------------------------------


class TestMergeAiguardignore:
    def test_merge_into_existing_config(self, tmp_path):
        from ai_guardian import _merge_aiguardignore

        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(GLOBAL_ONLY_TOML)

        existing = {"enabled": True, "ignore_files": ["existing/pattern/**"]}

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            result = _merge_aiguardignore(existing, "secret_scanning")

        assert result is not existing  # new dict (no mutation)
        assert "existing/pattern/**" in result["ignore_files"]
        assert "tests/fixtures/**" in result["ignore_files"]
        assert result["enabled"] is True  # other keys preserved

    def test_merge_into_none_config(self, tmp_path):
        from ai_guardian import _merge_aiguardignore

        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(GLOBAL_ONLY_TOML)

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            result = _merge_aiguardignore(None, "secret_scanning")

        assert result == {"ignore_files": ["tests/fixtures/**"]}

    def test_merge_generated_scanner_types_and_offensive_alias(self, tmp_path):
        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(textwrap.dedent("""\
                [ssrf_protection.allowlist]
                paths = ["tests/urls/**"]

                [code_scanning.allowlist]
                paths = ["tests/code/**"]

                [offensive_language.allowlist]
                paths = ["docs/language/**"]
                """))

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            from ai_guardian.config.loaders import _merge_aiguardignore

            ssrf = _merge_aiguardignore({}, "ssrf_protection", project_root=tmp_path)
            code = _merge_aiguardignore({}, "code_scanning", project_root=tmp_path)
            offensive = _merge_aiguardignore(
                {}, "scan_offensive", project_root=tmp_path
            )

        assert ssrf == {"ignore_files": ["tests/urls/**"]}
        assert code == {"ignore_files": ["tests/code/**"]}
        assert offensive == {"ignore_files": ["docs/language/**"]}

    def test_no_aiguardignore_file(self, tmp_path):
        from ai_guardian import _merge_aiguardignore

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            result = _merge_aiguardignore({"enabled": True}, "secret_scanning")

        assert result == {"enabled": True}

    def test_no_aiguardignore_module(self):
        from ai_guardian import _merge_aiguardignore

        with patch("ai_guardian.config.loaders.HAS_AIGUARDIGNORE", False):
            result = _merge_aiguardignore(None, "secret_scanning")
            assert result is None

    def test_does_not_mutate_original(self, tmp_path):
        from ai_guardian import _merge_aiguardignore

        toml_file = tmp_path / ".aiguardignore.toml"
        toml_file.write_text(GLOBAL_ONLY_TOML)

        original = {"ignore_files": ["original/**"]}

        with patch(
            "ai_guardian.aiguardignore.find_project_root", return_value=tmp_path
        ):
            _merge_aiguardignore(original, "secret_scanning")

        assert original["ignore_files"] == ["original/**"]
