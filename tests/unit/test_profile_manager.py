#!/usr/bin/env python3
"""Tests for the profile_manager module."""

import json

import pytest

from ai_guardian.profile_manager import (
    BUILT_IN_PROFILES,
    ProfileNotFoundError,
    format_profile_list,
    get_schema_uri,
    list_profiles,
    load_profile,
    resolve_profile,
    save_profile,
)


class TestGetSchemaUri:
    """Tests for get_schema_uri()."""

    def test_returns_file_uri(self):
        uri = get_schema_uri()
        assert uri.startswith("file://")
        assert "ai-guardian-config.schema.json" in uri


class TestResolveProfile:
    """Tests for resolve_profile()."""

    def test_resolve_builtin_minimal(self):
        ptype, path = resolve_profile("@minimal")
        assert ptype == "builtin"
        assert path.name == "minimal.json"
        assert path.exists()

    def test_resolve_builtin_standard(self):
        ptype, path = resolve_profile("@standard")
        assert ptype == "builtin"
        assert path.name == "standard.json"

    def test_resolve_builtin_strict(self):
        ptype, path = resolve_profile("@strict")
        assert ptype == "builtin"
        assert path.name == "strict.json"

    def test_resolve_builtin_unknown(self):
        with pytest.raises(ProfileNotFoundError, match="Unknown built-in profile"):
            resolve_profile("@nonexistent")

    def test_resolve_custom_profile(self, tmp_path):
        profiles_dir = tmp_path / "auto_config" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        (profiles_dir / "my-team.json").write_text('{"test": true}')

        ptype, path = resolve_profile("my-team")
        assert ptype == "custom"
        assert path.name == "my-team.json"

    def test_resolve_custom_not_found(self):
        with pytest.raises(ProfileNotFoundError, match="Profile not found"):
            resolve_profile("nonexistent-custom")

    @pytest.mark.parametrize("name", ["minimal", "standard", "strict", "moderator"])
    def test_resolve_builtin_without_at_prefix(self, name):
        """Bare builtin name resolves to builtin (e.g. 'standard' == '@standard')."""
        ptype, path = resolve_profile(name)
        assert ptype == "builtin"
        assert path.exists()

    def test_resolve_file_path(self, tmp_path):
        profile_file = tmp_path / "my-profile.json"
        profile_file.write_text('{"test": true}')

        ptype, path = resolve_profile(str(profile_file))
        assert ptype == "file"
        assert path == profile_file

    def test_resolve_file_path_not_found(self):
        with pytest.raises(ProfileNotFoundError, match="Profile file not found"):
            resolve_profile("/nonexistent/path/profile.json")

    def test_resolve_json_extension_treated_as_file(self, tmp_path):
        profile_file = tmp_path / "custom.json"
        profile_file.write_text("{}")
        ptype, path = resolve_profile(str(profile_file))
        assert ptype == "file"


class TestLoadProfile:
    """Tests for load_profile()."""

    def test_load_builtin_minimal(self):
        config = load_profile("@minimal")
        assert isinstance(config, dict)
        assert config["prompt_injection"]["sensitivity"] == "low"
        assert config["permissions"]["enabled"] is False

    def test_load_builtin_standard(self):
        config = load_profile("@standard")
        assert isinstance(config, dict)
        assert config["prompt_injection"]["sensitivity"] == "medium"
        assert config["permissions"]["enabled"] is True

    def test_load_builtin_strict(self):
        config = load_profile("@strict")
        assert isinstance(config, dict)
        assert config["prompt_injection"]["sensitivity"] == "high"
        assert config["on_scan_error"] == "block"
        assert config["annotations"]["enabled"] is False

    def test_load_replaces_schema_placeholder(self):
        config = load_profile("@standard")
        assert config["$schema"].startswith("file://")
        assert "__SCHEMA_URI__" not in config["$schema"]

    def test_cache_omits_path_for_runtime_resolution(self):
        config = load_profile("@standard")
        engines = config["secret_scanning"]["engines"]
        gitleaks = next(
            e for e in engines if isinstance(e, dict) and e.get("type") == "gitleaks"
        )
        cache = gitleaks["pattern_server"]["cache"]
        assert (
            "path" not in cache
        ), "cache.path should not be in profile; get_cache_dir() resolves at runtime"

    @pytest.mark.parametrize("profile_name", ["@minimal", "@standard", "@strict"])
    def test_profiles_use_per_engine_pattern_server(self, profile_name):
        """All built-in profiles must use per-engine pattern_server, not legacy format (issue #558)."""
        config = load_profile(profile_name)
        ss = config["secret_scanning"]

        assert (
            "pattern_server" not in ss
        ), f"{profile_name}: top-level secret_scanning.pattern_server is deprecated"

        engines = ss["engines"]
        gitleaks = next(
            (e for e in engines if isinstance(e, dict) and e.get("type") == "gitleaks"),
            None,
        )
        assert gitleaks is not None, f"{profile_name}: missing gitleaks engine dict"
        assert (
            "pattern_server" in gitleaks
        ), f"{profile_name}: gitleaks engine must have per-engine pattern_server"

    def test_standard_matches_default_template(self):
        from ai_guardian.setup import _get_default_config_template

        default = _get_default_config_template(permissive=False)
        standard = load_profile("@standard")
        assert json.dumps(default, sort_keys=True) == json.dumps(
            standard, sort_keys=True
        )

    @pytest.mark.parametrize("profile_name", BUILT_IN_PROFILES)
    def test_builtin_tls_defaults_match_setup(self, profile_name):
        """Every profile advertises opt-in HTTPS with identical empty trust defaults."""
        from ai_guardian.setup import _get_default_config_template

        expected = _get_default_config_template()["daemon"]["rest_tls"]
        assert load_profile(f"@{profile_name}")["daemon"].get("rest_tls") == expected

    def test_load_custom_profile(self, tmp_path):
        profiles_dir = tmp_path / "auto_config" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_data = {"$schema": "__SCHEMA_URI__", "test": True}
        (profiles_dir / "custom.json").write_text(json.dumps(profile_data))

        config = load_profile("custom")
        assert config["test"] is True
        assert config["$schema"].startswith("file://")

    def test_load_file_path_profile(self, tmp_path):
        profile_file = tmp_path / "external.json"
        profile_file.write_text(json.dumps({"external": True}))

        config = load_profile(str(profile_file))
        assert config["external"] is True

    def test_load_invalid_json(self, tmp_path):
        profile_file = tmp_path / "bad.json"
        profile_file.write_text("not valid json{")

        with pytest.raises(json.JSONDecodeError):
            load_profile(str(profile_file))

    def test_load_not_found(self):
        with pytest.raises(ProfileNotFoundError):
            load_profile("@nonexistent")


