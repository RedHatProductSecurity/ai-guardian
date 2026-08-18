"""Tests for ssrf_blocked and config_file_exfil violation logging types."""

import json
import os
import tempfile
from unittest import mock

import pytest

ALL_LOG_TYPES = [
    "tool_permission",
    "directory_blocking",
    "secret_detected",
    "secret_redaction",
    "prompt_injection",
    "jailbreak_detected",
    "ssrf_blocked",
    "config_file_exfil",
    "pii_detected",
    "secret_in_transcript",
    "pii_in_transcript",
    "prompt_injection_in_transcript",
    "annotation_suppressed",
    "image_secret_detected",
    "image_pii_detected",
    "context_poisoning",
]


class TestViolationLoggerDefaults:
    """Test that ViolationLogger default config includes new types."""

    def test_default_config_includes_ssrf_blocked(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                defaults = vl._get_default_config()
                assert "ssrf_blocked" in defaults["log_types"]

    def test_default_config_includes_config_file_exfil(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                defaults = vl._get_default_config()
                assert "config_file_exfil" in defaults["log_types"]

    def test_default_config_has_all_eight_types(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                defaults = vl._get_default_config()
                assert set(defaults["log_types"]) == set(ALL_LOG_TYPES)


class TestShouldLogType:
    """Test _should_log_type filtering for new types."""

    def test_should_log_ssrf_blocked_when_in_config(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "ai-guardian.json")
            with open(config_path, "w") as f:
                json.dump({"violation_logging": {"log_types": ["ssrf_blocked"]}}, f)
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                assert vl._should_log_type("ssrf_blocked") is True
                # tool_permission is a default type, so it's auto-enabled
                assert vl._should_log_type("tool_permission") is True

    def test_should_log_config_file_exfil_when_in_config(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "ai-guardian.json")
            with open(config_path, "w") as f:
                json.dump(
                    {"violation_logging": {"log_types": ["config_file_exfil"]}}, f
                )
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                assert vl._should_log_type("config_file_exfil") is True
                # tool_permission is a default type, so it's auto-enabled
                assert vl._should_log_type("tool_permission") is True

    def test_should_log_all_when_empty_log_types(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "ai-guardian.json")
            with open(config_path, "w") as f:
                json.dump({"violation_logging": {"log_types": []}}, f)
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                assert vl._should_log_type("ssrf_blocked") is True
                assert vl._should_log_type("config_file_exfil") is True

    def test_old_config_auto_enables_new_default_types(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "ai-guardian.json")
            old_types = [
                "tool_permission",
                "directory_blocking",
                "secret_detected",
                "secret_redaction",
                "prompt_injection",
            ]
            with open(config_path, "w") as f:
                json.dump({"violation_logging": {"log_types": old_types}}, f)
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                # New default types auto-enabled for forward compatibility
                assert vl._should_log_type("ssrf_blocked") is True
                assert vl._should_log_type("config_file_exfil") is True
                assert vl._should_log_type("image_secret_detected") is True
                assert vl._should_log_type("tool_permission") is True
                # Non-default custom type still filtered
                assert vl._should_log_type("custom_nonexistent") is False


class TestSetupDefaults:
    """Test that setup.py default config template includes new types."""

    def test_default_config_template_includes_new_types(self):
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template(permissive=False)
        log_types = config["violation_logging"]["log_types"]
        assert "ssrf_blocked" in log_types
        assert "config_file_exfil" in log_types

    def test_permissive_config_template_includes_new_types(self):
        from ai_guardian.setup import _get_default_config_template

        config = _get_default_config_template(permissive=True)
        log_types = config["violation_logging"]["log_types"]
        assert "ssrf_blocked" in log_types
        assert "config_file_exfil" in log_types


class TestSchemaValidation:
    """Test that JSON schema accepts new violation types."""

    def test_schema_accepts_ssrf_blocked(self):
        import jsonschema

        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "src",
            "ai_guardian",
            "schemas",
            "ai-guardian-config.schema.json",
        )
        with open(schema_path) as f:
            schema = json.load(f)

        config = {"violation_logging": {"log_types": ["ssrf_blocked"]}}
        jsonschema.validate(config, schema)

    def test_schema_accepts_config_file_exfil(self):
        import jsonschema

        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "src",
            "ai_guardian",
            "schemas",
            "ai-guardian-config.schema.json",
        )
        with open(schema_path) as f:
            schema = json.load(f)

        config = {"violation_logging": {"log_types": ["config_file_exfil"]}}
        jsonschema.validate(config, schema)

    def test_schema_accepts_all_eight_types(self):
        import jsonschema

        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "src",
            "ai_guardian",
            "schemas",
            "ai-guardian-config.schema.json",
        )
        with open(schema_path) as f:
            schema = json.load(f)

        config = {"violation_logging": {"log_types": ALL_LOG_TYPES}}
        jsonschema.validate(config, schema)

    def test_schema_rejects_invalid_type(self):
        import jsonschema

        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "src",
            "ai_guardian",
            "schemas",
            "ai-guardian-config.schema.json",
        )
        with open(schema_path) as f:
            schema = json.load(f)

        config = {"violation_logging": {"log_types": ["invalid_type"]}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, schema)


