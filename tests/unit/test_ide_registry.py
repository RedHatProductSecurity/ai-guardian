"""Parity and coverage-contract tests for supported IDE integrations."""

import json
import re
from pathlib import Path

import pytest

from ai_guardian.constants import HookEvent
from ai_guardian.hook_adapters import (
    ADAPTERS_BY_IDE_TYPE,
    _ENV_ALIAS_MAP,
)
from ai_guardian.hook_adapters.base import NormalizedHookInput
from ai_guardian.ide_registry import (
    ALL_IDE_TYPES,
    SUPPORTED_IDE_REGISTRY,
    SUPPORTED_IDE_TYPES,
)
from ai_guardian.scanners.transcript import TRANSCRIPT_ADAPTERS
from ai_guardian.sessions.adapters import SESSION_ADAPTERS
from ai_guardian.setup import (
    _MCP_IDE_CONFIGS,
    _RULES_IDE_CONFIGS,
    get_mcp_config_path,
)
from ai_guardian.setup.hooks import IDESetup

ROOT = Path(__file__).resolve().parents[2]


def _release_readiness_setup_ids() -> tuple:
    workflow = (ROOT / ".github" / "workflows" / "release-readiness.yml").read_text()
    ide_job_header = "  " + "ide-hook-e2e:"
    setup_section = workflow.split(ide_job_header, 1)[0]
    match = re.search(r'\bIDES="([^"]+)"', setup_section)
    assert match, "release-readiness setup list is missing"
    return tuple(match.group(1).split())


def _release_readiness_e2e_ids() -> tuple:
    workflow = (ROOT / ".github" / "workflows" / "release-readiness.yml").read_text()
    ide_job_header = "  " + "ide-hook-e2e:"
    matrix_section = workflow.split(ide_job_header, 1)[1].split("\n    steps:", 1)[0]
    matrix_section = matrix_section.split("        ide:\n", 1)[1]
    return tuple(re.findall(r"^\s+- ([a-z0-9-]+)$", matrix_section, re.MULTILINE))


def test_canonical_registry_is_unique_and_complete():
    keys = tuple(integration.key for integration in SUPPORTED_IDE_REGISTRY)

    assert keys == SUPPORTED_IDE_TYPES
    assert len(keys) == len(set(keys))
    assert set(keys).issubset(ALL_IDE_TYPES)


def test_setup_registry_matches_canonical_registry():
    assert set(IDESetup.IDE_CONFIGS) == set(ALL_IDE_TYPES)

    for integration in SUPPORTED_IDE_REGISTRY:
        config = IDESetup.IDE_CONFIGS[integration.key]
        assert config["name"] == integration.display_name
        if integration.setup_mode == "script-hooks":
            assert config.get("script_based") is True
        elif integration.setup_mode == "mcp-only":
            assert config.get("mcp_only") is True
        elif integration.setup_mode == "plugin":
            assert config.get("plugin_file") is True
        elif integration.setup_mode == "extension":
            assert config.get("extension_based") is True
        else:
            assert config.get("hooks") is not None


def test_adapter_aliases_and_classes_match_canonical_registry():
    for integration in SUPPORTED_IDE_REGISTRY:
        adapter_class = ADAPTERS_BY_IDE_TYPE[integration.key]
        assert adapter_class.__name__ == integration.adapter_class
        for alias in integration.adapter_aliases:
            assert _ENV_ALIAS_MAP[alias] is adapter_class


def test_mcp_and_rules_registries_match_canonical_capabilities():
    assert set(_MCP_IDE_CONFIGS) == set(SUPPORTED_IDE_TYPES)

    expected_rules = {
        integration.key
        for integration in SUPPORTED_IDE_REGISTRY
        if integration.rules_supported
    }
    assert set(_RULES_IDE_CONFIGS) == expected_rules


def test_managed_events_have_an_e2e_case_for_every_hook_surface():
    valid_cases = {"allow", "block", "post"}

    for integration in SUPPORTED_IDE_REGISTRY:
        cases = integration.e2e_events
        assert set(cases) == set(integration.managed_hook_events), integration.key
        for event_name, event_cases in cases.items():
            assert event_cases, f"{integration.key}/{event_name} has no E2E case"
            assert set(event_cases).issubset(valid_cases)

        if integration.supports_hooks and integration.setup_mode in {
            "command-hooks",
            "script-hooks",
        }:
            assert cases, f"{integration.key} has hooks but no event plan"


