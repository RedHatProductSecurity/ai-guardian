#!/usr/bin/env bash
set -euo pipefail

# _request_tos_consent: prompt user to accept ToS before installing a proprietary CLI.
# Returns 0 (proceed) or 1 (skip).
# Bypass: set ACCEPT_PROPRIETARY_TOS=true for non-interactive/CI use.
_request_tos_consent() {
  local name="$1"
  local tos_url="$2"

  if [ "${ACCEPT_PROPRIETARY_TOS:-}" = "true" ]; then
    echo "ACCEPT_PROPRIETARY_TOS=true — accepting ToS for ${name}"
    return 0
  fi

  if [ ! -t 0 ]; then
    echo "Non-interactive mode: skipping ${name} install (set ACCEPT_PROPRIETARY_TOS=true to enable)"
    return 1
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ${name} requires accepting its Terms of Service:"
  echo "  ${tos_url}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf "  Install %s and accept the ToS? [y/N] " "${name}"
  read -r _tos_answer || true
  if [ "${_tos_answer:-}" = "y" ] || [ "${_tos_answer:-}" = "Y" ]; then
    return 0
  fi
  echo "  Skipping ${name} installation."
  return 1
}

# Older OpenShell invocations may pass metadata as leading arguments. Consume
# only our reserved arguments and leave the agent command untouched. The
# current sandbox command uses OpenShell's supported --env options instead.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ai-guardian-agent)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "Error: --ai-guardian-agent requires a value" >&2
        exit 1
      fi
      export AI_GUARDIAN_AGENT="$2"
      shift 2
      ;;
    --ai-guardian-profile)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "Error: --ai-guardian-profile requires a value" >&2
        exit 1
      fi
      export AI_GUARDIAN_PROFILE="$2"
      shift 2
      ;;
    --ai-guardian-host-config)
      export AI_GUARDIAN_HOST_CONFIG_MOUNTED=true
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

SUPPORTED_AGENT_IDES=(
  claude cursor copilot codex windsurf gemini cline zoocode kiro
  aiderdesk openclaw opencode augment crush junie antigravity
)
CLI_AGENT_IDES=(claude copilot codex gemini kiro openclaw opencode crush antigravity)
SUPPORTED_IDES=("${SUPPORTED_AGENT_IDES[@]}" dummy-agent)

# AI_GUARDIAN_AGENT is the name used by the sandbox command. Keep
# AI_GUARDIAN_IDE as a compatibility alias for existing container users.
# If no explicit environment value is present, infer the agent when its
# command is the first argument (for example, ``... -- codex``).
IDE="${AI_GUARDIAN_AGENT:-${AI_GUARDIAN_IDE:-}}"
if [ -z "$IDE" ] && [ "$#" -gt 0 ]; then
  for supported_ide in "${SUPPORTED_IDES[@]}"; do
    if [ "$1" = "$supported_ide" ]; then
      IDE="$1"
      break
    fi
  done
fi
IDE="${IDE:-codex}"
PROFILE="${AI_GUARDIAN_PROFILE:-}"
if [ -n "${AI_GUARDIAN_CONFIG_DIR:-}" ]; then
  CONFIG_DIR="$AI_GUARDIAN_CONFIG_DIR"
elif [ -n "${AI_GUARDIAN_HOME:-}" ]; then
  CONFIG_DIR="$AI_GUARDIAN_HOME"
elif [ -n "${XDG_CONFIG_HOME:-}" ]; then
  CONFIG_DIR="${XDG_CONFIG_HOME}/ai-guardian"
else
  CONFIG_DIR="${HOME}/.config/ai-guardian"
