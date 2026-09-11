# SSRF Protection

Server-Side Request Forgery (SSRF) protection prevents AI agents from accessing private networks, cloud metadata endpoints, and dangerous URL schemes.

## ⚠️ Important Limitations

ai-guardian's SSRF protection is **pattern-based filtering**, not comprehensive network security.

### What It CAN Protect Against

✅ **Bash commands with explicit URLs**:
```bash
curl http://169.254.169.254/metadata  # ❌ BLOCKED
wget http://192.168.1.1/admin         # ❌ BLOCKED
```

✅ **Tool parameters containing private IPs**:
```python
WebFetch(url="http://169.254.169.254")      # ❌ BLOCKED
mcp__custom__fetch(url="http://internal")  # ❌ BLOCKED
```

### What It CANNOT Protect Against

❌ **MCP server internal calls**:
```python
# ai-guardian sees: source="web"
# But MCP server internally calls: http://169.254.169.254
mcp__notebooklm__research_start(source="web")  # ✅ ALLOWED (can't see internal call)
```

❌ **Other undetectable scenarios**:
- Dynamic URL construction inside tools
- HTTP redirects after tool execution starts
- IDE's own network requests
- Binary protocol inspection

### Why These Limitations Exist

ai-guardian is **hook-based**, not a network proxy:
- Hooks fire **before** tool execution (PreToolUse)
- We see command strings and tool parameters
- We do NOT see runtime network traffic
- MCP servers execute **after** the hook approves them

**Architecture**: ai-guardian cannot intercept network calls - it can only inspect text strings.

### For Comprehensive SSRF Protection

ai-guardian provides **pattern-based filtering only**. For complete protection:

**1. Network-level controls** (REQUIRED):
```bash
# Firewall rules blocking metadata endpoints
sudo iptables -A OUTPUT -d 169.254.169.254 -j REJECT
sudo iptables -A OUTPUT -d 10.0.0.0/8 -j REJECT

# Cloud provider network policies
# AWS: VPC egress rules
# GCP: Firewall rules
# Azure: Network Security Groups
```

**2. MCP server sandboxing** (RECOMMENDED):
- Run MCP servers in Docker containers with network policies
- Use VMs with restricted network access
- Only install MCP servers from trusted sources

**3. Supply chain verification** (PLANNED):
- Verify MCP server signatures
- Code review before installation
- Allowlist trusted publishers only

### Bottom Line

> ai-guardian catches obvious SSRF attempts in command strings but cannot replace network-level security. Think of it as a "basic syntax check" that prevents copy-paste mistakes, not comprehensive network protection.

---

## Overview

SSRF attacks allow attackers to make the AI agent send requests to unintended locations:
- **Credential theft**: Access cloud metadata endpoints to steal AWS/GCP/Azure credentials
- **Internal network scanning**: Probe private network services
- **Local file access**: Read local files via file:// URLs
- **Firewall bypass**: Access internal services from outside the network

AI Guardian's SSRF protection blocks these attacks by checking all Bash commands and tool parameters for dangerous URLs before execution.

