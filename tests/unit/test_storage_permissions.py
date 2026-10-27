"""Isolated POSIX setup/startup storage regressions for issue #2584."""

import json
import logging
import os
from pathlib import Path
import stat
import subprocess
import sys
from unittest import mock

import pytest

from ai_guardian.daemon.server import DaemonServer
from ai_guardian.setup.config import create_default_config

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX storage modes")


@pytest.mark.parametrize("mask", [0o000, 0o002, 0o022, 0o077])
@pytest.mark.parametrize("json_mode", [False, True])
def test_fresh_setup_and_token_provisioning_under_umask(tmp_path, mask, json_mode):
    """Start before package import: logging must not pre-create unsafe state."""
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    env = dict(os.environ)
    for key in (
        "AI_GUARDIAN_CONFIG_DIR",
        "AI_GUARDIAN_HOME",
        "AI_GUARDIAN_STATE_DIR",
        "AI_GUARDIAN_CACHE_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    ):
        env.pop(key, None)
    env["HOME"] = str(home)
    script = f"""
import json, os, stat
os.umask({mask})
from ai_guardian.config.utils import get_config_dir, get_state_dir, get_cache_dir
from ai_guardian.daemon.server import DaemonServer
from ai_guardian.setup.config import create_default_config
if {json_mode!r}:
    from ai_guardian.setup import setup_hooks
    from unittest.mock import patch
    with patch('ai_guardian.setup._discover_unconfigured_ides', return_value=([], [])):
        assert setup_hooks(create_config=True, json_output=True)
else:
    assert create_default_config()[0]
DaemonServer._ensure_auth_token()
from unittest.mock import patch
server = DaemonServer(enable_rest_api=True)
try:
    with patch('ai_guardian.config.loaders._load_config_file', return_value=(
        {{'daemon': {{'rest_host': '127.0.0.1', 'rest_port': 0}}}}, None
    )):
        server._start_rest_api()
    assert server._rest_port > 0
    server._write_pid_file()
finally:
    if server._rest_api:
        server._rest_api.stop()
home = __import__('pathlib').Path.home()
for directory in (get_config_dir(), get_state_dir(), get_cache_dir()):
    while directory != home:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, str(directory)
        directory = directory.parent
for path in (get_config_dir() / 'ai-guardian.json', get_state_dir() / 'daemon.token', get_state_dir() / 'daemon.pid'):
    assert stat.S_IMODE(path.stat().st_mode) == 0o600, str(path)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # The child never prints credentials, even when an assertion fails.
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("unsafe", ["leaf", "ancestor", "symlink", "dangling"])
@pytest.mark.parametrize("json_mode", [False, True])
def test_setup_rejects_unsafe_paths_without_mutating_them(
    tmp_path, monkeypatch, capsys, unsafe, json_mode
):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o700)
    config = shared / "config"
    if unsafe in {"leaf", "ancestor"}:
        config.mkdir(mode=0o700)
        (config if unsafe == "leaf" else shared).chmod(0o775)
    else:
        target = tmp_path / "target"
        if unsafe == "symlink":
            target.mkdir(mode=0o700)
        config.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(config))
    before = shared.stat().st_mode
    if json_mode:
        from ai_guardian.setup import setup_hooks

        with mock.patch(
            "ai_guardian.setup._discover_unconfigured_ides", return_value=([], [])
        ):
            success = setup_hooks(create_config=True, json_output=True)
        response = json.loads(capsys.readouterr().out)
        assert response["success"] is False
        message = response["error"]
    else:
        success, message = create_default_config()
    assert not success
    assert "storage" in message.lower()
    assert not (config / "ai-guardian.json").exists()
    assert shared.stat().st_mode == before
    if unsafe in {"symlink", "dangling"}:
        assert config.is_symlink()


@pytest.mark.parametrize("location", ["leaf", "ancestor"])
def test_unsafe_existing_state_explains_rest_failure_without_publishing_token(
    tmp_path, monkeypatch, caplog, location
):
    # Sanitizer CLI tests can leave logging globally disabled. Let pytest enable
    # capture for this assertion and restore the previous logging state afterward.
    caplog.set_level(logging.ERROR, logger="ai_guardian")
    shared = tmp_path / "shared"
    state = shared / "state"
    state.mkdir(parents=True, mode=0o700)
    bad = state if location == "leaf" else shared
    bad.chmod(0o775)
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(state))
    server = DaemonServer(enable_rest_api=True)
    with (
        mock.patch(
            "ai_guardian.config.loaders._load_config_file", return_value=({}, None)
        ),
        mock.patch("ai_guardian.daemon.rest_api.DaemonRestAPI") as listener,
    ):
        server._start_rest_api()
    listener.assert_not_called()
    assert server._rest_port == 0
    assert str(bad) in server._rest_error
    assert "0775" in server._rest_error
    assert "group/other-writable" in server._rest_error
    assert server._rest_error in caplog.text
    assert not (state / "daemon.token").exists()
    assert not list(state.glob(".daemon.token.*.tmp"))
    assert stat.S_IMODE(bad.stat().st_mode) == 0o775
    server._write_pid_file()
    metadata = json.loads((state / "daemon.pid").read_text())
    assert metadata["rest_status"] == "unavailable"
    assert metadata["rest_error"] == server._rest_error


def test_failed_token_publication_cleans_only_owned_temporary(tmp_path, monkeypatch):
    token = tmp_path / "daemon.token"
    monkeypatch.setattr("ai_guardian.daemon.get_auth_token_path", lambda: token)
    with mock.patch("os.replace", side_effect=OSError("unit-sensitive-error")):
        with pytest.raises(ValueError) as failure:
            DaemonServer._ensure_auth_token()
    assert "unit-sensitive-error" not in str(failure.value)
    assert not token.exists()
    assert not list(tmp_path.glob(".daemon.token.*.tmp"))


def test_existing_token_symlink_is_not_read_or_replaced(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.write_text("unit-sensitive-token")
    target.chmod(0o600)
    token = tmp_path / "daemon.token"
    token.symlink_to(target)
    monkeypatch.setattr("ai_guardian.daemon.get_auth_token_path", lambda: token)
    with pytest.raises(ValueError):
        DaemonServer._ensure_auth_token()
    assert token.is_symlink()
    assert target.read_text() == "unit-sensitive-token"


@pytest.mark.parametrize(
    "kind",
    [
        "directory_owner",
        "ancestor_link_owner",
        "file_owner",
        "file_mode",
        "directory_file",
    ],
)
def test_storage_rejects_untrusted_metadata_without_repairs(
    tmp_path, monkeypatch, kind
):
    from ai_guardian.storage import StorageError, check_storage_file

    directory = tmp_path / "material"
    directory.mkdir(mode=0o700)
    file = directory / "config.json"
    file.write_text("unit-sensitive-token")
    file.chmod(0o600)
    if kind == "file_mode":
        file.chmod(0o664)
    elif kind == "directory_file":
        file = directory
    else:
        original = Path.lstat
        bad = file if kind == "file_owner" else directory
        if kind == "ancestor_link_owner":
            link = tmp_path / "link"
            link.symlink_to(directory, target_is_directory=True)
            bad = link
            file = link / "config.json"

        def untrusted(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == bad:
                values = list(info)
                values[4] = os.geteuid() + 1000
                return os.stat_result(values)
            return info

        monkeypatch.setattr(Path, "lstat", untrusted)
    with pytest.raises(StorageError):
        check_storage_file(file)


def test_atomic_config_no_clobber_and_failure_cleanup(tmp_path, monkeypatch):
    from ai_guardian.storage import write_private_text

    config = tmp_path / "config.json"
    link = os.link

    def race(source, destination):
        config.write_text("intervening-user-config")
        link(source, destination)

    with mock.patch("os.link", side_effect=race):
        assert not write_private_text(config, "new-config")
    assert config.read_text() == "intervening-user-config"
    with mock.patch("os.replace", side_effect=OSError("publication failed")):
        with pytest.raises(OSError):
            write_private_text(config, "replacement", overwrite=True)
    assert config.read_text() == "intervening-user-config"
    assert not list(tmp_path.glob(".config.json.*.tmp"))


@pytest.mark.parametrize("force", [False, True])
def test_setup_never_truncates_existing_unsafe_config(tmp_path, monkeypatch, force):
    config = tmp_path / "ai-guardian.json"
    config.write_text("existing-user-content")
    config.chmod(0o664)
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path))
    success, message = create_default_config(force=force)
    assert not success
    assert "0664" in message
    assert config.read_text() == "existing-user-content"
    assert stat.S_IMODE(config.stat().st_mode) == 0o664


@pytest.mark.parametrize("option", ["dry_run", "json_output"])
def test_setup_preview_does_not_create_storage(tmp_path, monkeypatch, option):
    before = set(
        tmp_path.iterdir()
    )  # The shared isolation fixture already owns directories here.
    for key in ("CONFIG", "STATE", "CACHE"):
        monkeypatch.setenv(f"AI_GUARDIAN_{key}_DIR", str(tmp_path / key.lower()))
    assert create_default_config(**{option: True})[0]
    assert set(tmp_path.iterdir()) == before
    assert all(not (tmp_path / name).exists() for name in ("config", "state", "cache"))


def test_pid_publication_preserves_preexisting_temporary_collision(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path))
    collision = tmp_path / f".daemon.pid.{os.getpid()}.tmp"
    collision.write_text("existing-user-file")
    server = DaemonServer(enable_rest_api=False)
    with pytest.raises(FileExistsError):
        server._write_pid_file()
    assert collision.read_text() == "existing-user-file"
    assert not (tmp_path / "daemon.pid").exists()
