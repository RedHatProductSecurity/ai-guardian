"""
Tests for SDK config overlay (Issue #1139) and named agent profiles (Issue #1852).

Tests cover:
- _resolve_sdk_overlay(): env var file, inline JSON, configure() API, priority
- _load_config_file(): overlay merge on top of global + project config
- configure(): cache clearing, overlay replacement
- Cache invalidation: mtime, inline value, SDK overlay id
- Doctor check_config_overlay: source detection
- SDK monitor() integration with overlay
- _load_sdk_profile(): agent/client profile loading with * (wildcard) fallback
- GuardedAgent config profile overrides (name param, logging, system_prompt_preamble)
- guarded() config profile overrides (name param, logging)
"""

import json
import logging
import os
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.config.loaders import (
    _clear_config_cache,
    _load_config_file,
    _load_sdk_profile,
    _resolve_sdk_overlay,
    _sdk_scanning,
    configure,
)


class TestResolveSDKOverlay:
    """Tests for _resolve_sdk_overlay()."""

    def test_no_overlay_returns_none(self):
        assert _resolve_sdk_overlay() is None

    def test_file_overlay_via_env_var(self, tmp_path):
        overlay_file = tmp_path / "overlay.json"
        overlay_file.write_text(json.dumps({"preferred_ui": "headless"}))
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_OVERLAY": str(overlay_file),
            },
        ):
            result = _resolve_sdk_overlay()
        assert result == {"preferred_ui": "headless"}

    def test_inline_overlay_via_env_var(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_INLINE": '{"ssrf_protection": {"action": "block"}}',
            },
        ):
            result = _resolve_sdk_overlay()
        assert result == {"ssrf_protection": {"action": "block"}}

    def test_configure_overlay(self):
        import ai_guardian.config.loaders as cl

        old = cl._sdk_overlay
        try:
            cl._sdk_overlay = {"preferred_ui": "headless"}
            result = _resolve_sdk_overlay()
            assert result == {"preferred_ui": "headless"}
        finally:
            cl._sdk_overlay = old

    def test_inline_overrides_file(self, tmp_path):
        overlay_file = tmp_path / "overlay.json"
        overlay_file.write_text(
            json.dumps(
                {
                    "preferred_ui": "tkinter",
                    "ssrf_protection": {"action": "warn"},
                }
            )
        )
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_OVERLAY": str(overlay_file),
                "AI_GUARDIAN_CONFIG_INLINE": '{"preferred_ui": "headless"}',
            },
        ):
            result = _resolve_sdk_overlay()
        assert result["preferred_ui"] == "headless"
        assert result["ssrf_protection"]["action"] == "warn"

    def test_configure_overrides_inline(self):
        import ai_guardian.config.loaders as cl

        old = cl._sdk_overlay
        try:
            cl._sdk_overlay = {"preferred_ui": "nicegui"}
            with mock.patch.dict(
                os.environ,
                {
                    "AI_GUARDIAN_CONFIG_INLINE": '{"preferred_ui": "headless"}',
                },
            ):
                result = _resolve_sdk_overlay()
            assert result["preferred_ui"] == "nicegui"
        finally:
            cl._sdk_overlay = old

    def test_all_three_merged(self, tmp_path):
        overlay_file = tmp_path / "overlay.json"
        overlay_file.write_text(json.dumps({"from_file": True, "shared": "file"}))
        import ai_guardian.config.loaders as cl

        old = cl._sdk_overlay
        try:
            cl._sdk_overlay = {"from_api": True, "shared": "api"}
            with mock.patch.dict(
                os.environ,
                {
                    "AI_GUARDIAN_CONFIG_OVERLAY": str(overlay_file),
                    "AI_GUARDIAN_CONFIG_INLINE": '{"from_inline": true, "shared": "inline"}',
                },
            ):
                result = _resolve_sdk_overlay()
            assert result["from_file"] is True
            assert result["from_inline"] is True
            assert result["from_api"] is True
            assert result["shared"] == "api"
        finally:
            cl._sdk_overlay = old

    def test_invalid_file_path_returns_none(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_OVERLAY": "/nonexistent/overlay.json",
            },
        ):
            result = _resolve_sdk_overlay()
        assert result is None

    def test_invalid_inline_json_returns_none(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_INLINE": "not valid json {{{",
            },
        ):
            result = _resolve_sdk_overlay()
        assert result is None

    def test_inline_not_dict_returns_none(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_INLINE": '["not", "a", "dict"]',
            },
        ):
            result = _resolve_sdk_overlay()
        assert result is None


class TestLoadConfigFileWithOverlay:
    """Tests for _load_config_file() with SDK overlay."""

    def setup_method(self):
        _clear_config_cache()

    def test_overlay_merges_on_top_of_global(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {
            "secret_scanning": {"enabled": True},
            "ssrf_protection": {"action": "warn"},
            "preferred_ui": "tkinter",
        }
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_CONFIG_INLINE": '{"ssrf_protection": {"action": "block"}}',
            },
        ):
            _clear_config_cache()
            config, err = _load_config_file()

        assert err is None
        assert config["secret_scanning"]["enabled"] is True
        assert config["ssrf_protection"]["action"] == "block"
        assert config["preferred_ui"] == "tkinter"

    def test_overlay_merges_on_top_of_project(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {
            "secret_scanning": {"enabled": True},
            "ssrf_protection": {"action": "warn"},
        }
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        project_dir = tmp_path / "project" / ".ai-guardian"
        project_dir.mkdir(parents=True)
        project_config = {
            "ssrf_protection": {"action": "log-only"},
            "prompt_injection": {"enabled": False},
        }
        (project_dir / "ai-guardian.json").write_text(json.dumps(project_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_PROJECT_CONFIG": str(project_dir / "ai-guardian.json"),
                "AI_GUARDIAN_CONFIG_INLINE": '{"ssrf_protection": {"action": "block"}}',
            },
        ):
            _clear_config_cache()
            config, err = _load_config_file()

        assert err is None
        assert config["secret_scanning"]["enabled"] is True
        assert config["ssrf_protection"]["action"] == "block"
        assert config["prompt_injection"]["enabled"] is False

    def test_overlay_respects_immutable_true(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {
            "ssrf_protection": {
                "immutable": True,
                "action": "warn",
            },
        }
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_CONFIG_INLINE": '{"ssrf_protection": {"action": "block"}}',
            },
        ):
            _clear_config_cache()
            config, err = _load_config_file()

        assert err is None
        assert config["ssrf_protection"]["action"] == "warn"

    def test_overlay_respects_immutable_fields(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {
            "secret_scanning": {
                "enabled": True,
                "immutable": ["enabled"],
            },
            "ssrf_protection": {
                "action": "warn",
            },
        }
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_CONFIG_INLINE": '{"secret_scanning": {"enabled": false}, "ssrf_protection": {"action": "block"}}',
            },
        ):
            _clear_config_cache()
            config, err = _load_config_file()

        assert err is None
        assert config["secret_scanning"]["enabled"] is True
        assert config["ssrf_protection"]["action"] == "block"

    def test_overlay_can_set_global_only_sections(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {"secret_scanning": {"enabled": True}}
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_CONFIG_INLINE": '{"daemon": {"host": "0.0.0.0"}}',
            },
        ):
            _clear_config_cache()
            config, err = _load_config_file()

        assert err is None
        assert config["daemon"]["host"] == "0.0.0.0"

    def test_overlay_does_not_mutate_overlay_dict(self):
        import ai_guardian.config.loaders as cl

        old = cl._sdk_overlay
        try:
            overlay = {"ssrf_protection": {"action": "block"}}
            cl._sdk_overlay = overlay
            _clear_config_cache()
            _load_config_file()
            assert overlay == {"ssrf_protection": {"action": "block"}}
        finally:
            cl._sdk_overlay = old

    def test_no_overlay_backward_compatible(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {
            "secret_scanning": {"enabled": True},
            "ssrf_protection": {"action": "warn"},
        }
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
            },
        ):
            _clear_config_cache()
            config, err = _load_config_file()

        assert err is None
        assert config == {
            "secret_scanning": {"enabled": True},
            "ssrf_protection": {"action": "warn"},
        }

    def test_overlay_only_no_config_files(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_INLINE": '{"preferred_ui": "headless"}',
            },
        ):
            _clear_config_cache()
            config, err = _load_config_file()

        assert err is None
        assert config == {"preferred_ui": "headless"}


