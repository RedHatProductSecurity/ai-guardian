"""Tests for the shared OpenShell release/protocol compatibility check."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import check_openshell_compatibility as compatibility  # noqa: E402


def test_shared_compatibility_contract_is_consistent():
    message = compatibility.verify_contract()

    assert "OpenShell 0.1.2" in message
    assert "supervisor protocol 1.0" in message


def test_explicit_supported_patch_release_is_accepted():
    message = compatibility.check_release("0.1.3")

    assert "Rust middleware contract" in message


def test_explicit_unsupported_minor_release_fails():
    assert compatibility.main(["--version", "0.2.0"]) == 2
