#!/usr/bin/env bash
set -euo pipefail

# ai-guardian container launcher
#
# Usage:
#   ./container/run.sh                              # defaults: Codex, local config
#   ./container/run.sh --agent opencode
#   ./container/run.sh --profile @strict
#   ./container/run.sh --agent gemini --profile @minimal
#   ./container/run.sh --config-dir "$HOME/.config/ai-guardian"
#   ./container/run.sh --repo ~/myproject
#   ./container/run.sh --api-key sk-ant-...         # direct Anthropic API
#   ./container/run.sh --                           # pass extra args to container
#   ./container/run.sh -- bash -c "ai-guardian scan ."

IMAGE="${AI_GUARDIAN_IMAGE:-quay.io/redhatproductsecurity/ai-guardian:latest}"
IDE="${AI_GUARDIAN_AGENT:-${AI_GUARDIAN_IDE:-codex}}"
PROFILE="${AI_GUARDIAN_PROFILE:-}"
REST_PORT="${AI_GUARDIAN_REST_PORT:-63152}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
REPO_PATH=""
API_KEY="${ANTHROPIC_API_KEY:-}"
API_KEY_FROM_FLAG="false"
CONFIG_DIR_OVERRIDE=""
EXTRA_ARGS=()
SETUP_SCOPE="${AI_GUARDIAN_SETUP_SCOPE:-selected}"

SUPPORTED_AGENTS=(
    claude cursor copilot codex windsurf gemini cline zoocode kiro
    aiderdesk openclaw opencode augment crush junie antigravity dummy-agent
)

_require_option_value() {
    if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "Error: $1 requires a value" >&2
        exit 2
    fi
}

_is_supported_agent() {
    local candidate="$1"
    local supported_agent
    for supported_agent in "${SUPPORTED_AGENTS[@]}"; do
        if [[ "$candidate" = "$supported_agent" ]]; then
            return 0
        fi
    done
    return 1
}

_print_help() {
    echo "Usage: $0 [OPTIONS] [-- COMMAND...]"
    echo ""
    echo "Options:"
    echo "  --agent, --ide NAME       Select the agent (default: codex)"
    echo "  --profile NAME             Use a bundled or custom security profile"
    echo "  --config-dir, --guardian-home DIR"
    echo "                             Host ai-guardian config directory"
    echo "  --repo DIR                 Mount a repository at /sandbox/repo"
    echo "  --port PORT                Publish the daemon port"
    echo "  --base, --image IMAGE      Select the container image"
    echo "  --api-key KEY              Pass an Anthropic API key"
    echo "  --                        Pass the remaining arguments to the container"
    echo ""
    echo "Supported agents: ${SUPPORTED_AGENTS[*]}"
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent|--ide)
            _require_option_value "$@"
            IDE="$2"
            shift 2
            ;;
        --profile)
            _require_option_value "$@"
            PROFILE="$2"
            shift 2
            ;;
        --config-dir|--guardian-home)
            _require_option_value "$@"
            CONFIG_DIR_OVERRIDE="$2"
            shift 2
            ;;
        --repo)
            _require_option_value "$@"
            REPO_PATH="$2"
            shift 2
            ;;
        --port)
            _require_option_value "$@"
            REST_PORT="$2"
            shift 2
            ;;
        --base|--image)
            _require_option_value "$@"
            IMAGE="$2"
            shift 2
            ;;
        --api-key)
            _require_option_value "$@"
            API_KEY="$2"
            API_KEY_FROM_FLAG="true"
            shift 2
            ;;
        --help|-h)
            _print_help
            exit 0
            ;;
        --)          shift; EXTRA_ARGS=("$@"); break ;;
        *)           EXTRA_ARGS+=("$1"); shift ;;
    esac
done

if ! _is_supported_agent "$IDE"; then
    echo "Error: unsupported agent '$IDE'" >&2
    echo "Supported: ${SUPPORTED_AGENTS[*]}" >&2
    exit 2
fi

