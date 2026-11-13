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


def _run_write(tool_name, action, *, file_path="client.py", source=None):
    source = source or _source()
    tool_input = (
        {"file_path": file_path, "content": source}
        if tool_name == "Write"
        else {
            "file_path": file_path,
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
    1. The agent proposes a source Write or Edit containing an Authorization value.
    2. The PreToolUse hook parses the proposed source without executing it.
    3. The scanner finds a literal flowing into a supported HTTP request header.

    Expected User Experience:
    ❌ The write is denied before the tool applies it.
    🛡️ User sees a fixed message that says the source value is withheld.
    🔒 Neither the response nor its security message contains the credential.

    Manual verification: use disposable Python, JavaScript, and TypeScript files
    with synthetic values and a supported native Write/Edit tool; confirm the
    denial and absence of each literal in the hook response and violation details.
    """
    response = _run_write(tool_name, "block")

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["systemMessage"] == (
        "Hard-coded HTTP request credential detected in source code; the write "
        "was blocked. Credential values and source snippets are withheld."
    )
    assert SYNTHETIC_CREDENTIAL not in json.dumps(response)


def test_edit_replacement_is_checked_in_the_prospective_file(tmp_path):
    """USER EXPERIENCE: a value-only Edit is checked with its surrounding source."""
    target = tmp_path / "client.py"
    target.write_text(
        "import requests\n"
        "requests.get(url, auth=('service-user', 'OLD_SYNTHETIC_VALUE'))\n",
        encoding="utf-8",
    )
    hook_data = create_hook_data(
        tool_name="Edit",
        tool_input={
            "file_path": str(target),
            "old_string": "OLD_SYNTHETIC_VALUE",
            "new_string": SYNTHETIC_CREDENTIAL,
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

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["systemMessage"] == (
        "Hard-coded HTTP request credential detected in source code; the write "
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


@pytest.mark.parametrize(
    ("file_path", "source"),
    (
        (
            "client.js",
            "const token = 'SYNTHETIC_JS_HTTP_UX_CREDENTIAL_2722';\n"
            "fetch('/api', { headers: { Authorization: `Bearer ${token}` } });\n",
        ),
        (
            "client.ts",
            "import axios from 'axios';\n"
            "const token: string = 'SYNTHETIC_TS_HTTP_UX_CREDENTIAL_2722';\n"
            "axios.post('/api', { accessToken: token });\n",
        ),
    ),
)
@pytest.mark.parametrize("tool_name", ("Write", "Edit"))
def test_javascript_typescript_inline_credentials_deny_before_write_without_echo(
    file_path, source, tool_name
):
    """USER EXPERIENCE: JavaScript/TypeScript request credential → deny the write.

    Scenario:
    1. The agent proposes JavaScript or TypeScript containing a literal request credential.
    2. The source-only parser finds it in a supported HTTP request sink.
    3. The pre-tool policy denies the supported Write/Edit before application.

    Expected User Experience:
    ❌ The proposed write is denied under the default block action.
    🔒 The hook response is fixed and contains neither source snippets nor values.

    Manual verification: repeat with a disposable `.js` and `.ts` file through a
    supported native Write tool; verify the files were not created.
    """
    response = _run_write(
        tool_name,
        "block",
        file_path=file_path,
        source=source,
    )

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["systemMessage"] == (
        "Hard-coded HTTP request credential detected in source code; the write "
        "was blocked. Credential values and source snippets are withheld."
    )
    assert "SYNTHETIC_" not in json.dumps(response)


@pytest.mark.parametrize("file_path", ("client.js", "client.ts"))
def test_javascript_typescript_environment_reference_is_allowed(file_path):
    """USER EXPERIENCE: environment-backed request value → no scanner denial."""
    source = (
        "const token = process.env.API_TOKEN;\n"
        "fetch('/api', { headers: { Authorization: token } });\n"
    )
    response = _run_write("Write", "block", file_path=file_path, source=source)

    assert "permissionDecision" not in response.get("hookSpecificOutput", {})
    assert "HTTP request credential" not in response.get("systemMessage", "")


def test_javascript_incomplete_relevant_source_follows_default_block_policy():
    """USER EXPERIENCE: relevant unparseable source → report incomplete analysis.

    The hook blocks under the default policy but does not claim that a credential
    was confirmed or return any source text.
    """
    response = _run_write(
        "Write",
        "block",
        file_path="client.js",
        source=(
            "fetch('/api', { headers: { Authorization: "
            "'SYNTHETIC_INCOMPLETE_HTTP_UX_2722' }\n"
        ),
    )

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "analysis is incomplete" in response["systemMessage"]
    assert "SYNTHETIC_" not in json.dumps(response)


def test_javascript_warn_action_allows_write_with_value_free_warning():
    response = _run_write(
        "Write",
        "warn",
        file_path="client.js",
        source=(
            "fetch('/api', { headers: { Authorization: "
            "'SYNTHETIC_WARN_HTTP_UX_2722' } });\n"
        ),
    )

    assert "permissionDecision" not in response.get("hookSpecificOutput", {})
    assert "configured warn action allows this write" in response["systemMessage"]
    assert "SYNTHETIC_" not in json.dumps(response)


def test_javascript_edit_uses_prospective_file_context(tmp_path):
    target = tmp_path / "client.js"
    target.write_text(
        "fetch('/api', { headers: { Authorization: 'OLD_SYNTHETIC' } });\n",
        encoding="utf-8",
    )
    hook_data = create_hook_data(
        tool_name="Edit",
        tool_input={
            "file_path": str(target),
            "old_string": "OLD_SYNTHETIC",
            "new_string": "SYNTHETIC_EDIT_HTTP_UX_2722",
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

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "SYNTHETIC_EDIT_HTTP_UX_2722" not in json.dumps(response)
