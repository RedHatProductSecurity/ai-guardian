"""Tests for violations.utils.is_temp_path."""

import pytest
import tempfile
import os


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
    
    def test_macos_temp_path(self):
        """macOS temp paths return True."""
        assert is_temp_path("/var/folders/xx/abc123/T/file.txt") is True


class TestGuidanceTempFile:
    """Test guidance for temp file violations."""
    
    def test_secret_detected_temp_file(self, mock_violation_logger):
        """Temp file secret detection returns config-only suggestion."""
        violation = {
            "violation_type": "secret_detected",
            "blocked": {
                "file_path": "/tmp/hook_input.txt",
                "rule_id": "postgres-connection"
            }
        }
        instructions, snippet = get_resolution_instructions(violation)
        
        assert "temporary file" in instructions
        assert "allowlist_patterns" in instructions
        assert "inline" not in instructions.lower()
        assert "gitleaks:allow" not in instructions
    
    def test_pii_detected_temp_file(self, mock_violation_logger):
        """Temp file PII detection returns config-only suggestion."""
        violation = {
            "violation_type": "pii_detected",
            "blocked": {
                "file_path": "/tmp/hook_input.txt",
                "pii_types": ["credit_card"]
            }
        }
        instructions, snippet = get_resolution_instructions(violation)
        
        assert "temporary file" in instructions
        assert "allowlist_patterns" in instructions
    
    def test_prompt_injection_temp_file(self, mock_violation_logger):
        """Temp file prompt injection returns config-only suggestion."""
        violation = {
            "violation_type": "prompt_injection",
            "blocked": {
                "file_path": "/tmp/hook_input.txt",
                "pattern": "test_pattern"
            }
        }
        instructions, snippet = get_resolution_instructions(violation)
        
        assert "temporary file" in instructions
        assert "allowlist_patterns" in instructions


@pytest.fixture
def mock_violation_logger(mocker):
    """Mock violation logger."""
    return mocker.patch("ai_guardian.violations.guidance.violation_logger")
