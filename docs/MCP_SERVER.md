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
```

The MCP server is installed by default during setup. Use `--no-mcp` to skip.
Cursor desktop and the local Cursor CLI share the local user configuration
(`~/.cursor/hooks.json` and `~/.cursor/mcp.json`). For a Cursor Cloud workspace,
select the project explicitly; this writes only that workspace's files:

```bash
ai-guardian setup --ide cursor --project /path/to/workspace
```

The tray exposes the same operation as **Cursor Cloud (project setup)...**.
Without `--project`, setup remains user/desktop-scoped.

### Manual setup

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
```

## Proactive Level

Controls how aggressively the AI uses proactive security checks. Higher levels add latency and token usage (each check adds tool call/result pairs to the conversation context).

| Level | Behavior | Best for |
|-------|----------|----------|
| **low** (default) | Check only when user asks or after a block | Most users — hooks enforce everything |
| **medium** | Also check unfamiliar paths and suspicious commands | Teams wanting fewer blocked-and-retry cycles |
| **high** | Check every file access and command | High-security environments |

Configure via:
- `ai-guardian.json`: `"mcp_server": {"proactive_level": "low"}`
- Tray menu: MCP submenu → Proactive radio buttons
- Console: MCP Servers panel → Proactive Level dropdown

## Tools

### Security Checks (Proactive)

| Tool | Parameters | Returns | Purpose |
|------|-----------|---------|---------|
| `check_path` | `path`, `operation?` | `allowed` / `denied` / `not_found` | Is this path protected? |
| `check_command` | `command` | `allowed` / `blocked` + reason | Would this command be blocked? |
| `check_mcp_trust` | `server_name` | `trusted` / `untrusted` | Is this MCP server allowed? |
| `sanitize_text` | `text` | sanitized text + redaction count | Redact secrets/PII from text |
| `check_annotations` | `file_path` | valid/invalid + warnings | Are annotation pairs matched? |

`operation` (v1.12.0+): `"read"` (default), `"write"`, or `"edit"`. Checks whether the specific operation type is allowed on the path.

### Information (Query)

| Tool | Parameters | Returns | Purpose |
|------|-----------|---------|---------|
| `get_violations` | `violation_type?`, `limit?` | violation list with file:line | Recent security violations |
| `get_config` | — | feature enabled/disabled map | Current security posture |
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
| `get_violations` | Type, timestamp, file:line, action | Matched pattern internals |
| `get_patterns_list` | Category names and counts | Regex patterns |

### Self-protection

- ai-guardian's own MCP tools (`mcp__ai-guardian__*`) are auto-allowed — they don't need explicit permission rules
- All other MCP servers require explicit allow rules in the permissions config
- The MCP server process runs separately from the daemon — if the daemon is unavailable, MCP tools still work

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

- **Direct install** (`ai-guardian mcp-server`): Python >=3.10 (MCP SDK requirement). ai-guardian itself still supports Python 3.9 for all other features (hooks, CLI, Console, scanning).
- **Via uvx** (`uvx ai-guardian mcp-server`): No Python version requirement — uvx manages its own environment. This is the recommended method for users on Python 3.9.
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