if [[ ${#EXTRA_ARGS[@]} -eq 0 ]]; then
    EXTRA_ARGS=("$IDE")
fi

# --- Resolve the host ai-guardian configuration directory ---
# Explicit CLI option wins, followed by the two supported ai-guardian
# overrides, then XDG.  If HOME is unavailable (some agent launchers only
# export their own home variable), infer the user's home from that variable.
HOST_HOME="${HOME:-}"
if [[ -z "$HOST_HOME" ]]; then
    for agent_home_var in \
        CODEX_HOME CLAUDE_CONFIG_DIR CURSOR_CONFIG_DIR COPILOT_HOME \
        GEMINI_CLI_HOME CLINE_DATA_DIR KIRO_HOME JUNIE_HOME \
        AIDER_DESK_DIR AIDER_DESK_HOME_DIR OPENCLAW_STATE_DIR OPENCLAW_HOME \
        OPENCODE_CONFIG_DIR; do
        agent_home="${!agent_home_var:-}"
        if [[ -n "$agent_home" ]]; then
            case "$agent_home_var" in
                GEMINI_CLI_HOME|OPENCLAW_HOME) HOST_HOME="$agent_home" ;;
                *)
                    case "$agent_home" in
                        */*) HOST_HOME="${agent_home%/*}" ;;
                        *) HOST_HOME="${PWD:-.}" ;;
                    esac
                    ;;
            esac
            break
        fi
    done
fi
HOST_HOME="${HOST_HOME:-${PWD:-.}}"

if [[ -n "$CONFIG_DIR_OVERRIDE" ]]; then
    HOST_CONFIG_DIR="$CONFIG_DIR_OVERRIDE"
elif [[ -n "${AI_GUARDIAN_CONFIG_DIR:-}" ]]; then
    HOST_CONFIG_DIR="$AI_GUARDIAN_CONFIG_DIR"
elif [[ -n "${AI_GUARDIAN_HOME:-}" ]]; then
    HOST_CONFIG_DIR="$AI_GUARDIAN_HOME"
elif [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
    HOST_CONFIG_DIR="${XDG_CONFIG_HOME}/ai-guardian"
else
    HOST_CONFIG_DIR="${HOST_HOME}/.config/ai-guardian"
fi
HOST_CONFIG_PATH="${HOST_CONFIG_DIR}/ai-guardian.json"

# --- Build env var list ---
CONTAINER_CONFIG_DIR="/sandbox/.config/ai-guardian"
# Keep a host config beside the active sandbox config so an existing
# sandbox-local file can take precedence at container startup.
HOST_CONFIG_FALLBACK_PATH="/sandbox/.config/ai-guardian.host.json"
HOST_CONFIG_MOUNTED="false"
CONFIG_SOURCE="sandbox-local"
env_args=(
    -e "AI_GUARDIAN_AGENT=${IDE}"
    -e "AI_GUARDIAN_IDE=${IDE}"
    -e "AI_GUARDIAN_REST_PORT=${REST_PORT}"
    -e "AI_GUARDIAN_CONFIG_DIR=${CONTAINER_CONFIG_DIR}"
    -e "AI_GUARDIAN_HOME=${CONTAINER_CONFIG_DIR}"
    -e "AI_GUARDIAN_SETUP_SCOPE=${SETUP_SCOPE}"
)

if [[ -n "$PROFILE" ]]; then
    CONFIG_SOURCE="profile"
fi

# --- Volume mounts ---
volume_args=()
[[ -n "$REPO_PATH" ]] && volume_args+=(-v "${REPO_PATH}:/sandbox/repo")

# A profile is intentionally mutually exclusive with the host's complete
# config.  A custom profile file may be copied into the sandbox read-only;
# built-in profiles remain entirely sandbox-local.
PROFILE_MOUNT_SOURCE=""
PROFILE_MOUNT_TARGET=""
if [[ -n "$PROFILE" ]]; then
    case "$PROFILE" in
        @*)
            ;;
        /*|./*|../*)
            if [[ ! -f "$PROFILE" ]]; then
                echo "Error: custom profile file not found: $PROFILE" >&2
                exit 2
            fi
            PROFILE_MOUNT_SOURCE="$PROFILE"
            PROFILE_MOUNT_TARGET="${CONTAINER_CONFIG_DIR}/profiles/${PROFILE##*/}"
            ;;
        *)
            profile_candidate="${HOST_CONFIG_DIR}/profiles/${PROFILE}"
            [[ "$profile_candidate" != *.json ]] && profile_candidate="${profile_candidate}.json"
            if [[ -f "$profile_candidate" ]]; then
                PROFILE_MOUNT_SOURCE="$profile_candidate"
                PROFILE_MOUNT_TARGET="${CONTAINER_CONFIG_DIR}/profiles/${profile_candidate##*/}"
            fi
            ;;
    esac
    if [[ -n "$PROFILE_MOUNT_SOURCE" ]]; then
        volume_args+=(-v "${PROFILE_MOUNT_SOURCE}:${PROFILE_MOUNT_TARGET}:ro,z")
        env_args+=(-e "AI_GUARDIAN_PROFILE=${PROFILE_MOUNT_TARGET}")
        CONFIG_SOURCE="profile (host file, read-only)"
    else
        env_args+=(-e "AI_GUARDIAN_PROFILE=${PROFILE}")
    fi
else
    if [[ -f "$HOST_CONFIG_PATH" ]]; then
        volume_args+=(-v "${HOST_CONFIG_PATH}:${HOST_CONFIG_FALLBACK_PATH}:ro,z")
        env_args+=(
            -e "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true"
            -e "AI_GUARDIAN_HOST_CONFIG_PATH=${HOST_CONFIG_FALLBACK_PATH}"
        )
        HOST_CONFIG_MOUNTED="true"
        CONFIG_SOURCE="host config fallback (snapshot)"
    else
        if [[ -n "$CONFIG_DIR_OVERRIDE" || -n "${AI_GUARDIAN_CONFIG_DIR:-}" || -n "${AI_GUARDIAN_HOME:-}" ]]; then
            echo "Notice: host ai-guardian config not found at ${HOST_CONFIG_PATH}; using sandbox-local config" >&2
        fi
    fi
