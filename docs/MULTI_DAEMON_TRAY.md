# Multi-Daemon Tray Client

The system tray client discovers and manages AI Guardian daemons across multiple environments.

## Quick Start

```bash
ai-guardian daemon start          # Start local daemon (headless)
ai-guardian tray start            # Start tray (discovers all daemons)
ai-guardian tray start -b         # Start tray in background
ai-guardian tray stop             # Stop the tray
ai-guardian tray restart          # Restart the tray
```

> **Note**: The daemon runs headless. The tray is always a separate process.

## Instance Name

Set a human-friendly name in your config to identify this ai-guardian instance:

```json
{
  "name": "my-workstation"
}
```

The name appears in the Console banner, tray menu, REST API, and MCP.

If not set, defaults to `hostname`. For containers, the priority is:

1. Container label `ai-guardian.name` (set at run time)
2. Config `name` field (from `ai-guardian.json`)
3. Container name (from `podman ps`)
4. Hostname

## Tray Menu Structure

Each discovered daemon appears as a top-level menu item with its own submenu:

```
● local                         >
  Statistics                    >
  Console
  Violations
  Metrics
  Mode: auto                    >
  MCP Proactive: low            >
  Pause...                      >
  Resume
  Stop daemon
  Restart daemon
○ my-container (container)      >
  Console
  Violations
  Metrics
  Mode: auto                    >
  MCP Proactive: low            >
  Start daemon
─────────────
Restart
Quit
```

- **●** Running daemon — full submenu with Statistics, Pause/Resume, Stop/Restart
- **○** Stopped daemon — limited submenu with Console, Mode, Start daemon
- **⚠●** Running daemon with stale code detected — shows orange dot; local daemons show a **Restart daemon (stale code)** item; remote/container/Kubernetes daemons show a **Rebuild image** hint instead

## Stale-Code Indicator

When the ai-guardian source code on disk is newer than the running daemon binary, the tray shows a warning indicator next to the daemon name:

- **Local daemons**: orange dot + `Restart daemon (stale code)` menu item. Clicking it restarts the daemon and polls until it comes back online (up to 10 seconds), then refreshes the menu.
- **Container / Kubernetes daemons**: orange dot + `Rebuild image (stale code)` hint. Remote daemons cannot be restarted from the tray — you must rebuild the container image and redeploy.

Stale-code detection compares the installed package version against the timestamp of the source tree using the daemon's `/api/status` endpoint. This replaces the old dev-mode auto-restart behavior removed in v1.13.0.

## Discovery Methods

The tray discovers daemons using four methods:

| Runtime | Discovery | How |
|---------|-----------|-----|
| Local | PID file + socket ping | Check `~/.local/state/ai-guardian/daemon.pid` |
| Podman/Docker | `podman ps` / `docker ps` | Label filter + port filter (cascading) |
| Kubernetes | `kubectl get pods` | Label selector + user filter |
| Manual | Config file | `~/.config/ai-guardian/tray-targets.json` |

Discovery runs on-demand when the tray icon is clicked (~1 second to refresh).

### Container Discovery

Containers are discovered using two cascading filters:

1. **Label filter** (primary): Containers with `ai-guardian.daemon=true` label
2. **Port filter** (fallback): Containers with a port mapping to the REST port (default 63152)

Run a container daemon:

```bash
podman run -l ai-guardian.daemon=true -p :63152 your-image
```

Optional labels:
- `ai-guardian.name=my-sandbox` — display name in tray (defaults to container name)
- `ai-guardian.rest-port=8080` — custom REST port (defaults to 63152)

### Linux: Podman Container Discovery

On Linux, the tray uses the Docker SDK to communicate with Podman. For discovery
to work, the rootless Podman socket service must be active.

**Enable the Podman socket** (once, as a user service):

```bash
systemctl --user enable --now podman.socket
```

After enabling the socket, restart the tray — it will find the socket at the
standard XDG path (`$XDG_RUNTIME_DIR/podman/podman.sock`) automatically.

**If containers still do not appear**, the socket may be at a non-standard path.
Find it:

```bash
podman info --format '{{.Host.RemoteSocket.Path}}'
```

Export `DOCKER_HOST` before starting the tray:

```bash
export DOCKER_HOST=unix://$(podman info --format '{{.Host.RemoteSocket.Path}}')
ai-guardian tray start
```

To make this permanent, add the export to your shell profile (`~/.bashrc`,
`~/.zshrc`, etc.) or to a systemd user service that starts the tray.

> **macOS with Podman Desktop:** `DOCKER_HOST` is set automatically — no manual
> setup needed.

