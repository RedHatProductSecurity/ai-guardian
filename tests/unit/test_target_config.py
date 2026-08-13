"""Tests for target project config loading and allowlist merging."""

import json
import os
import sys

import pytest

from ai_guardian.config.target_config import (
    SCANNER_ALLOWLIST_KEYS,
    _extract_allowlists_from_config,
    _validate_overlay_patterns,
    load_target_allowlists,
    merge_target_allowlists,
)


@pytest.fixture
def target_dir(tmp_path):
    """Create a target directory with .ai-guardian subdir."""
    ai_guardian_dir = tmp_path / ".ai-guardian"
    ai_guardian_dir.mkdir()
    return tmp_path


def _write_config(target_dir, config):
    config_path = target_dir / ".ai-guardian" / "ai-guardian.json"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(json.dumps(config))


def _write_aiguardignore(target_dir, toml_text):
    (target_dir / ".aiguardignore.toml").write_text(toml_text)


def _write_gitleaks_toml(target_dir, toml_text):
    (target_dir / ".gitleaks.toml").write_text(toml_text)


class TestExtractAllowlists:
    def test_extracts_allowlist_patterns(self):
        config = {
            "prompt_injection": {
                "enabled": True,
                "action": "block",
                "allowlist_patterns": ["test-pattern"],
            },
        }
        result = _extract_allowlists_from_config(config)
        assert result == {"prompt_injection": {"allowlist_patterns": ["test-pattern"]}}

    def test_ignores_non_allowlist_fields(self):
        config = {
            "prompt_injection": {
                "enabled": True,
                "action": "block",
                "sensitivity": "high",
                "allowlist_patterns": ["safe"],
            },
        }
        result = _extract_allowlists_from_config(config)
        section = result["prompt_injection"]
        assert "enabled" not in section
        assert "action" not in section
        assert "sensitivity" not in section
        assert section["allowlist_patterns"] == ["safe"]

    def test_extracts_multiple_keys_per_scanner(self):
        config = {
            "secret_scanning": {
                "allowlist_patterns": ["pat1"],
                "ignore_files": ["*.test"],
                "ignore_tools": ["tool1"],
                "enabled": True,
            },
        }
        result = _extract_allowlists_from_config(config)
        assert result["secret_scanning"] == {
            "allowlist_patterns": ["pat1"],
            "ignore_files": ["*.test"],
            "ignore_tools": ["tool1"],
        }

    def test_skips_empty_lists(self):
        config = {
            "prompt_injection": {
                "allowlist_patterns": [],
            },
        }
        result = _extract_allowlists_from_config(config)
        assert result == {}

    def test_skips_non_list_values(self):
        config = {
            "prompt_injection": {
                "allowlist_patterns": "not-a-list",
            },
        }
        result = _extract_allowlists_from_config(config)
        assert result == {}

    def test_skips_unknown_sections(self):
        config = {
            "unknown_scanner": {
                "allowlist_patterns": ["pat"],
            },
        }
        result = _extract_allowlists_from_config(config)
        assert result == {}

    def test_extracts_code_scanning_allowlist(self):
        config = {
            "code_scanning": {
                "allowlist": ["B101"],
                "ignore_files": ["tests/**"],
            },
        }
        result = _extract_allowlists_from_config(config)
        assert result["code_scanning"] == {
            "allowlist": ["B101"],
            "ignore_files": ["tests/**"],
        }

    def test_all_scanner_sections_handled(self):
        config = {}
        for section, keys in SCANNER_ALLOWLIST_KEYS.items():
            config[section] = {}
            for key in keys:
                config[section][key] = [f"{section}-{key}-val"]
        result = _extract_allowlists_from_config(config)
        assert set(result.keys()) == set(SCANNER_ALLOWLIST_KEYS.keys())


class TestValidateOverlayPatterns:
    def test_blocks_dangerous_allowlist_pattern(self):
        overlay = {
            "prompt_injection": {
                "allowlist_patterns": [".*", "safe-pattern"],
            },
        }
        result = _validate_overlay_patterns(overlay)
        assert result["prompt_injection"]["allowlist_patterns"] == ["safe-pattern"]

    def test_blocks_broad_path_patterns(self):
        overlay = {
            "secret_scanning": {
                "ignore_files": ["*", "tests/**", "**"],
            },
        }
        result = _validate_overlay_patterns(overlay)
        assert result["secret_scanning"]["ignore_files"] == ["tests/**"]

    def test_blocks_traversal_path(self):
        overlay = {
            "secret_scanning": {
                "ignore_files": ["../../../etc/passwd", "tests/**"],
            },
        }
        result = _validate_overlay_patterns(overlay)
        assert result["secret_scanning"]["ignore_files"] == ["tests/**"]

    def test_passes_valid_patterns(self):
        overlay = {
            "prompt_injection": {
                "allowlist_patterns": ["test-fixture-\\d+"],
            },
            "secret_scanning": {
                "ignore_files": ["tests/fixtures/**"],
            },
        }
        result = _validate_overlay_patterns(overlay)
        assert result == overlay


