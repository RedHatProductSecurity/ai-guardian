# AI Guardian Container Image

UBI-based container image with ai-guardian and all headless-capable IDEs.
Published to [quay.io/redhatproductsecurity/ai-guardian](https://quay.io/redhatproductsecurity/ai-guardian) on every merge and release.

## What's Included

| Component | License | Installed |
|-----------|---------|-----------|
| ai-guardian | Apache 2.0 | Build time |
| gitleaks, betterleaks | MIT / Apache 2.0 | Build time |
| OpenCode | MIT | Build time |
| Gemini CLI | Apache 2.0 | Build time |
| Codex CLI | Apache 2.0 | Build time |
| OpenClaw | MIT | Build time |
| rapidocr-onnxruntime | Apache 2.0 | Build time |
| Claude Code | Proprietary (Anthropic) | **Runtime — ToS consent required** |
| Kiro CLI | Proprietary (AWS) | **Runtime — ToS consent required** |

Claude Code and Kiro CLI are proprietary and redistribution-restricted. They are not
bundled in the image. Instead, the container installs them at first start after
prompting the user to accept the respective Terms of Service.

See [Proprietary CLI Consent](#proprietary-cli-consent) below.

## Pull

```bash
# Latest build from main branch
podman pull quay.io/redhatproductsecurity/ai-guardian:latest

# Specific release version
podman pull quay.io/redhatproductsecurity/ai-guardian:1.13.2
```

Tag conventions:
- `:latest` — tracks main branch (updated on every merge)
- `:<version>` — pinned stable release (e.g. `1.13.2`)

## Build Locally

```bash
# Default (latest release)
podman build -t ai-guardian container/

# Specific version
podman build --build-arg AI_GUARDIAN_VERSION=1.13.2 -t ai-guardian container/

# Local wheel (copy wheel into container/ first)
cp dist/ai_guardian-1.13.2-py3-none-any.whl container/vendor/
podman build --build-arg AI_GUARDIAN_VERSION=ai_guardian-1.13.2-py3-none-any.whl \
    -t ai-guardian container/

# Multi-arch
podman build --platform linux/amd64,linux/arm64 -t ai-guardian container/
```

## Run

Using `run.sh` (recommended):

```bash
./container/run.sh                                    # defaults: claude, standard
./container/run.sh --ide opencode                     # select IDE
./container/run.sh --profile @strict                  # select profile
./container/run.sh --repo ~/myproject                 # mount a repo
./container/run.sh --api-key sk-ant-...               # Anthropic API auth
./container/run.sh --ide gemini --profile @minimal    # combine options
./container/run.sh -- ai-guardian doctor              # run a command
```

Vertex AI auth is auto-detected from environment variables (see [Authentication](#authentication)).

<details>
<summary>Manual container run (podman / docker)</summary>

```bash
# Default (Claude Code hooks)
podman run -it -p 63152 ai-guardian

# Select IDE
podman run -it -p 63152 -e AI_GUARDIAN_IDE=opencode ai-guardian

# Select configuration profile
podman run -it -p 63152 -e AI_GUARDIAN_PROFILE=@strict ai-guardian

# Authenticate with Anthropic API
podman run -it -p 63152 -e ANTHROPIC_API_KEY=sk-ant-... ai-guardian

# Authenticate with Vertex AI
podman run -it -p 63152 \
    -e CLAUDE_CODE_USE_VERTEX=1 \
    -e ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project \
    -e CLOUD_ML_REGION=global \
    -e GOOGLE_APPLICATION_CREDENTIALS=/sandbox/gcp-key.json \
    -v ~/gcp-key.json:/sandbox/gcp-key.json:ro \
    ai-guardian

# Mount a repo to test
podman run -it -p 63152 -v ~/myrepo:/sandbox/repo ai-guardian

# Run doctor
podman run -it ai-guardian ai-guardian doctor
```

</details>

## Container Engine

By default, `run.sh` uses Podman. To use Docker instead:

```bash
CONTAINER_ENGINE=docker ./container/run.sh
# or export for the session:
export CONTAINER_ENGINE=docker
./container/run.sh --ide claude
```

Both engines support the same `-p` syntax for port mapping. Use `docker port <container>` (instead of `podman port`) to find the mapped host port when using Docker.

## IDE Selection

Set `AI_GUARDIAN_IDE` to configure hooks for a specific IDE at container start:

| Value | IDE | Installed in image |
|-------|-----|--------------------|
| `claude` (default) | Claude Code | **Runtime — ToS consent** |
| `opencode` | OpenCode | Yes |
| `gemini` | Gemini CLI | Yes |
| `codex` | Codex CLI | Yes |
| `kiro` | Kiro CLI | **Runtime — ToS consent** |
| `openclaw` | OpenClaw | Yes |
| `cursor` | Cursor | No (hooks only) |
| `copilot` | GitHub Copilot | No (hooks only) |
| `windsurf` | Windsurf | No (hooks only) |
| `augment` | Augment | No (hooks only) |
| `cline` | Cline | No (hooks only) |
| `zoocode` | ZooCode | No (hooks only) |
| `junie` | Junie | No (hooks only) |
| `aiderdesk` | AiderDesk | No (hooks only) |
| `dummy-agent` | Dummy Agent (fake IDE for hook testing) | Yes — no LLM required |

IDEs marked "hooks only" are not installed in the image (they require a GUI) but
ai-guardian hooks are configured for them. Mount the IDE binary into the container
if needed.

## Proprietary CLI Consent

Claude Code (Anthropic) and Kiro CLI (AWS) are proprietary with redistribution
restrictions. They are not bundled in the image. When `AI_GUARDIAN_IDE=claude`
or `AI_GUARDIAN_IDE=kiro` is set, the container prompts for ToS acceptance at
first start and installs the CLI if the user agrees.

### Interactive (default)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Claude Code requires accepting its Terms of Service:
  https://www.anthropic.com/legal/consumer-terms
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Install Claude Code and accept the ToS? [y/N]
```

Answer `y` to install, `N` (or Enter) to skip.

### Non-interactive / CI

Set `ACCEPT_PROPRIETARY_TOS=true` to bypass the prompt and install
automatically. By setting this variable you confirm you have read and accept
the relevant Terms of Service.

```bash
# Claude Code — non-interactive
podman run -it -p 63152 \
    -e ACCEPT_PROPRIETARY_TOS=true \
    -e ANTHROPIC_API_KEY=sk-ant-... \
    quay.io/redhatproductsecurity/ai-guardian:latest

# Kiro CLI — non-interactive
podman run -it -p 63152 \
    -e AI_GUARDIAN_IDE=kiro \
    -e ACCEPT_PROPRIETARY_TOS=true \
    quay.io/redhatproductsecurity/ai-guardian:latest
```

The `run.sh` helper passes `ACCEPT_PROPRIETARY_TOS` through from the host
environment automatically if it is set.

### Already installed

If the binary is already present in `$HOME/.local/bin/` (e.g. from a mounted
volume), the consent prompt is skipped.

## Configuration Profile

Set `AI_GUARDIAN_PROFILE` to apply a security profile at container start:

| Value | Description |
|-------|-------------|
| (unset) | Standard profile (default) |
| `@minimal` | Minimal — fewer checks, lower false positive rate |
| `@standard` | Standard — balanced security and usability |
| `@strict` | Strict — maximum security, all checks enabled |
| `@moderator` | Moderator — all scanner actions set to `ask` for human-in-the-loop review |

You can also pass a custom profile name or path if you have saved custom profiles.

## Authentication

Pass authentication credentials as environment variables at runtime.

> **Tested configurations:** Anthropic API key and Google Vertex AI have been
> validated with this image. Other providers (AWS Bedrock, Azure, self-hosted)
> may require additional environment variables or volume mounts — consult the
> IDE's documentation for the required configuration.

### Anthropic API (direct)

```bash
podman run -it -p 63152 \
    -e ANTHROPIC_API_KEY=sk-ant-... \
    ai-guardian
```

### Google Vertex AI ✓ tested

```bash
podman run -it -p 63152 \
    -e CLAUDE_CODE_USE_VERTEX=1 \
    -e ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project \
    -e CLOUD_ML_REGION=global \
    -e GOOGLE_APPLICATION_CREDENTIALS=/sandbox/gcp-key.json \
    -v ~/my-gcp-key.json:/sandbox/gcp-key.json:ro \
    ai-guardian
```

### Other providers (untested)

Other Claude-compatible providers may work by passing the appropriate env vars.
The container does not pre-configure any provider-specific tooling beyond
Claude Code, so extra setup (CLI login, credential files, proxy config) may be
needed inside the container after startup.

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (direct API access) |
| `CLAUDE_CODE_USE_VERTEX` | Set to `1` to use Google Vertex AI |
| `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project ID (with Vertex AI) |
| `CLOUD_ML_REGION` | GCP region, e.g. `global` (with Vertex AI) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON key file (with Vertex AI) |

## Web Console

The ai-guardian daemon starts automatically and binds to `0.0.0.0` inside the
container (auto-detected via `/.dockerenv` / `/run/.containerenv`).

Access from the host: `http://localhost:63152`

## Build Args

| Arg | Default | Description |
|-----|---------|-------------|
| `AI_GUARDIAN_VERSION` | `1.13.2` | PyPI version or `.whl` filename |
| `AI_GUARDIAN_REST_PORT` | `63152` | Daemon REST API / web console port |
| `UV_VERSION` | `0.11.16` | uv package manager version |
| `OPENCODE_VERSION` | `1.17.3` | OpenCode version |

## Test Image (Dockerfile.test)

The test image extends the base image with bundled dummy-agent scenarios for hook regression testing. Not for distribution — local CI only.

### Build

```bash
# Build base image first
podman build -t ai-guardian container/

# Build test image on top
podman build -f container/Dockerfile.test -t ai-guardian-test container/
```

### Run

```bash
# Run all bundled scenarios (CI mode)
podman run --rm ai-guardian-test /sandbox/run-scenarios.sh

# Run a specific scenario
podman run --rm ai-guardian-test \
  ai-guardian dummy-agent --script /sandbox/scenarios/basic-secret.yaml

# Interactive REPL
podman run -it ai-guardian-test ai-guardian dummy-agent
```

### Bundled scenarios

| Scenario | What it tests |
|---|---|
| `basic-secret.yaml` | AWS key detection → block |
| `pii-detection.yaml` | Credit card, passport detection |
| `ask-dialog.yaml` | Ask dialog forwarding to tray |
| `tool-policy.yaml` | Directory rules, tool blocking |

## Expected Doctor Warnings

In a container, `ai-guardian doctor` will show expected warnings for:

- **System tray**: Not available (no display server)
- **Terminal emulator**: Not detected (no desktop)
- **tkinter**: Not installed (no GUI needed)

All security-critical checks (config, hooks, scanners, daemon) should pass.
