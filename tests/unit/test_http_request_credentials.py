"""Synthetic tests for Python HTTP request credential source analysis."""

import builtins
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_guardian.scanners.http_request_credentials import (
    INCOMPLETE_ANALYSIS,
    INLINE_LITERAL,
    MAX_SOURCE_CHARS,
    analyze_http_request_credentials,
    run_http_request_credential_scan,
)

SYNTHETIC_VALUE = "SYNTHETIC_HTTP_SOURCE_CREDENTIAL_VALUE_2717"


@pytest.mark.parametrize(
    ("source", "client", "sink"),
    (
        (
            "import requests\n"
            "requests.get('https://example.invalid', auth=('user', '"
            + SYNTHETIC_VALUE
            + "'))\n",
            "requests",
            "authentication",
        ),
        (
            "import httpx as hx\n"
            "hx.post('https://example.invalid', headers={"
            "'Authorization': 'Bearer " + SYNTHETIC_VALUE + "'})\n",
            "httpx",
            "authorization_header",
        ),
        (
            "from urllib.request import Request\n"
            "Request('https://example.invalid', headers={"
            "'X-API-Key': '" + SYNTHETIC_VALUE + "'})\n",
            "urllib.request",
            "api_key_header",
        ),
        (
            "import requests\n"
            "requests.get('https://demo:" + SYNTHETIC_VALUE + "@example.invalid/')\n",
            "requests",
            "url_userinfo",
        ),
        (
            "import httpx\n"
            "httpx.get(url, headers={'Authorization': b'Bearer "
            + SYNTHETIC_VALUE
            + "'})\n",
            "httpx",
            "authorization_header",
        ),
        (
            "import requests\n"
            "requests.get(url, headers={'Cookie': 'session="
            + SYNTHETIC_VALUE
            + "'})\n",
            "requests",
            "cookie_header",
        ),
        (
            "import aiohttp\n"
            "async def send():\n"
            "    session = aiohttp.ClientSession()\n"
            "    await session.post('https://example.invalid', json={"
            "'password': '" + SYNTHETIC_VALUE + "'})\n",
            "aiohttp",
            "password_field",
        ),
    ),
)
def test_supported_http_clients_detect_inline_credentials(source, client, sink):
    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.client == client
    assert finding.sink == sink
    assert finding.finding_class == INLINE_LITERAL
    assert finding.line_number is not None
    assert SYNTHETIC_VALUE not in repr(result)


def test_same_scope_assignments_and_aliases_flow_to_request_sinks():
    source = (
        "import requests as rq\n"
        "def send():\n"
        "    token = '" + SYNTHETIC_VALUE + "'\n"
        "    auth = ('service-user', token)\n"
        "    headers = {'Authorization': 'Bearer ' + token}\n"
        "    rq.post('https://example.invalid', auth=auth, headers=headers)\n"
    )

    result = analyze_http_request_credentials(source)

    assert {finding.sink for finding in result.findings} == {
        "authentication",
        "authorization_header",
    }
    assert all(finding.client == "requests" for finding in result.findings)
    assert all(finding.finding_class == INLINE_LITERAL for finding in result.findings)


def test_client_instance_and_basic_auth_assignment_are_supported():
    source = (
        "import httpx\n"
        "client = httpx.Client()\n"
        "client.auth = httpx.BasicAuth('user', '" + SYNTHETIC_VALUE + "')\n"
        "client.get('https://example.invalid')\n"
    )

    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].client == "httpx"
    assert result.findings[0].sink == "authentication"


def test_basic_auth_object_assigned_before_request_keeps_literal_password_flow():
    source = (
        "import requests\n"
        "from requests.auth import HTTPBasicAuth\n"
        "authorization = HTTPBasicAuth('service-user', '" + SYNTHETIC_VALUE + "')\n"
        "requests.get('https://example.invalid', auth=authorization)\n"
    )

    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].sink == "authentication"


@pytest.mark.parametrize(
    "mutation",
    (
        "client.headers.update({'Authorization': 'Bearer " + SYNTHETIC_VALUE + "'})\n",
        "client.headers['Authorization'] = 'Bearer " + SYNTHETIC_VALUE + "'\n",
    ),
)
def test_client_header_mutation_flows_into_later_requests(mutation):
    source = (
        "import requests\n"
        "client = requests.Session()\n"
        + mutation
        + "client.get('https://example.invalid')\n"
    )

    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].client == "requests"
    assert result.findings[0].sink == "authorization_header"