def test_transcript_and_session_capabilities_have_registered_implementations():
    transcript_names = {adapter.name for adapter in TRANSCRIPT_ADAPTERS}
    format_to_adapter = {
        "JSONL": "JSONL",
        "JSONL (explicit path)": "JSONL",
        "Cursor SQLite": "Cursor IDE",
        "Copilot Chat delta journal": "GitHub Copilot",
        "Cline JSON array": "Cline",
        "Kiro JSONL": "Kiro",
        "Windsurf JSONL": "Windsurf",
        "AiderDesk Markdown": "AiderDesk",
        "OpenClaw JSONL": "OpenClaw",
        "OpenCode SQLite": "OpenCode",
    }

    for integration in SUPPORTED_IDE_REGISTRY:
        for transcript_format in integration.transcript_formats:
            assert transcript_format in format_to_adapter, transcript_format
            assert format_to_adapter[transcript_format] in transcript_names

        if integration.session_support == "browser":
            assert integration.key in SESSION_ADAPTERS
        elif integration.session_support.startswith("shared:"):
            shared_key = integration.session_support.split(":", 1)[1]
            assert shared_key in SESSION_ADAPTERS


def test_release_readiness_matrices_match_canonical_registry():
    assert _release_readiness_setup_ids() == SUPPORTED_IDE_TYPES
    assert _release_readiness_e2e_ids() == SUPPORTED_IDE_TYPES


def test_installers_and_support_docs_mention_every_supported_ide():
    installer_text = (ROOT / "install.sh").read_text() + (
        ROOT / "install.ps1"
    ).read_text()
    support_text = (ROOT / "docs" / "AGENT_SUPPORT.md").read_text()
    checklist_text = (ROOT / "docs" / "IDE_INTEGRATION_CHECKLIST.md").read_text()

    for ide_type in SUPPORTED_IDE_TYPES:
        assert ide_type in installer_text
        assert ide_type in support_text
        assert ide_type in checklist_text


def test_explicit_cursor_project_scope_uses_selected_workspace(tmp_path):
    """A parent .cursor directory cannot redirect an explicit project target."""
    parent_cursor = tmp_path / ".cursor"
    parent_cursor.mkdir()
    project = tmp_path / "workspace"
    project.mkdir()

    setup = IDESetup()
    assert setup.get_config_path(
        "cursor", scope="project", project_dir=str(project)
    ) == str(project / ".cursor" / "hooks.json")
    assert (
        get_mcp_config_path("cursor", scope="project", project_dir=str(project))
        == project / ".cursor" / "mcp.json"
    )


@pytest.mark.parametrize("ide_type", SUPPORTED_IDE_TYPES)
def test_registered_adapters_handle_malformed_payloads(ide_type):
    """Every registered hook/bridge adapter must fail safely on bad fields."""
    integration = next(item for item in SUPPORTED_IDE_REGISTRY if item.key == ide_type)
    adapter = ADAPTERS_BY_IDE_TYPE[ide_type]()
    payload = {
        "hook_event_name": "not-a-real-event",
        "tool_input": "not-json",
        "tool_response": ["unexpected", {"shape": "value"}],
        "tool_name": 7,
        "cwd": 7,
    }

    normalized = adapter.normalize_input(payload)

    assert isinstance(normalized, NormalizedHookInput), ide_type
    assert isinstance(normalized.tool_input, dict), ide_type
    assert normalized.raw_data is payload
    if integration.setup_mode == "mcp-only":
        assert normalized.event == HookEvent.PROMPT


def _assert_response_contract(response, ide_type):
    assert set(("output", "exit_code")).issubset(response), ide_type
    assert isinstance(response["exit_code"], int), ide_type
    assert response["exit_code"] in {0, 1, 2}, ide_type


@pytest.mark.parametrize("ide_type", SUPPORTED_IDE_TYPES)
def test_registered_hook_adapters_cover_response_contract(ide_type):
    """Exercise allow, block, warning, and output-transform paths per adapter."""
    integration = next(item for item in SUPPORTED_IDE_REGISTRY if item.key == ide_type)
    adapter = ADAPTERS_BY_IDE_TYPE[ide_type]()
    if integration.setup_mode == "mcp-only":
        response = adapter.format_response(
            has_secrets=True,
            error_message="synthetic block",
            hook_event=HookEvent.PRE_TOOL_USE,
            violation_type="directory_blocking",
        )
        _assert_response_contract(response, ide_type)
        assert response["output"] is None
        return

    responses = (
        adapter.format_response(
            has_secrets=False,
            hook_event=HookEvent.PRE_TOOL_USE,
        ),
        adapter.format_response(
            has_secrets=True,
            error_message="synthetic block",
            hook_event=HookEvent.PRE_TOOL_USE,
            violation_type="directory_blocking",
        ),
        adapter.format_response(
            has_secrets=False,
            warning_message="synthetic warning",
            hook_event=HookEvent.PRE_TOOL_USE,
            violation_type="directory_blocking",
        ),
        adapter.format_response(
            has_secrets=False,
            hook_event=HookEvent.POST_TOOL_USE,
            modified_output="synthetic-redacted-output",
            tool_name="Bash",
        ),
    )

    for response in responses:
        _assert_response_contract(response, ide_type)

    blocked = responses[1]
    assert blocked.get("_blocked") is True, ide_type
    assert "synthetic-redacted-output" in str(responses[-1]), ide_type
    if isinstance(responses[0]["output"], str):
        json.loads(responses[0]["output"])
