#!/usr/bin/env bash
set -euo pipefail

# Integration cleanup is shared with native Windows and requires no installed
# AI Guardian code. Keep the engine beside this script for offline use.
DRY_RUN=false
REMOVE_ALL=false
YES=false
INTEGRATIONS_ONLY=false
SCOPE=user
PROJECTS=()
PYTHON=""

usage() {
    cat <<'EOF'
AI Guardian — Uninstall and orphan recovery (operator terminal only)

Usage: bash uninstall.sh [OPTIONS]
       curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/uninstall.sh | bash -s -- [OPTIONS]

Options:
    --integrations-only  Recover hooks/plugins/MCP without stopping processes,
                         removing the package, desktop integration, or user data
    --scope user|project|both
                         Select configuration layers (default: user)
    --project PATH       Exact project root; repeat for multiple selected projects
    --python PATH        Independent Python 3.11+ (otherwise python3/python)
    --dry-run            Non-mutating preview, including ownership validation
    --yes, -y            Confirm the selected scope without an interactive prompt
    --keep-config        Keep configuration, state, cache (default)
    --all                Also remove configuration, state, cache/violation history
    -h, --help           Show help

Default: clean user integrations, stop owned processes, remove desktop entries
and the package (uv tool, dedicated venv, pyenv, or pip). Selected project scopes
are never discovered recursively. Shared hook directories are never deleted.
Edited/removed integration files receive unique private sibling .bak backups.
Unrecognized, linked, malformed, or unwritable files are retained and reported;
partial integration cleanup exits nonzero before package/data removal.

Prerequisites: Bash, independent Python 3.11+, and scripts/ai_guardian_recovery.py
from the same checkout. A piped/download-only wrapper fetches the engine over
HTTPS with curl; download both files beforehand for reviewed/offline operation.
Restart affected hosts after cleanup. Settings and violation history are kept
unless --all is explicitly selected. See docs/UNINSTALL.md for limitations.
EOF
}

err() { printf 'Error: %s\n' "$1" >&2; }
log() { printf '%s\n' "$1"; }
confirm() {
    [ "$YES" = true ] && return 0
    local answer
    read -r -p "$1 [y/N] " answer || return 1
    case "$answer" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

while [ $# -gt 0 ]; do
    case "$1" in
        --integrations-only) INTEGRATIONS_ONLY=true; shift ;;
        --scope|--project|--python)
            [ $# -ge 2 ] || { err "$1 requires a value"; exit 2; }
            case "$1" in
                --scope) SCOPE="$2" ;;
                --project)
                    [ -n "$2" ] || { err "--project requires a non-empty path"; exit 2; }
                    PROJECTS+=("$2") ;;
                --python) PYTHON="$2" ;;
            esac
            shift 2 ;;
        --all) REMOVE_ALL=true; shift ;;
        --keep-config) REMOVE_ALL=false; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --yes|-y) YES=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) err "Unknown option: $1"; exit 2 ;;
    esac
done

if [ "$INTEGRATIONS_ONLY" = true ] && [ "$REMOVE_ALL" = true ]; then
    err "--all cannot be combined with --integrations-only"; exit 2
fi
if [ "$SCOPE" = project ] && [ "$INTEGRATIONS_ONLY" = false ]; then
    err "Project-only scope requires --integrations-only"; exit 2
fi

if [ -z "$PYTHON" ]; then
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -S -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            PYTHON="$candidate"; break
        fi
    done
fi
if [ -z "$PYTHON" ] || ! "$PYTHON" -I -S -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    err "An independent Python 3.11+ interpreter is required; no changes made"; exit 2
fi

ENGINE=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    ENGINE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/scripts/ai_guardian_recovery.py"
fi
if [ -z "$ENGINE" ] || [ ! -f "$ENGINE" ]; then
    command -v curl >/dev/null 2>&1 || { err "Missing companion scripts/ai_guardian_recovery.py and curl; no changes made"; exit 2; }
    ENGINE=$(mktemp "${TMPDIR:-/tmp}/ai-guardian-recovery.XXXXXXXX")
    trap 'rm -f -- "$ENGINE"' EXIT
    curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/scripts/ai_guardian_recovery.py -o "$ENGINE"
fi

ARGS=(--scope "$SCOPE")
# Bash 3.2 on macOS treats an empty array as unset under nounset.
for project in "${PROJECTS[@]-}"; do
    [ -z "$project" ] || ARGS+=(--project "$project")
done
[ "$DRY_RUN" = false ] || ARGS+=(--dry-run)
[ "$YES" = false ] || ARGS+=(--yes)

