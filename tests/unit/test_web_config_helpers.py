"""Tests for web config_helpers shared load/save utilities."""

import json
import os
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

from ai_guardian.web.config_helpers import (
    load_web_config,
    load_web_config_global,
    save_web_config,
    get_web_config_provenance,
    get_web_config_scope_label,
    get_web_config_notice,
    get_web_config_state,
    set_daemon_service,
    set_current_daemon_name,
    set_current_project_dir,
    load_web_projects,
    _is_remote_target,
)


class TestLoadWebConfig:
    """Tests for load_web_config."""

    def test_returns_empty_dict_when_missing(self, tmp_path):
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            assert load_web_config() == {}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path):
        (tmp_path / "ai-guardian.json").write_text("not json", encoding="utf-8")
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            assert load_web_config() == {}

    def test_returns_parsed_dict(self, tmp_path):
        data = {"features": {"secrets": True}}
        (tmp_path / "ai-guardian.json").write_text(json.dumps(data), encoding="utf-8")
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            assert load_web_config() == data


class TestSaveWebConfig:
    """Tests for save_web_config."""

    def test_creates_file(self, tmp_path):
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            save_web_config({"key": "value"})
        written = (tmp_path / "ai-guardian.json").read_text(encoding="utf-8")
        assert json.loads(written) == {"key": "value"}
        assert written.endswith("\n")

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "sub" / "dir"
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=nested),
            patch("ai_guardian.config.writer.get_config_dir", return_value=nested),
        ):
            save_web_config({"a": 1})
        assert (nested / "ai-guardian.json").exists()

    def test_indent_is_two(self, tmp_path):
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            save_web_config({"a": 1})
        written = (tmp_path / "ai-guardian.json").read_text(encoding="utf-8")
        assert '  "a": 1' in written

    def test_host_managed_config_is_not_written(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text('{"source": "host"}\n', encoding="utf-8")
        with (
            patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_READ_ONLY": "true"}),
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            assert save_web_config({"changed": True}) is False
        assert config_path.read_text(encoding="utf-8") == '{"source": "host"}\n'

    def test_host_snapshot_config_is_written_to_sandbox_copy(self, tmp_path):
        config_path = tmp_path / "ai-guardian.json"
        config_path.write_text('{"source": "host"}\n', encoding="utf-8")
        with (
            patch.dict(
                os.environ,
                {
                    "AI_GUARDIAN_CONFIG_SOURCE": "host",
                    "AI_GUARDIAN_CONFIG_READ_ONLY": "false",
                },
            ),
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            assert save_web_config({"changed": True}) is True
        assert json.loads(config_path.read_text(encoding="utf-8")) == {"changed": True}


class TestWebConfigState:
    def test_local_state_uses_config_environment(self):
        with patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_CONFIG_SOURCE": "host",
                "AI_GUARDIAN_CONFIG_READ_ONLY": "true",
            },
            clear=True,
        ):
            assert get_web_config_state() == {"source": "host", "read_only": True}


class TestWebConfigNotice:
    def test_host_snapshot_notice(self):
        notice = get_web_config_notice({"source": "host", "read_only": False})

        assert notice["message"] == (
            "Using host configuration snapshot. Changes apply only to this "
            "sandbox; the host configuration will not be modified."
        )
        assert notice["icon"] == "info"
        assert notice["background_class"] == "bg-amber-1"

    def test_read_only_notice(self):
        notice = get_web_config_notice({"source": "host", "read_only": True})

        assert notice["message"] == (
            "Host configuration is mounted read-only. "
            "Configuration editing is disabled."
        )
        assert notice["icon"] == "lock"
        assert notice["background_class"] == "bg-red-1"

    def test_other_sources_have_no_notice(self):
        assert get_web_config_notice({"source": "sandbox-local"}) is None
        assert get_web_config_notice({"source": "snapshot"}) is None
        assert get_web_config_notice(None) is None


class TestCacheInvalidation:
    """Tests for config cache invalidation on save (#1301)."""

    def test_save_clears_config_cache(self, tmp_path):
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.loaders._clear_config_cache") as mock_clear,
        ):
            save_web_config({"key": "value"})
        assert mock_clear.called

    def test_save_global_scope_clears_all_caches(self, tmp_path):
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.loaders._clear_config_cache") as mock_clear,
        ):
            save_web_config({"key": "value"})
        assert any(c == ((), {}) for c in mock_clear.call_args_list)


class TestRoundTrip:
    """Verify save then load returns same data."""

    def test_round_trip(self, tmp_path):
        data = {"features": {"pii": True}, "permissions": {"rules": []}}
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            save_web_config(data)
            assert load_web_config() == data


@dataclass
class _FakeTarget:
    name: str = "test-daemon"
    runtime: str = "container"


class _FakeClient:
    def get_status(self, target):
        return {"active_project_dirs": ["/projects/a", "/projects/b"]}


class _FakeService:
    def __init__(self):
        self._target = _FakeTarget()
        self._client = _FakeClient()
        self.calls = []

    def get_target_by_name(self, name):
        if name == self._target.name:
            return self._target
        return None

    def get_config_scoped(self, target, scope, project_dir=None):
        self.calls.append(("get_config_scoped", scope, project_dir))
        return {"remote": True, "scope": scope}

    def get_config_provenance(self, target, project_dir=None):
        self.calls.append(("get_config_provenance", project_dir))
        return {"source": "remote"}

    def write_config_bulk(self, target, scope, config, project_dir=None):
        self.calls.append(("write_config_bulk", scope, config, project_dir))
        return {"status": "ok"}

    def refresh_targets(self):
        pass