### Kubernetes Discovery

Disabled by default. Enable in config:

```json
{
  "daemon": {
    "tray": {
      "discover_kubernetes": true,
      "kubernetes": {
        "namespace": "ai-sdlc",
        "label_selector": "app=ai-guardian"
      }
    }
  }
}
```

Pods are filtered by the current user (`user=$USER` label added automatically).

### Manual Targets

Create `~/.config/ai-guardian/tray-targets.json`:

```json
{
  "daemons": [
    {
      "name": "central-server",
      "url": "https://guardian.company.com:63152",
      "token": "your-auth-token"
    }
  ]
}
```

Use `--no-discover` to skip auto-discovery and only load manual targets:

```bash
ai-guardian tray start --no-discover
```

## REST API

Each daemon exposes a REST API for tray communication:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/status` | GET | Daemon status (name, version, paused, menu_tags) |
| `/api/stats` | GET | Full stats (requests, blocked, violations, menu_tags) |
| `/api/pause` | POST | Pause scanning (`{"minutes": 15}`) |
| `/api/resume` | POST | Resume scanning |

### Bind Address

The REST API bind address is determined automatically:

- **Host machine**: `127.0.0.1` (localhost only, secure default)
- **Inside containers**: `0.0.0.0` (auto-detected via `/.dockerenv` or `/run/.containerenv`)
- **Override**: Set `daemon.rest_host` in config

The REST port is configurable via `daemon.rest_port` (default 63152, 0 = OS-assigned).

## Configuration Reference

```json
{
  "name": "my-workstation",
  "daemon": {
    "rest_port": 63152,
    "rest_host": "127.0.0.1",
    "tray": {
      "discover_containers": true,
      "discover_kubernetes": false,
      "kubernetes": {
        "namespace": "ai-sdlc",
        "label_selector": "app=ai-guardian"
      }
    }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `name` | hostname | Instance name shown in tray, Console, REST API, MCP |
| `daemon.rest_port` | `63152` | REST API port (0 = OS-assigned) |
| `daemon.rest_host` | `127.0.0.1` | REST API bind address. Auto-set to `0.0.0.0` inside containers |
| `daemon.tray.discover_containers` | `true` | Enable Podman/Docker container discovery (scans all available engines) |
| `daemon.tray.discover_kubernetes` | `false` | Enable Kubernetes pod discovery |

## Action Routing

Each daemon's submenu routes actions to the correct transport:

| Action | Local | Container | Kubernetes |
|--------|-------|-----------|------------|
| Statistics | Unix socket | REST API | REST API |
| Console | New terminal | `podman exec -it` | `kubectl exec -it` |
| Pause/Resume | Unix socket | REST API | REST API |
| Start/Stop/Restart | Subprocess | `podman exec` | `kubectl exec` |

> **In-progress guard**: Restart actions are protected against double-clicks. Once a restart is triggered, the menu item is disabled and the tray polls the daemon until it responds again (up to 10 seconds) before re-enabling the item.

## CLI Reference

```bash
ai-guardian tray start              # Start tray (foreground)
ai-guardian tray start -b           # Start tray (background)
ai-guardian tray start --no-discover  # Manual targets only
ai-guardian tray stop               # Stop running tray
ai-guardian tray restart            # Restart tray
```

## Tray Plugins

Plugins add custom menu items to the tray. Each daemon loads plugins from its own `tray-plugins/` directory and serves them via the REST API. The tray fetches and displays them automatically.

### Creating a Plugin

Create a JSON file in `~/.config/ai-guardian/tray-plugins/`:

```json
{
    "name": "My Tools",
    "items": [
        {
            "label": "Say Hello",
            "command": "echo 'Hello {tray.name}!'",
            "type": "terminal",
            "params": [
                {"name": "name", "hint": "Your name", "default": "World"}
            ]
        },
        {
            "label": "Pod Count",
            "command": "kubectl get pods --no-headers | wc -l",
            "type": "notification"
        },
        {
            "label": "Copy Pod IP",
            "command": "kubectl get svc my-app -o jsonpath='{.spec.clusterIP}'",
            "type": "clipboard"
        },
        {
            "label": "Rebuild",
            "command": "make build",
            "type": "background"
        }
    ]
}
```

Each `.json` file in the directory becomes a submenu in the tray.

### Command Types

| Type | Behavior |
|------|----------|
| `terminal` | Opens a new terminal window and runs the command |
| `background` | Runs silently with no visible output |
| `notification` | Runs silently, shows stdout as a system notification |
| `clipboard` | Runs silently, copies stdout to the system clipboard |
| `modal` | Runs silently, shows output in a native OS dialog with OK button |

### Interactive Parameters

Items with `params` show a form before executing. The user fills in values, then the placeholders `{tray.name}` in the command are substituted.

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Matches `{tray.name}` placeholder in command |
| `hint` | No | Help text shown as label/placeholder |
| `default` | No | Pre-filled value |
| `options` | No | List of allowed values — renders as dropdown |

Example with a dropdown:

```json
{
    "label": "Deploy Branch",
    "command": "make deploy BRANCH={tray.branch} ENV={tray.environment}",
    "type": "terminal",
    "params": [
        {"name": "branch", "hint": "Git branch", "default": "main"},
        {"name": "environment", "default": "dev", "options": ["dev", "staging", "prod"]}
    ]
}
```

Items without `params` execute immediately on click.

### Platform-Aware Commands

Commands can vary by platform using a command map instead of a string:

```json
{
    "label": "Open Shell",
    "command": {
        "darwin": "open -a Terminal",
        "linux": "gnome-terminal",
        "windows": "cmd.exe /k",
        "default": "bash"
    },
    "type": "terminal"
}
```

Platform keys match `platform.system().lower()`: `darwin`, `linux`, `windows`. The `default` key is the fallback. If no key matches and no default is set, the menu item is hidden on that platform.

### Target Variables

Plugin commands can reference the daemon's target context using built-in variables. These are automatically substituted from the `DaemonTarget` before execution:

| Variable | Source | Example |
|---|---|---|
| `{container_id}` | `target.container_id` | `a1b2c3d4e5f6` |
| `{container_engine}` | `target.container_engine` | `podman` |
| `{host}` | `target.host` | `127.0.0.1` |
| `{port}` | `target.port` | `63152` |
| `{name}` | `target.name` | `carbonite-dev` |
| `{pod_name}` | `target.pod_name` | `guardian-pod-1` |
| `{namespace}` | `target.namespace` | `ai-guardian` |

Example:

```json
{
    "label": "Container Logs",
    "command": "{container_engine} logs --tail 50 {container_id}",
    "type": "terminal"
}
```

Target variables use bare `{name}` syntax (no prefix), while user parameters use `{tray.name}`. Both can coexist in the same command. If a target field is `null`, the placeholder is replaced with an empty string.

### Run on Target

When `run_on_target` is `true`, the tray automatically wraps the command for the daemon's runtime:

| Runtime | Wrapping |
|---------|----------|
| Container | `<engine> exec [-it] <container_id> <command>` |
| Kubernetes | `oc exec [-it] <pod> -n <namespace> -- <command>` (falls back to `kubectl` if `oc` is not installed) |
| Local | No wrapping — runs as-is |

The plugin author writes the command as if running locally inside the target. The tray handles routing:

```json
{
    "label": "Doctor",
    "command": "ai-guardian doctor",
    "run_on_target": true,
    "type": "terminal"
}
```

For container targets, this becomes: `podman exec -it a1b2c3d4e5f6 ai-guardian doctor`

Both features can coexist:

```json
{
    "items": [
        {"label": "Doctor", "command": "ai-guardian doctor", "run_on_target": true, "type": "terminal"},
        {"label": "Logs", "command": "{container_engine} logs --tail 50 {container_id}", "type": "terminal"},
        {"label": "Restart", "command": "{container_engine} restart {container_id}", "type": "notification"}
    ]
}
```

- **Doctor**: runs inside the container (automatic wrapping via `run_on_target`)
- **Logs**: runs on host, references the container (target variable substitution)
- **Restart**: runs on host, references the container (target variable substitution)

### Plugin Discovery via REST API

The tray does not read plugin files directly. Each daemon serves its plugins via:

```
GET /api/tray-plugins
```

This means plugins work uniformly across all daemon types:

| Daemon | Plugin location |
|--------|----------------|
| Local | `~/.config/ai-guardian/tray-plugins/` |
| Container | `/home/user/.config/ai-guardian/tray-plugins/` inside the container |
| Remote | `~/.config/ai-guardian/tray-plugins/` on the remote host |

The tray receives real-time updates from each daemon via SSE (Server-Sent Events) push notifications. Violations, stats changes, and pause/resume state changes are pushed to the tray instantly — no polling delay. Tray plugins are refreshed alongside these event-driven updates. If SSE is unavailable (e.g., older daemon version or network interruption), the tray falls back to polling every 10 seconds. Local plugins load even when the daemon is stopped.

### Tag-Based Filtering

By default, all plugins appear on all daemons. Use tags to filter plugins to specific daemons.

**Daemon config** (`ai-guardian.json`):

```json
{
    "name": "carbonite-dev",
    "menu_tags": ["carbonite", "container"]
}
```

**Plugin JSON** (`tray-plugins/carbonite.json`):

```json
{
    "name": "Carbonite",
    "tags": ["carbonite"],
    "items": [...]
}
```

**Matching rules:**

| Plugin `tags` | Daemon `menu_tags` | Shown? |
|---|---|---|
| (none/empty) | (none/empty) | Yes |
| (none/empty) | `["carbonite"]` | Yes |
| `["carbonite"]` | `["carbonite", "container"]` | Yes |
| `["carbonite"]` | `["staging"]` | No |
| `["carbonite"]` | (none/empty) | No |

- Untagged plugins always show on all daemons
- Tagged plugins only show on daemons with at least one matching `menu_tags` entry
- Both sides support multiple tags (N-to-N relationship)
- Tag matching is exact string match

### Plugin Limits

- Up to 8 plugins per daemon
- Up to 12 items per plugin
- These are pre-allocated pystray slots (macOS requires fixed menu structure)

## Migration from v1.7.x

In v1.7.x, `ai-guardian daemon start` launched both the daemon and the system tray. In v1.8.0+, these are separate:

```bash
# Before (v1.7.x)
ai-guardian daemon start          # Started daemon + tray

# After (v1.8.0+)
ai-guardian daemon start          # Headless daemon only
ai-guardian tray start            # Separate tray process
```

To restore the old behavior, add both commands to your startup/login items.

## Ask Dialog Forwarding

When `action=ask` is triggered on a **headless or container daemon**, there is
no display available to show the dialog. The host tray bridges this gap by
acting as a display proxy: it receives the prompt, shows the full dialog on
the host, and sends the user's decision back to the daemon.

### Local daemon (host has display)

The hook runs inside the daemon process. The daemon calls its own REST API to
delegate dialog rendering to a subprocess, which shows the native UI.

```
┌─────────────────── host ──────────────────────────┐
│                                                    │
│  Hook (daemon process)                             │
│    └─ show_ask_dialog()                            │
│         ├─ _show_via_tray_forwarding()  → None     │
│         │    (local tray not registered            │
│         │     with local daemon)                   │
│         ├─ _is_headless_env()  → False             │
│         └─ _show_via_daemon()                      │
│              └─ POST /api/prompt  ──────────────┐  │
│                                                 │  │
│              ┌──── daemon REST ─────────────────┘  │
│              │  _handle_prompt()                   │
│              │    └─ _show_via_subprocess()         │
│              │         └─ ai-guardian prompt        │
│              │              --mode ask              │
│              │              └─ tkinter / NiceGUI    │
│              │              └─ user responds        │
│              │         └─ AskResult                 │
│              └─ HTTP response                       │
│         └─ decision applied to hook                │
└────────────────────────────────────────────────────┘
```

### Remote daemon (container / Kubernetes)

The hook runs inside the container. Because the container has no display, it
queues the prompt and waits. The host tray polls for pending prompts, shows
the dialog on the host machine, and POSTs the decision back.

```
┌──── container ─────────────────────────┐   ┌──── host ──────────────────────────────┐
│                                        │   │                                        │
│  Hook                                  │   │  Tray                                  │
│    └─ show_ask_dialog()                │   │    └─ every ~30s:                      │
│         └─ _show_via_tray_forwarding() │   │         POST /api/register-tray ──────>│
│              └─ is_tray_registered()   │   │              (sets is_tray_registered) │
│                    → True              │   │                                        │
│              └─ queue_prompt()         │   │    └─ every 2.5s:                      │
│              └─ decision_event.wait() <│───│─        GET /api/pending-prompts       │
│                                        │   │         └─ _handle_remote_prompt()     │
│                                        │   │              └─ _show_via_subprocess() │
│                                        │   │                   (NiceGUI on macOS,   │
│                                        │   │                    auto on Linux)       │
│                                        │   │              └─ user responds           │
│              └─ resolve_prompt()  <────│───│─        POST /api/prompt-decision      │
│              └─ decision_event.set()   │   │                                        │
│         └─ AskResult returned          │   │                                        │
│    └─ decision applied to hook         │   │                                        │
└────────────────────────────────────────┘   └────────────────────────────────────────┘
```

### No tray registered

If no tray has registered with the daemon (tray not running, or remote daemon
not yet discovered), `_show_via_tray_forwarding()` returns `None` immediately.
On a headless host (Linux + no `DISPLAY`), the hook falls through to the
configured `fallback_action` (default: `block`) with zero delay.

```
show_ask_dialog()
  └─ _show_via_tray_forwarding()  → None  (is_tray_registered = False)
  └─ _is_headless_env()           → True
  └─ fallback_action applied immediately  (no blocking)
```

### Platform notes

| Host OS | Dialog shown by tray |
|---|---|
| macOS 14+ | NiceGUI browser tab (tkinter suppressed — pystray is NSAccessory, cannot steal focus) |
| Linux KDE/GNOME | tkinter / NiceGUI / Textual per `preferred_ui` config |
| macOS < 14 | tkinter / NiceGUI / Textual per `preferred_ui` config |

The full dialog is shown in all cases: Allow Once, Allow Always (with pattern
editor), Suppress in Source, Ignore File, and Block. Pattern saving and source
annotations are applied by the **triggering daemon** (not the host), so they
land in the correct config files and source tree.

## Testing Ask Dialog Forwarding

End-to-end test procedure for verifying that ask dialogs generated inside a
container or remote daemon appear on the host tray.

### Prerequisites

1. **Start the container daemon:**

   ```bash
   # Using the bundled run script (sets ai-guardian.daemon=true label automatically)
   ./container/run.sh

   # Or manually with Podman/Docker
   podman run -l ai-guardian.daemon=true -p 63152:63152 quay.io/redhatproductsecurity/ai-guardian:latest
   ```

2. **On Linux — export the Podman socket** so the tray can discover the container (#1436):

   ```bash
   export DOCKER_HOST=unix://$(podman info --format '{{.Host.RemoteSocket.Path}}')
   ```

   > **macOS with Podman Desktop:** `DOCKER_HOST` is set automatically — skip this step.

3. **Start the host tray:**

   ```bash
   ai-guardian tray start -b
   ```

   The container daemon should appear in the tray menu within ~10 seconds. Confirm
   the container is listed with a running indicator (●) before proceeding.

### Option A — dummy-agent scenario (preferred)

Requires the `action: ask` pattern to be configured in the container's
`ai-guardian.json` (e.g., `prompt_injection.action: ask`).

Inside the container:

```bash
ai-guardian dummy-agent --script scenarios/ask-dialog.yaml
```

The scenario fires hook events through the full pipeline (UserPromptSubmit →
PreToolUse → PostToolUse) with content that triggers the ask mode. The daemon
queues the prompt, the tray polls `/api/pending-prompts`, and the dialog
appears on the host.

**Expected result:** Ask dialog appears on the host machine with **Allow Once**,
**Allow Always**, **Suppress in Source**, **Ignore File**, and **Block** options.

### Option B — direct REST API (workaround / quick smoke test)

If dummy-agent is unavailable or you want a quick confirmation without
configuring ask mode, POST directly to the container daemon's REST API:

```bash
# Inside the container
curl -s -X POST http://127.0.0.1:63152/api/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "ask",
    "violation": {
      "violation_type": "secret_detected",
      "summary": "AWS Access Key detected",
      "matched_text": "AKIAI<YOUR_ACCESS_KEY_ID>",
      "config_section": "secret_scanning"
    }
  }'
```

**Expected result:** Ask dialog appears on the host. The `curl` call blocks until
the user responds, then returns `{"decision": "allow_once"}` (or similar).

**Confirmed working on:** Linux and macOS. ✅

### Known Limitations

- **Hook pipeline does not trigger ask via synthetic payloads.** Hand-crafted
  hook payloads fired from the shell (e.g., via `ai-guardian hook`) do not reach
  the ask path because:
  - `PreToolUse` with a secret in `tool_input` → blocked by tool permission
    policy before secret scan runs
  - `PostToolUse` with a secret in `tool_response` → uses `secret_redaction`
    (action=warn), not `secret_scanning` (always blocks)
  - `UserPromptSubmit` with a secret in transcript → transcript scanning always
    warns, never asks

  Use **Option A** (dummy-agent scenario) or **Option B** (direct REST) to bypass
  these limitations.

- **Timeout (#1445):** The default hook timeout is 30 seconds, which may expire
  before the user responds to the dialog. If the ask dialog appears but the
  hook times out before a decision is made, increase
  `daemon.hook_timeout_seconds` in the container's config, or use Option B
  (REST has no hook timeout).

### Kubernetes Variant

Same procedure applies with `kubectl port-forward` in place of a direct port
mapping:

```bash
kubectl port-forward pod/<guardian-pod> 63152:63152
```

Then run Option B from any machine with access to `localhost:63152`.
