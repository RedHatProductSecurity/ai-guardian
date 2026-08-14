"""Tests for Web Console Phase 2 pages (Permissions & Secrets)."""

import json
from unittest import mock

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


# ---------------------------------------------------------------------------
# Import / existence tests
# ---------------------------------------------------------------------------


class TestPageImports:
    """Verify each Phase 2 page module imports and exposes its create function."""

    def test_permission_rules_page_exists(self):
        from ai_guardian.web.pages.permission_rules import (
            create_permission_rules_page,
        )

        assert callable(create_permission_rules_page)

    def test_skills_page_exists(self):
        from ai_guardian.web.pages.skills import create_skills_page

        assert callable(create_skills_page)

    def test_mcp_servers_page_exists(self):
        from ai_guardian.web.pages.mcp_servers import create_mcp_servers_page

        assert callable(create_mcp_servers_page)

    def test_mcp_security_page_exists(self):
        from ai_guardian.web.pages.mcp_security import create_mcp_security_page

        assert callable(create_mcp_security_page)

    def test_permissions_discovery_page_exists(self):
        from ai_guardian.web.pages.permissions_discovery import (
            create_permissions_discovery_page,
        )

        assert callable(create_permissions_discovery_page)

    def test_directory_rules_page_exists(self):
        from ai_guardian.web.pages.directory_rules import (
            create_directory_rules_page,
        )

        assert callable(create_directory_rules_page)

    def test_secrets_page_exists(self):
        from ai_guardian.web.pages.secrets import create_secrets_page

        assert callable(create_secrets_page)

    def test_secret_engines_page_exists(self):
        from ai_guardian.web.pages.secret_engines import (
            create_secret_engines_page,
        )

        assert callable(create_secret_engines_page)

    def test_secret_redaction_page_exists(self):
        from ai_guardian.web.pages.secret_redaction import (
            create_secret_redaction_page,
        )

        assert callable(create_secret_redaction_page)


# ---------------------------------------------------------------------------
# Route / sidebar consistency
# ---------------------------------------------------------------------------


class TestRouteSidebarConsistency:
    """Verify every Phase 2 route path appears in the sidebar and app."""

    # Routes that appear in the sidebar
    SIDEBAR_ROUTES = [
        "/permission-rules",
        "/mcp-servers",
        "/mcp-security",
        "/permissions-discovery",
        "/directory-rules",
        "/secrets",
        "/secret-engines",
        "/secret-redaction",
    ]

    # Routes registered in app.py (includes legacy routes for backward compat)
    APP_ROUTES = [
        "/permission-rules",
        "/skills",
        "/mcp-servers",
        "/mcp-security",
        "/permissions-discovery",
        "/directory-rules",
        "/secrets",
        "/secret-engines",
        "/secret-redaction",
    ]

    def test_all_routes_registered_in_app(self):
        """Check that app.py registers all Phase 2 routes."""
        import inspect
        from ai_guardian.web.app import WebConsole

        source = inspect.getsource(WebConsole._register_pages)
        for route in self.APP_ROUTES:
            assert route in source, f"Route {route} not found in app.py"

    def test_all_sidebar_routes_in_sidebar(self):
        """Check that header.py NAV_GROUPS includes all active paths."""
        from ai_guardian.web.components.header import NAV_GROUPS

        all_suffixes = [
            suffix for _group, items in NAV_GROUPS for _label, suffix in items
        ]
        for route in self.SIDEBAR_ROUTES:
            assert (
                route in all_suffixes
            ), f"Route {route} not found in sidebar navigation"

    def test_skills_route_not_in_sidebar(self):
        """Skills route should NOT be in sidebar (consolidated)."""
        from ai_guardian.web.components.header import NAV_GROUPS

        all_suffixes = [
            suffix for _group, items in NAV_GROUPS for _label, suffix in items
        ]
        assert (
            "/skills" not in all_suffixes
        ), "Legacy /skills route should not appear in sidebar"


