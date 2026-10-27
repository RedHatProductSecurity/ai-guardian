"""Protected pairing persistence and strict destination validation."""

from dataclasses import asdict, replace
import json
import os
from unittest import mock

import pytest

from ai_guardian.daemon.ssh_storage import (
    DESTINATION_ERROR,
    DUPLICATE_ERROR,
    STORAGE_ERROR,
    SSHConnectionError,
    SSHProfile,
    SSHStore,
    destination,
)
from tests.fixtures.ssh_daemon import make_pairing


@pytest.fixture
def pairing(tmp_path):
    return make_pairing(tmp_path)[0]


@pytest.mark.parametrize(
    "host", ["vm", "vm.example.internal", "tester@vm-alias", "127.0.0.1"]
)
def test_destination_allows_existing_aliases(host):
    assert destination(host) == host


@pytest.mark.parametrize(
    "host",
    [
        "-oProxyCommand=bad",
        "vm;echo bad",
        "vm\nother",
        "ssh://vm",
        "a b",
        "vm:22",
        "",
        None,
        "a@-vm",
        "u@v@w",
    ],
)
def test_destination_rejects_command_injection(host):
    with pytest.raises(SSHConnectionError) as error:
        destination(host)
    assert str(error.value) == DESTINATION_ERROR


def test_round_trip_private_and_exclusive(tmp_path, pairing):
    store = SSHStore(tmp_path / "connections")
    assert store.load() == []
    store.create(pairing.profile)
    assert store.load() == [pairing.profile]
    assert store.contains(pairing.profile)
    record = store.path / f"{pairing.profile.id}.json"
    original = record.read_bytes()
    with pytest.raises(SSHConnectionError) as error:
        store.create(replace(pairing.profile, token="replacement-credential"))
    assert str(error.value) == DUPLICATE_ERROR
    assert record.read_bytes() == original
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o700
        assert record.stat().st_mode & 0o777 == 0o600
    store.remove(pairing.profile.id)
    assert store.load() == []
    assert not store.contains(pairing.profile)
    assert not list(store.path.glob(".pair-*"))


def test_private_values_never_appear_in_reprs(pairing):
    assert pairing.profile.token not in repr(pairing.profile)
    assert pairing.profile.token not in repr(pairing)
    assert pairing.profile.ca_pem not in repr(pairing.profile)


@pytest.mark.parametrize(
    "change",
    [
        {"token": "bad\nheader"},
        {"certificate_sha256": "bad"},
        {"server_name": ""},
        {"ca_pem": ""},
        {"token": False},
    ],
)
def test_invalid_saved_record(pairing, change):
    with pytest.raises(ValueError):
        SSHProfile.from_dict({**asdict(pairing.profile), **change})


@pytest.mark.parametrize("profile_id", ["../other", "", "x" * 32, None])
def test_removal_never_uses_unvalidated_path(tmp_path, profile_id):
    with pytest.raises(SSHConnectionError):
        SSHStore(tmp_path).remove(profile_id)


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes; Windows records use DPAPI")
@pytest.mark.parametrize("unsafe", ["directory", "record", "symlink", "parent"])
def test_unsafe_storage_fails_closed(tmp_path, pairing, unsafe):
    store = SSHStore(tmp_path / "connections")
    store.create(pairing.profile)
    record = store.path / f"{pairing.profile.id}.json"
    if unsafe == "directory":
        store.path.chmod(0o755)
    elif unsafe == "record":
        record.chmod(0o644)
    elif unsafe == "parent":
        tmp_path.chmod(0o777)
    else:
        saved = tmp_path / "saved.json"
        record.rename(saved)
        record.symlink_to(saved)
    try:
        with pytest.raises(SSHConnectionError) as error:
            store.load()
        assert str(error.value) == STORAGE_ERROR
        assert not store.contains(pairing.profile)
    finally:
        tmp_path.chmod(0o700)


def test_malformed_or_misnamed_record_is_not_loaded(tmp_path, pairing):
    store = SSHStore(tmp_path / "connections")
    store.create(pairing.profile)
    record = store.path / f"{pairing.profile.id}.json"
    record.rename(store.path / "other.json")
    with pytest.raises(SSHConnectionError) as error:
        store.load()
    assert str(error.value) == STORAGE_ERROR


def test_windows_storage_encrypts_entire_profile(tmp_path, pairing):
    # Exercise the storage protocol without pretending POSIX chmod proves ACLs.
    store = SSHStore(tmp_path / "connections")
    calls = []

    def protect(data, *, decrypt=False):
        calls.append((data, decrypt))
        return data[::-1]

    with (
        mock.patch("ai_guardian.daemon.ssh_storage._WINDOWS", True),
        mock.patch("ai_guardian.daemon.ssh_storage._dpapi", side_effect=protect),
        mock.patch("ai_guardian.daemon.ssh_storage._material_file"),
    ):
        store.create(pairing.profile)
        assert store.load() == [pairing.profile]
    assert [call[1] for call in calls] == [False, True]
    assert json.loads(calls[0][0])["token"] == pairing.profile.token


@pytest.mark.skipif(os.name != "nt", reason="Native Windows DPAPI contract")
def test_native_dpapi_integrity():
    from ai_guardian.daemon.ssh_storage import _dpapi

    data = b"synthetic-pairing-record"
    encrypted = _dpapi(data)
    assert data not in encrypted
    assert _dpapi(encrypted, decrypt=True) == data
    with pytest.raises(SSHConnectionError):
        _dpapi(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), decrypt=True)


def test_dismissal_is_private_idempotent_case_insensitive_and_separate_from_trust(
    tmp_path, pairing
):
    store = SSHStore(tmp_path / "connections")
    assert not store.is_dismissed("alias")
    store.create(pairing.profile)
    original = (store.path / f"{pairing.profile.id}.json").read_bytes()
    store.dismiss("user@ALIAS")
    store.dismiss("alias")
    assert SSHStore(store.path).is_dismissed("Alias")
    assert len(list(store.path.glob(".dismissed-*"))) == 1
    marker = next(store.path.glob(".dismissed-*"))
    assert marker.read_bytes() == b""
    if os.name != "nt":
        assert marker.stat().st_mode & 0o777 == 0o600
    assert (store.path / f"{pairing.profile.id}.json").read_bytes() == original
    assert store.load() == [pairing.profile]


def test_dismissal_never_overwrites_existing_marker_content(tmp_path):
    store = SSHStore(tmp_path / "connections")
    store.dismiss("alias")
    marker = next(store.path.glob(".dismissed-*"))
    marker.write_bytes(b"preserve")
    with pytest.raises(SSHConnectionError, match=STORAGE_ERROR):
        store.dismiss("alias")
    assert marker.read_bytes() == b"preserve"