fi
if [[ "$HOST_CONFIG_MOUNTED" = "false" ]]; then
    env_args+=(-e "AI_GUARDIAN_HOST_CONFIG_MOUNTED=false")
fi

# --- Authentication ---
# Priority: --api-key flag > Vertex AI auto-detect > API key environment
VERTEX_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-${VERTEX_AI_PROJECT_ID:-}}"
VERTEX_REGION="${CLOUD_ML_REGION:-${VERTEX_AI_REGION:-global}}"
if [[ "$API_KEY_FROM_FLAG" = "true" ]]; then
    env_args+=(-e "ANTHROPIC_API_KEY=${API_KEY}")
elif [[ -n "$VERTEX_PROJECT" ]]; then
    env_args+=(
        -e "CLAUDE_CODE_USE_VERTEX=1"
        -e "ANTHROPIC_VERTEX_PROJECT_ID=${VERTEX_PROJECT}"
        -e "CLOUD_ML_REGION=${VERTEX_REGION}"
    )
    # Mount GCP credentials
    ADC_PATH="${GOOGLE_APPLICATION_CREDENTIALS:-${HOST_HOME}/.config/gcloud/application_default_credentials.json}"
    if [[ -f "$ADC_PATH" ]]; then
        env_args+=(
            -e "GOOGLE_APPLICATION_CREDENTIALS=/sandbox/.config/gcloud/application_default_credentials.json"
        )
        volume_args+=(-v "${ADC_PATH}:/sandbox/.config/gcloud/application_default_credentials.json:ro")
    else
        echo "Warning: GCP credentials not found at ${ADC_PATH}" >&2
        echo "  Run: gcloud auth application-default login" >&2
        echo "  Or set GOOGLE_APPLICATION_CREDENTIALS" >&2
    fi
elif [[ -n "$API_KEY" ]]; then
    export ANTHROPIC_API_KEY="$API_KEY"
    env_args+=(-e "ANTHROPIC_API_KEY")
fi

# --- Common agent credentials (forward only explicitly supported variables) ---
_forward_env() {
    local env_name="$1"
    local env_value="${!env_name:-}"
    if [[ -n "$env_value" ]]; then
        env_args+=(-e "${env_name}")
    fi
}

for common_env_name in \
    OPENAI_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY GOOGLE_API_KEY \
    COPILOT_GITHUB_TOKEN AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
    AWS_SESSION_TOKEN AWS_REGION AWS_DEFAULT_REGION \
    AZURE_OPENAI_API_KEY AZURE_OPENAI_ENDPOINT; do
    _forward_env "$common_env_name"
done

# --- Proprietary CLI ToS bypass (forward from host if set) ---
[[ -n "${ACCEPT_PROPRIETARY_TOS:-}" ]] && env_args+=(-e "ACCEPT_PROPRIETARY_TOS")

# --- Forge tokens (all optional — forward from host if set) ---
[[ -n "${GH_TOKEN:-}" ]]       && env_args+=(-e "GH_TOKEN")
[[ -n "${GITHUB_TOKEN:-}" ]]   && env_args+=(-e "GITHUB_TOKEN")
[[ -n "${GITLAB_TOKEN:-}" ]]   && env_args+=(-e "GITLAB_TOKEN")
[[ -n "${GITLAB_HOST:-}" ]]    && env_args+=(-e "GITLAB_HOST")

# --- Launch ---
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AI Guardian Support Container"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Image:    ${IMAGE}"
echo "  Engine:   ${CONTAINER_ENGINE}"
echo "  Agent:    ${IDE}"
echo "  Setup:    ${SETUP_SCOPE}"
echo "  Profile:  ${PROFILE:-none (host/default config)}"
echo "  Config:   ${CONFIG_SOURCE}"
echo "  Port:     ${REST_PORT}"
[[ -n "$REPO_PATH" ]] && echo "  Repo:     ${REPO_PATH}"
if [[ "$API_KEY_FROM_FLAG" = "true" || ( -n "$API_KEY" && -z "$VERTEX_PROJECT" ) ]]; then
    echo "  Auth:     Anthropic API key"
elif [[ -n "$VERTEX_PROJECT" ]]; then
    echo "  Auth:     Vertex AI"
fi
[[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]] \
    && echo "  GitHub:   token set" \
    || echo "  GitHub:   no token (export GH_TOKEN to enable)"
[[ -n "${GITLAB_TOKEN:-}" ]] \
    && echo "  GitLab:   token set${GITLAB_HOST:+ (${GITLAB_HOST})}" \
    || echo "  GitLab:   no token (export GITLAB_TOKEN to enable)"
echo ""

if [[ ${#volume_args[@]} -gt 0 ]]; then
    exec "$CONTAINER_ENGINE" run -it --rm \
        -p "${REST_PORT}" \
        "${env_args[@]}" \
        "${volume_args[@]}" \
        "${IMAGE}" \
        "${EXTRA_ARGS[@]}"
fi

exec "$CONTAINER_ENGINE" run -it --rm \
    -p "${REST_PORT}" \
    "${env_args[@]}" \
    "${IMAGE}" \
    "${EXTRA_ARGS[@]}"
