# Aider Integration Guide

This guide explains how to integrate AI Guardian with [Aider](https://aider.chat), the AI pair programming tool.

## Overview

Aider integrates with AI Guardian through **git pre-commit hooks**. This provides a **last line of defense** by scanning staged files for secrets before they are committed to your repository.

### Protection Level

⚠️ **Important Limitation**: Unlike Claude Code or Cursor integration, Aider's git hook integration only scans at **commit time**, not during AI generation. This means:

- ✅ **Blocks commits** with secrets from entering git history
- ✅ **Prevents accidental exposure** through version control
- ❌ **Does NOT scan prompts** during AI interaction
- ❌ **Does NOT prevent** AI from seeing secrets in working directory

This is a **complementary protection layer** to IDE-based hooks, not a replacement.

## Prerequisites

### Required

1. **Gitleaks** - Secret scanning engine
   ```bash
   # macOS
   brew install gitleaks

   # Linux (Ubuntu/Debian)
   curl -sSfL https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz | tar -xz
   sudo mv gitleaks /usr/local/bin/

   # Windows (using scoop)
   scoop install gitleaks
   ```

2. **Aider** - AI pair programming tool
   ```bash
   pip install aider-chat
   ```

### Optional

- **pre-commit framework** (for advanced hook management)
  ```bash
  pip install pre-commit
  ```

## Installation Methods

Choose one of the following methods:

### Method 1: Manual Git Hook (Recommended)

This method directly installs a git pre-commit hook.

**Step 1: Copy the pre-commit hook**

```bash
# From the ai-guardian repository
cp examples/aider/pre-commit-hook.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Or create manually:

```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# AI Guardian pre-commit hook for Aider
# Scans staged files for secrets before commit

set -e

echo "🛡️ AI Guardian: Scanning staged files for secrets..."

# Get list of staged files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACMR)

if [ -z "$STAGED_FILES" ]; then
  echo "✓ No files staged for commit"
  exit 0
fi

# Create temporary directory for staged content
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Extract each staged file to temp directory
echo "$STAGED_FILES" | while IFS= read -r file; do
  if [ -z "$file" ]; then continue; fi
  mkdir -p "$TEMP_DIR/$(dirname "$file")"
  git show ":$file" > "$TEMP_DIR/$file" 2>/dev/null || true
done

# Scan temp directory with gitleaks
if gitleaks detect \
    --source "$TEMP_DIR" \
    --no-git \
    --redact \
    --verbose \
    --exit-code 42; then
  echo "✓ No secrets detected in staged files"
  exit 0
else
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 42 ]; then
    echo ""
    echo "❌ COMMIT BLOCKED: Secrets detected in staged files"
    echo ""
    echo "Please remove sensitive information and try again."
    echo ""
    exit 1
  else
    echo "⚠️ Warning: Gitleaks scan failed (exit code: $EXIT_CODE)"
    echo "Allowing commit to proceed (fail-open policy)"
    exit 0
  fi
fi
EOF

chmod +x .git/hooks/pre-commit
```

**Step 2: Configure Aider**

Create `.aider.conf.yml` in your project root:

```bash
cp examples/aider/.aider.conf.yml .aider.conf.yml
```

Or create manually:

```bash
cat > .aider.conf.yml << 'EOF'
# Enable pre-commit hook verification
git-commit-verify: true
EOF
```

**Step 3: Test**

```bash
# Test the hook manually
echo "test-secret: ghp_16C0123456789abcdefghijklmTEST0000" > test-secret.txt
git add test-secret.txt
git commit -m "test commit"
# Should block with "COMMIT BLOCKED: Secrets detected"

# Clean up
rm test-secret.txt
git reset HEAD
```

### Method 2: pre-commit Framework

This method uses the `pre-commit` framework for hook management.

**Step 1: Install pre-commit**

```bash
pip install pre-commit
```

**Step 2: Create configuration**

```bash
cp examples/aider/.pre-commit-config.yaml .pre-commit-config.yaml
```

Or create manually:

```bash
cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
        name: Detect secrets with gitleaks
        entry: gitleaks detect --no-git --redact --verbose --exit-code 42
        language: golang
        stages: [commit]
        pass_filenames: false
EOF
```

**Step 3: Install hooks**

```bash
pre-commit install
```

**Step 4: Configure Aider**

```bash
cat > .aider.conf.yml << 'EOF'
git-commit-verify: true
EOF
```

**Step 5: Test**

```bash
# Test with pre-commit
pre-commit run --all-files
```

## Usage

Once installed, use Aider normally:

```bash
# Start Aider with verification enabled
aider [files]
```

Aider will automatically run the pre-commit hook before committing. If secrets are detected, the commit will be blocked:

```
🛡️ AI Guardian: Scanning staged files for secrets...

❌ COMMIT BLOCKED: Secrets detected in staged files

Please remove sensitive information and try again.
```

## Configuration

### Aider Settings

The `.aider.conf.yml` file controls Aider's behavior:

```yaml
# Enable pre-commit hook verification (REQUIRED)
git-commit-verify: true

# Optional: Other Aider settings
auto-commits: true
dirty-commits: false
```

### Gitleaks Configuration

You can customize secret detection rules by creating `.gitleaks.toml` in your project root:

```toml
# Example: Allow specific patterns
[allowlist]
  description = "Allow test secrets"
  regexes = [
    '''test-api-key-[a-zA-Z0-9]{16}''',
  ]
  paths = [
    '''tests/fixtures/.*''',
  ]
