# Scanner Installation Guide

> **No external scanner required.** ai-guardian includes a built-in `toml-patterns` engine (267+ regex patterns, pure Python) that provides comprehensive secret scanning without installing any external binary. External scanners like gitleaks and betterleaks are optional — they add additional pattern coverage but are not required.

AI Guardian provides automated installation and management of secret scanner engines to make setup as easy as possible.

## Supported Scanners

| Scanner | Speed | License | Installation |
|---------|-------|---------|--------------|
| Gitleaks | Standard | MIT | `ai-guardian scanner install gitleaks` |
| BetterLeaks | 20-40% faster | MIT | `ai-guardian scanner install betterleaks` |
| LeakTK | Standard | Apache-2.0 | `ai-guardian scanner install leaktk` |
| Secretlint | Local rules | MIT | `ai-guardian scanner install secretlint` |
| GitGuardian (`ggshield`) | Cloud service | MIT CLI | `ai-guardian scanner install gitguardian` |

The GitGuardian engine also requires explicit consent, an API key, and network
access to its cloud service. See [Multi-Engine Support](MULTI_ENGINE_SUPPORT.md)
for the data-flow and consent details.

## Quick Start

### During Initial Setup

The easiest way to install a scanner is during initial setup:

```bash
uv tool install ai-guardian                # recommended
# or: pip install ai-guardian
ai-guardian setup --install-scanner --ide claude
```

This automatically:
1. Detects your platform (macOS, Linux, Windows)
2. Tries to install via package manager (brew, apt, yum, choco)
3. Falls back to direct download if package manager unavailable
4. Verifies the installation
5. Configures IDE hooks

### Add Scanner Later

If you already have ai-guardian set up, you can install a scanner at any time:

```bash
# Install default scanner (gitleaks)
ai-guardian scanner install gitleaks

# Install faster alternative
ai-guardian scanner install betterleaks
```

## Installation Methods

AI Guardian tries multiple installation methods in order:

### 1. Package Manager (Preferred)

Automatically detects and uses your system's package manager:

**macOS (Homebrew):**
```bash
brew install gitleaks
brew install betterleaks
brew install leaktk/tap/leaktk
```

**Linux (apt):**
```bash
sudo apt-get install gitleaks
```

**Linux (yum):**
```bash
sudo yum install gitleaks
```

**Windows (Chocolatey):**
```bash
choco install gitleaks
```

### 2. Direct Download (Fallback)

If no package manager is available, ai-guardian downloads the binary directly from GitHub releases:

1. Detects your platform and architecture (e.g., darwin_arm64, linux_x64)
2. Downloads the appropriate binary from GitHub releases
3. Extracts and installs to `/usr/local/bin` (or `~/.local/bin` if permission denied)
4. Makes the binary executable (chmod +x on Unix-like systems)

Secretlint and GitGuardian always use their upstream release assets directly so
`--use-pinned` cannot be replaced by a package manager's different version.
Their release assets are checksum-verified before installation.

### 3. From File (Air-Gapped)

For environments without internet access:

```bash
# On internet-connected machine
ai-guardian scanner download betterleaks --output betterleaks.tar.gz

# Transfer to air-gapped system and install
ai-guardian scanner install --from-file betterleaks.tar.gz
```

## Version Management

AI Guardian uses a hybrid version management strategy:

### Default: Latest from GitHub

By default, `scanner install` fetches the latest version from GitHub releases:

```bash
ai-guardian scanner install gitleaks
# Automatically installs latest version (e.g., 8.30.1)
```

### Fallback: Pinned Versions

When GitHub API is unavailable (offline, network issues), ai-guardian falls back to pinned versions in `pyproject.toml`:

```toml
[tool.ai-guardian.scanners]
gitleaks = "8.30.1"
betterleaks = "1.3.1"
leaktk = "0.3.4"
secretlint = "13.0.5"
gitguardian = "1.54.0"
```

Container builds install these exact pins. CI checks GitHub release assets for
both Linux container targets (`linux_x64` and `linux_arm64`); it checks the
`detect-secrets` package release on PyPI. Update the pins deliberately when
reviewing scanner releases.

### Override: Explicit Version

Install a specific version:

```bash
ai-guardian scanner install gitleaks --version 8.30.1
```

### Offline: Use Pinned Version

For air-gapped or offline environments:

```bash
ai-guardian scanner install gitleaks --use-pinned
```

This uses the pinned version from `pyproject.toml` without checking GitHub.

### Custom Installation Path

Specify a custom installation directory:

```bash
# Install to /opt/bin
ai-guardian scanner install gitleaks --path /opt/bin

# Install to user's bin directory
ai-guardian scanner install gitleaks --path ~/bin
```

**Default Paths:**
- **Primary**: `/usr/local/bin` (system-wide, requires write permission)
- **Fallback**: `~/.local/bin` (user-only, no sudo needed)

