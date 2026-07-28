#!/usr/bin/env bash
set -euo pipefail

# --- Defaults ---

DRY_RUN=false
REMOVE_ALL=false
YES=false
REMOVED=()

usage() {
    cat <<'EOF'
AI Guardian — Uninstall script

Usage:
    curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/uninstall.sh | bash
    curl -fsSL https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/uninstall.sh | bash -s -- [OPTIONS]

Options:
    --all               Remove everything: package, hooks, config, state, cache
    --keep-config       Remove package + hooks but keep config/state (default)
    --dry-run           Show what would be removed without doing it
    --yes               Skip confirmation prompts
    -h, --help          Show this help message

What gets removed (default):
    • ai-guardian package (auto-detects: uv tool, venv, pyenv, pip)
    • IDE agent hooks (Claude, Cursor, Copilot, Codex, Windsurf, Gemini, Augment)
    • MCP server entries from IDE configs
    • Plugin/extension files (OpenCode, AiderDesk, OpenClaw)
    • Desktop shortcuts and autostart entries
    • Running daemon and tray processes

What gets removed (--all, in addition to above):
    • Configuration directory (~/.config/ai-guardian/)
    • State directory (~/.local/state/ai-guardian/) — violation history, logs
    • Cache directory (~/.cache/ai-guardian/)

What is NEVER removed:
    • Your Python installation, pyenv, or uv
    • Project-local hook files (.clinerules/, .kiro/, .junie/)
      — these are noted but must be removed manually per-project

Examples:
    # Default: remove package + hooks, keep config
    curl -fsSL .../uninstall.sh | bash

    # Remove everything including config and violation history
    curl -fsSL .../uninstall.sh | bash -s -- --all

    # Preview what would be removed
    curl -fsSL .../uninstall.sh | bash -s -- --dry-run

    # Non-interactive removal
    curl -fsSL .../uninstall.sh | bash -s -- --all --yes
EOF
}

# --- Helpers ---

log()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$1"; }
err()  { printf '\033[1;31mError:\033[0m %s\n' "$1" >&2; }
dry()  { printf '\033[1;35m  …\033[0m %s\n' "$1"; }

confirm() {
    if [ "$YES" = true ]; then
        return 0
    fi
    printf '\033[1;33m  ?\033[0m %s [y/N] ' "$1"
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

find_python() {
    local py
    for py in python3 python; do
        if command -v "$py" >/dev/null 2>&1; then
            echo "$py"
            return
        fi
    done
    return 1
}

backup_file() {
    local file="$1"
    if [ -f "$file" ]; then
        if [ "$DRY_RUN" = true ]; then
            dry "Would back up $file → ${file}.bak"
        else
            cp "$file" "${file}.bak"
        fi
    fi
}

# --- Parse arguments ---

while [ $# -gt 0 ]; do
    case "$1" in
        --all)         REMOVE_ALL=true; shift ;;
        --keep-config) REMOVE_ALL=false; shift ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --yes|-y)      YES=true; shift ;;
        -h|--help)     usage; exit 0 ;;
        *)             err "Unknown option: $1"; usage; exit 1 ;;
    esac
done

# --- Resolve directories ---

CONFIG_DIR="${AI_GUARDIAN_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/ai-guardian}"
STATE_DIR="${AI_GUARDIAN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/ai-guardian}"
CACHE_DIR="${AI_GUARDIAN_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/ai-guardian}"
VENV_DIR="$HOME/.ai-guardian-venv"
CLAUDE_CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AI Guardian — Uninstall"
if [ "$DRY_RUN" = true ]; then
    echo "  (DRY RUN — no changes will be made)"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ============================================================
# Step 1: Stop daemon and tray
# ============================================================

