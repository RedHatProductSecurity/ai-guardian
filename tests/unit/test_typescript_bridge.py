"""Tests for the shared TypeScript process bridge used by agent plugins."""

import json
import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from unittest import mock

import pytest

from ai_guardian import __version__
from ai_guardian.setup import (
    _AIDERDESK_EXTENSION_TS,
    _AI_GUARDIAN_BRIDGE_TS,
    _OPENCLAW_PLUGIN_TS,
    _OPENCODE_PLUGIN_TS,
    _OPENCODE_PLUGIN_V2_TS,
    _PI_EXTENSION_TS,
)
from ai_guardian.setup.hooks import (
    IDESetup,
    _load_typescript_template,
    _render_pi_extension_source,
    _render_typescript_source,
)

TYPESCRIPT_TEMPLATES = {
    "ai-guardian-bridge.ts": _AI_GUARDIAN_BRIDGE_TS,
    "aiderdesk-extension.ts": _AIDERDESK_EXTENSION_TS,
    "pi-extension.ts": _PI_EXTENSION_TS,
    "opencode-plugin-v1.ts": _OPENCODE_PLUGIN_TS,
    "opencode-plugin-v2.ts": _OPENCODE_PLUGIN_V2_TS,
    "openclaw-plugin.ts": _OPENCLAW_PLUGIN_TS,
}


@pytest.mark.parametrize(("filename", "source"), TYPESCRIPT_TEMPLATES.items())
def test_typescript_template_is_loaded_from_package_resources(filename, source):
    packaged = resources.files("ai_guardian.setup").joinpath("templates", filename)
    assert packaged.read_text(encoding="utf-8") == source
    assert _load_typescript_template(filename) == source


def test_generated_typescript_artifacts_resolve_template_placeholders():
    binary_path = "/tmp/guardian path/ai-guardian"
    setup = IDESetup()
    rendered_sources = [
        setup._render_guardian_bridge(binary_path),
        _render_typescript_source(_AIDERDESK_EXTENSION_TS),
        _render_pi_extension_source(enable_mcp=True, binary_path=binary_path),
        _render_pi_extension_source(enable_mcp=False, binary_path=binary_path),
        _render_typescript_source(_OPENCODE_PLUGIN_TS),
        _render_typescript_source(_OPENCODE_PLUGIN_V2_TS),
        _render_typescript_source(_OPENCLAW_PLUGIN_TS),
    ]

    for source in rendered_sources:
        assert "__AI_GUARDIAN_" not in source
        assert f"// ai-guardian-generated-version: {__version__}" in source

    assert 'const GUARDIAN_BINARY = "/tmp/guardian path/ai-guardian";' in (
        rendered_sources[0]
    )
    assert "const PI_MCP_ENABLED = true;" in rendered_sources[2]
    assert "const PI_MCP_ENABLED = false;" in rendered_sources[3]
    assert 'const GUARDIAN_BINARY = "/tmp/guardian path/ai-guardian";' in (
        rendered_sources[2]
    )


def test_generated_hosts_delegate_to_shared_bridge():
    """Host callbacks remain local while process handling lives in one file."""
    for source, ide_type in (
        (_AIDERDESK_EXTENSION_TS, "aiderdesk"),
        (_OPENCLAW_PLUGIN_TS, "openclaw"),
        (_OPENCODE_PLUGIN_TS, "opencode"),
    ):
        bridge_import = (
            "../ai-guardian/ai-guardian-bridge"
            if ide_type == "opencode"
            else "./ai-guardian-bridge"
        )
        assert bridge_import in source
        assert "createGuardianBridge" in source
        assert f"ideType: '{ide_type}'" in source
        assert "execSync" not in source
        assert "execFileSync" not in source


