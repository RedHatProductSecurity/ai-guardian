"""UX contracts for source-only HTTP request credential enforcement."""

import json
from unittest.mock import patch

import pytest

from ai_guardian.hook_processing import process_hook_data
from tests.fixtures.mock_mcp_server import create_hook_data

SYNTHETIC_CREDENTIAL = "SYNTHETIC_HTTP_UX_CREDENTIAL_VALUE_2717"


def _source():
    return (
        "import requests\n"
        "requests.post(url, headers={'Authorization': 'Bearer "
        + SYNTHETIC_CREDENTIAL
        + "'})\n"
    )


def _run_write(tool_name, action):
    source = _source()
    tool_input = (
        {"file_path": "client.py", "content": source}
        if tool_name == "Write"
        else {
            "file_path": "client.py",
            "old_string": "old_call()",
            "new_string": source,
        }
    )
    hook_data = create_hook_data(tool_name=tool_name, tool_input=tool_input)
    with (
        patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=({}, None),
        ),
        patch(
            "ai_guardian.config.loaders._load_http_request_credential_scanning_config",
            return_value=({"enabled": True, "action": action}, None),
        ),
    ):
        response = process_hook_data(hook_data)
    return json.loads(response["output"])


@pytest.mark.parametrize("tool_name", ("Write", "Edit"))
def test_hard_coded_http_credential_denies_source_write_without_echo(tool_name):
    """USER EXPERIENCE: source credential flow → deny before applying the write.

    Scenario:
    1. The agent proposes a Python Write or Edit containing an Authorization value.
    2. The PreToolUse hook parses the proposed source without executing it.
    3. The scanner finds a literal flowing into a supported HTTP request header.

    Expected User Experience:
    ❌ The write is denied before the tool applies it.
    🛡️ User sees a fixed message that says the source value is withheld.
    🔒 Neither the response nor its security message contains the credential.

    Manual verification: use a disposable Python file and a synthetic value with
    a supported native Write/Edit tool; confirm the denial and absence of the
    literal in the hook response and violation details.
    """
    response = _run_write(tool_name, "block")

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["systemMessage"] == (
        "Hard-coded HTTP request credential detected in Python source; the write "
        "was blocked. Credential values and source snippets are withheld."
    )
    assert SYNTHETIC_CREDENTIAL not in json.dumps(response)


def test_opencode_native_write_is_normalized_and_scanned_before_apply():
    hook_data = create_hook_data(tool_name="Write", tool_input={})
    hook_data.update(
        {
            "hook_source": "opencode",
            "opencode_version": "2.0.24",
            "hook_event_name": "tool.execute.before",
            "tool_name": "write",
            "tool_use": {
                "name": "write",
                "input": {"filePath": "client.py", "content": _source()},
            },
        }
    )
    with (
        patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=({}, None),
        ),
        patch(
            "ai_guardian.config.loaders._load_http_request_credential_scanning_config",
            return_value=({"enabled": True, "action": "block"}, None),
        ),
    ):
        response = json.loads(process_hook_data(hook_data)["output"])

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert SYNTHETIC_CREDENTIAL not in json.dumps(response)


def test_warn_action_allows_write_with_value_free_warning():
    """USER EXPERIENCE: warn policy surfaces the finding without denying the write."""
    response = _run_write("Write", "warn")

    assert "hookSpecificOutput" not in response or (
        "permissionDecision" not in response["hookSpecificOutput"]
    )
    assert "Hard-coded HTTP request credential detected" in response["systemMessage"]
    assert "configured warn action allows this write" in response["systemMessage"]
    assert SYNTHETIC_CREDENTIAL not in json.dumps(response)


def test_environment_reference_does_not_override_normal_write_permissions():
    """USER EXPERIENCE: credential references are not classified as inline literals."""
    hook_data = create_hook_data(
        tool_name="Write",
        tool_input={
            "file_path": "client.py",
            "content": (
                "import requests\n"
                "import os\n"
                "requests.post(url, headers={'Authorization': os.environ['API_TOKEN']})\n"
            ),
        },
    )
    with (
        patch(
            "ai_guardian.config.loaders._load_config_file",
            return_value=({}, None),
        ),
        patch(
            "ai_guardian.config.loaders._load_http_request_credential_scanning_config",
            return_value=({"enabled": True, "action": "block"}, None),
        ),
    ):
        response = json.loads(process_hook_data(hook_data)["output"])

    assert "permissionDecision" not in response.get("hookSpecificOutput", {})
    assert "Hard-coded HTTP request credential detected" not in response.get(
        "systemMessage", ""
    )