# ---------------------------------------------------------------------------
# Permission Rules config logic (consolidated page)
# ---------------------------------------------------------------------------


class TestPermissionRulesConfigLogic:
    def test_get_all_rules_empty(self):
        from ai_guardian.web.pages.permission_rules import _get_all_rules

        assert _get_all_rules({}) == []

    def test_get_all_rules_returns_all(self):
        from ai_guardian.web.pages.permission_rules import _get_all_rules

        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]},
                    {"matcher": "mcp__foo", "mode": "allow", "patterns": ["*"]},
                    {"matcher": "*", "mode": "deny", "patterns": ["*"]},
                ],
            }
        }
        rules = _get_all_rules(config)
        assert len(rules) == 3
        assert rules[0]["matcher"] == "Skill"
        assert rules[1]["matcher"] == "mcp__foo"
        assert rules[2]["matcher"] == "*"

    def test_get_all_rules_non_dict_permissions(self):
        from ai_guardian.web.pages.permission_rules import _get_all_rules

        assert _get_all_rules({"permissions": "invalid"}) == []

    def test_classify_matcher_mcp(self):
        from ai_guardian.web.pages.permission_rules import _classify_matcher

        label, icon, color = _classify_matcher("mcp__server__*")
        assert label == "MCP"
        assert color == "purple"

    def test_classify_matcher_skill(self):
        from ai_guardian.web.pages.permission_rules import _classify_matcher

        label, icon, color = _classify_matcher("Skill")
        assert label == "Skill"
        assert color == "blue"

    def test_classify_matcher_tool(self):
        from ai_guardian.web.pages.permission_rules import _classify_matcher

        for tool in ("Bash", "Write", "Read", "Edit", "Glob", "Grep", "WebFetch"):
            label, icon, color = _classify_matcher(tool)
            assert label == "Tool"
            assert color == "orange"

    def test_classify_matcher_global(self):
        from ai_guardian.web.pages.permission_rules import _classify_matcher

        label, icon, color = _classify_matcher("*")
        assert label == "Global"
        assert color == "grey"

    def test_classify_matcher_custom(self):
        from ai_guardian.web.pages.permission_rules import _classify_matcher

        label, icon, color = _classify_matcher("MyCustomTool")
        assert label == "Custom"
        assert color == "teal"

    def test_format_expiration_none(self):
        from ai_guardian.web.pages.permission_rules import _format_expiration

        assert _format_expiration(None) is None
        assert _format_expiration("") is None

    def test_format_expiration_expired(self):
        from ai_guardian.web.pages.permission_rules import _format_expiration

        result = _format_expiration("2020-01-01T00:00:00Z")
        assert result is not None
        assert result[0] == "EXPIRED"
        assert result[1] == "red"

    def test_format_expiration_future(self):
        from ai_guardian.web.pages.permission_rules import _format_expiration
        from datetime import datetime, timezone, timedelta

        future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        result = _format_expiration(future)
        assert result is not None
        assert "expires" in result[0]

    def test_parse_duration_valid(self):
        from ai_guardian.web.pages.permission_rules import _parse_duration
        from datetime import timedelta

        assert _parse_duration("30m") == timedelta(minutes=30)
        assert _parse_duration("2h") == timedelta(hours=2)
        assert _parse_duration("1d") == timedelta(days=1)
        assert _parse_duration("1d2h30m") == timedelta(days=1, hours=2, minutes=30)

    def test_parse_duration_plain_number(self):
        from ai_guardian.web.pages.permission_rules import _parse_duration
        from datetime import timedelta

        assert _parse_duration("60") == timedelta(minutes=60)

    def test_parse_duration_invalid(self):
        from ai_guardian.web.pages.permission_rules import _parse_duration

        assert _parse_duration("abc") is None
        assert _parse_duration("0d0h0m") is None

    def test_pattern_to_str_string(self):
        from ai_guardian.web.pages.permission_rules import _pattern_to_str

        assert _pattern_to_str("daf-*") == "daf-*"

    def test_pattern_to_str_dict(self):
        from ai_guardian.web.pages.permission_rules import _pattern_to_str

        assert _pattern_to_str({"pattern": "temp", "valid_until": "x"}) == "temp"

    def test_pattern_to_str_dict_no_pattern_key(self):
        from ai_guardian.web.pages.permission_rules import _pattern_to_str

        result = _pattern_to_str({"foo": "bar"})
        assert isinstance(result, str)

    def test_matches_search_empty_queries(self):
        from ai_guardian.web.pages.permission_rules import _matches_search

        rule = {"matcher": "Skill", "patterns": ["daf-*"]}
        assert _matches_search(rule, "", "") is True
        assert _matches_search(rule, None, None) is True
        assert _matches_search(rule, "", None) is True

    def test_matches_search_by_matcher(self):
        from ai_guardian.web.pages.permission_rules import _matches_search

        rule = {"matcher": "mcp__notebook__*", "patterns": ["*"]}
        assert _matches_search(rule, "notebook", "") is True
        assert _matches_search(rule, "NOTEBOOK", "") is True
        assert _matches_search(rule, "xyz", "") is False

    def test_matches_search_by_pattern(self):
        from ai_guardian.web.pages.permission_rules import _matches_search

        rule = {"matcher": "Skill", "patterns": ["daf-*", "review-pr"]}
        assert _matches_search(rule, "", "review") is True
        assert _matches_search(rule, "", "daf") is True
        assert _matches_search(rule, "", "xyz") is False

    def test_matches_search_both_fields(self):
        from ai_guardian.web.pages.permission_rules import _matches_search

        rule = {"matcher": "Skill", "patterns": ["daf-*", "review-pr"]}
        # Both match
        assert _matches_search(rule, "Skill", "daf") is True
        # Matcher matches but pattern doesn't
        assert _matches_search(rule, "Skill", "xyz") is False
        # Pattern matches but matcher doesn't
        assert _matches_search(rule, "mcp", "daf") is False

    def test_matches_search_dict_pattern(self):
        from ai_guardian.web.pages.permission_rules import _matches_search

        rule = {
            "matcher": "Skill",
            "patterns": [{"pattern": "temp-skill", "valid_until": "x"}],
        }
        assert _matches_search(rule, "", "temp") is True
        assert _matches_search(rule, "", "xyz") is False