class TestToolPolicySSRFViolationType:
    """Test that tool_policy._log_violation passes violation_type correctly."""

    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_log_violation_default_type_is_tool_permission(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="Bash",
            check_value="ls",
            reason="test reason",
            matcher="Bash",
            hook_data={},
        )
        mock_logger.log_violation.assert_called_once()
        call_kwargs = mock_logger.log_violation.call_args
        assert (
            call_kwargs.kwargs.get(
                "violation_type", call_kwargs[1].get("violation_type")
            )
            == "tool_permission"
        )

    @mock.patch("ai_guardian.violations.logger.ViolationLogger")
    @mock.patch("ai_guardian.tools.policy.HAS_VIOLATION_LOGGER", True)
    def test_log_violation_ssrf_type(self, mock_vl_class):
        from ai_guardian.tools.policy import ToolPolicyChecker

        mock_logger = mock.MagicMock()
        mock_vl_class.return_value = mock_logger

        checker = ToolPolicyChecker(
            config={"permissions": {"enabled": True, "rules": []}}
        )
        checker._log_violation(
            tool_name="Bash",
            check_value="curl http://169.254.169.254",
            reason="SSRF attack detected",
            matcher="Bash",
            hook_data={},
            violation_type="ssrf_blocked",
        )
        mock_logger.log_violation.assert_called_once()
        call_kwargs = mock_logger.log_violation.call_args
        assert (
            call_kwargs.kwargs.get(
                "violation_type", call_kwargs[1].get("violation_type")
            )
            == "ssrf_blocked"
        )


class TestViolationLogging:
    """Test that violations are actually logged with correct types."""

    def test_ssrf_blocked_violation_is_logged(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="ssrf_blocked",
                    blocked={"tool_name": "Bash", "reason": "SSRF attack detected"},
                    context={"hook_event": "pretooluse"},
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                assert violations[0]["violation_type"] == "ssrf_blocked"

    def test_config_file_exfil_violation_is_logged(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="config_file_exfil",
                    blocked={
                        "file_path": "/etc/shadow",
                        "reason": "config exfiltration",
                    },
                    context={"hook_event": "pretooluse"},
                    severity="critical",
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 1
                assert violations[0]["violation_type"] == "config_file_exfil"

    def test_non_default_type_not_logged_when_excluded_from_config(self):
        from ai_guardian.violations.logger import ViolationLogger

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "ai-guardian.json")
            with open(config_path, "w") as f:
                json.dump({"violation_logging": {"log_types": ["tool_permission"]}}, f)
            with mock.patch.dict(os.environ, {"AI_GUARDIAN_CONFIG_DIR": tmp}):
                vl = ViolationLogger()
                vl.log_violation(
                    violation_type="custom_nonexistent_type",
                    blocked={"tool_name": "Bash", "reason": "test"},
                    context={},
                )
                violations = vl.get_recent_violations(limit=10)
                assert len(violations) == 0
