"""Isolated standalone recovery tests; never inspect the operator's IDE homes."""

import json
import copy
import itertools
import ast
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.lifecycle.orphan_recovery import (
    powershell_environment as recovery_powershell_environment,
)

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "scripts" / "ai_guardian_recovery.py"
pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="Standalone recovery requires Python 3.11+"
)
HOME_VARIABLES = (
    "CLAUDE_CONFIG_DIR CURSOR_CONFIG_DIR COPILOT_HOME GROK_HOME CODEX_HOME "
    "GEMINI_CLI_HOME CLINE_DATA_DIR KIRO_HOME JUNIE_HOME AIDER_DESK_DIR "
    "AIDER_DESK_HOME_DIR OPENCLAW_STATE_DIR OPENCLAW_HOME OPENCLAW_CONFIG_PATH "
    "OPENCODE_CONFIG_DIR OPENCODE_CONFIG CRUSH_GLOBAL_CONFIG PI_CODING_AGENT_DIR"
).split()
GENERATED = "// ai-guardian-generated-version: 1.20.0\n"


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for name in HOME_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    for name, relative in {
        "APPDATA": "appdata",
        "LOCALAPPDATA": "localappdata",
        "XDG_CONFIG_HOME": ".config",
        "XDG_STATE_HOME": ".local/state",
        "XDG_CACHE_HOME": ".cache",
        "AI_GUARDIAN_CONFIG_DIR": ".config/ai-guardian",
        "AI_GUARDIAN_STATE_DIR": ".local/state/ai-guardian",
        "AI_GUARDIAN_CACHE_DIR": ".cache/ai-guardian",
    }.items():
        monkeypatch.setenv(name, str(home / relative))
    monkeypatch.chdir(tmp_path)
    return home


@pytest.fixture
def engine(isolated_home):
    return runpy.run_path(str(ENGINE))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def hook(command="/removed/venv/bin/ai-guardian"):
    return {"type": "command", "command": command}


def snapshot(home):
    return {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}


def powershell_environment(tmp_path):
    return recovery_powershell_environment(os.environ, tmp_path / "powershell-runtime")


@pytest.mark.parametrize("inherited", [None, "0", "2", "2147483647"])
def test_powershell_runtime_environment_overrides_startup_optimization(
    isolated_home, tmp_path, monkeypatch, inherited
):
    name = "DOTNET_MultiCoreJitMinNumCpus"
    if inherited is None:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)
    else:
        monkeypatch.setenv(name, inherited)
        monkeypatch.setenv(name.upper(), inherited)
    monkeypatch.setenv("COMPlus_MultiCoreJitMinNumCpus", "0")
    original = dict(os.environ)
    environment = powershell_environment(tmp_path)

    # CoreCLR parses this DWORD as hexadecimal. A decimal max-int string can
    # overflow and silently restore the default two-CPU optimization threshold.
    assert environment[name] == "7FFFFFFF"
    assert int(environment[name], 16) == 2**31 - 1
    assert [key for key in environment if key.casefold() == name.casefold()] == [name]
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "AI_GUARDIAN_STATE_DIR"):
        assert environment[key] == original[key]
    legacy_key = next(
        key for key in original if key.casefold() == "complus_multicorejitminnumcpus"
    )
    assert environment[legacy_key] == "0"
    assert dict(os.environ) == original