# ---------------------------------------------------------------------------
# Skills config logic (legacy — still tested for backward compat)
# ---------------------------------------------------------------------------


class TestSkillsConfigLogic:
    def test_get_skill_patterns_empty(self):
        from ai_guardian.web.pages.skills import _get_skill_patterns

        assert _get_skill_patterns({}) == ([], [])

    def test_get_skill_patterns_extracts_allow_deny(self):
        from ai_guardian.web.pages.skills import _get_skill_patterns

        config = {
            "permissions": {
                "enabled": True,
                "rules": [
                    {"matcher": "Skill", "mode": "allow", "patterns": ["daf-*"]},
                    {"matcher": "Skill", "mode": "deny", "patterns": ["evil-*"]},
                    {"matcher": "mcp__foo", "mode": "allow", "patterns": ["*"]},
                ],
            }
        }
        allow, deny = _get_skill_patterns(config)
        assert allow == ["daf-*"]
        assert deny == ["evil-*"]

    def test_get_skill_patterns_ignores_non_skill(self):
        from ai_guardian.web.pages.skills import _get_skill_patterns

        config = {
            "permissions": {
                "rules": [
                    {"matcher": "mcp__server", "mode": "allow", "patterns": ["*"]},
                ],
            }
        }
        allow, deny = _get_skill_patterns(config)
        assert allow == []
        assert deny == []

    def test_format_expiration_none(self):
        from ai_guardian.web.pages.skills import _format_expiration

        assert _format_expiration(None) is None
        assert _format_expiration("") is None

    def test_format_expiration_expired(self):
        from ai_guardian.web.pages.skills import _format_expiration

        result = _format_expiration("2020-01-01T00:00:00Z")
        assert result is not None
        assert result[0] == "EXPIRED"
        assert result[1] == "red"

    def test_format_expiration_future(self):
        from ai_guardian.web.pages.skills import _format_expiration
        from datetime import datetime, timezone, timedelta

        future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        result = _format_expiration(future)
        assert result is not None
        assert "expires" in result[0]


