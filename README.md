# AI Guardian

<p align="center">
  <img src="https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/images/ai-guardian-320.png" alt="AI Guardian Logo" width="320">
</p>

> AI IDE security hook: controls MCP/skill permissions, blocks directories, detects prompt injection, scans secrets

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://badge.fury.io/py/ai-guardian.svg)](https://pypi.org/project/ai-guardian/)

AI Guardian provides comprehensive protection for AI IDE interactions through multiple security layers.

## Security Disclaimer

**AI Guardian is not a silver bullet** and cannot guarantee detection of all security threats.

- **Prompt injection detection** may miss novel or obfuscated attacks
- **Secret scanning** depends on scanner patterns and may miss custom secret formats
- **Attackers evolve continuously** — new bypass techniques emerge constantly
- **Fail-open by design** — prioritizes availability over security (errors allow operations)

**Use AI Guardian as ONE layer in a defense-in-depth security strategy, not as your only protection.**

Combine with:
- Code review processes
- CI/CD security scanning
- Network security (firewalls, egress rules)
- Secret management (Vault, AWS Secrets Manager)

See [Security Design](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SECURITY_DESIGN.md) for limitations and architecture.

## Quick Start

**One-line install** (creates config, installs scanner, sets up hooks):

```bash
# Linux / macOS (auto-detects uv → venv → pip)
curl -fsSL https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/install.sh | bash -s -- --ide claude

# Force a specific install method
curl -fsSL https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/install.sh | bash -s -- --uv --ide claude    # uv tool install (fastest)
curl -fsSL https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/install.sh | bash -s -- --venv --ide claude  # venv + pip
curl -fsSL https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/install.sh | bash -s -- --pip --ide claude   # bare pip

# Windows (PowerShell)
irm https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/install.ps1 | iex
```

Or install manually:

```bash
uv tool install ai-guardian                # recommended
pip install ai-guardian                    # alternative
ai-guardian setup --ide claude --create-config --install-scanner
```

Or use the container image (no Python setup required):

```bash
# Recommended — run.sh handles auth, port mapping, and ToS consent
curl -fsSL https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/container/run.sh -o run.sh
chmod +x run.sh
ANTHROPIC_API_KEY=sk-ant-... ACCEPT_PROPRIETARY_TOS=true \
    ./run.sh --ide claude --repo $(pwd)

# Or manually with podman/docker
podman pull quay.io/itdove/ai-guardian:latest
podman run -it -p 63152:63152 \
    -v $(pwd):/workspace:z \
    -e AI_GUARDIAN_IDE=claude \
    -e ANTHROPIC_API_KEY=sk-ant-... \
    -e ACCEPT_PROPRIETARY_TOS=true \
    quay.io/itdove/ai-guardian:latest
```

