"""Behavior and prompt contracts for the local OpenWolf plugin sources."""

from __future__ import annotations

import re
import shutil
import subprocess
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_openwolf_plugin_node_contracts() -> None:
    """Run runtime tests when Node supports native TypeScript stripping."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")

    version = subprocess.run(
        [node, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    match = re.match(r"v(\d+)\.(\d+)", version)
    if match is None or tuple(map(int, match.groups())) < (22, 6):
        pytest.skip("Node.js 22.6 or newer is required for native TypeScript stripping")

    result = subprocess.run(
        [
            node,
            "--experimental-strip-types",
            "--experimental-loader",
            str(ROOT / "tests/unit/openwolf_ts_loader.mjs"),
            "--test",
            str(ROOT / "tests/unit/openwolf_plugin_contract.test.mjs"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_reframe_prompts_preserve_migration_scope_and_current_framework_apis() -> None:
    prompt = (ROOT / ".opencode/command/reframe.md").read_text(encoding="utf-8")
    framework_prompts = prompt.split("## Framework Prompts", maxsplit=1)[1]

    assert (
        "existing routes, screens, content, data flows, and behavior are the migration target"
        in framework_prompts
    )
    assert "never a migration checklist" in framework_prompts
    assert "SECTIONS TO BUILD" not in framework_prompts
    assert '@plugin "daisyui"' in framework_prompts
    assert r"@plugin \"daisyui\"" not in framework_prompts
    assert "flowbite-svelte" in framework_prompts
    assert "AccordionButton" not in framework_prompts
    assert "AccordionPanel" not in framework_prompts
    assert "extendTheme" not in framework_prompts
    assert "ChakraProvider with `value={system}`" in framework_prompts
    assert "List.Root/List.Item" in framework_prompts


def test_openwolf_hooks_and_agent_config_keep_their_contracts() -> None:
    shared = (ROOT / ".opencode/plugins/openwolf/shared.ts").read_text(encoding="utf-8")
    stdin_read = shared.index(".then(() => readStdin())")
    enabled_check = shared.index("openwolf?.enabled === false")
    assert stdin_read < enabled_check
    assert 'path.join(projectDir, ".wolf", "config.json")' in shared
    assert "observeTaskReview" not in shared
    assert not (ROOT / ".opencode/plugins/openwolf/task-review.ts").exists()

    plugin_index = (ROOT / ".opencode/plugins/openwolf/index.ts").read_text(
        encoding="utf-8"
    )
    event_handler = plugin_index.index("await handleOpenCodeEvent(")
    handler_catch = plugin_index.index("OpenWolf: event handler failed", event_handler)
    assert event_handler < handler_catch

    config = json.loads((ROOT / ".wolf/config.json").read_text(encoding="utf-8"))
    assert config["openwolf"]["agents"] == ["claude", "codex", "opencode", "cursor"]
