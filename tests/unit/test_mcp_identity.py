"""Tests for built-in AI Guardian MCP identity attestation."""

import json
import sys
from unittest.mock import patch

import pytest

from ai_guardian.ide_registry import SUPPORTED_IDE_REGISTRY
from ai_guardian.mcp import identity
from ai_guardian.setup.mcp import _MCP_IDE_CONFIGS

LOCAL_MCP_IDES = tuple(
    integration.key
    for integration in SUPPORTED_IDE_REGISTRY
    if integration.mcp_registration in {"local", "local-extension"}
)


def _module_command() -> str:
    return f"{sys.executable} -m ai_guardian"


def test_register_identity_writes_signed_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    assert identity.register_mcp_identity(_module_command()) is True

    manifest_path = identity.get_identity_manifest_path()
    key_path = identity.get_identity_key_path()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["server_name"] == "ai-guardian"
    assert manifest["entry_point"] == identity.ENTRY_POINT
    assert manifest["signature"]
    assert key_path.exists()


def test_missing_manifest_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))

    assert identity.verify_active_attestation() is False


def test_process_exists_uses_cross_platform_pid_check():
    with patch("ai_guardian.mcp.identity.is_pid_alive", return_value=True) as check:
        assert identity._process_exists(12345) is True

    check.assert_called_once_with(12345)


def test_genuine_process_passes_nonce_attestation(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))
    assert identity.register_mcp_identity(_module_command()) is True

    try:
        assert identity.attest_mcp_server() is True
        assert identity.verify_active_attestation() is True
    finally:
        identity.revoke_active_attestation()


def test_missing_identity_is_migrated_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))

    assert identity.ensure_mcp_identity() is True
    assert identity._load_verified_manifest() is not None

    try:
        assert identity.attest_mcp_server() is True
    finally:
        identity.revoke_active_attestation()


@pytest.mark.parametrize("ide_type", LOCAL_MCP_IDES)
def test_every_local_mcp_client_uses_startup_migration(ide_type, tmp_path, monkeypatch):
    """Every supported local MCP client shares the migration gate."""
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / ide_type / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / ide_type / "state"))

    assert ide_type in _MCP_IDE_CONFIGS
    assert identity.ensure_mcp_identity() is True

    try:
        assert identity.attest_mcp_server() is True
    finally:
        identity.revoke_active_attestation()


def test_stale_identity_is_migrated_after_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))
    assert identity.register_mcp_identity(_module_command()) is True

    assert identity._load_verified_manifest() is not None
    stale_identity = {
        **identity._current_identity(),
        "package_sha256": "stale-package-digest",
    }
    monkeypatch.setattr(identity, "_current_identity", lambda: stale_identity)
    with patch.object(identity, "register_mcp_identity", return_value=True) as migrate:
        assert identity.ensure_mcp_identity() is True

    migrate.assert_called_once()


def test_tampered_identity_is_not_migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))
    assert identity.register_mcp_identity(_module_command()) is True

    manifest_path = identity.get_identity_manifest_path()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["signature"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with patch.object(identity, "register_mcp_identity") as migrate:
        assert identity.ensure_mcp_identity() is False

    migrate.assert_not_called()


@pytest.mark.timeout(0)
def test_nonce_cannot_be_replayed(monkeypatch):
    challenge = identity.begin_identity_handshake()
    response = {
        "server_name": identity.MCP_SERVER_NAME,
        "nonce": challenge["nonce"],
        "pid": identity.os.getpid(),
    }
    observed = {
        "package_version": "1.0.0",
        "package_sha256": "package-digest",
        "runtime_executable": "runtime-executable",
        "runtime_executable_sha256": "runtime-digest",
        "entrypoint_sha256": None,
    }
    manifest = {
        **observed,
        "signature": "manifest-signature",
    }
    monkeypatch.setattr(identity, "_load_verified_manifest", lambda: manifest)
    monkeypatch.setattr(identity, "_current_identity", lambda: observed)
    monkeypatch.setattr(identity, "_process_executable", lambda pid: None)
    with patch.object(identity, "_write_json") as write_json:
        assert identity.complete_identity_handshake(challenge, response) is True
        assert identity.complete_identity_handshake(challenge, response) is False
    write_json.assert_called_once()


def test_tampered_manifest_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))
    assert identity.register_mcp_identity(_module_command()) is True

    manifest_path = identity.get_identity_manifest_path()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert identity.attest_mcp_server() is False


def test_spoofed_process_identity_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GUARDIAN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_GUARDIAN_STATE_DIR", str(tmp_path / "state"))
    assert identity.register_mcp_identity(_module_command()) is True
    challenge = identity.begin_identity_handshake()

    observed = identity._current_identity()
    observed["package_sha256"] = "0" * 64
    response = {
        "server_name": identity.MCP_SERVER_NAME,
        "nonce": challenge["nonce"],
        "pid": identity.os.getpid(),
    }
    with patch.object(identity, "_current_identity", return_value=observed):
        assert identity.complete_identity_handshake(challenge, response) is False


def test_setup_registers_identity_after_mcp_config_write(tmp_path):
    from ai_guardian.setup import IDESetup
    from ai_guardian.setup.mcp import _install_mcp_config

    config_path = tmp_path / "mcp.json"
    with (
        patch("ai_guardian.setup.mcp.get_mcp_config_path", return_value=config_path),
        patch(
            "ai_guardian.setup.mcp._resolve_binary_path",
            return_value="/mock/bin/ai-guardian",
        ),
        patch("ai_guardian.setup.mcp._register_mcp_identity") as register_identity,
    ):
        _install_mcp_config(IDESetup(), "claude")

    register_identity.assert_called_once_with("/mock/bin/ai-guardian")
