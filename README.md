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

Creates config, installs a scanner, and automatically detects supported IDE
configuration directories so their hooks can be installed. Use `--ide` to
target one IDE explicitly, or `--no-setup` to skip hook setup:

From the tray, open **IDE/CLI Setup...**. Use **Check hooks/MCP installation...** to
immediately verify locally installed integrations; if hooks or a required MCP
registration are missing or unhealthy, the tray offers setup choices and reports the final verification
status. The **Manual setup (specific IDE)** entries are for unusual,
incompletely detected, or targeted repair cases, while **Create Config...** is
for first-time or manual configuration. These explicit actions remain
available even when no daemon is running or only remote daemons are connected;
per-IDE setup also installs the MCP security advisor by default when that IDE
supports it.
The tray also checks automatically when it starts and then every 10 seconds
while running. The initial check also sends an **AI Guardian** health-result
notification; later healthy polling checks remain silent. Automatic checks
only offer setup on local-daemon trays.
When multiple integrations need setup, the tray shows an individual **Install
now** or **Never install** choice for each one. These choices are kept per
integration, so a newly detected IDE can still be offered later.
When no global `ai-guardian.json` exists, the automatic setup prompt also shows
a **Security profile** selector. `@standard` is selected and recommended by
default; `@minimal`, `@strict`, and `@moderator` include concise guidance, and
**Skip configuration for now** installs only the selected IDE hooks. If a
profile is selected, the tray creates the global config only after confirmation
and before installing hooks. Existing global or project-local configuration is
never overwritten by this flow. Configuration creation failures leave hook
setup untouched and the prompt is temporarily deferred.
The web console's **Configuration → Proactive Prompt State** page provides a
read-only view of these local prompt decisions. They are stored separately in
the XDG state file `proactive_prompts.json`, rather than in `ai-guardian.json`.
Entries named `ide_setup_<combination>` are prompt history; the synchronized
`ide_setup_status` entry is the current installed-IDE and current/last-verified
hook-health snapshot.
Within prompt history, `dismissed` means the automatic prompt was declined for
that exact combination, while `snoozed` means it is postponed until its stored
time. Neither value says whether the hooks are currently healthy: the tray
refreshes the snapshot from live hook verification before applying either
decision. Dismissed and snoozed integrations continue to be rechecked, and a
changed unhealthy result can make their prompt eligible again. **Never
install** is the only automatic choice that stops rechecking; the tray keeps
its last verified status visible and suppresses automatic setup until the
choice is reset, while manual setup remains available.
Use the per-IDE **Reset** button on that page, or
`ai-guardian ide-setup reset --ide <ide>`, to clear one IDE's saved prompt
decisions and Never install choice.

```bash
# Auto-detect installed IDEs (Linux / macOS)
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash

# Linux / macOS (auto-detects uv → venv → pip)
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --ide claude

# Force a specific install method
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --uv --ide claude    # uv tool install (fastest)
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --venv --ide claude  # venv + pip
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --pip --ide claude   # bare pip

# Windows (PowerShell)
irm https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.ps1 | iex

# Install without changing IDE hooks
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.sh | bash -s -- --no-setup
```

### Container

