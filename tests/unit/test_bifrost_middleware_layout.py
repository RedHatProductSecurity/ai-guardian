"""Regression checks for the Bifrost plugin compatibility contract."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
METADATA = ROOT / "go" / "bifrost-middleware" / "compatibility.json"


def test_bifrost_metadata_pins_qualified_build_inputs():
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))

    assert metadata["bifrost"] == {
        "version": "2.6.0",
        "revision": "172617bb045c6f43d697843c115e64f0155ed143",
        "hook_contract": "PreLLMHook/PostLLMHook",
        "build_mode": "dynamic-plugin",
    }
    assert metadata["toolchain"]["go"] == "1.27.4"


def test_bifrost_metadata_keeps_windows_out_of_native_plugin_artifacts():
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))

    assert metadata["platforms"][:2] == [
        {
            "os": "linux",
            "architecture": "amd64",
            "priority": "high",
            "artifact": "ai-guardian-bifrost-v2.6.0-go1.27.4-linux-amd64.so",
        },
        {
            "os": "linux",
            "architecture": "arm64",
            "priority": "high",
            "artifact": "ai-guardian-bifrost-v2.6.0-go1.27.4-linux-arm64.so",
        },
    ]
    assert metadata["unsupported"][0]["os"] == "windows"