# ---------------------------------------------------------------------------
# MCP Servers config logic
# ---------------------------------------------------------------------------


class TestMCPServersConfigLogic:
    def test_get_mcp_rules_empty(self):
        from ai_guardian.web.pages.mcp_servers import _get_mcp_rules

        assert _get_mcp_rules({}) == []

    def test_get_mcp_rules_filters_by_prefix(self):
        from ai_guardian.web.pages.mcp_servers import _get_mcp_rules

        config = {
            "permissions": {
                "rules": [
                    {"matcher": "mcp__server__*", "mode": "allow", "patterns": ["*"]},
                    {"matcher": "Skill", "mode": "allow", "patterns": ["foo"]},
                    {"matcher": "mcp__other", "mode": "deny", "patterns": ["bar"]},
                ],
            }
        }
        rules = _get_mcp_rules(config)
        assert len(rules) == 2
        assert rules[0]["matcher"] == "mcp__server__*"
        assert rules[1]["matcher"] == "mcp__other"


# ---------------------------------------------------------------------------
# Directory Rules validation
# ---------------------------------------------------------------------------


class TestDirectoryRulesValidation:
    def test_validate_valid_rules(self):
        from ai_guardian.web.pages.directory_rules import _validate_rules_json

        text = '[{"mode": "deny", "paths": ["~/.ssh/**"]}]'
        parsed, err = _validate_rules_json(text)
        assert err is None
        assert len(parsed) == 1

    def test_validate_invalid_json(self):
        from ai_guardian.web.pages.directory_rules import _validate_rules_json

        parsed, err = _validate_rules_json("{bad json")
        assert parsed is None
        assert "Invalid JSON" in err

    def test_validate_not_array(self):
        from ai_guardian.web.pages.directory_rules import _validate_rules_json

        parsed, err = _validate_rules_json('{"mode": "deny"}')
        assert parsed is None
        assert "array" in err

    def test_validate_missing_mode(self):
        from ai_guardian.web.pages.directory_rules import _validate_rules_json

        parsed, err = _validate_rules_json('[{"paths": ["/tmp"]}]')
        assert parsed is None
        assert "mode" in err

    def test_validate_invalid_mode(self):
        from ai_guardian.web.pages.directory_rules import _validate_rules_json

        parsed, err = _validate_rules_json('[{"mode": "maybe", "paths": ["/tmp"]}]')
        assert parsed is None
        assert "mode" in err

    def test_validate_missing_paths(self):
        from ai_guardian.web.pages.directory_rules import _validate_rules_json

        parsed, err = _validate_rules_json('[{"mode": "deny"}]')
        assert parsed is None
        assert "paths" in err

    def test_validate_empty_paths(self):
        from ai_guardian.web.pages.directory_rules import _validate_rules_json

        parsed, err = _validate_rules_json('[{"mode": "deny", "paths": []}]')
        assert parsed is None
        assert "paths" in err

    def test_get_editable_rules_filters_generated(self):
        from ai_guardian.web.pages.directory_rules import _get_editable_rules

        config = {
            "directory_rules": {
                "rules": [
                    {"mode": "deny", "paths": ["/secret"], "_generated": True},
                    {"mode": "allow", "paths": ["/safe"]},
                    {"mode": "deny", "paths": ["/locked"], "_immutable": True},
                ]
            }
        }
        editable = _get_editable_rules(config)
        assert len(editable) == 1
        assert editable[0]["paths"] == ["/safe"]

    def test_get_preserved_rules(self):
        from ai_guardian.web.pages.directory_rules import _get_preserved_rules

        config = {
            "directory_rules": {
                "rules": [
                    {"mode": "deny", "paths": ["/secret"], "_generated": True},
                    {"mode": "allow", "paths": ["/safe"]},
                ]
            }
        }
        preserved = _get_preserved_rules(config)
        assert len(preserved) == 1
        assert preserved[0].get("_generated") is True


