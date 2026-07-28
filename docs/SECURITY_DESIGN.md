# Security Design

AI Guardian's security architecture is built on defense-in-depth principles with self-protecting mechanisms that prevent AI agents from disabling their own security controls.

## Architecture Principles

- **Defense in Depth**: One layer in a multi-layered security strategy
- **Three-layer model**: MCP advisor (proactive, optional) → Skill instructions (guidance) → Hooks (enforcement, mandatory)
- **Fail-open**: If scanning errors occur, allows operation (availability over security)
- **In-memory scanning**: Uses `/dev/shm` on Linux for performance
- **Secure cleanup**: Overwrites temp files before deletion
- **No logging**: Secrets are never logged or stored
- **Privacy-first**: Heuristic detection runs locally, no external calls
- **MCP security boundary**: MCP tools expose yes/no decisions only — never rules, patterns, or allowlists (see [MCP Server](MCP_SERVER.md))

## Self-Protecting Security Architecture

AI Guardian uses **hardcoded deny patterns** that protect its own critical files from being modified by AI agents. This prevents AI from disabling security features or bypassing protection.

### Protected Files

1. **Configuration files** - Prevents AI from disabling security features
   - `~/.config/ai-guardian/ai-guardian.json` (global config)
   - `.ai-guardian/ai-guardian.json` (project config, NEW in v1.8.0)
   - `./.ai-guardian.json` (legacy)
   - Any file matching `*ai-guardian.json`

2. **IDE hook files** - Prevents AI from removing ai-guardian hooks
   - `~/.claude/settings.json` (Claude Code)
   - `~/.cursor/hooks.json` (Cursor IDE)

3. **Package source code** - Prevents AI from editing protection logic
   - `*/ai_guardian/*` (all package files)
   - `*/site-packages/ai_guardian/*`

4. **Directory protection markers** - Prevents AI from removing `.ai-read-deny` files
   - `*/.ai-read-deny` (all directory markers)
   - `**/.ai-read-deny` (recursive protection)

### How Self-Protection Works

The protection works through an **unbreakable loop**:

1. Deny patterns are checked in the PreToolUse hook **BEFORE** any tool executes
2. If a tool tries to modify a protected file, the operation is **BLOCKED**
3. The tool never executes, so the file is never modified
4. AI cannot edit the source code to remove the protection because editing is blocked by the same protection

### Example Attack Scenarios (All Blocked)

```bash
# Try 1: Edit config file
Edit(file_path="~/.config/ai-guardian/ai-guardian.json")
# BLOCKED by "*ai-guardian.json" pattern

# Try 2: Remove Claude hooks
Edit(file_path="~/.claude/settings.json")
# BLOCKED by "*/.claude/settings.json" pattern

# Try 3: Edit source code to disable protection
Edit(file_path="~/.local/lib/.../ai_guardian/tool_policy.py")
# BLOCKED by "*/ai_guardian/*" pattern

# Try 4: Use sed to bypass
Bash(command="sed -i 's/IMMUTABLE/DISABLED/' ~/.local/lib/.../ai_guardian/tool_policy.py")
# BLOCKED by "*sed*ai_guardian*" pattern

# Try 5: Use echo redirect to overwrite
Bash(command="echo '{}' > ~/.config/ai-guardian/ai-guardian.json")
# BLOCKED by "*>*ai-guardian*" pattern

# Try 6: Delete config file
Bash(command="rm ~/.config/ai-guardian/ai-guardian.json")
# BLOCKED by "*rm*ai-guardian.json*" pattern

# Try 7: Bypass directory protection by removing marker
Bash(command="rm ~/secrets/.ai-read-deny")
# BLOCKED by "*rm*.ai-read-deny*" pattern

# Try 8: Rename directory protection marker
Bash(command="mv .ai-read-deny .ai-read-deny.bak")
# BLOCKED by "*mv*.ai-read-deny*" pattern
```

### Why Filesystem Permissions Don't Work

AI Guardian's config directory is **always in the user's HOME directory**:
- Default: `~/.config/ai-guardian/`
- XDG: `$XDG_CONFIG_HOME/ai-guardian/`
- Custom: `$AI_GUARDIAN_CONFIG_DIR`

All paths resolve to the HOME directory, which is **always writable by the user** (and therefore by AI agents). Filesystem permissions cannot protect these files.

**Solution:** Hardcoded protection at the tool invocation level is the only cross-platform approach that works reliably.

### What Happens When Protection Triggers

```
Immutable Protection

Protection: Configuration File
Tool: Edit
File Path: ~/.claude/settings.json
Pattern: */.claude/settings.json

Why blocked: This is an ai-guardian or IDE hook configuration file.
Modifying these files could disable security protections.

This operation has been blocked for security.
DO NOT attempt to bypass this protection - it prevents security control tampering.

Recommendation:
- Configuration files must be edited manually (not by AI agents)
- Use your text editor to modify these files
- This prevents AI from disabling its own security controls

Protected categories:
- ai-guardian configuration files
- IDE hook configuration (Claude, Cursor)
- ai-guardian package source code
- .ai-read-deny marker files

This protection is immutable and cannot be disabled via configuration.
It ensures ai-guardian security controls cannot be bypassed.
```

