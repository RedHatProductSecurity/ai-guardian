"""
Unit tests for pattern_server warn_on_failure configuration.

Tests verify that the warn_on_failure setting correctly controls whether
warnings are shown when the pattern server fails to provide patterns.
Also tests context-aware warning messages (Issue #384).
"""

import logging
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock

import ai_guardian


def _minimal_env():
    """Return minimal env dict that preserves home dir resolution on all platforms."""
    keep = {}
    for key in (
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
    ):
        if key in os.environ:
            keep[key] = os.environ[key]
    return keep


from ai_guardian.patterns.server import PatternServerClient


class PatternServerWarningsTest(TestCase):
    """Test suite for pattern server warn_on_failure configuration"""

    def setUp(self):
        """Set up test fixtures"""
        # Capture logging output from ai_guardian modules
        self.log_capture = []

        # Create a custom handler that captures all log records
        class ListHandler(logging.Handler):
            def __init__(self, log_list):
                super().__init__()
                self.log_list = log_list

            def emit(self, record):
                self.log_list.append(record)

        self.log_handler = ListHandler(self.log_capture)
        self.log_handler.setLevel(logging.DEBUG)

        # Store original logging level
        self.original_level = logging.getLogger().level

        # Add handler to root logger (module loggers propagate here)
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.DEBUG)

        # Also add to specific loggers for pattern_server
        logging.getLogger("ai_guardian.patterns.server").addHandler(self.log_handler)
        logging.getLogger("ai_guardian.patterns.server").setLevel(logging.DEBUG)

    def tearDown(self):
        """Clean up test fixtures"""
        # Remove handlers
        logging.getLogger().removeHandler(self.log_handler)
        logging.getLogger("ai_guardian.patterns.server").removeHandler(self.log_handler)

        # Restore original logging level
        logging.getLogger().setLevel(self.original_level)

        # Close handler
        self.log_handler.close()

    def test_warn_on_failure_default_is_true(self):
        """Test that warn_on_failure defaults to True when not specified"""
        config = {
            "url": "https://pattern-server.example.com",
            "auth": {"token_env": "TEST_TOKEN"},
        }

        client = PatternServerClient(config)

        self.assertTrue(
            client.warn_on_failure, "warn_on_failure should default to True"
        )

    def test_warn_on_failure_explicit_true(self):
        """Test that warn_on_failure can be explicitly set to True"""
        config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": True,
            "auth": {"token_env": "TEST_TOKEN"},
        }

        client = PatternServerClient(config)

        self.assertTrue(
            client.warn_on_failure, "warn_on_failure should be True when set"
        )

    def test_warn_on_failure_explicit_false(self):
        """Test that warn_on_failure can be set to False"""
        config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": False,
            "auth": {"token_env": "TEST_TOKEN"},
        }

        client = PatternServerClient(config)

        self.assertFalse(
            client.warn_on_failure, "warn_on_failure should be False when set"
        )

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    def test_pattern_server_failure_falls_back_to_engines(
        self, mock_client_class, mock_pattern_config, mock_select_engine
    ):
        """Test that operation falls back to scanner engines when pattern server fails"""
        # Setup: Pattern server configured
        pattern_config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": True,
        }
        mock_pattern_config.return_value = pattern_config

        # Mock client that fails to get patterns (returns None)
        mock_client = MagicMock()
        mock_client.warn_on_failure = True
        mock_client.get_patterns_path.return_value = None
        mock_client.token_file = Path("/tmp/test-token")
        mock_client_class.return_value = mock_client

        # Mock scanner engine selection to succeed
        from ai_guardian.scanners.engine_builder import EngineConfig

        mock_engine = EngineConfig(
            type="gitleaks",
            binary="gitleaks",
            command_template=["gitleaks", "detect"],
            success_exit_code=0,
            secrets_found_exit_code=1,
            output_parser="gitleaks",
        )
        mock_select_engine.return_value = mock_engine

        # Execute: Scan content (will attempt to use pattern server, then fall back)
        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                with patch("shutil.which", return_value="/usr/local/bin/gitleaks"):
                    with patch("subprocess.run") as mock_run:
                        # Mock successful scan with no secrets
                        mock_run.return_value = MagicMock(returncode=0)
                        has_secrets, error_msg = ai_guardian.check_secrets(
                            content, "test.txt"
                        )

        # Verify: Operation should succeed (fall back to engines)
        self.assertFalse(
            has_secrets, "Operation should succeed with fallback to engines"
        )
        self.assertIsNone(error_msg, "No error message should be returned")

        # Verify select_engine was called (fallback occurred)
        self.assertTrue(
            mock_select_engine.called, "Should have fallen back to scanner engines"
        )

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    def test_pattern_server_fails_falls_back_to_engines(
        self, mock_client_class, mock_pattern_config, mock_select_engine
    ):
        """
        Test that operation falls back to scanner engines when pattern server fails.

        Note: As of issue #170, pattern server failures now fall back to scanner engines
        instead of blocking immediately.
        """
        # Setup: Pattern server configured
        pattern_config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": False,
        }
        mock_pattern_config.return_value = pattern_config

        # Mock client that fails to get patterns (returns None)
        mock_client = MagicMock()
        mock_client.warn_on_failure = False
        mock_client.get_patterns_path.return_value = None
        mock_client.token_file = Path("/tmp/test-token")
        mock_client_class.return_value = mock_client

        # Mock scanner engine selection to succeed
        from ai_guardian.scanners.engine_builder import EngineConfig

        mock_engine = EngineConfig(
            type="gitleaks",
            binary="gitleaks",
            command_template=["gitleaks", "detect"],
            success_exit_code=0,
            secrets_found_exit_code=1,
            output_parser="gitleaks",
        )
        mock_select_engine.return_value = mock_engine

        # Clear any previous log captures
        self.log_capture.clear()

        # Execute: Scan content (will attempt to use pattern server, then fall back)
        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                with patch("shutil.which", return_value="/usr/local/bin/gitleaks"):
                    with patch("subprocess.run") as mock_run:
                        # Mock successful scan with no secrets
                        mock_run.return_value = MagicMock(returncode=0)
                        has_secrets, error_msg = ai_guardian.check_secrets(
                            content, "test.txt"
                        )

        # Verify: Operation should succeed (fall back to engines)
        self.assertFalse(
            has_secrets, "Operation should succeed with fallback to engines"
        )
        self.assertIsNone(error_msg, "No error message should be returned")

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    def test_pattern_server_and_no_engines_warns(
        self, mock_client_class, mock_pattern_config, mock_select_engine
    ):
        """Test that operation shows WARNING when pattern server fails AND no scanner engines available"""
        # Setup: Pattern server configured without warn_on_failure field
        pattern_config = {"url": "https://pattern-server.example.com"}
        mock_pattern_config.return_value = pattern_config

        # Mock client that fails to get patterns (returns None)
        mock_client = MagicMock()
        mock_client.warn_on_failure = True  # Should be True by default
        mock_client.get_patterns_path.return_value = None
        mock_client.token_file = Path("/tmp/test-token")
        mock_client_class.return_value = mock_client

        # Mock scanner engine selection to fail (no scanners available)
        mock_select_engine.side_effect = RuntimeError(
            "No secret scanner found. Install one of:\n"
            "  • Gitleaks: brew install gitleaks\n"
            "  • BetterLeaks: brew install betterleaks\n"
            "  • LeakTK: brew install leaktk/tap/leaktk"
        )

        # Execute: Scan content (will attempt to use pattern server, then engines, both fail)
        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                has_secrets, error_msg = ai_guardian.check_secrets(content, "test.txt")

        # Verify: Operation should warn but NOT block (Issue #343)
        self.assertFalse(
            has_secrets, "Operation should NOT be blocked when no scanner available"
        )
        self.assertIsNotNone(error_msg, "Warning message should be returned")
        self.assertIn("WARNING", error_msg, "Should indicate warning")
        self.assertIn(
            "ai-guardian scanner install", error_msg, "Should contain install command"
        )
        self.assertIn(
            "you may leak secrets", error_msg, "Should warn about leaked secrets"
        )
        # Issue #384: Context-aware message should mention pattern server URL
        self.assertIn(
            "No secret scanning available", error_msg, "Should use context-aware title"
        )
        self.assertIn(
            "https://pattern-server.example.com",
            error_msg,
            "Should mention pattern server URL",
        )
        self.assertIn(
            "unavailable", error_msg, "Should indicate pattern server was unavailable"
        )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_warn_on_failure_auth_error_scenario(self, mock_get, mock_logger):
        """Test warning behavior when pattern server returns 401 auth error"""
        # Setup: Pattern server with warn_on_failure=True
        config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": True,
            "auth": {"token_env": "TEST_TOKEN"},
        }

        # Mock authentication error (401)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        # Set auth token in environment
        with patch.dict("os.environ", {"TEST_TOKEN": "fake-token"}):
            # Use a temporary cache directory that doesn't exist
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (will fail with 401)
                patterns_path = client.get_patterns_path()

                # Verify: Should return None and log error
                self.assertIsNone(patterns_path, "Should return None on auth failure")

                # Check that error was logged
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                self.assertTrue(
                    any("401 Unauthorized" in str(call) for call in error_calls),
                    f"Expected 401 auth error in logs. Got: {error_calls}",
                )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_warn_on_failure_network_error_scenario(self, mock_get, mock_logger):
        """Test warning behavior when pattern server has network error"""
        import requests

        # Setup: Pattern server with warn_on_failure=True
        config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": True,
            "auth": {"token_env": "TEST_TOKEN"},
        }

        # Mock network connection error
        mock_get.side_effect = requests.exceptions.ConnectionError(
            "Network unreachable"
        )

        # Set auth token in environment
        with patch.dict("os.environ", {"TEST_TOKEN": "fake-token"}):
            # Use a temporary cache directory that doesn't exist
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (will fail with network error)
                patterns_path = client.get_patterns_path()

                # Verify: Should return None and log error
                self.assertIsNone(patterns_path, "Should return None on network error")

                # Check that error was logged
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                self.assertTrue(
                    any("Connection error" in str(call) for call in error_calls),
                    f"Expected connection error in logs. Got: {error_calls}",
                )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_warn_on_failure_timeout_scenario(self, mock_get, mock_logger):
        """Test warning behavior when pattern server times out"""
        import requests

        # Setup: Pattern server with warn_on_failure=True
        config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": True,
            "auth": {"token_env": "TEST_TOKEN"},
        }

        # Mock timeout error
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

        # Set auth token in environment
        with patch.dict("os.environ", {"TEST_TOKEN": "fake-token"}):
            # Use a temporary cache directory that doesn't exist
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (will fail with timeout)
                patterns_path = client.get_patterns_path()

                # Verify: Should return None and log error
                self.assertIsNone(patterns_path, "Should return None on timeout")

                # Check that error was logged
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                self.assertTrue(
                    any("Timeout" in str(call) for call in error_calls),
                    f"Expected timeout error in logs. Got: {error_calls}",
                )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_warn_on_failure_server_unavailable_scenario(self, mock_get, mock_logger):
        """Test warning behavior when pattern server returns 503 (unavailable)"""
        # Setup: Pattern server with warn_on_failure=True
        config = {
            "url": "https://pattern-server.example.com",
            "warn_on_failure": True,
            "auth": {"token_env": "TEST_TOKEN"},
        }

        # Mock server unavailable error (503)
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_get.return_value = mock_response

        # Set auth token in environment
        with patch.dict("os.environ", {"TEST_TOKEN": "fake-token"}):
            # Use a temporary cache directory that doesn't exist
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (will fail with 503)
                patterns_path = client.get_patterns_path()

                # Verify: Should return None and log error
                self.assertIsNone(
                    patterns_path, "Should return None when server unavailable"
                )

                # Check that error was logged
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                self.assertTrue(
                    any(
                        "returned error" in str(call) or "503" in str(call)
                        for call in error_calls
                    ),
                    f"Expected 503 server error in logs. Got: {error_calls}",
                )

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    def test_pattern_server_unavailable_falls_back_to_engines(
        self, mock_client_class, mock_pattern_config, mock_select_engine
    ):
        """
        Test that operations fall back to scanner engines when pattern server is unavailable.

        As of issue #170, pattern server failures now fall back to scanner engines
        instead of blocking immediately. This provides better resilience.
        """
        # Setup: Pattern server configured
        pattern_config = {
            "url": "https://pattern-server.example.com",
            "patterns_endpoint": "/patterns/gitleaks/8.27.0",
        }
        mock_pattern_config.return_value = pattern_config

        # Mock client that fails to get patterns (returns None)
        # This simulates: pattern server down + cache expired
        mock_client = MagicMock()
        mock_client.get_patterns_path.return_value = None
        mock_client.token_file = Path("/tmp/test-token")
        mock_client_class.return_value = mock_client

        # Mock scanner engine selection to succeed
        from ai_guardian.scanners.engine_builder import EngineConfig

        mock_engine = EngineConfig(
            type="gitleaks",
            binary="gitleaks",
            command_template=["gitleaks", "detect"],
            success_exit_code=0,
            secrets_found_exit_code=1,
            output_parser="gitleaks",
        )
        mock_select_engine.return_value = mock_engine

        # Execute: Attempt to scan content
        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                with patch("shutil.which", return_value="/usr/local/bin/gitleaks"):
                    with patch("subprocess.run") as mock_run:
                        # Mock successful scan with no secrets
                        mock_run.return_value = MagicMock(returncode=0)
                        has_secrets, error_msg = ai_guardian.check_secrets(
                            content, "test.txt"
                        )

        # Verify: Operation should succeed (fall back to engines)
        self.assertFalse(
            has_secrets, "Operation should succeed with fallback to engines"
        )
        self.assertIsNone(error_msg, "No error message should be returned")

        # Verify select_engine was called (fallback occurred)
        self.assertTrue(
            mock_select_engine.called, "Should have fallen back to scanner engines"
        )

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    def test_warning_message_when_no_scanner(
        self, mock_client_class, mock_pattern_config, mock_select_engine
    ):
        """Test that warning message contains helpful information when no scanner available (Issue #343)"""
        # Setup: Pattern server configured
        pattern_config = {
            "url": "https://pattern-server.example.com",
            "patterns_endpoint": "/api/patterns",
            "warn_on_failure": True,
        }
        mock_pattern_config.return_value = pattern_config

        # Mock client that fails to get patterns
        mock_client = MagicMock()
        mock_client.warn_on_failure = True
        mock_client.get_patterns_path.return_value = None
        mock_client.token_file = Path("/home/user/.config/ai-guardian/pattern-token")
        mock_client_class.return_value = mock_client

        # Mock scanner engine selection to fail
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        # Execute: Scan content
        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                has_secrets, error_msg = ai_guardian.check_secrets(content, "test.txt")

        # Verify: Warning message (not blocking) with helpful details (Issue #343)
        self.assertFalse(
            has_secrets, "Operation should NOT be blocked when no scanner available"
        )
        self.assertIsNotNone(error_msg, "Warning message should be returned")

        # Check for helpful information in warning message
        self.assertIn("WARNING", error_msg, "Should indicate warning")
        self.assertIn(
            "ai-guardian scanner install", error_msg, "Should contain install command"
        )
        self.assertIn("you may leak secrets", error_msg, "Should warn about risk")
        # Issue #384: Context-aware message should mention pattern server URL
        self.assertIn(
            "No secret scanning available", error_msg, "Should use context-aware title"
        )
        self.assertIn(
            "https://pattern-server.example.com",
            error_msg,
            "Should mention pattern server URL",
        )

    @patch("subprocess.run")
    @patch("shutil.which")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    def test_engines_fallback_order_with_logging(
        self,
        mock_client_class,
        mock_pattern_config,
        mock_scanning_config,
        mock_which,
        mock_run,
    ):
        """Test that engines are tried in order with warnings logged for unavailable ones"""
        # Setup: Pattern server unavailable
        pattern_config = {"url": "https://pattern-server.example.com"}
        mock_pattern_config.return_value = pattern_config

        mock_client = MagicMock()
        mock_client.get_patterns_path.return_value = None  # Pattern server fails
        mock_client_class.return_value = mock_client

        # Scanner config: try betterleaks, then gitleaks
        scanner_config = {"engines": ["betterleaks", "gitleaks"]}
        mock_scanning_config.return_value = (scanner_config, None)

        # Mock: betterleaks not installed, gitleaks installed
        def which_side_effect(binary):
            if binary == "betterleaks":
                return None  # Not found
            elif binary == "gitleaks":
                return "/usr/local/bin/gitleaks"  # Found
            return None

        mock_which.side_effect = which_side_effect

        # Mock successful gitleaks run
        mock_run.return_value = MagicMock(returncode=0)

        # Execute: Scan content
        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                has_secrets, error_msg = ai_guardian.check_secrets(content, "test.txt")

        # Verify: Operation succeeded with gitleaks
        self.assertFalse(has_secrets, "Operation should succeed with gitleaks")
        self.assertIsNone(error_msg, "No error message")

        # Check that warnings were logged (via setUp's root-logger ListHandler)
        warning_msgs = [
            r.getMessage() for r in self.log_capture if r.levelno >= logging.WARNING
        ]
        info_msgs = [
            r.getMessage() for r in self.log_capture if r.levelno == logging.INFO
        ]

        # Should log warning about pattern server unavailable
        self.assertTrue(
            any(
                "Pattern server unavailable" in msg or "pattern server" in msg.lower()
                for msg in warning_msgs
            ),
            f"Expected pattern server warning. Got: {warning_msgs}",
        )

        # Should log warning about betterleaks not available
        self.assertTrue(
            any(
                "betterleaks" in msg and "not available" in msg.lower()
                for msg in warning_msgs
            ),
            f"Expected betterleaks unavailable warning. Got: {warning_msgs}",
        )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_public_url_without_token_succeeds(self, mock_get, mock_logger):
        """Test that public URLs work without authentication token"""
        # Setup: Pattern server pointing to public URL (GitHub raw content)
        config = {
            "url": "https://raw.githubusercontent.com",
            "patterns_endpoint": "/leaktk/patterns/main/target/patterns/gitleaks/8.27.0",
            "auth": {"token_env": "TEST_TOKEN"},
        }

        # Mock successful response (200 OK) for unauthenticated request
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "[rules]\n# Test patterns"
        mock_get.return_value = mock_response

        # NO token in environment (public URL scenario)
        with patch.dict("os.environ", _minimal_env(), clear=True):
            # Use a temporary cache directory
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (should succeed without token)
                patterns_path = client.get_patterns_path()

                # Verify: Should succeed and return cache path
                self.assertIsNotNone(
                    patterns_path, "Should succeed for public URLs without token"
                )
                self.assertTrue(patterns_path.exists(), "Cache file should be created")

                # Verify the request was made without Authorization header
                mock_get.assert_called_once()
                call_args = mock_get.call_args
                headers = call_args[1]["headers"]
                self.assertNotIn(
                    "Authorization",
                    headers,
                    "Should not include Authorization header for public URLs",
                )

                # Check that debug log mentions unauthenticated request
                debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
                self.assertTrue(
                    any("unauthenticated" in str(call).lower() for call in debug_calls),
                    f"Expected debug log about unauthenticated request. Got: {debug_calls}",
                )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_public_url_with_token_uses_auth(self, mock_get, mock_logger):
        """Test that authentication is used when token is available, even for public URLs"""
        # Setup: Pattern server pointing to public URL with token available
        config = {
            "url": "https://raw.githubusercontent.com",
            "patterns_endpoint": "/leaktk/patterns/main/target/patterns/gitleaks/8.27.0",
            "auth": {"token_env": "TEST_TOKEN"},
        }

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "[rules]\n# Test patterns"
        mock_get.return_value = mock_response

        # Token IS available in environment
        with patch.dict("os.environ", {"TEST_TOKEN": "ghp_test_token_12345"}):
            # Use a temporary cache directory
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (should use token)
                patterns_path = client.get_patterns_path()

                # Verify: Should succeed and use authentication
                self.assertIsNotNone(patterns_path, "Should succeed with token")

                # Verify the request included Authorization header
                mock_get.assert_called_once()
                call_args = mock_get.call_args
                headers = call_args[1]["headers"]
                self.assertIn(
                    "Authorization",
                    headers,
                    "Should include Authorization header when token available",
                )
                self.assertEqual(
                    headers["Authorization"], "Bearer ghp_test_token_12345"
                )

                # Check debug log mentions using authentication
                debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
                self.assertTrue(
                    any("Using authentication" in str(call) for call in debug_calls),
                    f"Expected debug log about using authentication. Got: {debug_calls}",
                )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_private_url_without_token_shows_helpful_error(self, mock_get, mock_logger):
        """Test that private URLs without token show helpful error message"""
        # Setup: Pattern server pointing to private endpoint
        config = {
            "url": "https://private-patterns.example.com",
            "patterns_endpoint": "/api/v1/patterns",
            "auth": {"token_env": "PRIVATE_PATTERN_TOKEN"},
        }

        # Mock 401 Unauthorized response (requires auth)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        # NO token in environment
        with patch.dict("os.environ", _minimal_env(), clear=True):
            # Use a temporary cache directory
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (should fail with helpful message)
                patterns_path = client.get_patterns_path()

                # Verify: Should fail
                self.assertIsNone(
                    patterns_path, "Should fail for private URLs without token"
                )

                # Check error message mentions authentication is required
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                self.assertTrue(
                    any("requires authentication" in str(call) for call in error_calls),
                    f"Expected error about authentication required. Got: {error_calls}",
                )

                # Check info message shows how to set token
                info_calls = [str(call) for call in mock_logger.info.call_args_list]
                self.assertTrue(
                    any("PRIVATE_PATTERN_TOKEN" in str(call) for call in info_calls),
                    f"Expected info about setting token. Got: {info_calls}",
                )

    @patch("ai_guardian.patterns.server.logger")
    @patch("requests.get")
    def test_private_url_with_wrong_token_shows_check_token_error(
        self, mock_get, mock_logger
    ):
        """Test that private URLs with wrong token show different error message"""
        # Setup: Pattern server with token configured
        config = {
            "url": "https://private-patterns.example.com",
            "patterns_endpoint": "/api/v1/patterns",
            "auth": {"token_env": "PRIVATE_PATTERN_TOKEN"},
        }

        # Mock 401 Unauthorized response (wrong token)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        # Token IS set but wrong
        with patch.dict("os.environ", {"PRIVATE_PATTERN_TOKEN": "wrong_token"}):
            # Use a temporary cache directory
            with tempfile.TemporaryDirectory() as tmpdir:
                config["cache"] = {"path": str(Path(tmpdir) / "test_patterns.toml")}
                client = PatternServerClient(config)

                # Execute: Try to get patterns (should fail)
                patterns_path = client.get_patterns_path()

                # Verify: Should fail
                self.assertIsNone(patterns_path, "Should fail with wrong token")

                # Check error message mentions checking the token (different from "no token")
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                self.assertTrue(
                    any(
                        "authentication failed" in str(call).lower()
                        for call in error_calls
                    ),
                    f"Expected error about authentication failed. Got: {error_calls}",
                )

                # Should mention checking the token
                info_calls = [str(call) for call in mock_logger.info.call_args_list]
                self.assertTrue(
                    any("check your" in str(call).lower() for call in info_calls),
                    f"Expected info about checking token. Got: {info_calls}",
                )


