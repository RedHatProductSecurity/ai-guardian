# AI Guardian Console Guide

The AI Guardian Console is a browser-based administration UI powered by
[NiceGUI](https://nicegui.io/). It manages security configuration, daemon
status, violations, scans, and multi-daemon deployments.

## Security Model

The Console is intended for deliberate, user-visible configuration changes.
Saving a setting requires an explicit action in the browser. AI Guardian does
not expose a terminal UI fallback.

## Upgrading from 1.19.x

AI Guardian 1.20.0 requires Python 3.10 or newer; `1.19.x` is the last
Python 3.9-compatible line. Upgrade Python first, or retain that line with
`ai-guardian<1.20`.

The Textual terminal console has been removed. Run `ai-guardian console` to
open the NiceGUI browser console; `ai-guardian tui` remains an alias for the
same browser UI, not a terminal fallback. NiceGUI is installed as a core
dependency. Existing persisted `textual` dialog preferences are interpreted as
`nicegui`, so no configuration rewrite is required for that migration. Review
the [requirements](#requirements) and [browser troubleshooting](#troubleshooting)
before upgrading a browserless environment.

## Requirements

- Python 3.10 or newer
- NiceGUI, installed as a core AI Guardian dependency
- A browser on the local machine, or access to the configured host and port

Tkinter is optional and provides native dialogs for ask-mode prompts. When
Tkinter is unavailable or disabled, dialogs use NiceGUI in the browser. In
headless mode, ask actions use their configured fallback behavior.

## Starting the Console

```bash
# Auto-assign a free port and open the browser
ai-guardian console

# The explicit web flag is retained for compatibility
ai-guardian console --web

# Use a specific port
ai-guardian console --web --port 8080
```

The console binds to `127.0.0.1` by default. Keep the host restricted to a
trusted interface unless access control and network isolation are configured.

The historical `ai-guardian tui` command remains as an alias for
`ai-guardian console`; it now opens the browser console.

## Pages

- **Security Dashboard**: Multi-daemon status and feature navigation
- **Daemon picker / SSH connections**: Pair an authorized SSH host, confirm its
  daemon TLS identity, view reconnect/offline state, and remove saved pairings
  (loopback-bound Console only; [SSH workflow](MULTI_DAEMON_TRAY.md#add-daemon-via-ssh))
- **Global Settings**: Effective security configuration and search
- **Violations**: Filterable violation records by daemon and type
- **Violation Logging**: Violation retention and output settings
- **Metrics**: Violation counts by type and severity
- **Detection Patterns**: Read-only built-in and pattern-server rules
- **Auto Directory Rules**: Discovered directory permission rules
- **Permission Rules**: Tool permission rules
- **Context Poisoning**: Detection settings and regex testing
- **Logs**: Daemon log viewer
- **Sessions**: SDK and hook trace records grouped by `run_id`
- **Tracing Settings**: Trace recording and retention controls
- **IDE Conversations**: IDE transcript inspection
- **Scan Configure**: False-positive analysis and suppression configuration
- **Daemon Detail**: Pause, resume, reload, and recent violations
- **About**: Version/system details and **Author: Dominique Vernier ([ITDoVe](https://github.com/itdove))**

To correlate an SDK run with a hook-based IDE session, provide the SDK
`RunContext.run_id` as the hook event's `run_id`. The matching values appear as
one run on **Sessions**.

## Configuration

```json
{
  "console": {
    "web": {
      "port": 0,
      "host": "127.0.0.1"
    }
  }
}
```

- `port`: Web-console port. `0` selects an available port.
- `host`: Bind address. `127.0.0.1` is the secure local default.

The preferred dialog setting supports `auto`, `tkinter`, `nicegui`, and
`headless`. Existing persisted `textual` values are treated as `nicegui` for
configuration compatibility. The environment override is
`AI_GUARDIAN_PREFERRED_UI`.

Automatic dialogs prefer **Native → Tkinter → NiceGUI** among implementations
that preserve the entire interaction. Explicit toolkit choices are exclusive;
only proven startup unavailability can advance an automatic flow. See the
[modal provider matrix](MODAL_PROVIDERS.md) for capability, placement, host-path,
progress and user-only support-consent exceptions and desktop verification.

## System Tray

The tray's **Web Console** menu item opens the browser console for the selected
daemon. The tray also uses NiceGUI for target-selection and form dialogs when
native Tkinter dialogs are unavailable.

On Linux, the tray may require the AppIndicator extension and PyGObject. Run
`ai-guardian doctor` to inspect those optional integrations.

## Troubleshooting

### The browser does not open

Copy the URL printed by `ai-guardian console` into a browser manually. Check
that the configured host and port are reachable and not already in use.

### Native dialogs do not appear

Install Tkinter using the platform package manager, or set
`AI_GUARDIAN_PREFERRED_UI=nicegui` to use the browser dialog explicitly.

### Running without a browser

Use `AI_GUARDIAN_PREFERRED_UI=headless` and configure the relevant ask-mode
fallback. Security hooks and daemon APIs continue to work without the Console.

## Related Documentation

- [Configuration](CONFIGURATION.md)
- [Multi-Daemon Tray](MULTI_DAEMON_TRAY.md)
- [Tool Policy](TOOL_POLICY.md)
- [Violation Logging](VIOLATION_LOGGING.md)
