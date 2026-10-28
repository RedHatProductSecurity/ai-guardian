"""Isolated policy, pipeline, audit, SDK and static-scan contracts for #2612."""

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ai_guardian.config.utils import deep_merge, get_feature_flags
from ai_guardian.scanners.password_likelihood import (
    MESSAGE,
    run_password_likelihood_scan,
)
from ai_guardian.scanners.pipeline import scan_content
from ai_guardian.scanners.scanner_registry import ScannerName, reset_default_registry
from ai_guardian.violations.log_violation import ScanContext, log_violation
from tests.fixtures.password_likelihood_corpus import TEXT, VALUE, isolated_policy


@pytest.fixture(autouse=True)
def reset_registry():
    reset_default_registry()
    yield
    reset_default_registry()


def test_project_policy_cannot_enable_disable_or_change_mode():
    base = isolated_policy("block")
    for section in ({"enabled": False}, {"action": "warn"}, {"enabled": True}):
        assert deep_merge(base, {"password_likelihood": section}) == base
        assert "password_likelihood" not in deep_merge(
            {}, {"password_likelihood": section}
        )


@pytest.mark.parametrize(
    "config", [{}, {"password_likelihood": None}, {"password_likelihood": False}]
)
def test_sdk_explicit_policy_has_no_implicit_workstation_opt_in(config):
    with patch(
        "ai_guardian.config.loaders._load_password_likelihood_config",
        side_effect=AssertionError("No workstation policy read"),
    ):
        assert (
            scan_content(
                TEXT, config=config, scanner_names={ScannerName.PASSWORD_LIKELIHOOD}
            )
            == []
        )


@pytest.mark.parametrize(
    "engine", ["toml-patterns", "gitleaks", "detect-secrets", "missing-engine"]
)
def test_heuristic_does_not_depend_on_fallback_engine(engine):
    config = isolated_policy("block")
    config["secret_scanning"]["engines"] = [engine]
    results = scan_content(TEXT, config=config)
    assert len(results) == 1 and results[0].should_block
    assert VALUE not in json.dumps(asdict(results[0]))


def test_audit_excludes_raw_values_hints_context_hashes_and_overrides():
    result = run_password_likelihood_scan(TEXT, config={"enabled": True})
    result.matched_text = VALUE  # defensive: legacy hint path must never run
    logger = Mock()
    log_violation(
        result,
        ScanContext(
            allowlist_content=TEXT, allowlist_context={"raw": VALUE}, tool_name=VALUE
        ),
        violation_logger=logger,
        blocked_overrides={"command": TEXT},
        context_overrides={"source_command": TEXT},
        allowlist_context={"snippet": TEXT},
    )
    record = logger.log_violation.call_args.kwargs
    assert VALUE not in json.dumps(record, default=str)
    assert "allowlist_context" not in record
    assert "pattern_hint" not in record["blocked"]
    assert record["blocked"]["findings"][0]["confidence_class"] == "contextual"


def test_sdk_blocks_before_application_continues_and_warns_without_claiming_prevention():
    from ai_guardian.sdk import SecurityViolation, monitor

    with patch("ai_guardian.sdk._DirectSession._register_project_with_daemon"):
        with monitor(config=isolated_policy("block")) as session:
            with pytest.raises(
                SecurityViolation, match="Suspected password-like"
            ) as error:
                session.check_content(TEXT)
            assert VALUE not in str(error.value)
        with monitor(config=isolated_policy("warn")) as session:
            with pytest.warns(UserWarning, match="Suspected password-like"):
                result = session.check_content(TEXT)
            assert result.detected and not result.blocked


def test_static_findings_and_sarif_do_not_contain_candidate_text():
    from ai_guardian.scanners.file_scanner import FileScanner
    from ai_guardian.reporting.sarif import SARIFFormatter

    scanner = FileScanner(config=isolated_policy())
    scanner._check_password_likelihood("notes.txt", TEXT)
    assert len(scanner.findings) == 1
    assert VALUE not in json.dumps(scanner.findings)
    assert scanner.findings[0]["rule_id"] == "PASSWORD-001"
    assert "snippet" not in scanner.findings[0]
    report = SARIFFormatter().create_sarif_report(scanner.findings)
    assert VALUE not in json.dumps(report)
    assert report["runs"][0]["results"][0]["ruleId"] == "PASSWORD-001"