fi
CONFIG_PATH="${CONFIG_DIR}/ai-guardian.json"
CONFIG_METADATA_PATH="${CONFIG_DIR}/.ai-guardian-config-metadata.json"
HOST_CONFIG_MOUNTED="${AI_GUARDIAN_HOST_CONFIG_MOUNTED:-false}"
# New sandbox commands stage a host config beside the active sandbox config. Keep
# the canonical path as the compatibility default for older invocations that
# mounted the host file directly over CONFIG_PATH.
HOST_CONFIG_PATH="${AI_GUARDIAN_HOST_CONFIG_PATH:-$CONFIG_PATH}"
CONFIG_SOURCE="${AI_GUARDIAN_CONFIG_SOURCE:-}"
CONFIG_READ_ONLY="${AI_GUARDIAN_CONFIG_READ_ONLY:-false}"
RESTORE_CONFIG="${AI_GUARDIAN_RESTORE_CONFIG:-false}"
SETUP_SCOPE="${AI_GUARDIAN_SETUP_SCOPE:-selected}"
OPEN_SHELL_STAGING="${AI_GUARDIAN_OPEN_SHELL_STAGING:-false}"

# The support image may use a released PyPI package while the sandbox command is
# newer than that package. Discover the setup command's advertised IDE choices
# so a newly added integration is skipped until the corresponding release is
# available, while an explicitly selected unsupported agent still fails fast.
SETUP_HELP="$(ai-guardian setup --help 2>&1 || true)"
SETUP_CHOICES_DETECTED="false"
if [[ "$SETUP_HELP" == *"--ide {"* ]]; then
  SETUP_CHOICES_DETECTED="true"
fi

_is_supported_ide() {
  local candidate="$1"
  local supported_ide
  for supported_ide in "${SUPPORTED_IDES[@]}"; do
    if [ "$candidate" = "$supported_ide" ]; then
      return 0
    fi
  done
  return 1
}

_is_cli_ide() {
  local candidate="$1"
  local cli_ide
  for cli_ide in "${CLI_AGENT_IDES[@]}"; do
    if [ "$candidate" = "$cli_ide" ]; then
      return 0
    fi
  done
  return 1
}

_is_installed_setup_ide() {
  local candidate="$1"

  if [ "$SETUP_CHOICES_DETECTED" != "true" ]; then
    return 0
  fi
  printf '%s\n' "$SETUP_HELP" \
    | grep -Eq "(^|[,{ ])${candidate}(,|[} ])"
}

if ! _is_supported_ide "$IDE"; then
    echo "Error: unsupported IDE '$IDE'"
    echo "Supported: ${SUPPORTED_IDES[*]}"
    exit 1
fi

if ! _is_installed_setup_ide "$IDE"; then
    echo "Error: installed ai-guardian does not support agent '$IDE'"
    echo "Install a release containing this integration or select a supported agent"
    exit 1
fi

case "$SETUP_SCOPE" in
  selected)
    SETUP_AGENT_IDES=("$IDE")
    ;;
  all)
    SETUP_AGENT_IDES=("${SUPPORTED_AGENT_IDES[@]}")
    ;;
  cli)
    SETUP_AGENT_IDES=("${CLI_AGENT_IDES[@]}")
    if ! _is_cli_ide "$IDE"; then
      echo "Error: agent '$IDE' is not a CLI agent supported by OpenShell"
      echo "Supported CLI agents: ${CLI_AGENT_IDES[*]}"
      exit 1
    fi
    ;;
  *)
    echo "Error: unsupported AI_GUARDIAN_SETUP_SCOPE '$SETUP_SCOPE'"
    echo "Supported setup scopes: selected, all, cli"
    exit 1
    ;;
esac

if [ -n "$PROFILE" ] && [ "$HOST_CONFIG_MOUNTED" = "true" ]; then
  echo "Error: AI_GUARDIAN_PROFILE and host config sharing are mutually exclusive"
  exit 1
fi

# OpenShell 0.0.116 transfers --upload files after the canonical process has
# started. The sandbox command marks this initial shell as staging so a required
# host config or custom profile can arrive before setup reads it.  Direct
# container launches retain the fail-fast behavior.
_wait_for_open_shell_upload() {
  local expected_path="$1"
  local description="$2"
  local attempts=0

  if [ "$OPEN_SHELL_STAGING" != "true" ] || [ -f "$expected_path" ]; then
    return 0
  fi

  echo "Waiting for OpenShell to upload ${description}: ${expected_path}"
  while [ ! -f "$expected_path" ]; do
    if [ "$attempts" -ge 1200 ]; then
      echo "Error: timed out waiting for OpenShell upload: $expected_path"
      exit 1
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done
}