### User Override

If you need to edit these files:
- Use your text editor manually (vim, nano, VS Code, etc.)
- The protection only blocks **AI agent** access via tools
- You retain full control over your configuration

If a user manually edits the source code to remove the protection:
- This is an intentional choice by the user
- Same as uninstalling ai-guardian entirely
- Not an AI bypass (requires manual intervention)

## Maintainer Bypass for Development

GitHub maintainers of the AI Guardian project can edit source code with AI assistance:

```bash
# Prerequisites
# 1. Authenticate with GitHub CLI
gh auth login

# 2. Be a collaborator on the repository
# (check: gh api repos/RedHatProductSecurity/ai-guardian/collaborators/YOUR_USERNAME)

# Now AI can help edit source files
# Allowed for maintainers:
Edit src/ai_guardian/tools/policy.py
Write tests/test_new_feature.py
Edit README.md

# But config files remain protected (even for maintainers):
# BLOCKED: Edit ~/.config/ai-guardian/ai-guardian.json
# BLOCKED: Edit ~/.claude/settings.json
# BLOCKED: Write ~/.cache/ai-guardian/maintainer-status.json
```

### How Maintainer Bypass Works

1. **GitHub OAuth Authentication** - Uses `gh` CLI to verify your GitHub identity
2. **Collaborator Check** - Confirms write access via GitHub API
3. **Scoped Bypass** - Only allows editing source code, never config files
4. **Automatic** - Works transparently when you're a maintainer
5. **Cached** - Status cached for 24 hours to avoid API rate limits

### Security Model

The bypass prevents **two distinct threat models**:

- **Threat A (Non-Maintainers)**: Blocked by GitHub collaborator check
  - AI can't fake OAuth credentials
  - GitHub API verifies real permissions

- **Threat B (Malicious Prompts to Maintainers)**: Blocked by scoped protection
  - Config files always protected (even for maintainers)
  - Cache files always protected (prevents poisoning)
  - Malicious prompts can't disable security features

### Troubleshooting

If maintainer bypass isn't working:

1. Check GitHub authentication: `gh auth status`
2. Verify collaborator access: `gh api repos/RedHatProductSecurity/ai-guardian/collaborators/YOUR_USERNAME`
3. Clear cache: `rm ~/.cache/ai-guardian/maintainer-status.json`
4. Check repo URL: `git config --get remote.origin.url` (must be github.com)

**Fork-Friendly:** Works on your own fork too! If you're a maintainer of `yourname/ai-guardian`, you can edit your fork's source code.

## Known Limitations

AI Guardian is not perfect and has known limitations.

### Prompt Injection Detection

- Heuristic pattern matching can be bypassed with novel techniques
- New attack vectors emerge faster than detection patterns update
- Trade-off between false positives (blocking legitimate text) and false negatives (missing attacks)

### Secret Scanning

- Depends on Gitleaks community-maintained patterns
- May miss organization-specific or custom secret formats
- Requires regular updates to detect new secret types

### Fail-Open Design

- Prioritizes availability over absolute security
- Detection errors allow operations to proceed (won't block legitimate work)
- Not suitable for zero-trust environments requiring fail-closed behavior

### Shell Mode (`!` Prefix) Bypass

Commands run with the `!` prefix in Claude Code (e.g., `! cat .env`) execute locally and bypass **all** ai-guardian hooks (UserPromptSubmit, PreToolUse, PostToolUse). The command text and output are added directly to the AI's conversation context **without any security scanning**.

This means:
- Secrets typed in `!` commands reach the AI model undetected
- PII in `!` command output is not redacted
- Prompt injection in `!` command output is not checked
- No violation is logged at the time of execution

**Do NOT use `!` commands to:**
- Display files containing secrets (`! cat .env`, `! cat ~/.aws/credentials`)
- Run commands that output credentials (`! aws sts get-caller-identity`)
- Paste or echo sensitive data (`! echo "API_KEY=..."`)
- Read untrusted files that could contain prompt injection

**Instead use:** Regular commands (without `!`) which go through Claude's Bash tool and are scanned by ai-guardian's PreToolUse and PostToolUse hooks.

**Mitigation:** Transcript scanning (v1.7.0, Issue #430) provides after-the-fact detection by scanning the conversation transcript for secrets, PII, and prompt injection on each `UserPromptSubmit` event. However, this is detection-only — it cannot block content already in the AI's context.

### What AI Guardian Protects Against

**Common threats it catches:**
- Known prompt injection patterns (instruction override, role manipulation, etc.)
- Standard secret formats (GitHub tokens, AWS keys, API keys, etc.)
- Accidental exposure of sensitive directories
- Unauthorized MCP server and skill access

**Threats it may miss:**
- Novel or zero-day prompt injection techniques
- Custom/proprietary secret formats
- Obfuscated or encoded attacks
- Social engineering attacks
- Compromised AI models

**Bottom line: Use AI Guardian as part of a comprehensive security strategy, not as sole protection.**

## Immutable Remote Configurations

Remote configurations can mark sections and permission rules as `immutable` to prevent local configs from overriding them. See [Configuration Guide](CONFIGURATION.md) for details on:

- Per-matcher immutability
- Section immutability
- Enterprise policy enforcement examples