`ACCEPT_PROPRIETARY_TOS=true` accepts the [Claude Code Terms of Service](https://www.anthropic.com/legal/consumer-terms) and installs Claude Code automatically at first start. Omit it to be prompted interactively instead.

See [container/README.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/container/README.md) for IDE selection, Vertex AI auth, and multi-arch details.

The pip/uv install:
- Installs a scanner engine (gitleaks)
- Creates `ai-guardian.json` config with secure defaults
- Installs IDE hooks (PreToolUse, PostToolUse, UserPromptSubmit)
- Sets up the MCP security advisor for AI-aware protection

> **MCP servers and Skills are blocked by default.** Built-in tools (Bash, Read, Write, Edit) are allowed and scanned by hooks, but MCP servers and Skills require explicit allow rules. See [Tool Policy](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/TOOL_POLICY.md#default-security-posture) for why and how to allow them.

### Daemon & Tray

The daemon provides faster hook processing. The tray is a separate process that discovers and manages daemons across local, Podman/Docker containers, and Kubernetes pods:

```bash
ai-guardian daemon start          # Start headless daemon (background: -b)
ai-guardian tray start -b         # Start system tray in background
ai-guardian tray stop             # Stop the tray
ai-guardian tray --install --autostart  # Add desktop shortcut + launch on login
```

The tray auto-discovers running daemons and shows per-daemon submenus with Statistics, Console, Pause/Resume, and Start/Stop controls. On first launch, the tray will offer to create a desktop shortcut automatically. See [Multi-Daemon Tray](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MULTI_DAEMON_TRAY.md) for full documentation.

> **Linux + Podman**: Container discovery requires the Podman socket to be active and `DOCKER_HOST` set:
> ```bash
> systemctl --user enable --now podman.socket
> export DOCKER_HOST=unix://$(podman info --format '{{.Host.RemoteSocket.Path}}')
> ai-guardian tray start -b
> ```
> macOS with Podman Desktop sets `DOCKER_HOST` automatically. See [Multi-Daemon Tray](docs/MULTI_DAEMON_TRAY.md#linux-podman) for details.

> **Breaking change in v1.8.0**: `daemon start` no longer launches the tray automatically. Run `ai-guardian tray start -b` separately, or use `ai-guardian tray --install --autostart` for a permanent desktop shortcut with login startup.

### Container

A pre-built container image is published to [quay.io/itdove/ai-guardian](https://quay.io/itdove/ai-guardian) with all headless-capable IDEs (Claude Code, OpenCode, Gemini CLI, Codex CLI, Kiro CLI, OpenClaw, Crush):

```bash
# Latest (tracks main branch)
podman pull quay.io/itdove/ai-guardian:latest
podman run -it -p 63152:63152 -e AI_GUARDIAN_IDE=claude quay.io/itdove/ai-guardian:latest

# Pinned release
podman pull quay.io/itdove/ai-guardian:v1.15.1
podman run -it -p 63152:63152 -e AI_GUARDIAN_IDE=claude quay.io/itdove/ai-guardian:v1.15.1

# Or build from source
podman build -t ai-guardian container/
podman run -it -p 63152:63152 -e AI_GUARDIAN_IDE=claude ai-guardian
```

See [container/README.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/container/README.md) for IDE selection, auth, and multi-arch builds.

### Security Profiles

Choose a profile that matches your environment:

```bash
ai-guardian setup --ide claude --create-config --profile @minimal --install-scanner
ai-guardian setup --ide claude --create-config --profile @strict --install-scanner
```

| Profile | Secrets | PII | Prompt Injection | SSRF |
|---------|---------|-----|------------------|------|
| @minimal | block | warn | low | warn |
| @standard (default) | block | block | medium | block |
| @strict | block | block | high | block |
| @moderator | ask | ask | medium | ask |

## Features

| Feature | Description | Docs |
|---------|-------------|------|
| Secret Scanning | Multi-layered detection of API keys, tokens, passwords | [docs/security/SECRET_SCANNING.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/SECRET_SCANNING.md) |
| PII Detection | Detect personally identifiable information | [docs/security/SECRET_SCANNING.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/SECRET_SCANNING.md) |
| Prompt Injection | Language-aware detection with tree-sitter AST parsing and configurable sensitivity | [docs/security/PROMPT_INJECTION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/PROMPT_INJECTION.md) |
| Image Scanning | OCR-based secret and PII detection in screenshots and images | [docs/security/IMAGE_SCANNING.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/IMAGE_SCANNING.md) |
| Unicode Attack Detection | Zero-width chars, bidi override, homoglyphs | [docs/security/UNICODE_ATTACKS.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/UNICODE_ATTACKS.md) |
| SSRF Protection | Block private IPs, cloud metadata, dangerous schemes | [docs/security/SSRF_PROTECTION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/SSRF_PROTECTION.md) |
| Config File Scanning | Detect exfiltration of sensitive config files | [docs/security/CREDENTIAL_EXFILTRATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/CREDENTIAL_EXFILTRATION.md) |
| Directory Blocking | `.ai-read-deny` markers + config-based rules | [docs/security/DIRECTORY_RULES.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/DIRECTORY_RULES.md) |
| Tool Permissions | Allow/deny lists for Skills, MCP, Bash, Write | [docs/TOOL_POLICY.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/TOOL_POLICY.md) |
| Violation Logging | JSON audit trail of all blocked operations | [docs/VIOLATION_LOGGING.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/VIOLATION_LOGGING.md) |
| Sanitize Command | Clean sensitive data from files | [docs/security/SECRET_REDACTION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/SECRET_REDACTION.md) |
| Interactive Console | TUI for managing configuration visually | [docs/CONSOLE.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONSOLE.md) |
| Scanner Management | Install and manage 8 scanner engines (including built-in toml-patterns) | [docs/SCANNER_INSTALLATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SCANNER_INSTALLATION.md) |
| Pre-commit Hook | Scan staged files for secrets before commit | [docs/PRE_COMMIT.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/PRE_COMMIT.md) |
| Inline Annotations | Suppress false positives with `ai-guardian:allow` and block annotations | [docs/ANNOTATIONS.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/ANNOTATIONS.md) |
| Self-Protection | Prevents AI from disabling its own security controls | [docs/SECURITY_DESIGN.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SECURITY_DESIGN.md) |
| MCP Security Advisor | Read-only security tools for AI agents (proactive checks) | [docs/MCP_SERVER.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MCP_SERVER.md) |
| MCP Security Scanning | Audit MCP server configs and source code for supply chain risks | [docs/MCP_SERVER.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MCP_SERVER.md#mcp-security-scanning) |
| Project Config Overlay | Per-repo config with immutable fields and global-only section protection | [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md#2-project-level-config-overlay-new-in-v180) |
| Multi-Daemon Tray | Discover and manage daemons across local, Podman/Docker, and Kubernetes | [docs/MULTI_DAEMON_TRAY.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MULTI_DAEMON_TRAY.md) |
| Desktop Shortcut & Autostart | Install tray as desktop app with optional login startup | [docs/MULTI_DAEMON_TRAY.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MULTI_DAEMON_TRAY.md#desktop-shortcuts) |
| Tray Plugins | Custom menu items with native tkinter popup forms (Textual terminal fallback), platform-aware commands | [docs/MULTI_DAEMON_TRAY.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MULTI_DAEMON_TRAY.md#tray-plugins) |
| TOML Pattern Engine | Built-in Python scanner with 425 pre-compiled patterns, no binary required | [docs/TOML_PATTERNS.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/TOML_PATTERNS.md) |
| Multi-Agent Support | Hook adapters for 14 AI coding agents with normalized input/output | [docs/AGENT_SUPPORT.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/AGENT_SUPPORT.md) |
| Container Image | UBI-based image with all headless IDEs and scanners, published to quay.io | [container/README.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/container/README.md) |
| Supply Chain Scanning | Detect malicious patterns in agent hooks, MCP configs, and plugin files | [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md#supply-chain-scanning) |
| Context Poisoning Detection | Detect persistent instruction injection in conversation context (OWASP LLM03) | [docs/security/CONTEXT_POISONING.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/CONTEXT_POISONING.md) |
| Security SDK & REST API | Programmatic security checking for Python agents and multi-language support | [docs/SDK.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SDK.md) |
| Secret Liveness Validation | Verify detected secrets are still active via provider APIs | [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md#secret-liveness-validation) |
| Hook Latency Metrics | Per-hook timing with console dashboard for performance analysis | [docs/HOOKS.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/HOOKS.md#hook-latency-tracking) |
| Canary Token Detection | Detect user-registered tripwire values in AI output to catch data exfiltration | [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md) |
| Offensive Language Scanner | Detect profanity, slurs, and non-inclusive terminology in code and comments | [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md) |
| Exfiltration Behavior Detection | Detect bash commands that steal credentials via curl, base64, SSH key exfil | [docs/security/CREDENTIAL_EXFILTRATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/CREDENTIAL_EXFILTRATION.md) |
| Code Security Scanning | Bandit/Semgrep-based detection of insecure code patterns (eval, weak crypto, injection) | [docs/SCANNER_INSTALLATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SCANNER_INSTALLATION.md) |
| Dummy Agent | LLM-free hook testing via interactive REPL with YAML scenario files | [docs/AGENT_SUPPORT.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/AGENT_SUPPORT.md) |
| Kubernetes Deployment | Kustomize manifests for Kind, OpenShift, and production deployments | [docs/kubernetes.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/kubernetes.md) |
| Security Instructions | Configurable agent context injection rules via TUI and web console | [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md) |
| Transcript Scanning | Scan IDE conversation transcripts for secrets/PII across 7+ IDEs | [docs/AGENT_SUPPORT.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/AGENT_SUPPORT.md#transcript-scanning-availability) |
| LeakTK Listen Mode | Event-driven scanning with 40x latency reduction vs polling | [docs/SCANNER_INSTALLATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SCANNER_INSTALLATION.md) |
| Zero-Config Onboarding | `init --scan` scans the project and generates a tuned config | [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md) |
| Language-Aware FP Suppression | Tree-sitter AST parsing reduces false positives in code | [docs/security/PROMPT_INJECTION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/PROMPT_INJECTION.md) |
| ML Prompt Injection Setup | One-command `ai-guardian ml setup` installs model + dependencies | [docs/security/PROMPT_INJECTION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/PROMPT_INJECTION.md) |
| Crush IDE Support | Hook adapter for Charmbracelet Crush with MCP advisory | [docs/AGENT_SUPPORT.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/AGENT_SUPPORT.md) |
| Event-Driven Tray Updates | Tray refreshes on daemon state changes instead of polling | [docs/MULTI_DAEMON_TRAY.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MULTI_DAEMON_TRAY.md) |
| Scan & Configure UI | Web console workflow to scan a project and generate config | [docs/CONSOLE.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONSOLE.md) |

## Default Behavior (No Configuration File)

ai-guardian provides protection **immediately** with zero configuration:

| Feature | Default | Notes |
|---------|---------|-------|
| Secret scanning | Enabled | Built-in `toml-patterns` scanner works without external tools |
| Prompt injection detection | Enabled | Heuristic detector |
| Config file scanning | Enabled | Detects exfiltration patterns |
| SSRF protection | Enabled | Blocks private IPs, metadata endpoints |
| Immutable file protection | Enabled | Cannot be disabled |
| `.ai-read-deny` markers | Enabled | Always respected |
| Violation logging | Enabled | Logs to `~/.local/state/ai-guardian/violations.jsonl` |
| Built-in tool permissions | Allowed | Bash, Read, Write, Edit — protected by hooks |
| MCP server permissions | **Blocked** | Require explicit allow rules (third-party code) |
| Skill permissions | **Blocked** | Require explicit allow rules (can override AI behavior) |
| Directory rules | Allow all | Configure `directory_rules` to restrict |

## Configuration

Config file: `~/.config/ai-guardian/ai-guardian.json` (or `$XDG_CONFIG_HOME/ai-guardian/`)

```bash
ai-guardian setup --create-config                          # Secure defaults (Skills/MCP blocked)
ai-guardian setup --create-config --permissive              # Permissive (all tools allowed)
ai-guardian setup --create-config --profile @minimal        # Personal projects, low friction
ai-guardian setup --create-config --profile @strict         # Enterprise SOC2/compliance
ai-guardian setup --create-config --profile @moderator      # Human-in-the-loop, ask on every finding
ai-guardian setup --list-profiles                           # List available profiles
```

- **Example config**: [ai-guardian-example.json](https://github.com/itdove/ai-guardian/blob/v1.15.1/ai-guardian-example.json)
- **JSON Schema**: [ai-guardian-config.schema.json](https://github.com/itdove/ai-guardian/blob/v1.15.1/src/ai_guardian/schemas/ai-guardian-config.schema.json) (IDE autocomplete + runtime validation)
- **Ignore file schema**: [aiguardignore.schema.json](https://github.com/itdove/ai-guardian/blob/v1.15.1/src/ai_guardian/schemas/aiguardignore.schema.json) (VS Code Taplo validation for `.aiguardignore.toml`)
- **Full reference**: [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md)

### Configuration Locations (Precedence Order)

1. **User config**: `~/.config/ai-guardian/ai-guardian.json` (base)
2. **Project config**: `.ai-guardian/ai-guardian.json` (merged on top of user config, see [docs](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md#2-project-level-config-overlay-new-in-v180))
3. **Remote configs** (highest, permissions only): Fetched from URLs in `remote_configs`
4. **Defaults**: Built-in defaults when no config exists

## Setup Command

```bash
ai-guardian setup                    # Auto-detect IDE
ai-guardian setup --ide claude       # Claude Code
ai-guardian setup --ide cursor       # Cursor IDE
ai-guardian setup --ide copilot      # GitHub Copilot
ai-guardian setup --dry-run          # Preview changes
ai-guardian setup --ide claude       # MCP security advisor installed by default
ai-guardian setup --remote-config-url https://example.com/policy.json
```

Run `ai-guardian setup` after upgrading to get the latest hooks. The MCP security advisor server is installed by default — the AI can check security proactively before acting. Use `--no-mcp` to skip. See [docs/MCP_SERVER.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MCP_SERVER.md) for details and [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md) for other setup options.

## Action Modes

Each security policy supports three enforcement levels:

| Mode | Execution | User Warning | Use Case |
|------|-----------|--------------|----------|
| `block` | Blocked | Error shown | **Enforce** policy (default) |
| `warn` | Allowed | Warning shown | **Educate** during rollout |
| `log-only` | Allowed | Silent | **Monitor** silently |

See [docs/CONFIGURATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md) for per-feature action mode configuration.

## Integration

| Agent | Setup Command | Hooks | MCP | Status |
|-------|--------------|-------|-----|--------|
| Claude Code | `--ide claude` | Full | Full | Complete |
| Cursor | `--ide cursor` | Full | N/A | Complete |
| GitHub Copilot | `--ide copilot` | Full | N/A | Complete |
| OpenAI Codex | `--ide codex` | Full | N/A | Complete |
| Windsurf | `--ide windsurf` | Full | N/A | Complete |
| Gemini CLI | `--ide gemini` | Full | N/A | Complete |
| Cline / ZooCode | `--ide cline` | Full | N/A | Complete |
| Kiro (AWS) | `--ide kiro` | Full | N/A | Complete |
| Augment Code | `--ide augment` | Full | N/A | Complete |
| AiderDesk | `--ide aiderdesk` | Extension | N/A | Complete |
| OpenClaw | `--ide openclaw` | Plugin | N/A | Complete |
| OpenCode | `--ide opencode` | Plugin | N/A | Complete |
| Crush (Charmbracelet) | `--ide crush` | Partial | Full | Complete |
| Junie (JetBrains) | `--ide junie` | N/A | Full | MCP-only |

- [GitHub Copilot Setup](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/GITHUB_COPILOT.md)
- [Aider Setup](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/AIDER.md)
- [Multi-Engine Support](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MULTI_ENGINE_SUPPORT.md)
- [Hook Ordering](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/HOOKS.md)

## How It Works

```
User prompt / Tool use
       |
  [MCP Advisor] -----> AI checks proactively (optional)
       |
  [AI Guardian Hook] -- Enforcement (mandatory)
       |
  MCP/Skill check --> Not allowed? --> BLOCK
       |
  Directory check --> .ai-read-deny? --> BLOCK
       |
  Prompt injection --> Detected? -----> BLOCK
       |
  Secret scan ------> Found? --------> BLOCK
       |
  ALLOW --> Send to AI / Execute tool
```

The MCP advisor lets the AI check *before* acting (advisory). Hooks enforce *during* execution (mandatory). PostToolUse hooks scan tool outputs using the same pipeline. See [docs/MCP_SERVER.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/MCP_SERVER.md) for the MCP server and [docs/SECURITY_DESIGN.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SECURITY_DESIGN.md) for full architecture.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_GUARDIAN_CONFIG_DIR` | Custom config directory | `~/.config/ai-guardian` |
| `AI_GUARDIAN_STATE_DIR` | State directory (logs, violations) | `~/.local/state/ai-guardian` |
| `AI_GUARDIAN_CACHE_DIR` | Cache directory (patterns) | `~/.cache/ai-guardian` |
| `AI_GUARDIAN_IDE_TYPE` | Override IDE auto-detection | Auto-detect |
| `AI_GUARDIAN_PATTERN_TOKEN` | Default pattern server auth token (all sections) | None |

Each detection feature (`secret_scanning`, `secret_redaction`, `ssrf_protection`, `config_file_scanning`) can use its own pattern server with independent auth via `token_env` or `token_file`. See [docs/PATTERN_SERVER.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/PATTERN_SERVER.md#per-section-auth-for-multiple-servers).

## Requirements

- **Python 3.9+** (3.10+ highly recommended — several features including AST-aware scanning, MCP server, and web console require Python 3.10+)
- **Windows**: Python 3.10, 3.13, and 3.14 are tested; other versions may work but are not CI-verified
- **Scanner engine**: gitleaks, betterleaks, leaktk, trufflehog, detect-secrets, secretlint, or gitguardian
- **GNOME Linux**: AppIndicator extension for system tray icon ([setup steps](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONSOLE.md#getting-started))

See [docs/SCANNER_INSTALLATION.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SCANNER_INSTALLATION.md) for installation instructions.

## Optional Dependencies

ai-guardian works out of the box with built-in Python-native scanners, NiceGUI/Textual fallback dialogs, and heuristic prompt injection detection. These optional packages enable extra functionality:

| Package | What it enables | Install |
|---------|-----------------|---------|
| **tkinter** | Native popup dialogs for ask mode (strongly recommended) | `install.sh --tkinter`, or see below |
| **PyGObject (gi)** | System tray on Linux | `install.sh --gobject`, or: `dnf install python3-gobject` / `apt install python3-gi` |
| **gitleaks** | Additional secret scanner engine | `ai-guardian scanner install gitleaks` |
| **betterleaks** | Additional secret scanner engine | `ai-guardian scanner install betterleaks` |
| **trufflehog** | Additional secret scanner engine (AGPL, subprocess) | `ai-guardian scanner install trufflehog` |
| **ML model** | ML-based prompt injection detection | `ai-guardian ml setup` (or `ml download` for model only) |

### tkinter Install by Platform

| Platform | Command |
|----------|---------|
| Fedora/RHEL | `sudo dnf install python3-tkinter` |
| Debian/Ubuntu | `sudo apt install python3-tk` |
| macOS (system Python) | Included |
| macOS (pyenv/Homebrew) | `brew install tcl-tk`, then rebuild Python |
| uv | Not available — NiceGUI browser form used automatically |

## Installation

**Linux / macOS:**

```bash
# Recommended: uv tool install (isolated, binary in PATH, no activation needed)
uv tool install ai-guardian

# Alternative: pip install
pip install ai-guardian

# Alternative: venv + pip
python -m venv ~/.ai-guardian-venv
~/.ai-guardian-venv/bin/pip install ai-guardian

# Optional: tkinter for native tray plugin popup dialogs (see docs/MULTI_DAEMON_TRAY.md)
# RHEL/Fedora: dnf install python3-tkinter | Debian: apt install python3-tk
# macOS: included with system Python; pyenv users need tcl-tk (brew install tcl-tk)
# uv: tkinter unavailable — NiceGUI browser form used automatically as fallback
```

**Windows (PowerShell):**

```powershell
# Recommended: uv tool install
uv tool install ai-guardian

# Alternative: pip install
pip install ai-guardian

# Alternative: venv + pip
python -m venv $env:USERPROFILE\.ai-guardian-venv
& "$env:USERPROFILE\.ai-guardian-venv\Scripts\pip" install ai-guardian

# Or use the one-line installer:
irm https://raw.githubusercontent.com/itdove/ai-guardian/v1.15.2/install.ps1 | iex
```

> **Warning:** The `main` branch contains unreleased development code. Always install stable releases from PyPI (`uv tool install ai-guardian` or `pip install ai-guardian`). Do not `git clone` + `pip install -e .` for production use — development builds may contain breaking changes, incomplete features, or experimental code that has not been release-tested.

For development and contributing:

```bash
git clone https://github.com/itdove/ai-guardian.git
cd ai-guardian && uv pip install -e .      # recommended
# or: pip install -e .
```

> **Dev builds:** CI builds a wheel on every PR and merge. Download from the [Actions tab](https://github.com/itdove/ai-guardian/actions/workflows/build-wheel.yml) for testing only; use PyPI for stable releases.

## Testing

Using [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv run --extra dev python -m pytest             # Run all tests
uv run --extra dev python -m pytest --cov=ai_guardian --cov-report=term  # With coverage
```

Or using pip:

```bash
pip install ai-guardian[dev]                     # Install test dependencies
pytest                                          # Run all tests
pytest --cov=ai_guardian --cov-report=term      # With coverage
```

See [AGENTS.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/AGENTS.md) for testing guidelines and CI/CD details.

## Contributing

We welcome contributions! This repo uses interaction limits, so:

- **Bug reports & feature requests** -- use [GitHub Discussions](https://github.com/itdove/ai-guardian/discussions)
- **Code contributions** -- fork + PR (not affected by interaction limits)

```bash
gh repo fork itdove/ai-guardian --clone
cd ai-guardian
git checkout -b feature-name
# Make changes, commit, push
gh pr create --web
```

See [CONTRIBUTING.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/CONTRIBUTING.md) for complete guidelines.

## Documentation

Full documentation is available in the [docs/](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/) folder:

- [Configuration Guide](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONFIGURATION.md)
- [Security Documentation](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/)
- [Console Guide](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/CONSOLE.md)
- [Tool Policy](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/TOOL_POLICY.md)
- [Scanner Installation](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SCANNER_INSTALLATION.md)
- [Security Design](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/SECURITY_DESIGN.md)
- [All Documentation](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/README.md)

## FAQ

**Q: Why no prompt injection examples in the docs?**
Publishing attack patterns makes them easier to misuse and would cause ai-guardian to block its own documentation. Use `test:` prefixed strings for testing. See OWASP LLM Top 10 for research.

**Q: What's `permissions` vs `permissions_directories` vs `directory_rules`?**
`permissions` = which **tools** can run. `permissions_directories` = auto-discover tool permissions from repos. `directory_rules` = which **paths** can be accessed. See [docs/TOOL_POLICY.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/TOOL_POLICY.md) and [docs/security/DIRECTORY_RULES.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/security/DIRECTORY_RULES.md).

**Q: How are multiple rules evaluated?**
Both `permissions.rules` and `directory_rules` use **last-match-wins**: rules are checked in array order and the last matching rule determines the outcome. Place broad deny rules first, then specific allow rules after. Common mistake: putting an allow rule before a deny-all — the deny-all wins because it comes last. See [docs/TOOL_POLICY.md](https://github.com/itdove/ai-guardian/blob/v1.15.1/docs/TOOL_POLICY.md#rule-evaluation-order-last-match-wins).

## License

Apache 2.0 - see [LICENSE](https://github.com/itdove/ai-guardian/blob/v1.15.1/LICENSE) file for details.

## Acknowledgments

- [Gitleaks](https://github.com/gitleaks/gitleaks) - Secret detection engine
- [Claude Code](https://claude.ai/code) - AI-powered IDE
- [Cursor](https://cursor.sh) - AI code editor
- [LeakTK](https://github.com/leaktk/patterns) - Community secret detection patterns
- [Hermes Security Patterns](https://github.com/fullsend-ai/experiments/tree/main/hermes-security-patterns) - Security research