if [ "$HOST_CONFIG_MOUNTED" = "true" ] && [ ! -f "$HOST_CONFIG_PATH" ]; then
  if [ "$OPEN_SHELL_STAGING" = "true" ]; then
    _wait_for_open_shell_upload "$HOST_CONFIG_PATH" "host ai-guardian config"
  else
    echo "Error: host ai-guardian config was requested but is missing: $HOST_CONFIG_PATH"
    exit 1
  fi
fi

if [ -n "$PROFILE" ] && [[ "$PROFILE" = /sandbox/* ]] && [ ! -f "$PROFILE" ]; then
  _wait_for_open_shell_upload "$PROFILE" "custom ai-guardian profile"
fi

# Docker's placeholder command makes a bare image run the selected CLI while
# still allowing an explicit command (for example, ``bash -l``) to pass
# through unchanged.
if [ "${1:-}" = "__AI_GUARDIAN_DEFAULT_AGENT__" ]; then
  shift
  if [ "$IDE" = "dummy-agent" ]; then
    set -- ai-guardian dummy-agent "$@"
  else
    set -- "$IDE" "$@"
  fi
fi

# OpenShell's gateway-managed inference route uses a placeholder API key.
# Configure only the documented client environment here. Claude Code's
# documented `--bare` flag remains explicit for interactive use; the
# non-interactive `--print` path below preserves AI Guardian's automation
# behavior without installing a persistent shell wrapper.
_claude_print_command_needs_bare() {
  local argument

  case "${1:-}" in
    auth|config|doctor|help|install|mcp|plugin|update|version|--help|-h|--version|-V)
      return 1
      ;;
  esac

  for argument in "$@"; do
    if [ "$argument" = "--bare" ]; then
      return 1
    fi
  done

  for argument in "$@"; do
    if [ "$argument" = "--print" ]; then
      return 0
    fi
  done
  return 1
}

_configure_openshell_inference_environment() {
  local bash_profile
  local bashrc
  local base_url
  local marker="# ai-guardian-openshell-inference-environment-v1"

  if [ "${AI_GUARDIAN_OPEN_SHELL_INFERENCE:-}" != "true" ]; then
    return 0
  fi

  case "$IDE" in
    claude) base_url="https://inference.local" ;;
    opencode) base_url="https://inference.local/v1" ;;
    *) return 0 ;;
  esac

  bashrc="${HOME}/.bashrc"
  bash_profile="${HOME}/.bash_profile"
  if ! mkdir -p "$HOME"; then
    echo "Error: unable to prepare the sandbox shell for OpenShell inference" >&2
    return 1
  fi

  if ! grep -Fq "$marker" "$bashrc" 2>/dev/null; then
    printf '\n' >>"$bashrc"
cat >>"$bashrc" <<EOF
# $marker
if [ "\${AI_GUARDIAN_OPEN_SHELL_INFERENCE:-}" = "true" ]; then
    # Remove the legacy AI Guardian Claude wrapper if this sandbox was
    # bootstrapped by an older image. Claude's --bare flag stays explicit.
    if [ "\${AI_GUARDIAN_AGENT:-}" = "claude" ]; then
        unset -f claude 2>/dev/null || true
    fi
    export ANTHROPIC_BASE_URL="\${ANTHROPIC_BASE_URL:-$base_url}"
    export ANTHROPIC_API_KEY="\${ANTHROPIC_API_KEY:-unused}"
fi
EOF
  fi

  if ! grep -Fq "$marker" "$bash_profile" 2>/dev/null; then
    printf '\n' >>"$bash_profile"
cat >>"$bash_profile" <<EOF
# $marker
if [ -f "\$HOME/.bashrc" ]; then
    . "\$HOME/.bashrc"
fi
EOF
  fi
}

if [ "${AI_GUARDIAN_OPEN_SHELL_INFERENCE:-}" = "true" ] &&
  { [ "$IDE" = "claude" ] || [ "$IDE" = "opencode" ]; }; then
  # Keep the route self-healing when an older OpenShell version or an existing
  # sandbox omitted the non-secret environment values from sandbox creation.
  if [ "$IDE" = "claude" ]; then
    export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://inference.local}"
  else
    export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://inference.local/v1}"
  fi
  export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-unused}"
  if ! _configure_openshell_inference_environment; then
    exit 1
  fi
  if [ "$IDE" = "claude" ]; then
    case "${1:-}" in
      claude|*/claude)
        if _claude_print_command_needs_bare "${@:2}"; then
          set -- "$1" --bare "${@:2}"
        fi
        ;;
    esac
  fi
fi

# dummy-agent: no API key required — launch REPL directly
if [ "$IDE" = "dummy-agent" ]; then
    echo "Starting ai-guardian daemon..."
    ai-guardian daemon start --background 2>/dev/null || true
    REST_PORT="${AI_GUARDIAN_REST_PORT:-63152}"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  AI Guardian dummy-agent ready (no LLM needed)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Interactive: ai-guardian dummy-agent"
    echo "  Script mode: ai-guardian dummy-agent --script /sandbox/scenarios/basic-secret.yaml"
    echo "  Web console: http://localhost:${REST_PORT}"
    echo "  Version:     $(ai-guardian --version 2>/dev/null || echo 'unknown')"
    echo ""
    exec "$@"
fi

# Codex reads OAuth state from auth.json rather than from the provider-specific
# CODEX_AUTH_* environment variables. OpenShell supplies those variables as
# opaque placeholders, so materialize only the placeholders in Codex's normal
# auth format. The id token is parsed locally by Codex and must be JWT-shaped;
# it is intentionally synthetic and contains no real user or account data.
_bootstrap_codex_openshell_auth() {
  local codex_home
  local auth_path

  if [ "$IDE" != "codex" ]; then
    return 0
  fi

  codex_home="${CODEX_HOME:-${HOME}/.codex}"
  auth_path="${codex_home}/auth.json"
  if ! mkdir -p "$codex_home"; then
    echo "Error: unable to create Codex state directory: $codex_home" >&2
    return 1
  fi

  if [ "${AI_GUARDIAN_OPEN_SHELL_PROVIDER:-false}" != "true" ]; then
    return 0
  fi

  if [ -z "${CODEX_AUTH_ACCESS_TOKEN:-}" ] ||
    [ -z "${CODEX_AUTH_REFRESH_TOKEN:-}" ] ||
    [ -z "${CODEX_AUTH_ACCOUNT_ID:-}" ]; then
    if [ -z "${OPENAI_API_KEY:-}" ]; then
      # This may be an explicitly supplied provider with a different credential
      # shape. Leave providers without a Codex-compatible credential alone.
      return 0
    fi

    # Codex reads API-key authentication from auth.json as well. OpenShell
    # injects OPENAI_API_KEY as an opaque placeholder, so let Codex write that
    # placeholder in its native format without exposing the real key.
    if ! printf '%s\n' "$OPENAI_API_KEY" | codex login --with-api-key >/dev/null 2>&1; then
      echo "Error: unable to create provider-backed Codex API-key auth file: $auth_path" >&2
      return 1
    fi
    echo "Configured Codex API-key authentication from the OpenShell provider"
    return 0
  fi

  if ! python3 - "$auth_path" <<'PY'
import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timezone


def _jwt_part(value):
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


now = int(datetime.now(timezone.utc).timestamp())
synthetic_id_token = ".".join(
    (
        _jwt_part({"alg": "none", "typ": "JWT"}),
        _jwt_part(
            {
                "iss": "https://auth.openai.com",
                "aud": "codex",
                "sub": "openshell-sandbox",
                "email": "openshell@localhost",
                "iat": now,
                "exp": now + 3600,
            }
        ),
        "openshell-placeholder-signature",
    )
)
auth = {
    "OPENAI_API_KEY": None,
    "auth_mode": "chatgpt",
    "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "tokens": {
        "access_token": os.environ["CODEX_AUTH_ACCESS_TOKEN"],
        "refresh_token": os.environ["CODEX_AUTH_REFRESH_TOKEN"],
        "account_id": os.environ["CODEX_AUTH_ACCOUNT_ID"],
        "id_token": synthetic_id_token,
    },
}

auth_path = sys.argv[1]
auth_dir = os.path.dirname(auth_path)
os.makedirs(auth_dir, exist_ok=True)
file_descriptor, temporary_path = tempfile.mkstemp(
    prefix=".auth.json.", suffix=".tmp", dir=auth_dir
)
try:
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
        json.dump(auth, stream, separators=(",", ":"))
        stream.write("\n")
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, auth_path)
except Exception:
    try:
        os.unlink(temporary_path)
    except OSError:
        # intentionally silent — cleanup of the temporary auth file
        pass
    raise
