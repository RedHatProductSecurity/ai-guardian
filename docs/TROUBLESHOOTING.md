# Troubleshooting Guide

Common issues with the AI Guardian daemon, system tray, and container deployments.

## General Diagnostics

Run `ai-guardian doctor` for a comprehensive health check covering config validation, scanner availability, hook installation, permissions, unknown config keys, and more. Use `--json` for machine-readable output.

```bash
ai-guardian doctor
ai-guardian doctor --json
```

## Daemon Startup Issues

### Stale Lock File Blocking Daemon Start

**Symptom:** `ai-guardian daemon start` fails with:
```
Another daemon is starting (pid 12345). Stop it first with: ai-guardian daemon stop
```
...but no daemon process is actually running.

**Cause:** A previous daemon crashed or was killed without cleaning up its lock file at `~/.local/state/ai-guardian/daemon.pid.lock`.

**Fix:**
```bash
# Verify no daemon is running
ps aux | grep ai-guardian

# Remove the stale lock file
rm ~/.local/state/ai-guardian/daemon.pid.lock

# Start the daemon
ai-guardian daemon start
```

> **Note:** The state directory location depends on your environment. If `XDG_STATE_HOME` is set, the lock file is at `$XDG_STATE_HOME/ai-guardian/daemon.pid.lock`. You can also override it with `AI_GUARDIAN_STATE_DIR`.

### "Another Daemon Is Starting" When No Daemon Is Running

**Symptom:** The error message references a PID that no longer exists.

**Cause:** The daemon uses atomic file creation (`O_CREAT|O_EXCL`) for its lock file to prevent concurrent starts. If the process that created the lock exited abnormally, the lock persists.

**Fix:** The daemon has built-in stale detection that checks if the PID in the lock file is alive. If detection fails (e.g., on some container runtimes where `/proc` is restricted):
```bash
# Force remove the lock
rm ~/.local/state/ai-guardian/daemon.pid.lock
rm ~/.local/state/ai-guardian/daemon.pid

# Restart
ai-guardian daemon start
```

### Multiple Daemon Processes in Containers

**Symptom:** `ps` shows multiple `ai-guardian daemon` processes running inside a container.

**Cause:** Race condition at container boot when multiple hook invocations trigger auto-start simultaneously. Although the lock file prevents most races, fast concurrent starts can slip through before the lock is written.

**Fix:**
```bash
# Stop all daemon processes
ai-guardian daemon stop

# If stop doesn't catch all processes
pkill -f "ai-guardian daemon"

# Start a single daemon
ai-guardian daemon start
```

**Prevention:** In container entrypoints, start the daemon explicitly before any hook invocations:
```bash
#!/bin/bash
# Start daemon first, then run your workload
ai-guardian daemon start
# ... rest of entrypoint
```

### Zombie Processes Preventing Restart

**Symptom:** `ps` shows daemon processes in `Z` (defunct/zombie) state, and new starts fail.

**Cause:** The parent process did not reap the child. Common in containers with init process issues.

**Fix:**
```bash
# Check for zombie processes
ps aux | grep -E 'Z.*ai-guardian'

# The zombie's parent must reap it, or kill the parent
kill <parent-pid>

# Remove lock files
rm ~/.local/state/ai-guardian/daemon.pid.lock
rm ~/.local/state/ai-guardian/daemon.pid

# Start fresh
ai-guardian daemon start
```

**Prevention:** Use a proper init system in containers (e.g., `tini` or `--init` flag with Docker/Podman):
```bash
podman run --init your-image
```

### Quick Recovery with `daemon reset`

**Symptom:** The daemon is in a broken state — orphaned process, stale PID file, hung socket — and normal `daemon stop` doesn't help.

**Fix:** Use the `reset` command for clean recovery:
```bash
ai-guardian daemon reset
```

This will:
1. Find the daemon process from the PID file
2. Send SIGTERM, wait up to 3 seconds, then SIGKILL if needed
3. Remove all daemon state files (`daemon.pid`, `daemon.pid.lock`, `daemon.sock`)
4. Clear the `daemon.stop-requested` marker so auto-start works again

The reset command does **not** touch: tray process, console, MCP server, configuration, or log files.

**Safe to run at any time** — if no daemon is running and no state files exist, it reports "No daemon state to reset" and exits cleanly.

**After reset:**
```bash
ai-guardian daemon start -b
```

---

## Tray Display Issues

### Tray Showing Container Name Instead of Config Name

**Symptom:** The system tray shows the container hostname (e.g., `a1b2c3d4e5f6`) instead of a meaningful name.

**Cause:** The daemon reads its display name from the config file's top-level `name` field, falling back to `socket.gethostname()`. If the daemon starts before the config file is written, it caches the hostname.