class TestIsRemoteTarget:
    """Tests for _is_remote_target helper."""

    def test_none_target(self):
        assert _is_remote_target(None) is False

    def test_local_target(self):
        assert _is_remote_target(_FakeTarget(runtime="local")) is False

    def test_container_target(self):
        assert _is_remote_target(_FakeTarget(runtime="container")) is True

    def test_kubernetes_target(self):
        assert _is_remote_target(_FakeTarget(runtime="kubernetes")) is True

    def test_manual_target(self):
        assert _is_remote_target(_FakeTarget(runtime="manual")) is True


class TestRemoteConfigRouting:
    """Tests for config_helpers routing to DaemonService for remote targets."""

    def setup_method(self):
        self._svc = _FakeService()
        set_daemon_service(self._svc)
        set_current_daemon_name("test-daemon")
        set_current_project_dir("")

    def teardown_method(self):
        set_daemon_service(None)
        set_current_daemon_name("")
        set_current_project_dir("")

    def test_load_web_config_routes_to_remote(self):
        result = load_web_config()
        assert result == {"remote": True, "scope": "merged"}
        assert ("get_config_scoped", "merged", None) in self._svc.calls

    def test_load_web_config_local_when_no_daemon_name(self, tmp_path):
        set_current_daemon_name("")
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            result = load_web_config()
        assert result == {}
        assert len(self._svc.calls) == 0

    def test_load_web_config_routes_local_target_through_service(self):
        self._svc._target = _FakeTarget(runtime="local")
        result = load_web_config()
        assert result == {"remote": True, "scope": "merged"}
        assert ("get_config_scoped", "merged", None) in self._svc.calls

    def test_load_web_config_global_routes_to_remote(self):
        result = load_web_config_global()
        assert result == {"remote": True, "scope": "global"}
        assert ("get_config_scoped", "global", None) in self._svc.calls

    def test_save_web_config_routes_through_service(self):
        config = {"secret_scanning": {"enabled": True}}
        save_web_config(config)
        assert ("write_config_bulk", "global", config, None) in self._svc.calls

    def test_save_web_config_global_when_no_project_selected(self):
        set_current_project_dir("")
        config = {"test": True}
        save_web_config(config)
        assert self._svc.calls[0][1] == "global"

    def test_provenance_routes_through_service(self):
        result = get_web_config_provenance()
        assert result == {"source": "remote"}
        assert ("get_config_provenance", None) in self._svc.calls

    def test_scope_label_global_when_no_project_selected(self):
        assert get_web_config_scope_label() == "Global"

    def test_load_returns_empty_on_service_error(self):
        self._svc.get_config_scoped = MagicMock(return_value=None)
        result = load_web_config()
        assert result == {}

    def test_no_service_falls_through_to_local(self, tmp_path):
        set_daemon_service(None)
        with (
            patch("ai_guardian.config.utils.get_config_dir", return_value=tmp_path),
            patch("ai_guardian.config.writer.get_config_dir", return_value=tmp_path),
        ):
            result = load_web_config()
        assert result == {}


class TestRemoteProjectScope:
    """Tests for remote daemon project scope routing (#1354)."""

    def setup_method(self):
        self._svc = _FakeService()
        set_daemon_service(self._svc)
        set_current_daemon_name("test-daemon")
        set_current_project_dir("")

    def teardown_method(self):
        set_daemon_service(None)
        set_current_daemon_name("")
        set_current_project_dir("")

    def test_load_passes_project_dir_to_remote(self):
        set_current_project_dir("/projects/a")
        result = load_web_config()
        assert result == {"remote": True, "scope": "merged"}
        assert ("get_config_scoped", "merged", "/projects/a") in self._svc.calls

    def test_save_uses_project_scope_when_selected(self):
        set_current_project_dir("/projects/a")
        config = {"test": True}
        save_web_config(config)
        assert (
            "write_config_bulk",
            "project",
            config,
            "/projects/a",
        ) in self._svc.calls

    def test_save_global_when_no_project(self):
        set_current_project_dir("")
        config = {"test": True}
        save_web_config(config)
        assert self._svc.calls[0][1] == "global"

    def test_scope_label_project_when_selected(self):
        set_current_project_dir("/projects/a")
        assert get_web_config_scope_label() == "Project"

    def test_scope_label_global_when_no_project(self):
        set_current_project_dir("")
        assert get_web_config_scope_label() == "Global"

    def test_provenance_passes_project_dir(self):
        set_current_project_dir("/projects/a")
        get_web_config_provenance()
        assert ("get_config_provenance", "/projects/a") in self._svc.calls

    def test_load_web_projects_returns_sorted_dirs(self):
        dirs = load_web_projects()
        assert dirs == ["/projects/a", "/projects/b"]

    def test_load_web_projects_empty_when_no_service(self):
        set_daemon_service(None)
        assert load_web_projects() == []

    def test_load_web_projects_empty_when_no_daemon_name(self):
        set_current_daemon_name("")
        assert load_web_projects() == []