PY
  then
    echo "Error: unable to create provider-backed Codex auth file: $auth_path" >&2
    return 1
  fi
}

if ! _bootstrap_codex_openshell_auth; then
  exit 1
fi

# Proprietary CLIs — install at runtime with ToS consent. Only the selected
# agent is started; all supported integrations are configured below.
if [ "$IDE" = "claude" ] && ! command -v claude >/dev/null 2>&1; then
  if _request_tos_consent "Claude Code" "https://www.anthropic.com/legal/consumer-terms"; then
    curl -fsSL https://claude.ai/install.sh | sh
    chmod 755 "${HOME}/.local/bin/claude" 2>/dev/null || true
  fi
fi

if [ "$IDE" = "kiro" ] && ! command -v kiro >/dev/null 2>&1; then
  if _request_tos_consent "Kiro CLI" "https://kiro.dev/license/"; then
    _kiro_arch=$(uname -m)
    curl --proto '=https' --tlsv1.2 -sSf \
      "https://desktop-release.q.us-east-1.amazonaws.com/latest/kirocli-${_kiro_arch}-linux.zip" \
      -o /tmp/kirocli.zip
    cd /tmp
    python3 -c "import zipfile; zipfile.ZipFile('kirocli.zip').extractall()"
    chmod +x kirocli/install.sh
    ./kirocli/install.sh --no-confirm
    rm -rf /tmp/kirocli*
    cd /sandbox
  fi
