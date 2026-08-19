# AI Guardian

<p align="center">
  <img src="https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/images/ai-guardian-320.png" alt="AI Guardian Logo" width="320">
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

See [Security Design](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SECURITY_DESIGN.md) for limitations and architecture.

## Quick Start

### 1. Install

```bash
uv tool install ai-guardian        # recommended
# or: pip install ai-guardian
```

### 2. Configure

```bash
ai-guardian setup --ide claude --create-config --install-scanner
```

### 3. Start

```bash
ai-guardian daemon start -b        # background daemon (faster hook processing)
ai-guardian tray start -b          # system tray (optional — manage daemons visually)
```

### 4. Open the Console

```bash
ai-guardian console --web                # web console (recommended, Python 3.10+)
ai-guardian console (or ai-guardian tui) # terminal console (all Python versions)
```

Manage settings, view violations, and scan projects. See [docs/CONSOLE.md](docs/CONSOLE.md).

Done. Open your IDE and start coding — ai-guardian protects automatically.

> **MCP servers and Skills are blocked by default.** Built-in tools (Bash, Read, Write, Edit) are allowed and scanned by hooks, but MCP servers and Skills require explicit allow rules. See [Tool Policy](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOOL_POLICY.md#default-security-posture) for why and how to allow them.

## Developer Install

For contributors cloning the repo:

```bash
git clone https://github.com/RedHatProductSecurity/ai-guardian.git
cd ai-guardian
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -e .[dev]

# Run tests
uv run --extra dev python -m pytest tests/test_<module>.py -v

# Run linters
black --target-version py39 src/ai_guardian/ tests/
ruff check src/ai_guardian/ tests/ --fix
```

See [CONTRIBUTING.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/CONTRIBUTING.md) and [AGENTS.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/AGENTS.md) for full development guidelines.

> **Warning:** The `main` branch contains unreleased development code. Always install stable releases from PyPI (`uv tool install ai-guardian` or `pip install ai-guardian`). Do not `git clone` + `pip install -e .` for production use.

## Installation Options

### One-Line Install

Creates config, installs scanner, and sets up hooks automatically:

```bash
# Linux / macOS (auto-detects uv → venv → pip)
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --ide claude

# Force a specific install method
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --uv --ide claude    # uv tool install (fastest)
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --venv --ide claude  # venv + pip
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --pip --ide claude   # bare pip

# Windows (PowerShell)
irm https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.ps1 | iex
```

### Container

A pre-built container image is published to [quay.io/redhatproductsecurity/ai-guardian](https://quay.io/redhatproductsecurity/ai-guardian) with all headless-capable IDEs (Claude Code, OpenCode, Gemini CLI, Codex CLI, Kiro CLI, OpenClaw, Crush):

```bash
# Recommended — run.sh handles auth, port mapping, and ToS consent
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/container/run.sh -o run.sh
chmod +x run.sh
ANTHROPIC_API_KEY=sk-ant-... ACCEPT_PROPRIETARY_TOS=true \
    ./run.sh --ide claude --repo $(pwd)

# Or manually with podman/docker
podman pull quay.io/redhatproductsecurity/ai-guardian:latest
podman run -it -p 63152:63152 \
    -v $(pwd):/workspace:z \
    -e AI_GUARDIAN_IDE=claude \
    -e ANTHROPIC_API_KEY=sk-ant-... \
    -e ACCEPT_PROPRIETARY_TOS=true \
    quay.io/redhatproductsecurity/ai-guardian:latest
```

`ACCEPT_PROPRIETARY_TOS=true` accepts the [Claude Code Terms of Service](https://www.anthropic.com/legal/consumer-terms) and installs Claude Code automatically at first start. Omit it to be prompted interactively instead.

```bash
# Pinned release
podman pull quay.io/redhatproductsecurity/ai-guardian:v1.15.0
podman run -it -p 63152:63152 -e AI_GUARDIAN_IDE=claude quay.io/redhatproductsecurity/ai-guardian:v1.15.0

# Or build from source
podman build -t ai-guardian container/
podman run -it -p 63152:63152 -e AI_GUARDIAN_IDE=claude ai-guardian
```

See [container/README.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/container/README.md) for IDE selection, Vertex AI auth, and multi-arch details.

### What Setup Does

The `setup` command:
- Installs a scanner engine (gitleaks)
- Creates `ai-guardian.json` config with secure defaults
- Installs IDE hooks (PreToolUse, PostToolUse, UserPromptSubmit)
- Sets up the MCP security advisor for AI-aware protection

### Daemon & Tray

The daemon provides faster hook processing. The tray discovers and manages daemons across local, Podman/Docker containers, and Kubernetes pods:

```bash
ai-guardian daemon start -b       # Start headless daemon (background: -b)
ai-guardian tray start -b         # Start system tray in background
ai-guardian tray stop             # Stop the tray
ai-guardian tray --install --autostart  # Add desktop shortcut + launch on login
```

The tray auto-discovers running daemons and shows per-daemon submenus with Statistics, Console, Pause/Resume, and Start/Stop controls. On first launch, the tray will offer to create a desktop shortcut automatically. See [Multi-Daemon Tray](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md) for full documentation.

> **Linux + Podman**: Container discovery requires the Podman socket to be active and `DOCKER_HOST` set:
> ```bash
> systemctl --user enable --now podman.socket
> export DOCKER_HOST=unix://$(podman info --format '{{.Host.RemoteSocket.Path}}')
> ai-guardian tray start -b
> ```
> macOS with Podman Desktop sets `DOCKER_HOST` automatically. See [Multi-Daemon Tray](docs/MULTI_DAEMON_TRAY.md#linux-podman) for details.

> **Breaking change in v1.8.0**: `daemon start` no longer launches the tray automatically. Run `ai-guardian tray start -b` separately, or use `ai-guardian tray --install --autostart` for a permanent desktop shortcut with login startup.

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
| Secret Scanning | Multi-layered detection of API keys, tokens, passwords | [docs/security/SECRET_SCANNING.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_SCANNING.md) |
| PII Detection | Detect personally identifiable information | [docs/security/SECRET_SCANNING.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_SCANNING.md) |
| Prompt Injection | Language-aware detection with tree-sitter AST parsing and configurable sensitivity | [docs/security/PROMPT_INJECTION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/PROMPT_INJECTION.md) |
| Image Scanning | OCR-based secret and PII detection in screenshots and images | [docs/security/IMAGE_SCANNING.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/IMAGE_SCANNING.md) |
| Unicode Attack Detection | Zero-width chars, bidi override, homoglyphs | [docs/security/UNICODE_ATTACKS.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/UNICODE_ATTACKS.md) |
| SSRF Protection | Block private IPs, cloud metadata, dangerous schemes | [docs/security/SSRF_PROTECTION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SSRF_PROTECTION.md) |
| Config File Scanning | Detect exfiltration of sensitive config files | [docs/security/CREDENTIAL_EXFILTRATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CREDENTIAL_EXFILTRATION.md) |
| Directory Blocking | `.ai-read-deny` markers + config-based rules | [docs/security/DIRECTORY_RULES.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/DIRECTORY_RULES.md) |
| Tool Permissions | Allow/deny lists for Skills, MCP, Bash, Write | [docs/TOOL_POLICY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOOL_POLICY.md) |
| Violation Logging | JSON audit trail of all blocked operations | [docs/VIOLATION_LOGGING.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/VIOLATION_LOGGING.md) |
| Sanitize Command | Clean sensitive data from files | [docs/security/SECRET_REDACTION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_REDACTION.md) |
| Interactive Console | TUI for managing configuration visually | [docs/CONSOLE.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONSOLE.md) |
| Scanner Management | Install and manage 8 scanner engines (including built-in toml-patterns) | [docs/SCANNER_INSTALLATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md) |
| Pre-commit Hook | Scan staged files for secrets before commit | [docs/PRE_COMMIT.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/PRE_COMMIT.md) |
| Inline Annotations | Suppress false positives with `ai-guardian:allow` and block annotations | [docs/ANNOTATIONS.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/ANNOTATIONS.md) |
| Self-Protection | Prevents AI from disabling its own security controls | [docs/SECURITY_DESIGN.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SECURITY_DESIGN.md) |
| MCP Security Advisor | Read-only security tools for AI agents (proactive checks) | [docs/MCP_SERVER.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md) |
| MCP Security Scanning | Audit MCP server configs and source code for supply chain risks | [docs/MCP_SERVER.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md#mcp-security-scanning) |
| Project Config Overlay | Per-repo config with immutable fields and global-only section protection | [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md#2-project-level-config-overlay-new-in-v180) |
| Multi-Daemon Tray | Discover and manage daemons across local, Podman/Docker, and Kubernetes | [docs/MULTI_DAEMON_TRAY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md) |
| Desktop Shortcut & Autostart | Install tray as desktop app with optional login startup | [docs/MULTI_DAEMON_TRAY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md#desktop-shortcuts) |
| Tray Plugins | Custom menu items with native tkinter popup forms (Textual terminal fallback), platform-aware commands | [docs/MULTI_DAEMON_TRAY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md#tray-plugins) |
| TOML Pattern Engine | Built-in Python scanner with 425 pre-compiled patterns, no binary required | [docs/TOML_PATTERNS.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOML_PATTERNS.md) |
| Multi-Agent Support | Hook adapters for 14 AI coding agents with normalized input/output | [docs/AGENT_SUPPORT.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md) |
| Container Image | UBI-based image with all headless IDEs and scanners, published to quay.io | [container/README.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/container/README.md) |
| Supply Chain Scanning | Detect malicious patterns in agent hooks, MCP configs, and plugin files | [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md#supply-chain-scanning) |
| Context Poisoning Detection | Detect persistent instruction injection in conversation context (OWASP LLM03) | [docs/security/CONTEXT_POISONING.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CONTEXT_POISONING.md) |
| Security SDK & REST API | Programmatic security checking for Python agents and multi-language support | [docs/SDK.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SDK.md) |
| Secret Liveness Validation | Verify detected secrets are still active via provider APIs | [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md#secret-liveness-validation) |
| Hook Latency Metrics | Per-hook timing with console dashboard for performance analysis | [docs/HOOKS.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/HOOKS.md#hook-latency-tracking) |
| OTEL Observability | OpenTelemetry trace export for SDK agent runs and interactive sessions | [docs/OBSERVABILITY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/OBSERVABILITY.md) |
| Canary Token Detection | Detect user-registered tripwire values in AI output to catch data exfiltration | [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) |
| Offensive Language Scanner | Detect profanity, slurs, and non-inclusive terminology in code and comments | [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) |
| Exfiltration Behavior Detection | Detect bash commands that steal credentials via curl, base64, SSH key exfil | [docs/security/CREDENTIAL_EXFILTRATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CREDENTIAL_EXFILTRATION.md) |
| Code Security Scanning | Bandit/Semgrep-based detection of insecure code patterns (eval, weak crypto, injection) | [docs/SCANNER_INSTALLATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md) |
| Dummy Agent | LLM-free hook testing via interactive REPL with YAML scenario files | [docs/AGENT_SUPPORT.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md) |
| Kubernetes Deployment | Kustomize manifests for Kind, OpenShift, and production deployments | [docs/kubernetes.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/kubernetes.md) |
| Security Instructions | Configurable agent context injection rules via TUI and web console | [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) |
| Transcript Scanning | Scan IDE conversation transcripts for secrets/PII across 7+ IDEs | [docs/AGENT_SUPPORT.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md#transcript-scanning-availability) |
| LeakTK Listen Mode | Event-driven scanning with 40x latency reduction vs polling | [docs/SCANNER_INSTALLATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md) |
| Zero-Config Onboarding | `init --scan` scans the project and generates a tuned config | [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) |
| Language-Aware FP Suppression | Tree-sitter AST parsing reduces false positives in code | [docs/security/PROMPT_INJECTION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/PROMPT_INJECTION.md) |
| ML Prompt Injection Setup | One-command `ai-guardian ml setup` installs model + dependencies | [docs/security/PROMPT_INJECTION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/PROMPT_INJECTION.md) |
| Crush IDE Support | Hook adapter for Charmbracelet Crush with MCP advisory | [docs/AGENT_SUPPORT.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md) |
| Event-Driven Tray Updates | Tray refreshes on daemon state changes instead of polling | [docs/MULTI_DAEMON_TRAY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md) |
| Scan & Configure UI | Web console workflow to scan a project and generate config | [docs/CONSOLE.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONSOLE.md) |

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

- **Example config**: [ai-guardian-example.json](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/ai-guardian-example.json)
- **JSON Schema**: [ai-guardian-config.schema.json](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/src/ai_guardian/schemas/ai-guardian-config.schema.json) (IDE autocomplete + runtime validation)
- **Ignore file schema**: [aiguardignore.schema.json](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/src/ai_guardian/schemas/aiguardignore.schema.json) (VS Code Taplo validation for `.aiguardignore.toml`)
- **Full reference**: [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md)

### Configuration Locations (Precedence Order)

1. **User config**: `~/.config/ai-guardian/ai-guardian.json` (base)
2. **Project config**: `.ai-guardian/ai-guardian.json` (merged on top of user config, see [docs](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md#2-project-level-config-overlay-new-in-v180))
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

Run `ai-guardian setup` after upgrading to get the latest hooks. The MCP security advisor server is installed by default — the AI can check security proactively before acting. Use `--no-mcp` to skip. See [docs/MCP_SERVER.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md) for details and [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) for other setup options.

## Action Modes

Each security policy supports three enforcement levels:

| Mode | Execution | User Warning | Use Case |
|------|-----------|--------------|----------|
| `block` | Blocked | Error shown | **Enforce** policy (default) |
| `warn` | Allowed | Warning shown | **Educate** during rollout |
| `log-only` | Allowed | Silent | **Monitor** silently |

See [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) for per-feature action mode configuration.

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

- [GitHub Copilot Setup](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/GITHUB_COPILOT.md)
- [Aider Setup](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AIDER.md)
- [Multi-Engine Support](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_ENGINE_SUPPORT.md)
- [Hook Ordering](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/HOOKS.md)

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

The MCP advisor lets the AI check *before* acting (advisory). Hooks enforce *during* execution (mandatory). PostToolUse hooks scan tool outputs using the same pipeline. See [docs/MCP_SERVER.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md) for the MCP server and [docs/SECURITY_DESIGN.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SECURITY_DESIGN.md) for full architecture.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_GUARDIAN_CONFIG_DIR` | Custom config directory | `~/.config/ai-guardian` |
| `AI_GUARDIAN_STATE_DIR` | State directory (logs, violations) | `~/.local/state/ai-guardian` |
| `AI_GUARDIAN_CACHE_DIR` | Cache directory (patterns) | `~/.cache/ai-guardian` |
| `AI_GUARDIAN_IDE_TYPE` | Override IDE auto-detection | Auto-detect |
| `AI_GUARDIAN_PATTERN_TOKEN` | Default pattern server auth token (all sections) | None |

Each detection feature (`secret_scanning`, `secret_redaction`, `ssrf_protection`, `config_file_scanning`) can use its own pattern server with independent auth via `token_env` or `token_file`. See [docs/PATTERN_SERVER.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/PATTERN_SERVER.md#per-section-auth-for-multiple-servers).

## Requirements

- **Python 3.9+** (3.10+ highly recommended — several features including AST-aware scanning, MCP server, and web console require Python 3.10+)
- **Windows**: Python 3.10, 3.13, and 3.14 are tested; other versions may work but are not CI-verified
- **Scanner engine**: gitleaks, betterleaks, leaktk, trufflehog, detect-secrets, secretlint, or gitguardian
- **GNOME Linux**: AppIndicator extension for system tray icon ([setup steps](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONSOLE.md#getting-started))

See [docs/SCANNER_INSTALLATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md) for installation instructions.

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

## Contributing

We welcome contributions! See [Developer Install](#developer-install) for setup and [CONTRIBUTING.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/CONTRIBUTING.md) for complete guidelines.

- **Bug reports & feature requests** -- use [GitHub Discussions](https://github.com/RedHatProductSecurity/ai-guardian/discussions)
- **Code contributions** -- fork + PR (not affected by interaction limits)

## Documentation

Full documentation is available in the [docs/](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/) folder:

- [Configuration Guide](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md)
- [Security Documentation](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/)
- [Console Guide](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONSOLE.md)
- [Tool Policy](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOOL_POLICY.md)
- [Scanner Installation](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md)
- [Security Design](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SECURITY_DESIGN.md)
- [All Documentation](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/README.md)

## FAQ

**Q: Why no prompt injection examples in the docs?**
Publishing attack patterns makes them easier to misuse and would cause ai-guardian to block its own documentation. Use `test:` prefixed strings for testing. See OWASP LLM Top 10 for research.

**Q: What's `permissions` vs `permissions_directories` vs `directory_rules`?**
`permissions` = which **tools** can run. `permissions_directories` = auto-discover tool permissions from repos. `directory_rules` = which **paths** can be accessed. See [docs/TOOL_POLICY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOOL_POLICY.md) and [docs/security/DIRECTORY_RULES.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/DIRECTORY_RULES.md).

**Q: How are multiple rules evaluated?**
Both `permissions.rules` and `directory_rules` use **last-match-wins**: rules are checked in array order and the last matching rule determines the outcome. Place broad deny rules first, then specific allow rules after. Common mistake: putting an allow rule before a deny-all — the deny-all wins because it comes last. See [docs/TOOL_POLICY.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOOL_POLICY.md#rule-evaluation-order-last-match-wins).

## License

Apache 2.0 - see [LICENSE](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/LICENSE) file for details.

## Acknowledgments

- [Gitleaks](https://github.com/gitleaks/gitleaks) - Secret detection engine
- [Claude Code](https://claude.ai/code) - AI-powered IDE
- [Cursor](https://cursor.sh) - AI code editor
- [LeakTK](https://github.com/leaktk/patterns) - Community secret detection patterns
- [Hermes Security Patterns](https://github.com/fullsend-ai/experiments/tree/main/hermes-security-patterns) - Security research

