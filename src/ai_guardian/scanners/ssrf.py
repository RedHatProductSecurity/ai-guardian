#!/usr/bin/env python3
"""
SSRF Protection Module - Pattern-Based Command Filtering

Provides pattern-based detection of Server-Side Request Forgery (SSRF) attempts
in tool parameters and Bash commands.

IMPORTANT LIMITATIONS:
--------------------
This module provides PATTERN-BASED FILTERING, not comprehensive SSRF protection.

✅ CAN DETECT:
  - Explicit URLs in Bash commands: curl http://169.254.169.254
  - Private IPs in tool parameters: WebFetch(url="http://10.0.0.1")
  - Metadata endpoints in command strings

❌ CANNOT DETECT:
  - Network calls inside MCP server implementations (after hook)
  - HTTP redirects that happen during tool execution
  - Dynamic URL construction inside tools
  - IDE's own network requests (no hook visibility)

ARCHITECTURE:
------------
- Hook-based: Runs at PreToolUse (before tool execution)
- Pattern matching: Analyzes command strings and parameters
- NOT a proxy: Cannot intercept actual network traffic
- NOT a firewall: Cannot block runtime connections

DEFENSE IN DEPTH:
-----------------
This is ONE LAYER in a multi-layer security strategy. For comprehensive
SSRF protection, ALSO implement:

1. Network-level controls (REQUIRED):
   - Firewall egress rules blocking 169.254.169.254
   - VPC/subnet isolation
   - Cloud provider network policies

2. MCP server sandboxing (RECOMMENDED):
   - Docker containers with --network restrictions
   - VMs with firewall rules
   - Only install MCP servers from trusted sources

3. Supply chain verification (FUTURE):
   - Verify MCP server signatures
   - Code review before installation

USAGE:
------
This module is designed to catch obvious mistakes and low-hanging fruit.
It does NOT provide comprehensive network security.

Think of it as: "Does this command STRING contain a dangerous IP?"
Not: "Can this tool make a dangerous network call?"

Design Philosophy:
- Immutable core protections: Cannot be disabled via config
- Local-first: All checks run locally
- Fast: <1ms overhead per Bash command
- Fail-closed: Block on parsing errors

Inspired by Hermes Security Framework patterns.
See docs/SSRF_PROTECTION.md for detailed documentation.
"""

import fnmatch
import ipaddress
import logging
import re
import socket
import struct
import urllib.parse
from typing import Tuple, Optional, Dict, Any, List

from ai_guardian.patterns import load_bundled_rules

logger = logging.getLogger(__name__)