class TestLoadTargetAllowlists:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        result = load_target_allowlists(str(tmp_path / "nonexistent"))
        assert result == {}

    def test_empty_dir_returns_empty(self, tmp_path):
        result = load_target_allowlists(str(tmp_path))
        assert result == {}

    def test_loads_ai_guardian_json(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "enabled": True,
                    "action": "block",
                    "allowlist_patterns": ["test-safe"],
                },
                "secret_scanning": {
                    "ignore_files": ["tests/fixtures/**"],
                },
            },
        )
        result = load_target_allowlists(str(target_dir))
        assert result["prompt_injection"]["allowlist_patterns"] == ["test-safe"]
        assert result["secret_scanning"]["ignore_files"] == ["tests/fixtures/**"]
        assert "enabled" not in result.get("prompt_injection", {})
        assert "action" not in result.get("prompt_injection", {})

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="tomllib requires Python 3.11+; tomli may not be installed",
    )
    def test_loads_aiguardignore(self, target_dir):
        _write_aiguardignore(
            target_dir,
            '[secret_scanning.allowlist]\npaths = ["tests/secrets/**"]\n',
        )
        result = load_target_allowlists(str(target_dir))
        assert "tests/secrets/**" in result.get("secret_scanning", {}).get(
            "ignore_files", []
        )

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="tomllib requires Python 3.11+; tomli may not be installed",
    )
    def test_loads_gitleaks_toml(self, target_dir):
        # .gitleaks.toml needs a git repo for find_project_root
        # Pass project_root directly by creating in target_dir
        _write_gitleaks_toml(
            target_dir,
            '[allowlist]\npaths = ["vendor/**"]\n',
        )
        result = load_target_allowlists(str(target_dir))
        ignore_files = result.get("secret_scanning", {}).get("ignore_files", [])
        assert "vendor/**" in ignore_files

    def test_invalid_json_returns_empty(self, target_dir):
        config_path = target_dir / ".ai-guardian" / "ai-guardian.json"
        config_path.write_text("not valid json")
        result = load_target_allowlists(str(target_dir))
        assert result == {}

    def test_merges_all_sources(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": ["pi-pattern"],
                },
                "secret_scanning": {
                    "ignore_files": ["from-config/**"],
                },
            },
        )
        result = load_target_allowlists(str(target_dir))
        assert "pi-pattern" in result["prompt_injection"]["allowlist_patterns"]
        assert "from-config/**" in result["secret_scanning"]["ignore_files"]

    def test_dangerous_patterns_filtered(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": [".*", "safe-one"],
                },
            },
        )
        result = load_target_allowlists(str(target_dir))
        patterns = result.get("prompt_injection", {}).get("allowlist_patterns", [])
        assert ".*" not in patterns
        assert "safe-one" in patterns


class TestMergeTargetAllowlists:
    def test_merge_appends_lists(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": ["target-pat"],
                },
            },
        )
        base = {
            "prompt_injection": {
                "enabled": True,
                "action": "block",
                "allowlist_patterns": ["base-pat"],
            },
        }
        result = merge_target_allowlists(base, str(target_dir))
        pi = result["prompt_injection"]
        assert pi["enabled"] is True
        assert pi["action"] == "block"
        assert "base-pat" in pi["allowlist_patterns"]
        assert "target-pat" in pi["allowlist_patterns"]

    def test_merge_preserves_base_settings(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": ["target-pat"],
                },
            },
        )
        base = {
            "prompt_injection": {
                "enabled": True,
                "action": "block",
                "sensitivity": "high",
            },
            "secret_scanning": {
                "enabled": True,
            },
        }
        result = merge_target_allowlists(base, str(target_dir))
        assert result["prompt_injection"]["enabled"] is True
        assert result["prompt_injection"]["action"] == "block"
        assert result["prompt_injection"]["sensitivity"] == "high"
        assert result["secret_scanning"]["enabled"] is True

    def test_merge_none_base(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": ["pat"],
                },
            },
        )
        result = merge_target_allowlists(None, str(target_dir))
        assert result["prompt_injection"]["allowlist_patterns"] == ["pat"]

    def test_merge_does_not_mutate_base(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": ["target"],
                },
            },
        )
        base = {
            "prompt_injection": {
                "allowlist_patterns": ["base"],
            },
        }
        original_base = json.loads(json.dumps(base))
        merge_target_allowlists(base, str(target_dir))
        assert base == original_base

    def test_merge_deduplicates(self, target_dir):
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": ["same-pat"],
                },
            },
        )
        base = {
            "prompt_injection": {
                "allowlist_patterns": ["same-pat"],
            },
        }
        result = merge_target_allowlists(base, str(target_dir))
        assert result["prompt_injection"]["allowlist_patterns"].count("same-pat") == 1

    def test_merge_no_target_config_returns_base_copy(self, tmp_path):
        base = {"prompt_injection": {"enabled": True}}
        result = merge_target_allowlists(base, str(tmp_path))
        assert result == base
        assert result is not base

    def test_merge_ignores_immutable_on_base(self, target_dir):
        """Target allowlists merge even into immutable base sections."""
        _write_config(
            target_dir,
            {
                "prompt_injection": {
                    "allowlist_patterns": ["target-pat"],
                },
            },
        )
        base = {
            "prompt_injection": {
                "immutable": True,
                "action": "block",
                "allowlist_patterns": ["base-pat"],
            },
        }
        result = merge_target_allowlists(base, str(target_dir))
        pi = result["prompt_injection"]
        assert "base-pat" in pi["allowlist_patterns"]
        assert "target-pat" in pi["allowlist_patterns"]
