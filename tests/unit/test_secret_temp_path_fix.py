"""Tests that violation messages show original file path, not temp scan path (Issue #882)."""

from unittest import mock


from ai_guardian.hook_processing import (
    _build_secret_detected_message,
    check_secrets,
)


class TestSecretMessageShowsOriginalPath:
    """Verify _build_secret_detected_message renders the file path from secret_details."""

    def test_original_path_in_location(self):
        details = {
            "rule_id": "generic-api-key",
            "file": "/project/Containerfile",
            "line_number": 9,
            "end_line": 9,
            "commit": "N/A",
            "total_findings": 1,
        }
        msg = _build_secret_detected_message("gitleaks", details, "Built-in rules")
        assert "Location: /project/Containerfile:9" in msg

    def test_temp_path_renders_as_given(self):
        details = {
            "rule_id": "generic-api-key",
            "file": "/dev/shm/aiguardian_abc123_Containerfile",
            "line_number": 9,
            "end_line": 9,
            "commit": "N/A",
            "total_findings": 1,
        }
        msg = _build_secret_detected_message("gitleaks", details, "Built-in rules")
        assert "/dev/shm/aiguardian_abc123_Containerfile:9" in msg

    def test_line_number_preserved(self):
        details = {
            "rule_id": "aws-access-key",
            "file": "/home/user/src/config.py",
            "line_number": 42,
            "end_line": 42,
            "commit": "N/A",
            "total_findings": 1,
        }
        msg = _build_secret_detected_message("gitleaks", details, "Built-in rules")
        assert "Location: /home/user/src/config.py:42" in msg