class TestConfigure:
    """Tests for configure() API."""

    def setup_method(self):
        _clear_config_cache()

    def test_configure_clears_cache(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {"ssrf_protection": {"action": "warn"}}
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
            },
        ):
            _clear_config_cache()
            config1, _ = _load_config_file()
            assert config1["ssrf_protection"]["action"] == "warn"

            configure(overlay={"ssrf_protection": {"action": "block"}})
            config2, _ = _load_config_file()
            assert config2["ssrf_protection"]["action"] == "block"

    def test_configure_none_clears_overlay(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {"ssrf_protection": {"action": "warn"}}
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
            },
        ):
            configure(overlay={"ssrf_protection": {"action": "block"}})
            config1, _ = _load_config_file()
            assert config1["ssrf_protection"]["action"] == "block"

            configure(overlay=None)
            config2, _ = _load_config_file()
            assert config2["ssrf_protection"]["action"] == "warn"

    def test_configure_replaces_previous(self):
        configure(overlay={"a": 1})
        configure(overlay={"b": 2})
        import ai_guardian.config.loaders as cl

        assert cl._sdk_overlay == {"b": 2}


class TestCacheInvalidation:
    """Tests for cache invalidation with overlay changes."""

    def setup_method(self):
        _clear_config_cache()

    def test_file_overlay_mtime_change_invalidates(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {"base": True}
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        overlay_file = tmp_path / "overlay.json"
        overlay_file.write_text(json.dumps({"version": 1}))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_CONFIG_OVERLAY": str(overlay_file),
            },
        ):
            _clear_config_cache()
            config1, _ = _load_config_file()
            assert config1["version"] == 1

            overlay_file.write_text(json.dumps({"version": 2}))
            # Force mtime change (some filesystems have coarse resolution)
            import time

            os.utime(overlay_file, (time.time() + 1, time.time() + 1))

            config2, _ = _load_config_file()
            assert config2["version"] == 2

    def test_inline_env_change_invalidates(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {"base": True}
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_CONFIG_INLINE": '{"version": 1}',
            },
        ):
            _clear_config_cache()
            config1, _ = _load_config_file()
            assert config1["version"] == 1

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
                "AI_GUARDIAN_CONFIG_INLINE": '{"version": 2}',
            },
        ):
            config2, _ = _load_config_file()
            assert config2["version"] == 2