fi

# Custom GitLab host — glab needs explicit config since it can't infer the host from GITLAB_TOKEN alone
if [[ -n "${GITLAB_TOKEN:-}" && -n "${GITLAB_HOST:-}" ]]; then
    glab auth login --hostname "$GITLAB_HOST" --token "$GITLAB_TOKEN" 2>/dev/null || true
fi
# gitlab.com: glab reads GITLAB_TOKEN natively, no action needed
# gh: reads GH_TOKEN / GITHUB_TOKEN natively, no action needed

if [ "$IDE" != "dummy-agent" ]; then
    # Apply the shared configuration precedence. Explicit profiles are
    # intentional overrides, followed by an explicit restored snapshot. An
    # existing sandbox-local config then wins over a normal host fallback, and
    # only then do we use the host config or generate a default config.
    if [ -n "$PROFILE" ]; then
        echo "Creating ai-guardian config from profile: $PROFILE"
        if ! ai-guardian setup --ide "$IDE" --create-config --profile "$PROFILE" \
            --force --yes; then
            echo "Error: unable to create ai-guardian config from profile: $PROFILE"
            exit 1
        fi
        CONFIG_SOURCE="profile"
        CONFIG_READ_ONLY="false"
    elif [ "$RESTORE_CONFIG" = "true" ] && [ "$HOST_CONFIG_MOUNTED" = "true" ]; then
        if [ "$HOST_CONFIG_PATH" = "$CONFIG_PATH" ]; then
            echo "Error: restored config snapshot must be staged outside active config path"
            exit 1
        fi
        mkdir -p "$(dirname "$CONFIG_PATH")"
        if ! cp "$HOST_CONFIG_PATH" "$CONFIG_PATH"; then
            echo "Error: unable to restore ai-guardian config snapshot: $HOST_CONFIG_PATH"
            exit 1
        fi
        echo "Restoring ai-guardian config snapshot"
        CONFIG_SOURCE="snapshot"
        CONFIG_READ_ONLY="false"
        if ! ai-guardian setup --ide "$IDE" --force --yes; then
            echo "Error: unable to configure selected IDE: $IDE"
            exit 1
        fi
    elif [ -f "$CONFIG_PATH" ] &&
        { [ "$HOST_CONFIG_MOUNTED" != "true" ] ||
          [ "$HOST_CONFIG_PATH" != "$CONFIG_PATH" ]; }; then
        echo "Using sandbox-local ai-guardian config: $CONFIG_PATH"
        CONFIG_SOURCE="sandbox-local"
        CONFIG_READ_ONLY="false"
        if ! ai-guardian setup --ide "$IDE" --force --yes; then
            echo "Error: unable to configure selected IDE: $IDE"
            exit 1
        fi
    elif [ "$HOST_CONFIG_MOUNTED" = "true" ]; then
        if [ "$HOST_CONFIG_PATH" != "$CONFIG_PATH" ]; then
            mkdir -p "$(dirname "$CONFIG_PATH")"
            if ! cp "$HOST_CONFIG_PATH" "$CONFIG_PATH"; then
                echo "Error: unable to stage host ai-guardian config: $HOST_CONFIG_PATH"
                exit 1
            fi
        fi
        CONFIG_SOURCE="host"
        if [ "$HOST_CONFIG_PATH" != "$CONFIG_PATH" ]; then
            echo "Using host ai-guardian config snapshot"
            # The host file is mounted/uploaded beside the active config.  The
            # active copy belongs to this sandbox and is intentionally
            # writable; the host file is never written back.
            CONFIG_READ_ONLY="false"
        else
            # Preserve compatibility with older direct read-only mounts that
            # place the host file over the active config path.
            echo "Using read-only host ai-guardian config"
            CONFIG_READ_ONLY="true"
        fi
        if ! ai-guardian setup --ide "$IDE" --force --yes; then
            echo "Error: unable to configure selected IDE: $IDE"
            exit 1
        fi
    else
        echo "Creating sandbox-local ai-guardian config"
        if ! ai-guardian setup --ide "$IDE" --create-config --force --yes; then
            echo "Error: unable to create sandbox-local ai-guardian config"
            exit 1
        fi
        CONFIG_SOURCE="sandbox-local"
        CONFIG_READ_ONLY="false"
    fi

    # Configure every supported integration so a runtime agent selection does
    # not leave the selected agent unprotected. GUI-only integrations receive
    # their hooks/bridges even when their GUI executable is not in the image.
    if [ "$SETUP_SCOPE" = "selected" ]; then
        echo "Configuring ai-guardian for selected agent: $IDE"
    else
        echo "Configuring ai-guardian for all supported agents"
    fi
    for setup_ide in "${SETUP_AGENT_IDES[@]}"; do
        if [ "$setup_ide" = "$IDE" ]; then
            continue
        fi
        if ! _is_installed_setup_ide "$setup_ide"; then
            echo "  Skipping: $setup_ide (not supported by installed ai-guardian)"
            continue
        fi
        echo "  Configuring: $setup_ide"
        if ! ai-guardian setup --ide "$setup_ide" --force --yes; then
            echo "Error: unable to configure supported agent: $setup_ide"
            exit 1
        fi
    done

    if [ ! -f "$CONFIG_PATH" ]; then
        echo "Error: setup completed but config file missing: $CONFIG_PATH"
        exit 1
    fi

    # A later `podman exec`/`docker exec` process does not inherit exports made
    # by this entrypoint. Persist the effective source and write capability so
    # a connected TUI or CLI sees the same sandbox snapshot semantics.
    if ! python3 - "$CONFIG_METADATA_PATH" "$CONFIG_SOURCE" "$CONFIG_READ_ONLY" <<'PY'