@pytest.mark.skipif(
    shutil.which("pwsh") is None, reason="Native PowerShell unavailable"
)
def test_native_powershell_startup_preserves_complete_selected_home(
    isolated_home, tmp_path
):
    write_json(isolated_home / ".claude.json", {"sentinel": "unrelated settings"})
    before = snapshot(isolated_home)
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-Command",
            "[Console]::Write($env:DOTNET_MultiCoreJitMinNumCpus)",
        ],
        env=powershell_environment(tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "7FFFFFFF"
    assert snapshot(isolated_home) == before


def stat_values(info, **overrides):
    """Model Windows' distinct path/handle timestamps without a Windows host."""
    values = {
        name: getattr(info, name)
        for name in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_nlink",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    }
    return SimpleNamespace(**{**values, **overrides})


def test_safe_read_compares_handle_timestamps_with_handle_timestamps(
    engine, tmp_path, monkeypatch
):
    path = write_json(tmp_path / "settings.json", {"hooks": {"PreToolUse": [hook()]}})
    original = path.read_bytes()
    real_fstat = os.fstat

    def windows_handle_stat(fd):
        info = real_fstat(fd)
        # CPython on Windows can expose creation time through lstat(), but
        # metadata change time through fstat() (python/cpython#157671).
        return stat_values(info, st_ctime_ns=info.st_ctime_ns + 10_000_000)

    monkeypatch.setattr(os, "fstat", windows_handle_stat)
    data, info = engine["safe_read"](path)
    assert data == original
    assert info.st_mode == path.lstat().st_mode


@pytest.mark.parametrize("field", ["st_mtime_ns", "st_ctime_ns", "st_size"])
def test_safe_read_still_rejects_handle_changes_during_read(
    engine, tmp_path, monkeypatch, field
):
    path = write_json(tmp_path / "settings.json", {"x": 1})
    original = path.read_bytes()
    real_fstat = os.fstat
    calls = 0

    def changed_handle_stat(fd):
        nonlocal calls
        calls += 1
        info = real_fstat(fd)
        return stat_values(info, **{field: getattr(info, field) + (calls - 1)})

    monkeypatch.setattr(os, "fstat", changed_handle_stat)
    with pytest.raises(ValueError, match="changed while reading"):
        engine["safe_read"](path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("field", ["st_ino", "st_ctime_ns"])
def test_safe_read_rejects_path_changes_while_handle_is_stable(
    engine, tmp_path, monkeypatch, field
):
    path = write_json(tmp_path / "settings.json", {"x": 1})
    original = path.read_bytes()
    real_lstat = Path.lstat
    calls = 0

    def changed_path_stat(selected):
        nonlocal calls
        info = real_lstat(selected)
        if selected == path:
            calls += 1
            if calls == 3:
                return stat_values(info, **{field: getattr(info, field) + 1})
        return info

    monkeypatch.setattr(Path, "lstat", changed_path_stat)
    with pytest.raises(ValueError, match="changed while reading"):
        engine["safe_read"](path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("missing", ["executable", "interpreter", "module"])
def test_package_first_removal_with_isolated_stdlib_python(
    isolated_home, tmp_path, missing
):
    """The application, pinned interpreter and launcher need not exist."""
    runtime = tmp_path / "removed-runtime"
    runtime.mkdir()
    launcher = runtime / "ai-guardian"
    launcher.write_text("not a real installation", encoding="utf-8")
    if missing == "interpreter":
        command = str(runtime / "python") + " -m ai_guardian"
    elif missing == "module":
        command = f'"{sys.executable}" -I -S -m ai_guardian_hook_runtime'
    else:
        command = str(launcher)
    config = write_json(
        isolated_home / ".claude/settings.json",
        {"hooks": {"PreToolUse": [{"hooks": [hook(command), hook("other")]}]}},
    )
    launcher.unlink()
    runtime.rmdir()
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(ENGINE), "--scope", "user", "--yes"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(config.read_text())["hooks"]["PreToolUse"][0]["hooks"] == [
        hook("other")
    ]
    assert len(list(config.parent.glob("*.bak"))) == 1


@pytest.mark.parametrize(
    "command",
    [
        "ai-guardian --ide cursor",
        '"/removed path/ai-guardian" --ide claude',
        '"C:\\removed path\\ai-guardian.exe" --ide cursor',
        '"C:\\removed path\\python.exe" -m ai_guardian --ide cline',
        "/removed/python -I -m ai_guardian_hook_runtime",
    ],
)
def test_owned_commands_do_not_require_runtime(engine, command):
    assert engine["owned_command"](command)


@pytest.mark.parametrize(
    "command",
    [
        "echo ai-guardian",
        "/tools/not-ai-guardian",
        "ai-guardian-helper",
        "echo /removed/ai-guardian",
        "ai-guardian && other-check",
        "ai-guardian; other-check",
        "python -m ai_guardian_other",
        "python other.py ai-guardian",
    ],
)
def test_ambiguous_or_unrelated_commands_are_not_owned(engine, command):
    assert not engine["owned_command"](command)


def test_preview_is_read_only_and_repeat_cleanup_is_noop(engine, isolated_home):
    config = write_json(
        isolated_home / ".cursor/hooks.json",
        {"version": 1, "hooks": {"preToolUse": [hook(), hook("other")]}},
    )
    before = snapshot(isolated_home)
    assert engine["main"](["--scope", "user", "--dry-run"]) == 0
    assert snapshot(isolated_home) == before
    assert engine["main"](["--scope", "user", "--yes"]) == 0
    assert json.loads(config.read_text())["hooks"]["preToolUse"] == [hook("other")]
    cleaned = snapshot(isolated_home)
    assert engine["main"](["--scope", "user", "--yes"]) == 0
    assert snapshot(isolated_home) == cleaned


def test_jsonc_preserves_comments_settings_and_nested_mcp(engine, isolated_home):
    path = isolated_home / ".config/opencode/opencode.jsonc"
    path.parent.mkdir(parents=True)
    path.write_text(
        """{ // retain this comment
  "model": "provider/model", "permissions": [],
  "mcp": {"timeout": {"startup": 1234}, "servers": {
    "ai-guardian": {"type":"local", "command":["/gone/ai-guardian","mcp-server"]},
    "third-party": {"url":"https://example.invalid/mcp"},
  }},
  "plugins": ["third-party-plugin"],
}""",
        encoding="utf-8",
    )
    assert engine["main"](["--yes"]) == 0
    output = path.read_text()
    assert "// retain this comment" in output
    assert '"permissions": []' in output
    assert '"startup": 1234' in output
    assert "third-party" in output
    assert "ai-guardian" not in output


def test_codex_toml_preserves_other_tables_and_quoted_children(engine, isolated_home):
    path = isolated_home / ".codex/config.toml"
    path.parent.mkdir()
    path.write_text(
        """# keep this comment
model = "test-model"
[features]
hooks = true
[mcp_servers."ai-guardian"]
command = "/gone/ai-guardian"
args = ["mcp-server"]
[mcp_servers."ai-guardian".env]
LABEL = "synthetic"
[mcp_servers.other]
command = "other-server"
""",
        encoding="utf-8",
    )
    assert engine["main"](["--yes"]) == 0
    output = path.read_text()
    assert "ai-guardian" not in output
    assert '# keep this comment\nmodel = "test-model"' in output
    assert "hooks = true" in output
    assert '[mcp_servers.other]\ncommand = "other-server"' in output


@pytest.mark.parametrize("filename", ["opencode.json", "opencode.jsonc"])
def test_relocated_opencode_and_owned_legacy_plugin_registration(
    engine, isolated_home, tmp_path, monkeypatch, filename
):
    base = tmp_path / "relocated code"
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(base))
    plugin = base / "plugins/ai-guardian.ts"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(GENERATED, encoding="utf-8")
    config = write_json(
        base / filename,
        {"plugin": [str(plugin), "other-plugin"], "mcp": {"ai-guardian": hook()}},
    )
    untouched = write_json(isolated_home / ".config/opencode/opencode.json", {"x": 1})
    assert engine["main"](["--yes"]) == 0
    assert json.loads(config.read_text()) == {
        "plugin": ["other-plugin"],
        "mcp": {},
    }
    assert not plugin.exists()
    assert untouched.read_text() == '{"x": 1}'


@pytest.mark.parametrize(
    "host,relative,manifest,source",
    [
        ("pi", ".pi/agent/extensions", "_PI_PACKAGE_JSON", "_PI_EXTENSION_TS"),
        (
            "aiderdesk",
            ".aider-desk/extensions",
            "_AIDERDESK_PACKAGE_JSON",
            "_AIDERDESK_EXTENSION_TS",
        ),
        (
            "openclaw",
            ".openclaw/plugins",
            "_OPENCLAW_PACKAGE_JSON",
            "_OPENCLAW_PLUGIN_TS",
        ),
    ],
)
def test_managed_and_legacy_artifacts_preserve_unowned_files(
    engine, isolated_home, host, relative, manifest, source
):
    from ai_guardian.setup import hooks

    base = isolated_home / relative
    package = base / "ai-guardian"
    write_json(package / "package.json", json.loads(getattr(hooks, manifest)))
    (package / "index.ts").write_text(
        hooks._render_typescript_source(getattr(hooks, source)), encoding="utf-8"
    )
    (package / "ai-guardian-bridge.ts").write_text(
        hooks.IDESetup._render_guardian_bridge("/gone/ai-guardian"), encoding="utf-8"
    )
    if host == "pi":
        (base / "ai-guardian.ts").write_text(GENERATED, encoding="utf-8")
    (package / "user-notes.txt").write_text("keep", encoding="utf-8")
    (base / "other.ts").write_text("keep", encoding="utf-8")
    assert engine["main"](["--yes"]) == 0
    assert not (package / "index.ts").exists()
    assert not (package / "package.json").exists()
    assert not (package / "ai-guardian-bridge.ts").exists()
    assert not (base / "ai-guardian.ts").exists()
    assert (package / "user-notes.txt").read_text() == "keep"
    assert (base / "other.ts").read_text() == "keep"


def test_project_cleanup_requires_explicit_scope_and_never_walks(
    engine, isolated_home, tmp_path
):
    project = tmp_path / "selected"
    script = project / ".clinerules/hooks/PreToolUse"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n/gone/ai-guardian --ide cline\n", encoding="utf-8")
    other = script.parent / "PostToolUse"
    other.write_text(
        "#!/bin/sh\nother-check # ai-guardian documentation\n", encoding="utf-8"
    )
    nested = write_json(
        project / "nested/.cursor/hooks.json", {"hooks": {"preToolUse": [hook()]}}
    )
    user = write_json(
        isolated_home / ".cursor/hooks.json", {"hooks": {"preToolUse": [hook()]}}
    )
    assert (
        engine["main"](["--scope", "project", "--project", str(project), "--yes"]) == 0
    )
    assert not script.exists()
    assert other.exists() and nested.exists()
    assert "ai-guardian" in user.read_text()


@pytest.mark.parametrize(
    "scope,args",
    [
        ("project", []),
        ("user", ["--project", "."]),
        ("project", ["--project", ""]),
        ("project", ["--project", "missing-project"]),
    ],
)
def test_invalid_scope_selection_fails_before_changes(
    engine, isolated_home, scope, args
):
    before = snapshot(isolated_home)
    with pytest.raises(SystemExit) as error:
        engine["main"](["--scope", scope, *args, "--yes"])
    assert error.value.code == 2
    assert snapshot(isolated_home) == before


@pytest.mark.parametrize(
    "contents", ['{"hooks": ', '{"hooks": []}', '{"hooks": {}, "hooks": {}}']
)
def test_malformed_config_reports_partial_failure_and_continues(
    engine, isolated_home, contents
):
    bad = isolated_home / ".claude/settings.json"
    bad.parent.mkdir()
    bad.write_text(contents, encoding="utf-8")
    good = write_json(
        isolated_home / ".cursor/hooks.json", {"hooks": {"preToolUse": [hook()]}}
    )
    assert engine["main"](["--yes"]) == 1
    assert bad.read_text() == contents
    assert not list(bad.parent.glob("*.bak"))
    assert "ai-guardian" not in good.read_text()


def test_unknown_named_mcp_server_is_preserved_and_reported(engine, isolated_home):
    config = write_json(
        isolated_home / ".claude.json",
        {"mcpServers": {"ai-guardian": {"command": "third-party-server"}}},
    )
    before = config.read_bytes()
    assert engine["main"](["--yes"]) == 1
    assert config.read_bytes() == before


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink and mode semantics")
def test_symlink_and_unwritable_targets_are_not_modified(
    engine, isolated_home, tmp_path
):
    outside = write_json(tmp_path / "outside.json", {"hooks": {"preToolUse": [hook()]}})
    cursor = isolated_home / ".cursor"
    cursor.mkdir()
    (cursor / "hooks.json").symlink_to(outside)
    claude = write_json(
        isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}}
    )
    claude.chmod(0o400)
    before = outside.read_bytes(), claude.read_bytes()
    assert engine["main"](["--yes"]) == 1
    assert (outside.read_bytes(), claude.read_bytes()) == before


@pytest.mark.skipif(sys.platform == "win32", reason="uninstall.sh is POSIX-only")
def test_bash_integration_only_never_stops_processes_or_uninstalls(
    isolated_home, tmp_path
):
    config = write_json(
        isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}}
    )
    result = subprocess.run(
        ["bash", str(ROOT / "uninstall.sh"), "--integrations-only", "--yes"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=os.environ.copy(),
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ai-guardian" not in config.read_text()
    assert "Stopping running processes" not in result.stdout
    assert "Detecting install method" not in result.stdout


@pytest.mark.skipif(
    shutil.which("pwsh") is None, reason="Native PowerShell unavailable"
)
def test_native_powershell_recovery(isolated_home, tmp_path):
    config = write_json(
        isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}}
    )
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(ROOT / "uninstall.ps1"),
            "-IntegrationsOnly",
            "-Yes",
            "-Python",
            sys.executable,
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=powershell_environment(tmp_path),
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ai-guardian" not in config.read_text()