def test_urllib_module_alias_and_request_body_credential_field_are_supported():
    source = (
        "import urllib.request as urlrequest\n"
        "payload = {'metadata': {'access_token': '" + SYNTHETIC_VALUE + "'}}\n"
        "urlrequest.Request('https://example.invalid', data=payload)\n"
    )

    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].client == "urllib.request"
    assert result.findings[0].sink == "token_field"


def test_url_userinfo_flows_through_assignment_to_request_constructor():
    source = (
        "from urllib.request import Request\n"
        "endpoint = 'https://demo:" + SYNTHETIC_VALUE + "@example.invalid/'\n"
        "Request(endpoint)\n"
    )

    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].client == "urllib.request"
    assert result.findings[0].sink == "url_userinfo"


def test_credential_named_url_query_parameter_is_detected_but_ordinary_query_is_safe():
    source = (
        "import requests\n"
        "endpoint = 'https://example.invalid/?access_token="
        + SYNTHETIC_VALUE
        + "&debug=verbose'\n"
        "requests.get(endpoint)\n"
    )

    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].sink == "token_field"


def test_camel_case_credential_field_is_normalized_and_detected():
    source = (
        "import requests\n"
        "requests.post(url, json={'accessToken': '" + SYNTHETIC_VALUE + "'})\n"
    )

    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].sink == "token_field"


@pytest.mark.parametrize(
    "source",
    (
        "import urllib.request as web\n"
        "web.urlopen('https://user:" + SYNTHETIC_VALUE + "@example.invalid/')\n",
        "from urllib.request import urlopen as open_url\n"
        "open_url('https://user:" + SYNTHETIC_VALUE + "@example.invalid/')\n",
    ),
)
def test_urllib_urlopen_userinfo_is_detected_for_module_and_function_imports(source):
    result = analyze_http_request_credentials(source)

    assert len(result.findings) == 1
    assert result.findings[0].client == "urllib.request"
    assert result.findings[0].sink == "url_userinfo"


@pytest.mark.parametrize(
    "source",
    (
        "import requests\n"
        "requests.get('https://example.invalid/?debug=" + SYNTHETIC_VALUE + "')\n",
        "import requests\n"
        "requests.get('https://example.invalid/?api_key=YOUR_TOKEN')\n",
        "import requests\n"
        "requests.get('https://example.invalid/', headers={"
        "'Authorization': '${SMOKE_HTTP_TOKEN}'})\n",
    ),
)
def test_ordinary_or_placeholder_url_query_is_not_reported(source):
    assert analyze_http_request_credentials(source).findings == ()


@pytest.mark.parametrize(
    "source",
    (
        "import requests\nrequests.get(url, auth=('user', os.environ['TOKEN']))\n",
        "import httpx\nhttpx.post(url, headers={'Authorization': os.getenv('TOKEN')})\n",
        "import aiohttp\n"
        "aiohttp.request('POST', url, json={'password': getpass.getpass()})\n",
        "import requests\n"
        "requests.post(url, json={'note': '" + SYNTHETIC_VALUE + "'})\n",
        "import httpx\n"
        "httpx.get(url, headers={'X-Trace-Id': '" + SYNTHETIC_VALUE + "'})\n",
        "import requests\nrequests.get(url, auth=('user', '<password>'))\n",
        "import requests\nrequests.post(url, json={'token': 'YOUR_TOKEN'})\n",
    ),
)
def test_references_placeholders_and_ordinary_request_data_are_not_blocked(source):
    assert analyze_http_request_credentials(source).findings == ()


def test_interprocedural_helper_values_are_outside_the_dataflow_boundary():
    source = (
        "import requests\n"
        "def provide_password():\n"
        "    return '" + SYNTHETIC_VALUE + "'\n"
        "requests.get(url, auth=('user', provide_password()))\n"
    )

    assert analyze_http_request_credentials(source).findings == ()


