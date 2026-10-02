# MCP Security Advisor Server

AI Guardian includes an MCP (Model Context Protocol) server that exposes read-only security tools to AI agents. The AI can check security **before** acting — instead of being blocked by hooks and retrying.

## Three-Layer Security Model

| Layer | Role | Trust |
|-------|------|-------|
| **MCP server** | Tools the AI *can* use | Advisory — AI chooses to use them |
| **Skill (instructions)** | Guidance for *when* to use them | Loaded automatically on MCP connect |
| **Hooks** | Enforcement if AI doesn't check | Mandatory — can't bypass |

## Setup

### Install with hooks

```bash
ai-guardian setup --ide claude
ai-guardian setup --ide cursor
ai-guardian setup --ide pi
```

The MCP server is installed by default during setup. Use `--no-mcp` to skip.
Cursor desktop and the local Cursor CLI share the local user configuration
(`~/.cursor/hooks.json` and `~/.cursor/mcp.json`). A project
`.cursor/mcp.json` is also supported for local Cursor workspaces, but it is not
the MCP registration mechanism for Cursor Cloud Agents. Cloud MCP servers must
be configured through Cursor's Cloud Agents dashboard/team settings or supplied
through the Cloud Agents API. For a Cursor Cloud workspace, select the project
explicitly to install only the project hooks:

```bash
ai-guardian setup --ide cursor --project /path/to/workspace
```

The tray exposes the same operation as **Cursor Cloud (project setup)...**;
it does not modify the project's `.cursor/mcp.json`. Without `--project`, setup
remains user/desktop-scoped.

Pi has no native MCP configuration file. Pi setup creates the managed extension
at `~/.pi/agent/extensions/ai-guardian/` (or the project
`.pi/extensions/ai-guardian/`) with a pinned
`@modelcontextprotocol/sdk` dependency. Setup installs that dependency in the
managed directory with `npm install --ignore-scripts --no-audit --no-fund` when
Node.js/npm is available. If installation fails, setup leaves the hook bridge in
place and reports the retry command; `--no-mcp` installs the hook-only variant
without the bridge. The extension launches the resolved local `ai-guardian
mcp-server`, verifies the server identity before registering tools, and preserves
the existing signed identity/nonce attestation. A failed attestation exposes no
MCP tools.

### Manual setup

Existing manual registrations are migrated automatically the first time the
server starts after this security feature is installed. Package upgrades also
refresh a valid identity record, so setup does not need to be rerun.

`ai-guardian doctor` and IDE setup health checks report the local MCP
registration state for supported clients without starting the server. A
`healthy` registration means the client config contains an enabled
`ai-guardian` entry, or (for Pi) the managed extension, pinned SDK, and identity
registration are present; `missing`, `disabled`, and `invalid` states identify
configuration problems separately from runtime identity failures.