# ---------------------------------------------------------------------------
# Secret Engines validation
# ---------------------------------------------------------------------------


class TestSecretEnginesValidation:
    def test_validate_simple_engines(self):
        from ai_guardian.web.pages.secret_engines import _validate_engines_json

        parsed, err = _validate_engines_json('["gitleaks", "betterleaks"]')
        assert err is None
        assert len(parsed) == 2

    def test_validate_advanced_engines(self):
        from ai_guardian.web.pages.secret_engines import _validate_engines_json

        text = '[{"type": "gitleaks"}, {"type": "trufflehog"}]'
        parsed, err = _validate_engines_json(text)
        assert err is None
        assert len(parsed) == 2

    def test_validate_invalid_engine_name(self):
        from ai_guardian.web.pages.secret_engines import _validate_engines_json

        parsed, err = _validate_engines_json('["nonexistent"]')
        assert parsed is None
        assert "unknown" in err

    def test_validate_missing_type_field(self):
        from ai_guardian.web.pages.secret_engines import _validate_engines_json

        parsed, err = _validate_engines_json('[{"binary": "/bin/x"}]')
        assert parsed is None
        assert "type" in err

    def test_validate_not_array(self):
        from ai_guardian.web.pages.secret_engines import _validate_engines_json

        parsed, err = _validate_engines_json('"gitleaks"')
        assert parsed is None
        assert "array" in err

    def test_validate_invalid_json(self):
        from ai_guardian.web.pages.secret_engines import _validate_engines_json

        parsed, err = _validate_engines_json("[bad")
        assert parsed is None
        assert "Invalid JSON" in err


# ---------------------------------------------------------------------------
# MCP Security audit wrapper
# ---------------------------------------------------------------------------


class TestMCPSecurityAudit:
    def test_run_audit_via_service_returns_dict(self):
        from ai_guardian.web.pages.mcp_security import _run_audit_via_service

        mock_service = mock.MagicMock()
        mock_target = mock.MagicMock()
        mock_service.get_target_by_name.return_value = mock_target
        mock_service.get_mcp_audit.return_value = {
            "servers": [],
            "findings": [],
            "trusted": 0,
            "untrusted": 0,
        }

        result = _run_audit_via_service(mock_service, "test-daemon")
        assert result is not None
        assert result["servers"] == []

    def test_run_audit_via_service_handles_error(self):
        from ai_guardian.web.pages.mcp_security import _run_audit_via_service

        mock_service = mock.MagicMock()
        mock_service.get_target_by_name.side_effect = Exception("boom")

        result = _run_audit_via_service(mock_service, "test-daemon")
        assert result is None


# ---------------------------------------------------------------------------
# Config load/save
# ---------------------------------------------------------------------------


class TestConfigLoadSave:
    def test_load_config_missing_file(self, tmp_path):
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config

            assert load_web_config() == {}

    def test_load_config_valid_file(self, tmp_path):
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"secret_scanning": {"enabled": true}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config

            result = load_web_config()
            assert result["secret_scanning"]["enabled"] is True

    def test_save_config_creates_file(self, tmp_path):
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import save_web_config

            save_web_config({"test": True})
            config_file = tmp_path / "ai-guardian.json"
            assert config_file.exists()
            data = json.loads(config_file.read_text())
            assert data["test"] is True

    def test_save_config_pretty_prints(self, tmp_path):
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import save_web_config

            save_web_config({"a": 1, "b": 2})
            text = (tmp_path / "ai-guardian.json").read_text()
            assert "\n" in text
            assert text.endswith("\n")


# ---------------------------------------------------------------------------
# Secret Validation config logic (Issue #976)
# ---------------------------------------------------------------------------


