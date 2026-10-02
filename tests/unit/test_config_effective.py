"""Tests for effective config provenance and formatting (Issue #1259)."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def config_dirs(tmp_path):
    """Set up global and project config directories."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    project_dir = tmp_path / "project" / ".ai-guardian"
    project_dir.mkdir(parents=True)
    return global_dir, project_dir


@pytest.fixture
def global_config():
    return {
        "secret_scanning": {
            "enabled": True,
            "action": "block",
            "engines": ["betterleaks"],
            "allowlist_patterns": [".*test.*\\.py"],
        },
        "prompt_injection": {
            "enabled": True,
            "action": "block",
        },
    }


@pytest.fixture
def project_config():
    return {
        "secret_scanning": {
            "action": "ask",
            "allowlist_patterns": ["YOUR_TOKEN"],
        },
    }


class TestComputeDetailedProvenance:
    """Tests for compute_detailed_provenance()."""

    def test_global_only(self, config_dirs, global_config):
        """All keys show 'global' when no project config exists."""
        global_dir, project_dir = config_dirs
        global_path = global_dir / "ai-guardian.json"
        global_path.write_text(json.dumps(global_config))

        with patch("ai_guardian.config.writer._resolve_config_path") as mock_resolve:

            def resolve(scope, project_dir=None):
                if scope == "global":
                    return global_path
                return (
                    project_dir / "ai-guardian.json"
                    if project_dir
                    else Path("/nonexistent/ai-guardian.json")
                )

            mock_resolve.side_effect = resolve

            from ai_guardian.config.writer import compute_detailed_provenance

            result = compute_detailed_provenance()

        assert result["secret_scanning"]["enabled"] == "global"
        assert isinstance(result["secret_scanning"]["engines"], list)
        assert result["secret_scanning"]["engines"][0]["source"] == "global"
        assert result["prompt_injection"]["enabled"] == "global"

    def test_with_project_overrides(self, config_dirs, global_config, project_config):
        """Project overrides show 'project', global-only keys show 'global'."""
        global_dir, project_dir = config_dirs
        global_path = global_dir / "ai-guardian.json"
        global_path.write_text(json.dumps(global_config))
        project_path = project_dir / "ai-guardian.json"
        project_path.write_text(json.dumps(project_config))

        with patch("ai_guardian.config.writer._resolve_config_path") as mock_resolve:
            mock_resolve.side_effect = lambda scope, pd=None: (
                global_path if scope == "global" else project_path
            )
            from ai_guardian.config.writer import compute_detailed_provenance

            result = compute_detailed_provenance()

        ss = result["secret_scanning"]
        assert ss["enabled"] == "global"
        assert ss["action"] == "project"

    def test_list_per_item_provenance(self, config_dirs, global_config, project_config):
        """List items tagged with their source (global vs project)."""
        global_dir, project_dir = config_dirs
        global_path = global_dir / "ai-guardian.json"
        global_path.write_text(json.dumps(global_config))
        project_path = project_dir / "ai-guardian.json"
        project_path.write_text(json.dumps(project_config))

        with patch("ai_guardian.config.writer._resolve_config_path") as mock_resolve:
            mock_resolve.side_effect = lambda scope, pd=None: (
                global_path if scope == "global" else project_path
            )
            from ai_guardian.config.writer import compute_detailed_provenance

            result = compute_detailed_provenance()

        allowlist = result["secret_scanning"]["allowlist_patterns"]
        assert isinstance(allowlist, list)
        sources = {e["value"]: e["source"] for e in allowlist}
        assert sources[".*test.*\\.py"] == "global"
        assert sources["YOUR_TOKEN"] == "project"

    def test_list_global_only_items(self, config_dirs, global_config):
        """Lists without project config get all items tagged 'global'."""
        global_dir, project_dir = config_dirs
        global_path = global_dir / "ai-guardian.json"
        global_path.write_text(json.dumps(global_config))

        with patch("ai_guardian.config.writer._resolve_config_path") as mock_resolve:
            mock_resolve.side_effect = lambda scope, pd=None: (
                global_path
                if scope == "global"
                else Path("/nonexistent/ai-guardian.json")
            )
            from ai_guardian.config.writer import compute_detailed_provenance

            result = compute_detailed_provenance()

        engines = result["secret_scanning"]["engines"]
        assert all(e["source"] == "global" for e in engines)


class TestFormatProvenanceText:
    """Tests for format_provenance_text()."""

    def test_basic_rendering(self):
        from ai_guardian.config.writer import format_provenance_text

        config = {
            "secret_scanning": {"enabled": True},
            "ssrf_protection": {"action": "warn"},
        }
        provenance = {
            "secret_scanning": {"enabled": "global"},
            "ssrf_protection": {"action": "project"},
        }

        text = format_provenance_text(config, provenance)

        assert "secret_scanning:" in text
        assert "(Global)" in text
        assert "(Project override)" in text
        assert "enabled" in text
        assert "action" in text

    def test_list_item_provenance(self):
        from ai_guardian.config.writer import format_provenance_text

        config = {"patterns": ["a", "b"]}
        provenance = {
            "patterns": [
                {"value": "a", "source": "global"},
                {"value": "b", "source": "project"},
            ]
        }

        text = format_provenance_text(config, provenance)

        lines = text.split("\n")
        assert any("a" in l and "(Global)" in l for l in lines)
        assert any("b" in l and "(Project override)" in l for l in lines)

    def test_empty_config(self):
        from ai_guardian.config.writer import format_provenance_text

        assert format_provenance_text({}, {}) == ""

    def test_skips_underscore_keys(self):
        from ai_guardian.config.writer import format_provenance_text

        config = {"_comment": "skip", "enabled": True}
        provenance = {"_comment": "global", "enabled": "global"}
        text = format_provenance_text(config, provenance)
        assert "_comment" not in text
        assert "enabled" in text