def test_parse_failure_is_incomplete_only_for_recognized_request_code():
    relevant = (
        "import requests\n" "requests.post(url, json={'password': '" + SYNTHETIC_VALUE
    )
    unrelated = "def ordinary_python(:\n    return 1\n"

    analysis = analyze_http_request_credentials(relevant)

    assert analysis.incomplete is True
    assert analysis.findings[0].finding_class == INCOMPLETE_ANALYSIS
    assert analyze_http_request_credentials(unrelated).findings == ()
    assert SYNTHETIC_VALUE not in repr(analysis)


def test_source_and_ast_limits_report_value_free_incomplete_analysis():
    source = (
        "import requests\n"
        "requests.post(url, json={'password': '" + SYNTHETIC_VALUE + "'})\n"
    )
    oversized = source + ("# padding\n" * 20_000)

    result = run_http_request_credential_scan(
        oversized, file_path="generated.py", config={}
    )

    assert result is not None and result.should_block
    assert result.extra["analysis_incomplete"] is True
    assert SYNTHETIC_VALUE not in repr(result)


def test_oversized_source_with_relevant_sink_after_analysis_limit_is_incomplete():
    padding_line = "# harmless padding\n"
    padding = padding_line * (MAX_SOURCE_CHARS // len(padding_line) + 1)
    source = (
        padding
        + "import requests\n"
        + "requests.get(url, auth=('user', '"
        + SYNTHETIC_VALUE
        + "'))\n"
    )

    analysis = analyze_http_request_credentials(source)

    assert len(source) > MAX_SOURCE_CHARS
    assert analysis.incomplete
    assert analysis.findings[0].finding_class == INCOMPLETE_ANALYSIS


def test_action_policy_and_disabled_scanner():
    source = (
        "import requests\n"
        "requests.get(url, auth=('user', '" + SYNTHETIC_VALUE + "'))\n"
    )
    assert run_http_request_credential_scan(
        source, file_path="generated.py", config={"action": "block"}
    ).should_block
    assert not run_http_request_credential_scan(
        source, file_path="generated.py", config={"action": "warn"}
    ).should_block
    assert (
        run_http_request_credential_scan(
            source, file_path="generated.py", config={"action": "log-only"}
        ).error_message
        == ""
    )
    assert run_http_request_credential_scan(
        source, file_path="generated.py", config={"action": "ask"}
    ).should_block
    assert (
        run_http_request_credential_scan(
            source, file_path="generated.py", config={"enabled": False}
        )
        is None
    )
    assert (
        run_http_request_credential_scan(source, file_path="generated.js", config={})
        is None
    )


def test_scan_result_and_blocked_record_contain_no_source_or_credential_values():
    source = (
        "import requests\n"
        "requests.post(url, headers={'Authorization': 'Bearer "
        + SYNTHETIC_VALUE
        + "'})\n"
    )
    result = run_http_request_credential_scan(
        source, file_path="generated.py", config={}
    )

    assert result is not None
    assert result.matched_text == ""
    assert result.matched_pattern == ""
    assert SYNTHETIC_VALUE not in repr(result)
    assert SYNTHETIC_VALUE not in result.error_message
    blocked = result.to_blocked_dict()
    assert SYNTHETIC_VALUE not in repr(blocked)
    assert all("snippet" not in key for key in blocked)


def test_ask_approval_is_private_and_operation_scoped():
    from ai_guardian.ask_mode import _format_ask_info_message, _handle_ask_mode_auto
    from ai_guardian.scanners.post_scan_filters import (
        PostScanContext,
        apply_post_scan_pipeline,
    )
    from ai_guardian.scanners.scanner_registry import (
        ScannerName,
        get_default_registry,
    )
    from ai_guardian.ui.ask_dialog import AskDecision, AskResult

    source = (
        "import requests\n"
        "requests.post(url, headers={'Authorization': 'Bearer "
        + SYNTHETIC_VALUE
        + "'})\n"
    )
    result = run_http_request_credential_scan(
        source,
        file_path="client.py",
        config={"enabled": True, "action": "ask"},
    )
    audit = MagicMock()
    with patch(
        "ai_guardian.ui.ask_dialog.show_ask_dialog",
        return_value=AskResult(AskDecision.ALLOW_ONCE),
    ) as dialog:
        decision = apply_post_scan_pipeline(
            get_default_registry().get(ScannerName.HTTP_REQUEST_CREDENTIAL_SCANNING),
            result,
            PostScanContext(
                handle_ask_mode_auto=_handle_ask_mode_auto,
                log_ask_decision=MagicMock(),
                format_ask_info_message=_format_ask_info_message,
                hook_event="PreToolUse",
                violation_logger=audit,
            ),
        )

    assert not decision.should_block
    info = dialog.call_args.args[0]
    assert info.decision_only
    assert info.config_section == "http_request_credential_scanning"
    assert info.matched_text == ""
    assert SYNTHETIC_VALUE not in repr(info)
    assert SYNTHETIC_VALUE not in repr(audit.log_violation.call_args)


def test_persisted_violation_record_omits_source_and_credential_values(tmp_path):
    from ai_guardian.violations.log_violation import ScanContext, log_violation
    from ai_guardian.violations.logger import ViolationLogger

    source = (
        "import requests\n"
        "requests.get(url, auth=('service-user', '" + SYNTHETIC_VALUE + "'))\n"
    )
    result = run_http_request_credential_scan(
        source, file_path="client.py", config={"enabled": True, "action": "block"}
    )
    path = tmp_path / "violations.jsonl"
    logger = ViolationLogger(
        log_path=path,
        config={
            "enabled": True,
            "log_types": [],
            "max_entries": 100,
            "retention_days": 30,
        },
    )
    context = ScanContext(
        tool_name="Write",
        project_path=str(tmp_path),
        allowlist_content=source,
        allowlist_sensitive_values=[SYNTHETIC_VALUE],
        allowlist_context={"candidate": SYNTHETIC_VALUE},
    )
    log_violation(
        result,
        context,
        violation_logger=logger,
        blocked_overrides={"matched_text": SYNTHETIC_VALUE},
        context_overrides={"raw_source": source},
        suggestion={"example": SYNTHETIC_VALUE},
        source=source,
        allowlist_context={"candidate": SYNTHETIC_VALUE},
    )

    serialized = path.read_text(encoding="utf-8")
    assert SYNTHETIC_VALUE not in serialized
    assert source not in serialized
    stored = json.loads(serialized)
    assert stored["blocked"]["findings"][0]["sink"] == "authentication"
    assert stored["suggestion"] == {}
    assert "tool_name" not in stored["context"]


def test_violations_console_never_renders_source_credential_text():
    pytest.importorskip("nicegui", reason="NiceGUI is required by web components")
    from ai_guardian.web.pages.violations import (
        DETAIL_FIELDS,
        _extract_matched_from_violation,
    )

    violation = {
        "violation_type": "http_request_credential_detected",
        "blocked": {
            "matched_text": SYNTHETIC_VALUE,
            "context_snippet": SYNTHETIC_VALUE,
            "reason": "Hard-coded HTTP request credential detected; source values withheld.",
        },
    }
    assert _extract_matched_from_violation(violation) == ""
    assert DETAIL_FIELDS["http_request_credential_detected"] == [
        ("File", "file_path"),
        ("Line", "line_number"),
        ("Action", "action"),
        ("Findings", "total_findings"),
        ("Reason", "reason"),
    ]


def test_analyzer_never_imports_or_executes_analyzed_source(monkeypatch):
    source = (
        "import requests\n"
        "requests.post('https://example.invalid', json={'token': '"
        + SYNTHETIC_VALUE
        + "'})\n"
    )
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "requests":
            raise AssertionError("analyzed source was imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = run_http_request_credential_scan(
        source, file_path="generated.py", config={}
    )

    assert result is not None and result.should_block


def test_config_defaults_schema_profiles_and_global_only_scope():
    from ai_guardian.config.loaders import _load_http_request_credential_scanning_config
    from ai_guardian.config.utils import GLOBAL_ONLY_SECTIONS, get_feature_flags
    from ai_guardian.setup.config import _get_default_config_template

    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "src/ai_guardian/schemas/ai-guardian-config.schema.json").read_text(
            encoding="utf-8"
        )
    )
    config = _get_default_config_template()["http_request_credential_scanning"]
    assert {
        key: value for key, value in config.items() if not key.startswith("_comment_")
    } == {"enabled": True, "action": "block"}
    assert "http_request_credential_scanning" in GLOBAL_ONLY_SECTIONS
    assert get_feature_flags({})["http_request_credential_scanning"] is True
    assert (
        schema["properties"]["http_request_credential_scanning"]["properties"][
            "action"
        ]["default"]
        == "block"
    )
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate({"http_request_credential_scanning": config}, schema)

    def runtime_settings(section):
        return {
            key: value
            for key, value in section.items()
            if not key.startswith("_comment_")
        }

    for profile in ("minimal", "standard", "strict", "moderator"):
        profile_config = json.loads(
            (root / "src/ai_guardian/templates/profiles" / f"{profile}.json").read_text(
                encoding="utf-8"
            )
        )
        assert runtime_settings(profile_config["http_request_credential_scanning"]) == {
            "enabled": True,
            "action": "block",
        }
    example = json.loads(
        (root / "ai-guardian-example.json").read_text(encoding="utf-8")
    )
    assert runtime_settings(example["http_request_credential_scanning"]) == {
        "enabled": True,
        "action": "block",
    }

    with patch(
        "ai_guardian.config.loaders._load_config_file", return_value=(None, None)
    ):
        assert _load_http_request_credential_scanning_config()[0] == {
            "enabled": True,
            "action": "block",
        }


