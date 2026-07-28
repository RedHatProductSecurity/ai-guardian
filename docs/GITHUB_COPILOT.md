# GitHub Copilot Integration Guide

This guide explains how to integrate AI Guardian with [GitHub Copilot](https://github.com/features/copilot) using its hook system.

## Overview

AI Guardian integrates with GitHub Copilot through **native hooks** that intercept prompts and tool usage before they're sent to the AI. This provides **real-time protection** by scanning for secrets and enforcing security policies during AI interactions.

### Protection Levels

✅ **Real-time scanning**:
- Scans user prompts before submission (`userPromptSubmitted` hook)
- Scans tool inputs before execution (`preToolUse` hook)
- Blocks operations containing secrets or accessing denied directories
- Enforces MCP/Skill permissions

## Prerequisites

### Required

1. **GitHub Copilot** - Installed and activated
   - GitHub Copilot subscription (Individual, Business, or Enterprise)
   - VS Code with GitHub Copilot extension, or
   - GitHub Copilot CLI

2. **Gitleaks** - Secret scanning engine
   ```bash
   # macOS
   brew install gitleaks

   # Linux (Ubuntu/Debian)
   curl -sSfL https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz | tar -xz
   sudo mv gitleaks /usr/local/bin/

   # Windows (using scoop)
   scoop install gitleaks
   ```

3. **AI Guardian** - Installed via uv or pip
   ```bash
   uv tool install ai-guardian        # recommended
   # or: pip install ai-guardian
   ```

## Installation

### Method 1: Automatic Setup (Recommended)

Use the `ai-guardian setup` command:

```bash
# Auto-detect and setup GitHub Copilot hooks
ai-guardian setup --ide copilot

# Or with confirmation prompt
ai-guardian setup --ide copilot --yes
```

The setup command will:
1. Detect your GitHub Copilot configuration
2. Add ai-guardian hooks to `~/.github/hooks/hooks.json`
3. Create a backup of your existing configuration
4. Merge with any existing hooks

### Method 2: Manual Setup

**Step 1: Locate GitHub Copilot hooks configuration**

The hooks configuration file is typically at:
```
~/.github/hooks/hooks.json
```

**Step 2: Create or edit hooks.json**

If the file doesn't exist, create it:

```bash
mkdir -p ~/.github/hooks
cat > ~/.github/hooks/hooks.json << 'EOF'
{
  "userPromptSubmitted": [
    {
      "command": "ai-guardian"
    }
  ],
  "preToolUse": [
    {
      "command": "ai-guardian"
    }
  ]
}
EOF
```

If the file exists, merge the hooks:

```json
{
  "userPromptSubmitted": [
    {
      "command": "ai-guardian"
    }
  ],
  "preToolUse": [
    {
      "command": "ai-guardian"
    }
  ]
}
```

**Step 3: Verify installation**

Test that ai-guardian is accessible:

```bash
which ai-guardian
# Should output: /path/to/bin/ai-guardian
```

## Configuration

### Hook Configuration

GitHub Copilot hooks are configured in `~/.github/hooks/hooks.json`:

```json
{
  "userPromptSubmitted": [
    {
      "command": "ai-guardian",
      "description": "Scan prompts for secrets before submission"
    }
  ],
  "preToolUse": [
    {
      "command": "ai-guardian",
      "description": "Check tool permissions and scan inputs"
    }
  ]
}
```

### Available Hooks

GitHub Copilot supports these hooks:

| Hook | Purpose | AI Guardian Support |
|------|---------|-------------------|
| `userPromptSubmitted` | Before sending prompt to AI | ✅ Supported |
| `preToolUse` | Before tool execution | ✅ Supported |
| `postToolUse` | After tool execution | ⏭️ Future |

### AI Guardian Configuration

Configure ai-guardian behavior in `~/.config/ai-guardian/ai-guardian.json`:

```json
{
  "tool_policy": {
    "default_action": "allow",
    "rules": [
      {
        "tool_pattern": "mcp__*",
        "action": "block",
        "reason": "MCP servers require explicit approval"
      }
    ]
  },
  "prompt_injection": {
    "enabled": true,
    "confidence_threshold": 0.8
  }
}
```

See [Configuration Guide](../README.md#configuration) for details.

## Usage

Once installed, AI Guardian runs automatically:

### Normal Operation

When you use GitHub Copilot:

1. **Type a prompt**: AI Guardian scans for secrets
2. **Copilot suggests code**: AI Guardian checks tool usage
3. **Clean content**: Request proceeds normally
4. **Secrets detected**: Request blocked with error message

### Example: Blocked Request

```
User prompt: "Deploy using API key: sk_live_abc123..."

🛡️ Secret Detected

Protection: Secret Scanning
Secret Type: stripe-api-key
Location: prompt:line 1
Scanner: Gitleaks
Pattern source: Default Gitleaks rules

Why blocked: Hard-coded secrets in prompts create security risks.
Secrets should never be included in AI prompts or source code.

This operation has been blocked for security.
DO NOT attempt to bypass this protection - it prevents credential leaks.

Recommendation:
- Store secrets in environment variables or secret managers
- Use placeholder values in examples (e.g., "sk_test_example_key")
- Never paste real API keys, tokens, or passwords

⚠️ Secret value NOT shown in this message for security

Config: ~/.config/ai-guardian/ai-guardian.json
Section: secret_scanning.enabled
```

### Example: Allowed Request

```
User prompt: "Refactor this function for better readability"

✓ No secrets detected
✓ Request allowed
```

## Response Format

GitHub Copilot expects specific JSON responses:

### userPromptSubmitted Hook

**Input from Copilot**:
```json
{
  "timestamp": 1704614400000,
  "cwd": "/path/to/project",
  "prompt": "User's prompt text",
  "source": "user"
}
```

**AI Guardian Response** (exit code only):
- Exit code 0: Allow prompt
- Exit code 2: Block prompt (with error message on stderr)

### preToolUse Hook

**Input from Copilot**:
```json
{
  "timestamp": 1704614600000,
  "cwd": "/path/to/project",
  "toolName": "bash",
  "toolArgs": "{\"command\":\"npm test\",\"description\":\"Run tests\"}"
}
```

**AI Guardian Response** (JSON):
```json
{
  "permissionDecision": "allow",
  "permissionDecisionReason": "Tool is allowed"
}
```

Or when blocked:
```json
{
  "permissionDecision": "deny",
  "permissionDecisionReason": "Secrets detected in tool arguments"
}
```

## Environment Variables

### AI_GUARDIAN_IDE_TYPE

Override IDE detection:

```bash
export AI_GUARDIAN_IDE_TYPE=copilot
```

Or:

```bash
export AI_GUARDIAN_IDE_TYPE=github_copilot
```

## Troubleshooting

### Hooks Not Running

**Problem**: AI Guardian doesn't seem to be blocking anything

**Solutions**:
1. Verify hooks.json exists: `cat ~/.github/hooks/hooks.json`
2. Check ai-guardian is in PATH: `which ai-guardian`
3. Test manually:
   ```bash
   echo '{"timestamp":1704614400000,"cwd":"/tmp","prompt":"test"}' | ai-guardian
   ```
4. Restart VS Code or Copilot CLI

### Permission Errors

**Problem**: `Permission denied` when running ai-guardian

**Solution**: Ensure ai-guardian is executable:
```bash
chmod +x $(which ai-guardian)
```

### JSON Parse Errors

**Problem**: `Failed to parse hook input`

**Solution**: GitHub Copilot might be sending unexpected format. Enable debug logging:
```bash
export AI_GUARDIAN_DEBUG=1
```

Then check stderr output for details.

### Gitleaks Not Found

**Problem**: `gitleaks: command not found`

**Solution**: Install gitleaks (see Prerequisites)

### False Positives

**Problem**: Legitimate content flagged as secrets

**Solutions**:
1. Add allowlist rules to `.gitleaks.toml` in your project
2. Use `gitleaks:allow` comment in code
3. Adjust pattern server configuration (if using)

### Performance Issues

**Problem**: AI Guardian slows down Copilot responses

**Solution**: This is expected for security scanning. To optimize:
1. Use project-specific `.gitleaks.toml` with focused rules
2. Disable prompt injection detection if not needed
3. Use in-memory temp files (automatic on Linux with `/dev/shm`)

## Security Considerations

### What AI Guardian Protects Against

✅ **Secrets in prompts**:
- API keys, tokens, passwords
- Private keys (SSH, PGP, RSA)
- Cloud credentials (AWS, GCP, Azure)
- Database connection strings

✅ **Directory blocking**:
- Files in directories with `.ai-read-deny` markers
- Prevents access to sensitive codebases

✅ **Tool permissions**:
- MCP server usage
- Skill execution
- Custom tool policies

### What AI Guardian Does NOT Protect Against

❌ **Secrets already in code** (use separate static analysis)
❌ **Secrets in git history** (use git-secrets or TruffleHog)
❌ **Network exfiltration** (use network policies)
❌ **Malicious tool installation** (use code review)

### Defense in Depth

**Recommended layers**:
1. **AI Guardian hooks** - Real-time prompt/tool scanning
2. **Git pre-commit hooks** - Commit-time verification
3. **CI/CD scanning** - Build-time secret detection
4. **Secret rotation** - Regular credential updates
5. **Monitoring** - Detect unusual AI usage patterns

## Advanced Configuration

### Custom Secret Patterns

Create `.gitleaks.toml` in your project:

```toml
title = "Custom Secret Rules"

[[rules]]
id = "company-api-key"
description = "Company API Key"
regex = '''company-api-[a-zA-Z0-9]{32}'''
tags = ["api", "company"]
```

### Tool Policy Rules

Configure MCP/Skill permissions in `~/.config/ai-guardian/ai-guardian.json`:

```json
{
  "tool_policy": {
    "default_action": "allow",
    "rules": [
      {
        "tool_pattern": "mcp__database__*",
        "action": "block",
        "reason": "Database operations require manual approval"
      },
      {
        "tool_pattern": "Bash",
        "allowed_commands": ["ls", "cat", "grep"],
        "action": "conditional"
      }
    ]
  }
}
```

### Prompt Injection Detection

Enable advanced prompt injection detection:

> **Note**: Specific attack pattern examples are not included for security reasons. See the main README FAQ for guidance on researching prompt injection safely.

```json
{
  "prompt_injection": {
    "enabled": true,
    "confidence_threshold": 0.8,
    "methods": ["heuristic", "vector"],
    "custom_patterns": [
      "company_specific_pattern_.*"
    ]
  }
}
```

## Enterprise Deployment

### Centralized Configuration

Use remote configuration for team-wide policies:

```bash
ai-guardian setup --ide copilot --remote-config-url https://company.com/ai-guardian-policy.json
```

Remote config example:

```json
{
  "tool_policy": {
    "default_action": "block",
    "rules": [
      {
        "tool_pattern": "Bash",
        "action": "allow",
        "allowed_commands": ["git", "npm", "make"]
      }
    ]
  },
  "allowed_directories": [
    "/projects/public/*"
  ],
  "blocked_directories": [
    "/projects/secrets/*",
    "/projects/private/*"
  ]
}
```

### Monitoring and Compliance

Track ai-guardian usage for compliance:

1. **Enable audit logging** (if available in your GitHub Copilot plan)
2. **Monitor blocked requests** via stderr logs
3. **Review patterns** to identify training needs
4. **Adjust policies** based on usage patterns

## Comparison: Copilot vs Other IDEs

| Feature | GitHub Copilot | Claude Code | Cursor |
|---------|---------------|-------------|--------|
| **Hook Type** | Native hooks | Native hooks | Native hooks |
| **Trigger Point** | Prompt + Tool | Prompt + Tool | Prompt + Tool |
| **Response Format** | JSON (tools), Exit code (prompts) | Exit codes | JSON |
| **Setup Complexity** | Medium | Low | Low |
| **Permission Levels** | allow/deny | allow/block | allow/deny |

## Resources

- [GitHub Copilot Documentation](https://docs.github.com/en/copilot)
- [GitHub Copilot Hooks Documentation](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-hooks)
- [AI Guardian Configuration](../README.md#configuration)
- [Gitleaks Configuration](https://github.com/gitleaks/gitleaks#configuration)

## Getting Help

**Issues with ai-guardian**:
- GitHub Issues: https://github.com/RedHatProductSecurity/ai-guardian/issues

**Issues with GitHub Copilot**:
- GitHub Support: https://support.github.com/

**Security concerns**:
- Open an issue with `[SECURITY]` prefix
