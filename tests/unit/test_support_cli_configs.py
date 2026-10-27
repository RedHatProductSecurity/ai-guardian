"""CLI diagnostics collect only bounded, sanitized configuration copies."""

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_guardian.reporting import cli_diagnostics as configs


@pytest.fixture
def isolated_cli_homes(monkeypatch, tmp_path):
    from ai_guardian.ide_paths import IDE_CONFIG_FILE_ENV_VARS, IDE_HOME_ENV_VARS

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for names in IDE_HOME_ENV_VARS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    for name in IDE_CONFIG_FILE_ENV_VARS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        "ai_guardian.config.utils.get_project_dir", lambda: str(project)
    )
    return home, project


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_read_config_refuses_normalized_path_outside_selected_directory(
    monkeypatch, tmp_path
):
    source = write(tmp_path / "project" / "settings.json", '{"model":"source"}')
    outside = write(
        tmp_path / "project-unrelated" / "private.json", '{"marker":"unrelated"}'
    )
    abspath = os.path.abspath

    def changed_path(path):
        return str(outside) if Path(path) == source else abspath(path)

    monkeypatch.setattr(configs.os.path, "abspath", changed_path)
    open_file = Mock(
        side_effect=AssertionError("Unsafe paths must be rejected before open")
    )
    monkeypatch.setattr(configs.os, "open", open_file)

    with pytest.raises(ValueError, match="escapes its source directory"):
        configs._read_config(source, 1024)

    open_file.assert_not_called()


@pytest.mark.parametrize("limit", [None, 1024])
def test_read_config_does_not_resolve_request_controlled_paths(
    monkeypatch, tmp_path, limit
):
    source = write(tmp_path / "project" / "settings.json", '{"model":"source"}')
    resolve = Path.resolve

    def reject_source_resolution(path, *args, **kwargs):
        if path in (source, source.parent):
            raise AssertionError("Source validation must not resolve untrusted paths")
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", reject_source_resolution)
    assert configs._read_config(source, limit) == source.read_bytes()


def test_read_config_rejects_link_before_collapsing_parent_traversal(tmp_path):
    project = tmp_path / "project"
    write(project / "settings.json", '{"model":"local"}')
    outside = tmp_path / "outside" / "child"
    outside.mkdir(parents=True)
    write(outside.parent / "settings.json", '{"marker":"unrelated"}')
    linked = project / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This filesystem cannot create symbolic links")

    with pytest.raises(ValueError, match="Linked configuration omitted"):
        configs._read_config(linked / ".." / "settings.json", 1024)


def test_read_config_can_preserve_a_complete_local_configuration(tmp_path):
    source = write(tmp_path / "settings.json", '{"model":"complete"}')
    assert configs._read_config(source, None) == source.read_bytes()


