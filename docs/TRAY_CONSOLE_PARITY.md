# Tray-to-Console Parity Matrix

**Status:** Reviewed prerequisite for [#2834](https://github.com/RedHatProductSecurity/ai-guardian/issues/2834)  
**Scope:** Current native tray menu actions and the boundary for Console and future broker work.  
**Source inventory:** `src/ai_guardian/tray/app.py`, `tray/menu_builder.py`, `tray/plugins.py`, and `tray/ssh_connections.py`.

This matrix is an action boundary, not a proposal for a generic HTTP command
endpoint. Every Console action must name one selected daemon target before it
is enabled. A broker, if introduced, must authorize both the operation and the
exact target through the shared daemon-target service.

## Decision Labels

| Label | Meaning |
| --- | --- |
| **Console parity** | Already available in the Web Console for the selected daemon or workstation Console. |
| **Console-native daemon action** | Safe to expose in the Console after an explicit target and capability check; it needs a daemon API or shared target-service operation. |
| **Tray/host only** | Depends on the workstation desktop, local process, local filesystem, terminal, browser launch, or user SSH configuration. |
| **Separate capability** | Requires a separately designed runtime, broker, host, or policy capability and is not implied by Console parity. |

## Matrix

| Tray action (including submenu variants) | Targets | Classification and Console state | Required capability/API boundary | Destructive impact | Offline / older-daemon behavior |
| --- | --- | --- | --- | --- | --- |
| Status, symbol legend, version/stale-code warning | Local, container, Kubernetes, SSH, manual | **Console parity** for daemon status; stale-code remediation is **separate capability** | Read-only selected-target status/version/capabilities; no action from status text | None; restart/rebuild is a separate action | Show cached state with an explicit offline/unknown marker. Missing additive fields must remain unknown, never inferred healthy. |
| Console, Violations, Metrics & Audit | Any selected daemon target | **Console parity**; existing tray routes to the workstation Console and selected daemon | Console route must carry the selected daemon identity; broker may proxy approved Console routes only | None by navigation | Disabled when target is unavailable. SSH opens the workstation Console, never a remote browser or an unselected local daemon. |
| Statistics submenu (requests, blocked, warned, logged, violation severity, last block, ask dialogs, config reload) | Any selected daemon | **Console parity** through dashboard/metrics; read-only tray summary | Authenticated stats/metrics endpoint scoped to target | None | Use last known snapshot with age/unknown indication. Older responses may omit newer counters; default display values only where the field contract defines them. |
| Pause/resume controls (daemon, project directory, session scope and duration) | Local and remote daemon targets | **Console-native daemon action**; Console already exposes daemon pause controls and must retain scope selection | Explicit pause/resume API with target, scope, duration, and acknowledgement; no broadening when a scope is unsupported | Security availability is reduced temporarily; requires explicit user action | Keep per-scope rows and report failed/missing acknowledgements. Do not silently convert a scoped pause into a daemon-wide pause. |
| MCP proactive level: `low`, `medium`, `high`, `paused` | Daemon target with MCP installed/enabled | **Console-native daemon action** | Target-scoped global configuration write plus reload; installation/setup is not this action | Changes advisory-check behavior; `paused` does not rewrite the saved level when it represents a temporary daemon pause | Missing capability fields are unavailable, not proof MCP is absent. Older daemons may fall back to authenticated global config read. |
| Working directory selector | Local daemon or SSH VM | **Tray/host only**; not a Console configuration-scope action | Local desktop folder picker, or validated absolute VM path for SSH terminal/plugin commands | Changes the tray's command working directory only | Persisted selection is local tray state. Never send workstation home as a VM default; empty SSH value means remote home. |
| Start, stop, restart daemon; local stale-code restart | Local daemon; SSH start/restart where explicitly supported | **Console-native daemon action** only where the daemon/runtime adapter owns lifecycle; local stale-code restart is **tray/host only** | Target-service lifecycle operation with runtime-specific authorization and readiness polling | Stops/restarts protection and may interrupt active sessions | Show transitional state and poll readiness. SSH uses the enrolled VM interpreter/context; unavailable context is an explicit failure. No local fallback for a remote target. |
| Match Tray Version / daemon upgrade | Local or SSH daemon installation; global tray self-upgrade | Daemon upgrade is **separate capability**; tray self-upgrade is **tray/host only** | Runtime/package-manager adapter bound to selected installation; never generic command execution | Replaces installed software and restarts/reloads it | Version mismatch remains visible. If pip/installer context is unavailable, direct the user to the host's supported maintenance path; do not claim success. |
| About (global tray, selected daemon About) | Workstation or selected daemon | Global tray About is **tray/host only**; daemon About is **Console parity** read-only | Selected-target About/status API for remote targets | None | Remote failure must be labeled unavailable, not replaced with workstation information. |
| Maintenance plugins: Doctor, reload, scanner install, daemon/plugin actions | Local, container, Kubernetes, SSH according to plugin/runtime | Doctor/config views are **Console parity**; daemon maintenance is **Console-native daemon action** only through explicit allowlisted operations | Named daemon API or shared service operation per plugin; no arbitrary shell/CLI surface | Scanner installation and reload can change protection/runtime; require confirmation where applicable | Preserve runtime-specific behavior. SSH commands run as the enrolled SSH user; nonzero exit/timeout is failure. Older daemons expose only operations they advertise. |
| User/bundled tray plugins and global plugins | Workstation or explicitly selected target | **Separate capability**; not Console parity by default | Plugin manifest must declare scope and an allowlisted operation. Broker must not execute arbitrary shell, CLI, or terminal commands. | Plugin-defined; destructive operations require their own confirmation and policy | Hide or disable unsupported scopes. Never fall back from a target plugin to workstation execution. |
| Terminal; sandbox Connect; sandbox Exec; sandbox Logs with follow | Workstation terminal, container/OpenShell sandbox target | **Tray/host only** for terminal and interactive Connect/Exec/follow; sandbox read-only status/log output may become a **Console-native daemon/runtime action** | Host terminal/browser process or separately designed sandbox API; command text is never a generic Console endpoint | Exec and interactive shell are arbitrary command execution and excluded from broker/Console scope | Offline targets cannot launch a local substitute. Report missing runtime/terminal explicitly. |
| Sandbox create, start, stop, restart, delete, config save/list/restore, status, logs, OpenShell policy, middleware readiness | Local container/OpenShell runtime targets | **Separate capability**; no current Console parity | Explicit container/OpenShell host adapter with target identity, runtime capability, and confirmation for delete/policy changes | Create/delete, lifecycle, config restore, and policy changes are destructive or security-sensitive | Runtime discovery may be stale; refresh after successful operation. Never represent a host runtime command as a daemon REST command. |
| SSH: Add daemon, Discover aliases, Review candidate, Dismiss alias, Reconnect tunnel, Manage connection | Workstation SSH configuration and enrolled SSH daemon | **Tray/host only** for enrollment/discovery/connection management; Console has equivalent loopback-only pairing controls but not remote-host generic management | Host-key verification, SSH-owned tunnel, daemon TLS identity/pin, explicit user approval; Console enrollment remains loopback-bound | Pairing/removal changes local trust and owned tunnel state; removal never stops remote daemon | Candidate discovery never implies trust. Offline saved targets remain visible; reconnect retries without replacing trust. Older daemons show explicit capability/upgrade warnings. |
| IDE/CLI Setup: health check, per-IDE setup, Cursor Cloud project setup, Create Config | Workstation IDEs, CLIs, project files | **Tray/host only**; Console may show read-only setup state but must not perform host setup remotely | Local filesystem/CLI/IDE integration and project selection; no daemon-target routing | Writes hooks, MCP registration, config, or project files | Disabled when integration is not detected. No remote/broker execution; preserve existing consent and platform checks. |
| Contact supports (global local tray host or selected daemon) | Workstation; selected daemon diagnostics | Support flow is **tray/host only** and user-consent-only; not a remote action surface | Local sanitized bundle preparation, selected target diagnostics, native review, explicit send/publication consent | May disclose reviewed diagnostics; public delivery requires separate native approval | Global support remains available without a daemon. Remote diagnostics are never collected implicitly; prepared content remains local until consent. |
| Restart tray, Quit | Workstation tray process | **Tray/host only** | Local process lifecycle | Stops the tray UI; does not stop daemon protection | No Console or broker equivalent. Daemons and hooks must remain independent. |

## Remote Eligibility Rules

The following actions are eligible for a target-scoped Console implementation,
subject to explicit capability checks: status/statistics, Console navigation,
violations/metrics/audit views, scoped pause/resume, MCP proactive-level writes,
daemon-scoped About, and named daemon maintenance operations. Daemon lifecycle
operations may be enabled only when the runtime adapter owns that lifecycle.

The following remain workstation-only or require a separately specified host
capability: terminal and arbitrary exec, IDE/CLI setup, tray lifecycle, SSH
enrollment and tunnel management, folder/project pickers, support publication,
container/OpenShell host operations, arbitrary plugins, and package upgrades.

No action in this document authorizes a generic `command`, `shell`, or
catch-all REST endpoint. A future broker must enforce the same classifications,
target binding, capability advertisement, confirmation requirements, and
offline/legacy behavior.

## Required Follow-up for #2834

1. Define the target-scoped operation names and response/capability contracts
   for the Console-native rows.
2. Keep broker/host operations separate from daemon REST routes; document the
   adapter and authorization boundary before implementing remote actions.
3. Add negative tests for wrong-target routing, missing capabilities, offline
   targets, older daemon fields, arbitrary command/plugin execution, and
   workstation-only actions presented as remote actions.

See [Multi-Daemon Tray](MULTI_DAEMON_TRAY.md) for current runtime behavior and
[Remote Broker Architecture](REMOTE_BROKER_ARCHITECTURE.md) for the proposed
broker trust and routing boundaries.