import json
import os
import sys
import tempfile


metadata_path, source, read_only = sys.argv[1:]
metadata_dir = os.path.dirname(os.path.abspath(metadata_path))
os.makedirs(metadata_dir, exist_ok=True)
metadata = {"source": source, "read_only": read_only.lower() == "true"}
file_descriptor, temporary_path = tempfile.mkstemp(
    prefix=".config-metadata.", suffix=".tmp", dir=metadata_dir
)
try:
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, separators=(",", ":"))
        stream.write("\n")
    os.replace(temporary_path, metadata_path)
except Exception:
    try:
        os.unlink(temporary_path)
    except OSError:
        # intentionally silent — cleanup of the temporary metadata file
        pass
    raise
PY
    then
        echo "Warning: unable to persist ai-guardian config metadata: $CONFIG_METADATA_PATH" >&2
    fi
else
    CONFIG_SOURCE="not used (dummy-agent)"
    CONFIG_READ_ONLY="false"
fi

# The daemon and console use these markers to expose and enforce whether the
# effective config is managed by the host.  The explicit source marker also
# lets a sandbox-local config win while a host fallback is staged alongside it.
export AI_GUARDIAN_CONFIG_SOURCE="$CONFIG_SOURCE"
export AI_GUARDIAN_CONFIG_READ_ONLY="$CONFIG_READ_ONLY"