stop_processes() {
    log "Stopping running processes..."
    local stopped=false

    # Stop daemon
    local daemon_pid_file="$STATE_DIR/daemon.pid"
    if [ -f "$daemon_pid_file" ]; then
        local daemon_pid
        daemon_pid=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['pid'])" "$daemon_pid_file" 2>/dev/null || echo "")
        if [ -n "$daemon_pid" ] && kill -0 "$daemon_pid" 2>/dev/null; then
            if [ "$DRY_RUN" = true ]; then
                dry "Would stop daemon (PID $daemon_pid)"
            else
                kill "$daemon_pid" 2>/dev/null || true
                ok "Stopped daemon (PID $daemon_pid)"
                REMOVED+=("daemon process")
            fi
            stopped=true
        fi
    fi

    # Stop tray
    local tray_lock="$STATE_DIR/tray.lock"
    if [ -f "$tray_lock" ]; then
        local tray_pid
        tray_pid=$(cat "$tray_lock" 2>/dev/null || echo "")
        if [ -n "$tray_pid" ] && kill -0 "$tray_pid" 2>/dev/null; then
            if [ "$DRY_RUN" = true ]; then
                dry "Would stop tray (PID $tray_pid)"
            else
                kill "$tray_pid" 2>/dev/null || true
                ok "Stopped tray (PID $tray_pid)"
                REMOVED+=("tray process")
            fi
            stopped=true
        fi
    fi

    if [ "$stopped" = false ]; then
        ok "No running processes found"
    fi
}

# ============================================================
# Step 2: Remove IDE hooks (JSON-based agents)
# ============================================================