def test_opencode_session_end_forwards_session_id():
    assert "hook_event_name: 'SessionEnd'" in _OPENCODE_PLUGIN_TS
    assert "session_id: input?.sessionID" in _OPENCODE_PLUGIN_TS


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
    bridge_path = install_root / setup.IDE_CONFIGS[ide_type]["bridge_file"]
    assert bridge_path.is_file()
    assert verification["healthy"] is True, verification
    host_file = "ai-guardian.ts" if ide_type == "opencode" else "index.ts"
    for artifact in (
        install_root / host_file,
        bridge_path,
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
    legacy_bridge_file = install_root / "ai-guardian-bridge.ts"
    legacy_bridge_file.write_text(
        setup._render_guardian_bridge("ai-guardian"), encoding="utf-8"
    )
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
    bridge_path = install_root / setup.IDE_CONFIGS["opencode"]["bridge_file"]
    assert bridge_path.is_file()
    assert not legacy_bridge_file.exists()


def test_opencode_auto_upgrade_does_not_require_registration(tmp_path):
    setup = IDESetup()
    install_root = tmp_path / "plugins"
    install_root.mkdir()
    plugin_file = install_root / "ai-guardian.ts"
    plugin_file.write_text(
        _OPENCODE_PLUGIN_TS.replace("__AI_GUARDIAN_VERSION__", __version__),
        encoding="utf-8",
    )
    legacy_bridge_file = install_root / "ai-guardian-bridge.ts"
    legacy_bridge_file.write_text(
        setup._render_guardian_bridge("ai-guardian"), encoding="utf-8"
    )
    config_file = tmp_path / "opencode.json"
    config_file.write_text("{}\n", encoding="utf-8")
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

    assert results and results[0]["success"] is True
    bridge_path = install_root / setup.IDE_CONFIGS["opencode"]["bridge_file"]
    assert bridge_path.is_file()
    assert not legacy_bridge_file.exists()


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


def _write_opencode_plugin_runtime(tmp_path):
    """Load the actual generated plugin with a recording, non-scanning bridge."""
    (tmp_path / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    plugin_dir = tmp_path / "ai-guardian-plugin"
    plugin_dir.mkdir()
    bridge_dir = tmp_path / "ai-guardian"
    bridge_dir.mkdir()
    (plugin_dir / "index.ts").write_text(
        _OPENCODE_PLUGIN_V2_TS.replace(
            "'../ai-guardian/ai-guardian-bridge'",
            "'../ai-guardian/ai-guardian-bridge.ts'",
        ),
        encoding="utf-8",
    )
    (bridge_dir / "ai-guardian-bridge.ts").write_text(
        """export function createGuardianBridge() {
  return { run(data) { globalThis.guardianCalls.push(data); return { blocked: false }; } };
}
""",
        encoding="utf-8",
    )


@pytest.mark.skipif(
    not _node_supports_type_stripping(),
    reason="Node.js with TypeScript type stripping is required",
)
def test_opencode_v2_idle_preserves_session_and_deletion_ends_it(tmp_path):
    """Execute the generated plugin with the published V2 event envelope."""
    _write_opencode_plugin_runtime(tmp_path)
    events = [
        {"type": "session.created", "data": {"sessionID": "session-one"}},
        {"type": "session.idle", "data": {"sessionID": "session-one"}},
        {"type": "session.idle", "data": {"sessionID": "session-one"}},
        {"type": "session.deleted", "data": {"sessionID": "session-two"}},
        {"type": "session.deleted", "data": {"sessionID": "session-one"}},
        {"type": "session.idle", "data": {}},
        {"type": "session.deleted"},
    ]
    runner = tmp_path / "run-plugin.mjs"
    runner.write_text(
        """import plugin from './ai-guardian-plugin/index.ts';
globalThis.guardianCalls = [];
let finish;
let subscriptionSignal;
const finished = new Promise(resolve => { finish = resolve; });
const ctx = {
  location: { directory: process.cwd() },
  app: { version: '2.0.22' },
  session: { hook: async () => {}, get: async () => ({ title: 'Native title' }) },
  tool: { hook: async () => {} },
  event: { async *subscribe({ signal }) {
    subscriptionSignal = signal;
    try { yield* JSON.parse(process.env.OPENCODE_EVENTS); }
    finally { finish(); }
  } },
};
const cleanup = await plugin.setup(ctx);
await finished;
cleanup();
console.log(JSON.stringify({ calls: globalThis.guardianCalls, aborted: subscriptionSignal.aborted }));
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [NODE, "--experimental-strip-types", str(runner)],
        cwd=tmp_path,
        env={**os.environ, "OPENCODE_EVENTS": json.dumps(events)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert [
        (call["hook_event_name"], call["session_id"]) for call in result["calls"]
    ] == [
        ("Stop", "session-one"),
        ("Stop", "session-one"),
        ("SessionEnd", "session-two"),
        ("SessionEnd", "session-one"),
    ]
    assert all(call["opencode_version"] == "2.0.22" for call in result["calls"])
    assert all(call["cwd"] == str(tmp_path) for call in result["calls"])
    assert result["aborted"] is True
    assert all(call["session_title"] == "Native title" for call in result["calls"][:2])
    assert all("session_title" not in call for call in result["calls"][2:])


@pytest.mark.skipif(
    not _node_supports_type_stripping(),
    reason="Node.js with TypeScript type stripping is required",
)
def test_opencode_v2_session_titles_runtime(tmp_path):
    """Metadata lookup is exact, bounded/cached, refreshable, and never skips hooks."""
    _write_opencode_plugin_runtime(tmp_path)
    runner = tmp_path / "run-titles.mjs"
    runner.write_text(
        """import assert from 'node:assert/strict';
import plugin from './ai-guardian-plugin/index.ts';
globalThis.guardianCalls = [];
const hooks = {};
const requests = [];
const signals = [];
const titles = new Map([['first', 'Original title'], ['other', 'Other title']]);
let now = 1000;
Date.now = () => now;
let mode = 'ok';
const cleanup = await plugin.setup({
  location: { directory: process.cwd() },
  app: { version: '2.0.22' },
  session: {
    hook: async (name, handler) => { hooks[name] = handler; },
    get: async ({ sessionID }, { signal }) => {
      requests.push(sessionID);
      signals.push(signal);
      if (mode === 'throw') throw new Error('metadata unavailable');
      if (mode === 'hang') return new Promise(() => {});
      if (mode === 'delay') await new Promise(resolve => setTimeout(resolve, 20));
      return { title: titles.get(sessionID) };
    },
  },
  tool: { hook: async (name, handler) => { hooks[name] = handler; } },
  event: { async *subscribe() {} },
});
const prompt = (sessionID) => hooks.prompt({ sessionID, prompt: { text: 'hello' } });
const before = (sessionID) => hooks['execute.before']({ sessionID, id: 'call-1', tool: 'read', input: {} });
const after = (sessionID) => hooks['execute.after']({ sessionID, id: 'call-1', tool: 'read', input: {}, status: 'completed', result: { output: 'clean' } });
const last = () => globalThis.guardianCalls.at(-1);
mode = 'delay';
await Promise.all([prompt('first'), before('first'), after('first')]);
assert.deepEqual(requests, ['first']);
assert.ok(globalThis.guardianCalls.every(call => call.session_title === 'Original title'));
mode = 'ok';
await prompt('other');
assert.equal(last().session_title, 'Other title');
titles.set('first', 'Renamed title');
await prompt('first');
assert.equal(last().session_title, 'Original title');
now += 30_001;
await prompt('first');
assert.equal(last().session_title, 'Renamed title');
await prompt('late');
assert.equal(last().session_title, '');
titles.set('late', 'Later title');
now += 30_001;
await prompt('late');
assert.equal(last().session_title, 'Later title');
for (const title of [null, 42, {}, [], undefined]) {
  now += 30_001;
  titles.set('invalid', title);
  await before('invalid');
  assert.equal(last().session_title, '');
  assert.equal(last().session_id, 'invalid');
}
titles.set('long', 'x'.repeat(9000));
await prompt('long');
assert.equal(last().session_title.length, 4096);
mode = 'throw';
await prompt('failure');
await before('failure');
await after('failure');
assert.equal(requests.filter(id => id === 'failure').length, 1);
assert.equal(last().session_title, '');
assert.equal(last().hook_event_name, 'tool.execute.after');
mode = 'hang';
await prompt('timeout');
assert.equal(signals.at(-1).aborted, true);
assert.equal(last().session_title, '');
assert.equal(last().session_id, 'timeout');
mode = 'ok';
for (let index = 0; index < 130; index++) await prompt(`cache-${index}`);
const beforeEviction = requests.filter(id => id === 'cache-0').length;
await prompt('cache-0');
assert.equal(requests.filter(id => id === 'cache-0').length, beforeEviction + 1);
cleanup();
console.log(JSON.stringify({ calls: globalThis.guardianCalls.length, requests: requests.length }));
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [NODE, "--experimental-strip-types", str(runner)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["calls"] > result["requests"] >= 130