class TestDoctorOverlayCheck:
    """Tests for doctor check_config_overlay."""

    def _make_doctor(self):
        from ai_guardian.doctor import Doctor

        return Doctor()

    def test_no_overlay_passes(self):
        doctor = self._make_doctor()
        result = doctor.check_config_overlay()
        assert result.status.value == "pass"
        assert "No SDK overlay" in result.message

    def test_file_overlay_detected(self, tmp_path):
        overlay_file = tmp_path / "overlay.json"
        overlay_file.write_text(json.dumps({"test": True}))
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_OVERLAY": str(overlay_file),
            },
        ):
            doctor = self._make_doctor()
            result = doctor.check_config_overlay()
        assert result.status.value == "pass"
        assert "file:" in result.message

    def test_inline_overlay_detected(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_INLINE": '{"test": true}',
            },
        ):
            doctor = self._make_doctor()
            result = doctor.check_config_overlay()
        assert result.status.value == "pass"
        assert "inline env var" in result.message

    def test_configure_overlay_detected(self):
        import ai_guardian.config.loaders as cl

        old = cl._sdk_overlay
        try:
            cl._sdk_overlay = {"test": True}
            doctor = self._make_doctor()
            result = doctor.check_config_overlay()
            assert result.status.value == "pass"
            assert "configure() API" in result.message
        finally:
            cl._sdk_overlay = old

    def test_missing_file_warns(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_OVERLAY": "/nonexistent/overlay.json",
            },
        ):
            doctor = self._make_doctor()
            result = doctor.check_config_overlay()
        assert result.status.value == "warn"
        assert "not found" in result.message