class TestContextAwareWarningMessages(TestCase):
    """Tests for context-aware scanner warning messages (Issue #384)."""

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    def test_warning_path1_no_pattern_server_attempted(
        self, mock_scanning_config, mock_select_engine
    ):
        """Path 1: No pattern server attempted, no engines — shows engines list."""
        mock_scanning_config.return_value = ({"engines": ["gitleaks"]}, None)
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", False):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                has_secrets, error_msg = ai_guardian.check_secrets(content, "test.txt")

        self.assertFalse(has_secrets)
        self.assertIsNotNone(error_msg)
        self.assertIn("No secret scanning available", error_msg)
        self.assertIn("No scanner engine is installed", error_msg)
        self.assertIn("['gitleaks']", error_msg)
        self.assertIn("none found", error_msg)
        self.assertNotIn("Pattern server", error_msg)
        self.assertIn("ai-guardian scanner install gitleaks", error_msg)
        self.assertIn("you may leak secrets", error_msg)

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_warning_path1_pattern_server_attempted_and_failed(
        self,
        mock_pattern_config,
        mock_client_class,
        mock_scanning_config,
        mock_select_engine,
    ):
        """Path 1: Pattern server attempted but failed, no engines — shows both."""
        pattern_config = {"url": "https://patterns.security.example.com"}
        mock_pattern_config.return_value = pattern_config

        mock_client = MagicMock()
        mock_client.get_patterns_path.return_value = None
        mock_client_class.return_value = mock_client

        mock_scanning_config.return_value = (
            {"engines": ["gitleaks", "betterleaks"]},
            None,
        )
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                has_secrets, error_msg = ai_guardian.check_secrets(content, "test.txt")

        self.assertFalse(has_secrets)
        self.assertIsNotNone(error_msg)
        self.assertIn("No secret scanning available", error_msg)
        self.assertIn("https://patterns.security.example.com", error_msg)
        self.assertIn("unavailable", error_msg)
        self.assertIn("['gitleaks', 'betterleaks']", error_msg)
        self.assertIn("none installed", error_msg)
        self.assertIn("ai-guardian scanner install gitleaks", error_msg)
        self.assertIn("you may leak secrets", error_msg)

    @patch("ai_guardian.scanners.secret_scanning.select_engine")
    @patch("ai_guardian.scanners.secret_scanning._load_secret_scanning_config")
    @patch("ai_guardian.scanners.secret_scanning.PatternServerClient")
    @patch("ai_guardian.scanners.secret_scanning._load_pattern_server_config")
    def test_warning_path2_pattern_server_ok_no_engines(
        self,
        mock_pattern_config,
        mock_client_class,
        mock_scanning_config,
        mock_select_engine,
    ):
        """Path 2: Pattern server succeeded but no engine to run patterns."""
        pattern_config = {"url": "https://patterns.security.example.com"}
        mock_pattern_config.return_value = pattern_config

        mock_client = MagicMock()
        mock_client.get_patterns_path.return_value = "/tmp/test-patterns.toml"
        mock_client_class.return_value = mock_client

        mock_scanning_config.return_value = ({"engines": ["gitleaks"]}, None)
        mock_select_engine.side_effect = RuntimeError("No secret scanner found")

        content = "This is test content"
        with patch("ai_guardian.scanners.secret_scanning.HAS_PATTERN_SERVER", True):
            with patch("ai_guardian.scanners.secret_scanning.HAS_SCANNER_ENGINE", True):
                has_secrets, error_msg = ai_guardian.check_secrets(content, "test.txt")

        self.assertFalse(has_secrets)
        self.assertIsNotNone(error_msg)
        self.assertIn("Scanner engine required", error_msg)
        self.assertIn("Enterprise patterns are available", error_msg)
        self.assertIn("no scanner engine is installed to use them", error_msg)
        self.assertIn("ai-guardian scanner install gitleaks", error_msg)
        self.assertIn("you may leak secrets", error_msg)
