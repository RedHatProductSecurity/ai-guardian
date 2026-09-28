"""Tests for violation_guidance — shared fix-guidance logic."""

import json

import pytest

from ai_guardian.constants import ALL_VIOLATION_TYPES
from ai_guardian.violations.guidance import (
    get_resolution_instructions,
    _type_placeholders,
)


class TestTypePlaceholders:

    def test_empty_list(self):
        assert _type_placeholders([]) == ["<regex>"]

    def test_single_type(self):
        assert _type_placeholders(["email"]) == ["<regex-for-email>"]

    def test_multiple_types(self):
        result = _type_placeholders(["email", "phone_number"])
        assert result == ["<regex-for-email>", "<regex-for-phone_number>"]


class TestToolPermission:

    def test_with_rule(self):
        v = {
            "violation_type": "tool_permission",
            "blocked": {},
            "suggestion": {
                "rule": {"matcher": "Bash", "mode": "allow", "patterns": ["ls"]}
            },
        }
        instr, snippet = get_resolution_instructions(v)
        assert "permissions.rules" in instr
        assert "Bash" in snippet
        assert "ls" in snippet

    def test_without_rule(self):
        v = {"violation_type": "tool_permission", "blocked": {}, "suggestion": {}}
        instr, snippet = get_resolution_instructions(v)
        assert "permissions.rules" in instr
        assert snippet == ""