**Fix:**
1. Set the `name` field in your `ai-guardian.json` config:
   ```json
   {
     "name": "my-project",
     "daemon": {
       "rest_port": 63152
     }
   }
   ```
2. Restart the daemon to pick up the new name:
   ```bash
   ai-guardian daemon stop
   ai-guardian daemon start
   ```

### Config Name Field Location

The daemon name is read from the **top-level** `name` field in `ai-guardian.json`, not from `daemon.name`:

```json
{
  "name": "my-project-name"
}
```

The config file is located at `~/.config/ai-guardian/ai-guardian.json` by default (or `$XDG_CONFIG_HOME/ai-guardian/ai-guardian.json`).

### Daemon Started Before Config Is Written

**Symptom:** The daemon displays the hostname because it started before the config file existed.

**Cause:** Auto-start triggers during hook processing can start the daemon before `ai-guardian setup --create-config` has run.

**Fix:**
```bash
# Create config first
ai-guardian setup --create-config

# Edit the config to set your preferred name
# Then restart the daemon
ai-guardian daemon stop
ai-guardian daemon start
```

---

## Tray Plugin Popup Issues

### Tray Quick Actions Open Browser Instead of Native Dialog (uv install)

**Symptom:** Tray plugin parameter popups open a NiceGUI browser form instead of a native tkinter dialog, even on a system where tkinter should be available.

**Cause:** When ai-guardian is installed via `uv tool install`, the Python runtime is python-build-standalone which may have an incomplete Tcl/Tk installation. Earlier versions of ai-guardian used an overly strict tkinter check (`package require Tk`) that failed on uv's Python even when tkinter itself worked fine. This was fixed in [#1037](https://github.com/itdove/ai-guardian/issues/1037).

**Fix:** Upgrade to ai-guardian v1.11.0 or later:
```bash
uv tool upgrade ai-guardian
```

**Workaround:** The NiceGUI browser form is functionally identical — it opens in your default browser instead of a native window. No data or functionality is lost.

**Verify tkinter works in your environment:**
```bash
# For uv tool installs:
$(uv tool dir)/ai-guardian/bin/python -c "import tkinter; root = tkinter.Tk(); root.destroy(); print('OK')"

# For pip/venv installs:
python -c "import tkinter; root = tkinter.Tk(); root.destroy(); print('OK')"
```

**Force a specific popup backend:**
```bash
AI_GUARDIAN_NO_TKINTER=1    # skip tkinter, use NiceGUI or Textual
AI_GUARDIAN_NO_NICEGUI=1    # skip NiceGUI, use Textual
```

### tkinter Not Available on Python 3.14 (uv)

**Symptom:** `import tkinter` fails with Python 3.14 installed via uv.