# OpenShell is already the outer sandbox. Configure Codex to use its full
# access mode inside that outer boundary so Codex does not start a nested
# bubblewrap sandbox/user namespace. The setting is written only to the
# sandbox-local CODEX_HOME.
_configure_codex_sandbox_mode() {
  local codex_home
  local config_path
  local sandbox_mode

  if [ "$IDE" != "codex" ] ||
    [ -z "${AI_GUARDIAN_CODEX_SANDBOX_MODE:-}" ]; then
    return 0
  fi

  sandbox_mode="$AI_GUARDIAN_CODEX_SANDBOX_MODE"
  case "$sandbox_mode" in
    read-only|workspace-write|danger-full-access)
      ;;
    *)
      echo "Error: unsupported AI_GUARDIAN_CODEX_SANDBOX_MODE: $sandbox_mode" >&2
      echo "Supported modes: read-only, workspace-write, danger-full-access" >&2
      return 1
      ;;
  esac

  codex_home="${CODEX_HOME:-${HOME}/.codex}"
  config_path="${codex_home}/config.toml"
  if ! python3 - "$config_path" "$sandbox_mode" <<'PY'
import os
import re
import stat
import sys
import tempfile


config_path = sys.argv[1]
sandbox_mode = sys.argv[2]
try:
    with open(config_path, encoding="utf-8") as stream:
        lines = stream.readlines()
except FileNotFoundError:
    lines = []

table_header = re.compile(r"^\s*\[")
mode_key = re.compile(r"^(\s*)sandbox_mode\s*=.*?(\r?\n)?$")
first_table_index = None
top_level_mode_index = None

for index, line in enumerate(lines):
    line_without_ending = line.rstrip("\r\n")
    if first_table_index is None and table_header.match(line_without_ending):
        first_table_index = index
    if first_table_index is None and mode_key.match(line_without_ending):
        top_level_mode_index = index
        break

if top_level_mode_index is not None:
    line = lines[top_level_mode_index]
    line_ending = "\r\n" if line.endswith("\r\n") else "\n"
    indentation = mode_key.match(line).group(1)
    lines[top_level_mode_index] = (
        f'{indentation}sandbox_mode = "{sandbox_mode}"{line_ending}'
    )
else:
    insertion_index = (
        first_table_index if first_table_index is not None else len(lines)
    )
    lines.insert(insertion_index, f'sandbox_mode = "{sandbox_mode}"\n')

config_dir = os.path.dirname(os.path.abspath(config_path))
os.makedirs(config_dir, exist_ok=True)
try:
    mode = stat.S_IMODE(os.stat(config_path).st_mode)
except FileNotFoundError:
    mode = 0o600

file_descriptor, temporary_path = tempfile.mkstemp(
    prefix=".config.toml.", suffix=".tmp", dir=config_dir
)
try:
    with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.writelines(lines)
    os.chmod(temporary_path, mode)
    os.replace(temporary_path, config_path)
except Exception:
    try:
        os.unlink(temporary_path)
    except OSError:
        # intentionally silent — cleanup of the temporary config file
        pass
    raise
PY
  then
    echo "Error: unable to configure Codex sandbox mode: $config_path" >&2
    return 1
  fi
  echo "Configured Codex sandbox mode: $sandbox_mode"
}