@pytest.mark.skipif(
    shutil.which("pwsh") is None, reason="Native PowerShell unavailable"
)
@pytest.mark.parametrize(
    "arguments",
    [
        ["-Scope", "invalid"],
        ["-Scope", "project"],
        ["-IntegrationsOnly", "-Python", "missing-independent-python"],
    ],
)
def test_native_powershell_prerequisite_errors_are_nonmutating_exit_two(
    isolated_home, tmp_path, arguments
):
    config = write_json(
        isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}}
    )
    original = snapshot(isolated_home)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(ROOT / "uninstall.ps1"), *arguments],
        env=powershell_environment(tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    after = snapshot(isolated_home)
    changed_paths = {
        path
        for path in original.keys() | after.keys()
        if original.get(path) != after.get(path)
    }
    assert not changed_paths
    assert config.exists()


@pytest.mark.parametrize(
    "host",
    [
        "claude",
        "cursor",
        "copilot",
        "grok",
        "codex",
        "windsurf",
        "gemini",
        "antigravity",
        "augment",
        "crush",
    ],
)
def test_current_setup_hook_schemas_round_trip(engine, host):
    from ai_guardian.setup.hooks import IDESetup

    setup = IDESetup()
    template = copy.deepcopy(setup.IDE_CONFIGS[host]["hooks"])
    base = {"unrelated": {"empty": [], "setting": False}}
    if host == "copilot":
        config = {**base, **template}  # Copilot setup writes top-level event arrays.
    else:
        config, _ = setup.merge_hooks(base, template, host)
    assert "ai-guardian" in json.dumps(config)
    cleaned, problems = engine["clean_json"](json.dumps(config), host, set())
    assert problems == []
    result = json.loads(cleaned)
    assert result["unrelated"] == {"empty": [], "setting": False}
    assert "ai-guardian" not in cleaned


@pytest.mark.parametrize("relocated", [False, True])
def test_inventory_matches_canonical_setup_paths(
    engine, isolated_home, tmp_path, monkeypatch, relocated
):
    from ai_guardian.setup.hooks import IDESetup
    from ai_guardian.setup.mcp import _MCP_IDE_CONFIGS, get_mcp_config_path

    if relocated:
        for name in HOME_VARIABLES:
            target = tmp_path / name
            monkeypatch.setenv(name, str(target))
    configs, artifacts = engine["inventory"]("user", [])
    paths = {entry.path for entry in configs}
    files = {entry.path for entry in artifacts}
    setup = IDESetup()
    for host, metadata in setup.IDE_CONFIGS.items():
        raw = setup.get_config_path(host)
        if not raw or not raw.startswith(("~", str(tmp_path))):
            continue  # Explicit project-local configurations are not user scope.
        path = Path(raw).expanduser()
        if metadata.get("plugin_file"):
            assert path / "ai-guardian.ts" in files, host
        elif metadata.get("managed_extension"):
            assert path / "ai-guardian/index.ts" in files, host
        elif metadata.get("extension_based"):
            assert path / "index.ts" in files, host
        else:
            assert path in paths, host
    for host in _MCP_IDE_CONFIGS:
        path = get_mcp_config_path(host)
        if path is not None and path.is_absolute():
            assert path in paths, host


@pytest.mark.parametrize("selected", list(itertools.product((False, True), repeat=4)))
def test_lossless_jsonc_removes_any_hook_subset(engine, selected):
    hooks = [
        hook() if remove else hook(f"other-{index}")
        for index, remove in enumerate(selected)
    ]
    text = (
        '{ /* preserve */ "hooks": {"preToolUse": '
        + json.dumps(hooks)[:-1]
        + ',]}, "other": [],}'
    )
    output, problems = engine["clean_json"](text, "cursor", set())
    assert not problems
    result = engine["load_json"](output)
    remaining = [entry for remove, entry in zip(selected, hooks) if not remove]
    assert result["hooks"].get("preToolUse", []) == remaining
    assert result["other"] == []
    assert "/* preserve */" in output


def test_plugin_registration_can_be_recovered_after_plugin_itself_is_removed(
    engine, isolated_home
):
    base = isolated_home / ".config/opencode"
    plugin = base / "plugins/ai-guardian.ts"
    config = write_json(base / "opencode.json", {"plugin": [str(plugin), "keep"]})
    assert engine["main"](["--yes"]) == 0
    assert json.loads(config.read_text())["plugin"] == ["keep"]


def test_explicit_opencode_file_wins_over_home_and_keeps_unowned_plugin(
    engine, tmp_path, monkeypatch
):
    base = tmp_path / "explicit"
    path = write_json(
        base / "custom.jsonc", {"mcp": {"servers": {"ai-guardian": hook()}}}
    )
    ignored = write_json(
        tmp_path / "ignored/opencode.json", {"mcp": {"ai-guardian": hook()}}
    )
    monkeypatch.setenv("OPENCODE_CONFIG", str(path))
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(ignored.parent))
    plugin = base / "plugins/ai-guardian.ts"
    plugin.parent.mkdir()
    plugin.write_text("// user-owned same-name plugin", encoding="utf-8")
    assert engine["main"](["--yes"]) == 1
    assert "ai-guardian" not in path.read_text()
    assert "ai-guardian" in ignored.read_text()
    assert plugin.read_text() == "// user-owned same-name plugin"