remove_json_hooks() {
    log "Removing IDE hooks..."

    PYTHON=$(find_python) || {
        warn "Python not found — cannot remove JSON hooks automatically"
        warn "Manually remove ai-guardian entries from your IDE config files"
        return
    }

    # Each entry: "agent_name|hook_config_path|mcp_config_path"
    # MCP config path is empty if same file or not applicable
    local agents=(
        "claude|${CLAUDE_CONFIG}|$HOME/.claude.json"
        "cursor|$HOME/.cursor/hooks.json|$HOME/.cursor/mcp.json"
        "copilot|$HOME/.github/hooks/hooks.json|"
        "codex|$HOME/.codex/hooks.json|$HOME/codex.json"
        "windsurf|$HOME/.codeium/windsurf/hooks.json|$HOME/.windsurf/mcp.json"
        "gemini|$HOME/.gemini/settings.json|"
        "augment|$HOME/.augment/settings.json|"
    )

    local found_any=false

    for entry in "${agents[@]}"; do
        IFS='|' read -r agent hook_path mcp_path <<< "$entry"

        # Check hook config
        if [ -f "$hook_path" ] && grep -q "ai-guardian" "$hook_path" 2>/dev/null; then
            found_any=true
            if [ "$DRY_RUN" = true ]; then
                dry "Would remove ai-guardian hooks from $agent ($hook_path)"
            else
                backup_file "$hook_path"
                "$PYTHON" -c "
import json, sys

path = sys.argv[1]
with open(path) as f:
    config = json.loads(f.read(), strict=False)

def is_ag_command(item):
    if not isinstance(item, dict):
        return False
    cmd = item.get('command', '')
    return isinstance(cmd, str) and 'ai-guardian' in cmd

def remove_ag_hooks(obj):
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            val = obj[key]
            if isinstance(val, list):
                cleaned = []
                for item in val:
                    if is_ag_command(item):
                        continue
                    if isinstance(item, dict):
                        had_hooks = 'hooks' in item
                        remove_ag_hooks(item)
                        if had_hooks and 'hooks' not in item:
                            continue
                    cleaned.append(item)
                if cleaned:
                    obj[key] = cleaned
                else:
                    del obj[key]
            elif isinstance(val, dict):
                remove_ag_hooks(val)
                if not val:
                    del obj[key]
    return obj

config = remove_ag_hooks(config)
with open(path, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
" "$hook_path"
                ok "Removed hooks from $agent ($hook_path)"
                REMOVED+=("$agent hooks")
            fi
        fi

        # Check MCP config (separate file)
        if [ -n "$mcp_path" ] && [ -f "$mcp_path" ] && grep -q "ai-guardian" "$mcp_path" 2>/dev/null; then
            found_any=true
            if [ "$DRY_RUN" = true ]; then
                dry "Would remove ai-guardian MCP server from $agent ($mcp_path)"
            else
                backup_file "$mcp_path"
                "$PYTHON" -c "
import json, sys

path = sys.argv[1]
with open(path) as f:
    config = json.loads(f.read(), strict=False)

for key in ('mcpServers', 'mcp'):
    if key in config and 'ai-guardian' in config[key]:
        del config[key]['ai-guardian']
        if not config[key]:
            del config[key]

with open(path, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
" "$mcp_path"
                ok "Removed MCP server from $agent ($mcp_path)"
                REMOVED+=("$agent MCP server")
            fi
        fi

        # For agents where MCP is in the same file as hooks (gemini, augment)
        if [ -z "$mcp_path" ] && [ -f "$hook_path" ] && grep -q '"mcpServers"' "$hook_path" 2>/dev/null; then
            if grep -q '"ai-guardian"' "$hook_path" 2>/dev/null; then
                # Already handled by hook removal above if hooks were found,
                # but handle MCP-only case
                if [ "$DRY_RUN" = true ]; then
                    dry "Would remove ai-guardian MCP server from $agent ($hook_path)"
                else
                    "$PYTHON" -c "
import json, sys

path = sys.argv[1]
with open(path) as f:
    config = json.loads(f.read(), strict=False)

for key in ('mcpServers', 'mcp'):
    if key in config and isinstance(config[key], dict) and 'ai-guardian' in config[key]:
        del config[key]['ai-guardian']
        if not config[key]:
            del config[key]

with open(path, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
" "$hook_path"
                    ok "Removed MCP server from $agent ($hook_path)"
                    REMOVED+=("$agent MCP server")
                fi
            fi
        fi
    done

    # Additional MCP-only configs (agents that might have MCP but no hooks path above)
    local mcp_only_configs=(
        "cline|$HOME/.cline/mcp_settings.json"
        "kiro|$HOME/.kiro/settings.json"
        "junie|$HOME/.junie/mcp.json"
        "aiderdesk|$HOME/.aider-desk/settings.json"
        "openclaw|$HOME/.openclaw/settings.json"
        "opencode|$HOME/.config/opencode/opencode.jsonc"
    )

    for entry in "${mcp_only_configs[@]}"; do
        IFS='|' read -r agent mcp_path <<< "$entry"
        if [ -f "$mcp_path" ] && grep -q "ai-guardian" "$mcp_path" 2>/dev/null; then
            found_any=true
            if [ "$DRY_RUN" = true ]; then
                dry "Would remove ai-guardian MCP server from $agent ($mcp_path)"
            else
                backup_file "$mcp_path"
                "$PYTHON" -c "
import json, re, sys

path = sys.argv[1]
with open(path) as f:
    text = f.read()

# Strip JSONC comments (avoid stripping // inside strings like URLs)
def strip_jsonc_comments(s):
    result, i, in_str = [], 0, False
    while i < len(s):
        c = s[i]
        if in_str:
            result.append(c)
            if c == '\\\\' and i + 1 < len(s):
                result.append(s[i + 1]); i += 2; continue
            if c == '\"': in_str = False
            i += 1
        elif c == '\"':
            in_str = True; result.append(c); i += 1
        elif s[i:i+2] == '//':
            while i < len(s) and s[i] != '\n': i += 1
        elif s[i:i+2] == '/*':
            i = s.find('*/', i + 2)
            i = i + 2 if i >= 0 else len(s)
        else:
            result.append(c); i += 1
    return ''.join(result)

config = json.loads(strip_jsonc_comments(text), strict=False)

for key in ('mcpServers', 'mcp'):
    if key in config and isinstance(config[key], dict) and 'ai-guardian' in config[key]:
        del config[key]['ai-guardian']
        if not config[key]:
            del config[key]

with open(path, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
" "$mcp_path"
                ok "Removed MCP server from $agent ($mcp_path)"
                REMOVED+=("$agent MCP server")
            fi
        fi
    done

    if [ "$found_any" = false ]; then
        ok "No IDE hooks found"
    fi
}

# ============================================================
# Step 3: Remove file-based agents (plugins/extensions)
# ============================================================

remove_file_agents() {
    log "Removing plugin/extension files..."
    local found=false

    # OpenCode plugin
    local opencode_plugin="$HOME/.config/opencode/plugins/ai-guardian.ts"
    if [ -f "$opencode_plugin" ]; then
        found=true
        if [ "$DRY_RUN" = true ]; then
            dry "Would remove $opencode_plugin"
        else
            rm -f "$opencode_plugin"
            ok "Removed OpenCode plugin"
            REMOVED+=("opencode plugin")
        fi
    fi

    # AiderDesk extension
    local aiderdesk_ext="$HOME/.aider-desk/extensions/ai-guardian"
    if [ -d "$aiderdesk_ext" ]; then
        found=true
        if [ "$DRY_RUN" = true ]; then
            dry "Would remove $aiderdesk_ext/"
        else
            rm -rf "$aiderdesk_ext"
            ok "Removed AiderDesk extension"
            REMOVED+=("aiderdesk extension")
        fi
    fi

    # OpenClaw plugin
    local openclaw_plugin="$HOME/.openclaw/plugins/ai-guardian"
    if [ -d "$openclaw_plugin" ]; then
        found=true
        if [ "$DRY_RUN" = true ]; then
            dry "Would remove $openclaw_plugin/"
        else
            rm -rf "$openclaw_plugin"
            ok "Removed OpenClaw plugin"
            REMOVED+=("openclaw plugin")
        fi
    fi

    if [ "$found" = false ]; then
        ok "No plugin/extension files found"
    fi

    # Warn about project-local hooks
    warn "Project-local hooks (cline, zoocode, kiro, junie) must be removed per-project:"
    echo "    rm -rf <project>/.clinerules/hooks/   # cline/zoocode"
    echo "    rm -rf <project>/.kiro/hooks/          # kiro"
    echo "    rm -rf <project>/.junie/guidelines/    # junie"
}

# ============================================================
# Step 4: Remove desktop/tray integration
# ============================================================

remove_desktop() {
    log "Removing desktop integration..."
    local found=false

    case "$(uname -s)" in
        Darwin)
            # macOS: app bundle
            local app_path="$HOME/Applications/AI Guardian Tray.app"
            if [ -d "$app_path" ]; then
                found=true
                if [ "$DRY_RUN" = true ]; then
                    dry "Would remove $app_path"
                else
                    rm -rf "$app_path"
                    ok "Removed tray app bundle"
                    REMOVED+=("tray app bundle")
                fi
            fi

            # macOS: LaunchAgent plist (current + old name)
            for plist_name in "com.itdove.ai-guardian.tray.plist" "com.ai-guardian.tray.plist"; do
                local plist="$HOME/Library/LaunchAgents/$plist_name"
                if [ -f "$plist" ]; then
                    found=true
                    if [ "$DRY_RUN" = true ]; then
                        dry "Would unload and remove $plist"
                    else
                        launchctl unload "$plist" 2>/dev/null || true
                        rm -f "$plist"
                        ok "Removed LaunchAgent ($plist_name)"
                        REMOVED+=("LaunchAgent")
                    fi
                fi
            done
            ;;
        Linux)
            # Linux: desktop shortcut
            local shortcut="$HOME/.local/share/applications/ai-guardian-tray.desktop"
            if [ -f "$shortcut" ]; then
                found=true
                if [ "$DRY_RUN" = true ]; then
                    dry "Would remove $shortcut"
                else
                    rm -f "$shortcut"
                    ok "Removed desktop shortcut"
                    REMOVED+=("desktop shortcut")
                fi
            fi

            # Linux: autostart
            local autostart="$HOME/.config/autostart/ai-guardian-tray.desktop"
            if [ -f "$autostart" ]; then
                found=true
                if [ "$DRY_RUN" = true ]; then
                    dry "Would remove $autostart"
                else
                    rm -f "$autostart"
                    ok "Removed autostart entry"
                    REMOVED+=("autostart entry")
                fi
            fi
            ;;
    esac

    if [ "$found" = false ]; then
        ok "No desktop integration found"
    fi
}

# ============================================================
# Step 5: Uninstall package
# ============================================================

remove_package() {
    log "Detecting install method..."
    local method=""

    # Check uv tool
    if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q "ai-guardian"; then
        method="uv"
    # Check venv
    elif [ -d "$VENV_DIR" ]; then
        method="venv"
    # Check pyenv virtualenv
    elif command -v pyenv >/dev/null 2>&1 && pyenv versions --bare 2>/dev/null | grep -q "ai-guardian"; then
        method="pyenv"
    # Check pip
    elif pip show ai-guardian >/dev/null 2>&1; then
        method="pip"
    fi

    if [ -z "$method" ]; then
        warn "ai-guardian package not found (already uninstalled?)"
        return
    fi

    case "$method" in
        uv)
            if [ "$DRY_RUN" = true ]; then
                dry "Would run: uv tool uninstall ai-guardian"
            else
                uv tool uninstall ai-guardian
                ok "Uninstalled via uv tool"
                REMOVED+=("package (uv tool)")
            fi
            ;;
        venv)
            if [ "$DRY_RUN" = true ]; then
                dry "Would remove venv at $VENV_DIR"
            else
                rm -rf "$VENV_DIR"
                ok "Removed venv at $VENV_DIR"
                REMOVED+=("package (venv)")
            fi
            ;;
        pyenv)
            if [ "$DRY_RUN" = true ]; then
                dry "Would run: pyenv virtualenv-delete -f ai-guardian"
            else
                pyenv virtualenv-delete -f ai-guardian
                ok "Uninstalled via pyenv virtualenv-delete"
                REMOVED+=("package (pyenv)")
            fi
            ;;
        pip)
            if [ "$DRY_RUN" = true ]; then
                dry "Would run: pip uninstall -y ai-guardian"
            else
                pip uninstall -y ai-guardian
                ok "Uninstalled via pip"
                REMOVED+=("package (pip)")
            fi
            ;;
    esac
}