A pre-built container image is published to [quay.io/redhatproductsecurity/ai-guardian](https://quay.io/redhatproductsecurity/ai-guardian) with ai-guardian and the supported agent integrations. Redistributable headless CLIs are bundled; proprietary or GUI-only agents are configured at startup without being embedded:

For provider-backed sessions, OpenShell is the preferred runtime when
available: provider credentials remain in the gateway and OpenShell supplies
deny-by-default network/filesystem policy and per-sandbox isolation. The plain
Docker/Podman container is the simpler fallback; credentials passed to it are
available inside the container and may be readable by the selected agent.

```bash
# Recommended — run.sh handles auth, port mapping, config sharing, and ToS consent
curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/container/run.sh -o run.sh
chmod +x run.sh
OPENAI_API_KEY=... \
    ./run.sh --agent codex --repo $(pwd)

# Preferred OpenShell sandbox (published image; local build is also supported)
# OpenShell defaults to Claude; select Codex or Pi explicitly when needed.
# Experimental: OpenShell integration is still evolving. Claude, Codex, Pi, and
# OpenCode using Claude have been tested; verify current compatibility before
# important work.
openshell settings set --global --key providers_v2_enabled --value true
podman pull quay.io/redhatproductsecurity/ai-guardian-openshell:latest
ai-guardian sandbox create --runtime openshell \
    --image quay.io/redhatproductsecurity/ai-guardian-openshell:latest \
    --cli codex --repo $(pwd)

# Or use Pi through the Anthropic-compatible OpenShell inference route.
ai-guardian sandbox create --runtime openshell \
    --image quay.io/redhatproductsecurity/ai-guardian-openshell:latest \
    --cli pi --repo $(pwd)

# Or build and select a local OpenShell image
podman build -f container/Dockerfile.openshell \
    -t localhost/ai-guardian-openshell:latest container/
ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:latest \
    --cli codex --repo $(pwd)
# A source-wheel build is documented in container/README.md; it includes the
# current development setup behavior instead of the stable PyPI fallback.

# Launch Codex directly instead of opening the shell
ai-guardian sandbox create --runtime openshell --cli codex --repo $(pwd) -- codex

# Or manually with podman/docker
podman pull quay.io/redhatproductsecurity/ai-guardian:latest
podman run -it -p 63152:63152 \
    -v $(pwd):/workspace:z \
    -e AI_GUARDIAN_AGENT=codex \
    -e OPENAI_API_KEY=<your-openai-key> \
    quay.io/redhatproductsecurity/ai-guardian:latest
```

For Codex authentication in a Docker/Podman sandbox, the host
`~/.codex/auth.json` is not mounted automatically. Authenticate inside the
sandbox or follow the [container Codex authentication
guide](docs/Sandbox.md#codex-authentication-in-container-sandboxes) for
headless OAuth, API-key, and explicit credential-copy options.

For a named sandbox that can be managed across sessions, use the CLI
subcommand. It supports both Docker/Podman containers and OpenShell:

```bash
ai-guardian sandbox create --runtime container --name guardian-codex --repo .
ai-guardian sandbox list
ai-guardian sandbox stop guardian-codex
ai-guardian sandbox start guardian-codex
ai-guardian sandbox connect guardian-codex
ai-guardian sandbox exec guardian-codex -- ai-guardian daemon status
ai-guardian sandbox logs guardian-codex --follow
ai-guardian sandbox config save guardian-codex
ai-guardian sandbox delete guardian-codex
```

New sandbox creation defaults to OpenShell; use `--runtime container` explicitly
when a plain Docker/Podman sandbox is required. Named lifecycle commands
automatically detect the runtime from AI Guardian labels and OpenShell
metadata when `--runtime` is omitted. An unqualified `list` includes both
runtimes. OpenShell operations use the installed `openshell` CLI and its active
gateway; set `OPENSHELL_CLI` when a different executable is required. The
sandbox command is also the supported entry point for interactive,
fully provisioned OpenShell sessions, including policy composition and
gateway-provider setup.

OpenShell `create` opens an independent interactive sandbox shell after setup,
matching the native OpenShell experience while leaving the sandbox available
after the shell exits; container `create` remains detached.

The OpenShell `status`, `stop`, `exec`, and `logs` forms are thin aliases of
the corresponding native commands. `connect` uses an independent
`openshell sandbox exec --name ... --tty` shell so exiting it does not
terminate the sandbox's main process. `start` and `restart` additionally
ensure that the AI Guardian daemon and gateway service are available; `delete`
removes that service before the native sandbox. `create` and `list` add AI
Guardian defaults and managed-resource filtering. See the
[Sandbox CLI guide](docs/Sandbox.md) for the full command reference, including
timestamped configuration snapshots and recreating a sandbox with
`--restore-config latest`.

The OpenShell subcommand exposes the daemon's internal port through the
gateway-managed `ai-guardian` service. The gateway gives each sandbox a
separate URL, so multiple sandboxes can use the same internal port:

```bash
openshell service expose NAME 63152 ai-guardian
openshell service get NAME ai-guardian
# Example: http://NAME--ai-guardian.openshell.localhost:PORT/
```

Tray and NiceGUI discovery query the gateway for these service URLs. `--port`
is a container-only option; OpenShell selects the service port through the
gateway and does not use a host-side forward process.

OpenShell must be installed and initialized on the host first, with a
reachable gateway and configured compute driver; follow the
[official OpenShell quickstart](https://docs.nvidia.com/openshell/get-started/quickstart).
On Fedora/Linux, verify the systemd user service with
`systemctl --user status openshell-gateway`. On macOS, verify the Homebrew
service with `brew services list`. In both cases, run `openshell status` before
using the OpenShell subcommand. When the gateway uses rootless Podman on Linux,
start its API socket first with `systemctl --user enable --now podman.socket`;
see the container guide for socket-path troubleshooting.

The OpenShell subcommand opens a shell by default. Its `--repo` option uploads an
isolated snapshot rather than binding the host checkout; the shell starts in
`/sandbox/repo`, and a read/write GitHub provider can push the sandbox copy
without writing files back to the host. Pass `-- codex` to launch Codex
directly instead of opening the shell.

OpenShell integration is experimental. The documented workflows have been
tested with Claude Code through Google Vertex AI, Codex through its OpenShell
provider, Pi through its Anthropic-compatible OpenShell route, and OpenCode
using Claude through Vertex AI. Claude
marketplace/plugin installation has also been tested with the read-only GitHub
overlay described below.

For Claude Code through Google Vertex AI, set the GCP project and launch with
the OpenShell image. The subcommand creates or updates and attaches the gateway
provider, configures the workspace's `inference.local` route, and supplies
Claude only the non-secret client settings it requires; the host ADC file is
consumed by the gateway and is not mounted into the sandbox. The
`ANTHROPIC_API_KEY=unused` value is only a Claude Code protocol placeholder,
not an API credential; the actual authentication comes from the attached
Vertex provider:

```bash
export ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project
export CLOUD_ML_REGION=global

ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:latest \
    --cli claude \
    --model claude-sonnet-4-6 \
    --repo .
```

From the resulting shell, start Claude explicitly with `claude --bare`, as
documented by OpenShell. `--bare` skips Claude's OAuth login flow and uses
`ANTHROPIC_API_KEY` directly. The value is only a non-secret placeholder:
`inference.local` strips it and injects the real GCP access token before
forwarding the request. AI Guardian does not install a persistent shell
wrapper. For an explicit automated `claude --print ...` command passed during
creation, the entrypoint adds `--bare` when it is missing. Administrative
commands such as `claude plugin` and `claude doctor` remain unchanged. Do not
set `CLAUDE_CODE_USE_VERTEX=1` inside an OpenShell sandbox; that direct-Vertex
mode expects GCP credential discovery inside the sandbox. Use the subcommand's
`--model` option (default `claude-sonnet-4-6`) to select the gateway model.

If using a locally built image, rebuild it after pulling this change so the
OpenShell inference environment fallback is included.

Claude's background self-updater is disabled in OpenShell because the image
installation is read-only. To update Claude Code, rebuild the OpenShell image
and create a new sandbox; the subcommand sets `DISABLE_AUTOUPDATER=1`
automatically.

OpenCode is a CLI with its own agent profiles and model/provider selection. The
`--agent` profile is required when `--cli opencode` is selected. Use the explicit
two-level form when an OpenCode profile should use Claude:

```bash
ai-guardian sandbox create --runtime openshell \
    --cli opencode \
    --agent claude \
    --model claude-sonnet-4-6 \
    --provider vertex-provider \
    --repo .
```

Here `--agent claude` is an OpenCode agent profile and `--model` selects the
OpenShell inference model. OpenCode's `build` and `plan` names are profiles,
not providers: with the default `claude-sonnet-4-6` model they use the same
Claude-compatible route, while an explicitly non-Claude model leaves generic
OpenCode provider handling unchanged. The tested Claude route enables
`ANTHROPIC_BASE_URL=https://inference.local/v1` and the non-secret
`ANTHROPIC_API_KEY=unused` placeholder. OpenCode has no Claude-style `--bare`
flag; run `opencode --agent NAME` normally. The gateway inference route must
be configured with `openshell inference set`.

The `opencode` + `claude` + Claude/Vertex combination has been tested. The
`--cli` value selects OpenCode, `--agent claude` selects the tested profile,
and `--model` plus `--provider` select the inference backend.

The Claude/Vertex policy does not grant GitHub access by default. The command
above is sufficient for Claude requests, Vertex inference, and an ordinary
Claude session. Marketplace or plugin installation and refresh are different:
you must add the read-only GitHub overlay because the Anthropic marketplace is
fetched from GitHub. Without this overlay, model requests still work but
marketplace installation or refresh fails due to OpenShell's deny-by-default
network policy. The read/write GitHub policy and GitHub provider are not
required for the public catalog:

```bash
ai-guardian sandbox create --runtime openshell \
    --base localhost/ai-guardian-openshell:latest \
    --cli claude \
    --policy ./container/openshell-github-readonly-policy.yaml \
    --repo .
```

For Codex ChatGPT/OAuth credentials, enable OpenShell Providers v2 once on the
active gateway:

```bash
openshell settings set --global --key providers_v2_enabled --value true
```

A Codex OAuth login does not require a separate API key after Providers v2 is
enabled. Legacy Codex discovery requires `OPENAI_API_KEY` instead.
The subcommand converts the gateway-provided OAuth placeholders into Codex's
native sandbox-local `auth.json`; real host tokens are not uploaded. When host
files must be uploaded, the subcommand uses a compatible staging flow and starts
the selected CLI with `sandbox exec` after setup.
For API-key authentication, the entrypoint runs `codex login --with-api-key`
with the provider-injected placeholder so Codex can read its native
`auth.json`; the real host key is never written into the sandbox.
Inside OpenShell, the subcommand sets Codex's sandbox-local
`sandbox_mode = "danger-full-access"` so Codex does not create a nested
bubblewrap sandbox. OpenShell remains the outer filesystem and network
boundary; regular Docker/Podman launches retain Codex's normal inner sandbox.
See the official [OpenShell Codex example](https://github.com/NVIDIA/OpenShell/blob/main/examples/agent-driven-policy-management/sandbox-agent.sh).

For a Codex-only sandbox, no GitHub policy is required. The subcommand applies
the shared base policy and selected Codex policy automatically. Add the
read-only or read/write GitHub policy only when the sandbox needs GitHub
access.

Claude Code can use Google Vertex AI by selecting `--cli claude` and setting
`ANTHROPIC_VERTEX_PROJECT_ID`; the OpenShell subcommand creates the required
gateway provider from Google ADC credentials. See the container guide for the
complete Vertex AI example.

For proprietary agents such as Claude Code, select the agent explicitly and
review its terms before enabling the runtime consent flow. See the container
guide for the supported agent matrix.

```bash
# Pinned release
podman pull quay.io/redhatproductsecurity/ai-guardian:v1.18.0
podman run -it -p 63152:63152 -e AI_GUARDIAN_AGENT=codex quay.io/redhatproductsecurity/ai-guardian:v1.18.0

# Or build from source
podman build -t ai-guardian container/
podman run -it -p 63152:63152 -e AI_GUARDIAN_AGENT=codex ai-guardian
```

See [container/README.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/container/README.md) for agent selection, host config/profile behavior, OpenShell, Vertex AI auth, and multi-arch details.
The container guide also includes [read-only](container/openshell-github-readonly-policy.yaml) and [read/write](container/openshell-github-readwrite-policy.yaml) OpenShell policy overlays, selected-CLI policy fragments, and provider setup.

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
ai-guardian pause [MINUTES]      # Pause global scanning (0/omitted: indefinite)
ai-guardian resume                # Resume global scanning
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

| Feature | Description |
|---------|-------------|
| [Secret Scanning](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_SCANNING.md) | Multi-layered detection of API keys, tokens, passwords |
| [PII Detection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_SCANNING.md) | Detect personally identifiable information |
| [Prompt Injection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/PROMPT_INJECTION.md) | Language-aware detection with tree-sitter AST parsing and configurable sensitivity |
| [Image Scanning](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/IMAGE_SCANNING.md) | OCR-based secret and PII detection in screenshots and images |
| [Unicode Attack Detection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/UNICODE_ATTACKS.md) | Zero-width chars, bidi override, homoglyphs |
| [SSRF Protection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SSRF_PROTECTION.md) | Block private IPs, cloud metadata, dangerous schemes |
| [Config File Scanning](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CREDENTIAL_EXFILTRATION.md) | Detect exfiltration of sensitive config files |
| [Directory Blocking](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/DIRECTORY_RULES.md) | `.ai-read-deny` markers + config-based rules |
| [Tool Permissions](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOOL_POLICY.md) | Allow/deny lists for Skills, MCP, Bash, Write |
| [Violation Logging](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/VIOLATION_LOGGING.md) | JSON audit trail with unified policy decisions |
| [Sanitize Command](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_REDACTION.md) | Clean sensitive data from files |
| [Interactive Console](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONSOLE.md) | TUI for managing configuration visually |
| [Scanner Management](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md) | Install and manage 8 scanner engines (including built-in toml-patterns) |
| [Pre-commit Hook](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/PRE_COMMIT.md) | Scan staged files for secrets before commit |
| [Inline Annotations](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/ANNOTATIONS.md) | Suppress false positives with `ai-guardian:allow` and block annotations |
| [Self-Protection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SECURITY_DESIGN.md) | Prevents AI from disabling its own security controls |
| [MCP Security Advisor](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md) | Read-only security tools for AI agents (proactive checks) |
| [MCP Security Scanning](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md#mcp-security-scanning) | Audit MCP server configs and source code for supply chain risks |
| [Project Config Overlay](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md#2-project-level-config-overlay-new-in-v180) | Per-repo config with immutable fields and global-only section protection |
| [Multi-Daemon Tray](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md) | Discover and manage daemons across local, Podman/Docker, and Kubernetes |
| [Desktop Shortcut & Autostart](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md#desktop-shortcuts) | Install tray as desktop app with optional login startup |
| [Tray Plugins](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md#tray-plugins) | Custom menu items with native tkinter popup forms (Textual terminal fallback), platform-aware commands |
| [TOML Pattern Engine](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOML_PATTERNS.md) | Built-in Python scanner with 425 pre-compiled patterns, no binary required |
| [Multi-Agent Support](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md) | Hook adapters for 17 AI coding agents with normalized input/output |
| [Container Image](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/container/README.md) | UBI-based image with supported agent integrations and scanners, published to quay.io |
| [Supply Chain Scanning](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md#supply-chain-scanning) | Detect malicious patterns in agent hooks, MCP configs, and plugin files |
| [Context Poisoning Detection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CONTEXT_POISONING.md) | Detect persistent instruction injection in conversation context (OWASP LLM03) |
| [Security SDK & REST API](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SDK.md) | Programmatic security checking for Python agents and multi-language support |
| [Secret Liveness Validation](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md#secret-liveness-validation) | Verify detected secrets are still active via provider APIs |
| [Hook Latency Metrics](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/HOOKS.md#hook-latency-tracking) | Per-hook timing with console dashboard for performance analysis |
| [OTEL Observability](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/OBSERVABILITY.md) | OpenTelemetry trace export for SDK agent runs and interactive sessions |
| [Canary Token Detection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) | Detect user-registered tripwire values in AI output to catch data exfiltration |
| [Offensive Language Scanner](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) | Detect profanity, slurs, and non-inclusive terminology in code and comments |
| [Exfiltration Behavior Detection](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CREDENTIAL_EXFILTRATION.md) | Detect bash commands that steal credentials via curl, base64, SSH key exfil |
| [Code Security Scanning](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md) | Bandit/Semgrep-based detection of insecure code patterns (eval, weak crypto, injection) |
| [Dummy Agent](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md) | LLM-free hook testing via interactive REPL with YAML scenario files |
| [Kubernetes Deployment](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/kubernetes.md) | Kustomize manifests for Kind, OpenShift, and production deployments |
| [Security Instructions](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) | Configurable agent context injection rules via TUI and web console |
| [Transcript Scanning](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md#transcript-scanning-availability) | Scan IDE conversation transcripts for secrets/PII across 7+ IDEs |
| [LeakTK Listen Mode](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md) | Event-driven scanning with 40x latency reduction vs polling |
| [Zero-Config Onboarding](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) | `init --scan` scans the project and generates a tuned config |
| [Language-Aware FP Suppression](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/PROMPT_INJECTION.md) | Tree-sitter AST parsing reduces false positives in code |
| [ML Prompt Injection Setup](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/PROMPT_INJECTION.md) | One-command `ai-guardian ml setup` installs model + dependencies |
| [Crush IDE Support](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md) | Hook adapter for Charmbracelet Crush with MCP advisory |
| [Pi IDE Support](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md) | Extension-based hook adapter for Pi with JSONL transcript scanning |
| [Event-Driven Tray Updates](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md) | Tray refreshes on daemon state changes instead of polling |
| [Scan & Configure UI](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONSOLE.md) | Web console workflow to scan a project and generate config |

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
ai-guardian ide-setup sync           # Refresh local IDE/hook status in XDG state
ai-guardian ide-setup sync --json     # Print the synchronized status as JSON
ai-guardian ide-setup reset --ide claude  # Reset Claude setup prompt decisions
```

Run `ai-guardian setup` after upgrading to get the latest hooks. The MCP security advisor server is installed by default — the AI can check security proactively before acting. Use `--no-mcp` to skip. See [docs/MCP_SERVER.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md) for details and [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) for other setup options.

### OpenAI Codex coverage

`OpenAI Codex (CLI + Desktop)` means Codex CLI and **Codex mode** selected in
the ChatGPT desktop app. Regular ChatGPT mode in that app is not currently
protected by AI Guardian's Codex lifecycle hooks. The ChatGPT desktop app,
Codex CLI, and Codex IDE extension can share MCP configuration, but shared MCP
availability does not imply hook enforcement.

## Action Modes

Each security policy supports three enforcement levels:

| Mode | Execution | User Warning | Use Case |
|------|-----------|--------------|----------|
| `block` | Blocked | Error shown | **Enforce** policy (default) |
| `warn` | Allowed | Warning shown | **Educate** during rollout |
| `log-only` | Allowed | Silent | **Monitor** silently |

See [docs/CONFIGURATION.md](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md) for per-feature action mode configuration.

## Integration

See [Agent Support](docs/AGENT_SUPPORT.md) for the current capability
matrix, [IDE/Agent Integration Checklist](docs/IDE_INTEGRATION_CHECKLIST.md)
for host integrations, and [CLI/Runtime Integration Checklist](docs/CLI_RUNTIME_CHECKLIST.md)
for container and OpenShell support.

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
| `AI_GUARDIAN_HOME` | Compatibility alias for the config directory | `~/.config/ai-guardian` |
| `AI_GUARDIAN_STATE_DIR` | State directory (logs, violations) | `~/.local/state/ai-guardian` |
| `AI_GUARDIAN_CACHE_DIR` | Cache directory (patterns) | `~/.cache/ai-guardian` |
| `AI_GUARDIAN_IDE_TYPE` | Override IDE auto-detection | Auto-detect |
| `AI_GUARDIAN_PATTERN_TOKEN` | Default pattern server auth token (all sections) | None |

`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `CURSOR_CONFIG_DIR`, `COPILOT_HOME`, and
`GEMINI_CLI_HOME` are honored by setup, MCP registration, verification, and
supported session discovery. `AI_GUARDIAN_CONFIG_DIR` takes precedence over
`AI_GUARDIAN_HOME`, which takes precedence over XDG. See the
[IDE-specific path reference](docs/AGENT_SUPPORT.md#ide-specific-home-and-configuration-paths)
for the complete variable list, precedence rules, and project-local behavior.

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

Full documentation is also available at [ai-guardian.readthedocs.io](https://ai-guardian.readthedocs.io/) with search and versioned navigation.

Source docs are in the [docs/](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/) folder.

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