def test_backups_are_exact_private_and_never_overwritten(engine, isolated_home):
    path = write_json(
        isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}}
    )
    original = path.read_bytes()
    for _ in range(2):
        path.write_bytes(original)
        assert engine["main"](["--yes"]) == 0
    backups = list(path.parent.glob("*.bak"))
    assert len(backups) == 2
    assert all(backup.read_bytes() == original for backup in backups)
    if sys.platform != "win32":
        assert all(backup.stat().st_mode & 0o777 == 0o600 for backup in backups)


@pytest.mark.parametrize("operation", ["backup", "replace"])
def test_mutation_failures_leave_original_and_report_nonzero(
    engine, isolated_home, monkeypatch, operation
):
    path = write_json(
        isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}}
    )
    original = path.read_bytes()
    if operation == "backup":
        real_open = os.open

        def fail_backup(file, *args, **kwargs):
            if ".ai-guardian-backup-" in str(file):
                raise PermissionError("synthetic backup failure")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(os, "open", fail_backup)
    else:
        monkeypatch.setattr(
            os,
            "replace",
            lambda *args: (_ for _ in ()).throw(
                PermissionError("synthetic replacement failure")
            ),
        )
    assert engine["main"](["--yes"]) == 1
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".guardian-recovery-*.tmp"))