# ============================================================
# Step 6: Remove config, state, cache (--all only)
# ============================================================

remove_data() {
    if [ "$REMOVE_ALL" = false ]; then
        ok "Keeping config/state/cache (use --all to remove)"
        return
    fi

    log "Removing config, state, and cache..."

    local dirs_to_remove=()
    [ -d "$CONFIG_DIR" ] && dirs_to_remove+=("$CONFIG_DIR")
    [ -d "$STATE_DIR" ] && dirs_to_remove+=("$STATE_DIR")
    [ -d "$CACHE_DIR" ] && dirs_to_remove+=("$CACHE_DIR")

    if [ ${#dirs_to_remove[@]} -eq 0 ]; then
        ok "No config/state/cache directories found"
        return
    fi

    echo ""
    warn "The following directories will be permanently deleted:"
    for dir in "${dirs_to_remove[@]}"; do
        echo "    $dir"
    done
    echo ""

    if ! confirm "Remove these directories? (contains violation history and settings)"; then
        warn "Skipping config/state/cache removal"
        return
    fi

    for dir in "${dirs_to_remove[@]}"; do
        if [ "$DRY_RUN" = true ]; then
            dry "Would remove $dir"
        else
            rm -rf "$dir"
            ok "Removed $dir"
            REMOVED+=("$(basename "$dir") directory")
        fi
    done
}

# ============================================================
# Run all steps
# ============================================================

stop_processes
remove_json_hooks
remove_file_agents
remove_desktop
remove_package
remove_data

# ============================================================
# Summary
# ============================================================

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$DRY_RUN" = true ]; then
    echo "  Dry run complete — no changes were made"
else
    echo "  AI Guardian uninstalled"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$DRY_RUN" = false ] && [ ${#REMOVED[@]} -gt 0 ]; then
    echo "  Removed:"
    for item in "${REMOVED[@]}"; do
        echo "    • $item"
    done
    echo ""
fi

if [ "$REMOVE_ALL" = false ] && [ "$DRY_RUN" = false ]; then
    echo "  Config kept at: $CONFIG_DIR"
    echo "  State kept at:  $STATE_DIR"
    echo "  To remove: rerun with --all"
    echo ""
fi

echo "  Project-local hooks (if any) must be removed manually:"
echo "    rm -rf <project>/.clinerules/hooks/"
echo "    rm -rf <project>/.kiro/hooks/"
echo "    rm -rf <project>/.junie/guidelines/"
echo ""
