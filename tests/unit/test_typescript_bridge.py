"""Tests for the shared TypeScript process bridge used by agent plugins."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian import __version__
from ai_guardian.setup import (
    _AIDERDESK_EXTENSION_TS,
    _AI_GUARDIAN_BRIDGE_TS,
    _OPENCLAW_PLUGIN_TS,
    _OPENCODE_PLUGIN_TS,
)
from ai_guardian.setup.hooks import IDESetup


def test_generated_hosts_delegate_to_shared_bridge():
    """Host callbacks remain local while process handling lives in one file."""
    for source, ide_type in (
        (_AIDERDESK_EXTENSION_TS, "aiderdesk"),
        (_OPENCLAW_PLUGIN_TS, "openclaw"),
        (_OPENCODE_PLUGIN_TS, "opencode"),
    ):
        assert "./ai-guardian-bridge" in source
        assert "createGuardianBridge" in source
        assert f"ideType: '{ide_type}'" in source
        assert "execSync" not in source
        assert "execFileSync" not in source


def test_shared_bridge_contains_process_and_response_contracts():
    """The shared source owns process failures, timeout, parsing, and redaction."""
    assert "execFileSync" in _AI_GUARDIAN_BRIDGE_TS
    assert "timeout: timeoutMs" in _AI_GUARDIAN_BRIDGE_TS
    assert "AI_GUARDIAN_IDE_TYPE: options.ideType" in _AI_GUARDIAN_BRIDGE_TS
    assert "failure.status === 1 || failure.status === 2" in _AI_GUARDIAN_BRIDGE_TS
    assert "parseGuardianOutput" in _AI_GUARDIAN_BRIDGE_TS
    assert "updatedToolOutput" in _AI_GUARDIAN_BRIDGE_TS
    assert "updatedMCPToolOutput" in _AI_GUARDIAN_BRIDGE_TS
    assert "updated_mcp_tool_output" in _AI_GUARDIAN_BRIDGE_TS
    assert "parseGuardianOutput(raw: unknown)" in _AI_GUARDIAN_BRIDGE_TS
    assert "typeof raw !== 'string'" in _AI_GUARDIAN_BRIDGE_TS


def test_setup_renders_resolved_binary_in_shared_bridge():
    setup = IDESetup()
    rendered = setup._render_guardian_bridge("/tmp/guardian with spaces/ai-guardian")

    assert (
        'const GUARDIAN_BINARY = "/tmp/guardian with spaces/ai-guardian";' in rendered
    )
    assert "...binaryArgs, '--ide', options.ideType" in rendered
    assert "ai-guardian" in rendered


def test_setup_renders_python_module_command_as_executable_and_args():
    setup = IDESetup()
    rendered = setup._render_guardian_bridge(r"C:\Python312\pythonw.exe -m ai_guardian")

    expected_binary = json.dumps(r"C:\Python312\pythonw.exe")
    assert f"const GUARDIAN_BINARY = {expected_binary};" in rendered
    assert 'const GUARDIAN_BINARY_ARGS: string[] = ["-m", "ai_guardian"];' in rendered


@pytest.mark.parametrize("ide_type", ["aiderdesk", "openclaw", "opencode"])
def test_setup_and_health_check_include_shared_bridge(tmp_path, ide_type):
    setup = IDESetup()
    install_root = tmp_path / ide_type
    config_file = install_root / "opencode.json"

    with (
        mock.patch.object(setup, "get_config_path", return_value=str(install_root)),
        mock.patch.object(
            setup, "verify_gitleaks_installed", return_value=(True, "ok")
        ),
        mock.patch(
            "ai_guardian.setup.hooks._resolve_opencode_config",
            return_value=config_file,
        ),
    ):
        success, message = setup.setup_ide_hooks(ide_type, force=True)
        verification = setup.verify_hooks_for_ide(ide_type)

    assert success is True, message
    assert (install_root / "ai-guardian-bridge.ts").is_file()
    assert verification["healthy"] is True, verification
    host_file = "ai-guardian.ts" if ide_type == "opencode" else "index.ts"
    for artifact in (
        install_root / host_file,
        install_root / "ai-guardian-bridge.ts",
    ):
        assert f"// ai-guardian-generated-version: {__version__}" in artifact.read_text(
            encoding="utf-8"
        )


def test_existing_opencode_is_upgraded_without_first_run_setup(tmp_path):
    setup = IDESetup()
    install_root = tmp_path / "plugins"
    install_root.mkdir()
    plugin_file = install_root / "ai-guardian.ts"
    plugin_file.write_text("// existing ai-guardian plugin\n", encoding="utf-8")
    config_file = tmp_path / "opencode.json"
    config_file.write_text(
        json.dumps({"plugin": [str(plugin_file)]}) + "\n", encoding="utf-8"
    )
    setup.IDE_CONFIGS = {"opencode": dict(IDESetup.IDE_CONFIGS["opencode"])}

    with (
        mock.patch.object(setup, "get_config_path", return_value=str(install_root)),
        mock.patch.object(
            setup, "verify_gitleaks_installed", return_value=(True, "ok")
        ),
        mock.patch(
            "ai_guardian.setup.hooks._resolve_opencode_config",
            return_value=config_file,
        ),
    ):
        results = setup.upgrade_typescript_integrations()

    assert results and results[0]["ide"] == "opencode"
    assert results[0]["success"] is True
    assert f"// ai-guardian-generated-version: {__version__}" in plugin_file.read_text(
        encoding="utf-8"
    )
    assert (install_root / "ai-guardian-bridge.ts").is_file()


def test_current_typescript_integration_is_not_rewritten(tmp_path):
    setup = IDESetup()
    install_root = tmp_path / "plugins"
    config_file = tmp_path / "opencode.json"
    setup.IDE_CONFIGS = {"opencode": dict(IDESetup.IDE_CONFIGS["opencode"])}

    with (
        mock.patch.object(setup, "get_config_path", return_value=str(install_root)),
        mock.patch.object(
            setup, "verify_gitleaks_installed", return_value=(True, "ok")
        ),
        mock.patch(
            "ai_guardian.setup.hooks._resolve_opencode_config",
            return_value=config_file,
        ),
    ):
        assert setup.setup_ide_hooks("opencode", force=True)[0]
        assert setup.upgrade_typescript_integrations() == []


NODE = shutil.which("node")


def _node_supports_type_stripping() -> bool:
    if not NODE:
        return False
    result = subprocess.run(
        [NODE, "--experimental-strip-types", "-e", "console.log('ok')"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _write_bridge_runtime(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    bridge_path = tmp_path / "ai-guardian-bridge.ts"
    bridge_path.write_text(_AI_GUARDIAN_BRIDGE_TS, encoding="utf-8")

    fake_guardian = tmp_path / "fake-guardian.mjs"
    fake_guardian.write_text(
        """#!/usr/bin/env node