def test_changed_file_is_not_overwritten(engine, isolated_home):
    path = write_json(
        isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}}
    )
    change = engine["Change"](path, path.read_bytes(), b"{}", path.stat().st_mode)
    path.write_text('{"new-setting":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        change.apply()
    assert path.read_text() == '{"new-setting":true}'
    assert not list(path.parent.glob("*.bak"))


def test_cancellation_and_preserved_guardian_history(
    engine, isolated_home, monkeypatch
):
    write_json(isolated_home / ".claude.json", {"mcpServers": {"ai-guardian": hook()}})
    write_json(
        isolated_home / ".config/ai-guardian/ai-guardian.json", {"setting": "retain"}
    )
    history = isolated_home / ".local/state/ai-guardian/violations.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text("synthetic history", encoding="utf-8")
    original = snapshot(isolated_home)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert engine["main"]([]) == 1
    assert snapshot(isolated_home) == original
    assert engine["main"](["--yes"]) == 0
    assert history.read_text() == "synthetic history"
    assert (
        isolated_home / ".config/ai-guardian/ai-guardian.json"
    ).read_bytes() == original[Path(".config/ai-guardian/ai-guardian.json")]


@pytest.mark.parametrize(
    "text",
    [
        'mcp_servers = {ai-guardian = {command="ai-guardian"}}\n',
        '[mcp_servers.ai-guardian]\ncommand = "ai-guardian"\n[broken\n',
        'note = """\n[mcp_servers.ai-guardian]\nnot a table\n"""\n[mcp_servers.ai-guardian]\ncommand="ai-guardian"\n',
    ],
)
def test_unsupported_or_malformed_toml_never_loses_unrelated_content(engine, text):
    try:
        result, _ = engine["clean_toml"](text)
    except ValueError:
        return
    # A fully verified surgical edit is also safe when the header-looking
    # string happens not to interfere with the actual owned table.
    assert 'note = """\n[mcp_servers.ai-guardian]\nnot a table\n"""' in result


def test_errors_do_not_echo_configuration_contents(engine, isolated_home, capsys):
    path = isolated_home / ".claude/settings.json"
    path.parent.mkdir()
    path.write_text('{"PRIVATE_DIAGNOSTIC_SENTINEL": malformed}', encoding="utf-8")
    assert engine["main"](["--yes"]) == 1
    captured = capsys.readouterr()
    assert "PRIVATE_DIAGNOSTIC_SENTINEL" not in captured.out + captured.err
    assert str(path) in captured.err


@pytest.mark.skipif(sys.platform == "win32", reason="uninstall.sh is POSIX-only")
def test_partial_cleanup_stops_full_uninstall_before_package_and_processes(
    isolated_home, tmp_path
):
    path = isolated_home / ".claude/settings.json"
    path.parent.mkdir()
    path.write_text("malformed", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(ROOT / "uninstall.sh"), "--yes", "--python", sys.executable],
        env=os.environ.copy(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Stopping running processes" not in result.stdout
    assert "Detecting install method" not in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="uninstall.sh is POSIX-only")
@pytest.mark.parametrize(
    "command_line",
    ["/usr/bin/other --label ai-guardian", "/gone/ai-guardian daemon start"],
)
def test_normal_uninstall_preview_requires_owned_process_launch(
    isolated_home, tmp_path, command_line
):
    import shlex

    state = isolated_home / ".local/state/ai-guardian"
    state.mkdir(parents=True)
    (state / "daemon.pid").write_text("12345", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ps = fake_bin / "ps"
    ps.write_text(
        "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(command_line) + "\n",
        encoding="utf-8",
    )
    ps.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "uninstall.sh"), "--dry-run", "--python", sys.executable],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if command_line.startswith("/gone/ai-guardian"):
        assert "Would stop owned process (PID 12345)" in result.stdout
    else:
        assert "Would stop owned process" not in result.stdout
        assert "Retained unverified/stale process reference:" in result.stdout


