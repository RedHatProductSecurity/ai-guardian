"""Contracts for the credential-free CLI MCP result-evidence proxy."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ai_guardian import __version__

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "agent_cli_mcp_proxy.py"
SPEC = importlib.util.spec_from_file_location("agent_cli_mcp_proxy_test", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
proxy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proxy
SPEC.loader.exec_module(proxy)


@pytest.mark.parametrize(
    ("cli", "servers"),
    (
        ("claude", ("mcpServers", "ai-guardian")),
        ("gemini", ("mcpServers", "ai-guardian")),
        ("opencode", ("mcp", "ai-guardian")),
        ("opencode", ("mcp", "servers", "ai-guardian")),
    ),
)
def test_json_config_wraps_only_the_ai_guardian_stdio_command(
    tmp_path, cli, servers, monkeypatch
):
    monkeypatch.setattr(proxy, "_installed_version", lambda _command: __version__)
    path = tmp_path / "config.json"
    entry = {
        "command": (
            ["/opt/ai-guardian", "mcp-server"]
            if cli == "opencode"
            else "/opt/ai-guardian"
        ),
        "args": [] if cli == "opencode" else ["mcp-server"],
        "preserved": "value",
    }
    config = {}
    parent = config
    for key in servers[:-1]:
        parent = parent.setdefault(key, {})
    parent[servers[-1]] = entry
    config["unrelated"] = {"preserve": True}
    path.write_text(json.dumps(config), encoding="utf-8")

    proxy._patch_json_config(path, cli, "/tmp/proxy.py")
    updated = json.loads(path.read_text(encoding="utf-8"))
    wrapped = updated
    for key in servers:
        wrapped = wrapped[key]

    expected = [
        sys.executable,
        "/tmp/proxy.py",
        "proxy",
        "--expected-version",
        __version__,
        "--",
        "/opt/ai-guardian",
    ]
    expected.append("mcp-server")
    if cli == "opencode":
        assert wrapped["command"] == expected
        assert "args" not in wrapped
    else:
        assert wrapped["command"] == sys.executable
        assert wrapped["args"] == [
            "/tmp/proxy.py",
            "proxy",
            "--expected-version",
            __version__,
            "--",
            "/opt/ai-guardian",
            "mcp-server",
        ]
    assert wrapped["preserved"] == "value"
    if cli == "opencode" and servers == ("mcp", "servers", "ai-guardian"):
        assert wrapped["codemode"] is False
    else:
        assert "codemode" not in wrapped
    assert updated["unrelated"] == {"preserve": True}


@pytest.mark.parametrize("cli", ("codex", "grok"))
@pytest.mark.parametrize("multiline_args", (False, True))
def test_toml_config_wraps_only_ai_guardian_server(
    tmp_path, cli, monkeypatch, multiline_args
):
    monkeypatch.setattr(proxy, "_installed_version", lambda _command: __version__)
    monkeypatch.setattr(
        proxy, "sys", SimpleNamespace(executable=r"C:\Python\python.exe")
    )
    path = tmp_path / "config.toml"
    proxy_path = r"C:\smoke\agent_cli_mcp_proxy.py"
    args_text = (
        'args = [\n    "mcp-server",\n    "value]inside-string",\n]\n'
        if multiline_args
        else 'args = ["mcp-server"]\n'
    )
    path.write_text(
        "[mcp_servers.ai-guardian]\n"
        'command = "/opt/ai-guardian"\n'
        + args_text
        + "enabled = true\n\n"
        + '[model.smoke]\nmodel = "local"\n',
        encoding="utf-8",
    )

    proxy._patch_toml_config(path, proxy_path)
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    updated = tomllib.loads(path.read_text(encoding="utf-8"))
    entry = updated["mcp_servers"]["ai-guardian"]
    assert entry["command"] == r"C:\Python\python.exe"
    assert entry["args"] == [
        proxy_path,
        "proxy",
        "--expected-version",
        __version__,
        "--",
        "/opt/ai-guardian",
        "mcp-server",
        *(["value]inside-string"] if multiline_args else []),
    ]
    assert entry["enabled"] is True
    assert updated["model"]["smoke"]["model"] == "local"


def test_pi_extension_wraps_managed_mcp_launch_without_touching_other_source(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(proxy, "_installed_version", lambda _command: __version__)
    monkeypatch.setattr(
        proxy, "sys", SimpleNamespace(executable=r"C:\Python\python.exe")
    )
    extension = tmp_path / "index.ts"
    extension.write_text(
        "// generated extension\n"
        'const GUARDIAN_BINARY = "/opt/ai-guardian";\n'
        "const GUARDIAN_BINARY_ARGS: string[] = [];\n"
        "const PI_MCP_ENABLED = true;\n"
        'registerMcpServer("ai-guardian", { command: GUARDIAN_BINARY, '
        'args: [...GUARDIAN_BINARY_ARGS, "mcp-server"] });\n',
        encoding="utf-8",
    )

    proxy_path = r"C:\smoke\agent_cli_mcp_proxy.py"
    proxy._patch_pi_extension(extension, proxy_path)
    source = extension.read_text(encoding="utf-8")
    assert f"const GUARDIAN_BINARY = {json.dumps(proxy.sys.executable)};" in source
    args_prefix = "const GUARDIAN_BINARY_ARGS: string[] = "
    encoded_args = source.split(args_prefix, 1)[1].split(";", 1)[0]
    assert json.loads(encoded_args) == [
        proxy_path,
        "proxy",
        "--expected-version",
        __version__,
        "--",
        "/opt/ai-guardian",
    ]
    assert 'registerMcpServer("ai-guardian"' in source
    assert "const PI_MCP_ENABLED = true;" in source


@pytest.mark.parametrize(
    ("returned_version", "expected_events"),
    (
        (None, ["mcp_call", "mcp_result_mismatch"]),
        ("not-the-installed-version", ["mcp_call", "mcp_result_mismatch"]),
        (__version__, ["mcp_call", "mcp_result_match"]),
    ),
)
def test_stdio_proxy_correlates_result_id_and_checks_installed_version(
    tmp_path, returned_version, expected_events
):
    server = tmp_path / "server.py"
    result = {"content": [{"type": "text", "text": "{}"}], "isError": False}
    if returned_version is not None:
        result["structuredContent"] = {"version": returned_version}
    server.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " if request.get('method') == 'tools/call':\n"
        f"  response={{'jsonrpc':'2.0','id':request['id'],'result':{result!r}}}\n"
        " else:\n"
        "  response={'jsonrpc':'2.0','id':request.get('id'),'result':{}}\n"
        " print(json.dumps(response),flush=True)\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.jsonl"
    env = {
        **os.environ,
        "AI_GUARDIAN_MCP_EVIDENCE_FILE": str(evidence),
    }
    request = {
        "jsonrpc": "2.0",
        "id": "request-1",
        "method": "tools/call",
        "params": {"name": "get_version", "arguments": {}},
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "proxy",
            "--expected-version",
            __version__,
            "--",
            sys.executable,
            str(server),
        ],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    response = json.loads(completed.stdout)
    assert response["id"] == "request-1"
    events = [
        json.loads(line)["event"]
        for line in evidence.read_text(encoding="utf-8").splitlines()
    ]
    assert events == expected_events
    assert returned_version is None or returned_version not in evidence.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("tool_name", "input_schema", "expected_event"),
    (
        ("get_version", {"type": "object", "properties": {}}, "mcp_tools_list_match"),
        ("other_tool", {"type": "object", "properties": {}}, "mcp_tools_list_mismatch"),
        ("get_version", {"type": "string"}, "mcp_tools_list_mismatch"),
    ),
)
def test_stdio_proxy_confirms_the_exact_get_version_tool_list(
    tmp_path, tool_name, input_schema, expected_event
):
    server = tmp_path / "server.py"
    server.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " result={'tools':[{'name':"
        f"{tool_name!r},'inputSchema':{input_schema!r}"
        "}]}\n"
        " print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.jsonl"
    env = {**os.environ, "AI_GUARDIAN_MCP_EVIDENCE_FILE": str(evidence)}
    request = {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list"}
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "proxy",
            "--expected-version",
            __version__,
            "--",
            sys.executable,
            str(server),
        ],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["id"] == "list-1"
    events = [
        json.loads(line)["event"]
        for line in evidence.read_text(encoding="utf-8").splitlines()
    ]
    assert events == [expected_event]


@pytest.mark.parametrize(
    ("tool_name", "expected_events"),
    (("get_config", []), ("get_version", ["mcp_call"])),
)
def test_stdio_proxy_ignores_unrelated_tools_and_unmatched_response_ids(
    tmp_path, tool_name, expected_events
):
    server = tmp_path / "server.py"
    server.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " print(json.dumps({'jsonrpc':'2.0','id':'wrong-id','result':{}}),flush=True)\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.jsonl"
    env = {**os.environ, "AI_GUARDIAN_MCP_EVIDENCE_FILE": str(evidence)}
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}},
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "proxy",
            "--expected-version",
            __version__,
            "--",
            sys.executable,
            str(server),
        ],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout
    events = (
        [
            json.loads(line)["event"]
            for line in evidence.read_text(encoding="utf-8").splitlines()
        ]
        if evidence.exists()
        else []
    )
    assert events == expected_events


def test_installed_version_reads_the_configured_server_binary(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": 10,
        }
        return subprocess.CompletedProcess(command, 0, "ai-guardian 1.23.0-dev\n", "")

    monkeypatch.setattr(proxy.subprocess, "run", run)

    assert proxy._installed_version("/usr/local/bin/ai-guardian") == "1.23.0-dev"
    assert commands == [["/usr/local/bin/ai-guardian", "--version"]]


@pytest.mark.parametrize("cli", ("claude", "codex", "gemini", "opencode", "pi", "grok"))
def test_install_proxy_targets_each_smoke_cli_managed_config(
    tmp_path, monkeypatch, cli
):
    monkeypatch.setattr(proxy, "_installed_version", lambda _command: __version__)
    home = tmp_path / "home"
    home.mkdir()
    if cli in {"claude", "gemini"}:
        config_path = (
            home / ".claude.json"
            if cli == "claude"
            else home / ".gemini" / "settings.json"
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ai-guardian": {
                            "command": "/opt/ai-guardian",
                            "args": ["mcp-server"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
    elif cli == "opencode":
        config_path = home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(
                {
                    "mcp": {
                        "servers": {
                            "ai-guardian": {
                                "command": ["/opt/ai-guardian", "mcp-server"]
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
    elif cli in {"codex", "grok"}:
        config_path = (
            home / ".codex" / "config.toml"
            if cli == "codex"
            else home / ".grok" / "config.toml"
        )
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "[mcp_servers.ai-guardian]\n"
            'command = "/opt/ai-guardian"\n'
            'args = ["mcp-server"]\n',
            encoding="utf-8",
        )
    else:
        config_path = home / ".pi" / "agent" / "extensions" / "ai-guardian" / "index.ts"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            'const GUARDIAN_BINARY = "/opt/ai-guardian";\n'
            "const GUARDIAN_BINARY_ARGS: string[] = [];\n",
            encoding="utf-8",
        )

    assert proxy._install_proxy(cli, home, None) == 0
    assert config_path.is_file()
    content = config_path.read_text(encoding="utf-8")
    if cli in {"claude", "gemini", "opencode"}:
        config = json.loads(content)
        if cli == "opencode":
            configured_args = config["mcp"]["servers"]["ai-guardian"]["command"]
        else:
            configured_args = config["mcpServers"]["ai-guardian"]["args"]
    elif cli in {"codex", "grok"}:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        config = tomllib.loads(content)
        configured_args = config["mcp_servers"]["ai-guardian"]["args"]
    else:
        args_prefix = "const GUARDIAN_BINARY_ARGS: string[] = "
        encoded_args = content.split(args_prefix, 1)[1].split(";", 1)[0]
        configured_args = json.loads(encoded_args)
    assert str(SCRIPT_PATH.resolve()) in configured_args