class SSRFProtector:
    """
    Detects and blocks SSRF attacks in tool calls.

    Immutable Core Protections (cannot be disabled):
    - Private IP ranges: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16
    - Cloud metadata endpoints: 169.254.169.254, metadata.google.internal, fd00:ec2::254
    - Dangerous schemes: file://, gopher://, ftp://, data://

    Configurable Additions:
    - Additional blocked IPs/domains
    - Allow localhost (override default block)
    """

    # IMMUTABLE: Core private IP ranges (RFC 1918 + loopback + link-local)
    # These CANNOT be disabled via configuration
    CORE_BLOCKED_IP_RANGES = [
        "10.0.0.0/8",  # Private network (RFC 1918)
        "172.16.0.0/12",  # Private network (RFC 1918)
        "192.168.0.0/16",  # Private network (RFC 1918)
        "127.0.0.0/8",  # Loopback
        "169.254.0.0/16",  # Link-local (AWS metadata)
        "::1/128",  # IPv6 loopback
        "fc00::/7",  # IPv6 private network
        "fe80::/10",  # IPv6 link-local
    ]

    # IMMUTABLE: Core blocked domains (cloud metadata endpoints)
    # These CANNOT be disabled via configuration
    CORE_BLOCKED_DOMAINS = [
        "metadata.google.internal",  # GCP metadata
        "metadata.goog",  # GCP metadata (alternative)
        "169.254.169.254",  # AWS/Azure metadata IP as domain
        "fd00:ec2::254",  # AWS IPv6 metadata
        "instance-data",  # AWS instance metadata
        "100.100.100.200",  # Alibaba Cloud metadata
        "192.0.0.192",  # Oracle Cloud (OCI) metadata
        "localhost",  # Localhost (unless allow_localhost is True)
    ]

    # IMMUTABLE: Dangerous URL schemes
    # These CANNOT be disabled via configuration
    DANGEROUS_SCHEMES = [
        "file",  # Local file access
        "gopher",  # Gopher protocol (legacy attack vector)
        "ftp",  # FTP protocol
        "ftps",  # Secure FTP
        "data",  # Data URLs (can encode arbitrary content)
        "dict",  # DICT protocol
        "ldap",  # LDAP protocol
        "ldaps",  # Secure LDAP
    ]

    # URL extraction patterns for Bash commands
    # Matches: http://, https://, curl, wget, etc.
    URL_PATTERNS = [
        # IPv6 URLs with brackets: http://[::1]/ or http://[fd00:ec2::254]/ or http://[::ffff:169.254.169.254]/
        # Note: Includes dots to support IPv6-mapped IPv4 addresses (::ffff:x.x.x.x)
        r'(?:https?|ftp|ftps|file|gopher)://\[[0-9a-fA-F:.]+\][^\s\'"<>{}|\\^`]*',
        # Standard URLs (non-IPv6)
        r'(?:https?|ftp|ftps|file|gopher)://[^\s\'"<>{}|\\^`\[\]]+',
        # data: URLs (no //)
        r'data:[^\s\'"<>{}|\\^`]+',
        # dict, ldap, ldaps URLs
        r'(?:dict|ldap|ldaps)://[^\s\'"<>{}|\\^`\[\]]+',
        # curl/wget with URL argument
        r'(?:curl|wget)\s+(?:-[^\s]+\s+)*(["\']?)(?:https?|ftp)://[^\s\'"<>{}|\\^`\[\]]+\1',
        # URLs in quotes (including IPv6 and IPv6-mapped IPv4)
        r'["\'](?:https?|ftp|file|gopher|data|dict|ldap|ldaps)://?\[[0-9a-fA-F:.]+\][^"\']*["\']',
        r'["\'](?:https?|ftp|file|gopher|dict|ldap|ldaps)://[^"\']+["\']',
        r'["\']data:[^"\']+["\']',
        # -u/--url flag (common in curl)
        r'--?url\s*[=\s]\s*(["\']?)(?:https?|ftp)://[^\s\'"<>{}|\\^`\[\]]+\1',
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the SSRF protector.

        Args:
            config: Optional configuration dictionary with keys:
                - enabled: bool (default True)
                - action: str - "block", "warn", "log-only" (default "block")
                - additional_blocked_ips: list of IP addresses/ranges to block
                - additional_blocked_domains: list of domain names to block
                - allow_localhost: bool (default False) - allow localhost access
                - allowed_domains: list of domains to allow (overrides deny-list, not immutable protections)
                - pattern_server: Dict - pattern server configuration (NEW in v1.5.0)
        """
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.action = self.config.get("action", "block")
        self.allow_localhost = self.config.get("allow_localhost", False)
        self.findings: List[Dict[str, Any]] = []

        # Parse allowed domains (for allow-list functionality)
        # Dual-path: exact strings use exact/subdomain matching (backward compat),
        # regex patterns use re.fullmatch() against hostname and hostname:port
        self._allowed_domains_exact = set()
        self._allowed_domain_regexes = []
        _regex_metachar_re = re.compile(r"[\\*+?\[\](){}|^$:]")
        for domain in self.config.get("allowed_domains", []):
            if not domain:
                continue
            if _regex_metachar_re.search(domain):
                try:
                    from ai_guardian.config.utils import validate_regex_pattern

                    if not validate_regex_pattern(domain):
                        logger.warning(
                            f"ReDoS-unsafe regex in allowed_domains, skipping: {domain}"
                        )
                        continue
                    compiled = re.compile(domain, re.IGNORECASE)
                    self._allowed_domain_regexes.append(compiled)
                except re.error as e:
                    logger.warning(
                        f"Invalid regex in allowed_domains, skipping: {domain} — {e}"
                    )
            else:
                self._allowed_domains_exact.add(domain.lower())

        # Compile URL extraction patterns
        self._compiled_url_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.URL_PATTERNS
        ]

        # Load patterns using pattern loader if pattern_server configured
        pattern_server_config = self.config.get("pattern_server")
        if pattern_server_config:
            logger.debug("SSRF Protection: Loading patterns via pattern server")
            merged_patterns = self._load_patterns_via_server(pattern_server_config)
            ip_ranges_to_use = merged_patterns.get("blocked_ip_ranges", [])
            domains_to_use = merged_patterns.get("blocked_domains", [])
        else:
            # Load from bundled TOML (primary source, fallback to hardcoded)
            toml_data = self._load_patterns_from_toml()
            ip_ranges_to_use = toml_data.get(
                "ip_ranges", [{"cidr": cidr} for cidr in self.CORE_BLOCKED_IP_RANGES]
            )
            # Add additional IPs from local config
            for ip in self.config.get("additional_blocked_ips", []):
                ip_ranges_to_use.append({"cidr": ip})

            domains_to_use = toml_data.get(
                "domains", [{"domain": d} for d in self.CORE_BLOCKED_DOMAINS]
            )
            # Add additional domains from local config
            for domain in self.config.get("additional_blocked_domains", []):
                domains_to_use.append({"domain": domain})

        # Pre-parse IP ranges for performance
        self._blocked_ip_networks = []
        for ip_range in ip_ranges_to_use:
            try:
                # Handle both dict format (pattern server) and string format (legacy)
                if isinstance(ip_range, dict):
                    cidr = ip_range.get("cidr")
                else:
                    cidr = ip_range

                network = ipaddress.ip_network(cidr, strict=False)
                self._blocked_ip_networks.append(network)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid IP range in SSRF config: {ip_range} - {e}")

        # Build complete blocked domains list
        # Separate exact domains from wildcard patterns for performance
        self._blocked_domains = set()
        self._blocked_domain_patterns = []  # Wildcard patterns (*, ?, **)

        for domain_entry in domains_to_use:
            # Handle both dict format (pattern server) and string format (legacy)
            if isinstance(domain_entry, dict):
                domain = domain_entry.get("domain")
            else:
                domain = domain_entry

            if domain:
                # Check if this is a wildcard pattern
                if "*" in domain or "?" in domain:
                    # Validate pattern syntax
                    if self._is_valid_domain_pattern(domain):
                        self._blocked_domain_patterns.append(domain.lower())
                    else:
                        logger.warning(
                            f"Invalid domain pattern in SSRF config, skipping: {domain}"
                        )
                else:
                    # Exact domain or subdomain match (lowercase for case-insensitive matching)
                    self._blocked_domains.add(domain.lower())

        # Remove localhost from blocked list if allow_localhost is True
        if self.allow_localhost:
            self._blocked_domains.discard("localhost")
            # Also remove localhost IP range
            self._blocked_ip_networks = [
                net
                for net in self._blocked_ip_networks
                if str(net) not in ["127.0.0.0/8", "::1/128"]
            ]

        # Load path-based rules (NEW in v1.6.0)
        self._path_based_rules = (
            {}
        )  # Map domain -> {allowed_paths: [...], blocked_paths: [...]}
        for rule in self.config.get("path_based_rules", []):
            domain = rule.get("domain", "").lower()
            if domain:
                self._path_based_rules[domain] = {
                    "allowed_paths": rule.get("allowed_paths", []),
                    "blocked_paths": rule.get("blocked_paths", []),
                }

        logger.info(
            f"SSRF Protection: Loaded {len(self._blocked_ip_networks)} IP ranges, "
            f"{len(self._blocked_domains)} exact domains, "
            f"{len(self._blocked_domain_patterns)} wildcard patterns, and "
            f"{len(self._path_based_rules)} path-based rules"
        )

    @staticmethod
    def _load_patterns_from_toml() -> Dict[str, Any]:
        """Load SSRF patterns from bundled TOML. Falls back to empty dict."""

        def _transform(raw_rules):
            ip_ranges = []
            domains = []
            for raw in raw_rules:
                match_type = raw.get("match_type", "")
                if match_type == "cidr":
                    ip_ranges.append(
                        {
                            "cidr": raw.get("cidr", ""),
                            "description": raw.get("description", ""),
                            "immutable": raw.get("tier") == "immutable",
                        }
                    )
                elif (
                    match_type == "literal" and raw.get("group", "") == "blocked_domain"
                ):
                    domains.append(
                        {
                            "domain": raw.get("source", ""),
                            "description": raw.get("description", ""),
                            "immutable": raw.get("tier") == "immutable",
                        }
                    )
            return {"ip_ranges": ip_ranges, "domains": domains}

        return load_bundled_rules("ssrf", _transform, {}, "SSRF Protection")

    def _load_patterns_via_server(self, pattern_server_config: Dict) -> Dict[str, Any]:
        """
        Load patterns via pattern server with fallback to defaults.

        Args:
            pattern_server_config: Pattern server configuration

        Returns:
            Dict with 'blocked_ip_ranges' and 'blocked_domains' lists
        """
        try:
            from ai_guardian.patterns.loader import SSRFPatternLoader

            loader = SSRFPatternLoader()
            merged_patterns = loader.load_patterns(
                pattern_server_config=pattern_server_config, local_config=self.config
            )

            logger.info(
                "SSRF Protection: Loaded patterns from pattern server/cache/defaults"
            )
            return merged_patterns

        except ImportError:
            logger.error(
                "pattern_loader module not available, using hardcoded defaults"
            )
            return {
                "blocked_ip_ranges": [
                    {"cidr": cidr} for cidr in self.CORE_BLOCKED_IP_RANGES
                ],
                "blocked_domains": [{"domain": d} for d in self.CORE_BLOCKED_DOMAINS],
            }
        except Exception as e:
            logger.error(f"Error loading patterns from pattern server: {e}")
            logger.debug("Falling back to hardcoded default patterns")
            return {
                "blocked_ip_ranges": [
                    {"cidr": cidr} for cidr in self.CORE_BLOCKED_IP_RANGES
                ],
                "blocked_domains": [{"domain": d} for d in self.CORE_BLOCKED_DOMAINS],
            }

    def _extract_urls(self, command: str) -> List[str]:
        """
        Extract URLs from a Bash command string.

        Args:
            command: Bash command to extract URLs from

        Returns:
            List of extracted URLs

        Examples:
            >>> self._extract_urls("curl http://example.com")
            ["http://example.com"]

            >>> self._extract_urls("wget 'https://169.254.169.254/latest/meta-data/'")
            ["https://169.254.169.254/latest/meta-data/"]
        """
        urls = []

        for pattern in self._compiled_url_patterns:
            matches = pattern.findall(command)
            for match in matches:
                # Extract URL from match (may have capture groups)
                if isinstance(match, tuple):
                    # Pattern had capture groups, find the URL
                    for part in match:
                        if part and ("://" in part or part.startswith("http")):
                            urls.append(part.strip("'\""))
                            break
                else:
                    urls.append(match.strip("'\""))

        # Also extract any bare URLs (simpler fallback)
        simple_url_pattern = re.compile(
            r'(?:https?|ftp|ftps|file|gopher|data)://[^\s\'"<>{}|\\^`\[\]]+',
            re.IGNORECASE,
        )
        simple_matches = simple_url_pattern.findall(command)
        urls.extend(simple_matches)

        # Deduplicate while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            # Clean up URL
            url = url.strip("'\"")
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls

    def _parse_url(
        self, url: str
    ) -> Tuple[
        Optional[str], Optional[str], Optional[str], Optional[str], Optional[int]
    ]:
        """
        Parse a URL into scheme, hostname, path, full URL, and port.

        Args:
            url: URL string to parse

        Returns:
            Tuple of (scheme, hostname, path, full_url, port) or (None, None, None, None, None) on error
        """
        try:
            parsed = urllib.parse.urlparse(url)
            scheme = parsed.scheme.lower() if parsed.scheme else None
            hostname = parsed.hostname  # Already handles IPv6 brackets

            # Include query parameters in path for path-based matching
            path = parsed.path if parsed.path else "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"

            return scheme, hostname, path, url, parsed.port
        except Exception as e:
            logger.warning(f"Failed to parse URL '{url}': {e}")
            return None, None, None, None, None

    @staticmethod
    def _parse_octet(p: str) -> int:
        """Parse a single IP octet that may be hex, octal, or decimal."""
        if p.lower().startswith("0x"):
            return int(p, 16)
        if p.startswith("0") and len(p) > 1 and p.isdigit():
            try:
                return int(p, 8)
            except ValueError:
                return int(p)
        return int(p)

    @staticmethod
    def _normalize_ip(host: str) -> str:
        """Convert hex/octal/decimal-encoded IPs to dotted-decimal for CIDR matching.

        Handles formats that curl/wget/browsers resolve but Python's ipaddress rejects:
        - Full hex: 0x7f000001 -> 127.0.0.1
        - Full decimal: 2130706433 -> 127.0.0.1
        - Octal octets: 0177.0.0.1 -> 127.0.0.1
        - Hex octets: 0x7f.0x00.0x00.0x01 -> 127.0.0.1
        - Mixed: 0x7f.0.0.1 -> 127.0.0.1
        - 2-part: 169.16689918 -> 169.254.169.254 (a.X where X is 24-bit)
        - 3-part: 10.1.512 -> 10.1.2.0 (a.b.X where X is 16-bit)
        """
        if not host:
            return host

        # Full hex: 0x7f000001
        if re.match(r"^0[xX][0-9a-fA-F]+$", host):
            try:
                val = int(host, 16)
                if 0 <= val <= 0xFFFFFFFF:
                    return socket.inet_ntoa(struct.pack("!I", val))
            except (ValueError, struct.error):
                pass

        # Full decimal or 1-part octal: 2130706433 or 017700000001
        if host.isdigit():
            try:
                val = SSRFProtector._parse_octet(host)
                if 0 <= val <= 0xFFFFFFFF:
                    return socket.inet_ntoa(struct.pack("!I", val))
            except (ValueError, struct.error):
                pass

        parts = host.split(".")
        num_parts = len(parts)

        # 2-part: a.X (X is 24-bit value for last 3 octets)
        if num_parts == 2:
            try:
                a = SSRFProtector._parse_octet(parts[0])
                b = SSRFProtector._parse_octet(parts[1])
                if 0 <= a <= 255 and 0 <= b <= 0xFFFFFF:
                    val = (a << 24) | b
                    return socket.inet_ntoa(struct.pack("!I", val))
            except (ValueError, struct.error):
                pass

        # 3-part: a.b.X (X is 16-bit value for last 2 octets)
        if num_parts == 3:
            try:
                a = SSRFProtector._parse_octet(parts[0])
                b = SSRFProtector._parse_octet(parts[1])
                c = SSRFProtector._parse_octet(parts[2])
                if 0 <= a <= 255 and 0 <= b <= 255 and 0 <= c <= 0xFFFF:
                    val = (a << 24) | (b << 16) | c
                    return socket.inet_ntoa(struct.pack("!I", val))
            except (ValueError, struct.error):
                pass

        # 4-part: octal/hex/mixed octets
        if num_parts == 4:
            try:
                octets = [SSRFProtector._parse_octet(p) for p in parts]
                if all(0 <= o <= 255 for o in octets):
                    normalized = ".".join(str(o) for o in octets)
                    if normalized != host:
                        return normalized
            except ValueError:
                pass

        return host

    def _is_ip_blocked(self, ip_str: str) -> bool:
        """
        Check if an IP address is in a blocked range.

        Args:
            ip_str: IP address string (IPv4 or IPv6)

        Returns:
            True if IP is blocked, False otherwise
        """
        try:
            ip_addr = ipaddress.ip_address(ip_str)

            for network in self._blocked_ip_networks:
                if ip_addr in network:
                    logger.debug(f"IP {ip_str} is in blocked range {network}")
                    return True

            # Check for IPv6-mapped IPv4 addresses (e.g., ::ffff:169.254.169.254)
            # These bypass IPv4 range checks because they're treated as IPv6
            if isinstance(ip_addr, ipaddress.IPv6Address) and ip_addr.ipv4_mapped:
                mapped_ipv4 = ip_addr.ipv4_mapped
                for network in self._blocked_ip_networks:
                    if (
                        isinstance(network, ipaddress.IPv4Network)
                        and mapped_ipv4 in network
                    ):
                        logger.debug(
                            f"IPv6-mapped IPv4 {ip_str} (mapped to {mapped_ipv4}) is in blocked range {network}"
                        )
                        return True

            return False
        except ValueError:
            # Not a valid IP address
            return False

    def _is_valid_domain_pattern(self, pattern: str) -> bool:
        """
        Validate a wildcard domain pattern.

        Args:
            pattern: Domain pattern to validate (e.g., "*.internal.com", "admin.*")

        Returns:
            True if pattern is valid, False otherwise
        """
        if not pattern or not pattern.strip():
            return False

        # Basic validation: pattern should look like a domain
        # Allow: *.domain.com, admin.*, *.corp.*, etc.
        # Disallow: **, ***, empty parts, etc.

        # Replace wildcards with valid characters for validation
        test_domain = pattern.replace("*", "a").replace("?", "b")

        # Basic domain format check (very lenient)
        # Domain should have at least one dot or be a valid TLD pattern
        if "." not in test_domain and pattern not in ["*", "localhost"]:
            return False

        # Check for invalid consecutive wildcards (*** is invalid, but ** is valid)
        if "***" in pattern:
            return False

        return True

    def _is_domain_blocked(self, domain: str) -> bool:
        """
        Check if a domain is in the blocked list.

        Supports:
        - Exact match: 'metadata.google.internal'
        - Subdomain match: 'api.metadata.google.internal' matches 'metadata.google.internal'
        - Wildcard patterns: '*.internal.com', 'admin.*', '*.corp.*'

        Args:
            domain: Domain name to check

        Returns:
            True if domain is blocked, False otherwise
        """
        if not domain:
            return False

        domain_lower = domain.lower()

        # Check exact match
        if domain_lower in self._blocked_domains:
            return True

        # Check if domain is an IP address
        if self._is_ip_blocked(domain_lower):
            return True

        # Check subdomain matching (e.g., foo.metadata.google.internal)
        for blocked in self._blocked_domains:
            if domain_lower.endswith("." + blocked):
                return True

        # Check wildcard patterns (e.g., *.internal.com, admin.*, *.corp.*)
        for pattern in self._blocked_domain_patterns:
            pattern_lower = pattern.lower()
            if fnmatch.fnmatch(domain_lower, pattern_lower):
                logger.debug(f"Domain '{domain}' matches wildcard pattern '{pattern}'")
                return True

        return False

    def _is_domain_allowed(self, domain: str, port: Optional[int] = None) -> bool:
        """
        Check if a domain is in the allowed list.

        Matching order:
        1. Exact match: 'api.corp.internal' matches 'api.corp.internal'
        2. Subdomain match: 'foo.api.corp.internal' matches if 'api.corp.internal' is allowed
        3. Regex match: '.*\\.example\\.com' matches via re.fullmatch() against hostname
           and hostname:port (for port-aware patterns like 'localhost:19200')

        Args:
            domain: Domain name to check
            port: Optional port number for port-aware regex matching

        Returns:
            True if domain is in allow-list, False otherwise
        """
        if not domain:
            return False

        if not self._allowed_domains_exact and not self._allowed_domain_regexes:
            return False

        domain_lower = domain.lower()

        # 1. Exact match (backward compatible)
        if domain_lower in self._allowed_domains_exact:
            return True

        # 2. Subdomain match (backward compatible)
        for allowed in self._allowed_domains_exact:
            if domain_lower.endswith("." + allowed):
                return True

        # 3. Regex match (new — supports port-aware patterns)
        if self._allowed_domain_regexes:
            targets = [domain_lower]
            if port is not None:
                targets.append(f"{domain_lower}:{port}")

            for regex in self._allowed_domain_regexes:
                for target in targets:
                    if regex.fullmatch(target):
                        logger.debug(
                            f"Domain '{target}' matches allowed regex '{regex.pattern}'"
                        )
                        return True

        return False

    def _match_path_pattern(self, path: str, pattern: str) -> bool:
        """
        Check if a URL path matches a glob pattern.

        Handles:
        - * (matches any chars except /)
        - ** (matches any chars including /)
        - ? (matches single char)
        - Query parameters (included in match)
        - Trailing slashes (normalized)
        - URL encoding (paths are used as-is, not decoded)

        Args:
            path: URL path to check (e.g., "/api/v1/users?page=1")
            pattern: Glob pattern (e.g., "/api/*", "/admin/**", "/health")

        Returns:
            True if path matches pattern, False otherwise
        """
        if not path or not pattern:
            return False

        # Normalize trailing slashes for consistent matching
        # "/admin/" should match "/admin" pattern
        path_normalized = path.rstrip("/") if path != "/" else "/"
        pattern_normalized = pattern.rstrip("/") if pattern != "/" else "/"

        # Convert glob pattern to regex
        # Need to escape special regex chars, then handle our wildcards
        import re as regex_module

        # Escape all regex special chars
        pattern_escaped = regex_module.escape(pattern_normalized)

        # Replace escaped wildcards with regex equivalents
        # ** matches any chars including /
        pattern_escaped = pattern_escaped.replace(r"\*\*", ".*")
        # * matches any chars except /
        pattern_escaped = pattern_escaped.replace(r"\*", "[^/]*")
        # ? matches single char
        pattern_escaped = pattern_escaped.replace(r"\?", ".")

        regex_pattern = "^" + pattern_escaped + "$"

        try:
            return bool(regex_module.match(regex_pattern, path_normalized))
        except regex_module.error:
            # Invalid pattern - fail closed
            logger.warning(f"Invalid path pattern: {pattern}")
            return False

    def _check_url(self, url: str) -> Tuple[bool, str, bool]:
        """
        Check if a URL is an SSRF attack.

        Evaluation order (deny-first approach):
        1. Check immutable core protections (dangerous schemes, metadata endpoints, private IPs)
        2. Check deny-list (additional_blocked_domains only)
        3. Check allow-list (allowed_domains) - can override step 2, NOT step 1
        4. Check path-based rules (can provide granular control on allowed/blocked domains)

        Args:
            url: URL to check

        Returns:
            Tuple of (is_ssrf, reason, is_immutable)
            - is_immutable: True for core protections that cannot be overridden by action mode
        """
        scheme, hostname, path, _, port = self._parse_url(url)

        if not scheme:
            # Failed to parse - fail closed (treat as immutable)
            return True, "failed to parse URL", True

        # IMMUTABLE: Check dangerous schemes (cannot be overridden by allow-list)
        if scheme in self.DANGEROUS_SCHEMES:
            return True, f"dangerous URL scheme '{scheme}://'", True

        if not hostname:
            return False, "", False

        # Normalize alternative IP encodings (hex/octal/decimal) that bypass
        # Python's ipaddress module but are resolved by curl/wget/browsers
        hostname = self._normalize_ip(hostname)

        # IMMUTABLE: Check core metadata endpoints (cannot be overridden by allow-list)
        hostname_lower = hostname.lower()

        if hostname_lower in [
            "metadata.google.internal",
            "metadata.goog",
            "169.254.169.254",
            "fd00:ec2::254",
            "instance-data",
            "100.100.100.200",  # Alibaba Cloud metadata
            "192.0.0.192",  # Oracle Cloud (OCI) metadata
        ]:
            return True, f"blocked domain '{hostname}'", True

        for core_metadata in ["metadata.google.internal", "metadata.goog"]:
            if hostname_lower.endswith("." + core_metadata):
                return True, f"blocked domain '{hostname}'", True

        # IMMUTABLE: Check if hostname is a private IP (cannot be overridden by allow-list)
        if self._is_ip_blocked(hostname):
            return True, f"private IP address '{hostname}'", True

        # Check deny-list (additional_blocked_domains only)
        # This can be overridden by allow-list or path-based rules
        domain_blocked = self._is_domain_blocked(hostname)
        domain_allowed = self._is_domain_allowed(hostname, port=port)

        # Check path-based rules for this domain (if any exist)
        path_rules = self._path_based_rules.get(hostname_lower)

        if domain_blocked and not domain_allowed:
            if path_rules and path_rules.get("allowed_paths"):
                for allowed_pattern in path_rules["allowed_paths"]:
                    if self._match_path_pattern(path, allowed_pattern):
                        logger.debug(
                            f"Domain {hostname} blocked but path {path} allowed by path rule"
                        )
                        if path_rules.get("blocked_paths"):
                            for blocked_pattern in path_rules["blocked_paths"]:
                                if self._match_path_pattern(path, blocked_pattern):
                                    logger.debug(
                                        f"Path {path} in both allowed and blocked lists - blocked wins"
                                    )
                                    return (
                                        True,
                                        f"blocked path '{path}' on domain '{hostname}'",
                                        False,
                                    )
                        return False, "", False

            return True, f"blocked domain '{hostname}'", False

        if path_rules and path_rules.get("blocked_paths"):
            for blocked_pattern in path_rules["blocked_paths"]:
                if self._match_path_pattern(path, blocked_pattern):
                    logger.debug(
                        f"Path {path} blocked by path rule on domain {hostname}"
                    )
                    return True, f"blocked path '{path}' on domain '{hostname}'", False

        return False, "", False

    @staticmethod
    def _format_ssrf_error(
        reason: str, url: str, command: str, immutable_note: str = ""
    ) -> str:
        return (
            f"\n{'='*70}\n"
            f"🚨 BLOCKED BY POLICY\n"
            f"🚨 SSRF PATTERN DETECTED{immutable_note}\n"
            f"{'='*70}\n\n"
            "AI Guardian has detected a Server-Side Request Forgery (SSRF) attempt.\n"
            "This operation has been blocked for security.\n\n"
            f"Detected threat:\n"
            f"  • Reason: {reason}\n"
            f"  • URL: {url}\n"
            f"  • Command: {command[:100]}{'...' if len(command) > 100 else ''}\n\n"
            "SSRF attacks can:\n"
            "  • Exfiltrate cloud credentials from metadata endpoints\n"
            "  • Access internal network services\n"
            "  • Read local files via file:// URLs\n"
            "  • Bypass firewalls and network segmentation\n\n"
            "Blocked resources:\n"
            "  • Private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)\n"
            "  • Cloud metadata endpoints (169.254.169.254, metadata.google.internal)\n"
            "  • Dangerous schemes (file://, gopher://, ftp://, data://)\n"
            "  • Localhost (127.0.0.1, ::1)\n\n"
            "⚠️  NOTE: Pattern-based detection only\n"
            "    ai-guardian blocks explicit URLs in command strings and parameters.\n"
            "    It CANNOT detect network calls inside MCP server implementations.\n\n"
            "For comprehensive SSRF protection, configure:\n"
            "  • Firewall egress rules (block 169.254.169.254)\n"
            "  • Network segmentation (VPC/subnet isolation)\n"
            "  • MCP server sandboxing (Docker with network policies)\n\n"
            "If this is legitimate (e.g., local development):\n"
            "  1. Set action to 'warn' in ~/.config/ai-guardian/ai-guardian.json\n"
            "  2. Enable allow_localhost for local testing\n"
            '  3. Temporarily disable: "ssrf_protection": {"enabled": false}\n\n'
            "Public AWS services (s3.amazonaws.com, etc.) are NOT blocked.\n\n"
            "See: docs/SSRF_PROTECTION.md for details\n"
            f"{'='*70}\n"
        )

    def _compute_url_position(self, command: str, url: str) -> None:
        """Compute line/column of a URL within a command string."""
        url_pos = command.find(url)
        if url_pos < 0:
            stripped = url.strip("'\"")
            url_pos = command.find(stripped)
        if url_pos >= 0:
            self.last_line_number = command[:url_pos].count("\n") + 1
            line_start = command.rfind("\n", 0, url_pos) + 1
            self.last_start_column = url_pos - line_start
            self.last_end_column = url_pos - line_start + len(url)
        else:
            self.last_line_number = 1
            self.last_start_column = None
            self.last_end_column = None

    def check(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a tool call contains SSRF attempts.

        Args:
            tool_name: Name of the tool being called
            tool_input: Tool input parameters

        Returns:
            Tuple of (should_block, error_message)
            - should_block: Whether to block execution (False in log/warn mode, True in block mode)
            - error_message: Formatted error message if should_block is True, warning if warn mode, None if log-only
        """
        self.last_line_number = None
        self.last_start_column = None
        self.last_end_column = None
        self.findings = []

        if not self.enabled:
            return False, None

        if tool_name == "WebFetch":
            url = tool_input.get("url", "")
            if not url:
                return False, None
            try:
                is_ssrf, reason, is_immutable = self._check_url(url)
                if is_ssrf:
                    effective_action = "block" if is_immutable else self.action
                    immutable_note = (
                        " (immutable — cannot be downgraded to warn/log-only)"
                        if is_immutable and self.action != "block"
                        else ""
                    )
                    if effective_action in (
                        "block",
                        "ask",
                    ) or effective_action.startswith("ask"):
                        error_msg = self._format_ssrf_error(
                            reason, url, url, immutable_note
                        )
                        return True, error_msg
                    if effective_action == "warn":
                        return (
                            False,
                            "⚠️  SSRF protection violation detected (warn mode) - execution allowed",
                        )
                    return False, None
                return False, None
            except Exception as e:
                logger.error(f"Error during SSRF check (WebFetch): {e}")
                return True, "SSRF protection error — blocked"

        if tool_name != "Bash":
            return False, None

        command = tool_input.get("command", "")
        if not command or not command.strip():
            return False, None

        try:
            urls = self._extract_urls(command)

            if not urls:
                return False, None

            for url in urls:
                is_ssrf, reason, is_immutable = self._check_url(url)

                if is_ssrf:
                    logger.error(f"SSRF attempt detected: {reason}, URL={url}")
                    self._compute_url_position(command, url)

                    effective_action = "block" if is_immutable else self.action

                    immutable_note = (
                        " (immutable — cannot be downgraded to warn/log-only)"
                        if is_immutable and self.action != "block"
                        else ""
                    )
                    error_msg = self._format_ssrf_error(
                        reason, url, command, immutable_note
                    )

                    self.findings.append(
                        {
                            "matched_text": url,
                            "matched_pattern": reason,
                            "line_number": self.last_line_number,
                            "start_column": self.last_start_column,
                            "end_column": self.last_end_column,
                            "is_immutable": is_immutable,
                            "reason": reason,
                            "error_message": error_msg,
                            "effective_action": effective_action,
                        }
                    )

            if not self.findings:
                return False, None

            first = self.findings[0]
            self.last_line_number = first["line_number"]
            self.last_start_column = first["start_column"]
            self.last_end_column = first["end_column"]

            effective_action = first["effective_action"]

            if effective_action.startswith("ask"):
                return True, first["error_message"]

            if effective_action == "warn":
                url = first["matched_text"]
                reason = first["reason"]
                logger.warning(
                    f"SSRF detected (warn mode): {reason}, URL={url} - execution allowed"
                )
                return (
                    False,
                    "⚠️  SSRF protection violation detected (warn mode) - execution allowed",
                )

            elif effective_action == "log-only":
                url = first["matched_text"]
                reason = first["reason"]
                logger.warning(
                    f"SSRF detected (log-only mode): {reason}, URL={url} - execution allowed"
                )
                return False, None

            else:
                return True, first["error_message"]

        except Exception as e:
            # Fail-closed: block on errors to prevent bypasses
            logger.error(f"Error during SSRF check: {e}")
            logger.debug("Failing closed - blocking operation")

            error_msg = (
                f"\n{'='*70}\n"
                f"🚨 BLOCKED BY POLICY\n"
                f"{'='*70}\n\n"
                f"SSRF protection encountered an error and blocked this operation.\n"
                f"Error: {str(e)}\n\n"
                f"{'='*70}\n"
            )

            return True, error_msg


def check_ssrf(
    tool_name: str, tool_input: Dict[str, Any], config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to check for SSRF attacks.

    Args:
        tool_name: Name of the tool being called
        tool_input: Tool input parameters
        config: Optional configuration dictionary

    Returns:
        Tuple of (should_block, error_message)
        - should_block: Whether to block execution
        - error_message: Error/warning message if detected
    """
    protector = SSRFProtector(config)
    return protector.check(tool_name, tool_input)