# Fail before unrelated uninstall work on any partial/ambiguous integration.
"$PYTHON" -I -S "$ENGINE" "${ARGS[@]}"
if [ "$INTEGRATIONS_ONLY" = true ]; then exit 0; fi
if [ "$DRY_RUN" = false ] && ! confirm "Continue with process, desktop and package removal?"; then
    log "Package/data removal cancelled."; exit 1
fi

CONFIG_DIR="${AI_GUARDIAN_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/ai-guardian}"
STATE_DIR="${AI_GUARDIAN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/ai-guardian}"
CACHE_DIR="${AI_GUARDIAN_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/ai-guardian}"
VENV_DIR="$HOME/.ai-guardian-venv"

stop_processes() {
    log "Stopping running processes..."
    local pid_file pid command_line
    for pid_file in "$STATE_DIR/daemon.pid" "$STATE_DIR/tray.lock"; do
        [ -f "$pid_file" ] || continue
        pid=$("$PYTHON" -I -S -c '
import json, pathlib, sys
try:
    text = pathlib.Path(sys.argv[1]).read_text()
    value = json.loads(text)
    pid = value.get("pid") if isinstance(value, dict) else value
    print(int(pid))
except (OSError, ValueError, TypeError):
    print("Retained invalid/unreadable process reference: " + sys.argv[1], file=sys.stderr)
' "$pid_file")
        [ -n "$pid" ] && [ "$pid" -gt 1 ] || continue
        command_line=$(ps -p "$pid" -o args= 2>/dev/null || true)
        if [ -n "$command_line" ] && "$PYTHON" -I -S -c '
import runpy, sys
owned = runpy.run_path(sys.argv[1])["owned_command"]
sys.exit(not owned(sys.argv[2]))
' "$ENGINE" "$command_line"; then
            if [ "$DRY_RUN" = true ]; then log "Would stop owned process (PID $pid)";
            else kill "$pid"; fi
        else log "Retained unverified/stale process reference: $pid_file"; fi
    done
}

remove_desktop() {
    log "Removing desktop integration..."
    local file
    # Only known AI Guardian files, never shared directories.
    for file in "$HOME/.local/share/applications/ai-guardian-tray.desktop" \
                "$HOME/.config/autostart/ai-guardian-tray.desktop" \
                "$HOME/Library/LaunchAgents/com.itdove.ai-guardian.tray.plist" \
                "$HOME/Library/LaunchAgents/com.ai-guardian.tray.plist"; do
        [ -f "$file" ] || continue
        if [ "$DRY_RUN" = true ]; then log "Would remove $file";
        else
            cp -p -- "$file" "$file.ai-guardian-backup-$(date +%s)-$$.bak"
            case "$file" in *.plist) launchctl unload "$file" 2>/dev/null || true ;; esac
            rm -f -- "$file"
        fi
    done
    local app="$HOME/Applications/AI Guardian Tray.app"
    if [ -d "$app" ]; then
        if [ "$DRY_RUN" = true ]; then log "Would remove $app";
        else rm -rf -- "$app"; fi
    fi
}

remove_package() {
    log "Detecting install method..."
    local method=""
    if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -Eq '^ai-guardian([[:space:]]|$)'; then method=uv
    elif [ -d "$VENV_DIR" ]; then method=venv
    elif command -v pyenv >/dev/null 2>&1 && pyenv versions --bare 2>/dev/null | grep -qx ai-guardian; then method=pyenv
    elif "$PYTHON" -m pip show ai-guardian >/dev/null 2>&1; then method=pip
    fi
    if [ -z "$method" ]; then log "ai-guardian package not found (already uninstalled?)"; return; fi
    if [ "$DRY_RUN" = true ]; then log "Would remove package ($method)"; return; fi
    case "$method" in
        uv) uv tool uninstall ai-guardian ;;
        venv) rm -rf -- "$VENV_DIR" ;;
        pyenv) pyenv virtualenv-delete -f ai-guardian ;;
        pip) "$PYTHON" -m pip uninstall -y ai-guardian ;;
    esac
}

remove_data() {
    if [ "$REMOVE_ALL" = false ]; then log "Keeping config/state/cache and violation history."; return; fi
    if [ "$DRY_RUN" = false ] && ! confirm "Permanently remove AI Guardian settings and violation history?"; then
        log "Keeping config/state/cache."; return
    fi
    local dir
    for dir in "$CONFIG_DIR" "$STATE_DIR" "$CACHE_DIR"; do
        case "$dir" in ""|/|"$HOME") err "Refusing unsafe data directory"; return 1 ;; esac
        [ -d "$dir" ] || continue
        if [ "$DRY_RUN" = true ]; then log "Would remove $dir";
        else rm -rf -- "$dir"; fi
    done
}

stop_processes
remove_desktop
remove_package
remove_data
if [ "$DRY_RUN" = true ]; then log "Dry run complete — no changes were made";
else log "AI Guardian uninstall complete. Restart affected hosts."; fi