Add to `~/.claude.json` (or `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "ai-guardian": {
      "command": "ai-guardian",
      "args": ["mcp-server"]
    }
  }
}
```

### Via uvx (no install needed)

```json
{
  "mcpServers": {
    "ai-guardian": {
      "command": "uvx",
      "args": ["ai-guardian", "mcp-server"]
    }
  }
}
```

For a manual Cursor registration, add the following to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ai-guardian": {
      "type": "stdio",
      "command": "ai-guardian",
      "args": ["mcp-server"]
    }
  }
}
```

### Multi-IDE support

| IDE | MCP config file |
|-----|----------------|
| Claude Code | `~/.claude/settings.json` or `~/.claude.json` → `mcpServers` |
| Cursor desktop / CLI | `~/.cursor/mcp.json` (`type: "stdio"`) |
| Windsurf | `~/.windsurf/mcp.json` |

## Enable / Disable

The MCP server is controlled by IDE config. Install/uninstall via:

```bash
ai-guardian setup --ide claude             # Install (default)
ai-guardian setup --ide claude --no-mcp   # Uninstall
ai-guardian setup --ide pi --no-mcp       # Keep Pi hooks, omit MCP bridge
```

## Proactive Level

Controls how aggressively the AI uses proactive security checks. Higher levels add latency and token usage (each check adds tool call/result pairs to the conversation context).

| Level | Behavior | Best for |
|-------|----------|----------|
| **low** (default) | Check only when user asks or after a block | Most users — hooks enforce everything |
| **medium** | Also check unfamiliar paths and suspicious commands | Teams wanting fewer blocked-and-retry cycles |
| **high** | Check every file access and command | High-security environments |
| **paused** | Skip proactive MCP action-gating checks; hooks continue enforcing security | Temporarily paused daemon or explicit proactive pause |

Configure via:
- `ai-guardian.json`: `"mcp_server": {"proactive_level": "low"}`
- Tray menu: MCP submenu → Proactive radio buttons
- TUI/Web Console: MCP Servers panel → Proactive Level selector

An active global daemon pause or applicable directory pause temporarily overrides
the configured `low`, `medium`, or `high` level and reports the effective level
as `paused`. The configured level is not changed and resumes automatically when
the pause expires or the daemon resumes. Hooks remain the mandatory enforcement
layer during every MCP pause.

## Tools

### Security Checks (Proactive)

| Tool | Parameters | Returns | Purpose |
|------|-----------|---------|---------|
| `check_path` | `path`, `operation?`, `project_dir?` | `allowed` / `denied` / `not_found` / `paused` + policy decision | Is this path protected? |
| `check_command` | `command`, `project_dir?` | `allowed` / `blocked` / `paused` + reason + policy decision | Would this command be blocked? |
| `check_mcp_trust` | `server_name`, `project_dir?` | `trusted` / `untrusted` / `paused` + policy decision | Is this MCP server allowed? |
| `sanitize_text` | `text` | sanitized text + redaction count | Redact secrets/PII from text |
| `check_annotations` | `file_path` | valid/invalid + warnings | Are annotation pairs matched? |

`operation` (v1.12.0+): `"read"` (default), `"write"`, or `"edit"`. Checks whether the specific operation type is allowed on the path.

Security check and violation responses include the normalized `policy_decision`
object when available. Its versioned, redacted shape is documented in
[`VIOLATION_LOGGING.md`](VIOLATION_LOGGING.md#unified-policy-decision).

When an action-gating check returns `status: "paused"`, it also returns
`skipped: true`, `reason: "proactive_checks_paused"`, and a message explaining
that hooks remain active. No new allow/block/trust decision is evaluated. Query,
diagnostic, and reporting tools remain available while action-gating is paused.

`check_command` evaluates the project configuration used by the caller when
`project_dir` is supplied. Integrations may provide the same context through
`AI_GUARDIAN_PROJECT_DIR`. If neither is available, the MCP server's launch
directory is used. The MCP process captures the trusted developer-session
setting once at startup, matching the daemon's snapshot behavior rather than
rereading that setting for each request.

`get_config` accepts the same optional `project_dir` context when reporting the
effective proactive level, so directory-scoped pauses are reflected consistently
with action-gating checks.

Command-check reason categories are intentionally stable and do not expose
matched rules or patterns:

| Reason | Meaning |
|--------|---------|
| `command_policy_denied` | A command protection policy blocked the command |
| `permission_denied` | An ordinary tool permission blocked the command |
| `identity_failure` | The running built-in MCP process is not currently verified |
| `policy_check_error` | The policy check could not be completed |

Scanner-specific categories such as `secret_detected` and `ssrf_detected` may
also be returned. An MCP startup failure reports `startup_failure` or
`identity_failure` on stderr and exposes no tools.

### Information (Query)

| Tool | Parameters | Returns | Purpose |
|------|-----------|---------|---------|
| `get_violations` | `violation_type?`, `limit?` | violation list with file:line and policy decision | Recent security violations |
| `get_config` | `project_dir?` | feature enabled/disabled map | Current security posture |
| `get_scanner_status` | — | installed scanners + versions | Scanner inventory |
| `get_scanner_supported` | — | all available scanners | What can be installed |
| `get_patterns_list` | — | category names + counts | Active detection patterns |
| `get_metrics` | `since_days?` | stats by type/severity | Violation statistics |
| `doctor` | — | check results with fix hints | Health check |

### Support Bundle

| Tool | Parameters | Returns | Purpose |
|------|-----------|---------|---------|
| `prepare_support_bundle` | — | bundle_id, temp_path, file list | Create sanitized diagnostics |
| `send_support_bundle` | `bundle_id` | sent/error | Send after user review |

## Resources

| URI | Content |
|-----|---------|
| `ai-guardian://security-posture` | Feature status, action modes, scanner status |
| `ai-guardian://protected-paths` | Directories with `.ai-read-deny` markers |
| `ai-guardian://recent-violations` | Last 10 violations |

## Security Model

The MCP server is a **security advisor, not a security map**. It answers yes/no — it does not expose rules, patterns, or allowlists that could be used to find gaps.

| Tool | Exposes | Does NOT expose |
|------|---------|-----------------|
| `check_path` | allowed/denied for operation | Which rule matched, full rules list |
| `check_command` | allowed/blocked + reason category | Which pattern matched, the deny list |
| `get_config` | Feature on/off, action mode | Allowlist patterns, regex, rule details |
| `get_violations` | Type, timestamp, file:line, action, normalized policy decision | Matched pattern internals or raw content |
| `get_patterns_list` | Category names and counts | Regex patterns |

### Self-protection

- The `mcp__ai-guardian__*` namespace is not an identity proof. A same-name or
  otherwise unverified MCP registration is blocked before permission rules are
  evaluated.
- Setup records the canonical AI Guardian package, executable, entry point, and
  installation hash in a signed local identity record. Existing, manual, and
  `uvx` registrations create or migrate that record automatically at startup.
- Each AI Guardian MCP process performs a nonce-based attestation and receives a
  short-lived process-bound session. Hook policy checks require a live verified
  session before allowing built-in MCP tools. Once verified, the built-in
  security advisor is allowed independently of ordinary host MCP permission
  rules, including when Pi routes a bridge call through its tool hook.
