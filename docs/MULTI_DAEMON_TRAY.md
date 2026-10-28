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

With multiple daemons, each has a submenu; one daemon uses the same applicable
entries in a flat layout. This includes SSH-managed VMs:

Local daemons are always first. All other daemons are sorted alphabetically by
their displayed name, ignoring case, across SSH/container/Kubernetes/manual
transports. Discovery refresh preserves that ordering and the selected target.

```
● local                         >
  Status                        >
  Pause...                      >
  Terminal
  Console
  Violations
  Metrics & Audit
  Statistics                    >
  MCP Proactive: low            >
  Working Dir: ~
  Maintenance                   >
  About
● ssh-my-vm                     >
  Status                        >
  Pause...                      >
  Terminal
  Console
  Violations
  Metrics & Audit
  Statistics                    >
  MCP Proactive: low            >
  Working Dir: ~
  Maintenance                   >
  About
  Manage SSH connection...
─────────────
Restart
Quit
─────────────
Contact supports
About
```

- **●** Running daemon — full submenu with Statistics, Pause/Resume, Stop/Restart
- **○** Offline SSH daemon — cached diagnostics, Terminal and management remain;
  REST-dependent actions are unavailable and **Start daemon** is offered.
- **⚠●** Running daemon with stale code detected — shows orange dot; local daemons show a **Restart daemon (stale code)** item; remote/container/Kubernetes daemons show a **Rebuild image** hint instead

The MCP Proactive submenu includes `low`, `medium`, `high`, and `paused`.
Daemon pauses temporarily use the `paused` effective state without changing the
saved proactive level; hooks continue enforcing security.