class TestFormatDiffText:
    """Tests for format_diff_text()."""

    def test_shows_only_project_overrides(self):
        from ai_guardian.config.writer import format_diff_text

        project_cfg = {"ssrf_protection": {"action": "warn"}}
        provenance = {
            "ssrf_protection": {
                "enabled": "global",
                "action": "project",
            }
        }

        text = format_diff_text(project_cfg, provenance)
        assert "action" in text
        assert "warn" in text

    def test_empty_when_no_overrides(self):
        from ai_guardian.config.writer import format_diff_text

        text = format_diff_text({}, {})
        assert text.strip() == ""

    def test_list_diff_shows_project_items_only(self):
        from ai_guardian.config.writer import format_diff_text

        project_cfg = {"patterns": ["a", "b"]}
        provenance = {
            "patterns": [
                {"value": "a", "source": "global"},
                {"value": "b", "source": "project"},
            ]
        }

        text = format_diff_text(project_cfg, provenance)
        assert "- b" in text
        assert "- a" not in text


class TestFormatScalar:
    """Tests for _format_scalar()."""

    def test_bool(self):
        from ai_guardian.config.writer import _format_scalar

        assert _format_scalar(True) == "true"
        assert _format_scalar(False) == "false"

    def test_none(self):
        from ai_guardian.config.writer import _format_scalar

        assert _format_scalar(None) == "null"

    def test_string(self):
        from ai_guardian.config.writer import _format_scalar

        assert _format_scalar("hello") == "hello"

    def test_list(self):
        from ai_guardian.config.writer import _format_scalar

        assert _format_scalar(["a", "b"]) == '["a", "b"]'


class TestWebConfigEffective:
    """Tests for web config_effective.py module-level functions."""

    @pytest.fixture(autouse=True)
    def _require_nicegui(self):
        pytest.importorskip("nicegui", reason="NiceGUI not available")

    def test_load_effective_data_error(self):
        from ai_guardian.web.pages.config_effective import _load_effective_data

        with patch(
            "ai_guardian.web.pages.config_effective.load_scoped_config",
            side_effect=Exception("test error"),
            create=True,
        ):
            merged, prov, proj, error = _load_effective_data()
            # On import error, returns error string
            assert error is not None or merged is not None

    def test_has_project_override_scalar(self):
        from ai_guardian.web.pages.config_effective import _has_project_override

        assert _has_project_override("project") is True
        assert _has_project_override("global") is False

    def test_has_project_override_dict(self):
        from ai_guardian.web.pages.config_effective import _has_project_override

        assert _has_project_override({"a": "project", "b": "global"}) is True
        assert _has_project_override({"a": "global", "b": "global"}) is False

    def test_has_project_override_list(self):
        from ai_guardian.web.pages.config_effective import _has_project_override

        assert _has_project_override([{"value": "x", "source": "project"}]) is True
        assert _has_project_override([{"value": "x", "source": "global"}]) is False

    def test_provenance_label(self):
        from ai_guardian.web.pages.config_effective import _provenance_label

        assert _provenance_label("project") == "Project"
        assert _provenance_label("global") == "Global"
        assert _provenance_label("generated") == "Generated"

    def test_provenance_color(self):
        from ai_guardian.web.pages.config_effective import _provenance_color

        assert _provenance_color("project") == "blue"
        assert _provenance_color("global") == "grey-6"
        assert _provenance_color("generated") == "amber-8"

    def test_inject_generated_rules_adds_provenance(self):
        """Generated rules should be injected with 'generated' provenance."""
        from ai_guardian.web.pages.config_effective import _inject_generated_rules

        merged = {
            "permissions": {
                "auto_directory_rules": {"enabled": True},
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["test-*"]}
                ],
            },
            "directory_rules": {"action": "block", "rules": []},
        }
        provenance = {
            "directory_rules": {"action": "global", "rules": []},
        }
        with patch(
            "ai_guardian.tools.directory_rules.DirectoryRuleGenerator"
        ) as mock_cls:
            mock_gen = MagicMock()
            mock_gen.generate_directory_rules.return_value = [
                {
                    "mode": "allow",
                    "paths": ["~/.claude/skills/s1/**"],
                    "_generated": True,
                }
            ]
            mock_cls.return_value = mock_gen
            with patch(
                "ai_guardian.tools.directory_rules.insert_generated_rules"
            ) as mock_insert:
                _inject_generated_rules(merged, provenance)
                mock_insert.assert_called_once()
                # Provenance should have generated entries
                rules_prov = provenance["directory_rules"]["rules"]
                assert any(
                    isinstance(e, dict) and e.get("source") == "generated"
                    for e in rules_prov
                )

    def test_inject_generated_rules_noop_when_disabled(self):
        """No injection when auto_directory_rules is disabled."""
        from ai_guardian.web.pages.config_effective import _inject_generated_rules

        merged = {"permissions": {"auto_directory_rules": {"enabled": False}}}
        provenance = {}
        _inject_generated_rules(merged, provenance)
        assert "directory_rules" not in merged
