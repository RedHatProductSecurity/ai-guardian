"""Local SSH alias discovery uses disposable configs, never OpenSSH or keys."""

import os
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian.daemon import ssh_config


@pytest.fixture
def config(tmp_path):
    path = tmp_path / ".ssh" / "config"
    path.parent.mkdir()
    return path


def test_concrete_aliases_comments_equals_quotes_and_case_insensitive_dedup(config):
    config.write_text(
        '# Host not-a-host\nHost = "ai-guardian-one" OTHER ai-guardian-two # comment\n'
        "HOST AI-GUARDIAN-ONE *.example !bad a? b[12] -option user@host\n"
        "HostName not-an-alias\nHost existing-vm\n",
        encoding="utf-8",
    )
    assert ssh_config.scan_aliases(config).aliases == (
        "ai-guardian-one",
        "ai-guardian-two",
        "existing-vm",
        "OTHER",
    )
    assert ssh_config.scan_aliases(config, prefix="AI-guardian-").aliases == (
        "ai-guardian-one",
        "ai-guardian-two",
    )


def test_discovery_never_executes_predicates_ssh_or_opens_identity_files(config):
    key = config.parent / "id_ed25519"
    config.write_text(
        'Match exec "not-a-command"\n IdentityFile id_ed25519\n'
        " Include conditional.conf\nHost declared-after-match\n"
        " ProxyCommand not-a-command\n LocalCommand not-a-command\n",
        encoding="utf-8",
    )
    (config.parent / "conditional.conf").write_text("Host hidden\n")
    with (
        mock.patch("subprocess.Popen") as popen,
        mock.patch("subprocess.run") as run,
        mock.patch.object(
            ssh_config, "_read_config", wraps=ssh_config._read_config
        ) as opened,
    ):
        result = ssh_config.scan_aliases(config)
    assert result.aliases == ("declared-after-match",)
    assert result.notices
    assert all(call.args[0] != key for call in opened.call_args_list)
    popen.assert_not_called()
    run.assert_not_called()


def test_unconditional_includes_are_inline_bounded_and_cycle_safe(config):
    directory = config.parent / "config.d"
    directory.mkdir()
    config.write_text('Include "config.d/*.conf"\nHost root\n')
    (directory / "a.conf").write_text("Include ../config\nHost included second\n")
    (directory / "b.conf").write_text("Host not-included-conditionally\n")
    result = ssh_config.scan_aliases(config)
    # The first included Host starts a conditional scope; sibling Include
    # expansions were selected by the unconditional directive and are still read.
    assert result.aliases == (
        "included",
        "not-included-conditionally",
        "root",
        "second",
    )
    assert result.notices  # Parent traversal is outside the supported Include subset.
    (directory / "a.conf").write_text("Include config\nHost included\n")
    assert ssh_config.scan_aliases(config).aliases == (
        "included",
        "not-included-conditionally",
        "root",
    )
    assert ssh_config.scan_aliases(config).notices  # Root include cycle.


def test_missing_unreadable_malformed_and_oversized_configs_are_safe(
    config, monkeypatch
):
    assert ssh_config.scan_aliases(config).aliases == ()
    assert ssh_config.scan_aliases(config).notices
    config.write_text('Host "unterminated\nHost still-valid\n')
    assert ssh_config.scan_aliases(config).aliases == ("still-valid",)
    with mock.patch.object(
        ssh_config, "_read_config", side_effect=PermissionError("private data")
    ):
        result = ssh_config.scan_aliases(config)
    assert result.aliases == ()
    assert "private data" not in repr(result)
    monkeypatch.setattr(ssh_config, "MAX_FILE_BYTES", 8)
    config.write_text("Host too-large\n")
    assert ssh_config.scan_aliases(config).aliases == ()


def test_include_restrictions_do_not_read_keys_external_paths_or_symlinks(
    config, tmp_path
):
    outside = tmp_path / "external.conf"
    outside.write_text("Host external\n")
    config.write_text(
        f"Include id_ed25519 {outside} $HOME/key.conf **/*.conf\nHost safe\n"
    )
    (config.parent / "id_ed25519").write_text("Host not-a-config\n")
    assert ssh_config.scan_aliases(config).aliases == ("safe",)
    if hasattr(Path, "symlink_to"):
        try:
            (config.parent / "link.conf").symlink_to(outside)
        except OSError:
            pytest.skip("Symlinks unavailable to this account")
        config.write_text("Include link.conf\nHost safe\n")
        assert ssh_config.scan_aliases(config).aliases == ("safe",)


@pytest.mark.parametrize(
    "limit", ["MAX_FILES", "MAX_ALIASES", "MAX_DEPTH", "MAX_TOTAL_BYTES"]
)
def test_resource_limits_produce_bounded_partial_results(config, monkeypatch, limit):
    config.write_text("Include a.conf b.conf\nHost root extra\n")
    (config.parent / "a.conf").write_text("Include c.conf\nHost first\n")
    (config.parent / "b.conf").write_text("Host second\n")
    (config.parent / "c.conf").write_text("Host third\n")
    monkeypatch.setattr(ssh_config, limit, 1)
    result = ssh_config.scan_aliases(config)
    assert result.notices
    assert len(result.aliases) <= (1 if limit == "MAX_ALIASES" else 5)


def test_default_path_is_user_openssh_config_on_all_platforms(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ssh_config.user_ssh_config() == tmp_path / ".ssh" / "config"


def test_include_directory_enumeration_and_unmatched_patterns_are_bounded(
    config, monkeypatch
):
    monkeypatch.setattr(ssh_config, "MAX_DIRECTORY_ENTRIES", 1)
    config.write_text("Include *.conf\nHost root\n")
    for index in range(3):
        (config.parent / f"{index}.conf").write_text(f"Host host-{index}\n")
    result = ssh_config.scan_aliases(config)
    assert len(result.aliases) <= 2
    assert ssh_config.LIMIT_NOTICE in result.notices
    monkeypatch.setattr(ssh_config, "MAX_FILES", 2)
    config.write_text("Include a.conf b.conf c.conf\nHost root\n")
    assert ssh_config.LIMIT_NOTICE in ssh_config.scan_aliases(config).notices


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow and FIFO behavior")
def test_nonregular_files_and_link_swaps_are_not_read(config):
    config.write_text("Host root\n")
    original_open = os.open
    replacement = config.parent / "other.conf"
    replacement.write_text("Host replaced\n")

    def swap(path, flags):
        config.unlink()
        config.symlink_to(replacement)
        return original_open(path, flags)

    with mock.patch.object(ssh_config.os, "open", side_effect=swap):
        assert not ssh_config.scan_aliases(config).aliases
    config.unlink()
    os.mkfifo(config)
    assert not ssh_config.scan_aliases(config).aliases


def test_settings_are_global_opt_in_and_invalid_types_fail_closed(tmp_path):
    path = tmp_path / "settings.json"
    assert ssh_config.load_settings(path) == {
        "enabled": False,
        "alias_prefix": "ai-guardian-",
    }
    path.write_text(
        '{"daemon":{"tray":{"ssh_alias_discovery":{"enabled":true,"alias_prefix":""}}}}'
    )
    assert ssh_config.load_settings(path) == {"enabled": True, "alias_prefix": ""}
    path.write_text('{"daemon":{"tray":{"ssh_alias_discovery":{"enabled":"true"}}}}')
    assert ssh_config.load_settings(path)["enabled"] is False
    path.write_text("[]")
    assert ssh_config.load_settings(path)["enabled"] is False