@pytest.mark.skipif(
    shutil.which("pwsh") is None, reason="Native PowerShell unavailable"
)
def test_native_powershell_preview_project_scope_and_idempotency(
    isolated_home, tmp_path
):
    project = tmp_path / "selected project"
    config = write_json(
        project / ".cursor/hooks.json", {"hooks": {"preToolUse": [hook()]}}
    )
    user = write_json(
        isolated_home / ".cursor/hooks.json", {"hooks": {"preToolUse": [hook()]}}
    )
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(ROOT / "uninstall.ps1"),
        "-IntegrationsOnly",
        "-Scope",
        "project",
        "-Project",
        str(project),
        "-Python",
        sys.executable,
    ]
    environment = powershell_environment(tmp_path)
    before = config.read_bytes()
    preview = subprocess.run(
        [*command, "-DryRun"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert config.read_bytes() == before
    for _ in range(2):
        result = subprocess.run(
            [*command, "-Yes"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert "ai-guardian" not in config.read_text()
    assert "ai-guardian" in user.read_text()
    assert len(list(config.parent.glob("*.bak"))) == 1


def test_ci_lifecycle_is_explicit_native_and_shared_by_release_and_smoke():
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/orphan-recovery.yml").read_text()
    )
    job = workflow["jobs"]["recovery"]
    assert set(job["strategy"]["matrix"]["os"]) == {
        "ubuntu-26.04",
        "macos-latest",
        "windows-latest",
    }
    native = next(step for step in job["steps"] if step.get("shell") == "pwsh")
    assert native["if"] == "runner.os == 'Windows'"
    bash = next(step for step in job["steps"] if step.get("shell") == "bash")
    assert bash["if"] == "runner.os != 'Windows'"
    smoke = yaml.safe_load((ROOT / ".github/workflows/smoke-tests.yml").read_text())
    assert (
        smoke["jobs"]["orphan-recovery"]["uses"]
        == "./.github/workflows/orphan-recovery.yml"
    )
    release = yaml.safe_load(
        (ROOT / ".github/workflows/release-readiness.yml").read_text()
    )
    assert (
        release["jobs"]["smoke-tests"]["uses"] == "./.github/workflows/smoke-tests.yml"
    )
    assert "orphan-recovery" not in release["jobs"]  # Avoid running the matrix twice.
    scenario = (ROOT / "tests/lifecycle/orphan_recovery.py").read_text()
    tree = ast.parse(scenario)
    assert 'os.environ.get("GITHUB_ACTIONS") != "true"' in scenario
    assert any(
        [element.value for element in node.elts if isinstance(element, ast.Constant)]
        == ["-m", "pip", "uninstall", "-y", "ai-guardian"]
        for node in ast.walk(tree)
        if isinstance(node, ast.List)
    )
    assert '"claude", "cursor", "codex", "opencode", "pi"' in scenario
    # Shell caches are isolated, not ignored inside any selected config home.
    assert '"powershell-runtime"' in scenario
    assert '"PSModuleAnalysisCachePath"' in scenario
    assert '"DOTNET_MultiCoreJitMinNumCpus": "7FFFFFFF"' in scenario
    assert "if p.is_file() and not p.is_relative_to(runtime)" in scenario


def test_lifecycle_matrix_accounts_for_every_supported_host():
    from ai_guardian.ide_registry import SUPPORTED_IDE_TYPES

    matrix = (
        (ROOT / "docs/UNINSTALL.md")
        .read_text()
        .split("## Missing-runtime lifecycle matrix", 1)[1]
    )
    for host in SUPPORTED_IDE_TYPES:
        assert f"(`{host}`)" in matrix, host
    assert "not live host qualification" in matrix