# Direct Docker/Podman users may still opt into Codex's inner network gate.
# OpenShell sets AI_GUARDIAN_CODEX_SANDBOX_MODE instead, so the two modes never
# write conflicting Codex settings.
_configure_codex_sandbox_network_access() {
  local codex_home
  local config_path

  if [ "$IDE" != "codex" ] ||
    [ "${AI_GUARDIAN_CODEX_NETWORK_ACCESS:-false}" != "true" ]; then
    return 0
  fi

  codex_home="${CODEX_HOME:-${HOME}/.codex}"
  config_path="${codex_home}/config.toml"
  if ! python3 - "$config_path" <<'PY'
import os
import re
import stat
import sys
import tempfile


config_path = sys.argv[1]
try:
    with open(config_path, encoding="utf-8") as stream:
        lines = stream.readlines()
except FileNotFoundError:
    lines = []

table_header = re.compile(
    r"^\s*(\[\[?)([^\]]+)(\]\]?)\s*(?:#.*)?$"
)
key_pattern = re.compile(r"^(\s*)network_access\s*=")
section_start = None
section_end = len(lines)

for index, line in enumerate(lines):
    match = table_header.match(line.rstrip("\r\n"))
    if not match:
        continue
    if section_start is not None:
        section_end = index
        break
    if (
        match.group(1) == "["
        and match.group(3) == "]"
        and match.group(2).strip() == "sandbox_workspace_write"
    ):
        section_start = index

if section_start is None:
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n"
    if lines and lines[-1].strip():
        lines.append("\n")
    lines.extend(
        ["[sandbox_workspace_write]\n", "network_access = true\n"]
    )
else:
    for index in range(section_start + 1, section_end):
        match = key_pattern.match(lines[index])
        if match:
            line_ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
            lines[index] = f"{match.group(1)}network_access = true{line_ending}"
            break
    else:
        lines.insert(section_end, "network_access = true\n")

config_dir = os.path.dirname(os.path.abspath(config_path))
os.makedirs(config_dir, exist_ok=True)
try:
    mode = stat.S_IMODE(os.stat(config_path).st_mode)
except FileNotFoundError:
    mode = 0o600

file_descriptor, temporary_path = tempfile.mkstemp(
    prefix=".config.toml.", suffix=".tmp", dir=config_dir
)
try:
    with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.writelines(lines)
    os.chmod(temporary_path, mode)
    os.replace(temporary_path, config_path)
except Exception:
    try:
        os.unlink(temporary_path)
    except OSError:
        # intentionally silent — cleanup of the temporary config file
        pass
    raise
PY
  then
    echo "Error: unable to configure Codex network access: $config_path" >&2
    return 1
  fi
  echo "Configured Codex workspace-write network access: true"
}

if ! _configure_codex_sandbox_mode; then
  exit 1
fi

if [ -z "${AI_GUARDIAN_CODEX_SANDBOX_MODE:-}" ] &&
  ! _configure_codex_sandbox_network_access; then
  exit 1
fi

echo "Starting ai-guardian daemon..."
ai-guardian daemon start --background 2>/dev/null || true

REST_PORT="${AI_GUARDIAN_REST_PORT:-63152}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AI Guardian support container ready"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Agent:        $IDE"
    if [ "$SETUP_SCOPE" = "selected" ]; then
      echo "  Setup:        selected agent"
    elif [ "$SETUP_SCOPE" = "cli" ]; then
  echo "  Setup:        supported CLI agents"
else
  echo "  Setup:        all supported agents"
fi
echo "  Profile:      ${PROFILE:-none (host/default config)}"
echo "  Config:       $CONFIG_PATH"
echo "  Config source: $CONFIG_SOURCE"
if [ "${AI_GUARDIAN_OPEN_SHELL_INFERENCE:-}" = "true" ]; then
    echo "  Auth:         OpenShell inference route"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  Auth:         Anthropic API key"
elif [ -n "${ANTHROPIC_VERTEX_PROJECT_ID:-}" ]; then
    echo "  Auth:         Vertex AI"
else
    echo "  Auth:         not configured"
fi
if [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
    echo "  GitHub:       token set"
fi
if [ -n "${GITLAB_TOKEN:-}" ]; then
    echo "  GitLab:       token set${GITLAB_HOST:+ (${GITLAB_HOST})}"
fi
echo "  Web console:  http://localhost:${REST_PORT} (internal port to find host port run: podman port \$(hostname))"
echo "  Doctor:       ai-guardian doctor"
echo "  Version:      $(ai-guardian --version 2>/dev/null || echo 'unknown')"
echo ""

exec "$@"