def test_profiles_schema_example_and_status_are_default_off():
    from ai_guardian.setup.config import _get_default_config_template
    import jsonschema

    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "src/ai_guardian/schemas/ai-guardian-config.schema.json").read_text()
    )
    expected = _get_default_config_template()["password_likelihood"]
    assert expected["enabled"] is False and expected["action"] == "ask"
    for path in [
        root / "ai-guardian-example.json",
        *sorted((root / "src/ai_guardian/templates/profiles").glob("*.json")),
    ]:
        config = json.loads(path.read_text())
        assert config["password_likelihood"] == expected
        jsonschema.validate(
            config["password_likelihood"], schema["properties"]["password_likelihood"]
        )
    assert not get_feature_flags({})["password_likelihood"]
    assert get_feature_flags(isolated_policy())["password_likelihood"]


def test_web_save_is_global_preserves_policy_and_reports_failure():
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.web.pages import secrets

    with (
        patch.object(secrets, "load_web_config_global", return_value={"unrelated": 7}),
        patch.object(secrets, "save_web_config", return_value=False) as save,
    ):
        assert secrets._save_password_likelihood_setting("enabled", True) is False
        assert save.call_args.kwargs == {"scope": "global"}
        assert save.call_args.args[0]["unrelated"] == 7
        assert secrets._save_password_likelihood_setting("enabled", "true") is False
        assert save.call_count == 1


def test_shared_sanitizer_batch_and_sdk_policy_replace_all_spans():
    from ai_guardian.scanners.sanitizer import sanitize_text, sanitize_text_batch
    from ai_guardian.sdk import monitor

    text = TEXT + "\n" + VALUE
    policy = {"enabled": True, "action": "warn"}
    result = sanitize_text(text, password_config=policy, no_pii=True, no_threats=True)
    assert VALUE not in json.dumps(result)
    assert (
        VALUE[:4] not in result["sanitized_text"]
        and VALUE[-4:] not in result["sanitized_text"]
    )
    assert VALUE not in repr(sanitize_text_batch([text, TEXT], password_config=policy))
    with patch("ai_guardian.sdk._DirectSession._register_project_with_daemon"):
        with monitor(config=isolated_policy()) as session:
            assert VALUE not in json.dumps(session.sanitize(text))


def test_audit_failures_withhold_exception_details(caplog):
    result = run_password_likelihood_scan(TEXT, config={"enabled": True})
    logger = Mock()
    logger.log_violation.side_effect = ValueError(TEXT)
    log_violation(result, ScanContext(), violation_logger=logger)
    assert "Failed to persist suspected-password violation" in caplog.text
    assert VALUE not in caplog.text


def test_sdk_reports_incomplete_warning_without_claiming_detection():
    from ai_guardian.sdk import monitor
    from ai_guardian.scanners.password_likelihood import MAX_INPUT_CHARS

    with patch("ai_guardian.sdk._DirectSession._register_project_with_daemon"):
        with monitor(config=isolated_policy()) as session:
            with pytest.warns(UserWarning, match="analysis incomplete"):
                result = session.check_content("x" * (MAX_INPUT_CHARS + 1))
            assert not result.detected and not result.blocked


def test_persisted_and_retrieved_audit_is_safe(tmp_path):
    from ai_guardian.violations.logger import ViolationLogger

    audit_path = tmp_path / "violations.jsonl"
    audit = ViolationLogger(log_path=audit_path, config={"enabled": True})
    result = run_password_likelihood_scan(TEXT, config={"enabled": True})
    log_violation(result, ScanContext(allowlist_content=TEXT), violation_logger=audit)
    records = audit.get_recent_violations(violation_type="suspected_password")
    assert len(records) == 1
    for serialized in (audit_path.read_text(), json.dumps(records)):
        assert VALUE not in serialized and VALUE[:4] not in serialized
        assert (
            "allowlist_context" not in serialized and "pattern_hint" not in serialized
        )


