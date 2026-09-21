# AiderDesk Integration

AI Guardian integrates with [AiderDesk](https://github.com/hotovo/aider-desk) via its Extension system (introduced in v0.55.0).

> **Note**: AiderDesk (GUI desktop app) is different from Aider (CLI tool). For Aider CLI integration via git hooks, see [AIDER.md](AIDER.md).

## How It Works

Unlike other IDEs that use shell-based hooks or JSON config files, AiderDesk uses TypeScript/JavaScript extensions. AI Guardian ships a thin host extension plus a shared TypeScript process bridge that:

1. Hooks into AiderDesk events (tool calls, prompts, file access, commits)
2. Delegates process execution, timeout handling, environment propagation, and response parsing to `ai-guardian-bridge.ts`
3. Spawns `ai-guardian` as a child process with event data on stdin and translates the bridge result into AiderDesk's expected format

The bridge reuses the same exit-code protocol as Kiro hooks:
- **Exit 0** = allow (stdout content sent as context)
- **Exit 1 or 2** = block (stderr content shown as error)
- Other process failures and timeouts fail open, matching the existing extension behavior

## Prerequisites

- AiderDesk v0.55.0 or later
- Node.js (already required by AiderDesk)
- `ai-guardian` installed and on PATH

## Installation

```bash
# Install the extension
ai-guardian setup --ide aiderdesk

# Install dependencies
cd ~/.aider-desk/extensions/ai-guardian
npm install

# MCP server is installed by default (use --no-mcp to skip)
ai-guardian setup --ide aiderdesk
```

The extension installs to `~/.aider-desk/extensions/ai-guardian/` (global scope). AiderDesk automatically detects and hot-reloads extensions.

### Dry Run

Preview what would be installed without making changes:

```bash
ai-guardian setup --ide aiderdesk --dry-run
```

### Force Reinstall

Overwrite an existing installation:

```bash
ai-guardian setup --ide aiderdesk --force
```

## What Gets Scanned

| AiderDesk Event | AI Guardian Check | Blocking |
|---|---|---|
| Tool approval (`onToolApproval`) | Secret scanning, directory rules, SSRF | Yes |
| Tool execution (`onToolCalled`) | Secret scanning, directory rules | Yes |
| Tool output (`onToolFinished`) | Secret/PII redaction | Modified output |
| Prompt submission (`onPromptStarted`) | Prompt injection detection | Yes |
| File context (`onFilesAdded`) | Directory access rules | Yes |
| Git commits (`onBeforeCommit`) | Secret scanning | Yes |

## Extension Files

After installation, the extension directory contains:

```
~/.aider-desk/extensions/ai-guardian/
  index.ts          # Extension source (TypeScript)
  ai-guardian-bridge.ts  # Shared process and response bridge
  package.json      # Dependencies (@aiderdesk/extensions)
  node_modules/     # Created by npm install
```

## Verifying Installation

1. Open AiderDesk
2. The extension should appear in the extensions list
3. Try a command that would be blocked (e.g., accessing a protected directory)
4. Check AI Guardian logs: `ai-guardian violations list`

## Comparison with Other IDEs

| Feature | Shell Hooks (Claude, Kiro) | JSON Config (Cursor, Copilot) | Extension (AiderDesk) |
|---|---|---|---|
| Language | Shell script | JSON config | TypeScript |
| Location | `.ide/hooks/` | `~/.ide/config.json` | `~/.aider-desk/extensions/` |
| Setup | `ai-guardian setup --ide X` | `ai-guardian setup --ide X` | `ai-guardian setup --ide aiderdesk` + `npm install` |
| Hot reload | No (restart IDE) | No (restart IDE) | Yes (automatic) |
| Node.js required | No | No | Yes |

## Troubleshooting

### Extension Not Loading

1. Verify the extension directory exists: `ls ~/.aider-desk/extensions/ai-guardian/`
2. Verify dependencies installed: `ls ~/.aider-desk/extensions/ai-guardian/node_modules/`
3. If `node_modules/` is missing, run `cd ~/.aider-desk/extensions/ai-guardian && npm install`

### ai-guardian Not Found

The extension calls `ai-guardian` from PATH. Verify it's accessible:

```bash
which ai-guardian
ai-guardian --version
```

### Blocked Operations Not Working

1. Check ai-guardian config: `ai-guardian doctor`
2. Verify scanner is installed: `ai-guardian scanner list`
3. Check violations log: `ai-guardian violations list`

## Uninstalling

Remove the extension directory:

```bash
rm -rf ~/.aider-desk/extensions/ai-guardian
```

To also remove MCP server config:

```bash
ai-guardian setup --ide aiderdesk --no-mcp
```