def test_discovers_cli_settings_hooks_mcp_and_project_overlays(
    isolated_cli_homes, tmp_path
):
    home, project = isolated_cli_homes
    paths = [
        home / ".claude/settings.json",
        home / ".claude.json",
        home / ".codex/config.toml",
        home / ".codex/hooks.json",
        home / ".config/opencode/opencode.jsonc",
        home / ".gemini/settings.json",
        home / ".pi/agent/settings.json",
        project / ".claude/settings.local.json",
        project / ".mcp.json",
        project / ".cursor/hooks.json",
        project / ".cursor/mcp.json",
        project / "opencode.json",
        project / ".codex/config.toml",
    ]
    for path in paths:
        write(path, "{}" if path.suffix != ".toml" else 'model = "test-model"')
    # These files must never be discovered, traversed, or copied.
    for name in (".codex/auth.json", ".pi/agent/auth.json", ".claude/history.jsonl"):
        write(home / name, "PRIVATE AUTH OR HISTORY")

    sources = configs._config_sources()
    discovered = {path for _, _, _, path in sources}
    assert set(paths) <= discovered
    assert not any(
        "auth.json" in str(path) or "history" in str(path) for path in discovered
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    assert len(files) == len(paths)
    assert all(
        "PRIVATE AUTH OR HISTORY" not in (tmp_path / "review" / f["name"]).read_text()
        for f in files
    )
    assert len({f["name"] for f in files}) == len(files)


def test_discovery_respects_relocated_cli_homes(
    isolated_cli_homes, monkeypatch, tmp_path
):
    home, _ = isolated_cli_homes
    relocated = tmp_path / "relocated"
    for env, directory in (
        ("CODEX_HOME", "codex"),
        ("CLAUDE_CONFIG_DIR", "claude"),
        ("PI_CODING_AGENT_DIR", "pi"),
    ):
        monkeypatch.setenv(env, str(relocated / directory))
    explicit = write(relocated / "opencode/custom.jsonc", "{}")
    monkeypatch.setenv("OPENCODE_CONFIG", str(explicit))
    expected = [
        write(relocated / "codex/config.toml", 'model = "custom"'),
        write(relocated / "claude/settings.json", "{}"),
        write(relocated / "pi/settings.json", "{}"),
        explicit,
    ]
    stale = write(home / ".codex/config.toml", 'model = "stale"')
    discovered = {path for _, _, _, path in configs._config_sources()}
    assert set(expected) <= discovered
    assert stale not in discovered


@pytest.mark.parametrize(
    "suffix,text",
    [
        (".json", '{"model":"useful","apiKey":"unissued-sensitive-value"}'),
        (
            ".jsonc",
            '{/* diagnostic comment */ "model":"useful","apiKey":"unissued-sensitive-value",}',
        ),
        (".toml", 'model = "useful"\napi_key = "unissued-sensitive-value"'),
        (".yaml", "model: useful\napi_key: unissued-sensitive-value"),
    ],
)
def test_supported_formats_are_sanitized_to_reviewable_json(
    isolated_cli_homes, monkeypatch, tmp_path, suffix, text
):
    source = write(tmp_path / f"source{suffix}", text)
    monkeypatch.setattr(
        configs, "_config_sources", lambda: [("test-cli", "user", "settings", source)]
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    artifact = tmp_path / "review" / files[0]["name"]
    data = json.loads(artifact.read_text())
    assert data["configuration"]["model"] == "useful"
    assert "unissued-sensitive-value" not in artifact.read_text()
    assert data["format"] == suffix.lstrip(".")
    assert files[0]["redactions"] >= 1
    assert files[0]["name"] == "cli-test-cli-user-settings.json"
    assert source.read_text() == text


def test_nested_credentials_env_headers_and_home_paths_are_removed(
    isolated_cli_homes, monkeypatch, tmp_path
):
    home, project = isolated_cli_homes
    value = {
        "mcp": {
            "server": {
                "env": {"CUSTOM_SECRET_NAME": "unissued-env-value"},
                "headers": {"X-Custom": "unissued-header-value"},
            }
        },
        "auth": {"private_key": ["unissued-list-value"]},
        "model": "diagnostic-model",
        "directory": str(home / "private-work"),
        "projects": {str(project): {"enabled": True}},
    }
    source = write(tmp_path / "config.json", json.dumps(value))
    monkeypatch.setattr(
        configs, "_config_sources", lambda: [("test-cli", "user", "settings", source)]
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    text = (tmp_path / "review" / files[0]["name"]).read_text()
    for secret in (
        "unissued-env-value",
        "unissued-header-value",
        "unissued-list-value",
    ):
        assert secret not in text
    assert json.loads(text)["configuration"]["model"] == "diagnostic-model"
    assert json.dumps(str(home))[1:-1] not in text
    assert json.dumps(str(project))[1:-1] not in text
    assert files[0]["redactions"] >= 5


def test_claude_global_state_is_limited_to_mcp_configuration(
    isolated_cli_homes, monkeypatch, tmp_path
):
    home, _ = isolated_cli_homes
    source = write(
        home / ".claude.json",
        json.dumps(
            {
                "mcpServers": {
                    "ai-guardian": {"command": "ai-guardian", "args": ["mcp-server"]}
                },
                "history": ["private conversation"],
                "projects": {"private project": {"history": "private conversation"}},
                "oauthAccount": {"emailAddress": "private identity"},
            }
        ),
    )
    monkeypatch.setattr(
        configs, "_config_sources", lambda: [("claude", "user", "mcp", source)]
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    value = json.loads((tmp_path / "review" / files[0]["name"]).read_text())
    assert set(value["configuration"]) == {"mcpServers"}
    assert "private" not in json.dumps(value)


@pytest.mark.parametrize(
    "text", ['{"api_key":"unissued-malformed-value",', "[1, 2]", "\x00binary"]
)
def test_invalid_configuration_never_falls_back_to_raw_content(
    isolated_cli_homes, monkeypatch, tmp_path, text
):
    source = write(tmp_path / "config.json", text)
    monkeypatch.setattr(
        configs, "_config_sources", lambda: [("test-cli", "user", "settings", source)]
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    value = json.loads((tmp_path / "review" / files[0]["name"]).read_text())
    assert value["status"] == "omitted"
    assert "configuration" not in value
    assert "unissued-malformed-value" not in json.dumps(value)
    assert (
        files[0]["note"] == "Configuration omitted; review the diagnostic status file"
    )


def test_oversized_configuration_is_not_read_or_truncated(
    isolated_cli_homes, monkeypatch, tmp_path
):
    source = write(tmp_path / "config.json", '"' + "x" * configs.MAX_CONFIG_BYTES + '"')
    monkeypatch.setattr(
        configs, "_config_sources", lambda: [("test-cli", "user", "settings", source)]
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    artifact = (tmp_path / "review" / files[0]["name"]).read_text()
    assert json.loads(artifact)["status"] == "omitted"
    assert "x" * 100 not in artifact


@pytest.mark.skipif(
    os.name == "nt", reason="Symlink creation needs privileges on Windows"
)
def test_linked_config_is_not_followed(isolated_cli_homes, monkeypatch, tmp_path):
    secret = write(tmp_path / "auth.json", '{"private":"linked credential value"}')
    linked = tmp_path / "config.json"
    linked.symlink_to(secret)
    monkeypatch.setattr(
        configs, "_config_sources", lambda: [("test-cli", "user", "settings", linked)]
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    text = (tmp_path / "review" / files[0]["name"]).read_text()
    assert json.loads(text)["status"] == "omitted"
    assert "linked credential value" not in text


def test_sanitizer_failure_omits_config_without_logging_source_contents(
    isolated_cli_homes, monkeypatch, tmp_path, caplog
):
    source = write(tmp_path / "config.json", '{"model":"unissued-private-data"}')
    monkeypatch.setattr(
        configs, "_config_sources", lambda: [("test-cli", "user", "settings", source)]
    )
    monkeypatch.setattr(
        "ai_guardian.reporting.github_support.public_text",
        Mock(side_effect=RuntimeError("unissued-private-data")),
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    text = (tmp_path / "review" / files[0]["name"]).read_text()
    assert json.loads(text)["status"] == "omitted"
    assert "unissued-private-data" not in text + caplog.text


def test_missing_cli_configs_need_no_cli_or_mcp_process(
    isolated_cli_homes, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "subprocess.run", Mock(side_effect=AssertionError("No CLI invocation"))
    )
    assert configs.collect_cli_configs(tmp_path / "review") == []


def test_configuration_budget_also_counts_malformed_input(
    isolated_cli_homes, monkeypatch, tmp_path
):
    invalid = write(tmp_path / "first.json", '{"invalid":')
    valid = write(tmp_path / "second.json", '{"model":"remaining-input"}')
    monkeypatch.setattr(configs, "MAX_CONFIG_TOTAL_BYTES", len(invalid.read_bytes()))
    monkeypatch.setattr(
        configs,
        "_config_sources",
        lambda: [
            ("test-cli", "user", "first", invalid),
            ("test-cli", "user", "second", valid),
        ],
    )
    files = configs.collect_cli_configs(tmp_path / "review")
    assert len(files) == 2
    assert all(f["collection_status"] == "omitted" for f in files)
    assert all(
        "remaining-input" not in (tmp_path / "review" / f["name"]).read_text()
        for f in files
    )


def test_credential_containers_are_redacted_regardless_of_value_type():
    value, count = configs._redact_credentials(
        {
            "httpHeaders": ["unissued-sensitive-value"],
            "env": "unissued-sensitive-value",
            "privateKey": ["unissued-sensitive-value"],
            "providers": [{"accessKey": {"value": "unissued-sensitive-value"}}],
        }
    )
    assert "unissued-sensitive-value" not in json.dumps(value)
    assert count == 4


def test_explicit_config_override_cannot_collect_an_auth_store(
    isolated_cli_homes, monkeypatch, tmp_path
):
    auth = write(tmp_path / "auth.json", '{"private":"unissued-auth-data"}')
    monkeypatch.setenv("OPENCODE_CONFIG", str(auth))
    assert auth not in {path for _, _, _, path in configs._config_sources()}