**Cause:** uv uses python-build-standalone binaries which may not include Tcl/Tk libraries for newer Python versions. This is a [known upstream issue](https://github.com/astral-sh/uv/issues/7036).

**Workaround:** Use Python 3.12 or 3.13 for full tkinter/tray support:
```bash
uv tool install ai-guardian --python 3.13
```

Or use the NiceGUI/Textual fallback — the tray plugin cascade handles this automatically.

### tkinter Crashes with SIGABRT on macOS

**Symptom:** The tray popup crashes immediately with a `SIGABRT` or `NSInvalidArgumentException` on macOS.

**Cause:** On macOS, if PyObjC's `NSApplication.sharedApplication()` is initialized before `tkinter.Tk()`, the Objective-C runtime creates an NSApplication wrapper that lacks Tk's `macOSVersion` category method. When tkinter later tries to call this method, the process aborts.

**Fix:** This was fixed in [#1037](https://github.com/itdove/ai-guardian/issues/1037). Upgrade to v1.11.0 or later.

**Workaround:** Skip tkinter and use the NiceGUI fallback:
```bash
export AI_GUARDIAN_NO_TKINTER=1
```

### Tcl Can't Find init.tcl from Tray Daemon

**Symptom:** tkinter works from the CLI but fails when launched from the tray daemon subprocess with an error like `can't find a usable init.tcl`.

**Cause:** uv's venv uses symlinks to the python-build-standalone install. When the tray daemon resolves the Python executable, Tcl searches for `init.tcl` relative to the symlink rather than the real Python install path.

**Fix:** Fixed in [#1037](https://github.com/itdove/ai-guardian/issues/1037) — ai-guardian now resolves the real Python path and sets `TCL_LIBRARY` to the correct location. Upgrade to v1.11.0 or later.

---

## Container-Specific Issues

### Container Entrypoint Starting Daemon Before Config Is Ready

**Symptom:** The daemon starts with default settings because the config file hasn't been mounted or generated yet.

**Cause:** The entrypoint script starts the daemon before volume mounts are available or before config generation completes.

**Fix:** Order your entrypoint to ensure config exists first:
```bash
#!/bin/bash
# 1. Wait for config to be available
while [ ! -f /path/to/ai-guardian.json ]; do
  sleep 1
done

# 2. Start daemon
ai-guardian daemon start

# 3. Continue with workload
exec "$@"
```

### Port Conflicts When Multiple Daemons Bind to the Same Port

**Symptom:** Daemon fails to start, or the REST API is unavailable. Log shows:
```
REST API failed to start: [Errno 98] Address already in use
```

**Cause:** Multiple daemons (or a daemon restart) are trying to bind to the same port. The default port is `63152`.

**Fix:**
```bash
# Check what's using the port
lsof -i :63152
# or
ss -tlnp | grep 63152

# Stop the conflicting process
ai-guardian daemon stop

# Or configure a different port in ai-guardian.json
```

```json
{
  "daemon": {
    "rest_port": 63153
  }
}
```

> **Note:** In containers, the daemon automatically binds to `0.0.0.0` instead of `127.0.0.1` (detected via `/.dockerenv` or `/run/.containerenv`).

### Daemon Auto-Start Races from Concurrent Hook Invocations

**Symptom:** Multiple hook invocations in quick succession each try to start a daemon, causing lock contention or multiple processes.

**Cause:** When the daemon is not running, each `ai-guardian` CLI invocation attempts auto-start. With concurrent IDE operations (e.g., opening multiple files), several processes race to start the daemon.

**Fix:** The daemon uses atomic lock file creation to prevent most races, but if issues persist:
```bash
# Stop everything
ai-guardian daemon stop
pkill -f "ai-guardian daemon" 2>/dev/null

# Clean up
rm -f ~/.local/state/ai-guardian/daemon.pid.lock
rm -f ~/.local/state/ai-guardian/daemon.pid

# Start manually
ai-guardian daemon start
```

---

## General Issues

### Daemon Auto-Start Failures (Fail-Open)

**Symptom:** AI Guardian hooks run but are slower than expected, and logs show fallback messages.

**Cause:** When the daemon fails to start or respond, the CLI falls back to "direct mode" — processing hooks inline without the daemon. This is by design (fail-open) to avoid blocking the IDE.

**Log messages indicating direct mode:**
```
Daemon returned no response, falling back to direct
Daemon unavailable, falling back to direct
Daemon client error, falling back to direct: <error>
```

**Fix:** Start the daemon manually to restore fast hook processing:
```bash
ai-guardian daemon start
```

If the daemon keeps failing, check:
- Lock file issues (see above)
- Port conflicts (see above)
- Config file errors: `ai-guardian setup --validate`

### Port Already in Use

**Symptom:** Daemon starts but the REST API is not available.

**Cause:** Another process (or a previous daemon instance) is using port `63152`.

**Fix:**
```bash
# Find what's using the port
lsof -i :63152

# Kill the conflicting process or change the port
ai-guardian daemon stop

# Start with a clean slate
ai-guardian daemon start
```

To change the default port permanently:
```json
{
  "daemon": {
    "rest_port": 63200
  }
}
```

### Config Reload Not Picking Up Changes

**Symptom:** You edited `ai-guardian.json` but the daemon behavior hasn't changed.

**Cause:** The daemon detects config changes via file modification time (mtime) on each hook request, with a SHA256 checksum verification every 60 seconds. Some edge cases where changes may not be detected:
- NFS or network filesystems with clock skew
- File replaced atomically (same mtime as previous version)
- Editing inside the daemon's 60-second checksum window

**Fix:** Restart the daemon to force a config reload:
```bash
ai-guardian daemon stop
ai-guardian daemon start
```

Or trigger a reload via the REST API:
```bash
curl -X POST http://127.0.0.1:63152/api/reload
```

### How to Verify the Daemon Is Working

Use the status endpoint to confirm the daemon is running and responsive:

```bash
curl http://127.0.0.1:63152/api/status
```

**Expected response:**
```json
{
  "running": true,
  "paused": false,
  "uptime_seconds": 3600,
  "version": "1.9.0",
  "name": "my-project"
}
```

**Other useful commands:**
```bash
# Check daemon process
ai-guardian daemon status

# View detailed stats
curl http://127.0.0.1:63152/api/stats

# Health check (lightweight)
curl http://127.0.0.1:63152/api/health
```

> **Note:** If you configured a custom `rest_port` or `auth_token`, adjust the curl commands accordingly. With auth enabled:
> ```bash
> curl -H "Authorization: Bearer YOUR_TOKEN" http://127.0.0.1:63152/api/status
> ```

### Daemon Idle Timeout

The daemon automatically shuts down after 30 minutes of inactivity by default. This is configurable:

```json
{
  "daemon": {
    "idle_timeout_minutes": 30
  }
}
```

Set to `0` to disable idle shutdown.

---

## Cursor: Double Popups / Hooks Firing Twice

**Symptom:** When both Claude Code and Cursor are installed, ai-guardian popups
appear twice for the same event.

**Cause:** Cursor has an "Include third-party extensions" toggle (in Cursor
Settings > General) that imports and executes hooks from `~/.claude/settings.json`.
When this is enabled, both Claude Code's hooks and Cursor's own hooks
(`~/.cursor/hooks.json`) fire for the same event.

**Fix:** Disable "Include third-party extensions" in Cursor settings. This ensures
each IDE uses only its own hook configuration:

- Claude Code: `~/.claude/settings.json`
- Cursor: `~/.cursor/hooks.json`

Alternatively, uninstall ai-guardian hooks from one IDE:
```bash
# Keep only Claude Code hooks
ai-guardian setup --ide claude --uninstall-ide cursor

# Keep only Cursor hooks
ai-guardian setup --ide cursor --uninstall-ide claude
```

---

## Known Claude Code Limitations

These are open upstream issues in the Claude Code runtime that affect ai-guardian's security enforcement. They are not bugs in ai-guardian — they are limitations in the hook system that ai-guardian cannot work around.

For per-violation-type impact details, see [AGENT_SUPPORT.md — Known Limitations](AGENT_SUPPORT.md#known-limitations).

### Secret/PII Redaction Bypassed in Bash Output

**Symptom:** ai-guardian detects a secret or PII in Bash output and redacts it, but the model still sees the original unredacted text.

**Cause:** Claude Code ignores the `updatedToolOutput` field returned by `PostToolUse` hooks for Bash tool results.

**Workaround:** Use `block` action mode for secrets and PII instead of `warn` or `log-only`. This prevents the tool call entirely rather than relying on post-execution redaction.

**Upstream:** [anthropics/claude-code#64326](https://github.com/anthropics/claude-code/issues/64326)

### Image/Binary File Reads Not Scanned

**Symptom:** ai-guardian does not detect secrets or PII in image files read by Claude Code.

**Cause:** Claude Code does not fire `PreToolUse` hooks (or does not include scannable content) when reading image/binary files.

**Workaround:** Use directory rules to block access to directories containing sensitive images. There is no way to scan image content inline.

**Upstream:** [anthropics/claude-code#62639](https://github.com/anthropics/claude-code/issues/62639)

### Skill Tool Calls Bypass All Hooks

**Symptom:** Tool calls made within a skill (slash command) are not checked by ai-guardian — no permission enforcement, no directory blocking, no SSRF protection.

**Cause:** Claude Code does not fire `PreToolUse` hooks for tool calls originating from skill invocations.

**Workaround:** Audit installed skills and limit skill access to trusted sources. There is no hook-based enforcement for skill tool calls.

**Upstream:** [anthropics/claude-code#66446](https://github.com/anthropics/claude-code/issues/66446)

### No Tool Result Transform Hook

**Symptom:** ai-guardian cannot sanitize or transform tool output before the model processes it.

**Cause:** Claude Code does not provide a hook event for modifying tool results. The `PostToolUse` hook can inspect but not reliably transform output.

**Workaround:** ai-guardian strips detection patterns from its own warn/log-only messages ([#1327](https://github.com/itdove/ai-guardian/issues/1327)), but cannot sanitize arbitrary tool output.

**Upstream:** [anthropics/claude-code#18653](https://github.com/anthropics/claude-code/issues/18653)

---

## File Locations Quick Reference

| File | Default Path | Purpose |
|------|-------------|---------|
| Config | `~/.config/ai-guardian/ai-guardian.json` | Main configuration |
| PID file | `~/.local/state/ai-guardian/daemon.pid` | Running daemon PID and port |
| Lock file | `~/.local/state/ai-guardian/daemon.pid.lock` | Startup lock (prevents concurrent starts) |
| Tray lock | `~/.local/state/ai-guardian/tray.lock` | Tray instance lock |
| Socket | `~/.local/state/ai-guardian/daemon.sock` | Unix domain socket (alternative to REST) |
| Violations | `~/.local/state/ai-guardian/violations.json` | Security violation audit log |

Paths are governed by XDG conventions and can be overridden with environment variables:
- `AI_GUARDIAN_CONFIG_DIR` or `XDG_CONFIG_HOME`
- `AI_GUARDIAN_STATE_DIR` or `XDG_STATE_HOME`
