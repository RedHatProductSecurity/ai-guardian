#!/usr/bin/env bash
set -euo pipefail

# ai-guardian container launcher
#
# Usage:
#   ./container/run.sh                              # defaults: claude, standard profile
#   ./container/run.sh --ide opencode
#   ./container/run.sh --profile @strict
#   ./container/run.sh --ide gemini --profile @minimal
#   ./container/run.sh --repo ~/myproject
#   ./container/run.sh --api-key sk-ant-...         # direct Anthropic API
#   ./container/run.sh --                           # pass extra args to container run
#   ./container/run.sh -- bash -c "ai-guardian scan ."

IMAGE="${AI_GUARDIAN_IMAGE:-quay.io/redhatproductsecurity/ai-guardian:latest}"
IDE="${AI_GUARDIAN_IDE:-claude}"
PROFILE="${AI_GUARDIAN_PROFILE:-}"
REST_PORT="${AI_GUARDIAN_REST_PORT:-63152}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
REPO_PATH=""
API_KEY="${ANTHROPIC_API_KEY:-}"
EXTRA_ARGS=()

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ide)       IDE="$2"; shift 2 ;;
        --profile)   PROFILE="$2"; shift 2 ;;
        --repo)      REPO_PATH="$2"; shift 2 ;;
        --port)      REST_PORT="$2"; shift 2 ;;
        --image)     IMAGE="$2"; shift 2 ;;
        --api-key)   API_KEY="$2"; shift 2 ;;
        --)          shift; EXTRA_ARGS=("$@"); break ;;
        *)           EXTRA_ARGS+=("$1"); shift ;;
    esac
done

# --- Build env var list ---
env_args=(
    -e "AI_GUARDIAN_IDE=${IDE}"
    -e "AI_GUARDIAN_REST_PORT=${REST_PORT}"
)

[[ -n "$PROFILE" ]] && env_args+=(-e "AI_GUARDIAN_PROFILE=${PROFILE}")

# --- Volume mounts ---
volume_args=()
[[ -n "$REPO_PATH" ]] && volume_args+=(-v "${REPO_PATH}:/sandbox/repo")

# --- Authentication ---
# Priority: --api-key flag > ANTHROPIC_API_KEY env > Vertex AI auto-detect
if [[ -n "$API_KEY" ]]; then
    env_args+=(-e "ANTHROPIC_API_KEY=${API_KEY}")
elif [[ -n "${ANTHROPIC_VERTEX_PROJECT_ID:-}" ]]; then
    env_args+=(
        -e "CLAUDE_CODE_USE_VERTEX=1"
        -e "ANTHROPIC_VERTEX_PROJECT_ID=${ANTHROPIC_VERTEX_PROJECT_ID}"
        -e "CLOUD_ML_REGION=${CLOUD_ML_REGION:-global}"
    )
    # Mount GCP credentials
    ADC_PATH="${GOOGLE_APPLICATION_CREDENTIALS:-${HOME}/.config/gcloud/application_default_credentials.json}"
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
fi

# --- Proprietary CLI ToS bypass (forward from host if set) ---
[[ -n "${ACCEPT_PROPRIETARY_TOS:-}" ]] && env_args+=(-e "ACCEPT_PROPRIETARY_TOS=${ACCEPT_PROPRIETARY_TOS}")

# --- Forge tokens (all optional — forward from host if set) ---
[[ -n "${GH_TOKEN:-}" ]]       && env_args+=(-e "GH_TOKEN=${GH_TOKEN}")
[[ -n "${GITHUB_TOKEN:-}" ]]   && env_args+=(-e "GITHUB_TOKEN=${GITHUB_TOKEN}")
[[ -n "${GITLAB_TOKEN:-}" ]]   && env_args+=(-e "GITLAB_TOKEN=${GITLAB_TOKEN}")
[[ -n "${GITLAB_HOST:-}" ]]    && env_args+=(-e "GITLAB_HOST=${GITLAB_HOST}")

# --- Launch ---
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AI Guardian Support Container"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Image:    ${IMAGE}"
echo "  Engine:   ${CONTAINER_ENGINE}"
echo "  IDE:      ${IDE}"
echo "  Profile:  ${PROFILE:-standard (default)}"
echo "  Port:     ${REST_PORT}"
[[ -n "$REPO_PATH" ]] && echo "  Repo:     ${REPO_PATH}"
[[ -n "$API_KEY" ]] && echo "  Auth:     Anthropic API key"
[[ -n "${ANTHROPIC_VERTEX_PROJECT_ID:-}" && -z "$API_KEY" ]] && echo "  Auth:     Vertex AI"
[[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]] \
    && echo "  GitHub:   token set" \
    || echo "  GitHub:   no token (export GH_TOKEN to enable)"
[[ -n "${GITLAB_TOKEN:-}" ]] \
    && echo "  GitLab:   token set${GITLAB_HOST:+ (${GITLAB_HOST})}" \
    || echo "  GitLab:   no token (export GITLAB_TOKEN to enable)"
echo ""

exec $CONTAINER_ENGINE run -it --rm \
    -p "${REST_PORT}" \
    "${env_args[@]}" \
    "${volume_args[@]+"${volume_args[@]}"}" \
    "${IMAGE}" \
    "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