class TestSaveProfile:
    """Tests for save_profile()."""

    def test_save_new_profile(self, tmp_path):
        config = {"test": True, "secret_scanning": {"enabled": True}}
        success, message = save_profile("my-team", config)
        assert success is True
        assert "Saved profile" in message

        profiles_dir = tmp_path / "auto_config" / "profiles"
        saved = json.loads((profiles_dir / "my-team.json").read_text())
        assert saved["test"] is True

    def test_save_creates_profiles_dir(self, tmp_path):
        profiles_dir = tmp_path / "auto_config" / "profiles"
        assert not profiles_dir.exists()

        save_profile("new-profile", {"test": True})
        assert profiles_dir.exists()

    def test_save_refuses_builtin_name(self):
        for name in BUILT_IN_PROFILES:
            success, message = save_profile(name, {"test": True})
            assert success is False
            assert "built-in" in message.lower()

    def test_save_refuses_at_prefix(self):
        success, message = save_profile("@custom", {"test": True})
        assert success is False
        assert "@" in message

    def test_save_invalid_name(self):
        success, message = save_profile("bad name!", {"test": True})
        assert success is False
        assert "Invalid profile name" in message

    def test_save_overwrites_existing(self, tmp_path):
        save_profile("overwrite-me", {"version": 1})
        save_profile("overwrite-me", {"version": 2})

        profiles_dir = tmp_path / "auto_config" / "profiles"
        saved = json.loads((profiles_dir / "overwrite-me.json").read_text())
        assert saved["version"] == 2


class TestListProfiles:
    """Tests for list_profiles()."""

    def test_list_builtin_only(self):
        profiles = list_profiles()
        builtin = [p for p in profiles if p["type"] == "builtin"]
        assert len(builtin) == 4
        names = {p["name"] for p in builtin}
        assert names == {"@minimal", "@standard", "@strict", "@moderator"}

    def test_list_with_custom(self, tmp_path):
        profiles_dir = tmp_path / "auto_config" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        (profiles_dir / "my-team.json").write_text("{}")

        profiles = list_profiles()
        custom = [p for p in profiles if p["type"] == "custom"]
        assert len(custom) == 1
        assert custom[0]["name"] == "my-team"

    def test_list_ignores_non_json(self, tmp_path):
        profiles_dir = tmp_path / "auto_config" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        (profiles_dir / "readme.txt").write_text("not a profile")
        (profiles_dir / "valid.json").write_text("{}")

        profiles = list_profiles()
        custom = [p for p in profiles if p["type"] == "custom"]
        assert len(custom) == 1
        assert custom[0]["name"] == "valid"


class TestFormatProfileList:
    """Tests for format_profile_list()."""

    def test_format_includes_all_builtins(self):
        output = format_profile_list()
        assert "@minimal" in output
        assert "@standard" in output
        assert "@strict" in output
        assert "@moderator" in output
        assert "Built-in:" in output

    def test_format_includes_custom(self, tmp_path):
        profiles_dir = tmp_path / "auto_config" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        (profiles_dir / "my-team.json").write_text("{}")

        output = format_profile_list()
        assert "Custom:" in output
        assert "my-team" in output


class TestProfileSchemaValidation:
    """Verify all built-in profiles are valid against the JSON schema."""

    def test_all_profiles_validate_against_schema(self):
        import jsonschema
        from importlib.resources import files

        schema_path = (
            files("ai_guardian") / "schemas" / "ai-guardian-config.schema.json"
        )
        with open(str(schema_path)) as f:
            schema = json.load(f)

        for profile_name in BUILT_IN_PROFILES:
            config = load_profile(f"@{profile_name}")
            jsonschema.validate(config, schema)