class TestSDKMonitorWithOverlay:
    """Tests for SDK monitor() integration with configure() overlay."""

    def test_monitor_with_configure(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        global_config = {"secret_scanning": {"enabled": False}}
        (config_dir / "ai-guardian.json").write_text(json.dumps(global_config))

        with mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_DIR": str(config_dir),
            },
        ):
            configure(
                overlay={
                    "secret_scanning": {"enabled": True},
                    "ssrf_protection": {"action": "block"},
                }
            )
            from ai_guardian.sdk import monitor

            with monitor() as session:
                assert session._config["secret_scanning"]["enabled"] is True
                assert session._config["ssrf_protection"]["action"] == "block"

    def test_monitor_config_param_still_replaces(self):
        configure(overlay={"ssrf_protection": {"action": "block"}})
        custom_config = {"my_custom": True}
        from ai_guardian.sdk import monitor

        with monitor(config=custom_config) as session:
            assert session._config == {"my_custom": True}
            assert "ssrf_protection" not in session._config


# ============================================================================
# Named Agent Profiles (Issue #1852)
# ============================================================================


class TestLoadSDKProfile:
    """Tests for _load_sdk_profile()."""

    def setup_method(self):
        _clear_config_cache()

    def test_no_config_returns_empty(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            _clear_config_cache()
            result = _load_sdk_profile("agents", "code-reviewer")
        assert result == {}

    def test_no_sdk_section_returns_empty(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps({"secret_scanning": {"enabled": True}})
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            result = _load_sdk_profile("agents", "code-reviewer")
        assert result == {}

    def test_default_profile_only(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps({"sdk": {"agents": {"*": {"max_turns": 50, "mode": "rest"}}}})
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            result = _load_sdk_profile("agents", "unknown-agent")
        assert result == {"max_turns": 50, "mode": "rest"}

    def test_named_profile_merges_with_default(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps(
                {
                    "sdk": {
                        "agents": {
                            "*": {
                                "mode": "rest",
                                "max_turns": 50,
                            },
                            "code-reviewer": {
                                "max_turns": 20,
                                "model": "claude-haiku-4-5-20251001",
                            },
                        }
                    }
                }
            )
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            result = _load_sdk_profile("agents", "code-reviewer")
        assert result["max_turns"] == 20
        assert result["model"] == "claude-haiku-4-5-20251001"
        assert result["mode"] == "rest"

    def test_named_profile_without_default(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps(
                {"sdk": {"agents": {"quick-chat": {"max_turns": 5, "mode": "rest"}}}}
            )
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            result = _load_sdk_profile("agents", "quick-chat")
        assert result == {"max_turns": 5, "mode": "rest"}

    def test_none_name_returns_default(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps(
                {
                    "sdk": {
                        "agents": {
                            "*": {"max_turns": 50},
                            "named": {"max_turns": 10},
                        }
                    }
                }
            )
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            result = _load_sdk_profile("agents", None)
        assert result == {"max_turns": 50}

    def test_clients_section(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps(
                {
                    "sdk": {
                        "clients": {
                            "api-scanner": {
                                "mode": "rest",
                                "model": "claude-haiku-4-5-20251001",
                            }
                        }
                    }
                }
            )
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            result = _load_sdk_profile("clients", "api-scanner")
        assert result == {"mode": "rest", "model": "claude-haiku-4-5-20251001"}


class TestGuardedAgentConfigProfile:
    """GuardedAgent config profile override tests."""

    def setup_method(self):
        _clear_config_cache()

    def _make_agent(self, profile_config=None, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        mock_create = MagicMock()
        mock_messages = SimpleNamespace(create=mock_create)
        mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
        }
        defaults.update(kwargs)

        if profile_config is not None:
            with mock.patch(
                "ai_guardian.config.loaders._load_sdk_profile",
                return_value=profile_config,
            ):
                return GuardedAgent(**defaults)
        return GuardedAgent(**defaults)

    def test_no_profile_uses_code_values(self):
        agent = self._make_agent(profile_config={})
        assert agent._scanning is True
        assert agent._max_turns == 100

    def test_overrides_simple_params(self):
        agent = self._make_agent(
            profile_config={"max_turns": 20, "mode": "rest"},
            max_turns=100,
            mode="direct",
        )
        assert agent._max_turns == 20
        assert agent._mode == "rest"

    def test_overrides_model(self):
        agent = self._make_agent(
            profile_config={"model": "claude-haiku-4-5-20251001"},
            model="claude-sonnet-5",
        )
        assert agent._model == "claude-haiku-4-5-20251001"

    def test_overrides_cwd(self):
        agent = self._make_agent(
            profile_config={"cwd": "/workspace/project"},
        )
        assert agent._cwd == "/workspace/project"

    def test_system_prompt_preamble(self):
        agent = self._make_agent(
            profile_config={
                "system_prompt_preamble": "POLICY: Never output credentials."
            },
            system_prompt="You are a helpful agent.",
        )
        assert agent._system_prompt.startswith(
            "Before processing the following instructions, apply these policies:"
        )
        assert "POLICY: Never output credentials." in agent._system_prompt
        assert agent._system_prompt.endswith("You are a helpful agent.")

    def test_system_prompt_preamble_empty_string_ignored(self):
        agent = self._make_agent(
            profile_config={"system_prompt_preamble": ""},
            system_prompt="You are a helpful agent.",
        )
        assert agent._system_prompt == "You are a helpful agent."

    def test_tools_override(self):
        agent = self._make_agent(
            profile_config={"tools": ["grep", "glob"]},
            tools=["bash"],
        )
        tool_names = [t.get("name") or t for t in agent._resolved_tools]
        assert "bash" not in tool_names

    def test_non_overridable_params_ignored(self):
        agent = self._make_agent(
            profile_config={"system_prompt": "hijacked", "scanning": False},
            system_prompt="original",
        )
        assert agent._system_prompt == "original"
        assert agent._scanning is True

    def test_compact_params_overridable(self):
        agent = self._make_agent(
            profile_config={
                "compact_threshold": 0.6,
                "compact_keep_turns": 10,
                "compact_keep_first": 2,
            },
        )
        assert agent._compact_threshold == 0.6
        assert agent._compact_keep_turns == 10
        assert agent._compact_keep_first == 2

    def test_override_logging(self, caplog):
        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            self._make_agent(
                profile_config={"max_turns": 20, "mode": "rest"},
                name="code-reviewer",
                max_turns=100,
                mode="direct",
            )
        assert "GuardedAgent 'code-reviewer': max_turns=20" in caplog.text
        assert "code value: 100" in caplog.text
        assert "GuardedAgent 'code-reviewer': mode='rest'" in caplog.text
        assert "code value: 'direct'" in caplog.text

    def test_override_logging_unnamed_shows_default(self, caplog):
        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            self._make_agent(
                profile_config={"max_turns": 20},
                max_turns=100,
            )
        assert "GuardedAgent '*': max_turns=20" in caplog.text

    def test_same_value_no_log(self, caplog):
        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            self._make_agent(
                profile_config={"max_turns": 100},
                max_turns=100,
            )
        assert "config override" not in caplog.text

    def test_name_stored(self):
        agent = self._make_agent(profile_config={}, name="my-agent")
        assert agent._name == "my-agent"

    def test_max_budget_tokens_override(self):
        agent = self._make_agent(
            profile_config={"max_budget_tokens": 500000},
        )
        assert agent._max_budget_tokens == 500000

    def test_profile_integration_with_config_file(self, tmp_path):
        """End-to-end: GuardedAgent reads from ai-guardian.json file."""
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps(
                {
                    "sdk": {
                        "agents": {
                            "*": {"mode": "rest"},
                            "code-reviewer": {
                                "max_turns": 20,
                                "model": "claude-haiku-4-5-20251001",
                            },
                        }
                    }
                }
            )
        )

        mock_create = MagicMock()
        mock_messages = SimpleNamespace(create=mock_create)
        mock_client = SimpleNamespace(messages=mock_messages)

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            agent = GuardedAgent(
                name="code-reviewer",
                model="claude-sonnet-5",
                tools=["bash"],
                client=mock_client,
                max_turns=100,
            )

        assert agent._model == "claude-haiku-4-5-20251001"
        assert agent._max_turns == 20


def _make_stub_extractor():
    from ai_guardian.integrations.base import ProviderExtractor

    class _StubExtractor(ProviderExtractor):
        @classmethod
        def detect(cls, client):
            return False

        def methods_to_wrap(self):
            return []

        def extract_input(self, method_name, args, kwargs):
            return []

        def extract_output(self, method_name, response):
            return []

    return _StubExtractor()


class TestGuardedFunctionConfigProfile:
    """guarded() config profile override tests."""

    def setup_method(self):
        _clear_config_cache()

    def _make_guarded(self, profile_config=None, client=None, **kwargs):
        from ai_guardian.integrations.base import guarded

        defaults = {"extractor": _make_stub_extractor()}
        defaults.update(kwargs)

        if client is None:
            client = object()

        if profile_config is not None:
            with mock.patch(
                "ai_guardian.config.loaders._load_sdk_profile",
                return_value=profile_config,
            ):
                return guarded(client, **defaults)
        return guarded(client, **defaults)

    def test_no_profile_uses_code_values(self):
        wrapped = self._make_guarded(profile_config={})
        assert wrapped._mode == "direct"

    def test_overrides_mode(self):
        wrapped = self._make_guarded(
            profile_config={"mode": "rest"},
            mode="direct",
        )
        assert wrapped._mode == "rest"

    def test_override_logging(self, caplog):
        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            self._make_guarded(
                profile_config={"mode": "rest"},
                name="api-scanner",
                mode="direct",
            )
        assert "guarded 'api-scanner': mode='rest'" in caplog.text
        assert "code value: 'direct'" in caplog.text

    def test_override_logging_unnamed_shows_default(self, caplog):
        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            self._make_guarded(
                profile_config={"mode": "rest"},
                mode="direct",
            )
        assert "guarded '*': mode='rest'" in caplog.text

    def test_model_override_stored(self):
        wrapped = self._make_guarded(
            profile_config={"model": "claude-haiku-4-5-20251001"},
        )
        assert wrapped._model_override == "claude-haiku-4-5-20251001"

    def test_model_override_injected_into_kwargs(self):
        wrapped = self._make_guarded(
            profile_config={"model": "claude-haiku-4-5-20251001"},
        )
        captured_kwargs = {}
        original_method = MagicMock(return_value="response")

        with mock.patch("ai_guardian.integrations.base.monitor") as mock_monitor:
            mock_session = MagicMock()
            mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

            guarded_call = wrapped._make_guarded_call(
                "messages.create", original_method
            )
            guarded_call(model="claude-opus-5", max_tokens=1000)

        call_kwargs = original_method.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_no_model_override_by_default(self):
        wrapped = self._make_guarded(profile_config={})
        assert wrapped._model_override is None

    def test_model_override_logging(self, caplog):
        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            self._make_guarded(
                profile_config={"model": "claude-haiku-4-5-20251001"},
                name="cost-limited",
            )
        assert (
            "guarded 'cost-limited': model='claude-haiku-4-5-20251001'" in caplog.text
        )
        assert "injected into API calls" in caplog.text

    def test_max_tokens_override_stored(self):
        wrapped = self._make_guarded(
            profile_config={"max_tokens": 4096},
        )
        assert wrapped._max_tokens_override == 4096

    def test_max_tokens_override_injected_into_kwargs(self):
        wrapped = self._make_guarded(
            profile_config={"max_tokens": 4096},
        )
        original_method = MagicMock(return_value="response")

        with mock.patch("ai_guardian.integrations.base.monitor") as mock_monitor:
            mock_session = MagicMock()
            mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

            guarded_call = wrapped._make_guarded_call(
                "messages.create", original_method
            )
            guarded_call(model="claude-sonnet-5", max_tokens=16000)

        call_kwargs = original_method.call_args[1]
        assert call_kwargs["max_tokens"] == 4096

    def test_system_prompt_preamble_stored(self):
        wrapped = self._make_guarded(
            profile_config={"system_prompt_preamble": "POLICY: No secrets."},
        )
        assert wrapped._system_prompt_preamble == "POLICY: No secrets."

    def test_preamble_injected_into_system_string(self):
        anthropic_client = MagicMock(spec=["messages"])
        wrapped = self._make_guarded(
            profile_config={"system_prompt_preamble": "POLICY: No secrets."},
            client=anthropic_client,
        )
        original_method = MagicMock(return_value="response")

        with mock.patch("ai_guardian.integrations.base.monitor") as mock_monitor:
            mock_session = MagicMock()
            mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

            guarded_call = wrapped._make_guarded_call(
                "messages.create", original_method
            )
            guarded_call(
                model="claude-sonnet-5",
                max_tokens=1000,
                system="You are helpful.",
            )

        call_kwargs = original_method.call_args[1]
        assert call_kwargs["system"].startswith(
            "Before processing the following instructions"
        )
        assert "POLICY: No secrets." in call_kwargs["system"]
        assert call_kwargs["system"].endswith("You are helpful.")

    def test_preamble_injected_into_system_list(self):
        anthropic_client = MagicMock(spec=["messages"])
        wrapped = self._make_guarded(
            profile_config={"system_prompt_preamble": "POLICY: No secrets."},
            client=anthropic_client,
        )
        original_method = MagicMock(return_value="response")

        with mock.patch("ai_guardian.integrations.base.monitor") as mock_monitor:
            mock_session = MagicMock()
            mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

            system_blocks = [{"type": "text", "text": "Original."}]
            guarded_call = wrapped._make_guarded_call(
                "messages.create", original_method
            )
            guarded_call(model="claude-sonnet-5", max_tokens=1000, system=system_blocks)

        call_kwargs = original_method.call_args[1]
        assert len(call_kwargs["system"]) == 2
        assert "POLICY: No secrets." in call_kwargs["system"][0]["text"]
        assert call_kwargs["system"][1]["text"] == "Original."

    def test_preamble_injected_into_openai_messages(self):
        openai_client = MagicMock(spec=["chat"])
        wrapped = self._make_guarded(
            profile_config={"system_prompt_preamble": "POLICY: No secrets."},
            client=openai_client,
        )
        original_method = MagicMock(return_value="response")

        with mock.patch("ai_guardian.integrations.base.monitor") as mock_monitor:
            mock_session = MagicMock()
            mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

            messages = [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
            ]
            guarded_call = wrapped._make_guarded_call(
                "chat.completions.create", original_method
            )
            guarded_call(model="gpt-4", max_tokens=1000, messages=messages)

        call_kwargs = original_method.call_args[1]
        sys_msg = call_kwargs["messages"][0]
        assert "POLICY: No secrets." in sys_msg["content"]
        assert sys_msg["content"].endswith("You are helpful.")
        assert call_kwargs["messages"][1] == {"role": "user", "content": "Hi"}

    def test_preamble_empty_string_not_injected(self):
        wrapped = self._make_guarded(
            profile_config={"system_prompt_preamble": ""},
        )
        assert wrapped._system_prompt_preamble is None

    def test_unknown_profile_keys_ignored(self):
        wrapped = self._make_guarded(
            profile_config={"max_turns": 20, "cwd": "/tmp"},
        )
        assert not hasattr(wrapped, "_max_turns")
        assert not hasattr(wrapped, "_cwd")

    def test_profile_integration_with_config_file(self, tmp_path):
        """End-to-end: guarded() reads from ai-guardian.json file."""
        from ai_guardian.integrations.base import guarded

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps(
                {
                    "sdk": {
                        "clients": {
                            "api-scanner": {
                                "mode": "rest",
                                "model": "claude-haiku-4-5-20251001",
                            }
                        }
                    }
                }
            )
        )

        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            wrapped = guarded(
                object(),
                name="api-scanner",
                extractor=_make_stub_extractor(),
                mode="direct",
            )

        assert wrapped._mode == "rest"
        assert wrapped._model_override == "claude-haiku-4-5-20251001"


# ============================================================================
# SDK Scanning Flag (Issue #1868)
# ============================================================================


class TestSDKScanning:
    """Tests for _sdk_scanning()."""

    def setup_method(self):
        _clear_config_cache()

    def test_default_true_no_config(self):
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file", return_value=(None, None)
        ):
            assert _sdk_scanning() is True

    def test_default_true_no_sdk_section(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps({"secret_scanning": {"enabled": True}})
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            assert _sdk_scanning() is True

    def test_globally_disabled(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps({"sdk": {"scanning": False}})
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            assert _sdk_scanning() is False

    def test_globally_enabled_explicit(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps({"sdk": {"scanning": True}})
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            assert _sdk_scanning() is True

    def test_unnamed_agent_uses_global(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(
            json.dumps({"sdk": {"scanning": False}})
        )
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            assert _sdk_scanning("agents", None) is False

    def test_config_error_returns_true(self):
        with mock.patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=(None, "parse error"),
        ):
            assert _sdk_scanning() is True

    def test_sdk_not_dict_returns_true(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "ai-guardian.json").write_text(json.dumps({"sdk": "invalid"}))
        with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": str(config_dir)}):
            _clear_config_cache()
            assert _sdk_scanning() is True


class TestGuardedSDKDisabled:
    """guarded() returns unwrapped client when sdk.scanning=false."""

    def setup_method(self):
        _clear_config_cache()

    def test_guarded_returns_unwrapped_client(self):
        from ai_guardian.integrations.base import guarded

        client = SimpleNamespace(messages=SimpleNamespace(create=lambda: None))

        with mock.patch("ai_guardian.config.loaders._sdk_scanning", return_value=False):
            result = guarded(client, extractor=_make_stub_extractor())

        assert result is client

    def test_guarded_returns_unwrapped_with_name(self):
        from ai_guardian.integrations.base import guarded

        client = SimpleNamespace(messages=SimpleNamespace(create=lambda: None))

        with mock.patch("ai_guardian.config.loaders._sdk_scanning", return_value=False):
            result = guarded(
                client, name="disabled-client", extractor=_make_stub_extractor()
            )

        assert result is client

    def test_guarded_logs_disabled_message(self, caplog):
        from ai_guardian.integrations.base import guarded

        client = SimpleNamespace(messages=SimpleNamespace(create=lambda: None))

        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            with mock.patch(
                "ai_guardian.config.loaders._sdk_scanning", return_value=False
            ):
                guarded(client, extractor=_make_stub_extractor())

        assert "SDK scanning disabled via config" in caplog.text
        assert "unwrapped client" in caplog.text


class TestGuardedAgentSDKDisabled:
    """GuardedAgent skips scanning when sdk.scanning=false."""

    def setup_method(self):
        _clear_config_cache()

    def _make_agent(self, sdk_scanning=False, **kwargs):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        mock_create = MagicMock()
        mock_messages = SimpleNamespace(create=mock_create)
        mock_client = SimpleNamespace(messages=mock_messages)

        defaults = {
            "model": "claude-sonnet-5",
            "tools": ["bash"],
            "client": mock_client,
        }
        defaults.update(kwargs)

        with (
            mock.patch(
                "ai_guardian.config.loaders._sdk_scanning",
                return_value=sdk_scanning,
            ),
            mock.patch(
                "ai_guardian.config.loaders._load_sdk_profile",
                return_value={},
            ),
        ):
            return GuardedAgent(**defaults)

    def test_scanning_disabled(self):
        agent = self._make_agent(sdk_scanning=False)
        assert agent._scanning is False

    def test_scanning_enabled_by_default(self):
        agent = self._make_agent(sdk_scanning=True)
        assert agent._scanning is True

    def test_logs_disabled_message(self, caplog):
        with caplog.at_level(logging.INFO, logger="ai_guardian.integrations"):
            self._make_agent(sdk_scanning=False)
        assert "SDK scanning disabled via config" in caplog.text
        assert "scanning skipped" in caplog.text