class TestSecretValidationConfigLogic:
    """Tests for secret validation UI config read/write patterns."""

    def test_validate_secrets_default_false(self, tmp_path):
        """validate_secrets defaults to False when not in config."""
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"secret_scanning": {"enabled": true}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config

            config = load_web_config()
            ss = config.get("secret_scanning", {})
            assert ss.get("validate_secrets", False) is False

    def test_validate_secrets_roundtrip(self, tmp_path):
        """validate_secrets can be saved and loaded back."""
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"secret_scanning": {}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config, save_web_config

            cfg = load_web_config()
            cfg["secret_scanning"]["validate_secrets"] = True
            save_web_config(cfg)

            cfg2 = load_web_config()
            assert cfg2["secret_scanning"]["validate_secrets"] is True

    def test_validation_timeout_ms_default(self, tmp_path):
        """validation_timeout_ms defaults to 3000 when absent."""
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"secret_scanning": {}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config

            config = load_web_config()
            ss = config.get("secret_scanning", {})
            assert ss.get("validation_timeout_ms", 3000) == 3000

    def test_validation_timeout_ms_roundtrip(self, tmp_path):
        """validation_timeout_ms can be saved and loaded back."""
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"secret_scanning": {}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config, save_web_config

            cfg = load_web_config()
            cfg["secret_scanning"]["validation_timeout_ms"] = 5000
            save_web_config(cfg)

            cfg2 = load_web_config()
            assert cfg2["secret_scanning"]["validation_timeout_ms"] == 5000

    def test_on_inactive_default_warn(self, tmp_path):
        """on_inactive defaults to 'warn' when absent."""
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"secret_scanning": {}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config

            config = load_web_config()
            ss = config.get("secret_scanning", {})
            assert ss.get("on_inactive", "warn") == "warn"

    def test_on_inactive_roundtrip(self, tmp_path):
        """on_inactive can be saved and loaded back."""
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text('{"secret_scanning": {}}')

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config, save_web_config

            cfg = load_web_config()
            cfg["secret_scanning"]["on_inactive"] = "allow"
            save_web_config(cfg)

            cfg2 = load_web_config()
            assert cfg2["secret_scanning"]["on_inactive"] == "allow"

    def test_validation_fields_preserve_other_config(self, tmp_path):
        """Saving validation fields does not clobber existing config."""
        config_file = tmp_path / "ai-guardian.json"
        config_file.write_text(
            json.dumps(
                {
                    "secret_scanning": {
                        "enabled": True,
                        "allowlist_patterns": ["pk_test_.*"],
                    }
                }
            )
        )

        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config, save_web_config

            cfg = load_web_config()
            cfg["secret_scanning"]["validate_secrets"] = True
            cfg["secret_scanning"]["validation_timeout_ms"] = 2000
            cfg["secret_scanning"]["on_inactive"] = "allow"
            save_web_config(cfg)

            cfg2 = load_web_config()
            ss = cfg2["secret_scanning"]
            # New fields saved
            assert ss["validate_secrets"] is True
            assert ss["validation_timeout_ms"] == 2000
            assert ss["on_inactive"] == "allow"
            # Existing fields preserved
            assert ss["enabled"] is True
            assert ss["allowlist_patterns"] == ["pk_test_.*"]

    def test_validation_fields_in_empty_config(self, tmp_path):
        """Saving validation fields works when starting from empty config."""
        with (
            mock.patch(
                "ai_guardian.config.utils.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "ai_guardian.config.writer.get_config_dir", return_value=tmp_path
            ),
        ):
            from ai_guardian.web.config_helpers import load_web_config, save_web_config

            cfg = load_web_config()  # {} since file doesn't exist
            ss = cfg.setdefault("secret_scanning", {})
            ss["validate_secrets"] = True
            save_web_config(cfg)

            cfg2 = load_web_config()
            assert cfg2["secret_scanning"]["validate_secrets"] is True
