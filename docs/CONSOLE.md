# AI Guardian Console Guide

This guide provides comprehensive documentation for the AI Guardian interactive Console.

## Overview

The AI Guardian Console is a modern, tab-based interactive interface built with [Textual](https://textual.textualize.io/) that provides a user-friendly way to manage security policies and configurations. With 6,207 lines of code across 16 modules and 11 specialized tabs, the Console offers powerful features while maintaining ease of use.

### Why Use the Console?

✅ **User-friendly**: No need to remember JSON schema syntax or command-line flags  
✅ **Real-time validation**: Prevents syntax errors before saving configuration  
✅ **Discovery**: See all available configuration options in one place  
✅ **Safety**: Requires manual clicks - AI agents cannot modify config  
✅ **One-click approval**: Quickly allow blocked operations from violation log  
✅ **Visual feedback**: Color-coded status indicators and clear information hierarchy  
✅ **Advanced features**: Time-based toggles, smart rule merging, violation filtering  

### Security by Design

**The Console is designed for manual, deliberate config changes only.**

Unlike command-line flags, the Console requires you to physically see and click buttons to approve changes. This prevents an AI agent from sneakily modifying your configuration behind the scenes.

- ✅ **Manual approval required**: You must click buttons for each change
- ✅ **Human-in-the-loop**: Every config modification is visible in the UI
- ❌ **No automated changes**: No way for an agent to bypass the interactive interface

## Web Console

AI Guardian also provides a **browser-based web console** powered by [NiceGUI](https://nicegui.io/), as an alternative to the TUI. The web console connects to daemons via their REST APIs and provides a unified multi-daemon dashboard.

### Launching the Web Console

```bash
# Auto-assign a free port and open browser
ai-guardian console --web

# Use a specific port
ai-guardian console --web --port 8080
```

The web console binds to `127.0.0.1` (localhost only) for security.

### Web Console Pages

- **Security Dashboard** — Multi-daemon status overview with live auto-refresh, clickable feature cards for quick navigation
- **Global Settings** — Feature enabled/disabled flags across all daemons, with global search to find any setting
- **Violations** — Filterable violations table with daemon and type filters
- **Violation Logging** — Logging configuration status per daemon
- **Metrics** — Violation statistics by type and severity with time range selector
- **Detection Patterns** — Read-only view of all detection rules (built-in and pattern server) with category filtering *(NEW in v1.11.0)*
- **Auto Directory Rules** — View and manage auto-discovered directory permission rules *(NEW in v1.11.0)*
- **Permission Rules** — View and manage tool permission rules *(NEW in v1.11.0)*
- **Context Poisoning** — Context poisoning detection settings with regex tester *(NEW in v1.11.0)*
- **Logs** — Daemon log viewer
- **Sessions** — Unified security-focused SDK and hook trace view, grouped by `run_id`
- **Tracing Settings** — Enable or disable SDK and hook trace recording, and configure refresh and remote-cache retention
- **IDE Conversations** — Raw IDE-specific conversation replay for debugging
- **Scan Configure** — Scan a project to detect false positives and auto-generate suppression config *(NEW in v1.15.0)*
- **Daemon Detail** — Single daemon stats, controls (pause/resume/reload), recent violations

To correlate an SDK run with a hook-based IDE session, provide the SDK
`RunContext.run_id` as the hook event's `run_id`. If the IDE cannot provide that
field, set the same value as `AI_GUARDIAN_RUN_ID` when starting the non-SDK
agent. Matching values appear as one run on **Sessions**. The daemon persists
the `session_id` binding across restarts; sessions without a matching value
remain separate.

Both consoles save these controls in the top-level `tracing` configuration.
Values from the deprecated `sdk.trace_viewer` section are still displayed when
no top-level override exists, but new edits do not modify the deprecated section.

An **Interrupted** Sessions status means the recording remained in progress
without receiving a `SessionEnd` event, such as after a daemon restart. It does
not necessarily mean the agent crashed. The stored/API `stop_reason` remains
`crashed` for backward compatibility.

### System Tray Integration

The system tray includes a **Web Console** menu item that opens the web console in your default browser. The web console must be running first (`ai-guardian console --web`).

### Configuration

```json
{
  "console": {
    "web": {
      "port": 0,
      "host": "127.0.0.1"
    }
  }
}
```

- `port`: Port for web console. `0` = auto-assign free port (default)
- `host`: Bind address. Keep `127.0.0.1` for security

### Requirements

- Python >= 3.10 (NiceGUI dependency)
- NiceGUI is included as a core dependency

### Coexistence with TUI

Both console modes coexist:
- `ai-guardian console` — TUI (terminal-based, Textual)
- `ai-guardian console --web` — Web console (browser-based, NiceGUI)

The TUI remains the primary interface. The web console is for users who prefer a browser-based experience or need multi-daemon monitoring.

---

## TUI Console (Terminal)

## Getting Started

### Prerequisites

1. **AI Guardian installed**:
   ```bash
   uv tool install ai-guardian        # recommended (or: pip install ai-guardian)
   ```

2. **Terminal with 256-color support** (most modern terminals)

3. **Minimum terminal size**: 80x24 characters (recommended: 120x40)

4. **GNOME Desktop (Linux)**: The system tray icon requires the AppIndicator extension. Without it, `ai-guardian tray start` runs but the tray icon does not appear.

   ```bash
   # Fedora / RHEL
   sudo dnf install gnome-shell-extension-appindicator.noarch

   # Ubuntu / Debian
   sudo apt install gnome-shell-extension-appindicator

   # Log out and log back in (required on Wayland)

   # Enable the extension
   gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com

   # Verify
   ai-guardian doctor   # "System tray" check should show PASS
   ```

   Run `ai-guardian doctor` to check whether the extension is detected.

5. **Linux browser window raising (optional)**: On KDE/GNOME, opening the Web Console may leave the browser minimized. Install one of the following so AI Guardian can raise the browser window automatically:

   ```bash
   # KDE Wayland (recommended for modern KDE)
   sudo dnf install kdotool    # Fedora / RHEL
   sudo apt install kdotool    # Ubuntu / Debian

   # X11 (any desktop)
   sudo dnf install xdotool    # Fedora / RHEL
   sudo apt install xdotool    # Ubuntu / Debian
   ```

   AI Guardian tries `kdotool` (KDE Wayland), then `xdotool` (X11), then `wmctrl` (X11). Without any of these tools, the URL still opens but the browser window may stay minimized.

6. **Linux terminal emulator**: The tray **Console** menu item opens the Console in a terminal window. A supported terminal emulator must be installed: `gnome-terminal`, `kgx` (GNOME Console), `konsole`, `xfce4-terminal`, or `xterm`. Fedora 44+ ships `kgx` by default, which is supported. If none is found, install one:

   ```bash
   # Fedora / RHEL
   sudo dnf install gnome-terminal

   # Ubuntu / Debian
   sudo apt install gnome-terminal

   # Verify
   ai-guardian doctor   # "Terminal emulator" check should show PASS
   ```

### Launching the Console

```bash
ai-guardian tui
```

The Console will launch in your terminal with a tab-based interface.

### First Steps

1. **Navigate tabs**: Click on tab headers or use keyboard shortcuts (see Navigation section)
2. **View violations**: Check the **Violations** tab for any blocked operations
3. **Configure permissions**: Use **Skills** and **MCP Servers** tabs to manage tool access
4. **Adjust global settings**: Use **Global Settings** tab to enable/disable security features
5. **Save changes**: Configuration is automatically saved when you make changes

## Navigation

### Global Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit the Console |
| `Escape` | Go back to previous screen / Close modal |
| `r` | Refresh current screen |
| `p` | Switch to Project scope (shown when in Global scope) |
| `g` | Switch to Global scope (shown when in Project scope) |
| `Arrow keys` | Navigate between UI elements |
| `Tab` | Move to next focusable element |
| `Shift+Tab` | Move to previous focusable element |
| `Enter` | Activate button / Select option |
| `Space` | Toggle checkbox / Activate button |

### Config Scope Toggle (NEW in v1.8.0)

Press `p` to switch to **Project** scope or `g` to switch back to **Global** scope. The current scope is shown in the header bar and the footer shows only the available toggle key.

- **Global scope** (default): Edit `~/.config/ai-guardian/ai-guardian.json`
- **Project scope**: Edit `.ai-guardian/ai-guardian.json` at the repo root

In Project scope:
- Global-only sections (daemon, MCP server, support) are disabled
- Fields marked `immutable` in the global config are locked
- The header shows `[Project]` to indicate the active scope

### Tab Navigation

Click on tab headers to switch between tabs:
- **⚙️ Global Settings**
- **📋 Violations**
- **🎯 Skills**
- **🔌 MCP Servers**
- **🔒 MCP Security**
- **🔒 Secrets**
- **🛡️ Prompt Injection**
- **🌐 Remote Configs**
- **🔍 Permissions Discovery**
- **🛡️ Directory Protection**
- **📄 Config**
- **📝 Logs**

### Modal Windows

Some actions open modal windows (e.g., viewing violation details, adding new rules):
- `Escape` - Close modal and return to main screen
- `Enter` - Confirm action (on buttons)
- Click outside modal area - No effect (modal retains focus)

## Tab Reference

### 1. ⚙️ Global Settings

Manage global security feature toggles with time-based controls.

#### Features

**Tool Permissions Enforcement** (`permissions.enabled`)
- Controls whether AI Guardian enforces tool permission rules
- When disabled, all tools are allowed without checks
- Supports time-based temporary disabling

**Secret Scanning** (`secret_scanning`)
- Controls whether Gitleaks secret detection is active
- When disabled, no secret scanning is performed
- Supports time-based temporary disabling

#### Time-Based Toggle Modes

Each setting supports three operational modes:

1. **Permanently Enabled** (default)
   - Feature is always active
   - Standard security posture
   - Recommended for normal operations

2. **Permanently Disabled**
   - Feature is always inactive
   - Use only when feature is not needed
   - Not recommended for production use

3. **Temporarily Disabled** (advanced)
   - Disabled until specified timestamp
   - Automatically re-enables at expiration
   - Visual countdown timer shown in UI

#### Use Cases for Temporary Disable

- **Emergency debugging sessions**: Need unrestricted tool access for incident response
- **Scheduled maintenance windows**: Planned work requiring elevated permissions
- **Time-boxed experimentation**: Testing with guardrails temporarily removed

#### How to Use

1. Click the **Mode** dropdown to select:
   - "Enabled" - Permanently on
   - "Disabled" - Permanently off
   - "Disabled until..." - Temporarily off

2. For temporary disable:
   - Enter expiration timestamp in ISO 8601 format
   - Example: `2026-04-15T18:00:00Z`
   - UI shows countdown: "Auto re-enable in X hours"

3. Click **Save** to apply changes

**Configuration location**: `~/.config/ai-guardian/ai-guardian.json`

**Example configuration**:
```json
{
  "permissions": {
    "enabled": {
      "value": false,
      "disabled_until": "2026-04-15T18:00:00Z"
    }
  },
  "secret_scanning": {
    "enabled": true
  }
}
```

---

### 2. 📋 Violations

View all recent blocked operations with filtering and one-click approval.

#### Overview

The Violations tab displays all security violations logged by AI Guardian, including:
- **Tool permission denials**: Blocked Skill or MCP server executions
- **Secret detections**: Files or prompts containing secrets
- **Directory access denials**: Blocked reads of protected directories
- **Prompt injection attempts**: Suspicious prompts flagged by detection engine

#### Features

**Violation Filtering**
- Filter by type: All, Tool Permissions, Secrets, Directories, Prompt Injection
- Click filter buttons at top of tab
- Badge shows count per category
- Filter by **project directory**: dropdown with browse button lets you restrict the violations list to a specific daemon project directory — useful in multi-project workspaces where multiple agents share one daemon

**One-Click Approval**
- Click **Approve & Add Rule** to automatically create permission rule
- Smart rule merging: Combines with existing patterns where possible
- Instant effect: Tool is allowed on next execution

**Violation Details**
- Click **View Details** to see full JSON payload
- Shows timestamps, tool names, patterns, rejection reasons
- Copy details for debugging or reporting

**Mark as Resolved**
- Click **Mark Resolved** to remove from active list
- Keeps violation log clean
- Resolved violations are archived (not deleted)

#### Violation Types

**Tool Permission Violations**
```
Tool: gh-cli
Pattern: gh-cli
Status: DENIED
Reason: Tool not in allow list
```
- Shows which Skill or MCP server was blocked
- Displays the exact pattern that was denied
- One-click to add to allow list

**Secret Violations**
```
Type: Secret Detected
File: config.json
Secret Type: AWS Access Key
Status: BLOCKED
```
- Shows file or prompt containing secret
- Indicates type of secret (API key, password, token, etc.)
- No auto-approval (manual review required)

**Directory Access Violations**
```
Type: Directory Access Denied
Path: /private/credentials
Reason: .ai-read-deny marker present
```
- Shows which directory was blocked
- Indicates reason (marker file or exclusion list)
- Link to Directory Protection tab for management

**Prompt Injection Violations**
```
Type: Prompt Injection Detected
Confidence: 0.95
Pattern: Ignore previous instructions
```
- Shows suspicious prompt text
- Confidence score (0.0-1.0)
- Pattern that triggered detection

#### Workflow Example

1. **AI attempts to use a tool** (e.g., `daf-cli`)
2. **Tool is blocked** (not in allow list)
3. **Violation appears in Console** with details
4. **Review violation**: Click **View Details**
5. **Approve if safe**: Click **Approve & Add Rule**
6. **Automatic rule creation**: Pattern added to `skills.allow[]`
7. **Tool now works**: Next execution succeeds

#### Smart Rule Merging

When approving violations, AI Guardian intelligently merges patterns:

**Before**:
```json
{
  "skills": {
    "allow": ["daf-*", "release"]
  }
}
```

**Approve violation for**: `daf-cli`

**After** (smart merge):
```json
{
  "skills": {
    "allow": ["daf-*", "release"]
  }
}
```
*Pattern `daf-cli` already covered by `daf-*`, so no duplicate added.*

**Approve violation for**: `gh-cli`

**After** (new pattern):
```json
{
  "skills": {
  "allow": ["daf-*", "release", "gh-cli"]
  }
}
```

#### Violation Log Location

Violations are logged to: `~/.config/ai-guardian/violation.log` (JSON lines format)

Each line is a JSON object with:
- `timestamp`: ISO 8601 timestamp
- `type`: Violation type (tool_permission, secret, directory, prompt_injection)
- `status`: DENIED, BLOCKED, FLAGGED
- `details`: Type-specific metadata

---

### 3. 🎯 Skills

Manage Skill permission rules (allow/deny patterns).

#### Overview

**Purpose:** Controls which **TOOLS** (Skills) the AI can execute.

**Relationship to other tabs:**
- This tab edits the `permissions.rules` section (matcher: "Skill")
- Works with **Permissions Discovery** tab (tab 8): Auto-discovered skills feed INTO this allow/deny list
- **NOT related** to **Directory Protection** tab (tab 9): That controls filesystem PATHS, not tool execution

Skills are CLI commands exposed by AI coding assistants (e.g., `daf-cli`, `release`, `gh-cli`). This tab controls which Skills the AI can execute.

#### Configuration Structure

**Allow List** (`skills.allow[]`)
- Tools explicitly permitted
- Supports wildcards: `daf-*` matches `daf-cli`, `daf-status`, etc.
- Empty list = deny all (secure default)

**Deny List** (`skills.deny[]`)
- Tools explicitly forbidden (overrides allow list)
- Useful for denying specific tools within wildcard allow
- Example: Allow `git-*` but deny `git-push`

#### Pattern Syntax

| Pattern | Matches | Description |
|---------|---------|-------------|
| `daf-cli` | `daf-cli` only | Exact match |
| `daf-*` | `daf-cli`, `daf-status`, `daf-info`, ... | Prefix wildcard |
| `*-cli` | `daf-cli`, `gh-cli`, `glab-cli`, ... | Suffix wildcard |
| `*` | Everything | Match all (use with caution) |

#### Time-Based Patterns (Advanced)

Patterns can have expiration timestamps for temporary permissions:

```json
{
  "pattern": "dangerous-tool",
  "valid_until": "2026-04-15T18:00:00Z"
}
```

**Visual indicators in Console**:
- `[expires 2026-04-15T18:00:00Z]` - Yellow badge, expires soon (< 24 hours)
- `[until 2026-04-15T18:00:00Z]` - Gray badge, expires later
- `[EXPIRED]` - Red badge, pattern no longer active

**Auto-cleanup**: Expired patterns are automatically removed on next config load.

#### How to Use

**Add new pattern**:
1. Enter pattern in **Add Pattern** input field
2. Select **Allow** or **Deny** mode
3. Click **Add**
4. Pattern appears in respective list

**Remove pattern**:
1. Find pattern in Allow or Deny list
2. Click **Remove** button next to pattern
3. Pattern is deleted from configuration

**Review patterns**:
- Scroll through Allow and Deny lists
- Green checkmarks (✓) indicate allowed
- Red crosses (✗) indicate denied

#### Example Configurations

**Minimal (secure default)**:
```json
{
  "skills": {
    "allow": []
  }
}
```
*All Skills blocked.*

**Development workflow**:
```json
{
  "skills": {
    "allow": ["daf-*", "release", "gh-cli", "git-cli"]
  }
}
```
*DevAIFlow tools, release management, GitHub/Git access.*

**Restrictive (deny specific tools)**:
```json
{
  "skills": {
    "allow": ["git-*"],
    "deny": ["git-push", "git-force-push"]
  }
}
```
*Allow all git commands except pushing.*

#### Common Skill Patterns

| Pattern | Purpose |
|---------|---------|
| `daf-*` | DevAIFlow session management |
| `gh-cli` | GitHub CLI operations |
| `glab-cli` | GitLab CLI operations |
| `git-cli` | Git version control |
| `release` | Release automation |
| `arc` | Ansible Automation Platform |
| `code-review` | Code review automation |
| `security-review` | Security scanning |

---

### 4. 🔌 MCP Servers

Manage MCP server permissions and the AI Guardian MCP security advisor.

#### AI Guardian MCP Security Advisor

This panel includes controls for ai-guardian's own MCP server:

- **Enable/Disable toggle**: Turn the MCP security advisor on/off without restarting the IDE
- **Proactive Level**: `low` (default) / `medium` / `high` — controls how often the AI uses proactive security checks. See [MCP Server docs](MCP_SERVER.md).
- **Support Bundle**: Configure the export destination and TTL for sanitized diagnostic bundles

#### MCP Server Permissions

**Purpose:** Controls which **TOOLS** (MCP servers) the AI can invoke.

**Relationship to other tabs:**
- This tab edits the `permissions.rules` section (matcher: "mcp__*")
- Works with **Permissions Discovery** tab (tab 8): Auto-discovered MCP permissions feed INTO this allow/deny list
- **NOT related** to **Directory Protection** tab (tab 9): That controls filesystem PATHS, not tool execution

MCP servers are external tools/services accessed via the Model Context Protocol. Examples include:
- `mcp__notebooklm-mcp__*` - NotebookLM operations
- `mcp__filesystem__*` - File system access
- `mcp__database__*` - Database queries

This tab controls which MCP servers the AI can invoke.

#### Configuration Structure

**Allow List** (`mcp_servers.allow[]`)
- MCP servers explicitly permitted
- Supports wildcards: `mcp__notebooklm-mcp__*`
- Empty list = deny all

**Deny List** (`mcp_servers.deny[]`)
- MCP servers explicitly forbidden
- Overrides allow list entries

#### Pattern Syntax

MCP server names follow the format: `mcp__<server>__<tool>`

| Pattern | Matches | Description |
|---------|---------|-------------|
| `mcp__notebooklm-mcp__chat_configure` | Exact tool | Specific MCP tool |
| `mcp__notebooklm-mcp__*` | All NotebookLM tools | Server wildcard |
| `mcp__*` | All MCP servers | Global wildcard (dangerous) |

#### How to Use

**Add MCP server pattern**:
1. Enter pattern (e.g., `mcp__notebooklm-mcp__*`)
2. Select **Allow** or **Deny**
3. Click **Add**

**Remove pattern**:
1. Click **Remove** next to pattern in list

**Review patterns**:
- Separate lists for Allow and Deny
- Visual indicators for mode (✓/✗)

#### Example Configurations

**Allow specific MCP server**:
```json
{
  "mcp_servers": {
    "allow": ["mcp__notebooklm-mcp__*"]
  }
}
```
*Only NotebookLM MCP tools allowed.*

**Deny specific tools within allowed server**:
```json
{
  "mcp_servers": {
    "allow": ["mcp__filesystem__*"],
    "deny": ["mcp__filesystem__delete", "mcp__filesystem__write"]
  }
}
```
*File system reads allowed, writes/deletes blocked.*

#### Security Best Practices

1. **Principle of least privilege**: Only allow MCP servers you actively use
2. **Avoid global wildcards**: Don't use `mcp__*` unless absolutely necessary
3. **Review violations**: Check Violations tab for blocked MCP calls before allowing
4. **Time-limit dangerous tools**: Use time-based patterns for risky operations

---

### 4b. 🔒 MCP Security

Audit MCP server configurations for security issues. This panel performs static analysis of your IDE's MCP server definitions to detect potential risks.

#### What It Checks

| Check | Severity | Description |
|-------|----------|-------------|
| Credential exposure | Critical | Credential env vars (KEY, TOKEN, SECRET, PASSWORD) passed to untrusted servers |
| npx auto-install | Medium | `npx -y` auto-installs packages without review on untrusted servers |
| Unpinned versions | Medium | Packages without version pins (e.g., `uvx pkg` instead of `uvx pkg@1.2.3`) |
| Suspicious URLs | High | Raw IPs, localhost, ngrok/tunneling services in server args |

#### Trust Model

Trust is derived from `permissions.rules` — the same rules you configure in the **MCP Servers** tab:
- **Trusted**: Servers with a matching `allow` rule can receive credentials without warning
- **Untrusted**: Servers without an `allow` rule trigger credential exposure warnings

#### How to Use

The panel runs automatically when opened. Click **Run Audit** to refresh results.

For deep source code scanning (outbound HTTP calls, sensitive file reads, subprocess execution), use the CLI:

```bash
ai-guardian mcp scan              # Scan all servers
ai-guardian mcp scan server-name  # Scan specific server
ai-guardian mcp audit             # Config-only audit (same as Console panel)
ai-guardian mcp list              # List servers with trust status
```

---

### 5. 🔒 Secrets

View secret detection configuration and Gitleaks integration status.

#### Overview

The Secrets tab displays the configuration for secret scanning using [Gitleaks](https://github.com/gitleaks/gitleaks), an open-source secret detection tool.

#### Features

**Secret Scanning Status**
- Shows whether secret scanning is enabled globally
- Links to Global Settings tab to enable/disable
- Displays Gitleaks installation status

**Gitleaks Integration**
- Path to gitleaks binary (auto-detected)
- Version information
- Installation instructions if not found

**Secret Pattern Server** (optional)
- Custom pattern server URL for organization-specific secrets
- Token environment variable for authentication
- Test connection button

#### Configuration Display

The tab shows read-only configuration from `~/.config/ai-guardian/ai-guardian.json`:

```json
{
  "secret_scanning": {
    "enabled": true,
    "pattern_server": {
      "url": "https://patterns.example.com/secrets",
      "auth": {
        "token_env": "PATTERN_SERVER_TOKEN"
      }
    }
  }
}
```

#### Secret Detection Workflow

1. **AI generates code or receives file content**
2. **AI Guardian scans content** using Gitleaks
3. **Secrets detected**: Operation blocked, violation logged
4. **No secrets**: Operation proceeds normally

#### Supported Secret Types

Gitleaks detects 100+ secret types including:
- API keys (AWS, Azure, GCP, GitHub, etc.)
- Private keys (RSA, SSH, PGP)
- Passwords and tokens
- Database connection strings
- OAuth credentials
- Custom patterns (via pattern server)


#### Immutable Remote Configurations (Issue #67)

**NEW**: Remote configurations can mark sections and permission rules as `immutable` to enforce enterprise policies.

**How Immutability Appears in Console:**

1. **Remote Configs Tab**:
   - Remote configs with immutable sections/rules are displayed with a visual indicator
   - Warning message: "⚠ This remote config contains immutable sections that override local settings"
   - Immutable sections are highlighted or marked with a 🔒 icon

2. **Skills/MCP Tabs**:
   - When a matcher is marked as immutable in remote config, local rules for that matcher cannot be added
   - Add button shows: "Cannot add rules - Skill matcher is immutable (enforced by remote config)"
   - Existing local rules for immutable matchers are not shown (filtered out during merge)

3. **Other Settings Tabs** (Prompt Injection, Pattern Server, etc.):
   - When a section is marked as immutable in remote config, local overrides are ignored
   - Section displays: "⚠ Settings enforced by remote config (immutable)"
   - Edit/modify buttons are disabled with tooltip: "Cannot modify - section is immutable"

**Example Immutable Remote Config:**

Per-Matcher Immutability:
```json
{
  "permissions": [
    {
      "matcher": "Skill",
      "mode": "allow",
      "patterns": ["daf-*", "gh-cli"],
      "immutable": true
    }
  ]
}
```

Section Immutability:
```json
{
  "prompt_injection": {
    "enabled": true,
    "sensitivity": "high",
    "immutable": true
  }
}
```

**Enterprise Use Cases:**
- Enforce mandatory skill allowlists that users cannot extend
- Prevent weakening of prompt injection detection settings
- Lock pattern server configuration for compliance
- Centrally managed security policies with proven enforcement

#### Troubleshooting

**"Gitleaks not found"**
```bash
# Install Gitleaks
brew install gitleaks  # macOS
# Or see https://github.com/gitleaks/gitleaks#installation
```

**"Pattern server unreachable"**
- Check URL is correct
- Verify token environment variable is set: `echo $PATTERN_SERVER_TOKEN`
- Test connection: `curl -H "Authorization: Bearer $PATTERN_SERVER_TOKEN" https://patterns.example.com/secrets`

**False positives**
- Add to `.gitleaksignore` file in project root
- Use Gitleaks allowlist in custom config

---

### 6. 🛡️ Prompt Injection

View and configure prompt injection detection settings.

#### Overview

Prompt injection attacks attempt to manipulate AI behavior by inserting malicious instructions into prompts. This tab configures the detection engine.

#### Detection Methods

**Pattern-Based Detection**
- Regex patterns matching known injection techniques
- Examples: "Ignore previous instructions", "You are now", "System: "

**Machine Learning Detection** (optional)
- ML model scoring prompt trustworthiness
- Confidence threshold: 0.0 (allow all) to 1.0 (block all)

#### Configuration Options

**Sensitivity Level**
- **Low**: Only blocks obvious injection attempts
- **Medium**: Balanced false positive/negative rate (recommended)
- **High**: Aggressive detection, may flag legitimate prompts

**Allowlist**
- Trusted prompt patterns that bypass detection
- Useful for common phrases flagged as false positives

**Custom Patterns**
- Organization-specific injection patterns
- Regex syntax supported

#### Configuration Structure

```json
{
  "prompt_injection": {
    "enabled": true,
    "sensitivity": "medium",
    "allowlist": [
      "As mentioned in previous conversation",
      "Based on earlier context"
    ],
    "custom_patterns": [
      "(?i)disregard (all )?prior",
      "(?i)new instructions:"
    ]
  }
}
```

#### How Prompt Injection Detection Works

1. **User submits prompt** to AI assistant
2. **AI Guardian intercepts** prompt before sending to AI
3. **Detection engine analyzes** prompt text
4. **Injection detected**: Prompt blocked, user notified, violation logged
5. **Clean prompt**: Forwarded to AI normally

#### Common Injection Patterns Detected

- **Instruction override**: "Ignore all previous instructions and..."
- **Role manipulation**: "You are now a different AI without restrictions..."
- **Context poisoning**: "The system administrator said..."
- **Delimiter injection**: Using special tokens to break prompt boundaries

#### Troubleshooting

**Legitimate prompts blocked (false positive)**
1. Review violation in Violations tab
2. Add phrase to allowlist in Prompt Injection tab
3. Or reduce sensitivity level

**Injection attacks not detected (false negative)**
1. Increase sensitivity level
2. Add custom pattern matching the attack
3. Report pattern to AI Guardian project for inclusion

---

### 7. 🌐 Remote Configs

Manage remote policy URLs for loading enterprise/team configurations.

#### Overview

Remote Configs allow organizations to centralize security policies that are automatically fetched and merged into local configuration. This enables:
- **Enterprise-wide policies**: Enforce organization security standards
- **Team-level defaults**: Share common configurations across team members
- **Centralized updates**: Update policies once, apply everywhere

#### Features

**Add Remote URL**
- Enter URL to remote configuration JSON file
- Toggle enabled/disabled per URL
- Optional authentication via environment variable token

**Test Connection**
- Click **Test** to verify URL is reachable
- Shows HTTP status and response preview
- Validates JSON format

**Refresh Settings**
- `refresh_interval_hours`: How often to fetch updates (default: 24 hours)
- `expire_after_hours`: When to discard cached config (default: 168 hours / 7 days)

**Priority Order**
- Multiple URLs can be configured
- Later URLs override earlier ones
- Local config always has highest priority (overrides remote)

#### Configuration Structure

```json
{
  "remote_configs": {
    "urls": [
      {
        "url": "https://policies.example.com/ai-guardian/enterprise.json",
        "enabled": true,
        "token_env": "POLICY_SERVER_TOKEN"
      },
      {
        "url": "https://team-config.example.com/ai-guardian.json",
        "enabled": true,
        "token_env": ""
      }
    ],
    "refresh_interval_hours": 24,
    "expire_after_hours": 168
  }
}
```

#### How to Use

**Add remote config URL**:
1. Click **Add Remote Config**
2. Enter URL (must be HTTPS for security)
3. Optionally enter token environment variable name
4. Click **Add**

**Enable/disable URL**:
1. Find URL in list
2. Toggle **Enabled** checkbox
3. Changes are saved automatically

**Test connectivity**:
1. Click **Test** button next to URL
2. View response in modal window
3. Verify JSON is valid and contains expected policies

**Remove URL**:
1. Click **Remove** button
2. Confirm deletion

#### Remote Config Format

Remote configuration files must be valid JSON matching AI Guardian schema:

```json
{
  "skills": {
    "allow": ["daf-*", "release"]
  },
  "mcp_servers": {
    "allow": []
  },
  "secret_scanning": {
    "enabled": true
  },
  "directory_exclusions": {
    "enabled": true,
    "paths": ["/etc/secrets", "~/.ssh"]
  }
}
```

#### Use Cases

**Enterprise Security Policy**
- URL: `https://security.corp.example/ai-guardian/enterprise-policy.json`
- Contains: Mandatory secret scanning, restricted MCP servers, baseline permissions
- All employees fetch this config automatically

**Team Shared Defaults**
- URL: `https://github.com/example-org/ai-guardian-config/raw/main/team.json`
- Contains: Team-specific Skill permissions, shared directory exclusions
- Team members opt-in by adding URL

**Project-Specific Config**
- URL: `https://api.github.com/repos/example/project/contents/.ai-guardian.json`
- Contains: Project dependencies, required tools
- Developers working on project automatically get correct permissions

#### Security Considerations

1. **Use HTTPS only**: Reject HTTP URLs to prevent MITM attacks
2. **Authenticate with tokens**: Set `token_env` for private configs
3. **Verify sources**: Only add URLs from trusted organizations
4. **Review merged config**: Check Config tab to see final effective configuration
5. **Cache expiration**: Set appropriate `expire_after_hours` to balance freshness vs. availability

#### Troubleshooting

**"Connection failed"**
- Check URL is reachable: `curl https://policies.example.com/config.json`
- Verify token is set: `echo $POLICY_SERVER_TOKEN`
- Check firewall/proxy settings

**"Invalid JSON"**
- Validate remote file: `curl URL | jq .`
- Check for syntax errors in remote config

**"Config not updating"**
- Check `refresh_interval_hours` setting
- Manually trigger refresh: Delete cache file at `~/.config/ai-guardian/remote-cache/`
- Verify remote config was actually modified (check Last-Modified header)

---

### 8. 🔍 Permissions Discovery

Manage auto-discovery of permissions from local directories or GitHub repositories.

#### Overview

**Purpose:** Auto-discover **TOOL** permissions from directories/repos and merge INTO `permissions.rules`.

**Relationship to other tabs:**
- Discovered permissions automatically populate **Skills** (tab 3) and **MCP Servers** (tab 4) allow lists
- This is the `permissions_directories` configuration section
- **Data flow:** Scan directories → Discover permission files → Generate rules → **Merge into** `permissions.rules`
- **NOT related** to **Directory Protection** tab (tab 9): Despite similar names, this discovers TOOL permissions, not filesystem path restrictions

**Critical distinction:**
- **This tab (Permissions Discovery):** WHERE to find tool permission files (config source)
- **Directory Protection tab:** WHICH paths to block from AI access (security policy)

Permissions Discovery allows AI Guardian to automatically load permission rules from specified directories or GitHub repos. This is useful for:
- **Shared team permissions**: Store in Git, auto-load across team
- **Project-specific rules**: Each repo defines its own required permissions
- **Multi-workspace setups**: Discover permissions from multiple directories

#### Configuration Structure

**Allow List** (`permissions_directories.allow[]`)
- Directories/repos to scan for permissions
- Files found are merged into configuration

**Deny List** (`permissions_directories.deny[]`)
- Directories/repos to explicitly exclude
- Useful for excluding subdirectories within allowed paths

#### Directory Entry Format

Each entry contains:
- **matcher**: Path pattern or URL to match
- **mode**: `allow` or `deny`
- **url**: GitHub URL (for remote repos) or empty for local paths
- **token_env**: Environment variable containing GitHub token (optional)

#### Example Configurations

**Local directory discovery**:
```json
{
  "permissions_directories": {
    "allow": [
      {
        "matcher": "~/.config/ai-guardian/policies/*",
        "mode": "allow",
        "url": "",
        "token_env": ""
      }
    ]
  }
}
```

**GitHub repository discovery**:
```json
{
  "permissions_directories": {
    "allow": [
      {
        "matcher": "**/.ai-guardian-permissions.json",
        "mode": "allow",
        "url": "https://github.com/example-org/ai-policies",
        "token_env": "GITHUB_TOKEN"
      }
    ]
  }
}
```

#### File Discovery Rules

AI Guardian searches for these files in specified directories:
- `.ai-guardian-permissions.json`
- `.ai-guardian-skills.json`
- `.ai-guardian-mcp.json`
- Any JSON file matching the matcher pattern

Files must contain valid AI Guardian permission rules:
```json
{
  "skills": {
    "allow": ["git-cli", "gh-cli"]
  },
  "mcp_servers": {
    "allow": ["mcp__notebooklm-mcp__*"]
  }
}
```

#### How to Use

**Add local directory**:
1. Click **Add Directory** under Allow or Deny section
2. Enter matcher pattern (e.g., `~/projects/*/.ai-guardian-*.json`)
3. Leave URL and token fields empty for local
4. Click **Add**

**Add GitHub repository**:
1. Click **Add Directory** under Allow section
2. Enter matcher pattern (e.g., `**/.ai-guardian-permissions.json`)
3. Enter GitHub repo URL: `https://github.com/org/repo`
4. Enter token env var if repo is private: `GITHUB_TOKEN`
5. Click **Add**

**Remove directory**:
1. Find entry in Allow or Deny list
2. Click **Remove**

#### Matcher Pattern Syntax

| Pattern | Matches | Description |
|---------|---------|-------------|
| `~/.config/policies/*.json` | All JSON in directory | Glob pattern |
| `**/.ai-guardian.json` | All `.ai-guardian.json` files recursively | Recursive glob |
| `/etc/ai-guardian/` | Specific directory | Exact path |

#### Priority and Merging

Permissions from multiple discovered files are merged:
1. Files discovered from allow directories are merged together
2. Later entries override earlier ones (for conflicts)
3. Local configuration has highest priority (overrides all discovered)

#### Use Cases

**Team shared permissions (Git)**:
```bash
# In team repo: team-config/.ai-guardian-permissions.json
{
  "skills": {
    "allow": ["daf-*", "release", "gh-cli"]
  }
}

# In user config: permissions_directories.allow
{
  "matcher": "**/.ai-guardian-permissions.json",
  "url": "https://github.com/example-org/team-config",
  "token_env": "GITHUB_TOKEN"
}
```

**Per-project permissions**:
```bash
# Each project has: .ai-guardian-permissions.json
# User config discovers from all project directories:
{
  "matcher": "~/projects/*/.ai-guardian-permissions.json",
  "mode": "allow"
}
```

#### Security Considerations

1. **Verify sources**: Only add trusted directories/repos to allow list
2. **Use deny list**: Exclude untrusted subdirectories
3. **Private repos**: Always use token_env for private GitHub repos
4. **Review merged config**: Check Config tab to see final permissions

---

### 9. 🛡️ Directory Protection

Manage directory exclusions and `.ai-read-deny` marker scanning.

#### Overview

**Purpose:** Controls which **PATHS** (directories/files) the AI can access/read.

**Relationship to other tabs:**
- This is the `directory_rules` (or `directory_exclusions` deprecated) configuration section
- **COMPLETELY SEPARATE** from **Permissions Discovery** tab (tab 8)
- **NOT related** to Skills/MCP permissions (tabs 3-4)

**Critical distinction - avoid confusion:**
- **Permissions Discovery tab (8):** Auto-discovers TOOL permissions (which tools can run)
- **This tab (Directory Protection):** Blocks filesystem PATHS (e.g., block `~/.ssh` directory)

**Common mistake:**  
❌ "I want to block a tool from accessing `/etc` → use Permissions Discovery"  
✅ "I want to block ANY tool from accessing `/etc` → use Directory Protection"

Directory Protection prevents AI agents from reading sensitive directories by:
1. **Exclusion paths**: Manually specified directories to block
2. **`.ai-read-deny` markers**: Automatic detection of marker files

#### Features

**Toggle Directory Protection**
- Enable/disable the entire directory exclusions feature
- When disabled, all directories are readable

**Exclusion Paths**
- Add paths that AI cannot read
- Supports absolute and home-relative paths (`~`)
- Wildcards not supported (exact path match only)

**Active Marker Scan**
- Shows all `.ai-read-deny` markers found in workspace
- Scans common directories: `~`, `~/projects`, `~/Documents`, etc.
- Real-time status: Active markers are automatically enforced

#### Configuration Structure

```json
{
  "directory_exclusions": {
    "enabled": true,
    "paths": [
      "/etc/secrets",
      "~/.ssh",
      "~/.gnupg",
      "~/Documents/private"
    ]
  }
}
```

#### How `.ai-read-deny` Markers Work

**Create marker**:
```bash
# Protect a directory
touch /path/to/sensitive-dir/.ai-read-deny
```

**Effect**:
- Any read attempt of files in `/path/to/sensitive-dir/` is blocked
- Subdirectories are also protected (recursive)
- Marker file itself can contain explanation (optional):
  ```
  This directory contains customer PII and should not be accessed by AI.
  Contact: security@example.com
  ```

**Detection**:
- AI Guardian scans for `.ai-read-deny` markers at startup
- Console shows active markers in Directory Protection tab
- No need to configure paths manually

#### How to Use

**Enable/disable directory protection**:
1. Toggle **Directory Exclusions Enabled** checkbox
2. Changes are saved immediately

**Add exclusion path**:
1. Enter path in **Add Path** input field
2. Use absolute path (`/etc/secrets`) or home-relative (`~/.ssh`)
3. Click **Add**
4. Path appears in exclusion list

**Remove exclusion path**:
1. Find path in list
2. Click **Remove**

**View active markers**:
- Scroll to **Active .ai-read-deny Markers** section
- List shows all detected marker files
- Click **Rescan** to refresh

#### Common Exclusion Paths

| Path | Purpose |
|------|---------|
| `~/.ssh` | SSH private keys |
| `~/.gnupg` | GPG keys |
| `/etc/secrets` | System secrets |
| `~/.aws` | AWS credentials |
| `~/.config/gcloud` | Google Cloud credentials |
| `~/Documents/private` | Personal files |
| `/var/secrets` | Application secrets |

#### Use Cases

**Protect credentials directories**:
```json
{
  "directory_exclusions": {
    "enabled": true,
    "paths": [
      "~/.ssh",
      "~/.aws",
      "~/.config/gcloud",
      "~/.gnupg"
    ]
  }
}
```

**Prevent AI from reading customer data**:
```bash
# In customer data directory:
touch /data/customers/.ai-read-deny

# Marker automatically detected and enforced
```

**Per-project sensitive directories**:
```bash
# In each project:
touch ./credentials/.ai-read-deny
touch ./private-keys/.ai-read-deny
```

#### Troubleshooting

**"Directory not blocked"**
- Verify path is correct (check for typos)
- Ensure directory_exclusions.enabled is true
- Check for trailing slashes (should not have `/` at end)
- Use absolute paths or `~` for home directory

**"Marker not detected"**
- Click **Rescan** in Console
- Verify marker file is named exactly `.ai-read-deny` (leading dot)
- Check marker is in parent directory of files you want to protect

**"False positives (legitimate reads blocked)"**
- Remove path from exclusion list
- Or delete `.ai-read-deny` marker
- Consider using more specific exclusion paths

---

### 10. 📄 Config

View and export merged configuration from all sources.

#### Overview

The Config tab displays the final, effective configuration after merging:
- Local user config (`~/.config/ai-guardian/ai-guardian.json`)
- Project-local config (`.ai-guardian.json` in repo root)
- Remote configs (from Remote Configs tab)
- Discovered permissions (from Permissions Discovery tab)

#### Features

**Configuration Display**
- Syntax-highlighted JSON
- Read-only view
- Shows all configuration keys and values

**Source Information**
- Lists which config files were loaded
- Shows priority order (highest priority last)
- Indicates if remote configs were fetched

**Export Configuration**
- Click **Export** to save merged config to file
- Useful for debugging or sharing
- Output is valid AI Guardian config JSON

#### Configuration Merge Priority

From lowest to highest priority:
1. **Built-in defaults**: Hard-coded safe defaults
2. **Remote configs**: Fetched from URLs (in URL order)
3. **Discovered permissions**: From local directories/GitHub repos
4. **Project-local config**: `.ai-guardian.json` in repo root
5. **User config**: `~/.config/ai-guardian/ai-guardian.json` (highest priority)

**Merge behavior**:
- Objects are deep-merged
- Arrays are replaced (not merged)
- Primitives (strings, booleans, numbers) are replaced

#### Example Merged Configuration

```json
{
  "permissions": {
    "enabled": true,
    "rules": [
      {
        "matcher": "Skill",
        "mode": "allow",
        "patterns": ["daf-*", "release", "gh-cli"]
      }
    ]
  },
  "secret_scanning": {
    "enabled": {
      "value": false,
      "disabled_until": "2026-04-15T18:00:00Z"
    }
  },
  "mcp_servers": {
    "allow": ["mcp__notebooklm-mcp__*"],
    "deny": []
  },
  "directory_exclusions": {
    "enabled": true,
    "paths": [
      "~/.ssh",
      "~/.aws"
    ]
  },
  "remote_configs": {
    "urls": [
      {
        "url": "https://policies.example.com/ai-guardian.json",
        "enabled": true
      }
    ],
    "refresh_interval_hours": 24,
    "expire_after_hours": 168
  }
}
```

#### How to Use

**View configuration**:
- Navigate to Config tab
- Scroll through JSON display
- All active settings are shown

**Export configuration**:
1. Click **Export** button
2. Choose file location
3. Configuration saved as JSON file

**Troubleshooting configuration**:
1. Check Config tab to see final merged result
2. Compare with individual config files to debug merge issues
3. Look for unexpected values that might come from remote configs

#### Use Cases

**Debug permission issues**:
- View merged config to see which allow/deny rules are active
- Check if remote config is overriding local settings
- Verify time-based patterns haven't expired

**Share configuration**:
- Export config and send to colleague
- Colleague imports as their local config
- Ensures consistent settings across team

**Backup configuration**:
- Export config periodically
- Store in version control
- Restore if local config is accidentally modified

---

### 11. 📝 Logs

View rotating application logs with filtering.

#### Overview

The Logs tab displays AI Guardian's application logs in real-time, useful for:
- Debugging permission issues
- Monitoring secret detections
- Tracking configuration changes
- Investigating blocked operations

#### Features

**Real-time Log Viewing**
- Tail mode: Automatically scrolls to newest logs
- Manual scrolling: Review historical logs

**Log Level Filtering**
- **DEBUG**: Verbose logging (all events)
- **INFO**: Normal operations
- **WARNING**: Potential issues
- **ERROR**: Failures and exceptions
- **CRITICAL**: Severe problems

**Log Format**
```
2026-04-15 10:30:45 [INFO] ai_guardian.hooks: Tool permission check: gh-cli -> ALLOWED
2026-04-15 10:31:02 [WARNING] ai_guardian.secrets: Secret detected in prompt (AWS Access Key)
2026-04-15 10:31:15 [ERROR] ai_guardian.remote_config: Failed to fetch remote config from https://...
```

Each log entry contains:
- **Timestamp**: ISO 8601 format with milliseconds
- **Level**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Module**: Which AI Guardian component logged the message
- **Message**: Human-readable description

#### How to Use

**View all logs**:
- Navigate to Logs tab
- Logs are displayed in chronological order (oldest first)
- Scroll to review

**Filter by log level**:
1. Click log level filter buttons (DEBUG, INFO, WARNING, ERROR, CRITICAL)
2. Only logs at selected level and above are shown
3. Example: Select WARNING to see WARNING, ERROR, and CRITICAL

**Search logs**:
- Use terminal's search feature (usually `Ctrl+F` or `Cmd+F`)
- Search for tool names, file paths, error messages

**Refresh logs**:
- Press `r` key to reload logs from file
- Useful if logs are written from another process

#### Log File Location

Logs are written to: `~/.local/state/ai-guardian/ai-guardian.log`

**Log rotation**:
- Maximum size: 10 MB
- Rotation: Up to 5 backup files
- Oldest logs are automatically deleted

**Log files**:
```
~/.local/state/ai-guardian/ai-guardian.log        # Current log
~/.local/state/ai-guardian/ai-guardian.log.1      # Previous rotation
~/.local/state/ai-guardian/ai-guardian.log.2      # 2 rotations ago
...
~/.local/state/ai-guardian/ai-guardian.log.5      # Oldest backup
```

#### Common Log Messages

**Tool permission check**:
```
[INFO] Tool permission check: gh-cli -> ALLOWED (matched pattern: gh-cli)
[WARNING] Tool permission check: dangerous-tool -> DENIED (not in allow list)
```

**Secret detection**:
```
[WARNING] Secret detected in file: config.json (type: AWS Access Key)
[INFO] Secret scan passed for prompt (0 secrets found)
```

**Directory access**:
```
[WARNING] Directory access denied: ~/.ssh (exclusion list)
[INFO] Directory access denied: /data/private (.ai-read-deny marker)
```

**Configuration events**:
```
[INFO] Loaded user config from ~/.config/ai-guardian/ai-guardian.json
[INFO] Fetched remote config from https://policies.example.com/ai-guardian.json
[WARNING] Remote config fetch failed: Connection timeout
[ERROR] Invalid JSON in config file: Unexpected token at line 42
```

#### Troubleshooting with Logs

**Problem**: "Why was my tool blocked?"
1. Go to Logs tab
2. Filter to WARNING level
3. Search for tool name (e.g., "gh-cli")
4. Find log entry explaining denial reason

**Problem**: "Is secret scanning working?"
1. Check logs for `[INFO] Secret scan`
2. Should see entries for each file/prompt scanned
3. If no entries, secret scanning may be disabled

**Problem**: "Remote config not loading"
1. Filter to ERROR level
2. Look for "remote config" in messages
3. Error message explains connection/parsing issue

---

## Common Workflows

### Workflow 1: Allowing a Blocked Tool

**Scenario**: AI attempts to use `gh-cli` but it's blocked.

**Steps**:
1. **Violation appears** in Violations tab (📋)
2. **Review details**: Click **View Details** to see full info
3. **Approve**: Click **Approve & Add Rule**
4. **Verify**: Check Skills tab (🎯) - `gh-cli` now in allow list
5. **Test**: AI can now use `gh-cli` successfully

**Result**: `gh-cli` added to `skills.allow[]` in config.

---

### Workflow 2: Temporarily Disabling Secret Scanning

**Scenario**: Need to debug with test credentials for 2 hours.

**Steps**:
1. Go to **Global Settings** tab (⚙️)
2. Find **Secret Scanning** section
3. Select mode: **Disabled until...**
4. Enter timestamp: `2026-04-15T18:00:00Z` (2 hours from now)
5. Click **Save**
6. Console shows: "[status-warn]Auto re-enable in 2 hours[/status-warn]"
7. Work with test credentials
8. After 2 hours: Secret scanning automatically re-enables

**Result**: Temporary debugging access without permanently disabling security.

---

### Workflow 3: Setting Up Team Permissions

**Scenario**: Share common AI tool permissions across development team.

**Steps**:
1. **Create team config** in Git repo: `team-config/.ai-guardian-permissions.json`
   ```json
   {
     "skills": {
       "allow": ["daf-*", "release", "gh-cli", "git-cli"]
     }
   }
   ```

2. **Commit and push** to team repo

3. **Each team member adds remote config**:
   - Go to **Remote Configs** tab (🌐)
   - Click **Add Remote Config**
   - Enter URL: `https://raw.githubusercontent.com/example-org/team-config/main/.ai-guardian-permissions.json`
   - Click **Add**

4. **Verify**: Check **Config** tab (📄) to see merged permissions

**Result**: All team members automatically get same baseline permissions.

---

### Workflow 4: Protecting Customer Data Directory

**Scenario**: Prevent AI from accessing `/data/customers/` directory.

**Method 1: Exclusion path**
1. Go to **Directory Protection** tab (🛡️)
2. Ensure **Directory Exclusions Enabled** is checked
3. Enter path: `/data/customers`
4. Click **Add**
5. Verify in list

**Method 2: Marker file** (recommended)
1. Create marker: `touch /data/customers/.ai-read-deny`
2. Go to **Directory Protection** tab (🛡️)
3. Click **Rescan**
4. Verify marker appears in **Active .ai-read-deny Markers**

**Result**: AI cannot read files from `/data/customers/`.

---

### Workflow 5: Investigating Secret Detection

**Scenario**: AI reports secret detected, but you believe it's a false positive.

**Steps**:
1. Go to **Violations** tab (📋)
2. Find secret violation entry
3. Click **View Details**
4. Review detected secret type and location
5. **If false positive**:
   - Add to Gitleaks allowlist: `.gitleaksignore`
   - Or add to secret detection allowlist (if supported)
6. **If true positive**:
   - Remove secret from code
   - Rotate credentials
   - Mark violation as resolved

**Result**: False positives ignored, true secrets remediated.

---

### Workflow 6: Reviewing Merged Configuration

**Scenario**: Unexpected permission behavior, need to debug config merge.

**Steps**:
1. Go to **Config** tab (📄)
2. Review merged configuration JSON
3. Compare with individual sources:
   - User config: `~/.config/ai-guardian/ai-guardian.json`
   - Remote configs (listed in Config tab header)
   - Project config: `.ai-guardian.json` in repo
4. Identify which source is overriding settings
5. Adjust as needed in respective config file/tab

**Result**: Configuration behavior explained and corrected.

---

## Advanced Features

### Time-Based Permissions

**Purpose**: Grant temporary access to tools or temporarily disable security features.

**Use cases**:
- Emergency debugging requiring elevated permissions
- Scheduled maintenance windows
- Time-boxed experiments

**Implementation**:

**Time-based toggle (Global Settings)**:
```json
{
  "secret_scanning": {
    "value": false,
    "valid_until": "2026-04-15T18:00:00Z"
  }
}
```
*Secret scanning disabled until 6 PM, then auto re-enables.*

**Time-based pattern (Skills/MCP)**:
```json
{
  "skills": {
    "allow": [
      {
        "pattern": "dangerous-tool",
        "valid_until": "2026-04-15T18:00:00Z"
      }
    ]
  }
}
```
*`dangerous-tool` allowed until 6 PM, then automatically removed.*

**Visual indicators**:
- Green: Active (not expired)
- Yellow: Expiring soon (< 24 hours)
- Red: Expired (rule inactive)

**Auto-cleanup**: Expired rules are removed on next config load.

---

### Smart Rule Merging

**Purpose**: Prevent duplicate patterns and optimize allow/deny lists.

**How it works**:

When approving a violation, AI Guardian checks if the pattern is already covered by existing rules:

**Example 1: Already covered**
- Existing: `daf-*`
- New violation: `daf-cli`
- Action: No change (already covered by wildcard)

**Example 2: New pattern needed**
- Existing: `daf-*`, `release`
- New violation: `gh-cli`
- Action: Add `gh-cli` to allow list

**Example 3: Wildcard optimization** (future)
- Existing: `daf-cli`, `daf-status`, `daf-info`
- New violation: `daf-config`
- Action: Replace with `daf-*` wildcard (if user confirms)

**Benefits**:
- Cleaner configuration
- Easier to understand and maintain
- Reduces config file size

---

### Nested Tab Structure

**Location**: Violations tab

**Purpose**: Organize violations by type for easier navigation.

**Implementation**:

Violations tab contains nested tabs:
- **All** - All violations (default)
- **Tool Permissions** - Blocked Skills/MCP servers
- **Secrets** - Secret detections
- **Directories** - Directory access denials
- **Prompt Injection** - Suspicious prompts

**Badge counts**: Each sub-tab shows violation count.

**How to use**:
1. Navigate to Violations tab (📋)
2. Click sub-tab header to filter by type
3. Click **All** to see all violations again

---

### Custom Styling and Themes

**Theme support**: Console uses Textual's theming system.

**Color schemes**:
- **Primary**: Main accent color (blue)
- **Accent**: Focus indicator (cyan)
- **Success**: Positive status (green)
- **Warning**: Warnings (yellow)
- **Error**: Errors and denials (red)

**Customization** (advanced):
Modify `src/ai_guardian/tui/theme.py` to define custom theme:
```python
CUSTOM_THEME = Theme(
    name="custom",
    primary="#ff6b6b",
    accent="#4ecdc4",
    # ... other colors
)
```

---

### Keyboard-Driven Navigation

**Philosophy**: Console is fully keyboard-navigable for power users.

**Tab navigation**:
- `Tab` - Next element
- `Shift+Tab` - Previous element
- `Arrow keys` - Navigate lists and buttons

**Modal shortcuts**:
- `Escape` - Close modal
- `Enter` - Confirm (on buttons)

**Global shortcuts**:
- `q` - Quit Console
- `r` - Refresh current tab
- `?` - Help (future)

**Accessibility**: Focus indicators clearly show which element is active.

---

## Troubleshooting

### Console Won't Launch

**Symptom**: `ai-guardian tui` command fails or crashes.

**Diagnosis**:
```bash
# Check AI Guardian is installed
ai-guardian --version

# Check terminal size
tput cols  # Should be >= 80
tput lines # Should be >= 24

# Check Python version
python --version  # Should be >= 3.9

# Run with debug logging
ai-guardian tui --log-level DEBUG
```

**Solutions**:
- Upgrade AI Guardian: `pip install --upgrade ai-guardian`
- Use larger terminal window
- Check for conflicting Python packages: `pip list | grep textual`
- Check logs: `~/.local/state/ai-guardian/ai-guardian.log`

---

### Configuration Not Saving

**Symptom**: Changes in Console don't persist after restart.

**Diagnosis**:
```bash
# Check config file exists and is writable
ls -la ~/.config/ai-guardian/ai-guardian.json

# Check permissions
stat ~/.config/ai-guardian/ai-guardian.json

# Check for JSON syntax errors
cat ~/.config/ai-guardian/ai-guardian.json | jq .
```

**Solutions**:
- Verify file permissions: `chmod 644 ~/.config/ai-guardian/ai-guardian.json`
- Fix JSON syntax errors (use jq or JSON validator)
- Check disk space: `df -h ~/.config`
- Inspect logs for write errors

---

### Remote Config Not Loading

**Symptom**: Remote policies not appearing in merged config.

**Diagnosis**:
1. Go to **Remote Configs** tab
2. Click **Test** next to URL
3. Check response status

**Common causes**:
- **Connection timeout**: URL unreachable
- **Authentication failure**: Invalid token or token_env not set
- **Invalid JSON**: Remote file has syntax errors
- **Cache not expired**: Using stale cached version

**Solutions**:
```bash
# Test URL manually
curl https://policies.example.com/ai-guardian.json

# Test with auth token
curl -H "Authorization: Bearer $POLICY_TOKEN" https://...

# Clear cache to force refresh
rm -rf ~/.config/ai-guardian/remote-cache/

# Check logs for fetch errors
grep "remote config" ~/.local/state/ai-guardian/ai-guardian.log
```

---

### Permissions Not Working

**Symptom**: Tool allowed/denied contrary to configuration.

**Diagnosis**:
1. Go to **Config** tab - Check merged configuration
2. Go to **Violations** tab - Look for related violations
3. Go to **Logs** tab - Filter to WARNING, search for tool name

**Common causes**:
- **Deny list overrides allow**: Tool in both allow and deny lists (deny wins)
- **Pattern mismatch**: Tool name doesn't match pattern (e.g., `gh` vs `gh-cli`)
- **Expired time-based rule**: Pattern had `valid_until` that passed
- **Remote config override**: Remote config denying tool
- **Typo in pattern**: Pattern has incorrect spelling

**Solutions**:
- Review merged config in Config tab
- Remove from deny list if unintended
- Use exact tool names (check Violations tab for actual names used)
- Remove expired patterns
- Adjust remote config or override locally

---

### Console Display Issues

**Symptom**: Garbled text, missing colors, layout problems.

**Diagnosis**:
```bash
# Check terminal type
echo $TERM  # Should be xterm-256color or similar

# Check terminal size
tput cols && tput lines

# Test color support
curl -s https://raw.githubusercontent.com/JohnMorales/dotfiles/master/colors/24-bit-color.sh | bash
```

**Solutions**:
- Use terminal with 256-color support (iTerm2, Alacritty, Windows Terminal)
- Increase terminal size to at least 80x24
- Set TERM environment variable: `export TERM=xterm-256color`
- Update terminal emulator to latest version

---

### Secret Scanning Not Working

**Symptom**: Known secrets not detected.

**Diagnosis**:
1. Go to **Global Settings** tab - Check secret scanning is enabled
2. Go to **Secrets** tab - Verify Gitleaks path is set
3. Check Gitleaks installation: `gitleaks version`

**Solutions**:
```bash
# Install Gitleaks
brew install gitleaks  # macOS

# Verify installation
which gitleaks
gitleaks version

# Test Gitleaks manually
echo "AKIAIOSFODNN7EXAMPLE" | gitleaks detect --no-git --redact -

# Check logs for Gitleaks errors
grep -i "gitleaks" ~/.local/state/ai-guardian/ai-guardian.log
```

---

## Technical Implementation

### Architecture

The Console is built using:
- **Textual**: Modern Python Console framework
- **asyncio**: Asynchronous event handling
- **JSON**: Configuration storage and interchange

**Module structure**:
```
src/ai_guardian/tui/
├── app.py                    # Main Console application
├── global_settings.py        # Global Settings tab
├── violations.py             # Violations tab
├── skills.py                 # Skills tab
├── mcp_servers.py            # MCP Servers tab
├── secrets.py                # Secrets tab
├── prompt_injection.py       # Prompt Injection tab
├── remote_configs.py         # Remote Configs tab
├── permissions_discovery.py  # Permissions Discovery tab
├── directory_protection.py   # Directory Protection tab
├── config_viewer.py          # Config tab
├── logs.py                   # Logs tab
├── widgets.py                # Reusable widgets (TimeBasedToggle, etc.)
└── theme.py                  # Color schemes and styling
```

**Total lines of code**: 6,207 across 16 modules.

---

### Data Flow

**Configuration loading**:
```
1. Load built-in defaults
2. Fetch remote configs (if enabled)
3. Discover permissions from directories/repos
4. Load project-local config (.ai-guardian.json)
5. Load user config (~/.config/ai-guardian/ai-guardian.json)
6. Deep merge all sources (higher priority overwrites)
7. Display merged config in Console
```

**User makes change in Console**:
```
1. User clicks button or enters text
2. Event handler validates input
3. Update in-memory configuration
4. Write to user config file (~/.config/ai-guardian/ai-guardian.json)
5. Refresh Console display
6. Emit success/error notification
```

**Violation handling**:
```
1. AI Guardian hook blocks operation
2. Violation logged to ~/.config/ai-guardian/violation.log
3. Violation appears in Console Violations tab
4. User clicks "Approve & Add Rule"
5. Pattern extracted from violation
6. Smart merge check (already covered?)
7. Add to skills.allow[] or mcp_servers.allow[]
8. Save configuration
9. Violation marked as resolved
```

---

### Textual Framework Features Used

**Reactive properties**: Auto-refresh UI when data changes  
**Message passing**: Communication between components  
**Modal screens**: Violation details, add dialogs  
**Custom widgets**: TimeBasedToggle, PatternRow, ViolationCard  
**Bindings**: Keyboard shortcuts (q, r, Escape)  
**CSS styling**: Consistent look and feel  
**Nested tabs**: Violations sub-tabs  

**Benefits of Textual**:
- Modern, maintainable code
- Responsive UI updates
- Built-in accessibility
- Cross-platform (Linux, macOS, Windows)

---

### Configuration File Format

AI Guardian uses JSON for configuration:

**User config**: `~/.config/ai-guardian/ai-guardian.json`
**Project config**: `.ai-guardian.json` (in repo root)
**Violation log**: `~/.config/ai-guardian/violation.log` (JSON lines)
**Application log**: `~/.local/state/ai-guardian/ai-guardian.log` (plain text)

**Schema validation**: JSON is validated against internal schema on load.

**Error handling**:
- Invalid JSON: Error message in Console, fallback to defaults
- Missing fields: Filled with defaults
- Unknown fields: Ignored (forward compatibility)

---

### Performance Considerations

**Large violation logs**:
- Only recent violations loaded by default
- Pagination for large result sets
- Resolved violations archived

**Large configuration**:
- Lazy loading of remote configs
- Cache with expiration
- Incremental refresh

**Responsive UI**:
- Async I/O for network requests
- Background threads for file operations
- Debounced input validation

---

### Scan Configure

Available in both the **Web Console** (Tools > Scan Configure) and **TUI Console** (Tools > Scan Configure).

Exposes the `ai-guardian init-project --scan` functionality in the console UI. Scans a project directory to detect false positive patterns and auto-generate suppression configuration.

#### How It Works

1. **Enter a project directory** and optional FP threshold (default: 10 files)
2. **Click Run Scan** — the scanner runs all detection engines against the project
3. **Review results** — findings are clustered by pattern fingerprint; high-frequency clusters (appearing in many files) are flagged as likely false positives
4. **Preview config changes** — generated `ai-guardian.json` allowlist entries and `.aiguardignore.toml` ignore paths are shown before writing
5. **Choose scope** — save config at **Project** level (in the scanned directory) or **Global** level (`~/.ai-guardian/`)
6. **Apply or Discard** — write the configuration or cancel

#### Key Details

- **All scanners run** regardless of enabled/disabled settings — this discovers all potential false positives upfront so you don't get blocked later when enabling more scanners
- **Progress bar** shows files scanned in real time with cancellation support
- **Rule links** (web console) — each detected rule links to its scanner config page for more context
- **Session persistence** (web console) — scan results survive page navigation; clicking a rule link and returning preserves your results
- **Config merge** — generated config is merged into existing configuration (list values are deduplicated, not overwritten)
- **CLI equivalent**: `ai-guardian init-project --scan --threshold 10`

## Summary

The AI Guardian Console provides a comprehensive, user-friendly interface for managing security policies:

- **11 specialized tabs** covering all aspects of AI security
- **Time-based permissions** for temporary elevated access
- **One-click violation approval** for rapid workflow
- **Remote config support** for enterprise policy management
- **Smart rule merging** to keep configuration clean
- **Real-time validation** to prevent errors
- **Full keyboard navigation** for power users

For questions, issues, or feature requests, see the main [AI Guardian repository](https://github.com/RedHatProductSecurity/ai-guardian).