def test_persistence_failure_withholds_exception_text_in_real_logger(tmp_path, caplog):
    from ai_guardian.violations.logger import ViolationLogger

    audit = ViolationLogger(
        log_path=tmp_path / "violations.jsonl", config={"enabled": True}
    )
    result = run_password_likelihood_scan(TEXT, config={"enabled": True})
    with patch("builtins.open", side_effect=OSError(TEXT)):
        log_violation(result, ScanContext(), violation_logger=audit)
    assert VALUE not in caplog.text
    assert "Failed to persist suspected-password violation" in caplog.text


def test_warning_cannot_downgrade_a_stronger_credential_detection():
    from ai_guardian.scanners.scan_result import ScanResult

    strong = ScanResult(
        detected=True, violation_type="secret_detected", should_block=True
    )
    with patch("ai_guardian.hook_events.scanners.run_secret_scan", return_value=strong):
        results = scan_content(TEXT, config=isolated_policy())
    assert results[0] is strong and results[0].should_block
    assert results[1].violation_type == "suspected_password"
    assert not results[1].should_block


def test_web_read_only_policy_does_not_save():
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from ai_guardian.web.pages import secrets

    with (
        patch.object(secrets, "is_web_config_read_only", return_value=True),
        patch.object(secrets, "save_web_config") as save,
    ):
        assert secrets._save_password_likelihood_setting("enabled", True) is False
    save.assert_not_called()


def test_registry_failure_is_generic_and_respects_explicit_block_policy(caplog):
    from ai_guardian.scanners.scanner_registry import get_default_registry

    registry = get_default_registry()
    entry = registry.get(ScannerName.PASSWORD_LIKELIHOOD)
    with patch.object(entry, "run_fn", side_effect=ValueError(TEXT)):
        results = scan_content(TEXT, config=isolated_policy("block"), registry=registry)
    assert len(results) == 1 and results[0].should_block and not results[0].detected
    assert VALUE not in caplog.text + repr(results)


def test_read_file_location_survives_the_independent_pipeline():
    (result,) = scan_content(TEXT, config=isolated_policy(), file_path="notes.txt")
    assert result.file_path == "notes.txt"
    assert result.to_blocked_dict()["file_path"] == "notes.txt"


def test_experimental_static_rule_routes_to_existing_secrets_page():
    from ai_guardian.constants import (
        RULE_ID_TO_SLUG,
        RULE_ID_TO_CONFIG_SECTION,
        RULE_ID_TO_VIOLATION_TYPE,
    )

    assert RULE_ID_TO_SLUG["PASSWORD-001"] == "/secrets"
    assert RULE_ID_TO_CONFIG_SECTION["PASSWORD-001"] == "password_likelihood"
    assert RULE_ID_TO_VIOLATION_TYPE["PASSWORD-001"] == "suspected_password"


@pytest.mark.parametrize("read_only", [False, True])
def test_web_controls_autosave_only_on_change_and_preserve_read_only(read_only):
    pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
    from unittest.mock import MagicMock
    from ai_guardian.web.pages import secrets, violation_logging

    ui = MagicMock()
    with (
        patch.object(secrets, "ui", ui),
        patch.object(secrets, "is_web_config_read_only", return_value=read_only),
        patch.object(secrets, "add_help_button"),
        patch.object(secrets, "field_help_icon"),
        patch.object(secrets, "_save_password_likelihood_setting") as save,
    ):
        secrets._render_password_likelihood({})
    ui.checkbox.assert_called_once_with(
        "Enable local password-likelihood analysis", value=False
    )
    ui.select.assert_called_once_with(
        ["ask", "warn", "block"], value="ask", label="Outcome"
    )
    ui.button.assert_not_called()
    ui.checkbox.return_value.on_value_change.assert_called_once()
    ui.select.return_value.on_value_change.assert_called_once()
    save.assert_not_called()
    for widget in (
        ui.checkbox.return_value,
        ui.select.return_value,
    ):
        assert widget.disable.call_count == int(read_only)
    assert "suspected_password" in dict(violation_logging.ALL_LOG_TYPES)