class TestCheckSecretsUsesOriginalPath:
    """Verify check_secrets replaces temp paths with file_path."""

    @mock.patch("ai_guardian.scanners.secret_scanning._log_secret_detection_violation")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @mock.patch("ai_guardian.scanners.secret_scanning.get_strategy")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_engine")
    @mock.patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_strategy_path_uses_original_file_path(
        self,
        mock_load_config,
        mock_select_engine,
        mock_get_strategy,
        mock_select_all,
        mock_log_violation,
    ):
        mock_load_config.return_value = (
            {"enabled": True, "engines": ["gitleaks"]},
            None,
        )

        mock_engine = mock.MagicMock()
        mock_engine.type = "gitleaks"
        mock_engine.pattern_server = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        mock_secret = mock.MagicMock()
        mock_secret.rule_id = "generic-api-key"
        mock_secret.file = "/dev/shm/aiguardian_xyz_Containerfile"
        mock_secret.line_number = 9
        mock_secret.end_line = 9
        mock_secret.commit = "N/A"

        mock_result = mock.MagicMock()
        mock_result.has_secrets = True
        mock_result.secrets = [mock_secret]
        mock_result.engine = "gitleaks"
        mock_result.error = None

        mock_strategy_obj = mock.MagicMock()
        mock_strategy_obj.execute.return_value = mock_result
        mock_get_strategy.return_value = mock_strategy_obj

        has_secrets, error_msg = check_secrets(
            "some content with secret",
            filename="Containerfile",
            file_path="/project/Containerfile",
        )

        assert has_secrets is True
        assert "Location: /project/Containerfile:9" in error_msg
        assert "/dev/shm/aiguardian_" not in error_msg

    @mock.patch("ai_guardian.scanners.secret_scanning._log_secret_detection_violation")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @mock.patch("ai_guardian.scanners.secret_scanning.get_strategy")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_engine")
    @mock.patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_strategy_path_falls_back_to_filename(
        self,
        mock_load_config,
        mock_select_engine,
        mock_get_strategy,
        mock_select_all,
        mock_log_violation,
    ):
        mock_load_config.return_value = (
            {"enabled": True, "engines": ["gitleaks"]},
            None,
        )

        mock_engine = mock.MagicMock()
        mock_engine.type = "gitleaks"
        mock_engine.pattern_server = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        mock_secret = mock.MagicMock()
        mock_secret.rule_id = "generic-api-key"
        mock_secret.file = "/dev/shm/aiguardian_xyz_Containerfile"
        mock_secret.line_number = 5
        mock_secret.end_line = 5
        mock_secret.commit = "N/A"

        mock_result = mock.MagicMock()
        mock_result.has_secrets = True
        mock_result.secrets = [mock_secret]
        mock_result.engine = "gitleaks"
        mock_result.error = None

        mock_strategy_obj = mock.MagicMock()
        mock_strategy_obj.execute.return_value = mock_result
        mock_get_strategy.return_value = mock_strategy_obj

        has_secrets, error_msg = check_secrets(
            "some content with secret",
            filename="Containerfile",
            file_path=None,
        )

        assert has_secrets is True
        assert "Location: Containerfile:5" in error_msg
        assert "/dev/shm/aiguardian_" not in error_msg

    @mock.patch("ai_guardian.scanners.secret_scanning._log_secret_detection_violation")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @mock.patch("ai_guardian.scanners.secret_scanning.get_strategy")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_engine")
    @mock.patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_line_number_preserved_with_path_fix(
        self,
        mock_load_config,
        mock_select_engine,
        mock_get_strategy,
        mock_select_all,
        mock_log_violation,
    ):
        mock_load_config.return_value = (
            {"enabled": True, "engines": ["betterleaks"]},
            None,
        )

        mock_engine = mock.MagicMock()
        mock_engine.type = "betterleaks"
        mock_engine.pattern_server = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        mock_secret = mock.MagicMock()
        mock_secret.rule_id = "aws-access-key"
        mock_secret.file = "/tmp/aiguardian_abc_main.py"
        mock_secret.line_number = 42
        mock_secret.end_line = 42
        mock_secret.commit = "N/A"

        mock_result = mock.MagicMock()
        mock_result.has_secrets = True
        mock_result.secrets = [mock_secret]
        mock_result.engine = "betterleaks"
        mock_result.error = None

        mock_strategy_obj = mock.MagicMock()
        mock_strategy_obj.execute.return_value = mock_result
        mock_get_strategy.return_value = mock_strategy_obj

        has_secrets, error_msg = check_secrets(
            "AWS_KEY = 'AKIA...'",
            filename="main.py",
            file_path="/home/user/project/main.py",
        )

        assert has_secrets is True
        assert "Location: /home/user/project/main.py:42" in error_msg

    @mock.patch("ai_guardian.scanners.secret_scanning._log_secret_detection_violation")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_all_engines")
    @mock.patch("ai_guardian.scanners.secret_scanning.get_strategy")
    @mock.patch("ai_guardian.scanners.secret_scanning.select_engine")
    @mock.patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_violation_log_receives_original_path(
        self,
        mock_load_config,
        mock_select_engine,
        mock_get_strategy,
        mock_select_all,
        mock_log_violation,
    ):
        mock_load_config.return_value = (
            {"enabled": True, "engines": ["gitleaks"]},
            None,
        )

        mock_engine = mock.MagicMock()
        mock_engine.type = "gitleaks"
        mock_engine.pattern_server = None
        mock_select_engine.return_value = mock_engine
        mock_select_all.return_value = [mock_engine]

        mock_secret = mock.MagicMock()
        mock_secret.rule_id = "generic-api-key"
        mock_secret.file = "/dev/shm/aiguardian_xyz_Containerfile"
        mock_secret.line_number = 9
        mock_secret.end_line = 9
        mock_secret.commit = "N/A"

        mock_result = mock.MagicMock()
        mock_result.has_secrets = True
        mock_result.secrets = [mock_secret]
        mock_result.engine = "gitleaks"
        mock_result.error = None

        mock_strategy_obj = mock.MagicMock()
        mock_strategy_obj.execute.return_value = mock_result
        mock_get_strategy.return_value = mock_strategy_obj

        check_secrets(
            "content",
            filename="Containerfile",
            file_path="/project/Containerfile",
        )

        mock_log_violation.assert_called_once()
        args = mock_log_violation.call_args
        assert args[0][0] == "/project/Containerfile"
        secret_details = args[0][2]
        assert secret_details["file"] == "/project/Containerfile"