- Tampered, invalid, expired, or orphaned identity data fails closed with an
  MCP identity verification error. Missing records and valid stale records are
  migrated automatically; permission rules cannot override this gate or block a
  successfully verified built-in server.
- All other MCP servers require explicit allow rules in the permissions config
- The MCP server process runs separately from the daemon — if the daemon is unavailable, MCP tools still work. Project context is supplied explicitly when the client can provide it; otherwise the server launch directory is used.

## Support Bundle Flow

The support bundle uses a two-step process with user approval:

1. **Prepare**: `prepare_support_bundle()` creates a sanitized temp directory (protected by `.ai-read-deny`)
2. **Review**: AI shows the file list with redaction counts and the temp path — the user reviews and deletes unwanted files
3. **Send**: After user approval, `send_support_bundle(bundle_id)` sends remaining files to the configured destination

Sanitized files include: config (tokens redacted), violations (paths truncated), metrics (aggregate only), doctor results, system info, and full log (secrets/PII redacted).

Default destination: `~/.local/state/ai-guardian/support-bundles/`. Configure via `support.export_destination` (local path, `s3://bucket/prefix/`, or `gs://bucket-name/`).

### CLI Alternative

The same prepare/send workflow is available via the CLI for direct use without an AI agent:

```bash
ai-guardian support prepare                    # Prepare bundle, show file summary
ai-guardian support send                       # Send last prepared bundle (with confirmation)
ai-guardian support send --prepare --yes       # One-shot: prepare + send (for CI)
ai-guardian support status                     # Show destination, auth, pending bundles
ai-guardian support prepare --output ./bundle  # Save to specific directory
ai-guardian support prepare --no-log           # Exclude log file
```

Both interfaces share the same underlying logic — same sanitization, same destinations, same bundle format.

## Configuration

```json
{
  "mcp_server": {
    "proactive_level": "low"
  },
  "support": {
    "export_destination": "",
    "auth": {
      "method": "none",
      "token_env": ""
    },
    "bundle_ttl_minutes": 30
  }
}
```

## Requirements

- **Direct install** (`ai-guardian mcp-server`): Python >=3.10.
- **Via uvx** (`uvx ai-guardian mcp-server`): uvx manages an isolated Python environment. This can be used when the host runtime cannot be upgraded, but the `1.19.x` release line is the last AI Guardian release compatible with Python 3.9.
- For S3 export: `uv pip install boto3` (or `pip install boto3`)
- For GCS export: Google Application Default Credentials (`gcloud auth application-default login`) or `GOOGLE_APPLICATION_CREDENTIALS` env var. No extra packages needed.

## MCP Security Scanning

Audit MCP server configurations and source code for security issues. This is separate from the MCP security *advisor* server above — scanning is a CLI/Console feature for reviewing the security of your MCP server setup.

### CLI Commands

```bash
ai-guardian mcp list              # List servers with trust status
ai-guardian mcp audit             # Config audit (credential exposure, npx -y, unpinned packages)
ai-guardian mcp scan              # Deep source code scan (all servers)
ai-guardian mcp scan server-name  # Deep scan specific server
```

### Trust Model

Trust is derived from `permissions.rules` — MCP servers with a matching `allow` rule are trusted. No separate trust configuration needed.

| MCP Server | Permission | Has credentials | Result |
|---|---|---|---|
| `mcp-atlassian` | allow | Yes | OK — trusted, needs credentials |
| `unknown-server` | not listed | Yes | **Warning** — untrusted server receiving credentials |
| `unknown-server` | not listed | No | OK — no credentials at risk |

### Config Audit Checks

| Check | Severity | Description |
|-------|----------|-------------|
| Credential exposure | Critical | Credential env vars (KEY, TOKEN, SECRET, PASSWORD) on untrusted servers |
| npx auto-install | Medium | `npx -y` auto-installs packages without review |
| Unpinned versions | Medium | Packages without version pins (`pkg` instead of `pkg@1.2.3`) |
| Suspicious URLs | High | Raw IPs, localhost, ngrok/tunneling services |

### Deep Source Scan Checks

| Check | Severity | Description |
|-------|----------|-------------|
| Outbound HTTP | Medium | `requests.get()`, `fetch()`, `axios` calls |
| Sensitive file reads | High | Access to `~/.ssh`, `~/.aws`, `/etc/shadow` |
| Subprocess/exec | High | `subprocess.run()`, `os.system()`, `eval()` |
| Base64 encoding | Medium | `base64.b64encode()`, `btoa()` (exfiltration pattern) |
| Environment harvesting | High | `dict(os.environ)`, `os.environ.copy()` |

### Console Panel

The MCP Security panel is available in the Console under **Permissions > MCP Security**. It shows the same config audit results as `ai-guardian mcp audit`.

## Skill Instructions

The MCP server automatically loads skill instructions (from the bundled `SKILL.md`) during the MCP initialize handshake. The AI receives these instructions when the server connects — no separate skill installation needed.

The instructions teach the AI:
- When to use each tool based on the proactive level
- How to handle annotation protection
- The support bundle review workflow
- That hooks are the enforcement layer — MCP is advisory