## Managing Scanners

### List Installed Scanners

```bash
ai-guardian scanner list
```

Output:
```
Installed scanners:

  • gitleaks 8.30.1 (default)
  • betterleaks 1.1.2

Use --verbose to show installation paths
```

### Show Scanner Details

```bash
ai-guardian scanner info gitleaks
```

Output:
```
Scanner: gitleaks
Version: 8.30.1
Path:    /usr/local/bin/gitleaks
Default: Yes
GitHub:  https://github.com/gitleaks/gitleaks
```

### Verify Installation

After installation, verify the scanner works:

```bash
gitleaks version
```

If the scanner is not in your PATH, add `~/.local/bin` to your PATH:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"
```

## Platform Support

AI Guardian supports the following platforms and architectures:

### macOS
- ARM64 (Apple Silicon)
- x64 (Intel)

### Linux
- x64
- ARM64 (aarch64)
- ARMv7
- ARMv6
- x32

### Windows
- x64
- ARM64
- x32

## Troubleshooting

### Scanner Not Found After Installation

If `gitleaks version` fails after installation:

1. Check which path was used:
   ```bash
   ai-guardian scanner info gitleaks
   ```

2. If installed to `~/.local/bin`, add it to your PATH:
   ```bash
   # Add to ~/.bashrc or ~/.zshrc
   export PATH="$HOME/.local/bin:$PATH"
   
   # Reload your shell
   source ~/.bashrc  # or ~/.zshrc
   ```

3. If installed to `/usr/local/bin`, it should already be in your PATH. Verify:
   ```bash
   echo $PATH | grep "/usr/local/bin"
   ```

### Download Failures

If direct download fails:

1. Check your internet connection
2. Try again with `--use-pinned` to use offline pinned version
3. Manually download from GitHub:
   - Gitleaks: https://github.com/gitleaks/gitleaks/releases
   - BetterLeaks: https://github.com/betterleaks/betterleaks/releases
   - LeakTK: https://github.com/leaktk/leaktk/releases

### Package Manager Timeout

If package manager installation times out:

```bash
# Try direct download instead
ai-guardian scanner install gitleaks
# Will automatically fall back to direct download
```

### Permission Denied

If you get permission errors installing to `/usr/local/bin`:

```bash
# Install to user directory instead
ai-guardian scanner install gitleaks
# Installs to ~/.local/bin (no sudo required)
```

## Configuration

After installing a scanner, update your configuration to use it:

```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["betterleaks", "gitleaks"]
  }
}
```

The first engine in the list is used by default. Additional engines provide fallback if the primary engine is not available.

## Enterprise Deployment

For enterprise environments:

1. **Centralized Installation**:
   ```bash
   # Install to shared location
   ai-guardian scanner install gitleaks
   # Then distribute ~/.local/bin/gitleaks to all machines
   ```

2. **Air-Gapped Networks**:
   ```bash
   # Download on internet-connected machine
   ai-guardian scanner download betterleaks --output betterleaks.tar.gz
   
   # Distribute tarball to air-gapped machines
   # Install from file
   ai-guardian scanner install --from-file betterleaks.tar.gz
   ```

3. **Version Control**:
   Use `--use-pinned` to ensure consistent versions across all installations:
   ```bash
   ai-guardian scanner install gitleaks --use-pinned
   ```

## CI/CD Integration

For CI/CD pipelines:

```yaml
# GitHub Actions example
steps:
  - name: Setup AI Guardian
    run: |
      uv tool install ai-guardian          # or: pip install ai-guardian
      ai-guardian setup --install-scanner --non-interactive
      
  - name: Scan repository
    run: |
      ai-guardian scan . --sarif-output results.sarif
```

The scanner is installed once and reused across all workflow runs.

## Performance Comparison

| Scanner | Speed | Memory | Pattern Updates |
|---------|-------|--------|-----------------|
| Gitleaks | Standard | ~50MB | Manual |
| BetterLeaks | 20-40% faster | ~40MB | Manual |
| LeakTK | Standard | ~30MB | Automatic |

**Recommendation**: Use BetterLeaks for best performance, or LeakTK for automatic pattern updates.

## ML Prompt Injection Setup (v1.15.0+)

AI Guardian supports ML-based prompt injection detection using a local model. One command downloads and configures the engine:

```bash
ai-guardian ml setup
```

This downloads the ML model, verifies integrity, and updates your config to enable ML-based detection. No external API calls are made — inference runs locally.

For details on model architecture, performance benchmarks, and advanced configuration, see [ML_ENGINE_SUPPORT.md](ML_ENGINE_SUPPORT.md).

## Next Steps

- See [README.md](../README.md) for general AI Guardian setup
- See [CONFIGURATION.md](CONFIGURATION.md) for scanner configuration options
- See [MCP_SERVER.md](MCP_SERVER.md) for programmatic scanner management
