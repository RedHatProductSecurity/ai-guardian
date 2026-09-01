"""Tests for violations.utils.is_temp_path and guidance temp-file behavior."""

import os
import tempfile

from ai_guardian.violations.guidance import get_resolution_instructions
from ai_guardian.violations.utils import is_temp_path


class TestIsTempPath:
    """Test is_temp_path function."""

    def test_normal_path(self):
        """Normal paths return False."""
        assert is_temp_path("/usr/bin/python") is False
        assert is_temp_path("/home/user/project") is False

    def test_tmp_path(self):
        """/tmp paths return True."""
        assert is_temp_path("/tmp/file.txt") is True
        assert is_temp_path("/tmp/foo/bar") is True

    def test_var_tmp_path(self):
        """/var/tmp paths return True."""
        assert is_temp_path("/var/tmp/file.txt") is True

    def test_system_tmp_path(self):
        """System temp dir returns True."""
        assert is_temp_path(tempfile.gettempdir()) is True
        assert is_temp_path(os.path.join(tempfile.gettempdir(), "file.txt")) is True

    def test_empty_path(self):
        """Empty path returns False."""
        assert is_temp_path("") is False

    def test_none_path(self):
        """None path returns False."""
        assert is_temp_path(None) is False

    def test_macos_temp_path(self, monkeypatch):
        """macOS-style temp paths return True."""
        monkeypatch.setattr(tempfile, "gettempdir", lambda: "/var/folders/xx/abc123/T")
        assert is_temp_path("/var/folders/xx/abc123/T/file.txt") is True

    def test_prefix_collision_not_temp(self):
        """Paths that merely share a string prefix with a temp dir are not temp."""
        assert is_temp_path("/tmp2/persistent_repo/secret.py") is False
        assert is_temp_path("/tmp-backup/config.py") is False
        assert is_temp_path("/var/tmpreaper.conf") is False

    def test_path_traversal_out_of_temp_not_temp(self):
        """A traversal out of /tmp is not classified as a temp path."""
        assert is_temp_path("/tmp/../etc/passwd") is False


class TestGuidanceTempFile:
    """Test guidance for temp file violations."""

    def test_secret_detected_temp_file(self):
        """Temp file secret detection returns config-only suggestion, pattern pre-filled."""
        violation = {
            "violation_type": "secret_detected",
            "blocked": {
                "file_path": "/tmp/hook_input.txt",
                "rule_id": "postgres-connection",
            },
        }
        instructions, snippet = get_resolution_instructions(violation)

        assert "temporary file" in instructions
        assert "allowlist_patterns" in instructions
        assert "inline" not in instructions.lower()
        assert "gitleaks:allow" not in instructions
        assert "postgres-connection" in snippet

    def test_pii_detected_temp_file(self):
        """Temp file PII detection returns config-only suggestion."""
        violation = {
            "violation_type": "pii_detected",
            "blocked": {
                "file_path": "/tmp/hook_input.txt",
                "pii_types": ["credit_card"],
            },
        }
        instructions, snippet = get_resolution_instructions(violation)

        assert "temporary file" in instructions
        assert "allowlist_patterns" in instructions

    def test_prompt_injection_temp_file(self):
        """Temp file prompt injection returns config-only suggestion."""
        violation = {
            "violation_type": "prompt_injection",
            "blocked": {
                "file_path": "/tmp/hook_input.txt",
                "pattern": "test_pattern",
            },
        }
        instructions, snippet = get_resolution_instructions(violation)

        assert "temporary file" in instructions
        assert "allowlist_patterns" in instructions

    def test_config_file_exfil_temp_file(self):
        """Temp file config exfil detection returns config-only suggestion."""
        violation = {
            "violation_type": "config_file_exfil",
            "blocked": {"file_path": "/tmp/hook_input.txt"},
        }
        instructions, snippet = get_resolution_instructions(violation)

        assert "temporary file" in instructions
        assert "ignore_files" in instructions
        assert snippet == ""

    def test_image_secret_detected_temp_file(self):
        """Temp file image secret detection returns config-only suggestion."""
        violation = {
            "violation_type": "image_secret_detected",
            "blocked": {"file_path": "/tmp/hook_input.png"},
        }
        instructions, snippet = get_resolution_instructions(violation)

        assert "temporary file" in instructions
        assert "ignore_files" in instructions

    def test_secret_detected_non_temp_file_unaffected(self):
        """Non-temp files keep the original inline-annotation guidance."""
        violation = {
            "violation_type": "secret_detected",
            "blocked": {
                "file_path": "/home/user/project/config.py",
                "rule_id": "postgres-connection",
            },
        }
        instructions, snippet = get_resolution_instructions(violation)

        assert "temporary file" not in instructions
        assert "gitleaks:allow" in instructions

    def test_pii_detected_missing_file_path_uses_placeholder(self):
        """Missing file_path falls back to a placeholder instead of null in the snippet."""
        violation = {
            "violation_type": "pii_detected",
            "blocked": {"pii_types": ["credit_card"]},
        }
        _, snippet = get_resolution_instructions(violation)

        assert "null" not in snippet
        assert "<file>" in snippet