@pytest.mark.parametrize("tool_name", ("Write", "Edit"))
def test_pretool_hook_denies_python_write_with_http_credential(tool_name):
    from ai_guardian.hook_processing import process_hook_data
    from tests.fixtures.mock_mcp_server import create_hook_data

    source = (
        "import requests\n"
        "requests.post(url, headers={'Authorization': 'Bearer "
        + SYNTHETIC_VALUE
        + "'})\n"
    )
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
            return_value=({"enabled": True, "action": "block"}, None),
        ),
    ):
        response = process_hook_data(hook_data)

    output = response["output"]
    parsed = json.loads(output)
    assert parsed["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "HTTP request credential" in parsed["systemMessage"]
    assert SYNTHETIC_VALUE not in output


def test_console_http_scanner_policy_save_preserves_sibling_settings(monkeypatch):
    pytest.importorskip("nicegui", reason="NiceGUI is required by web components")
    from ai_guardian.web.pages import secrets

    saved = {}
    monkeypatch.setattr(secrets, "is_web_config_read_only", lambda: False)
    monkeypatch.setattr(
        secrets,
        "load_web_config_global",
        lambda: {"unrelated": {"enabled": True}},
    )

    def save(config, *, scope):
        saved["config"] = config
        saved["scope"] = scope
        return True

    monkeypatch.setattr(secrets, "save_web_config", save)
    assert secrets._save_http_request_credential_setting("action", "warn")
    assert saved["scope"] == "global"
    assert saved["config"]["unrelated"] == {"enabled": True}
    assert saved["config"]["http_request_credential_scanning"] == {"action": "warn"}
    assert not secrets._save_http_request_credential_setting("action", "ignore")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value", "success"), [("enabled", False, True), ("action", "warn", False)]
)
async def test_console_http_scanner_controls_autosave_human_changes(
    key, value, success
):
    pytest.importorskip("nicegui", reason="NiceGUI is required by web components")
    from ai_guardian.web.pages import secrets

    ui = MagicMock()
    save = MagicMock()
    io = AsyncMock(return_value=success)
    with (
        patch.object(secrets, "ui", ui),
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "add_help_button"),
        patch.object(secrets, "field_help_icon"),
        patch.object(secrets, "_save_http_request_credential_setting", save),
        patch.object(secrets.run, "io_bound", io),
    ):
        secrets._render_http_request_credential_scanning({})
        io.assert_not_awaited()
        widget = (
            ui.checkbox.return_value if key == "enabled" else ui.select.return_value
        )
        await widget.on_value_change.call_args.args[0](SimpleNamespace(value=value))
    io.assert_awaited_once_with(save, key, value)
    ui.notify.assert_called_once_with(
        (
            "Global HTTP request credential settings saved"
            if success
            else "Could not save global HTTP request credential settings"
        ),
        type="positive" if success else "negative",
    )