**About** shows **Author: Dominique Vernier ([ITDoVe](https://github.com/itdove))**,
without displaying the full profile URL, alongside the existing
version, system, scanner and repository details. With Tk available, click the
author line or focus it and press Enter/Space to open the profile. Opening or
closing About does not open the profile. If Tk is unavailable, the browser UI
keeps the same clickable attribution; the profile still opens only on selection.
Older daemon responses also retain this author attribution. See the
[provider/capability matrix](MODAL_PROVIDERS.md) for all modal families and exceptions.
The Tk dialog finishes layout before opening and requests foreground focus again
after the tray-menu handoff, so it stays visible rather than immediately dropping
behind other windows. The raising hint is temporary, not permanent always-on-top.

On Linux, About and shared informational message dialogs have no reading
deadline: leaving a window open beyond 30 seconds must not replace it with
another provider. Normal dismissal (including Escape or the window close
button) completes the action. Missing providers and startup failures retain
fallback support; an isolated Tk window that has already mapped is never
replaced by another toolkit after a later failure. Diagnostics identify the
provider, exit status and startup/display stage without logging dialog content.
This does not change the separate response deadlines for security prompts.

For an intermittent opening/style flash, record the distribution, desktop,
X11/Wayland session, selected UI and actual provider/process, plus the delay and
a screen recording with sensitive content removed. Compare repeated opens and
leaving the window open beyond 30 seconds on GNOME/zenity and KDE/kdialog where
available. A rendering/decorations transition is not by itself evidence of a
toolkit fallback.

**Contact supports**, immediately above **About**, is a global action available
even with no running daemon. It respects the configured support destination;
GitHub is the default; its first screen has a **Destination** dropdown with
**Create ZIP only** (initial selection) or **Gist + Discussion**, followed by
**Next** to open the selected review page, without rewriting saved export settings.
The native modal has an aligned file table,
fully paged View buttons, inclusion checkboxes, Select all / Deselect all, a message
field, GitHub-only Bug Reports/Q&A selection, and a final destination. The ZIP
and send reviews list **doctor.json** first and preselect only that file for new
bundles, with remaining files alphabetically ordered. Saved selections, including
an unchecked Doctor, are retained. Title starts blank; GitHub requires a title
and message, and ZIP/legacy reviews require a message. The action also requires
at least one selected file. Dialogs request
foreground focus instead of opening minimized. The ZIP
choice needs no GitHub authentication or upload and includes complete selected
diagnostics; only the log can be shortened. Logs and violations cover the last
12 hours, with included violation records kept complete. Cancel, Create ZIP or Send when ready.
The result stays visible until closed; a created ZIP offers **Open destination
folder** in the native file browser. View includes a **Wrap lines** toggle and
a horizontal scrollbar when wrapping is off.
Next is disabled for the public choice without GitHub credentials. It requires separate
native consent to upload the exact selected files to your unlisted Gist, then to
publish the exact Discussion containing its actual link. Unlisted is not private.
After upload, cancellation or failure shows **Open Gist** for management/deletion
instead of claiming nothing was uploaded. It never collects remote-daemon
diagnostics implicitly. See [Support bundles](SUPPORT.md#from-the-system-tray).
Explicit local CLI/MCP exports do not contact support. Retained reviewed copies
remain available to a later terminal `support send` within their original lifetime.

Every discovered daemon is exposed in the tray. The menu is rebuilt when the
discovery result changes, so the number of running containers or other remote
daemons is not limited by a fixed tray slot count.

## Stale-Code Indicator

For a local development (`-dev`) install, the daemon records the newest
modification time of its tracked runtime files in its PID file at startup. The
tray compares that value with the current inventory and shows a warning when a
tracked file is newer. For installed releases, staleness is determined from the
daemon and tray package versions; remote/container/Kubernetes targets use their
reported daemon version because their source trees are not available locally.

The inventory is curated rather than the entire package. It includes Python
modules under `config/`, `hook_adapters/`, `hook_events/`, `patterns/`,
`scanners/`, `sdk/`, `setup/`, `tools/`, `utils/`, `violations/`, and
`observability/`; the package initializer and root hook, configuration, adapter,
health-check, and self-test modules; and selected daemon lifecycle, REST API,
reporting, MCP audit, prompt, pattern-editor, and tray-plugin helpers, plus the
shared `sessions/base.py` title helper. It tracks
the bundled `patterns/data/*.toml` rules, `templates/tray-plugins/*.json`, and
`schemas/ai-guardian-config.schema.json` because daemon paths read those files
at runtime. The exact directory and path allowlists live beside
`DaemonState.get_package_max_mtime()` in `src/ai_guardian/daemon/state.py`.

Client-only code stays out of the inventory: for example, the full
`integrations/`, `ui/`, `web/`, and `tray/` trees, `daemon/client.py`,
`daemon/discovery.py`, `mcp/server.py`, and the daemon's CLI-only `auto_setup.py`
and `desktop.py` helpers. A few individual files in those packages are included
where the daemon server calls them directly.

When adding a package module or resource, check whether the daemon server, its
REST handlers, or hook-processing path imports and uses it. Add a whole
directory only when it is a cohesive daemon runtime subsystem; add an explicit
path for an isolated shared helper or resource. Keep unrelated CLI and client
code excluded, and add coverage for both included and excluded paths.

- **Local daemons**: orange dot + `Restart daemon (stale code)` menu item. Clicking it restarts the daemon and polls until it comes back online (up to 10 seconds), then refreshes the menu.
- **Container / Kubernetes daemons**: orange dot + `Rebuild image (stale code)` hint. Remote daemons cannot be restarted from the tray — you must rebuild the container image and redeploy.

The dev source-time comparison is a warning only; it does not restart the
daemon automatically. This replaces the old dev-mode auto-restart behavior
removed in v1.13.0.

## Discovery Methods

The tray finds daemon targets through runtime discovery, explicit SSH enrollment
or manual configuration:

| Runtime | Discovery | How |
|---------|-----------|-----|
| Local | PID file + socket ping | Check `~/.local/state/ai-guardian/daemon.pid` |
| Podman/Docker | `podman ps` / `docker ps` | Label filter + port filter (cascading) |
| Kubernetes | `kubectl get pods` | Label selector + user filter |
| SSH | Explicit enrollment + saved connections | Verify a known alias with **Add daemon via SSH**; optional alias inventory offers candidates, not trusted targets |
| Manual | Config file | `~/.config/ai-guardian/tray-targets.json` |

Runtime discovery refreshes in the background and on tray interaction. SSH alias
inventory is opt-in; saved SSH targets reconnect independently of that inventory.
The [Ubuntu VM guide](UBUNTU_VM.md) covers its upcoming-release PyPI prerequisites.

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

### Socket interruptions and Podman Desktop

The tray refreshes container discovery periodically in addition to reacting to
container events. If the Podman API socket briefly disappears—for example when
Podman Desktop closes or recreates its connection—the tray keeps the last-known
container targets visible with an unknown status and retries automatically. A
successful query replaces that cache, so containers that were actually deleted
or stopped disappear normally after the engine is reachable again.

The tray does not run `systemctl` or restart Podman Desktop automatically. The
socket is a user-session service and its setup differs across platforms. On
Linux, repair or enable it with:

```bash
systemctl --user enable --now podman.socket
```

An inactive `podman.service` is expected with socket activation; check the
socket instead:

```bash
systemctl --user status podman.socket
```

If the socket is at a non-standard path, export the Docker-compatible endpoint
before starting the tray:

```bash
export DOCKER_HOST=unix://$(podman info --format '{{.Host.RemoteSocket.Path}}')
```

### Kubernetes Discovery

Disabled by default. Enable in config:

```json
{
  "daemon": {
    "tray": {
      "discover_kubernetes": true,
      "kubernetes": {
        "namespace": "ai-sdlc",
        "label_selector": "app=ai-guardian",
        "ownership": {
          "label": "ai-guardian.owner",
          "value": "my-user"
        }
      }
    }
  }
}
```

Pods are always filtered by an ownership label. The default contract is
`ai-guardian.owner=$USER`; set `AI_GUARDIAN_K8S_OWNER` or configure an explicit
`ownership.value` when the cluster owner identity differs from the local
username. Every daemon deployment must set the same ownership label. This
prevents discovery and token reads from crossing user boundaries in shared
namespaces. The ownership selector is added to `label_selector` and cannot be
removed by setting a broader base selector.

### Add daemon via SSH

**Fresh headless Ubuntu VM?** Start with the
[ordered PyPI/venv HTTPS/SSH guide](UBUNTU_VM.md), including the release gate,
VM-hosted Console bootstrap and workstation-side pairing. As of 2026-10-28,
production PyPI 1.20.0 does not contain these features; the guide targets 1.21
development until a supporting published artifact is qualified.

For an SSH-only VM (including a known AWS instance), choose **Add daemon via SSH**
in the tray. The shared modal dispatcher tries **Native → Tkinter → NiceGUI**,
respecting explicit preferences and advancing only after proven pre-display
startup failure. It never switches toolkit after host input or cancellation.
No Web Console, `tray-targets.json` editing or separately maintained tunnel is
needed. The local Web Console retains its existing pairing controls too.

**Prerequisites:** a system OpenSSH client, an existing host-key-verified SSH
destination and agent/key authentication, and a POSIX remote host with `python3`
and a running loopback HTTPS AI Guardian daemon. Provision its certificate and
local trust as described [below](#native-https-and-explicit-certificate-trust).
This does not install/start the remote daemon or provision SSH keys. Unknown or
changed SSH host keys are never accepted automatically; verify them independently
using your ordinary SSH client before pairing. Password/keyboard-interactive
authentication is not offered by this non-interactive workflow.

1. Enter the known alias or `user@host`. Port, identity-file, jump-host and agent
   settings come from your existing SSH configuration; options/commands/URLs are
   not accepted in the host field. Use an alias for IPv6 literals or custom ports.
2. Review **Verify SSH daemon identity**: the SSH destination, remote daemon name,
   actual runtime port, expected TLS SAN identity and certificate SHA-256 pin.
   Certificate trust and the authorized daemon credential are retrieved only over
   authenticated, host-key-verified SSH as that user, without sudo. The fixed
   read-only Python probe cannot execute commands from remote metadata.
3. Check **I confirm this SSH destination and daemon certificate identity**, then
   choose **Trust and add daemon**. Cancel saves nothing. HTTPS verification and
   authenticated status must succeed before saving. SSH private keys/passwords
   are never read into or stored by AI Guardian; the daemon token is never shown.
4. The target appears as `ssh-<destination>` with cached state and the standard
   **Console**, **Violations**, **Metrics & Audit**, **Statistics**, **Terminal**,
   **Maintenance** and applicable **MCP** controls. Actions run in background workers.
   **Manage SSH connection...** returns to the picker for removal.

The owned OpenSSH process adds an explicit `127.0.0.1` local forward to the remote
loopback listener. SSH and TLS identities are verified independently: the local
TCP address/port never becomes the expected remote TLS identity. CA, SAN,
validity and the paired leaf pin are checked on the actual request connection
before HTTP headers or credentials. Readiness uses an unauthenticated health
request. Failed/occupied ports and dead/removed generations cannot select a
plaintext or unverified fallback. Only processes created for these connections
are stopped; unrelated listeners are never killed. Existing SSH configuration
is trusted local configuration; forwarding conflicts in it can prevent startup.

No public inbound REST port or VM-to-workstation inbound connection is needed.
Polling-only tray registration keeps remote permission prompts and decisions on
tray-initiated authenticated requests. This registration requires the #2552
daemon implementation; older HTTPS daemons can provide status/control but show
an explicit upgrade warning for permission prompts. Callback-only live trace
push is not available over this connection. Existing trace retrieval/catch-up
uses tray-initiated REST instead; no reverse SSH forward is created.

#### SSH menu/action parity audit

SSH targets share the normal per-daemon menu construction and ordering, rather
than a reduced transport-specific submenu. The following are intentional details
and runtime differences:

| Entry | SSH behavior and limitations |
|---|---|
| Status / Statistics | Selected VM's cached counters, pause scopes, version and connection/prompt warnings; menu rendering never starts SSH or requests REST. Offline targets do not present unavailable counters as live data. |
| Console / Violations / Metrics & Audit | Open the workstation-hosted Console at the selected saved VM's route, never a browser/server on the VM or the workstation daemon's data. REST-backed navigation is disabled while offline. |
| Pause... | Same global durations, individual sessions and all-sessions-in-directory groups. Requests stay on the selected connection; missing scope support or failed acknowledgement is reported, never broadened. |
| Terminal | A workstation terminal runs system OpenSSH to the saved destination, retaining host-key checks and alias/jump-host settings. The terminal stays open after SSH exits so login/connection errors remain readable until dismissal. No local shell/container fallback; an unavailable terminal reports failure. |
| Maintenance | The VM's daemon-scoped plugins, with bundled defaults while remote definitions are unavailable. Stop/Restart/Reload and scanner installation run as the SSH user on that VM. Bundled **View Doctor** opens its workstation Console health page; remote CLI diagnostics are also supported by the SSH transport. Nonzero exit/timeout is not reported as success. |
| MCP | Installation/enabled state and configured proactive level come from the VM, not workstation settings. If older/main daemons omit the new stats fields, the connection worker reads the existing authenticated `GET /api/config?scope=global` endpoint. Supported level changes write only that VM's global configuration through authenticated REST, which reloads it. A daemon-wide pause changes the displayed effective level, not the saved choice. Only absent/invalid capabilities show unavailable controls; installation remains VM-side setup, not workstation setup. |
| Working Dir | An optional absolute **VM** directory for Terminal and target plugin commands, entered through the shared native-first form dispatcher. No saved selection or an empty value means remote home; the workstation home is never sent as a default `cd`. Explicit VM paths display literally, not shortened against the workstation's home. This is not a workstation folder picker or a project/configuration-scope change. Cancel saves nothing. |
| Start daemon | Uses the same SSH user, interpreter and configuration/state paths as the last authenticated daemon. Available after stopping it in this tray session; it does not provision a new daemon. |
| Match Tray Version | Available under the normal version-mismatch rules when pip exists in that VM installation. Runs that installation's Python/pip and reports restart failure separately. UV/pipx-managed or externally managed installations without pip require their original installer, accessible through Terminal. A development tray version is not an installable release. Global tray self-upgrade remains a separate workstation action. |
| About | Fetches the selected VM's information; an unavailable remote response is explicitly identified, not replaced with unlabeled workstation information. |
| Manage SSH connection... | Retained in both flat and multi-daemon layouts. Removal discards saved pairing/owned tunnels, never stops the VM daemon. |
| Container/Kubernetes/OpenShell controls | Container creation, pod operations, sandbox Connect/Manage and image-rebuild hints do not apply to SSH VMs and are not copied. Version/connection warnings still apply. |

The private PID metadata now publishes the daemon's actual Python interpreter
and configuration/state directories. The fixed read-only SSH probe retrieves
that context without executing it. For existing Linux daemons from main without
these new fields, the same probe uses the same-user running daemon's procfs
arguments and executable identity to prove its interpreter. It preserves a venv
interpreter link rather than resolving it to the base Python, and reads neither
process environments nor unrelated processes. It does not execute a guessed
`ai-guardian` from PATH. Only after verified TLS and authenticated
status does the tray enable its use for explicit CLI actions; arbitrary virtualenv
paths work even when `ai-guardian` is absent from non-interactive PATH. These
paths contain no daemon token and are not substituted with workstation paths.
Context is retained **in memory** across a daemon stop/network outage, but not
across tray restart. If the tray starts while the VM daemon is stopped, or
the running installation cannot be proven (including older non-Linux daemons
without this metadata), CLI actions explain that context is unavailable. Start
the daemon through Terminal and reconnect; newer daemons publish portable PID
metadata. Updating package files alone does not replace a running process. MCP
on current main does **not** require an upgrade to this feature branch: its
existing configuration endpoint supplies the missing menu state. Do not
interpret missing MCP capability fields as proof that MCP is not installed.

Remote plugin command maps marked `run_on_target` resolve against the VM's
reported POSIX platform, not the desktop's platform. Existing bundled bare
`ai-guardian` Maintenance commands are also SSH-bound, including older bundles
without that flag. Workstation browser actions open locally without invoking a
remote shell. Other workstation-command plugins, remote global-scope plugins
and multi-target actions inside a VM-scoped menu are intentionally unavailable;
use a workstation/global plugin for local actions and explicit target execution
for VM commands. No unsupported command falls back to workstation execution.

Menu callbacks retain the displayed VM and its clicked tunnel generation across
discovery reordering/reconnection. Removal or identity change invalidates remote
commands. All network/process work runs outside menu-building and GUI callbacks.
No additional manually maintained tunnel, root installation or sudo is needed.

Permission responses stay bound to the tunnel generation that fetched them.
Prompt IDs also contain a daemon-instance nonce, so a dialog left open across a
daemon restart cannot approve a different invocation after a counter resets.

Disconnected targets stay visible **offline** and retry with bounded timeouts
and exponential backoff (2 seconds up to 60 seconds). New runtime ports can be
detected on reconnect; changed certificate trust, TLS identity or daemon tokens
are never adopted silently. Independently verify a renewal/rotation, then remove
and explicitly pair again. Restarting the tray reconnects saved destinations.
Tray/Web Console shutdown and saved-target removal clean up their owned tunnels;
another running local client observes removal on its next refresh, and every
authenticated request also checks that its saved pairing still exists unchanged.
Removing a connection never stops the remote daemon.

Pairings live under the local **state directory** at
`ssh-connections/<destination-id>.json`, separate from `ai-guardian.json` and
`tray-targets.json`. POSIX directories/files are owner-only (`0700`/`0600`) with
ownership and parent-path checks. Windows encrypts/authenticates the entire
record with current-user DPAPI; copying it to another account does not provision
trust or credentials. Temporary CA material is public certificate data, with the
immutable paired pin still enforced. SSH storage is not collected by support
bundles; do not attach pairing records to issues. Tray enrollment uses the desktop
modal flow. Web enrollment/removal is available only in a loopback-bound Web
Console, not an exposed-network Console. Tray and
Console each own their own tunnels if both query a saved target concurrently.

Custom `AI_GUARDIAN_CONFIG_DIR`, `AI_GUARDIAN_HOME`, `AI_GUARDIAN_STATE_DIR` and XDG
paths must be available in the remote SSH environment. A stopped daemon, missing
configuration, unsafe storage, unavailable metadata, a running process without a
REST listener, non-loopback listener or legacy HTTP-only daemon fails with a
distinct credential-free message; port 63152 is never assumed. This connects to
user-identified hosts only: it does not enumerate AWS instances or use AWS APIs.

#### Discover SSH aliases

Discovery is **off by default**, independent of saved SSH connections. Choose
**Discover SSH aliases...** directly in the workstation tray, next to **Add daemon
via SSH**. This settings entry is always available—even with discovery disabled,
zero matching aliases, or no enrolled daemons. **Add daemon via SSH** remains the
separate pairing action, not the discovery settings form.

1. Check or uncheck **Enable SSH alias discovery**, reflecting the current saved
   value, then choose **Continue**. This step does not save anything.
2. Edit **Optional alias prefix (empty lists all supported concrete aliases)**,
   reflecting the saved prefix, then **Save**. Use a literal prefix such as
   `guardian-`, or leave it empty to include existing supported aliases without
   renaming. Invalid prefixes show feedback and can be corrected in the same flow.

**Cancel**, Escape or title-bar **Close** before Save leaves both settings
unchanged. The complete two-step form uses the shared **Native → Tkinter →
NiceGUI** dispatcher; only pre-display startup failure permits fallback, never
cancellation or a later-step error. Configuration reads/writes and enumeration
run outside the tray GUI thread. Saving does not contact hosts, execute SSH or
grant trust; connection and identity verification remain explicit separate steps.

The **workstation loopback Web Console home `/` → SSH daemon connections** retains
the equivalent **Discover SSH aliases**, prefix and **Save SSH discovery settings**
controls above the daemon cards. The picker is not a sidebar item: from a daemon
dashboard, click **AI Guardian** in the top-left header to return home. Launch
this Console in a workstation terminal, not through the VM's SSH bootstrap
tunnel. Both entry points share workstation-global validation and persistence,
not the selected remote daemon or a project. Untouched Web Console fields follow
saved tray changes on refresh; unsaved browser edits are not overwritten. Settings
survive tray restarts. Alternatively, set the following in the local user
`ai-guardian.json`:

```json
{"daemon": {"tray": {"ssh_alias_discovery": {
  "enabled": true,
  "alias_prefix": "ai-guardian-"
}}}}
```

The case-insensitive prefix is a literal filter, not a required naming convention.
Leave it empty to list **all concrete existing aliases**, with no renaming. A
prefix such as `ai-guardian-` is useful when the same config includes unrelated
hosts. Discovery reads **`~/.ssh/config`**; the system OpenSSH client on Windows
uses **`%USERPROFILE%\.ssh\config`**. Windows' system-wide equivalent is
`%PROGRAMDATA%\ssh\ssh_config` (`/etc/ssh/ssh_config` on POSIX); system-wide files
are not enumerated. Windows alternate SSH clients/config locations are not
searched. Actual connections still delegate users, ports, keys, jump hosts and
connection predicates to the system OpenSSH client.

At tray startup and each background refresh, **SSH aliases available to pair (N)**
appears as a pending-enrollment menu only when aliases are available, separate
from saved/connected targets. With zero aliases it disappears, not a greyed `(0)`
entry; discovery warnings remain accessible as **SSH alias discovery notice**.
The **Discover SSH aliases...** settings entry remains available in either case. Each
alias offers **Review discovered daemon** and **Dismiss alias**. The loopback Web
Console picker refreshes the equivalent list automatically. Changing either the
SSH config or these discovery settings takes effect on the next refresh, without
restarting the daemon or tray. Saving from the tray requests that refresh; scanning
does not block the tray/browser UI.

**Review discovered daemon** probes only that user-chosen alias, then opens the
complete **Verify SSH daemon identity** step directly—no separate Add action or
manual host-entry form. The tray uses the shared native-first modal dispatcher;
the already-open Web Console uses its existing browser review. Both retain full
destination/port/SAN/fingerprint details and explicit, initially unchecked consent.
Cancel saves nothing. Finding a name alone does **not** establish that AI Guardian
is installed or running there. No background probes are performed, no SSH command
or predicate is executed during enumeration, no key contents are read, no SSH
config is modified, and no cloud inventory is queried.

Only confirmed, SSH-verified, HTTPS-verified **and authenticated** enrollment saves
a pairing. Existing dynamic-port tunnels, backoff, restart recovery and polling-only
tray registration then apply unchanged. Refreshes do not open trust dialogs,
replace saved credentials/certificates, or create candidate connection workers.
Offline hosts, absent SSH clients and unconfigured/stopped daemons report the
existing credential-free errors only when reviewed; other candidates remain usable.

**Parser limits and conditional configuration:**

- Only declared concrete `Host` names are listed. Comments, quoted names,
  `Host=...`, multiple names and case-insensitive duplicates are handled. Wildcard
  and negated patterns are never expanded into destinations. Host names must fit
  the existing safe SSH destination syntax; unsupported names remain available
  through independently configured supported aliases.
- Unconditional `Include` directives support regular **`config` or `*.conf` files
  below the user's `.ssh` directory**, including literal subdirectories and
  basename globs such as `Include config.d/*.conf`. Relative paths are relative
  to `.ssh`, not the including file. Put this directive **before the first `Host`
  or `Match`** and use `.conf` filenames for fragments. Included text shares scope;
  an included `Host`/`Match` can make later Include directives conditional too.
- Includes inside `Host` or `Match` scopes are skipped. Match conditions (including
  `exec`, `localnetwork`, `canonical` and `final`) are never evaluated. A later
  explicit `Host` declaration starts a new host scope and can be listed; it is
  not proof that its effective settings will work. This is an alias inventory,
  not an OpenSSH configuration evaluator.
- Include cycles, links, external paths, parent traversal, recursive/directory
  globs, environment/percent expansion and key-file paths are unsupported and
  skipped. Limits: 8 nested file levels including the root, 64 files and Include
  patterns, 256 aliases, 256 KiB per file / 1 MiB total, and 4,096 directory entries
  per basename glob. Incomplete/unsupported scans show a credential-free notice;
  valid partial results remain available. Use a small dedicated Include file or
  explicit **Add daemon via SSH** for unsupported constructs.

Dismissal persists across refreshes/restarts as a private, hostname-digest marker
in the existing SSH state directory; it never edits SSH configuration or trust.
**Removing a saved connection also dismisses its alias**, so discovery cannot
recreate it or repeatedly offer enrollment. Changing/removing the SSH config never
deletes saved pairings. Dismissed aliases can still be paired deliberately through
**Add daemon via SSH**; there is no automatic reset of dismissal state. Turning
discovery off hides candidates but leaves saved connections/tunnels unchanged.
Removal closes only client-owned tunnels and never stops the remote daemon.

#### POSIX storage preconditions

Setup (including JSON mode) and startup create missing application directories
and their missing parents with explicit `0700` permissions. Generated configuration
and authentication tokens use `0600` files from creation, including temporary
files. An ordinary group-writable umask such as `0002` cannot make newly created
storage fail its own credential checks. Setup publishes configuration atomically;
without an explicit overwrite request it preserves an intervening creator's file.

Existing directories are **not** silently chmodded. Credential storage rejects
untrusted ownership, linked application directories/files, and group/other-writable
ancestors (with the existing exception for trusted sticky system temporary
ancestors). A secure application leaf is insufficient if, for example, `.local`
or `.local/state` remains `0775`. Setup reports the offending path and precondition
without writing configuration. Review existing storage with its administrator;
do not assume running setup repairs shared directories. Missing configuration is
an independent setup problem, not proof of a permission failure.

`ai-guardian daemon status` distinguishes **IPC: running** from **REST API:
available**, **unavailable**, or **disabled**. An unavailable listener includes its
credential-free startup reason, including the offending storage path/mode when
known. PID metadata and IPC status expose additive `rest_status` and `rest_error`
fields; legacy daemons lacking readiness information are shown as unknown rather
than presumed healthy. IPC can continue serving hooks when REST startup fails;
this does not mean tray/HTTPS enrollment is ready. SSH pairing separately reports
missing configuration, unsafe metadata, and a live process without REST. It does
not echo remote exception text, tokens, certificates, or key contents.

These mode checks apply to POSIX. Windows retains administrator-managed ACLs;
POSIX unit tests do not qualify Windows access control.

Unit/UX tests exercise synthetic TLS endpoints and mocked SSH processes. Live
private-VM enrollment, reconnect/prompt delivery and native Windows/macOS desktop
qualification remain a release/manual-validation gate, not a claim established
by those tests. See the manual checklist in
`tests/ux/test_user_experience_contract_ssh_daemons.py`.

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

### Native HTTPS and explicit certificate trust

Native HTTPS is opt-in (`daemon.rest_tls`, targeting 1.21; not in PyPI 1.20.0).
For a fresh headless guest, use the [Ubuntu VM HTTPS/SSH guide](UBUNTU_VM.md);
it explicitly separates the upcoming release from published-PyPI qualification.
The advanced trust/PKI reference below remains applicable to supporting builds.
Existing localhost HTTP configurations need no changes. TLS does **not** change
`rest_host`, publish
ports, open a firewall, enable mTLS, or replace the daemon's bearer token. Container
bind-address defaults also remain unchanged. Set an explicit loopback bind address
when the daemon must only be reachable through an administrative tunnel.

#### Test HTTPS on your own PC

**Prerequisites:** Linux, OpenSSL **3.x** (`openssl version`), `curl`, and an
AI Guardian build with native daemon TLS (1.21 or newer). Your local daemon and
Web Console should already be running. This test needs no second machine, public
DNS, firewall changes or system-wide certificate installation.

This enables HTTPS for the **daemon REST API**, normally
`https://127.0.0.1:63152`. It does **not** enable HTTPS for the Web Console
webpage; keep using the Console's existing browser URL. Keep the REST listener
bound to `127.0.0.1` (`daemon.rest_host`); enabling HTTPS does not change its bind
address. For remote or production setups, use the
[private-VM/private-CA guidance](#private-vm-provisioning-and-pairing-no-public-inbound-rest)
below instead.

Run the following commands yourself in a **normal terminal**, not through an AI
agent. Keep that terminal open for step 4, which uses the same `TLS_DIR` variable.
No scanning or protection settings need to change.

##### 1. Generate a local test certificate

Create a fresh private directory so existing certificates and keys are not
overwritten:

```bash
umask 077
mkdir -p "$HOME/.config/ai-guardian"
TLS_DIR=$(mktemp -d "$HOME/.config/ai-guardian/tls-local.XXXXXX")

openssl req -x509 -newkey rsa:3072 -noenc -sha256 -days 90 \
  -keyout "$TLS_DIR/server-key.pem" \
  -out "$TLS_DIR/server-cert.pem" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" \
  -addext "subjectKeyIdentifier=hash" \
  -addext "authorityKeyIdentifier=keyid:always"

printf 'Certificate directory: %s\n' "$TLS_DIR"
```

The new directory is owner-only (`0700`), and `umask 077` makes the new key and
certificate files owner-only (`0600`). Existing parent-directory permissions are
not changed. The unattended daemon needs an **unencrypted** private key, so keep
it private and never paste its contents into the Console or chat. The certificate
expires after **90 days**; it contains both the `localhost` DNS SAN and the
`127.0.0.1` IP SAN, not just a Common Name.

##### 2. Fill in the Web Console fields

Select the **local daemon**, use **Global** scope, then open
**Global Settings → Daemon REST HTTPS**. For example, if the command printed
`/home/alex/.config/ai-guardian/tls-local.A1b2C3`, enter:

| Field | Value |
|-------|-------|
| Enable native HTTPS | On |
| Certificate chain PEM path (on daemon host) | `/home/alex/.config/ai-guardian/tls-local.A1b2C3/server-cert.pem` |
| Private-key PEM path (on daemon host) | `/home/alex/.config/ai-guardian/tls-local.A1b2C3/server-key.pem` |
| Trusted CA PEM path (empty: system trust) | `/home/alex/.config/ai-guardian/tls-local.A1b2C3/server-cert.pem` |
| Expected server SAN identity / SNI | `localhost` |
| Optional independently verified SHA-256 leaf pin | Leave empty for this initial local test |

Replace the example directory with **your exact printed directory**, including
your username and random suffix. Use full absolute paths, not the literal
`$TLS_DIR` variable or file contents; these fields do not expand shell variables.

The **Trusted CA PEM path** explicitly trusts the self-signed public certificate
you just generated. This is sufficient for this local test; no separate CA or
system trust-store installation is needed. Do not leave this field empty for the
self-signed recipe or trust an arbitrary discovered certificate. Certificate
validity and identity verification remain mandatory. Local REST clients verify
`localhost` even when connecting to `127.0.0.1`.

##### 3. Save and restart

Click **Save HTTPS settings**, then run in your terminal:

```bash
ai-guardian daemon restart
```

Reload alone does **not** replace the live listener or certificate. After the
restart, refresh the Console and tray so they pick up the HTTPS listener and
saved trust. The Console webpage itself keeps its existing URL/scheme.

##### 4. Verify HTTPS and expected results

In the **same terminal** as step 1:

```bash
curl --noproxy '*' --fail --show-error \
  --cacert "$TLS_DIR/server-cert.pem" \
  https://127.0.0.1:63152/api/health
```

Expected: JSON containing `"status": "ok"`. `curl` explicitly trusts your public
certificate and verifies the URL's `127.0.0.1` IP SAN. In a new terminal, replace
`$TLS_DIR/server-cert.pem` with the full printed certificate path, in quotes.
If your REST port differs, replace `63152` in these URLs with the actual port
(including the assigned port if configured as `0`).

Also check that authentication is still required:

```bash
curl --noproxy '*' --show-error \
  --cacert "$TLS_DIR/server-cert.pem" \
  --output /dev/null --write-out 'HTTP %{http_code}\n' \
  https://127.0.0.1:63152/api/status
```

Expected: **HTTP 401** without daemon-token authentication. HTTPS does not
replace that authentication. `/api/health` checks transport/connectivity only;
success does not establish authenticated SDK/tray integration.

- Without `--cacert`, this freshly generated, untrusted self-signed certificate
  should fail certificate verification.
- Plain `http://127.0.0.1:63152/api/health` should no longer succeed on this TLS
  listener; a reset/closed connection rather than JSON is expected.

If something fails:

| Symptom | What to check |
|---------|---------------|
| Self-signed certificate / unknown CA | Use the generated `server-cert.pem` for both the Console's trusted CA field and `curl --cacert`. Keep certificate verification enabled. |
| Server identity / SAN mismatch | The Console identity is `localhost`; the `curl` URL uses `127.0.0.1`. The certificate must contain both SANs as generated above. |
| Missing file, permission error, or unavailable REST listener | Check full paths on the daemon host and access by its user. The key must be owner-only; certificates/trust files and their parent directories must not be writable by other users. Review unsafe existing parents rather than making them broadly writable. Invalid TLS material prevents REST startup, not a fallback to HTTP. |
| Expired or not-yet-valid certificate | Check the system clock. Generate replacement material before the 90-day expiry, update the paths, restart, then refresh the Console/tray. Startup warns within 30 days of expiry. |

See [validation, renewal and restart](#validation-failures-renewal-and-restart)
for more detail.

#### Listener and client configuration

```json
{
  "daemon": {
    "rest_host": "127.0.0.1",
    "rest_port": 63152,
    "rest_tls": {
      "enabled": true,
      "cert_file": "/private/guardian/server-chain.pem",
      "key_file": "/private/guardian/server-key.pem",
      "client": {
        "ca_file": "/private/guardian/trusted-ca.pem",
        "server_name": "daemon.vm.internal",
        "certificate_sha256": ""
      }
    }
  }
}
```

The certificate file starts with the server leaf, followed by intermediates. The
key must be an unencrypted matching PEM key: unattended startup never prompts for
a password. Use a certificate with an appropriate DNS/IP **subject alternative
name** (SAN) and server-auth usage; a Common Name alone is not sufficient.
`client` configures local REST callers (SDK project registration, ask requests,
trace submission and Console health checks), not the server's client-auth policy.
These callers connect to loopback but verify `server_name`, not `127.0.0.1`.
For public/enterprise CA certificates, an empty `ca_file` uses system trust.

Manual remote targets have their own explicitly provisioned trust:

```json
{
  "daemons": [{
    "name": "private-vm",
    "url": "https://127.0.0.1:64443",
    "token": "provision-the-existing-daemon-token-privately",
    "tls": {
      "ca_file": "/private/trusted-vm-ca.pem",
      "server_name": "daemon.vm.internal",
      "certificate_sha256": ""
    }
  }]
}
```

The URL is the TCP connection address; `server_name` supplies both SNI and the
expected certificate identity. SSH-managed connections reuse this transport without
requiring a localhost certificate. The same target can use a direct HTTPS address
with the same trusted identity. Empty `server_name` verifies the URL hostname/IP.
The optional `certificate_sha256` is the independently verified SHA-256 **leaf
certificate** fingerprint (64 hex digits, with optional colons). It is an extra
constraint: CA trust, validity, hostname and server-auth verification still apply.
Discovery cannot approve trust, enroll certificates or replace an existing pin.

#### Private VM provisioning and pairing (no public inbound REST)

Use an existing organizational PKI where available. Otherwise, issue a server
certificate from a private CA maintained by the administrator. Example OpenSSL
commands, run by the operator, not an agent:

1. On the VM, create a private directory and a server key/CSR. The identity need
   not resolve in public DNS:
   ```bash
   umask 077
   mkdir -p "$HOME/.config/ai-guardian/tls"
   cd "$HOME/.config/ai-guardian/tls"
   openssl req -new -newkey rsa:3072 -noenc -keyout server-key.pem -out server.csr -subj /CN=daemon.vm.internal
   ```
2. Send the CSR over an independently authenticated administrative channel to
   the private-CA administrator. Keep the CA private key off the VM and clients.
   On the administrator's offline workstation, if no CA exists:
   ```bash
   umask 077
   openssl req -x509 -newkey rsa:3072 -noenc -keyout ca-key.pem -out ca.pem -days 365 -subj /CN=Guardian-private-CA -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign
   ```
   Create `server.ext` containing:
   ```ini
   basicConstraints=critical,CA:FALSE
   keyUsage=critical,digitalSignature,keyEncipherment
   extendedKeyUsage=serverAuth
   subjectAltName=DNS:daemon.vm.internal
   subjectKeyIdentifier=hash
   authorityKeyIdentifier=keyid,issuer
   ```
   Issue the certificate and return only the server certificate and public CA:
   ```bash
   openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out server-chain.pem -days 90 -sha256 -extfile server.ext
   ```
3. **Before saving trust**, compare the CA's SHA-256 fingerprint using a trusted
   console or SSH session with an already independently verified SSH host key,
   not an unauthenticated REST connection or discovery result:
   ```bash
   openssl x509 -in ca.pem -noout -fingerprint -sha256
   openssl x509 -in server-chain.pem -noout -fingerprint -sha256
   ```
   Provision the verified CA on the VM (for local REST callers) and tray/client
   host. Optionally record the separately verified server fingerprint as the
   additional leaf pin. An independently verified self-signed server certificate
   can instead be the dedicated `ca_file`; never trust one just because it was
   discovered. Copy no private keys to clients.
4. Configure the VM as above with its own absolute paths, explicit loopback
   `rest_host`, and matching local `client` trust. Keep private keys and the
   token-bearing `tray-targets.json` owner-only (`0600`, private parent directory
   on POSIX). Trust/certificate files must not be writable by other users; runtime
   checks reject unsafe POSIX file ownership/modes. On Windows, administrators
   must restrict file and parent-directory ACLs to the owning account (and needed
   system administrators); POSIX mode checks are not an ACL validator.
5. Restart the daemon through the ordinary operator workflow. No public inbound
   REST port is necessary. For a manual connectivity check, the operator may use
   an already verified SSH connection:
   ```bash
   ssh -N -L 127.0.0.1:64443:127.0.0.1:63152 vm
   ```
   Provision the existing daemon token privately and configure the manual target
   above. Refresh/restart the tray to reload manual target trust. Alternatively,
   use [Add daemon via SSH](#add-daemon-via-ssh) to enroll and manage the tunnel.
   SSH key provisioning/management remains outside AI Guardian.

#### Validation failures, renewal and restart

TLS 1.2 or newer and certificate verification are mandatory. Verification and any
pin comparison complete on the actual request connection **before** HTTP headers,
tokens or request bodies are transmitted. Daemon REST requests ignore environment
proxies and refuse redirects (including HTTPS-to-HTTP), so credentials are not
forwarded to another destination. HTTPS failures never retry over HTTP.

Invalid, missing, expired, not-yet-valid or mismatched server material prevents
REST startup; it never creates a plaintext listener. The local IPC daemon can
remain available, but REST-dependent features report an unavailable listener.
Startup warns for a leaf expiring within 30 days. Validity is checked at startup;
clients revalidate the live certificate on every new request, including after it
expires. Errors distinguish CA validation, identity/validity and changed-pin
failures, without including tokens, key contents or raw crypto/parser errors.

Certificate files are loaded at startup. Config reload does **not** change the
live listener, certificate or transport; explicit daemon restart is required.
Renew ahead of expiry, install the matching certificate/key securely, and restart.
For CA rotation, independently verify the replacement CA before updating trust;
an overlap bundle can ease planned rotation. If pinning, independently verify the
new leaf fingerprint and explicitly update each saved pin, then refresh the tray.
Changed pins fail closed; no observed certificate can silently replace them.
Replacing files without restart leaves the original certificate in service.

Hook/SDK remote-daemon clients use `AI_GUARDIAN_DAEMON_URL` and the existing
`AI_GUARDIAN_AUTH_TOKEN`, plus optional `AI_GUARDIAN_DAEMON_CA_FILE`,
`AI_GUARDIAN_DAEMON_SERVER_NAME` and `AI_GUARDIAN_DAEMON_CERT_SHA256`. Remote trace
submission uses the same three trust variables with its existing trace endpoint
and token variables. Trust options on an HTTP URL are rejected. Prefer the token
environment variable over embedding a token in the legacy daemon URL; do not
paste tokens or private keys into logs, support diagnostics or chat.

## REST API

Each daemon exposes a REST API for tray communication:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/status` | GET | Daemon status (name, version, paused, middleware_pause, menu_tags, config_source, config_read_only) |
| `/api/stats` | GET | Full stats, including active stable-ID hook sessions (`active_sessions`), remote MCP installation/enabled state and configured proactive level (`mcp_installed`, `mcp_enabled`, `mcp_proactive_level`) |
| `/api/middleware/status` | GET | Effective daemon pause for OpenShell middleware; accepts optional `project_dir` |
| `/api/pause` | POST | Pause scanning (`{"minutes": 15}`) |
| `/api/resume` | POST | Resume scanning |
| `/api/pause_session` | POST | Pause an active stable-ID hook session (`{"session_key": "...", "minutes": 15}`) |
| `/api/resume_session` | POST | Resume an active stable-ID hook session (`{"session_key": "..."}`) |
| `/api/pause_dir` | POST | Pause all hook sessions in a project directory (`{"dir": "...", "minutes": 15}`) |
| `/api/resume_dir` | POST | Resume all hook sessions in a project directory (`{"dir": "..."}`) |

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
        "label_selector": "app=ai-guardian",
        "ownership": {
          "label": "ai-guardian.owner",
          "value": "my-user"
        }
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

| Action | Local | Container | Kubernetes | SSH VM |
|--------|-------|-----------|------------|--------|
| Statistics | Unix socket | REST API | REST API | Background-polled HTTPS cache |
| Console | Workstation Console | Workstation Console | Workstation Console | Workstation Console scoped to VM |
| Terminal | Local shell | `podman exec -it` | `kubectl exec -it` | Saved OpenSSH destination |
| Pause/Resume | Unix socket | REST API | REST API | Authenticated managed HTTPS tunnel |
| Start/Stop/Restart | Subprocess | `podman exec` | `kubectl exec` | SSH user's actual installation/context |

> **In-progress guard**: Local/container restart actions retain their existing
> double-click guard and status polling. SSH CLI actions report their actual exit
> status; the connection worker independently discovers daemon stop/start and
> reconnects with backoff, without reading the workstation PID file.

## CLI Reference

```bash
ai-guardian tray start              # Start tray (foreground)
ai-guardian tray start -b           # Start tray (background)
ai-guardian tray start --no-discover  # Manual targets only
ai-guardian tray stop               # Stop running tray
ai-guardian tray restart            # Restart tray

# Global controls without a tray (no selector means global)
ai-guardian pause 15
ai-guardian pause                   # Indefinite global pause
ai-guardian resume

# List active stable-ID hook sessions and copy a session_key
ai-guardian daemon status
ai-guardian pause 15 --session '<session-key>'
ai-guardian pause --session '<session-key>'  # Until resume or session end
ai-guardian resume --session '<session-key>'

# All sessions using the normalized project directory
ai-guardian pause 15 --dir /path/to/project
ai-guardian pause --dir /path/to/project     # Indefinite directory pause
ai-guardian resume --dir /path/to/project
```

Syntax: `pause [MINUTES] [--dir DIRECTORY | --session SESSION_KEY]` and
`resume [--dir DIRECTORY | --session SESSION_KEY]`. Selectors are mutually
exclusive and require non-empty values. Integer durations range from 0 through
1440 minutes; 0 or omission means indefinite within that scope's existing
lifetime. The nested `daemon pause --minutes MINUTES` and `daemon resume` forms
remain supported with the same scope selectors.

Session-scoped controls require a currently active stable hook identity. Use
the full `session_key` from status, not a display title, raw session ID, directory,
or an inferred current session. Unknown/expired keys and unsupported session
requests fail with non-zero status and never fall back to broader control.
Session pauses clear on timed expiry, resume, SessionEnd, 24 hours of inactivity,
or daemon restart. Integrations without stable identities are covered only by
global or directory-wide pauses.

Resume clears only the selected scope's pause; other pause layers still apply.
All forms reuse the existing configured daemon and do not auto-start a daemon
or tray or change pause state offline. A stopped/unreachable daemon is an error.
They remain human-operated CLI controls protected against execution by AI
sessions; there is no mutating MCP pause/resume tool. Multi-daemon selection
continues to use the tray's existing target routing, not a new CLI selector.

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

### Linux pause/resume menu stability

On Linux, the tray intentionally does not rebuild the native menu every second
while a daemon is paused. GTK/AppIndicator replaces the menu during an update,
which can collapse an open nested submenu in KDE before **Resume** can be
selected. Linux pause labels therefore use a stable paused indicator instead of
a live countdown; pause/resume visibility still refreshes when the pause state
changes. macOS keeps the live countdown refresh behavior.

AppIndicator popup replacement is deferred until the popup closes and a short
click-delivery grace period elapses, then renders fresh daemon stats. KDE sends
the popup's close event before the selected item's click; rebuilding immediately
can discard that action, including Pause/Resume or About. Rapid reopening keeps
the new popup protected from an older close callback.
Scoped actions and idle polling refresh actual pause/resume
transitions, expiry, session end, and session/project-list changes; countdown-only
changes do not replace Linux menus. Windows and macOS retain countdown updates.

### Session and directory pause controls

**Sessions...** lists active hook sessions that have a stable identity from their
agent adapter. Entries prefer a human-readable session title, for example
`OpenCode: Fix tray labels`, and fall back to the session ID, then the stable
session key when no usable title is known (including older daemons). Titles are
compact, single-line, display-safe text capped at 80 characters. Identical labels
receive an eight-character stable-key fingerprint so they remain distinguishable.
Windows menu text escapes literal ampersands so titles such as `Fix A&B` retain
the `&` instead of turning it into a keyboard mnemonic. Stored titles and other
platforms' menu text are unchanged.
The submenu retains the full session key and project directory; controls always
target that key, never the title. This works for local, remote, and container
daemons, so two sessions in the same directory can be paused independently.

Titles reported by later hook activity update existing entries without changing
identity or pause state. Missing, blank, or invalid title metadata does not erase
a previously known title. OpenCode V2 reads native metadata for the exact session
through its plugin API, with a 500 ms lookup deadline and a 30-second cache
(including misses; at most 128 entries). Other integrations use supplied hook
name/title metadata; unknown titles keep the ID fallback. No transcript or
conversation-wide discovery is performed for tray labels.

Session pause
durations are 5, 15, or 30 minutes, 1 hour, or until resumed/session end. Timed
pauses expire automatically; every session pause is cleared on a SessionEnd
event, after 24 hours without hook activity, or when the daemon restarts. Session
pauses are intentionally not persisted across restarts.

The **All sessions in directory...** submenu is the explicit bulk control. It
combines explicitly paused directories with `active_project_dirs`, which records
recently observed project directories rather than currently open IDE sessions.
Directory entries remain until the project tracking TTL expires (currently 24
hours without another request), including while global scanning is paused.

In both single- and multi-daemon layouts, a confirmed session or directory pause
shows **☾** and a selectable **Resume** on the next menu opening, even immediately
within the stats-cache window. Resume restores **●** and the duration choices.
Headers, Status, and scoped controls share the same stats snapshot; no additional
hook request, unrelated menu interaction, or tray restart is needed.

| Indicator | Meaning |
|-----------|---------|
| **● Daemon (global)** | No global pause; session/directory pauses may still apply |
| **☾ Daemon (global)** | Scanning is paused globally |
| **● / ☾** on a session or directory | That scope's own pause is absent / present |
| **◐** on a daemon header | Daemon is not globally paused, but at least one session or directory is paused |

Resuming a session does not clear a directory or global pause. Resuming a
directory does not clear individual session or global pauses. Thus a scoped
**●** is not a promise that effective scanning has resumed; each submenu explains
that other pause layers may still apply. Directory controls remain the bulk
control for all callers in that project, including those without stable IDs.

Scoped requests require an explicit daemon acknowledgement. An unreachable,
unsupported, or ended scope produces a failure notification without claiming
success or falling back to a broader scope. Older daemons without session support
show that limitation while retaining their directory/global controls.

Session controls are offered only for hooks that provide a stable session ID;
the daemon never guesses an identity from a project directory. Integrations,
MCP callers, and provider middleware requests without a stable hook identity
cannot be isolated by session. Use the global control or **All sessions in
directory...** for those callers. `GET /api/stats` reports `active_sessions` with
the daemon-issued `session_key` for CLI/API control. The tray pre-allocates 16
session entries; additional sessions are listed by `ai-guardian daemon status`.

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
| Linux KDE/GNOME | tkinter / NiceGUI per `preferred_ui` config |
| macOS < 14 | tkinter / NiceGUI per `preferred_ui` config |

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