class TestPromptInjection:

    def test_with_pattern(self):
        v = {
            "violation_type": "prompt_injection",
            "blocked": {"pattern": "ignore previous"},
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "allowlist_patterns" in instr
        assert "ignore previous" in snippet

    def test_without_pattern(self):
        v = {"violation_type": "prompt_injection", "blocked": {}, "suggestion": {}}
        _, snippet = get_resolution_instructions(v)
        assert "<pattern>" in snippet


class TestJailbreakDetected:

    def test_with_pattern(self):
        v = {
            "violation_type": "jailbreak_detected",
            "blocked": {"pattern": "DAN mode"},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert "DAN mode" in snippet

    def test_fallback_to_matched_text(self):
        v = {
            "violation_type": "jailbreak_detected",
            "blocked": {"matched_text": "bypass text"},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert "bypass text" in snippet


class TestSecretDetected:

    def test_uses_rule_id(self):
        v = {
            "violation_type": "secret_detected",
            "blocked": {"file_path": "app.py", "rule_id": "aws-access-key-id"},
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "aws-access-key-id" in instr
        assert "<regex-for-aws-access-key-id>" in snippet
        assert "gitleaks:allow" in instr

    def test_uses_secret_type_fallback(self):
        v = {
            "violation_type": "secret_detected",
            "blocked": {"secret_type": "generic-api-key"},
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "<regex-for-generic-api-key>" in snippet

    def test_unknown_secret_type(self):
        v = {"violation_type": "secret_detected", "blocked": {}, "suggestion": {}}
        instr, snippet = get_resolution_instructions(v)
        assert "<regex>" in snippet
        assert "your-regex-pattern" not in snippet


class TestDirectoryBlocking:

    def test_with_directory(self):
        v = {
            "violation_type": "directory_blocking",
            "blocked": {"denied_directory": "/home/secrets"},
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "/home/secrets" in instr
        assert "/home/secrets" in snippet


class TestPiiDetected:

    def test_with_types(self):
        v = {
            "violation_type": "pii_detected",
            "blocked": {
                "file_path": "data.csv",
                "pii_types": ["email", "phone_number"],
            },
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "scan_pii" in instr
        parsed = json.loads(snippet)
        patterns = parsed["scan_pii"]["allowlist_patterns"]
        assert "<regex-for-email>" in patterns
        assert "<regex-for-phone_number>" in patterns
        assert parsed["scan_pii"]["ignore_files"] == ["data.csv"]

    def test_without_types_fallback(self):
        v = {
            "violation_type": "pii_detected",
            "blocked": {"file_path": "data.csv"},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        parsed = json.loads(snippet)
        assert parsed["scan_pii"]["allowlist_patterns"] == ["<regex>"]

    def test_no_generic_pattern_placeholder(self):
        """<pattern> literal must not appear when types are known."""
        v = {
            "violation_type": "pii_detected",
            "blocked": {"pii_types": ["ssn"]},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert '"<pattern>"' not in snippet


class TestSecretRedaction:

    def test_with_types(self):
        v = {
            "violation_type": "secret_redaction",
            "blocked": {"redacted_types": ["generic-api-key", "stripe-api-key"]},
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "secret_scanning" in instr
        parsed = json.loads(snippet)
        patterns = parsed["secret_scanning"]["allowlist_patterns"]
        assert "<regex-for-generic-api-key>" in patterns
        assert "<regex-for-stripe-api-key>" in patterns

    def test_without_types_fallback(self):
        v = {"violation_type": "secret_redaction", "blocked": {}, "suggestion": {}}
        _, snippet = get_resolution_instructions(v)
        parsed = json.loads(snippet)
        assert parsed["secret_scanning"]["allowlist_patterns"] == ["<regex>"]

    def test_no_generic_pattern_placeholder(self):
        v = {
            "violation_type": "secret_redaction",
            "blocked": {"redacted_types": ["api-key"]},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert '"<pattern>"' not in snippet


class TestSsrfBlocked:

    def test_extracts_domain(self):
        v = {
            "violation_type": "ssrf_blocked",
            "blocked": {"tool_value": "https://example.com/api/v1"},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert "example.com" in snippet

    def test_no_url_fallback(self):
        v = {"violation_type": "ssrf_blocked", "blocked": {}, "suggestion": {}}
        _, snippet = get_resolution_instructions(v)
        assert "<domain>" in snippet


class TestConfigFileExfil:

    def test_with_file_path(self):
        v = {
            "violation_type": "config_file_exfil",
            "blocked": {"file_path": ".env.production"},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert ".env.production" in snippet


class TestSecretInTranscript:

    def test_with_secret_type(self):
        v = {
            "violation_type": "secret_in_transcript",
            "blocked": {"secret_type": "aws-secret-key"},
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "transcript" in instr.lower()
        assert "<regex-for-aws-secret-key>" in snippet

    def test_without_secret_type(self):
        v = {"violation_type": "secret_in_transcript", "blocked": {}, "suggestion": {}}
        _, snippet = get_resolution_instructions(v)
        parsed = json.loads(snippet)
        assert parsed["secret_scanning"]["allowlist_patterns"] == ["<regex>"]


class TestPiiInTranscript:

    def test_with_pii_types(self):
        v = {
            "violation_type": "pii_in_transcript",
            "blocked": {"pii_types": ["email", "ssn"]},
            "suggestion": {},
        }
        instr, snippet = get_resolution_instructions(v)
        assert "transcript" in instr.lower()
        parsed = json.loads(snippet)
        patterns = parsed["scan_pii"]["allowlist_patterns"]
        assert "<regex-for-email>" in patterns
        assert "<regex-for-ssn>" in patterns

    def test_without_pii_types(self):
        v = {"violation_type": "pii_in_transcript", "blocked": {}, "suggestion": {}}
        _, snippet = get_resolution_instructions(v)
        parsed = json.loads(snippet)
        assert parsed["scan_pii"]["allowlist_patterns"] == ["<regex>"]


class TestImageViolations:

    def test_image_secret(self):
        v = {
            "violation_type": "image_secret_detected",
            "blocked": {"file_path": "screenshot.png"},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert "screenshot.png" in snippet

    def test_image_pii(self):
        v = {
            "violation_type": "image_pii_detected",
            "blocked": {"file_path": "photo.jpg"},
            "suggestion": {},
        }
        _, snippet = get_resolution_instructions(v)
        assert "photo.jpg" in snippet


class TestUnknownType:

    def test_unknown_returns_generic(self):
        v = {"violation_type": "never_heard_of_this", "blocked": {}, "suggestion": {}}
        instr, snippet = get_resolution_instructions(v)
        assert "Review" in instr
        assert snippet == ""


class TestAllKnownTypesHaveInstructions:

    def test_all_types_produce_nonempty_output(self):
        for vtype in ALL_VIOLATION_TYPES:
            v = {
                "violation_type": vtype,
                "blocked": {
                    "pattern": "test",
                    "file_path": "test.py",
                    "denied_directory": "/tmp",
                    "tool_value": "https://x.com",
                    "pii_types": ["email"],
                    "redacted_types": ["api-key"],
                    "secret_type": "api-key",
                },
                "suggestion": {
                    "rule": {"matcher": "Bash", "mode": "allow", "patterns": ["t"]}
                },
            }
            instr, snippet = get_resolution_instructions(v)
            assert instr, f"{vtype} should produce non-empty instructions"
            if vtype != "canary_detected":
                assert snippet, f"{vtype} should produce a config snippet"


class TestAdditionalViolationTypes:
    @pytest.mark.parametrize(
        "vtype,blocked,section,key",
        [
            (
                "context_poisoning",
                {"pattern": "trusted preference"},
                "context_poisoning",
                "allowlist_patterns",
            ),
            (
                "supply_chain",
                {"file_path": "config/hooks.json"},
                "supply_chain",
                "allowlist_paths",
            ),
            (
                "code_security",
                {"rule_id": "B101", "file_path": "tests/example.py"},
                "code_scanning",
                "allowlist",
            ),
            (
                "offensive_language",
                {"matched_text": "legacy-term"},
                "scan_offensive",
                "allowlist_patterns",
            ),
            (
                "exfil_detection",
                {"matched_text": "safe-command"},
                "exfil_detection",
                "allowlist_patterns",
            ),
        ],
    )
    def test_type_specific_config_guidance(self, vtype, blocked, section, key):
        instructions, snippet = get_resolution_instructions(
            {"violation_type": vtype, "blocked": blocked}
        )

        assert section in instructions
        parsed = json.loads(snippet)
        assert key in parsed[section]

    def test_canary_guidance_is_investigation_only(self):
        instructions, snippet = get_resolution_instructions(
            {
                "violation_type": "canary_detected",
                "blocked": {"matched_text": "CANARY_VALUE"},
            }
        )

        assert "canary_detection.tokens" in instructions
        assert "Do not suppress" in instructions
        assert snippet == ""


@pytest.mark.parametrize(
    "vtype,phrase",
    [
        ("prompt_injection_in_transcript", "transcript"),
        ("annotation_suppressed", "annotation"),
    ],
)
def test_filter_types_have_explicit_no_remediation_guidance(vtype, phrase):
    instructions, snippet = get_resolution_instructions(
        {"violation_type": vtype, "blocked": {}}
    )

    assert phrase in instructions.lower()
    assert instructions
    assert snippet == ""


class TestNoGenericPlaceholdersWhenDataAvailable:
    """Ensure that when violation data contains type info, we never show '<pattern>'."""

    @pytest.mark.parametrize(
        "vtype,blocked,forbidden",
        [
            ("pii_detected", {"pii_types": ["email"]}, '"<pattern>"'),
            ("secret_redaction", {"redacted_types": ["api-key"]}, '"<pattern>"'),
            ("pii_in_transcript", {"pii_types": ["ssn"]}, '"<pattern>"'),
            ("secret_in_transcript", {"secret_type": "aws-key"}, '"<pattern>"'),
            ("secret_detected", {"rule_id": "stripe"}, "your-regex-pattern"),
        ],
    )
    def test_no_generic_placeholder(self, vtype, blocked, forbidden):
        v = {"violation_type": vtype, "blocked": blocked, "suggestion": {}}
        _, snippet = get_resolution_instructions(v)
        assert (
            forbidden not in snippet
        ), f"{vtype}: snippet still contains '{forbidden}'"


class TestRobustInputHandling:

    def test_blocked_not_dict(self):
        v = {"violation_type": "pii_detected", "blocked": "bad", "suggestion": {}}
        instr, snippet = get_resolution_instructions(v)
        assert instr

    def test_suggestion_not_dict(self):
        v = {"violation_type": "tool_permission", "blocked": {}, "suggestion": "bad"}
        instr, snippet = get_resolution_instructions(v)
        assert instr