**Note**: This is pattern-based filtering. See [Important Limitations](#️-important-limitations) above for what it can and cannot protect against.

## Core Protections (Immutable - Pattern Matching)

These protections **CANNOT be disabled** via configuration:

### Private IP Ranges (RFC 1918 + Loopback + Link-local)

**IPv4:**
- `10.0.0.0/8` - Private network (Class A)
- `172.16.0.0/12` - Private network (Class B)
- `192.168.0.0/16` - Private network (Class C)
- `127.0.0.0/8` - Loopback (localhost)
- `169.254.0.0/16` - Link-local (AWS/Azure metadata)

**IPv6:**
- `::1/128` - Loopback
- `fc00::/7` - Unique local addresses (private network)
- `fe80::/10` - Link-local addresses

### Cloud Metadata Endpoints

**AWS:**
- `169.254.169.254` - IPv4 metadata endpoint
- `fd00:ec2::254` - IPv6 metadata endpoint
- `instance-data` - Instance metadata service

**Google Cloud Platform:**
- `metadata.google.internal` - Primary metadata endpoint
- `metadata.goog` - Alternative metadata endpoint

**Azure:**
- `169.254.169.254` - Shared with AWS (same IP range)

### Dangerous URL Schemes

- `file://` - Local filesystem access
- `gopher://` - Legacy protocol (attack vector)
- `ftp://` - File transfer protocol
- `ftps://` - Secure FTP
- `data://` - Data URLs (can encode arbitrary content)
- `dict://` - DICT protocol
- `ldap://` - LDAP protocol
- `ldaps://` - Secure LDAP

## Configuration

### Basic Configuration

Default configuration (`~/.config/ai-guardian/ai-guardian.json`):

```json
{
  "ssrf_protection": {
    "enabled": true,
    "action": "block"
  }
}
```

### Full Configuration

```json
{
  "ssrf_protection": {
    "enabled": true,
    "action": "block",
    "additional_blocked_ips": [
      "203.0.113.0/24",
      "198.51.100.0/24"
    ],
    "additional_blocked_domains": [
      "internal.example.com",
      "admin.local",
      "*.corp.internal"
    ],
    "allowed_domains": [
      "api.corp.internal",
      "public.staging.example.com"
    ],
    "allow_localhost": false
  }
}
```

### Configuration Options

#### `enabled` (boolean, default: true)

Enable or disable SSRF protection entirely.

**Example:**
```json
{
  "ssrf_protection": {
    "enabled": false
  }
}
```

**Time-based enabling** (NEW in v1.5.0):
```json
{
  "ssrf_protection": {
    "enabled": {
      "value": false,
      "valid_until": "2026-12-31T23:59:59Z"
    }
  }
}
```

#### `action` (string, default: "block")

Action to take when SSRF is detected:
- `"block"` - Prevent execution and show error message (recommended)
- `"warn"` - Log violation, show warning to user, but allow execution
- `"log-only"` - Log violation silently without user warning, allow execution

**Block mode (default, recommended):**
```json
{
  "ssrf_protection": {
    "action": "block"
  }
}
```

**Warn mode (for testing/debugging):**
```json
{
  "ssrf_protection": {
    "action": "warn"
  }
}
```

**Log-only mode (for monitoring without blocking):**
```json
{
  "ssrf_protection": {
    "action": "log-only"
  }
}
```

#### `additional_blocked_ips` (array, default: [])

Additional IP addresses or CIDR ranges to block beyond core protections.

**Supports:**
- Single IPv4 addresses: `"203.0.113.5"`
- IPv4 CIDR ranges: `"203.0.113.0/24"`
- Single IPv6 addresses: `"2001:db8::1"`
- IPv6 CIDR ranges: `"2001:db8::/32"`

**Example:**
```json
{
  "ssrf_protection": {
    "additional_blocked_ips": [
      "203.0.113.0/24",
      "198.51.100.0/24",
      "2001:db8::/32"
    ]
  }
}
```

#### `additional_blocked_domains` (array, default: [])

Additional domain names to block beyond core protections.

**Supports:**
- **Exact domain**: `"internal.example.com"` - Blocks `internal.example.com` exactly
- **Subdomain matching**: `"internal.example.com"` - Also blocks `api.internal.example.com`, `db.internal.example.com`
- **Wildcard patterns** (NEW in v1.5.0): Use `*` and `?` for flexible pattern matching

**Wildcard Pattern Syntax:**
- `*` - Match zero or more characters (within a domain component)
- `?` - Match exactly one character
- Case-insensitive matching

**Wildcard Pattern Examples:**

```json
{
  "ssrf_protection": {
    "additional_blocked_domains": [
      // Exact domain + subdomain matching (traditional)
      "internal.example.com",
      
      // Wildcard patterns (NEW in v1.5.0)
      "*.internal.com",      // Block all .internal.com domains (api.internal.com, db.internal.com)
      "admin.*",             // Block admin.* with any suffix (admin.example.com, admin.local)
      "*.corp.*",            // Block all .corp. domains (api.corp.internal, db.corp.example.com)
      "metadata.*",          // Block all metadata.* endpoints (metadata.aws.com, metadata.google.internal)
      "*.local",             // Block all .local domains (test.local, dev.local)
      "test?.example.com"    // Block test1.example.com, test2.example.com, testa.example.com
    ]
  }
}
```

**Use Cases for Wildcard Patterns:**

1. **Block entire TLDs**: `*.internal`, `*.local`, `*.corp`
   ```json
   "additional_blocked_domains": ["*.internal", "*.local"]
   ```

2. **Block subdomains**: `*.admin.example.com`, `*.staging.*`
   ```json
   "additional_blocked_domains": ["*.admin.example.com"]
   ```

3. **Block naming patterns**: `metadata.*`, `admin.*`, `internal.*`
   ```json
   "additional_blocked_domains": ["metadata.*", "admin.*"]
   ```

4. **Enterprise policies**: Block all internal domains with single pattern
   ```json
   "additional_blocked_domains": ["*.corp.internal"]
   ```

**Pattern Matching Behavior:**

- `*.internal.com` matches:
  - ✅ `api.internal.com`
  - ✅ `db.internal.com`
  - ✅ `cache.internal.com`
  - ❌ `example.com`
  - ❌ `internal.com` (no prefix)

- `admin.*` matches:
  - ✅ `admin.example.com`
  - ✅ `admin.corp.internal`
  - ✅ `admin.local`
  - ❌ `api.example.com`

- `*.corp.*` matches:
  - ✅ `api.corp.internal`
  - ✅ `db.corp.example.com`
  - ❌ `corp.internal` (no prefix)
  - ❌ `api.example.com`

**Traditional Example (exact + subdomain matching):**
```json
{
  "ssrf_protection": {
    "additional_blocked_domains": [
      "internal.example.com",
      "admin.local",
      "corp.internal"
    ]
  }
}
```

#### `allowed_domains` (array, default: []) - NEW in v1.5.0

**Issue #252**: Domain allow-list to override `additional_blocked_domains` blocks while maintaining core protections.

**Evaluation order (deny-first approach)**:
1. ✅ Check immutable core protections (metadata endpoints, dangerous schemes, private IPs)
2. ❌ Check deny-list (`additional_blocked_domains`)
3. ✅ Check allow-list (`allowed_domains`) - can override step 2, **NOT step 1**

**Supports:**
- Exact domain: `"api.corp.internal"`
- Subdomain matching: Allows `v1.api.corp.internal` if `api.corp.internal` is allowed

**Use cases:**
1. **Internal APIs**: Allow specific internal APIs while blocking other internal domains
2. **Development servers**: Allow specific dev/staging servers without allowing all localhost
3. **Partner services**: Allow specific partner domains on restricted networks
4. **Granular control**: Override broad domain blocks with specific exceptions

**Example:**
```json
{
  "ssrf_protection": {
    "additional_blocked_domains": [
      "api.corp.internal",
      "admin.corp.internal",
      "secret.corp.internal"
    ],
    "allowed_domains": [
      "api.corp.internal",
      "public.corp.internal"
    ]
  }
}
```

**Result:**
- ✅ `http://api.corp.internal` - ALLOWED (in allow-list, overrides deny-list)
- ✅ `http://public.corp.internal` - ALLOWED (in allow-list)
- ✅ `http://v1.api.corp.internal` - ALLOWED (subdomain of allowed domain)
- ❌ `http://admin.corp.internal` - BLOCKED (in deny-list, not in allow-list)
- ❌ `http://secret.corp.internal` - BLOCKED (in deny-list, not in allow-list)

**⚠️ CRITICAL LIMITATION - Cannot Override Immutable Protections:**

The allow-list **CANNOT** override these immutable core protections:
- ❌ **Cloud metadata endpoints**: `169.254.169.254`, `metadata.google.internal`, `metadata.goog`, `fd00:ec2::254`
- ❌ **Private IP ranges**: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`
- ❌ **IPv6 private**: `::1`, `fc00::/7`, `fe80::/10`
- ❌ **Dangerous schemes**: `file://`, `gopher://`, `ftp://`, `data://`, `dict://`, `ldap://`

**Example - Immutable protections cannot be overridden:**
```json
{
  "ssrf_protection": {
    "allowed_domains": [
      "metadata.google.internal",  // ❌ Will NOT work - still blocked
      "169.254.169.254"              // ❌ Will NOT work - still blocked
    ]
  }
}
```

**Security best practices:**
- Use allow-lists sparingly and only for known-safe domains
- Document the business reason for each allowed domain
- Review allow-lists regularly and remove unused entries
- Prefer network-level controls for critical infrastructure
- Test in staging before deploying to production

#### `allow_localhost` (boolean, default: false)

Allow access to localhost (127.0.0.1, ::1) for local development.

**Use case**: Local development servers, testing environments.

**Example:**
```json
{
  "ssrf_protection": {
    "allow_localhost": true
  }
}
```

**Security warning**: Only enable `allow_localhost` in development environments, never in production.

## Examples

### Example 1: AWS Metadata Endpoint Attack (BLOCKED)

```bash
# Attacker attempts to steal AWS credentials
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

**AI Guardian blocks this with:**
```
🚨 BLOCKED BY POLICY
🚨 SSRF ATTACK DETECTED

Detected threat:
  • Reason: private IP address '169.254.169.254'
  • URL: http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

### Example 2: Private Network Scanning (BLOCKED)

```bash
# Attacker attempts to scan internal network
curl http://192.168.1.1/admin
```

**AI Guardian blocks this with:**
```
🚨 BLOCKED BY POLICY
🚨 SSRF ATTACK DETECTED

Detected threat:
  • Reason: private IP address '192.168.1.1'
  • URL: http://192.168.1.1/admin
```

### Example 3: File Access via file:// URL (BLOCKED)

```bash
# Attacker attempts to read /etc/passwd
curl file:///etc/passwd
```

**AI Guardian blocks this with:**
```
🚨 BLOCKED BY POLICY
🚨 SSRF ATTACK DETECTED

Detected threat:
  • Reason: dangerous URL scheme 'file://'
  • URL: file:///etc/passwd
```

### Example 4: Public AWS Service (ALLOWED)

```bash
# Legitimate access to public S3 bucket
curl https://s3.amazonaws.com/my-bucket/file.txt

# Legitimate AWS CLI command
aws s3 ls s3://my-bucket/
```

**AI Guardian allows these** - public AWS services are NOT blocked.

### Example 5: Local Development (ALLOWED with config)

With `allow_localhost: true`:

```bash
# Access local development server
curl http://localhost:3000/api/users
```

**AI Guardian allows this** when `allow_localhost` is enabled.

Without `allow_localhost` (default), this would be blocked.

## False Positives

SSRF protection is designed to minimize false positives:

### NOT Blocked (Legitimate Use)

✅ **Public IP addresses:**
- `curl http://8.8.8.8` (Google DNS)
- `curl https://1.1.1.1` (Cloudflare DNS)

✅ **Public AWS services:**
- `curl https://s3.amazonaws.com/bucket/file.txt`
- `aws ec2 describe-instances`
- `aws s3 ls`

✅ **HTTPS URLs to public domains:**
- `curl https://api.github.com/repos`
- `wget https://releases.ubuntu.com/22.04/ubuntu-22.04.3-desktop-amd64.iso`

✅ **Commands without URLs:**
- `ls -la /var/log`
- `grep "error" /tmp/app.log`
- `find . -name "*.py"`

### Blocked (Security Threats)

❌ **Private network access:**
- `curl http://10.0.0.1`
- `wget http://192.168.1.1/admin`

❌ **Metadata endpoints:**
- `curl http://169.254.169.254/latest/meta-data/`
- `curl http://metadata.google.internal/`

❌ **Dangerous schemes:**
- `curl file:///etc/passwd`
- `curl gopher://internal.server`

❌ **Localhost (by default):**
- `curl http://localhost:8080`
- `wget http://127.0.0.1:3000`

## Legitimate AWS Access vs Attacks

**Key distinction**: IP address vs domain name

### Public AWS Services (ALLOWED)

```bash
# ✅ Public S3 endpoint (domain name, resolves to public IP)
curl https://s3.amazonaws.com/my-bucket/file.txt

# ✅ AWS CLI (uses public AWS APIs)
aws ec2 describe-instances
aws s3 ls s3://my-bucket/
```

### Metadata Endpoints (BLOCKED)

```bash
# ❌ AWS metadata endpoint (private IP, credential theft)
curl http://169.254.169.254/latest/meta-data/

# ❌ Direct access to instance metadata
curl http://169.254.169.254/latest/user-data
```

**Why the difference?**
- Public AWS services use public domain names (s3.amazonaws.com) that resolve to public IPs
- Metadata endpoints use private IP address (169.254.169.254) for instance-local access only
- Legitimate AWS usage never requires accessing 169.254.169.254 from Bash commands

## Comprehensive SSRF Protection with OpenShell

For production deployments, ai-guardian's pattern-based SSRF detection should be complemented with **runtime sandboxing** using [OpenShell](https://github.com/NVIDIA/OpenShell).

### Why OpenShell?

OpenShell provides **real network isolation** via policy-driven sandboxing:
- Intercepts ALL outbound network calls (not just command strings)
- Policy engine operates from application layer to kernel
- Hot-reloadable policies without container restarts
- Works with Claude Code, GitHub Copilot, and other AI agents

### Architecture Comparison

**ai-guardian** (Hook-Based):
```
User → PreToolUse Hook → Pattern Match → Block if dangerous URL
       ↓
       Tool Executes → ❌ Cannot see internal network calls
```

**OpenShell** (Runtime Sandbox):
```
User → Tool Executes → Network Call → Policy Engine → Block if violates policy
                                      ↑
                                      Intercepts at kernel level
```

### Example Policy

OpenShell uses declarative YAML for network policies:

```yaml
# openshell-github-readwrite-policy.yaml
network:
  outbound:
    # Block metadata endpoints
    - action: deny
      destination: "169.254.169.254"
    
    # Block private IPs
    - action: deny
      destination: "10.0.0.0/8"
    - action: deny
      destination: "172.16.0.0/12"
    - action: deny
      destination: "192.168.0.0/16"
    
    # Allow specific public APIs
    - action: allow
      destination: "api.github.com"
      methods: [GET, POST]
    - action: allow
      destination: "*.googleapis.com"
    
    # Default deny
    - action: deny
      destination: "*"
```

### Setup

```bash
# Install OpenShell
docker pull ghcr.io/nvidia/openshell:latest

# Run agent in OpenShell sandbox
openshell run --policy openshell-github-readwrite-policy.yaml -- claude-code
```

### Defense in Depth Strategy

**Layer 1: ai-guardian** (IDE hooks)
- Catches obvious mistakes in Bash commands
- Fast, lightweight pattern matching
- Educational value

**Layer 2: OpenShell** (Runtime sandbox)
- Comprehensive network isolation
- Policy-driven enforcement
- Catches everything ai-guardian misses

**Layer 3: Infrastructure** (Network controls)
- Firewall egress rules
- VPC/subnet isolation
- Cloud provider network policies

### When to Use OpenShell

**Required for**:
- ✅ Production agent deployments
- ✅ Zero-trust environments
- ✅ Compliance requirements (SOC 2, HIPAA)
- ✅ Multi-tenant systems

**Optional for**:
- ⚠️ Local development (overhead acceptable)
- ⚠️ High-security development teams
- ⚠️ Testing untrusted MCP servers

### Learn More

- [OpenShell GitHub](https://github.com/NVIDIA/OpenShell)
- [OpenShell Documentation](https://nvidia.github.io/OpenShell/)
- Compatible with: Claude Code, GitHub Copilot, OpenCode

---

## Edge Cases and FAQs

### Q: Can I disable SSRF protection for specific commands?

**A:** Not currently. SSRF protection applies to all Bash commands. Use action modes instead:
- `"action": "warn"` - Shows warning but allows execution
- `"action": "log-only"` - Logs but doesn't notify user

### Q: What about DNS rebinding attacks?

**A:** AI Guardian does NOT perform DNS resolution (by design). This avoids:
- Performance overhead
- Network dependencies
- TOCTOU (Time-of-Check-Time-of-Use) issues

This means a public domain that resolves to a private IP would bypass protection. This is a known limitation. For complete protection, combine with:
- Network egress filtering
- DNS filtering
- Runtime monitoring

### Q: Can I allow specific private IPs?

**A:** Core protections cannot be disabled. However, you can use action modes:
- Set `"allow_localhost": true` to allow localhost specifically
- Set `"action": "warn"` globally and approve on a case-by-case basis

### Q: What about IPv6 metadata endpoints?

**A:** Fully supported. AI Guardian blocks:
- `fd00:ec2::254` (AWS IPv6 metadata)
- All IPv6 private ranges (fc00::/7, fe80::/10)
- IPv6 loopback (::1)

### Q: Performance impact?

**A:** <1ms overhead per Bash command. URL extraction and IP validation are highly optimized.

### Q: Can attackers bypass this?

**Known bypass vectors:**
- DNS rebinding (domain resolves to private IP)
- URL redirects (server redirects to metadata endpoint)
- URL shorteners (obscure destination)

**Mitigations:**
- AI Guardian blocks direct access (first line of defense)
- Combine with network egress filtering (second line)
- Use runtime monitoring (third line)

## Credits

SSRF protection inspired by:
- **Hermes Security Framework**: https://github.com/fullsend-ai/experiments/tree/main/hermes-security-patterns
- Validated against real-world SSRF attack payloads from Hermes testing

## Related Documentation

- [README.md](../README.md) - Main documentation
- [CHANGELOG.md](../../CHANGELOG.md) - Version history
- [Tool Policy](../TOOL_POLICY.md) - Permission system
- [Prompt Injection](PROMPT_INJECTION.md) - Prompt injection detection

## Security Notes

**Defense in Depth**: SSRF protection is ONE layer of security. Combine with:
- ✅ Network egress filtering
- ✅ DNS filtering
- ✅ Runtime monitoring
- ✅ Principle of least privilege
- ✅ Code review

**Pattern-Based Filtering Limitations**:
- Hook-based: Only inspects command strings and tool parameters
- Cannot see MCP server internal network calls
- Cannot intercept runtime network traffic
- Does not perform DNS resolution (by design)
- Cannot detect URL redirects during execution
- Cannot detect DNS rebinding attacks
- Cannot detect dynamic URL construction inside tools

**What This Means**:
- ai-guardian catches obvious SSRF attempts in command strings
- It does NOT provide comprehensive network security
- For production deployments, use network-level controls and runtime sandboxing (see OpenShell above)

**Fail-Closed**: SSRF protection fails closed on errors - if URL parsing fails, the command is blocked.

**No Warranty**: This software is provided "AS IS" under the Apache 2.0 License.