const mode = process.env.BRIDGE_CASE;
if (mode === 'allow') {
  process.stdout.write(JSON.stringify({args: process.argv.slice(2), ide: process.env.AI_GUARDIAN_IDE_TYPE}));
} else if (mode === 'nested-block') {
  process.stdout.write(JSON.stringify({output: JSON.stringify({decision: 'block', reason: 'blocked response'})}));
} else if (mode === 'redaction') {
  process.stdout.write(JSON.stringify({output: JSON.stringify({hookSpecificOutput: {updatedToolOutput: '[REDACTED]'}})}));
} else if (mode === 'blocked-process') {
  process.stderr.write('blocked process');
  process.exit(2);
} else if (mode === 'failed-process') {
  process.stderr.write('failed process');
  process.exit(3);
} else if (mode === 'timeout') {
  setTimeout(() => process.stdout.write('{}'), 1000);
}
""",
        encoding="utf-8",
    )
    fake_guardian.chmod(0o755)

    runner = tmp_path / "run-bridge.mjs"
    runner.write_text(
        """import { createGuardianBridge } from './ai-guardian-bridge.ts';
const bridge = createGuardianBridge({
  ideType: 'test',
  binary: process.env.BRIDGE_BINARY,
  args: process.env.BRIDGE_ARGS ? JSON.parse(process.env.BRIDGE_ARGS) : undefined,
  timeoutMs: Number(process.env.BRIDGE_TIMEOUT || 30000),
});
console.log(JSON.stringify(bridge.run({ source: 'unit-test' })));
""",
        encoding="utf-8",
    )
    return fake_guardian, runner


@pytest.mark.skipif(
    not _node_supports_type_stripping(),
    reason="Node.js with TypeScript type stripping is required",
)
@pytest.mark.parametrize(
    ("case_name", "expected"),
    [
        ("allow", {"blocked": False}),
        ("nested-block", {"blocked": True, "error": "blocked response"}),
        ("redaction", {"blocked": False, "updatedOutput": "[REDACTED]"}),
        ("blocked-process", {"blocked": True, "error": "blocked process"}),
        ("failed-process", {"blocked": False}),
        ("timeout", {"blocked": False}),
    ],
)
def test_shared_bridge_runtime_contract(tmp_path, case_name, expected):
    """Exercise allow, response, process-failure, and timeout paths."""
    fake_guardian, runner = _write_bridge_runtime(tmp_path)
    env = os.environ.copy()
    env["BRIDGE_CASE"] = case_name
    env["BRIDGE_BINARY"] = str(NODE)
    env["BRIDGE_ARGS"] = json.dumps([str(fake_guardian)])
    if case_name == "timeout":
        env["BRIDGE_TIMEOUT"] = "20"

    completed = subprocess.run(
        [NODE, "--experimental-strip-types", str(runner)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    for key, value in expected.items():
        assert result.get(key) == value

    if case_name == "allow":
        assert "--ide" in result["output"]
        assert "test" in result["output"]