```

See [Gitleaks documentation](https://github.com/gitleaks/gitleaks#configuration) for details.

### Fail Policy

The default behavior is **fail-open**: if gitleaks encounters an error (not secrets found), the commit is allowed. This ensures availability.

To change to **fail-closed** (block on errors), edit `.git/hooks/pre-commit`:

```bash
# Change this section:
else
  # Gitleaks error (not secrets found)
  echo "⚠️ Warning: Gitleaks scan failed (exit code: $EXIT_CODE)"
  echo "Allowing commit to proceed (fail-open policy)"
  exit 0
fi

# To this:
else
  echo "❌ COMMIT BLOCKED: Gitleaks scan failed"
  exit 1
fi
```

## Troubleshooting

### Hook Not Running

**Problem**: Commits succeed without scanning

**Solutions**:
1. Verify hook is executable: `ls -la .git/hooks/pre-commit`
2. Make executable if needed: `chmod +x .git/hooks/pre-commit`
3. Check Aider config: `cat .aider.conf.yml` should have `git-commit-verify: true`
4. Test hook manually: `.git/hooks/pre-commit`

### Gitleaks Not Found

**Problem**: `gitleaks: command not found`

**Solution**: Install gitleaks (see Prerequisites above)

### False Positives

**Problem**: Legitimate content flagged as secrets

**Solutions**:
1. Add allowlist rules to `.gitleaks.toml`
2. Use `gitleaks:allow` comment in code:
   ```python
   api_key = "test-key-12345"  # gitleaks:allow
   ```

### Hook Bypassed

**Problem**: Someone commits without running hooks

**Solution**: Enforce hooks at the server level using:
- GitHub: Branch protection rules + push restrictions
- GitLab: Server-side hooks
- Pre-receive hooks on git server

### Performance Issues

**Problem**: Hook takes too long for large commits

**Solution**: Optimize by scanning only changed files:
```bash
# In .git/hooks/pre-commit, replace the scan section with:
for file in $STAGED_FILES; do
  if [ -z "$file" ]; then continue; fi
  
  git show ":$file" | gitleaks detect --no-git --stdin --redact --exit-code 42
  if [ $? -eq 42 ]; then
    echo "❌ Secrets detected in $file"
    exit 1
  fi
done
```

## Comparison: Aider vs IDE Hooks

| Feature | Aider (git hooks) | Claude Code/Cursor |
|---------|------------------|-------------------|
| **Trigger Point** | Before git commit | Before prompt submission |
| **Protection Level** | Commit-time | Real-time (during AI use) |
| **Scans** | Staged files only | Prompts + files |
| **Performance Impact** | Only during commits | Every AI interaction |
| **Setup Complexity** | Low | Medium |
| **Bypass Protection** | git commit --no-verify | No easy bypass |

**Recommendation**: Use **both** for defense-in-depth:
- IDE hooks (Claude Code/Cursor): Real-time protection
- Aider git hooks: Commit-time verification (last line of defense)

## Advanced Usage

### Multiple Projects

To share the hook across projects, use git templates:

```bash
# Create template directory
mkdir -p ~/.git-templates/hooks

# Copy hook
cp examples/aider/pre-commit-hook.sh ~/.git-templates/hooks/pre-commit
chmod +x ~/.git-templates/hooks/pre-commit

# Configure git to use template
git config --global init.templateDir ~/.git-templates

# For existing repos
git init
```

### CI/CD Integration

Run the same scan in CI/CD:

```yaml
# .github/workflows/security.yml
name: Security Scan
on: [push, pull_request]

jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0
      
      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Custom Scan Rules

Create organization-specific rules:

```toml
# .gitleaks.toml
title = "Organization Secret Rules"

[[rules]]
id = "org-api-key"
description = "Organization API Key"
regex = '''org-api-[a-zA-Z0-9]{32}'''
tags = ["api", "organization"]

[[rules]]
id = "internal-token"
description = "Internal Service Token"
regex = '''int-tok-[a-zA-Z0-9]{24}'''
tags = ["token", "internal"]
```

## Security Best Practices

1. **Enable verification**: Always set `git-commit-verify: true` in `.aider.conf.yml`
2. **Regular updates**: Keep gitleaks updated: `brew upgrade gitleaks`
3. **Custom rules**: Add organization-specific secret patterns
4. **Multiple layers**: Use both IDE hooks and git hooks
5. **Server-side enforcement**: Configure server-side hooks for ultimate protection
6. **Monitor bypasses**: Track `git commit --no-verify` usage
7. **Education**: Train team on why hooks exist and how to use them

## Resources

- [Aider Documentation](https://aider.chat/docs/)
- [Aider Git Integration](https://aider.chat/docs/git.html)
- [Gitleaks Configuration](https://github.com/gitleaks/gitleaks#configuration)
- [Git Hooks Documentation](https://git-scm.com/docs/githooks)
- [pre-commit Framework](https://pre-commit.com/)

## Getting Help

**Issues with ai-guardian**:
- GitHub Issues: https://github.com/RedHatProductSecurity/ai-guardian/issues

**Issues with Aider**:
- Aider Discord: https://aider.chat/docs/discord.html
- GitHub Issues: https://github.com/paul-gauthier/aider/issues

**Issues with Gitleaks**:
- GitHub Issues: https://github.com/gitleaks/gitleaks/issues
