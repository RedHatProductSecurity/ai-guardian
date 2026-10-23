"""
Unit tests for support bundle module.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.reporting.support_bundle import (
    _sanitize_config,
    _sanitize_violations,
    _get_system_info,
    _get_bundle_status,
    _get_gcs_token_from_adc,
    _get_gcs_token_from_gcloud,
    _load_bundle_from_path,
    _send_to_email,
    _send_to_gcs,
    _zip_bundle,
    prepare_bundle,
    send_bundle,
    support_command,
    _active_bundles,
    _cleanup_bundle,
)


@pytest.fixture(autouse=True)
def _isolate_diagnostic_collectors():
    """Bundle unit tests exercise export, not live doctor/OCR/scanner canaries."""
    doctor = SimpleNamespace(
        checks=[
            SimpleNamespace(
                name="test-health",
                status=SimpleNamespace(value="pass"),
                message="Synthetic health result",
            )
        ]
    )
    smoke = SimpleNamespace(phase1_passed=True, phase2_results=[])
    with (
        patch(
            "ai_guardian.reporting.support_bundle.collect_cli_configs", return_value=[]
        ),
        patch("ai_guardian.doctor.Doctor.run_all", return_value=doctor),
        patch("ai_guardian.smoke_test.SmokeTestRunner.run", return_value=smoke),
    ):
        yield


class TestSanitizeConfig:
    """Test config sanitization."""

    def test_redacts_sensitive_keys(self):
        config = {
            "secret_scanning": {"enabled": True},
            "pattern_server": {
                "auth_token": "my-secret-token",
                "url": "https://example.com/patterns",
            },
        }
        sanitized, count = _sanitize_config(config)
        assert sanitized["pattern_server"]["auth_token"] == "[REDACTED]"
        assert sanitized["pattern_server"]["url"] == "[REDACTED]"
        assert count == 2

    def test_strips_comments(self):
        config = {
            "_comment_test": "This is a comment",
            "enabled": True,
        }
        sanitized, _ = _sanitize_config(config)
        assert "_comment_test" not in sanitized
        assert sanitized["enabled"] is True

    def test_preserves_non_sensitive(self):
        config = {"secret_scanning": {"enabled": True}}
        sanitized, count = _sanitize_config(config)
        assert sanitized["secret_scanning"]["enabled"] is True
        assert count == 0


class TestSanitizeViolations:
    """Test violation sanitization."""

    def test_truncates_file_paths(self):
        violations = [
            {
                "timestamp": "2026-05-09T10:00:00Z",
                "violation_type": "secret_detected",
                "context": {"file_path": "/home/user/project/src/secrets.py"},
            }
        ]
        sanitized, count = _sanitize_violations(violations)
        assert sanitized[0]["context"]["file_path"] == str(
            Path("...") / "src" / "secrets.py"
        )
        assert count >= 1

    def test_removes_content_preview(self):
        violations = [
            {
                "context": {"content_preview": "password = 'hunter2'", "file_path": ""},
            }
        ]
        sanitized, count = _sanitize_violations(violations)
        assert "content_preview" not in sanitized[0]["context"]


class TestGetSystemInfo:
    """Test system info collection."""

    def test_returns_expected_fields(self):
        info = _get_system_info()
        assert "ai_guardian_version" in info
        assert "python_version" in info
        assert "platform" in info
        assert "os" in info


class TestPrepareBundle:
    """Test bundle preparation."""

    @patch("ai_guardian.reporting.support_bundle._get_support_config", return_value={})
    def test_blank_default_title_is_a_draft_and_file_list_puts_doctor_first(
        self, mock_config
    ):
        result = prepare_bundle(include_log=False, include_violations=False)
        try:
            context = json.loads(
                (Path(result["temp_path"]) / "support-context.json").read_text()
            )
            assert context == {
                "title": "",
                "description": "",
                "category": "bug-reports",
            }
            names = [item["name"] for item in result["files"]]
            assert names[0] == "doctor.json"
            assert names[1:] == sorted(
                names[1:], key=lambda name: (name.casefold(), name)
            )
        finally:
            _cleanup_bundle(result["bundle_id"])

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_creates_bundle(self, mock_config):
        mock_config.return_value = {
            "export_destination": "~/support",
            "bundle_ttl_minutes": 30,
        }

        result = prepare_bundle()

        assert "bundle_id" in result
        assert result["bundle_id"].startswith("support-")
        assert "temp_path" in result
        assert "files" in result
        assert len(result["files"]) > 0

        # System info should always be present
        file_names = [f["name"] for f in result["files"]]
        assert "system-info.json" in file_names

        # Cleanup
        _cleanup_bundle(result["bundle_id"])

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_bundle_files_exist_on_disk(self, mock_config):
        mock_config.return_value = {"export_destination": "~/support"}

        result = prepare_bundle()
        temp_path = Path(result["temp_path"])
        assert temp_path.exists()

        for f in result["files"]:
            assert (temp_path / f["name"]).exists()

        _cleanup_bundle(result["bundle_id"])

    @pytest.mark.parametrize("destination", ["github-discussions", "local"])
    def test_prepares_individual_cli_copies_and_respects_user_removal(
        self, monkeypatch, tmp_path, destination
    ):
        from ai_guardian.reporting import cli_diagnostics

        dest = str(tmp_path / "exports") if destination == "local" else destination
        monkeypatch.setattr(
            "ai_guardian.reporting.support_bundle._get_support_config",
            lambda: {"export_destination": dest},
        )
        source = tmp_path / "cli-settings.json"
        source.write_text('{"model":"test-model","api_key":"unissued-test-value"}')
        monkeypatch.setattr(
            cli_diagnostics,
            "_config_sources",
            lambda: [("test-cli", "user", "settings", source)],
        )
        monkeypatch.setattr(
            "ai_guardian.reporting.support_bundle.collect_cli_configs",
            cli_diagnostics.collect_cli_configs,
        )
        result = prepare_bundle(include_log=False, include_violations=False)
        root = Path(result["temp_path"])
        try:
            name = "cli-test-cli-user-settings.json"
            assert name in {f["name"] for f in result["files"]}
            assert "unissued-test-value" not in (root / name).read_text()
            assert "unissued-test-value" in source.read_text()
            (root / name).unlink()  # User opts out before sending.
            if destination == "local":
                sent = send_bundle(result["bundle_id"])
                assert not (Path(sent["destination"]) / name).exists()
            else:
                from ai_guardian.reporting.github_support import _read_files

                assert name not in _read_files(_active_bundles[result["bundle_id"]])
        finally:
            _cleanup_bundle(result["bundle_id"])


class TestSendBundle:
    """Test bundle sending."""

    def test_rejects_unknown_bundle_id(self):
        result = send_bundle("nonexistent-bundle")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Local destination path detection requires Unix-style paths",
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_sends_to_local_directory(self, mock_config, tmp_path):
        dest = tmp_path / "support-output"
        mock_config.return_value = {
            "export_destination": str(dest),
            "bundle_ttl_minutes": 30,
        }

        bundle = prepare_bundle()
        result = send_bundle(bundle["bundle_id"])

        assert result["status"] == "sent"
        assert dest.exists()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_defaults_to_reviewed_github_discussions(self, mock_config):
        """Unset destinations use GitHub, but preparation cannot grant approval."""
        mock_config.return_value = {}

        bundle = prepare_bundle()
        assert bundle["destination"] == "github-discussions"
        with (
            patch(
                "ai_guardian.reporting.github_support.send_discussion",
                return_value={"status": "error", "error_code": "cancelled"},
            ) as sender,
            patch(
                "ai_guardian.reporting.github_support.credentials_available",
                return_value=True,
            ),
            patch(
                "ai_guardian.reporting.github_support.review_dialog",
                side_effect=lambda request: {
                    "request_id": request["request_id"],
                    "delivery": "discussion",
                },
            ),
        ):
            assert send_bundle(bundle["bundle_id"])["error_code"] == "cancelled"
            sender.assert_called_once()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_local_export_retains_reviewed_copy(self, mock_config, tmp_path):
        dest = tmp_path / "output"
        mock_config.return_value = {
            "export_destination": str(dest),
            "bundle_ttl_minutes": 30,
        }

        bundle = prepare_bundle()
        bundle_id = bundle["bundle_id"]
        temp_path = Path(bundle["temp_path"])

        send_bundle(bundle_id)

        assert not temp_path.exists()
        assert _active_bundles[bundle_id]["temp_path"] == str(dest / bundle_id)
        assert _active_bundles[bundle_id]["preserve_directory"] is True
        _cleanup_bundle(bundle_id)
        assert (dest / bundle_id).exists()


class TestPrepareBundleFlags:
    """Test prepare_bundle with filtering flags."""

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_no_log_excludes_log_file(self, mock_config):
        mock_config.return_value = {"export_destination": "~/support"}
        result = prepare_bundle(include_log=False)
        file_names = [f["name"] for f in result["files"]]
        assert "ai-guardian.log" not in file_names
        assert "system-info.json" in file_names
        _cleanup_bundle(result["bundle_id"])

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_no_violations_excludes_violations(self, mock_config):
        mock_config.return_value = {"export_destination": "~/support"}
        result = prepare_bundle(include_violations=False)
        file_names = [f["name"] for f in result["files"]]
        assert "violations.jsonl" not in file_names
        assert "system-info.json" in file_names
        _cleanup_bundle(result["bundle_id"])

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_output_path_copies_files(self, mock_config, tmp_path):
        output_dir = tmp_path / "my-bundle"
        mock_config.return_value = {"export_destination": "~/support"}
        result = prepare_bundle(output_path=str(output_dir))
        assert output_dir.exists()
        assert "output_path" in result
        for f in result["files"]:
            assert (output_dir / f["name"]).exists()
        _cleanup_bundle(result["bundle_id"])

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_both_exclusions(self, mock_config):
        mock_config.return_value = {}
        result = prepare_bundle(include_log=False, include_violations=False)
        file_names = [f["name"] for f in result["files"]]
        assert "ai-guardian.log" not in file_names
        assert "violations.jsonl" not in file_names
        assert "system-info.json" in file_names
        _cleanup_bundle(result["bundle_id"])


class TestLoadBundleFromPath:
    """Test _load_bundle_from_path helper."""

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_valid_directory(self, mock_config, tmp_path):
        mock_config.return_value = {}
        bundle_dir = tmp_path / "support-20260511-abcd1234"
        bundle_dir.mkdir()
        (bundle_dir / "system-info.json").write_text("{}")
        bundle_id = _load_bundle_from_path(str(bundle_dir))
        assert bundle_id is not None
        assert bundle_id in _active_bundles
        _cleanup_bundle(bundle_id)

    def test_nonexistent_directory(self):
        result = _load_bundle_from_path("/nonexistent/path")
        assert result is None

    def test_empty_directory(self, tmp_path):
        empty_dir = tmp_path / "empty-bundle"
        empty_dir.mkdir()
        result = _load_bundle_from_path(str(empty_dir))
        assert result is None

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_uses_dir_name_as_bundle_id(self, mock_config, tmp_path):
        mock_config.return_value = {}
        bundle_dir = tmp_path / "support-20260511-test1234"
        bundle_dir.mkdir()
        (bundle_dir / "ai-guardian.json").write_text("{}")
        bundle_id = _load_bundle_from_path(str(bundle_dir))
        assert bundle_id == "support-20260511-test1234"
        _cleanup_bundle(bundle_id)


class TestGetBundleStatus:
    """Test _get_bundle_status helper."""

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_returns_expected_fields(self, mock_config):
        mock_config.return_value = {
            "export_destination": "~/support",
            "bundle_ttl_minutes": 15,
        }
        status = _get_bundle_status()
        assert "destination" in status
        assert "destination_type" in status
        assert "auth_method" in status
        assert "auth_configured" in status
        assert "bundle_ttl_minutes" in status
        assert "pending_bundles" in status
        assert status["bundle_ttl_minutes"] == 15

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_local_destination_type(self, mock_config):
        mock_config.return_value = {"export_destination": "~/support"}
        status = _get_bundle_status()
        assert status["destination_type"] == "local"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_s3_destination_type(self, mock_config):
        mock_config.return_value = {"export_destination": "s3://bucket/prefix"}
        status = _get_bundle_status()
        assert status["destination_type"] == "s3"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_no_destination_defaults(self, mock_config):
        mock_config.return_value = {}
        status = _get_bundle_status()
        assert status["destination_type"] == "github-discussions"
        assert status["destination"] == "github-discussions"


class TestSupportCommand:
    """Test support_command CLI entry point."""

    def _make_args(self, support_command_val=None, **kwargs):
        defaults = {
            "support_command": support_command_val,
            "json": False,
            "no_log": False,
            "no_violations": False,
            "output": None,
            "prepare": False,
            "yes": False,
            "bundle": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_prepare_subcommand(self, mock_config, capsys):
        mock_config.return_value = {"export_destination": "~/support"}
        args = self._make_args(support_command_val="prepare")
        result = support_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "support-" in captured.out

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_prepare_json(self, mock_config, capsys):
        mock_config.return_value = {}
        args = self._make_args(support_command_val="prepare", json=True)
        result = support_command(args)
        assert result == 0
        data = json.loads(capsys.readouterr().out)
        assert "bundle_id" in data
        assert "files" in data

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_prepare_no_log(self, mock_config, capsys):
        mock_config.return_value = {}
        args = self._make_args(support_command_val="prepare", no_log=True, json=True)
        result = support_command(args)
        assert result == 0
        data = json.loads(capsys.readouterr().out)
        file_names = [f["name"] for f in data["files"]]
        assert "ai-guardian.log" not in file_names

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_prepare_with_output(self, mock_config, tmp_path, capsys):
        output_dir = tmp_path / "my-output"
        mock_config.return_value = {}
        args = self._make_args(support_command_val="prepare", output=str(output_dir))
        result = support_command(args)
        assert result == 0
        assert output_dir.exists()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Local destination path detection requires Unix-style paths",
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_send_with_prepare_and_yes(self, mock_config, tmp_path, capsys):
        dest = tmp_path / "send-dest"
        mock_config.return_value = {
            "export_destination": str(dest),
            "bundle_ttl_minutes": 30,
        }
        args = self._make_args(support_command_val="send", prepare=True, yes=True)
        result = support_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Sent" in captured.out or "sent" in captured.out

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("builtins.input", return_value="n")
    @patch("sys.stdin")
    def test_send_with_prepare_user_declines(
        self, mock_stdin, mock_input, mock_config, capsys
    ):
        mock_stdin.isatty.return_value = True
        mock_config.return_value = {"export_destination": "~/support"}
        args = self._make_args(support_command_val="send", prepare=True)
        result = support_command(args)
        assert result == 1

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Local destination path detection requires Unix-style paths",
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("builtins.input", return_value="y")
    @patch("sys.stdin")
    def test_send_with_prepare_user_confirms(
        self, mock_stdin, mock_input, mock_config, tmp_path, capsys
    ):
        mock_stdin.isatty.return_value = True
        dest = tmp_path / "confirmed-dest"
        mock_config.return_value = {
            "export_destination": str(dest),
            "bundle_ttl_minutes": 30,
        }
        args = self._make_args(support_command_val="send", prepare=True)
        result = support_command(args)
        assert result == 0

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Local destination path detection requires Unix-style paths",
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_send_with_bundle_path(self, mock_config, tmp_path, capsys):
        dest = tmp_path / "dest"
        bundle_dir = tmp_path / "support-20260511-test1234"
        bundle_dir.mkdir()
        (bundle_dir / "system-info.json").write_text('{"test": true}')
        mock_config.return_value = {
            "export_destination": str(dest),
            "bundle_ttl_minutes": 30,
        }
        args = self._make_args(
            support_command_val="send", bundle=str(bundle_dir), yes=True
        )
        result = support_command(args)
        assert result == 0

    def test_send_no_bundle_available(self, capsys):
        args = self._make_args(support_command_val="send")
        result = support_command(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "prepare" in captured.err.lower()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_status_subcommand(self, mock_config, capsys):
        mock_config.return_value = {
            "export_destination": "~/support",
            "bundle_ttl_minutes": 30,
        }
        args = self._make_args(support_command_val="status")
        result = support_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Destination" in captured.out or "destination" in captured.out

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_status_json(self, mock_config, capsys):
        mock_config.return_value = {
            "export_destination": "~/support",
            "bundle_ttl_minutes": 30,
        }
        args = self._make_args(support_command_val="status", json=True)
        result = support_command(args)
        assert result == 0
        data = json.loads(capsys.readouterr().out)
        assert "destination" in data

    def test_no_subcommand_shows_usage(self, capsys):
        args = self._make_args()
        result = support_command(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "usage" in captured.err.lower() or "support" in captured.err.lower()


class TestGCSDestinationType:
    """Test GCS destination type detection."""

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_gcs_destination_type(self, mock_config):
        mock_config.return_value = {"export_destination": "gs://my-bucket"}
        status = _get_bundle_status()
        assert status["destination_type"] == "gcs"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_gcs_destination_with_trailing_slash(self, mock_config):
        mock_config.return_value = {"export_destination": "gs://my-bucket/"}
        status = _get_bundle_status()
        assert status["destination_type"] == "gcs"


class TestGCSTokenFromADC:
    """Test ADC credential discovery."""

    @patch("ai_guardian.reporting.support_bundle.urlopen")
    def test_reads_authorized_user_credentials(self, mock_urlopen, tmp_path):
        creds_file = tmp_path / "adc.json"
        creds_file.write_text(
            json.dumps(
                {
                    "type": "authorized_user",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                    "refresh_token": "test-refresh-token",
                }
            )
        )

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = json.dumps(
            {"access_token": "test-token-123"}
        ).encode()
        mock_urlopen.return_value = mock_response

        with patch.dict(
            os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": str(creds_file)}
        ):
            token = _get_gcs_token_from_adc()

        assert token == "test-token-123"

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="GCS ADC path ~/.config/gcloud not applicable on Windows",
    )
    def test_returns_none_when_no_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                token = _get_gcs_token_from_adc()
        assert token is None

    def test_skips_non_authorized_user_type(self, tmp_path):
        creds_file = tmp_path / "service-account.json"
        creds_file.write_text(
            json.dumps(
                {
                    "type": "service_account",
                    "project_id": "test-project",
                }
            )
        )

        with patch.dict(
            os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": str(creds_file)}
        ):
            token = _get_gcs_token_from_adc()

        assert token is None


class TestGCSTokenFromGcloud:
    """Test gcloud CLI fallback."""

    @patch("subprocess.run")
    def test_returns_token_from_gcloud(self, mock_run):
        mock_run.return_value = MagicMock(stdout="gcloud-token-456\n")
        token = _get_gcs_token_from_gcloud()
        assert token == "gcloud-token-456"
        mock_run.assert_called_once_with(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )

    @patch("subprocess.run", side_effect=FileNotFoundError("gcloud not found"))
    def test_returns_none_when_gcloud_missing(self, mock_run):
        token = _get_gcs_token_from_gcloud()
        assert token is None

    @patch("subprocess.run")
    def test_returns_none_for_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        token = _get_gcs_token_from_gcloud()
        assert token is None


class TestSendToGCS:
    """Test GCS upload."""

    def _make_bundle_dir(self, tmp_path):
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / ".ai-read-deny").touch()
        (bundle_dir / "ai-guardian.json").write_text('{"test": true}')
        (bundle_dir / "system-info.json").write_text('{"version": "1.0"}')
        return bundle_dir

    @patch(
        "ai_guardian.reporting.support_bundle._get_gcs_token_from_adc",
        return_value="test-token",
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config", return_value={})
    @patch("ai_guardian.reporting.support_bundle.urlopen")
    def test_upload_success(self, mock_urlopen, mock_config, mock_adc, tmp_path):
        bundle_dir = self._make_bundle_dir(tmp_path)

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b"{}"
        mock_urlopen.return_value = mock_response

        result = _send_to_gcs(
            "support-20260511-abc123",
            bundle_dir,
            "gs://my-bucket/ai-guardian/support/config-bundle/",
        )

        assert result["status"] == "sent"
        assert "gs://my-bucket/" in result["destination"]
        assert "support-20260511-abc123" in result["destination"]
        assert "2 files uploaded" in result["message"]
        assert mock_urlopen.call_count == 2

    @patch(
        "ai_guardian.reporting.support_bundle._get_gcs_token_from_adc",
        return_value="test-token",
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config", return_value={})
    @patch("ai_guardian.reporting.support_bundle.urlopen")
    def test_upload_uses_correct_object_path(
        self, mock_urlopen, mock_config, mock_adc, tmp_path
    ):
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "ai-guardian.json").write_text('{"test": true}')

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b"{}"
        mock_urlopen.return_value = mock_response

        _send_to_gcs(
            "support-20260511-abc123",
            bundle_dir,
            "gs://my-bucket/ai-guardian/support/config-bundle",
        )

        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert (
            "ai-guardian%2Fsupport%2Fconfig-bundle%2Fsupport-20260511-abc123%2Fai-guardian.json"
            in request.full_url
        )

    @patch(
        "ai_guardian.reporting.support_bundle._get_gcs_token_from_adc",
        return_value=None,
    )
    @patch(
        "ai_guardian.reporting.support_bundle._get_gcs_token_from_gcloud",
        return_value=None,
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config", return_value={})
    def test_no_credentials_error(self, mock_config, mock_gcloud, mock_adc, tmp_path):
        bundle_dir = self._make_bundle_dir(tmp_path)

        result = _send_to_gcs(
            "support-20260511-abc123", bundle_dir, "gs://my-bucket/prefix/"
        )

        assert result["status"] == "error"
        assert "credentials" in result["message"].lower()
        assert "gcloud auth" in result["message"]

    @patch(
        "ai_guardian.reporting.support_bundle._get_gcs_token_from_adc",
        return_value=None,
    )
    @patch(
        "ai_guardian.reporting.support_bundle._get_gcs_token_from_gcloud",
        return_value=None,
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_config_token_env_fallback(
        self, mock_config, mock_gcloud, mock_adc, tmp_path
    ):
        mock_config.return_value = {"auth": {"token_env": "MY_GCS_TOKEN"}}
        bundle_dir = self._make_bundle_dir(tmp_path)

        with patch("ai_guardian.reporting.support_bundle.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_response.read.return_value = b"{}"
            mock_urlopen.return_value = mock_response

            with patch.dict(os.environ, {"MY_GCS_TOKEN": "env-token-789"}):
                result = _send_to_gcs(
                    "support-20260511-abc123", bundle_dir, "gs://my-bucket/prefix/"
                )

        assert result["status"] == "sent"

    @patch(
        "ai_guardian.reporting.support_bundle._get_gcs_token_from_adc",
        return_value="test-token",
    )
    @patch("ai_guardian.reporting.support_bundle._get_support_config", return_value={})
    @patch("ai_guardian.reporting.support_bundle.urlopen")
    def test_http_error(self, mock_urlopen, mock_config, mock_adc, tmp_path):
        bundle_dir = self._make_bundle_dir(tmp_path)

        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://storage.googleapis.com/...",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

        result = _send_to_gcs(
            "support-20260511-abc123", bundle_dir, "gs://my-bucket/prefix/"
        )

        assert result["status"] == "error"
        assert "403" in result["message"]

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_send_bundle_routes_to_gcs(self, mock_config, tmp_path):
        mock_config.return_value = {
            "export_destination": "gs://test-bucket/ai-guardian/support/config-bundle/",
            "bundle_ttl_minutes": 30,
        }

        bundle = prepare_bundle()
        bundle_id = bundle["bundle_id"]

        with patch("ai_guardian.reporting.support_bundle._send_to_gcs") as mock_gcs:
            mock_gcs.return_value = {
                "status": "sent",
                "destination": "gs://test-bucket/...",
                "message": "ok",
            }
            result = send_bundle(bundle_id)

        assert mock_gcs.called
        assert result["status"] == "sent"


# --- Email destination tests (Issue #932) ---


class TestZipBundle:
    """Test _zip_bundle() helper."""

    def test_creates_zip_file(self, tmp_path):
        """Zip bundle creates a valid zip with all files except .ai-read-deny."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "config.json").write_text('{"key": "value"}')
        (bundle_dir / "violations.json").write_text("[]")
        (bundle_dir / ".ai-read-deny").write_text("")

        zip_path = _zip_bundle(bundle_dir, "test-bundle-001")

        assert zip_path.exists()
        assert zip_path.name == "test-bundle-001.zip"
        import zipfile

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "config.json" in names
            assert "violations.json" in names
            assert ".ai-read-deny" not in names

    def test_empty_bundle(self, tmp_path):
        """Zip bundle with only .ai-read-deny produces empty zip."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / ".ai-read-deny").write_text("")

        zip_path = _zip_bundle(bundle_dir, "empty-bundle")

        assert zip_path.exists()
        import zipfile

        with zipfile.ZipFile(zip_path) as zf:
            assert len(zf.namelist()) == 0


class TestSendToEmail:
    """Test _send_to_email() function with all auth methods."""

    def _make_bundle_dir(self, tmp_path):
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "config.json").write_text('{"sanitized": true}')
        (bundle_dir / "system.json").write_text('{"version": "1.0"}')
        (bundle_dir / ".ai-read-deny").write_text("")
        return bundle_dir

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_send_with_starttls_no_auth(self, mock_smtp_cls, mock_config, tmp_path):
        """Send via SMTP with STARTTLS and no authentication (corporate relay)."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "relay.company.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "guardian@company.com",
                "subject_prefix": "[Support]",
                "auth": {"method": "none"},
            }
        }
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-001", bundle_dir, "mailto:support@company.com")

        assert result["status"] == "sent"
        assert "support@company.com" in result["destination"]
        mock_smtp_cls.assert_called_once_with("relay.company.com", 587, timeout=30)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_not_called()
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_send_with_env_auth(
        self, mock_smtp_cls, mock_config, tmp_path, monkeypatch
    ):
        """Send via SMTP with environment variable credentials."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "noreply@example.com",
                "auth": {
                    "method": "env",
                    "username_env": "SMTP_USER",
                    "password_env": "SMTP_PASSWORD",
                },
            }
        }
        monkeypatch.setenv("SMTP_USER", "testuser")
        monkeypatch.setenv("SMTP_PASSWORD", "testpass")
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-002", bundle_dir, "support@example.com")

        assert result["status"] == "sent"
        mock_server.login.assert_called_once_with("testuser", "testpass")
        mock_server.sendmail.assert_called_once()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_send_with_inline_auth(self, mock_smtp_cls, mock_config, tmp_path):
        """Send via SMTP with inline credentials."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "noreply@example.com",
                "auth": {
                    "method": "inline",
                    "username": "inlineuser",
                    "password": "inlinepass",
                },
            }
        }
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-003", bundle_dir, "mailto:admin@example.com")

        assert result["status"] == "sent"
        mock_server.login.assert_called_once_with("inlineuser", "inlinepass")

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP_SSL")
    def test_send_with_implicit_ssl(self, mock_smtp_ssl_cls, mock_config, tmp_path):
        """Send via SMTPS (port 465, implicit SSL)."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "smtp_tls": True,
                "from": "noreply@example.com",
                "auth": {"method": "none"},
            }
        }
        mock_server = MagicMock()
        mock_smtp_ssl_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-004", bundle_dir, "mailto:admin@example.com")

        assert result["status"] == "sent"
        mock_smtp_ssl_cls.assert_called_once_with("smtp.example.com", 465, timeout=30)
        # SMTP_SSL doesn't call starttls
        mock_server.starttls.assert_not_called()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_send_without_tls(self, mock_smtp_cls, mock_config, tmp_path):
        """Send via plain SMTP (no TLS, port 25)."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "internal-relay.local",
                "smtp_port": 25,
                "smtp_tls": False,
                "from": "guardian@internal.local",
                "auth": {"method": "none"},
            }
        }
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-005", bundle_dir, "ops@internal.local")

        assert result["status"] == "sent"
        mock_smtp_cls.assert_called_once_with("internal-relay.local", 25, timeout=30)
        mock_server.starttls.assert_not_called()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_smtp_auth_error(self, mock_smtp_cls, mock_config, tmp_path):
        """SMTP authentication failure returns error status."""
        import smtplib

        mock_config.return_value = {
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "noreply@example.com",
                "auth": {
                    "method": "inline",
                    "username": "bad",
                    "password": "creds",
                },
            }
        }
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Authentication failed"
        )
        mock_smtp_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-006", bundle_dir, "mailto:support@example.com")

        assert result["status"] == "error"
        assert "authentication failed" in result["message"].lower()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_smtp_connection_error(self, mock_smtp_cls, mock_config, tmp_path):
        """SMTP connection failure returns error with zip path."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "unreachable.example.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "noreply@example.com",
                "auth": {"method": "none"},
            }
        }
        mock_smtp_cls.side_effect = OSError("Connection refused")

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-007", bundle_dir, "mailto:support@example.com")

        assert result["status"] == "error"
        assert "Connection refused" in result["message"]

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.webbrowser.open")
    def test_fallback_no_smtp_configured(self, mock_webbrowser, mock_config, tmp_path):
        """When no SMTP host is configured, fall back to system mailto:."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "",
                "subject_prefix": "[Test]",
            }
        }

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-008", bundle_dir, "mailto:help@example.com")

        assert result["status"] == "sent"
        assert "zip_path" in result
        assert Path(result["zip_path"]).name == "bundle-008.zip"
        assert "No SMTP configured" in result["message"]
        mock_webbrowser.assert_called_once()
        # Verify the zip was created
        assert Path(result["zip_path"]).exists()

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.webbrowser.open")
    def test_fallback_no_email_config(self, mock_webbrowser, mock_config, tmp_path):
        """When email section is entirely missing, fall back to system mailto:."""
        mock_config.return_value = {}

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-009", bundle_dir, "support@example.com")

        assert result["status"] == "sent"
        assert "zip_path" in result
        assert "No SMTP configured" in result["message"]

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_size_warning_large_bundle(self, mock_smtp_cls, mock_config, tmp_path):
        """Large bundles >10MB produce a size warning in the message."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "noreply@example.com",
                "auth": {"method": "none"},
            }
        }
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        # Create a large file that will exceed 10 MB (compressed is smaller,
        # but incompressible random data stays large).
        import os as _os

        large_file = bundle_dir / "large_data.bin"
        large_file.write_bytes(_os.urandom(11 * 1024 * 1024))

        result = _send_to_email("bundle-big", bundle_dir, "mailto:support@example.com")

        assert result["status"] == "sent"
        assert "Warning" in result["message"]
        assert "MB" in result["message"]

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    @patch("ai_guardian.reporting.support_bundle.smtplib.SMTP")
    def test_strips_mailto_prefix(self, mock_smtp_cls, mock_config, tmp_path):
        """The mailto: prefix is stripped from the destination address."""
        mock_config.return_value = {
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_tls": True,
                "from": "noreply@example.com",
                "auth": {"method": "none"},
            }
        }
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        bundle_dir = self._make_bundle_dir(tmp_path)
        result = _send_to_email("bundle-010", bundle_dir, "mailto:user@example.com")

        assert result["status"] == "sent"
        # Verify sendmail was called with the correct to address (no mailto: prefix)
        call_args = mock_server.sendmail.call_args
        assert call_args[0][1] == ["user@example.com"]


class TestEmailDestinationType:
    """Test email destination detection in _get_bundle_status and send_bundle routing."""

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_mailto_detected_as_email_type(self, mock_config):
        mock_config.return_value = {
            "export_destination": "mailto:support@company.com",
        }
        status = _get_bundle_status()
        assert status["destination_type"] == "email"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_at_sign_detected_as_email_type(self, mock_config):
        mock_config.return_value = {
            "export_destination": "support@company.com",
        }
        status = _get_bundle_status()
        assert status["destination_type"] == "email"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_send_bundle_routes_to_email(self, mock_config, tmp_path):
        mock_config.return_value = {
            "export_destination": "mailto:support@company.com",
            "bundle_ttl_minutes": 30,
        }
        bundle = prepare_bundle()
        bundle_id = bundle["bundle_id"]

        with patch("ai_guardian.reporting.support_bundle._send_to_email") as mock_email:
            mock_email.return_value = {
                "status": "sent",
                "destination": "mailto:support@company.com",
                "message": "ok",
            }
            result = send_bundle(bundle_id)

        assert mock_email.called
        assert result["status"] == "sent"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_send_bundle_routes_at_sign_to_email(self, mock_config, tmp_path):
        mock_config.return_value = {
            "export_destination": "support@company.com",
            "bundle_ttl_minutes": 30,
        }
        bundle = prepare_bundle()
        bundle_id = bundle["bundle_id"]

        with patch("ai_guardian.reporting.support_bundle._send_to_email") as mock_email:
            mock_email.return_value = {
                "status": "sent",
                "destination": "mailto:support@company.com",
                "message": "ok",
            }
            result = send_bundle(bundle_id)

        assert mock_email.called
        assert result["status"] == "sent"


class TestEmailAuthStatus:
    """Test auth_configured for email destinations in _get_bundle_status."""

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_email_no_auth_configured(self, mock_config):
        """No auth method means auth_configured is True (no creds needed)."""
        mock_config.return_value = {
            "export_destination": "mailto:support@company.com",
            "email": {"auth": {"method": "none"}},
        }
        status = _get_bundle_status()
        assert status["auth_configured"] is True
        assert status["auth_method"] == "none"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_email_env_auth_configured(self, mock_config, monkeypatch):
        """Env auth is configured when both env vars are set."""
        mock_config.return_value = {
            "export_destination": "mailto:support@company.com",
            "email": {
                "auth": {
                    "method": "env",
                    "username_env": "MY_USER",
                    "password_env": "MY_PASS",
                },
            },
        }
        monkeypatch.setenv("MY_USER", "user")
        monkeypatch.setenv("MY_PASS", "pass")
        status = _get_bundle_status()
        assert status["auth_configured"] is True
        assert status["auth_method"] == "env"

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_email_env_auth_not_configured(self, mock_config, monkeypatch):
        """Env auth is not configured when env vars are missing."""
        mock_config.return_value = {
            "export_destination": "mailto:support@company.com",
            "email": {
                "auth": {
                    "method": "env",
                    "username_env": "MISSING_USER",
                    "password_env": "MISSING_PASS",
                },
            },
        }
        monkeypatch.delenv("MISSING_USER", raising=False)
        monkeypatch.delenv("MISSING_PASS", raising=False)
        status = _get_bundle_status()
        assert status["auth_configured"] is False

    @patch("ai_guardian.reporting.support_bundle._get_support_config")
    def test_email_inline_auth_configured(self, mock_config):
        """Inline auth is configured when username and password are set."""
        mock_config.return_value = {
            "export_destination": "mailto:support@company.com",
            "email": {
                "auth": {
                    "method": "inline",
                    "username": "user",
                    "password": "pass",
                },
            },
        }
        status = _get_bundle_status()
        assert status["auth_configured"] is True
        assert status["auth_method"] == "inline"


class TestDoctorEmailAuth:
    """Test doctor check for email auth configuration."""

    @staticmethod
    def _make_doctor(config):
        """Create a Doctor with pre-loaded config (skip disk I/O)."""
        from ai_guardian.doctor import Doctor

        doc = Doctor.__new__(Doctor)
        doc.fix = False
        doc.check_connectivity = False
        doc._config = config
        doc._config_error = None
        doc._config_loaded = True
        return doc

    def test_inline_auth_warns(self):
        """Doctor warns when SMTP credentials are hardcoded."""
        doc = self._make_doctor(
            {
                "support": {
                    "email": {
                        "auth": {"method": "inline", "username": "u", "password": "p"}
                    }
                }
            }
        )
        result = doc.check_email_auth()
        assert result.status.value == "warn"
        assert "hardcoded" in result.message.lower()

    def test_env_auth_passes(self):
        """Doctor passes for env var auth."""
        doc = self._make_doctor(
            {
                "support": {
                    "email": {
                        "auth": {
                            "method": "env",
                            "username_env": "U",
                            "password_env": "P",
                        }
                    }
                }
            }
        )
        result = doc.check_email_auth()
        assert result.status.value == "pass"

    def test_no_smtp_host_warns(self):
        """Doctor warns when email destination set but no SMTP host."""
        doc = self._make_doctor(
            {
                "support": {
                    "export_destination": "mailto:support@company.com",
                    "email": {"smtp_host": ""},
                }
            }
        )
        result = doc.check_email_auth()
        assert result.status.value == "warn"
        assert "mailto" in result.message.lower()

    def test_no_config_skips(self):
        """Doctor skips when no config loaded."""
        doc = self._make_doctor(None)
        result = doc.check_email_auth()
        assert result.status.value == "skip"

    def test_no_email_section_passes(self):
        """Doctor passes when support section has no email config."""
        doc = self._make_doctor({"support": {"export_destination": "/tmp/bundles"}})
        result = doc.check_email_auth()
        assert result.status.value == "pass"
